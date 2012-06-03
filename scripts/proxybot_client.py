#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import daemon
import getpass
from optparse import OptionParser
import MySQLdb
import shortuuid
import subprocess
import sleekxmpp
from sleekxmpp.exceptions import IqTimeout
import xmlrpclib
import constants
from constants import Stage, ProxybotCommand, HostbotCommand
from proxybot_invisibility import ProxybotInvisibility
from proxybot_user import Participant, User
from slash_commands import SlashCommand, SlashCommandRegistry, ExecutionError

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


def active_only(fn):
    def wrapped(*args, **kwargs):
        if args[0].stage is Stage.ACTIVE:
            return fn(*args, **kwargs)
        else:
            logging.error("This function can only be executed after proxybot becomes active.")
            return
    return wrapped
def participants_only(fn):
    def wrapped(*args, **kwargs):
        if args[1]['from'].user in args[0].participants or args[1]['from'].bare in constants.admin_users:
            return fn(*args, **kwargs)
        else:
            logging.debug("This stanza from %s is only handled for conversation participants." % args[1]['from'].user)
            return
    return wrapped
def participants_and_observers_only(fn):
    def wrapped(*args, **kwargs):
        observers = set([])
        for participant in args[0].participants:
            observers = observers.union(participant.observers())
        if args[1]['from'].user in args[0].participants.union(observers) or args[1]['from'].bare in constants.admin_users:
            return fn(*args, **kwargs)
        else:
            args[1].reply("You cannot send messages to this proxybot.").send()
            logging.debug("This stanza from %s is only handled for conversation participants and observers." % args[1]['from'].user)
            return
    return wrapped
def hostbot_only(fn):
    def wrapped(*args, **kwargs):
        if args[1]['from'] == constants.hostbot_component_jid:
            return fn(*args, **kwargs)
        else:
            logging.error("This command can only be invoked by the hostbot, but the IQ stanza was from %s." % args[1]['from'])
            return
    return wrapped


class Proxybot(sleekxmpp.ClientXMPP):
    def __init__(self, username, participants, stage=Stage.IDLE):
        if not username.startswith(constants.proxybot_prefix):
            logging.error("Proxybot JID %s does not start with %s" % (username, constants.proxybot_prefix))
            return
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s/%s' % (username, constants.server, constants.proxybot_resource), constants.proxybot_password)
        self.stage = stage
        self.participants = set([Participant(participant, self.boundjid.user) for participant in participants])
        self.invisible = False
        self.hidden_from_observers = False
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
        self._xmlrpc_command('add_rosteritem', { 'localserver': constants.server, 'server': constants.hostbot_server,
            'group': 'bots',
            'localuser': self.boundjid.user,
            'user': '',
            'nick': constants.hostbot_nick,
            'subs': 'both'
        })
        # Set up slash commands to be handled by the hostbot's SlashCommandRegistry
        self.commands = SlashCommandRegistry()
        def is_admin(sender):
            return sender.bare in constants.admin_users
        def is_participant(sender):
            return self.stage is Stage.ACTIVE and sender.user in self.participants
        def is_admin_or_participant(sender):
            return is_admin(sender) or is_participant(sender)
        def has_none(sender, arg_string, arg_tokens):
            if len(arg_tokens) == 0:
                return []
            return False
        def sender_as_only_arg(sender, arg_string, arg_tokens):
            if len(arg_tokens) == 0:
                return [sender.user]
            return False
        def sender_and_one_arg(sender, arg_string, arg_tokens):            
            if len(arg_tokens) == 1:
                return [sender.user, arg_tokens[0]]
            return False
        def only_string(sender, arg_string, arg_tokens):
            if len(arg_string.strip()) > 0:
                return [sender.user, arg_string]
            return False
        def one_arg_and_string(sender, arg_string, arg_tokens):
            if len(arg_tokens) >= 2:
                return [sender.user, arg_tokens[0], arg_string.partition(arg_tokens[0])[2].strip()]
            return False
        self.commands.add(SlashCommand(command_name     = 'leave',
                                       text_arg_format  = '',
                                       text_description = 'Leave this conversation.',
                                       validate_sender  = is_participant,
                                       transform_args   = sender_as_only_arg,
                                       action           = self._remove_participant))
        self.commands.add(SlashCommand(command_name     = 'list',
                                       text_arg_format  = '',
                                       text_description = 'List the participants in this conversation',
                                       validate_sender  = is_admin_or_participant,
                                       transform_args   = has_none,
                                       action           = lambda: 'The current participants are:\n' + \
                                           ''.join(['\t%s\n' % user for user in self.participants]).strip('\n')))
        self.commands.add(SlashCommand(command_name     = 'invite',
                                       text_arg_format  = 'username',
                                       text_description = 'Invite another user to this conversation.',
                                       validate_sender  = is_participant,
                                       transform_args   = sender_and_one_arg,
                                       action           = self._invite_participant))
        self.commands.add(SlashCommand(command_name     = 'kick',
                                       text_arg_format  = 'username',
                                       text_description = 'Kick a user out of this conversation.',
                                       validate_sender  = is_participant,
                                       transform_args   = sender_and_one_arg,
                                       action           = self._kick_participant))
        self.commands.add(SlashCommand(command_name     = 'whisper',
                                       text_arg_format  = 'username message to be sent to that user',
                                       text_description = 'Whisper a quick message to only one other participant',
                                       validate_sender  = is_admin_or_participant,
                                       transform_args   = one_arg_and_string,
                                       action           = self._whisper_message))
        self.commands.add(SlashCommand(command_name     = 'invisible',
                                       text_arg_format  = '',
                                       text_description = 'Hide this conversation from everyone who isn\'t already a participant',
                                       validate_sender  = is_participant,
                                       transform_args   = sender_as_only_arg,
                                       action           = self._hide_from_observers))
        self.commands.add(SlashCommand(command_name     = 'visible',
                                       text_arg_format  = '',
                                       text_description = 'Let this conversation be found by friends of participants',
                                       validate_sender  = is_participant,
                                       transform_args   = sender_as_only_arg,
                                       action           = self._show_to_observers))
        self.commands.add(SlashCommand(command_name     = 'notify',
                                       text_arg_format  = 'message to be sent to that conversation',
                                       text_description = 'Send a message to the participants for an active proxybot',
                                       validate_sender  = is_admin,
                                       transform_args   = only_string,
                                       action           = self._notify))
        self.commands.add(SlashCommand(command_name     = 'bounce',
                                       text_arg_format  = '',
                                       text_description = 'Disconnect this proxybot and restart it in a new process, reloading the script.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_none,
                                       action           = lambda: self.event('bounce', {})))
        self.commands.add(SlashCommand(command_name     = 'kill',
                                       text_arg_format  = '',
                                       text_description = 'Disconnect and unregister this proxybot.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_none,
                                       action           = lambda: self.event('disconnect_and_unregister', {})))
        # Add event handlers
        self.add_event_handler('session_start', self._handle_start)
        self.add_event_handler('presence_probe', self._handle_presence_probe)
        self.add_event_handler('presence_available', self._handle_presence_available)
        self.add_event_handler('presence_unavailable', self._handle_presence_unavailable)
        self.add_event_handler('message', self._handle_message)
        self.add_event_handler('disconnect_and_unregister', self.disconnect_and_unregister, threaded=True)
        self.add_event_handler('bounce', self.bounce, threaded=True)
        for state in ['active', 'inactive', 'gone', 'composing', 'paused']:
            self.add_event_handler('chatstate_%s' % state, self._handle_chatstate)

    def disconnect_and_unregister(self, event={}):
        self._update_rosters(self.participants, set([]))
        self.disconnect(wait=True)
        self._xmlrpc_command('unregister', {
            'user': self.boundjid.user,
            'host': constants.server,
        })
    def bounce(self, event={}):
        subprocess.Popen([sys.executable, constants.proxybot_script,
            '--daemon',
            '--username', self.boundjid.user,
            '--bounced'], shell=False, stdout=open(constants.proxybot_logfile, 'a'), stderr=subprocess.STDOUT)
        self.disconnect(wait=True)

    def _handle_start(self, event):
        # Register these commands *after* session_start
        self['xep_0050'].add_command(node=HostbotCommand.delete_proxybot,
                                     name='Disconnect and unregister proxybot',
                                     handler=self._cmd_complete_delete_proxybot,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=HostbotCommand.bounce_proxybot,
                                     name='Disconnect and restart the proxybot',
                                     handler=self._cmd_complete_bounce_proxybot,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=HostbotCommand.participant_deleted,
                                     name='Remove a participant from this proxybot',
                                     handler=self._cmd_receive_participant_deleted,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=HostbotCommand.add_observer,
                                     name='Add an observer to this proxybot',
                                     handler=self._cmd_receive_add_observer,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=HostbotCommand.remove_observer,
                                     name='Remove an observer from this proxybot',
                                     handler=self._cmd_receive_remove_observer,
                                     jid=self.boundjid.full)
        # Set up rosters and visibility
        if self.stage is Stage.IDLE:
            # Don't add itself to the rosters or re-send invisibility IQ if this proxybot is already
            # active, otherwise it will move back to the idle group in the participants' rosters.
            for participant in self.participants:
                participant.add_to_rosters(self._get_nick(participant), self.stage)
            iq = self.Iq()
            iq['from'] = self.boundjid.full
            iq['type'] = 'set'
            iq['proxybot_invisibility'].make_list('invisible-to-participants')
            iq['proxybot_invisibility'].add_item(itype='group', ivalue='contacts', iaction='deny', iorder=1)
            iq['proxybot_invisibility'].add_item(iaction='allow', iorder=2)
            iq.send()
            self.get_roster()
            # Check to see if everyone is online, and also send the initial presence
            self._set_invisibility(not reduce(lambda a, b: a.is_online() and b.is_online(), self.participants))
        else:    
            self.get_roster() #LATER test to see if I need to do get_roster in a particular order with the other things
            # if anyone is offline, remove them from the conversation, although they'll (hopefully?) see it later as an observer
            for participant in self.participants:
                if not participant.is_online():
                    self._remove_participant(participant)
            # if we're still not retired, we know at least two users are still online, so we should be visible
            if self.stage is not Stage.RETIRED:
                self._set_invisibility(False)

    def _update_rosters(self, old_participants, new_participants, participants_changed=True):
        observer_nick = self._get_nick()
        # First, create the old and new lists of observers
        old_observers = set([])
        new_observers = set([])
        for old_participant in old_participants:
            old_observers.update(old_participant.observers())
        if not self.hidden_from_observers:  # only add to observers if we're not hidden
            for new_participant in new_participants:
                new_observers.update(new_participant.observers())
        # Then, update the participants
        if participants_changed:
            for participant in old_participants.difference(new_observers).difference(new_participants):
                participant.delete_from_rosters()
            for participant in new_participants:
                participant.add_to_rosters(self._get_nick(participant), self.stage)
        # Next, update the observers
        for old_observer in old_observers.difference(self.participants).difference(new_observers):
            old_observer.delete_from_rosters()
        for new_observer in new_observers.difference(self.participants):
            new_observer.add_to_rosters(observer_nick, self.stage)
        # Finally, broadcast updated presence
        self.send_presence()

    def _get_nick(self, viewing_participant=None):  # observers all see the same nickname, so this is None for them
        users = [participant.user() for participant in self.participants.difference([viewing_participant] if viewing_participant else [])]
        if self.stage is Stage.IDLE:
            return users[0]
        elif self.stage is Stage.ACTIVE:
            if viewing_participant: 
                users.insert(0, 'you')
            comma_sep = ''.join([', %s' % user for user in users[1:-1]])
            return '%s%s & %s' % (users[0], comma_sep, users[-1])
        else:
            return self.boundjid.user

    #NOTE not @active_only because a participant can be removed when that user is deleted
    def _remove_participant(self, user):
        if len(self.participants) <= 2:  # then after this person leaves, there will only be 1, so we can preemptively retire
            self.stage = Stage.RETIRED
            session = {'user': user,
                       'next': self._cmd_send_retire,
                       'error': self._cmd_error}
            self['xep_0050'].start_command(jid=constants.hostbot_component_jid,
                                           node=ProxybotCommand.retire,
                                           session=session)
            logging.info('Removing user %s from the conversation and retiring the proxybot' % user)
        else:
            old_participants = self.participants.copy()
            self.participants.remove(user)
            self._update_rosters(old_participants, self.participants)
            self._broadcast_alert('%s has left the conversation' % user)
            session = {'user': user,
                       'next': self._cmd_send_remove_participant,
                       'error': self._cmd_error}
            self['xep_0050'].start_command(jid=constants.hostbot_component_jid,
                                           node=ProxybotCommand.remove_participant,
                                           session=session)
            logging.info('Removing user %s from the conversation' % user)
        return "Goodbye, %s!" % user

    @active_only
    def _add_participant(self, user):
        #LATER broadcast a join message before this happens, to prevent offline message queueing
        old_participants = self.participants.copy()
        self.participants.add(Participant(user, self.boundjid.user))
        self._update_rosters(old_participants, self.participants)
        session = {'user': user,
                   'next': self._cmd_send_add_participant,
                   'error': self._cmd_error}
        self['xep_0050'].start_command(jid=constants.hostbot_component_jid,
                                       node=ProxybotCommand.add_participant,
                                       session=session)
        logging.info('Adding user %s to the conversation' % user)

    def _invite_participant(self, sender, invitee):
        if invitee == sender:
            raise ExecutionError, 'You\'re already participating in this conversation!'
        elif invitee in self.participants:
            raise ExecutionError, '%s is already participating in this conversation!' % invitee
        temp_user = User(invitee, self.boundjid.user)
        if temp_user.is_online():
            self._broadcast_alert('%s has invited %s into the conversation.' % (sender, invitee))
            self._add_participant(invitee)
            self.send_message(mto="%s@%s" % (invitee, constants.server), mbody= '%s has invited you to the conversation.' % sender)
        else:
            raise ExecutionError, 'You can only invite users who are currently online.'
        return ''
    def _kick_participant(self, sender, kickee):
        if kickee not in self.participants:
            raise ExecutionError, '%s is not participating in this conversation, so can\'t be kicked.' % kickee
        elif kickee == sender:
            raise ExecutionError, 'You can\'t kick yourself! Type /leave to leave the conversation.'
        self.send_message(mto="%s@%s" % (kickee, constants.server), mbody= '%s has kicked you from the conversation.' % sender)
        self._remove_participant(kickee)    
        self._broadcast_alert('%s has kicked %s from the conversation.' % (sender, kickee))
        return ''

    def _show_to_observers(self, sender):
        if not self.hidden_from_observers:
            raise ExecutionError, "This conversation is already visible to everyone, including friends of the participants."
        self.hidden_from_observers = False
        self._update_rosters(set([]), self.participants, participants_changed=False)
        self._broadcast_alert('%s has made this conversation visible to friends of the participants.' % sender)
        return ''
    def _hide_from_observers(self, sender):
        if self.hidden_from_observers:
            raise ExecutionError, "This conversation is already invisible and hidden from friends."
        self.hidden_from_observers = True
        self._update_rosters(self.participants, set([]), participants_changed=False)
        self._broadcast_alert('%s has made this conversation invisible to everyone, including friends of the participants.' % sender)
        return ''

    @participants_only
    def _handle_presence_available(self, presence):
        if self.stage is Stage.IDLE:
            if len(self.participants) != 2:
                logging.error("In Stage.IDLE with %d extra participants! %s" %  (len(self.participants) - 2, str(list(self.participants)).strip('[]')))
                return
            other_participant = self.participants.difference([presence['from'].user]).pop()
            if self.invisible and other_participant and other_participant.is_online():
                self._set_invisibility(False)

    @participants_only
    def _handle_presence_unavailable(self, presence):
        if self.stage is Stage.IDLE:
            if len(self.participants) != 2:
                logging.error("In Stage.IDLE with %d extra participants! %s" %  (len(self.participants) - 2, str(list(self.participants)).strip('[]')))
                return
            # if either participant goes offline, we definitely want to be invisible until both are online again
            self._set_invisibility(True)
        elif self.stage is Stage.ACTIVE:
            self._remove_participant(presence['from'].user)

    @participants_only
    def _handle_chatstate(self, msg):
        #LATER try this without new_msg
        if msg['from'].user in self.participants:
            new_msg = msg.__copy__()
            del new_msg['body']
            self._broadcast_message(new_msg, new_msg['from'].user)

    @participants_and_observers_only
    def _handle_presence_probe(self, presence):
        logging.error("                  PRESENCE PROBE %s" % presence)

    @participants_and_observers_only
    def _handle_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if self.commands.is_command(msg['body']):
                msg.reply(self.commands.handle_command(msg['from'], msg['body'])).send()
                return
            elif msg['body'].strip().startswith('/'):  # don't send mis-typed /commands to the other participants
                msg.reply(self.commands.handle_command(msg['from'], '/help')).send()
                return
            elif msg['from'].bare in constants.admin_users:
                msg.reply("Admins cannot send normal messages to proxybots, please use the /notify command.").send()
                return
            elif self.stage is Stage.IDLE:  # idle proxybots can receive /commands, but the commands don't activate them
                self.stage = Stage.ACTIVE
                self._update_rosters(set([]), self.participants)
                session = {'user1': msg['from'].user,
                           'user2': self.participants.difference([msg['from'].user]).pop().user(),  # ugh, verbose
                           'next': self._cmd_send_activate,
                           'error': self._cmd_error}
                self['xep_0050'].start_command(jid=constants.hostbot_component_jid,
                                               node=ProxybotCommand.activate,
                                               session=session)
                logging.info('Activating the proxybot')
            # now we know we're in an active stage, and can proceed with the message broadcast
            if msg['from'].user not in self.participants:
                self._broadcast_alert('%s has joined the conversation' % msg['from'].user)
                self._add_participant(msg['from'].user)
            self._broadcast_message(msg, msg['from'].user)

    def _broadcast_message(self, msg, sender=None):
        del msg['id']
        del msg['from']
        del msg['html'] #LATER fix html, but it's a pain with reformatting
        if msg['body'] and msg['body'] != '':
            if sender:
                msg['body'] = '[%s] %s' % (sender, msg['body']) # all messages need this, so you know who the conversation is with later
            else:
                msg['body'] = '/me *%s*' % (msg['body'])
        for participant in self.participants:
            if not sender or sender != participant:
                new_msg = msg.__copy__()
                new_msg['to'] = "%s@%s" % (participant.user(), constants.server)
                new_msg.send()
    def _broadcast_alert(self, body):
        msg = self.Message()
        msg['body'] = body
        self._broadcast_message(msg)
    def _whisper_message(self, sender, recipient, body):
        recipient_jid = '%s@%s' % (recipient, constants.server)
        if recipient == sender:
            raise ExecutionError, 'You can\'t whisper to youerself.'
        if recipient not in self.participants and recipient_jid not in constants.admin_users:
            raise ExecutionError, 'You can\'t whisper to someone who isn\'t a participant in this conversation.'
        self.send_message(mto=recipient_jid, mbody='(whispering)[%s] %s' % (sender, body))
        return ''
    def _notify(self, sender, body):
        if self.stage != Stage.ACTIVE:
            raise ExecutionError, 'This proxybot is %s, and you can only send a message to an %s conversation.' % (self.stage, Stage.ACTIVE)
        msg = self.Message()
        msg['body'] = body
        self._broadcast_message(msg, sender)
        return ''

    def _set_invisibility(self, invisibility):
        init_invisible = self.invisible
        self.invisible = invisibility  # the object needs to keep this as state so that it doesn't get stuck in a presence available/unavailable loop
        self.send_presence(ptype='unavailable')
        iq = self.Iq()
        iq['from'] = self.boundjid.full
        iq['type'] = 'set'
        if self.invisible:
            iq['proxybot_invisibility'].make_active('invisible-to-participants')
        else:
            iq['proxybot_invisibility'].make_active()
        try:
            iq.send()
        except IqTimeout, e:
            logging.error('Failed to set invisibility for %s to %s with error: %s' % (self.boundjid.full, invisibility, e))
            self.invisible = init_invisible  #NOTE this may just trigger a retry, due to the aforementioned loop.
        self.send_presence()

    # Adhoc commands for which the proxybot is the provider and the hostbot is the user
    @hostbot_only
    def _cmd_receive_participant_deleted(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Participant deleted')
        form.addField(ftype='text-single', var='user')
        session['payload'] = form
        session['next'] = self._cmd_complete_participant_deleted
        session['has_next'] = False
        return session
    @hostbot_only
    def _cmd_receive_add_observer(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Add observer')
        form.addField(ftype='text-single', var='participant')
        form.addField(ftype='text-single', var='observer')
        session['payload'] = form
        session['next'] = self._cmd_complete_add_observer
        session['has_next'] = False
        return session
    @hostbot_only
    def _cmd_receive_remove_observer(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Remove observer')
        form.addField(ftype='text-single', var='participant')
        form.addField(ftype='text-single', var='observer')
        session['payload'] = form
        session['next'] = self._cmd_complete_remove_observer
        session['has_next'] = False
        return session
    def _cmd_complete_delete_proxybot(self, payload, session):
        self.disconnect_and_unregister()
        session['has_next'] = False
        session['next'] = None
        return session
    def _cmd_complete_bounce_proxybot(self, payload, session):
        self.bounce()
        session['has_next'] = False
        session['next'] = None
        return session
    def _cmd_complete_participant_deleted(self, payload, session):
        form = payload
        user = form['values']['user']
        self._remove_participant(user)
        session['payload'] = None
        session['next'] = None
        return session
    def _cmd_complete_add_observer(self, payload, session):
        form = payload
        participant_to_match = form['values']['participant']
        observer = form['values']['observer']
        # Add an observer on the proxybot's participant object that matches the participant name from the form.
        # I can't use a fancy set intersection here, because I can't enforce which will be returned of the
        # proxybot's participant object or the string that is seen as equal to it.
        for participant in self.participants:
            if participant == participant_to_match:
                participant.add_observer(observer, self.boundjid.user, self._get_nick())
                logging.info("Added observer %s for participant %s on stage %s proxybot %s" % (observer, participant, self.stage, self.boundjid.full))
        session['payload'] = None
        session['next'] = None
        return session
    def _cmd_complete_remove_observer(self, payload, session):
        form = payload
        participant_to_match = form['values']['participant']
        observer = form['values']['observer']
        # see note in _cmd_complete_add_observer about how this works
        for participant in self.participants:
            if participant == participant_to_match:
                participant.remove_observer(observer, self.boundjid.user)
                logging.info("Removed observer %s for participant %s on stage %s proxybot %s" % (observer, participant, self.stage, self.boundjid.full))
        session['payload'] = None
        session['next'] = None
        return session

    # Adhoc commands for which the proxybot is the user and the hostbot is the provider
    @hostbot_only
    def _cmd_send_activate(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='proxybot', value=self.boundjid.user)
        form.addField(var='user1', value=session['user1'])
        form.addField(var='user2', value=session['user2'])
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)
    @hostbot_only
    def _cmd_send_retire(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='proxybot', value=self.boundjid.user)
        form.addField(var='user', value=session['user'])
        session['payload'] = form
        session['next'] = self._cmd_finish_retire
        self['xep_0050'].complete_command(session)
    @hostbot_only
    def _cmd_send_add_participant(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='proxybot', value=self.boundjid.user)
        form.addField(var='user', value=session['user'])
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)
    @hostbot_only
    def _cmd_send_remove_participant(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='proxybot', value=self.boundjid.user)
        form.addField(var='user', value=session['user'])
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)
    @hostbot_only
    def _cmd_finish_retire(self, iq, session):
        self.event('disconnect_and_unregister', {})
    
    # Adhoc commands - general functions
    def _cmd_error(self, iq, session):
        logging.error("COMMAND: %s %s" % (iq['error']['condition'],
                                          iq['error']['text']))
        self['xep_0050'].terminate_command(session)

    def _xmlrpc_command(self, command, data):
        fn = getattr(self.xmlrpc_server, command)
        return fn({
            'user': constants.proxybot_xmlrpc_jid,
            'server': constants.server,
            'password': constants.proxybot_xmlrpc_password
        }, data)
        

if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)
    optp.add_option("-u", "--username", dest="username",
                    help="proxybot username")
    optp.add_option("-1", "--participant1", dest="participant1",
                    help="first participant's username")
    optp.add_option("-2", "--participant2", dest="participant2",
                    help="second participant's username")
    optp.add_option('-d', '--daemon', help='run as daemon',
                    action='store_const', dest='daemon',
                    const=True, default=False)
    optp.add_option("-b", "--bounced", help="this proxybot was bounced, and stage needs to be fetched from the database",
                    action='store_const', dest='bounced',
                    const=True, default=False)
    opts, args = optp.parse_args()

    if opts.username is None:
        opts.username = raw_input("Proxybot username: ")
    logging.basicConfig(level=opts.loglevel,
                        format='%(proxybot_id)-36s %%(levelname)-8s %%(message)s' % {'proxybot_id': opts.username})

    if opts.bounced:
        proxybot_id = opts.username.split(constants.proxybot_prefix)[1]
        db = None
        cursor = None
        try:
            db = MySQLdb.connect('localhost', constants.userinfo_mysql_user, constants.userinfo_mysql_password, constants.db_name)
            cursor = db.cursor()
            cursor.execute("""SELECT proxybots.stage, proxybot_participants.user FROM 
                proxybots, proxybot_participants WHERE
                proxybots.id = proxybot_participants.proxybot_id AND
                proxybots.id = %(proxybot_id)s""", {'proxybot_id': shortuuid.decode(proxybot_id)})
            result = cursor.fetchall()
            if result[0][0] == 'idle':
                stage = Stage.IDLE
            elif result[0][0] == 'active':
                stage = Stage.ACTIVE
            else:
                stage = Stage.RETIRED
            participants = set([item[1] for item in result])
            db.close()
        except MySQLdb.Error, e:
            print "%(proxybot_jid)-34s Error %(number)d: %(string)s" % {'proxybot_jid': opts.username, 'number': e.args[0], 'string': e.args[1]}
            if db:
                db.close()
            sys.exit(1)
        xmpp = Proxybot(opts.username, participants, stage)
    else:
        if opts.participant1 is None:
            opts.participant1 = raw_input("First participant for this proxybot: ")
        if opts.participant2 is None:
            opts.participant2 = getpass.getpass("Second participant for this proxybot: ")
        xmpp = Proxybot(opts.username, [opts.participant1, opts.participant2])
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0004') # Data Forms
    xmpp.register_plugin('xep_0050') # Adhoc Commands
    xmpp.register_plugin('xep_0085') # Chat State Notifications
    xmpp.register_plugin('xep_0199') # XMPP Ping

    def run_proxybot(xmpp, proxybot_jid):
        if xmpp.connect((constants.server_ip, constants.client_port)):
            xmpp.process(block=True)
            print('%(proxybot_jid)-34s Done' % {'proxybot_jid': proxybot_jid})
        else:
            print('%(proxybot_jid)-34s Unable to connect' % {'proxybot_jid': proxybot_jid})

    if opts.daemon:    
        with daemon.DaemonContext(stdout=sys.stdout, stderr=sys.stderr):
            run_proxybot(xmpp, opts.username)
    else:
        run_proxybot(xmpp, opts.username)
