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

#TODO read these from config file?
#TODO make 'contacts' groupname a variable?
PROXYBOT_PASSWORD = 'ow4coirm5oc5coc9folv'
SERVER_URL = '127.0.0.1'
XMLRPC_SERVER_URL = 'http://%s:4560' % SERVER_URL

class Stage:
    IDLE = 1
    ACTIVE = 2
    RETIRED = 3


class ProxyBot(sleekxmpp.ClientXMPP):
    def __init__(self, username, server, participants):
        if not username.startswith('proxybot'):
            logging.error("Not a valid proxybot JID: %s" % jid)
            return
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s' % (username, server), PROXYBOT_PASSWORD)
        self.stage = Stage.IDLE
        self.participants = set([Participant(participant) for participant in participants])
        self.invisible = False
        self.xmlrpc_server = xmlrpclib.ServerProxy(XMLRPC_SERVER_URL)
        self.add_event_handler("session_start", self._handle_start)
        self.add_event_handler('presence_probe', self._handle_presence_probe)
        self.add_event_handler('presence_available', self._handle_presence_available)
        self.add_event_handler('presence_unavailable', self._handle_presence_unavailable)
        self.add_event_handler("message", self._handle_message)
        for state in ['active', 'inactive', 'gone', 'composing', 'paused']:
            self.add_event_handler('chatstate_%s' % state, self._handle_chatstate)

    def retire(self):
        if self.stage is Stage.ACTIVE and len(self.participants) < 2:
            self.stage = Stage.RETIRED
            self.disconnect(wait=True)
            self._xmlrpc_command('unregister', {
                'user': username or self.boundjid.user,
                'host': self.boundjid.host
            })
            logging.warning("TODO: update component DB? or maybe component unregisters me?")
        else:
            logging.error("Attempted retire from an %s stage with the following %d participants: %s" %  (self.stage, len(self.participants), str(list(self.participants)).strip('[]')))

    def disconnect(self, *args, **kwargs):
        for participant in self.participants:
            self._delete_proxy_rosteritem(participant)
        super(ProxyBot, self).disconnect(*args, **kwargs)        
    
    def _handle_start(self, event):
        if len(self.participants) != 2:
             logging.error("In session_start with %d extra participants! %s" %  (len(self.participants) - 2, str(list(self.participants)).strip('[]')))
        for participant in self.participants:
            self._add_own_rosteritem(participant)
            self._add_proxy_rosteritem(participant)
        self.get_roster()
        iq = self.Iq()
        iq['from'] = self.boundjid.full
        iq['type'] = 'set'
        iq['proxybot_invisibility'].make_list('invisible-to-participants')
        iq['proxybot_invisibility'].add_item(itype='group', ivalue='contacts', iaction='deny', iorder=1)
        iq['proxybot_invisibility'].add_item(iaction='allow', iorder=2)
        iq.send()
        self._set_invisiblity(False) # this sends initial presence

    def _remove_participant(self, user):    
        old_guests = set([])
        for participant in self.participants:
            old_guests = old_guests.union(participant.guests())
        self.participants.remove(user)
        new_guests = set([])
        for participant in self.participants:
            new_guests = new_guests.union(participant.guests())
        guests_to_remove = old_guests.difference(new_guests)
        for guest in guests_to_remove:
            self._delete_own_rosteritem(guest)
            self._delete_proxy_rosteritem(guest)
        self.send_presence()
        logging.warning("TODO: update component DB with removed participant")
        self._broadcast_alert('%s has disconnected and left the conversation' % user)
        if len(self.participants) < 2:
            self.retire()

    def _add_participant(self, user):
        if self.stage is Stage.ACTIVE:
            self._broadcast_alert('%s has joined the conversation' % user) #broadcast before the user is in the conversation, to prevent offline message queueing
        new_participant = Participant(user)
        old_guests = set([])
        for participant in self.participants:
            old_guests = old_guests.union(participant.guests())
        new_guests = new_participant.guests().difference(old_guests)    
        for guest in new_guests:
            self._add_own_rosteritem(guest)
            self._add_proxy_rosteritem(guest)
        self.participants.add(new_participant)    
        self.send_presence()
        logging.warning("TODO: update component DB with added participant")
            
    def _handle_presence_probe(self, presence):
        logging.error("                  PRESENCE PROBE %s" % presence)

    def _handle_presence_available(self, presence):
        if presence['from'].user not in self.participants: return
        if self.stage is Stage.IDLE:
            if len(self.participants) != 2:
                 logging.error("In Stage.IDLE with %d extra participants! %s" %  (len(self.participants) - 2, str(list(self.participants)).strip('[]')))
            other_participant = self.participants.difference([presence['from'].user]).pop()
            try:
                if self.invisible and other_participant and other_participant.is_online():
                    self._set_invisiblity(False)
            except xmlrpclib.ProtocolError, e:
                logging.error('ProtocolError in user_sessions_info for %s, assuming offline: %s' % (other_participant, str(e)))
                
    def _handle_presence_unavailable(self, presence):
        if presence['from'].user not in self.participants: return
        if self.stage is Stage.IDLE:
            if len(self.participants) != 2:
                 logging.error("In Stage.IDLE with %d extra participants! %s" %  (len(self.participants) - 2, str(list(self.participants)).strip('[]')))
            # if either participant goes offline, we definitely want to be invisible until both are online again
            self._set_invisiblity(True)
        elif self.stage is Stage.ACTIVE and presence['from'].user in self.participants:
            self._remove_participant(presence['from'].user)

    def _set_invisiblity(self, visibility):
        logging.warning('setting invisiblity to %s' % visibility)
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

    def _handle_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if self.stage is Stage.ACTIVE:
                logging.warning("TODO: update component DB with new particpant")
            elif self.stage is Stage.IDLE:    
                self.stage = Stage.ACTIVE
                guests = set([])
                for participant in self.participants:
                    guests = guests.union(participant.guests())
                for guest in guests:
                    self._add_own_rosteritem(guest)
                    self._add_proxy_rosteritem(guest)
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

    def get_nick(self, viewer):
        if self.stage is Stage.IDLE:
            return self.participants.difference([viewer]).pop().user()
        elif self.stage is Stage.ACTIVE:
            others = [participant.user() for participant in self.participants.difference([viewer])]
            if len(others) > 1:
                comma_sep = ''.join(['%s, ' % other for other in others[:-2]])
                print '%s%s and %s' % (comma_sep, others[-2], others[-1])
                return '%s%s and %s' % (comma_sep, others[-2], others[-1])
            else:
                print others[0]
                return others[0]
        else:
            return self.boundjid.user

    def _xmlrpc_command(self, command, data):
            fn = getattr(self.xmlrpc_server, command)
            return fn({
                'user': self.boundjid.user,
                'server': self.boundjid.host,
                'password': PROXYBOT_PASSWORD
            }, data)
    def _add_own_rosteritem(self, user):
        if isinstance(user, Participant):
            user = user.user()
        self._xmlrpc_command('add_rosteritem', {
            'group': 'contacts',
            'localuser': self.boundjid.user,
            'user': user,
            'nick': user,
            'subs': 'both',
            'localserver': self.boundjid.host,
            'server':      self.boundjid.host
        })
    def _delete_own_rosteritem(self, user):
        if isinstance(user, Participant):
            user = user.user()
        self._xmlrpc_command('delete_rosteritem', {
           'localuser': self.boundjid.user,
           'user': user,
           'localserver': self.boundjid.host,
           'server':      self.boundjid.host
        })
    def _add_proxy_rosteritem(self, user):
        if isinstance(user, Participant):
            user = user.user()
        self._xmlrpc_command('add_rosteritem', {
            'group': 'Chatidea Contacts',
            'localuser': user,
            'user': self.boundjid.user,
            'nick': self.get_nick(user),
            'subs': 'both',
            'localserver': self.boundjid.host,
            'server':      self.boundjid.host
        })
    def _delete_proxy_rosteritem(self, user):
        if isinstance(user, Participant):
            user = user.user()
        self._xmlrpc_command('delete_rosteritem', {
           'localuser': user,
           'user': self.boundjid.user,
           'localserver': self.boundjid.host,
           'server':      self.boundjid.host
        })


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
