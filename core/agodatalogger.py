#!/usr/bin/env python
#
# datalogger - logs data to sqlite db and generates graph data for the AMQP based automation control
#
# Copyright (c) 2012 Christoph Jaeger office@diakonesis.at>
#
# create sqlite table:
# CREATE TABLE data(id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT, environment TEXT, unit TEXT, level REAL, timestamp TIMESTAMP);


import sys
import syslog
import ConfigParser, os

from qpid.messaging import *
from qpid.util import URL
from qpid.log import enable, DEBUG, WARN

from pysqlite2 import dbapi2 as sqlite3
import sqlite3 as lite
import datetime

import pandas
import pandas.io.sql as psql
import simplejson

config = ConfigParser.ConfigParser()
config.read('/etc/opt/agocontrol/config.ini')

try:
	username = config.get("system","username")
except ConfigParser.NoOptionError, e:
	username = "agocontrol"

try:
	password = config.get("system","password")
except ConfigParser.NoOptionError, e:
	password = "letmein"

try:
	broker = config.get("system","broker")
except ConfigParser.NoOptionError, e:
	broker = "localhost"

try:
	debug = config.get("system","debug")
except ConfigParser.NoOptionError, e:
	debug = "WARN"

if debug=="DEBUG":
	enable("qpid", DEBUG)
else:
	enable("qpid", WARN)

# route stderr to syslog
class LogErr:
	def write(self, data):
		syslog.syslog(syslog.LOG_ERR, data)

syslog.openlog(sys.argv[0], syslog.LOG_PID, syslog.LOG_DAEMON)
sys.stderr = LogErr()

# get sqlite connection
con = lite.connect('agodatalogger.db')


#def GetGraphData(uuid, start, end):
def GetGraphData():
	#uuid = uuid
	#start_date = start
	#end_date = end

	uuid="5ee20e88-8dd7-451f-a2c7-00ead37f2216"
	start_date="2012-11-13 11:00:00"
	end_date="2012-11-13 11:15:00"
	environment="temperature"

	try:
		df = psql.read_frame("""SELECT strftime('%s', timestamp) AS Date,
		environment AS Env,
		unit AS Unit,
		AVG(level) AS Level
		FROM data
		WHERE timestamp BETWEEN '""" + start_date + """' AND '""" + end_date + """' 
		AND environment='""" + environment + """'
		AND uuid='""" + uuid + """' GROUP BY strftime('%s', timestamp), Unit
		ORDER BY timestamp""", con, index_col = 'Date')

		if not df.empty:
			df.index = [pandas.datetools.to_datetime(datetime.datetime.fromtimestamp(int(di)).strftime('%Y-%m-%d %H:%M:%S')) for di in df.index]

			ticks = df.ix[:, ['Level']]

			ticks = ticks.asfreq('1Min', method='pad').prod(axis=1).resample('5min', how='mean')

			start_date = datetime.datetime(2012, 11, 13, 11, 00, 0, 0)
			end_date = datetime.datetime(2012, 11, 13, 14, 30, 00, 0)
			date_range = pandas.DatetimeIndex(start=start_date, end=end_date, freq='5Min')

      			df2 = ticks.reindex(date_range).fillna(method='backfill').fillna(method='pad')
			data = map(lambda x: x.strip(), str(df2).splitlines(True))
			json_map = {}
			for i in range(len(data) - 1):
				json_map[data[i][:19]] = data[i][23:]
			return simplejson.dumps(json_map)
		else:
			return "No data"

	except sqlite3.Error as e:
		print  "Error " + e.args[0]

###



connection = Connection(broker, username=username, password=password, reconnect=True)
try:
	connection.open()
	session = connection.session()
	receiver = session.receiver("agocontrol; {create: always, node: {type: topic}}")
	receiver.capacity=100
	#sender = session.sender("agocontrol; {create: always, node: {type: topic}}")
	while True:
		try:
			message = receiver.fetch(timeout=1)
			if 'level' in message.content:
                		uuid = message.content["uuid"]
				environment =  message.subject.replace('environment.','').replace('changed','').replace('event.','')
				if 'unit' in message.content:
                			unit =  message.content["unit"]
				else:
					unit = ""
                		level =  message.content["level"]
				try:
                			with con:
                    				cur = con.cursor()
                    				cur.execute("INSERT INTO data VALUES(null,?,?,?,?,?)", (uuid,environment,unit,level,datetime.datetime.now()))
                    				newId = cur.lastrowid
                    				print "Info: New record ID %s with values uuid: %s, environment: %s, unit: %s, level: %s" % (newId,uuid,environment,unit,level)
				except sqlite3.Error as e:
					print  "Error " + e.args[0]

			if 'command' in message.content:
				if message.content['command'] == 'getloggergraph':
					result = GetGraphData()
					print result

			session.acknowledge()

		except Empty:
			pass

except SendError, e:
	print e
except ReceiverError, e:
	print e
except KeyboardInterrupt:
	pass
finally:
	connection.close()
