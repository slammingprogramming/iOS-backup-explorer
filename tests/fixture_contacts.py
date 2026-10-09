# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake address book (AddressBook.sqlitedb) for tests.

Everything here is invented. The tables follow the layout iOS uses,
trimmed to what the reader looks at.
"""

from datetime import datetime, timezone

from tests.fixture_apps import database_bytes

SCHEMA = """
CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, First TEXT,
    Last TEXT, Middle TEXT, Prefix TEXT, Suffix TEXT, Nickname TEXT,
    Organization TEXT, Department TEXT, JobTitle TEXT, Birthday,
    Note TEXT, CreationDate INTEGER, ModificationDate INTEGER,
    Kind INTEGER DEFAULT 0);
CREATE TABLE ABMultiValue (UID INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER, property INTEGER, identifier INTEGER, label INTEGER,
    value TEXT);
CREATE TABLE ABMultiValueLabel (ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT);
CREATE TABLE ABMultiValueEntry (UID INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER, key INTEGER, value TEXT);
CREATE TABLE ABMultiValueEntryKey (ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT);
"""

PHONE, EMAIL, ADDRESS, IM, URL, RELATED, DATE = 3, 4, 5, 13, 22, 23, 12

LONG_NOTE = ("Line one\nLine two; with, specials \\ and unicode é 日本語 — "
             "and then a very long sentence that has to be folded in a vCard "
             "because it is far longer than seventy-five bytes.")


def apple_seconds(year, month, day):
    delta = (datetime(year, month, day, tzinfo=timezone.utc)
             - datetime(2001, 1, 1, tzinfo=timezone.utc))
    return int(delta.total_seconds())


def build(conn):
    conn.executescript(SCHEMA)
    labels = {}

    def label(text):
        if text is None:
            return None
        if text not in labels:
            labels[text] = conn.execute(
                "INSERT INTO ABMultiValueLabel (value) VALUES (?)",
                (text,)).lastrowid
        return labels[text]

    keys = {}
    for key in ("Street", "City", "State", "ZIP", "Country", "CountryCode",
                "username", "service"):
        keys[key] = conn.execute(
            "INSERT INTO ABMultiValueEntryKey (value) VALUES (?)",
            (key,)).lastrowid

    def person(**kw):
        names = ("First Last Middle Prefix Suffix Nickname Organization "
                 "Department JobTitle Birthday Note CreationDate "
                 "ModificationDate Kind").split()
        cur = conn.execute(
            "INSERT INTO ABPerson (" + ", ".join(names) + ") VALUES ("
            + ",".join("?" * len(names)) + ")",
            [kw.get(n) for n in names])
        return cur.lastrowid

    def value(record, prop, text, lab=None):
        return conn.execute(
            "INSERT INTO ABMultiValue (record_id, property, label, value) "
            "VALUES (?,?,?,?)", (record, prop, label(lab), text)).lastrowid

    def entries(uid, **parts):
        for key, text in parts.items():
            conn.execute("INSERT INTO ABMultiValueEntry (parent_id, key, "
                         "value) VALUES (?,?,?)", (uid, keys[key], text))

    alice = person(First="Alice", Last="Example", Organization="Example Corp",
                   Department="Research", JobTitle="Engineer",
                   Birthday=apple_seconds(1990, 5, 17),
                   Note="Met at the conference.\nLikes tea.",
                   CreationDate=700_000_000, ModificationDate=777_000_000)
    value(alice, PHONE, "(555) 010-1234", "_$!<Mobile>!$_")
    value(alice, PHONE, "+1 555 010 0000", "_$!<Work>!$_")
    value(alice, EMAIL, "alice@example.com", "_$!<Work>!$_")
    uid = value(alice, ADDRESS, None, "_$!<Home>!$_")
    entries(uid, Street="1 Main St", City="Springfield", State="IL",
            ZIP="62701", Country="United States", CountryCode="us")
    value(alice, URL, "https://example.com/alice", "_$!<HomePage>!$_")

    bob = person(First="Bob", Last="Sample", Nickname="Bobby",
                 Birthday="1985-12-01 00:00:00 +0000",
                 CreationDate=701_000_000, ModificationDate=701_000_000)
    value(bob, EMAIL, "Friend@Example.com", "_$!<Home>!$_")
    value(bob, PHONE, "+1 555 010 5678", "iPhone")

    pizza = person(Organization="Pizza Place", Kind=1)
    value(pizza, PHONE, "555-010-7777", "_$!<Main>!$_")
    uid = value(pizza, ADDRESS, None, "_$!<Work>!$_")
    entries(uid, Street="9 Oven Rd", City="Naples")

    mum = person(Nickname="Mum")
    value(mum, PHONE, "+44 20 7946 0000", "Mother's mobile")

    nameless = person()
    value(nameless, PHONE, "555-010-6666", None)

    zed = person(First="Zed", Middle="Q", Last="Zebra", Prefix="Dr.",
                 Suffix="Jr.", JobTitle="Zookeeper",
                 Birthday="--06-30")
    value(zed, RELATED, "Alice Example", "_$!<Spouse>!$_")
    value(zed, DATE, str(apple_seconds(2015, 8, 9)), "_$!<Anniversary>!$_")
    uid = value(zed, IM, None, "_$!<Home>!$_")
    entries(uid, username="zed.zebra", service="Skype")

    sam = person(First="Sam", Last="Smith, Jr.", Note=LONG_NOTE)
    value(sam, EMAIL, "sam@example.com", None)
    value(sam, PHONE, "", "_$!<Mobile>!$_")        # an empty value: ignored

    ghost = person(First="Orphan")                  # a person with nothing
    conn.execute("INSERT INTO ABMultiValue (record_id, property, label, "
                 "value) VALUES (999, 3, NULL, '555-0000')")  # belongs to no one
    conn.commit()
    return {"alice": alice, "bob": bob, "pizza": pizza, "mum": mum,
            "nameless": nameless, "zed": zed, "sam": sam, "ghost": ghost}


def backup_files():
    return [("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb",
             database_bytes(build))]
