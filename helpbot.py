#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import uuid
import logging
from mysql_conn import MySQLManager
from optparse import OptionParser
import sleekxmpp
import constants
from constants import g
from ejabberdctl import EjabberdCTL
from edge import FetchedEdge, NotEdgeException
from invite import FetchedInvite, NotInviteException
from user import FetchedUser, NotUserException
from vinebot import FetchedVinebot, NotVinebotException

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

class MessageGraph(object):
    def __init__(self, no_stage_reply):
        self._nodes = {}
        self._no_stage_reply = no_stage_reply
        
    def add_node(self, stage, text_generator):
        self._nodes[stage] = text_generator
        
    def get_reply(self, user, body):
        try:
            text_generator = self._nodes[user.stage]
            stage, reply = text_generator(user, body)
            user.set_stage(stage)
            return reply
        except KeyError:
            return self._no_stage_reply
    
    @staticmethod
    def process_yes_no(stage, body, yes_stage, yes_response, no_stage, no_response):
        body = body.strip()
        if body in ['y', 'yes', 'yep', 'yea', 'yeah', 'ok'] and yes_stage and yes_response:
            return yes_stage, yes_response
        elif body in ['n', 'no', 'nope', 'nah'] and no_stage and no_response:
            return no_stage, no_response
        else:
            return stage, "Sorry, I didn't understand that response. Please answer with either 'yes' or 'no'."
    

class HelpBot(sleekxmpp.ClientXMPP):
    def __init__(self):
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s' % (constants.helpbot_jid_user, constants.domain), constants.helpbot_xmpp_password)
        g.db = MySQLManager(constants.helpbot_mysql_user, constants.helpbot_mysql_password)
        g.ectl = EjabberdCTL(constants.helpbot_xmlrpc_user, constants.helpbot_xmlrpc_password)
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("message", self.message)
        self.final_message = "Sorry, there's nothing else I can do for you right now. Type /help for a list of commands, or ping @lehrblogger with questions!"
        self.message_graph = MessageGraph(self.final_message)
        def node_welcome(user, body):
            return 'roster_groups', "Hi %s, welcome to Vine! I'm here to help you get started. First, look for two new new groups in your buddy list. Do you see them?" % user.name
        self.message_graph.add_node('welcome', node_welcome)
        def node_roster_groups(user, body):
            invite = FetchedInvite(invitee_id=user.id)
            temp_text = "\n\nLook for the contact for our conversation in your buddy list under 'Vine Conversations', and send a message to it."
            if invite.sender.is_online():
                yes_stage = 'friends_online'
                yes_response = "Great, I'll send %s a message!%s" % (invite.sender.name, temp_text)
                other_body = "Hi! Your friend %s just signed up for Vine, so I thought I'd send you a message to show him/her how the buddy list works." % user.name
                other_recipient = invite.sender
            else:
                yes_stage = 'no_friends_online'
                yes_response = "Sorry, %s (who invited you) isn't online right now, so I'll start a conversation with another bot, %s.%s" % (invite.sender.name, constants.echo_user, temp_text)
                other_body = str(uuid.uuid4())  # doesn't matter what, as long as it won't be sent by someone else next
                other_recipient = FetchedUser(name=constants.echo_user)
            self._send_message(other_recipient, other_body)
            return MessageGraph.process_yes_no('roster_groups',
                                               body,
                                               yes_stage,
                                               yes_response,
                                               'roster_groups',
                                               "Sorry, then something might be broken. Maybe check again, or ping lehrblogger for help?")
        self.message_graph.add_node('roster_groups', node_roster_groups)
        self.register_plugin('xep_0030') # Service Discovery
        self.register_plugin('xep_0004') # Data Forms
        self.register_plugin('xep_0060') # PubSub
        self.register_plugin('xep_0199') # XMPP Ping
    
    def _send_message(self, recipient, body):
        msg = self.Message()
        msg['type'] = 'chat'
        msg['body'] = body
        self_user = FetchedUser(name=constants.helpbot_jid_user)
        try:
            outgoing_edge = FetchedEdge(f_user=self_user, t_user=recipient)
            edge_vinebot = FetchedVinebot(dbid=outgoing_edge.vinebot_id)
            msg['to'] = '%s@%s' % (edge_vinebot.jiduser, constants.leaves_domain)
            msg.send()
        except NotEdgeException:
            g.logger.warning('No edge found from %s to intended message recipient %s!' % (self_user.name, recipient.name))
    
    def start(self, event):
        self.send_presence()
        self.get_roster()
    
    def message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            try:
                vinebot = FetchedVinebot(jiduser=msg['from'].username)
                if msg['body'].startswith('*** '):  # Do this first, in case the conversation is residually active
                    if msg['body'].find(constants.act_on_user_stage) >= 0:
                        try:
                            g.logger.info(msg['body'])
                            _, sender_name = msg['body'].split(constants.act_on_user_stage, 1)
                            sender = FetchedUser(can_write=True, name=sender_name.strip())
                            if sender.needs_onboarding():  # Only handle this message once, otherwise we'll jump ahead in the flow.
                                msg.reply(self.message_graph.get_reply(sender, None)).send()
                        except NotUserException:
                            g.logger.warning('User not found for %s' % sender_name.strip())
                    elif msg['body'].find('left the conversation') >= 0:
                        msg.reply('/leave').send()
                    else:
                        g.logger.warning('Message ignored: %s' % msg)
                elif len(vinebot.participants) == 2:
                    sender = filter(lambda user: user.name != self.boundjid.user, vinebot.participants)[0]  # get the other participant's user object
                    body = msg['body'].replace('[%s]' % sender.name, '').strip()
                    msg.reply(self.message_graph.get_reply(sender, body)).send()
                else:
                    from_string, _ = msg['body'].split('] ', 1)
                    from_string  = from_string.strip('[')
                    from_strings = from_string.split(', ')
                    sender_name = from_strings[0].strip()
                    if len(from_strings) == 2 and from_strings[1].strip() == 'whispering':
                        msg.reply('/whisper %s %s' % (sender_name, self.final_message)).send()
                    elif sender_name != constants.echo_user:
                        msg.reply('/me sits quietly').send()
            except NotVinebotException:
                msg.reply('Sorry, something seems to be wrong. Type /help for a list of commands, or ping @lehrblogger with questions!').send()
    

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
    xmpp = HelpBot()
    if xmpp.connect((constants.server_ip, constants.client_port)):
        xmpp.process(block=True)
        g.logger.info("Done")
    else:    
        g.logger.error("Unable to connect")
    logging.shutdown()
