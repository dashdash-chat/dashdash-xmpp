#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class Bot(object):
    def __init__(self, user, leaf, participants=None, is_active=None, is_party=None):
        self.user = user
        self.leaf = leaf
        self.is_vinebot = user.startswith(constants.vinebot_prefix)
        self._participants = participants
        self._is_active = is_active
        self._is_party = is_party
        self._topic = None
        self._observers = None
    
    def _fetch_basic_data(self):
        self._participants, self._is_active, self._is_party = self.leaf.db_fetch_vinebot(self.user)
    
    def __getattr__(self, name):
        if self.is_vinebot:
            if name == 'participants':
                if self._participants is None:
                    self._fetch_basic_data()
                return self._participants
            elif name == 'is_active':
                if self._is_active is None:
                    self._fetch_basic_data()
                return self._is_active
            elif name == 'is_party':
                if self._is_party is None:
                    self._fetch_basic_data()
                return self._is_party
            elif name == 'topic':
                if self._topic is None:
                    self._topic = self.leaf.db_fetch_topic(self.user)
                return self._topic
            elif name == 'observers':
                if self._observers is None:
                    self._observers = self.leaf.db_fetch_observers(self.participants)
                return self._observers
            elif name == 'everyone':
                return self.participants.union(self.observers)
            else:
                raise AttributeError
        else:
            if name == 'participants':
                return set([])
            # elif name == 'is_active':
            #     return False
            # elif name == 'is_party':
            #     return False
            # elif name == 'topic':
            #     return ''
            elif name == 'observers':
                return set([])
            else:
                raise AttributeError