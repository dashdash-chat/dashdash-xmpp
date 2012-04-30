#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import MySQLdb
import sleekxmpp
import logging
import getpass
from optparse import OptionParser
import sleekxmpp
from sleekxmpp.exceptions import IqError, IqTimeout

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class RegistrarBot(sleekxmpp.ClientXMPP):

    def __init__(self, jid, password):
        sleekxmpp.ClientXMPP.__init__(self, jid, password)
        self.database = None
        self.cursor = None
        try:
            self.database = MySQLdb.connect('localhost', 'python-helper', 'vap4yirck8irg4od4lo6', 'chatidea')
            self.cursor = self.database.cursor()
            self.cursor.execute("SELECT username FROM users WHERE has_jid = 0")
            self.usernames = [username[0] for username in self.cursor.fetchall()]
        except MySQLdb.Error, e:
            print "Error %d: %s" % (e.args[0], e.args[1])
            sys.exit(1)
            if self.database:
                self.database.close()
        self.add_event_handler("session_start", self.start, threaded=True)

    def start(self, event):
        self.send_presence()
        self.get_roster()
        for username in self.usernames:
            print username
            iq = self.Iq()
            iq['type'] = 'set'
            iq['to'] = self.boundjid.domain
            iq['register']['username'] = username
            iq['register']['password'] = 'password' #TODO figure out user password stuff later
            try:
                iq.send()
                self.cursor.execute("UPDATE users SET has_jid = 1 WHERE username = %(username)s", {'username': username})
                logging.info("Account created for %s!" % username)
            except IqError as e:
                logging.error("Could not register account for %s: %s" % (username, e.iq['error']['text']))
            except IqTimeout:
                logging.error("No response from server.")
            except MySQLdb.Error, e:
                print "Error %d: %s" % (e.args[0], e.args[1])
        if self.database:
            self.database.close()
        self.disconnect()

if __name__ == '__main__':
    optp = OptionParser()
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-d', '--debug', help='set logging to DEBUG',
                    action='store_const', dest='loglevel',
                    const=logging.DEBUG, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)
    optp.add_option("-j", "--jid", dest="jid",
                    help="JID to use")
    optp.add_option("-p", "--password", dest="password",
                    help="password to use")
    opts, args = optp.parse_args()

    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')

    if opts.jid is None:
        opts.jid = raw_input("Username: ")
    if opts.password is None:
        opts.password = getpass.getpass("Password: ")

    xmpp = RegistrarBot(opts.jid, opts.password)
    xmpp.register_plugin('xep_0030') # Service Discovery
    xmpp.register_plugin('xep_0004') # Data forms
    xmpp.register_plugin('xep_0066') # Out-of-band Data
    xmpp.register_plugin('xep_0077') # In-band Registration

    if xmpp.connect(('127.0.0.1', 5222)):
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")
