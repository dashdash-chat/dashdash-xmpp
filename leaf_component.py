
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
from user import User, NotUserException
from edge import FetchedEdge, InsertedEdge, NotEdgeException
from vinebot import FetchedVinebot, InsertedVinebot, NotVinebotException
import constants
from constants import g
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
            return sender.user in bot.participants and vinebot
        def observer_to_vinebot(sender, vinebot):
            return sender.user in bot.observers and vinebot
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
            logging.warning("TODO: send unavailable from all vinebots")
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
            logging.warning("TODO: send available from all vinebots")
        #logging.info('starting! other leaves online? %s' % other_leaves_online)
    
    def handle_presence_available(self, presence):
        try:
            vinebot = FetchedVinebot(jiduser=presence['to'].user)
            user = User(name=presence['from'].user)
            if vinebot.is_active():
                participants = vinebot.fetch_participants()
                observers = vinebot.fetch_observers()
                if user in participants:
                    self.send_presences(vinebot, participants + observers)
                elif user in observers:
                    self.send_presences(vinebot, [user])
            else:
                edge_t_user = FetchedEdge(t_user=user, vinebot=vinebot)
                edge_f_user = FetchedEdge(f_user=user, vinebot=vinebot)
                if edge_t_user:
                    self.send_presences(vinebot, [edge_t_user.f_user])
                if edge_f_user:
                    self.send_presences(vinebot, [user], edge_f_user.t_user.status())
        except NotVinebotException:
            return
        except NotUserException:
            return
    
    def handle_presence_away(self, presence):
        try:
            vinebot = FetchedVinebot(jiduser=presence['to'].user)
            user = User(name=presence['from'].user)
            participants = vinebot.fetch_participants()
            if user in participants:  # [] if vinebot is not active
                if len(participants) > 2:
                    observers = vinebot.fetch_observers()
                    self.send_presences(vinebot, participants + observers)
                else:  # elif len(participants) == 2:
                    vinebot.remove_participant(user)  # this deactivates the vinebot
                    remaining_user = participants.difference([user])
                    self.send_presences(vinebot, [user], pshow=remaining_user.status())
                    self.send_presences(vinebot, [remaining_user], pshow=presence['type'])
            else:
                edge_t_user = FetchedEdge(t_user=user, vinebot=vinebot)
                if edge_t_user:
                    self.send_presences(vinebot, [edge_t_user.f_user], pshow=presence['type'])
        except NotVinebotException:
            return
        except NotUserException:
            return
    
    def handle_presence_unavailable(self, presence):
        try:
            vinebot = FetchedVinebot(jiduser=presence['to'].user)
            user = User(name=presence['from'].user)
            participants = vinebot.fetch_participants()
            if user in participants:  # [] if vinebot is not active
                vinebot.remove_participant(user)   
                if len(participants) > 2:
                    observers = vinebot.fetch_observers()
                    self.send_presences(vinebot, participants + observers)
                    
                else:  # elif len(participants) == 2:
                    remaining_user = participants.difference([user])
                    self.send_presences(vinebot, [remaining_user], pshow='unavailable')
        except NotVinebotException:
            return
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
                    self.send_reply(msg, vinebot, 'Received: %s' % msg['body'])
                    # if msg['from'].user in bot.participants:
                    #     if not bot.is_active:
                    #         user1, user2 = bot.participants  # in case one user is away or offline
                    #         user1_status = self.user_status(user1)
                    #         user2_status = self.user_status(user2)
                    #         self.send_presences(bot, [user1], pshow=user2_status)
                    #         self.send_presences(bot, [user2], pshow=user1_status)
                    #         if user1_status != 'unavailable' and user2_status != 'unavailable':
                    #             g.db_activate_pair_vinebot(bot.user, True)
                    #             self.update_rosters(set([]), bot.participants, bot.user, False)
                    #             self.send_presences(bot, bot.observers)
                    #             self.broadcast_msg(msg, bot.participants, sender=msg['from'].user)
                    #         else:
                    #             parent_message_id = g.db_log_message(bot.user, msg['from'].user, [], msg['body'])
                    #             self.send_reply(msg, 'Sorry, this users is offline.', parent_message_id=parent_message_id)
                    #     else:
                    #         self.broadcast_msg(msg, bot.participants, sender=msg['from'].user)
                    # elif msg['from'].user in bot.observers:
                    #     if bot.is_active:
                    #         self.add_participant(msg['from'].user, bot, '%s has joined the conversation' % msg['from'].user)
                    #         self.broadcast_msg(msg, bot.participants, sender=msg['from'].user)
                    #     else:    
                    #         parent_message_id = g.db_log_message(bot.user, msg['from'].user, [], msg['body'])
                    #         self.send_reply(msg, 'Sorry, this conversation has ended for now.', parent_message_id=parent_message_id)
                    # else:
                    #     parent_message_id = g.db_log_message(bot.user, msg['from'].user, [], msg['body'])
                    #     if bot.is_active:
                    #         self.send_reply(msg, 'Sorry, only friends of participants can join this conversation.', parent_message_id=parent_message_id)
                    #     else:    
                    #         self.send_reply(msg, 'Sorry, this conversation has ended.', parent_message_id=parent_message_id)
            except NotVinebotException:
                if msg['from'].bare in (constants.admin_users + [constants.graph_xmpp_user]):
                    if self.commands.is_command(msg['body']):
                        handle_command(msg)
                    else:
                        parent_message_id = g.db.log_message(msg['from'].user, [], msg['body'])
                        self.send_reply(msg, None, 'Sorry, this leaf only accepts /commands from admins.', parent_message_id=parent_message_id)
                else:
                    parent_message_id = g.db.log_message(msg['from'].user, [], msg['body'])
                    self.send_reply(msg, None, 'Sorry, you can\'t send messages to %s.' % msg['to'], parent_message_id=parent_message_id)
    
    def handle_chatstate(self, msg):
        pass

    ##### helper functions
    def send_presences(self, vinebot, recipients, pshow='available'):
        for recipient in recipients:
            self.sendPresence(pfrom='%s@%s' % (vinebot.jiduser, self.boundjid.bare),
                                pto='%s@%s' % (recipient.name, constants.server),
                                pshow=None if pshow == 'available' else pshow,
                                pstatus=unicode(vinebot.topic) if vinebot.topic else None)
    
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

    ##### admin /commands
    def create_user(self, parent_command_id, user, password):
        try:
            g.db.execute("INSERT INTO users (name) VALUES (%(user)s)", {'user': user})
            g.ectl.register(user, password)
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
            g.db.execute("DELETE FROM users WHERE name = %(user)s", {'user': user})
            g.ectl.unregister(user)
        except IntegrityError:
            raise ExecutionError, (parent_command_id, 'there was an IntegrityError - are you sure the user already exists?')
        return parent_command_id, None
    
    def create_edge(self, parent_command_id, from_username, to_username):
        try:
            f_user = User(name=from_username)
            t_user = User(name=to_username)
        except NotUserException, e:
            raise ExecutionError, (parent_command_id, e)
        try:
            FetchedEdge(f_user, t_user)
            raise ExecutionError, (parent_command_id, '%s and %s already have a directed edge connecting them.' % (f_user.name, t_user.name))
        except NotEdgeException:  # no edge was found in the database, so we can continue
            pass
        try:
            reverse_edge = FetchedEdge(t_user, f_user)
            vinebot = FetchedVinebot(dbid=reverse_edge.vinebot_id, edges=[reverse_edge])
            f_user.note_visible_active_vinebots()
            t_user.note_visible_active_vinebots()
            InsertedEdge(f_user, t_user, vinebot_id=vinebot.id)
            f_user.update_visible_active_vinebots()
            t_user.update_visible_active_vinebots()
            #TODO send presences to observers?
        except NotEdgeException:
            vinebot = InsertedVinebot(g.db, g.ectl)
            InsertedEdge(f_user, t_user, vinebot_id=vinebot.id)
        self.send_presences(vinebot, [f_user], pshow=t_user.status())
        vinebot.add_to_roster_of(f_user)
        vinebot.cleanup()
        return parent_command_id, '%s and %s now have a directed edge between them.' % (f_user.name, t_user.name)
    
    def delete_edge(self, parent_command_id, from_username, to_username):
        try:
            f_user = User(name=from_username)
            t_user = User(name=to_username)
        except NotUserException, e:
            raise ExecutionError, (parent_command, e)
        try:
            edge = FetchedEdge(f_user, t_user)
        except NotEdgeException:
            raise ExecutionError, (parent_command_id, '%s and %s do not have a directed edge connecting them.' % (f_user.name, t_user.name))
        vinebot = FetchedVinebot(dbid=edge.vinebot_id)
        try:
            reverse_edge = FetchedEdge(t_user, f_user)
            f_user.note_visible_active_vinebots()
            t_user.note_visible_active_vinebots()
            edge.delete()
            f_user.update_visible_active_vinebots()
            t_user.update_visible_active_vinebots()
        except NotEdgeException:    
            edge.delete()
            if not vinebot.is_active():
                vinebot.delete()
        vinebot.remove_from_roster_of(f_user)
        vinebot.cleanup()
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





































