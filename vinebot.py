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

class AbstractVinebot(object):
    def __init__(self):
        self.topic = None
        self._edges = None
        self._participants = None
        self._observers = None
        # self._topic = self._format_topic(topic)
        #TODO
        #TODO
        #TODO get a lock for this vinebot
        #TODO
        #TODO
    
    def cleanup(self):
        pass
        #TODO release the lock for this vinebot
        #NOTE that it shouldn't rely on database state, since the vinebot may have been deleted
    
    def add_to_roster_of(self, user, nick):
        g.ectl.add_rosteritem(user.name, self.jiduser, nick)
    
    def remove_from_roster_of(self, user):
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
                                                 WHERE participants.vinebot_id = %(id)s
                                                 AND participants.user_id = users.id
                                                 AND participants.user_id = incoming.to_id
                                                 AND participants.user_id = outgoing.from_id
                                                 AND incoming.from_id = outgoing.to_id
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
        g.db.execute("""INSERT INTO participants (vinebot_id, user_id)
                        VALUES (%(vinebot_id)s, %(user_id)s)
                     """, {
                        'vinebot_id': self.id,
                        'user_id': user.id
                     })
        #NOTE adding "self.participants" here to initialize the pariticipants causes an error I don't understand
        self._participants = self._participants.union([user])
    
    def remove_participant(self, user):
        self._participants = self._participants.difference([user])
        g.db.execute("""DELETE FROM participants
                        WHERE user_id = %(user_id)s
                        AND vinebot_id = %(vinebot_id)s
                     """, {
                        'vinebot_id': self.id,
                        'user_id': user.id
                     })
    
    def get_nick(self, viewer):
        #refactor this, if viewer is none then we have a mess
        if self.is_active:
            users = list(self.participants.difference([viewer]))
        else:
            users = list(self.edge_users.difference([viewer]))
        if len(users) < 1:
            return self.jiduser
        elif len(users) == 1:
            return users[0].name
        else:
            if viewer:
                users.insert(0, 'you')
            comma_sep = ''.join([', %s' % user.name for user in users[1:-1]])
            return '%s%s & %s' % (users[0].name, comma_sep, users[-1].name)
    
    def update_rosters(self, old_participants, new_participants):
        #NOTE that I'm no longer using participants_changed - because it would only be false if the users already had symmetric edges, it's not worth the complexity
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
        for old_participant in old_participants.difference(new_observers).difference(new_participants):
            self.remove_from_roster_of(old_participant)
        for new_participant in new_participants:
            self.add_to_roster_of(new_participant, self.get_nick(new_participant))
        # Finally, update the observers
        for old_observer in old_observers.difference(new_participants).difference(new_observers):
            self.remove_from_roster_of(old_observer)
        for new_observer in new_observers.difference(new_participants):
            self.add_to_roster_of(new_observer, nick=observer_nick)
    
    def delete(self):
        #TODO remove from rosters?
        g.db.execute("""DELETE FROM edges
                           WHERE vinebot_id = %(id)s
                        """, {           
                           'id': self.id
                        })
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
        if name == 'is_active':
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
                raise AttributeError("Vinebot somehow has %d edges" % len(self.edges))
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
        if name in ['is_active', 'edges', 'edge_users', 'participants', 'observers', 'everyone']:
            raise AttributeError("%s is an immutable attribute." % name)
        else:
            dict.__setattr__(self, name, value)
    
    def __eq__(self, other):
        if not isinstance(other, AbstractVinebot):
            return False
        return (self.id == other.id and self.jiduser == other.jiduser)
    
    def __hash__(self):
        return hash('%d.%s' % (self.id, self.jiduser))
    

class InsertedVinebot(AbstractVinebot):
    def __init__(self):
        super(InsertedVinebot, self).__init__()
        _uuid = uuid.uuid4()
        self.jiduser = '%s%s' % (constants.vinebot_prefix, shortuuid.encode(_uuid))
        self.id = g.db.execute("""INSERT INTO vinebots (uuid)
                                      VALUES (%(uuid)s)
                                   """, {
                                      'uuid': _uuid.bytes
                                   })
    

class FetchedVinebot(AbstractVinebot):
    def __init__(self, jiduser=None, dbid=None):#, edges=None):
        super(FetchedVinebot, self).__init__()
        # if edges and len(edges) > 2:
        #     raise Exception, 'Vinebots cannot have more than two edges associated with them.'
        if dbid:
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
        # if edges:
        #     for edge in edges:
        #         self.add_fetched_edge(edge)
    
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
    
