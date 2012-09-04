#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input
    
class NotEdgeException(Exception):
    pass

class AbstractEdge(object):
    def __init__(self, db, ectl, f_user, t_user):
        self._db = db
        self._ectl = ectl
        self.f_user = f_user  # from
        self.t_user = t_user  # to
        self.vinebot_id = None
        self.id = None
    
    def delete(self):
        self._db.execute("""DELETE FROM edges
                           WHERE id = %(id)s
                        """, {           
                           'id': self.id
                        })

class InsertedEdge(AbstractEdge):
    def __init__(self, db, ectl, f_user, t_user, vinebot_id):
        super(InsertedEdge, self).__init__(db, ectl, f_user, t_user)
        dbid = self._db.execute("""INSERT INTO edges (f_id, t_id, vinebot_id)
                                  VALUES (%(t_id)s, %(f_id)s, (%(vinebot_id)s))
                               """, {           
                                  't_id': t_user.id, 
                                  'f_id': f_user.id,
                                  'vinebot_id': vinebot.id
                               })
        self._vinebot_id = vinebot_id
        self._id = dbid
    

class FetchedEdge(AbstractEdge):
    def __init__(self, db, ectl, f_user, t_user):
         super(FetchedEdge, self).__init__(db, ectl, f_user, t_user)
         dbid, vinebot_id = self._db.execute_and_fetchall("""SELECT id, vinebot_id
                                                   FROM edges
                                                   WHERE t_id = %(t_id)s
                                                   AND f_id = %(f_id)s
                                                """, {
                                                   't_id': t_user.id, 
                                                   'f_id': f_user.id
                                                })
        if not dbid or not vinebot_id:
            raise NotEdgeException
        self._vinebot_id = vinebot_id
        self._id = dbid
    
