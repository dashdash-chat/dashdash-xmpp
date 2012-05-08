#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import getpass
from optparse import OptionParser
import xmlrpclib
import sleekxmpp

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

#TODO read these from config file?
PROXYBOT_PASSWORD = 'ow4coirm5oc5coc9folv'
SERVER_URL = '127.0.0.1'
XMLRPC_SERVER_URL = 'http://%s:4560' % SERVER_URL

def debug_with_space(messages):
    print ' '
    for message in messages:
        print message
    print ' '
  
class ProxyBot(sleekxmpp.ClientXMPP):
    def __init__(self, username, server, contacts):
        if not username.startswith('proxybot'):
            logging.error("Not a valid proxybot JID: %s" % jid)
            self._xmlrpc_unregister()
            return
        sleekxmpp.ClientXMPP.__init__(self, '%s@%s' % (username, server), PROXYBOT_PASSWORD)
        self.is_registered = True
        self.convo_active = False
        self.contacts = set(contacts)
        self.xmlrpc_server = xmlrpclib.ServerProxy(XMLRPC_SERVER_URL)
        self.add_event_handler("session_start", self._handle_start)
        self.add_event_handler("message", self._handle_message)
        self.add_event_handler('presence_unavailable', self._handle_presence_unavailable)
        for state in ['active', 'inactive', 'gone', 'composing', 'paused']:
            self.add_event_handler('chatstate_%s' % state, self._handle_chatstate)
    
    def connect(self, *args, **kwargs): 
        for contact in self.contacts:
            res = self._xmlrpc_command('user_sessions_info', {
                'user': contact,
                'host': self.boundjid.host
            })
            if len(res['sessions_info']) == 0:  # one of the two initial users is no longer online!
                self._xmlrpc_unregister()
                return False
        return super(ProxyBot, self).connect(*args, **kwargs)

    def disconnect(self, *args, **kwargs):    
        if self.authenticated:
            if not self.convo_active:
                for contact in self.contacts:
                    self._delete_rosteritem_proxy(contact)
                print "TODO remove entry from database, since we've disconnected from an unavailable presense"
        super(ProxyBot, self).disconnect(*args, **kwargs)        
        self._xmlrpc_unregister()

    def _handle_start(self, event):
        contacts = list(self.contacts)
        self._add_rosteritem_proxy(contacts[0], contacts[1])
        self._add_rosteritem_proxy(contacts[1], contacts[0])
        for contact in self.contacts:
            self.send_presence(pto='%s@localhost' % contact, pshow="available") # because no one is on the list
        self.send_presence() # need this so we can receive messages
        self.get_roster()

    def _xmlrpc_unregister(self, username=None):
        self._xmlrpc_command('unregister', {
            'user': username or self.boundjid.user,
            'host': self.boundjid.host
        })
        if not username:
            self.is_registered = False
    def _xmlrpc_command(self, command, data):
            if self.is_registered:
                fn = getattr(self.xmlrpc_server, command)
            else:  # if the proxybot has already unregistered itself, don't try to execute more xmlrpc commands!
                fn = lambda *args, **kwargs: None
            return fn({
                'user': self.boundjid.user,
                'server': self.boundjid.host,
                'password': PROXYBOT_PASSWORD
            }, data)

    def _add_rosteritem_proxy(self, contact1, contact2):
        # proxybot adds self to contact1's roster as contact2
        self._xmlrpc_command('add_rosteritem', {
            'group': 'Chatidea Contacts',
            'localuser': contact1,
            'user': self.boundjid.user,
            'nick': contact2,
            'subs': 'both',
            'localserver': self.boundjid.host,
            'server':      self.boundjid.host
        })
        self._xmlrpc_command('add_rosteritem', {
            'group': 'participants',
            'localuser': self.boundjid.user,
            'user': contact1,
            'nick': contact1,
            'subs': 'both',
            'localserver': self.boundjid.host,
            'server':      self.boundjid.host
        })

    def _delete_rosteritem_proxy(self, contact):
        # proxybot deletes self from contact's roster
        self._xmlrpc_command('delete_rosteritem', {
            'localuser': contact,
            'user': self.boundjid.user,
            'localserver': self.boundjid.host,
            'server':      self.boundjid.host
        })
        self._xmlrpc_command('delete_rosteritem', {
            'localuser': self.boundjid.user,
            'user': contact,
            'localserver': self.boundjid.host,
            'server':      self.boundjid.host
        })

    def _handle_presence_unavailable(self, presence):    
        self.contacts.remove(presence['from'].user)
        self._delete_rosteritem_proxy(presence['from'].user)
        msg = self.Message()
        msg['body'] = '%s has disconnected and left the conversation' % presence['from'].user
        #TODO send new nickname with offline status, keep in roster??
        self._broadcast_message(msg)
        if len(self.contacts) < 2: 
            self.disconnect(wait=True)

    def _handle_chatstate(self, msg):
        #TODO ask Lance how to properly handle this double message problem.
        new_msg = msg.__copy__()
        del new_msg['body']
        self._broadcast_message(new_msg, new_msg['from'].user)

    def _handle_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if msg['from'].user in self.contacts:
                self._broadcast_message(msg, msg['from'].user)
            elif not msg['from'].user.startswith('proxybot'):
                msg.reply("You cannot send messages with this proxybot.").send()

    def _broadcast_message(self, msg, sender=None):
        del msg['id']
        del msg['from']
        del msg['html'] #TODO fix html, but it's a pain with reformatting
        if msg['body'] and msg['body'] != '':
            if sender:
                if len(self.contacts) > 2:
                    msg['body'] = '[%s]: %s' % (sender, msg['body'])
            else:
                msg['body'] = '/me %s' % (msg['body'])
        for contact in self.contacts:
            if not sender or sender != contact:
                new_msg = msg.__copy__()
                new_msg['to'] = "%s@localhost" % contact
                new_msg.send()

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
    # xmpp.register_plugin('xep_0033') # Extended Stanza Addressing
    # xmpp.register_plugin('xep_0004') # Data Forms
    # xmpp.register_plugin('xep_0060') # PubSub
    xmpp.register_plugin('xep_0085') # Chat State Notifications
    xmpp.register_plugin('xep_0199') # XMPP Ping

    if xmpp.connect():
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")
