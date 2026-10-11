# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Opening a note that is locked with a password.

A locked note keeps its text encrypted in ``ZICNOTEDATA.ZDATA``. What is
needed to open it is stored beside it:

====================================  =====================================
``ZICCLOUDSYNCINGOBJECT.ZCRYPTOSALT``     the salt for the password
``...ZCRYPTOITERATIONCOUNT``              PBKDF2 rounds
``...ZCRYPTOWRAPPEDKEY``                  the note's own key, wrapped
``ZICNOTEDATA.ZCRYPTOINITIALIZATIONVECTOR``  the AES-GCM nonce
``ZICNOTEDATA.ZCRYPTOTAG``                the AES-GCM authentication tag
====================================  =====================================

The scheme (from the published research on Apple Notes, not from Apple):

1. the key-encryption key is ``PBKDF2-HMAC-SHA256(password, salt,
   iterations)``, 16 bytes;
2. the note's key is that key's RFC 3394 AES key unwrap of the wrapped key;
3. the text is AES-GCM, with the note's key, the stored nonce and tag. What
   comes out is what an unlocked note holds: gzip-compressed protobuf.

A wrong password fails twice over: the key unwrap checks its own integrity
value, and AES-GCM checks the tag. So **a result is never wrong text**: it is
the note, or a ``WrongPassword``. That makes the scheme safe to try against
every locked note.

The steps and the table each value is read from agree with Apple's Platform
Security Guide and with two open-source tools used on real notes (hashcat's
Apple Secure Notes module and the Apple Cloud Notes Parser). This module has
been checked against the RFC 3394 test vector, a PBKDF2-SHA256 vector and by
round trips, but **not against a real locked note** (the backup it was written
against held none); see ``docs/apps/notes.md``.

Needs ``pycryptodome`` (installed with ``iphone_backup_decrypt``), loaded only
when a locked note is opened.
"""

import hashlib
import struct
import unicodedata

_DEFAULT_IV = b"\xa6" * 8            # RFC 3394, section 2.2.3.1


class WrongPassword(ValueError):
    """The password does not open this note (or its data is damaged)."""


class Unavailable(RuntimeError):
    """The cryptography package is not installed."""


def _aes():
    try:
        from Crypto.Cipher import AES
    except ImportError as exc:                     # pragma: no cover
        raise Unavailable(
            "Opening locked notes needs the pycryptodome package "
            "(pip install -r requirements.txt)") from exc
    return AES


def key_unwrap(kek, wrapped):
    """RFC 3394 AES key unwrap; ``WrongPassword`` if the integrity value is
    not the expected one (which is what a wrong key looks like)."""
    if len(wrapped) < 24 or len(wrapped) % 8:
        raise WrongPassword("the wrapped key has a wrong length")
    AES = _aes()
    cipher = AES.new(kek, AES.MODE_ECB)
    blocks = [wrapped[i:i + 8] for i in range(0, len(wrapped), 8)]
    a, r = blocks[0], blocks[1:]
    n = len(r)
    for j in range(5, -1, -1):
        for i in range(n, 0, -1):
            t = n * j + i
            b = cipher.decrypt(
                struct.pack(">Q", struct.unpack(">Q", a)[0] ^ t)
                + r[i - 1])
            a, r[i - 1] = b[:8], b[8:]
    if a != _DEFAULT_IV:
        raise WrongPassword("the key does not unwrap")
    return b"".join(r)


def key_wrap(kek, key):
    """RFC 3394 AES key wrap (used by the tests to make locked notes)."""
    AES = _aes()
    cipher = AES.new(kek, AES.MODE_ECB)
    r = [key[i:i + 8] for i in range(0, len(key), 8)]
    n = len(r)
    a = _DEFAULT_IV
    for j in range(6):
        for i in range(1, n + 1):
            b = cipher.encrypt(a + r[i - 1])
            t = n * j + i
            a = struct.pack(">Q", struct.unpack(">Q", b[:8])[0] ^ t)
            r[i - 1] = b[8:]
    return a + b"".join(r)


def spellings(password):
    """The ways a typed password may have been stored: as typed, and in the
    two Unicode normal forms (an accented letter can be one character or
    two, and a keyboard does not say which)."""
    seen, found = set(), []
    for text in (password, unicodedata.normalize("NFC", password),
                 unicodedata.normalize("NFD", password)):
        raw = text.encode("utf-8")
        if raw not in seen:
            seen.add(raw)
            found.append(raw)
    return found


def derive_key(password, salt, iterations, length=16):
    """The key-encryption key for *password* (bytes)."""
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, length)


def decrypt(password, salt, iterations, wrapped_key, iv, tag, data):
    """The plaintext of a locked note's data, or ``WrongPassword``.

    *password* is the text the person typed.
    """
    if not (salt and iterations and wrapped_key and iv and tag and data):
        raise WrongPassword("this note's encryption details are incomplete")
    AES = _aes()
    for raw in spellings(password):
        try:
            key = key_unwrap(derive_key(raw, salt, int(iterations)),
                             wrapped_key)
        except WrongPassword:
            continue
        if len(key) not in (16, 24, 32):
            continue
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
            return cipher.decrypt_and_verify(data, tag)
        except ValueError:
            continue
    raise WrongPassword("the password does not open this note")


def encrypt(password, salt, iterations, key, iv, data):
    """Lock *data* the way a note is locked: ``(wrapped_key, tag,
    ciphertext)``. For the tests, and nothing else."""
    AES = _aes()
    wrapped = key_wrap(derive_key(password.encode("utf-8"), salt, iterations),
                       key)
    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return wrapped, tag, ciphertext
