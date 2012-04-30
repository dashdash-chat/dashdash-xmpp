#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import getpass
from optparse import OptionParser
import sleekxmpp
from sleekxmpp.componentxmpp import ComponentXMPP

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class HostbotComponent(ComponentXMPP):
    def __init__(self, jid, secret, server, port):
        ComponentXMPP.__init__(self, jid, secret, server, port)
        self.nick = 'Hostbot'
        self.auto_authorize = True

        # You don't need a session_start handler, but that is
        # where you would broadcast initial presence.

        # The message event is triggered whenever a message
        # stanza is received. Be aware that that includes
        # MUC messages and error messages.
        self.add_event_handler('message', self.message)
        self.add_event_handler('presence_probe', self.handle_probe)

    def fulljid_with_user(self):
        return 'host' + '@' + self.boundjid.full

    def message(self, msg):
        if msg['type'] in ['groupchat', 'error']: return
        if msg['to'].user == 'host':
            if msg['body'].startswith('/'):
                cmd, space, body = msg['body'].lstrip('/').partition(' ')
                if cmd == 'help':
                    msg.reply("The available commands are:"
                        + "\n    /help - print a list of commands"
                        + "\n    /echo - echo back the message you sent"
                        + "\n(All commands should be followed by a space, and then the text on which you want the command to operate.)").send()
                elif cmd == 'echo':
                    msg.reply("Echo:\n%(body)s" % {'body': body}).send()
                elif cmd == 'roster':
                    self.update_roster('hatter@localhost', name='Mad Hatter', groups=['Chatidea Contacts'])
                    msg.reply("cool").send()
                else:
                    msg.reply("I'm sorry, I didn't understand that command.\nType /help for a full list.").send()
            else:
                msg.reply("Hi, welcome to Chatidea.im!\nType /help for a list of commands.").send()
        else:
            resp = msg.reply("You've got the wrong bot!\nPlease contact host@%s for assistance." % msg['to'].domain).send()
            
    def handle_probe(self, presence):
        #handle proxy bot stuff here
        self.sendPresence(pfrom=self.fulljid_with_user(), pnick=self.nick, pto=presence['from'], pstatus="Who do you want to chat with?", pshow="available")

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
    optp.add_option("-s", "--server", dest="server",
                    help="server to connect to")
    optp.add_option("-P", "--port", dest="port",
                    help="port to connect to")
    opts, args = optp.parse_args()

    if opts.jid is None:
        opts.jid = 'bot.localhost'
    if opts.password is None:
        opts.password = 'yeij9bik9fard3ij4bai'
    if opts.server is None:
        opts.server = 'localhost'
    if opts.port is None:
        opts.port = 5237

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    xmpp = HostbotComponent(opts.jid, opts.password, opts.server, opts.port)
    xmpp.registerPlugin('xep_0030') # Service Discovery
    xmpp.registerPlugin('xep_0004') # Data Forms
    xmpp.registerPlugin('xep_0060') # PubSub
    xmpp.registerPlugin('xep_0199') # XMPP Ping

    if xmpp.connect('127.0.0.1'):
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")
