#!/usr/bin/env python
# -*- coding: utf-8 -*-
import io
import errno
import socket
import gevent
import xmlrpclib
import constants
from constants import g

NUM_RETRIES = 3

class EjabberdCTL(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.xmlrpc_server_shared = xmlrpclib.ServerProxy('http://%s:%s' % (constants.xmlrpc_server, constants.xmlrpc_port))
    
    def register(self, user, password):
        self._xmlrpc_command('register', {
            'user': user,
            'host': constants.domain,
            'password': password
        })
    
    def unregister(self, user):
        self._xmlrpc_command('unregister', {
            'user': user,
            'host': constants.domain,
        })
    
    def add_rosteritem(self, user, vinebot_user, nick):
        def wrapped_add_rosteritem(user, vinebot_user, nick):
            xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.xmlrpc_server, constants.xmlrpc_port))
            for i in range(1, NUM_RETRIES + 1):
                try:
                    result = self._xmlrpc_command('add_rosteritem', {
                        'localuser': user,
                        'localserver': constants.domain,
                        'user': vinebot_user,
                        'server': constants.leaves_domain,
                        'group': '%s@%s ' % (user, constants.domain),
                        'nick': nick,
                        'subs': 'both'
                    }, xmlrpc_server)    
                except socket.error as e:
                    if e.errno == errno.ECONNRESET:
                        g.logger.warning('Failed add_rosteritem XMLRPC request #%d for %s with %s and %s: %s' % (i, user, vinebot_user, nick, e))
                    else:
                        raise e
                if result['res'] == 0:
                    return
                else:
                    g.logger.warning('Failed add_rosteritem XMLRPC request #%d for %s with %s and %s: %s' % (i, user, vinebot_user, nick, result))
        gevent.spawn(wrapped_add_rosteritem, user, vinebot_user, nick)
        
    def delete_rosteritem(self, user, vinebot_user):
        def wrapped_delete_rosteritem(user, vinebot_user):
            xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.xmlrpc_server, constants.xmlrpc_port))
            for i in range(1, NUM_RETRIES + 1):
                try:
                    result = self._xmlrpc_command('delete_rosteritem', {
                        'localuser': user,
                        'localserver': constants.domain,
                        'user': vinebot_user,
                        'server': constants.leaves_domain
                    }, xmlrpc_server)
                except socket.error as e:
                    if e.errno == errno.ECONNRESET:
                        g.logger.warning('Failed delete_rosteritem XMLRPC request #%d for %s with %s: %s' % (i, user, vinebot_user, e))
                    else:
                        raise e
                if result['res'] == 0:
                    return
                else:
                    g.logger.warning('Failed delete_rosteritem XMLRPC request #%d for %s with %s: %s' % (i, user, vinebot_user, result))
        gevent.spawn(wrapped_delete_rosteritem, user, vinebot_user)
    
    def get_roster(self, user):    
        rosteritems = self._xmlrpc_command('get_roster', {
            'user': user, 
            'host': constants.domain})
        roster = []
        for rosteritem in rosteritems['contacts']:
            rosteritem = rosteritem['contact']
            if rosteritem[2]['subscription'] != 'both':
                g.logger.warning('Incorrect roster subscription for: %s' % rosteritem)
            if rosteritem[4]['group'] != '%s@%s ' % (user, constants.domain):
                g.logger.warning('Incorrect roster group for rosteritem: %s' % rosteritem)
            vinebot_user = rosteritem[0]['jid'].split('@')[0]
            if not vinebot_user.startswith(constants.vinebot_prefix):
                g.logger.warning("Non-vinebot user(s) found on roster for user %s!\n%s" % (user, rosteritems))
            roster.append((vinebot_user, rosteritem[1]['nick'], rosteritem[4]['group']))
        return roster
    
    def user_status(self, user):
        try:
            res = self._xmlrpc_command('user_sessions_info', {
                'user': user,
                'host': constants.domain
            })
            if len(res['sessions_info']) > 0:
                return res['sessions_info'][0]['session'][6]['status']
            else:
                return 'unavailable'
        except xmlrpclib.ProtocolError, e:
            g.logger.error('ProtocolError in user_status, assuming %s is unavailable: %s' % (user, str(e)))
            return 'unavailable'
        except xmlrpclib.Fault, e:
            g.logger.error('Fault in user_status, assuming %s is unavailable: %s' % (user, str(e)))
            return 'unavailable'
    
    def _xmlrpc_command(self, command, data, xmlrpc_server=None):        
        g.logger.debug('XMLRPC ejabberdctl: %s %s' % (command, str(data)))
        if xmlrpc_server is None:
            xmlrpc_server = self.xmlrpc_server_shared
        fn = getattr(xmlrpc_server, command)
        return fn({
            'user': self.username,
            'server': constants.domain,
            'password': self.password
        }, data)
    
