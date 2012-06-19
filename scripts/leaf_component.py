#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
import logging
from optparse import OptionParser
import uuid
import shortuuid
import xmlrpclib
import sleekxmpp
from sleekxmpp.componentxmpp import ComponentXMPP
from sleekxmpp.exceptions import IqError, IqTimeout
import constants
from slash_commands import SlashCommand, SlashCommandRegistry, ExecutionError

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class LeafComponent(ComponentXMPP):
    def __init__(self, leaf_id):
        self.id = leaf_id
        ComponentXMPP.__init__(self, '%s%s.%s' % (constants.leaf_name, self.id, constants.server), 
                                     constants.leaf_secret,
                                     constants.server,
                                     constants.component_port)
        # self.registerPlugin('xep_0030') # Service Discovery
        # self.registerPlugin('xep_0004') # Data Forms
        # self.registerPlugin('xep_0060') # PubSub
        # self.registerPlugin('xep_0199') # XMPP Ping
        self.xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))
        self.db = None
        self.cursor = None
        self.db_connect()
        self.commands = SlashCommandRegistry()
        def is_admin(sender, recipient):
            return sender.bare in constants.admin_users
        def is_participant(sender, recipient):
            participants, is_active, is_party = self.db_fetch_vinebot(recipient.user)
            return is_active and sender.user in participants
        # def is_admin_or_participant(sender):
        #     return is_admin(sender) or is_participant(sender)
        # def has_none(sender, arg_string, arg_tokens):
        #     if len(arg_tokens) == 0:
        #         return []
        #     return False
        def sender_and_recipient(sender, recipient, arg_string, arg_tokens):
            if len(arg_tokens) == 0:
                return [sender.user, recipient.user]
            return False
        # def sender_and_one_token(sender, arg_string, arg_tokens):            
        #     if len(arg_tokens) == 1:
        #         return [sender.user, arg_tokens[0]]
        #     return False
        # def only_string(sender, arg_string, arg_tokens):
        #     if len(arg_string.strip()) > 0:
        #         return [sender.user, arg_string]
        #     return False
        # def one_token_and_string(sender, arg_string, arg_tokens):
        #     if len(arg_tokens) >= 2:
        #         return [sender.user, arg_tokens[0], arg_string.partition(arg_tokens[0])[2].strip()]
        #     return False
        self.commands.add(SlashCommand(command_name     = 'leave',
                                       text_arg_format  = '',
                                       text_description = 'Leave this conversation.',
                                       validate_sender  = is_participant,
                                       transform_args   = sender_and_recipient,
                                       action           = self.user_left))                  
        self.add_event_handler("session_start", self.handle_start)
        self.del_event_handler('presence_probe', self._handle_probe)
        self.add_event_handler('presence_probe', self.handle_probe)
        self.add_event_handler('presence_available', self.handle_presence_available)
        self.add_event_handler('presence_unavailable', self.handle_presence_unavailable)
        self.add_event_handler('message', self.handle_message)
        for state in ['active', 'inactive', 'gone', 'composing', 'paused']:
            self.add_event_handler('chatstate_%s' % state, self.handle_chatstate)
    
    def disconnect(self, *args, **kwargs):
        #LATER check if other leaves are online, since otherwise we don't need to do this.
        for user_vinebot_pair in self.db_fetch_all_uservinebots():
            self.sendPresence(pfrom='%s@%s%s.%s' % (user_vinebot_pair[1], constants.leaf_name, self.id, constants.server),
                              pto='%s@%s' % (user_vinebot_pair[0], constants.server),
                              pshow='unavailable')
        kwargs['wait'] = True
        super(LeafComponent, self).disconnect(*args, **kwargs)
    
    
    ##### event handlers
    def handle_start(self, event):
        #LATER check if other leaves are online, since otherwise we don't need to do this.
        all_uservinebots = self.db_fetch_all_uservinebots()
        for user_vinebot_pair in all_uservinebots:
            self.sendPresence(pfrom='%s@%s%s.%s' % (user_vinebot_pair[1], constants.leaf_name, self.id, constants.server),
                              pto='%s@%s' % (user_vinebot_pair[0], constants.server))
        logging.info("Session started with %d user-vinebots" % len(all_uservinebots))
    
    def handle_probe(self, presence):
        self.sendPresence(pfrom=presence['to'], pto=presence['from'])
    
    def handle_presence_available(self, presence):
        if presence['to'].user.startswith(constants.vinebot_prefix):
            participants, is_active, is_party = self.db_fetch_vinebot(presence['to'].user)
            self.sendPresence(pfrom=presence['to'], pto=presence['from'])
            if presence['from'].user in participants:
                participants.remove(presence['from'].user)
                for participant in participants:
                    self.sendPresence(pfrom=presence['to'], 
                                      pto='%s@%s' % (participant, constants.server))
    
    def handle_presence_unavailable(self, presence):
        if presence['to'].user.startswith(constants.vinebot_prefix):
            self.user_disconnected(presence['from'].user, presence['to'].user)
    
    def handle_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if msg['from'].bare in constants.admin_users:
                if self.commands.is_command(msg['body']):
                    msg.reply(self.commands.handle_command(msg['from'], msg['to'], msg['body'])).send()
                elif msg['body'].strip().startswith('/'):
                    msg.reply(self.commands.handle_command(msg['from'], msg['to'], '/help')).send()
                else:
                    msg.reply('Sorry, but admins can only send /commands to vinebots.').send()
            elif not msg['to'].user.startswith(constants.vinebot_prefix):
               msg.reply('Sorry, but I can only handle messages send to vinebots.').send()
            else:
                participants, is_active, is_party = self.db_fetch_vinebot(msg['to'].user)
                if msg['from'].user in participants:
                    participants = set(filter(self.user_online, participants))
                    #offline_participants = participants.difference(online_participants)
                    if len(participants) >= 2:
                        if self.commands.is_command(msg['body']):
                            logging.info(self.commands.handle_command(msg['from'], msg['to'], msg['body']))
                        elif msg['body'].strip().startswith('/'):
                            msg.reply(self.commands.handle_command(msg['from'], msg['to'], '/help')).send()
                        else:
                            if not is_active:
                                self.db_activate_vinebot(msg['to'].user, True)
                                for observer in self.db_fetch_observers(participants):
                                    self.add_proxy_rosteritem(observer, msg['to'].user, self.get_nick(participants))
                            self.broadcast_msg(msg, participants, sender=msg['from'].user)
                    else:
                        if is_party:
                            logging.error('TODO cleanup this party vinebot, and figure out how it got into this state')
                            msg.reply('TODO cleanup this party vinebot').send()
                        else:
                            self.sendPresence(pfrom=msg['to'], pto=msg['from'], pshow='unavailable')
                            msg.reply('Sorry, but %s is offline.' % participants.difference([msg['from'].user]).pop()).send()
                else:
                    if msg['from'].user in self.db_fetch_observers(participants):
                        if is_active:
                            participants.add(msg['from'].user)
                            if is_party:
                                self.db_add_participant(msg['from'].user, msg['to'].user)
                            else:
                                old_participants = participants.difference([msg['from'].user])
                                new_vinebot_user = self.db_new_party_vinebot(participants, msg['to'].user)
                                for old_participant in old_participants:
                                    self.add_proxy_rosteritem(old_participant, new_vinebot_user, old_participants.difference([old_participant]).pop())
                            self.addupdate_rosteritems(participants, msg['to'].user)
                            self.broadcast_alert('%s has joined the conversation' % msg['from'].user, participants, msg['to'].user)
                            self.broadcast_msg(msg, participants, sender=msg['from'].user)
                        else:
                            msg.reply('Sorry, but you can\'t join a conversation that hasn\'t started yet.').send()
                    else:
                        msg.reply('Sorry, but only friends of participants can join this conversation.').send()
    
    def handle_chatstate(self, msg):
        # if it's not "to" a proxybot, ignore
        # else, fetch the data for that proxybot
            # if it's "from" one of the two users
                # if both users are online
                    # if it's active, then pass on the chatstate
        logging.info("Chatstate received")
    
    # helper functions
    def broadcast_msg(self, msg, participants, sender=None):
        del msg['id']
        del msg['html'] #LATER fix html, but it's a pain with reformatting
        msg['from'] = msg['to']
        if msg['body'] and msg['body'] != '':
            if sender:
                msg['body'] = '[%s] %s' % (sender, msg['body'])
            else:
                msg['body'] = '/me *%s*' % (msg['body'])
        for participant in participants:
            if not sender or sender != participant:
                new_msg = msg.__copy__()
                new_msg['to'] = '%s@%s' % (participant, constants.server)
                new_msg.send()
    
    def broadcast_alert(self, body, participants, vinebot_user):
        msg = self.Message()
        msg['body'] = body
        msg['to'] = '%s@%s%s.%s' % (vinebot_user, constants.leaf_name, self.id, constants.server)  # this will get moved to 'from' in broadcast_msg
        logging.info((msg, participants))
        self.broadcast_msg(msg, participants)
    
    def get_nick(self, participants, viewing_participant=None):  # observers all see the same nickname, so this is None for them
        if viewing_participant: 
            participants = participants.difference([viewing_participant])
            participants = list(participants)
            participants.insert(0, 'you')
        else:
            participants = list(participants)
        comma_sep = ''.join([', %s' % participant for participant in participants[1:-1]])
        return '%s%s & %s' % (participants[0], comma_sep, participants[-1])
    
    def addupdate_rosteritems(self, participants, vinebot_user):
        for participant in participants:
            self.add_proxy_rosteritem(participant, vinebot_user, self.get_nick(participants, participant))
        for observer in self.db_fetch_observers(participants):
            self.add_proxy_rosteritem(observer, vinebot_user, self.get_nick(participants))
    
    
    def user_disconnected(self, user, vinebot_user):
        self.remove_participant(user, vinebot_user, "has disconnected and left the conversation")
    
    def user_left(self, user, vinebot_user):
        self.remove_participant(user, vinebot_user, "has left the conversation")
    
    def remove_participant(self, user, vinebot_user, alert_msg):
        participants, is_active, is_party = self.db_fetch_vinebot(vinebot_user)
        # participants = set(filter(self.user_online, participants))
        logging.info((user, vinebot_user, participants, is_active, is_party))
        if user in participants:
            if is_party:
                if len(participants) > 2:
                    participants.remove(user)
                    self.addupdate_rosteritems(participants, vinebot_user)
                    self.db_remove_participant(user, vinebot_user)
                else:
                    for observer in self.db_fetch_observers(participants):
                        self.delete_proxy_rosteritem(observer, vinebot_user)
                    self.db_delete_party(vinebot_user)
            else:
                if is_active:
                    self.db_activate_vinebot(vinebot_user, False)
                    for observer in self.db_fetch_observers(participants):
                        self.delete_proxy_rosteritem(observer, vinebot_user)
                self.sendPresence(pfrom='%s@%s' % (vinebot_user, constants.server),
                                  pto='%s@%s' % (participants.difference([user]).pop(), constants.server),
                                  pshow='unavailable')
            self.broadcast_alert('%s %s' % (user, alert_msg), participants, vinebot_user)
    
    ##### ejabberdctl XML RPC commands
    def add_proxy_rosteritem(self, user, vinebot_user, nick):
        self.xmlrpc_command('add_rosteritem', {
            'localuser': user,
            'localserver': constants.server,
            'user': vinebot_user,
            'server': '%s%s.%s' % (constants.leaf_name, self.id, constants.server),
            'group': constants.proxybot_group,
            'nick': nick,
            'subs': 'both'
        })
    
    def delete_proxy_rosteritem(self, user, vinebot_user):
        self.xmlrpc_command('delete_rosteritem', {
            'localuser': user,
            'localserver': constants.server,
            'user': vinebot_user,
            'server': '%s%s.%s' % (constants.leaf_name, self.id, constants.server)
        })
    
    def user_online(self, user):
        try:              
            res = self.xmlrpc_command('user_sessions_info', {
                'user': user,
                'host': constants.server
            })
            return len(res['sessions_info']) > 0
        except xmlrpclib.ProtocolError, e:
            logging.error('ProtocolError in is_online, assuming %s is offline: %s' % (user, str(e)))
            return False
    
    def xmlrpc_command(self, command, data):
        fn = getattr(self.xmlrpc_server, command)
        return fn({
            'user': '%s%s' % (constants.leaf_xmlrpc_jid_prefix, self.id),
            'server': constants.server,
            'password': constants.leaf_xmlrpc_password
        }, data)
    
    
    ##### database queries and connection management
    def db_add_participant(self, user, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("""INSERT INTO party_vinebots (id, user)
                           VALUES (%(id)s, (SELECT id FROM users 
                                            WHERE user = %(user)s 
                                            LIMIT 1))""", {'id': vinebot_uuid.bytes, 'user': user})
    
    def db_remove_participant(self, user, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("""DELETE FROM party_vinebots 
                           WHERE user = (SELECT id FROM users WHERE user = %(user)s)
                           AND id = %(id)s""", {'id': vinebot_uuid.bytes, 'user': user})
    
    def db_delete_party(self, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        self.db_execute("""DELETE FROM party_vinebots WHERE id = %(id)s""", {'id': vinebot_uuid.bytes})
    
    def db_new_party_vinebot(self, participants, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        new_vinebot_uuid = uuid.uuid4()
        self.db_execute("""UPDATE pair_vinebots SET id = %(new_id)s, is_active = 0
                           WHERE id = %(old_id)s""", {'new_id': new_vinebot_uuid.bytes, 'old_id': vinebot_uuid.bytes})
        for participant in participants:  #LATER use cursor.executemany()
            self.db_add_participant(participant, vinebot_user)
        return '%s%s' % (constants.vinebot_prefix, shortuuid.encode(new_vinebot_uuid))
    
    def db_fetch_all_uservinebots(self):  # useful for starting up/shutting down the leaf
        uservinebots = []
        pair_vinebots = self.db_execute_and_fetchall("""SELECT users.user, pair_vinebots.id, pair_vinebots.is_active
                          FROM users, pair_vinebots
                          WHERE pair_vinebots.user1 = users.id OR pair_vinebots.user2 = users.id""", {}, strip_pairs=False)
        for pair_vinebot in pair_vinebots:
            user, vinebot_user, is_active = (pair_vinebot[0],
                                            '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid.UUID(bytes=pair_vinebot[1]))),
                                            pair_vinebot[2])
            uservinebots.append((user, vinebot_user))
            if is_active:
                participants, is_active, is_party = self.db_fetch_vinebot(vinebot_user)
                observers = self.db_fetch_observers(participants)
                uservinebots.extend([(observer, vinebot_user) for observer in observers])
        return uservinebots
    
    def db_activate_vinebot(self, vinebot_user, activate):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        pair_vinebot = self.db_execute("""UPDATE pair_vinebots SET is_active = %(activate)s
                                          WHERE id = %(id)s""", {'id': vinebot_uuid.bytes, 'activate': activate},)
    
    def db_fetch_vinebot(self, vinebot_user):
        vinebot_id = vinebot_user.replace(constants.vinebot_prefix, '')
        vinebot_uuid = shortuuid.decode(vinebot_id)
        pair_vinebot = self.db_execute_and_fetchall("""SELECT users_1.user, users_2.user, pair_vinebots.is_active
                          FROM users AS users_1, users AS users_2, pair_vinebots
                          WHERE pair_vinebots.id = %(id)s AND pair_vinebots.user1 = users_1.id AND pair_vinebots.user2 = users_2.id
                          LIMIT 1""", {'id': vinebot_uuid.bytes}, strip_pairs=False)
        if len(pair_vinebot) > 0:
            participants = set([pair_vinebot[0][0], pair_vinebot[0][1]])
            is_active = (pair_vinebot[0][2] == 1)
            is_party = False
        else:
            party_vinebot = self.db_execute_and_fetchall("""SELECT users.user FROM users, party_vinebots
                              WHERE party_vinebots.id = %(id)s 
                              AND party_vinebots.user = users.id""", {'id': vinebot_uuid.bytes})
            if len(party_vinebot) > 0:
                participants = set(party_vinebot)
                is_active = True
                is_party = True
            else:
                participants = set([])
                is_active = False
                is_party = False
        return (participants, is_active, is_party)
    
    def db_fetch_observers(self, participants):
        observers = set([])
        for participant in participants:
            observers = observers.union(self.db_execute_and_fetchall("""SELECT users.user FROM users, pair_vinebots
                WHERE (pair_vinebots.user1 = (SELECT id FROM users  WHERE user = %(user)s LIMIT 1)
                   AND pair_vinebots.user2 = users.id)
                OR    (pair_vinebots.user2 = (SELECT id FROM users  WHERE user = %(user)s LIMIT 1)
                   AND pair_vinebots.user1 = users.id)""", {'user': participant}))
        return observers.difference(participants)
    
    def db_execute_and_fetchall(self, query, data={}, strip_pairs=True):
        self.db_execute(query, data)
        fetched = self.cursor.fetchall()
        if fetched and len(fetched) > 0:
            if strip_pairs:
                return [result[0] for result in fetched]
            else:
                return fetched
        return []
    
    def db_execute(self, query, data={}):
        if not self.db or not self.cursor:
            logging.info("Database connection missing, attempting to reconnect and retry query")
            if self.db:
                self.db.close()
            self.db_connect()
        try:
            self.cursor.execute(query, data)
        except MySQLdb.OperationalError, e:
            logging.info('Database OperationalError %s for query, will retry: %s' % (e, query % data))
            self.db_connect()  # Try again, but only once
            self.cursor.execute(query, data)
    
    def db_connect(self):
        try:
            self.db = MySQLdb.connect('localhost',
                                      '%s%s' % (constants.leaf_name, self.id),
                                      constants.leaf_mysql_password,
                                      constants.db_name)
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
    optp.add_option("-i", "--id", dest="leaf_id",
                    help="Leaf id (must correspond to ejabberd.cfg)")
    opts, args = optp.parse_args()
    
    logging.basicConfig(level=opts.loglevel,
                        format='%%(asctime)-15s leaf%(leaf_id)-3s %%(levelname)-8s %%(message)s' % {'leaf_id': opts.leaf_id})
    
    if opts.leaf_id is None:
        opts.leaf_id = raw_input("Leaf ID: ")
    xmpp = LeafComponent(opts.leaf_id)
    
    if xmpp.connect(constants.server_ip, constants.component_port):
        xmpp.process(block=True)
        xmpp.cleanup()
        logging.info("Done")
    else:    
        logging.error("Unable to connect")