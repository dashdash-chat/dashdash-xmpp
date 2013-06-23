#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re
import sys
from MySQLdb import IntegrityError
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
        self._status = None
        self._friends = None
        self._active_vinebots = None
        self._observed_vinebots = None
        self._symmetric_vinebots = None
        self._outgoing_vinebots = None
        self._incoming_vinebots = None
        self._noted_vinebot_ids = None
        self._stage = None
        self.can_write = can_write
        # if self.can_write:  the user doesn't actually require a lock, since deleting is really the only potential issue
    
    def status(self):
        if not self._status:  # cache this, since a user status can't change during the handling of a single stanza
            self._status = g.ectl.user_status(self.name)
        return self._status
    
    def is_online(self):
        return self.status() != 'unavailable'  # this function is useful for list filters
    
    def roster(self):
        return g.ectl.get_roster(self.name)
    
    def block(self, blockee):
        try:
            g.db.execute_and_fetchall("""INSERT INTO blocks (from_user_id, to_user_id)
                                         VALUES (%(from_user_id)s, %(to_user_id)s)
                                      """, {
                                         'from_user_id': self.id,
                                         'to_user_id': blockee.id
                                      })
            return True
        except IntegrityError, e:
            if e[0] == 1062:
                return False
            raise e
    
    def unblock(self, unblockee):
        res = g.db.execute_and_fetchall("""SELECT COUNT(*)
                                           FROM blocks
                                           WHERE to_user_id = %(to_user_id)s
                                           AND from_user_id = %(from_user_id)s
                                        """, {
                                           'from_user_id': self.id,
                                           'to_user_id': unblockee.id
                                        }, strip_pairs=True)
        if res and res[0] > 0:
            g.db.execute_and_fetchall("""DELETE FROM blocks
                                         WHERE to_user_id = %(to_user_id)s
                                         AND from_user_id = %(from_user_id)s
                                    """, {
                                       'from_user_id': self.id,
                                       'to_user_id': unblockee.id
                                    })
            return True
        else:
            return False
    
    def blockees(self):
        block_pairs = g.db.execute_and_fetchall("""SELECT users.name, users.id
                                                   FROM blocks, users
                                                   WHERE blocks.to_user_id = users.id
                                                   AND blocks.from_user_id = %(from_user_id)s
                                                """, {
                                                   'from_user_id': self.id
                                                })
        return frozenset([FetchedUser(name=block_pair[0], dbid=block_pair[1]) for block_pair in block_pairs])
    
    def needs_onboarding(self):
        return self.stage == 'welcome'
    
    def set_stage(self, stage):
        # if not self.can_write:  #NOTE that this actually doesn't mess up any Vinebot state, so we don't need to be careful about this
        #     raise UserPermissionsException
        g.db.execute("""UPDATE users
                        SET stage = %(stage)s
                        WHERE id = %(id)s
                     """, {
                        'stage': str(stage),
                        'id': self.id
                     })
        self._stage = str(stage)
    
    def _fetch_stage(self):
        stage = g.db.execute_and_fetchall("""SELECT stage
                                                    FROM users
                                                    WHERE id = %(id)s
                                                 """, {
                                                    'id': self.id
                                                 }, strip_pairs=True)
        return stage[0] if stage else None
    
    def _fetch_friends(self):
        friend_pairs = g.db.execute_and_fetchall("""SELECT users.name, users.id
                                                    FROM users, edges AS outgoing, edges AS incoming
                                                    WHERE outgoing.vinebot_id = incoming.vinebot_id
                                                    AND outgoing.from_id = %(id)s
                                                    AND incoming.to_id = %(id)s
                                                    AND outgoing.to_id = incoming.from_id
                                                    AND outgoing.to_id = users.id
                                                    AND users.is_active = true
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
                                                AND (SELECT COUNT(*) FROM participants WHERE vinebot_id = vinebots.id) = 0
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
                                                AND (SELECT COUNT(*) FROM participants WHERE vinebot_id = vinebots.id) = 0
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
        g.db.execute("""UPDATE users
                        SET is_active = false
                        WHERE id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.ectl.unregister(self.name)
    
    def purge(self):
        if not self.can_write:
            raise UserPermissionsException
        g.db.execute("""DELETE FROM user_tasks
                        WHERE user_id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM demos
                        WHERE user_id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM invitees
                        WHERE invitee_id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""UPDATE invites
                        SET sender = NULL
                        WHERE sender = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM blocks
                        WHERE to_user_id = %(id)s
                        OR from_user_id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM artificial_follows
                        WHERE to_user_id = %(id)s
                        OR from_user_id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM twitter_follows
                        WHERE from_twitter_id = (SELECT twitter_id
                                                 FROM users
                                                 WHERE id = %(id)s)
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM recipients
                        WHERE recipient_id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM recipients
                        WHERE message_id IN (SELECT id
                                             FROM messages
                                             WHERE sender_id = %(id)s)
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM recipients
                        WHERE message_id IN (SELECT id
                                             FROM messages
                                             WHERE parent_command_id IN (SELECT id
                                                                         FROM commands
                                                                         WHERE sender_id = %(id)s))
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM messages
                        WHERE parent_command_id IN (SELECT id
                                                    FROM commands
                                                    WHERE sender_id = %(id)s)
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM messages
                        WHERE sender_id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM commands
                        WHERE sender_id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.db.execute("""DELETE FROM users
                        WHERE id = %(id)s
                     """, {
                        'id': self.id
                     })
        g.ectl.unregister(self.name)
    
    def __getattr__(self, name):
        if name == 'jid':
            return '%s@%s' % (self.name, constants.domain)
        elif name == 'is_protected':
            return self.name in constants.protected_users
        elif name == 'friends':
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
        elif name == 'stage':
            if self._stage is None:
                self._stage = self._fetch_stage()
            return self._stage
        # __getattr__ is only called as a last resort, so we don't need a catchall
    
    def __setattr__(self, name, value):
        if name == ['jid', 'friends', 'active_vinebots', 'observed_vinebots', 'symmetric_vinebots', 'incoming_vinebots', 'outgoing_vinebots', 'stage']:
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
    def __init__(self, name, password, should_register=True):
        super(InsertedUser, self).__init__(can_write=True)
        name = name.lower()
        if not re.match('^\w{1,15}$', name):
            raise NotUserException, 'Usernames must match /^\w{1,15}$/'
        try:
            dbid = g.db.execute("""INSERT INTO users (name)
                                   VALUES (%(name)s)
                                """, {
                                   'name': name
                                })
        except IntegrityError, e:
            dbid = g.db.execute_and_fetchall("""SELECT id
                                                FROM users
                                                WHERE name = %(name)s
                                                AND is_active = false
                                             """, {
                                                'name': name
                                             }, strip_pairs=True)
            if not dbid:
                raise IntegrityError, e
            dbid = dbid[0]
            g.db.execute("""UPDATE users
                            SET is_active = true,
                                stage = %(stage)s
                            WHERE id = %(id)s
                         """, {
                            'stage': None,
                            'id': dbid
                         })
        if should_register and password:
            g.ectl.register(name, password)
        self.id = dbid
        self.name = name
        self.twitter_id = None  # Newly-created users won't ever have tokens, since they haven't auth'd on the site yet
        self.twitter_token = None
        self.twitter_secret = None
    

class FetchedUser(AbstractUser):
    def __init__(self, can_write=False, name=None, dbid=None):
        super(FetchedUser, self).__init__(can_write)
        self.name = None
        self.id = None
        if name and dbid:
            dbid = int(dbid)
            res = g.db.execute_and_fetchall("""SELECT id, twitter_id, twitter_token, twitter_secret, stage
                                               FROM users
                                               WHERE id = %(id)s
                                            """, {
                                               'id': dbid
                                            })
            if res and len(res) == 1:  # Otherwise something bad has happened and we should raise the exception below
                res = res[0]
                self.id = dbid
                self.name = name.lower()
        elif name:
            res = g.db.execute_and_fetchall("""SELECT id, twitter_id, twitter_token, twitter_secret, stage
                                                FROM users
                                                WHERE name = %(name)s
                                                AND is_active = true
                                             """, {
                                                'name': name.lower()
                                             })
            if res and len(res) == 1:
                res = res[0]
                self.id = res[0]
                self.name = name.lower()
        elif dbid:
            dbid = int(dbid)
            res = g.db.execute_and_fetchall("""SELECT name, twitter_id, twitter_token, twitter_secret, stage
                                                FROM users
                                                WHERE id = %(id)s
                                                AND is_active = true
                                             """, {
                                                'id': dbid
                                             })
            if res and len(res) == 1:
                res = res[0]
                self.id = dbid
                self.name = res[0]
        else:
            raise NotUserException, 'User objects must be initialized with either a name or id.'
        if not self.id or not self.name:
            raise NotUserException, 'User with name=%s and id=%s was not found in the database' % (name.lower(), dbid)
        self.twitter_id     = res[1]
        self.twitter_token  = res[2]
        self.twitter_secret = res[3]
        self._stage = res[4]
    
