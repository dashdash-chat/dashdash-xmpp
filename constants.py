
server = 'localhost'
xmlrpc_port = 4560

proxybot_prefix = 'proxybot_'
proxybot_resource = 'python_client'
proxybot_password = 'ow4coirm5oc5coc9folv'
hostbot_server = 'bot.localhost'
hostbot_jid = '%s/python_component' % hostbot_server
hostbot_nick = 'Hostbot'
hostbot_secret = 'is3joic8vorn8uf4ge4o'
hostbot_port = 5237
default_user_password = 'password'

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
userinfo_mysql_user = 'userinfo'
userinfo_mysql_password = 'me6oth8ig3tot7as2ash'

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
    participant_deleted = 'participant_deleted'
    add_observer = 'add_observer'
    remove_observer = 'remove_observer'
