# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Builds NSKeyedArchiver property lists from Python values, for tests."""

import plistlib
from datetime import datetime

APPLE0 = datetime(2001, 1, 1)


class Archive:
    def __init__(self):
        self.objects = ["$null"]
        self._classes = {}

    def _add(self, obj):
        self.objects.append(obj)
        return plistlib.UID(len(self.objects) - 1)

    def cls(self, name):
        if name not in self._classes:
            self._classes[name] = self._add(
                {"$classname": name, "$classes": [name, "NSObject"]})
        return self._classes[name]

    def encode(self, value):
        """The reference (or inline value) that stands for *value*."""
        if value is None:
            return plistlib.UID(0)
        if isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, (str, bytes)):
            return self._add(value)
        if isinstance(value, datetime):
            return self._add({"$class": self.cls("NSDate"),
                              "NS.time": (value - APPLE0).total_seconds()})
        if isinstance(value, list):
            slot = self._add(None)
            self.objects[slot.data] = {
                "$class": self.cls("NSArray"),
                "NS.objects": [self.encode(v) for v in value]}
            return slot
        if isinstance(value, dict) and "$class" in value:
            slot = self._add(None)
            body = {"$class": self.cls(value["$class"])}
            body.update({k: self.encode(v) for k, v in value.items()
                         if k != "$class"})
            self.objects[slot.data] = body
            return slot
        if isinstance(value, dict):
            slot = self._add(None)
            self.objects[slot.data] = {
                "$class": self.cls("NSDictionary"),
                "NS.keys": [self.encode(k) for k in value],
                "NS.objects": [self.encode(v) for v in value.values()]}
            return slot
        raise TypeError(type(value))

    def dumps(self, root):
        reference = self.encode(root)
        return plistlib.dumps({
            "$archiver": "NSKeyedArchiver", "$version": 100000,
            "$top": {"root": reference}, "$objects": self.objects},
            fmt=plistlib.FMT_BINARY)


def archive(root):
    return Archive().dumps(root)
