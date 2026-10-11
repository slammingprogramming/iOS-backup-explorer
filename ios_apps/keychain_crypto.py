# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Opening the items of the keychain that an encrypted backup holds.

``KeychainDomain/keychain-backup.plist`` holds the keychain in four lists
(``genp`` generic passwords, ``inet`` internet passwords, ``cert``
certificates, ``keys`` keys). Each row has a ``v_Data`` blob:

====================  =====================================================
4 bytes, little endian    the version (3; 2 in older backups)
4 bytes                   the protection class (6 to 11)
4 bytes                   the length of the wrapped key (40)
that many bytes           the item's own key, RFC 3394-wrapped with the
                          class key of the backup's key bag
the rest                  the data, AES-GCM, with the 16-byte tag last
====================  =====================================================

The class keys are in the backup's key bag (``Manifest.plist``), which the
backup password unlocks. Classes 9, 10 and 11 are the "this device only"
ones: they are wrapped with a key that never leaves the phone. (A real backup's
key bag lists a key for them too, but it does not unwrap their items.) Those
items cannot be opened anywhere else.

The GCM nonce is empty. That is allowed by the GCM definition (the first
counter block is then all zeros, rather than one made from the nonce) but not
by most libraries, so GCM is done here. The decrypted data is a DER-encoded
set of name/value pairs (``acct``, ``svce``, ``v_Data``...) in version 3, and
a binary property list in version 2.

The format follows the open-source ``iphone-dataprotection`` tools, and has
been run on a real encrypted backup: every item of classes 6, 7 and 8 opened
(each one passes its GCM tag check, which a wrong reading of the format would
not), and only the "this device only" items did not. The tests use items made
by this module's own encoder, with the GCM and key wrap code checked against
``pycryptodome`` and the RFC 3394 vector. A wrong class key or damaged item
fails the GCM tag check, so nothing wrong is ever shown as right.

Needs ``pycryptodome`` (installed with ``iphone_backup_decrypt``).
"""

import hashlib
import hmac
import plistlib
import re
import struct
from datetime import datetime, timezone

from . import notes_crypto

# the keychain protection classes, and which of them are tied to the phone
CLASSES = {
    6: "When unlocked",
    7: "After first unlock",
    8: "Always",
    9: "When unlocked, this device only",
    10: "After first unlock, this device only",
    11: "Always, this device only",
}
DEVICE_ONLY = frozenset({9, 10, 11})

_MAX_DER_DEPTH = 12
_MAX_ITERATIONS = 100_000_000


class ItemError(ValueError):
    """An item that cannot be opened. ``reason`` says why, in words for a
    person; ``device_only`` is True if it can never be opened off the phone."""

    def __init__(self, reason, device_only=False):
        super().__init__(reason)
        self.reason = reason
        self.device_only = device_only


class WrongBackupPassword(ValueError):
    """The password does not unlock the backup's key bag."""


# ── GCM with any nonce, including none ───────────────────────

def _blocks(data):
    return [data[i:i + 16] for i in range(0, len(data), 16)]


def _multiply(x, y):
    """The product of two 128-bit field elements, as GCM defines it."""
    z, v = 0, y
    for bit in range(127, -1, -1):
        if (x >> bit) & 1:
            z ^= v
        v = (v >> 1) ^ (0xE1 << 120) if v & 1 else v >> 1
    return z


def _ghash(h, data):
    """GHASH of *data*, which is already padded to whole blocks."""
    y = 0
    for block in _blocks(data):
        y = _multiply(y ^ int.from_bytes(block, "big"), h)
    return y


def _pad(data):
    return data + b"\0" * (-len(data) % 16)


def _gcm(key, iv, data, aad, decrypting, tag=None):
    AES = notes_crypto._aes()
    cipher = AES.new(key, AES.MODE_ECB)
    h = int.from_bytes(cipher.encrypt(b"\0" * 16), "big")
    if len(iv) == 12:
        j0 = int.from_bytes(iv + b"\0\0\0\1", "big")
    else:
        j0 = _ghash(h, _pad(iv) + (len(iv) * 8).to_bytes(16, "big"))
    prefix, counter = j0 >> 32, j0 & 0xFFFFFFFF
    out = bytearray()
    for number, block in enumerate(_blocks(data), 1):
        stream = cipher.encrypt(
            ((prefix << 32) | ((counter + number) & 0xFFFFFFFF))
            .to_bytes(16, "big"))
        out += bytes(a ^ b for a, b in zip(block, stream))
    ciphertext = data if decrypting else bytes(out)
    lengths = (len(aad) * 8).to_bytes(8, "big") \
        + (len(ciphertext) * 8).to_bytes(8, "big")
    s = _ghash(h, _pad(aad) + _pad(ciphertext) + lengths)
    expected = (s ^ int.from_bytes(cipher.encrypt(j0.to_bytes(16, "big")),
                                   "big")).to_bytes(16, "big")
    if decrypting:
        if not hmac.compare_digest(expected, tag):
            raise ValueError("the authentication tag does not match")
        return bytes(out)
    return bytes(out), expected


def gcm_decrypt(key, iv, ciphertext, tag, aad=b""):
    """AES-GCM decryption for a nonce of any length (even none). Raises
    ``ValueError`` if the tag does not match."""
    return _gcm(key, iv, ciphertext, aad, True, tag)


def gcm_encrypt(key, iv, plaintext, aad=b""):
    """``(ciphertext, tag)``. For the tests and nothing else."""
    return _gcm(key, iv, plaintext, aad, False)


# ── DER ──────────────────────────────────────────────────────

def _generalized_time(text):
    match = re.fullmatch(r"(\d{4})(\d\d)(\d\d)(\d\d)(\d\d)(\d\d)(\.\d+)?Z?",
                         text)
    if not match:
        return text
    year, month, day, hour, minute, second = (int(x) for x in match.groups()[:6])
    try:
        moment = datetime(year, month, day, hour, minute, second,
                          tzinfo=timezone.utc)
    except ValueError:
        return text
    return moment.timestamp() + (float(match.group(7)) if match.group(7)
                                 else 0.0)


def der_decode(data, depth=0):
    """The first value of *data*, as ``(value, rest)``.

    A SEQUENCE or SET is a list; strings are ``str``; an OCTET STRING is
    ``bytes``; INTEGER is ``int``; BOOLEAN ``bool``; a date is Unix seconds
    (a ``float``); NULL is None. Anything else is its raw ``bytes``.
    """
    if depth > _MAX_DER_DEPTH:
        raise ValueError("DER nested too deeply")
    if len(data) < 2:
        raise ValueError("DER ends too soon")
    tag, length, position = data[0], data[1], 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or len(data) < 2 + count:
            raise ValueError("bad DER length")
        length = int.from_bytes(data[2:2 + count], "big")
        position = 2 + count
    end = position + length
    if end > len(data):
        raise ValueError("DER value is longer than the data")
    body, rest = data[position:end], data[end:]
    if tag & 0x20:                                   # constructed
        items = []
        while body:
            item, body = der_decode(body, depth + 1)
            items.append(item)
        return items, rest
    if tag == 0x0C or tag == 0x13 or tag == 0x16:    # UTF8 / printable / IA5
        return body.decode("utf-8", "replace"), rest
    if tag == 0x04:
        return bytes(body), rest
    if tag == 0x02:
        return int.from_bytes(body, "big", signed=True), rest
    if tag == 0x01:
        return body != b"\0", rest
    if tag == 0x05:
        return None, rest
    if tag in (0x18, 0x17):
        text = body.decode("ascii", "replace")
        if tag == 0x17 and len(text) >= 2:                  # UTCTime
            text = ("19" if int(text[:2] or 0) >= 50 else "20") + text
        return _generalized_time(text), rest
    return bytes(body), rest


def attributes(der):
    """The name/value pairs of a version 3 item as a dict."""
    top, _rest = der_decode(der)
    result = {}
    for pair in top if isinstance(top, list) else []:
        if isinstance(pair, list) and len(pair) == 2 \
                and isinstance(pair[0], str):
            result[pair[0]] = pair[1]
    return result


# ── Items ────────────────────────────────────────────────────

def split_item(blob):
    """``(version, protection_class, wrapped_key, ciphertext, tag)``."""
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 48:
        raise ItemError("the item is too short to be an item")
    version, clas = struct.unpack("<II", blob[:8])
    clas &= 0xF
    if version in (2, 3):
        (length,) = struct.unpack("<I", blob[8:12])
        if length != 40 or 12 + length + 16 > len(blob):
            raise ItemError("the item's key has an unexpected size")
        wrapped = bytes(blob[12:12 + length])
        return version, clas, wrapped, bytes(blob[12 + length:-16]), \
            bytes(blob[-16:])
    raise ItemError(f"the item is in an old format (version {version})")


def open_item(blob, class_key):
    """The attributes (a dict) of the item *blob*, given the key for its
    protection class. Raises ``ItemError``."""
    version, clas, wrapped, ciphertext, tag = split_item(blob)
    if class_key is None:
        raise ItemError(
            "locked to the phone it came from" if clas in DEVICE_ONLY
            else "the backup holds no key for its protection class",
            device_only=clas in DEVICE_ONLY)
    try:
        item_key = notes_crypto.key_unwrap(class_key, wrapped)
    except notes_crypto.WrongPassword:
        if clas in DEVICE_ONLY:
            # (a real backup's key bag lists these classes too, but their
            # items were wrapped with the phone's own keys)
            raise ItemError("locked to the phone it came from",
                            device_only=True) from None
        raise ItemError("its key could not be unwrapped") from None
    try:
        plain = gcm_decrypt(item_key, b"", ciphertext, tag)
    except ValueError:
        raise ItemError("it is damaged (the tag does not match)") from None
    try:
        if version == 3:
            found = attributes(plain)
        else:
            found = plistlib.loads(plain)
            if not isinstance(found, dict):
                raise ValueError("not a dictionary")
    except (ValueError, plistlib.InvalidFileException) as exc:
        raise ItemError(f"its data could not be read ({exc})") from None
    return found


def class_of(blob):
    """The protection class of an item, or None."""
    try:
        return split_item(blob)[1]
    except ItemError:
        return None


# ── The key bag ──────────────────────────────────────────────

class ClassKeys:
    """The unlocked class keys of a backup: ``key(6)`` and so on."""

    def __init__(self, keys):
        self._keys = dict(keys)

    def key(self, protection_class):
        return self._keys.get(protection_class)

    def classes(self):
        return sorted(self._keys)


def _tlv(blob):
    position = 0
    while position + 8 <= len(blob):
        tag = blob[position:position + 4]
        (length,) = struct.unpack(">L", blob[position + 4:position + 8])
        yield tag, blob[position + 8:position + 8 + length]
        position += 8 + length


def _number(value):
    return struct.unpack(">L", value)[0] if len(value) == 4 else value


def unlock_keybag(keybag_blob, password):
    """Unlock the key bag of a backup (``Manifest.plist``'s ``BackupKeyBag``)
    with the backup password. Returns ``ClassKeys``. Takes some seconds: the
    password is stretched by millions of rounds, on purpose."""
    attrs, classes, current = {}, {}, None
    for tag, data in _tlv(keybag_blob):
        data = _number(data)
        if tag == b"UUID" and b"UUID" not in attrs:
            attrs[tag] = data
        elif tag == b"UUID":
            if current and b"CLAS" in current:
                classes[current[b"CLAS"]] = current
            current = {}
        elif tag in (b"CLAS", b"WRAP", b"WPKY") and current is not None:
            current[tag] = data
        elif current is None:
            attrs.setdefault(tag, data)
    if current and b"CLAS" in current:
        classes[current[b"CLAS"]] = current
    try:
        rounds1, salt1 = attrs[b"DPIC"], attrs[b"DPSL"]
        rounds2, salt2 = attrs[b"ITER"], attrs[b"SALT"]
    except KeyError:
        raise ValueError("the key bag is not in the expected format") \
            from None
    for rounds in (rounds1, rounds2):
        if not isinstance(rounds, int) or not 1 <= rounds <= _MAX_ITERATIONS:
            raise ValueError("the key bag asks for an unreasonable number "
                             "of rounds")
    first = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt1,
                                rounds1, 32)
    stretched = hashlib.pbkdf2_hmac("sha1", first, salt2, rounds2, 32)
    return _class_keys(classes, stretched)


def _class_keys(classes, passphrase_key):
    keys = {}
    for number, entry in classes.items():
        wrapped = entry.get(b"WPKY")
        if not wrapped or not (entry.get(b"WRAP", 0) & 2):
            continue
        try:
            keys[number] = notes_crypto.key_unwrap(passphrase_key, wrapped)
        except notes_crypto.WrongPassword:
            raise WrongBackupPassword(
                "the password does not unlock this backup") from None
    if not keys:
        raise WrongBackupPassword("the key bag holds no keys to unlock")
    return ClassKeys(keys)


def keys_from_library(backup):
    """The class keys of an ``iphone_backup_decrypt`` backup that is already
    open, or None if this version of the library does not give them."""
    for name in ("keybag", "_keybag"):
        keybag = getattr(backup, name, None)
        keys = getattr(keybag, "classes_keys", None)
        if keys:
            return ClassKeys(keys)
    return None
