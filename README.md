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
  * `cd /vagrant`
  * `git clone git://github.com/lehrblogger/ejabberd.git`
  * `cd ejabberd`
  * `git checkout -b tag-v2.1.11 v2.1.11`
  * `cd src`
  * `./configure`
  * `make`
  * `sudo make install`
  * `sudo ejabberdctl start`
  * `cd ../..`
  * `svn co https://svn.process-one.net/ejabberd-modules`
  * `cd /vagrant/ejabberd-modules/mod_admin_extra/trunk`
  * `./build.sh`
  * `sudo cp /vagrant/ejabberd-modules/mod_admin_extra/trunk/ebin/mod_admin_extra.beam /lib/ejabberd/ebin/`
  * `cd /vagrant/ejabberd-modules/ejabberd_xmlrpc/trunk`
  * `./build.sh`
  * `sudo cp /vagrant/ejabberd-modules/ejabberd_xmlrpc/trunk/ebin/ejabberd_xmlrpc.beam /lib/ejabberd/ebin/`
  * `cd ~`
  * `wget http://ejabberd.jabber.ru/files/contributions/xmlrpc-1.13-ipr2.tgz`
  * `tar -xzvf xmlrpc-1.13-ipr2.tgz`
  * `cd xmlrpc-1.13/src`
  * `make`
  * `sudo cp /home/vagrant/xmlrpc-1.13/ebin/*.beam /lib/ejabberd/ebin/`
  * `sudo ejabberdctl restart`
0. Create the xmpp-env virtualenv 
  * `cd /vagrant`
  * `sudo virtualenv xmpp-env`  # TODO fix it so that you don't need to run this twice
  * `sudo virtualenv xmpp-env`
  * `cd xmpp-env`
  * `source bin/activate`
  * `bin/pip-2.6 install dnspython`
  * `bin/pip install mysql-python`
  * `bin/pip install python-daemon`
  * `git clone git://github.com/lehrblogger/shortuuid.git`
  * `cd shortuuid`
  * `../bin/python setup.py install`
  * `cd ..`
  * `bin/pip install sleekxmpp`
0. Download the vine-xmpp code (easier from your local machine) and run the leaf component (from the VM)
  * `cd xmpp-env`
  * `git clone git@github.com:lehrblogger/vine-xmpp.git xmpp`
  * `cd xmpp`
  * `../bin/python ./scripts/leaf_component.py -i 1`
  * Test Vine using local dev accounts in standard XMPP clients
  * Control-c to stop the XMPP component server
  * `cd ..`
  * `deactivate`
  * `cd ..`
  * `sudo ejabberdctl stop`

To Run the Leaf Component
------
  * `../bin/python ./scripts/leaf_component.py -i 1`
  * `nohup python ./scripts/leaf_component.py -i 1 >> /var/log/vine/leaf1.log &`