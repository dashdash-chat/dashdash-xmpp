#!/usr/bin/env python
# -*- coding: utf-8 -*-\
from datetime import datetime, timedelta
import logging
from MySQLdb import IntegrityError, OperationalError, ProgrammingError
from optparse import OptionParser
import constants
from constants import g
from ejabberdctl import EjabberdCTL
from mysql_conn import MySQLManager

class DatabaseStats(object):
    def __init__(self, start, end, other_users_only):
        self.excluded_users = [1, 3, 4, 6, 10, 19, 24, 34, 35, 40, 47, 57, 58, 60, 62, 66, 68, 81, 82, 115, 173, 207]
        if other_users_only:
            self.excluded_users.append(16)
        self.start = start
        self.end = end
    
    def log_stats(self):
        g.logger.info('    %d invites used' % self.invites_used())
        g.logger.info('    %d users who sent a message' % self.users_who_sent_message())
        g.logger.info('    %d messages sent' % self.messages_sent())
        g.logger.info('    %d group messages sent' % self.group_messages_sent())
    
    def invites_used(self):
        invite_count = g.db.execute_and_fetchall("""SELECT COUNT(*) FROM invites, invitees 
                                                    WHERE invites.id = invitees.invite_id
                                                    AND invitees.used < %(end)s
                                                    AND invitees.used >= %(start)s
                                                    AND invitees.invitee_id NOT IN %(excluded_users)s
                                                    AND invites.sender NOT IN %(excluded_users)s
                                                  """, {
                                                     'start': self.start,
                                                     'end': self.end,
                                                     'excluded_users': self.excluded_users
                                                  }, strip_pairs=True)
        if invite_count and len(invite_count) > 0:
            return invite_count[0]
        return 0
    
    def users_who_sent_message(self):
        users = g.db.execute_and_fetchall("""SELECT messages.sender_id, users.name FROM messages, users
                                             WHERE messages.sent_on < %(end)s
                                             AND messages.sent_on >= %(start)s
                                             AND messages.sender_id = users.id
                                             AND messages.sender_id NOT IN %(excluded_users)s
                                             AND (SELECT COUNT(*) FROM recipients 
                                                  WHERE recipients.message_id = messages.id
                                                  AND recipients.recipient_id NOT IN %(excluded_users)s) > 0
                                             GROUP BY messages.sender_id;
                                          """, {
                                             'start': self.start,
                                             'end': self.end,
                                             'excluded_users': self.excluded_users
                                          })
        return len(users)
    
    def messages_sent(self):
        messages_sent = g.db.execute_and_fetchall("""SELECT COUNT(*) FROM messages
                                                     WHERE messages.sent_on < %(end)s
                                                     AND messages.sent_on >= %(start)s
                                                     AND messages.sender_id NOT IN %(excluded_users)s
                                                     AND (SELECT COUNT(*) FROM recipients 
                                                          WHERE recipients.message_id = messages.id
                                                          AND recipients.recipient_id NOT IN %(excluded_users)s) > 0;
                                                  """, {
                                                     'start': self.start,
                                                     'end': self.end,
                                                     'excluded_users': self.excluded_users
                                                  }, strip_pairs=True)
        if messages_sent and len(messages_sent) > 0:
            return messages_sent[0]
        return 0
    
    def group_messages_sent(self):
            group_messages_sent = g.db.execute_and_fetchall("""SELECT COUNT(*) FROM messages
                                                               WHERE messages.sent_on < %(end)s
                                                               AND messages.sent_on >= %(start)s
                                                               AND messages.sender_id NOT IN %(excluded_users)s
                                                               AND (SELECT COUNT(*) FROM recipients 
                                                                    WHERE recipients.message_id = messages.id
                                                                    AND recipients.recipient_ID NOT IN %(excluded_users)s) > 1;
                                                            """, {
                                                               'start': self.start,
                                                               'end': self.end,
                                                               'excluded_users': self.excluded_users
                                                            }, strip_pairs=True)
            if group_messages_sent and len(group_messages_sent) > 0:
                return group_messages_sent[0]
            return 0

class EjabberdStats(object):
    g.ectl = EjabberdCTL(constants.leaves_xmlrpc_user, constants.leaves_xmlrpc_password)
    
    def __init__(self, num_days):
        self.num_days = num_days
    
    # sudo ejabberdctl num_active_users dashdash.com 30

if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to DEBUG',
                    action='store_const', dest='loglevel',
                    const=logging.DEBUG, default=logging.INFO)
    optp.add_option('-n', '--num_intervals', help='the number of intervals to query back',
                    dest='num_intervals', default=5)
    optp.add_option('-s', '--interval_size', help='the number of days in each interval',
                    dest='interval_size', default=7)
    optp.add_option('-a', '--all_time', help='run queries since beginning of project',
                    action='store_const', dest='all_time',
                    const=True, default=False)
    optp.add_option('-o', '--other_users_only', help='exclude lehrblogger\'s activity',
                    action='store_const', dest='other_users_only',
                    const=True, default=False)
    opts, args = optp.parse_args()
    num_intervals = int(opts.num_intervals)
    interval_size = int(opts.interval_size)
    logging.basicConfig(format=constants.log_format, level=opts.loglevel)
    g.loglevel = opts.loglevel
    g.use_new_logger('stats')
    g.db = MySQLManager(constants.leaves_mysql_user, constants.leaves_mysql_password)
    now = datetime.now()
    for end in range(0, num_intervals * interval_size, interval_size):
        start = end + interval_size
        stats = DatabaseStats(now - timedelta(days=start), now - timedelta(days=end), opts.other_users_only)
        g.logger.info('Between %d and %d days ago:' % (end, start))
        stats.log_stats()
    if opts.all_time:
        g.logger.info('All time:')
        stats = DatabaseStats(now - timedelta(days=1000), now, opts.other_users_only)
        stats.log_stats()
    logging.shutdown()
