default['vine_xmpp']['xmpp_env_dir']  = "#{Chef::Environment.load(node.chef_environment).default_attributes['dirs']['source']}/xmpp-env"
default['vine_xmpp']['xmpp_repo_dir'] = "#{node['vine_xmpp']['xmpp_env_dir']}/xmpp"
