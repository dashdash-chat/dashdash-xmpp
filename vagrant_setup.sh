sudo apt-get install curl

curl http://www.erlang.org/download/otp_src_R13B04.tar.gz > /vagrant/otp_src_R13B04.tar.gz
gunzip -c otp_src_R13B04.tar.gz | tar xf -
cd otp_src_R13B04/
./configure 
make
sudo make install
cd ..

sudo apt-get install libexpat1-dev
sudo apt-get install git-core
git clone git@github.com:lehrblogger/ejabberd.git
cd ejabberd
git checkout -b 2.1.x origin/2.1.x
cd src
./configure
make
sudo make install
sudo ejabberdctl start

cd /vagrant
sudo apt-get install subversion
svn co https://svn.process-one.net/ejabberd-modules
cd /vagrant/ejabberd-modules/mod_admin_extra/trunk
./build.sh
cp /vagrant/ejabberd-modules/mod_admin_extra/trunk/ebin/mod_admin_extra.beam /lib/ejabberd/ebin/
cd /vagrant/ejabberd-modules/ejabberd_xmlrpc/trunk
./build.sh
cp /vagrant/ejabberd-modules/ejabberd_xmlrpc/trunk/ebin/ejabberd_xmlrpc.beam /lib/ejabberd/ebin/
cd /home/vagrant/
wget http://ejabberd.jabber.ru/files/contributions/xmlrpc-1.13-ipr2.tgz
tar -xzvf xmlrpc-1.13-ipr2.tgz
cd xmlrpc-1.13/src
make
cp /home/vagrant/xmlrpc-1.13/ebin/*.beam /lib/ejabberd/ebin/

sudo ejabberdctl restart

sudo apt-get install mysql-server
sudo apt-get install libmysqlclient-dev
mysql -u root -p < /vagrant/init_users.sql 

apt-get install python-setuptools # OR python-dev TRY BOTH
pip-2.6 install dnspython
pip-2.6 install mysql-python

git clone git@github.com:lehrblogger/SleekXMPP.git sleekxmpp
sudo python setup.py install