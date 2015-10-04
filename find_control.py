import basic
from actuator_names import ActuatorNames
from sensor_names import SensorNames
from bd_wrapper import BDWrapper
from analyzer import Analyzer
import plotter

import pickle
import pandas as pd
import plotter
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from datetime import datetime, timedelta
from math import sqrt
from sklearn.metrics import mean_squared_error
from sklearn.svm import SVR, LinearSVR
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB, MultinomialNB
from copy import deepcopy
import scipy.fftpack as fftpack
from statsmodels.nonparametric.smoothers_lowess import lowess




class FindControl:
	zonelist = None
	testlist = None
	actuNames = None
	sensorNames = None
	bdm = None
	anal = None

	def __init__ (self):
		self.zonelist = basic.csv2list('metadata/partialzonelist.csv')
		self.testlist = ['RM-4132', 'RM-2150', 'RM-2108']
		self.actuNames = ActuatorNames()
		self.sensorNames = SensorNames()
		self.bdm = BDWrapper()
		self.anal = Analyzer()
	
	def make_dataframe(self, filename):
		data = dict()
		with open(filename, 'rb') as fp:
			dataDict = pickle.load(fp)
			for zone in self.testlist:
				data[zone] = pd.DataFrame.from_dict(dataDict[zone])
		return data

	def make_most_influence_dict(self, df):
		sensorList = np.array(df.keys())
		corrMat = df.corr()

		for sensor in sensorList:
			corrMat[sensor][sensor] = 0
		corrMat = abs(corrMat)

		for sensor in sensorList:
			print sensor

			maxIndices = np.where(corrMat[sensor]>0.5)[0] #This threashold should be defined later
			print corrMat
			if len(maxIndices)==0:
				continue
#			plotData = df[sensorList[maxIndices]]
			plotData = list()
			plotLabel = list()
			for idx in maxIndices:
				plotData.append(df[sensorList[idx]])
				plotLabel.append(sensorList[idx])

			plotter.plot_multiple_2dline(range(0,len(df[sensorList[maxIndices[0]]])), plotData, dataLabels=plotLabel)

# Input: data1(series), data2(series), Output: arranged data2 (list)
	def data_allign(self, data1, data2, direction):
		output = list()
		test = list()
		for tp in data1.index:
			if direction=='right':
				newData = data2[data2.index>tp].head(1)
			elif direction=='left':
				newData = data2[data2.index<=tp].tail(1)
			else:
				print "direction value is wrong"
				return None 

			if newData.empty:
				if direction=='right':
					newData = data2[data2.index<=tp].tail(1)
				elif direction=='left':
					newData = data2[data2.index>=tp].head(1)
				#TODO: Won't it make an error? Will there be a datum always?
			print data1[tp], newData
			test.append(newData)
			output.append(float(newData))
		return output


	def download_control_data(self):
		reqList = list()
		reqList.append(('RM-4132', datetime(2015,9,29,12,01), datetime(2015,9,30,2,59)))
		reqList.append(('RM-2108', datetime(2015,9,29,12,01), datetime(2015,9,30,2,59)))
		acsDF = pd.DataFrame({'acs':[],'cs':[],'oc':[]})
		for req in reqList:
			zoneDict = dict()
			for sensorType in self.actuNames.nameList+self.sensorNames.nameList:
				uuid = self.bdm.get_sensor_uuids({'room':req[0], 'template':sensorType})[0]
				rawData = self.bdm.get_sensor_ts(uuid, 'PresentValue', req[1], req[2])
				zoneDict[sensorType] = rawData
			
			# Actual Cooling Setpoint Data Allignment
			acsSeries = zoneDict[self.actuNames.actualCoolingSetpoint]
			csSeries = zoneDict[self.actuNames.commonSetpoint]
			ocSeries = zoneDict[self.actuNames.occupiedCommand]

			csList = csSeries.tolist()
			acsList = self.data_allign(csSeries, acsSeries, 'right')
			ocList = self.data_allign(csSeries, ocSeries, 'left')
			if not (len(csList)==len(acsList) and len(csList)==len(ocList)):
				print "allignment is wrong"
				return None
			newDF = pd.DataFrame({'acs':acsList, 'cs':csList, 'oc':ocList})
			acsDF = pd.concat([acsDF, newDF])
			
			ocList = ocSeries.tolist()
			csList = self.data_allign(ocSeries, csSeries, 'left')
			acsList = self.data_allign(ocSeries, acsSeries, 'right')
			newDF = pd.DataFrame({'acs':acsList, 'cs':csList, 'oc':ocList})
			acsDF = pd.concat([acsDF, newDF])



	def merge_data(self, data1, dataList):
		dataDict = dict()
		for key in data1.iterkeys():
#			data1[key] = pd.concat([df1, dataList[key]])
			for data in dataList:
				dataDict[key] = pd.concat([data1[key],data[key]])
		return dataDict

	def lpf(self, data):
		filtered = deepcopy(data)
		lpfLen = 20
		for i in range(0,lpfLen):
			filtered = filtered + self.shift_fill(data,i)
			filtered = filtered + self.shift_fill(data,-i)
		filtered = filtered / (lpfLen*2+1)
		return filtered


	def shift_fill(self, data, period=1):
		if period>=0:
			return data.shift(period).fillna(method='bfill')
		else:
			return data.shift(period).fillna(method='ffill')
	def calc_i(self, data, period):
		calced = self.shift_fill(data,1)
		for i in range(2,period+1):
			calced = calced + self.shift_fill(data,i)
		return calced

	def arrange_data(self, zoneData):
		oc = zoneData[self.actuNames.occupiedCommand]
		cs = zoneData[self.actuNames.commonSetpoint]
		acs = self.lpf(zoneData[self.actuNames.actualCoolingSetpoint])
		ahs = zoneData[self.actuNames.actualHeatingSetpoint]
		zt = self.lpf(zoneData[self.sensorNames.zoneTemperature])
		try:
			tempocc = zoneData[self.actuNames.tempOccSts]
			newoc = np.logical_or((oc-1)/2, tempocc)
		except:
			pass
		wcad = zoneData[self.actuNames.warmCoolAdjust]
		cc = self.lpf(zoneData[self.actuNames.coolingCommand])
		hc = zoneData[self.actuNames.heatingCommand]
		cmf = zoneData[self.actuNames.coolingMaxFlow]
		ocm = zoneData[self.actuNames.occupiedCoolingMinimumFlow]
		const = pd.Series(data=np.ones(len(oc)), index=oc.index)
		zt_lag1 = self.shift_fill(zt,3)
		zt_lag2 = self.shift_fill(zt,6)
		zt_lag3 = self.shift_fill(zt,9)
		zt_lag4 = self.shift_fill(zt,12)
		zt_lag5 = self.shift_fill(zt,15)
		acs_i = self.calc_i(acs, 10)
		zt_i = self.calc_i(zt, 10)
		acs_lag1 = self.shift_fill(acs,3)
		acs_lag2 = self.shift_fill(acs,6)
		acs_lag3 = self.shift_fill(acs,9)
		acs_lag4 = self.shift_fill(acs,12)
		acs_lag5 = self.shift_fill(acs,15)
		cc_lag1 = self.shift_fill(cc,3)
		cc_lag2 = self.shift_fill(cc,6)
		cc_lag3 = self.shift_fill(cc,9)
		mincc = deepcopy(cc)
		mincc[:]=0
		maxcc = deepcopy(cc)
		maxcc[:]=100
		newcs = cs + wcad
		acs_diff = acs - zt
		acs_diff_diff = acs_diff.diff().fillna(method='bfill')
		acs_diff_lag1 = self.shift_fill(acs_diff,1)
		acs_diff_lag2 = self.shift_fill(acs_diff,2)
		acs_diff_lag3 = self.shift_fill(acs_diff,3)
		acs_diff_lag4 = self.shift_fill(acs_diff,4)
		acs_diff_lag5 = self.shift_fill(acs_diff,5)
		acs_diff_lag6 = self.shift_fill(acs_diff,6)

		#acsDF = pd.DataFrame({'acs':acs, 'cs':cs, 'oc':oc, 'tempocc':tempocc, 'wcad':wcad})
		#acsDF = pd.DataFrame({'acs':acs, 'cs':newcs, 'oc':newoc})
		#ahsDF = pd.DataFrame({'ahs':ahs, 'cs':cs, 'oc':oc, 'tempocc':tempocc, 'wcad':wcad})
		#ahsDF = pd.DataFrame({'ahs':ahs, 'cs':newcs, 'oc':newoc})



		#ccDF = pd.DataFrame({'cc':cc, 'zt':zt, 'acs':acs, 'zt_lag1':zt_lag1, 'zt_lag2':zt_lag2, 'zt_lag3':zt_lag3,'acs_lag1':acs_lag1,'acs_lag2':acs_lag2, 'acs_lag3':acs_lag3, 'maxcc':maxcc, 'mincc':mincc, 'acsdiff':acs_diff, 'zt_lag4':zt_lag4, 'zt_lag5':zt_lag5, 'acs_lag4':acs_lag4, 'acs_lag5':acs_lag5})
		#ccDF = pd.DataFrame({'cc':cc, 'zt':zt, 'acs':acs, 'acs_diff':acs_diff, 'acs_diff_diff':acs_diff_diff, 'acs_diff_lag1':acs_diff_lag1, 'acs_diff_lag2':acs_diff_lag2, 'acs_diff_lag3':acs_diff_lag3, 'acs_diff_lag4':acs_diff_lag4, 'acs_diff_lag5':acs_diff_lag5, 'acs_i':acs_i, 'zt_i':zt_i, })
		#hcDF = pd.DataFrame({'hc':zoneData[self.actuNames.heatingCommand], 'zt':zoneData[self.sensorNames.zoneTemperature], 'ahs':zoneData[self.actuNames.actualHeatingSetpoint]})
		#asfspDF = pd.DataFrame({'asfsp':zoneData[self.actuNames.actualSupplyFlowSP], 'cc':zoneData[self.actuNames.coolingCommand], 'hc':zoneData[self.actuNames.heatingCommand], 'ocm':zoneData[self.actuNames.occupiedCoolingMinimumFlow], 'oc':oc, 'cmf':cmf})
		asfspDF = pd.DataFrame({'asfsp':zoneData[self.actuNames.actualSupplyFlowSP], 'cc':zoneData[self.actuNames.coolingCommand], 'const':const, 'oc':oc, 'cmf':cmf, 'ocm':ocm, 'tempocc':tempocc})
		#dcDF = pd.DataFrame({'dc':zoneData[self.actuNames.damperCommand], 'asf':zoneData[self.sensorNames.actualSupplyFlow], 'asfsp':zoneData[self.actuNames.actualSupplyFlowSP]})
		output = dict()
		#output['acs'] = acsDF
		#output['ahs'] = ahsDF
		#output['cc'] = ccDF
		#output['hc'] = hcDF
		output['asfsp'] = asfspDF
		#output['dc'] = dcDF
		return output

	def organize_data(self):
		#rawDataDict = self.anal.receive_entire_sensors_notstore(datetime(2015,9,29),datetime(2015,9,30,6))
		filenameList = list()
		testfilenameList = list()
		testfilenameList.append('data\oneweek_4152_0714.pkl')
#		testfilenameList.append('data\oneday_2148_0820.pkl')
		filenameList.append('data\oneweek_2150_0920.pkl')
		#filenameList.append('data\oneweek_2148_0714.pkl')
		#filenameList.append('data\onemonth_2150_0820.pkl')

		dataList = list()
#		for idx, filename in enumerate(filenameList):
#			with open(filename, 'rb') as fp:
#				data = pickle.load(fp)
#			if idx==0:
#				dataList.append(self.arrange_data(data['RM-4132']))
#			else:
#				dataList.append(self.arrange_data(data['RM-2108']))

		#for zone in self.testlist:
		#	dataList.append(self.arrange_data(rawDataDict[zone]))
		for idx, filename in enumerate(filenameList):
			with open(filename,'rb') as fp:
				rawDataDict = pickle.load(fp)
				dataList.append(self.arrange_data(rawDataDict))
		
		testDataList = list()
		for idx, filename in enumerate(testfilenameList):
			with open(filename,'rb') as fp:
				rawDataDict = pickle.load(fp)
				testDataList.append(self.arrange_data(rawDataDict))

		if len(testDataList)==1:
			testDataDict = testDataList[0]
		else:
			testDataDict=  self.merge_data(testDataList[0], testDataList[:-1])

#		dataList.append(self.arrange_data(rawDataDict))

		if len(dataList)==1:
			dataDict = dataList[0]
		else:
			dataDict = self.merge_data(dataList[0], dataList[:-1])

		for key, data in dataDict.iteritems():
			print key
			print "SVR"
			#self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=SVR(kernel='rbf', verbose=False), filename='figs/rbfSVM.pdf')
			#self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=SVR(kernel='linear', verbose=True),filename='figs/linearSVM.pdf')
			self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=LinearSVR(verbose=True),filename='figs/linearSVM.pdf')
#			self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=SVR(kernel='polynomial', verbose=True), filename='figs/polySVM.pdf')
			#self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=SVR(kernel='sigmoid', verbose=True), filename='figs/sigmoidSVM.pdf')
			print "Logistic"
			#self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=LogisticRegression(solver='newton-cg'), filename='figs/newtonLogistic.pdf')
			#self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=LogisticRegression(solver='lbfgs'), filename='figs/lbfgsLogistic.pdf')
			#self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=LogisticRegression(solver='liblinear'), filename='figs/liblinLogistic.pdf')
			print "Gaussian Naive Bayes"
			self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=GaussianNB())
			#self.fit_data(data[key], data.drop(key,axis=1), testDataDict[key][key], testDataDict[key].drop(key,axis=1), model=MultinomialNB())
	
	def fit_data(self, y, xs, testy, testxs, model=SVR(kernel='rbf'),filename='figs/test.pdf'):
		#svr_rbf = SVR(kernel='rbf', C=1e3, gamma=0.1)
		#svr_rbf = SVR()
		fitted = model.fit(xs,y)
		y_rbf = fitted.predict(xs)
		#ax1 = fig.add_subplot(2,2,1,projection='3d')
		#ax1.scatter(xs[xs.keys()[0]],xs[xs.keys()[1]],y,c='k')
		
		#ax2 = fig.add_subplot(2,2,2,projection='3d')
		#ax2.scatter(xs[xs.keys()[0]],xs[xs.keys()[1]],y_rbf,c='k')

		testy_rbf = fitted.predict(testxs)
		#ax3 = fig.add_subplot(2,2,3,projection='3d')
		#ax3.scatter(testxs[testxs.keys()[0]],testxs[testxs.keys()[1]],testy,c='k')

		#ax4 = fig.add_subplot(2,2,4,projection='3d')
		#ax4.scatter(testxs[testxs.keys()[0]],testxs[testxs.keys()[1]],testy_rbf,c='k')
		rmse = sqrt(mean_squared_error(testy, testy_rbf))
		normRmse = rmse/np.mean(testy)

		fig = plt.figure()
		ax1 = fig.add_subplot(121)
		ax1.plot(y,c='b')
		ax1.plot(xs[xs.keys()[0]], c='r')
		ax2 = fig.add_subplot(122)
		ax2.plot(y, c='b')
		ax2.plot(xs[xs.keys()[1]], c='r')
		#plt.show()


		fig = plt.figure()
		ax1 = fig.add_subplot(121)
		plotList = list()
		plotList.append(ax1.plot_date(y.index, y, c='b', label='original', marker='None', linestyle='-'))
		plotList.append(ax1.plot_date(y.index, y_rbf, c='r', label='fitted', marker='None', linestyle='-'))
		ax1.set_title('Learning Data')
		ax1.legend()
		plotList = list()
		ax2 = fig.add_subplot(122)
		plotList.append(ax2.plot_date(testy.index, testy, c='b', label='original', marker='None', linestyle='-'))
		plotList.append(ax2.plot_date(testy.index, testy_rbf, c='r', label='fitted', marker='None', linestyle='-'))
		ax2.set_title('Test Data')
		ax2.legend()
		plotter.save_fig(fig, filename)
		plt.show()

		
		print rmse, normRmse
		print '\n'


		
		pass
