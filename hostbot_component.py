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
from constants import Stage, ProxybotCommand, HostbotCommand

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


def proxybot_only(fn):
    def wrapped(*args, **kwargs):
        if args[1]['from'].user.startswith(constants.proxybot_prefix):
            return fn(*args, **kwargs)
        else:
            logging.error("This command can only be invoked by a proxybot, but the IQ stanza was from %s." % args[1]['from'])
            return
    return wrapped


class HostbotComponent(ComponentXMPP):
    def __init__(self):
        ComponentXMPP.__init__(self, constants.hostbot_jid, constants.hostbot_secret, constants.server, constants.hostbot_port)
        shortuuid.set_alphabet('1234567890abcdefghijklmnopqrstuvwxyz')
        self.boundjid.regenerate()
        self.auto_authorize = True
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
        # Connect to the database
        self.db = None
        self.cursor = None
        try:
            self.db = MySQLdb.connect(constants.server, constants.hostbot_mysql_user, constants.hostbot_mysql_password, constants.db_name)
            self.cursor = self.db.cursor()
        except MySQLdb.Error, e:
            logging.error("Failed to connect to database and creat cursor, %d: %s" % (e.args[0], e.args[1]))
            self.cleanup()
        # Add event handlers
        self.add_event_handler("session_start", self.start)
        self.add_event_handler('message', self.message)
        self.add_event_handler('presence_probe', self.handle_probe)

    def start(self, event):
        # Register these commands *after* session_start
        self['xep_0050'].add_command(node=ProxybotCommand.activate,
                                     name='Activate proxybot',
                                     handler=self._cmd_receive_activate,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=ProxybotCommand.retire,
                                     name='Retire proxybot',
                                     handler=self._cmd_receive_retire,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=ProxybotCommand.add_participant,
                                     name='Add a participant',
                                     handler=self._cmd_receive_add_participant,
                                     jid=self.boundjid.full)
        self['xep_0050'].add_command(node=ProxybotCommand.remove_participant,
                                     name='Remove a participant',
                                     handler=self._cmd_receive_remove_participant,
                                     jid=self.boundjid.full)
        self.send_presence(pfrom=self.fulljid_with_user(), pnick=constants.hostbot_nick, pstatus="Who do you want to chat with?", pshow="available")

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
                elif cmd == 'create_user' and msg['from'].user.startswith('admin'):
                    try:
                        user, password = body.split(' ')
                        new_user = self._create_user(user, password)
                        if new_user:
                            msg.reply("User %s successfully created." % new_user).send()
                        else:
                            msg.reply("Something went wrong - perhaps %s already exists?" % new_user).send()
                    except ValueError, e:
                        msg.reply("Please include a password after the username.").send()
                elif cmd == 'delete_user' and msg['from'].user.startswith('admin'):
                    user = body.split(' ')[0]
                    old_user = self._delete_user(user)
                    if old_user:
                        msg.reply("User %s successfully deleted." % user).send()
                    else:
                        msg.reply("Something went wrong - perhaps %s does not exist?" % user).send()
                elif cmd == 'create_friendship' and msg['from'].user.startswith('admin'):
                    user1, user2 = body.split(' ')
                    proxybot_jid = self._create_friendship(user1, user2)
                    if proxybot_jid:
                        msg.reply("Friendship for %s and %s successfully created as %s." % (user1, user2, proxybot_jid)).send()
                    else:
                        msg.reply("Something went wrong - are you sure both %s and %s exist and are not friends?" % (user1, user2)).send()
                elif cmd == 'delete_friendship' and msg['from'].user.startswith('admin'):
                    user1, user2 = body.split(' ')
                    proxybot_jid = self._delete_friendship(user1, user2)
                    if proxybot_jid:
                        msg.reply("Friendship for %s and %s successfully deleted as %s." % (user1, user2, proxybot_jid)).send()
                    else:
                        msg.reply("Something went wrong - are you sure both %s and %s exist and are friends?" % (user1, user2)).send()
                else:
                    msg.reply("I'm sorry, I didn't understand that command.\nType /help for a full list.").send()
            else:
                msg.reply("Hi, welcome to Chatidea.im!\nType /help for a list of commands.").send()
        else:
            resp = msg.reply("You've got the wrong bot!\nPlease contact host@%s for assistance." % msg['to'].domain).send()

    def handle_probe(self, presence):
        self.sendPresence(pfrom=self.fulljid_with_user(), pnick=constants.hostbot_nick, pstatus="Who do you want to chat with?", pshow="available", pto=presence['from'])

    def _create_user(self, user, password):
        #LATER validate that user does not start with admin or any of the other reserverd names
        user = user.lower()
        if self._user_exists(user):
            return None
        self._xmlrpc_command('register', {
            'user': user,
            'host': constants.server,
            'password': password
        })
        self.cursor.execute("INSERT INTO users (user) VALUES (%(user)s)", {'user': user})
        return user

    def _delete_user(self, user):
        if not self._user_exists(user):
            return None
        self._xmlrpc_command('unregister', {
            'user': user,
            'host': constants.server,
        })
        self.cursor.execute("DELETE FROM users WHERE user = %(user)s", {'user': user})
        # tell the non-retired proxybots to remove this participant - they should then be able to take care of themselves as appropriate
        self.cursor.execute("""SELECT proxybots.id FROM proxybots, proxybot_participants WHERE
            proxybots.id = proxybot_participants.proxybot_id AND
            (proxybots.state = 'idle' OR proxybots.state = 'active') AND
            proxybot_participants.user = %(user)s""", {'user': user})
        proxybot_ids = [proxybot_id[0] for proxybot_id in self.cursor.fetchall()]
        for proxybot_id in proxybot_ids:
            session = {'user': user,
                       'next': self._cmd_send_participant_deleted,
                       'error': self._cmd_error}
            self['xep_0050'].start_command(jid=self._get_jid_for_proxybot(proxybot_id),
                                           node=HostbotCommand.participant_deleted,
                                           session=session,
                                           ifrom=constants.hostbot_jid)
        return user
     
    def _create_friendship(self, user1, user2):
        if not (self._user_exists(user1) and self._user_exists(user2)):
            return None
        proxybot_id = self._find_idle_proxybot(user1, user2)
        if proxybot_id:
            logging.error("Idle proxybots %s arleady exists for %s and %s!" % (proxybot_id, user1, user2))
            return None
        proxybot_id = uuid.uuid4()
        new_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(proxybot_id))
        try:
            self._xmlrpc_command('register', {
                'user': new_jid,
                'host': constants.server,
                'password': constants.proxybot_password
            })
            self.cursor.execute("INSERT INTO proxybots (id) VALUES (%(proxybot_id)s)", {'proxybot_id': proxybot_id})
            self.cursor.execute("""INSERT INTO proxybot_participants (proxybot_id, user) VALUES 
                (%(proxybot_id)s, %(user1)s), (%(proxybot_id)s, %(user2)s)""",
                {'proxybot_id': proxybot_id, 'user1': user1, 'user2': user2})
            subprocess.Popen([sys.executable, "/vagrant/chatidea/proxybot_client.py",
                '--daemon',
                #'-v',
                '-u', new_jid,
                '-1', user1,
                '-2', user2], shell=False)#, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            logging.info("Proxybot %s created for %s and %s" % (new_jid, user1, user2))
        except MySQLdb.Error, e:
            logging.error('Failed to register proxybot %s for %s and %s with MySQL error %s' % (new_jid, user1, user2, e))
        except xmlrpclib.Fault as e:
            logging.error("Could not register account: %s" % e)
        return new_jid

    def _delete_friendship(self, user1, user2):
        if not (self._user_exists(user1) and self._user_exists(user2)):
            return None
        proxybot_id = self._find_idle_proxybot(user1, user2)
        if proxybot_id:
            session = {'next': self._cmd_complete,
                       'error': self._cmd_error}
            self['xep_0050'].start_command(jid=self._get_jid_for_proxybot(proxybot_id),
                                           node=HostbotCommand.delete_proxybot,
                                           session=session,
                                           ifrom=constants.hostbot_jid)
            self.cursor.execute("DELETE FROM proxybot_participants WHERE proxybot_id = %(proxybot_id)s", {'proxybot_id': proxybot_id})
            self.cursor.execute("DELETE FROM proxybots WHERE id = %(proxybot_id)s", {'proxybot_id': proxybot_id})
            return proxybot_id
        return None

    def _get_jid_for_proxybot(self, proxybot_id):
        return '%s%s@%s/%s' % (constants.proxybot_prefix,
                               shortuuid.encode(uuid.UUID(proxybot_id)),
                               constants.server,
                               constants.proxybot_resource)

    def _find_idle_proxybot(self, user1, user2):
        self.cursor.execute("""SELECT proxybots.id FROM proxybots, 
            proxybot_participants AS proxybot_participants_1, proxybot_participants AS proxybot_participants_2 WHERE 
            proxybots.state = 'idle' AND
            proxybots.id = proxybot_participants_1.proxybot_id AND
            proxybots.id = proxybot_participants_2.proxybot_id AND
            proxybot_participants_1.user = %(user1)s AND
            proxybot_participants_2.user = %(user2)s""", {'user1': user1, 'user2': user2})
        proxybot_ids = [proxybot_id[0] for proxybot_id in self.cursor.fetchall()]
        if len(proxybot_ids) == 0:
            return None
        elif len(proxybot_ids) == 1:
            return proxybot_ids[0]
        else:
            logging.error("There are %d idle proxybots for %s and %s! There should only be 1." % (len(proxybot_ids), user1, user2))
            return None

    def _user_exists(self, user):
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE user=%(user)s", {'user': user})
        num_users = self.cursor.fetchall()
        if num_users and int(num_users[0][0]) == 0:
            return False
        else:
            return True

    # Adhoc commands for which the hostbot is the user and the proxybot is the provider
    @proxybot_only
    def _cmd_send_participant_deleted(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='user',
                      value=session['user'])
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)

    # Adhoc commands for which the hostbot is the provider and the proxybot is the user
    @proxybot_only
    def _cmd_receive_activate(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Activate proxybot')
        form['instructions'] = 'Record the activation of a proxybot in the database.'
        form.addField(var='proxybot',
                      ftype='text-single',
                      label='The user of the proxybot')
        form.addField(var='user1',
                      ftype='text-single',
                      label='The first of the two users in the conversation')
        form.addField(var='user2',
                      ftype='text-single',
                      label='The second of the two users in the conversation')
        session['payload'] = form
        session['next'] = self._cmd_complete_activate
        session['has_next'] = False
        return session
    @proxybot_only
    def _cmd_receive_retire(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Retire proxybot')
        form['instructions'] = 'Record the retirement of a proxybot in the database.'
        form.addField(var='proxybot',
                      ftype='text-single',
                      label='The user of the proxybot')
        form.addField(var='user',
                      ftype='text-single',
                      label='The last user to leave the conversation')
        session['payload'] = form
        session['next'] = self._cmd_complete_retire
        session['has_next'] = False
        return session
    @proxybot_only
    def _cmd_receive_add_participant(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Add a participant')
        form['instructions'] = 'Record the addition of a participant to an active proxybot in the database.'
        form.addField(var='proxybot',
                      ftype='text-single',
                      label='The user of the proxybot')
        form.addField(var='user',
                      ftype='text-single',
                      label='The user to add')
        session['payload'] = form
        session['next'] = self._cmd_complete_add_participant
        session['has_next'] = False
        return session
    @proxybot_only
    def _cmd_receive_remove_participant(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Remove a participant')
        form['instructions'] = 'Record the removal of a participant from an active proxybot in the database.'
        form.addField(var='proxybot',
                      ftype='text-single',
                      label='The user of the proxybot')
        form.addField(var='user',
                      ftype='text-single',
                      label='The user to remove')
        session['payload'] = form
        session['next'] = self._cmd_complete_remove_participant
        session['has_next'] = False
        return session
    def _cmd_complete_activate(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user1 = form['values']['user1']
        user2 = form['values']['user2']
        self.cursor.execute("UPDATE proxybots SET state = 'active' WHERE id = %(id)s", {'id': shortuuid.decode(proxybot_id)})
        self._create_friendship(user1, user2)  #NOTE activate before creating the new proxybot, so the idle-does-not-exist check passes
        session['payload'] = None
        session['next'] = None
        return session
    def _cmd_complete_retire(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self.cursor.execute("UPDATE proxybots SET state = 'retired' WHERE id = %(id)s", {'id': shortuuid.decode(proxybot_id)})
        self.cursor.execute("DELETE FROM proxybot_participants WHERE user = %(user)s and proxybot_id = %(proxybot_id)s",
            {'user': user, 'proxybot_id': shortuuid.decode(proxybot_id)})
        session['payload'] = None
        session['next'] = None
        return session
    def _cmd_complete_add_participant(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self.cursor.execute("INSERT INTO proxybot_participants (proxybot_id, user) VALUES (%(proxybot_id)s, %(user)s)",
            {'proxybot_id': shortuuid.decode(proxybot_id), 'user': user})
        session['payload'] = None
        session['next'] = None
        return session
    def _cmd_complete_remove_participant(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self.cursor.execute("DELETE FROM cur_proxybot_participants WHERE user = %(user)s and proxybot_id = %(proxybot_id)s",
            {'user': user, 'proxybot_id': shortuuid.decode(proxybot_id)})
        session['payload'] = None
        session['next'] = None
        return session
    
    # Adhoc commands - general functions
    def _cmd_complete(self, iq, session):
        self['xep_0050'].complete_command(session)
    def _cmd_error(self, iq, session):
        logging.error("COMMAND: %s %s" % (iq['error']['condition'],
                                          iq['error']['text']))
        self['xep_0050'].terminate_command(session)

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
