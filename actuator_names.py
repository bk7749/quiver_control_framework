class ActuatorNames:
	commonSetpoint = 'Common Setpoint'
	nameList = list()
	
	def __init__(self):
		self.nameList.append(commonSetpoint)

	def __contains__(self, given):
		if given in self.nameList:
			return True
		else:
			return False

