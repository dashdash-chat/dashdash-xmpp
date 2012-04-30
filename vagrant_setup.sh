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

sudo apt-get install mysql-server
sudo apt-get install libmysqlclient-dev
mysql -u root -p < /vagrant/init_users.sql 

apt-get install python-setuptools # OR python-dev TRY BOTH
pip-2.6 install dnspython
pip-2.6 install mysql-python

git clone git@github.com:lehrblogger/SleekXMPP.git sleekxmpp
sudo python setup.py install