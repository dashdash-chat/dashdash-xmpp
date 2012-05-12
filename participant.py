#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
import xmlrpclib

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

#TODO read these from config file?
USERINFOBOT_PASSWORD = 'nal4rey2hun5ewv4ud6p'
HOST = 'localhost' #todo make same as server URL
SERVER_URL = '127.0.0.1'
XMLRPC_SERVER_URL = 'http://%s:4560' % SERVER_URL

class User(object):
    def __init__(self, user):
        self._user = user
        self.xmlrpc_server = xmlrpclib.ServerProxy(XMLRPC_SERVER_URL)
    
    def user(self):
        return self._user
    
    def _xmlrpc_command(self, command, data):
            fn = getattr(self.xmlrpc_server, command)
            return fn({
                'user': 'userinfo',
                'server': HOST,
                'password': USERINFOBOT_PASSWORD
            }, data)
    
    def is_online(self):
        res = self._xmlrpc_command('user_sessions_info', {
            'user': self.user(),
            'host': HOST
        })
        return len(res['sessions_info']) > 0
        
    def __eq__(self, other):
        if isinstance(other, str) or isinstance(other, unicode):
            return other == self.user()
        else:
            #TODO fix this so that it properly calls parent function, AttributeError: 'super' object has no attribute '__eq__'
            return super(User, self).__eq__(*args, **kwargs)
    
    def __ne__(self, other):
        if isinstance(other, str) or isinstance(other, unicode):
            return other != self.user()
        else:
            #TODO fix this so that it properly calls parent function, AttributeError: 'super' object has no attribute '__eq__'
            return super(User, self).__ne__(*args, **kwargs)
    
    def __hash__(self):
        return hash(self.user())
    
class Participant(User):
    def __init__(self, *args, **kwargs):
        super(Participant, self).__init__(*args, **kwargs)
        self._guests = set([])
        self.fetch_guests()
        #TODO fetch guests from DB
        #TODO instantiate objects
        #TODO add to set

    def guests(self):
        return self._guests

    def fetch_guests(self):
        db = None
        cursor = None
        try:
            db = MySQLdb.connect('localhost', 'userinfo-helper', 'rycs3yuf8of4vit9fac3', 'chatidea')
            cursor = db.cursor()
            cursor.execute("SELECT recipient FROM convo_starts WHERE sender = %(sender)s ORDER BY count DESC", {'sender': self.user()})
            self._guests = set([contact[0] for contact in cursor.fetchall()]) 
        except MySQLdb.Error, e:
            print "Error %d: %s" % (e.args[0], e.args[1])
            db.close()
            sys.exit(1)
        db.close()  # no need to keep the DB connection open!
