#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import getpass
import time
from optparse import OptionParser
import sleekxmpp
import constants

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class InitializerBot(sleekxmpp.ClientXMPP):
    def __init__(self, username, password):
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s' % (username, constants.server), password)
        self.commands = [
            "/delete_user alice",
            "/delete_user chesire_cat",
            "/delete_user queen_of_hearts",
            "/delete_user dormouse",
            "/delete_user march_hare ",
            "/create_user alice password",
            "/create_user chesire_cat password",
            "/create_user queen_of_hearts password",
            "/create_user dormouse password",
            "/create_user march_hare password",
            "sleep 5",  #NOTE sleep here so that the proxybots can finish their adhoc commands #LATER find a better way to do this
            "/create_friendship alice queen_of_hearts",
            "/create_friendship alice chesire_cat",
            "/create_friendship dormouse chesire_cat",
            "/create_friendship march_hare queen_of_hearts"]
        self.command_iterator = self.commands.__iter__()
        self.outstanding_commands = 0
        self.add_event_handler('session_start', self._handle_start)
        self.add_event_handler('message', self._handle_message)
        self.add_event_handler('disconnect', self.disconnect, threaded=True)

    def _handle_start(self, event):
        self.send_presence()
        self.get_roster()
        self._send_next_command()

    def _handle_message(self, msg):
        if msg['type'] in ('chat', 'normal') and msg['from'].bare == constants.hostbot_user_jid:
            logging.info('%(user)-18s: %(body)s\n' % {'user': msg['from'], 'body': msg['body']})
            self._send_next_command()

    def _send_next_command(self):
        try:
            command = self.command_iterator.next()
            if command.split(' ')[0] == 'sleep':
                logging.info('%(user)-18s: %(body)s\n' % {'user': self.boundjid.bare, 'body': '(sleeping)'})
                time.sleep(int(command.split(' ')[1]))
                command = self.command_iterator.next()
            self.send_message(mto=constants.hostbot_user_jid, mbody=command, mtype='chat')
            logging.info('%(user)-18s: %(body)s' % {'user': self.boundjid.bare, 'body': command})
        except StopIteration, e:    
            self.event('disconnect', {})


if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)
    optp.add_option("-u", "--username", dest="username",
                    help="admin username")
    optp.add_option("-p", "--password", dest="password",
                    help="password to use")
    opts, args = optp.parse_args()

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    if not opts.username.startswith('admin'):
        opts.jid = raw_input("Admin username: ")

    xmpp = InitializerBot(opts.username, opts.password or constants.admin_password)
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0199') # XMPP Ping

    if xmpp.connect():
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")