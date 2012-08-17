#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
import uuid
import shortuuid
import xmlrpclib
import os
parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.sys.path.insert(0,parentdir) 
import constants

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


leaf_id = 1
xmlrpc_server = xmlrpclib.ServerProxy('http://%s:%s' % (constants.server, constants.xmlrpc_port))

def xmlrpc_command(command, data):
    fn = getattr(xmlrpc_server, command)
    return fn({
        'user': '%s%s' % (constants.leaf_xmlrpc_jid_prefix, leaf_id),
        'server': constants.server,
        'password': constants.leaf_xmlrpc_password
    }, data)

def add_proxy_rosteritem(user, vinebot_jid, nick):
    xmlrpc_command('add_rosteritem', {
        'localuser': user,
        'localserver': constants.server,
        'user': vinebot_jid,
        'server': '%s%s.%s' % (constants.leaf_name, leaf_id, constants.server),
        'group': constants.roster_group,
        'nick': nick,
        'subs': 'both'
    })

def delete_proxy_rosteritem(user, vinebot_jid):
    xmlrpc_command('delete_rosteritem', {
        'localuser': user,
        'localserver': constants.server,
        'user': vinebot_jid,
        'server': '%s%s.%s' % (constants.leaf_name, leaf_id, constants.server)
    })

def get_roster(user):
    return xmlrpc_command('get_roster', {
        'user': user, 
        'host': constants.server
    })['contacts']

if __name__ == '__main__':
    db = MySQLdb.connect('localhost', '%s%s' % (constants.leaf_name, leaf_id), constants.leaf_mysql_password, constants.db_name)
    cursor = db.cursor()
    cursor.execute("DELETE FROM party_vinebots")
    cursor.execute("UPDATE pair_vinebots SET is_active = 0")
    
    cursor.execute("SELECT name FROM users")
    users = [result[0] for result in cursor.fetchall()]
    for user in users:
        for rosteritem in get_roster(user):
            delete_proxy_rosteritem(user, rosteritem['contact'][0]['jid'].split('@')[0])
    cursor.execute("""SELECT pair_vinebots.id, users_1.name, users_2.name
                      FROM users AS users_1, users AS users_2, pair_vinebots
                      WHERE pair_vinebots.user1 = users_1.id AND pair_vinebots.user2 = users_2.id""")
    
    pair_vinebots = [('%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid.UUID(bytes=result[0]))), result[1], result[2]) for result in cursor.fetchall()]
    for pair_vinebot in pair_vinebots:
        vinebot_jid, user1, user2 = pair_vinebot
        add_proxy_rosteritem(user1, vinebot_jid, user2)
        add_proxy_rosteritem(user2, vinebot_jid, user1)
    
    db.close()

