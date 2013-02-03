#!/usr/bin/env python
# -*- coding: utf-8 -*-
import MySQLdb
import sys
import os, random, string  # for password generation    
import constants
from constants import g
import user as u

INVITE_LENGTH = 7  # to match human working memory

if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding('utf8')
else:
    raw_input = input

class NotInviteException(Exception):
    pass

class ImmutableInviteException(Exception):
    pass

class AbstractInvite(object):
    url_prefix = 'http://%s/invite/' % constants.domain
    
    def __init__(self):
        self.code = None
        self.sender = None
        self.recipient = None
        self.visible = None
    
    def _has_been_used(self):
        if self.recipient is None:
            recipient_id = g.db.execute_and_fetchall("""SELECT recipient
                                                        FROM invites
                                                        WHERE code = %(code)s
                                                    """, {
                                                        'code': self.code
                                                        }, strip_pairs=True)
            if len(recipient_id) > 0 and recipient_id[0] is not None:
                self.recipient = u.FetchedUser(dbid=recipient_id)
        return self.recipient is not None
    
    def hide(self):
        self._set_visible(False)
        
    def show(self):
        self._set_visible(True)
    
    def _set_visible(self, visible):
        if self._has_been_used():
            raise ImmutableInviteException
        g.db.execute("""UPDATE invites
                        SET visible = %(visible)s
                        WHERE code = %(code)s
                        AND recipient IS NULL
                     """, {
                        'visible': visible,
                        'code': self.code
                     })
    
    def delete(self):
        if self._has_been_used():
            raise ImmutableInviteException
        g.db.execute("""DELETE FROM invites
                        WHERE code = %(code)s
                        AND recipient IS NULL
                     """, {
                        'code': self.code
                     })
    
    def __getattr__(self, name):
        if name == 'url':
            return '%s%s' % (AbstractInvite.url_prefix, self.code)
        # __getattr__ is only called as a last resort, so we don't need a catchall
    
    def __str__(self):
        return self.__repr__()
    
    def __repr__(self):
        return '%s(code=\'%s\', sender=%s, recipient=%s, visible=%s)' % (self.__class__.__name__, self.code, self.sender, self.recipient, self.visible)
    

class InsertedInvite(AbstractInvite):
    def __init__(self, sender):
        super(InsertedInvite, self).__init__()
        if not sender:
            raise Exception, 'New invites need to be given a user as the sender.'
        self.sender = sender
        for i in range(10):
            try:
                new_code = self._generate_code()
                g.db.execute("""INSERT INTO invites (code, sender)
                                VALUES (%(code)s, %(sender)s)
                             """, {
                                'code': new_code,
                                'sender': sender.id
                             })
                self.code = new_code
                self.visible = True
                return
            except MySQLdb.Error, e:
                if e[0] == 1062:
                    continue  # and try to generate a new code
                else:
                    raise e
        raise Exception, 'Failed to generate unique invite code in 10 tries!'
    
    def _generate_code(self):
        chars = string.ascii_lowercase + string.digits
        random.seed = (os.urandom(1024))
        return ''.join(random.choice(chars) for i in range(INVITE_LENGTH))
    

class FetchedInvite(AbstractInvite):
    def __init__(self, code, sender_id=None, recipient_id=None, visible=None):
        super(FetchedInvite, self).__init__()
        if code.startswith(super(FetchedInvite, self).url_prefix):
            code = code.replace(super(FetchedInvite, self).url_prefix, '')
        self.code = code
        if sender_id and visible is not None:  # recipient_id can be None
            self.sender = u.FetchedUser(dbid=sender_id)
            self.recipient = u.FetchedUser(dbid=recipient_id) if recipient_id is not None else None
            self.visible = visible
        else:
            results = g.db.execute_and_fetchall("""SELECT sender, visible
                                                   FROM invites
                                                   WHERE code = %(code)s
                                                   LIMIT 1
                                                """, {
                                                   'code': code
                                                })
            if len(results) < 1:
                raise NotInviteException, 'No invite found for code %s' % code
            self.sender = u.FetchedUser(dbid=results[0][0])
            self.visible = results[0][1]
    
    @staticmethod
    def fetch_sender_invites(sender):
        results = g.db.execute_and_fetchall("""SELECT code, sender, recipient, visible
                                               FROM invites
                                               WHERE sender = %(sender)s
                                            """, {
                                               'sender': sender.id
                                            })
        return [FetchedInvite(result[0], sender_id=result[1], recipient_id=result[2], visible=result[3]) for result in results]
    
