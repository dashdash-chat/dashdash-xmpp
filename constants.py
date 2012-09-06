from shared import env_vars
import shortuuid
shortuuid.set_alphabet('1234567890abcdefghijklmnopqrstuvwxyz')

server = env_vars.server
server_ip = env_vars.server_ip

component_port = env_vars.component_port
leaf_name = "leaves"
leaf_secret = env_vars.leaf_secret
max_leaves = 10

xmlrpc_port = env_vars.xmlrpc_port
leaves_xmlrpc_user  = '_leaves'
leaves_xmlrpc_password = env_vars.leaf_xmlrpc_password

leaf_mysql_lock_name = 'leaf'
leaf_mysql_password = env_vars.leaf_mysql_password
db_host = env_vars.db_host
db_name = 'vine'

vinebot_prefix = 'vinebot_'
roster_group = env_vars.roster_group

admin_users = env_vars.admin_users
graph_xmpp_user = '%s@%s' % ('_graph', server)

client_port = env_vars.client_port
default_user_password = env_vars.default_user_password

# global variables to save the hassle of passing around the values
class g(object):
    db = None 
    ectl = None


# leaf_name = "leaf"
# leaf_xmlrpc_jid_prefix = '_leaf``'