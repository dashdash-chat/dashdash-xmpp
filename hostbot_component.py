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
    def __init__(self, restore_proxybots, bounce_proxybots):
        ComponentXMPP.__init__(self, constants.hostbot_jid, constants.hostbot_secret, constants.server, constants.hostbot_port)
        self.boundjid.regenerate()
        self.auto_authorize = True
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
        self.register_plugin('xep_0030') # Service Discovery
        self.register_plugin('xep_0004') # Data Forms
        self.register_plugin('xep_0050') # Adhoc Commands
        self.register_plugin('xep_0199') # XMPP Ping
        # Connect to the database
        self.db = None
        self.cursor = None
        try:
            self.db = MySQLdb.connect(constants.server, constants.hostbot_mysql_user, constants.hostbot_mysql_password, constants.db_name)
            self.cursor = self.db.cursor()
        except MySQLdb.Error, e:
            logging.error("Failed to connect to database and creat cursor, %d: %s" % (e.args[0], e.args[1]))
            self.cleanup()
        if restore_proxybots:
            self.cursor.execute("SELECT id FROM proxybots WHERE stage != 'retired'")
            proxybot_uuids = [proxybot_uuid[0] for proxybot_uuid in self.cursor.fetchall()]
            for proxybot_uuid in proxybot_uuids:
                proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(proxybot_uuid)))
                if not self._proxybot_is_online(proxybot_jid):
                    self._launch_proxybot(['--username', proxybot_jid, '--bounced'])
                    logging.info("Restored client process for %s, %s" % (proxybot_jid, proxybot_uuid))
        if bounce_proxybots:
            self.cursor.execute("SELECT id FROM proxybots WHERE stage != 'retired'")
            proxybot_uuids = [proxybot_uuid[0] for proxybot_uuid in self.cursor.fetchall()]
            for proxybot_uuid in proxybot_uuids:
                proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(proxybot_uuid)))
                if self._proxybot_is_online(proxybot_jid):
                    session = {'next': self._cmd_complete,
                               'error': self._cmd_error}
                    self['xep_0050'].start_command(jid=self._get_jid_for_proxybot(proxybot_uuid),
                                                   node=HostbotCommand.bounce_proxybot,
                                                   session=session,
                                                   ifrom=constants.hostbot_jid)
                    logging.info("Bouncing client process for %s, %s" % (proxybot_jid, proxybot_uuid))
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
            if msg['body'].startswith('/') and msg['from'].user.startswith('admin'):
                cmd, space, body = msg['body'].lstrip('/').partition(' ')
                if cmd == 'create_user':
                    try:
                        user, password = body.split(' ')
                        new_user = self._create_user(user, password)
                        if new_user:
                            msg.reply("User %s successfully created." % new_user).send()
                        else:
                            msg.reply("Something went wrong - perhaps %s already exists?" % new_user).send()
                    except ValueError, e:
                        msg.reply("Please include a password after the username.").send()
                elif cmd == 'delete_user':
                    user = body.split(' ')[0]
                    old_user = self._delete_user(user)
                    if old_user:
                        msg.reply("User %s successfully deleted." % user).send()
                    else:
                        msg.reply("Something went wrong - perhaps %s does not exist?" % user).send()
                elif cmd == 'create_friendship':
                    user1, user2 = body.split(' ')
                    proxybot_jid = self._create_friendship(user1, user2)
                    if proxybot_jid:
                        msg.reply("Friendship for %s and %s successfully created as %s." % (user1, user2, proxybot_jid)).send()
                    else:
                        msg.reply("Something went wrong - are you sure both %s and %s exist and are not friends?" % (user1, user2)).send()
                elif cmd == 'delete_friendship':
                    user1, user2 = body.split(' ')
                    proxybot_jid = self._delete_friendship(user1, user2)
                    if proxybot_jid:
                        msg.reply("Friendship for %s and %s successfully deleted as %s." % (user1, user2, proxybot_jid)).send()
                    else:
                        msg.reply("Something went wrong - are you sure both %s and %s exist and are friends?" % (user1, user2)).send()
                elif cmd == 'restore_proxybot':
                    proxybot = body.split(' ')[0]
                    if proxybot:
                        if proxybot.startswith(constants.proxybot_prefix):
                            proxybot_jid = proxybot
                            proxybot_uuid = shortuuid.decode(proxybot.split(constants.proxybot_prefix)[1])
                        else:    
                            proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(proxybot)))
                            proxybot_uuid = proxybot
                        try:
                            self.cursor.execute("""SELECT COUNT(*) FROM proxybots WHERE 
                                id = %(proxybot_uuid)s AND stage != 'retired'""", {'proxybot_uuid': proxybot_uuid})
                            num_proxybots = self.cursor.fetchall()
                            if num_proxybots and int(num_proxybots[0][0]) > 0 and not self._proxybot_is_online(proxybot_jid):
                                self._launch_proxybot(['--username', proxybot_jid, '--bounced'])
                                msg.reply("Proxybot %s has been restarted - look for it online!" % proxybot_jid).send()
                            else:
                                msg.reply("%d proxybots found in the database for %s, %s." % (int(num_proxybots[0][0]), proxybot_jid, proxybot_uuid)).send()
                        except ValueError, e:
                            msg.reply("Error: %s\nAre you sure %s, %s is registered and in the database?" % (e, proxybot_jid, proxybot_uuid)).send()
                    else:
                        msg.reply("Please include a JID username for the proxybot.").send()
                else:
                    msg.reply("I'm sorry, I didn't understand that command.\nType /help for a full list.").send()
            else:
                msg.reply("I'm sorry, but I only understand /commands from admins.").send()
        else:
            resp = msg.reply("You've got the wrong bot!\nPlease send messages to host@%s." % msg['to'].domain).send()

    def handle_probe(self, presence):
        self.sendPresence(pfrom=self.fulljid_with_user(),
                          pnick=constants.hostbot_nick,
                          pstatus="Who do you want to chat with?",
                          pshow="available",
                          pto=presence['from'])

    def _launch_proxybot(self, proxybot_args):
        process_args = [sys.executable, "/vagrant/chatidea/proxybot_client.py", constants.daemons]
        process_args.extend(proxybot_args)
        subprocess.Popen(process_args, shell=False, stdout=open(constants.proxybot_logfile, 'a'), stderr=subprocess.STDOUT)

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
            (proxybots.stage = 'idle' OR proxybots.stage = 'active') AND
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
            self._launch_proxybot(['--username', new_jid, '--participant1', user1, '--participant2', user2])
            self._add_or_remove_observers(user1, user2, HostbotCommand.add_observer)
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
            self._add_or_remove_observers(user1, user2, HostbotCommand.remove_observer)
            return proxybot_id
        return None
    
    def _add_or_remove_observers(self, user1, user2, command):    
        # find active proxybots with each user as a participant but *not* the other, and add/remove the other as an observer
        for participant, observer in [(user1, user2), (user2, user1)]:
            self.cursor.execute("""SELECT proxybots.id FROM proxybots, proxybot_participants WHERE
                proxybots.id = proxybot_participants.proxybot_id AND
                proxybots.stage = 'active' AND
                proxybot_participants.user = %(participant)s AND
            	proxybots.id NOT IN (SELECT proxybot_id FROM proxybot_participants WHERE user =  %(observer)s)""",
            	{'participant': participant, 'observer': observer}, )
            proxybot_ids = [proxybot_id[0] for proxybot_id in self.cursor.fetchall()]
            for proxybot_id in proxybot_ids:
                session = {'participant': participant,
                           'observer': observer,
                           'next': self._cmd_send_addremove_observer,
                           'error': self._cmd_error}
                self['xep_0050'].start_command(jid=self._get_jid_for_proxybot(proxybot_id),
                                               node=command,  # they can use the same adhoc send function!
                                               session=session,
                                               ifrom=constants.hostbot_jid)

    def _get_jid_for_proxybot(self, proxybot_uuid):
        return '%s%s@%s/%s' % (constants.proxybot_prefix,
                               shortuuid.encode(uuid.UUID(proxybot_uuid)),
                               constants.server,
                               constants.proxybot_resource)

    def _find_idle_proxybot(self, user1, user2):
        self.cursor.execute("""SELECT proxybots.id FROM proxybots, 
            proxybot_participants AS proxybot_participants_1, proxybot_participants AS proxybot_participants_2 WHERE 
            proxybots.stage = 'idle' AND
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
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE user = %(user)s", {'user': user})
        num_users = self.cursor.fetchall()
        if num_users and int(num_users[0][0]) == 0:
            return False
        else:
            return True

    # Adhoc commands for which the hostbot is the user and the proxybot is the provider
    @proxybot_only
    def _cmd_send_participant_deleted(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='user', value=session['user'])
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)
    @proxybot_only
    def _cmd_send_addremove_observer(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='participant', value=session['participant'])
        form.addField(var='observer', value=session['observer'])
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)

    # Adhoc commands for which the hostbot is the provider and the proxybot is the user
    @proxybot_only
    def _cmd_receive_activate(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Activate proxybot')
        form.addField(ftype='text-single', var='proxybot')
        form.addField(ftype='text-single', var='user1')
        form.addField(ftype='text-single', var='user2')
        session['payload'] = form
        session['next'] = self._cmd_complete_activate
        session['has_next'] = False
        return session
    @proxybot_only
    def _cmd_receive_retire(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Retire proxybot')
        form.addField(ftype='text-single', var='proxybot')
        form.addField(ftype='text-single', var='user')
        session['payload'] = form
        session['next'] = self._cmd_complete_retire
        session['has_next'] = False
        return session
    @proxybot_only
    def _cmd_receive_add_participant(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Add a participant')
        form.addField(ftype='text-single', var='proxybot')
        form.addField(ftype='text-single', var='user')
        session['payload'] = form
        session['next'] = self._cmd_complete_add_participant
        session['has_next'] = False
        return session
    @proxybot_only
    def _cmd_receive_remove_participant(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Remove a participant')
        form.addField(ftype='text-single', var='proxybot')
        form.addField(ftype='text-single', var='user')
        session['payload'] = form
        session['next'] = self._cmd_complete_remove_participant
        session['has_next'] = False
        return session
    def _cmd_complete_activate(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user1 = form['values']['user1']
        user2 = form['values']['user2']
        self.cursor.execute("UPDATE proxybots SET stage = 'active' WHERE id = %(id)s", {'id': shortuuid.decode(proxybot_id)})
        self._create_friendship(user1, user2)  #NOTE activate before creating the new proxybot, so the idle-does-not-exist check passes
        session['payload'] = None
        session['next'] = None
        return session
    def _cmd_complete_retire(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self.cursor.execute("UPDATE proxybots SET stage = 'retired' WHERE id = %(id)s", {'id': shortuuid.decode(proxybot_id)})
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
        self.cursor.execute("DELETE FROM proxybot_participants WHERE user = %(user)s and proxybot_id = %(proxybot_id)s",
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

    def _proxybot_is_online(self, proxybot_jid):
        try:              
            res = self._xmlrpc_command('user_sessions_info', {
                'user': proxybot_jid,
                'host': constants.server
            })
            return len(res['sessions_info']) > 0
        except xmlrpclib.ProtocolError, e:
            logging.error('ProtocolError in is_online for %s, assuming offline: %s' % (proxybot_jid, str(e)))
            return False
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
    optp.add_option('-r', '--restore', help='restore inactive proxybots from the db',
                    action='store_const', dest='restore',
                    const=True, default=False)
    optp.add_option('-b', '--bounce', help='bounce all of the online proxybots',
                    action='store_const', dest='bounce',
                    const=True, default=False)
    opts, args = optp.parse_args()

    logging.basicConfig(level=opts.loglevel,
                        format='Hostbot  %(levelname)-8s %(message)s')

    xmpp = HostbotComponent(opts.restore, opts.bounce)
    
    if xmpp.connect(constants.server):
        xmpp.process(block=True)
        xmpp.cleanup()
        print("Hostbot done")
    else:
        print("Hostbot unable to connect.")
