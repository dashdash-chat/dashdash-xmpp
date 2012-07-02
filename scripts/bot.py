#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import constants

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class Bot(object):
    def __init__(self, user, leaf, participants=None, is_active=None, is_party=None, topic=None):
        self.user = user
        self.leaf = leaf
        self.is_vinebot = user.startswith(constants.vinebot_prefix)
        self._participants = participants
        self._is_active = is_active
        self._is_party = is_party
        self._topic = topic
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
                
    def __setattr__(self, name, value):
        if not self.__dict__.has_key('_attrExample__initialised'):  # this test allows attrs to be set in the __init__ method
            return dict.__setattr__(self, name, value)
        if name == 'participants':
            self.__setitem__('_participants', value)
        elif name == 'is_active':
            self.__setitem__('_is_active', value)
        elif name == 'is_party':
            self.__setitem__('_is_party', value)
        elif name == 'topic':
            self.__setitem__('_topic', value)
        elif name == 'observers':
            self.__setitem__('_observers', value)
        elif name == 'everyone':
            raise AttributeError("%s is an immutable attribute.")
        else:
            dict.__setattr__(self, item, value)
