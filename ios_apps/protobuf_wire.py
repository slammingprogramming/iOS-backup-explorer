# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Reading Protocol Buffers *wire format*, with no schema.

Some Apple data (the Maps favorites of iOS 12, for one) is stored as protocol
buffer messages whose definitions Apple does not publish. The wire format
itself is public and simple: a message is a sequence of fields, each a number
and a value of one of a few kinds. This module reads that, and nothing about
what a field means: the caller says which field numbers it has found, by
looking at real data, to hold what.

    https://protobuf.dev/programming-guides/encoding/

No GUI, no dependency.
"""

import struct

VARINT, FIXED64, LENGTH_DELIMITED, FIXED32 = 0, 1, 2, 5
MAX_FIELD = 3000                 # (a real message does not use numbers so large)


def _varint(data, i):
    shift = value = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7
        if shift > 70:
            raise ValueError("a number that is too long")


def parse(data):
    """``[(field number, wire type, value)]`` for the message *data*, or None
    if it is not a message. Values are: an int (varint), a float (a 64- or
    32-bit field read as a double or a float), or bytes (length-delimited:
    text, a nested message, or raw bytes)."""
    fields, i = [], 0
    try:
        while i < len(data):
            key, i = _varint(data, i)
            field, wire = key >> 3, key & 7
            if field == 0 or field > MAX_FIELD:
                return None
            if wire == VARINT:
                value, i = _varint(data, i)
            elif wire == FIXED64:
                value = struct.unpack_from("<d", data, i)[0]
                i += 8
            elif wire == FIXED32:
                value = struct.unpack_from("<f", data, i)[0]
                i += 4
            elif wire == LENGTH_DELIMITED:
                size, i = _varint(data, i)
                value = bytes(data[i:i + size])
                if len(value) != size:
                    return None
                i += size
            else:
                return None
            fields.append((field, wire, value))
    except (IndexError, struct.error, ValueError):
        return None
    return fields


def is_text(value):
    """Whether the bytes are printable UTF-8 text (and not empty)."""
    try:
        text = value.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return False
    return bool(text) and all(c.isprintable() or c in "\n\t" for c in text)


def messages_at(data, path):
    """The nested messages (bytes) reached by following the field numbers in
    *path* from the message *data*, every one of them when a field repeats."""
    found = [data]
    for number in path:
        step = []
        for message in found:
            for field, wire, value in parse(message) or ():
                if field == number and wire == LENGTH_DELIMITED:
                    step.append(value)
        found = step
    return found


def texts_at(data, path):
    """The text values at *path* (a tuple of field numbers, the last of which
    holds the text), in order."""
    if not path:
        return []
    return [value.decode("utf-8") for value in messages_at(data, path)
            if is_text(value)]


def numbers_at(data, path, wire=VARINT):
    """The numbers (of the given wire type) at *path*."""
    if not path:
        return []
    out = []
    for message in messages_at(data, path[:-1]):
        for field, kind, value in parse(message) or ():
            if field == path[-1] and kind == wire:
                out.append(value)
    return out
