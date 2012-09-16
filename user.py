#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import constants
from constants import g
import vinebot as v

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input
    
class NotUserException(Exception):
    pass

class UserPermissionsException(Exception):
    pass

class AbstractUser(object):
    def __init__(self, can_write=False, name=None, dbid=None):
        self._friends = None
        self._active_vinebots = None
        self._observed_vinebots = None
        self._symmetric_vinebots = None
        self._outgoing_vinebots = None
        self._incoming_vinebots = None
        self._noted_vinebot_ids = None
        self.can_write = can_write
        # if self.can_write:  the user doesn't actually require a lock, since deleting is really the only potential issue
    
    def status(self):
        return g.ectl.user_status(self.name)
    
    def is_online(self):
        return self.status() != 'unavailable'  # this function is useful for list filterss
    
    def roster(self):
        return g.ectl.get_roster(self.name)
    
    def _fetch_friends(self):
        friend_pairs = g.db.execute_and_fetchall("""SELECT users.name, users.id
                                                    FROM users, edges AS outgoing, edges AS incoming
                                                    WHERE outgoing.vinebot_id = incoming.vinebot_id
                                                    AND outgoing.from_id = %(id)s
                                                    AND incoming.to_id = %(id)s
                                                    AND outgoing.to_id = incoming.from_id
                                                    AND outgoing.to_id = users.id
                                                 """, {
                                                    'id': self.id
                                                 })
        return frozenset([FetchedUser(name=friend_pair[0], dbid=friend_pair[1]) for friend_pair in friend_pairs])
    
    def _fetch_current_active_vinebots(self):
        vinebot_ids = g.db.execute_and_fetchall("""SELECT vinebot_id
                                                   FROM participants
                                                   WHERE user_id = %(id)s
                                                """, {
                                                   'id': self.id
                                                }, strip_pairs=True)
        return frozenset([v.FetchedVinebot(can_write=self.can_write, dbid=vinebot_id) for vinebot_id in vinebot_ids])
    
    def _fetch_vinebots_symmetric_only(self):
        vinebots = g.db.execute_and_fetchall("""SELECT vinebots.id, vinebots.uuid
                                                FROM vinebots, edges AS incoming, edges AS outgoing
                                                WHERE incoming.vinebot_id = vinebots.id
                                                AND incoming.to_id = %(id)s
                                                AND outgoing.from_id = %(id)s
                                                AND incoming.from_id = outgoing.to_id
                                                GROUP BY vinebots.id
                                             """, {
                                                'id': self.id
                                             })
        return frozenset([v.FetchedVinebot(can_write=self.can_write, dbid=vinebot[0], _uuid=vinebot[1]) for vinebot in vinebots])

    
    def _fetch_vinebots_incoming_only(self):
        vinebots = g.db.execute_and_fetchall("""SELECT vinebots.id, vinebots.uuid
                                                FROM vinebots, edges AS incoming
                                                WHERE incoming.vinebot_id = vinebots.id
                                                AND incoming.to_id = %(id)s
                                                AND (SELECT COUNT(*)
                                                     FROM edges AS outgoing
                                                     WHERE outgoing.to_id = incoming.from_id
                                                     AND outgoing.from_id = %(id)s
                                                    ) = 0
                                                GROUP BY vinebots.id
                                             """, {
                                                'id': self.id
                                             })
        return frozenset([v.FetchedVinebot(can_write=self.can_write, dbid=vinebot[0], _uuid=vinebot[1]) for vinebot in vinebots])
    
    def _fetch_vinebots_outgoing_only(self):
        vinebots = g.db.execute_and_fetchall("""SELECT vinebots.id, vinebots.uuid
                                                FROM vinebots, edges AS outgoing
                                                WHERE outgoing.vinebot_id = vinebots.id
                                                AND outgoing.from_id = %(id)s
                                                AND (SELECT COUNT(*)
                                                     FROM edges AS incoming
                                                     WHERE incoming.to_id = %(id)s
                                                     AND incoming.from_id = outgoing.to_id
                                                    ) = 0
                                                GROUP BY vinebots.id
                                             """, {
                                                'id': self.id
                                             })
        return frozenset([v.FetchedVinebot(can_write=self.can_write, dbid=vinebot[0], _uuid=vinebot[1]) for vinebot in vinebots])
        
    
    def _fetch_visible_active_vinebot_ids(self):
        return g.db.execute_and_fetchall("""SELECT participants.vinebot_id
                                            FROM edges AS outgoing, edges AS incoming, participants
                                            WHERE outgoing.vinebot_id = incoming.vinebot_id
                                            AND outgoing.from_id = %(id)s
                                            AND incoming.to_id = %(id)s
                                            AND outgoing.to_id = incoming.from_id
                                            AND participants.user_id = outgoing.to_id
                                         """, {
                                            'id': self.id
                                         }, strip_pairs=True)
    
    def _fetch_visible_active_vinebots(self):
        return frozenset([v.FetchedVinebot(can_write=self.can_write, dbid=vinebot_id) for vinebot_id in self._fetch_visible_active_vinebot_ids()])
    
    def note_visible_active_vinebots(self):
        self._noted_vinebot_ids = set(self._fetch_visible_active_vinebot_ids())
    
    def calc_active_vinebot_diff(self):
        if self._noted_vinebot_ids == None:
            raise Exception, 'User\'s noted visible active vinebots must be fetched before they are updated!'
        current_vinebot_ids = set(self._fetch_visible_active_vinebot_ids())
        old_vinebot_ids = self._noted_vinebot_ids.difference(current_vinebot_ids)
        new_vinebot_ids = current_vinebot_ids.difference(self._noted_vinebot_ids)
        if len(old_vinebot_ids) > 0 and len(new_vinebot_ids) > 0:
            raise Exception, '%d has both vinebots that are now not visible AND vinebots that are now visible that weren\'t before. You did too much between calculations!'
        elif len(old_vinebot_ids) > 0:
            return set([v.FetchedVinebot(can_write=self.can_write, dbid=vinebot_id) for vinebot_id in old_vinebot_ids])
        elif len(new_vinebot_ids) > 0:
            return set([v.FetchedVinebot(can_write=self.can_write, dbid=vinebot_id) for vinebot_id in new_vinebot_ids])
        else:
            return set([])
    
    def delete(self):
        if not self.can_write:
            raise UserPermissionsException
        g.db.execute("""DELETE FROM users
                        WHERE id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.ectl.unregister(self.name)
    
    def __getattr__(self, name):
        if name == 'jid':
            return '%s@%s' % (self.name, constants.server)
        if name == 'friends':
            if self._friends is None:
                self._friends = self._fetch_friends()
            return self._friends
        elif name == 'active_vinebots':
            if self._active_vinebots is None:
                self._active_vinebots = self._fetch_current_active_vinebots()
            return self._active_vinebots
        elif name == 'observed_vinebots':
            if self._observed_vinebots is None:
                self._observed_vinebots = self._fetch_visible_active_vinebots()
            return self._observed_vinebots
        elif name == 'symmetric_vinebots':
            if self._symmetric_vinebots is None:
                self._symmetric_vinebots = self._fetch_vinebots_symmetric_only()
            return self._symmetric_vinebots
        elif name == 'incoming_vinebots':
            if self._incoming_vinebots is None:
                self._incoming_vinebots = self._fetch_vinebots_incoming_only()
            return self._incoming_vinebots
        elif name == 'outgoing_vinebots':
            if self._outgoing_vinebots is None:
                self._outgoing_vinebots = self._fetch_vinebots_outgoing_only()
            return self._outgoing_vinebots
        else:
            dict.__getattr__(self, name)
    
    def __setattr__(self, name, value):
        if name == ['jid', 'friends', 'active_vinebots', 'observed_vinebots', 'symmetric_vinebots', 'incoming_vinebots', 'outgoing_vinebots']:
            raise AttributeError("%s is an immutable attribute." % name)
        else:
            dict.__setattr__(self, name, value)
    
    def __eq__(self, other):
        if not isinstance(other, AbstractUser):
            return False
        return (self.id == other.id and self.name == other.name)
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    def __hash__(self):
        return hash('%d.%s' % (self.id, self.name))
    
    def __str__(self):
        return self.__repr__()
    
    def __repr__(self):
        return '%s(name=\'%s\', dbid=%d)' % (self.__class__.__name__, self.name, self.id)
    

class InsertedUser(AbstractUser):
    def __init__(self, name, password):
        super(InsertedUser, self).__init__(can_write=True)
        dbid = g.db.execute("""INSERT INTO users (name)
                               VALUES (%(name)s)
                            """, {
                               'name': name
                            })
        g.ectl.register(name, password)
        self.id = dbid
        self.name = name
    

class FetchedUser(AbstractUser):
    def __init__(self, can_write=False, name=None, dbid=None):
        super(FetchedUser, self).__init__(can_write)
        if name and dbid:
            self.id = dbid
            self.name = name
        elif name:
            dbid = g.db.execute_and_fetchall("""SELECT id
                                                FROM users
                                                WHERE name = %(name)s
                                             """, {
                                                'name': name
                                             }, strip_pairs=True)
            self.id = dbid[0] if len(dbid) == 1 else None
            self.name = name
        elif dbid:
            name = g.db.execute_and_fetchall("""SELECT name
                                                         FROM users
                                                         WHERE id = %(id)s
                                                      """, {
                                                         'id': dbid
                                                      }, strip_pairs=True)
            self.id   = dbid
            self.name = name[0] if len(name) == 1 else None
        else:
            raise Exception, 'User objects must be initialized with either a name or id.'
        if not self.id or not self.name:
            raise NotUserException, 'User with name=%s and id=%s was not found in the database' % (name, dbid)
    
