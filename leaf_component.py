#!/usr/bin/env python
# -*- coding: utf-8 -*-
from gevent import monkey; monkey.patch_all()
import sys
from datetime import datetime
from MySQLdb import IntegrityError, OperationalError, ProgrammingError
import logging
from optparse import OptionParser
import re
import uuid
import shortuuid
import sleekxmpp
from sleekxmpp.componentxmpp import ComponentXMPP
from sleekxmpp.exceptions import IqError, IqTimeout
from sleekxmpp.xmlstream.scheduler import Task
from twilio.rest import TwilioRestClient
import twitter
import constants
from constants import g
from ejabberdctl import EjabberdCTL
from mysql_conn import MySQLManager
from slash_commands import SlashCommand, SlashCommandRegistry, ExecutionError
from invite import FetchedInvite, InsertedInvite, AbstractInvite, NotInviteException, ImmutableInviteException
from user import FetchedUser, InsertedUser, NotUserException
from edge import FetchedEdge, InsertedEdge, NotEdgeException
from vinebot import AbstractVinebot, FetchedVinebot, InsertedVinebot, NotVinebotException, PRONOUN
try:
    import web.celery_tasks as celery_tasks
except ImportError:
    celery_tasks = None
    
if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

CURRENT_TCO_LENGTH = 20

class LeafComponent(ComponentXMPP):
    def __init__(self):
        ComponentXMPP.__init__(self,
                               constants.leaves_domain,
                               constants.leaves_secret,
                               constants.domain,
                               constants.component_port)
        self.registerPlugin('xep_0030') # Service Discovery
        self.registerPlugin('xep_0199') # XMPP Ping
        self.registerPlugin('xep_0085') # Chat State Notifications
        self.acquired_lock_num = None
        g.db = MySQLManager(constants.leaves_mysql_user, constants.leaves_mysql_password)
        g.ectl = EjabberdCTL(constants.leaves_xmlrpc_user, constants.leaves_xmlrpc_password)
        g.send_presences = self.send_presences
        self.commands = SlashCommandRegistry()
        self.add_slash_commands()
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
        def admin_to_vinebot(sender, vinebot):
            return vinebot and sender.jid in constants.admin_jids
        def admin_to_leaf(sender, vinebot):
            return not vinebot and sender.jid in constants.admin_jids
        def admin_or_graph_to_leaf(sender, vinebot):
            return not vinebot and sender.jid in (constants.admin_jids + [constants.graph_jid])
        def admin_or_helpbot_to_leaf(sender, vinebot):
            return not vinebot and sender.jid in (constants.admin_jids + [constants.helpbot_jid])
        def participant_or_edgeuser_to_vinebot(sender, vinebot):
            return vinebot and (sender in vinebot.participants or sender in vinebot.edge_users)   # short circuit to avoid the extra query
        def observer_to_vinebot(sender, vinebot):
            return vinebot and sender in vinebot.observers
        def admin_or_observer_to_vinebot(sender, vinebot):
            return admin_to_vinebot(sender, vinebot) or observer_to_vinebot(sender, vinebot)
        def admin_or_participant_or_edgeuser_to_vinebot(sender, vinebot):
            return admin_to_vinebot(sender, vinebot) or participant_or_edgeuser_to_vinebot(sender, vinebot)
        def user_to_vinebot(sender, vinebot):
            return True
        # Argument transformations for /commands
        def logid_vinebot_sender(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot and len(arg_tokens) == 0:
                parent_command_id = g.db.log_command(sender, command_name, None, None, vinebot=vinebot)
                return [parent_command_id, vinebot, sender]
            return False
        def logid_vinebot_sender_token(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot and len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = g.db.log_command(sender, command_name, token, None, vinebot=vinebot)
                return [parent_command_id, vinebot, sender, token]
            return False
        def logid_vinebot_sender_string_or_none(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot:
                string_or_none = arg_string if len(arg_string.strip()) > 0 else None
                parent_command_id = g.db.log_command(sender, command_name, None, string_or_none, vinebot=vinebot)
                return [parent_command_id, vinebot, sender, string_or_none]
            return False
        def logid_vinebot_sender_token_string(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot and len(arg_tokens) >= 2:
                token = arg_tokens[0]
                string = arg_string.partition(arg_tokens[0])[2].strip()
                parent_command_id = g.db.log_command(sender, command_name, token, string, vinebot=vinebot)
                return [parent_command_id, vinebot, sender, token, string]
            return False
        def logid_vinebot_sender_token_string_or_none(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot and len(arg_tokens) >= 1:
                token = arg_tokens[0]
                string = arg_string.partition(arg_tokens[0])[2].strip()
                string_or_none = string if len(string) > 0 else None
                parent_command_id = g.db.log_command(sender, command_name, token, string_or_none, vinebot=vinebot)
                return [parent_command_id, vinebot, sender, token, string_or_none]
            return False
        def logid_token(command_name, sender, vinebot, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = g.db.log_command(sender, command_name, token, None, vinebot=vinebot)
                return [parent_command_id, token]
            return False
        def logid_token_or_none(command_name, sender, vinebot, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = g.db.log_command(sender, command_name, token, None, vinebot=vinebot)
                return [parent_command_id, token]
            elif len(arg_tokens) == 0:
                parent_command_id = g.db.log_command(sender, command_name, None, None, vinebot=vinebot)
                return [parent_command_id]
            return False
        def logid_token_token(command_name, sender, vinebot, arg_string, arg_tokens):
            if len(arg_tokens) == 2:
                token1 = arg_tokens[0]
                token2 = arg_tokens[1]
                # Please forgive me for storing the second token as the command's string, but ugh I don't want
                # to add an extra column right now. I'll fix it when I have a second command with two tokens.
                parent_command_id = g.db.log_command(sender, command_name, token1, token2, vinebot=vinebot)
                return [parent_command_id, token1, token2]
            return False
        def logid_token_int_or_none(command_name, sender, vinebot, arg_string, arg_tokens):
            if len(arg_tokens) == 2:
                token1 = arg_tokens[0]
                token2 = arg_tokens[1]
                parent_command_id = g.db.log_command(sender, command_name, token1, token2, vinebot=vinebot)
                try:  # convert to int here to prevent string error when logging, see comment in logid_token_token
                    token2 = int(token2)
                except ValueError:
                    return False
                if token2 < 1:
                    return False
                return [parent_command_id, token1, token2]
            return logid_token(command_name, sender, vinebot, arg_string, arg_tokens)
        # Register vinebot commands
        self.commands.add(SlashCommand(command_name     = 'debug',
                                       list_rank        = 1000,
                                       text_arg_format  = '',
                                       text_description = 'Information about this conversation that\'s useful for debugging.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.debug_vinebot))
        self.commands.add(SlashCommand(command_name     = 'block',
                                       list_rank        = 700,
                                       text_arg_format  = '<username>',
                                       text_description = 'Prevent a user from seeing if you\'re online or joining your conversations.',
                                       validate_sender  = participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token,
                                       action           = self.block_user))
        self.commands.add(SlashCommand(command_name     = 'unblock',
                                       list_rank        = 701,
                                       text_arg_format  = '<username>',
                                       text_description = 'Allow a previously-blocked user to see if you\'re online and join your conversations.',
                                       validate_sender  = participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token,
                                       action           = self.unblock_user))
        self.commands.add(SlashCommand(command_name     = 'blocks',
                                       list_rank        = 702,
                                       text_arg_format  = '',
                                       text_description = 'List the users you currently have blocked.',
                                       validate_sender  = participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.list_blockees))
        self.commands.add(SlashCommand(command_name     = 'join',
                                       list_rank        = 900,
                                       text_arg_format  = '',
                                       text_description = 'Join this conversation without interrupting.',
                                       validate_sender  = admin_or_observer_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.user_joined))    
        self.commands.add(SlashCommand(command_name     = 'leave',
                                       list_rank        = 800,
                                       text_arg_format  = '',
                                       text_description = 'Leave this conversation. If it\'s just the two of you, it will no longer be visible to friends.',
                                       validate_sender  = participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.user_left))                  
        self.commands.add(SlashCommand(command_name     = 'invite',
                                       list_rank        = 1,
                                       text_arg_format  = '<username>',
                                       text_description = 'Invite a user to this conversation.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token,
                                       action           = self.invite_user))
        self.commands.add(SlashCommand(command_name     = 'kick',
                                       list_rank        = 20,
                                       text_arg_format  = '<username>',
                                       text_description = 'Kick a user out of this conversation.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token,
                                       action           = self.kick_user))
        self.commands.add(SlashCommand(command_name     = 'list',
                                       list_rank        = 100,
                                       text_arg_format  = '',
                                       text_description = 'List the participants in this conversation.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.list_participants))
        self.commands.add(SlashCommand(command_name     = 'nearby',
                                       list_rank        = 150,
                                       text_arg_format  = '',
                                       text_description = 'List the friends of the participants who can see this conversation (but not what you\'re saying).',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.list_observers))
        self.commands.add(SlashCommand(command_name     = 'whisper',
                                       list_rank        = 250,
                                       text_arg_format  = '<username> <message text>',
                                       text_description = 'Whisper a quick message to only one other participant.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token_string,
                                       action           = self.whisper_msg))
        self.commands.add(SlashCommand(command_name     = 'topic',
                                       list_rank        = 90,
                                       text_arg_format  = '<new topic>',
                                       text_description = 'Set the topic for the conversation, which friends of participants can see.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_string_or_none,
                                       action           = self.set_topic))
        self.commands.add(SlashCommand(command_name     = 'invites',
                                       list_rank        = 200,
                                       text_arg_format  = '',
                                       text_description = 'List the invite codes that your friends can use to sign up.',
                                       validate_sender  = participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.invites))
        self.commands.add(SlashCommand(command_name     = 'tweet_invite',
                                       list_rank        = 10,
                                       text_arg_format  = '<twitter_username> <optional tweet_body>',
                                       text_description = 'Post a tweet inviting someone to sign up that reads: "@username tweet_body %sinvite_code"' % AbstractInvite.url_prefix,
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token_string_or_none,
                                       action           = self.tweet_invite))
        self.commands.add(SlashCommand(command_name     = 'me',
                                       list_rank        = 30,
                                       text_arg_format  = '<action_message>',
                                       text_description = 'Sends a message in the format "*** [username] action_message".',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_string_or_none,
                                       action           = self.me_action_message))
        self.commands.add(SlashCommand(command_name     = 'party',
                                       list_rank        = 5,
                                       text_arg_format  = '<comma,separated,usernames> /topic <party_topic>',
                                       text_description = 'Start a new conversation with the specified topic, and send a message to the listed users asking if they want to join. Remember the "/topic" in the middle! ',
                                       validate_sender  = user_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token_string,
                                       action           = self.party))
        self.commands.add(SlashCommand(command_name     = 'online',
                                       list_rank        = 6,
                                       text_arg_format  = '',
                                       text_description = 'List your contacts who are online – great for copy-pasting into /party!',
                                       validate_sender  = user_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.online_contacts))
        #LATER /listen or /eavesdrop to ask for a new topic from the participants?
        # Register admin commands
        self.commands.add(SlashCommand(command_name     = 'new_user',
                                       list_rank        = 1,
                                       text_arg_format  = '<username> <password>',
                                       text_description = 'Create a new user in both ejabberd and the Dashdash database.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.create_user))
        self.commands.add(SlashCommand(command_name     = 'del_user',
                                       list_rank        = 2,
                                       text_arg_format  = '<username>',
                                       text_description = 'Unregister a user in ejabberd and deactivate her in the Dashdash database.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.delete_user))
        self.commands.add(SlashCommand(command_name     = 'purge_user',
                                       list_rank        = 3,
                                       text_arg_format  = '<username> --force',
                                       text_description = 'Unregister a user in ejabberd and purge ALL of her entries from the Dashdash database.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.purge_user))
        self.commands.add(SlashCommand(command_name     = 'new_edge',
                                       list_rank        = 4,
                                       text_arg_format  = '<username1> <username2>',
                                       text_description = 'Create a friendship between two users.',
                                       validate_sender  = admin_or_graph_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.create_edge))
        self.commands.add(SlashCommand(command_name     = 'del_edge',
                                       list_rank        = 5,
                                       text_arg_format  = '<username1> <username2>',
                                       text_description = 'Delete a friendship between two users.',
                                       validate_sender  = admin_or_graph_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.delete_edge))
        self.commands.add(SlashCommand(command_name     = 'sync',
                                       list_rank        = 6,
                                       text_arg_format  = '<username>',
                                       text_description = 'Remove old, unused conversation contacts from a user\'s roster.',
                                       validate_sender  = admin_or_graph_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.sync_roster))
        self.commands.add(SlashCommand(command_name     = 'edges',
                                       list_rank        = 7,
                                       text_arg_format  = '<username>',
                                       text_description = 'List all current edges, or only the specified user\'s edges.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.list_edges))
        self.commands.add(SlashCommand(command_name     = 'hide_invite',
                                       list_rank        = 10,
                                       text_arg_format  = '<code>',
                                       text_description = 'Mark an invite as hidden, so that it isn\'t listed on http://dashdash.com.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.hide_invite))
        self.commands.add(SlashCommand(command_name     = 'show_invite',
                                       list_rank        = 11,
                                       text_arg_format  = '<code>',
                                       text_description = 'Mark an invite as visible, so that it is listed on http://dashdash.com.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.show_invite))
        self.commands.add(SlashCommand(command_name     = 'new_invite',
                                       list_rank        = 8,
                                       text_arg_format  = '<username> <optional max_uses (default 1)>',
                                       text_description = 'Generate a new invite code with the given user as the sender.',
                                       validate_sender  = admin_or_helpbot_to_leaf,
                                       transform_args   = logid_token_int_or_none,
                                       action           = self.new_invite))
        self.commands.add(SlashCommand(command_name     = 'del_invite',
                                       list_rank        = 9,
                                       text_arg_format  = '<code>',
                                       text_description = 'Delete the specified invite, but onlf it it\'s unsed.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.del_invite))
        self.commands.add(SlashCommand(command_name     = 'invites_for',
                                       list_rank        = 12,
                                       text_arg_format  = '<username>',
                                       text_description = 'List all of the invites for the specified user.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.invites_for))
        self.commands.add(SlashCommand(command_name     = 'score',
                                       list_rank        = 13,
                                       text_arg_format  = '<username>',
                                       text_description = 'Queue a celery task to score the edges for the speicified user.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.score_edges))
    
    def disconnect(self, *args, **kwargs):
        other_leaves_online = False
        for lock_num_to_check in range(constants.max_leaves):
            if self.acquired_lock_num != lock_num_to_check:
                try:
                    checked_lock = g.db.is_unlocked_leaf('%s%s' % (constants.leaves_mysql_lock_name, lock_num_to_check))
                except ProgrammingError, e:
                    if e[0] == 2014:
                        g.logger.error('Caught ProgrammingError 2014 "%s" from is_unlocked_leaf(%s%s), aborting disconnect' % (e[1], constants.leaves_mysql_lock_name, lock_num_to_check))
                        return False
                    raise e
                if not checked_lock:
                    other_leaves_online = True
                    break
        if not other_leaves_online:
            connected_users = g.ectl.connected_users()
            g.logger.info('[shutdown] beginning cleanup, %d users online' % len(connected_users))
            for vinebot in FetchedVinebot.fetch_vinebots_with_participants():
                g.logger.info('[shutdown] sending %d presences for vinebot with dbid=%d' % (len(vinebot.everyone), vinebot.id))
                self.send_presences(vinebot, vinebot.everyone.intersection(connected_users), pshow='unavailable')
            for vinebot in FetchedVinebot.fetch_vinebots_with_edges():
                for edge in vinebot.edges:
                    if edge.f_user in connected_users:
                        g.logger.info('[shutdown] sending presence from user.id=%-04d to online  user.id=%-04d for edge.id=%-05d & vinebot.id=%-05d' % (edge.t_user.id, edge.f_user.id, edge.id, vinebot.id))
                        self.send_presences(vinebot, [edge.f_user], pshow='unavailable')
                    else:
                        g.logger.info('[shutdown] skipped presence from user.id=%-04d to offline user.id=%-04d for edge.id=%-05d & vinebot.id=%-05d' % (edge.t_user.id, edge.f_user.id, edge.id, vinebot.id))
            g.logger.info('[shutdown] sending  presences to admins')
            self.send_presences(None, [FetchedUser(name=admin_jid.split('@')[0]) for admin_jid in constants.admin_jids], pshow='unavailable')
            g.logger.info('[shutdown] cleanup finished, disconnecting')
        kwargs['wait'] = True    
        super(LeafComponent, self).disconnect(*args, **kwargs)
        g.db.cleanup()  # Cleanup after last scheduled task is done
    
    ##### event handlers
    def handle_start(self, event):
        def register_leaf():  # this is a function because using return makes it cleaner
            for lock_num_to_acquire in range(constants.max_leaves):
                acquired_lock = g.db.lock_leaf('%s%s' % (constants.leaves_mysql_lock_name, lock_num_to_acquire))
                if acquired_lock:
                    self.acquired_lock_num = lock_num_to_acquire
                    if lock_num_to_acquire > 0:
                        return True
                    for lock_num_to_check in range(lock_num_to_acquire + 1, constants.max_leaves):
                        checked_lock = g.db.is_unlocked_leaf('%s%s' % (constants.leaves_mysql_lock_name, lock_num_to_check))
                        if not checked_lock:
                            return True
                    return False
            return constants.max_leaves > 0  # if there are no locks to acquire, but we have to go through the whole loop to make sure we acquire one ourself
        other_leaves_online = register_leaf()
        g.use_new_logger('%s%02d' % (constants.leaves_mysql_lock_name, self.acquired_lock_num))
        if not other_leaves_online:
            connected_users = g.ectl.connected_users()
            g.logger.info('[startup] beginning initialization, %d users online' % len(connected_users))
            for vinebot in FetchedVinebot.fetch_vinebots_with_participants():
                g.logger.info('[shutdown] sending %d presences for vinebot with dbid=%d' % (len(vinebot.everyone), vinebot.id))
                self.send_presences(vinebot, vinebot.observers.intersection(connected_users), pshow='away' if vinebot.is_idle else 'available')
                self.send_presences(vinebot, vinebot.participants)
            for vinebot in FetchedVinebot.fetch_vinebots_with_edges():
                for edge in vinebot.edges:
                    if edge.f_user in connected_users:
                        g.logger.info('[startup] sending presence from user.id=%-04d to online  user.id=%-04d for edge.id=%-05d & vinebot.id=%-05d' % (edge.t_user.id, edge.f_user.id, edge.id, vinebot.id))
                        self.send_presences(vinebot, [edge.f_user], pshow=edge.t_user.status())
                    else:
                        g.logger.info('[startup] skipped presence from user.id=%-04d to offline user.id=%-04d for edge.id=%-05d & vinebot.id=%-05d' % (edge.t_user.id, edge.f_user.id, edge.id, vinebot.id))
            g.logger.info('[startup] sending  presences to admins')
            self.send_presences(None, [FetchedUser(name=admin_jid.split('@')[0]) for admin_jid in constants.admin_jids])
            g.logger.info('[startup] initialization finished')
        self.schedule(name='vinebot_idler', seconds=180, callback=self.send_idle_presences, repeat=True)
        g.logger.info('Ready')
    
    def handle_presence_available(self, presence):
        user = None
        vinebot = None
        try:
            user = FetchedUser(name=presence['from'].user)
            vinebot = FetchedVinebot(can_write=False, jiduser=presence['to'].user)
            if vinebot.is_active:
                if user in vinebot.participants:
                    self.send_presences(vinebot, vinebot.everyone, pshow='away' if vinebot.is_idle else 'available')
                elif user in vinebot.observers:
                    self.send_presences(vinebot, [user], pshow='away' if vinebot.is_idle else 'available')
            else:
                try:
                    edge_t_user = FetchedEdge(t_user=user, vinebot_id=vinebot.id)
                    self.send_presences(vinebot, [edge_t_user.f_user])
                except NotEdgeException:
                    pass
                try:
                    edge_f_user = FetchedEdge(f_user=user, vinebot_id=vinebot.id)
                    self.send_presences(vinebot, [user], edge_f_user.t_user.status())
                except NotEdgeException:
                    pass
            #LATER maybe use asymmetric presence subscriptions in XMPP to deal with this more efficiently?
            for incoming_vinebot in user.incoming_vinebots.difference([vinebot]):
                self.send_presences(incoming_vinebot, incoming_vinebot.edge_users.difference([user]))
        except NotVinebotException:
            if presence['to'].bare == constants.leaves_jid:
                self.send_presences(None, [user])
        except NotUserException:
            pass
        finally:
            if vinebot:
                vinebot.release_lock()
    
    def handle_presence_away(self, presence):
        user = None
        vinebot = None
        try:
            user = FetchedUser(name=presence['from'].user)
            vinebot = FetchedVinebot(jiduser=presence['to'].user)
            if user in vinebot.participants:  # [] if vinebot is not active
                if len(vinebot.participants) == 2:  
                    vinebot.make_writer()  
                    g.logger.info('[away] %03d participants' % len(vinebot.participants))
                    remaining_user = iter(vinebot.participants.difference([user])).next()
                    self.remove_participant(vinebot, user)  # this deactivates the vinebot
                    self.send_presences(vinebot, [user], pshow=remaining_user.status())
                    self.send_presences(vinebot, [remaining_user], pshow=presence['type'])
            else:
                try:
                    edge_t_user = FetchedEdge(t_user=user, vinebot_id=vinebot.id)
                    self.send_presences(vinebot, [edge_t_user.f_user], pshow=presence['type'])
                except NotEdgeException:
                    pass
            for incoming_vinebot in user.incoming_vinebots.difference([vinebot]):
                self.send_presences(incoming_vinebot, incoming_vinebot.edge_users.difference([user]), pshow=presence['type'])
        except NotVinebotException:
            if presence['to'].bare == constants.leaves_jid:
                self.send_presences(None, [user])
        except NotUserException:
            pass
        finally:
            if vinebot:
                vinebot.release_lock()
    
    def handle_presence_unavailable(self, presence):
        user = None
        vinebot = None
        try:
            user = FetchedUser(name=presence['from'].user)
            vinebot = FetchedVinebot(jiduser=presence['to'].user)
            if not user.is_online():
                if user in vinebot.participants:  # [] if vinebot is not active
                    vinebot.make_writer()
                    if len(vinebot.participants) > 2:
                        self.send_presences(vinebot, vinebot.everyone.difference([user]), pshow='away' if vinebot.is_idle else 'available')
                        self.remove_participant(vinebot, user)
                        self.broadcast_alert(vinebot, '%s had disconnected and left the conversation' % user.name, postponed_sender=user)
                    else:  # elif len(participants) == 2:
                        self.send_presences(vinebot, vinebot.participants.difference([user]))
                        self.send_presences(vinebot, vinebot.participants.difference([user]), pshow='unavailable')
                        self.remove_participant(vinebot, user)
                    g.logger.info('[offline] %03d participants' % len(vinebot.participants))
                elif user in vinebot.edge_users:
                    self.send_presences(vinebot, vinebot.edge_users.difference([user]), pshow='unavailable')
                for incoming_vinebot in user.incoming_vinebots.difference([vinebot]):
                    self.send_presences(incoming_vinebot, incoming_vinebot.edge_users.difference([user]), pshow='unavailable')
        except NotVinebotException:
            pass
        except NotUserException:
            pass
        finally:
            if vinebot:
                vinebot.release_lock()
    
    def handle_msg(self, msg):
        def handle_command(msg, sender, vinebot=None):
            parent_command_id, response = self.commands.handle_command(sender, msg['body'], vinebot)
            if parent_command_id is None:  # if the command has some sort of error
                command_name, arg_string = self.commands.parse_command(msg['body'])
                parent_command_id = g.db.log_command(sender, command_name, None, arg_string, vinebot=vinebot, is_valid=False)
            if vinebot:
                self.send_alert(vinebot, None, sender, response, parent_command_id=parent_command_id)
            else:
                self.send_alert(None, None, sender, response, fromjid=msg['to'], parent_command_id=parent_command_id)
        
        if msg['type'] in ('chat', 'normal'):
            vinebot = None
            try:
                user = FetchedUser(name=msg['from'].user)
                vinebot = FetchedVinebot(can_write=True, jiduser=msg['to'].user)
                if self.commands.is_command(msg['body']):
                    handle_command(msg, user, vinebot)
                else:
                    if vinebot.is_active:
                        if user in vinebot.participants:
                            self.broadcast_message(vinebot, user, vinebot.participants, msg['body'], activate=True)
                        elif user in vinebot.observers:
                            g.logger.info('[enter] %03d participants' % len(vinebot.participants))
                            self.add_participant(vinebot, user)
                            self.broadcast_alert(vinebot, '%s has joined the conversation.' % user.name)
                            self.broadcast_message(vinebot, user, vinebot.participants, msg['body'], activate=True)
                        else:
                            parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                            self.send_alert(vinebot, None, user, 'Sorry, only friends of participants can join this conversation.', parent_message_id=parent_message_id)
                    else:
                        if len(vinebot.edges) > 0 and user in vinebot.edge_users:
                            if self.activate_vinebot(vinebot, user, force_activate=(user.jid == constants.helpbot_jid)):
                                self.broadcast_message(vinebot, user, vinebot.edge_users, msg['body'])
                            else:
                                parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                                self.send_presences(vinebot, vinebot.edge_users)
                                self.send_presences(vinebot, vinebot.edge_users, pshow='unavailable')
                                self.send_alert(vinebot, None, user, 'Sorry, this user is offline.', parent_message_id=parent_message_id)
                        else:
                            parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                            self.send_alert(vinebot, None, user, 'Sorry, you can\'t send messages to this contact. Try another in your list?', parent_message_id=parent_message_id)
            except NotVinebotException:
                if user.jid in (constants.admin_jids + [constants.graph_jid, constants.helpbot_jid]):
                    if self.commands.is_command(msg['body']):
                        handle_command(msg, user)
                    else:
                        parent_message_id = g.db.log_message(user, [], msg['body'])
                        self.send_alert(None, None, user, 'Sorry, this leaf only accepts /commands from admins.', fromjid=msg['to'], parent_message_id=parent_message_id)
                else:
                    parent_message_id = g.db.log_message(user, [], msg['body'])
                    self.send_alert(None, None, user, 'Sorry, you can\'t send messages to %s. Try another contact in your list?' % msg['to'], fromjid=msg['to'], parent_message_id=parent_message_id)
            except NotUserException:
                if msg['body'].startswith(constants.session_opened_signal):
                    try:
                        self.user_session_opened(FetchedUser(name=msg['body'].replace(constants.session_opened_signal, '').strip()))
                    except NotUserException:
                        g.logger.error('Received session_opened_signal for unknown user: %s' % msg)
                else:
                    g.logger.error('Received message from unknown user: %s' % msg)
            finally:
                if vinebot:
                    vinebot.release_lock()
    
    def handle_chatstate(self, msg):
        if msg['type'] in ('chat', 'normal'):
            vinebot = None
            try:
                user = FetchedUser(name=msg['from'].user)
                vinebot = FetchedVinebot(jiduser=msg['to'].user)
                del msg['id']
                del msg['body']
                del msg['html']
                del msg['type']
                if user in vinebot.participants:
                    self.broadcast_message(vinebot, user, vinebot.everyone.difference([user]), None, msg=msg)
                elif user in vinebot.edge_users:
                    self.broadcast_message(vinebot, user, vinebot.edge_users.difference([user]), None, msg=msg)
            except NotVinebotException:
                pass
            except NotUserException:
                pass
            finally:
                if vinebot:
                    vinebot.release_lock()
    
    ##### helper functions
    def user_session_opened(self, user):
        _, result = self.sync_roster(None, user.name)
        g.logger.info('Auto sync_roster on session_opened_signal: %s' % result)
        if user.name != constants.helpbot_jid_user and user.needs_onboarding():
            try:
                helpbot = FetchedUser(name=constants.helpbot_jid_user)
                if helpbot.is_online():
                    def quiet_create_edge(username1, username2):
                        try:
                            self.create_edge(None, username1, username2)
                        except IntegrityError:
                            pass  #TODO maybe move this into create_edge
                        except ExecutionError, e:
                            g.logger.warning(e[1])
                    try:
                        invite = FetchedInvite(invitee_id=user.id)
                        quiet_create_edge(helpbot.name, invite.sender.name)
                        quiet_create_edge(invite.sender.name, helpbot.name)
                    except NotInviteException:
                        pass
                    try:
                        outgoing_edge = FetchedEdge(f_user=helpbot, t_user=user)
                    except NotEdgeException:  # Old users we're demo'ing with might not have these edges, so create them temporarily.
                        quiet_create_edge(helpbot.name, user.name)
                        quiet_create_edge(user.name, helpbot.name)
                        outgoing_edge = FetchedEdge(f_user=helpbot, t_user=user)
                    try:
                        edge_vinebot = FetchedVinebot(can_write=True, dbid=outgoing_edge.vinebot_id)
                        self.broadcast_message(edge_vinebot, None, [helpbot], '%s %s' % (constants.act_on_user_stage, user.name))
                    except NotVinebotException:
                        g.logger.warning('No vinebot found for edge %s' % outgoing_edge)
                    finally:
                        if edge_vinebot:
                            edge_vinebot.release_lock()
            except NotUserException:
                g.logger.error('%s user does not exist in the database!' % constants.helpbot_jid_user)
        if user.name in constants.watched_usernames:
            client = TwilioRestClient(constants.twilio_account_sid, constants.twilio_auth_token)
            for to_number in constants.twilio_to_numbers:
                call = client.calls.create(to=to_number,
                                           from_=constants.twilio_from_number,
                                           if_machine='Hangup',
                                           url='http://twimlets.com/holdmusic?Bucket=com.twilio.music.ambient')
            g.logger.info('[twilio] %s has signed on, and %d alert phonecall(s) have been made.' % (user.name, len(constants.twilio_to_numbers)))    
    
    def send_presences(self, vinebot, recipients, pshow='available'):
        pfrom = constants.leaves_jid
        pstatus = ''
        for recipient in recipients:
            if vinebot:
                pfrom = '%s@%s' % (vinebot.jiduser, constants.leaves_domain)
                pstatus = vinebot.get_status(recipient)
            self.sendPresence(pfrom=pfrom,
                                pto='%s@%s' % (recipient.name, constants.domain),
                                pshow=None if pshow == 'available' else pshow,
                                pstatus=pstatus)
    
    def send_probes(self, vinebot, recipients):
        pfrom = constants.leaves_jid
        if vinebot:
            pfrom = '%s@%s' % (vinebot.jiduser, constants.leaves_domain)
        for recipient in recipients:
            self.sendPresence(pfrom=pfrom,
                                pto='%s@%s' % (recipient.name, constants.domain),
                                ptype='probe')
    
    def send_idle_presences(self):
        for active_vinebot in FetchedVinebot.fetch_vinebots_with_participants():
            self.send_presences(active_vinebot, active_vinebot.observers, pshow='away' if active_vinebot.is_idle else 'available')
            self.send_presences(active_vinebot, active_vinebot.participants)
            if active_vinebot.is_idle:
                g.logger.info('[idle] %03d participants' % len(active_vinebot.participants))
    
    def build_and_send_messages(self, vinebot, sender, recipients, body, msg):
        #LATER fix html, but it's a pain with reformatting
        if msg is None:  # need to pass this for chat states
            msg = self.Message()
            msg['type'] = 'chat'
        if body and body != '':
            if sender:
                msg['body'] = '[%s] %s' % (sender.name, body)
            else:
                msg['body'] = '*** %s' % (body)
        actual_recipients = []
        for recipient in recipients:
            if not sender or sender != recipient:
                new_msg = msg.__copy__()
                new_msg['to'] = '%s@%s' % (recipient.name, constants.domain)
                new_msg['from'] = '%s@%s' % (vinebot.jiduser, constants.leaves_domain)
                new_msg.send()
                actual_recipients.append(recipient)
                if body and body != '' and sender:
                    g.logger.info('[message] received')
        return actual_recipients
    
    def broadcast_message(self, vinebot, sender, current_recipients, body, msg=None, parent_command_id=None, activate=False):
        if body and body != '' and sender:  # Every time we broadcast a message FROM A USER, check for old suspended messages that we might want to also send
            suspended_messages = vinebot.get_suspended_messages()
            current_recipients_copy = set(current_recipients).copy()
            for suspended_message_id, suspended_message_body, suspended_message_recipients in suspended_messages:
                # remember that suspended_message_recipients exludes the sender...
                # ...so we can re add that person to the group that will receive the sender's message here:
                suspended_recipients = suspended_message_recipients.union(current_recipients_copy)
                # ...and also avoid sending that person the trigger message here, since it was possibly sent without the second sender knowing the first sender was present:
                current_recipients = current_recipients.intersection(suspended_message_recipients)
                actual_suspended_recipients = self.build_and_send_messages(vinebot, None, suspended_recipients, suspended_message_body, None)
                g.db.unsuspend_message(suspended_message_id, actual_suspended_recipients)
        actual_current_recipients = self.build_and_send_messages(vinebot, sender, current_recipients, body, msg)
        g.db.log_message(sender, actual_current_recipients, body, vinebot=vinebot, parent_command_id=parent_command_id)
        if body and body != '':
            if sender:
                g.logger.info('[message] sent to %03d recipients' % len(actual_current_recipients))
            if activate and not vinebot.is_idle:
                self.send_presences(vinebot, vinebot.everyone)
    
    def broadcast_alert(self, vinebot, body, parent_command_id=None, activate=False, postponed_sender=None):
        if postponed_sender is None:
            self.broadcast_message(vinebot, None, vinebot.participants, body, parent_command_id=parent_command_id, activate=activate)
        else:
            g.db.suspend_message(vinebot.participants.difference([postponed_sender]), body, vinebot, parent_command_id=parent_command_id)
    
    def send_alert(self, vinebot, sender, recipient, body, prefix='/**', fromjid=None, parent_message_id=None, parent_command_id=None):
        if body == '':
            return
        elif body.startswith('Sorry, '):
            g.logger.info('[error] %s' % body)
        msg = self.Message()
        msg['type'] = 'chat'
        msg['body'] = '%s %s' % (prefix, body)
        msg['from'] = '%s@%s' % (vinebot.jiduser, constants.leaves_domain) if vinebot else fromjid
        msg['to'] = recipient.jid
        msg.send()
        g.db.log_message(sender, [recipient], body, vinebot=vinebot, parent_message_id=parent_message_id, parent_command_id=parent_command_id)
        if parent_message_id is None and parent_command_id is None:
            g.logger.error('Call to send_alert with no parent. msg=%s' % (body, msg))
    
    def activate_vinebot(self, vinebot, activater, force_activate=False):
        if vinebot.is_active:
            g.logger.error('Called activate_vinebot for id=%d when vinebot was already active.' % vinebot.id)
            return True
        if len(vinebot.edges) == 0:
            raise Exception, 'Called activate_vinebot for id=%d when vinebot was not active and had no edges.' % vinebot.id
        user1, user2 = vinebot.edge_users
        both_users_online = user1.is_online() and user2.is_online()
        if force_activate or vinebot.check_recent_activity(excluded_user=activater):    
            g.logger.info('[activate] %03d participants' % len(vinebot.participants))
            self.send_presences(vinebot, [user1])  # just activated vinebots are never idle
            self.send_presences(vinebot, [user2])
            if both_users_online:
                self.add_participant(vinebot, user1)
                self.add_participant(vinebot, user2)
        else:
            g.logger.info('[activate] primed for %03d participants' % len(vinebot.participants))
        return both_users_online  # As long as both users are online, return true, even if no participants were *actually* added
    
    def add_participant(self, vinebot, user):
        g.logger.info('[add_participant] %03d participants' % len(vinebot.participants))
        old_participants = vinebot.participants.copy()  # makes a shallow copy, which is good, because it saves queries on User.friends 
        vinebot.add_participant(user)
        if len(vinebot.participants) < 2:
            pass  # this is the first participant, so assume that we're adding another one in a second
        elif len(vinebot.participants) == 2:
            vinebot.update_rosters(set([]), vinebot.participants)
            self.send_presences(vinebot, vinebot.observers)  # participants get the proper presence in activate_vinebot() above
        elif len(vinebot.participants) == 3:
            vinebot.update_rosters(old_participants, vinebot.participants)
            if len(vinebot.edges) > 0:
                new_vinebot = None
                try:
                    new_vinebot = InsertedVinebot(old_vinebot=vinebot)
                    self.send_presences(new_vinebot, new_vinebot.everyone)  # for group conversations, presence can always be available
                finally:
                    if new_vinebot:
                        new_vinebot.release_lock()
            self.send_presences(vinebot, vinebot.everyone)
        else:
            # there's no way this vinebot can still have edges associated with it
            vinebot.update_rosters(old_participants, vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
    
    def remove_participant(self, vinebot, user):
        g.logger.info('[remove_participant] %03d participants' % len(vinebot.participants))
        old_participants = vinebot.participants.copy()
        vinebot.remove_participant(user)
        if len(vinebot.participants) == 1:
            other_user = iter(vinebot.participants.difference([user])).next()
            vinebot.remove_participant(other_user)
            self.send_presences(vinebot, vinebot.observers)
            self.send_presences(vinebot, vinebot.observers, pshow='unavailable')
            if len(vinebot.edges) > 0:
                # Get the active vinebots that have only these two participants, but not the ones that already have edges!
                active_vinebots = FetchedVinebot.fetch_vinebots_with_participants(participants=old_participants)
                edgeless_active_vinebots = filter(lambda active_vinebot: len(active_vinebot.edges) == 0, active_vinebots)
                if len(edgeless_active_vinebots) > 0:  # These two users still have an active vinebot, so we need to transfer their edge(s)
                    for edge in vinebot.edges:
                        edge.change_vinebot(edgeless_active_vinebots[0])  # It doesn't matter which active vinebot they get transferred to though
                    vinebot.update_rosters(old_participants, set([]))
                    vinebot.delete()
                else:
                    if len(vinebot.edges) == 1:
                        vinebot.update_rosters(old_participants, set([]), protected_participants=set([iter(vinebot.edges).next().f_user]))
                    else:#if len(vinebot.edges) == 2:
                        vinebot.update_rosters(old_participants, set([]), protected_participants=vinebot.edge_users)
                    self.send_probes(vinebot, old_participants)  # revert to the statuses of the users, not of the conversation
                for active_vinebot in active_vinebots:  # No matter what, we still need to release these locks
                    active_vinebot.release_lock()
            else:
                vinebot.update_rosters(old_participants, set([]))
                vinebot.delete()
        elif len(vinebot.participants) == 2:
            vinebot.update_rosters(old_participants, vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
            if len(vinebot.edges) == 0:  # Only move edges to this vinebot if it doesn't already have any
                user1, user2 = vinebot.participants
                try:
                    try:
                        edge = FetchedEdge(f_user=user2, t_user=user1)
                        old_vinebot = FetchedVinebot(can_write=True, dbid=edge.vinebot_id)
                    except NotEdgeException:
                        try:
                            edge = FetchedEdge(f_user=user1, t_user=user2)
                            old_vinebot = FetchedVinebot(can_write=True, dbid=edge.vinebot_id)
                        except NotEdgeException:
                            old_vinebot = None
                    if old_vinebot and not old_vinebot.is_active:
                        old_vinebot.delete(new_vinebot=vinebot)
                finally:
                    if old_vinebot:
                        old_vinebot.release_lock()
        else:
            # this conversation had more than three people to start, so nothing changes if we remove someone
            vinebot.update_rosters(old_participants, vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
    
    def cleanup_and_delete_edge(self, edge):
        vinebot = None
        try:
            vinebot = FetchedVinebot(can_write=True, dbid=edge.vinebot_id)
            try:
                FetchedEdge(f_user=edge.t_user, t_user=edge.f_user)  # reverse_edge
                edge.f_user.note_visible_active_vinebots()
                edge.t_user.note_visible_active_vinebots()
                edge.delete(vinebot)
                for other_vinebot in edge.f_user.calc_active_vinebot_diff().difference([vinebot]):
                    try:
                        other_vinebot.remove_from_roster_of(edge.f_user)
                    finally:
                        other_vinebot.release_lock()
                for other_vinebot in edge.t_user.calc_active_vinebot_diff().difference([vinebot]):
                    try:
                        other_vinebot.remove_from_roster_of(edge.t_user)
                    finally:
                        other_vinebot.release_lock()
            except NotEdgeException:
                edge.delete(vinebot)
                if not vinebot.is_active:
                    vinebot.delete()
            if not vinebot.is_active:
                vinebot.remove_from_roster_of(edge.f_user)
        finally:
            if vinebot:
                vinebot.release_lock()
    
    ##### user /commands
    def debug_vinebot(self, parent_command_id, vinebot, user):
        self.send_alert(vinebot, None, user, 'dbid = %d\n%s\n%s\nparticipants = %s\nedge_users = %s' % (vinebot.id, vinebot.jiduser, vinebot.last_active_text, vinebot.participants, vinebot.edge_users), parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def user_joined(self, parent_command_id, vinebot, user):
        send_now = len(vinebot.participants) < 3  # we still want to tell small conversations about new participants
        if send_now:
            alert_msg_first = '%s has joined the conversation, but didn\'t want to interrupt. ' % user.name
        else:
            alert_msg_first = '%s had joined the conversation, but hadn\'t wanted to interrupt and didn\'t receive the current message. ' % user.name
        if vinebot.topic is not None:
            alert_msg = '%sThe current topic is:\n\t%s' % (alert_msg_first, vinebot.topic)
        else:
            alert_msg = '%sNo one has set the topic.' % alert_msg_first
        try:    
            g.logger.info('[join] %03d participants' % len(vinebot.participants))
            self.add_participant(vinebot, user)
        except IntegrityError, e:
            if e[0] == 1062:  # "Duplicate entry '48-16' for key 'PRIMARY'"
                raise ExecutionError, (parent_command_id, 'You can\'t join a conversation you\'re already in!')
            raise e
        self.broadcast_alert(vinebot, alert_msg, parent_command_id=parent_command_id, activate=True, postponed_sender=(None if send_now else user))
        return parent_command_id, '' if send_now else 'You\'ve joined the conversation, but no one has been notified yet.'
    
    def user_left(self, parent_command_id, vinebot, user):    
        g.logger.info('[left] %03d participants' % len(vinebot.participants))
        self.remove_participant(vinebot, user)
        self.broadcast_alert(vinebot, '%s has left the conversation.' % user.name, parent_command_id=parent_command_id)
        return parent_command_id, 'You left the conversation.'  # do this even if inactive, so users don't know if the other left
    
    def invite_user(self, parent_command_id, vinebot, inviter, invitee):
        try:
            invitee = FetchedUser(name=invitee)
        except NotUserException:
            raise ExecutionError, (parent_command_id, '%s isn\'t yet using Dashdash. Perhaps you meant "/tweet_invite %s"?' % (invitee, invitee))
        if inviter == invitee:
            raise ExecutionError, (parent_command_id, 'you can\'t invite yourself.')
        if invitee.name in constants.protected_users:
            raise ExecutionError, (parent_command_id, 'you can\'t invite administrator accounts.')
        if invitee in vinebot.participants:
            raise ExecutionError, (parent_command_id, '%s is already in this conversation.' % invitee.name)
        if not invitee.is_online():
            raise ExecutionError, (parent_command_id, '%s is offline and can\'t be invited.' % invitee.name)
        g.logger.info('[invite] %03d participants' % len(vinebot.participants))
        if not vinebot.is_active:
            self.activate_vinebot(vinebot, inviter, force_activate=True)
        if vinebot.topic is not None:
            alert_msg = '%s has invited %s to the conversation. The current topic is:\n\t%s' % (inviter.name, invitee.name, vinebot.topic)
        else:
            alert_msg = '%s has invited %s to the conversation. No one has set the topic.' % (inviter.name, invitee.name)
        self.add_participant(vinebot, invitee)
        self.broadcast_alert(vinebot, alert_msg, parent_command_id=parent_command_id, activate=True)
        return parent_command_id, ''
    
    def kick_user(self, parent_command_id, vinebot, kicker, kickee):
        try:
            kickee = FetchedUser(name=kickee)
        except NotUserException:
            raise ExecutionError, (parent_command_id, '%s isn\'t a participant in the conversation, so can\'t be kicked.' % kickee)
        if kicker == kickee:
            raise ExecutionError, (parent_command_id, 'you can\'t kick yourself. Maybe you meant /leave?')
        if kickee.name in constants.protected_users:
            raise ExecutionError, (parent_command_id, 'you can\'t kick administrator accounts.')
        if len(vinebot.participants) == 2:
            raise ExecutionError, (parent_command_id, 'you can\'t kick someone if it\'s just the two of you. Maybe you meant /leave?')
        if not kickee in vinebot.participants:
            raise ExecutionError, (parent_command_id, '%s isn\'t a participant in the conversation, so can\'t be kicked.' % kickee.name)
        g.logger.info('[kick] %03d participants' % len(vinebot.participants))
        self.remove_participant(vinebot, kickee)
        self.broadcast_alert(vinebot, '%s was kicked from the conversation by %s.' % (kickee.name, kicker.name), parent_command_id=parent_command_id)
        self.send_alert(vinebot, None, kickee, '%s has kicked you from the conversation.' % kicker.name, parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def block_user(self, parent_command_id, vinebot, blocker, blockee):
        try:
            blockee = FetchedUser(name=blockee)
        except NotUserException:
            raise ExecutionError, (parent_command_id, '%s isn\'t a Dashdash user, so can\'t be blocked.' % blockee)
        if blocker == blockee:
            raise ExecutionError, (parent_command_id, 'you can\'t block yourself.')
        if blockee.name in constants.protected_users:
            raise ExecutionError, (parent_command_id, 'you can\'t block administrator accounts.')
        if blocker.block(blockee):
            if celery_tasks:
                celery_tasks.score_edges.delay(blockee.id)
                g.logger.info('[block] success, celery task queued')
            else:
                g.logger.info('[block] success, no celery task queued')
            return parent_command_id, 'You blocked %s.' % blockee.name
        else:
            g.logger.info('[block] duplicate')
            raise ExecutionError, (parent_command_id, '%s was already blocked.' % blockee.name)
    
    def unblock_user(self, parent_command_id, vinebot, unblocker, unblockee):
        try:
            unblockee = FetchedUser(name=unblockee)
        except NotUserException:
            raise ExecutionError, (parent_command_id, '%s isn\'t a Dashdash user, so can\'t be unblocked.' % unblockee)
        if unblocker == unblockee:
            raise ExecutionError, (parent_command_id, 'you can\'t unblock yourself.')
        if unblockee.name in constants.protected_users:
            raise ExecutionError, (parent_command_id, 'you can\'t unblock administrator accounts.')
        if unblocker.unblock(unblockee):
            if celery_tasks:
                celery_tasks.score_edges.delay(unblockee.id)
                g.logger.info('[unblock] success, celery task queued')
            else:
                g.logger.info('[unblock] success, no celery task queued')
            return parent_command_id, 'You unblocked %s.' % unblockee.name
        else:
            g.logger.info('[unblock] missing')
            raise ExecutionError, (parent_command_id, '%s wasn\'t blocked.' % unblockee.name)
    
    def list_blockees(self, parent_command_id, vinebot, user):
        blockees = user.blockees()
        if len(blockees) > 0:
            output = ''.join(['\t%s\n' % blockee.name for blockee in blockees]).strip('\n')
            return parent_command_id, 'You\'ve blocked %d user%s:\n%s' % (len(blockees), 's' if len(blockees) > 1 else '', output)
        else:
            return parent_command_id, 'You don\'t currently have any users blocked.'
    
    def list_participants(self, parent_command_id, vinebot, user):
        usernames = [participant.name for participant in vinebot.participants.difference([user])]
        if len(vinebot.participants) == 0:
            return parent_command_id, 'This conversation isn\'t yet active, so there are no participants.'
        if user in vinebot.participants:
            usernames.append(PRONOUN)
        if vinebot.topic is not None:
            return parent_command_id, 'The current participants are:\n%s\nThe current topic is:\n\t%s' % (
                    ''.join(['\t%s\n' % username for username in usernames]).strip('\n'), vinebot.topic)
        else:
            return parent_command_id, 'The current participants are:\n%s\nNo one has set the topic.' % (
                    ''.join(['\t%s\n' % username for username in usernames]).strip('\n'))
    
    def list_observers(self, parent_command_id, vinebot, user):
        connected_users = g.ectl.connected_users()
        observers = list(vinebot.observers.intersection(connected_users))
        observer_string = ''.join(['\t%s\n' % observer.name for observer in observers]).strip('\n')
        if vinebot.is_active:
            if len(observers) > 1:
                response = 'These users are online and can see this conversation:\n' + observer_string
            elif len(observers) == 1:
                response = '%s is online and can see this conversation.' % observers[0].name
            else:
                response = 'There are no users online that can see this conversaton.'
        else:
            if len(observers) > 1:
                response = 'If this conversation were active, then these online users would see it:\n' + observer_string
            elif len(observers) == 1:
                response = 'If this conversation were active, then %s would see it.' % observers[0].name
            else:
                response = 'There are no users online that can see this conversaton.'
        return parent_command_id, response
    
    def whisper_msg(self, parent_command_id, vinebot, sender, recipient, body):
        try:
            recipient = FetchedUser(name=recipient)
        except NotUserException:
            raise ExecutionError, (parent_command_id, 'you can\'t whisper to someone who isn\'t a participant in this conversation.')
        if recipient == sender:
            raise ExecutionError, (parent_command_id, 'you can\'t whisper to yourself.')
        if recipient not in vinebot.participants and recipient.jid not in constants.admin_jids:
            raise ExecutionError, (parent_command_id, 'you can\'t whisper to someone who isn\'t a participant in this conversation.')
        self.send_alert(vinebot, sender, recipient, body, prefix='[%s, whispering]' % sender.name, parent_command_id=parent_command_id)
        g.logger.info('[whisper] %03d participants' % len(vinebot.participants))
        if len(vinebot.participants) == 2:
            return parent_command_id, 'You whispered to %s, but it\'s just the two of you here so no one would have heard you anyway...' % recipient.name
        else:
            return parent_command_id, 'You whispered to %s, and no one noticed!' % recipient.name
    
    def set_topic(self, parent_command_id, vinebot, sender, topic):
        if topic and len(topic) > 100:
            raise ExecutionError, (parent_command_id, 'topics can\'t be longer than 100 characters, and this was %d characters.' % len(topic))
        else:
            vinebot.topic = topic  # using a fancy custom setter!
            if vinebot.is_active or (vinebot.topic is not None and self.activate_vinebot(vinebot, sender)):  # short-circuit prevents unnecessary vinebot activation
                if vinebot.topic is not None:
                    body = '%s has set the topic of the conversation:\n\t%s' % (sender.name, vinebot.topic)
                else:
                    body = '%s has cleared the topic of conversation.' % sender.name
                if vinebot.is_active:
                    self.send_presences(vinebot, vinebot.everyone)
                    self.broadcast_alert(vinebot, body, parent_command_id=parent_command_id, activate=True)
                else:  # same as broadcast_alert, but use vinebot.edge_users since there are no participants yet
                    self.send_presences(vinebot, vinebot.edge_users)
                    self.broadcast_message(vinebot, None, vinebot.edge_users, body, parent_command_id=parent_command_id, activate=True)
            else:
                if vinebot.topic is not None:
                    modified = 'set'
                else:
                    modified = 'cleared'
                recipient = vinebot.edge_users.difference([sender]).pop()
                if recipient.is_online():
                    notified = '%s wasn\'t' % recipient.name
                else:
                    notified = '%s is offline so won\'t be' % recipient.name
                body = 'You\'ve %s the topic of conversation, but %s notified.' % (modified, notified)
                self.send_presences(vinebot, [recipient], pshow=sender.status())
                self.send_presences(vinebot, [sender], pshow=recipient.status())
                self.send_alert(vinebot, None, sender, body, parent_command_id=parent_command_id)
        g.logger.info('[topic] %03d participants' % len(vinebot.participants))
        return parent_command_id, ''
    
    def tweet_invite(self, parent_command_id, vinebot, sender, twitter_username, tweet_body):
        max_tweet_body = 140 - (len(twitter_username) + len(' ') + len(' ') + CURRENT_TCO_LENGTH)
        if tweet_body:
            tweet_body = tweet_body.strip()
            if tweet_body and len(tweet_body) > max_tweet_body:
                raise ExecutionError, (parent_command_id, 'The tweet you specified was %d characters, and can\'t be longer than %d characters. Try again?' % (len(tweet_body), max_tweet_body))    
        else:
            if vinebot.is_active:
                other_participants = list(vinebot.participants.difference([sender]))
            else:
                other_participants = list(vinebot.edge_users.difference([sender]))
            tweet_first = 'Come chat with me'
            tweet_last =  ' and @%s on @DashdashInc!' % other_participants.pop().name
            tweet_extra = ' It\'s like a cocktail party, but on the Internet:'
            for other_participant in other_participants:
                tweet_body = tweet_first + tweet_last
                tweet_more = ', @%s' % other_participant.name
                if len(tweet_body + tweet_more) > max_tweet_body:
                    break
                else:
                    tweet_first += ', @%s' % other_participant.name
            if len(tweet_first + tweet_last + tweet_extra) > max_tweet_body:
                tweet_body = tweet_first + tweet_last
            else:
                tweet_body = tweet_first + tweet_last + tweet_extra
        try:
            new_user = InsertedUser(twitter_username, None, should_register=False)
        except NotUserException:
            raise ExecutionError, (parent_command_id, 'Twitter usernames only contain letters, numbers, and underscores.')
        except IntegrityError:
            old_user = FetchedUser(name=twitter_username)
            if old_user.is_online():
                raise ExecutionError, (parent_command_id, '%s is already using Dashdash. Try /invite-ing them to this conversation?' % old_user.name)
            else:
                raise ExecutionError, (parent_command_id, '%s is already using Dashdash, but is offline right now.' % old_user.name)
        try:
            invite = InsertedInvite(sender)
            invite.use(new_user)
        except IntegrityError:
            pass  # We don't need to worry if the user already has an invite
        tweet = '@%s %s %s' % (new_user.name, tweet_body, invite.url)
        try:
            api = twitter.Api(consumer_key=constants.twitter_consumer_key, consumer_secret=constants.twitter_consumer_secret,
                              access_token_key=sender.twitter_token, access_token_secret=sender.twitter_secret)
            status = api.PostUpdate(tweet)
            alert_msg = '%s has invited %s to the conversation on Twitter.\n\thttp://twitter.com/%s/status/%s' % (sender.name, twitter_username, sender.name, status.id)
            if not vinebot.is_active:
                self.activate_vinebot(vinebot, sender, force_activate=True)
            self.broadcast_alert(vinebot, alert_msg, parent_command_id=parent_command_id, activate=True)
            g.logger.info('[tweet_invite] success')
            return parent_command_id, ''
        except UnicodeDecodeError:
            g.logger.info('[tweet_invite] unicode error')
            return parent_command_id, 'Something went wrong encoding your tweet. Perhaps it contains non-ASCII characters?' + \
                                      'Here\'s what would have been tweeted:\n\t%s' % tweet
        except Exception, e:
            g.logger.warn('Error posting tweet from %s: %s' % (sender, e))
            g.logger.info('[tweet_invite] other error')
            return parent_command_id, 'Something went wrong posting to Twitter - try signing in again at http://%s.\n' % constants.domain + \
                                      'Here\'s what would have been tweeted:\n\t%s' % tweet
    
    def me_action_message(self, parent_command_id, vinebot, sender, action_message):
        if action_message is None:
            raise ExecutionError, (parent_command_id, 'you must specify an action_message.')
        if not vinebot.is_active:
            self.activate_vinebot(vinebot, sender, force_activate=True)
        self.broadcast_alert(vinebot, "%s %s" % (sender.name, action_message), parent_command_id=parent_command_id, activate=True)
        g.logger.info('[me] %03d participants' % len(vinebot.participants))
        return parent_command_id, ''
    
    def party(self, parent_command_id, vinebot, sender, usernames, topic):
        suggestion = '\n\nCopy-paste your message and try again?'
        if not re.match('^(\w{1,15})(,(\w{1,15}))*$', usernames):
            raise ExecutionError, (parent_command_id, 'the list of usernames can\'t be empty and must be formatted like this: user_1,user_2,user_3. Copy-paste your message and try again?%s' % suggestion)
        if topic[:7] != '/topic ':
            raise ExecutionError, (parent_command_id, 'you need to separate the topic from the usernames with " /topic ", and remember the username list can\'t contain spaces.%s' % suggestion)
        topic = topic[7:].strip()
        if topic == '':
            raise ExecutionError, (parent_command_id, 'you need to specify a topic for the conversation.%s' % suggestion)
        connected_users = g.ectl.connected_users().difference(constants.protected_users)
        recipients = []
        offline_usernames = []
        for username in set(usernames.split(',')).difference(constants.protected_users + [constants.echo_user, constants.helpbot_jid_user]):
            if username == sender.name:
                raise ExecutionError, (parent_command_id, 'you can\'t invite yourself!%s' % suggestion)
            try:
                recipient = FetchedUser(name=username)
                if recipient in connected_users:
                    recipients.append(recipient)
                else:
                    offline_usernames.append(recipient.name)
            except NotUserException:
                raise ExecutionError, (parent_command_id, '%s isn\'t a registered user.%s' % (username, suggestion))
        if len(recipients) == 0:
            raise ExecutionError, (parent_command_id, 'at least some of the users you invite must be online.%s' % suggestion)
        elif len(recipients) == 1:
            others = ''
        elif len(recipients) == 2:
            others = ' and 1 other'
        else: # len(recipients) > 2
            others = ' and %d others' % (len(recipients) - 1)
        invite_body = '%s has invited you%s to talk about:\n\t%s\nRespond to join the conversation!' % (sender.name, others, topic)
        vinebot = None
        try:
            vinebot = InsertedVinebot()
            vinebot.topic = topic
            self.add_participant(vinebot, sender)
            vinebot.add_to_roster_of(sender, topic)
            for recipient in recipients:
                vinebot.add_to_roster_of(recipient, topic)
            self.send_presences(vinebot, [sender] + recipients)
            self.send_alert(vinebot, sender, sender, 'Waiting for people to join...', parent_command_id=parent_command_id)
            self.broadcast_message(vinebot, None, recipients, invite_body, parent_command_id=parent_command_id)
        finally:
            if vinebot:
                vinebot.release_lock()
        g.logger.info('[party] %d online recipients, %d offline recipients' % (len(recipients), len(offline_usernames)))
        offline_body = ''
        if len(offline_usernames) > 0:
            offline_body = '\nThe following %d user%s offline:\n\t%s' % (len(offline_usernames),
                                                                      ' was' if len(offline_usernames) == 1 else 's were',
                                                                      '\n\t'.join(offline_usernames))
        return parent_command_id, 'You invited %d user%s to a new conversation!%s' % (len(recipients), '' if len(recipients) == 1 else 's', offline_body)
    
    def online_contacts(self, parent_command_id, vinebot, sender):
        connected_users = g.ectl.connected_users()
        contacts = set(list(sender.friends) + [vinebot.edge_users.difference([sender]).pop() for vinebot in sender.outgoing_vinebots])
        online_contacts = set([contact.name for contact in contacts.intersection(connected_users)])
        online_contacts = online_contacts.difference(constants.protected_users)
        if len(online_contacts) == 0:
            return parent_command_id, 'You have no online contacts.'
        return parent_command_id, 'You have %d online contact%s:\n\t%s' % (len(online_contacts), '' if len(online_contacts) == 1 else 's', ','.join(online_contacts))
    
    ##### admin /commands
    def create_user(self, parent_command_id, username, password):
        try:
            InsertedUser(username, password)
        except NotUserException:
            raise ExecutionError, (parent_command_id, 'usernames can only contain letters, numbers, and underscores.')
        except IntegrityError:
            raise ExecutionError, (parent_command_id, 'there was an IntegrityError - are you sure the user doesn\'t already exist?')
        return parent_command_id, None
    
    def delete_user(self, parent_command_id, username):
        try:
            user = FetchedUser(can_write=True, name=username)
            if user.is_protected:
                raise ExecutionError, (parent_command_id, 'this user is protected and cannot be deleted/deactivated.')
            for vinebot in user.active_vinebots:
                try:
                    self.remove_participant(vinebot, user)
                finally:
                    vinebot.release_lock()
            for edge in FetchedEdge.fetch_edges_for_user(user):
                self.cleanup_and_delete_edge(edge)
            user.delete()
        except IntegrityError:
            raise ExecutionError, (parent_command_id, 'there was an IntegrityError - are you sure the user already exists?')
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, e)
        return parent_command_id, None
    
    def purge_user(self, parent_command_id, username, confirmation):
        if confirmation != '--force':
            raise ExecutionError, (parent_command_id, 'are you sure you want to do that? If so, please use \'--force\', but purging users with many messages may hose the database.')
        try:
            user = FetchedUser(can_write=True, name=username)
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this user exists?')
        self.delete_user(parent_command_id, username)
        user.purge()
        return parent_command_id, None
    
    def create_edge(self, parent_command_id, from_username, to_username):
        if from_username == to_username:
            raise ExecutionError, (parent_command_id, 'users cannot have edges to themselves.')
        try:
            f_user = FetchedUser(can_write=True, name=from_username)
            t_user = FetchedUser(can_write=True, name=to_username)
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, e)
        try:
            FetchedEdge(f_user=f_user, t_user=t_user)
            raise ExecutionError, (parent_command_id, '%s and %s already have a directed edge between them.' % (f_user.name, t_user.name))
        except NotEdgeException:  # no edge was found in the database, so we can continue
            pass
        vinebot = None
        try:
            try:
                reverse_edge = FetchedEdge(f_user=t_user, t_user=f_user)
                vinebot = FetchedVinebot(can_write=True, dbid=reverse_edge.vinebot_id)#, edges=[reverse_edge])
                f_user.note_visible_active_vinebots()
                t_user.note_visible_active_vinebots()
                InsertedEdge(f_user, t_user, vinebot=vinebot)
                for other_vinebot in f_user.calc_active_vinebot_diff().difference([vinebot]):
                    try:
                        other_vinebot.add_to_roster_of(f_user, other_vinebot.get_nick(f_user))
                    finally:
                        other_vinebot.release_lock()
                    self.send_presences(other_vinebot, [f_user])
                for other_vinebot in t_user.calc_active_vinebot_diff().difference([vinebot]):
                    try:
                        other_vinebot.add_to_roster_of(t_user, other_vinebot.get_nick(t_user))
                    finally:
                        other_vinebot.release_lock()
                    self.send_presences(other_vinebot, [t_user])
            except NotEdgeException:
                vinebot = InsertedVinebot()
                InsertedEdge(f_user, t_user, vinebot=vinebot)
            self.send_presences(vinebot, [f_user], pshow=t_user.status())
            vinebot.add_to_roster_of(f_user, vinebot.get_nick(f_user))
        finally:
            if vinebot:
                vinebot.release_lock()
        return parent_command_id, '%s and %s now have a directed edge between them.' % (f_user.name, t_user.name)
    
    def delete_edge(self, parent_command_id, from_username, to_username):
        try:
            f_user = FetchedUser(can_write=True, name=from_username)  # these users will be used in cleanup_and_delete_edge, so need can_write=True
            t_user = FetchedUser(can_write=True, name=to_username)
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, e)
        try:
            edge = FetchedEdge(f_user=f_user, t_user=t_user)
        except NotEdgeException:
            raise ExecutionError, (parent_command_id, '%s and %s do not have a directed edge between them.' % (f_user.name, t_user.name))
        self.cleanup_and_delete_edge(edge)
        return parent_command_id, '%s and %s no longer have a directed edge between them.' % (f_user.name, t_user.name)
    
    def sync_roster(self, parent_command_id, username):
        # RosterItem classes encapsulate data and facilitate comparisons for computing set differences.
        # We don't want the set differences to be symmetric, since there's no need to delete incorrect
        # items that we're just going to add with a new group/nickname a moment later.
        class RosterItem(object):
            def __init__(self, viewer, jiduser, group, nick):
                self._viewer = viewer
                self._jiduser = jiduser
                self._group = group
                self._nick = nick
            def add_to_roster(self):
                g.ectl.add_rosteritem(self._viewer.name, self._jiduser, self._group, self._nick)
                return 'Adding   rosteritem %s with group \'%s\' and nick \'%s\'' % (self._jiduser, self._group, self._nick)
            def delete_from_roster(self):
                g.ectl.delete_rosteritem(self._viewer.name, self._jiduser)
                return 'Deleting rosteritem %s with group \'%s\' and nick \'%s\'' % (self._jiduser, self._group, self._nick)
            def __hash__(self):
                return hash('rosteritem.%s' % self._jiduser)
            def __eq__(self, other):
                if not isinstance(other, RosterItem):
                    return False
                return (self._jiduser == other._jiduser and self._group == other._group and self._nick == other._nick)
            def __ne__(self, other):
                return not self.__eq__(other)
        class ExpectedRosterItem(RosterItem):
            def __init__(self, viewer, vinebot):
                super(ExpectedRosterItem, self).__init__(viewer, vinebot.jiduser, vinebot.group, vinebot.get_nick(viewer))
            def __eq__(self, other):
                if isinstance(other, ActualRosterItem):  # when figuring out which rosteritems to delete, we only care about jids
                    return (self._jiduser == other._jiduser)
                return super(ExpectedRosterItem, self).__eq__(self, other)
        class ActualRosterItem(RosterItem):
            pass  # we only need this class for type checking in ExpectedRosterItem.__eq__
        try:
            user = FetchedUser(name=username)
            user_roster = user.roster()
            expected_vinebots = frozenset([]).union(user.active_vinebots) \
                                             .union(user.observed_vinebots) \
                                             .union(user.symmetric_vinebots) \
                                             .union(user.outgoing_vinebots)
            expected_rosteritems = frozenset([ExpectedRosterItem(user, expected                       ) for expected in expected_vinebots])
            actual_rosteritems   = frozenset([ActualRosterItem(  user, actual[0], actual[1], actual[2]) for actual   in user_roster])
            errors = []
            for actual_rosteritem in actual_rosteritems.difference(expected_rosteritems):
                errors.append(actual_rosteritem.delete_from_roster())
            for expected_rosteritem in expected_rosteritems.difference(actual_rosteritems):
                errors.append(expected_rosteritem.add_to_roster())
            if errors:
                return parent_command_id, '%s needed the following roster updates:\n\t%s' % (user.name, '\n\t'.join(errors))
            else:
                return parent_command_id, '%s needed no roster updates.' % user.name
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this user exists?')
    
    def list_edges(self, parent_command_id, username):
        try:
            user = FetchedUser(name=username)
            edges = FetchedEdge.fetch_edges_for_user(user)
            def has_reverse(edge):
                for other_edge in edges:
                    if (edge.f_user == other_edge.t_user) and (edge.t_user == other_edge.f_user):
                        return True
                return False
            symmetric = filter(has_reverse, edges)
            asymmetric = edges.difference(symmetric)
            incoming = filter(lambda edge: edge.t_user == user, asymmetric)
            outgoing = filter(lambda edge: edge.f_user == user, asymmetric)
            if (len(outgoing) + len(incoming) + len(symmetric)) != len(edges):
                raise ExecutionError, (parent_command_id, 'something bad happened to the edge set calculations for %s' % user)
            output = '%d %s has:' % (user.id, user.name)
            output += self._format_list_output(user.friends,
                                               'friends (symmetric edges)',
                                               lambda friend: '%d %s' % (friend.id, friend.name))
            output += self._format_list_output(incoming,
                                               'incoming edges',
                                               lambda edge: '%d %s' % (edge.f_user.id, edge.f_user.name))
            output += self._format_list_output(outgoing,
                                               'outgoing edges',
                                               lambda edge: '%d %s' % (edge.t_user.id, edge.t_user.name))
            return parent_command_id, output
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this user exists?')
    
    def hide_invite(self, parent_command_id, invite_code):
        try:
            invite = FetchedInvite(code=invite_code)
            if not invite.visible:
                return parent_command_id, '%s\'s invite %s was already hidden.' % (invite.sender.name, invite.code)
            invite.hide()
            return parent_command_id, '%s\'s invite %s has been hidden.' % (invite.sender.name, invite.code)
        except NotInviteException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this invite exists?')
        except ImmutableInviteException, e:
            raise ExecutionError, (parent_command_id, 'this invite has been used, so you can\'t hide it.')
    
    def show_invite(self, parent_command_id, invite_code):
        try:
            invite = FetchedInvite(code=invite_code)
            if invite.visible:
                return parent_command_id, '%s\'s invite %s was already visible.' % (invite.sender.name, invite.code)
            invite.show()
            return parent_command_id, '%s\'s invite %s has been set to visible.' % (invite.sender.name, invite.code)
        except NotInviteException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this invite exists?')
        except ImmutableInviteException, e:
            raise ExecutionError, (parent_command_id, 'this invite has been used, so is already visible.')
    
    def new_invite(self, parent_command_id, username, max_uses=1):
        try:
            sender = FetchedUser(name=username)
            invite = InsertedInvite(sender, max_uses=max_uses)
            return parent_command_id, '%s created for %s with %d use%s.' % (invite.url, sender.name, max_uses, '' if max_uses == 1 else 's')
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this user exists?')
    
    def del_invite(self, parent_command_id, invite_code):
        try:
            invite = FetchedInvite(code=invite_code)
            invite.delete()
            return parent_command_id, '%s\'s invite %s has been deleted.' % (invite.sender.name, invite.code)
        except NotInviteException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this invite exists?')
        except ImmutableInviteException, e:
            invite.disable()
            raise ExecutionError, (parent_command_id, 'this invite has already been used so can\'t be deleted, but now it can\'t be used again.')
    
    def invites(self, parent_command_id, vinebot, sender):
        return self.invites_for(parent_command_id, None, sender)
    
    def invites_for(self, parent_command_id, username, sender=None):
        try:
            if not sender:
                sender = FetchedUser(name=username)
            invites = FetchedInvite.fetch_sender_invites(sender)
            visible = filter(lambda invite: invite.visible and len(invite.recipients) < invite.max_uses, invites)
            used = filter(lambda invite: len(invite.recipients) > 0, invites)
            hidden = filter(lambda invite: not invite.visible and len(invite.recipients) == 0, invites)
            output = '%d %s has:' % (sender.id, sender.name)
            output += self._format_list_output(visible,
                                               'visible invites',
                                               lambda invite: '%s%s' % (invite.url, '' if (invite.max_uses - len(invite.recipients)) == 1 else ' (%d uses left)' % (invite.max_uses - len(invite.recipients))))
            output += self._format_list_output(used,
                                               'used invites',
                                               lambda invite: '%s by %s' % (invite.url, ", ".join([r.name for r in invite.recipients])))
            output += self._format_list_output(hidden,
                                               'hidden invites',
                                               lambda invite: '%s%s' % (invite.url, '' if (invite.max_uses - len(invite.recipients)) == 1 else ' (%d uses left)' % (invite.max_uses - len(invite.recipients))))
            return parent_command_id, output
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this user exists?')
    
    def score_edges(self, parent_command_id, username):
        try:
            user = FetchedUser(name=username)
            if celery_tasks:
                celery_tasks.score_edges.delay(user.id)
                return parent_command_id, 'Score edges Celery task queued for %s' % user.name
            else:
                raise ExecutionError, (parent_command_id, 'the celery_tasks module was not found.')
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, e)
    
    def _format_list_output(self, items, title, item_formatter):
        output = '\n\t%d %s' % (len(items), title)
        if len(items) > 0:
            output += '\n\t\t'
        output += '\n\t\t'.join([item_formatter(item) for item in items])
        return output
    

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
    g.use_new_logger('leaf__')
    xmpp = LeafComponent()
    if xmpp.connect(constants.server_ip, constants.component_port):
        xmpp.process(block=True)
        g.logger.info("Done")
    else:    
        g.logger.error("Unable to connect")
    logging.shutdown()
