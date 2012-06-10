#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
from optparse import OptionParser
import sleekxmpp
import constants

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class DemoBot(sleekxmpp.ClientXMPP):
    def __init__(self, jid):
        sleekxmpp.ClientXMPP.__init__(self, jid, constants.default_user_password)
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.message)
        self.last_message = None

    def start(self, event):
        self.send_presence()
        self.get_roster()

    def message(self, msg):
        if msg['type'] in ('chat', 'normal') and msg['body'].startswith('[') and not msg['body'].startswith('/me '):
            body = msg['body'].split(']')[1].strip()
            if self.last_message != body:  # prevent infinite loops between demobots 
                msg.reply(body).send()
                self.last_message = body


if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)
    optp.add_option("-j", "--jid", dest="jid",
                    help="JID to use")
    opts, args = optp.parse_args()
    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    if opts.jid is None:
        opts.jid = raw_input("Username: ")
    
    xmpp = DemoBot(opts.jid)
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0004') # Data Forms
    xmpp.register_plugin('xep_0060') # PubSub
    xmpp.register_plugin('xep_0199') # XMPP Ping
    
    if xmpp.connect((constants.server_ip, constants.client_port)):
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")

