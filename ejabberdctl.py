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
    
    def add_rosteritem(self, user, vinebot_user, group, nick):
        gevent.spawn(self._retried_xmlrpc_command, 'add_rosteritem', {
                        'localuser': user,
                        'localserver': constants.domain,
                        'user': vinebot_user,
                        'server': constants.leaves_domain,
                        'group': group,
                        'nick': nick,
                        'subs': 'both'
                    })
    
    def delete_rosteritem(self, user, vinebot_user):
        gevent.spawn(self._retried_xmlrpc_command, 'delete_rosteritem', {
                        'localuser': user,
                        'localserver': constants.domain,
                        'user': vinebot_user,
                        'server': constants.leaves_domain
                    })
    
    def get_roster(self, user):    
        rosteritems = self._xmlrpc_command('get_roster', {
            'user': user, 
            'host': constants.domain})
        roster = []
        for rosteritem in rosteritems['contacts']:
            rosteritem = rosteritem['contact']
            if rosteritem[2]['subscription'] != 'both':
                g.logger.warning('Incorrect roster subscription for: %s' % rosteritem)
            vinebot_user = rosteritem[0]['jid'].split('@')[0]
            if not vinebot_user.startswith(constants.vinebot_prefix):
                g.logger.warning("Non-vinebot user(s) found on roster for user %s!\n%s" % (user, rosteritems))
            roster.append((vinebot_user, rosteritem[4]['group'], rosteritem[1]['nick']))
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
    
    def _retried_xmlrpc_command(self, command, data):
        xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.xmlrpc_server, constants.xmlrpc_port))
        for i in range(1, NUM_RETRIES + 1):
            result = None
            try:
                result = self._xmlrpc_command(command, data, xmlrpc_server)
            except socket.error as e:
                if e.errno in [errno.ECONNRESET, errno.ETIMEDOUT]:
                    g.logger.warning('Failed %s XMLRPC command #%d for %s with %s and error %s' % (command, i, data['localuser'], data['user'], e))
                    xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.xmlrpc_server, constants.xmlrpc_port))
                else:
                    raise e
            if result is not None and 'res' in result and result['res'] == 0:
                return True
            else:
                g.logger.warning('Failed %s XMLRPC command #%d for %s with %s and result %s' % (command, i, data['localuser'], data['user'], result))
        return False
    
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
    
