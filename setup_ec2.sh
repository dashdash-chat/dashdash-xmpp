# for ejabberd machine
sudo yum update
sudo yum groupinstall "Development Tools"

cd ~/.ssh/
ssh-keygen -t rsa -C "lehrburger@gmail.com"
cat id_rsa.pub 
ssh -T git@github.com
git config --global user.name "Steven Lehrburger"
git config --global user.email "lehrburger@gmail.com"
cd ..

sudo yum install ncurses ncurses-devel  # not sure if both are necessary here
sudo yum install expat-devel
sudo yum install zlib-devel
sudo yum install openssl-devel

wget http://www.erlang.org/download/otp_src_R13B04.tar.gz
gunzip -c otp_src_R13B04.tar.gz | tar xf -
cd otp_src_R13B04/
./configure
make
sudo make install
cd ..

git clone git@github.com:lehrblogger/ejabberd.git
cd ejabberd
git checkout 2.1.x-stanza-restrictions
cd src
./configure
make
sudo make install
sudo ejabberdctl start
sudo ejabberdctl stop
cd ../..

svn co https://svn.process-one.net/ejabberd-modules
cd ejabberd-modules/mod_admin_extra/trunk
./build.sh
sudo cp ebin/mod_admin_extra.beam /lib/ejabberd/ebin/
cd ../../ejabberd_xmlrpc/trunk/
./build.sh
sudo cp ebin/ejabberd_xmlrpc.beam /lib/ejabberd/ebin/
cd ../../..

wget http://ejabberd.jabber.ru/files/contributions/xmlrpc-1.13-ipr2.tgz
tar -xzvf xmlrpc-1.13-ipr2.tgz
cd xmlrpc-1.13/src
make
cd ..
sudo cp ebin/*.beam /lib/ejabberd/ebin/
cd ..

git clone git@github.com:lehrblogger/chatidea-config
sudo cp chatidea-config/ejabberd.cfg /etc/ejabberd

sudo ejabberdctl start
sudo ejabberdctl register admin1 vine.im ADMIN_PASSWORD

wget http://downloads.sourceforge.net/pcre/pcre-8.10.tar.bz2
tar -jxf pcre-8.10.tar.bz2
cd pcre-8.10
./config
make
sudo make install
cd..
wget http://nginx.org/download/nginx-1.2.0.tar.gz
gunzip -c nginx-1.2.0.tar.gz | tar xf -
cd nginx-1.2.0
./configure
make
sudo make install
sudo vim /usr/local/nginx/html/index.html 
sudo /usr/local/nginx/sbin/nginx


# for bot machine
sudo yum update
sudo yum groupinstall "Development Tools"

cd ~/.ssh/
ssh-keygen -t rsa -C "lehrburger@gmail.com"
cat id_rsa.pub 
ssh -T git@github.com
git config --global user.name "Steven Lehrburger"
git config --global user.email "lehrburger@gmail.com"
cd ..

sudo yum install mysql mysql-devel mysql-server
sudo service mysqld start
#sudo mysqld_safe
mysql -u root
SET PASSWORD FOR 'root'@'localhost' = PASSWORD('MYSQL_ROOT_PASSWORD');
SET PASSWORD FOR 'root'@'127.0.0.1' = PASSWORD('MYSQL_ROOT_PASSWORD');
cntrl-d

sudo yum install python-devel
sudo easy_install dnspython
sudo easy_install mysql-python
sudo easy_install python-daemon

git clone git@github.com:lehrblogger/shortuuid.git
cd shortuuid
sudo python setup.py install
cd ..

git clone git://github.com/fritzy/SleekXMPP.git sleekxmpp
cd sleekxmpp
git checkout master
sudo python setup.py install
cd ..

git clone git@github.com:lehrblogger/chatidea chatidea
cd chatidea/
git submodule init
git submodule update
cd ..

sudo mkdir /var/log/vine
sudo rm /var/log/vine/leaf1.log
sudo touch /var/log/vine/leaf1.log
sudo chown ec2-user /var/log/vine/leaf1.log
sudo rm /var/log/vine/misc.log
sudo touch /var/log/vine/misc.log
sudo chown ec2-user /var/log/vine/misc.log

mysql -u root -pMYSQL_ROOT_PASSWORD < ~/chatidea/scripts/config/init_tables.sql

nohup python ~/chatidea/scripts/leaf_component.py -i 1 >> /var/log/chatidea/leaf1.log &
