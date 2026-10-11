# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The usual fake Notes database plus notes locked with passwords.

Everything is invented. The notes are locked with ``ios_apps.notes_crypto``'s
own ``encrypt``, so these tests show that locking and unlocking agree with
each other and with the RFC 3394 and AES-GCM primitives; they cannot show that
the scheme is the one Apple uses (see ``docs/apps/notes.md``).
"""

from ios_apps import notes_crypto
from tests import fixture_notes as fn

SHARED = "correct horse"          # locks "Bank PINs" and "Diary"
OTHER = "Zürich 2026"             # locks "Vault" (an accented letter)
HINT = "my city and a year"
ROUNDS = 1000                     # (iOS uses more; fewer keeps tests quick)

BANK, DIARY, VAULT, BROKEN = 40, 41, 42, 43
BANK_TEXT = "PIN for the card is 4821\n"
DIARY_TEXT = "Dear diary, nothing happened.\n"
VAULT_TEXT = "The vault holds a spare key.\n"


def _lock(pk, password, runs):
    salt = bytes([pk]) * 16
    key = bytes([pk + 1]) * 16
    iv = bytes([pk + 2]) * 16
    wrapped, tag, data = notes_crypto.encrypt(
        password, salt, ROUNDS, key, iv, fn.blob(runs))
    return salt, wrapped, iv, tag, data


def build(conn):
    """The usual database; note 40 "Bank PINs" and 41 "Diary" are locked with
    SHARED, 42 "Vault" with OTHER (and has a hint), and 43 "Broken" claims to
    be locked but holds no encryption details."""
    fn.build(conn)
    for column, kind in (("ZCRYPTOSALT", "BLOB"), ("ZCRYPTOWRAPPEDKEY", "BLOB"),
                         ("ZCRYPTOITERATIONCOUNT", "INTEGER"),
                         ("ZPASSWORDHINT", "VARCHAR")):
        conn.execute(f"ALTER TABLE ZICCLOUDSYNCINGOBJECT ADD COLUMN "
                     f"{column} {kind}")
    for column in ("ZCRYPTOINITIALIZATIONVECTOR", "ZCRYPTOTAG"):
        conn.execute(f"ALTER TABLE ZICNOTEDATA ADD COLUMN {column} BLOB")

    def locked(pk, title, password, text, hint=None, runs=None):
        salt, wrapped, iv, tag, data = _lock(
            pk, password, runs or [fn.run(title + "\n", style=0),
                                    fn.run(text)])
        conn.execute(
            "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZTITLE1, "
            "ZFOLDER, ZACCOUNT3, ZCREATIONDATE3, ZMODIFICATIONDATE1, "
            "ZIDENTIFIER, ZISPASSWORDPROTECTED, ZCRYPTOSALT, "
            "ZCRYPTOWRAPPEDKEY, ZCRYPTOITERATIONCOUNT, ZPASSWORDHINT) "
            "VALUES (?, 8, ?, 2, 1, 760000000, ?, ?, 1, ?, ?, ?, ?)",
            (pk, title, 770_000_000 - pk, f"NOTE-{pk}", salt, wrapped,
             ROUNDS, hint))
        conn.execute(
            "INSERT INTO ZICNOTEDATA (ZNOTE, ZDATA, "
            "ZCRYPTOINITIALIZATIONVECTOR, ZCRYPTOTAG) VALUES (?, ?, ?, ?)",
            (pk, data, iv, tag))

    locked(BANK, "Bank PINs", SHARED, BANK_TEXT, runs=[
        fn.run("Bank PINs\n", style=0), fn.run(BANK_TEXT),
        fn.run("￼", attachment=fn.PHOTO), fn.run("\n")])
    locked(DIARY, "Diary", SHARED, DIARY_TEXT)
    locked(VAULT, "Vault", OTHER, VAULT_TEXT, hint=HINT)
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZTITLE1, ZFOLDER, "
        "ZACCOUNT3, ZCREATIONDATE3, ZMODIFICATIONDATE1, ZIDENTIFIER, "
        "ZISPASSWORDPROTECTED) VALUES (?, 8, 'Broken lock', 2, 1, 1, 770000000"
        ", 'NOTE-43', 1)", (BROKEN,))
    conn.execute("INSERT INTO ZICNOTEDATA (ZNOTE, ZDATA) VALUES (?, ?)",
                 (BROKEN, b"not encrypted data"))
    # the photo of the note "Bank PINs" (the same media file as note 10's)
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZNOTE, ZIDENTIFIER, "
        "ZTYPEUTI, ZMEDIA) VALUES (44, 3, ?, ?, ?, 20)",
        (BANK, fn.PHOTO[0], fn.PHOTO[1]))
    conn.commit()


def backup_files():
    """The ``(domain, path, bytes)`` list for a backup with these notes."""
    from tests.fixture_apps import database_bytes
    files = fn.backup_files()
    return [(domain, path, database_bytes(build) if path == "NoteStore.sqlite"
             else data) for domain, path, data in files]
