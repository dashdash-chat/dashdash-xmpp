#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
import logging
import getpass
from optparse import OptionParser
import subprocess
import uuid
import shortuuid
import xmlrpclib
import sleekxmpp
from sleekxmpp.componentxmpp import ComponentXMPP
from sleekxmpp.exceptions import IqError, IqTimeout
import constants
from constants import Stage, ProxybotCommand

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

class HostbotComponent(ComponentXMPP):
    def __init__(self):
        ComponentXMPP.__init__(self, constants.hostbot_jid, constants.hostbot_secret, constants.server, constants.hostbot_port)
        shortuuid.set_alphabet('1234567890abcdefghijklmnopqrstuvwxyz')
        self.boundjid.regenerate()
        self.nick = 'Hostbot'
        self.auto_authorize = True
        # Connect to the database
        self.db = None
        self.cursor = None
        try:
            self.db = MySQLdb.connect(constants.server, constants.hostbot_mysql_user, constants.hostbot_mysql_password, constants.db_name)
            self.cursor = self.db.cursor()
        except MySQLdb.Error, e:
            logging.error("Failed to connect to database and creat cursor, %d: %s" % (e.args[0], e.args[1]))
            self.cleanup()
        # Initialize user accounts #LATER remove when I have real users
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
        self.cursor.execute("SELECT username FROM users WHERE has_jid = 0")
        usernames = [username[0] for username in self.cursor.fetchall()] 
        for username in usernames:
            try:
                self._xmlrpc_command('register', {
                    'user': username,
                    'host': constants.server,
                    'password': constants.default_user_password
                })
                self.cursor.execute("UPDATE users SET has_jid = 1 WHERE username = %(username)s", {'username': username})
            except MySQLdb.Error, e:
                logging.error('Failed to register account for user %s with MySQL error %s' % (username, e))
                self.cleanup()
            except xmlrpclib.ProtocolError, e:
                logging.error('Failed to register account for user %s with XML RPC error %s' % (username, e))
                self.cleanup()
        # Unregister old proxybots
        self.cursor.execute("SELECT id FROM cur_proxybots", {})
        proxybot_ids = [proxybot_id[0] for proxybot_id in self.cursor.fetchall()]
        for proxybot_id in proxybot_ids:
            self._xmlrpc_command('unregister', {
                'user': '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(proxybot_id))),
                'host': constants.server,
            })
        # Initialize database tables
        self.cursor.execute("DROP TABLE IF EXISTS cur_proxybots;", {})
        self.cursor.execute("""CREATE TABLE cur_proxybots (
            id CHAR(36) NOT NULL PRIMARY KEY,
          state ENUM('idle', 'active', 'retired') NOT NULL,
            created TIMESTAMP DEFAULT NOW()
        )""", {})
        self.cursor.execute("DROP TABLE IF EXISTS cur_proxybot_participants;", {})
        self.cursor.execute("""CREATE TABLE cur_proxybot_participants (
            proxybot_id CHAR(36) NOT NULL,
          FOREIGN KEY (proxybot_id) REFERENCES cur_proxybots(id),
          username VARCHAR(15),
            created TIMESTAMP DEFAULT NOW()
        )""", {})
        # Add event handlers
        self.add_event_handler("session_start", self.start)
        self.add_event_handler('message', self.message)
        self.add_event_handler('presence_probe', self.handle_probe)

    def start(self, event):
        # Register these commands *after* session_start
        self['xep_0050'].add_command(node=ProxybotCommand.activate,
                                     name='Activate proxybot',
                                     handler=self._command_activate,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=ProxybotCommand.retire,
                                     name='Retire proxybot',
                                     handler=self._command_retire,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=ProxybotCommand.add_participant,
                                     name='Add a participant',
                                     handler=self._command_add_participant,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=ProxybotCommand.remove_participant,
                                     name='Remove a participant',
                                     handler=self._command_remove_participant,
                                     jid=self.boundjid.full)
        # Create the proxybots *after* those commands are ready 
        self.cursor.execute("SELECT sender, recipient FROM convo_starts", {})
        undirected_graph_edges = set([frozenset(pair) for pair in self.cursor.fetchall()])  # symmetric relationships for now
        for edge in undirected_graph_edges:
            user1, user2 = list(edge)
            self._create_new_proxybot(user1, user2)
        self.send_presence(pfrom=self.fulljid_with_user(), pnick=self.nick, pstatus="Who do you want to chat with?", pshow="available")
    
    def _create_new_proxybot(self, user1, user2):
        proxybot_id = uuid.uuid4()
        new_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(proxybot_id))
        try:
            self._xmlrpc_command('register', {
                'user': new_jid,
                'host': constants.server,
                'password': constants.proxybot_password
            })
            self.cursor.execute("INSERT INTO cur_proxybots (id) VALUES (%(proxybot_id)s)", {'proxybot_id': proxybot_id})
            self.cursor.execute("INSERT INTO cur_proxybot_participants (proxybot_id, username) VALUES (%(proxybot_id)s, %(username)s)",
                {'proxybot_id': proxybot_id, 'username': user1})
            self.cursor.execute("INSERT INTO cur_proxybot_participants (proxybot_id, username) VALUES (%(proxybot_id)s, %(username)s)",
                {'proxybot_id': proxybot_id, 'username': user2})
            subprocess.Popen([sys.executable, "/vagrant/chatidea/proxybot_client.py",
                '-u', new_jid,
                '-1', user1,
                '-2', user2,
                '--daemon'], shell=False)#, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            logging.info("Proxybot %s created for %s and %s" % (new_jid, user1, user2))
        except MySQLdb.Error, e:
            logging.error('Failed to register proxybot %s for %s and %s with MySQL error %s' % (new_jid, user1, user2, e))
        except xmlrpclib.Fault as e:
            logging.error("Could not register account: %s" % e)

    def cleanup(self):
        if self.db:
            self.db.close()
        sys.exit(1)
    
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
                else:
                    msg.reply("I'm sorry, I didn't understand that command.\nType /help for a full list.").send()
            else:
                msg.reply("Hi, welcome to Chatidea.im!\nType /help for a list of commands.").send()
        else:
            resp = msg.reply("You've got the wrong bot!\nPlease contact host@%s for assistance." % msg['to'].domain).send()
            
    def handle_probe(self, presence):
        self.sendPresence(pfrom=self.fulljid_with_user(), pnick=self.nick, pstatus="Who do you want to chat with?", pshow="available", pto=presence['from'])

    def _command_activate(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Activate proxybot')
        form['instructions'] = 'Record the activation of a proxybot in the database.'
        form.addField(var='proxybot',
                      ftype='text-single',
                      label='The username of the proxybot')
        form.addField(var='user1',
                      ftype='text-single',
                      label='The first of the two users in the conversation')
        form.addField(var='user2',
                      ftype='text-single',
                      label='The second of the two users in the conversation')
        session['payload'] = form
        session['next'] = self._command_activate_complete
        session['has_next'] = False
        return session
    def _command_retire(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Retire proxybot')
        form['instructions'] = 'Record the retirement of a proxybot in the database.'
        form.addField(var='proxybot',
                      ftype='text-single',
                      label='The username of the proxybot')
        form.addField(var='user',
                      ftype='text-single',
                      label='The last user to leave the conversation')
        session['payload'] = form
        session['next'] = self._command_retire_complete
        session['has_next'] = False
        return session
    def _command_add_participant(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Add a participant')
        form['instructions'] = 'Record the addition of a participant to an active proxybot in the database.'
        form.addField(var='proxybot',
                      ftype='text-single',
                      label='The username of the proxybot')
        form.addField(var='user',
                      ftype='text-single',
                      label='The user to add')
        session['payload'] = form
        session['next'] = self._command_add_participant_complete
        session['has_next'] = False
        return session
    def _command_remove_participant(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Remove a participant')
        form['instructions'] = 'Record the removal of a participant from an active proxybot in the database.'
        form.addField(var='proxybot',
                      ftype='text-single',
                      label='The username of the proxybot')
        form.addField(var='user',
                      ftype='text-single',
                      label='The user to remove')
        session['payload'] = form
        session['next'] = self._command_remove_participant_complete
        session['has_next'] = False
        return session
    def _command_activate_complete(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user1 = form['values']['user1']
        user2 = form['values']['user2']
        self._create_new_proxybot(user1, user2)
        self.cursor.execute("UPDATE cur_proxybots SET state = 'active' WHERE id = %(id)s", {'id': shortuuid.decode(proxybot_id)})
        session['payload'] = None
        session['next'] = None
        return session
    def _command_retire_complete(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self.cursor.execute("UPDATE cur_proxybots SET state = 'retired' WHERE id = %(id)s", {'id': shortuuid.decode(proxybot_id)})
        self.cursor.execute("DELETE FROM cur_proxybot_participants WHERE username = %(username)s and proxybot_id = %(proxybot_id)s",
            {'username': user, 'proxybot_id': shortuuid.decode(proxybot_id)})
        session['payload'] = None
        session['next'] = None
        return session
    def _command_add_participant_complete(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self.cursor.execute("INSERT INTO cur_proxybot_participants (proxybot_id, username) VALUES (%(proxybot_id)s, %(username)s)",
            {'proxybot_id': shortuuid.decode(proxybot_id), 'username': user})
        session['payload'] = None
        session['next'] = None
        return session
    def _command_remove_participant_complete(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self.cursor.execute("DELETE FROM cur_proxybot_participants WHERE username = %(username)s and proxybot_id = %(proxybot_id)s",
            {'username': user, 'proxybot_id': shortuuid.decode(proxybot_id)})
        session['payload'] = None
        session['next'] = None
        return session

    def _xmlrpc_command(self, command, data):
        fn = getattr(self.xmlrpc_server, command)
        return fn({
            'user': constants.hostbot_xmlrpc_jid,  #NOTE the server is not bot.localhost because of xml_rpc authentication
            'server': constants.server,
            'password': constants.hostbot_xmlrpc_password
        }, data)


if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
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

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    xmpp = HostbotComponent()
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0004') # Data Forms
    xmpp.register_plugin('xep_0050') # Adhoc Commands
    xmpp.register_plugin('xep_0199') # XMPP Ping
    
    if xmpp.connect(constants.server):
        xmpp.process(block=True)
        xmpp.cleanup()
        print("Done")
    else:
        print("Unable to connect.")
