Vagrant::Config.run do |config|
  config.vm.box = "lucid32"
  
  config.vm.forward_port 80, 4567
  config.vm.forward_port 5222, 5222
  config.vm.forward_port 5237, 5237
  config.vm.forward_port 5269, 5269
  config.vm.forward_port 5280, 5280
  
  # Enable and configure the chef solo provisioner
  config.vm.provision :chef_solo do |chef|
    # We're going to download our cookbooks from the web
    chef.recipe_url = "http://files.vagrantup.com/getting_started/cookbooks.tar.gz"
  
    # Tell chef what recipe to run. In this case, the `vagrant_main` recipe
    # does all the magic.
    chef.add_recipe("vagrant_main")
  end
end
