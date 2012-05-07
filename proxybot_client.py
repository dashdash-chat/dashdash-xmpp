#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import getpass
from optparse import OptionParser
import xmlrpclib
import sleekxmpp

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

#TODO read these from config file?
HOSTBOT_PASSWORD = 'yeij9bik9fard3ij4bai'
PROXYBOT_PASSWORD = 'ow4coirm5oc5coc9folv'
SERVER_URL = '127.0.0.1'
XMLRPC_SERVER_URL = 'http://%s:4560' % SERVER_URL
XMLRPC_LOGIN = {'user': 'host', 'server': 'localhost', 'password': HOSTBOT_PASSWORD} #NOTE the server is not bot.localhost because of xml_rpc authentication

    
class ProxyBot(sleekxmpp.ClientXMPP):
    def __init__(self, username, server, contacts):
        # if not jid.startswith('proxybot'):
        #     logging.error("Not a valid proxybot JID: %s" % jid)
        #     return
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s' % (username, server), PROXYBOT_PASSWORD)
        self.convo_active = False
        self.contacts = set(contacts)
        self.xmlrpc_server = xmlrpclib.ServerProxy(XMLRPC_SERVER_URL)
        self.add_event_handler("session_start", self._start)
        self.add_event_handler("message", self._message)
    
    def disconnect(self, reconnect=False, wait=None, send_close=True):    
        if self.authenticated:
            if not self.convo_active:
                contacts = list(self.contacts)
                self._delete_rosteritem_proxy(contacts[0], contacts[1])
                self._delete_rosteritem_proxy(contacts[1], contacts[0])
                print "TODO remove entry from database, since we've disconnected from an unavailable presense"  
            self._xmlrpc_command('unregister', {
                'user': self.boundjid.user,
                'host': self.boundjid.host
            })
        super(ProxyBot, self).disconnect(reconnect=reconnect, wait=True, send_close=send_close)
                                                  
    def _start(self, event):
        contacts = list(self.contacts)
        self._add_rosteritem_proxy(contacts[0], contacts[1])
        self._add_rosteritem_proxy(contacts[1], contacts[0])
        for contact in self.contacts:
            self.send_presence(pto='%s@localhost' % contact, pshow="available") # because no one is on the list
        self.send_presence() # need this so we can receive messages
        self.get_roster()
        
    def _xmlrpc_command(self, command, data):
            fn = getattr(self.xmlrpc_server, command)
            return fn({
                'user': self.boundjid.user,
                'server': self.boundjid.host,
                'password': PROXYBOT_PASSWORD
            }, data)

    def _add_rosteritem_proxy(self, contact1, contact2):
        self._xmlrpc_command('add_rosteritem', {
            'localuser': contact1,
            'localserver': self.boundjid.host,
            'user': self.boundjid.user,
            'server': self.boundjid.host,
            'nick': contact2,
            'group': 'Chatidea Contacts',
            'subs': 'both'
        })
        # self._xmlrpc_command('add_rosteritem', {
        #     'localuser': self.boundjid.user,
        #     'localserver': self.boundjid.host,
        #     'user': contact1,
        #     'server': self.boundjid.host,
        #     'nick': contact1,
        #     'group': 'participants',
        #     'subs': 'both'
        # })

    def _delete_rosteritem_proxy(self, contact1, contact2):
        self._xmlrpc_command('delete_rosteritem', {
            'localuser': contact1,
            'localserver': self.boundjid.host,
            'user': self.boundjid.user,
            'server': self.boundjid.host
        })

    def _message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if msg['from'].user in self.contacts:
                for contact in self.contacts:
                    if msg['from'].user is not contact:
                        self.send_message(mto="%s@localhost" % contact, mbody=msg['body'], mtype='chat')
            else:
                msg.reply("You cannot send messages with this proxybot.").send()


if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-d', '--debug', help='set logging to DEBUG',
                    action='store_const', dest='loglevel',
                    const=logging.DEBUG, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)
    optp.add_option("-u", "--username", dest="username",
                    help="proxybot username")
    optp.add_option("-s", "--server", dest="server",
                    help="server for proxybot and contacts")
    optp.add_option("-1", "--contact1", dest="contact1",
                    help="first contact's username")
    optp.add_option("-2", "--contact2", dest="contact2",
                    help="second contact's username")
    opts, args = optp.parse_args()

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    if opts.username is None:
        opts.username = raw_input("Proxybot username: ")
    if opts.server is None:
        opts.server = raw_input("Server for proxybot and contacts: ")
    if opts.contact1 is None:
        opts.contact1 = raw_input("First contact for this proxybot: ")
    if opts.contact2 is None:
        opts.contact2 = getpass.getpass("Second contact for this proxybot: ")

    xmpp = ProxyBot(opts.username, opts.server, [opts.contact1, opts.contact2])
    xmpp.register_plugin('xep_0030') # Service Discovery
    # xmpp.register_plugin('xep_0004') # Data Forms
    # xmpp.register_plugin('xep_0060') # PubSub
    xmpp.register_plugin('xep_0199') # XMPP Ping

    if xmpp.connect():
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")
