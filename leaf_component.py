#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
from datetime import datetime
import MySQLdb
from MySQLdb import IntegrityError, OperationalError
import logging
from optparse import OptionParser
import uuid
import shortuuid
import sleekxmpp
from sleekxmpp.componentxmpp import ComponentXMPP
from sleekxmpp.exceptions import IqError, IqTimeout
from vinebot import Vinebot
import constants
from ejabberdctl import EjabberdCTL
from mysql_conn import MySQLConnection
from slash_commands import SlashCommand, SlashCommandRegistry, ExecutionError

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class LeafComponent(ComponentXMPP):
    def __init__(self):
        ComponentXMPP.__init__(self,
                               '%s.%s' % (constants.leaf_name, constants.server), 
                               constants.leaf_secret,
                               constants.server,
                               constants.component_port)
        self.registerPlugin('xep_0030') # Service Discovery
        self.registerPlugin('xep_0199') # XMPP Ping
        self.registerPlugin('xep_0085') # Chat State Notifications
        self.db = MySQLConnection(constants.leaf_name, constants.leaf_mysql_password)
        self.ejabberdctl = EjabberdCTL(constants.leaves_xmlrpc_user, constants.leaves_xmlrpc_password)
        self.commands = SlashCommandRegistry()
        self.add_event_handler("session_start",        self.handle_start)
        self.del_event_handler('presence_probe',       self._handle_probe)  # important! see SleekXMPP chat room conversation from June 17, 2012
        self.add_event_handler('presence_probe',       self.handle_presence_available)  # this prevents invisibility from working! it's a misleading thing to support, since other people can enter conversations with you
        self.add_event_handler('presence_available',   self.handle_presence_available)
        self.add_event_handler('presence_chat',        self.handle_presence_available)
        self.add_event_handler('presence_dnd',         self.handle_presence_away)
        self.add_event_handler('presence_away',        self.handle_presence_away)
        self.add_event_handler('presence_xa',          self.handle_presence_away)
        self.add_event_handler('presence_unavailable', self.handle_presence_unavailable)
        self.add_event_handler('message',              self.handle_msg)
        for state in ['active', 'inactive', 'gone', 'composing', 'paused']:
            self.add_event_handler('chatstate_%s' % state, self.handle_chatstate)
    
    def add_slash_commands(self):
        # Access filters for /commands
        def admin_to_vinebot(sender, bot):
            return sender.bare in constants.admin_users and bot.is_vinebot
        def admin_to_leaf(sender, bot):
            return sender.bare in constants.admin_users and not bot.is_vinebot
        def admin_or_graph_to_leaf(sender, bot):
            return sender.bare in (constants.admin_users + [constants.graph_xmpp_user]) and not bot.is_vinebot
        def participant_to_vinebot(sender, bot):
            return sender.user in bot.participants and bot.is_vinebot
        def observer_to_vinebot(sender, bot):
            return sender.user in bot.observers and bot.is_vinebot
        def admin_or_participant_to_vinebot(sender, bot):
            return admin_to_vinebot(sender, bot) or participant_to_vinebot(sender, bot)
        # Argument transformations for /commands
        def logid_sender_vinebot(command_name, sender, bot, arg_string, arg_tokens):
            if bot.is_vinebot and len(arg_tokens) == 0:
                parent_command_id = self.db_log_command(bot.user, sender.user, command_name, None, None)
                return [parent_command_id, sender.user, bot]
            return False
        def logid_sender_vinebot_token(command_name, sender, bot, arg_string, arg_tokens):
            if bot.is_vinebot and len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = self.db_log_command(bot.user, sender.user, command_name, token, None)
                return [parent_command_id, sender.user, bot, token]
            return False
        def logid_sender_vinebot_string_or_none(command_name, sender, bot, arg_string, arg_tokens):
            if bot.is_vinebot:
                string_or_none = arg_string if len(arg_string.strip()) > 0 else None
                parent_command_id = self.db_log_command(bot.user, sender.user, command_name, None, string_or_none)
                return [parent_command_id, sender.user, bot, string_or_none]
            return False
        def logid_sender_vinebot_token_string(command_name, sender, bot, arg_string, arg_tokens):
            if bot.is_vinebot and len(arg_tokens) >= 2:
                token = arg_tokens[0]
                string = arg_string.partition(arg_tokens[0])[2].strip()
                parent_command_id = self.db_log_command(bot.user, sender.user, command_name, token, string)
                return [parent_command_id, sender.user, bot, token, string]
            return False
        def logid_token(command_name, sender, bot, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = self.db_log_command(bot.user, sender.user, command_name, token, None)
                return [parent_command_id, token]
            return False
        def logid_token_or_none(command_name, sender, bot, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = self.db_log_command(bot.user, sender.user, command_name, token, None)
                return [parent_command_id, token]
            elif len(arg_tokens) == 0:
                parent_command_id = self.db_log_command(bot.user, sender.user, command_name, None, None)
                return [parent_command_id]
            return False
        def logid_token_token(command_name, sender, bot, arg_string, arg_tokens):
            if len(arg_tokens) == 2:
                token1 = arg_tokens[0]
                token2 = arg_tokens[1]
                # Please forgive me for storing the second token as the command's string, but ugh I don't want
                # to add an extra column right now. I'll fix it when I have a second command with two tokens.
                parent_command_id = self.db_log_command(bot.user, sender.user, command_name, token1, token2)
                return [parent_command_id, token1, token2]
            return False
        # Register vinebot commands
        self.commands.add(SlashCommand(command_name     = 'join',
                                       text_arg_format  = '',
                                       text_description = 'Join this conversation without interrupting.',
                                       validate_sender  = observer_to_vinebot,
                                       transform_args   = logid_sender_vinebot,
                                       action           = self.user_joined))    
        self.commands.add(SlashCommand(command_name     = 'leave',
                                       text_arg_format  = '',
                                       text_description = 'Leave this conversation.',
                                       validate_sender  = participant_to_vinebot,
                                       transform_args   = logid_sender_vinebot,
                                       action           = self.user_left))                  
        self.commands.add(SlashCommand(command_name     = 'invite',
                                       text_arg_format  = '<username>',
                                       text_description = 'Invite a user to this conversation.',
                                       validate_sender  = admin_or_participant_to_vinebot,
                                       transform_args   = logid_sender_vinebot_token,
                                       action           = self.invite_user))
        self.commands.add(SlashCommand(command_name     = 'kick',
                                       text_arg_format  = '<username>',
                                       text_description = 'Kick a user out of this conversation.',
                                       validate_sender  = admin_or_participant_to_vinebot,
                                       transform_args   = logid_sender_vinebot_token,
                                       action           = self.kick_user))
        self.commands.add(SlashCommand(command_name     = 'list',
                                       text_arg_format  = '',
                                       text_description = 'List the participants in this conversation.',
                                       validate_sender  = admin_or_participant_to_vinebot,
                                       transform_args   = logid_sender_vinebot,
                                       action           = self.list_participants))
        self.commands.add(SlashCommand(command_name     = 'nearby',
                                       text_arg_format  = '',
                                       text_description = 'List the friends of the participants who can see this conversation (but not what you\'re saying).',
                                       validate_sender  = admin_or_participant_to_vinebot,
                                       transform_args   = logid_sender_vinebot,
                                       action           = self.list_observers))
        self.commands.add(SlashCommand(command_name     = 'whisper',
                                       text_arg_format  = '<username> <message text>',
                                       text_description = 'Whisper a quick message to only one other participant.',
                                       validate_sender  = admin_or_participant_to_vinebot,
                                       transform_args   = logid_sender_vinebot_token_string,
                                       action           = self.whisper_msg))
        self.commands.add(SlashCommand(command_name     = 'topic',
                                       text_arg_format  = '<new topic>',
                                       text_description = 'Set the topic for the conversation, which friends of participants can see.',
                                       validate_sender  = admin_or_participant_to_vinebot,
                                       transform_args   = logid_sender_vinebot_string_or_none,
                                       action           = self.set_topic))
        #LATER /listen or /eavesdrop to ask for a new topic from the participants?
        # Register admin commands
        self.commands.add(SlashCommand(command_name     = 'new_user',
                                       text_arg_format  = '<username> <password>',
                                       text_description = 'Create a new user in both ejabberd and the Vine database.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.create_user))
        self.commands.add(SlashCommand(command_name     = 'del_user',
                                       text_arg_format  = '<username>',
                                       text_description = 'Unregister a user in ejabberd and remove her from the Vine database.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.destroy_user))
        self.commands.add(SlashCommand(command_name     = 'new_friendship',
                                       text_arg_format  = '<username1> <username2>',
                                       text_description = 'Create a friendship between two users.',
                                       validate_sender  = admin_or_graph_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.create_friendship))
        self.commands.add(SlashCommand(command_name     = 'del_friendship',
                                       text_arg_format  = '<username1> <username2>',
                                       text_description = 'Delete a friendship between two users.',
                                       validate_sender  = admin_or_graph_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.destroy_friendship))
        self.commands.add(SlashCommand(command_name     = 'prune',
                                       text_arg_format  = '<username>',
                                       text_description = 'Remove old, unused vinebots from a user\'s roster.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.prune_roster))
        self.commands.add(SlashCommand(command_name     = 'friendships',
                                       text_arg_format  = '<username (optional)>',
                                       text_description = 'List all current friendships, or only the specified user\'s friendships.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token_or_none,
                                       action           = self.friendships))
    
    def disconnect(self, *args, **kwargs):
        # LATER check if other leaves are online, since otherwise we don't need to do this.
        # for vinebot in all vinebots
        #    self.send_presences(vinebot, vinebot.everyone, pshow='unavailable')
        self.db.cleanup()
        kwargs['wait'] = True
        super(LeafComponent, self).disconnect(*args, **kwargs)
    
    ##### event handlers
    def handle_start(self, event):
        other_leaves_online = self.register_leaf()
        # if other_leaves_online: do a bunch of stuff
        logging.info('other leaves online? %s' % other_leaves_online)
                
    def register_leaf(self):
        for lock_num_to_acquire in range(constants.max_leaves):
            acquired_lock = self.db.get_lock('%s%s' % (constants.leaf_mysql_lock_name, lock_num_to_acquire))
            logging.info('acquiring %d? %s' % (lock_num_to_acquire, acquired_lock))
            if acquired_lock:
                if lock_num_to_acquire > 0:
                    return True
                for lock_num_to_check in range(lock_num_to_acquire + 1, constants.max_leaves):
                    checked_lock = self.db.is_free_lock('%s%s' % (constants.leaf_mysql_lock_name, lock_num_to_check))
                    logging.info('checking %d? %s' % (lock_num_to_check, checked_lock))
                    if not checked_lock:
                        return True
                return False
        return constants.max_leaves > 0  # if there are no locks to acquire
    
    def handle_presence_available(self, presence):
        pass
    
    def handle_presence_away(self, presence):
        pass
    
    def handle_presence_unavailable(self, presence):
        pass
    
    def handle_msg(self, msg):
        logging.info(msg)
        pass
    
    def handle_chatstate(self, msg):
        pass
    


if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)
    opts, args = optp.parse_args()
    logging.basicConfig(level=opts.loglevel, format='%(asctime)-15s %(levelname)-8s %(message)s')
    xmpp = LeafComponent()
    if xmpp.connect(constants.server_ip, constants.component_port):
        xmpp.process(block=True)
        logging.info("Done")
    else:    
        logging.error("Unable to connect")










































