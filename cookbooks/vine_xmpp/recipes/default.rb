#
# Cookbook Name:: vine_xmpp
# Recipe:: default
#
# Copyright 2013, Vine.IM
#
# All rights reserved - Do Not Redistribute
#
env_data = data_bag_item("dev_data", "dev_data")

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
    notifies :restart, 'service[supervisor]', :delayed
  end
end
