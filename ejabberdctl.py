#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import xmlrpclib
import constants

class EjabberdCTL(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
    
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
        self._xmlrpc_command('add_rosteritem', {
            'localuser': user,
            'localserver': constants.domain,
            'user': vinebot_user,
            'server': constants.leaves_domain,
            'group': '%s@%s ' % (user, constants.domain),
            'nick': nick,
            'subs': 'both'
        })
    
    def delete_rosteritem(self, user, vinebot_user):
        self._xmlrpc_command('delete_rosteritem', {
            'localuser': user,
            'localserver': constants.domain,
            'user': vinebot_user,
            'server': constants.leaves_domain,
        })
    
    def get_roster(self, user):
        rosteritems = self._xmlrpc_command('get_roster', {
            'user': user, 
            'host': constants.domain})
        roster = []
        for rosteritem in rosteritems['contacts']:
            rosteritem = rosteritem['contact']
            if rosteritem[2]['subscription'] != 'both':
                logging.warning('Incorrect roster subscription for: %s' % rosteritem)
            if rosteritem[4]['group'] != '%s@%s' % (user, constants.domain):
                logging.warning('Incorrect roster group for rosteritem: %s' % rosteritem)
            user = rosteritem[0]['jid'].split('@')[0]
            if not user.startswith(constants.vinebot_prefix):
                logging.warning("Non-vinebot user(s) found on roster for user %s!\n%s" % (user, rosteritems))
            roster.append((user, rosteritem[1]['nick'], rosteritem[4]['group']))
        return roster
    
    def user_online(self, user):
        return self.user_status(user) != 'unavailable'  # this function is useful for list filters
    
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
            logging.error('ProtocolError in user_status, assuming %s is unavailable: %s' % (user, str(e)))
            return 'unavailable'
        except xmlrpclib.Fault, e:
            logging.error('Fault in user_status, assuming %s is unavailable: %s' % (user, str(e)))
            return 'unavailable'
    
    def _xmlrpc_command(self, command, data):
        fn = getattr(self.xmlrpc_server, command)
        logging.debug('XMLRPC ejabberdctl: %s %s' % (command, str(data)))
        return fn({
            'user': self.username,
            'server': constants.domain,
            'password': self.password
        }, data)
    
