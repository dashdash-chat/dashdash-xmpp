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
#TODO make 'contacts' groupname a variable?
ROSTERBOT_PASSWORD = 'nal4rey2hun5ewv4ud6p'
HOST = 'localhost' #todo make same as server URL
SERVER_URL = '127.0.0.1'
XMLRPC_SERVER_URL = 'http://%s:4560' % SERVER_URL

#should User keep track of more roster state? or is it enough to own the add/removes?
class User(object):
    def __init__(self, user, proxybot):
        self._user = user
        self._proxybot = proxybot
        self.xmlrpc_server = xmlrpclib.ServerProxy(XMLRPC_SERVER_URL)
    
    def user(self):
        return self._user
    
    def proxybot(self):
        return self._proxybot
    
    def add_to_rosters(self, participants):
        self._add_proxy_rosteritem()
        self._add_user_rosteritem(self._get_nick(participants))
        
    def delete_from_rosters(self):
        self._delete_proxy_rosteritem()
        self._delete_user_rosteritem()
    
    def _get_nick(self, participants):
        others = [participant.user() for participant in participants.difference([self._user])]
        if len(others) > 1:
            comma_sep = ''.join(['%s, ' % other for other in others[:-2]])
            return '%s%s and %s' % (comma_sep, others[-2], others[-1])
        elif len(others) == 1:
            return others[0]
        else:
            return self._proxybot
            
    def _xmlrpc_command(self, command, data):
            fn = getattr(self.xmlrpc_server, command)
            return fn({
                'user': 'rosterbot',
                'server': HOST,
                'password': ROSTERBOT_PASSWORD
            }, data)
    def _add_proxy_rosteritem(self):
        self._xmlrpc_command('add_rosteritem', { 'localserver': HOST, 'server': HOST,
            'group': 'contacts',
            'localuser': self._proxybot,
            'user': self._user,
            'nick': self._user,
            'subs': 'both'
        })
    def _delete_proxy_rosteritem(self):
        self._xmlrpc_command('delete_rosteritem', { 'localserver': HOST, 'server': HOST,
           'localuser': self._proxybot,
           'user': self._user
        })
    def _add_user_rosteritem(self, nick=None):
        self._xmlrpc_command('add_rosteritem', { 'localserver': HOST, 'server': HOST,
            'group': 'Chatidea Contacts',
            'localuser': self._user,
            'user': self._proxybot,
            'nick': nick or self._proxybot,
            'subs': 'both'
        })
    def _delete_user_rosteritem(self):
        self._xmlrpc_command('delete_rosteritem', { 'localserver': HOST, 'server': HOST,
           'localuser': self._user,
           'user': self._proxybot
        })
    def is_online(self):
        try:              
            res = self._xmlrpc_command('user_sessions_info', {
                'user': self._user,
                'host': HOST
            })
            return len(res['sessions_info']) > 0
        except xmlrpclib.ProtocolError, e:
            logging.error('ProtocolError in is_online for %s, assuming offline: %s' % (self._user, str(e)))
            return False
        
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

class Observer(User):
    pass
            
class Participant(User):
    def __init__(self, *args, **kwargs):
        super(Participant, self).__init__(*args, **kwargs)
        self._observers = set([])
        self.fetch_observers()
        #TODO fetch observers from DB
        #TODO instantiate objects
        #TODO add to set

    def observers(self):
        return self._observers

    def fetch_observers(self):
        db = None
        cursor = None
        try:
            db = MySQLdb.connect('localhost', 'userinfo-helper', 'rycs3yuf8of4vit9fac3', 'chatidea')
            cursor = db.cursor()
            cursor.execute("SELECT recipient FROM convo_starts WHERE sender = %(sender)s ORDER BY count DESC", {'sender': self.user()})
            self._observers = set([Observer(contact[0], self.proxybot()) for contact in cursor.fetchall()]) 
        except MySQLdb.Error, e:
            print "Error %d: %s" % (e.args[0], e.args[1])
            db.close()
            sys.exit(1)
        db.close()  # no need to keep the DB connection open!
