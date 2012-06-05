chatidea
========

useful commands:
----------------

    erlc -I /lib/ejabberd/include -pa /vagrant/ejabberd/src -o /lib/ejabberd/ebin /vagrant/ejabberd/src/mod_register.erl
    
    cp /vagrant/chatidea/scripts/config/ejabberd.cfg /etc/ejabberd && ejabberdctl restart

    sudo tail -f /var/log/ejabberd/ejabberd.log
    tail -f /var/log/chatidea/proxybots.log

    sudo kill -15 `ps faux | grep proxybot | grep python | awk '{print $2}'`
    
    sudo ejabberdctl restart

    vim /etc/ejabberd/ejabberd.cfg 
    tail -f /var/log/ejabberd/ejabberd.log

    mysql -u root -pos6juc8ik4if6jiev3co < /vagrant/chatidea/scripts/config/init_tables.sql
    mysql -u root -pos6juc8ik4if6jiev3co --database chatidea

    nohup python ~/chatidea/scripts/hostbot_component.py >> /var/log/chatidea/hostbot.log &

    python /vagrant/chatidea/scripts/hostbot_component.py -v

    python /vagrant/sleekxmpp/examples/register_account_for_other.py -v -j 'admin1@vine.im' -p 'FgT5bk3' -n 'temp0' -w 'FgT5bk3'
  
    SELECT * FROM users; SELECT * FROM proxybots WHERE stage != 'retired'; SELECT proxybot_participants.* FROM proxybots, proxybot_participants WHERE proxybots.stage != 'retired' and proxybots.id = proxybot_participants.proxybot_id;


    PROXYBOT='proxybot_12345' && ejabberdctl unregister $PROXYBOT vine.im && ejabberdctl register $PROXYBOT vine.im ow4coirm5oc5coc9folv && python /vagrant/chatidea/scripts/proxybot_client.py -u $PROXYBOT -1 alice -2 dormouse
