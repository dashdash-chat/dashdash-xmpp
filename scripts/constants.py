try:
   from config import env_vars as env_vars
except ImportError, e:
   from config_dev import env_vars as env_vars  
import shortuuid
shortuuid.set_alphabet('1234567890abcdefghijklmnopqrstuvwxyz')


server = env_vars.server
server_ip = '127.0.0.1'
component_port = env_vars.component_port
client_port = env_vars.client_port
xmlrpc_port = env_vars.xmlrpc_port

proxybot_script = '%sscripts/proxybot_client.py' % env_vars.repo_dir
proxybot_prefix = 'proxybot_'
proxybot_resource = 'python_client'
proxybot_password = env_vars.proxybot_password
hostbot_user = 'host'
hostbot_server = 'bot.%s' % server
hostbot_user_jid = '%s@%s' % (hostbot_user, hostbot_server)
hostbot_component_jid = '%s/python_component' % hostbot_server
hostbot_nick = 'Hostbot'
hostbot_secret = env_vars.hostbot_secret
default_user_password = env_vars.default_user_password

admin_users = env_vars.admin_users
admin_password = env_vars.admin_password

hostbot_xmlrpc_jid = '_hostbot'
hostbot_xmlrpc_password = env_vars.hostbot_xmlrpc_password
proxybot_xmlrpc_jid = '_proxybot'
proxybot_xmlrpc_password = env_vars.proxybot_xmlrpc_password
rosterbot_xmlrpc_jid = '_rosterbot'
rosterbot_xmlrpc_password = env_vars.rosterbot_xmlrpc_password

proxybot_group = 'contacts'
active_group = 'Vine Conversations'
idle_group = 'Vine Contacts'

db_name = 'chatidea'
hostbot_mysql_user = 'hostbot'
hostbot_mysql_password = env_vars.hostbot_mysql_password
proxybotinfo_mysql_user = 'proxybotinfo'
proxybotinfo_mysql_password = env_vars.proxybotinfo_mysql_password
userinfo_mysql_user = 'userinfo'
userinfo_mysql_password = env_vars.userinfo_mysql_password

proxybot_logfile = '%sproxybots.log' % env_vars.log_dir

class Stage:
    IDLE = 1
    ACTIVE = 2
    RETIRED = 3

class ProxybotCommand:
    activate = 'activate'
    retire = 'retire'
    add_participant = 'add_participant'
    remove_participant = 'remove_participant'

class HostbotCommand:
    delete_proxybot = 'delete_proxybot'
    bounce_proxybot = 'bounce_proxybot'
    participant_deleted = 'participant_deleted'
    add_observer = 'add_observer'
    remove_observer = 'remove_observer'
