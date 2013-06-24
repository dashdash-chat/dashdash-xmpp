#!/usr/bin/env python
# -*- coding: utf-8 -*-\
from datetime import datetime, timedelta
import logging
from mailsnake import MailSnake
from mailsnake.exceptions import *
from MySQLdb import IntegrityError, OperationalError, ProgrammingError
from optparse import OptionParser
import constants
from constants import g
from ejabberdctl import EjabberdCTL
from mysql_conn import MySQLManager
import user as u

def fetch_users():
    user_ids = g.db.execute_and_fetchall("""SELECT id 
                                            FROM users, invitees
                                            WHERE users.name NOT IN %(excluded_users)s
                                            AND users.id = invitees.invitee_id
                                            AND invitees.invite_id != %(test_user_invite)s
                                            AND email IS NOT NULL
                                         """, {
                                            'excluded_users': constants.protected_users,
                                            'test_user_invite': 433 # for code 'lookingglass'
                                         }, strip_pairs=True)
    return frozenset([u.FetchedUser(dbid=user_id) for user_id in user_ids])

def subscribe_or_update(user):
    try:
        active = g.ectl.get_last(user.name)
        try:
            ms.listSubscribe(
                id = 'b2f9b04668',
                email_address = user.email,
                merge_vars = {
                       'UNAME': user.name,
                       'LACTIVE': active,
                       },
                update_existing = True,
                double_optin = False,
            )
            g.logger.warning('Successfully subscribed %s' % user)  # Warning here, since there are infos in requests.packages.urllib3.connectionpool
        except ListAlreadySubscribedException:
            g.logger.warning('User %s was already subscribed.' % (user, e))
    except Exception, e:
        g.logger.warning('Exception for user %s: %s' % (user, e))

if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.WARNING)
    optp.add_option('-v', '--verbose', help='set logging to DEBUG',
                    action='store_const', dest='loglevel',
                    const=logging.DEBUG, default=logging.WARNING)
    opts, args = optp.parse_args()
    logging.basicConfig(format=constants.log_format, level=opts.loglevel)
    g.loglevel = opts.loglevel
    g.use_new_logger('emails')
    g.db = MySQLManager(constants.leaves_mysql_user, constants.leaves_mysql_password)
    g.ectl = EjabberdCTL(constants.leaves_xmlrpc_user, constants.leaves_xmlrpc_password)
    ms = MailSnake(constants.mailchimp_api_key)
    try:
        ms.ping()
        users = fetch_users()
        for user in users:
            subscribe_or_update(user)
    except InvalidApiKeyException:
        g.logger.error('Invalid Mailchimp API Key, exiting.')
    logging.shutdown()
