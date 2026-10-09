# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading Messages (iMessage / SMS) from a backup
# Copyright (C) 2026 slammingprogramming and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Reads the Messages database (``sms.db``) into conversations and messages.

This reader works on a connection to a *working copy* of the database and
never touches the backup. The schema differs between iOS versions, so every
optional column is checked for before it is used.
"""

import re

from .common import apple_time, table_columns

DATABASE = "HomeDomain/Library/SMS/sms.db"
"""Where the Messages database lives in a backup (``Domain/path``)."""

ATTACHMENTS_DOMAIN = "MediaDomain"

_OBJECT_REPLACEMENT = "\ufffc"     # stands in for an attachment in the text

_REACTION_NAMES = {
    2000: "Loved", 2001: "Liked", 2002: "Disliked", 2003: "Laughed at",
    2004: "Emphasized", 2005: "Questioned", 2006: "Reacted to",
}
_ADD_RANGE = range(2000, 2007)
_REMOVE_RANGE = range(3000, 3007)

_CHUNK = 500


def decode_attributed_body(blob):
    """The text stored in a message's ``attributedBody`` blob, or None.

    Since iOS 16 many messages have no ``text`` and keep their text only
    inside an archived ``NSAttributedString``. The string follows the class
    name ``NSString`` after a ``+`` marker and a length: one byte for short
    text, ``0x81`` plus two bytes (little endian) for longer text, ``0x82``
    plus four for very long text.
    """
    if not blob:
        return None
    data = bytes(blob)
    start = data.find(b"NSString")
    if start < 0:
        return None
    marker = data.find(b"+", start + 8, start + 8 + 16)
    if marker < 0 or marker + 1 >= len(data):
        return None
    pos = marker + 1
    first = data[pos]
    if first == 0x81:
        length = int.from_bytes(data[pos + 1:pos + 3], "little")
        pos += 3
    elif first == 0x82:
        length = int.from_bytes(data[pos + 1:pos + 5], "little")
        pos += 5
    elif first < 0x80:
        length = first
        pos += 1
    else:
        return None
    return data[pos:pos + length].decode("utf-8", errors="replace")


def attachment_backup_path(filename):
    """``Domain/path`` of an attachment in the backup, from the path the
    database stores (``~/Library/SMS/Attachments/ab/12/GUID/name``)."""
    if not filename:
        return None
    path = filename
    for prefix in ("~/", "/var/mobile/", "/private/var/mobile/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    return f"{ATTACHMENTS_DOMAIN}/{path.lstrip('/')}"


class Attachment:
    __slots__ = ("rowid", "name", "mime", "uti", "size", "backup_path",
                 "is_sticker")

    def __init__(self, rowid, name, mime, uti, size, backup_path,
                 is_sticker=False):
        self.rowid, self.name, self.mime, self.uti = rowid, name, mime, uti
        self.size, self.backup_path = size, backup_path
        self.is_sticker = is_sticker

    @property
    def is_image(self):
        return bool(self.mime and self.mime.startswith("image/"))


class Reaction:
    __slots__ = ("kind", "sender", "from_me")

    def __init__(self, kind, sender, from_me):
        self.kind, self.sender, self.from_me = kind, sender, from_me


class Message:
    """One message, or a conversation event such as "X left"."""

    __slots__ = ("rowid", "guid", "chat_id", "when", "read_when", "from_me",
                 "sender", "handle", "service", "text", "attachments",
                 "reactions", "kind")

    def __init__(self, **fields):
        self.attachments, self.reactions = [], []
        self.kind = "message"
        self.text, self.service, self.handle = "", None, None
        self.guid = self.read_when = self.when = None
        self.from_me, self.sender, self.chat_id, self.rowid = False, "", 0, 0
        for name, value in fields.items():
            setattr(self, name, value)


class Conversation:
    """A conversation. iOS keeps a separate chat for iMessage and for SMS
    with the same person; they are shown together here, like in Messages."""

    __slots__ = ("chat_ids", "title", "participants", "is_group", "services",
                 "count", "last_when", "preview", "identifier")

    def __init__(self, **fields):
        self.chat_ids, self.participants, self.services = [], [], set()
        self.title = self.preview = self.identifier = ""
        self.is_group, self.count, self.last_when = False, 0, None
        for name, value in fields.items():
            setattr(self, name, value)

    @property
    def service_label(self):
        return " + ".join(sorted(self.services))


class MessagesReader:
    """Reads conversations and messages through an open SQLite connection."""

    def __init__(self, conn, contacts=None):
        self.conn = conn
        self.contacts = contacts
        self._columns = {t: table_columns(conn, t) for t in
                         ("message", "chat", "handle", "attachment")}
        self._names = {}
        self._chat_conversation = {}

    # -- names ------------------------------------------------

    def display_name(self, handle):
        """The contact's name for a phone number or email, or the handle."""
        if not handle:
            return ""
        if handle not in self._names:
            name = self.contacts.name_for(handle) if self.contacts else None
            self._names[handle] = name or handle
        return self._names[handle]

    def _column(self, table, name, alias):
        return f"{alias}.{name}" if name in self._columns[table] else "NULL"

    # -- conversations ----------------------------------------

    def conversations(self):
        """Every conversation that has messages, newest first."""
        chats = {}
        chat_sql = ", ".join(self._column("chat", name, "c") for name in
                             ("chat_identifier", "display_name",
                              "service_name", "style", "room_name"))
        for rowid, identifier, display, service, style, room in \
                self.conn.execute(f"SELECT c.ROWID, {chat_sql} FROM chat c"):
            chats[rowid] = dict(identifier=identifier or "",
                                display=display or "", service=service,
                                group=(style == 43) or bool(room))
        totals = {}
        for chat_id, count, last in self.conn.execute(
                "SELECT cmj.chat_id, COUNT(*), MAX(m.date) "
                "FROM chat_message_join cmj "
                "JOIN message m ON m.ROWID = cmj.message_id "
                "GROUP BY cmj.chat_id"):
            totals[chat_id] = (count, last)
        people = {}
        for chat_id, handle in self.conn.execute(
                "SELECT chj.chat_id, h.id FROM chat_handle_join chj "
                "JOIN handle h ON h.ROWID = chj.handle_id"):
            people.setdefault(chat_id, []).append(handle)

        merged = {}
        for chat_id, chat in chats.items():
            if chat_id not in totals:
                continue            # nothing was ever said in it
            group = chat["group"] or len(people.get(chat_id, [])) > 1
            key = ("group", chat_id) if group \
                else ("direct", chat["identifier"] or chat_id)
            conv = merged.get(key)
            if conv is None:
                handles = people.get(chat_id) or (
                    [chat["identifier"]] if chat["identifier"] else [])
                conv = merged[key] = Conversation(
                    is_group=group, identifier=chat["identifier"],
                    participants=[self.display_name(h) for h in handles])
            conv.chat_ids.append(chat_id)
            if chat["service"]:
                conv.services.add(chat["service"])
            conv.title = conv.title or chat["display"]
            count, last = totals[chat_id]
            conv.count += count
            when = apple_time(last)
            if when is not None and (conv.last_when is None
                                     or when > conv.last_when):
                conv.last_when = when
        result = []
        for conv in merged.values():
            if not conv.title:
                names = conv.participants
                conv.title = ", ".join(names[:3]) + (
                    f" and {len(names) - 3} more" if len(names) > 3 else "") \
                    if names else (conv.identifier or "Unknown")
            for chat_id in conv.chat_ids:
                self._chat_conversation[chat_id] = conv
            conv.preview = self._preview(conv)
            result.append(conv)
        result.sort(key=lambda c: c.last_when or 0, reverse=True)
        return result

    def _preview(self, conv):
        marks = ",".join("?" * len(conv.chat_ids))
        row = self.conn.execute(
            f"SELECT {self._column('message', 'text', 'm')}, "
            f"{self._column('message', 'attributedBody', 'm')}, "
            f"{self._column('message', 'cache_has_attachments', 'm')} "
            "FROM message m JOIN chat_message_join cmj "
            "ON cmj.message_id = m.ROWID "
            f"WHERE cmj.chat_id IN ({marks}) "
            "ORDER BY m.date DESC, m.ROWID DESC LIMIT 1",
            conv.chat_ids).fetchone()
        if row is None:
            return ""
        text = self._text_of(row[0], row[1])
        if not text and row[2]:
            return "Attachment"
        return text.replace("\n", " ")[:120]

    # -- messages ---------------------------------------------

    @staticmethod
    def _text_of(text, attributed_body):
        if not text:
            text = decode_attributed_body(attributed_body) or ""
        return text.replace(_OBJECT_REPLACEMENT, "").strip()

    def messages(self, conversation):
        """All messages of *conversation* in order, with their attachments
        and tapback reactions attached."""
        wanted = ("guid", "text", "attributedBody", "date", "date_read",
                  "is_from_me", "service", "associated_message_type",
                  "associated_message_guid", "item_type", "group_title",
                  "group_action_type", "cache_has_attachments")
        columns = ", ".join(self._column("message", name, "m")
                            for name in wanted)
        handle_id = self._column("handle", "id", "h")
        marks = ",".join("?" * len(conversation.chat_ids))
        rows = self.conn.execute(
            f"SELECT m.ROWID, cmj.chat_id, {columns}, {handle_id} "
            "FROM message m "
            "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
            "LEFT JOIN handle h ON h.ROWID = m.handle_id "
            f"WHERE cmj.chat_id IN ({marks}) "
            "ORDER BY m.date, m.ROWID", conversation.chat_ids).fetchall()

        messages, by_guid, reaction_rows = [], {}, []
        for row in rows:
            (rowid, chat_id, guid, text, body, date, read, from_me, service,
             assoc_type, assoc_guid, item_type, group_title, group_action,
             has_attachments, handle) = row
            who = "Me" if from_me else self.display_name(handle)
            if assoc_type in _ADD_RANGE or assoc_type in _REMOVE_RANGE:
                reaction_rows.append((assoc_type, assoc_guid, who, from_me,
                                      rowid, chat_id, date, text, body,
                                      guid, handle, service))
                continue
            message = Message(
                rowid=rowid, guid=guid, chat_id=chat_id,
                when=apple_time(date), read_when=apple_time(read),
                from_me=bool(from_me), sender=who, handle=handle,
                service=service, text=self._text_of(text, body))
            if item_type:
                message.kind = "event"
                message.text = self._event_text(
                    who, item_type, group_title, group_action,
                    message.text)
            messages.append(message)
            if guid:
                by_guid[guid] = message
        self._attach_files(messages)
        self._attach_reactions(messages, by_guid, reaction_rows)
        return messages

    @staticmethod
    def _event_text(who, item_type, group_title, group_action, text):
        if item_type == 2 and group_title:
            return f"{who} named the conversation \u201c{group_title}\u201d"
        if item_type == 1:
            return (f"{who} removed someone from the conversation"
                    if group_action == 1
                    else f"{who} added someone to the conversation")
        if item_type == 3:
            return f"{who} left the conversation"
        if item_type == 4:
            return text or f"{who} shared their location"
        return text or "(conversation event)"

    def _attach_files(self, messages):
        by_rowid = {m.rowid: m for m in messages}
        wanted = ("filename", "transfer_name", "mime_type", "uti",
                  "total_bytes", "is_sticker")
        columns = ", ".join(self._column("attachment", n, "a")
                            for n in wanted)
        ids = list(by_rowid)
        for start in range(0, len(ids), _CHUNK):
            chunk = ids[start:start + _CHUNK]
            marks = ",".join("?" * len(chunk))
            for (message_id, rowid, filename, transfer, mime, uti, size,
                 sticker) in self.conn.execute(
                    "SELECT maj.message_id, a.ROWID, " + columns +
                    " FROM message_attachment_join maj "
                    "JOIN attachment a ON a.ROWID = maj.attachment_id "
                    f"WHERE maj.message_id IN ({marks}) ORDER BY a.ROWID",
                    chunk):
                name = transfer or (filename or "").rsplit("/", 1)[-1] \
                    or "attachment"
                by_rowid[message_id].attachments.append(Attachment(
                    rowid, name, mime, uti, size,
                    attachment_backup_path(filename), bool(sticker)))

    @staticmethod
    def _attach_reactions(messages, by_guid, reaction_rows):
        removed = set()
        for (assoc_type, assoc_guid, who, from_me, *_rest) in reaction_rows:
            if assoc_type in _REMOVE_RANGE:
                removed.add((who, assoc_type - 1000,
                             _target_guid(assoc_guid)))
        for (assoc_type, assoc_guid, who, from_me, rowid, chat_id, date, text,
             body, guid, handle, service) in reaction_rows:
            if assoc_type not in _ADD_RANGE:
                continue
            target = _target_guid(assoc_guid)
            if (who, assoc_type, target) in removed:
                continue
            reaction = Reaction(_REACTION_NAMES[assoc_type], who,
                                bool(from_me))
            parent = by_guid.get(target)
            if parent is not None:
                parent.reactions.append(reaction)
            else:                    # the message it reacted to is gone
                messages.append(Message(
                    rowid=rowid, guid=guid, chat_id=chat_id,
                    when=apple_time(date), from_me=bool(from_me),
                    sender=who, handle=handle, service=service,
                    kind="event",
                    text=f"{who} {reaction.kind.lower()} a message"))
        messages.sort(key=lambda m: (m.when is None, m.when or 0, m.rowid))

    def attachment_paths(self, conversation=None):
        """``Domain/path`` of every attachment in the backup (of one
        conversation, or of all of them)."""
        sql = ("SELECT DISTINCT a.filename FROM attachment a "
               "JOIN message_attachment_join maj ON maj.attachment_id = a.ROWID ")
        params = []
        if conversation is not None:
            marks = ",".join("?" * len(conversation.chat_ids))
            sql += ("JOIN chat_message_join cmj ON cmj.message_id = "
                    f"maj.message_id WHERE cmj.chat_id IN ({marks}) ")
            params = list(conversation.chat_ids)
        paths = (attachment_backup_path(row[0])
                 for row in self.conn.execute(sql + "ORDER BY a.ROWID", params))
        return [p for p in paths if p]

    # -- searching --------------------------------------------

    def search(self, text, limit=500):
        """Messages containing *text*, ignoring case, newest first, as
        ``(conversation, message)`` pairs. Needs ``conversations()`` first.

        Messages whose text lives only in ``attributedBody`` are decoded
        and matched on the real text: searching the raw blob would also
        hit the archive's own bookkeeping strings.
        """
        needle = text.strip()
        if not needle:
            return []
        like = "%" + (needle.replace("\\", "\\\\").replace("%", "\\%")
                      .replace("_", "\\_")) + "%"
        columns = ", ".join(self._column("message", name, "m") for name in
                            ("guid", "text", "attributedBody", "date",
                             "is_from_me", "service"))
        base = (f"SELECT m.ROWID, cmj.chat_id, {columns}, "
                f"{self._column('handle', 'id', 'h')} FROM message m "
                "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
                "LEFT JOIN handle h ON h.ROWID = m.handle_id ")
        rows = list(self.conn.execute(
            base + "WHERE m.text LIKE ? ESCAPE '\\' "
            "ORDER BY m.date DESC LIMIT ?", (like, limit)))
        if "attributedBody" in self._columns["message"]:
            wanted = needle.casefold()
            matched = 0
            for row in self.conn.execute(
                    base + "WHERE (m.text IS NULL OR m.text = '') "
                    "AND m.attributedBody IS NOT NULL "
                    "ORDER BY m.date DESC"):
                decoded = self._text_of(None, row[4])
                if decoded and wanted in decoded.casefold():
                    rows.append(row)
                    matched += 1
                    if matched >= limit:
                        break
        found = []
        for row in rows:
            (rowid, chat_id, guid, body_text, body, date, from_me, service,
             handle) = row
            conv = self._chat_conversation.get(chat_id)
            if conv is None:
                continue
            found.append((conv, Message(
                rowid=rowid, guid=guid, chat_id=chat_id,
                when=apple_time(date), from_me=bool(from_me),
                sender="Me" if from_me else self.display_name(handle),
                handle=handle, service=service,
                text=self._text_of(body_text, body))))
        found.sort(key=lambda pair: (pair[1].when is None,
                                     -(pair[1].when or 0)))
        return found[:limit]


_GUID_PREFIX = re.compile(r"^(?:p:\d+/|bp:)")


def _target_guid(associated_guid):
    """The guid of the message a tapback refers to (``p:0/GUID``)."""
    return _GUID_PREFIX.sub("", associated_guid or "")
