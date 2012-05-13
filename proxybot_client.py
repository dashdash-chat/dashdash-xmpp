#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import getpass
from optparse import OptionParser
import xmlrpclib
import sleekxmpp
from proxybot_invisibility import ProxybotInvisibility
from participant import Participant

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


#TODO make 'contacts' groupname a variable?
#TODO read these from config file?
PROXYBOT_PASSWORD = 'ow4coirm5oc5coc9folv'


class Stage:
    IDLE = 1
    ACTIVE = 2
    RETIRED = 3


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
        if args[1]['from'].user in args[0].participants:
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
        if args[1]['from'].user in args[0].participants.union(observers):
            return fn(*args, **kwargs)
        else:
            logging.debug("This stanza from %s is only handled for conversation participants and observers." % args[1]['from'].user)
            return
    return wrapped

class ProxyBot(sleekxmpp.ClientXMPP):
    def __init__(self, username, server, participants):
        if not username.startswith('proxybot'):
            logging.error("Not a valid proxybot JID: %s" % jid)
            return
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s' % (username, server), PROXYBOT_PASSWORD)
        self.stage = Stage.IDLE
        self.participants = set([Participant(participant, self.boundjid.user) for participant in participants[0:2]]) # only two participants to start!
        self.invisible = False
        self.add_event_handler("session_start", self._handle_start)
        self.add_event_handler('presence_probe', self._handle_presence_probe)
        self.add_event_handler('presence_available', self._handle_presence_available)
        self.add_event_handler('presence_unavailable', self._handle_presence_unavailable)
        self.add_event_handler("message", self._handle_message)
        for state in ['active', 'inactive', 'gone', 'composing', 'paused']:
            self.add_event_handler('chatstate_%s' % state, self._handle_chatstate)

    @active_only
    def retire(self):
        if len(self.participants) < 2:
            self.stage = Stage.RETIRED
            self.disconnect(wait=True)
            logging.warning("TODO: update component DB, and ask component to unregister me")
        else:
            logging.error("Attempted retire from an %s stage with the following %d participants: %s" %  (self.stage, len(self.participants), str(list(self.participants)).strip('[]')))

    def disconnect(self, *args, **kwargs):
        for participant in self.participants:
            participant.delete_from_rosters()
        super(ProxyBot, self).disconnect(*args, **kwargs)        
    
    def _handle_start(self, event):
        for participant in self.participants:
            participant.add_to_rosters(self.participants)
        self.get_roster()
        iq = self.Iq()
        iq['from'] = self.boundjid.full
        iq['type'] = 'set'
        iq['proxybot_invisibility'].make_list('invisible-to-participants')
        iq['proxybot_invisibility'].add_item(itype='group', ivalue='contacts', iaction='deny', iorder=1)
        iq['proxybot_invisibility'].add_item(iaction='allow', iorder=2)
        iq.send()
        # is everyone online? this also sends the initial presence
        self._set_invisiblity(not reduce(lambda a, b: a.is_online() and b.is_online(), self.participants))

    @active_only
    def _remove_participant(self, user):    
        if len(self.participants) < 3:
            self.retire()
        else:
            old_observers = set([])
            for participant in self.participants:
                old_observers = old_observers.union(participant.observers())
            self.participants.remove(user)
            self._broadcast_alert('%s has left the conversation' % user)
            new_observers = self.participants.copy()  # start with this, so you don't accidentally remove an active participant
            for participant in self.participants:
                new_observers = new_observers.union(participant.observers())
            observers_to_remove = old_observers.difference(new_observers)
            for observer in observers_to_remove:
                observer.delete_from_rosters()
            self.send_presence() # so that it appears as online to removed participants
            logging.warning("TODO: update component DB with removed participant")

    @active_only
    def _add_participant(self, user):        
        self._broadcast_alert('%s has joined the conversation' % user) #broadcast before the user is in the conversation, to prevent offline message queueing
        new_participant = Participant(user, self.boundjid.user)
        old_observers = set([])
        for participant in self.participants:
            old_observers = old_observers.union(participant.observers())
        new_observers = new_participant.observers().difference(old_observers)    
        for observer in new_observers:
            participant.add_to_rosters(self.participants)
        self.participants.add(new_participant)
        self.send_presence()
        logging.warning("TODO: update component DB with added participant")
    
    @participants_only
    def _handle_presence_available(self, presence):
        if self.stage is Stage.IDLE:
            if len(self.participants) != 2:
                 logging.error("In Stage.IDLE with %d extra participants! %s" %  (len(self.participants) - 2, str(list(self.participants)).strip('[]')))
            other_participant = self.participants.difference([presence['from'].user]).pop()
            if self.invisible and other_participant and other_participant.is_online():
                self._set_invisiblity(False)

    @participants_only
    def _handle_presence_unavailable(self, presence):
        if self.stage is Stage.IDLE:
            if len(self.participants) != 2:
                 logging.error("In Stage.IDLE with %d extra participants! %s" %  (len(self.participants) - 2, str(list(self.participants)).strip('[]')))
            # if either participant goes offline, we definitely want to be invisible until both are online again
            self._set_invisiblity(True)
        elif self.stage is Stage.ACTIVE:
            self._remove_participant(presence['from'].user)

    @participants_and_observers_only
    def _handle_presence_probe(self, presence):
        logging.error("                  PRESENCE PROBE %s" % presence)    

    @participants_and_observers_only
    def _handle_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if self.stage is Stage.ACTIVE:
                logging.warning("TODO: update component DB with new particpant")
            elif self.stage is Stage.IDLE:    
                self.stage = Stage.ACTIVE
                observers = set([])
                for participant in self.participants:
                    observers = observers.union(participant.observers())
                for observer in observers:
                    observer.add_to_rosters(self.participants)
                self.send_presence()
                logging.warning("TODO: update component DB with stage change, so it can create a new proxybot for you")
            else:
                msg.reply("Sorry, but this conversation is no longer active. Try starting or joining a different one!").send()
                logging.error("Received message %s in retired stage." % msg)
                return
            # now we know we're in an active stage, and can proceed with the message broadcast
            if msg['body'].startswith('/'): #LATER proper command handling
                if msg['body'].startswith('/leave'):
                    self._remove_participant(msg['from'].user)
                else:
                    msg.reply("TODO: handle other slash commands").send()
            else:
                if msg['from'].user not in self.participants: #LATER restrict newcomers to friends of participants
                    self._add_participant(msg['from'].user)
                if msg['from'].user in self.participants:     #NOTE for now this will always be true
                    self._broadcast_message(msg, msg['from'].user)
                else:
                    msg.reply("You cannot send messages with this proxybot.").send()

    @participants_only
    def _handle_chatstate(self, msg):
        #LATER try this without new_msg
        #LATER do i need to duplicate complex _handle_message logic here?
        new_msg = msg.__copy__()
        del new_msg['body']
        self._broadcast_message(new_msg, new_msg['from'].user)
    
    def _broadcast_alert(self, body):
        msg = self.Message()
        msg['body'] = body
        self._broadcast_message(msg)

    def _broadcast_message(self, msg, sender=None):
        del msg['id']
        del msg['from']
        del msg['html'] #LATER fix html, but it's a pain with reformatting
        if msg['body'] and msg['body'] != '':
            if sender:
                msg['body'] = '[%s] %s' % (sender, msg['body']) # all messages need this, so you know who the conversation is with later
            else:
                msg['body'] = '/me %s' % (msg['body'])
        for participant in self.participants:
            if not sender or sender != participant:
                new_msg = msg.__copy__()
                new_msg['to'] = "%s@localhost" % participant.user()
                new_msg.send()

    def _set_invisiblity(self, visibility):
        self.invisible = visibility
        self.send_presence(ptype='unavailable')
        iq = self.Iq()
        iq['from'] = self.boundjid.full
        iq['type'] = 'set'
        if self.invisible:
            iq['proxybot_invisibility'].make_active('invisible-to-participants')
        else:
            iq['proxybot_invisibility'].make_active()
        iq.send()
        self.send_presence()

if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-d', '--debug', help='set logging to DEBUG',
                    action='store_const', dest='loglevel',
                    const=logging.DEBUG, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)
    optp.add_option("-u", "--username", dest="username",
                    help="proxybot username")
    optp.add_option("-s", "--server", dest="server",
                    help="server for proxybot and participants")
    optp.add_option("-1", "--participant1", dest="participant1",
                    help="first participant's username")
    optp.add_option("-2", "--participant2", dest="participant2",
                    help="second participant's username")
    opts, args = optp.parse_args()

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    if opts.username is None:
        opts.username = raw_input("Proxybot username: ")
    if opts.server is None:
        opts.server = raw_input("Server for proxybot and participants: ")
    if opts.participant1 is None:
        opts.participant1 = raw_input("First participant for this proxybot: ")
    if opts.participant2 is None:
        opts.participant2 = getpass.getpass("Second participant for this proxybot: ")

    xmpp = ProxyBot(opts.username, opts.server, [opts.participant1, opts.participant2])
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0085') # Chat State Notifications
    xmpp.register_plugin('xep_0199') # XMPP Ping

    if xmpp.connect():
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")
