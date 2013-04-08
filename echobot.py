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

class EchoBot(sleekxmpp.ClientXMPP):
    def __init__(self, jid, password):
        sleekxmpp.ClientXMPP.__init__(self, jid, password)
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.message)
        self.last_message = None
    
    def start(self, event):
        self.send_presence()
        self.get_roster()
    
    def message(self, msg):
        if msg['type'] in ('chat', 'normal') and msg['body'].startswith('[') and not msg['body'].startswith('/me '):
            from_string, body = msg['body'].split('] ', 1)
            from_string  = from_string.strip('[')
            from_strings = from_string.split(', ')
            body = body.strip()
            if self.last_message != body:  # simple guard against infinite loops between demobots
                self.last_message = body
                if self.boundjid.user == 'cheshire_cat':
                    body = '%s :D' % body
                if len(from_strings) == 2 and from_strings[1].strip() == 'whispering':
                    msg.reply('/whisper %s %s' % (from_strings[0].strip(), body)).send()
                else:
                    msg.reply(body).send()
    

if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to DEBUG',
                    action='store_const', dest='loglevel',
                    const=logging.DEBUG, default=logging.INFO)
    opts, args = optp.parse_args()
    logging.basicConfig(format=constants.log_format, level=opts.loglevel)
    
    xmpp = EchoBot('%s@%s' % (constants.echo_user, constants.domain), constants.default_user_password)
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0004') # Data Forms
    xmpp.register_plugin('xep_0060') # PubSub
    xmpp.register_plugin('xep_0199') # XMPP Ping
    
    if xmpp.connect((constants.server_ip, constants.client_port)):
        xmpp.process(block=True)
        logging.info("Done")
    else:
        logging.info("Unable to connect.")
    logging.shutdown()

