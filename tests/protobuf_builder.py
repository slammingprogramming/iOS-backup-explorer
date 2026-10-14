# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Builds protocol buffer messages (wire format) for tests, from invented
values. ``message((1, 5), (2, "text"), (3, 1.5), (4, message(...)))``."""

import struct


def varint(number):
    out = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        out.append(byte | (0x80 if number else 0))
        if not number:
            return bytes(out)


def field(number, value):
    """One field: an int is a varint, a float a 64-bit double, a str or bytes
    is length-delimited."""
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, float):
        return varint(number << 3 | 1) + struct.pack("<d", value)
    if isinstance(value, str):
        value = value.encode("utf-8")
    return varint(number << 3 | 2) + varint(len(value)) + bytes(value)


def message(*pairs):
    return b"".join(field(number, value) for number, value in pairs)


def nested(path, leaf):
    """*leaf* (bytes, a message or text) wrapped in messages along *path*
    (a tuple of field numbers), outermost first."""
    for number in reversed(path):
        leaf = field(number, leaf)
    return leaf
