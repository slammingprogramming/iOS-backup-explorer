# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake voicemail folder for tests. Everything here is invented."""

import plistlib

from tests.fixture_apps import build_addressbook, database_bytes

FOLDER = "Library/Voicemail"
UNIX0 = 1_750_000_000          # 2025-06-15, in seconds since 1970


def transcript_bytes(text, pieces=None, whole=True):
    """A ``.transcript`` file: an archived object with the whole text and
    the words it is made of (the pieces)."""
    pieces = pieces if pieces is not None else text.split()
    uid = plistlib.UID
    objects = ["$null", None, {"$classname": "VMTranscript"}, text,
               {"$class": uid(5), "NS.objects": []}, {"$classname": "NSArray"},
               {"$classname": "VMSegment"}]
    root = {"$class": uid(2), "confidence": 0.9, "segments": uid(4)}
    if whole:
        root["transcriptionString"] = uid(3)
    objects[1] = root
    for piece in pieces:
        objects.append(piece)
        objects.append({"$class": uid(6), "substring": uid(len(objects) - 1),
                        "duration": 0.5})
        objects[4]["NS.objects"].append(uid(len(objects) - 1))
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000,
                           "$top": {"root": uid(1)}, "$objects": objects},
                          fmt=plistlib.FMT_BINARY)


def build(conn):
    conn.executescript("""
        CREATE TABLE voicemail (ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            remote_uid INTEGER, date INTEGER, token TEXT, sender TEXT,
            callback_num TEXT, duration INTEGER, expiration INTEGER,
            trashed_date INTEGER, flags INTEGER, receiver TEXT, label TEXT);
        CREATE TABLE map (ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT, label TEXT);
    """)
    conn.executemany(
        "INSERT INTO voicemail (ROWID, remote_uid, date, sender, "
        "callback_num, duration, expiration, trashed_date, flags, label) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", [
            (3, 101, UNIX0, "+15550101234", "+15550101234", 34,
             UNIX0 + 5_000_000, 0, 4354, ""),               # Alice
            (4, 102, UNIX0 + 3600, "5550107777", "5550107777", 30,
             UNIX0 + 5_000_000, 0, 4355, ""),               # Pizza Place
            (5, 103, UNIX0 + 7200, "5559990000", "5559990001", 43,
             UNIX0 + 5_000_000, UNIX0 + 9000, 4354, ""),    # unknown, deleted
            (6, 104, UNIX0 + 10800, "", "5551112222", 0, 0, 0, 4354, ""),
            (7, 105, UNIX0 + 14400, "5550106666", "", 15, 0, 0, 4354, ""),
            (8, 106, UNIX0 - 86400, "5550101234", "", 20, 0, 0, 4354, ""),
        ])
    conn.execute("INSERT INTO map (account, label) VALUES ('1', 'x')")
    conn.commit()


def backup_files(audio=True, transcripts=True, contacts=True):
    files = [("HomeDomain", f"{FOLDER}/voicemail.db", database_bytes(build))]
    if contacts:
        files.append(("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb",
                      database_bytes(build_addressbook)))
    if audio:
        for number in (3, 4, 5, 6, 7):          # 8 has no recording
            files.append(("HomeDomain", f"{FOLDER}/{number}.amr",
                          b"#!AMR\n" + bytes([number]) * 40))
    if transcripts:
        files.append(("HomeDomain", f"{FOLDER}/3.transcript",
                      transcript_bytes("Hi, it is Alice calling about "
                                       "dinner.")))
        files.append(("HomeDomain", f"{FOLDER}/4.transcript",
                      transcript_bytes("", ["Your", "pizza", "is", "ready"],
                                       whole=False)))
        files.append(("HomeDomain", f"{FOLDER}/5.transcript",
                      b"not an archive"))                # unreadable
        files.append(("HomeDomain", f"{FOLDER}/7.transcript",
                      transcript_bytes("")))             # nothing was said
    return files
