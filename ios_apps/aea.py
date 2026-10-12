# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Reading Apple Encrypted Archives (files that start with ``AEA1``) that are
encrypted with a key we have: the *symmetric* profiles.

The Health app keeps the files that clinics send it (a PDF report, a note as
HTML or RTF) in this format, one file for each attachment, in
``HealthDomain/Health/Files/<identifier>``. The key of each file is stored in
the Health database (``attachments.encryption_key``, a small archived object
holding a 32-byte ``sym_key``), so the files can be opened from a backup that
holds both.

The format is not documented by Apple. It was learned from, and checked
against, the work of others (see the credits in ``AUTHORS``):

* The Apple Wiki's page on the format (theapplewiki.com, "Apple Encrypted
  Archive"), which describes the profiles, the header and the layout.
* kinnay/AEA ("python-aea", MIT licence), a Python implementation: the key
  derivation steps and the order of the fields were compared with it, and the
  decoder here was checked against it on real files.
* blacktop/ipsw (``pkg/aea``, MIT licence), whose decoder is written down in
  prose in the same terms.

No code was copied; this module is written for this program.

Layout of a symmetric-profile archive::

    "AEA1"  u24 profile  u8 scrypt-strength  u32 size-of-auth-data
    auth data                       (size given above; empty for Health)
    [signature, 160 bytes]          (only profile 2)
    main salt (32)  root-header MAC (32)  root header (48, encrypted)
    MAC of the first cluster (32)
    then the clusters; each holds the segment headers (encrypted), the MAC
    of the next cluster, a MAC for each segment, and the segments.

Every encrypted piece is AES-256 in counter mode with a key, an IV and a MAC
key that come from HKDF-SHA256 of the key above it; the MAC is HMAC-SHA256.
Everything is checked before it is used, so a wrong key, or a damaged file,
raises :class:`ArchiveError` and never returns wrong bytes.
"""

import hashlib
import hmac
import lzma
import plistlib
import struct
import zlib

from . import keyed_archive, notes_crypto

MAGIC = b"AEA1"
SYMMETRIC = 1
SYMMETRIC_SIGNED = 2
SIGNATURE_SIZE = {SYMMETRIC: 0, SYMMETRIC_SIGNED: 160}
CHECKSUM_SIZE = {0: 0, 1: 8, 2: 32}          # none, MurmurHash64A, SHA-256
MURMUR_SEED = 0xE2236FDC26A5F6D2
MASK = (1 << 64) - 1


class ArchiveError(ValueError):
    """The file is not an archive this module can open with this key."""


def is_archive(data):
    """Whether *data* (bytes) starts like an Apple Encrypted Archive."""
    return bytes(data[:4]) == MAGIC


def symmetric_key(blob):
    """The 32-byte key held in the ``encryption_key`` of a Health attachment
    (an archived object with a ``sym_key``), or None."""
    try:
        value = keyed_archive.unarchive(plistlib.loads(bytes(blob)))
    except (ValueError, TypeError, plistlib.InvalidFileException,
            keyed_archive.ArchiveError):
        return None
    key = value.get("sym_key") if isinstance(value, dict) else None
    return bytes(key) if isinstance(key, (bytes, bytearray)) \
        and len(key) == 32 else None


# ── The building blocks ──────────────────────────────────────

def hkdf(length, key, info, salt=b""):
    """HKDF-SHA256 (RFC 5869) of *key*."""
    pseudo = hmac.new(salt or bytes(32), key, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(pseudo, block + info + bytes([counter]),
                         hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def murmur64a(data, seed=MURMUR_SEED):
    """MurmurHash64A of *data* as 8 little-endian bytes."""
    m, r = 0xC6A4A7935BD1E995, 47
    h = (seed ^ (len(data) * m)) & MASK
    whole = len(data) - len(data) % 8
    for offset in range(0, whole, 8):
        k = struct.unpack_from("<Q", data, offset)[0]
        k = (k * m) & MASK
        k ^= k >> r
        k = (k * m) & MASK
        h = ((h ^ k) * m) & MASK
    if len(data) % 8:
        h ^= int.from_bytes(data[whole:], "little")
        h = (h * m) & MASK
    h ^= h >> r
    h = (h * m) & MASK
    h ^= h >> r
    return struct.pack("<Q", h)


def _checksum(kind, data):
    if kind == 2:
        return hashlib.sha256(data).digest()
    if kind == 1:
        return murmur64a(data)
    return b""


def _check_and_decrypt(keys, data, salt, mac):
    """Verify *mac* over *data* (``keys`` = MAC key, AES key, IV: 80 bytes)
    and return the decrypted *data*."""
    expected = hmac.new(keys[:32], salt + data + struct.pack("<Q", len(salt)),
                        hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        raise ArchiveError("the key does not open this file, or the file is "
                           "damaged (a check value is wrong)")
    AES = notes_crypto._aes()
    return AES.new(keys[32:64], AES.MODE_CTR, nonce=b"",
                   initial_value=keys[64:80]).decrypt(data)


def _decompress(kind, data, size):
    try:
        if kind == "-":
            return data
        if kind == "z":
            return zlib.decompress(data)
        if kind == "x":
            return lzma.decompress(data)
        if kind == "e":
            try:
                import liblzfse
            except ImportError:
                raise ArchiveError(
                    "this file is compressed with LZFSE; reading it needs "
                    "the pyliblzfse package (pip install pyliblzfse)")
            return liblzfse.decompress(data)
        if kind == "4":
            try:
                import lz4.block
            except ImportError:
                raise ArchiveError(
                    "this file is compressed with LZ4; reading it needs the "
                    "lz4 package (pip install lz4)")
            return lz4.block.decompress(data, size)
    except (zlib.error, lzma.LZMAError, ValueError) as exc:
        if isinstance(exc, ArchiveError):
            raise
        raise ArchiveError(f"a compressed part is damaged ({exc})") from exc
    raise ArchiveError(f"this file uses a compression ({kind!r}) that is "
                       "not supported")


# ── Opening an archive ───────────────────────────────────────

class _Reader:
    def __init__(self, data):
        self.data, self.pos = memoryview(data), 0

    def read(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ArchiveError("the file is too short or damaged")
        chunk = bytes(self.data[self.pos:self.pos + size])
        self.pos += size
        return chunk


def decrypt(data, key):
    """The contents of the archive *data* (bytes) opened with the 32-byte
    *key*. Raises :class:`ArchiveError` if it is not an archive of a
    symmetric profile, the key is wrong, or anything in it is damaged."""
    if not is_archive(data):
        raise ArchiveError("not an Apple Encrypted Archive")
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise ArchiveError("the key must be 32 bytes")
    reader = _Reader(data)
    reader.read(4)
    profile = int.from_bytes(reader.read(3), "little")
    scrypt = reader.read(1)[0]
    auth_size = struct.unpack("<I", reader.read(4))[0]
    if profile not in SIGNATURE_SIZE:
        raise ArchiveError(
            f"profile {profile} needs a password or a private key; only "
            "files encrypted with a key we hold can be opened")
    auth = reader.read(auth_size)
    reader.read(SIGNATURE_SIZE[profile])       # (a signature is not checked)
    salt = reader.read(32)
    root_mac = reader.read(32)
    root_data = reader.read(48)
    cluster_mac = reader.read(32)

    info = b"AEA_AMK" + profile.to_bytes(3, "little") + bytes([scrypt])
    main = hkdf(32, bytes(key), info, salt)
    root = _check_and_decrypt(hkdf(80, main, b"AEA_RHEK"), root_data,
                              cluster_mac + auth, root_mac)
    (original_size, _archive_size, segment_size, per_cluster) = \
        struct.unpack_from("<QQII", root)
    compression = chr(root[24])
    checksum_kind = root[25]
    if checksum_kind not in CHECKSUM_SIZE:
        raise ArchiveError("the file uses an unknown checksum")
    if original_size == 0:
        return b""
    if not 0 < per_cluster <= 1 << 16 or segment_size <= 0:
        raise ArchiveError("the file's header is damaged")
    header_size = 8 + CHECKSUM_SIZE[checksum_kind]

    out = bytearray()
    cluster = 0
    while len(out) < original_size:
        cluster_key = hkdf(32, main, b"AEA_CK" + struct.pack("<I", cluster))
        headers = reader.read(header_size * per_cluster)
        next_mac = reader.read(32)
        macs = reader.read(32 * per_cluster)
        headers = _check_and_decrypt(
            hkdf(80, cluster_key, b"AEA_CHEK"), headers, next_mac + macs,
            cluster_mac)
        for index in range(per_cluster):
            head = headers[header_size * index:header_size * (index + 1)]
            size, packed = struct.unpack_from("<II", head)
            segment = reader.read(packed)
            segment_key = hkdf(80, cluster_key,
                               b"AEA_SK" + struct.pack("<I", index))
            segment = _check_and_decrypt(segment_key, segment, b"",
                                         macs[32 * index:32 * (index + 1)])
            if size > packed:
                segment = _decompress(compression, segment, size)
            if len(segment) != size:
                raise ArchiveError("a part of the file has the wrong size")
            if _checksum(checksum_kind, segment) != head[8:]:
                raise ArchiveError("a part of the file fails its checksum")
            out += segment
            if len(out) >= original_size:
                break
        cluster_mac = next_mac
        cluster += 1
    if len(out) != original_size:
        raise ArchiveError("the file is not the size it says")
    return bytes(out)
