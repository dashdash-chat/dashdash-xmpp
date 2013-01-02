maintainer       "Vine.IM"
maintainer_email "lehrburger@gmail.com"
license          "All rights reserved"
description      "Installs/Configures vine_xmpp"
long_description IO.read(File.join(File.dirname(__FILE__), 'README.md'))
version          "0.1.0"

#NOTE using specific versions so that I can stay aware of changes in upstream cookbooks
depends "vine_shared", "~> 0.1.0"
