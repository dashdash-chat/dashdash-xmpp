#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import uuid
import shortuuid
import constants
from datetime import datetime, timedelta

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

class NotVinebotException(Exception):
    pass

class AbstractVinebot(object):
    def __init__(self, db, ectl):
        self._db = db
        self._ectl = ectl
        self._edges = []
        self.topic = None
        # self._participants = participants
        # self._is_active = is_active
        # self._is_party = is_party
        # self._topic = self._format_topic(topic)
        # self._observers = None
        #TODO
        #TODO
        #TODO get a lock for this vinebot
        #TODO
        #TODO
    
    def cleanup(self):
        pass
        #TODO release the lock for this vinebot
    
    def add_to_roster_of(self, user):
        self._ectl.add_rosteritem(user.name, self.jiduser, user.name)  #TODO calculate the nickname
    
    def remove_from_roster_of(self, user):
        self._ectl.delete_rosteritem(user.name, self.jiduser)
    
    def is_active(self):
        participant_count = self._db.execute_and_fetchall("""SELECT COUNT(*)
                                                             FROM participants
                                                             WHERE vinebot_id = %(id)s
                                                          """, {
                                                              'id': self.id
                                                          })
        return participant_count[0][0] > 0
    
    def fetch_participants(self):
        participants = self._db.execute_and_fetchall("""SELECT users.name, users.id
                                                        FROM participants, users
                                                        WHERE participants.vinebot_id = %(id)s
                                                        AND participants.user_id = users.id
                                                     """, {
                                                         'id': self.id
                                                     })
        return set([User(name=participant[0], dbid=participant[1]) for participant in participants])
    
    def fetch_observers(self):
        if not self.is_active():
            return set([])
        observers = self._db.execute_and_fetchall("""SELECT users.name, users.id
                                                     FROM participants, edges AS outgoing, edges AS incoming, users
                                                     WHERE participants.vinebot_id = %(id)s
                                                     AND participants.user_id = users.id
                                                     AND participants.user_id = incoming.to_id
                                                     AND participants.user_id = outgoing.from_id
                                                     AND incoming.from_id = outgoing.to_id
                                                  """, {
                                                      'id': self.id
                                                  })
        return set([User(name=observer[0], dbid=observer[1]) for observer in observers])
    
    def update_rosters(self):
        if len(self._edges) == 2:
            logging.info("update symmetric rosters here")
        elif len(self._edges) == 1:
            logging.info("update asymmetric rosters here")
            # make sure that vinebot isn't on other users roster?
        else:
            logging.info("update party rosters")
    
    def add_fetched_edge(self, edge):
        if edge.vinebot_id != self.id:
            raise Exception, 'Edge with id %s and vinebot_id %s cannot be added to Vinebot with id %s' % (edge.id, edge.vinebot_id, self.id)
        if len(self._edges) == 2:
            raise Exception, "Vinebot %s already has two edges %s and %s" % (self._id, self._edges[0].id, self._edges[1].id)
        if len(self._edges) == 1:
            if not (edge.from_user.id == self._edges[0].to_user.id and edge.to_user.id == self._edges[0].from_user.id):
                raise Exception, "New edge users %s and %s do not match existing edge users %s and %s " % (edge.from_user.id, edge.to_user.id, self._edges[0].from_user.id, self._edges[0].to_user.id)
        self._edges.append(edge)
        
    def delete(self):
        self._db.execute("""DELETE FROM edges
                           WHERE vinebot_id = %(id)s
                        """, {           
                           'id': self.id
                        })
        self._db.execute("""DELETE FROM participants
                           WHERE vinebot_id = %(id)s
                        """, {           
                           'id': self.id
                        })
        self._db.execute("""DELETE FROM topics
                           WHERE vinebot_id = %(id)s
                        """, {           
                           'id': self.id
                        })
        self._db.execute("""DELETE FROM vinebots
                           WHERE id = %(id)s
                        """, {           
                           'id': self.id
                        })
    

class InsertedVinebot(AbstractVinebot):
    def __init__(self, db, ectl, ):
        super(InsertedVinebot, self).__init__(db, ectl)
        _uuid = uuid.uuid4()
        self.jiduser = '%s%s' % (constants.vinebot_prefix, shortuuid.encode(_uuid))
        self.id = self._db.execute("""INSERT INTO vinebots (uuid)
                                      VALUES (%(uuid)s)
                                   """, {
                                      'uuid': _uuid.bytes
                                   })
    

class FetchedVinebot(AbstractVinebot):
    def __init__(self, db, ectl, jiduser=None, dbid=None, edges=None):
        super(FetchedVinebot, self).__init__(db, ectl)
        if edges and len(edges) > 2:
            raise Exception, 'Vinebots cannot have more than two edges associated with them.'
        if dbid:
            _uuid = self._db.execute_and_fetchall("""SELECT uuid 
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
            dbid = self._db.execute_and_fetchall("""SELECT id
                                                    FROM vinebots
                                                    WHERE uuid = %(uuid)s
                                                 """, {
                                                    'uuid': _uuid.bytes
                                                 }, strip_pairs=True)
            self.jiduser = jiduser
            self.id = dbid[0]
        elif jiduser == '':  # because the leaf itself has no username, and we want to fail gracefully
            raise NotVinebotException
        else:
            raise Exception, 'FetchedVinebots require either the vinebot\'s username or database id as parameters.'
        if edges:
            for edge in edges:
                self.add_fetched_edge(edge)
    
