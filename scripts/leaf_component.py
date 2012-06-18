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
        self.add_event_handler("session_start", self.handle_start)
        self.del_event_handler('presence_probe', self._handle_probe)
        self.add_event_handler('presence_probe', self.handle_probe)
        self.add_event_handler('presence_available', self.handle_presence_available)
        self.add_event_handler('presence_unavailable', self.handle_presence_unavailable)
        self.add_event_handler('message', self.handle_message)
        for state in ['active', 'inactive', 'gone', 'composing', 'paused']:
            self.add_event_handler('chatstate_%s' % state, self.handle_chatstate)
    
    ##### event handlers
    def handle_start(self, event):
        self.sendPresence()
        logging.info("Session started")
    
    def handle_probe(self, presence):
        logging.warning(presence['from'])
        self.tempSendPrecence(pfrom=presence['to'], pto=presence['from'])
        logging.info("Presence probe received from %s by %s" % (presence['from'].user, presence['to'].user))
    
    def handle_presence_available(self, presence):
        if presence['to'].user.startswith(constants.vinebot_prefix):
            participants, observers, is_active, is_party = self.db_fetch_vinebot(presence['to'].user)
            
            self.tempSendPrecence(pfrom=presence['to'], pto=presence['from'])
            logging.info("Presence available received from %s by %s" % (presence['from'].user, presence['to'].user))
    
    def handle_presence_unavailable(self, presence):
        if presence['to'].user.startswith(constants.vinebot_prefix):
            participants, observers, is_active, is_party = self.db_fetch_vinebot(presence['to'].user)
            online_participants = set(filter(self.user_online, participants))
            if presence['from'].user in participants:
                if is_party:
                    if len(participants) > 2:
                        for observer in observers:
                            self.add_proxy_rosteritem(observer, presence['to'].user, self.get_nick(online_participants))
                        self.db_remove_participant(presence['from'].user, presence['to'].user)
                    else:    
                        for observer in observers:
                            self.delete_proxy_rosteritem(observer, presence['to'].user)
                        self.db_delete_party(presence['to'].user)
                else:
                    if is_active:
                        self.db_activate_vinebot(presence['to'].user, False)
                        for observer in observers:
                            self.delete_proxy_rosteritem(observer, presence['to'].user)
                    #TODO make invisible                         
        logging.info("Presence unavailable received from %s by %s" % (presence['from'].user, presence['to'].user))
    
    def handle_message(self, msg):
        if msg['type'] in ('chat', 'normal'):
            if not msg['to'].user.startswith(constants.vinebot_prefix):
               msg.reply('Sorry, but I can only handle messages send to vinebots.').send()
            else:
                participants, observers, is_active, is_party = self.db_fetch_vinebot(msg['to'].user)
                if msg['from'].user in participants:
                    online_participants = set(filter(self.user_online, participants))
                    offline_participants = participants.difference(online_participants)
                    if len(online_participants) >= 2:
                        if msg['body'].startswith('/'):
                            msg.reply('TODO handle slash commands').send()
                        else:
                            if not is_active:
                                self.db_activate_vinebot(msg['to'].user, True)
                                for observer in observers:
                                    logging.info((observer, self.get_nick(online_participants)))
                                    self.add_proxy_rosteritem(observer, msg['to'].user, self.get_nick(online_participants))
                            self.broadcast_msg(msg, participants, sender=msg['from'].user)
                    else:
                        if is_party:
                            logging.info('TODO cleanup this party vinebot')
                            msg.reply('TODO cleanup this party vinebot').send()
                        else:
                            logging.info('TODO set to invisible and send error message')
                            msg.reply('TODO set to invisible and send error message').send()
                else:
                    if msg['from'].user in observers:
                        if is_active:
                            msg.reply('TODO observer joins conversation, update aliases, transition to is_party').send()
                        else:
                            msg.reply('Sorry, but you can\'t join a conversation that hasn\'t started yet.').send()
                    else:
                        msg.reply('Sorry, but vinebots only handle messages from participants.').send()
    
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
                new_msg['to'] = "%s@%s" % (participant, constants.server)
                new_msg.send()
    
    def get_nick(self, participants, viewing_participant=None):  # observers all see the same nickname, so this is None for them
        if viewing_participant: 
            participants = participants.difference([viewing_participant])
            participants.insert(0, 'you')
        participants = list(participants)
        comma_sep = ''.join([', %s' % participant for participant in participants[1:-1]])
        return '%s%s & %s' % (participants[0], comma_sep, participants[-1])
    
    def tempSendPrecence(self, pto, pfrom):
        pres = self.Presence()
        pres['to'] = pto
        pres['from'] = pfrom
        pres.send()
    
    
    ##### ejabberdctl XML RPC commands
    # def add_proxy_rosteritems(self, user1, user2, vinebot_jid):
    #     self.add_proxy_rosteritem(user1, vinebot_jid, user2)
    #     self.add_proxy_rosteritem(user2, vinebot_jid, user1)
    
    def add_proxy_rosteritem(self, user, vinebot_jid, nick):
        self.xmlrpc_command('add_rosteritem', {
            'localuser': user,
            'localserver': constants.server,
            'user': vinebot_jid,
            'server': '%s%s.%s' % (constants.leaf_name, self.id, constants.server),
            'group': constants.proxybot_group,
            'nick': nick,
            'subs': 'both'
        })

    def delete_proxy_rosteritem(self, user, vinebot_jid):
        self.xmlrpc_command('delete_rosteritem', {
            'localuser': user,
            'localserver': constants.server,
            'user': vinebot_jid,
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
            logging.error('ProtocolError in is_online, assuming %s is offline: %s' % (self._user, str(e)))
            return False
    
    def xmlrpc_command(self, command, data):
        fn = getattr(self.xmlrpc_server, command)
        return fn({
            'user': '%s%s' % (constants.leaf_xmlrpc_jid_prefix, self.id),
            'server': constants.server,
            'password': constants.leaf_xmlrpc_password
        }, data)
    
    
    ##### database queries and connection management
    def db_remove_participant(self, user, vinebot_jid):
        logging.error("TODO implement party vinebot stuff")
    
    def db_delete_party(self, vinebot_jid):
        logging.error("TODO implement party vinebot stuff")
    
    def db_activate_vinebot(self, vinebot_jid, activate):
        _shortuuid = vinebot_jid.replace(constants.vinebot_prefix, '')
        _uuid = shortuuid.decode(_shortuuid)
        pair_vinebot = self.db_execute("""UPDATE pair_vinebots SET is_active = %(activate)s
                                          WHERE id = %(id)s""", {'id': _uuid.bytes, 'activate': activate},)
    
    def db_fetch_vinebot(self, vinebot_jid):
        _shortuuid = vinebot_jid.replace(constants.vinebot_prefix, '')
        _uuid = shortuuid.decode(_shortuuid)
        pair_vinebot = self.db_execute_and_fetchall("""SELECT users_1.user, users_2.user, users_1.id, users_2.id, pair_vinebots.is_active
                          FROM users AS users_1, users AS users_2, pair_vinebots
                          WHERE pair_vinebots.id = %(id)s AND pair_vinebots.user1 = users_1.id AND pair_vinebots.user2 = users_2.id
                          LIMIT 1""", {'id': _uuid.bytes}, strip_pairs=False)
        if len(pair_vinebot) > 0:
            participants = set([pair_vinebot[0][0], pair_vinebot[0][1]])
            participant_ids = set([pair_vinebot[0][2], pair_vinebot[0][3]])
            is_active = (pair_vinebot[0][4] == 1)
            is_party = False
        else:
            party_vinebot = []
            #TODO query for party vinebots
            if len(party_vinebot) > 0:
                participants = set([])
                participant_ids = set([])
                is_active = True
                is_party = True
            else:
                participants = set([])
                participant_ids = set([])
                is_active = False
                is_party = False
        observers = set([])
        if len(participant_ids) >= 2:
            for participant_id in participant_ids:
                observers = observers.union(self.db_fetch_friends(participant_id))
            observers = observers.difference(participants)
        return (participants, observers, is_active, is_party)
    
    def db_fetch_friends(self, user_id):
        return self.db_execute_and_fetchall("""SELECT users.user FROM users, pair_vinebots
            WHERE (pair_vinebots.user1 = %(user_id)s AND pair_vinebots.user2 = users.id)
            OR    (pair_vinebots.user2 = %(user_id)s AND pair_vinebots.user1 = users.id)""", {'user_id': user_id})

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
