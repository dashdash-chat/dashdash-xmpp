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
import xmlrpclib
import sleekxmpp
from sleekxmpp.componentxmpp import ComponentXMPP
from sleekxmpp.exceptions import IqError, IqTimeout
import constants
from slash_commands import SlashCommand, SlashCommandRegistry, ExecutionError
from bot import Bot

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class LeafComponent(ComponentXMPP):
    def __init__(self, leaf_id):
        self.id = leaf_id
        ComponentXMPP.__init__(self, '%s%s.%s' % (constants.leaf_name, self.id, constants.server), 
                               constants.leaf_secret, constants.server, constants.component_port)
        self.registerPlugin('xep_0030') # Service Discovery
        self.registerPlugin('xep_0199') # XMPP Ping
        self.registerPlugin('xep_0085') # Chat State Notifications
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
        self.db = None
        self.cursor = None
        self.db_connect()
        self.commands = SlashCommandRegistry()
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
        # Add event handlers
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
    
    def disconnect(self, *args, **kwargs):
        #LATER check if other leaves are online, since otherwise we don't need to do this.
        pair_vinebots = self.db_fetch_all_pair_vinebots()
        party_vinebots = self.db_fetch_all_party_vinebots()
        for vinebot in pair_vinebots + party_vinebots:
            self.send_presences(vinebot, vinebot.everyone, pshow='unavailable')
        kwargs['wait'] = True
        super(LeafComponent, self).disconnect(*args, **kwargs)
    
    
    ##### event handlers
    def handle_start(self, event):
        #LATER check if other leaves are online, since otherwise we don't need to do this.
        pair_vinebots = self.db_fetch_all_pair_vinebots()
        for vinebot in pair_vinebots:
            user1, user2 = vinebot.participants
            user1_status = self.user_status(user1)
            user2_status = self.user_status(user2)
            self.send_presences(vinebot, [user1], pshow=user2_status)
            self.send_presences(vinebot, [user2], pshow=user1_status)
            if user1_status in ['away', 'xa', 'dnd', 'unavailable']:
                self.remove_participant(user1, vinebot)
            elif user2_status in ['away', 'xa', 'dnd', 'unavailable']:
                self.remove_participant(user2, vinebot)
            elif vinebot.is_active:
                self.send_presences(vinebot, vinebot.observers)
        party_vinebots = self.db_fetch_all_party_vinebots()
        for vinebot in party_vinebots:
            online_participants = []
            for participant in vinebot.participants:
                if not self.user_online(participant):
                    self.remove_participant(participant, vinebot)
                else:
                    online_participants.append(participant)
            if len(online_participants) > 2:
                self.send_presences(vinebot, online_participants)
                self.send_presences(vinebot, vinebot.observers)
        logging.info("Leaf started with %d pair_vinebots and %d party_vinebots" % (len(pair_vinebots), len(party_vinebots)))
    
    def handle_presence_available(self, presence):
        bot = Bot(presence['to'].user, self)
        if bot.is_vinebot:
            if presence['from'].user in bot.participants:
                if bot.is_active:  # either pair or party, and active bots always have both participants online
                    self.send_presences(bot, bot.everyone)
                elif self.user_online(bot.other_participant(presence['from'].user)):
                    self.send_presences(bot, bot.participants)
            elif presence['from'].user in bot.observers:
                if bot.is_active:
                    self.send_presences(bot, [presence['from'].user])
    
    def handle_presence_away(self, presence):
        bot = Bot(presence['to'].user, self)
        if bot.is_vinebot and presence['from'].user in bot.participants:
            if bot.is_party:
                self.send_presences(bot, bot.everyone)
            else:
                if bot.is_active:
                    self.remove_participant(presence['from'].user, bot)
                self.send_presences(bot, [presence['from'].user], pshow=self.user_status(bot.other_participant(presence['from'].user)))
                self.send_presences(bot, [bot.other_participant(presence['from'].user)], pshow=presence['type'])
    
    def handle_presence_unavailable(self, presence):
        bot = Bot(presence['to'].user, self)
        if bot.is_vinebot and presence['from'].user in bot.participants:
            if bot.is_party:
                alert_msg = '%s has disconnected and left the conversation' % presence['from'].user
                self.send_presences(bot, [presence['from'].user])
            else:
                alert_msg = ''
                self.send_presences(bot, bot.participants.difference([presence['from'].user]), pshow='unavailable')
            if bot.is_active:
                self.remove_participant(presence['from'].user, bot, alert_msg)
    
    def handle_msg(self, msg):
        if msg['type'] in ('chat', 'normal'):
            bot = Bot(msg['to'].user, self)
            if not bot.is_vinebot and not msg['from'].bare in (constants.admin_users + [constants.graph_xmpp_user]):
                parent_message_id = self.db_log_message(msg['to'].user, msg['from'].user, [], msg['body'])
                self.send_reply(msg, 'Sorry, you can\'t send messages to %s.' % msg['to'], parent_message_id=parent_message_id)
            elif self.commands.is_command(msg['body']):
                parent_command_id, response = self.commands.handle_command(msg['from'], msg['body'], bot)
                if not parent_command_id:  # if the command has some sort of error
                    command_name, arg_string = self.commands.parse_command(msg['body'])
                    parent_command_id = self.db_log_command(bot.user, msg['from'].user, command_name, None, arg_string, is_valid=False)
                self.send_reply(msg, response, parent_command_id=parent_command_id)
            elif msg['from'].bare in (constants.admin_users + [constants.graph_xmpp_user]):    
                parent_message_id = self.db_log_message(msg['to'].user, msg['from'].user, [], msg['body'])
                self.send_reply(msg, 'Sorry, this leaf only accepts /commands from admins.', parent_message_id=parent_message_id)
            else:
                if msg['from'].user in bot.participants:
                    if not bot.is_active:
                        user1, user2 = bot.participants  # in case one user is away or offline
                        user1_status = self.user_status(user1)
                        user2_status = self.user_status(user2)
                        self.send_presences(bot, [user1], pshow=user2_status)
                        self.send_presences(bot, [user2], pshow=user1_status)
                        if user1_status != 'unavailable' and user2_status != 'unavailable':
                            self.db_activate_pair_vinebot(bot.user, True)
                            self.update_rosters(set([]), bot.participants, bot.user, False)
                            self.send_presences(bot, bot.observers)
                            self.broadcast_msg(msg, bot.participants, sender=msg['from'].user)
                        else:
                            parent_message_id = self.db_log_message(bot.user, msg['from'].user, [], msg['body'])
                            self.send_reply(msg, 'Sorry, this users is offline.', parent_message_id=parent_message_id)
                    else:
                        self.broadcast_msg(msg, bot.participants, sender=msg['from'].user)
                elif msg['from'].user in bot.observers:
                    if bot.is_active:
                        self.add_participant(msg['from'].user, bot, '%s has joined the conversation' % msg['from'].user)
                        self.broadcast_msg(msg, bot.participants, sender=msg['from'].user)
                    else:    
                        parent_message_id = self.db_log_message(bot.user, msg['from'].user, [], msg['body'])
                        self.send_reply(msg, 'Sorry, this conversation has ended for now.', parent_message_id=parent_message_id)
                else:
                    parent_message_id = self.db_log_message(bot.user, msg['from'].user, [], msg['body'])
                    if bot.is_active:
                        self.send_reply(msg, 'Sorry, only friends of participants can join this conversation.', parent_message_id=parent_message_id)
                    else:    
                        self.send_reply(msg, 'Sorry, this conversation has ended.', parent_message_id=parent_message_id)
    
    def handle_chatstate(self, msg):
        bot = Bot(msg['to'].user, self)
        if bot.is_vinebot and msg['from'].user in bot.participants and bot.is_active:
            #LATER try this without using the new_msg to strip the body, see SleekXMPP chat logs
            new_msg = msg.__copy__()
            del new_msg['body']
            self.broadcast_msg(new_msg, bot.participants.union(bot.observers), sender=msg['from'].user)
    
    
    ##### user /commands
    def user_joined(self, parent_command_id, user, vinebot):
        if vinebot.topic:
            alert_msg = '%s has joined the conversation, but didn\'t want to interrupt. The current topic is:\n\t%s' % (user, vinebot.topic)
        else:
            alert_msg = '%s has joined the conversation, but didn\'t want to interrupt. No one has set the topic.' % user
        self.add_participant(user, vinebot, alert_msg, parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def user_left(self, parent_command_id, user, vinebot):
        self.remove_participant(user, vinebot, '%s has left the conversation' % user, parent_command_id=parent_command_id)
        if not vinebot.is_party and vinebot.is_active:  # revert to previous status states
            user1, user2 = vinebot.participants
            self.send_presences(vinebot, [user1], pshow=self.user_status(user2))
            self.send_presences(vinebot, [user2], pshow=self.user_status(user1))
        return parent_command_id, 'You left the conversation.'
    
    def invite_user(self, parent_command_id, inviter, vinebot, invitee):
        if inviter == invitee:
            raise ExecutionError, 'you can\'t invite yourself.'
        if not self.user_online(invitee):
            raise ExecutionError, '%s is offline and can\'t be invited.' % invitee
        if vinebot.topic:
            alert_msg = '%s has invited %s to the conversation. The current topic is:\n\t%s' % (inviter, invitee, vinebot.topic)
        else:
            alert_msg = '%s has invited %s to the conversation. No one has set the topic.' % (inviter, invitee)
        self.add_participant(invitee, vinebot, alert_msg, parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def kick_user(self, parent_command_id, kicker, vinebot, kickee):
        if kicker == kickee:
            raise ExecutionError, 'you can\'t kick yourself. Maybe you meant /leave?'
        if len(vinebot.participants) == 2:
            raise ExecutionError, 'you can\'t kick someone if it\s just the two of you. Maybe you meant /leave?'
        self.remove_participant(kickee, vinebot, '%s was kicked from the conversation by %s' % (kickee, kicker), parent_command_id=parent_command_id)
        msg = self.Message()
        body = '%s has kicked you from the conversation' % kicker
        msg['body'] = body
        msg['from'] = '%s@%s' % (vinebot.user, self.boundjid.bare)
        msg['to'] = '%s@%s' % (kickee, constants.server)
        msg.send()
        self.db_log_message(vinebot.user, None, [kickee], body, parent_command_id=parent_command_id)
        return parent_command_id, ''
    
    def list_participants(self, parent_command_id, user, vinebot):
        participants = vinebot.participants.copy()
        if user in participants:  # admins aren't participants
            participants.remove(user)
            participants = list(participants)
            participants.append('you')
        if vinebot.topic:
            return parent_command_id, 'The current participants are:\n%s\nThe current topic is:\n\t%s' % (
                    ''.join(['\t%s\n' % user for user in participants]).strip('\n'), vinebot.topic)
        else:
            return parent_command_id, 'The current participants are:\n%s\nNo one has set the topic.' % (
                    ''.join(['\t%s\n' % user for user in participants]).strip('\n'))
    
    def list_observers(self, parent_command_id, user, vinebot):
        observers = filter(self.user_online, vinebot.observers)
        observer_string = ''.join(['\t%s\n' % user for user in observers]).strip('\n')
        if vinebot.is_active:
            if len(observers) > 1:
                response = 'These users are online and can see this conversation:\n' + observer_string
            elif len(observers) == 1:
                response = '%s is online and can see this conversation.' % observers[0]
            else:
                response = 'There are no users online that can see this conversaton.'
        else:
            if len(observers) > 1:
                response = 'If this conversation were active, then these online users would see it:\n' + observer_string
            elif len(observers) == 1:
                response = 'If this conversation were active, then %s would see it.' % observers[0]
            else:
                response = 'There are no users online that can see this conversaton.'
        return parent_command_id, response
    
    def whisper_msg(self, parent_command_id, sender, vinebot, recipient, body):
        if recipient == sender:
            raise ExecutionError, 'you can\'t whisper to youerself.'
        recipient_jid = '%s@%s' % (recipient, constants.server)
        if recipient not in vinebot.participants and recipient_jid not in constants.admin_users:
            raise ExecutionError, 'you can\'t whisper to someone who isn\'t a participant in this conversation.'
        self.send_message(mto=recipient_jid,
                          mfrom='%s@%s' % (vinebot.user, self.boundjid.bare),
                          mbody='[%s, whispering] %s' % (sender, body))
        self.db_log_message(vinebot.user, sender, [recipient], body, parent_command_id=parent_command_id)
        if len(vinebot.participants) == 2:
            return parent_command_id, 'You whispered to %s, but it\'s just the two of you here so no one would have heard you anyway...' % recipient
        else:
            return parent_command_id, 'You whispered to %s, and no one noticed!' % recipient
    
    def set_topic(self, parent_command_id, sender, vinebot, topic):
        if topic and len(topic) > 100:
            raise ExecutionError, 'topics can\'t be longer than 100 characters, and this was %d characters.' % len(topic)
        else:
            self.db_set_topic(vinebot.user, topic)
            vinebot.topic = ((topic, datetime.now()) if topic else None)
            if vinebot.is_active:
                self.send_presences(vinebot, vinebot.participants)
            else:
                user1, user2 = vinebot.participants
                user1_status = self.user_status(user1)
                user2_status = self.user_status(user2)
                self.send_presences(vinebot, [user1], pshow=user2_status)
                self.send_presences(vinebot, [user2], pshow=user1_status)
            if vinebot.topic:
                self.broadcast_alert('%s has set the topic of the conversation:\n\t%s' % (sender, vinebot.topic),
                                     vinebot.participants,
                                     vinebot.user,
                                     parent_command_id)
            else:
                self.broadcast_alert('%s has cleared the topic of conversation.' % sender,
                                     vinebot.participants,
                                     vinebot.user,
                                     parent_command_id)
            return parent_command_id, ''
    
    
    ##### admin /commands
    def create_user(self, parent_command_id, user, password):
        self.db_create_user(user)
        self.register(user, password)
        return parent_command_id, None
    
    def destroy_user(self, parent_command_id, user):
        self.db_destroy_user(user)
        self.unregister(user)
        return parent_command_id, None
    
    def create_friendship(self, parent_command_id, user1, user2):
        vinebot_user = self.db_create_pair_vinebot(user1, user2)
        if vinebot_user:
            participants = set([user1, user2])
            vinebot = Bot(vinebot_user, self, participants=participants, is_active=False, is_party=False)
            self.add_rosteritem(user1, vinebot_user, self.get_nick(participants, user1))
            self.add_rosteritem(user2, vinebot_user, self.get_nick(participants, user2))
            self.send_presences(vinebot, [user1], pshow=self.user_status(user2))
            self.send_presences(vinebot, [user2], pshow=self.user_status(user1))
            # update observer lists accordingly
            for active_vinebot in self.db_fetch_user_pair_vinebots(user2):
                self.add_rosteritem(user1, active_vinebot[1], self.get_nick(active_vinebot[0]))
            for active_vinebot in self.db_fetch_user_pair_vinebots(user1):
                self.add_rosteritem(user2, active_vinebot[1], self.get_nick(active_vinebot[0]))
        return parent_command_id, None
    
    def destroy_friendship(self, parent_command_id, user1, user2):
        destroyed_vinebot_user, is_active = self.db_delete_pair_vinebot(user1, user2)
        self.delete_rosteritem(user1, destroyed_vinebot_user)
        self.delete_rosteritem(user2, destroyed_vinebot_user)
        if is_active:
            for observer in self.db_fetch_observers([user1, user2]):
                self.delete_rosteritem(observer, destroyed_vinebot_user)
        for active_vinebot in self.db_fetch_user_pair_vinebots(user2):
            if user1 not in self.db_fetch_observers(active_vinebot[0]):
                self.delete_rosteritem(user1, active_vinebot[1])
        for active_vinebot in self.db_fetch_user_pair_vinebots(user1):
            if user2 not in self.db_fetch_observers(active_vinebot[0]):
                self.delete_rosteritem(user2, active_vinebot[1])
        return parent_command_id, None
    
    def prune_roster(self, parent_command_id, user):
        errors = []
        for roster_user, roster_nick in self.get_roster(user):
            bot = Bot(roster_user, self)
            if bot.is_vinebot and user in bot.participants:
                correct_nick = self.get_nick(bot.participants, user)
                if roster_nick != correct_nick:
                    errors.append('Incorrect nickname of %s for %s in roster of participant %s, should be %s.' %
                        (roster_nick, roster_user, user, correct_nick))
                    self.add_rosteritem(user, roster_user, correct_nick)
            elif bot.is_vinebot and user in bot.observers:
                if bot.is_active:
                    correct_nick = self.get_nick(bot.participants)
                    if roster_nick != correct_nick:
                        errors.append('Incorrect nickname of %s for %s in roster of observer %s, should be %s.' %
                            (roster_nick, roster_user, user, correct_nick))
                        self.add_rosteritem(user, roster_user, correct_nick)
                else:
                    errors.append('%s in roster of %s: inactive vinebots shouldn\'t have observers!' %
                        (roster_user, user))
                    self.delete_rosteritem(user, roster_user)
            else:
                errors.append('Incorrect roster item %s for %s: participants=%s, is_active=%s, is_party=%s' %
                    (roster_user, user, bot.participants, bot.is_active, bot.is_party))
                self.delete_rosteritem(user, roster_user)
        if errors:
            return parent_command_id, '\n'.join(errors)
        else:
            return parent_command_id, 'No invalid roster items found.'
    
    def friendships(self, parent_command_id, user=None):
        if user:
            friends = self.db_fetch_user_friends(user)
            if len(friends) <= 0:
                return parent_command_id, '%s doesn\'t have any friends.' % user
            output = '%s has %d friends:\n\t' % (user, len(friends))
            output += '\n\t'.join(friends)
        else:
            pair_vinebots = self.db_fetch_all_pair_vinebots()
            if len(pair_vinebots) <= 0:
                return parent_command_id, 'No pair vinebots found. Use /new_friendship to create one for two users.'    
            output = 'There are %d friendships:' % len(pair_vinebots)
            for vinebot in pair_vinebots:
                user1, user2 = vinebot.participants
                output += '\n\t%s\n\t%s\n\t\t\t\t\t%s@%s\n\t\t\t\t\t%s' % (user1,
                                                                           user2,
                                                                           vinebot.user,
                                                                           self.boundjid.bare,
                                                                           'active' if vinebot.is_active else 'inactive')
        return parent_command_id, output
    
    
    ##### helper functions
    def send_presences(self, vinebot, recipients, pshow='available'):
        for recipient in recipients:
            self.sendPresence(pfrom='%s@%s' % (vinebot.user, self.boundjid.bare),
                                pto='%s@%s' % (recipient, constants.server),
                                pshow=None if pshow == 'available' else pshow,
                                pstatus=unicode(vinebot.topic) if vinebot.topic else None)
    
    def get_vinebot_user(self, uuid_or_bytes):
        try:
            return '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid_or_bytes))
        except AttributeError:
            return '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid.UUID(bytes=uuid_or_bytes)))
    
    def broadcast_msg(self, msg, participants, sender=None, parent_command_id=None):
        body = msg['body']
        vinebot_jid = msg['to']
        del msg['id']
        del msg['html'] #LATER fix html, but it's a pain with reformatting
        msg['from'] = vinebot_jid
        if body and body != '':
            if sender:
                msg['body'] = '[%s] %s' % (sender, body)
            else:
                msg['body'] = '*** %s' % (body)
        recipients = []
        for participant in participants:
            if not sender or sender != participant:
                new_msg = msg.__copy__()
                new_msg['to'] = '%s@%s' % (participant, constants.server)
                new_msg.send()
                recipients.append(participant)
        self.db_log_message(vinebot_jid.user, sender, recipients, body, parent_command_id)
    
    def broadcast_alert(self, body, participants, vinebot_user, parent_command_id):
        msg = self.Message()
        msg['body'] = body
        msg['to'] = '%s@%s' % (vinebot_user, self.boundjid.bare)  # this will get moved to 'from' in broadcast_msg
        self.broadcast_msg(msg, participants, parent_command_id=parent_command_id)
    
    def send_reply(self, msg, body, parent_message_id=None, parent_command_id=None):
        msg.reply(body).send()
        if not parent_message_id and not parent_command_id:
            logging.error('Attempted to send reply "%s" with no parent. msg=%s' % (body, msg))
        else:
            self.db_log_message(msg['from'].user,
                                None,
                                [msg['to'].user],
                                body,
                                parent_message_id=parent_message_id,
                                parent_command_id=parent_command_id)
    
    def get_nick(self, participants, viewing_participant=None):  # observers all see the same nickname, so this is None for them
        if len(participants) < 2:
            return 'error'
        else:
            if viewing_participant:
                participants = participants.difference([viewing_participant])
                if len(participants) == 1:
                    return participants.pop()
                else:
                    participants = list(participants)
                    participants.insert(0, 'you')
            else:
                participants = list(participants)
            comma_sep = ''.join([', %s' % participant for participant in participants[1:-1]])
            return '%s%s & %s' % (participants[0], comma_sep, participants[-1])
    
    def update_rosters(self, old_participants, new_participants, vinebot_user, participants_changed):
        observer_nick = self.get_nick(new_participants)
        # First, create the old and new lists of observers
        old_observers = self.db_fetch_observers(old_participants)
        new_observers = self.db_fetch_observers(new_participants)
        # Then, update the participants
        if participants_changed:
            for old_participant in old_participants.difference(new_observers).difference(new_participants):
                self.delete_rosteritem(old_participant, vinebot_user)
            for new_participant in new_participants:
                self.add_rosteritem(new_participant, vinebot_user, self.get_nick(new_participants, new_participant))
        # Finally, update the observers
        for old_observer in old_observers.difference(new_participants).difference(new_observers):
            self.delete_rosteritem(old_observer, vinebot_user)
        for new_observer in new_observers.difference(new_participants):
            self.add_rosteritem(new_observer, vinebot_user, observer_nick)
    
    def add_participant(self, user, vinebot, alert_msg, parent_command_id=None):
        if user in vinebot.participants:
            raise ExecutionError, '%s is already part of this conversation!' % user
        old_participants = vinebot.participants.copy()
        vinebot.participants.add(user)
        if vinebot.is_party:
            self.db_add_participant(user, vinebot.user)
        else:
            new_pair_vinebot_user = self.db_create_party_vinebot(vinebot.participants, vinebot.user)
            new_pair_vinebot = Bot(new_pair_vinebot_user, self, participants=old_participants, is_active=False, is_party=False)
            user1, user2 = old_participants
            self.add_rosteritem(user1, new_pair_vinebot_user, user2)
            self.add_rosteritem(user2, new_pair_vinebot_user, user1)
            self.send_presences(new_pair_vinebot, [user1], pshow=self.user_status(user2))
            self.send_presences(new_pair_vinebot, [user2], pshow=self.user_status(user1))   
            self.send_presences(vinebot, vinebot.everyone)
        self.update_rosters(old_participants, vinebot.participants, vinebot.user, True)
        self.broadcast_alert(alert_msg, vinebot.participants, vinebot.user, parent_command_id)
    
    def remove_participant(self, user, vinebot, alert_msg='', parent_command_id=None):
        if user in vinebot.participants:
            if vinebot.is_party:
                if len(vinebot.participants) >= 3:
                    new_participants = vinebot.participants.difference([user])
                    if len(vinebot.participants) == 3:
                        pair_vinebot_user, pair_is_active = self.db_fetch_pair_vinebot(*list(new_participants))
                        if pair_vinebot_user and not pair_is_active:
                            self.db_fold_party_into_pair(vinebot.user, pair_vinebot_user)
                            for participant in vinebot.participants:
                                self.delete_rosteritem(participant, pair_vinebot_user)
                    self.update_rosters(vinebot.participants, new_participants, vinebot.user, True)
                    self.db_remove_participant(user, vinebot.user)
                else:
                    new_participants = set([])
                    self.update_rosters(vinebot.participants, new_participants, vinebot.user, True)
                    self.db_delete_party_vinebot(vinebot.user)
                # only broadcast the alert for parties
                self.broadcast_alert(alert_msg, new_participants, vinebot.user, parent_command_id)
            else:
                if vinebot.is_active:
                    self.db_activate_pair_vinebot(vinebot.user, False)
                    self.update_rosters(vinebot.participants, set([]), vinebot.user, False)
    
    
    ##### ejabberdctl XML RPC commands
    def register(self, user, password):
        self.xmlrpc_command('register', {
            'user': user,
            'host': constants.server,
            'password': password
        })
    
    def unregister(self, user):
        self.xmlrpc_command('unregister', {
            'user': user,
            'host': constants.server,
        })
    
    def add_rosteritem(self, user, vinebot_user, nick):
        self.xmlrpc_command('add_rosteritem', {
            'localuser': user,
            'localserver': constants.server,
            'user': vinebot_user,
            'server': self.boundjid.bare,
            'group': constants.roster_group,
            'nick': nick,
            'subs': 'both'
        })
    
    def delete_rosteritem(self, user, vinebot_user):
        self.xmlrpc_command('delete_rosteritem', {
            'localuser': user,
            'localserver': constants.server,
            'user': vinebot_user,
            'server': self.boundjid.bare
        })
    
    def get_roster(self, user):
        rosteritems = self.xmlrpc_command('get_roster', {
            'user': user, 
            'host': constants.server})
        roster = []
        for rosteritem in rosteritems['contacts']:
            rosteritem = rosteritem['contact']
            if rosteritem[2]['subscription'] != 'both':
                logging.warning('Incorrect roster subscription for: %s' % rosteritem)
            if rosteritem[4]['group'] != constants.roster_group:
                logging.warning('Incorrect roster group for rosteritem: %s' % rosteritem)
            user = rosteritem[0]['jid'].split('@')[0]
            if not user.startswith(constants.vinebot_prefix):
                logging.warning("Non-vinebot user(s) found on roster for user %s!\n%s" % (user, rosteritems))
            roster.append((user, rosteritem[1]['nick']))
        return roster
    
    def user_online(self, user):
        return self.user_status(user) != 'unavailable'  # this function is useful for list filters
    
    def user_status(self, user):
        try:              
            res = self.xmlrpc_command('user_sessions_info', {
                'user': user,
                'host': constants.server
            })
            if len(res['sessions_info']) > 0:
                return res['sessions_info'][0]['session'][6]['status']
            else:
                return 'unavailable'
        except xmlrpclib.ProtocolError, e:
            logging.error('ProtocolError in is_online, assuming %s is unavailable: %s' % (user, str(e)))
            return 'unavailable'
    
    def xmlrpc_command(self, command, data):
        fn = getattr(self.xmlrpc_server, command)
        logging.debug('XMLRPC %s: %s' % (command, str(data)))
        return fn({
            'user': '%s%s' % (constants.leaf_xmlrpc_jid_prefix, self.id),
            'server': constants.server,
            'password': constants.leaf_xmlrpc_password
        }, data)
    
    
    ##### database queries and connection management
    def db_create_pair_vinebot(self, user1, user2):
        vinebot_user, is_active = self.db_fetch_pair_vinebot(user1, user2)
        if vinebot_user:
            raise ExecutionError, 'these users are already friends.'
        vinebot_uuid = uuid.uuid4()
        try:
            self.db_execute("""INSERT INTO pair_vinebots (id, user1, user2)
                               VALUES (%(id)s,
                                       (SELECT id FROM users WHERE name = %(user1)s LIMIT 1),
                                       (SELECT id FROM users WHERE name = %(user2)s LIMIT 1)
                                      )""", {'id': vinebot_uuid.bytes, 'user1': user1, 'user2': user2})
            return self.get_vinebot_user(vinebot_uuid)
        except IntegrityError:
            raise ExecutionError, 'there was an IntegrityError - are you sure both users exist?'
        except OperationalError:
            raise ExecutionError, 'there was an OperationalError - are you sure both users exist?'
    
    def db_delete_pair_vinebot(self, user1, user2):
        vinebot_user, is_active = self.db_fetch_pair_vinebot(user1, user2)
        if not vinebot_user:
            raise ExecutionError, 'No friendship found.'
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("DELETE FROM pair_vinebots WHERE id = %(id)s", {'id': vinebot_uuid.bytes})
        self.db_execute("DELETE FROM topics WHERE vinebot = %(vinebot_id)s", {'vinebot_id': vinebot_uuid.bytes})
        return (vinebot_user, is_active)
    
    def db_create_party_vinebot(self, participants, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        new_vinebot_uuid = uuid.uuid4()
        self.db_execute("""UPDATE pair_vinebots SET id = %(new_id)s, is_active = 0
                           WHERE id = %(old_id)s""", {'new_id': new_vinebot_uuid.bytes, 'old_id': vinebot_uuid.bytes})
        for participant in participants:  #LATER use cursor.executemany()
            self.db_add_participant(participant, vinebot_user)
        return self.get_vinebot_user(new_vinebot_uuid)
    
    def db_delete_party_vinebot(self, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("DELETE FROM party_vinebots WHERE id = %(id)s", {'id': vinebot_uuid.bytes})
        self.db_execute("DELETE FROM topics WHERE vinebot = %(vinebot_id)s", {'vinebot_id': vinebot_uuid.bytes})
    
    def db_add_participant(self, user, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("""INSERT INTO party_vinebots (id, user)
                           VALUES (%(id)s, (SELECT id FROM users 
                                            WHERE name = %(user)s 
                                            LIMIT 1))""", {'id': vinebot_uuid.bytes, 'user': user})
    
    def db_remove_participant(self, user, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("""DELETE FROM party_vinebots 
                           WHERE user = (SELECT id FROM users WHERE name = %(user)s)
                           AND id = %(id)s""", {'id': vinebot_uuid.bytes, 'user': user})
    
    def db_fold_party_into_pair(self, party_vinebot_user, pair_vinebot_user):
        party_vinebot_id = party_vinebot_user.replace(constants.vinebot_prefix, '')
        party_vinebot_uuid = shortuuid.decode(party_vinebot_id)
        pair_vinebot_id = pair_vinebot_user.replace(constants.vinebot_prefix, '')
        pair_vinebot_uuid = shortuuid.decode(pair_vinebot_id)
        self.db_execute("UPDATE pair_vinebots SET id = %(new_id)s, is_active = %(activate)s  WHERE id = %(old_id)s", {
            'new_id': party_vinebot_uuid.bytes,
            'old_id': pair_vinebot_uuid.bytes,
            'activate': True})
        self.db_execute("DELETE FROM party_vinebots WHERE id = %(id)s", {'id': party_vinebot_uuid.bytes})
        self.db_execute("DELETE FROM topics WHERE vinebot = %(vinebot_id)s", {'vinebot_id': pair_vinebot_uuid.bytes})
    
    def db_fetch_all_pair_vinebots(self):
        pair_vinebots = self.db_execute_and_fetchall("""SELECT  pair_vinebots.id,
                                                                users_1.name,
                                                                users_2.name,
                                                                pair_vinebots.is_active,
                                                                topics.body,
                                                                topics.created
                                                        FROM users AS users_1, users AS users_2, pair_vinebots
                                                        LEFT JOIN topics ON pair_vinebots.id = topics.vinebot
                                                        WHERE pair_vinebots.user1 = users_1.id
                                                        AND   pair_vinebots.user2 = users_2.id""")
        return [Bot(self.get_vinebot_user(pair_vinebot[0]),
                    self,
                    participants=set([pair_vinebot[1], pair_vinebot[2]]),
                    is_active=(pair_vinebot[3] == 1),
                    is_party=False,
                    topic=(pair_vinebot[-2:] if pair_vinebot[4] else '')
                ) for pair_vinebot in pair_vinebots]
    
    def db_fetch_all_party_vinebots(self):
        party_vinebots = self.db_execute_and_fetchall("""SELECT party_vinebots.id, GROUP_CONCAT(users.name), topics.body, topics.created
                                                         FROM users, party_vinebots
                                                         LEFT JOIN topics ON party_vinebots.id = topics.vinebot
                                                         WHERE party_vinebots.user = users.id""")
        return [Bot(self.get_vinebot_user(party_vinebot[0]),
                    self,
                    participants=set(party_vinebot[1].split(',')),
                    is_active=True,
                    is_party=True,
                    topic=(party_vinebot[-2:] if len(party_vinebot) > 3 and party_vinebot[3] else '')
                ) for party_vinebot in party_vinebots if party_vinebot and party_vinebot[0]]  # the query returns (None, None) if no rows are found
    
    def db_activate_pair_vinebot(self, vinebot_user, is_active):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("""UPDATE pair_vinebots SET is_active = %(is_active)s
                           WHERE id = %(id)s""", {'id': vinebot_uuid.bytes, 'is_active': is_active})
    
    def db_fetch_vinebot(self, vinebot_user):
        participants = set([])
        is_active = False
        is_party = False
        if vinebot_user.startswith(constants.vinebot_prefix):
            vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
            vinebot_uuid = shortuuid.decode(vinebot_id)
            pair_vinebot = self.db_execute_and_fetchall("""SELECT users_1.name, users_2.name, pair_vinebots.is_active
                              FROM users AS users_1, users AS users_2, pair_vinebots
                              WHERE pair_vinebots.id = %(id)s AND pair_vinebots.user1 = users_1.id AND pair_vinebots.user2 = users_2.id
                              LIMIT 1""", {'id': vinebot_uuid.bytes})
            if len(pair_vinebot) > 0:
                participants = set([pair_vinebot[0][0], pair_vinebot[0][1]])
                is_active = (pair_vinebot[0][2] == 1)
                is_party = False
            else:
                party_vinebot = self.db_execute_and_fetchall("""SELECT users.name FROM users, party_vinebots
                                  WHERE party_vinebots.id = %(id)s 
                                  AND party_vinebots.user = users.id""", {'id': vinebot_uuid.bytes}, strip_pairs=True)
                if len(party_vinebot) > 0:
                    participants = set(party_vinebot)
                    is_active = True
                    is_party = True
        return (participants, is_active, is_party)
    
    def db_fetch_pair_vinebot(self, user1, user2):
        pair_vinebot = self.db_execute_and_fetchall("""SELECT pair_vinebots.id, pair_vinebots.is_active
            FROM users AS users_1, users AS users_2, pair_vinebots
            WHERE (pair_vinebots.user1 = users_1.id AND users_1.name = %(user1)s
               AND pair_vinebots.user2 = users_2.id AND users_2.name = %(user2)s)
               OR (pair_vinebots.user1 = users_1.id AND users_1.name = %(user2)s
               AND pair_vinebots.user2 = users_2.id AND users_2.name = %(user1)s)
            """, {'user1': user1, 'user2': user2})
        if pair_vinebot and pair_vinebot[0]:
            if len(pair_vinebot) > 1:
                logging.error('Multiple pair_vinebots found for %s and %s; %s' % (user1, user2, pair_vinebots))
            return (self.get_vinebot_user(pair_vinebot[0][0]), pair_vinebot[0][1] == 1)
        else:
            return (None, False)
    
    def db_fetch_observers(self, participants):
        observers = set([])
        for participant in participants:
            observers = observers.union(self.db_fetch_user_friends(participant))
        return observers.difference(participants)
    
    def db_fetch_user_friends(self, user):
        return self.db_execute_and_fetchall("""SELECT users.name FROM users, pair_vinebots
                    WHERE (pair_vinebots.user1 = (SELECT id FROM users  WHERE name = %(user)s LIMIT 1)
                       AND pair_vinebots.user2 = users.id)
                    OR    (pair_vinebots.user2 = (SELECT id FROM users  WHERE name = %(user)s LIMIT 1)
                       AND pair_vinebots.user1 = users.id)""", {'user': user}, strip_pairs=True)
    
    def db_fetch_user_pair_vinebots(self, user, is_active=True):
        pair_vinebots = self.db_execute_and_fetchall("""SELECT users_1.name, users_2.name, pair_vinebots.id
                                                      FROM users AS users_1, users AS users_2, pair_vinebots
                                                     WHERE pair_vinebots.is_active = %(is_active)s
                                                       AND pair_vinebots.user1 = users_1.id 
                                                       AND pair_vinebots.user2 = users_2.id
                                                      AND (users_1.name = %(user)s 
                                                        OR users_2.name = %(user)s)""", {'user': user, 'is_active': is_active})
        active_vinebots = [(set([pair_vinebot[0], pair_vinebot[1]]), 
                            self.get_vinebot_user(pair_vinebot[2])
                           ) for pair_vinebot in pair_vinebots]
        active_vinebots.extend(self.db_fetch_user_party_vinebots(user))
        return active_vinebots
    
    def db_fetch_user_party_vinebots(self, user):
        party_vinebots = []
        party_vinebot_ids = self.db_execute_and_fetchall("""SELECT party_vinebots.id FROM party_vinebots
            WHERE party_vinebots.user = (SELECT id FROM users  WHERE name = %(user)s LIMIT 1)""", {'user': user}, strip_pairs=True)
        for party_vinebot_id in party_vinebot_ids:
            party_vinebot_user = self.get_vinebot_user(party_vinebot_id)
            participants, is_active, is_party = self.db_fetch_vinebot(party_vinebot_user)
            party_vinebots.append((participants, party_vinebot_user))
        return party_vinebots
    
    def db_create_user(self, user):
        try:
            self.db_execute("INSERT INTO users (name) VALUES (%(user)s)", {'user': user})
        except IntegrityError:
            raise ExecutionError, 'there was an IntegrityError - are you sure the user doesn\'t already exist?'
    
    def db_destroy_user(self, user):
        try:
            for friend in self.db_fetch_user_friends(user):
                self.destroy_friendship(user, friend)
            for party_vinebot_uuid in self.db_fetch_user_party_vinebots(user):
                vinebot_user = self.get_vinebot_user(party_vinebot_uuid)
                self.remove_participant(user, vinebot_user, '%s\'s account has been deleted.' % user)
            self.db_execute("DELETE FROM users WHERE name = %(user)s", {'user': user})
        except IntegrityError:
            raise ExecutionError, 'there was an IntegrityError - are you sure the user doesn\'t already exist?'
    
    def db_set_topic(self, vinebot_user, topic):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("DELETE FROM topics WHERE vinebot = %(vinebot_id)s", {'vinebot_id': vinebot_uuid.bytes})
        if topic:
            self.db_execute("""INSERT INTO topics (vinebot, body)
                               VALUES (%(vinebot_id)s, %(body)s)""", {'vinebot_id': vinebot_uuid.bytes, 'body': topic.encode('utf-8')})
    
    def db_fetch_topic(self, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        topic = self.db_execute_and_fetchall("SELECT body, created FROM topics WHERE vinebot = %(vinebot_id)s LIMIT 1",
                                     {'vinebot_id': vinebot_uuid.bytes})
        if topic and len(topic) > 0:
            return topic[0]
        else:
            return None
    
    def db_log_message(self, vinebot_user, sender, recipients, body, parent_message_id=None, parent_command_id=None):
        if not body or body == '':  # chatstate stanzas and some /command replies stanzas don't have a body, so don't log them
            return
        vinebot_bytes = None  # we still want to log the error response if a user sends a message to a non-vinebot leaf JID
        if vinebot_user.startswith(constants.vinebot_prefix):
            vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
            vinebot_bytes = shortuuid.decode(vinebot_id).bytes
        if sender:
            log_id = self.db_execute("""INSERT INTO messages (vinebot_id, sender_id, parent_message_id, parent_command_id, body)
                                        VALUES (
                                            %(vinebot_id)s,
                                            (SELECT id FROM users WHERE name = %(sender)s),
                                            %(parent_message_id)s,
                                            %(parent_command_id)s,
                                            %(body)s
                                        )""", {
                                            'vinebot_id': vinebot_bytes,
                                            'sender':  sender,
                                            'parent_message_id': parent_message_id,
                                            'parent_command_id': parent_command_id,
                                            'body': body.encode('utf-8')
                                        })
        else:
            log_id = self.db_execute("""INSERT INTO messages (vinebot_id, sender_id, parent_message_id, parent_command_id, body)
                                        VALUES (
                                            %(vinebot_id)s,
                                            %(sender_id)s,
                                            %(parent_message_id)s,
                                            %(parent_command_id)s,
                                            %(body)s
                                        )""", {
                                            'vinebot_id': vinebot_bytes,
                                            'sender_id':  None,
                                            'parent_message_id': parent_message_id,
                                            'parent_command_id': parent_command_id,
                                            'body': body.encode('utf-8')
                                        })
        for recipient in recipients:
            self.db_execute("""INSERT INTO message_recipients (message_id, recipient_id)
                               VALUES (
                                   %(log_id)s,
                                   (SELECT id FROM users WHERE name = %(recipient)s)
                               )""", {'log_id': log_id, 'recipient': recipient})
        return log_id
    
    def db_log_command(self, vinebot_user, sender, command_name, token, string, is_valid=True):
        vinebot_bytes = None
        if vinebot_user.startswith(constants.vinebot_prefix):
            vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
            vinebot_bytes = shortuuid.decode(vinebot_id).bytes
        if string:
            string = string.encode('utf-8')
        return self.db_execute("""INSERT INTO commands (vinebot_id, sender_id, command_name, is_valid, token, string)
                                  VALUES (
                                      %(vinebot_id)s,
                                      (SELECT id FROM users WHERE name = %(sender)s),
                                      %(command_name)s,
                                      %(is_valid)s,
                                      %(token)s,
                                      %(string)s
                                  )""", {
                                      'vinebot_id': vinebot_bytes,
                                      'sender':  sender,
                                      'command_name': command_name,
                                      'is_valid': is_valid,
                                      'token': token or None,
                                      'string': string or None
                                  })
    
    def db_execute_and_fetchall(self, query, data={}, strip_pairs=False):
        self.db_execute(query, data)
        fetched = self.cursor.fetchall()
        if fetched and len(fetched) > 0:
            if strip_pairs:
                return [result[0] for result in fetched]
            else:
                return fetched
        return []
    
    def db_execute(self, query, data={}):
        if not self.db or not self.cursor:
            logging.info("MySQL connection missing, attempting to reconnect and retry query")
            if self.db:
                self.db.close()
            self.db_connect()
        try:
            self.cursor.execute(query, data)
        except MySQLdb.OperationalError, e:
            if e[0] > 2000:  # error codes at http://dev.mysql.com/doc/refman/5.5/en/error-handling.html
                logging.info('MySQL OperationalError %d "%s" for query, will retry: %s' % (e[0], e[1], query % data))
                self.db_connect()  # Try again, but only once
                self.cursor.execute(query, data)
            else:
                raise e
        return self.db.insert_id()
    
    def db_connect(self):
        try:
            self.db = MySQLdb.connect(constants.db_host,
                                      '%s%s' % (constants.leaf_name, self.id),
                                      constants.leaf_mysql_password,
                                      constants.db_name)
            self.db.autocommit(True)
            self.cursor = self.db.cursor()
            logging.info("MySQL connection created")
        except MySQLdb.Error, e:
            logging.error('MySQL connection and/or cursor creation failed with %d: %s' % (e.args[0], e.args[1]))
            self.cleanup()
    
    def cleanup(self):
        if self.db:
            self.db.close()
        sys.exit(1)
    

if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)
    optp.add_option("-i", "--id", dest="leaf_id",
                    help="Leaf id (must correspond to ejabberd.cfg)")
    opts, args = optp.parse_args()
    
    logging.basicConfig(level=opts.loglevel,
                        format='%%(asctime)-15s leaf%(leaf_id)-3s %%(levelname)-8s %%(message)s' % {'leaf_id': opts.leaf_id})
    
    if opts.leaf_id is None:
        opts.leaf_id = raw_input("Leaf ID: ")
    xmpp = LeafComponent(opts.leaf_id)
    
    if xmpp.connect(constants.server_ip, constants.component_port):
        xmpp.process(block=True)
        xmpp.cleanup()
        logging.info("Done")
    else:    
        logging.error("Unable to connect")
