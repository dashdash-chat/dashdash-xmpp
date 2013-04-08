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
        self.id = None
        self.code = None
        self.sender = None
        self.max_uses = None
        self.visible = None
        self._recipients = None
    
    def _fetch_recipients(self):
        recipient_ids = g.db.execute_and_fetchall("""SELECT invitee_id
                                                     FROM invitees
                                                     WHERE invite_id = %(invite_id)s
                                                """, {
                                                    'invite_id': self.id
                                                    }, strip_pairs=True)
        return [u.FetchedUser(dbid=recipient_id) for recipient_id in recipient_ids]
    
    def _is_used_up(self):
        return len(self.recipients) >= self.max_uses
    
    def _has_been_used(self):
        return len(self.recipients) > 0
    
    def use(self, recipient):
        if self._is_used_up():
            raise ImmutableInviteException
        g.db.execute("""INSERT INTO invitees (invite_id, invitee_id)
                        VALUES (%(invite_id)s, %(invitee_id)s)
                     """, {
                        'invite_id': self.id,
                        'invitee_id': recipient.id,
                     })
        self.recipients.append(recipient)
    
    def hide(self):
        self._set_visible(False)
    
    def show(self):
        self._set_visible(True)
    
    def _set_visible(self, visible):
        if self._is_used_up():
            raise ImmutableInviteException
        g.db.execute("""UPDATE invites
                        SET visible = %(visible)s
                        WHERE id = %(id)s
                     """, {
                        'visible': visible,
                        'id': self.id
                     })
    
    def delete(self):
        if self._has_been_used():
            raise ImmutableInviteException
        g.db.execute("""DELETE FROM invites
                        WHERE id = %(id)s
                     """, {
                        'id': self.id
                     })
    
    def disable(self):
        if self._is_used_up():
            return
        g.db.execute("""UPDATE invites
                        SET max_uses = %(max_uses)s
                        WHERE id = %(id)s
                     """, {
                        'max_uses': len(self.recipients),
                        'id': self.id
                     })
    
    def __getattr__(self, name):
        if name == 'url':
            return '%s%s' % (AbstractInvite.url_prefix, self.code)
        elif name == 'recipients':
            if self._recipients is None:
                self._recipients = self._fetch_recipients()
            return self._recipients
        # __getattr__ is only called as a last resort, so we don't need a catchall
    
    def __str__(self):
        return self.__repr__()
    
    def __repr__(self):
        return '%s(code=\'%s\', sender=%s, recipients=%s, visible=%s)' % (self.__class__.__name__, self.code, self.sender, self.recipients, self.visible)
    

class InsertedInvite(AbstractInvite):
    def __init__(self, sender, max_uses=1):
        super(InsertedInvite, self).__init__()
        if not sender:
            raise Exception, 'New invites need to be given a user as the sender.'
        if max_uses < 1:
            raise Exception, 'New invites must have a max_uses of at least 1.'
        self.sender = sender    
        self.max_uses = max_uses
        for i in range(10):
            try:
                new_code = self._generate_code()
                dbid = g.db.execute("""INSERT INTO invites (code, sender, max_uses)
                                       VALUES (%(code)s, %(sender)s, %(max_uses)s)
                                    """, {
                                       'code': new_code,
                                       'sender': sender.id,
                                       'max_uses': max_uses
                                    })
                self.id = dbid
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
    def __init__(self, code=None, sender_id=None, invitee_id=None, visible=None):
        super(FetchedInvite, self).__init__()
        if code is not None:
            if code.startswith(super(FetchedInvite, self).url_prefix):
                code = code.replace(super(FetchedInvite, self).url_prefix, '')
            self.code = code
            if sender_id and visible is not None:
                results = g.db.execute_and_fetchall("""SELECT id, max_uses
                                                       FROM invites
                                                       WHERE code = %(code)s
                                                       AND sender = %(sender_id)s
                                                       LIMIT 1
                                                    """, {
                                                       'code': code,
                                                       'sender_id': sender_id
                                                    })
                if len(results) < 1:
                    raise NotInviteException, 'No invite found for code %s' % code
                self.id = results[0][0]
                self.sender = u.FetchedUser(dbid=sender_id)
                self.max_uses = results[0][1]
                self.visible = visible
            else:
                results = g.db.execute_and_fetchall("""SELECT id, max_uses, sender, visible
                                                       FROM invites
                                                       WHERE code = %(code)s
                                                       LIMIT 1
                                                    """, {
                                                       'code': code
                                                    })
                if len(results) < 1:
                    raise NotInviteException, 'No invite found for code %s' % code
                self.id = results[0][0]
                self.max_uses = results[0][1]
                self.sender = u.FetchedUser(dbid=results[0][2])
                self.visible = results[0][3]
        else:
            if invitee_id is not None:
                results = g.db.execute_and_fetchall("""SELECT invites.id, invites.code, invites.sender, invites.max_uses
                                                       FROM invites, invitees
                                                       WHERE invites.id = invitees.invite_id
                                                       AND invitees.invitee_id = %(invitee_id)s
                                                       LIMIT 1
                                                    """, {
                                                       'invitee_id': invitee_id
                                                    })
                if len(results) < 1:
                    raise NotInviteException, 'No invite found for code %s' % code
                self.id = results[0][0]
                self.code = results[0][1]
                self.sender = u.FetchedUser(dbid=results[0][2])
                self.max_uses = results[0][3]
                self.visible = visible
            else:
                raise NotInviteException, 'No invite found for code=%s, sender_id=%s, invitee_id=%s, visible=%s' % (code, sender_id, invitee_id, visible)
    
    @staticmethod
    def fetch_sender_invites(sender):
        results = g.db.execute_and_fetchall("""SELECT code, sender, visible
                                               FROM invites
                                               WHERE sender = %(sender)s
                                            """, {
                                               'sender': sender.id
                                            })
        return [FetchedInvite(code=result[0], sender_id=result[1], visible=result[2]) for result in results]
    
