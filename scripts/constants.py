from config import secrets as secrets
import shortuuid
shortuuid.set_alphabet('1234567890abcdefghijklmnopqrstuvwxyz')


server = 'ec2-107-21-87-153.compute-1.amazonaws.com'
server_ip = '127.0.0.1'
component_port = secrets.component_port
client_port = secrets.client_port
xmlrpc_port = secrets.xmlrpc_port

proxybot_script = '/vagrant/chatidea/scripts/proxybot_client.py'
proxybot_prefix = 'proxybot_'
proxybot_resource = 'python_client'
proxybot_password = secrets.proxybot_password
hostbot_user = 'host'
hostbot_server = 'bot.ec2-107-21-87-153.compute-1.amazonaws.com'
hostbot_user_jid = '%s@%s' % (hostbot_user, hostbot_server)
hostbot_component_jid = '%s/python_component' % hostbot_server
hostbot_nick = 'Hostbot'
hostbot_secret = secrets.hostbot_secret
default_user_password = secrets.default_user_password

admin_users = secrets.admin_users
admin_password = secrets.admin_password

hostbot_xmlrpc_jid = '_hostbot'
hostbot_xmlrpc_password = secrets.hostbot_xmlrpc_password
proxybot_xmlrpc_jid = '_proxybot'
proxybot_xmlrpc_password = secrets.proxybot_xmlrpc_password
rosterbot_xmlrpc_jid = '_rosterbot'
rosterbot_xmlrpc_password = secrets.rosterbot_xmlrpc_password

proxybot_group = 'contacts'
active_group = 'Chatidea Conversations'
idle_group = 'Chatidea Contacts'

db_name = 'chatidea'
hostbot_mysql_user = 'hostbot'
hostbot_mysql_password = secrets.hostbot_mysql_password
proxybotinfo_mysql_user = 'proxybotinfo'
proxybotinfo_mysql_password = secrets.proxybotinfo_mysql_password
userinfo_mysql_user = 'userinfo'
userinfo_mysql_password = secrets.userinfo_mysql_password

proxybot_logfile = '/var/log/chatidea/proxybots.log'

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
