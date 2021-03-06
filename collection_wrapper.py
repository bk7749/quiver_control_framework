import pymongo
import threading
import pandas as pd
from datetime import datetime



class DefaultRow(object):
	content = None
	def __init__ (self, uuid, name):
		self.content = dict()
		self.content['uuid'] = uuid
		self.content['name'] = name

class ExpLogRow(DefaultRow):
	def __init__ (self, uuid, name, setTime=None, setVal=None, origVal=None):
		super(ExpLogRow, self).__init__(uuid, name)
		self.content['set_time'] = setTime
		self.content['set_value'] = setVal
		self.content['original_value'] = origVal
	def get_dict(self):
		return self.content

class StatusRow(DefaultRow):
	def __init__ (self, uuid, name, setTime=None, setVal=None, resetVal=None, actuType=None, underControl=None):
		super(StatusRow, self).__init__(uuid, name)
		self.content['set_time'] = setTime
		self.content['set_value'] = setVal
		self.content['reset_value'] = resetVal
		self.content['actuator_type'] = actuType
		self.content['under_control'] = underControl
	def get_dict(self):
		return self.content

class SetRow(DefaultRow):
	def __init__ (self, uuid, name, setTime=None, resetTime=None, setVal=None):
		super(SetRow, self).__init__(uuid, name)
		self.content['set_time'] = setTime
		self.content['set_value'] = setVal
		self.content['reset_value'] = resetVal
		self.content['original_value'] = origVal
	def get_dict(self):
		return self.content

class CollectionWrapper:
	
	lock = None
	dbName = None
	collectionName = None
	collection = None
	def __init__(self, collName):
		self.lock = threading.Lock()
		self.dbName = 'quiverdb'
		self.collectionName = collName
		client = pymongo.MongoClient()
		db = client[self.dbName]
		self.collection = db[collName]

# data(DataFrame) -> X
	def store_dataframe(self, data):
		self.lock.acquire()
		dataDict = data.to_dict('records')
		self.collection.insert_many(dataDict)
#		self.collection.create_index([('timestamp',pymongo.ASCENDING),('zone',pymongo.ASCENDING)])
		self.lock.release()
	
	def store_row(self,row):
		if isinstance(row, DefaultRow):
			self.lock.acquire()
			dataDict = row.get_dict()
			self.collection.insert_one(dataDict)
			self.lock.release()
			return True
		else:
			print 'Input row does not follow DefaultRow\'s format'
			return False
	def update_row(self, row):
		rowID =pd.DataFrame(list(self.collection.find({'uuid':row['uuid']})))['_id'][0]
		result = self.collection.update_one({'_id':rowID}, {'$set':row}, upsert=False)
		print result.matched_count, " are changed"
	
	def load_dataframe(self, query):
		self.lock.acquire()
		df = pd.DataFrame(list(self.collection.find(query)))
		self.lock.release()
		return df

	def pop_dataframe(self,query):
		self.lock.acquire()
		df = pd.DataFrame(list(self.collection.find(query)))
		self.collection.remove(query)
		self.lock.release()
		return df

	def remove_dataframe(self,query):
		self.lock.acquire()
		self.collection.remove(query)
		self.lock.release()

	def remove_all(self):
		self.lock.acquire()
		self.collection.remove()
		self.lock.release()
	
	def get_size(self):
		return self.collection.find({}).count()
	
	def to_csv(self):
		output = self.load_dataframe({})
		output.to_csv('data/'+self.collectionName+'_log_'+datetime.now().isoformat().replace(':','_',10)+'.csv')

