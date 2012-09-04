#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input
    
class NotUserException(Exception):
    pass

class User(object):
    def __init__(self, db, ectl, name=None, dbid=None):
        self._db = db
        self._ectl = ectl
        self._noted_vinebot_ids = None
        if name and dbid:
            self.name = name
            self.id = dbid
        elif name:
            self.name = name
            self.id   = self.execute_and_fetchall("""SELECT id
                                                     FROM users
                                                     WHERE name = %(name)s
                                                     LIMIT 1
                                                  """, {
                                                     'name' = name
                                                  } strip_pairs=True)
        elif dbid:
            self.id   = dbid
            self.name = self.execute_and_fetchall("""SELECT name
                                                     FROM users
                                                     WHERE id = %(id)s
                                                     LIMIT 1
                                                  """, {
                                                     'id' = dbid
                                                  } strip_pairs=True)
        else:
            raise Exception, 'User objects must be initialized with either a name or id.'
        if not self.id or not self.name:
            raise NotUserException, 'both of these users were not found in the database.'
    
    def fetch_visible_active_vinebots(self):
        return self.execute_and_fetchall("""SELECT participants.vinebot_id
                                            FROM edges AS outgoing, edges AS incoming, participants
                                            WHERE outgoing.vinebot_id = incoming.vinebot_id
                                            AND outgoing.from_id = %(id)s
                                            AND incoming.to_id = %(id)s
                                            AND outgoing.to_id = incoming.from_id
                                            AND participants.user_id = outgoing.to_id
                                         """, {
                                            'id' = self.id
                                         }, strip_pairs=True)
    
    def note_visible_active_vinebots(self):
        self._noted_vinebot_ids = set(self.fetch_visible_active_vinebots())
    
    def update_visible_active_vinebots(self):
        if _noted_vinebot_ids == None:
            raise Exception, 'User\'s noted visible active vinebots must be fetched before they are updated!'
        current_vinebot_ids = set(self.fetch_visible_active_vinebots())
        for vinebot_id in self._noted_vinebot_ids.difference(current_vinebot_ids):
            vinbot = DatabaseVinebot(self._db, self._ectl, dbid=reverse_edge.vinebot_id, 
            self._ectl.delete_rosteritem(self.name, vinbot.jiduser)
        for vinebot_id in current_vinebot_ids.difference(self._noted_vinebot_ids):
            vinbot = DatabaseVinebot(self._db, self.ectl, dbid=reverse_edge.vinebot_id, 
            self._ectl.add_rosteritem(self.name, vinbot.jiduser, vinbot.jiduser)  #TODO calculate nick
        self._noted_vinebot_ids = None
    
    def get_active_vinebots(self):
        vinebot_ids = self.execute_and_fetchall("""SELECT vinebot_id
                                                   FROM participants
                                                   WHERE user_id = %(id)s
                                                   LIMIT 1
                                                """, {
                                                   'id' = self.id
                                                }, strip_pairs=True)
        return [DatabaseVinebot(self._db, self._ectl, dbid=vinebot_id) for vinebot_id in vinebot_ids]
    
