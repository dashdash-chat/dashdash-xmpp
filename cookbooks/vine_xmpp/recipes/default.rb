#
# Cookbook Name:: vine_xmpp
# Recipe:: default
#
# Copyright 2013, Vine.IM
#
# All rights reserved - Do Not Redistribute
#
env_data = data_bag_item("dev_data", "dev_data")

# Prepare the virtualenv for the vine-xmpp repo
python_virtualenv "#{node['vine_xmpp']['xmpp_env_dir']}" do
  owner env_data["server"]["user"]
  group env_data["server"]["group"]
  action :create
end
["mysql-python", "dnspython", #'python-daemon' # TODO: do I still need this?
 "twilio", "shortuuid", "sleekxmpp",
].each do |library|
  python_pip "#{library}" do
    virtualenv node['vine_xmpp']['xmpp_env_dir']
    action :install
  end
end
bash "install gevent 1.0rc2" do  #since pypi only has v0.13
  cwd node['vine_xmpp']['xmpp_env_dir']
  code <<-EOH
    wget https://github.com/downloads/SiteSupport/gevent/gevent-1.0rc2.tar.gz
    tar xvzf gevent-1.0rc2.tar.gz
    cd gevent-1.0rc2/
    #{node['vine_xmpp']['xmpp_env_dir']}/bin/python setup.py install
  EOH
end

# Check out the application files and render the python constants template
deploy_wrapper 'xmpp' do
    ssh_wrapper_dir node['dirs']['ssl']
    ssh_key_dir node['dirs']['ssl']
    ssh_key_data env_data['server']['xmpp_deploy_key']
    sloppy true
end
git "#{node['vine_xmpp']['xmpp_repo_dir']}" do
    repository "git@github.com:lehrblogger/vine-xmpp.git"
    branch "leaves-edges"
    destination "#{node['vine_xmpp']['xmpp_repo_dir']}"
    ssh_wrapper "#{node['dirs']['ssl']}/xmpp_deploy_wrapper.sh"
    action :sync
end
template "constants.py" do
  path "#{node['vine_xmpp']['xmpp_repo_dir']}/constants.py"
  source "constants.py.erb"
  owner env_data["server"]["user"]
  group env_data["server"]["group"]
  mode 0644
  variables :env_data => env_data
end

# Render the .conf file so that supervisor can manage these processes
["leaf"
].each do |program_name|
  template "supervisord_#{program_name}.conf" do
    path "/etc/supervisor/conf.d/supervisord_#{program_name}.conf"
    source "supervisord_#{program_name}.conf.erb"
    owner "root"
    group "root"
    mode 0644
    variables ({
      :logs_dir => "#{node['dirs']['log']}/supervisord",
      :env_data => env_data
    })
    notifies :start, 'service[supervisor]', :delayed
  end
end
