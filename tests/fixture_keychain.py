# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake keychain for tests: ``keychain-backup.plist`` with invented items,
and a fake backup key bag, made with ``ios_apps.keychain_crypto``'s own
helpers.

Everything is invented. Because the items are locked by the same module that
opens them, the tests show that locking and opening agree and that the pieces
(RFC 3394, GCM, DER) behave as their standards say; they cannot show that a
real phone's keychain looks like this (see ``docs/apps/keychain.md``).
"""

import plistlib
import struct
from datetime import datetime, timezone

from ios_apps import keychain_crypto as kc
from ios_apps import notes_crypto

PASSWORD = "backup password"
# invented class keys (a real backup holds random ones)
CLASS_KEYS = {6: b"\x06" * 32, 7: b"\x07" * 32, 8: b"\x08" * 32}


# ── DER ──────────────────────────────────────────────────────

def _length(n):
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def der(tag, body):
    return bytes([tag]) + _length(len(body)) + body


def der_value(value):
    """The DER of a Python value, the way the keychain stores attributes."""
    if isinstance(value, bool):
        return der(0x01, b"\xff" if value else b"\x00")
    if isinstance(value, int):
        size = max(1, (value.bit_length() + 8) // 8)
        return der(0x02, value.to_bytes(size, "big", signed=True))
    if isinstance(value, str):
        return der(0x0C, value.encode("utf-8"))
    if isinstance(value, bytes):
        return der(0x04, value)
    if isinstance(value, datetime):
        return der(0x18, value.strftime("%Y%m%d%H%M%SZ").encode("ascii"))
    if value is None:
        return der(0x05, b"")
    raise TypeError(type(value))


def der_attributes(attrs):
    """A SET of SEQUENCE(name, value), as in a version 3 item."""
    pairs = b"".join(der(0x30, der_value(k) + der_value(v))
                     for k, v in attrs.items())
    return der(0x31, pairs)


# ── Items ────────────────────────────────────────────────────

def make_item(attrs, clas=6, class_keys=None, version=3, item_key=None):
    """The ``v_Data`` blob of an item holding *attrs*."""
    class_keys = class_keys or CLASS_KEYS
    item_key = item_key or bytes([clas + 40]) * 32
    wrapped = notes_crypto.key_wrap(class_keys[clas] if clas in class_keys
                                    else b"\x00" * 32, item_key)
    plain = (der_attributes(attrs) if version == 3
             else plistlib.dumps(attrs, fmt=plistlib.FMT_BINARY))
    ciphertext, tag = kc.gcm_encrypt(item_key, b"", plain)
    return struct.pack("<III", version, clas, len(wrapped)) + wrapped \
        + ciphertext + tag


WHEN = datetime(2024, 3, 5, 14, 30, 0, tzinfo=timezone.utc)
LATER = datetime(2025, 1, 20, 9, 15, 30, tzinfo=timezone.utc)

# (kind, attributes, protection class); the passwords are invented
ITEMS = [
    ("genp", {"svce": "AirPort", "acct": "Cafe Wifi",
              "agrp": "apple", "cdat": WHEN, "mdat": LATER, "sync": 0,
              "v_Data": b"espresso2024"}, 7),
    ("genp", {"svce": "Example Mail", "acct": "pat@example.com",
              "agrp": "com.example.mail", "labl": "Example Mail",
              "cdat": WHEN, "mdat": WHEN, "sync": 1,
              "v_Data": "mail password"}, 6),
    ("genp", {"svce": "Notes token", "acct": "token", "agrp": "com.example.n",
              "cdat": WHEN, "mdat": WHEN, "v_Data": bytes(range(1, 17))}, 8),
    ("genp", {"svce": "Deleted thing", "acct": "gone", "tomb": 1,
              "cdat": WHEN, "mdat": LATER, "v_Data": b"old"}, 6),
    ("inet", {"srvr": "www.example.com", "ptcl": "htps", "port": 443,
              "path": "/login", "acct": "taylor", "atyp": "form",
              "agrp": "com.apple.cfnetwork", "cdat": WHEN, "mdat": LATER,
              "v_Data": b"s3cret! \xe2\x9c\x93"}, 6),
    ("inet", {"srvr": "imap.example.org", "ptcl": "imps", "port": 993,
              "path": "", "acct": "taylor@example.org", "cdat": WHEN,
              "mdat": WHEN, "v_Data": b"imap-pass"}, 7),
    ("cert", {"labl": "Example CA", "subj": b"\x30\x00", "cdat": WHEN,
              "mdat": WHEN, "v_Data": b"\x30\x82\x01\x00certificate-bytes"},
     7),
    ("keys", {"labl": "Example key", "klbl": b"\x01\x02\x03", "kcls": 1,
              "cdat": WHEN, "mdat": WHEN, "v_Data": b"private-key-bytes"}, 7),
    # tied to the phone: the backup has no key for these
    ("genp", {"svce": "Device only", "acct": "x", "v_Data": b"nope"}, 10),
    ("inet", {"srvr": "device.example.com", "acct": "y", "v_Data": b"no"}, 9),
]


def keychain_plist(items=None, class_keys=None, extra=None):
    """The bytes of ``keychain-backup.plist``."""
    lists = {"genp": [], "inet": [], "cert": [], "keys": []}
    for number, (kind, attrs, clas) in enumerate(items or ITEMS):
        lists[kind].append({
            "v_Data": make_item(attrs, clas, class_keys),
            "v_PersistentRef": struct.pack(">I", number) * 3})
    lists["keybag-uuid"] = "00000000-0000-0000-0000-000000000000"
    lists.update(extra or {})
    return plistlib.dumps(lists, fmt=plistlib.FMT_BINARY)


# ── The key bag ──────────────────────────────────────────────

def _entry(tag, value):
    if isinstance(value, int):
        value = struct.pack(">L", value)
    return tag + struct.pack(">L", len(value)) + value


def keybag_blob(password=PASSWORD, class_keys=None, dpic=7, iterations=5,
                claimed_dpic=None, claimed_iterations=None,
                device_wrapped=()):
    """A backup key bag that *password* unlocks, holding *class_keys*. The
    round counts it states can be made to differ from the real ones."""
    import hashlib
    class_keys = class_keys or CLASS_KEYS
    dpsl, salt = b"D" * 20, b"S" * 20
    first = hashlib.pbkdf2_hmac("sha256", password.encode(), dpsl, dpic, 32)
    key = hashlib.pbkdf2_hmac("sha1", first, salt, iterations, 32)
    blob = (_entry(b"VERS", 5) + _entry(b"TYPE", 1)
            + _entry(b"UUID", b"U" * 16) + _entry(b"HMCK", b"H" * 40)
            + _entry(b"WRAP", 1) + _entry(b"SALT", salt)
            + _entry(b"ITER", claimed_iterations if claimed_iterations
                     is not None else iterations)
            + _entry(b"DPWT", 0)
            + _entry(b"DPIC", claimed_dpic or dpic) + _entry(b"DPSL", dpsl))
    for number, class_key in class_keys.items():
        blob += (_entry(b"UUID", bytes([number]) * 16)
                 + _entry(b"CLAS", number) + _entry(b"WRAP", 2)
                 + _entry(b"KTYP", 0)
                 + _entry(b"WPKY", notes_crypto.key_wrap(key, class_key)))
    for number in device_wrapped:
        # a class wrapped with the phone's own key: the password cannot open it
        blob += (_entry(b"UUID", bytes([number]) * 16)
                 + _entry(b"CLAS", number) + _entry(b"WRAP", 1)
                 + _entry(b"KTYP", 0) + _entry(b"WPKY", b"\xee" * 40))
    return blob
