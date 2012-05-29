import shortuuid
shortuuid.set_alphabet('1234567890abcdefghijklmnopqrstuvwxyz')

daemons = '--daemon'
# daemons = '--verbose'
# daemons = ''

server = 'localhost'
server_ip = '127.0.0.1'
component_port = 5237
client_port = 5222
xmlrpc_port = 4560

proxybot_prefix = 'proxybot_'
proxybot_resource = 'python_client'
proxybot_password = 'ow4coirm5oc5coc9folv'
hostbot_user = 'host'
hostbot_server = 'bot.localhost'
hostbot_user_jid = '%s@%s' % (hostbot_user, hostbot_server)
hostbot_component_jid = '%s/python_component' % hostbot_server
hostbot_nick = 'Hostbot'
hostbot_secret = 'is3joic8vorn8uf4ge4o'
hostbot_port = 5237
default_user_password = 'password'

admin_users = ['admin1@localhost']
admin_password = 'FgT5bk3'

hostbot_xmlrpc_jid = '_hostbot'
hostbot_xmlrpc_password = 'wraf7marj7og4e7ob4je'
proxybot_xmlrpc_jid = '_proxybot'
proxybot_xmlrpc_password = 'floif8ef7ceut5yek4da'
rosterbot_xmlrpc_jid = '_rosterbot'
rosterbot_xmlrpc_password = 'nal4rey2hun5ewv4ud6p'

proxybot_group = 'contacts'
active_group = 'Chatidea Conversations'
idle_group = 'Chatidea Contacts'

db_name = 'chatidea'
hostbot_mysql_user = 'hostbot'
hostbot_mysql_password = 'ish9gen8ob8hap7ac9hy'
proxybotinfo_mysql_user = 'proxybotinfo'
proxybotinfo_mysql_password = 'oin9yef4aim9nott8if9'
userinfo_mysql_user = 'userinfo'
userinfo_mysql_password = 'me6oth8ig3tot7as2ash'

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
