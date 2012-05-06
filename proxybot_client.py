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


class ProxyBot(sleekxmpp.ClientXMPP):
    def __init__(self, jid, password):
        # if not jid.startswith('proxybot'):
        #     logging.error("Not a valid proxybot JID: %s" % jid)
        #     return
        sleekxmpp.ClientXMPP.__init__(self, jid, password)
        self.convo_active = False
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.message)
    
    def disconnect(self, reconnect=False, wait=None, send_close=True):    
        if self.authenticated:
            self['xep_0077'].cancel_registration(jid=self.boundjid.host, ifrom=self.boundjid, block=False)
        super(ProxyBot, self).disconnect(reconnect=reconnect, wait=True, send_close=send_close)
                                                  
    def start(self, event):
        self.send_presence()
        self.get_roster()

    def message(self, msg):
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
    optp.add_option("-j", "--jid", dest="jid",
                    help="JID to use")
    optp.add_option("-p", "--password", dest="password",
                    help="password to use")
    opts, args = optp.parse_args()

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    if opts.jid is None:
        opts.jid = raw_input("Username: ")
    if opts.password is None:
        opts.password = getpass.getpass("Password: ")

    xmpp = ProxyBot(opts.jid, opts.password)
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
