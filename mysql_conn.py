#!/usr/bin/env python
# -*- coding: utf-8 -*-\
import MySQLdb
import constants
from constants import g

class MySQLConnection(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.conn = None
        self.cursor = None
        self.connect()
    
    def execute_and_fetchall(self, query, data={}, strip_pairs=False):
        self.execute(query, data)
        fetched = self.cursor.fetchall()
        if fetched and len(fetched) > 0:
            if strip_pairs:
                return [result[0] for result in fetched]
            else:
                return fetched
        return []
    
    def execute(self, query, data={}):
        g.logger.debug(query % data)
        if not self.conn or not self.cursor:
            g.logger.debug("MySQL connection %s missing, attempting to reconnect and retry query" % self)
            self.connect()
        try:
            self.cursor.execute(query, data)
        except MySQLdb.OperationalError, e:
            if e[0] > 2000:  # error codes at http://dev.mysql.com/doc/refman/5.5/en/error-handling.html
                g.logger.info('MySQL OperationalError %d "%s" for query, will retry: %s' % (e[0], e[1], query % data))
                self.connect()  # Try again, but only once
                self.cursor.execute(query, data)
            else:
                raise e
        return self.conn.insert_id()
    
    def connect(self):
        self.cleanup()
        try:
            self.conn = MySQLdb.connect(constants.db_host,
                                        self.username,
                                        self.password,
                                        constants.db_name)
            self.conn.autocommit(True)
            self.cursor = self.conn.cursor()
            g.logger.debug("MySQL connection %s ready" % self)
        except MySQLdb.Error, e:
            g.logger.error('MySQL connection and/or cursor creation failed with %d: %s' % (e.args[0], e.args[1]))
            self.cleanup()
    
    def cleanup(self):
        if self.conn:
            self.conn.close()
    

class MySQLManager(object):
    def __init__(self, username, password):
        self._username = username
        self._password = password
        # the MySQLManager object has one connection for the leaf's lock and the data queries, one then one for each vinebot lock
        self._db = MySQLConnection(self._username, self._password)
        self._vinebot_conn_pool = set([MySQLConnection(self._username, self._password), MySQLConnection(self._username, self._password)])  # start it off with two in the pool
        self._vinebot_conn_dict = {}
    
    def execute_and_fetchall(self, query, data={}, strip_pairs=False):
        return self._db.execute_and_fetchall(query, data=data, strip_pairs=strip_pairs)
    
    def execute(self, query, data={}):
        return self._db.execute(query, data=data)
    
    def cleanup(self):
        self._db.cleanup()
        for db in self._vinebot_conn_pool:
            db.cleanup()
        self._vinebot_conn_pool = set([])
        for db in self._vinebot_conn_dict.values():
            db.cleanup()
        self._vinebot_conn_dict = {}
    
    def log_message(self, sender, recipients, body, vinebot=None, parent_message_id=None, parent_command_id=None):
        if body is None or body == '':  # chatstate stanzas and some /command replies stanzas don't have a body, so don't try to log them
            return
        log_id = self.execute("""INSERT INTO messages (vinebot_id, sender_id, parent_message_id, parent_command_id, body)
                                    VALUES (
                                        %(vinebot_id)s,
                                        %(sender_id)s,
                                        %(parent_message_id)s,
                                        %(parent_command_id)s,
                                        %(body)s
                                    )""", {
                                        'vinebot_id': vinebot.id if vinebot else None,
                                        'sender_id': sender.id if sender else None,
                                        'parent_message_id': parent_message_id,
                                        'parent_command_id': parent_command_id,
                                        'body': body.encode('utf-8')
                                    })
        for recipient in recipients:
            self.execute("""INSERT INTO recipients (message_id, recipient_id)
                            VALUES (%(log_id)s, %(recipient_id)s)
                         """, {
                               'log_id': log_id,
                               'recipient_id': recipient.id
                         })
        return log_id
    
    def log_command(self, sender, command_name, token, string, vinebot=None, is_valid=True):
        if string:
            string = string.encode('utf-8')
        return self.execute("""INSERT INTO commands (vinebot_id, sender_id, command_name, is_valid, token, string)
                                  VALUES (
                                      %(vinebot_id)s,
                                      %(sender_id)s,
                                      %(command_name)s,
                                      %(is_valid)s,
                                      %(token)s,
                                      %(string)s
                                  )""", {
                                      'vinebot_id': vinebot.id if vinebot else None,
                                      'sender_id':  sender.id,
                                      'command_name': command_name,
                                      'is_valid': is_valid,
                                      'token': token or None,
                                      'string': string or None
                                  })
    
    def lock_leaf(self, lock_name, timeout=0):
        if not lock_name.startswith(constants.leaves_mysql_lock_name):
            raise Exception
        lock = self._db.execute_and_fetchall("SELECT GET_LOCK(%(lock_name)s, %(timeout)s)", {
                                                'lock_name': lock_name,
                                                'timeout': timeout
                                             }, strip_pairs=True)
        return (lock and (lock[0] == 1))
    
    def is_unlocked_leaf(self, lock_name):
        if not lock_name.startswith(constants.leaves_mysql_lock_name):
            raise Exception
        lock = self._db.execute_and_fetchall("SELECT IS_FREE_LOCK(%(lock_name)s)", {
                                                'lock_name': lock_name
                                             }, strip_pairs=True)
        return (lock and (lock[0] == 1))
    
    def lock_vinebot(self, lock_name, timeout=0):
        try:
            db = self._vinebot_conn_pool.pop()
        except KeyError:
            db = MySQLConnection(self._username, self._password)
        lock = db.execute_and_fetchall("SELECT GET_LOCK(%(lock_name)s, %(timeout)s)", {
                                              'lock_name': lock_name,
                                              'timeout': timeout
                                           }, strip_pairs=True)
        lock_was_acquired = (lock and (lock[0] == 1))
        if lock_was_acquired:
            self._vinebot_conn_dict[lock_name] = db
            g.logger.debug('Acquired lock %s with MySQL conn %s' % (lock_name, db))
        else:
            self._vinebot_conn_pool.add(db)
            g.logger.error('Failed to acquire %s before timeout %d!' % (lock_name, timeout))
        return lock_was_acquired
    
    def release_vinebot(self, lock_name):
        if not lock_name in self._vinebot_conn_dict:
            raise Exception  # somehow we locked a vinebot without storing the connection
        db = self._vinebot_conn_dict.pop(lock_name)
        db.execute("SELECT RELEASE_LOCK(%(lock_name)s)", {'lock_name': lock_name})
        self._vinebot_conn_pool.add(db)
        g.logger.debug('Released lock %s with MySQL conn %s' % (lock_name, db))
    
