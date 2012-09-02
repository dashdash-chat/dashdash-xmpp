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
            self.cursor = self.db.cursor()
            logging.info("MySQL connection created")
        except MySQLdb.Error, e:
            logging.error('MySQL connection and/or cursor creation failed with %d: %s' % (e.args[0], e.args[1]))
            self.cleanup()
    
    def cleanup(self):
        if self.conn:
            self.conn.close()
    
