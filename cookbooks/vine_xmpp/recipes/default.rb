#
# Cookbook Name:: vine_xmpp
# Recipe:: default
#
# Copyright 2013, Vine.IM
#
# All rights reserved - Do Not Redistribute
#

xmpp_env_dir  = "#{node['dirs']['source']}/xmpp-env"
xmpp_repo_dir = "#{xmpp_env_dir}/xmpp"

# Prepare the virtualenv for the vine-xmpp repo
python_virtualenv xmpp_env_dir do
  owner node.run_state['config']['user']
  group node.run_state['config']['group']
  action :create
end
['mysql-python', 'dnspython',
 'twilio', 'shortuuid', 'sleekxmpp',
].each do |library|
  python_pip library do
    virtualenv xmpp_env_dir
    action :install
  end
end

# Check out the application files and render the python constants template
deploy_wrapper 'xmpp' do
    ssh_wrapper_dir node['dirs']['ssl']
    ssh_key_dir node['dirs']['ssl']
    ssh_key_data Chef::EncryptedDataBagItem.load(node.chef_environment, "vine_xmpp")['deploy_key']
    sloppy true
end
git xmpp_repo_dir do
    repository "git@github.com:lehrblogger/vine-xmpp.git"
    branch "leaves-edges"
    destination xmpp_repo_dir
    ssh_wrapper "#{node['dirs']['ssl']}/xmpp_deploy_wrapper.sh"
    action :sync
end
template 'constants.py' do
  path "#{xmpp_repo_dir}/constants.py"
  source "constants.py.erb"
  owner node.run_state['config']['user']
  group node.run_state['config']['group']
  mode 0644
end

# Create the supervisor program
supervisor_service "leaves" do
  command "#{xmpp_env_dir}/bin/python #{xmpp_repo_dir}/leaf_component.py"
  environment :PYTHON_EGG_CACHE => "#{xmpp_env_dir}/.python-eggs"
  directory xmpp_repo_dir
  user node.run_state['config']['user']
  process_name "leaf_%(process_num)02d"
  stdout_logfile "#{node['supervisor']['log_dir']}/leaves.log"
  stderr_logfile "#{node['supervisor']['log_dir']}/leaves.log"
  numprocs node.run_state['config']['leaves']['max_leaves']
  stopsignal "INT"  # this is the only one that properly logs "Done" from the leaf (I haven't checked which do presence cleanup)
  autostart false
  autorestart false
  priority 2
  startsecs 10
  stopwaitsecs 300
  action :enable
end

["cd #{xmpp_env_dir} && source bin/activate && cd #{xmpp_repo_dir}"
].each do |command|
  ruby_block "append line to history" do
    block do
      file = Chef::Util::FileEdit.new("/home/#{node.run_state['config']['user']}/.bash_history")
      file.insert_line_if_no_match("/[^\s\S]/", command)  # regex never matches anything
      file.write_file
    end
  end
end
