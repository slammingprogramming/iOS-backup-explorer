# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Fake app databases (Messages, Contacts, ...) for tests.

Everything here is invented. The tables and columns follow the layout iOS
uses, trimmed to what the readers look at, and include the awkward cases
the readers have to cope with.
"""

import os
import shutil
import sqlite3
import struct
import tempfile
import zlib

# A moment in September 2026, in seconds since 2001-01-01.
T0 = 778_000_000
NS = 1_000_000_000

LONG_TEXT = ("This is a long message, long enough that its length no longer "
             "fits in a single byte inside the archived text. ") * 3

def make_png(width=1, height=1, colour=(200, 30, 30)):
    """A small, valid PNG picture of one colour."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    rows = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


PNG_BYTES = make_png(2, 2)
NOTES_TXT = b"remember the milk\n"

ATTACHMENT_PATHS = {
    "photo": "Library/SMS/Attachments/ab/11/GUID-A1/photo.png",
    "notes": "Library/SMS/Attachments/cd/22/GUID-A2/notes.txt",
}


def attributed_body(text):
    """An ``attributedBody`` blob holding *text*, laid out the way iOS does:
    an archived NSAttributedString whose NSString is introduced by ``+`` and
    a length."""
    raw = text.encode("utf-8")
    if len(raw) < 0x80:
        length = bytes([len(raw)])
    elif len(raw) < 0x10000:
        length = b"\x81" + len(raw).to_bytes(2, "little")
    else:
        length = b"\x82" + len(raw).to_bytes(4, "little")
    return (b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12"
            b"NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84"
            b"\x84\x08NSString\x01\x94\x84\x01+" + length + raw +
            b"\x86\x84\x02iI\x01" + bytes([min(len(text), 127)]) +
            b"\x92\x84\x84\x84\x0cNSDictionary\x00\x94\x84\x01i\x01\x92\x84"
            b"\x96\x96\x1d__kIMMessagePartAttributeName\x86\x86\x86")


SMS_SCHEMA = """
CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT, text TEXT,
    attributedBody BLOB, handle_id INTEGER DEFAULT 0, service TEXT,
    date INTEGER, date_read INTEGER, is_from_me INTEGER DEFAULT 0,
    cache_has_attachments INTEGER DEFAULT 0, item_type INTEGER DEFAULT 0,
    group_title TEXT, group_action_type INTEGER DEFAULT 0,
    associated_message_guid TEXT, associated_message_type INTEGER DEFAULT 0);
CREATE TABLE handle (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT,
    service TEXT);
CREATE TABLE chat (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT,
    style INTEGER, chat_identifier TEXT, service_name TEXT,
    room_name TEXT, display_name TEXT);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER,
    message_date INTEGER DEFAULT 0);
CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT,
    filename TEXT, transfer_name TEXT, mime_type TEXT, uti TEXT,
    total_bytes INTEGER, is_sticker INTEGER DEFAULT 0);
CREATE TABLE message_attachment_join (message_id INTEGER,
    attachment_id INTEGER);
"""

# Older iOS: no attributedBody, no tapbacks, no group events.
OLD_SMS_SCHEMA = """
CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT, text TEXT,
    handle_id INTEGER DEFAULT 0, service TEXT, date INTEGER,
    is_from_me INTEGER DEFAULT 0, cache_has_attachments INTEGER DEFAULT 0);
CREATE TABLE handle (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT,
    service TEXT);
CREATE TABLE chat (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT,
    chat_identifier TEXT, service_name TEXT);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT, mime_type TEXT, total_bytes INTEGER);
CREATE TABLE message_attachment_join (message_id INTEGER,
    attachment_id INTEGER);
"""


def build_sms_db(conn):
    """Fill *conn* with the Messages scenario the tests rely on."""
    conn.executescript(SMS_SCHEMA)
    conn.executemany("INSERT INTO handle (id, service) VALUES (?, ?)", [
        ("+15550101234", "iMessage"),     # 1  Alice
        ("+15550101234", "SMS"),          # 2  Alice again, over SMS
        ("friend@example.com", "iMessage"),   # 3  Bob, by email
        ("+15550105678", "iMessage"),     # 4  Bob, by phone (group)
        ("+15550109999", "SMS"),          # 5  nobody in the address book
    ])
    conn.executemany(
        "INSERT INTO chat (guid, style, chat_identifier, service_name, "
        "room_name, display_name) VALUES (?, ?, ?, ?, ?, ?)", [
            ("iMessage;-;+15550101234", 45, "+15550101234", "iMessage",
             None, None),                                     # 1
            ("SMS;-;+15550101234", 45, "+15550101234", "SMS", None, None),
            ("iMessage;-;friend@example.com", 45, "friend@example.com",
             "iMessage", None, None),                         # 3
            ("iMessage;+;chat123", 43, "chat123", "iMessage", "chat123",
             "Weekend Plans"),                                # 4 group
            ("iMessage;-;+15550100000", 45, "+15550100000", "iMessage",
             None, None),                                     # 5 empty
            ("SMS;-;+15550109999", 45, "+15550109999", "SMS", None, None),
        ])
    conn.executemany("INSERT INTO chat_handle_join VALUES (?, ?)",
                     [(1, 1), (2, 2), (3, 3), (4, 1), (4, 4), (4, 5),
                      (6, 5)])

    def message(guid, chat, text=None, body=None, handle=0, service="iMessage",
                when=0, from_me=0, attachments=0, item_type=0, title=None,
                action=0, assoc_guid=None, assoc_type=0, ns=True, read=0):
        stamp = (T0 + when) * (NS if ns else 1) if ns else T0 + when
        cur = conn.execute(
            "INSERT INTO message (guid, text, attributedBody, handle_id, "
            "service, date, date_read, is_from_me, cache_has_attachments, "
            "item_type, group_title, group_action_type, "
            "associated_message_guid, associated_message_type) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (guid, text, body, handle, service, stamp,
             stamp + read * NS if read else 0, from_me, attachments,
             item_type, title, action, assoc_guid, assoc_type))
        conn.execute("INSERT INTO chat_message_join VALUES (?, ?, ?)",
                     (chat, cur.lastrowid, stamp))
        return cur.lastrowid

    message("G-M1", 1, "Hey, are you free tonight?", handle=1, when=0,
            read=5)
    message("G-M2", 1, "Yes! What time?", from_me=1, when=60)
    message("G-M3", 1, None, attributed_body("Around 7 — see you "
                                            "there \U0001F389"),
            handle=1, when=120)
    message("G-T1", 1, "Liked “Around 7”", from_me=1, when=130,
            assoc_guid="p:0/G-M3", assoc_type=2001)
    message("G-T2", 1, "Loved “Yes! What time?”", handle=1,
            when=140, assoc_guid="p:0/G-M2", assoc_type=2000)
    message("G-T3", 1, "Removed a heart", handle=1, when=150,
            assoc_guid="p:0/G-M2", assoc_type=3000)
    m5 = message("G-M5", 1, "￼", handle=1, when=200, attachments=1)
    message("G-M5b", 1, "A caption with the photo", handle=1, when=201)
    # an older SMS thread with the same person: dates in plain seconds
    message("G-M8", 2, "Old SMS from before iMessage", handle=2,
            service="SMS", when=-5_000_000, ns=False)
    message("G-M9", 3, None, attributed_body(LONG_TEXT), handle=3, when=30)
    # a group conversation
    message("G-M10", 4, "Who's bringing snacks?", handle=4, when=300)
    message("G-M11", 4, "I will", from_me=1, when=310)
    message("G-M12", 4, None, handle=1, when=320, item_type=2,
            title="Weekend Plans")
    message("G-M13", 4, None, handle=5, when=330, item_type=3)
    message("G-T4", 4, "Laughed at a message", handle=4, when=340,
            assoc_guid="p:0/G-GONE", assoc_type=2003)    # target missing
    message("G-M14", 6, "Your code is 123456", handle=5, service="SMS",
            when=400)

    conn.executemany(
        "INSERT INTO attachment (guid, filename, transfer_name, mime_type, "
        "uti, total_bytes) VALUES (?, ?, ?, ?, ?, ?)", [
            ("GUID-A1", "~/" + ATTACHMENT_PATHS["photo"], "photo.png",
             "image/png", "public.png", len(PNG_BYTES)),
            ("GUID-A2", "~/" + ATTACHMENT_PATHS["notes"], "notes.txt",
             "text/plain", "public.plain-text", len(NOTES_TXT)),
        ])
    conn.executemany("INSERT INTO message_attachment_join VALUES (?, ?)",
                     [(m5, 1), (m5, 2)])
    conn.commit()


def build_old_sms_db(conn):
    """A pared-down database from an old iOS version."""
    conn.executescript(OLD_SMS_SCHEMA)
    conn.execute("INSERT INTO handle (id, service) VALUES ('+15550101234', "
                 "'SMS')")
    conn.execute("INSERT INTO chat (guid, chat_identifier, service_name) "
                 "VALUES ('SMS;-;+15550101234', '+15550101234', 'SMS')")
    conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
    for n, (text, from_me) in enumerate([("hello from 2015", 0),
                                         ("hi!", 1)]):
        conn.execute("INSERT INTO message (guid, text, handle_id, service, "
                     "date, is_from_me) VALUES (?, ?, 1, 'SMS', ?, ?)",
                     (f"OLD-{n}", text, 450_000_000 + n * 60, from_me))
        conn.execute("INSERT INTO chat_message_join VALUES (1, ?)", (n + 1,))
    conn.commit()


ADDRESSBOOK_SCHEMA = """
CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, First TEXT,
    Last TEXT, Middle TEXT, Organization TEXT, Nickname TEXT);
CREATE TABLE ABMultiValue (UID INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER, property INTEGER, identifier INTEGER, label INTEGER,
    value TEXT);
"""


def build_addressbook(conn):
    conn.executescript(ADDRESSBOOK_SCHEMA)
    conn.executemany(
        "INSERT INTO ABPerson (First, Last, Organization, Nickname) "
        "VALUES (?, ?, ?, ?)", [
            ("Alice", "Example", None, None),     # 1
            ("Bob", "Sample", None, None),        # 2
            (None, None, "Pizza Place", None),    # 3
            (None, None, None, "Mum"),            # 4
            (None, None, None, None),             # 5 (no name at all)
        ])
    conn.executemany(
        "INSERT INTO ABMultiValue (record_id, property, label, value) "
        "VALUES (?, ?, 0, ?)", [
            (1, 3, "(555) 010-1234"),
            (2, 4, "Friend@Example.com"),
            (2, 3, "+1 555 010 5678"),
            (3, 3, "555-010-7777"),
            (4, 3, "+44 20 7946 0000"),
            (5, 3, "555-010-6666"),
            (1, 5, "somewhere"),                  # not a phone or an email
        ])
    conn.commit()


def database_bytes(builder):
    """The bytes of a new database filled in by ``builder(conn)``."""
    folder = tempfile.mkdtemp(prefix="ibe-appdb-")
    try:
        path = os.path.join(folder, "x.db")
        conn = sqlite3.connect(path)
        builder(conn)
        conn.close()
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def sms_db_with_wal():
    """``(db, wal, shm)`` bytes where the newest message exists *only* in
    the write-ahead log, as happens on a live phone."""
    folder = tempfile.mkdtemp(prefix="ibe-appdb-")
    try:
        path = os.path.join(folder, "sms.db")
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_autocheckpoint = 0")
        build_sms_db(conn)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        cur = conn.execute(
            "INSERT INTO message (guid, text, handle_id, service, date, "
            "is_from_me) VALUES ('G-WAL', 'Only in the WAL', 1, 'iMessage', "
            "?, 0)", ((T0 + 999) * NS,))
        conn.execute("INSERT INTO chat_message_join VALUES (1, ?, ?)",
                     (cur.lastrowid, (T0 + 999) * NS))
        conn.commit()
        blobs = []
        for suffix in ("", "-wal", "-shm"):
            with open(path + suffix, "rb") as handle:
                blobs.append(handle.read())
        conn.close()
        return tuple(blobs)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
