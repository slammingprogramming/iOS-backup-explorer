# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Builds Apple Encrypted Archives (symmetric profile) for tests, and holds
one archive made by another implementation (kinnay/AEA, MIT licence) with the
key and the text it holds, so the reader is checked against more than itself.
Everything in them is invented."""

import base64
import hashlib
import hmac
import lzma
import os
import struct
import zlib

KEY = bytes(range(32))
TEXT = b"Invented clinical note.\nNothing here is real.\n"

# made by python-aea 1.1.0: profile 1, SHA-256 checksums, no compression
REFERENCE_ARCHIVE = base64.b64decode(
    "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")


def _hkdf(length, key, info, salt=b""):
    prk = hmac.new(salt or bytes(32), key, hashlib.sha256).digest()
    okm, previous, n = b"", b"", 0
    while len(okm) < length:
        n += 1
        previous = hmac.new(prk, previous + info + bytes([n]),
                            hashlib.sha256).digest()
        okm += previous
    return okm[:length]


def _seal(keys, data, salt):
    from Crypto.Cipher import AES
    sealed = AES.new(keys[32:64], AES.MODE_CTR, nonce=b"",
                     initial_value=keys[64:]).encrypt(data)
    mac = hmac.new(keys[:32], salt + sealed + struct.pack("<Q", len(salt)),
                   hashlib.sha256).digest()
    return sealed, mac


def _murmur(data):
    from ios_apps.aea import murmur64a
    return murmur64a(data)


COMPRESSORS = {"-": lambda d: d, "z": zlib.compress, "x": lzma.compress}
CHECKSUMS = {0: lambda d: b"", 1: _murmur,
             2: lambda d: hashlib.sha256(d).digest()}
CHECKSUM_SIZE = {0: 0, 1: 8, 2: 32}


def build(plain, key=KEY, segment_size=0x4000, per_cluster=32,
          compression="-", checksum=2, profile=1, auth=b"", fault=None):
    """An archive of *plain* in the symmetric profile *profile* (1, or 2 with
    an empty signature). *fault* makes an archive that is authentic (every
    check value is right) but wrong inside: ``"checksum"`` (the recorded
    checksum of a segment is not the segment's) or ``"size"`` (the recorded
    size is not the size it unpacks to)."""
    salt = os.urandom(32)
    main = _hkdf(32, key, b"AEA_AMK" + profile.to_bytes(3, "little")
                 + bytes(1), salt)
    cluster_size = segment_size * per_cluster
    count = max(1, -(-len(plain) // cluster_size))
    clusters, next_mac = [], os.urandom(32)
    for index in reversed(range(count)):
        cluster_key = _hkdf(32, main, b"AEA_CK" + struct.pack("<I", index))
        headers, macs, body = b"", b"", b""
        chunk = plain[index * cluster_size:(index + 1) * cluster_size]
        for number in range(per_cluster):
            piece = chunk[number * segment_size:(number + 1) * segment_size]
            if piece:
                packed = COMPRESSORS[compression](piece)
                if len(packed) >= len(piece):
                    packed = piece
                recorded = len(piece)
                if fault == "size":
                    packed = zlib.compress(piece)
                    recorded = len(piece) + 50 + len(packed)
                headers += struct.pack("<II", recorded, len(packed)) \
                    + CHECKSUMS[checksum](piece + (b"x" if fault == "checksum"
                                                   else b""))
                sealed, mac = _seal(_hkdf(80, cluster_key, b"AEA_SK"
                                          + struct.pack("<I", number)),
                                    packed, b"")
            else:
                headers += bytes(8 + CHECKSUM_SIZE[checksum])
                sealed, mac = b"", os.urandom(32)
            macs += mac
            body += sealed
        sealed_headers, cluster_mac = _seal(
            _hkdf(80, cluster_key, b"AEA_CHEK"), headers, next_mac + macs)
        clusters.append(sealed_headers + next_mac + macs + body)
        next_mac = cluster_mac
    root = (struct.pack("<QQII", len(plain), 0, segment_size, per_cluster)
            + compression.encode() + bytes([checksum]) + bytes(22))
    root, root_mac = _seal(_hkdf(80, main, b"AEA_RHEK"), root,
                           next_mac + auth)
    return (b"AEA1" + profile.to_bytes(3, "little") + bytes(1)
            + struct.pack("<I", len(auth)) + auth
            + (bytes(160) if profile == 2 else b"")
            + salt + root_mac + root + next_mac
            + b"".join(reversed(clusters)))
