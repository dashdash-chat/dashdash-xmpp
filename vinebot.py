#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import constants
from datetime import datetime, timedelta

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input


class Vinebot(object):
    def __init__(self, user, leaf, participants=None, is_active=None, is_party=None, topic=None):
        self._user = user
        self._leaf = leaf
        self._is_vinebot = user.startswith(constants.vinebot_prefix)
        self._participants = participants
        self._is_active = is_active
        self._is_party = is_party
        self._topic = self._format_topic(topic)
        self._observers = None
    
    def other_participant(self, user):
        if not self.is_party and len(self.participants) == 2:
            return self.participants.difference([user]).pop()
        else:
            raise Exception, 'Improper use of method: must use on pair bot with two participants.' + \
                ' user=%s, is_party=%s, participants=%s' % (self.user, self.is_party, self.participants)
    
    def _fetch_basic_data(self):
        self._participants, self._is_active, self._is_party = self.leaf.db_fetch_vinebot(self.user)
    
    def _format_topic(self, topic):
        if topic:
            body, created = topic
            return "%s%s" % (body, (created - timedelta(hours=6)).strftime(' (set on %b %d at %-I:%M%p EST)'))
        return None
    
    def __getattr__(self, name):
        if name == 'user':
            return self._user
        elif name == 'leaf':
            return self._leaf
        elif name == 'is_vinebot':
            return self._is_vinebot
        elif self.is_vinebot:
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
                    self._topic = self._format_topic(self.leaf.db_fetch_topic(self.user))
                return self._topic
            elif name == 'observers':
                if self._observers is None:
                    self._observers = self.leaf.db_fetch_observers(self.participants)
                return self._observers
            elif name == 'everyone':
                return self.participants.union(self.observers)
            else:
                logging.error("BLEARGH %s" % name)
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
        if name == 'participants':
            dict.__setattr__(self, '_participants', value)
        elif name == 'is_active':
            dict.__setattr__(self, '_is_active', value)
        elif name == 'is_party':
            dict.__setattr__(self, '_is_party', value)
        elif name == 'topic':
            dict.__setattr__(self, '_topic', self._format_topic(value))
        elif name == 'observers':    
            dict.__setattr__(self, '_observers', value)
        elif name in ['user', 'leaf', 'is_vinebot', 'everyone']:
            raise AttributeError("%s is an immutable attribute." % name)
        else:
            dict.__setattr__(self, name, value)
