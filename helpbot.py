#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
from mysql_conn import MySQLManager
from optparse import OptionParser
import sleekxmpp
import constants
from constants import g
from edge import FetchedEdge, NotEdgeException
from user import FetchedUser, NotUserException
from vinebot import FetchedVinebot, NotVinebotException

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

class EchoBot(sleekxmpp.ClientXMPP):
    def __init__(self, jid, password):
        sleekxmpp.ClientXMPP.__init__(self, jid, password)
        g.db = MySQLManager(constants.help_mysql_user, constants.help_mysql_password)
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.message)
    
    def start(self, event):
        self.send_presence()
        self.get_roster()
    
    def message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            g.logger.info(msg['body'])
            if not msg['from'].user.startswith(constants.vinebot_prefix):
                try:
                    _, username = msg['body'].split('*** ')
                except ValueError:
                    g.logger.warning('Message ignored: %s' % msg)
                    return
                try:
                    helpbot = FetchedUser(name=constants.help_jid_user)
                    user = FetchedUser(can_write=True, name=username)
                    outgoing_edge = FetchedEdge(f_user=helpbot, t_user=user)
                    vinebot = FetchedVinebot(dbid=outgoing_edge.vinebot_id)
                    if not user.is_onboarded():
                        new_msg = self.Message()
                        new_msg['type'] = 'chat'
                        new_msg['body'] = constants.onboarding_messages[user.onboarding_stage]
                        new_msg['to'] = '%s@%s' % (vinebot.jiduser, constants.leaves_domain)
                        new_msg.send()
                        user.increment_onboarding_stage()
                except NotUserException:
                    g.logger.warning('User not found for %s' % username)
                except NotEdgeException:
                    g.logger.warning('Edge not found from %s to %s' % (constants.help_jid_user, username))
                except NotVinebotException:
                    g.logger.warning('Vinebot not found for %s and %s with id=%d' % (constants.help_jid_user, username, outgoing_edge.vinebot_id))
            else:
                msg.reply('Sorry, but I\'m not the smartest of chat bots. Type /help for a list of commands, or ping @lehrblogger with questions!').send()

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
    g.loglevel = opts.loglevel
    g.use_new_logger('helpbot')
    xmpp = EchoBot('%s@%s' % (constants.help_jid_user, constants.domain), constants.help_xmpp_password)
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0004') # Data Forms
    xmpp.register_plugin('xep_0060') # PubSub
    xmpp.register_plugin('xep_0199') # XMPP Ping
    if xmpp.connect((constants.server_ip, constants.client_port)):
        xmpp.process(block=True)
        g.logger.info("Done")
    else:    
        g.logger.error("Unable to connect")
    logging.shutdown()
