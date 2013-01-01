default['vine_xmpp']['xmpp_venv_dir']     = "#{Chef::Environment.load(node.chef_environment).default_attributes['dirs']['source_dir']}/xmpp-env"
default['vine_xmpp']['xmpp_repo_dir']     = "#{node['vine_xmpp']['xmpp_venv_dir']}/xmpp"
