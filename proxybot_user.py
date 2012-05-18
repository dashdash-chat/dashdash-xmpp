#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
import logging
import xmlrpclib
import constants

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


#IDEA should User keep track of more roster state? or is it enough to own the add/removes?
class User(object):
    def __init__(self, user, proxybot):
        self._user = user
        self._proxybot = proxybot
        self.current_nick = None
        self.current_group = None
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
    
    def user(self):
        return self._user
    
    def proxybot(self):
        return self._proxybot
    
    def add_to_rosters(self, nick, group):
        self._add_proxy_rosteritem()
        self._add_user_rosteritem(nick, group)
        
    def delete_from_rosters(self):
        self._delete_proxy_rosteritem()
        self._delete_user_rosteritem()
        
    def update_roster(self, nick):
        if nick != self.current_nick or constants.active_group != self.current_group:  # only update if there's a change
            self._add_user_rosteritem(nick, constants.active_group)  # roster items only change for active proxybots

    def _xmlrpc_command(self, command, data):
            fn = getattr(self.xmlrpc_server, command)
            return fn({
                'user': constants.rosterbot_xmlrpc_jid,
                'server': constants.server,
                'password': constants.rosterbot_xmlrpc_password
            }, data)
    def _add_proxy_rosteritem(self):
        self._xmlrpc_command('add_rosteritem', { 'localserver': constants.server, 'server': constants.server,
            'group': constants.proxybot_group,
            'localuser': self._proxybot,
            'user': self._user,
            'nick': self._user,
            'subs': 'both'
        })
    def _delete_proxy_rosteritem(self):
        self._xmlrpc_command('delete_rosteritem', { 'localserver': constants.server, 'server': constants.server,
           'localuser': self._proxybot,
           'user': self._user
        })
    def _add_user_rosteritem(self, nick, group):
        self.current_nick = nick
        self.current_group = group
        self._xmlrpc_command('add_rosteritem', { 'localserver': constants.server, 'server': constants.server,
            'group': group,
            'localuser': self._user,
            'user': self._proxybot,
            'nick': nick,
            'subs': 'both'
        })
    def _delete_user_rosteritem(self):
        self._xmlrpc_command('delete_rosteritem', { 'localserver': constants.server, 'server': constants.server,
           'localuser': self._user,
           'user': self._proxybot
        })
    def is_online(self):
        try:              
            res = self._xmlrpc_command('user_sessions_info', {
                'user': self._user,
                'host': constants.server
            })
            return len(res['sessions_info']) > 0
        except xmlrpclib.ProtocolError, e:
            logging.error('ProtocolError in is_online for %s, assuming offline: %s' % (self._user, str(e)))
            return False
        
    def __str__(self):
        return self.user()
    def __eq__(self, other):
        if isinstance(other, str) or isinstance(other, unicode):
            return other == self.user()
        elif isinstance(other, User):
            return other.user() == self.user()
        else:
            return NotImplemented
    def __ne__(self, other):
        return not self.__eq__(other)
    def __hash__(self):
        return hash(self.user())

class Observer(User):
    def add_to_rosters(self, nick):
        super(Observer, self).add_to_rosters(nick, constants.active_group)
            
class Participant(User):
    def __init__(self, *args, **kwargs):
        super(Participant, self).__init__(*args, **kwargs)
        self._observers = set([])
        self.fetch_observers()
        #TODO fetch observers from DB
        #TODO instantiate objects
        #TODO add to set
    
    def add_to_rosters(self, nick):
        super(Participant, self).add_to_rosters(nick, constants.idle_group)

    def observers(self):
        return self._observers

    def fetch_observers(self):
        db = None
        cursor = None
        try:
            db = MySQLdb.connect(constants.server, constants.userinfo_mysql_user, constants.userinfo_mysql_password, constants.db_name)
            cursor = db.cursor()
            cursor.execute("SELECT recipient FROM convo_starts WHERE sender = %(sender)s ORDER BY count DESC", {'sender': self.user()})
            self._observers = set([Observer(contact[0], self.proxybot()) for contact in cursor.fetchall()]) 
            db.close()  # no need to keep the DB connection open!
        except MySQLdb.Error, e:
            print "Error %d: %s" % (e.args[0], e.args[1])
            db.close()
            sys.exit(1)
        
