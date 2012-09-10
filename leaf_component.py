
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
import constants
from constants import g
from ejabberdctl import EjabberdCTL
from mysql_conn import MySQLConnection
from slash_commands import SlashCommand, SlashCommandRegistry, ExecutionError
from user import FetchedUser, InsertedUser, NotUserException
from edge import FetchedEdge, InsertedEdge, NotEdgeException
from vinebot import FetchedVinebot, InsertedVinebot, NotVinebotException

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
        self.acquired_lock_num = None
        g.db = MySQLConnection(constants.leaf_name, constants.leaf_mysql_password)
        g.ectl = EjabberdCTL(constants.leaves_xmlrpc_user, constants.leaves_xmlrpc_password)
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
            return sender.bare in constants.admin_users and vinebot
        def admin_to_leaf(sender, vinebot):
            return sender.bare in constants.admin_users and not vinebot
        def admin_or_graph_to_leaf(sender, vinebot):
            return sender.bare in (constants.admin_users + [constants.graph_xmpp_user]) and not vinebot
        def participant_to_vinebot(sender, vinebot):
            return sender.user in vinebot.participants and vinebot
        def observer_to_vinebot(sender, vinebot):
            return sender.user in vinebot.observers and vinebot
        def admin_or_participant_to_vinebot(sender, vinebot):
            return admin_to_vinebot(sender, vinebot) or participant_to_vinebot(sender, vinebot)
        # Argument transformations for /commands
        def logid_sender_vinebot(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot and len(arg_tokens) == 0:
                parent_command_id = g.db.log_command(sender.user, command_name, None, None, vinebot=vinebot)
                return [parent_command_id, sender.user, vinebot]
            return False
        def logid_sender_vinebot_token(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot and len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = g.db.log_command(sender.user, command_name, token, None, vinebot=vinebot)
                return [parent_command_id, sender.user, vinebot, token]
            return False
        def logid_sender_vinebot_string_or_none(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot:
                string_or_none = arg_string if len(arg_string.strip()) > 0 else None
                parent_command_id = g.db.log_command(sender.user, command_name, None, string_or_none, vinebot=vinebot)
                return [parent_command_id, sender.user, vinebot, string_or_none]
            return False
        def logid_sender_vinebot_token_string(command_name, sender, vinebot, arg_string, arg_tokens):
            if vinebot and len(arg_tokens) >= 2:
                token = arg_tokens[0]
                string = arg_string.partition(arg_tokens[0])[2].strip()
                parent_command_id = g.db.log_command(sender.user, command_name, token, string, vinebot=vinebot)
                return [parent_command_id, sender.user, vinebot, token, string]
            return False
        def logid_token(command_name, sender, vinebot, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = g.db.log_command(sender.user, command_name, token, None, vinebot=vinebot)
                return [parent_command_id, token]
            return False
        def logid_token_or_none(command_name, sender, vinebot, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                token = arg_tokens[0]
                parent_command_id = g.db.log_command(sender.user, command_name, token, None, vinebot=vinebot)
                return [parent_command_id, token]
            elif len(arg_tokens) == 0:
                parent_command_id = g.db.log_command(sender.user, command_name, None, None, vinebot=vinebot)
                return [parent_command_id]
            return False
        def logid_token_token(command_name, sender, vinebot, arg_string, arg_tokens):
            if len(arg_tokens) == 2:
                token1 = arg_tokens[0]
                token2 = arg_tokens[1]
                # Please forgive me for storing the second token as the command's string, but ugh I don't want
                # to add an extra column right now. I'll fix it when I have a second command with two tokens.
                parent_command_id = g.db.log_command(sender.user, command_name, token1, token2, vinebot=vinebot)
                return [parent_command_id, token1, token2]
            return False
        # Register vinebot commands
        # self.commands.add(SlashCommand(command_name     = 'join',
        #                                        text_arg_format  = '',
        #                                        text_description = 'Join this conversation without interrupting.',
        #                                        validate_sender  = observer_to_vinebot,
        #                                        transform_args   = logid_sender_vinebot,
        #                                        action           = self.user_joined))    
        #         self.commands.add(SlashCommand(command_name     = 'leave',
        #                                        text_arg_format  = '',
        #                                        text_description = 'Leave this conversation.',
        #                                        validate_sender  = participant_to_vinebot,
        #                                        transform_args   = logid_sender_vinebot,
        #                                        action           = self.user_left))                  
        #         self.commands.add(SlashCommand(command_name     = 'invite',
        #                                        text_arg_format  = '<username>',
        #                                        text_description = 'Invite a user to this conversation.',
        #                                        validate_sender  = admin_or_participant_to_vinebot,
        #                                        transform_args   = logid_sender_vinebot_token,
        #                                        action           = self.invite_user))
        #         self.commands.add(SlashCommand(command_name     = 'kick',
        #                                        text_arg_format  = '<username>',
        #                                        text_description = 'Kick a user out of this conversation.',
        #                                        validate_sender  = admin_or_participant_to_vinebot,
        #                                        transform_args   = logid_sender_vinebot_token,
        #                                        action           = self.kick_user))
        #         self.commands.add(SlashCommand(command_name     = 'list',
        #                                        text_arg_format  = '',
        #                                        text_description = 'List the participants in this conversation.',
        #                                        validate_sender  = admin_or_participant_to_vinebot,
        #                                        transform_args   = logid_sender_vinebot,
        #                                        action           = self.list_participants))
        #         self.commands.add(SlashCommand(command_name     = 'nearby',
        #                                        text_arg_format  = '',
        #                                        text_description = 'List the friends of the participants who can see this conversation (but not what you\'re saying).',
        #                                        validate_sender  = admin_or_participant_to_vinebot,
        #                                        transform_args   = logid_sender_vinebot,
        #                                        action           = self.list_observers))
        #         self.commands.add(SlashCommand(command_name     = 'whisper',
        #                                        text_arg_format  = '<username> <message text>',
        #                                        text_description = 'Whisper a quick message to only one other participant.',
        #                                        validate_sender  = admin_or_participant_to_vinebot,
        #                                        transform_args   = logid_sender_vinebot_token_string,
        #                                        action           = self.whisper_msg))
        #         self.commands.add(SlashCommand(command_name     = 'topic',
        #                                        text_arg_format  = '<new topic>',
        #                                        text_description = 'Set the topic for the conversation, which friends of participants can see.',
        #                                        validate_sender  = admin_or_participant_to_vinebot,
        #                                        transform_args   = logid_sender_vinebot_string_or_none,
        #                                        action           = self.set_topic))
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
                                       action           = self.delete_user))
        self.commands.add(SlashCommand(command_name     = 'new_edge',
                                       text_arg_format  = '<username1> <username2>',
                                       text_description = 'Create a friendship between two users.',
                                       validate_sender  = admin_or_graph_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.create_edge))
        self.commands.add(SlashCommand(command_name     = 'del_edge',
                                       text_arg_format  = '<username1> <username2>',
                                       text_description = 'Delete a friendship between two users.',
                                       validate_sender  = admin_or_graph_to_leaf,
                                       transform_args   = logid_token_token,
                                       action           = self.delete_edge))
        # self.commands.add(SlashCommand(command_name     = 'prune',
        #                                text_arg_format  = '<username>',
        #                                text_description = 'Remove old, unused vinebots from a user\'s roster.',
        #                                validate_sender  = admin_to_leaf,
        #                                transform_args   = logid_token,
        #                                action           = self.prune_roster))
        # self.commands.add(SlashCommand(command_name     = 'friendships',
        #                                text_arg_format  = '<username (optional)>',
        #                                text_description = 'List all current friendships, or only the specified user\'s friendships.',
        #                                validate_sender  = admin_to_leaf,
        #                                transform_args   = logid_token_or_none,
        #                                action           = self.friendships))
    
    def disconnect(self, *args, **kwargs):
        other_leaves_online = False
        for lock_num_to_check in range(constants.max_leaves):
            if self.acquired_lock_num != lock_num_to_check:
                checked_lock = g.db.is_free_lock('%s%s' % (constants.leaf_mysql_lock_name, lock_num_to_check))
                #logging.info('%d checked? %s' % (lock_num_to_check, checked_lock))
                if not checked_lock:
                    other_leaves_online = True
                    break
        #logging.info('disconnecting! other leaves online? %s' % other_leaves_online)
        if not other_leaves_online:
            for vinebot in FetchedVinebot.fetch_vinebots_with_participants():
                self.send_presences(vinebot, vinebot.everyone, pshow='unavailable')
            for vinebot in FetchedVinebot.fetch_vinebots_with_edges():
                for edge in vinebot.edges:
                    self.send_presences(vinebot, [edge.f_user], pshow='unavailable')
        g.db.cleanup()
        kwargs['wait'] = True
        super(LeafComponent, self).disconnect(*args, **kwargs)
    
    ##### event handlers
    def handle_start(self, event):
        def register_leaf():  # this is a function because using return makes it cleaner
            for lock_num_to_acquire in range(constants.max_leaves):
                acquired_lock = g.db.get_lock('%s%s' % (constants.leaf_mysql_lock_name, lock_num_to_acquire))
                #logging.info('acquiring %d? %s' % (lock_num_to_acquire, acquired_lock))
                if acquired_lock:
                    self.acquired_lock_num = lock_num_to_acquire
                    if lock_num_to_acquire > 0:
                        return True
                    for lock_num_to_check in range(lock_num_to_acquire + 1, constants.max_leaves):
                        checked_lock = g.db.is_free_lock('%s%s' % (constants.leaf_mysql_lock_name, lock_num_to_check))
                        #logging.info('checking %d? %s' % (lock_num_to_check, checked_lock))
                        if not checked_lock:
                            return True
                    return False
            return constants.max_leaves > 0  # if there are no locks to acquire, but we have to go through the whole loop to make sure we acquire one ourself
        other_leaves_online = register_leaf()
        if not other_leaves_online:
            for vinebot in FetchedVinebot.fetch_vinebots_with_participants():
                self.send_presences(vinebot, vinebot.everyone)
            for vinebot in FetchedVinebot.fetch_vinebots_with_edges():
                for edge in vinebot.edges:
                    self.send_presences(vinebot, [edge.f_user], pshow=edge.t_user.status())
        #logging.info('starting! other leaves online? %s' % other_leaves_online)
    
    def handle_presence_available(self, presence):
        try:
            user = FetchedUser(name=presence['from'].user)
            vinebot = None
            try:
                vinebot = FetchedVinebot(jiduser=presence['to'].user)            
                if vinebot.is_active:
                    if user in vinebot.participants:
                        self.send_presences(vinebot, vinebot.everyone)
                    elif user in vinebot.observers:
                        self.send_presences(vinebot, [user])
                else:
                    try:
                        edge_t_user = FetchedEdge(t_user=user, vinebot=vinebot)
                        self.send_presences(vinebot, [edge_t_user.f_user])
                    except NotEdgeException:
                        pass
                    try:
                        edge_f_user = FetchedEdge(f_user=user, vinebot=vinebot)
                        self.send_presences(vinebot, [user], edge_f_user.t_user.status())
                    except NotEdgeException:
                        pass
            except NotVinebotException:
                pass
            for incoming_vinebot in user.incoming_vinebots.difference([vinebot]):
                self.send_presences(incoming_vinebot, [user])
        except NotUserException:
            return
    
    def handle_presence_away(self, presence):
        try:
            user = FetchedUser(name=presence['from'].user)
            vinebot = None
            try:
                vinebot = FetchedVinebot(jiduser=presence['to'].user)
                if user in vinebot.participants:  # [] if vinebot is not active
                    if len(vinebot.participants) >= 3:
                        self.send_presences(vinebot, vinebot.everyone)
                    else:  # elif len(participants) == 2:
                        remaining_user = iter(vinebot.participants.difference([user])).next()
                        self.remove_participant(vinebot, user)  # this deactivates the vinebot
                        self.send_presences(vinebot, [user], pshow=remaining_user.status())
                        self.send_presences(vinebot, [remaining_user], pshow=presence['type'])
                else:
                    try:
                        edge_t_user = FetchedEdge(t_user=user, vinebot=vinebot)
                        self.send_presences(vinebot, [edge_t_user.f_user], pshow=presence['type'])
                    except NotEdgeException:
                        pass
            except NotVinebotException:
                return
            for incoming_vinebot in user.incoming_vinebots.difference([vinebot]):
                self.send_presences(incoming_vinebot, [user], pshow=presence['type'])
        except NotUserException:
            return
    
    def handle_presence_unavailable(self, presence):
        try:
            user = FetchedUser(name=presence['from'].user)
            vinebot = None
            try:
                vinebot = FetchedVinebot(jiduser=presence['to'].user)
                logging.info('ok')
                logging.info(user.is_online())
                if not user.is_online():
                    if user in vinebot.participants:  # [] if vinebot is not active
                        if len(vinebot.participants) > 2:
                            self.send_presences(vinebot, vinebot.everyone.difference([user]))
                        else:  # elif len(participants) == 2:
                            self.send_presences(vinebot, vinebot.participants.difference([user]), pshow='unavailable')
                        self.remove_participant(vinebot, user)
                    elif user in vinebot.edge_users:
                        self.send_presences(vinebot, vinebot.edge_users.difference([user]), pshow='unavailable')
            except NotVinebotException:
                return
            for incoming_vinebot in user.incoming_vinebots.difference([vinebot]):
                if len(incoming_vinebot.edges) == 1:  # no need to send this presence to vinebots with two edges #LATER make this more efficient
                    self.send_presences(incoming_vinebot, incoming_vinebot.edge_users.difference([user]), pshow='unavailable')
        except NotUserException:
            return
    
    def handle_msg(self, msg):
        def handle_command(msg, vinebot=None):
            parent_command_id, response = self.commands.handle_command(msg['from'], msg['body'], vinebot)
            if parent_command_id is None:  # if the command has some sort of error
                command_name, arg_string = self.commands.parse_command(msg['body'])
                parent_command_id = g.db.log_command(msg['from'].user, command_name, None, arg_string, vinebot=vinebot, is_valid=False)
            self.send_reply(msg, vinebot, response, parent_command_id=parent_command_id)
        if msg['type'] in ('chat', 'normal'):
            try:
                vinebot = FetchedVinebot(jiduser=msg['to'].user)
                if self.commands.is_command(msg['body']):
                    handle_command(msg, vinebot)
                else:
                    user = FetchedUser(name=msg['from'].user)
                    if vinebot.participants:
                        if user in vinebot.participants:
                            self.broadcast_message(vinebot, user, vinebot.participants, msg['body'])
                        elif user in vinebot.observers:
                            vinebot.add_participant(user)
                            self.broadcast_alert(vinebot, vinebot.participants, '%s has joined the conversation' % user.name)
                            self.broadcast_message(vinebot, user, vinebot.participants, msg['body'])
                        else:
                            parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                            self.send_reply(msg, vinebot, 'Sorry, only friends of participants can join this conversation.', parent_message_id=parent_message_id)
                    else:
                        #TODO ugh this is a mess, use if len(vinebot.edges) > 0:
                        try:
                            edge_t_user = FetchedEdge(t_user=user, vinebot=vinebot)
                        except NotEdgeException:
                            edge_t_user = None
                        try:
                            edge_f_user = FetchedEdge(f_user=user, vinebot=vinebot)
                        except NotEdgeException:
                            edge_f_user = None
                        if edge_t_user or edge_f_user:
                            user1, user2 = set([edge_t_user.t_user, edge_t_user.f_user] if edge_t_user else [] +
                                               [edge_f_user.t_user, edge_f_user.f_user] if edge_f_user else [])
                            user1_status = user1.status()
                            user2_status = user2.status()
                            self.send_presences(vinebot, [user1], pshow=user2_status)
                            self.send_presences(vinebot, [user2], pshow=user1_status)
                            if user1_status != 'unavailable' and user2_status != 'unavailable':
                                self.add_participant(vinebot, user1)
                                self.add_participant(vinebot, user2)
                                self.send_presences(vinebot, vinebot.observers)
                                self.broadcast_message(vinebot, user, vinebot.participants, msg['body'])
                            else:
                                parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                                self.send_reply(msg, vinebot, 'Sorry, this users is offline.', parent_message_id=parent_message_id)
                        else:
                            parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                            self.send_reply(msg, vinebot, 'Sorry, you can\'t send messages to this user.', parent_message_id=parent_message_id)
                    vinebot.cleanup()
            except NotVinebotException:
                try:
                    if msg['from'].bare in (constants.admin_users + [constants.graph_xmpp_user]):
                        if self.commands.is_command(msg['body']):
                            handle_command(msg)
                        else:
                            user = FetchedUser(name=msg['from'].user)
                            parent_message_id = g.db.log_message(user, [], msg['body'])
                            self.send_reply(msg, None, 'Sorry, this leaf only accepts /commands from admins.', parent_message_id=parent_message_id)
                    else:
                        user = FetchedUser(name=msg['from'].user)
                        parent_message_id = g.db.log_message(user, [], msg['body'])
                        self.send_reply(msg, None, 'Sorry, you can\'t send messages to %s.' % msg['to'], parent_message_id=parent_message_id)
                except NotUserException:
                    logging.error('Received message from unknown user: %s' % msg)
            except NotUserException:
                logging.error('Received message from unknown user: %s' % msg)
    
    def handle_chatstate(self, msg):
        pass
    
    ##### helper functions
    def send_presences(self, vinebot, recipients, pshow='available'):
        for recipient in recipients:
            self.sendPresence(pfrom='%s@%s' % (vinebot.jiduser, self.boundjid.bare),
                                pto='%s@%s' % (recipient.name, constants.server),
                                pshow=None if pshow == 'available' else pshow,
                                pstatus=unicode(vinebot.topic) if vinebot.topic else None)
    
    def broadcast_message(self, vinebot, sender, recipients, body, parent_command_id=None):
        #LATER fix html, but it's a pain with reformatting
        msg = self.Message()
        if body and body != '':
            if sender:
                msg['body'] = '[%s] %s' % (sender.name, body)
            else:
                msg['body'] = '*** %s' % (body)
        actual_recipients = []
        for recipient in recipients:
            if not sender or sender != recipient:
                new_msg = msg.__copy__()
                new_msg['to'] = '%s@%s' % (recipient.name, constants.server)
                new_msg['from'] = '%s@%s' % (vinebot.jiduser, self.boundjid.bare)
                new_msg.send()
                actual_recipients.append(recipient.name)
        g.db.log_message(sender, actual_recipients, body, vinebot=vinebot, parent_command_id=parent_command_id)
    
    def broadcast_alert(self, vinebot, recipients, body, parent_command_id=None):
        self.broadcast_message(vinebot, None, recipients, body, parent_command_id=parent_command_id)
    
    def send_reply(self, msg, vinebot, body, parent_message_id=None, parent_command_id=None):
        msg.reply(body).send()
        if parent_message_id is None and parent_command_id is None:
            logging.error('Attempted to send reply "%s" with no parent. msg=%s' % (body, msg))
        else:
            g.db.log_message(None,
                                [msg['to'].user],
                                body,
                                vinebot=vinebot,
                                parent_message_id=parent_message_id,
                                parent_command_id=parent_command_id)
    
    def add_participant(self, vinebot, user):
        old_participants = vinebot.participants.copy()  # makes a shallow copy, which is good, because it saves queries on User.friends 
        vinebot.add_participant(user)
        if len(vinebot.participants) < 2:
            pass  # this is the first participant, so assume that we're adding another one in a second
        elif len(vinebot.participants) == 2:
            vinebot.update_rosters(set([]), vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
        elif len(vinebot.participants) == 3:
            vinebot.update_rosters(old_participants, vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
            if len(vinebot.edges) > 0:
                new_vinebot = InsertedVinebot()
                for edge in vinebot.edges:
                    edge.change_vinebot(new_vinebot) 
                    new_vinebot.add_to_roster_of(edge.f_user, new_vinebot.get_nick(edge.t_user))
        else:
            # there's no way this vinebot can still have edges associated with it
            vinebot.update_rosters(old_participants, vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
    
    def remove_participant(self, vinebot, user):
        old_participants = vinebot.participants.copy()
        vinebot.remove_participant(user)
        if len(vinebot.participants) < 1:
            pass
        elif len(vinebot.participants) == 1:
            vinebot.remove_participant(iter(vinebot.participants.difference([user])).next())
            vinebot.update_rosters(old_participants, set([]))
            self.send_presences(vinebot, vinebot.everyone)
            if len(vinebot.edges) == 0:
                vinebot.delete()
        elif len(vinebot.participants) == 2:
            vinebot.update_rosters(old_participants, vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
            user1, user2 = vinebot.participants
            try:
                edge_t_user = FetchedEdge(f_user=user2, t_user=user1)
            except NotEdgeException:
                edge_t_user = None
            try:
                edge_f_user = FetchedEdge(f_user=user1, t_user=user2)
            except NotEdgeException:
                edge_f_user = None
            edge = edge_t_user if edge_t_user else edge_f_user
            if edge_t_user:
                old_vinebot = FetchedVinebot(dbid=edge_t_user.vinebot_id)
            elif edge_f_user:
                old_vinebot = FetchedVinebot(dbid=edge_f_user.vinebot_id)
            if edge and len(old_vinebot.participants) == 0:
                old_vinebot.delete()
                if edge_t_user:
                    edge_t_user.change_vinebot(new_vinebot)
                if edge_f_user:
                    edge_f_user.change_vinebot(new_vinebot)
        else:
            # this conversation had more than three people so start, so nothing changes if we remove someone
            vinebot.update_rosters(old_participants, vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
    
    ##### admin /commands
    def create_user(self, parent_command_id, username, password):
        try:
            InsertedUser(username, password)
        except IntegrityError:
            raise ExecutionError, (parent_command_id, 'there was an IntegrityError - are you sure the user doesn\'t already exist?')
        return parent_command_id, None
    
    def delete_user(self, parent_command_id, user):
        try:
            #TODO implement this
            # for friend in g.db_fetch_user_friends(user):
            #     self.delete_friendship(user, friend)
            # for party_vinebot_uuid in g.db_fetch_user_party_vinebots(user):
            #     vinebot_user = self.get_vinebot_user(party_vinebot_uuid)
            #     self.remove_participant(user, vinebot_user, '%s\'s account has been deleted.' % user)
            user = FetchedUser(name=user)
            user.delete()
        except IntegrityError:
            raise ExecutionError, (parent_command_id, 'there was an IntegrityError - are you sure the user already exists?')
        return parent_command_id, None
    
    def create_edge(self, parent_command_id, from_username, to_username):
        try:
            f_user = FetchedUser(name=from_username)
            t_user = FetchedUser(name=to_username)
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, e)
        try:
            FetchedEdge(f_user, t_user)
            raise ExecutionError, (parent_command_id, '%s and %s already have a directed edge connecting them.' % (f_user.name, t_user.name))
        except NotEdgeException:  # no edge was found in the database, so we can continue
            pass
        try:
            reverse_edge = FetchedEdge(t_user, f_user)
            vinebot = FetchedVinebot(dbid=reverse_edge.vinebot_id)#, edges=[reverse_edge])
            f_user.note_visible_active_vinebots()
            t_user.note_visible_active_vinebots()
            InsertedEdge(f_user, t_user, vinebot_id=vinebot.id)
            for other_vinebot in f_user.calc_active_vinebot_diff().difference([vinebot]):
                other_vinebot.add_to_roster_of(f_user, other_vinebot.get_nick(f_user))
                self.send_presences(other_vinebot, [f_user])
            for other_vinebot in t_user.calc_active_vinebot_diff().difference([vinebot]):
                other_vinebot.add_to_roster_of(t_user, other_vinebot.get_nick(t_user))
                self.send_presences(other_vinebot, [t_user])
        except NotEdgeException:
            vinebot = InsertedVinebot()
            InsertedEdge(f_user, t_user, vinebot_id=vinebot.id)
        self.send_presences(vinebot, [f_user], pshow=t_user.status())
        vinebot.add_to_roster_of(f_user, vinebot.get_nick(f_user))
        return parent_command_id, '%s and %s now have a directed edge between them.' % (f_user.name, t_user.name)
    
    def delete_edge(self, parent_command_id, from_username, to_username):
        try:
            f_user = FetchedUser(name=from_username)
            t_user = FetchedUser(name=to_username)
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, e)
        try:
            edge = FetchedEdge(f_user, t_user)
        except NotEdgeException:
            raise ExecutionError, (parent_command_id, '%s and %s do not have a directed edge connecting them.' % (f_user.name, t_user.name))
        vinebot = FetchedVinebot(dbid=edge.vinebot_id)
        try:
            FetchedEdge(t_user, f_user)  # reverse_edge
            f_user.note_visible_active_vinebots()
            t_user.note_visible_active_vinebots()
            edge.delete()
            for other_vinebot in f_user.calc_active_vinebot_diff().difference([vinebot]):
                other_vinebot.remove_from_roster_of(f_user)
            for other_vinebot in t_user.calc_active_vinebot_diff().difference([vinebot]):
                other_vinebot.remove_from_roster_of(t_user)
        except NotEdgeException:    
            edge.delete()
            if not vinebot.is_active:
                vinebot.delete()
        if not vinebot.is_active:
            vinebot.remove_from_roster_of(f_user)
        return parent_command_id, '%s and %s no longer have a directed edge between them.' % (f_user.name, t_user.name)
    

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





































