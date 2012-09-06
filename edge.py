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
        dbid = self._db.execute("""INSERT INTO edges (from_id, to_id, vinebot_id)
                                   VALUES (%(f_id)s, %(t_id)s, (%(vinebot_id)s))
                                """, {           
                                   't_id': t_user.id, 
                                   'f_id': f_user.id,
                                   'vinebot_id': vinebot_id
                                })
        self.vinebot_id = vinebot_id
        self.id = dbid
    

class FetchedEdge(AbstractEdge):
    def __init__(self, db, ectl, f_user, t_user):
        super(FetchedEdge, self).__init__(db, ectl, f_user, t_user)
        result = self._db.execute_and_fetchall("""SELECT id, vinebot_id
                                                            FROM edges
                                                            WHERE to_id = %(t_id)s
                                                            AND from_id = %(f_id)s
                                                         """, {
                                                            't_id': t_user.id, 
                                                            'f_id': f_user.id
                                                         })
        if len(result) == 0:
            raise NotEdgeException
        self.id = result[0][0]
        self.vinebot_id = result[0][1]
    
