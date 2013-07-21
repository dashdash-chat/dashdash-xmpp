#!/usr/bin/env python
# -*- coding: utf-8 -*-
import shortuuid
import sys
import uuid
import constants
from datetime import datetime, timedelta
from constants import g
import user as u
import edge as e

IDLE_MINUTES = 10
PRONOUN = 'me'

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

class NotVinebotException(Exception):
    pass

class VinebotPermissionsException(Exception):
    pass

class AbstractVinebot(object):
    def __init__(self, can_write=False):
        self._topic_body = None
        self._topic_timestamp = None
        self._edges = None
        self._participants = None
        self._observers = None
        self._last_active = None
        self.can_write = can_write
        #TODO add transactions?
    
    def acquire_lock(self):
        if self.can_write:
            g.db.lock_vinebot(self.jiduser, 5)
    
    def release_lock(self):
        if self.can_write:
            g.db.release_vinebot(self.jiduser)
    
    def make_writer(self):
        self.release_lock()
        self.can_write = True
        self.acquire_lock()
    
    def add_to_roster_of(self, user, nick, async=True):
        if not self.can_write:
            raise VinebotPermissionsException
        g.ectl.add_rosteritem(user.name, self.jiduser, self.group, nick, async)
    
    def remove_from_roster_of(self, user, async=True):
        if not self.can_write:
            raise VinebotPermissionsException
        g.send_presences(self, [user])
        g.send_presences(self, [user], pshow='unavailable')
        g.ectl.delete_rosteritem(user.name, self.jiduser, async)
    
    def _fetch_participants(self):
        participants = g.db.execute_and_fetchall("""SELECT users.name, users.id
                                                    FROM participants, users
                                                    WHERE participants.vinebot_id = %(id)s
                                                    AND participants.user_id = users.id
                                                    AND users.is_active = true
                                                 """, {
                                                     'id': self.id
                                                 })
        return frozenset([u.FetchedUser(name=participant[0], dbid=participant[1]) for participant in participants])
    
    def _fetch_observers(self):
        if not self.is_active:
            observers = g.db.execute_and_fetchall("""SELECT users.name, users.id
                                                     FROM users
                                                     LEFT OUTER JOIN recipients ON users.id = recipients.recipient_id
                                                     LEFT OUTER JOIN messages ON recipients.message_id = messages.id
                                                     LEFT OUTER JOIN commands ON messages.parent_command_id = commands.id
                                                     WHERE messages.vinebot_id = %(vinebot_id)s
                                                     AND messages.sender_id IS NULL
                                                     AND commands.command_name = "party"
                                                     AND commands.is_valid IS TRUE
                                                     ORDER BY commands.sent_on DESC
                                                  """, {
                                                     'vinebot_id': self.id
                                                  })
        else:
            observers = g.db.execute_and_fetchall("""SELECT users.name, users.id
                                                     FROM participants, edges AS outgoing, edges AS incoming, users
                                                     WHERE outgoing.to_id = users.id
                                                     AND incoming.from_id = outgoing.to_id
                                                     AND participants.vinebot_id = %(id)s
                                                     AND participants.user_id = incoming.to_id
                                                     AND participants.user_id = outgoing.from_id
                                                     AND users.is_active = true
                                                     AND (SELECT COUNT(*)
                                                          FROM participants
                                                          WHERE participants.vinebot_id = %(id)s
                                                          AND user_id=users.id
                                                         ) = 0
                                                  """, {
                                                      'id': self.id
                                                  })
        return frozenset([u.FetchedUser(name=observer[0], dbid=observer[1]) for observer in observers])
    
    def _fetch_edges(self):
        edge_ids = g.db.execute_and_fetchall("""SELECT id
                                                FROM edges
                                                WHERE vinebot_id = %(id)s
                                             """, {
                                                 'id': self.id
                                             }, strip_pairs=True)
        return frozenset([e.FetchedEdge(dbid=edge_id) for edge_id in edge_ids])
    
    def add_participant(self, user):
        if not self.can_write:
            raise VinebotPermissionsException
        g.db.execute("""INSERT INTO participants (vinebot_id, user_id)
                        VALUES (%(vinebot_id)s, %(user_id)s)
                     """, {
                        'vinebot_id': self.id,
                        'user_id': user.id
                     })
        #NOTE adding "self.participants" here to initialize the pariticipants causes an error I don't understand
        self._participants = self._participants.union([user])
    
    def remove_participant(self, user):
        if not self.can_write:
            raise VinebotPermissionsException
        self._participants = self._participants.difference([user])
        g.db.execute("""DELETE FROM participants
                        WHERE user_id = %(user_id)s
                        AND vinebot_id = %(vinebot_id)s
                     """, {
                        'vinebot_id': self.id,
                        'user_id': user.id
                     })
    
    def get_status(self, viewer):
        statuses = []
        party_sender = None
        if len(self.participants) == 1:
            party_sender = self._fetch_party_sender()
        if self.is_active and self.topic_body is not None:
            if len(self.participants) == 1 and party_sender is not None:
                statuses.append('/party invite from %s' % party_sender.name)
            else:
                statuses.append(self._participant_string(viewer))
        elif self.topic:
            statuses.append(self.topic)
        if self.is_active and self.is_idle:
            if len(self.participants) > 1 and party_sender is None:
                if self.last_active is None:
                    statuses.append('has never been active')
                else:
                    statuses.append('last active %s ago' % self._format_timestamp(self.last_active))
        return '; '.join(statuses)
    
    def get_nick(self, viewer):
        if self.is_active and self.topic_body is not None:
            return '%s (%d)' % (self.topic_body, len(self.participants))
        else:
            return self._participant_string(viewer)
    
    def _fetch_party_sender(self):
        sender_id = g.db.execute_and_fetchall("""SELECT commands.sender_id
                                                 FROM commands
                                                 LEFT OUTER JOIN messages ON commands.id = messages.parent_command_id
                                                 WHERE messages.vinebot_id = %(vinebot_id)s
                                                 AND messages.sender_id IS NULL
                                                 AND commands.command_name = "party"
                                                 AND commands.is_valid IS TRUE
                                                 ORDER BY commands.sent_on DESC
                                                 LIMIT 1
                                              """, {
                                                 'vinebot_id': self.id
                                              }, strip_pairs=True)
        if sender_id:
            return u.FetchedUser(dbid=sender_id[0])
        return None
    
    def _participant_string(self, viewer):
        if not self.is_active:
            usernames = [user.name for user in self.edge_users.difference([viewer])]
        else:
            usernames = [user.name for user in self.participants.difference([viewer])]
            usernames.sort()  # to prevent the names from jumping around in statuses, alphabetic order is fine for now
            if viewer and viewer in self.participants:
                usernames.insert(0, PRONOUN)
        if len(usernames) == 0:
            return self.jiduser
        elif len(usernames) == 1:
            return usernames[0]
        elif len(usernames) == 2 and viewer and viewer in self.participants:
            return '%s & %s' % (usernames[1], usernames[0])
        else:
            participant_string = '%s & %s' % (', '.join(usernames[:-1]), usernames[-1])
            return participant_string
    
    def update_rosters(self, old_participants, new_participants, protected_participants=frozenset([])):  # if there are still edges between the users, we might not want to change their rosteritems
        observer_nick = self.get_nick(None)
        # First, create the old and new lists of observers
        def get_observers_for(users):
            return frozenset(reduce(lambda observers, user: observers.union(user.friends), users, set([])))
        old_observers = get_observers_for(old_participants)
        new_observers = get_observers_for(new_participants)
        # Only update connected users for now – others will sync_roster when they come online
        connected_users = g.ectl.connected_users()
        new_participants = new_participants.intersection(connected_users)
        new_participants = new_participants.intersection(connected_users)
        new_observers = new_observers.intersection(connected_users)
        old_observers = old_observers.intersection(connected_users)
        # Then, update the participants
        for old_participant in old_participants.difference(new_observers).difference(new_participants).difference(protected_participants):
            self.remove_from_roster_of(old_participant, async=False)
        for new_participant in new_participants.union(protected_participants):  # we still need to give the old edge users the updated nick
            self.add_to_roster_of(new_participant, self.get_nick(new_participant), async=False)
        # Finally, update the observers
        for old_observer in old_observers.difference(new_participants).difference(protected_participants).difference(new_observers):
            self.remove_from_roster_of(old_observer)
        for new_observer in new_observers.difference(new_participants).difference(protected_participants):
            self.add_to_roster_of(new_observer, nick=observer_nick)
    
    def check_recent_activity(self, excluded_user=None):
        if excluded_user is not None:
            last_active = self._fetch_last_active(excluded_user=excluded_user)
            if last_active is None:
                return False
            return last_active > (datetime.now() - timedelta(minutes=IDLE_MINUTES))
        else:
            if self.last_active is None:
                return False
            return self.last_active > (datetime.now() - timedelta(minutes=IDLE_MINUTES))
    
    def _fetch_last_active(self, excluded_user=None):
        last_message = g.db.execute_and_fetchall("""SELECT sent_on
                                                    FROM messages
                                                    WHERE vinebot_id = %(vinebot_id)s
                                                    AND sender_id != %(excluded_user_id)s
                                                    AND sender_id IS NOT NULL
                                                    AND parent_command_id IS NULL
                                                    AND body IS NOT NULL
                                                    ORDER BY sent_on DESC
                                                    LIMIT 1
                                                 """, {
                                                    'vinebot_id': self.id,
                                                    'excluded_user_id': excluded_user.id if excluded_user else 0 #TODO for some reason NULL doesn't work here, but 0 is kinda hacky
                                                 }, strip_pairs=True)
        last_command = g.db.execute_and_fetchall("""SELECT sent_on
                                                    FROM commands
                                                    WHERE vinebot_id = %(vinebot_id)s
                                                    AND sender_id != %(excluded_user_id)s
                                                    AND sender_id IS NOT NULL
                                                    AND command_name IN ('join', 'topic', 'invite', 'tweet_invite')
                                                    AND is_valid IS TRUE
                                                    ORDER BY sent_on DESC
                                                    LIMIT 1
                                                 """, {
                                                    'vinebot_id': self.id,
                                                    'excluded_user_id': excluded_user.id if excluded_user else 0
                                                 }, strip_pairs=True)
        if last_message and last_command:
            return last_message[0] if last_message[0] > last_command [0] else last_command[0]
        elif last_message:
            return last_message[0]
        elif last_command:
            return last_command[0]
        else:
            return None
    
    def get_last_message(self, sender=None):
        if sender:  # Either the sender is specified or IS NOT NULL, otherwise pairs of queries are the same
            last_message = g.db.execute_and_fetchall("""SELECT messages.sender_id, messages.body, messages.sent_on, GROUP_CONCAT(DISTINCT recipients.recipient_id)
                                                        FROM messages
                                                        LEFT OUTER JOIN recipients ON messages.id = recipients.message_id
                                                        WHERE messages.vinebot_id = %(vinebot_id)s
                                                        AND messages.sender_id = %(sender_id)s
                                                        AND messages.body IS NOT NULL
                                                        AND messages.parent_command_id IS NULL
                                                        GROUP BY messages.id
                                                        ORDER BY messages.sent_on DESC
                                                        LIMIT 1
                                                     """, {
                                                        'vinebot_id': self.id,
                                                        'sender_id': sender.id
                                                     })
            last_command = g.db.execute_and_fetchall("""SELECT commands.sender_id, messages.body, messages.sent_on, GROUP_CONCAT(DISTINCT recipients.recipient_id)
                                                        FROM messages
                                                        LEFT OUTER JOIN commands ON messages.parent_command_id = commands.id
                                                        LEFT OUTER JOIN recipients ON messages.id = recipients.message_id
                                                        WHERE commands.vinebot_id = %(vinebot_id)s
                                                        AND commands.sender_id = %(sender_id)s
                                                        AND messages.sender_id IS NULL
                                                        AND commands.command_name IN ('me', 'topic')
                                                        AND commands.is_valid IS TRUE
                                                        GROUP BY messages.id
                                                        ORDER BY commands.sent_on DESC
                                                        LIMIT 1
                                                     """, {
                                                        'vinebot_id': self.id,
                                                        'sender_id': sender.id
                                                     })
        else:
            last_message = g.db.execute_and_fetchall("""SELECT messages.sender_id, messages.body, messages.sent_on, GROUP_CONCAT(DISTINCT recipients.recipient_id)
                                                        FROM messages
                                                        LEFT OUTER JOIN recipients ON messages.id = recipients.message_id
                                                        WHERE messages.vinebot_id = %(vinebot_id)s
                                                        AND messages.sender_id IS NOT NULL
                                                        AND messages.body IS NOT NULL
                                                        AND messages.parent_command_id IS NULL
                                                        GROUP BY messages.id
                                                        ORDER BY messages.sent_on DESC
                                                        LIMIT 1
                                                     """, {
                                                        'vinebot_id': self.id
                                                     })
            last_command = g.db.execute_and_fetchall("""SELECT commands.sender_id, messages.body, messages.sent_on, GROUP_CONCAT(DISTINCT recipients.recipient_id)
                                                        FROM messages
                                                        LEFT OUTER JOIN commands ON messages.parent_command_id = commands.id
                                                        LEFT OUTER JOIN recipients ON messages.id = recipients.message_id
                                                        WHERE commands.vinebot_id = %(vinebot_id)s
                                                        AND commands.sender_id IS NOT NULL
                                                        AND messages.sender_id IS NULL
                                                        AND commands.command_name IN ('me', 'topic')
                                                        AND commands.is_valid IS TRUE
                                                        GROUP BY messages.id
                                                        ORDER BY commands.sent_on DESC
                                                        LIMIT 1
                                                     """, {
                                                        'vinebot_id': self.id
                                                     })
        return_tuple = None
        if last_message and last_command:
            return_tuple = last_message[0] if last_message[0][2] > last_command[0][2] else last_command[0]
        elif last_message:
            return_tuple = last_message[0]
        elif last_command:
            return_tuple = last_command[0]
        if return_tuple is None:
            return (None, None, None, None)
        return (u.FetchedUser(dbid=return_tuple[0]),
               return_tuple[1],
               return_tuple[2],
               set([] if return_tuple[3] is None else [u.FetchedUser(dbid=recipient_id) for recipient_id in return_tuple[3].split(',')]))
    
    def get_suspended_messages(self):
        suspended_messages = g.db.execute_and_fetchall("""SELECT messages.id, messages.body, GROUP_CONCAT(DISTINCT recipients.recipient_id)
                                                          FROM messages
                                                          LEFT OUTER JOIN recipients ON messages.id = recipients.message_id
                                                          WHERE messages.vinebot_id = %(vinebot_id)s
                                                          AND messages.body IS NOT NULL
                                                          AND messages.sender_id IS NULL
                                                          AND messages.sent_on = %(sent_on)s
                                                          GROUP BY messages.id
                                                       """, {
                                                          'vinebot_id': self.id,
                                                          'sent_on': '0000-00-00 00:00:00'
                                                       })
        return [(suspended_message[0],
                 suspended_message[1],
                 set([] if suspended_message[2] is None else [u.FetchedUser(dbid=recipient_id) for recipient_id in suspended_message[2].split(',')])
                ) for suspended_message in suspended_messages
               ]
    
    def _set_topic(self, body):
        if not self.can_write:
            raise VinebotPermissionsException
        g.db.execute("""DELETE FROM topics
                        WHERE vinebot_id = %(vinebot_id)s
                    """, {
                        'vinebot_id': self.id
                    })
        self._topic_body = None
        self._topic_timestamp = None
        if body:
            g.db.execute("""INSERT INTO topics (vinebot_id, body)
                            VALUES (%(vinebot_id)s, %(body)s)
                         """, {
                            'vinebot_id': self.id,
                            'body': body.encode('utf-8')
                         })
            self._topic_body = body
            self._topic_timestamp = datetime.now()
        self.update_rosters(set([]), self.participants)
    
    def _fetch_topic(self):
        topic = g.db.execute_and_fetchall("""SELECT body, created
                                             FROM topics
                                             WHERE vinebot_id = %(vinebot_id)s
                                          """, {
                                             'vinebot_id': self.id
                                          })
        if topic and len(topic) > 0 and len(topic[0]) == 2:
            self._topic_body, self._topic_timestamp = topic[0]
            return self._topic_body, self._topic_timestamp
        return None, None
    
    def _format_timestamp(self, timestamp):
        if timestamp is None:
            return ''
        # generates strings that look like "1 day, 5 hours, 6 mins", FML
        remainder = (datetime.now() - timestamp).total_seconds()
        if remainder < 1:  # if the timestamp is too recent, the remainder could be negative, and divmod will behave weirdly
            remainder = 0
        days,    remainder = divmod(remainder, 60 * 60 * 24)
        hours,   remainder = divmod(remainder, 60 * 60)
        minutes, remainder = divmod(remainder, 60)
        if (days + hours + minutes) == 0:
            return 'a moment'
        count_units =  [(days, 'day'), (hours, 'hour'), (minutes, 'minute')]
        return ', '.join(['%d %s%s' %  (count, unit, '' if count == 1 else 's')
                          for count, unit in count_units
                          if count > 0])
    
    def delete(self, new_vinebot=None):
        if not self.can_write:
            raise VinebotPermissionsException
        if self.is_active:
            raise Exception
        for user in self.edge_users:
            self.remove_from_roster_of(user)
        if new_vinebot:
            for edge in self.edges:
                edge.change_vinebot(new_vinebot)
        # never delete the actual edges though - either they're deleted elsewhere, or will be transferred to a new vinebot
        g.db.execute("""DELETE FROM participants
                           WHERE vinebot_id = %(id)s
                        """, {
                           'id': self.id
                        })
        g.db.execute("""DELETE FROM topics
                           WHERE vinebot_id = %(id)s
                        """, {
                           'id': self.id
                        })
        g.db.execute("""DELETE FROM vinebots
                        WHERE id = %(id)s
                        AND (SELECT COUNT(*) FROM messages WHERE vinebot_id = %(id)s) = 0
                        AND (SELECT COUNT(*) FROM commands WHERE vinebot_id = %(id)s) = 0;
                    """, {
                        'id': self.id
                    })
    
    def __getattr__(self, name):
        if name == 'topic':
            if self.topic_body is not None:
                if self.topic_timestamp is not None:
                    return '"%s" as of %s ago' % (self.topic_body, self._format_timestamp(self.topic_timestamp))
                return '"%s"' % self.topic_body
            else:
                return None
        elif name == 'topic_body':
            return self._topic_body
        elif name == 'topic_timestamp':
            return self._topic_timestamp
        elif name == 'is_active':
            return len(self.participants) >= 1  # should only ever be == 1 on a newly-created /party vinebot, but that's ok
        elif name == 'last_active':
            if self._last_active is None:
                self._last_active = self._fetch_last_active()
            return self._last_active
        elif name == 'is_idle':
            return not self.check_recent_activity()
        elif name == 'group':
            group = 'Contacts'
            if self.is_active:
                group = 'Conversations'
            if constants.debug:
                return 'Dashdash %s (Dev)' % group
            return 'Dashdash %s' % group
        elif name == 'edges':
            if self._edges is None:
                self._edges = self._fetch_edges()
            return self._edges
        elif name == 'edge_users':
            if len(self.edges) == 0:
                return set([])
            elif len(self.edges) == 1:
                edge = iter(self.edges).next()
                return set([edge.t_user, edge.f_user])  # doesn't need to be a frozenset
            elif len(self.edges) == 2:
                edge1, edge2 = self.edges
                return set([edge1.t_user, edge1.f_user, edge2.t_user, edge2.f_user])
            else:
                raise AttributeError("Vinebot %d somehow has %d edges" % (self.id, len(self.edges)))
        elif name == 'participants':
            if self._participants is None:
                self._participants = self._fetch_participants()
            return self._participants
        elif name == 'observers':
            if self._observers is None:
                self._observers = self._fetch_observers()
            return self._observers
        elif name == 'everyone':
            return self.participants.union(self.observers)
        # __getattr__ is only called as a last resort, so we don't need a catchall
    
    def __setattr__(self, name, value):
        if name == 'topic':
            self._set_topic(value)
        elif name in ['topic_body', 'topic_timestamp', 'is_active', 'last_active', 'is_idle', 'edges', 'edge_users', 'participants', 'observers', 'everyone']:
            raise AttributeError("%s is an immutable attribute." % name)
        else:
            dict.__setattr__(self, name, value)
    
    def __eq__(self, other):
        if not isinstance(other, AbstractVinebot):
            return False
        return (self.id == other.id and self.jiduser == other.jiduser)
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    def __hash__(self):
        return hash('%d.%s' % (self.id, self.jiduser))
    
    def __str__(self):
        return self.__repr__()
    
    def __repr__(self):
        return '%s(jiduser=\'%s\', dbid=%d)' % (self.__class__.__name__, self.jiduser, self.id)
    

class InsertedVinebot(AbstractVinebot):
    def __init__(self, old_vinebot=None):
        super(InsertedVinebot, self).__init__(can_write=True)
        _uuid = uuid.uuid4()
        self.jiduser = '%s%s' % (constants.vinebot_prefix, shortuuid.encode(_uuid))
        self.acquire_lock()  # I wish this could go in AbstractVinebot.__init__(), but that happens before we have self.jiduser
        self.id = g.db.execute("""INSERT INTO vinebots (uuid)
                                  VALUES (%(uuid)s)
                               """, {
                                  'uuid': _uuid.bytes
                               })
        if old_vinebot and old_vinebot.edges:
            self._edges = []
            for edge in old_vinebot.edges:
                edge.change_vinebot(self)
                self._edges.append(edge)
                self.add_to_roster_of(edge.f_user, self.get_nick(edge.f_user))
    

class FetchedVinebot(AbstractVinebot):
    def __init__(self, can_write=False, jiduser=None, dbid=None, _uuid=None):#, edges=None):
        super(FetchedVinebot, self).__init__(can_write)
        if dbid and _uuid:
            self.jiduser = '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid.UUID(bytes=_uuid)))
            self.id = dbid
        elif dbid:
            _uuid = g.db.execute_and_fetchall("""SELECT uuid
                                                 FROM vinebots
                                                 WHERE id = %(id)s
                                              """, {
                                                  'id': dbid
                                              }, strip_pairs=True)
            if not _uuid:
                raise NotVinebotException
            self.jiduser = '%s%s' % (constants.vinebot_prefix, shortuuid.encode(uuid.UUID(bytes=_uuid[0])))
            self.id = dbid
        elif jiduser:
            if not jiduser.startswith(constants.vinebot_prefix):
                raise NotVinebotException
            _shortuuid = jiduser.replace(constants.vinebot_prefix, '')
            _uuid = shortuuid.decode(_shortuuid)
            dbid = g.db.execute_and_fetchall("""SELECT id
                                                FROM vinebots
                                                WHERE uuid = %(uuid)s
                                             """, {
                                                'uuid': _uuid.bytes
                                             }, strip_pairs=True)
            if not dbid:
                raise NotVinebotException
            self.jiduser = jiduser
            self.id = dbid[0]
        elif jiduser == constants.leaves_jid_user:  # because the leaf itself has no username, and we want to fail gracefully
            raise NotVinebotException
        else:
            raise Exception, 'FetchedVinebots require either the vinebot\'s username or database id as parameters.'
        self.acquire_lock()
        self._topic_body, self._topic_timestamp = self._fetch_topic()
    
    @staticmethod
    def fetch_vinebots_with_participants(participants=[]):
        if len(participants) == 0:
            vinebot_ids = g.db.execute_and_fetchall("""SELECT vinebot_id
                                                       FROM participants
                                                       GROUP BY vinebot_id
                                                    """, strip_pairs=True)
            return [FetchedVinebot(dbid=vinebot_id) for vinebot_id in vinebot_ids]
        elif len(participants) == 2:
            participants = list(participants)
            vinebot_ids = g.db.execute_and_fetchall("""SELECT first_participants.vinebot_id
                                                       FROM participants AS first_participants
                                                       WHERE first_participants.user_id = %(first_user_id)s
                                                       AND (SELECT COUNT(*)
                                                            FROM participants AS second_participants
                                                            WHERE second_participants.user_id = %(second_user_id)s
                                                            AND first_participants.vinebot_id = second_participants.vinebot_id
                                                           ) > 0
                                                       AND (SELECT COUNT(*)
                                                            FROM participants AS other_participants
                                                            WHERE other_participants.user_id NOT IN (%(first_user_id)s, %(second_user_id)s)
                                                            AND first_participants.vinebot_id = other_participants.vinebot_id
                                                           ) = 0
                                                        """, {
                                                            'first_user_id': participants[0].id,
                                                            'second_user_id': participants[1].id
                                                        }, strip_pairs=True)
            return [FetchedVinebot(can_write=True, dbid=vinebot_id) for vinebot_id in vinebot_ids]  #NOTE these vinebots need write privileges to change edges
        else:
            raise Exception, 'Passed invalid number of participants %d to fetch_vinebots_with_participants.' % len(participants)
    
    @staticmethod
    def fetch_vinebots_with_edges():
        vinebot_ids = g.db.execute_and_fetchall("""SELECT edges.vinebot_id
                                                   FROM edges
                                                   WHERE edges.vinebot_id IS NOT NULL
                                                   AND (SELECT COUNT(*) FROM participants WHERE vinebot_id = edges.vinebot_id) = 0
                                                   GROUP BY edges.vinebot_id
                                                """, strip_pairs=True)
        return [FetchedVinebot(dbid=vinebot_id) for vinebot_id in vinebot_ids]
    
