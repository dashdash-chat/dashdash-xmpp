#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import uuid
import shortuuid
import constants
from datetime import datetime, timedelta
from constants import g
import user as u
import edge as e

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

class NotVinebotException(Exception):
    pass

class VinebotPermissionsException(Exception):
    pass

class AbstractVinebot(object):
    def __init__(self, can_write=False):
        self._topic = None  # None is meaningful to the leaf component, so it might get initialized again by FetchedVinebot
        self._edges = None
        self._participants = None
        self._observers = None
        self.can_write = can_write
        #TODO add transactions?
    
    def acquire_lock(self):
        if self.can_write:
            g.db.lock_vinebot(self.jiduser, 10)
            logging.debug('acquired lock for %s' % self.jiduser)
    
    def release_lock(self):
        if self.can_write:
            g.db.release_vinebot(self.jiduser)
            logging.debug('released lock for %s' % self.jiduser)
    
    def add_to_roster_of(self, user, nick):
        if not self.can_write:
            raise VinebotPermissionsException
        g.ectl.add_rosteritem(user.name, self.jiduser, nick)
    
    def remove_from_roster_of(self, user):
        if not self.can_write:
            raise VinebotPermissionsException
        g.ectl.delete_rosteritem(user.name, self.jiduser)
    
    def _fetch_participants(self):
        participants = g.db.execute_and_fetchall("""SELECT users.name, users.id
                                                    FROM participants, users
                                                    WHERE participants.vinebot_id = %(id)s
                                                    AND participants.user_id = users.id
                                                 """, {
                                                     'id': self.id
                                                 })
        return frozenset([u.FetchedUser(name=participant[0], dbid=participant[1]) for participant in participants])
    
    def _fetch_observers(self):
        if not self.is_active:
            return frozenset([])
        observers = g.db.execute_and_fetchall("""SELECT users.name, users.id
                                                 FROM participants, edges AS outgoing, edges AS incoming, users
                                                 WHERE outgoing.to_id = users.id
                                                 AND incoming.from_id = outgoing.to_id
                                                 AND participants.vinebot_id = %(id)s
                                                 AND participants.user_id = incoming.to_id
                                                 AND participants.user_id = outgoing.from_id
                                                 AND (SELECT COUNT(*) 
                                                      FROM participants 
                                                      WHERE participants.vinebot_id = %(id)s 
                                                      AND user_id=users.id
                                                     ) = 0
                                              """, {
                                                  'id': self.id
                                              })
        return frozenset([u.FetchedUser(name=observer[0], dbid=observer[1]) for observer in observers])
    
    def _fetch_edges(self):
        edge_ids = g.db.execute_and_fetchall("""SELECT id
                                                FROM edges
                                                WHERE vinebot_id = %(id)s
                                             """, {
                                                 'id': self.id
                                             }, strip_pairs=True)
        return frozenset([e.FetchedEdge(dbid=edge_id) for edge_id in edge_ids])
    
    def add_participant(self, user):
        if not self.can_write:
            raise VinebotPermissionsException
        g.db.execute("""INSERT INTO participants (vinebot_id, user_id)
                        VALUES (%(vinebot_id)s, %(user_id)s)
                     """, {
                        'vinebot_id': self.id,
                        'user_id': user.id
                     })
        #NOTE adding "self.participants" here to initialize the pariticipants causes an error I don't understand
        self._participants = self._participants.union([user])
    
    def remove_participant(self, user):        
        if not self.can_write:
            raise VinebotPermissionsException
        self._participants = self._participants.difference([user])
        g.db.execute("""DELETE FROM participants
                        WHERE user_id = %(user_id)s
                        AND vinebot_id = %(vinebot_id)s
                     """, {
                        'vinebot_id': self.id,
                        'user_id': user.id
                     })
    
    def get_nick(self, viewer):
        if self.is_active:
            usernames = [user.name for user in self.participants.difference([viewer])]
        else:
            usernames = [user.name for user in self.edge_users.difference([viewer])]
        if len(usernames) < 1:
            return self.jiduser
        elif len(usernames) == 1:
            return usernames[0]
        else:
            if viewer:
                usernames.insert(0, 'you')
            comma_sep = ''.join([', %s' % username for username in usernames[1:-1]])
            return '%s%s & %s' % (usernames[0], comma_sep, usernames[-1])
    
    def update_rosters(self, old_participants, new_participants, protected_participants=set([])):  # if there are still edges between the users, we might not want to change their rosteritems
        observer_nick = self.get_nick(None)
        # First, create the old and new lists of observers
        def get_observers_for(users):
            return reduce(lambda observers, user: observers.union(user.friends), users, set([]))
        old_observers = get_observers_for(old_participants)
        # if new_participants == self.participants:
        #     new_observers = self.observers  # no need to calculate the observer list twice
        # else:
        new_observers = get_observers_for(new_participants)
        # Then, update the participants
        for old_participant in old_participants.difference(new_observers).difference(new_participants).difference(protected_participants):
            self.remove_from_roster_of(old_participant)
        for new_participant in new_participants.difference(protected_participants):
            self.add_to_roster_of(new_participant, self.get_nick(new_participant))
        # Finally, update the observers
        for old_observer in old_observers.difference(new_participants).difference(protected_participants).difference(new_observers):
            self.remove_from_roster_of(old_observer)
        for new_observer in new_observers.difference(new_participants).difference(protected_participants):
            self.add_to_roster_of(new_observer, nick=observer_nick)
    
    def _set_topic(self, body):        
        if not self.can_write:
            raise VinebotPermissionsException
        g.db.execute("""DELETE FROM topics
                        WHERE vinebot_id = %(vinebot_id)s
                    """, {
                        'vinebot_id': self.id
                    })
        self._topic = None
        if body:
            g.db.execute("""INSERT INTO topics (vinebot_id, body)
                            VALUES (%(vinebot_id)s, %(body)s)
                         """, {
                            'vinebot_id': self.id,
                            'body': body.encode('utf-8')
                         })
            self._topic = self._format_topic(body, datetime.now())
    
    def _fetch_topic(self):
        topic = g.db.execute_and_fetchall("""SELECT body, created
                                             FROM topics
                                             WHERE vinebot_id = %(vinebot_id)s
                                          """, {
                                             'vinebot_id': self.id
                                          })
        if topic and len(topic) > 0:
            body, created = topic[0]
            return self._format_topic(body, created)
        return None
    
    def _format_topic(self, body, created):
        return "%s%s" % (body, (created - timedelta(hours=6)).strftime(' (as of %b %d at %-I:%M%p EST)'))
    
    def delete(self):        
        if not self.can_write:
            raise VinebotPermissionsException
        for user in self.edge_users:
            self.remove_from_roster_of(user)
        # don't delete the actual edges though - either they're deleted elsewhere, or will be transferred to a new vinebot
        g.db.execute("""DELETE FROM participants
                           WHERE vinebot_id = %(id)s
                        """, {           
                           'id': self.id
                        })
        g.db.execute("""DELETE FROM topics
                           WHERE vinebot_id = %(id)s
                        """, {           
                           'id': self.id
                        })
        g.db.execute("""DELETE FROM vinebots
                           WHERE id = %(id)s
                        """, {           
                           'id': self.id
                        })
    
    def __getattr__(self, name):
        if name == 'topic':
            return self._topic
        elif name == 'is_active':
            return len(self.participants) >= 2
        elif name == 'edges':
            if self._edges is None:
                self._edges = self._fetch_edges()
            return self._edges
        elif name == 'edge_users':
            if len(self.edges) == 0:
                return set([])
            elif len(self.edges) == 1:
                edge = iter(self.edges).next()
                return set([edge.t_user, edge.f_user])  # doesn't need to be a frozenset
            elif len(self.edges) == 2:
                edge1, edge2 = self.edges
                return set([edge1.t_user, edge1.f_user, edge2.t_user, edge2.f_user])
            else:
                raise AttributeError("Vinebot %d somehow has %d edges" % (self.id, len(self.edges)))
        elif name == 'participants':
            if self._participants is None:
                self._participants = self._fetch_participants()
            return self._participants
        elif name == 'observers':
            if self._observers is None:
                self._observers = self._fetch_observers()
            return self._observers
        elif name == 'everyone':
            return self.participants.union(self.observers)
        # __getattr__ is only called as a last resort, so we don't need a catchall
    
    def __setattr__(self, name, value):
        if name == 'topic':
            self._set_topic(value)
        elif name in ['topic', 'is_active', 'edges', 'edge_users', 'participants', 'observers', 'everyone']:
            raise AttributeError("%s is an immutable attribute." % name)
        else:
            dict.__setattr__(self, name, value)
    
    def __eq__(self, other):
        if not isinstance(other, AbstractVinebot):
            return False
        return (self.id == other.id and self.jiduser == other.jiduser)
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    def __hash__(self):
        return hash('%d.%s' % (self.id, self.jiduser))
    
    def __str__(self):
        return self.__repr__()
    
    def __repr__(self):
        return '%s(jiduser=\'%s\', dbid=%d)' % (self.__class__.__name__, self.jiduser, self.id)
    

class InsertedVinebot(AbstractVinebot):
    def __init__(self):
        super(InsertedVinebot, self).__init__(can_write=True)
        _uuid = uuid.uuid4()
        self.jiduser = '%s%s' % (constants.vinebot_prefix, shortuuid.encode(_uuid))
        self.id = g.db.execute("""INSERT INTO vinebots (uuid)
                                      VALUES (%(uuid)s)
                                   """, {
                                      'uuid': _uuid.bytes
                                   })
        self.acquire_lock()  # I wish this could go in AbstractVinebot.__init__(), but that happens before we have self.jiduser
    

class FetchedVinebot(AbstractVinebot):
    def __init__(self, can_write=False, jiduser=None, dbid=None, _uuid=None):#, edges=None):
        super(FetchedVinebot, self).__init__(can_write)
        if dbid and _uuid:
            self.jiduser = '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid.UUID(bytes=_uuid)))
            self.id = dbid
        elif dbid:
            _uuid = g.db.execute_and_fetchall("""SELECT uuid 
                                                     FROM vinebots
                                                     WHERE id = %(id)s
                                                  """, {
                                                      'id': dbid
                                                  }, strip_pairs=True)
            if not _uuid:
                raise NotVinebotException
            self.jiduser = '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid.UUID(bytes=_uuid[0])))
            self.id = dbid
        elif jiduser:
            if not jiduser.startswith(constants.vinebot_prefix):
                raise NotVinebotException
            _shortuuid = jiduser.replace(constants.vinebot_prefix, '')
            _uuid = shortuuid.decode(_shortuuid)
            dbid = g.db.execute_and_fetchall("""SELECT id
                                                    FROM vinebots
                                                    WHERE uuid = %(uuid)s
                                                 """, {
                                                    'uuid': _uuid.bytes
                                                 }, strip_pairs=True)
            if not dbid:
                raise NotVinebotException
            self.jiduser = jiduser
            self.id = dbid[0]
        elif jiduser == '':  # because the leaf itself has no username, and we want to fail gracefully
            raise NotVinebotException
        else:
            raise Exception, 'FetchedVinebots require either the vinebot\'s username or database id as parameters.'
        self._topic = self._fetch_topic()
        self.acquire_lock()
    
    @staticmethod
    def fetch_vinebots_with_participants():
        vinebot_ids = g.db.execute_and_fetchall("""SELECT vinebot_id 
                                                   FROM participants
                                                   GROUP BY vinebot_id
                                                """, strip_pairs=True)
        return [FetchedVinebot(dbid=vinebot_id) for vinebot_id in vinebot_ids]
    
    @staticmethod
    def fetch_vinebots_with_edges():
        vinebot_ids = g.db.execute_and_fetchall("""SELECT edges.vinebot_id 
                                                   FROM edges
                                                   WHERE edges.vinebot_id IS NOT NULL
                                                   AND (SELECT COUNT(*) FROM participants WHERE vinebot_id = edges.vinebot_id) = 0
                                                   GROUP BY edges.vinebot_id
                                                """, strip_pairs=True)
        return [FetchedVinebot(dbid=vinebot_id) for vinebot_id in vinebot_ids]
    
