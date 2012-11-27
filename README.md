Development Setup
----------
0. Set up the base VM
  * Follow the instructions in https://github.com/lehrblogger/vine-shared/#development-setup
0. Install Erlang
  * `sudo apt-get install build-essential`
  * `wget http://www.erlang.org/download/otp_src_R13B04.tar.gz`
  * `gunzip -c otp_src_R13B04.tar.gz | tar xf -`
  * `cd otp_src_R13B04/`
  * `./configure`
  * `make`
  * `sudo make install`
  * `cd ..`
0. Install ejabberd with the necessary modules
  * `sudo apt-get install libexpat1-dev`
  * `sudo apt-get install git-core subversion`
  * `cd ~`
  * `git clone git://github.com/lehrblogger/ejabberd.git`
  * `cd ejabberd`
  * `git checkout 2.1.x-stanza-restrictions` # which has my fixes!
  * `cd src`
  * `./configure`
  * `make`
  * `sudo make install`
  * `sudo ejabberdctl start`
  * `cd ../..`
  * `svn co https://svn.process-one.net/ejabberd-modules`
  * `cd ~/ejabberd-modules/mod_admin_extra/trunk`
  * `./build.sh`
  * `sudo cp ~/ejabberd-modules/mod_admin_extra/trunk/ebin/mod_admin_extra.beam /lib/ejabberd/ebin/`
  * `cd ~/ejabberd-modules/ejabberd_xmlrpc/trunk`
  * `./build.sh`
  * `sudo cp ~/ejabberd-modules/ejabberd_xmlrpc/trunk/ebin/ejabberd_xmlrpc.beam /lib/ejabberd/ebin/`
  * `cd ~`
  * `wget http://ejabberd.jabber.ru/files/contributions/xmlrpc-1.13-ipr2.tgz`
  * `tar -xzvf xmlrpc-1.13-ipr2.tgz`
  * `cd xmlrpc-1.13/src`
  * `make`
  * `sudo cp ~/xmlrpc-1.13/ebin/*.beam /lib/ejabberd/ebin/`
  * `sudo ejabberdctl restart`
0. Create the xmpp-env virtualenv 
  * `cd /vagrant`
  * `sudo virtualenv xmpp-env`  # TODO fix it so that you don't need to run this twice, maybe try https://github.com/pypa/virtualenv/issues/209#issuecomment-8646032
  * `sudo virtualenv xmpp-env`
  * `cd xmpp-env`
  * `source bin/activate`
  * `bin/pip-2.6 install dnspython`
  * `bin/pip install mysql-python`
  * `bin/pip install python-daemon` TODO: do I still need this?
  * `bin/pip install twilio`
  * `git clone git://github.com/lehrblogger/shortuuid.git`
  * `cd shortuuid`
  * `../bin/python setup.py install`
  * `cd ..`
  * `bin/pip install sleekxmpp`
  * `deactivate`
0. Download the vine-xmpp code (try cloning from local machine)
  * `cd /vagrant/xmpp-env`
  * `git clone git@github.com:lehrblogger/vine-xmpp.git xmpp`
  * `cd xmpp`
  * `sudo cp shared/ejabberd.cfg /etc/ejabberd && sudo ejabberdctl restart`
0. Create admin users and open ejabberd dashboard
  * `sudo ejabberdctl register admin1 dev.vine.im [password]`
  * `sudo ejabberdctl register admin2 dev.vine.im [password]`
  * `sudo ejabberdctl register _leaves dev.vine.im [leaf_xmlrpc_password]` ([from vine-shared](https://github.com/lehrblogger/vine-shared/blob/master/env_vars.py#L12))
  * `sudo ejabberdctl add_rosteritem admin1 dev.vine.im leaf leaves.dev.vine.im Leaf Admin both`
  * `sudo ejabberdctl add_rosteritem admin2 dev.vine.im leaf leaves.dev.vine.im Leaf Admin both`
  * Visit https://dev.vine.im:5281/admin in a browser and explore
  * (I tend to use https://dev.vine.im:5281/admin/server/dev.vine.im/users/ the most)
0. Run the leaf component (from the VM)
  * `cd /vagrant/xmpp-env`
  * `source bin/activate`
  * `cd xmpp`
  * `../bin/python ./leaf_component.py`
  * Connect as either admin user in your XMPP client of choice using 'admin1@dev.vine.im'
  * Send a message to the account 'leaf@leaves.dev.vine.im' (I could have made the username not matter, but some clients expect it.)
  * Experiment with the various commands to modify users and their relationships
  * Connect as the users you create using other XMPP clients, and try sending messages between them
  * Control-c to stop the XMPP component server
  * `cd ..`
  * `deactivate`
  * `cd ..`
  * `sudo ejabberdctl stop`

To Run the Leaf Component
------
  * `../bin/python leaf_component.py -i 1`
  * `nohup python leaf_component.py -i 1 >> /var/log/vine/leaf1.log &`