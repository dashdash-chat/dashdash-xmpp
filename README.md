chatidea
========

useful commands:
----------------

    erlc -I /lib/ejabberd/include -pa /vagrant/ejabberd/src -o /lib/ejabberd/ebin /vagrant/ejabberd/src/mod_register.erl
    cp /vagrant/chatidea/ejabberd.cfg /etc/ejabberd && ejabberdctl restart

    sudo tail -f /var/log/ejabberd/ejabberd.log

    sudo kill -15 `ps faux | grep proxybot | awk '{print $2}'`
    
    sudo ejabberdctl restart

    vim /etc/ejabberd/ejabberd.cfg 
    tail -f /var/log/ejabberd/ejabberd.log

    mysql -u root -p < /vagrant/init_users.sql
    mysql -u root -pos6juc8ik4if6jiev3co

    python /vagrant/chatidea/hostbot_component.py -v

    python /vagrant/register_account.py -v -u 'temp0' -p 'FgT5bk3' 

    python /vagrant/sleekxmpp/examples/register_account_for_other.py -v -j 'admin1@localhost' -p 'FgT5bk3' -n 'temp0' -w 'FgT5bk3'
    
    python /vagrant/chatidea/proxybot_client.py -u proxybot262522004685566022765104720483704520632 -s localhost -1 alice -2 dormouse

    ejabberdctl unregister proxybot12345 localhost && ejabberdctl register proxybot12345 localhost ow4coirm5oc5coc9folv && python /vagrant/chatidea/proxybot_client.py -u proxybot12345 -s localhost -1 alice -2 dormouse -v

passwords:
----------
    admin password: FgT5bk3
    sql root password: os6juc8ik4if6jiev3co
    sql python-helper password: vap4yirck8irg4od4lo6
    hostbot component secret and host@localhost password: yeij9bik9fard3ij4bai
    proxybot password: ow4coirm5oc5coc9folv

TODO:
    double-check ejabberd_xmlrpc access restrictions, think about encryption