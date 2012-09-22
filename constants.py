from shared import env_vars
import shortuuid
shortuuid.set_alphabet('1234567890abcdefghijklmnopqrstuvwxyz')

server = env_vars.server
server_ip = env_vars.server_ip

component_port = env_vars.component_port
leaves_domain = '%s.%s' % ('leaves', server)
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
roster_group = env_vars.roster_group

admin_jids = env_vars.admin_jids
graph_xmpp_jid = '%s@%s' % ('_graph', server)

client_port = env_vars.client_port
default_user_password = env_vars.default_user_password

# global variables to save the hassle of passing around the values
class g(object):
    db = None 
    ectl = None
