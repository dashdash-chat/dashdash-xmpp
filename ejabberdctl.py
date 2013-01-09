#!/usr/bin/env python
# -*- coding: utf-8 -*-
import io
import xmlrpclib
import constants
from constants import g

class FireAndForget(xmlrpclib.Transport):
    mock_xml_response = u'<?xml version="1.0"?><methodResponse><params><param><value><struct><member><name>res</name><value><int>0</int></value></member></struct></value></param></params></methodResponse>'
    
    def single_request(self, host, handler, request_body, verbose=0):
        h = self.make_connection(host)
        if verbose:
            h.set_debuglevel(1)
        try:
            self.send_request(h, handler, request_body)
            self.send_host(h, host)
            self.send_user_agent(h)
            self.send_content(h, request_body)
            self.verbose = verbose
            h.close()  # h is closed by the standard transport anyway, so it's fine to ignore the response by doing this.
            response = io.StringIO(self.mock_xml_response)
            return self.parse_response(response)
        except xmlrpclib.Fault:
            raise
        except Exception:
            # All unexpected errors leave connection in a strange state, so we clear it.
            self.close()
            raise
    

class EjabberdCTL(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.xmlrpc_server_needsresponse = xmlrpclib.ServerProxy('http://%s:%s' % (constants.xmlrpc_server, constants.xmlrpc_port))
        self.xmlrpc_server_fireandforget = xmlrpclib.ServerProxy('http://%s:%s' % (constants.xmlrpc_server, constants.xmlrpc_port),
                                                                 transport=FireAndForget())
    
    def register(self, user, password):
        self._xmlrpc_command('register', {
            'user': user,
            'host': constants.domain,
            'password': password
        }, self.xmlrpc_server_needsresponse)
    
    def unregister(self, user):
        self._xmlrpc_command('unregister', {
            'user': user,
            'host': constants.domain,
        }, self.xmlrpc_server_needsresponse)
    
    def add_rosteritem(self, user, vinebot_user, nick):
        self._xmlrpc_command('add_rosteritem', {
            'localuser': user,
            'localserver': constants.domain,
            'user': vinebot_user,
            'server': constants.leaves_domain,
            'group': '%s@%s ' % (user, constants.domain),
            'nick': nick,
            'subs': 'both'
        }, self.xmlrpc_server_fireandforget)
    
    def delete_rosteritem(self, user, vinebot_user):
        self._xmlrpc_command('delete_rosteritem', {
            'localuser': user,
            'localserver': constants.domain,
            'user': vinebot_user,
            'server': constants.leaves_domain,
        }, self.xmlrpc_server_fireandforget)
    
    def get_roster(self, user):
        rosteritems = self._xmlrpc_command('get_roster', {
            'user': user, 
            'host': constants.domain}, self.xmlrpc_server_needsresponse)
        roster = []
        for rosteritem in rosteritems['contacts']:
            rosteritem = rosteritem['contact']
            if rosteritem[2]['subscription'] != 'both':
                g.logger.warning('Incorrect roster subscription for: %s' % rosteritem)
            if rosteritem[4]['group'] != '%s@%s' % (user, constants.domain):
                g.logger.warning('Incorrect roster group for rosteritem: %s' % rosteritem)
            user = rosteritem[0]['jid'].split('@')[0]
            if not user.startswith(constants.vinebot_prefix):
                g.logger.warning("Non-vinebot user(s) found on roster for user %s!\n%s" % (user, rosteritems))
            roster.append((user, rosteritem[1]['nick'], rosteritem[4]['group']))
        return roster
    
    def user_status(self, user):
        try:              
            res = self._xmlrpc_command('user_sessions_info', {
                'user': user,
                'host': constants.domain
            }, self.xmlrpc_server_needsresponse)
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
    
    def _xmlrpc_command(self, command, data, xmlrpc_server):
        g.logger.debug('XMLRPC ejabberdctl: %s %s' % (command, str(data)))
        fn = getattr(xmlrpc_server, command)
        return fn({
            'user': self.username,
            'server': constants.domain,
            'password': self.password
        }, data)
    
