#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
from MySQLdb import IntegrityError
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
        def is_admin(sender, recipient):
            return sender.bare in constants.admin_users
        def is_participant(sender, recipient):
            participants, is_active, is_party = self.db_fetch_vinebot(recipient.user)
            return sender.user in participants
        def is_admin_or_participant(sender, recipient):
            return is_admin(sender, recipient) or is_participant(sender, recipient)
        # Argument transformations for /commands
        def has_none(sender, recipient, arg_string, arg_tokens):
            if len(arg_tokens) == 0:
                return []
            return False
        def sender_recipient(sender, recipient, arg_string, arg_tokens):
            if len(arg_tokens) == 0:
                return [sender.user, recipient.user]
            return False
        def sender_recipient_token(sender, recipient, arg_string, arg_tokens):            
            if len(arg_tokens) == 1:
                return [sender.user, recipient.user, arg_tokens[0]]
            return False
        def sender_recipient_token_string(sender, recipient, arg_string, arg_tokens):
            if len(arg_tokens) >= 2:
                return [sender.user, recipient.user, arg_tokens[0], arg_string.partition(arg_tokens[0])[2].strip()]
            return False
        def token(sender, recipient, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                return [arg_tokens[0]]
            return False
        def token_token(sender, recipient, arg_string, arg_tokens):
            if len(arg_tokens) == 2:
                return [arg_tokens[0], arg_tokens[1]]
            return False
        # Register vinebot commands
        self.commands.add(SlashCommand(command_name     = 'leave',
                                       text_arg_format  = '',
                                       text_description = 'Leave this conversation.',
                                       validate_sender  = is_participant,
                                       transform_args   = sender_recipient,
                                       action           = self.user_left))                  
        self.commands.add(SlashCommand(command_name     = 'invite',
                                       text_arg_format  = 'username',
                                       text_description = 'Invite a user to this conversation.',
                                       validate_sender  = is_admin_or_participant,
                                       transform_args   = sender_recipient_token,
                                       action           = self.invite_user))
        self.commands.add(SlashCommand(command_name     = 'kick',
                                       text_arg_format  = 'username',
                                       text_description = 'Kick a user out of this conversation.',
                                       validate_sender  = is_admin_or_participant,
                                       transform_args   = sender_recipient_token,
                                       action           = self.kick_user))
        self.commands.add(SlashCommand(command_name     = 'list',
                                       text_arg_format  = '',
                                       text_description = 'List the participants in this conversation.',
                                       validate_sender  = is_admin_or_participant,
                                       transform_args   = sender_recipient,
                                       action           = self.list_participants))
        self.commands.add(SlashCommand(command_name     = 'observers',
                                       text_arg_format  = '',
                                       text_description = 'List the observers of this conversation.',
                                       validate_sender  = is_admin_or_participant,
                                       transform_args   = sender_recipient,
                                       action           = self.list_observers))
        self.commands.add(SlashCommand(command_name     = 'whisper',
                                       text_arg_format  = 'username message to be sent to that user',
                                       text_description = 'Whisper a quick message to only one other participant.',
                                       validate_sender  = is_admin_or_participant,
                                       transform_args   = sender_recipient_token_string,
                                       action           = self.whisper_msg))
        # Register admin commands
        self.commands.add(SlashCommand(command_name     = 'new_user',
                                       text_arg_format  = 'username password',
                                       text_description = 'Create a new user in both ejabberd and the Vine database.',
                                       validate_sender  = is_admin,
                                       transform_args   = token_token,
                                       action           = self.create_user))
        self.commands.add(SlashCommand(command_name     = 'del_user',
                                       text_arg_format  = 'username',
                                       text_description = 'Unregister a user in ejabberd and remove her from the Vine database.',
                                       validate_sender  = is_admin,
                                       transform_args   = token,
                                       action           = self.destroy_user))
        self.commands.add(SlashCommand(command_name     = 'new_friendship',
                                       text_arg_format  = 'username1 username2',
                                       text_description = 'Create a friendship between two users.',
                                       validate_sender  = is_admin,
                                       transform_args   = token_token,
                                       action           = self.create_friendship))
        self.commands.add(SlashCommand(command_name     = 'del_friendship',
                                       text_arg_format  = 'username1 username2',
                                       text_description = 'Delete a friendship between two users.',
                                       validate_sender  = is_admin,
                                       transform_args   = token_token,
                                       action           = self.destroy_friendship))
        self.commands.add(SlashCommand(command_name     = 'prune',
                                       text_arg_format  = 'username',
                                       text_description = 'Remove old, unused vinebots from a user\'s roster.',
                                       validate_sender  = is_admin,
                                       transform_args   = token,
                                       action           = self.prune_roster))
        self.commands.add(SlashCommand(command_name     = 'friendships',
                                       text_arg_format  = '',
                                       text_description = 'List all current friendships.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_none,
                                       action           = self.friendships))
        # Add event handlers
        self.add_event_handler("session_start", self.handle_start)
        self.del_event_handler('presence_probe', self._handle_probe)
        self.add_event_handler('presence_probe', self.handle_probe)
        self.add_event_handler('presence_available', self.handle_presence_available)
        self.add_event_handler('presence_unavailable', self.handle_presence_unavailable)
        self.add_event_handler('message', self.handle_msg)
        for state in ['active', 'inactive', 'gone', 'composing', 'paused']:
            self.add_event_handler('chatstate_%s' % state, self.handle_chatstate)
    
    def disconnect(self, *args, **kwargs):
        #LATER check if other leaves are online, since otherwise we don't need to do this.
        pair_vinebots = self.db_fetch_all_pair_vinebots()
        party_vinebots = self.db_fetch_all_party_vinebots()
        for vinebot_user, participants, is_active in pair_vinebots + party_vinebots:
            for participant in participants:
                self.sendPresence(pfrom='%s@%s' % (vinebot_user, self.boundjid.bare),
                                  pto='%s@%s' % (participant, constants.server),
                                  pshow='unavailable')
        kwargs['wait'] = True
        super(LeafComponent, self).disconnect(*args, **kwargs)
    
    ##### event handlers
    def handle_start(self, event):
        #LATER check if other leaves are online, since otherwise we don't need to do this.
        pair_vinebots = self.db_fetch_all_pair_vinebots()
        for vinebot_user, participants, is_active in pair_vinebots:
            user1_online, user2_online = self.send_presence_for_pair_vinebot(participants[0], participants[1], vinebot_user)
            if is_active:
                if user1_online and user2_online:
                    for observer in self.db_fetch_observers(participants):
                        self.sendPresence(pfrom=vinebot_user,
                                          pto='%s@%s' % (observer, constants.server))
                else:
                    self.remove_participant(participants[1] if user1_online else participants[0], vinebot_user)
        party_vinebots = self.db_fetch_all_party_vinebots()
        for vinebot_user, participants, is_active in party_vinebots:
            online_participants = []
            for participant in participants:
                if not self.user_online(participant):
                    self.remove_participant(participant, vinebot_user)
                else:
                    online_participants.append(participant)
            if len(online_participants) > 2:
                for online_participants in online_participants:
                    self.sendPresence(pfrom='%s@%s' % (vinebot_user, self.boundjid.bare),
                                      pto='%s@%s' % (online_participants, constants.server))
        logging.info("Leaf started with %d pair_vinebots and %d party_vinebots" % (len(pair_vinebots), len(party_vinebots)))
    
    def handle_probe(self, presence):
        self.sendPresence(pfrom=presence['to'], pto=presence['from'])
    
    def handle_presence_available(self, presence):
        if presence['to'].user.startswith(constants.vinebot_prefix):
            participants, is_active, is_party = self.db_fetch_vinebot(presence['to'].user)
            if is_active:  # if it's active, we should always send out the presence
                self.sendPresence(pfrom=presence['to'], pto=presence['from'])
                if presence['from'].user in participants:
                    participants.remove(presence['from'].user)
                    for participant in participants:
                        self.sendPresence(pfrom=presence['to'], pto='%s@%s' % (participant, constants.server))
            else:  # only pairs are inactive, so make sure both users are online
                if presence['from'].user in participants:
                    other_participant = participants.difference([presence['from'].user]).pop()
                    if self.user_online(other_participant):
                        self.sendPresence(pfrom=presence['to'], pto=presence['from'])
                        self.sendPresence(pfrom=presence['to'], pto='%s@%s' % (other_participant, constants.server))
    
    def handle_presence_unavailable(self, presence):
        #NOTE don't call this when users are still online! remember delete_rosteritem triggers presence_unavaible... nasty bugs
        if presence['to'].user.startswith(constants.vinebot_prefix) and not self.user_online(presence['from'].user):
            participants = self.remove_participant(presence['from'].user,
                                                   presence['to'].user,
                                                   '%s has disconnected and left the conversation' % presence['from'].user)
            for participant in participants:
                self.sendPresence(pfrom=presence['to'],
                                  pto='%s@%s' % (participant, constants.server),
                                  pshow='unavailable')
    
    def handle_msg(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if msg['from'].bare in constants.admin_users:
                if self.commands.is_command(msg['body']):
                    msg.reply(self.commands.handle_command(msg['from'], msg['to'], msg['body'])).send()
                elif msg['body'].strip().startswith('/'):
                    msg.reply(self.commands.handle_command(msg['from'], msg['to'], '/help')).send()
                else:
                    msg.reply('Sorry, but admins can only send /commands to leaves.').send()
            elif not msg['to'].user.startswith(constants.vinebot_prefix):
               msg.reply('Sorry, but I can only handle messages send to vinebots.').send()
            else:
                participants, is_active, is_party = self.db_fetch_vinebot(msg['to'].user)
                if msg['from'].user in participants:
                    participants = set(filter(self.user_online, participants))
                    if self.commands.is_command(msg['body']):
                        msg.reply(self.commands.handle_command(msg['from'], msg['to'], msg['body'])).send()
                    elif msg['body'].strip().startswith('/'):
                        msg.reply(self.commands.handle_command(msg['from'], msg['to'], '/help')).send()
                    else:
                        if not is_active:
                            self.db_activate_pair_vinebot(msg['to'].user, True)
                            self.update_rosters(set([]), participants, msg['to'].user, False)
                        self.broadcast_msg(msg, participants, sender=msg['from'].user)
                else:
                    if msg['from'].user in self.db_fetch_observers(participants):
                        if is_active:
                            self.add_participant(msg['from'].user, msg['to'].user, '%s has joined the conversation' % msg['from'].user)
                            self.broadcast_msg(msg, participants, sender=msg['from'].user)
                        else:
                            msg.reply('Sorry, but you can\'t join a conversation that hasn\'t started yet.').send()
                    else:
                        msg.reply('Sorry, but only friends of participants can join this conversation.').send()
    
    def handle_chatstate(self, msg):
        if msg['to'].user.startswith(constants.vinebot_prefix):
            participants, is_active, is_party = self.db_fetch_vinebot(msg['to'].user)
            if msg['from'].user in participants:
                #LATER try this without using the new_msg to strip the body, see SleekXMPP chat logs
                new_msg = msg.__copy__()
                del new_msg['body']
                observers = filter(self.user_online, self.db_fetch_observers(participants))
                self.broadcast_msg(new_msg, participants.union(observers), sender=msg['from'].user)
    
    
    ##### user /commands
    def user_left(self, user, vinebot_user):
        self.remove_participant(user, vinebot_user, '%s has left the conversation' % user)
        return 'You left the conversation.'
    
    def invite_user(self, inviter, vinebot_user, invitee):
        if inviter == invitee:
            raise ExecutionError, 'you can\'t invite yourself.'
        self.add_participant(invitee, vinebot_user, '%s has invited %s the conversation' % (inviter, invitee))
        return ''
    
    def kick_user(self, kicker, vinebot_user, kickee):
        if kicker == kickee:
            raise ExecutionError, 'you can\'t kick yourself. Maybe you meant /leave?'
        self.remove_participant(kickee, vinebot_user, '%s was kicked from the conversation by %s' % (kickee, kicker))
        msg = self.Message()
        msg['body'] = '%s has kicked you from the conversation' % kicker
        msg['from'] = '%s@%s' % (vinebot_user, self.boundjid.bare)
        msg['to'] = '%s@%s' % (kickee, constants.server)
        msg.send()
        return ''
    
    def list_participants(self, user, vinebot_user):
        if vinebot_user.startswith(constants.vinebot_prefix):
            participants, is_active, is_party = self.db_fetch_vinebot(vinebot_user)
            participants.remove(user)
            if is_active:
                participants = list(participants)
                participants.append('you')
                return 'The current participants are:\n' + ''.join(['\t%s\n' % user for user in participants]).strip('\n')
            else:
                return 'This conversation hasn\'t started yet. Why don\'t you send %s a message?' % participants.pop()
        else:
            raise ExecutionError, 'this command only works with vinebots.'
    
    def list_observers(self, user, vinebot_user):
        if vinebot_user.startswith(constants.vinebot_prefix):
            participants, is_active, is_party = self.db_fetch_vinebot(vinebot_user)
            observers = filter(self.user_online, self.db_fetch_observers(participants))
            observer_string = ''.join(['\t%s\n' % user for user in observers]).strip('\n')
            if is_active:
                if len(observers) > 1:
                    return 'These users are online and can see this conversation:\n' + observer_string
                elif len(observers) == 1:
                    return '%s is online and can see this conversation.' % observers[0]
                else:
                    return 'There are no users online that can see this conversaton.'
            else:
                if len(observers) > 1:
                    return 'If this conversation were active, then these online users would see it:\n' + observer_string
                elif len(observers) == 1:
                    return 'If this conversation were active, then %s would see it.' % observers[0]
                else:
                    return 'There are no users online that can see this conversaton.'
        else:
            raise ExecutionError, 'this command only works with vinebots.'
    
    def whisper_msg(self, sender, vinebot_user, recipient, body):
        recipient_jid = '%s@%s' % (recipient, constants.server)
        if recipient == sender:
            raise ExecutionError, 'You can\'t whisper to youerself.'
        participants, is_active, is_party = self.db_fetch_vinebot(vinebot_user)
        if recipient not in participants and recipient_jid not in constants.admin_users:
            raise ExecutionError, 'You can\'t whisper to someone who isn\'t a participant in this conversation.'
        self.send_message(mto=recipient_jid,
                          mfrom='%s@%s' % (vinebot_user, self.boundjid.bare),
                          mbody='[%s, whispering] %s' % (sender, body))
        if len(participants) == 2:
            return 'You whispered to %s, but it\'s just the two of you here so no one would have heard you anyway...' % recipient
        else:
            return 'You whispered to %s, and no one noticed!' % recipient
    
    
    ##### admin /commands
    def create_user(self, user, password):
        self.db_create_user(user)
        self.register(user, password)
    
    def destroy_user(self, user):
        self.db_destroy_user(user)
        self.unregister(user)
    
    def create_friendship(self, user1, user2):
        vinebot_user = self.db_create_pair_vinebot(user1, user2)
        participants = set([user1, user2])
        self.add_rosteritem(user1, vinebot_user, self.get_nick(participants, user1))
        self.add_rosteritem(user2, vinebot_user, self.get_nick(participants, user2))
        # update observer lists accordingly
        for active_vinebot in self.db_fetch_user_pair_vinebots(user2):
            self.add_rosteritem(user1, active_vinebot[1], self.get_nick(active_vinebot[0]))
        for active_vinebot in self.db_fetch_user_pair_vinebots(user1):
            self.add_rosteritem(user2, active_vinebot[1], self.get_nick(active_vinebot[0]))
        self.send_presence_for_pair_vinebot(user1, user2, vinebot_user)
    
    def destroy_friendship(self, user1, user2):
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
    
    def prune_roster(self, user):
        errors = []
        for roster_user, roster_nick in self.get_roster(user):
            participants, is_active, is_party = self.db_fetch_vinebot(roster_user)
            if user in participants:
                correct_nick = self.get_nick(participants, user)
                if roster_nick != correct_nick:
                    errors.append('Incorrect nickname of %s for %s in roster of participant %s, should be %s.' %
                        (roster_nick, roster_user, user, correct_nick))
                    self.add_rosteritem(user, roster_user, correct_nick)
            elif user in self.db_fetch_observers(participants):
                if is_active:
                    correct_nick = self.get_nick(participants)
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
                    (roster_user, user, participants, is_active, is_party))
                self.delete_rosteritem(user, roster_user)
        if errors:
            return '\n'.join(errors)
        else:
            return 'No invalid roster items found.'
    
    def friendships(self):
        pair_vinebots = self.db_fetch_all_pair_vinebots()
        if len(pair_vinebots) <= 0:
            return 'No pair vinebots found. Use /new_friendship to create one for two users.'    
        output = 'There are %d frienddships:' % len(pair_vinebots)
        for vinebot_user, participants, is_active in pair_vinebots:
            output += '\n\t%s\n\t%s\n\t\t\t\t\t%s@%s\n\t\t\t\t\t%s' % (participants[0],
                                                                       participants[1],
                                                                       vinebot_user,
                                                                       self.boundjid.bare,
                                                                       'active' if is_active else 'inactive')
        return output
    
    
    ##### helper functions
    def get_vinebot_user(self, uuid_or_bytes):
        try:
            return '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid_or_bytes))
        except AttributeError:
            return '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid.UUID(bytes=uuid_or_bytes)))
    
    def broadcast_msg(self, msg, participants, sender=None):
        del msg['id']
        del msg['html'] #LATER fix html, but it's a pain with reformatting
        msg['from'] = msg['to']
        if msg['body'] and msg['body'] != '':
            if sender:
                msg['body'] = '[%s] %s' % (sender, msg['body'])
            else:
                msg['body'] = '/me *%s*' % (msg['body'])
        for participant in participants:
            if not sender or sender != participant:
                new_msg = msg.__copy__()
                new_msg['to'] = '%s@%s' % (participant, constants.server)
                new_msg.send()
    
    def broadcast_alert(self, body, participants, vinebot_user):
        msg = self.Message()
        msg['body'] = body
        msg['to'] = '%s@%s' % (vinebot_user, self.boundjid.bare)  # this will get moved to 'from' in broadcast_msg
        self.broadcast_msg(msg, participants)
    
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
    
    def send_presence_for_pair_vinebot(self, user1, user2, vinebot_user):
        user1_online = self.user_online(user1)
        user2_online = self.user_online(user2)
        if user1_online and user2_online:
            for user in [user1, user2]:
                self.sendPresence(pfrom='%s@%s' % (vinebot_user, self.boundjid.bare),
                                  pto='%s@%s' % (user, constants.server))
        else:
            for user in [user1, user2]:
                self.sendPresence(pfrom='%s@%s' % (vinebot_user, self.boundjid.bare),
                                  pto='%s@%s' % (user, constants.server),
                                  pshow='unavailable')
        return (user1_online, user2_online)
    
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
    
    def add_participant(self, user, vinebot_user, alert_msg):
        participants, is_active, is_party = self.db_fetch_vinebot(vinebot_user)
        if user in participants:
            raise ExecutionError, '%s is already part of this conversation!' % user
        new_participants = participants.union([user])
        if is_party:
            self.db_add_participant(user, vinebot_user)
        else:
            new_pair_vinebot_user = self.db_create_party_vinebot(new_participants, vinebot_user)
            for participant in participants:
                self.add_rosteritem(participant, new_pair_vinebot_user, participants.difference([participant]).pop())
        self.update_rosters(participants, new_participants, vinebot_user, True)
        self.broadcast_alert(alert_msg, participants, vinebot_user)
    
    def remove_participant(self, user, vinebot_user, alert_msg=''):
        participants, is_active, is_party = self.db_fetch_vinebot(vinebot_user)
        if user in participants:
            if is_party:
                if len(participants) >= 3:
                    new_participants = participants.difference([user])
                    if len(participants) == 3:
                        pair_vinebot_user, pair_is_active = self.db_fetch_pair_vinebot(*list(new_participants))
                        if pair_vinebot_user and not pair_is_active:
                            self.db_fold_party_into_pair(vinebot_user, pair_vinebot_user)
                            for participant in participants:
                                self.delete_rosteritem(participant, pair_vinebot_user)
                    self.update_rosters(participants, new_participants, vinebot_user, True)
                    self.db_remove_participant(user, vinebot_user)
                else:
                    new_participants = set([])
                    self.update_rosters(participants, new_participants, vinebot_user, True)
                    self.db_delete_party_vinebot(vinebot_user)
                # only broadcast the alert for parties
                self.broadcast_alert(alert_msg, new_participants, vinebot_user)
            else:
                if is_active:
                    self.db_activate_pair_vinebot(vinebot_user, False)
                    self.update_rosters(participants, set([]), vinebot_user, False)
                return participants
        return []
    
    
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
        try:              
            res = self.xmlrpc_command('user_sessions_info', {
                'user': user,
                'host': constants.server
            })
            return len(res['sessions_info']) > 0
        except xmlrpclib.ProtocolError, e:
            logging.error('ProtocolError in is_online, assuming %s is offline: %s' % (user, str(e)))
            return False
    
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
            raise ExecutionError, 'These users are already friends.'
        vinebot_uuid = uuid.uuid4()
        try:
            self.db_execute("""INSERT INTO pair_vinebots (id, user1, user2)
                               VALUES (%(id)s, 
                                       (SELECT id FROM users  WHERE user = %(user1)s LIMIT 1),
                                       (SELECT id FROM users  WHERE user = %(user2)s LIMIT 1)
                                      )""", {'id': vinebot_uuid.bytes, 'user1': user1, 'user2': user2})
            return self.get_vinebot_user(vinebot_uuid)
        except IntegrityError:
            raise ExecutionError, 'There was an IntegrityError - are you sure both users exist?'
    
    def db_delete_pair_vinebot(self, user1, user2):
        vinebot_user, is_active = self.db_fetch_pair_vinebot(user1, user2)
        if not vinebot_user:
            raise ExecutionError, 'No friendship found.'
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("DELETE FROM pair_vinebots WHERE id = %(id)s", {'id': vinebot_uuid.bytes})
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
        self.db_execute("""DELETE FROM party_vinebots WHERE id = %(id)s""", {'id': vinebot_uuid.bytes})
    
    def db_add_participant(self, user, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("""INSERT INTO party_vinebots (id, user)
                           VALUES (%(id)s, (SELECT id FROM users 
                                            WHERE user = %(user)s 
                                            LIMIT 1))""", {'id': vinebot_uuid.bytes, 'user': user})
    
    def db_remove_participant(self, user, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("""DELETE FROM party_vinebots 
                           WHERE user = (SELECT id FROM users WHERE user = %(user)s)
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
    
    def db_fetch_all_pair_vinebots(self):
        pair_vinebots = self.db_execute_and_fetchall("""SELECT  users_1.user, users_2.user, pair_vinebots.id, pair_vinebots.is_active
                                                        FROM users AS users_1, users AS users_2, pair_vinebots
                                                        WHERE pair_vinebots.user1 = users_1.id
                                                        AND   pair_vinebots.user2 = users_2.id""")
        return [(self.get_vinebot_user(pair_vinebot[2]),
                 [pair_vinebot[0],  pair_vinebot[1]],
                 (pair_vinebot[3] == 1)
                ) for pair_vinebot in pair_vinebots]
    
    def db_fetch_all_party_vinebots(self):
        party_vinebots = self.db_execute_and_fetchall("""SELECT party_vinebots.id, GROUP_CONCAT(users.user)
                                                         FROM users, party_vinebots
                                                         WHERE party_vinebots.user = users.id""", {})
        return [(self.get_vinebot_user(party_vinebot[0]),
                 party_vinebot[1].split(','),
                 True
                ) for party_vinebot in party_vinebots if party_vinebot[0]]  # the query returns (None, None) if no rows are found
    
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
            pair_vinebot = self.db_execute_and_fetchall("""SELECT users_1.user, users_2.user, pair_vinebots.is_active
                              FROM users AS users_1, users AS users_2, pair_vinebots
                              WHERE pair_vinebots.id = %(id)s AND pair_vinebots.user1 = users_1.id AND pair_vinebots.user2 = users_2.id
                              LIMIT 1""", {'id': vinebot_uuid.bytes})
            if len(pair_vinebot) > 0:
                participants = set([pair_vinebot[0][0], pair_vinebot[0][1]])
                is_active = (pair_vinebot[0][2] == 1)
                is_party = False
            else:
                party_vinebot = self.db_execute_and_fetchall("""SELECT users.user FROM users, party_vinebots
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
            WHERE (pair_vinebots.user1 = users_1.id AND users_1.user = %(user1)s
               AND pair_vinebots.user2 = users_2.id AND users_2.user = %(user2)s)
               OR (pair_vinebots.user1 = users_1.id AND users_1.user = %(user2)s
               AND pair_vinebots.user2 = users_2.id AND users_2.user = %(user1)s)
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
        return self.db_execute_and_fetchall("""SELECT users.user FROM users, pair_vinebots
                    WHERE (pair_vinebots.user1 = (SELECT id FROM users  WHERE user = %(user)s LIMIT 1)
                       AND pair_vinebots.user2 = users.id)
                    OR    (pair_vinebots.user2 = (SELECT id FROM users  WHERE user = %(user)s LIMIT 1)
                       AND pair_vinebots.user1 = users.id)""", {'user': user}, strip_pairs=True)
    
    def db_fetch_user_pair_vinebots(self, user, is_active=True):
        pair_vinebots = self.db_execute_and_fetchall("""SELECT users_1.user, users_2.user, pair_vinebots.id
                                                      FROM users AS users_1, users AS users_2, pair_vinebots
                                                     WHERE pair_vinebots.is_active = %(is_active)s
                                                       AND pair_vinebots.user1 = users_1.id 
                                                       AND pair_vinebots.user2 = users_2.id
                                                      AND (users_1.user = %(user)s 
                                                        OR users_2.user = %(user)s)""", {'user': user, 'is_active': is_active})
        active_vinebots = [(set([pair_vinebot[0], pair_vinebot[1]]), 
                            self.get_vinebot_user(pair_vinebot[2])
                           ) for pair_vinebot in pair_vinebots]
        active_vinebots.extend(self.db_fetch_user_party_vinebots(user))
        return active_vinebots
    
    def db_fetch_user_party_vinebots(self, user):
        party_vinebots = []
        party_vinebot_ids = self.db_execute_and_fetchall("""SELECT party_vinebots.id FROM party_vinebots
            WHERE party_vinebots.user = (SELECT id FROM users  WHERE user = %(user)s LIMIT 1)""", {'user': user}, strip_pairs=True)
        for party_vinebot_id in party_vinebot_ids:
            party_vinebot_user = self.get_vinebot_user(party_vinebot_id)
            participants, is_active, is_party = self.db_fetch_vinebot(party_vinebot_user)
            party_vinebots.append((participants, party_vinebot_user))
        return party_vinebots
    
    def db_create_user(self, user):
        try:
            self.db_execute("INSERT INTO users (user) VALUES (%(user)s)", {'user': user})
        except IntegrityError:
            raise ExecutionError, 'There was an IntegrityError - are you sure the user doesn\'t already exist?'
    
    def db_destroy_user(self, user):
        try:
            for friend in self.db_fetch_user_friends(user):
                self.destroy_friendship(user, friend)
            for party_vinebot_uuid in self.db_fetch_user_party_vinebots(user):
                vinebot_user = self.get_vinebot_user(party_vinebot_uuid)
                self.remove_participant(user, vinebot_user, '%s\'s account has been deleted.' % user)
            self.db_execute("DELETE FROM users WHERE user = %(user)s", {'user': user})
        except IntegrityError:
            raise ExecutionError, 'There was an IntegrityError - are you sure the user doesn\'t already exist?'
    
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
            logging.info("Database connection missing, attempting to reconnect and retry query")
            if self.db:
                self.db.close()
            self.db_connect()
        try:
            self.cursor.execute(query, data)
        except MySQLdb.OperationalError, e:
            logging.info('Database OperationalError %s for query, will retry: %s' % (e, query % data))
            self.db_connect()  # Try again, but only once
            self.cursor.execute(query, data)
    
    def db_connect(self):
        try:
            self.db = MySQLdb.connect('localhost',
                                      '%s%s' % (constants.leaf_name, self.id),
                                      constants.leaf_mysql_password,
                                      constants.db_name)
            self.db.autocommit(True)
            self.cursor = self.db.cursor()
            logging.info("Database connection created")
        except MySQLdb.Error, e:
            logging.error('Database connection and/orcursor creation failed with %d: %s' % (e.args[0], e.args[1]))
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
