#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import getpass
from optparse import OptionParser
import xmlrpclib
import sleekxmpp
from proxybot_invisibility import ProxybotInvisibility

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

#TODO read these from config file?
#TODO make 'participants' groupname a variable?
PROXYBOT_PASSWORD = 'ow4coirm5oc5coc9folv'
SERVER_URL = '127.0.0.1'
XMLRPC_SERVER_URL = 'http://%s:4560' % SERVER_URL

class Stage:
    IDLE = 1
    ACTIVE = 2
    RETIRED = 3

class ProxyBot(sleekxmpp.ClientXMPP):
    def __init__(self, username, server, contacts):
        if not username.startswith('proxybot'):
            logging.error("Not a valid proxybot JID: %s" % jid)
            return
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s' % (username, server), PROXYBOT_PASSWORD)
        self.stage = Stage.IDLE
        self.contacts = set(contacts)
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
        if self.stage is Stage.ACTIVE and len(self.contacts) < 2:
            self.stage = Stage.RETIRED
            self.disconnect(wait=True)
            self._xmlrpc_command('unregister', {
                'user': username or self.boundjid.user,
                'host': self.boundjid.host
            })
            logging.warning("TODO: update component DB? or maybe component unregisters me?")
        else:
            logging.error("Attempted retire from an %s stage with the following %d contacts: %s" %  (self.stage, len(self.contacts), str(list(self.contacts)).strip('[]')))

    def disconnect(self, *args, **kwargs):    
        self._delete_proxy_rosteritems(self.contacts)
        super(ProxyBot, self).disconnect(*args, **kwargs)        
    
    def _handle_start(self, event):
        if len(self.contacts) != 2:
             logging.error("In session_start with %d extra contacts! %s" %  (len(self.contacts) - 2, str(list(self.contacts)).strip('[]')))
        contact1, contact2 = list(self.contacts)
        self._add_participant(contact1)
        self._add_participant(contact2)
        self._add_proxy_rosteritem(contact1, nick=contact2)
        self._add_proxy_rosteritem(contact2, nick=contact1)
        self.get_roster()
        iq = self.Iq()
        iq['from'] = self.boundjid.full
        iq['type'] = 'set'
        iq['proxybot_invisibility'].make_list('invisible-to-participants')
        iq['proxybot_invisibility'].add_item(itype='group', ivalue='participants', iaction='deny', iorder=1)
        iq['proxybot_invisibility'].add_item(iaction='allow', iorder=2)
        iq.send()
        self._set_invisiblity(False) # this sends initial presence

    def _handle_presence_probe(self, presence):
        logging.error("WTF PRESENCE PROBE %s" % presence)
  
    def _handle_presence_available(self, presence):
        if presence['from'].user not in self.contacts: return
        print '_handle_presence_available for %s' % presence['from'].user
        if self.stage is Stage.IDLE:
            if len(self.contacts) != 2:
                 logging.error("In Stage.IDLE with %d extra contacts! %s" %  (len(self.contacts) - 2, str(list(self.contacts)).strip('[]')))
            contact1, contact2 = list(self.contacts)
            other_contact = self.contacts.difference([presence['from'].user]).pop()
            print 'MOTHERFUCKER is maybe online: %s' % other_contact
            try:
                if self.invisible and other_contact and self._has_active_session(other_contact):
                    self._set_invisiblity(False)
            except xmlrpclib.ProtocolError, e:
                logging.error('ProtocolError in user_sessions_info for %s, assuming offline: %s' % (other_contact, str(e)))
                
    def _handle_presence_unavailable(self, presence):
        if presence['from'].user not in self.contacts: return
        print ' _handle_presence_UNavailable for %s' % presence['from'].user
        if self.stage is Stage.IDLE:
            if len(self.contacts) != 2:
                 logging.error("In Stage.IDLE with %d extra contacts! %s" %  (len(self.contacts) - 2, str(list(self.contacts)).strip('[]')))
            # if either contact goes offline, we definitely want to be invisible until both are online again
            self._set_invisiblity(True)
        elif self.stage is Stage.ACTIVE and presence['from'].user in self.contacts:
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

    def _remove_participant(self, participant):
        self.contacts.remove(participant)
        logging.warning("TODO: remove yourself from the rosters of all of the user's friends")
        logging.warning("TODO: update component DB with removed participant")
        self._broadcast_alert('%s has disconnected and left the conversation' % participant)
        if len(self.contacts) < 2:
            self.retire()

    def _add_participant(self, participant):
        self.contacts.add(participant)
        logging.warning("TODO: add yourself to the rosters of all of the user's friends")
        logging.warning("TODO: update component DB with added participant") 
        self._broadcast_alert('%s has joined the conversation' % participant)

    def _handle_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if self.stage is Stage.ACTIVE:
                logging.warning("TODO: update component DB with new particpant")
            elif self.stage is Stage.IDLE:
                logging.warning("TODO: add yourself to the rosters of all of BOTH users' friends")
                logging.warning("TODO: update component DB with stage change, so it can create a new proxybot for you")
                self.Stage = Stage.ACTIVE
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
                if msg['from'].user not in self.contacts: #LATER restrict newcomers to friends of participants
                    self._add_participant(msg['from'].user)
                if msg['from'].user in self.contacts:     #NOTE for now this will always be true
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
        for contact in self.contacts:
            if not sender or sender != contact:
                new_msg = msg.__copy__()
                new_msg['to'] = "%s@localhost" % contact
                new_msg.send()


    def _xmlrpc_command(self, command, data):
            fn = getattr(self.xmlrpc_server, command)
            return fn({
                'user': self.boundjid.user,
                'server': self.boundjid.host,
                'password': PROXYBOT_PASSWORD
            }, data)
    def _add_participant(self, user):
        self._xmlrpc_command('add_rosteritem', {
            'group': 'participants',
            'localuser': self.boundjid.user,
            'user': user,
            'nick': user,
            'subs': 'both',
            'localserver': self.boundjid.host,
            'server':      self.boundjid.host
        })
    def _add_proxy_rosteritem(self, target, nick=None):
        self._xmlrpc_command('add_rosteritem', {
            'group': 'Chatidea Contacts',
            'localuser': target,
            'user': self.boundjid.user,
            'nick': nick or self.boundjid.user,
            'subs': 'both',
            'localserver': self.boundjid.host,
            'server':      self.boundjid.host
        })
    def _delete_proxy_rosteritem(self, target):
        self._xmlrpc_command('delete_rosteritem', {
           'localuser': target,
           'user': self.boundjid.user,
           'localserver': self.boundjid.host,
           'server':      self.boundjid.host
        })
    def _delete_proxy_rosteritems(self, contacts):
        for contact in contacts:
            self._delete_proxy_rosteritem(contact)
    def _has_active_session(self, user):
        res = self._xmlrpc_command('user_sessions_info', {
            'user': user,
            'host': self.boundjid.host
        })
        return len(res['sessions_info']) > 0


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
                    help="server for proxybot and contacts")
    optp.add_option("-1", "--contact1", dest="contact1",
                    help="first contact's username")
    optp.add_option("-2", "--contact2", dest="contact2",
                    help="second contact's username")
    opts, args = optp.parse_args()

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    if opts.username is None:
        opts.username = raw_input("Proxybot username: ")
    if opts.server is None:
        opts.server = raw_input("Server for proxybot and contacts: ")
    if opts.contact1 is None:
        opts.contact1 = raw_input("First contact for this proxybot: ")
    if opts.contact2 is None:
        opts.contact2 = getpass.getpass("Second contact for this proxybot: ")

    xmpp = ProxyBot(opts.username, opts.server, [opts.contact1, opts.contact2])
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0085') # Chat State Notifications
    xmpp.register_plugin('xep_0199') # XMPP Ping

    if xmpp.connect():
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")
