
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
from mysql_conn import MySQLManager
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
        g.db = MySQLManager(constants.leaf_name, constants.leaf_mysql_password)
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
            return vinebot and sender.jid in constants.admin_jids
        def admin_to_leaf(sender, vinebot):
            return not vinebot and sender.jid in constants.admin_jids
        def admin_or_graph_to_leaf(sender, vinebot):
            return not vinebot and sender.jid in (constants.admin_jids + [constants.graph_xmpp_jid])
        def participant_or_edgeuser_to_vinebot(sender, vinebot):
            return vinebot and (sender in vinebot.participants or sender in vinebot.edge_users)   # short circuit to avoid the extra query
        def observer_to_vinebot(sender, vinebot):
            return vinebot and sender in vinebot.observers
        def admin_or_observer_to_vinebot(sender, vinebot):
            return admin_to_vinebot(sender, vinebot) or observer_to_vinebot(sender, vinebot)
        def admin_or_participant_or_edgeuser_to_vinebot(sender, vinebot):
            return admin_to_vinebot(sender, vinebot) or participant_or_edgeuser_to_vinebot(sender, vinebot)
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
        # Register vinebot commands
        self.commands.add(SlashCommand(command_name     = 'debug',
                                       text_arg_format  = '',
                                       text_description = 'Information about this conversation that\'s useful for debugging.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.debug_vinebot))
        self.commands.add(SlashCommand(command_name     = 'join',
                                       text_arg_format  = '',
                                       text_description = 'Join this conversation without interrupting.',
                                       validate_sender  = admin_or_observer_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.user_joined))    
        self.commands.add(SlashCommand(command_name     = 'leave',
                                       text_arg_format  = '',
                                       text_description = 'Leave this conversation. If it\'s just the two of you, it will no longer be visible to friends.',
                                       validate_sender  = participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.user_left))                  
        self.commands.add(SlashCommand(command_name     = 'invite',
                                       text_arg_format  = '<username>',
                                       text_description = 'Invite a user to this conversation.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token,
                                       action           = self.invite_user))
        self.commands.add(SlashCommand(command_name     = 'kick',
                                       text_arg_format  = '<username>',
                                       text_description = 'Kick a user out of this conversation.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token,
                                       action           = self.kick_user))
        self.commands.add(SlashCommand(command_name     = 'list',
                                       text_arg_format  = '',
                                       text_description = 'List the participants in this conversation.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.list_participants))
        self.commands.add(SlashCommand(command_name     = 'nearby',
                                       text_arg_format  = '',
                                       text_description = 'List the friends of the participants who can see this conversation (but not what you\'re saying).',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender,
                                       action           = self.list_observers))
        self.commands.add(SlashCommand(command_name     = 'whisper',
                                       text_arg_format  = '<username> <message text>',
                                       text_description = 'Whisper a quick message to only one other participant.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_token_string,
                                       action           = self.whisper_msg))
        self.commands.add(SlashCommand(command_name     = 'topic',
                                       text_arg_format  = '<new topic>',
                                       text_description = 'Set the topic for the conversation, which friends of participants can see.',
                                       validate_sender  = admin_or_participant_or_edgeuser_to_vinebot,
                                       transform_args   = logid_vinebot_sender_string_or_none,
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
        self.commands.add(SlashCommand(command_name     = 'sync',
                                       text_arg_format  = '<username>',
                                       text_description = 'Remove old, unused vinebots from a user\'s roster.',
                                       validate_sender  = admin_or_graph_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.sync_roster))
        self.commands.add(SlashCommand(command_name     = 'edges',
                                       text_arg_format  = '<username>',
                                       text_description = 'List all current edges, or only the specified user\'s edges.',
                                       validate_sender  = admin_to_leaf,
                                       transform_args   = logid_token,
                                       action           = self.list_edges))
    
    def disconnect(self, *args, **kwargs):
        other_leaves_online = False
        for lock_num_to_check in range(constants.max_leaves):
            if self.acquired_lock_num != lock_num_to_check:
                checked_lock = g.db.is_unlocked_leaf('%s%s' % (constants.leaf_mysql_lock_name, lock_num_to_check))
                if not checked_lock:
                    other_leaves_online = True
                    break
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
                acquired_lock = g.db.lock_leaf('%s%s' % (constants.leaf_mysql_lock_name, lock_num_to_acquire))
                if acquired_lock:
                    self.acquired_lock_num = lock_num_to_acquire
                    if lock_num_to_acquire > 0:
                        return True
                    for lock_num_to_check in range(lock_num_to_acquire + 1, constants.max_leaves):
                        checked_lock = g.db.is_unlocked_leaf('%s%s' % (constants.leaf_mysql_lock_name, lock_num_to_check))
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
        logging.info('Ready')
    
    def handle_presence_available(self, presence):
        user = None
        vinebot = None
        try:
            user = FetchedUser(name=presence['from'].user)
            vinebot = FetchedVinebot(can_write=True, jiduser=presence['to'].user)
            if vinebot.is_active:
                if user in vinebot.participants:
                    self.send_presences(vinebot, vinebot.everyone)
                elif user in vinebot.observers:
                    self.send_presences(vinebot, [user])
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
            pass
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
            vinebot = FetchedVinebot(can_write=True, jiduser=presence['to'].user)
            if user in vinebot.participants:  # [] if vinebot is not active
                if len(vinebot.participants) > 2:
                    self.send_presences(vinebot, vinebot.everyone)
                else:  # elif len(participants) == 2:
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
            pass
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
            vinebot = FetchedVinebot(can_write=True, jiduser=presence['to'].user)
            if not user.is_online():
                if user in vinebot.participants:  # [] if vinebot is not active
                    if len(vinebot.participants) > 2:
                        self.send_presences(vinebot, vinebot.everyone.difference([user]))
                    else:  # elif len(participants) == 2:
                        self.send_presences(vinebot, vinebot.participants.difference([user]), pshow='unavailable')
                    self.remove_participant(vinebot, user)
                    self.broadcast_alert(vinebot, '%s has disconnected and left the conversation' % user.name)
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
                            self.broadcast_message(vinebot, user, vinebot.participants, msg['body'])
                        elif user in vinebot.observers:
                            self.add_participant(vinebot, user)
                            self.broadcast_alert(vinebot, '%s has joined the conversation' % user.name)
                            self.broadcast_message(vinebot, user, vinebot.participants, msg['body'])
                        else:
                            parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                            self.send_alert(vinebot, None, user, 'Sorry, only friends of participants can join this conversation.', parent_message_id=parent_message_id)
                    else:
                        if len(vinebot.edges) > 0:
                            if self.activate_vinebot(vinebot):
                                self.broadcast_message(vinebot, user, vinebot.participants, msg['body'])
                            else:
                                parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                                self.send_alert(vinebot, None, user, 'Sorry, this users is offline.', parent_message_id=parent_message_id)
                        else:
                            parent_message_id = g.db.log_message(user, [], msg['body'], vinebot=vinebot)
                            self.send_alert(vinebot, None, user, 'Sorry, you can\'t send messages to this user. Try another contact in your list?', parent_message_id=parent_message_id)
            except NotVinebotException:
                if user.jid in (constants.admin_jids + [constants.graph_xmpp_jid]):
                    if self.commands.is_command(msg['body']):
                        handle_command(msg, user)
                    else:
                        parent_message_id = g.db.log_message(user, [], msg['body'])
                        self.send_alert(None, None, user, 'Sorry, this leaf only accepts /commands from admins.', fromjid=msg['to'], parent_message_id=parent_message_id)
                else:
                    parent_message_id = g.db.log_message(user, [], msg['body'])
                    self.send_alert(None, None, user, 'Sorry, you can\'t send messages to %s. Try another contact in your list?' % msg['to'], fromjid=msg['to'], parent_message_id=parent_message_id)
            except NotUserException:
                logging.error('Received message from unknown user: %s' % msg)
            finally:
                if vinebot:
                    vinebot.release_lock()
    
    def handle_chatstate(self, msg):
        try:
            user = FetchedUser(name=msg['from'].user)
            vinebot = FetchedVinebot(jiduser=msg['to'].user)
            if user in vinebot.participants:
                del msg['id']
                del msg['body']
                del msg['html']
                self.broadcast_message(vinebot, user, vinebot.everyone, None, msg=msg)
        except NotVinebotException:
            pass
        except NotUserException:
            pass
    
    ##### helper functions
    def send_presences(self, vinebot, recipients, pshow='available'):
        for recipient in recipients:
            self.sendPresence(pfrom='%s@%s' % (vinebot.jiduser, self.boundjid.bare),
                                pto='%s@%s' % (recipient.name, constants.server),
                                pshow=None if pshow == 'available' else pshow,
                                pstatus=unicode(vinebot.topic) if vinebot.topic else None)
    
    def broadcast_message(self, vinebot, sender, recipients, body, msg=None, parent_command_id=None):
        #LATER fix html, but it's a pain with reformatting
        if msg is None:  # need to pass this for chat states
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
                actual_recipients.append(recipient)
        g.db.log_message(sender, actual_recipients, body, vinebot=vinebot, parent_command_id=parent_command_id)
    
    def broadcast_alert(self, vinebot, body, parent_command_id=None):
        self.broadcast_message(vinebot, None, vinebot.participants, body, parent_command_id=parent_command_id)
    
    def send_alert(self, vinebot, sender, recipient, body, prefix='***', fromjid=None, parent_message_id=None, parent_command_id=None):
        if body == '':
            return
        msg = self.Message()
        msg['body'] = '%s %s' % (prefix, body)
        msg['from'] = '%s@%s' % (vinebot.jiduser, self.boundjid.bare) if vinebot else fromjid
        msg['to'] = recipient.jid
        msg.send()
        g.db.log_message(sender, [recipient], body, vinebot=vinebot, parent_message_id=parent_message_id, parent_command_id=parent_command_id)
        if parent_message_id is None and parent_command_id is None:
            logging.error('Call to send_alert with no parent. msg=%s' % (body, msg))
    
    def activate_vinebot(self, vinebot):
        if vinebot.is_active:
            logging.error('Called activate_vinebot for id=%d when vinebot was already active.' % vinebot.id)
            return True
        if len(vinebot.edges) == 0:
            raise Exception, 'Called activate_vinebot for id=%d when vinebot was not active and had no edges.' % vinebot.id
        user1, user2 = vinebot.edge_users
        user1_status = user1.status()
        user2_status = user2.status()
        self.send_presences(vinebot, [user1], pshow=user2_status)
        self.send_presences(vinebot, [user2], pshow=user1_status)
        both_users_online = user1_status != 'unavailable' and user2_status != 'unavailable'
        if both_users_online:
            self.add_participant(vinebot, user1)
            self.add_participant(vinebot, user2)
        return both_users_online
    
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
            if len(vinebot.edges) > 0:
                new_vinebot = None
                try:
                    new_vinebot = InsertedVinebot()
                    for edge in vinebot.edges:
                        edge.change_vinebot(new_vinebot) 
                        new_vinebot.add_to_roster_of(edge.f_user, new_vinebot.get_nick(edge.f_user))
                    self.send_presences(new_vinebot, new_vinebot.everyone)
                finally:
                    if new_vinebot:
                        new_vinebot.release_lock()
            self.send_presences(vinebot, vinebot.everyone)
        else:
            # there's no way this vinebot can still have edges associated with it
            vinebot.update_rosters(old_participants, vinebot.participants)
            self.send_presences(vinebot, vinebot.everyone)
    
    def remove_participant(self, vinebot, user):
        old_participants = vinebot.participants.copy()
        vinebot.remove_participant(user)
        if len(vinebot.participants) == 1:
            #LATER if two users have two active vinebots, one with an edge, and the person leaves the one with the edge, it won't get moved to the other
            other_user = iter(vinebot.participants.difference([user])).next()
            vinebot.remove_participant(other_user)
            if len(vinebot.edges) == 1:
                vinebot.update_rosters(old_participants, set([]), protected_participants=set([iter(vinebot.edges).next().f_user]))
            elif len(vinebot.edges) == 2:
                vinebot.update_rosters(old_participants, set([]), protected_participants=vinebot.edge_users)
            else:
                vinebot.update_rosters(old_participants, set([]))
                vinebot.delete()
        elif len(vinebot.participants) == 2:
            vinebot.update_rosters(old_participants, vinebot.participants)
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
            # this conversation had more than three people so start, so nothing changes if we remove someone
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
        self.send_alert(vinebot, None, user, 'dbid = %d\n%s\nparticipants = %s\nedge_users = %s' % (vinebot.id, vinebot.jiduser, vinebot.participants, vinebot.edge_users), parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def user_joined(self, parent_command_id, vinebot, user):
        if vinebot.topic:
            alert_msg = '%s has joined the conversation, but didn\'t want to interrupt. The current topic is:\n\t%s' % (user.name, vinebot.topic)
        else:
            alert_msg = '%s has joined the conversation, but didn\'t want to interrupt. No one has set the topic.' % user.name
        try:
            self.add_participant(vinebot, user)
        except IntegrityError, e:
            if e[0] == 1062:  # "Duplicate entry '48-16' for key 'PRIMARY'"
                raise ExecutionError, (parent_command_id, 'You can\'t join a conversation you\'re already in!')
            raise e
        self.broadcast_alert(vinebot, alert_msg, parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def user_left(self, parent_command_id, vinebot, user):
        if len(vinebot.participants) == 2:  # revert to previous status states
            user1, user2 = vinebot.participants
            self.send_presences(vinebot, [user1], pshow=user2.status())
            self.send_presences(vinebot, [user2], pshow=user1.status())
        self.remove_participant(vinebot, user)
        self.broadcast_alert(vinebot, '%s has left the conversation' % user.name, parent_command_id=parent_command_id)
        return parent_command_id, 'You left the conversation.'  # do this even if inactive, so users don't know if the other left
    
    def invite_user(self, parent_command_id, vinebot, inviter, invitee):
        try:
            invitee = FetchedUser(name=invitee)
        except NotUserException:
            raise ExecutionError, (parent_command_id, '%s is offline and can\'t be invited.' % invitee)
        if inviter == invitee:
            raise ExecutionError, (parent_command_id, 'you can\'t invite yourself.')
        if invitee.jid in (constants.admin_jids + [constants.graph_xmpp_jid, constants.leaves_xmlrpc_user]):
            raise ExecutionError, (parent_command_id, 'you can\'t invite administrator accounts.')
        if invitee in vinebot.participants:
            raise ExecutionError, (parent_command_id, '%s is already in this conversation.' % invitee.name)
        if len(vinebot.participants) == 0:
            raise ExecutionError, (parent_command_id, 'You can\'t invite someone before the conversation has started.')
        if not invitee.is_online():
            raise ExecutionError, (parent_command_id, '%s is offline and can\'t be invited.' % invitee.name)
        if vinebot.topic:
            alert_msg = '%s has invited %s to the conversation. The current topic is:\n\t%s' % (inviter.name, invitee.name, vinebot.topic)
        else:
            alert_msg = '%s has invited %s to the conversation. No one has set the topic.' % (inviter.name, invitee.name)
        self.add_participant(vinebot, invitee)
        self.broadcast_alert(vinebot, alert_msg, parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def kick_user(self, parent_command_id, vinebot, kicker, kickee):
        try:
            kickee = FetchedUser(name=kickee)
        except NotUserException:
            raise ExecutionError, (parent_command_id, '%s isn\'t a participant in the conversation, so can\'t be kicked.' % kickee)
        if kicker == kickee:
            raise ExecutionError, (parent_command_id, 'you can\'t kick yourself. Maybe you meant /leave?')
        if kickee.jid in (constants.admin_jids + [constants.graph_xmpp_jid, constants.leaves_xmlrpc_user]):
            raise ExecutionError, (parent_command_id, 'you can\'t kick administrator accounts.')
        if len(vinebot.participants) == 2:
            raise ExecutionError, (parent_command_id, 'you can\'t kick someone if it\'s just the two of you. Maybe you meant /leave?')
        if not kickee in vinebot.participants:
            raise ExecutionError, (parent_command_id, '%s isn\'t a participant in the conversation, so can\'t be kicked.' % kickee.name)
        self.remove_participant(vinebot, kickee)
        self.broadcast_alert(vinebot, '%s was kicked from the conversation by %s' % (kickee.name, kicker.name), parent_command_id=parent_command_id)
        self.send_alert(vinebot, None, kickee, '%s has kicked you from the conversation' % kicker.name, parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def list_participants(self, parent_command_id, vinebot, user):
        usernames = [participant.name for participant in vinebot.participants.difference([user])]
        if user in vinebot.participants:
            usernames.append('you')
        if vinebot.topic:
            return parent_command_id, 'The current participants are:\n%s\nThe current topic is:\n\t%s' % (
                    ''.join(['\t%s\n' % username for username in usernames]).strip('\n'), vinebot.topic)
        else:
            return parent_command_id, 'The current participants are:\n%s\nNo one has set the topic.' % (
                    ''.join(['\t%s\n' % username for username in usernames]).strip('\n'))
    
    def list_observers(self, parent_command_id, vinebot, user):
        observers = filter(lambda observer: observer.is_online(), vinebot.observers)
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
            raise ExecutionError, (parent_command_id, 'you can\'t whisper to youerself.')
        if recipient not in vinebot.participants and recipient.jid not in constants.admin_jids:
            raise ExecutionError, (parent_command_id, 'you can\'t whisper to someone who isn\'t a participant in this conversation.')
        self.send_alert(vinebot, sender, recipient, body, prefix='[%s, whispering]' % sender.name, parent_command_id=parent_command_id)
        if len(vinebot.participants) == 2:
            return parent_command_id, 'You whispered to %s, but it\'s just the two of you here so no one would have heard you anyway...' % recipient.name
        else:
            return parent_command_id, 'You whispered to %s, and no one noticed!' % recipient.name
    
    def set_topic(self, parent_command_id, vinebot, sender, topic):
        if topic and len(topic) > 100:
            raise ExecutionError, (parent_command_id, 'topics can\'t be longer than 100 characters, and this was %d characters.' % len(topic))
        else:
            vinebot.topic = topic  # using a fancy custom setter!
            if vinebot.is_active or self.activate_vinebot(vinebot):  # short-circuit prevents unnecessary vinebot activation
                self.send_presences(vinebot, vinebot.everyone)
                if vinebot.topic:
                    body = '%s has set the topic of the conversation:\n\t%s' % (sender.name, vinebot.topic)
                else:
                    body = '%s has cleared the topic of conversation.' % sender.name
                self.broadcast_alert(vinebot, body, parent_command_id=parent_command_id)
            else:
                if vinebot.topic:
                    body = 'You\'ve set the topic of conversation, but %s is offline so won\'t be notified.' % iter(vinebot.edge_users).next().name
                else:
                    body = 'You\'ve cleared the topic of conversation, but %s is offline so won\'t be notified.' % iter(vinebot.edge_users).next().name
                self.send_alert(vinebot, None, sender, body, parent_command_id=None)
        return parent_command_id, ''
    
    ##### admin /commands
    def create_user(self, parent_command_id, username, password):
        try:
            InsertedUser(username, password)
        except IntegrityError:
            raise ExecutionError, (parent_command_id, 'there was an IntegrityError - are you sure the user doesn\'t already exist?')
        return parent_command_id, None
    
    def delete_user(self, parent_command_id, username):
        try:
            user = FetchedUser(can_write=True, name=username)
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
    
    def create_edge(self, parent_command_id, from_username, to_username):
        try:
            f_user = FetchedUser(can_write=True, name=from_username)
            t_user = FetchedUser(can_write=True, name=to_username)
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, e)
        try:
            FetchedEdge(f_user=f_user, t_user=t_user)
            raise ExecutionError, (parent_command_id, '%s and %s already have a directed edge connecting them.' % (f_user.name, t_user.name))
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
            raise ExecutionError, (parent_command_id, '%s and %s do not have a directed edge connecting them.' % (f_user.name, t_user.name))
        self.cleanup_and_delete_edge(edge)
        return parent_command_id, '%s and %s no longer have a directed edge between them.' % (f_user.name, t_user.name)
    
    def sync_roster(self, parent_command_id, username):
        try:
            user = FetchedUser(name=username)
            expected_vinebots = frozenset([]).union(user.active_vinebots) \
                                             .union(user.observed_vinebots) \
                                             .union(user.symmetric_vinebots) \
                                             .union(user.outgoing_vinebots)
            expected_rosteritems = frozenset([(expected.jiduser, expected.get_nick(user)) for expected in expected_vinebots])
            actual_rosteritems = frozenset(user.roster())
            errors = []
            for roster_user, roster_nick in expected_rosteritems.difference(actual_rosteritems):
                errors.append('No rosteritem found for vinebot %s with nick %s' % (roster_user, roster_nick))
                g.ectl.add_rosteritem(user.name, roster_user, roster_nick)
            for roster_user, roster_nick in actual_rosteritems.difference(expected_rosteritems):
                errors.append('No vinebot found for rosteritem %s with nick %s' % (roster_user, roster_nick))
                g.ectl.delete_rosteritem(user.name, roster_user)
            if errors:
                return parent_command_id, '%s has the following roster errors:\n\t%s' % (user.name, '\n\t'.join(errors))
            else:
                return parent_command_id, '%s has no roster errors.' % user.name
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
            output += '\n\t%d friends (symmetric edges)' % len(user.friends)
            if len(user.friends) > 0: output += '\n\t\t'
            output += '\n\t\t'.join(['%d %s' % (friend.id, friend.name) for friend in user.friends])
            output += '\n\t%d incoming edges' % len(incoming)
            if len(incoming) > 0: output += '\n\t\t'
            output += '\n\t\t'.join(['%d %s' % (edge.f_user.id, edge.f_user.name) for edge in incoming ])
            output += '\n\t%d outgoing edges' % len(outgoing)
            if len(outgoing) > 0: output += '\n\t\t'
            output += '\n\t\t'.join(['%d %s' % (edge.t_user.id, edge.t_user.name) for edge in outgoing ])
            return parent_command_id, output
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, 'are you sure this user exists?')
    

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
        logging.error("Leaf was unable to connect")
