#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import MySQLdb
import constants

class MySQLConnection(object):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.conn = None
        self.cursor = None
        self.connect()
    
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
            self.execute("""INSERT INTO message_recipients (message_id, recipient_id)
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
    
    def get_lock(self, lock_name, timeout=0):
        lock = self.execute_and_fetchall("SELECT GET_LOCK(%(lock_name)s, %(timeout)s)", {
                                                'lock_name': lock_name,
                                                'timeout': timeout
                                             }, strip_pairs=True)
        return (lock and (lock[0] == 1))
    
    def is_free_lock(self, lock_name):
        lock = self.execute_and_fetchall("SELECT IS_FREE_LOCK(%(lock_name)s)", {
                                                'lock_name': lock_name
                                             }, strip_pairs=True)
        return (lock and (lock[0] == 1))
    
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
        logging.debug(query % data)
        if not self.conn or not self.cursor:
            logging.info("MySQL connection missing, attempting to reconnect and retry query")
            self.connect()
        try:
            self.cursor.execute(query, data)
        except MySQLdb.OperationalError, e:
            if e[0] > 2000:  # error codes at http://dev.mysql.com/doc/refman/5.5/en/error-handling.html
                logging.info('MySQL OperationalError %d "%s" for query, will retry: %s' % (e[0], e[1], query % data))
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
            #self.conn.autocommit(True)
            self.cursor = self.conn.cursor()
            logging.info("MySQL connection created")
        except MySQLdb.Error, e:
            logging.error('MySQL connection and/or cursor creation failed with %d: %s' % (e.args[0], e.args[1]))
            self.cleanup()
    
    def cleanup(self):
        if self.conn:
            self.conn.close()
    
