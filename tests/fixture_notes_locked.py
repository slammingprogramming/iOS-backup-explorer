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
from tests.fixture_apps import PNG_BYTES

SHARED = "correct horse"          # locks "Bank PINs" and "Diary"
OTHER = "Zürich 2026"             # locks "Vault" (an accented letter)
HINT = "my city and a year"
ROUNDS = 1000                     # (iOS uses more; fewer keeps tests quick)

BANK, DIARY, VAULT, BROKEN = 40, 41, 42, 43
LOCKED_MEDIA = "MEDIA-LOCKED"
LOCKED_FILE = f"{fn.NOTES_ACCOUNT}/Media/{LOCKED_MEDIA}/1_GEN-L/{LOCKED_MEDIA}"
LOCKED_PLAIN = PNG_BYTES            # what the locked file holds
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
    for column in ("ZASSETCRYPTOINITIALIZATIONVECTOR", "ZASSETCRYPTOTAG"):
        conn.execute(f"ALTER TABLE ZICCLOUDSYNCINGOBJECT ADD COLUMN "
                     f"{column} BLOB")

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
    # a photo of the note "Bank PINs" that holds no lock details (the same
    # media file as note 10's): it cannot be opened
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZNOTE, ZIDENTIFIER, "
        "ZTYPEUTI, ZMEDIA) VALUES (44, 3, ?, ?, ?, 20)",
        (BANK, fn.PHOTO[0], fn.PHOTO[1]))
    # and a locked picture: its media row (no file name: that is locked
    # too) holds what opens the file
    salt, key, iv = b"m" * 16, b"n" * 16, b"o" * 16
    wrapped, tag, _data = notes_crypto.encrypt(SHARED, salt, ROUNDS, key, iv,
                                               LOCKED_PLAIN)
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZIDENTIFIER, "
        "ZCRYPTOSALT, ZCRYPTOWRAPPEDKEY, ZCRYPTOITERATIONCOUNT, "
        "ZASSETCRYPTOINITIALIZATIONVECTOR, ZASSETCRYPTOTAG) "
        "VALUES (45, 11, ?, ?, ?, ?, ?, ?)",
        (LOCKED_MEDIA, salt, wrapped, ROUNDS, iv, tag))
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZNOTE, ZIDENTIFIER, "
        "ZTYPEUTI, ZMEDIA) VALUES (46, 3, ?, 'ATT-LOCKED', 'public.png', 45)",
        (BANK,))
    conn.commit()


def locked_file():
    """What the backup holds for the locked picture: its data, locked."""
    salt, key, iv = b"m" * 16, b"n" * 16, b"o" * 16
    _wrapped, _tag, data = notes_crypto.encrypt(SHARED, salt, ROUNDS, key, iv,
                                                LOCKED_PLAIN)
    return data


def backup_files():
    """The ``(domain, path, bytes)`` list for a backup with these notes."""
    from tests.fixture_apps import database_bytes
    files = fn.backup_files()
    files = [(domain, path, database_bytes(build)
              if path == "NoteStore.sqlite" else data)
             for domain, path, data in files]
    return files + [(fn.NOTES_DOMAIN, LOCKED_FILE.split(
        fn.NOTES_DOMAIN + "/")[-1], locked_file())]
