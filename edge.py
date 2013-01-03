#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
from constants import g
import user as u
import vinebot as v

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
    
    def change_vinebot(self, vinebot):
        if not vinebot.can_write:
            raise v.VinebotPermissionsException
        g.db.execute("""UPDATE edges
                        SET vinebot_id = %(vinebot_id)s
                        WHERE id = %(id)s
                     """, {
                        'vinebot_id': vinebot.id,
                        'id': self.id
                     })
        self.vinebot_id = vinebot.id
    
    def delete(self, vinebot):  # passing in this vinebot doesn't actually protect us from anything, but forces us to be explicit
        if not vinebot.can_write:
            raise v.VinebotPermissionsException
        g.db.execute("""DELETE FROM edges
                            WHERE id = %(id)s
                         """, {           
                            'id': self.id
                         })
    
    def __str__(self):
        return self.__repr__()
    
    def __repr__(self):
        return '%s(dbid=\'%s\', vinebot_id=%d)' % (self.__class__.__name__, self.id, self.vinebot_id)
    

class InsertedEdge(AbstractEdge):
    def __init__(self, f_user, t_user, vinebot):        
        if not vinebot.can_write:
            raise v.VinebotPermissionsException
        super(InsertedEdge, self).__init__()
        dbid = g.db.execute("""INSERT INTO edges (from_id, to_id, vinebot_id)
                               VALUES (%(f_id)s, %(t_id)s, (%(vinebot_id)s))
                            """, {           
                               't_id': t_user.id, 
                               'f_id': f_user.id,
                               'vinebot_id': vinebot.id
                            })
        self.f_user = f_user
        self.t_user = t_user
        self.vinebot_id = vinebot.id
        self.id = dbid
    

class FetchedEdge(AbstractEdge):
    def __init__(self, f_user=None, t_user=None, vinebot_id=None, dbid=None):
        super(FetchedEdge, self).__init__()
        if f_user and t_user and vinebot_id and dbid:
            self.f_user = f_user
            self.t_user = t_user
            self.id = dbid
            self.vinebot_id = vinebot_id
        elif dbid and vinebot_id is None and f_user is None and t_user is None:
            result = g.db.execute_and_fetchall("""SELECT from_id, to_id, vinebot_id
                                                  FROM edges
                                                  WHERE id = %(id)s
                                               """, {
                                                  'id': dbid
                                               })
            if len(result) == 0:
                raise NotEdgeException
            self.f_user = u.FetchedUser(dbid=result[0][0])
            self.t_user = u.FetchedUser(dbid=result[0][1])
            self.id = dbid
            self.vinebot_id = result[0][2]
        elif f_user and t_user and vinebot_id is None and dbid is None:
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
            if result[0][1] is None:
                g.logger.error('Edge %s from %s to %s has no vinebot!' % (result[0][0], f_user.name, t_user.name))
                raise NotEdgeException
            self.f_user = f_user
            self.t_user = t_user
            self.id = result[0][0]
            self.vinebot_id = result[0][1]
        elif vinebot_id and f_user and t_user is None and dbid is None:
            result = g.db.execute_and_fetchall("""SELECT id, to_id
                                                  FROM edges
                                                  WHERE vinebot_id = %(vinebot_id)s
                                                  AND from_id = %(f_id)s
                                               """, {
                                                   'vinebot_id': vinebot_id, 
                                                   'f_id': f_user.id
                                               })
            if len(result) == 0:
                raise NotEdgeException
            self.f_user = f_user
            self.t_user = u.FetchedUser(dbid=result[0][1])
            self.id = result[0][0]
            self.vinebot_id = vinebot_id
        elif vinebot_id and t_user and f_user is None and dbid is None:
            result = g.db.execute_and_fetchall("""SELECT id, from_id
                                                  FROM edges
                                                  WHERE vinebot_id = %(vinebot_id)s
                                                  AND to_id = %(t_id)s
                                               """, {
                                                   'vinebot_id': vinebot_id, 
                                                   't_id': t_user.id
                                               })
            if len(result) == 0:
                raise NotEdgeException
            self.f_user = u.FetchedUser(dbid=result[0][1])
            self.t_user = t_user
            self.id = result[0][0]
            self.vinebot_id = vinebot_id
        else:
            raise Exception, 'FechedEdges require either both users or a vinebot_id and either user, or a dbid, or all four as parameters.'
    
    @staticmethod  # this is here and not in AbstractUser because it is coupled tightly to the FetchedEdge constructor, and isn't really a "safe" interface
    def fetch_edges_for_user(user):
        results = g.db.execute_and_fetchall("""SELECT from_id, vinebot_id, id
                                               FROM edges
                                               WHERE to_id = %(to_id)s
                                            """, {
                                               'to_id': user.id
                                            })
        to_edges = []
        if results and len(results) > 0:
            to_edges = [FetchedEdge(f_user=u.FetchedUser(dbid=result[0]),
                                    t_user=user,
                                    vinebot_id=result[1],
                                    dbid=result[2]
                                   ) for result in results]
        results = g.db.execute_and_fetchall("""SELECT to_id, vinebot_id, id
                                               FROM edges
                                               WHERE from_id = %(from_id)s
                                            """, {
                                               'from_id': user.id
                                            })
        from_edges = []
        if results and len(results) > 0:
            from_edges = [FetchedEdge(f_user=user,
                                      t_user=u.FetchedUser(dbid=result[0]),
                                      vinebot_id=result[1],
                                      dbid=result[2]
                                     ) for result in results]
        return frozenset(to_edges + from_edges)
    
