# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The keychain of an encrypted backup: saved passwords, Wi-Fi passwords,
certificates and keys. No GUI.

``keychain-backup.plist`` is opened with the class keys of the backup's key bag
(see ``keychain_crypto``). What opens is shown; what cannot be opened (the
"this device only" items, which no backup can unlock) is counted and
explained, never guessed at.

The values are shown in the clear: opening this tab means looking at your own
passwords. Exports that hold them are confirmed by the tab.
"""

import plistlib
from collections import Counter

from . import keychain_crypto as kc
from .records import Column, Dataset

PATH = "KeychainDomain/keychain-backup.plist"
KINDS = {"genp": "Password", "inet": "Website or server password",
         "cert": "Certificate", "keys": "Key"}

_PROTOCOLS = {"htps": "https", "http": "http", "ftp": "ftp", "ftps": "ftps",
              "imap": "imap", "imps": "imaps", "pop3": "pop3",
              "pops": "pop3s", "smtp": "smtp", "ssh": "ssh", "ldap": "ldap",
              "ldps": "ldaps", "smb": "smb", "afp": "afp", "nntp": "nntp",
              "tlnt": "telnet", "rtsp": "rtsp", "irc": "irc"}
_PLAIN_PORTS = {0, 80, 443}


class Item:
    """One keychain item: its kind, protection class and attributes."""

    def __init__(self, kind, clas, attrs):
        self.kind, self.clas, self.attrs = kind, clas, attrs


def read_plist(source):
    """The lists of ``keychain-backup.plist`` (a path or its bytes)."""
    if isinstance(source, (bytes, bytearray)):
        data = plistlib.loads(source)
    else:
        with open(source, "rb") as handle:
            data = plistlib.load(handle)
    if not isinstance(data, dict):
        raise ValueError("the keychain file is not in the expected format")
    return data


def open_items(data, keys):
    """``(items, unreadable)``: the items that open, and ``Counter`` of
    ``(kind, class, reason, device_only)`` for those that do not."""
    items, unreadable = [], Counter()
    for kind in KINDS:
        for row in data.get(kind) or ():
            blob = row.get("v_Data") if isinstance(row, dict) else None
            clas = kc.class_of(blob)
            key = keys.key(clas) if keys is not None and clas else None
            try:
                attrs = kc.open_item(blob, key)
            except kc.ItemError as error:
                unreadable[(kind, clas, error.reason,
                            error.device_only)] += 1
                continue
            items.append(Item(kind, clas, attrs))
    return items, unreadable


def secret_text(value):
    """The secret as text if it is text, else None."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            text = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return None
        if all(ch.isprintable() or ch in "\n\t" for ch in text):
            return text
    return None


def _shown_secret(value):
    text = secret_text(value)
    if text is not None:
        return text
    if isinstance(value, (bytes, bytearray)):
        return f"({len(value):,} bytes of data)"
    return "" if value is None else str(value)


def _text(value):
    """An attribute as text: names are usually text, but some are stored as
    bytes (and the protocol as a number)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        text = secret_text(value)
        return text if text is not None else bytes(value).hex()
    return str(value)


def _protocol(value):
    """``https`` for the code ``htps``, which a keychain stores as text or
    as the number of its four letters."""
    if isinstance(value, int):
        letters = value.to_bytes(4, "big").decode("latin-1").strip("\0 ") \
            if 0 < value < 2 ** 32 else ""
        code = letters if letters.isprintable() and letters.isalnum() else ""
    else:
        code = _text(value).strip()
    return _PROTOCOLS.get(code.lower(), code)


def _where(attrs, kind):
    if kind == "inet":
        scheme = _protocol(attrs.get("ptcl"))
        port = attrs.get("port")
        text = f"{scheme}://" if scheme else ""
        text += _text(attrs.get("srvr"))
        if isinstance(port, int) and port not in _PLAIN_PORTS:
            text += f":{port}"
        return text + _text(attrs.get("path"))
    return _text(attrs.get("svce"))


def password_row(item):
    attrs = item.attrs
    wifi = item.kind == "genp" and attrs.get("svce") == "AirPort"
    kind = "Wi-Fi password" if wifi else KINDS[item.kind]
    secret = attrs.get("v_Data")
    return {
        "kind": kind,
        "where": _text(attrs.get("acct")) if wifi else _where(attrs,
                                                              item.kind),
        "account": "" if wifi else _text(attrs.get("acct")),
        "password": _shown_secret(secret),
        "label": _text(attrs.get("labl")),
        "group": _text(attrs.get("agrp")),
        "access": kc.CLASSES.get(item.clas, f"Class {item.clas}"),
        "created": attrs.get("cdat") if isinstance(
            attrs.get("cdat"), float) else None,
        "modified": attrs.get("mdat") if isinstance(
            attrs.get("mdat"), float) else None,
        "synced": bool(attrs.get("sync")),
        "removed": bool(attrs.get("tomb")),
        "attrs": attrs,
    }


def _describe_value(value):
    if isinstance(value, float):
        from .common import format_datetime
        return format_datetime(value, seconds=True)
    if isinstance(value, (bytes, bytearray)):
        text = secret_text(value)
        if text is not None:
            return text
        shown = bytes(value[:48]).hex()
        return shown + ("..." if len(value) > 48 else "") \
            + f"  ({len(value):,} bytes)"
    return str(value)


def details(row):
    lines = [f"{row['kind']}"]
    for name, value in sorted(row["attrs"].items()):
        if name == "v_Data":
            continue
        lines.append(f"{name}: {_describe_value(value)}")
    secret = row["attrs"].get("v_Data")
    if secret is not None:
        lines.append("")
        lines.append("Value: " + _describe_value(secret))
    return "\n".join(lines)


def _passwords(items):
    rows = [password_row(i) for i in items if i.kind in ("genp", "inet")]
    shown = [r for r in rows if not r["removed"]]
    gone = len(rows) - len(shown)
    note = ("Passwords are shown as they are stored: keep what you export "
            "private."
            + (f" {gone:,} deleted items (left by iCloud Keychain sync) are "
               "not listed." if gone else ""))
    return Dataset(
        "passwords", "Passwords",
        [Column("kind", "Kind", 150), Column("where", "Where", 240),
         Column("account", "Account", 190),
         Column("password", "Password", 220),
         Column("group", "Saved by", 170),
         Column("modified", "Changed", 130, "date")],
        shown, note=note, sort=("where", False), details=details)


def _things(items, kind, key, title, label):
    rows = []
    for item in items:
        if item.kind != kind:
            continue
        attrs = item.attrs
        secret = attrs.get("v_Data")
        rows.append({
            "kind": KINDS[kind], "label": _text(attrs.get("labl")) or label,
            "size": len(secret) if isinstance(secret, (bytes, bytearray))
            else None,
            "group": _text(attrs.get("agrp")),
            "access": kc.CLASSES.get(item.clas, f"Class {item.clas}"),
            "created": attrs.get("cdat") if isinstance(
                attrs.get("cdat"), float) else None,
            "attrs": attrs})
    return Dataset(
        key, title,
        [Column("label", "Name", 260), Column("size", "Size", 90, "size",
                                             "e"),
         Column("group", "Saved by", 200), Column("access", "Available", 200),
         Column("created", "Added", 130, "date")],
        rows, sort=("label", False),
        details=lambda row: details({**row, "kind": title[:-1]}))


def _unreadable(unreadable):
    rows = []
    for (kind, clas, reason, device_only), count in sorted(
            unreadable.items(), key=lambda kv: (-kv[1], kv[0][0])):
        rows.append({
            "kind": KINDS[kind],
            "access": kc.CLASSES.get(clas, "Unknown" if clas is None
                                     else f"Class {clas}"),
            "count": count, "reason": reason,
            "device_only": device_only})
    return Dataset(
        "unreadable", "Cannot be opened",
        [Column("kind", "Kind", 180), Column("access", "Available", 240),
         Column("count", "Items", 70, "number", "e"),
         Column("reason", "Why", 360)],
        rows, sort=("count", True),
        note="Items marked \"this device only\" are locked with a key that "
             "never leaves the phone, so no backup can open them.")


def datasets_for(data, keys):
    """The tables for the keychain *data* opened with *keys* (``ClassKeys``,
    or None if there is no key bag)."""
    items, unreadable = open_items(data, keys)
    result = []
    passwords = _passwords(items)
    if passwords.rows:
        result.append(passwords)
    for kind, key, title, label in (("cert", "certificates", "Certificates",
                                     "Certificate"),
                                    ("keys", "keys", "Keys", "Key")):
        table = _things(items, kind, key, title, label)
        if table.rows:
            result.append(table)
    if unreadable:
        result.append(_unreadable(unreadable))
    return result


def counts(data):
    """How many items the file holds, per kind (without opening them)."""
    return {kind: len(data.get(kind) or ()) for kind in KINDS}


class KeychainReader:
    """Reads one working copy of ``keychain-backup.plist``."""

    def __init__(self, path, keys):
        self.path = path
        self.keys = keys
        self.data = read_plist(path)

    def datasets(self):
        return datasets_for(self.data, self.keys)
