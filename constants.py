from shared import env_vars
import shortuuid
shortuuid.set_alphabet('1234567890abcdefghijklmnopqrstuvwxyz')

domain = env_vars.domain
server_ip = env_vars.server_ip
xmlrpc_server = env_vars.xmlrpc_server

component_port = env_vars.component_port
leaves_domain = '%s.%s' % ('leaves', domain)
leaves_jid_user = 'leaf'
leaves_jid = '%s@%s' % (leaves_jid_user, leaves_domain)
leaves_secret = env_vars.leaves_secret
max_leaves = 10

xmlrpc_port = env_vars.xmlrpc_port
leaves_xmlrpc_user  = '_leaves'
leaves_xmlrpc_password = env_vars.leaves_xmlrpc_password

leaves_mysql_user = 'leaves'
leaves_mysql_lock_name = 'leaf'
leaves_mysql_password = env_vars.leaves_mysql_password
db_host = env_vars.db_host
db_name = 'vine'

vinebot_prefix = 'vinebot_'

admin_jids = env_vars.admin_jids
graph_xmpp_jid = '%s@%s' % ('_graph', domain)

watched_usernames = env_vars.watched_usernames
twilio_account_sid = 'AC94ebb7a389884563bb59bcc318c6cfc8'
twilio_auth_token = env_vars.twilio_auth_token
twilio_from_number = '+17542276773'
twilio_to_numbers = env_vars.twilio_to_numbers

client_port = env_vars.client_port
default_user_password = env_vars.default_user_password

# global variables to save the hassle of passing around the values
class g(object):
    db = None 
    ectl = None
