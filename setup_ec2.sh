cd .ssh/
ls
ssh-keygen -t rsa -C "lehrburger@gmail.com"
cat id_rsa.pub 
ssh -T git@github.com
git config --global user.name "Steven Lehrburger"
git config --global user.email "lehrburger@gmail.com"
cd ..

sudo yum update
sudo yum groupinstall "Development Tools"
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
sudo ejabberdctl start
sudo ejabberdctl stop

sudo yum install mysql-server
sudo yum install mysql
sudo yum install mysql-devel
sudo service mysqld start
sudo mysqld_safe
mysql -u root
SET PASSWORD FOR 'root'@'localhost' = PASSWORD('MYSQL_ROOT_PASSWORD');
SET PASSWORD FOR 'root'@'127.0.0.1' = PASSWORD('MYSQL_ROOT_PASSWORD');
cntrl-d

# maybe sudo yum install python-devel
sudo easy_install dnspython
sudo easy_install mysql-python
sudo easy_install python-daemon

git clone git@github.com:lehrblogger/shortuuid.git
cd shortuuid
sudo python setup.py install

git clone git@github.com:lehrblogger/SleekXMPP.git sleekxmpp
cd sleekxmpp
git checkout develop
sudo python setup.py install

git clone git@github.com:lehrblogger/chatidea chatidea
cd chatidea/
git submodule init
git submodule update
sudo cp scripts/config/ejabberd.cfg /etc/ejabberd
cd ..

sudo ejabberdctl register admin1 ec2-107-21-87-153.compute-1.amazonaws.com ADMIN_PASSWORD

sudo ejabberdctl start

sudo mkdir /var/log/chatidea
sudo touch /var/log/chatidea/proxybots.log
sudo chown ec2-user /var/log/chatidea/proxybots.log
sudo touch /var/log/chatidea/hostbot.log
sudo chown ec2-user /var/log/chatidea/hostbot.log
sudo touch /var/log/chatidea/misc.log
sudo chown ec2-user /var/log/chatidea/misc.log
sudo: no tty present and no askpass program specified
python chatidea/scripts/hostbot_component.py

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
make
sudo make install
sudo vim /usr/local/nginx/html/index.html 
/usr/local/nginx/sbin/nginx -s start
