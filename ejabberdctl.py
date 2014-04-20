#!/usr/bin/env python
# -*- coding: utf-8 -*-
import io
import errno
import socket
import gevent
from httplib import BadStatusLine
from socket import gaierror
import xmlrpclib
import constants
from constants import g
import user as u

NUM_RETRIES = 3

class EjabberdCTLException(Exception):
    pass

class EjabberdCTL(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.xmlrpc_server_shared = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server_ip, constants.xmlrpc_port))
    
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
    
    def add_rosteritem(self, user, vinebot_user, group, nick, async=True):
        if async:
            gevent.spawn(self._retried_xmlrpc_command, 'add_rosteritem', {
                         'localuser': user,
                         'localserver': constants.domain,
                         'user': vinebot_user,
                         'server': constants.leaves_domain,
                         'group': group,
                         'nick': nick,
                         'subs': 'both'
                     })
        else:
            self._retried_xmlrpc_command('add_rosteritem', {
                                         'localuser': user,
                                         'localserver': constants.domain,
                                         'user': vinebot_user,
                                         'server': constants.leaves_domain,
                                         'group': group,
                                         'nick': nick,
                                         'subs': 'both'
                                     })
    
    def delete_rosteritem(self, user, vinebot_user, async=True):
        if async:
            gevent.spawn(self._retried_xmlrpc_command, 'delete_rosteritem', {
                         'localuser': user,
                         'localserver': constants.domain,
                         'user': vinebot_user,
                         'server': constants.leaves_domain
                     })
        else:
            self._retried_xmlrpc_command('delete_rosteritem', {
                                         'localuser': user,
                                         'localserver': constants.domain,
                                         'user': vinebot_user,
                                         'server': constants.leaves_domain
                                     })
    
    def get_roster(self, user):
        try:
            rosteritems = self._xmlrpc_command('get_roster', {
                'user': user, 
                'host': constants.domain
            }, assuming_text='none')
            roster = []
            for rosteritem in rosteritems['contacts']:
                rosteritem = rosteritem['contact']
                if rosteritem[2]['subscription'] != 'both':
                    g.logger.warning('Incorrect roster subscription for: %s' % rosteritem)
                vinebot_user = rosteritem[0]['jid'].split('@')[0]
                if not vinebot_user.startswith(constants.vinebot_prefix):
                    g.logger.warning("Non-vinebot user found on roster for user %s: %s" % (user, rosteritem))
                roster.append((vinebot_user, rosteritem[4]['group'], rosteritem[1]['nick']))
            return roster
        except EjabberdCTLException, e:
            return []
    
    def user_status(self, user):
        try:
            res = self._xmlrpc_command('user_sessions_info', {
                'user': user,
                'host': constants.domain
            }, assuming_text='%s is unavailable' % user)
            if len(res['sessions_info']) > 0:
                return res['sessions_info'][0]['session'][6]['status']
        except EjabberdCTLException, e:
            pass
        return 'unavailable'
    
    def connected_users(self):
        try:
            res = self._retried_xmlrpc_command('connected_users_vhost', {
                'host': constants.domain
            }, assuming_text='none')
            usernames = [r['sessions'].split('@')[0] for r in res]
            usernames = filter(lambda username: username not in constants.protected_users, usernames)
            return frozenset([u.FetchedUser(name=username) for username in usernames])
        except EjabberdCTLException, e:
            return frozenset([])
    
    def get_last(self, user):
        try:
            return self._retried_xmlrpc_command('get_last', {
                'user': user,
                'host': constants.domain
            }, assuming_text='Never')
        except EjabberdCTLException:
            return 'Never'
    
    def _retried_xmlrpc_command(self, command, data, assuming_text=None):
        xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server_ip, constants.xmlrpc_port))
        for i in range(1, NUM_RETRIES + 1):
            result = None
            try:
                result = self._xmlrpc_command(command, data, xmlrpc_server=xmlrpc_server, assuming_text=assuming_text)
            except socket.error as e:
                if e.errno in [errno.ECONNRESET, errno.ETIMEDOUT]:
                    g.logger.warning('Failed %s XMLRPC command #%d for %s and error %s' % (command, i, data, e))
                    xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server_ip, constants.xmlrpc_port))
                else:
                    raise e
            except BadStatusLine:
                g.logger.warning('Failed %s XMLRPC command #%d for %s and error BadStatusLine' % (command, i, data))
                xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server_ip, constants.xmlrpc_port))
            if result is not None and 'res' in result and result['res'] == 0:
                return True
            elif result is not None and command in result:
                return result[command]
            else:
                g.logger.warning('Failed %s XMLRPC command #%d for %s and result %s' % (command, i, data, result))
        return False
    
    def _xmlrpc_command(self, command, data, xmlrpc_server=None, assuming_text=None):
        g.logger.debug('XMLRPC ejabberdctl: %s %s' % (command, str(data)))
        if xmlrpc_server is None:
            xmlrpc_server = self.xmlrpc_server_shared
        fn = getattr(xmlrpc_server, command)
        try:
            return fn({
                'user': self.username,
                'server': constants.domain,
                'password': self.password
            }, data)  #LATER do I need to worry about injection attacks when setting topics as roster nicknames?
        except xmlrpclib.ProtocolError, e:
            g.logger.error(  'ProtocolError in %s, assuming %s: %s' % (command, assuming_text, str(e)))
        except xmlrpclib.Fault, e:
            g.logger.error(          'Fault in %s, assuming %s: %s' % (command, assuming_text, str(e)))
        except gaierror, e:    
            g.logger.error('Socket gaierror in %s, assuming %s: %s' % (command, assuming_text, str(e)))
        raise EjabberdCTLException
            
    
