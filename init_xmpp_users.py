import sys
import _mysql
import sleekxmpp

conn = None
try:
    conn = _mysql.connect('localhost', 'python-helper', 'vap4yirck8irg4od4lo6', 'chatidea')
    conn.query("SELECT VERSION()")
    result = conn.use_result()
    print "MySQL version: %s" % result.fetch_row()[0]
except _mysql.Error, e:
    print "Error %d: %s" % (e.args[0], e.args[1])
    sys.exit(1)
finally:
    if conn:
        conn.close()

# "sleek-registrar" user to register new accounts