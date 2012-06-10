#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
import logging
import xmlrpclib
import constants
from constants import Stage

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


#IDEA should User keep track of more roster state? or is it enough to own the add/removes?
class User(object):
    def __init__(self, user, proxybot_jid):
        self._user = user
        self._proxybot_jid = proxybot_jid
        self.current_nick = None
        self.current_group = None
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))

    def user(self):
        return self._user
    
    def proxybot_jid(self):
        return self._proxybot_jid
    
    def add_to_rosters(self, nick, stage):
        self._add_proxy_rosteritem()
        if stage is Stage.IDLE:
            self._add_user_rosteritem(nick, constants.idle_group)
        elif stage is Stage.ACTIVE:
            self._add_user_rosteritem(nick, constants.active_group)
        
    def delete_from_rosters(self):
        self._delete_proxy_rosteritem()
        self._delete_user_rosteritem()

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
            'localuser': self._proxybot_jid,
            'user': self._user,
            'nick': self._user,
            'subs': 'both'
        })
    def _delete_proxy_rosteritem(self):
        self._xmlrpc_command('delete_rosteritem', { 'localserver': constants.server, 'server': constants.server,
           'localuser': self._proxybot_jid,
           'user': self._user
        })
    def _add_user_rosteritem(self, nick, group):
        self.current_nick = nick
        self.current_group = group
        self._xmlrpc_command('add_rosteritem', { 'localserver': constants.server, 'server': constants.server,
            'group': group,
            'localuser': self._user,
            'user': self._proxybot_jid,
            'nick': nick,
            'subs': 'both'
        })
    def _delete_user_rosteritem(self):
        self._xmlrpc_command('delete_rosteritem', { 'localserver': constants.server, 'server': constants.server,
           'localuser': self._user,
           'user': self._proxybot_jid
        })
    def is_online(self):
        try:              
            res = self._xmlrpc_command('user_sessions_info', {
                'user': self._user,
                'host': constants.server
            })
            return len(res['sessions_info']) > 0
        except xmlrpclib.ProtocolError, e:
            logging.error('ProtocolError in is_online, assuming %s is offline: %s' % (self._user, str(e)))
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
    pass
            
class Participant(User):
    def __init__(self, *args, **kwargs):
        super(Participant, self).__init__(*args, **kwargs)
        self._observers = set([])
        self.fetch_observers()

    def observers(self):
        return self._observers

    def fetch_observers(self):
        db = None
        cursor = None
        try:
            db = MySQLdb.connect('localhost', constants.userinfo_mysql_user, constants.userinfo_mysql_password, constants.db_name)
            cursor = db.cursor()
            cursor.execute("""SELECT proxybot_participants_2.user FROM proxybots, 
                proxybot_participants AS proxybot_participants_1, proxybot_participants AS proxybot_participants_2 WHERE 
                proxybots.stage = 'idle' AND
                proxybots.id = proxybot_participants_1.proxybot_id AND
                proxybots.id = proxybot_participants_2.proxybot_id AND
                proxybot_participants_1.user = %(user)s""", {'user': self.user()})
            self._observers = set([Observer(contact[0], self.proxybot_jid()) for contact in cursor.fetchall()]) 
            db.close()  # no need to keep the DB connection open!
        except MySQLdb.Error, e:
            logging.error("MySQLdb %d: %s" % (e.args[0], e.args[1])
            if db:
                db.close()
            sys.exit(1)
    
    def add_observer(self, user, proxybot_jid, nick):
        observer = Observer(user, proxybot_jid)
        observer.add_to_rosters(nick, Stage.ACTIVE)
        self._observers.add(observer)
    
    def remove_observer(self, user, proxybot_jid):
        observer = Observer(user, proxybot_jid)  # we only need this Observer object so we can make the appropriate xmlrpc calls, it isn't saved
        observer.delete_from_rosters()
        self._observers.remove(user)
