#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
import logging
import getpass
from optparse import OptionParser
import subprocess
import uuid
import sleekxmpp
from sleekxmpp.componentxmpp import ComponentXMPP
from sleekxmpp.exceptions import IqError, IqTimeout

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

PROXYBOT_PASSWORD = 'ow4coirm5oc5coc9folv'

class HostbotComponent(ComponentXMPP):
    def __init__(self, jid, secret, server, port):
        ComponentXMPP.__init__(self, jid, secret, server, port)
        self.main_server = server
        self.boundjid.resource = 'python_component'
        self.boundjid.regenerate()
        self.nick = 'Hostbot'
        self.auto_authorize = True
        self._dbs_open()
        self.cursor_state.execute("DROP TABLE IF EXISTS cur_proxybots;", {})
        self.cursor_state.execute("""CREATE TABLE cur_proxybots (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user1 VARCHAR(15),
            user2 VARCHAR(15),
            created TIMESTAMP DEFAULT NOW()
        )""", {})

        # You don't need a session_start handler, but that is where you would broadcast initial presence.
        self.add_event_handler('message', self.message)
        self.add_event_handler('presence_probe', self.handle_probe)
    
    def cleanup(self):
        self._dbs_close()
    
    def fulljid_with_user(self):
        return 'host' + '@' + self.boundjid.full

    def message(self, msg):
        if msg['type'] in ['groupchat', 'error']: return
        if msg['to'].user == 'host':
            if msg['body'].startswith('/'):
                cmd, space, body = msg['body'].lstrip('/').partition(' ')
                if cmd == 'help':
                    msg.reply("The available commands are:"
                        + "\n    /help - print a list of commands"
                        + "\n    /echo - echo back the message you sent"
                        + "\n(All commands should be followed by a space, and then the text on which you want the command to operate.)").send()
                elif cmd == 'echo':
                    msg.reply("Echo:\n%(body)s" % {'body': body}).send()
                elif cmd == 'roster':
                    self.update_roster('hatter@localhost', name='Mad Hatter', groups=['Chatidea Contacts'])
                    msg.reply("cool").send()
                else:
                    msg.reply("I'm sorry, I didn't understand that command.\nType /help for a full list.").send()
            else:
                msg.reply("Hi, welcome to Chatidea.im!\nType /help for a list of commands.").send()
        else:
            resp = msg.reply("You've got the wrong bot!\nPlease contact host@%s for assistance." % msg['to'].domain).send()
            
    def handle_probe(self, presence):
        sender = presence['from'].user
        self.cursor_chatidea.execute("SELECT recipient FROM convo_starts WHERE sender = %(sender)s ORDER BY count DESC", {'sender': sender})
        contacts = [contact[0] for contact in self.cursor_chatidea.fetchall()]
        for contact in contacts:
            self.cursor_state.execute("""SELECT COUNT(*) FROM cur_proxybots WHERE 
                (user1 = %(sender)s AND user2 = %(contact)s) OR 
                (user1 = %(contact)s AND user2 = %(sender)s)
                """, {'sender': sender, 'contact': contact})
            if not int(self.cursor_state.fetchall()[0][0]):
                #TODO check to make sure users are online before making proxybots for them
                #   Since we can rely on the proxybot to destroy itself when it has fewer than
                #   two online users, we can just make them naively for now, but it's a hack.
                self._register_proxybot(sender, contact)
        self.sendPresence(pfrom=self.fulljid_with_user(), pnick=self.nick, pto=presence['from'], pstatus="Who do you want to chat with?", pshow="available")
    
    def _register_proxybot(self, user1, user2):
        new_jid = 'proxybot%d' % (uuid.uuid4().int)
        print new_jid
        print self.fulljid_with_user()
        iq = self.Iq()
        iq['type'] = 'set'
        iq['from'] = self.fulljid_with_user()
        iq['to'] = self.main_server
        iq['register']['username'] = new_jid
        iq['register']['password'] = PROXYBOT_PASSWORD
        try:
            iq.send()
            self.cursor_state.execute("""INSERT INTO cur_proxybots (user1, user2) 
                VALUES (%(user1)s, %(user2)s)""", {'user1': user1, 'user2': user2})
            subprocess.call(["python", "/vagrant/chatidea/proxybot_client.py", '-j', '%s@localhost' % new_jid, '-p', PROXYBOT_PASSWORD], shell=False)
            #TODO add the two users for this proxybot to the python subprocess call
            logging.info("Account created for %s!" % new_jid)
        except IqError as e:
            logging.error("Could not register account: %s" % e.iq['error']['text'])
        except IqTimeout:
            logging.error("No response from server.")

    def _dbs_open(self):
        self.db_chatidea = None
        self.cursor_chatidea = None
        self.db_state = None
        self.cursor_state = None
        try:
            self.db_chatidea = MySQLdb.connect('localhost', 'python-helper', 'vap4yirck8irg4od4lo6', 'chatidea')
            self.cursor_chatidea = self.db_chatidea.cursor()
            self.db_state = MySQLdb.connect('localhost', 'python-helper', 'vap4yirck8irg4od4lo6', 'chatidea_state')
            self.cursor_state = self.db_state.cursor()
        except MySQLdb.Error, e:
            print "Error %d: %s" % (e.args[0], e.args[1])
            self.dbs_close()
            sys.exit(1)

    def _dbs_close(self):
        if self.db_chatidea:
            self.db_chatidea.close()
        if self.db_state:
            self.db_state.close()

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
    optp.add_option("-j", "--jid", dest="jid",
                    help="JID to use")
    optp.add_option("-p", "--password", dest="password",
                    help="password to use")
    optp.add_option("-s", "--server", dest="server",
                    help="server to connect to")
    optp.add_option("-P", "--port", dest="port",
                    help="port to connect to")
    opts, args = optp.parse_args()

    if opts.jid is None:
        opts.jid = 'bot.localhost'
    if opts.password is None:
        opts.password = 'yeij9bik9fard3ij4bai'
    if opts.server is None:
        opts.server = 'localhost'
    if opts.port is None:
        opts.port = 5237

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    xmpp = HostbotComponent(opts.jid, opts.password, opts.server, opts.port)
    xmpp.registerPlugin('xep_0030') # Service Discovery
    xmpp.registerPlugin('xep_0004') # Data Forms
    xmpp.registerPlugin('xep_0060') # PubSub
    xmpp.register_plugin('xep_0077') # In-band Registration
    xmpp.registerPlugin('xep_0199') # XMPP Ping
    
    if xmpp.connect('127.0.0.1'):
        xmpp.process(block=True)
        xmpp.cleanup()
        print("Done")
    else:
        print("Unable to connect.")
