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
from slash_commands import SlashCommand, SlashCommandRegistry, ExecutionError
from proxybot_user import User
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
            logging.warning("%s tried to use a proxybot ad hoc command: %s" % args[1]['from'], args[1]['body'])
            return
    return wrapped


class HostbotComponent(ComponentXMPP):
    def __init__(self, restore_proxybots, bounce_proxybots):
        ComponentXMPP.__init__(self, constants.hostbot_component_jid, constants.hostbot_secret, constants.server, constants.component_port)
        self.boundjid.regenerate()
        self.auto_authorize = True
        self.db = None
        self.cursor = None
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
        self.register_plugin('xep_0030') # Service Discovery
        self.register_plugin('xep_0004') # Data Forms
        self.register_plugin('xep_0050') # Adhoc Commands
        self.register_plugin('xep_0199') # XMPP Ping
        if restore_proxybots:
            proxybot_uuids = self._db_execute_and_fetchall("SELECT id FROM proxybots WHERE stage != 'retired'")
            for proxybot_uuid in proxybot_uuids:
                proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(proxybot_uuid)))
                if not self._proxybot_is_online(proxybot_jid):
                    self._launch_proxybot(['--username', proxybot_jid, '--bounced'])
                    logging.info("Restored client process for %s, %s" % (proxybot_jid, proxybot_uuid))
        if bounce_proxybots:
            proxybot_uuids = self._db_execute_and_fetchall("SELECT id FROM proxybots WHERE stage != 'retired'")
            for proxybot_uuid in proxybot_uuids:
                proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(proxybot_uuid)))
                try:
                    self._proxybot_bounce(proxybot_jid, proxybot_uuid)
                except ExecutionError:
                    logging.info("%s, %s wasn't online, so can't be bounced" % (proxybot_jid, proxybot_uuid))
        # Set up slash commands to be handled by the hostbot's SlashCommandRegistry
        self.commands = SlashCommandRegistry()
        def is_admin(sender):
            return sender.bare in constants.admin_users
        def has_none(sender, arg_string, arg_tokens):
            if len(arg_tokens) == 0:
                return []
            return False
        def has_one_token(sender, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                return arg_tokens
            return False
        def has_two_tokens(sender, arg_string, arg_tokens):
            if len(arg_tokens) == 2:
                return arg_tokens
            return False
        def has_proxybot_id(sender, arg_string, arg_tokens):
            if len(arg_tokens) == 1:
                proxybot = arg_tokens[0]
                if proxybot.startswith(constants.proxybot_prefix):
                    proxybot = proxybot.split('@')[0]
                    try:
                        proxybot_jid = proxybot
                        proxybot_uuid = shortuuid.decode(proxybot.split(constants.proxybot_prefix)[1])
                    except ValueError, e:
                        return False
                else:
                    try:
                        proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(proxybot)))
                        proxybot_uuid = uuid.UUID(proxybot)
                    except ValueError, e:
                        return False
                return (proxybot_jid, proxybot_uuid)
            return False         
        def all_or_proxybot_id(sender, arg_string, arg_tokens):
            if len(arg_tokens) == 1 and arg_tokens[0] == 'all':
                return [arg_tokens[0], None]
            return has_proxybot_id(sender, arg_string, arg_tokens)
        self.commands.add(SlashCommand(command_name     = 'new_user',
                                       text_arg_format  = 'username password',
                                       text_description = 'Create a new user in both ejabberd and the Vine database.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_two_tokens,
                                       action           = self._create_user))
        self.commands.add(SlashCommand(command_name     = 'del_user',
                                       text_arg_format  = 'username',
                                       text_description = 'Unregister a user in ejabberd and remove her from the Vine database and applicable proxybots.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_one_token,
                                       action           = self._delete_user))
        self.commands.add(SlashCommand(command_name     = 'new_friendship',
                                       text_arg_format  = 'arg1 arg2',
                                       text_description = 'Create a friendship (and launch a new idle proxybot) between two users.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_two_tokens,
                                       action           = self._create_friendship))
        self.commands.add(SlashCommand(command_name     = 'del_friendship',
                                       text_arg_format  = 'username1 username2',
                                       text_description = 'Delete a friendship (and destroy the idle proxybot) between two users.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_two_tokens,
                                       action           = self._delete_friendship))
        self.commands.add(SlashCommand(command_name     = 'friendships',
                                       text_arg_format  = '',
                                       text_description = 'List all current friendships (i.e., all idle proxybots).',
                                       validate_sender  = is_admin,
                                       transform_args   = has_none,
                                       action           = self._list_friendships))
        self.commands.add(SlashCommand(command_name     = 'restore',
                                       text_arg_format  = 'proxybot_jid OR proxybot_uuid',
                                       text_description = 'Restore an idle or active proxybot from the database.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_proxybot_id,
                                       action           = self._proxybot_restore))
        self.commands.add(SlashCommand(command_name     = 'bounce',
                                       text_arg_format  = 'proxybot_jid OR proxybot_uuid',
                                       text_description = 'Bounce a single proxybot.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_proxybot_id,
                                       action           = self._proxybot_bounce))
        self.commands.add(SlashCommand(command_name     = 'status',
                                       text_arg_format  = 'proxybot_jid OR proxybot_uuid',
                                       text_description = 'Check the status of a proxybot.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_proxybot_id,
                                       action           = self._proxybot_status))
        self.commands.add(SlashCommand(command_name     = 'cleanup',
                                       text_arg_format  = 'proxybot_jid OR proxybot_uuid',
                                       text_description = 'Set a proxybot to retired in the database, and remove it from everyone\'s rosters.',
                                       validate_sender  = is_admin,
                                       transform_args   = has_proxybot_id,
                                       action           = self._proxybot_cleanup))
        self.commands.add(SlashCommand(command_name     = 'purge',
                                       text_arg_format  = 'proxybot_jid OR proxybot_uuid OR \'all\'',
                                       text_description = 'Remove a database entry (and associated participants) for a specific proxybot, or for all proxybots.',
                                       validate_sender  = is_admin,
                                       transform_args   = all_or_proxybot_id,
                                       action           = self._proxybot_purge))
        # Add event handlers
        self.add_event_handler("session_start", self._handle_start)
        self.add_event_handler('message', self._handle_message)
        self.add_event_handler('presence_probe', self._handle_probe)

    def _handle_start(self, event):
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
        self.send_presence(pfrom=constants.hostbot_user_jid, pnick=constants.hostbot_nick, pshow="available")
        logging.info("Session started")

    def _handle_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if msg['to'].user == constants.hostbot_user:
                if self.commands.is_command(msg['body']):
                    msg.reply(self.commands.handle_command(msg['from'], msg['body'])).send()
                else:
                    msg.reply(self.commands.handle_command(msg['from'], '/help')).send()
            else:
                resp = msg.reply("You've got the wrong bot!\nPlease send messages to %s@%s." % (constants.hostbot_user, constants.hostbot_server)).send()

    def _handle_probe(self, presence):
        self.sendPresence(pfrom=constants.hostbot_user_jid, pnick=constants.hostbot_nick, pshow="available", pto=presence['from'])

    def _launch_proxybot(self, proxybot_args):
        process_args = [sys.executable, constants.proxybot_script, '--daemon']
        process_args.extend(proxybot_args)
        subprocess.Popen(process_args, shell=False, stdout=open(constants.proxybot_logfile, 'a'), stderr=subprocess.STDOUT)

    def _create_user(self, user, password):
        #LATER validate that user does not start with admin or any of the other reserverd names
        user = user.lower()
        if self._user_exists(user):
            raise ExecutionError, 'User %s already exists in the Vine database' % user
        self._xmlrpc_command('register', {
            'user': user,
            'host': constants.server,
            'password': password
        })
        self._db_execute("INSERT INTO users (user) VALUES (%(user)s)", {'user': user})
        logging.info("Creating user %s" % user)
    def _delete_user(self, user):
        if not self._user_exists(user):
            raise ExecutionError, 'User %s does not exist in the Vine database' % user
        self._xmlrpc_command('unregister', {
            'user': user,
            'host': constants.server,
        })
        self._db_execute("DELETE FROM users WHERE user = %(user)s", {'user': user})
        # tell the non-retired proxybots to remove this participant - they should then be able to take care of themselves as appropriate
        proxybot_ids = self._db_execute_and_fetchall("""SELECT proxybots.id FROM proxybots, proxybot_participants WHERE
            proxybots.id = proxybot_participants.proxybot_id AND
            (proxybots.stage = 'idle' OR proxybots.stage = 'active') AND
            proxybot_participants.user = %(user)s""", {'user': user})
        for proxybot_id in proxybot_ids:
            session = {'user': user,
                       'next': self._cmd_send_participant_deleted,
                       'error': self._cmd_error}
            self['xep_0050'].start_command(jid=self._full_jid_for_proxybot(proxybot_id),
                                           node=HostbotCommand.participant_deleted,
                                           session=session,
                                           ifrom=constants.hostbot_component_jid)
        logging.info("Deleting user %s" % user)

    def _create_friendship(self, user1, user2):
        if not self._user_exists(user1):
            raise ExecutionError, 'User1 %s does not exist in the Vine database' % user1
        if not self._user_exists(user2):
            raise ExecutionError, 'User2 %s does not exist in the Vine database' % user2
        (proxybot_jid, proxybot_uuid) = self._find_idle_proxybot(user1, user2)
        if proxybot_jid and proxybot_uuid:
            raise ExecutionError, 'Idle proxybot %s arleady exists for %s and %s!' % (proxybot_id, user1, user2)
        proxybot_uuid = uuid.uuid4()
        proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(proxybot_uuid))
        try:
            self._xmlrpc_command('register', {
                'user': proxybot_jid,
                'host': constants.server,
                'password': constants.proxybot_password
            })
            self._db_execute("INSERT INTO proxybots (id) VALUES (%(proxybot_id)s)", {'proxybot_id': proxybot_uuid})
            self._db_execute("""INSERT INTO proxybot_participants (proxybot_id, user) VALUES 
                (%(proxybot_id)s, %(user1)s), (%(proxybot_id)s, %(user2)s)""",
                {'proxybot_id': proxybot_uuid, 'user1': user1, 'user2': user2})
            self._launch_proxybot(['--username', proxybot_jid, '--participant1', user1, '--participant2', user2])
            self._add_or_remove_observers(user1, user2, HostbotCommand.add_observer)
            logging.info('Friendship %s, %s created for %s and %s' % (proxybot_jid, proxybot_uuid, user1, user2))
            return 'Friendship for %s and %s successfully created as %s.' % (user1, user2, proxybot_jid)
        except MySQLdb.Error, e:
            logging.error('Failed to register %s, %s for %s and %s with MySQL error %s' % (proxybot_jid, proxybot_uuid, user1, user2, e))
            raise ExecutionError
        except xmlrpclib.Fault as e:
            logging.error('Failed to register %s, %s for %s and %s with XMLRPC error %s' % (proxybot_jid, proxybot_uuid, user1, user2, e))
            raise ExecutionError
    def _delete_friendship(self, user1, user2):
        if not self._user_exists(user1):
            raise ExecutionError, 'User1 %s does not exist in the Vine database' % user1
        if not self._user_exists(user2):
            raise ExecutionError, 'User2 %s does not exist in the Vine database' % user2
        proxybot_jid, proxybot_uuid = self._find_idle_proxybot(user1, user2)
        if not proxybot_jid or not proxybot_uuid:
            raise ExecutionError, 'Idle proxybot not found %s and %s.' % (user1, user2)
        session = {'next': self._cmd_send_delete_proxybot,
                   'error': self._cmd_error}
        self['xep_0050'].start_command(jid=self._full_jid_for_proxybot(proxybot_uuid),
                                       node=HostbotCommand.delete_proxybot,
                                       session=session,
                                       ifrom=constants.hostbot_component_jid)
        try:
            self._db_execute("DELETE FROM proxybot_participants WHERE proxybot_id = %(proxybot_id)s", {'proxybot_id': proxybot_uuid})
            self._db_execute("DELETE FROM proxybots WHERE id = %(proxybot_id)s", {'proxybot_id': proxybot_uuid})
            self._add_or_remove_observers(user1, user2, HostbotCommand.remove_observer)
            logging.info('Friendship %s, %s deleted for %s and %s' % (proxybot_jid, proxybot_uuid, user1, user2))
            return 'Friendship for %s and %s successfully deleted as %s.' % (user1, user2, proxybot_uuid)
        except MySQLdb.Error, e:
            logging.error('Failed to delete %s, %s for %s and %s with MySQL error %s' % (proxybot_jid, proxybot_uuid, user1, user2, e))
            raise ExecutionError
        except xmlrpclib.Fault as e:
            logging.error('Failed to delete %s, %s for %s and %s with XMLRPC error %s' % (proxybot_jid, proxybot_uuid, user1, user2, e))
            raise ExecutionError
    def _list_friendships(self):
        try:
            friendships = self._db_execute_and_fetchall("""SELECT GROUP_CONCAT(proxybot_participants.user SEPARATOR ' '), proxybots.id FROM
                proxybots, proxybot_participants WHERE proxybots.stage = 'idle' AND
                proxybots.id = proxybot_participants.proxybot_id GROUP BY proxybots.id""", strip_pairs=False)
        except Exception, e:
            raise ExecutionError, 'There was an error finding idle proxybots in the database: %s' % e
        if len(friendships) <= 0:
            return 'No idle proxybots found. Use /new_friendship to create an idle proxybot for two users.'    
        output = 'The current friendships (i.e. idle proxybots) are:'
        for friendship in friendships:
            try:
                user1, user2 = friendship[0].split(' ')
            except ValueError:
                raise ExecutionError, 'There were not two users found for %s, %s in this string: %s' % (proxbot_uuid, proxybot_jid, friendship[0])
            proxbot_uuid = friendship[1]
            proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(friendship[1])))
            output += '\n\t%s\n\t%s\n\t\t\t\t\t%s\n\t\t\t\t\t%s' % (user1, user2, proxbot_uuid, proxybot_jid)
        return output

    def _add_or_remove_observers(self, user1, user2, command):
        # find active proxybots with each user as a participant but *not* the other, and add/remove the other as an observer
        for participant, observer in [(user1, user2), (user2, user1)]:
            proxybot_ids = self._db_execute_and_fetchall("""SELECT proxybots.id FROM proxybots, proxybot_participants WHERE
                proxybots.id = proxybot_participants.proxybot_id AND
                proxybots.stage = 'active' AND
                proxybot_participants.user = %(participant)s AND
                proxybots.id NOT IN (SELECT proxybot_id FROM proxybot_participants WHERE user =  %(observer)s)""",
                {'participant': participant, 'observer': observer}, )
            for proxybot_id in proxybot_ids:
                session = {'participant': participant,
                           'observer': observer,
                           'next': self._cmd_send_addremove_observer,
                           'error': self._cmd_error}
                self['xep_0050'].start_command(jid=self._full_jid_for_proxybot(proxybot_id),
                                               node=command,  # they can use the same ad hoc send function!
                                               session=session,
                                               ifrom=constants.hostbot_component_jid)

    def _full_jid_for_proxybot(self, proxybot_uuid):
        try:
            proxybot_id = shortuuid.encode(uuid.UUID(proxybot_uuid))
        except AttributeError:
            proxybot_id = shortuuid.encode(proxybot_uuid)
        return '%s%s@%s/%s' % (constants.proxybot_prefix,
                               proxybot_id,
                               constants.server,
                               constants.proxybot_resource)

    def _find_idle_proxybot(self, user1, user2):
        proxybot_ids = self._db_execute_and_fetchall("""SELECT proxybots.id FROM proxybots, 
            proxybot_participants AS proxybot_participants_1, proxybot_participants AS proxybot_participants_2 WHERE 
            proxybots.stage = 'idle' AND
            proxybots.id = proxybot_participants_1.proxybot_id AND
            proxybots.id = proxybot_participants_2.proxybot_id AND
            proxybot_participants_1.user = %(user1)s AND
            proxybot_participants_2.user = %(user2)s""", {'user1': user1, 'user2': user2})
        if len(proxybot_ids) == 0:
            return (None, None)
        elif len(proxybot_ids) == 1:
            proxybot_jid = '%s%s' % (constants.proxybot_prefix, shortuuid.encode(uuid.UUID(proxybot_ids[0])))
            proxybot_uuid = uuid.UUID(proxybot_ids[0])
            return (proxybot_jid, proxybot_uuid)
        else:
            logging.error('There are %d idle proxybots for %s and %s! There should only be 1: %s' % (len(proxybot_ids), user1, user2, proxybot_ids))
            return (None, None)

    def _user_exists(self, user):
        num_users = self._db_execute_and_fetchall("SELECT COUNT(*) FROM users WHERE user = %(user)s", {'user': user})
        if num_users and int(num_users[0]) == 0:
            return False
        else:
            return True

    def _proxybot_restore(self, proxybot_jid, proxybot_uuid):
        num_proxybots = self._db_execute_and_fetchall("""SELECT COUNT(*) FROM proxybots WHERE 
            id = %(proxybot_uuid)s AND stage != 'retired'""", {'proxybot_uuid': proxybot_uuid})
        if not num_proxybots:
            raise ExecutionError, 'No proxybot found in the database for %s, %s.' % (proxybot_jid, proxybot_uuid)
        if int(num_proxybots[0]) != 1:
            raise ExecutionError, '%d proxybots found in the database for %s, %s.' % (int(num_proxybots[0][0]), proxybot_jid, proxybot_uuid)
        if self._proxybot_is_online(proxybot_jid):
            raise ExecutionError, 'Proxybot already online for %s, %s.' % (int(num_proxybots[0][0]), proxybot_jid, proxybot_uuid)
        self._launch_proxybot(['--username', proxybot_jid, '--bounced'])
        logging.info("Restored client process for %s, %s" % (proxybot_jid, proxybot_uuid))
        return 'Proxybot %s has been restarted - look for it online!' % proxybot_jid
    def _proxybot_bounce(self, proxybot_jid, proxybot_uuid):
        if not self._proxybot_is_online(proxybot_jid):
            raise ExecutionError, '%s, %s wasn\'t online, so can\'t be bounced. /restore it instead?' % (proxybot_jid, proxybot_uuid)
        session = {'next': self._cmd_send_bounce_proxybot,
                   'error': self._cmd_error}
        self['xep_0050'].start_command(jid=self._full_jid_for_proxybot(proxybot_uuid),  # this is the only time the proxybot_uuid is already a uuid not a string
                                       node=HostbotCommand.bounce_proxybot,
                                       session=session,
                                       ifrom=constants.hostbot_component_jid)
        logging.info("Bouncing client process for %s, %s" % (proxybot_jid, proxybot_uuid))
        return '%s, %s has been bounced - look for it online!' % (proxybot_jid, proxybot_uuid)
    def _proxybot_status(self, proxybot_jid, proxybot_uuid):
        try:
            stage = self._db_execute_and_fetchall("SELECT stage FROM proxybots WHERE id = %(proxybot_id)s", {'proxybot_id': proxybot_uuid})[0]
        except IndexError, e:
            raise ExecutionError, 'There was an error finding the proxybot: %s' % e
        try:
            participants = self._db_execute_and_fetchall("SELECT user FROM proxybot_participants WHERE proxybot_id = %(proxybot_id)s", {'proxybot_id': proxybot_uuid})
        except Exception, e:
            raise ExecutionError, 'There was an error finding the participants for this proxybot: %s' % e
        try:
            #LATER this code is copied from proxybot_user.py, but I'm not sure where best to put it
            observers = set([])
            for participant in participants:
                observers = observers.union(self._db_execute_and_fetchall("""SELECT proxybot_participants_2.user FROM proxybots, 
                    proxybot_participants AS proxybot_participants_1, proxybot_participants AS proxybot_participants_2 WHERE 
                    proxybots.stage = 'idle' AND
                    proxybots.id = proxybot_participants_1.proxybot_id AND
                    proxybots.id = proxybot_participants_2.proxybot_id AND
                    proxybot_participants_1.user = %(user)s""", {'user': participant}))
        except Exception, e:
            raise ExecutionError, 'There was an error finding the observers for this proxybot: %s' % e
        #LATER add commands to get data from the live process for this proxybot, probably using ad hoc commands.
        output = '%(proxybot_jid)s\n%(proxybot_uuid)s' + \
                '\n\t%(online)s' + \
                '\n\t%(stage)s' + \
                '\n\tParticipants:%(participants)s' + \
                '\n\tObservers:%(observers)s'
        return output % {
                'proxybot_jid': proxybot_jid,
                'proxybot_uuid': proxybot_uuid,
                'online': 'online' if self._proxybot_is_online(proxybot_jid) else 'offline',
                'stage': stage,
                'participants': ''.join(['\n\t\t%s' % user for user in participants]),
                'observers': ''.join(['\n\t\t%s' % user for user in observers.difference(participants)])
             }
    def _proxybot_cleanup(self, proxybot_jid, proxybot_uuid):
        if self._proxybot_is_online(proxybot_jid):
            return '%s@%s is online - try sending it a /command to reset its state' % (proxybot_jid, constants.server)
        self._db_execute("UPDATE proxybots SET stage = 'retired' WHERE id = %(id)s", {'id': proxybot_uuid})
        try:
            participants = self._db_execute_and_fetchall("SELECT user FROM proxybot_participants WHERE proxybot_id = %(proxybot_id)s", {'proxybot_id': proxybot_uuid})
        except Exception, e:
            raise ExecutionError, 'There was an error finding the participants for this proxybot: %s' % e
        try:
            #LATER this code is copied from proxybot_user.py, but I'm not sure where best to put it
            observers = set([])
            for participant in participants:
                observers = observers.union(self._db_execute_and_fetchall("""SELECT proxybot_participants_2.user FROM proxybots, 
                    proxybot_participants AS proxybot_participants_1, proxybot_participants AS proxybot_participants_2 WHERE 
                    proxybots.stage = 'idle' AND
                    proxybots.id = proxybot_participants_1.proxybot_id AND
                    proxybots.id = proxybot_participants_2.proxybot_id AND
                    proxybot_participants_1.user = %(user)s""", {'user': participant}))
        except Exception, e:
            raise ExecutionError, 'There was an error finding the observers for this proxybot: %s' % e
        users = [User(username, proxybot_jid) for username in observers.union(participants)]
        for user in users:
            user.delete_from_rosters()
        logging.info("Database and roster cleanup was done for %s, %s with users %s" % (proxybot_jid, proxybot_uuid, ', '.join([str(user) for user in users])))
        return 'This proxybot has been retired in the database and is no longer in the following rosters: %s' % ', '.join([str(user) for user in users])
    def _proxybot_purge(self, proxybot_jid, proxybot_uuid):
        if proxybot_jid == 'all':
            self._db_execute("DELETE proxybot_participants FROM proxybots, proxybot_participants WHERE proxybots.stage = 'retired' AND proxybots.id = proxybot_participants.proxybot_id")
            self._db_execute("DELETE FROM proxybots WHERE stage = 'retired'")
            logging.info("All proxybots deleted from database")
            return 'All retired proxybots have been deleted from the database.'
        try:
            stage = self._db_execute_and_fetchall("SELECT stage FROM proxybots WHERE id = %(proxybot_id)s", {'proxybot_id': proxybot_uuid})[0]
        except IndexError, e:
            raise ExecutionError, 'There was an error finding the proxybot: %s' % e
        if self._proxybot_is_online(proxybot_jid) and stage != 'retired':
            raise ExecutionError, '%s@%s is online and %s, and this command is only for retired proxybots.' % (proxybot_jid, constants.server, stage)
        self._db_execute("DELETE FROM proxybot_participants WHERE proxybot_id = %(proxybot_id)s", {'proxybot_id': proxybot_uuid})
        self._db_execute("DELETE FROM proxybots WHERE stage = 'retired' AND id = %(proxybot_id)s", {'proxybot_id': proxybot_uuid})
        logging.info("%s, %s deleted from database" % (proxybot_jid, proxybot_uuid))
        return '%s, %s has been deleted from the database.' % (proxybot_jid, proxybot_uuid)

    # Adhoc commands for which the hostbot is the user and the proxybot is the provider
    @proxybot_only
    def _cmd_send_participant_deleted(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='user', value=session['user'])
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)
        logging.info("Ad hoc command sent to proxybot: participant_deleted")
    @proxybot_only
    def _cmd_send_addremove_observer(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        form.addField(var='participant', value=session['participant'])
        form.addField(var='observer', value=session['observer'])
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)
        logging.info("Ad hoc command sent to proxybot: addremove_observer")
    @proxybot_only
    def _cmd_send_delete_proxybot(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        # no fields!
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)
        logging.info("Ad hoc command sent to proxybot: delete_proxybot")
    @proxybot_only
    def _cmd_send_bounce_proxybot(self, iq, session):
        form = self['xep_0004'].makeForm(ftype='submit')
        # no fields!
        session['payload'] = form
        session['next'] = None
        self['xep_0050'].complete_command(session)
        logging.info("Ad hoc command sent to proxybot: bounce_proxybot")

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
        logging.info("Ad hoc command from %s recieved: activate" % iq['from'].user)
        return session
    @proxybot_only
    def _cmd_receive_retire(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Retire proxybot')
        form.addField(ftype='text-single', var='proxybot')
        form.addField(ftype='text-single', var='user')
        session['payload'] = form
        session['next'] = self._cmd_complete_retire
        session['has_next'] = False
        logging.info("Ad hoc command from %s recieved: retire" % iq['from'].user)
        return session
    @proxybot_only
    def _cmd_receive_add_participant(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Add a participant')
        form.addField(ftype='text-single', var='proxybot')
        form.addField(ftype='text-single', var='user')
        session['payload'] = form
        session['next'] = self._cmd_complete_add_participant
        session['has_next'] = False
        logging.info("Ad hoc command from %s recieved: add_participant" % iq['from'].user)
        return session
    @proxybot_only
    def _cmd_receive_remove_participant(self, iq, session):
        form = self['xep_0004'].makeForm('form', 'Remove a participant')
        form.addField(ftype='text-single', var='proxybot')
        form.addField(ftype='text-single', var='user')
        session['payload'] = form
        session['next'] = self._cmd_complete_remove_participant
        session['has_next'] = False
        logging.info("Ad hoc command from %s recieved: remove_participant" % iq['from'].user)
        return session
    def _cmd_complete_activate(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user1 = form['values']['user1']
        user2 = form['values']['user2']
        self._db_execute("UPDATE proxybots SET stage = 'active' WHERE id = %(id)s", {'id': shortuuid.decode(proxybot_id)})
        self._create_friendship(user1, user2)  #NOTE activate before creating the new proxybot, so the idle-does-not-exist check passes
        session['payload'] = None
        session['next'] = None
        logging.info(payload)
        logging.info(session)
        logging.info("Ad hoc command from %s completed and recorded in the database: activate" % session['from'].user)
        return session
    def _cmd_complete_retire(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self._db_execute("UPDATE proxybots SET stage = 'retired' WHERE id = %(id)s", {'id': shortuuid.decode(proxybot_id)})
        self._db_execute("DELETE FROM proxybot_participants WHERE user = %(user)s and proxybot_id = %(proxybot_id)s",
            {'user': user, 'proxybot_id': shortuuid.decode(proxybot_id)})
        session['payload'] = None
        session['next'] = None
        logging.info("Ad hoc command from %s completed and recorded in the database: retire" % session['from'].user)
        return session
    def _cmd_complete_add_participant(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self._db_execute("INSERT INTO proxybot_participants (proxybot_id, user) VALUES (%(proxybot_id)s, %(user)s)",
            {'proxybot_id': shortuuid.decode(proxybot_id), 'user': user})
        session['payload'] = None
        session['next'] = None
        logging.info("Ad hoc command from %s completed and recorded in the database: add_participant" % session['from'].user)
        return session
    def _cmd_complete_remove_participant(self, payload, session):
        form = payload
        proxybot_id = form['values']['proxybot'].split('proxybot_')[1]
        user = form['values']['user']
        self._db_execute("DELETE FROM proxybot_participants WHERE user = %(user)s and proxybot_id = %(proxybot_id)s",
            {'user': user, 'proxybot_id': shortuuid.decode(proxybot_id)})
        session['payload'] = None
        session['next'] = None
        logging.info("Ad hoc command from %s completed and recorded in the database: remove_participant" % session['from'].user)
        return session

    # Adhoc commands - general functions
    def _cmd_error(self, iq, session):
        logging.error('%s ad hoc command: %s %s' % (iq['command']['node'], iq['error']['condition'], iq['error']['text']))
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
            'user': constants.hostbot_xmlrpc_jid,  #NOTE the server is not bot.vine.im because of xml_rpc authentication
            'server': constants.server,
            'password': constants.hostbot_xmlrpc_password
        }, data)

    def _db_execute_and_fetchall(self, query, data={}, strip_pairs=True):
        self._db_execute(query, data)
        fetched = self.cursor.fetchall()
        if fetched and len(fetched) > 0:
            if strip_pairs:
                return [result[0] for result in fetched]
            else:
                return fetched
        return []
    def _db_execute(self, query, data={}):
        if not self.db or not self.cursor:
            logging.info("Database connection missing, attempting to reconnect")
            if self.db:
                self.db.close()
            self._db_connect()
        try:
            self.cursor.execute(query, data)
        except MySQLdb.OperationalError, e:
            logging.info('Database OperationalError %s for query, will retry: %s', (e, query % data))
            self._db_connect()  # Try again, but only once
            self.cursor.execute(query, data)
    def _db_connect(self):
        try:
            self.db = MySQLdb.connect('localhost', constants.hostbot_mysql_user, constants.hostbot_mysql_password, constants.db_name)
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
    optp.add_option('-r', '--restore', help='restore inactive proxybots from the db',
                    action='store_const', dest='restore',
                    const=True, default=False)
    optp.add_option('-b', '--bounce', help='bounce all of the online proxybots',
                    action='store_const', dest='bounce',
                    const=True, default=False)
    opts, args = optp.parse_args()

    logging.basicConfig(level=opts.loglevel,
                        format='%(asctime)-15s Hostbot %(levelname)-8s %(message)s')

    xmpp = HostbotComponent(opts.restore, opts.bounce)

    if xmpp.connect(constants.server_ip, constants.component_port):
        xmpp.process(block=True)
        xmpp.cleanup()
        logging.info("Done")
    else:    
        logging.error("Unable to connect")
