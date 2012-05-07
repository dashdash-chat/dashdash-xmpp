#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import getpass
from optparse import OptionParser
import sleekxmpp

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

PROXYBOT_PASSWORD = 'ow4coirm5oc5coc9folv' #TODO read from config file
    
class ProxyBot(sleekxmpp.ClientXMPP):
    def __init__(self, username, server, contacts):
        # if not jid.startswith('proxybot'):
        #     logging.error("Not a valid proxybot JID: %s" % jid)
        #     return
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s' % (username, server), PROXYBOT_PASSWORD)
        self.convo_active = False
        self.contacts = contacts
        self.add_event_handler("session_start", self._start)
        self.add_event_handler("message", self._message)
        self.add_event_handler('presence_subscribe', self._handle_subscribe)
    
    def disconnect(self, reconnect=False, wait=None, send_close=True):    
        if self.authenticated:
            self['xep_0077'].cancel_registration(jid=self.boundjid.host, ifrom=self.boundjid, block=False)
            if not self.convo_active:
                print "TODO remove entry from database, since we've disconnected from an unavailable presense"
        super(ProxyBot, self).disconnect(reconnect=reconnect, wait=True, send_close=send_close)
                                                  
    def _start(self, event):
        self.sendPresenceSubscription(pto='%s@%s' % (self.contacts[0], self.boundjid.host), 
                                      ptype='subscribe', 
                                      pnick=self.contacts[1])
        self.sendPresenceSubscription(pto='%s@%s' % (self.contacts[1], self.boundjid.host), 
                                      ptype='subscribe', 
                                      pnick=self.contacts[0])                     
        # self.send_presence() because no one is on the list
        self.get_roster()
        print self.client_roster

    def _handle_subscribe(self, presence):
        print ' '
        print 'in presence'
        print presence
        print ' '
        if presence['from'].user in self.contacts:
            self.sendPresence(pto=presence['from'], ptype='subscribed')
        else:
            self.sendPresence(pto=presence['from'], ptype='unsubscribed')

    def _message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            msg.reply("Thanks for sending\n%(body)s" % msg).send()


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
    xmpp.register_plugin('xep_0077') # In-band Registrations
    xmpp.register_plugin('xep_0199') # XMPP Ping

    if xmpp.connect():
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")
