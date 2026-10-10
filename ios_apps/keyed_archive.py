# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading NSKeyedArchiver property lists
# Copyright (C) 2026 slammingprogramming and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Turns the property lists iOS writes with ``NSKeyedArchiver`` (a table of
objects that point at each other by number) back into plain Python values:
dictionaries, lists, strings, numbers, dates and bytes. No GUI.

An archived object of a class the app does not know becomes a dict of its
fields with the class name under ``"$class"``, so nothing is lost.
"""

import plistlib
from datetime import datetime, timedelta, timezone

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
MAX_DEPTH = 200


class ArchiveError(ValueError):
    """The data is not a readable keyed archive."""


def is_keyed_archive(data):
    """Whether *data* (bytes) looks like an NSKeyedArchiver property list."""
    return b"NSKeyedArchiver" in bytes(data[:400])


def load(data):
    """The Python value archived in *data* (bytes of a property list)."""
    try:
        plist = plistlib.loads(data)
    except Exception as exc:
        raise ArchiveError(f"not a property list: {exc}") from exc
    return unarchive(plist)


def unarchive(plist):
    """The Python value of an already parsed keyed archive."""
    if not isinstance(plist, dict) or "$objects" not in plist \
            or "$top" not in plist:
        raise ArchiveError("not a keyed archive")
    objects = plist["$objects"]
    if not isinstance(objects, list):
        raise ArchiveError("the archive has no object table")
    cache = {}

    def resolve(value, depth=0):
        if depth > MAX_DEPTH:
            raise ArchiveError("the archive is nested too deeply")
        if isinstance(value, plistlib.UID):
            index = value.data
            if not 0 <= index < len(objects):
                raise ArchiveError("a reference points outside the archive")
            if index in cache:
                return cache[index]
            cache[index] = None            # (a loop gives None, not a crash)
            result = convert(objects[index], depth + 1)
            cache[index] = result
            return result
        return convert(value, depth + 1)

    def class_name(info):
        if isinstance(info, plistlib.UID):
            info = objects[info.data] if 0 <= info.data < len(objects) \
                else None
        return info.get("$classname", "") if isinstance(info, dict) else ""

    def convert(obj, depth):
        if obj == "$null":
            return None
        if isinstance(obj, list):
            return [resolve(v, depth) for v in obj]
        if not isinstance(obj, dict):
            return obj
        if "$class" not in obj:
            return {k: resolve(v, depth) for k, v in obj.items()}
        name = class_name(obj["$class"])
        if name in ("NSArray", "NSMutableArray", "NSSet", "NSMutableSet",
                    "NSOrderedSet"):
            return [resolve(v, depth) for v in obj.get("NS.objects", [])]
        if name in ("NSDictionary", "NSMutableDictionary"):
            keys = [resolve(k, depth) for k in obj.get("NS.keys", [])]
            values = [resolve(v, depth) for v in obj.get("NS.objects", [])]
            return {_hashable(k): v for k, v in zip(keys, values)}
        if name in ("NSString", "NSMutableString"):
            return obj.get("NS.string", "")
        if name in ("NSData", "NSMutableData"):
            return obj.get("NS.data", b"")
        if name == "NSDate":
            return APPLE_EPOCH + timedelta(seconds=obj.get("NS.time", 0))
        if name == "NSURL":
            base = resolve(obj.get("NS.base"), depth)
            relative = resolve(obj.get("NS.relative"), depth)
            return f"{base or ''}{relative or ''}"
        if name == "NSUUID":
            data = obj.get("NS.uuidbytes", b"")
            return str(_uuid(data)) if len(data) == 16 else None
        if name == "NSNumber":
            return obj.get("NS.number")
        result = {"$class": name}
        for key, value in obj.items():
            if key != "$class":
                result[key] = resolve(value, depth)
        return result

    top = plist["$top"]
    if isinstance(top, dict) and list(top) == ["root"]:
        return resolve(top["root"])
    return {k: resolve(v) for k, v in top.items()}


def _hashable(key):
    return key if isinstance(key, (str, int, float, bytes, bool)) \
        or key is None else repr(key)


def _uuid(data):
    import uuid
    return uuid.UUID(bytes=bytes(data))


def find(value, wanted, _depth=0):
    """Every value stored under the key *wanted* anywhere inside *value*
    (dictionaries and lists are searched, deeply)."""
    found = []
    if _depth > MAX_DEPTH:
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            if key == wanted:
                found.append(item)
            found.extend(find(item, wanted, _depth + 1))
    elif isinstance(value, list):
        for item in value:
            found.extend(find(item, wanted, _depth + 1))
    return found
