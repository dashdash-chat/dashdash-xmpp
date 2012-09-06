#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
from constants import g
from user import FetchedUser

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input
    
class NotEdgeException(Exception):
    pass

class AbstractEdge(object):
    def __init__(self):
        self.f_user = None  # from
        self.t_user = None  # to
        self.vinebot_id = None
        self.id = None
    
    def delete(self):
        g.db.execute("""DELETE FROM edges
                            WHERE id = %(id)s
                         """, {           
                            'id': self.id
                         })

class InsertedEdge(AbstractEdge):
    def __init__(self, f_user, t_user, vinebot_id):
        super(InsertedEdge, self).__init__()
        dbid = g.db.execute("""INSERT INTO edges (from_id, to_id, vinebot_id)
                                   VALUES (%(f_id)s, %(t_id)s, (%(vinebot_id)s))
                                """, {           
                                   't_id': t_user.id, 
                                   'f_id': f_user.id,
                                   'vinebot_id': vinebot_id
                                })
        self.f_user = f_user
        self.t_user = t_user
        self.vinebot_id = vinebot_id
        self.id = dbid
    

class FetchedEdge(AbstractEdge):
    def __init__(self, f_user=None, t_user=None, vinebot=None):
        super(FetchedEdge, self).__init__()
        if f_user and t_user and vinebot is None:
            result = g.db.execute_and_fetchall("""SELECT id, vinebot_id
                                                                FROM edges
                                                                WHERE to_id = %(t_id)s
                                                                AND from_id = %(f_id)s
                                                             """, {
                                                                't_id': t_user.id, 
                                                                'f_id': f_user.id
                                                             })
            if len(result) == 0:
                raise NotEdgeException
            self.f_user = f_user
            self.t_user = t_user
            self.id = result[0][0]
            self.vinebot_id = result[0][1]
        elif vinebot and f_user and t_user is None:
            result = g.db.execute_and_fetchall("""SELECT id, to_id
                                                      FROM edges
                                                      WHERE vinebot_id = %(vinebot_id)s
                                                      AND from_id = %(f_id)s
                                                  """, {
                                                      'vinebot_id': vinebot.id, 
                                                      'f_id': f_user.id
                                                  })
            if len(result) == 0:
                raise NotEdgeException
            self.f_user = f_user
            self.t_user = FetchedUser(dbid=result[0][1])
            self.id = result[0][0]
            self.vinebot_id = vinebot.id
        elif vinebot and t_user and f_user is None:
            result = g.db.execute_and_fetchall("""SELECT id, from_id
                                                      FROM edges
                                                      WHERE vinebot_id = %(vinebot_id)s
                                                      AND to_id = %(t_id)s
                                                  """, {
                                                      'vinebot_id': vinebot.id, 
                                                      't_id': t_user.id
                                                  })
            if len(result) == 0:
                raise NotEdgeException
            self.f_user = FetchedUser(dbid=result[0][1])
            self.t_user = t_user
            self.id = result[0][0]
            self.vinebot_id = vinebot.id
        else:
            raise Exception, 'FechedEdges require either both users or a vinebot and either user as parameters.'
    
