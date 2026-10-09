# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading the call history
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

"""Reads ``CallHistory.storedata``: phone and FaceTime calls (iOS 8 and
later). No GUI."""

from dataclasses import dataclass

from .common import ContactBook, apple_time, table_columns

DATABASE = "HomeDomain/Library/CallHistoryDB/CallHistory.storedata"

OUTGOING, INCOMING, MISSED = "outgoing", "incoming", "missed"
DIRECTIONS = {OUTGOING: "Outgoing", INCOMING: "Incoming", MISSED: "Missed"}
KINDS = {"phone": "Phone", "facetime_video": "FaceTime video",
         "facetime_audio": "FaceTime audio", "other": "Other"}


@dataclass
class Call:
    rowid: int
    address: str = ""
    name: str = ""             # a contact's name, or what the phone cached
    when: float = None
    duration: float = 0.0
    direction: str = INCOMING
    kind: str = "phone"
    service: str = ""
    location: str = ""
    country: str = ""
    unread: bool = False

    @property
    def display_name(self):
        return self.name or self.address or "Unknown caller"

    @property
    def direction_label(self):
        return DIRECTIONS.get(self.direction, self.direction)

    @property
    def kind_label(self):
        return KINDS.get(self.kind, "Other")


def decode_address(value):
    """The number or address of a call. The phone stores it as bytes."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", "replace")
    return str(value).replace("\x00", "").strip()


def classify_kind(call_type, service=""):
    """``phone``, ``facetime_video``, ``facetime_audio`` or ``other``."""
    if call_type == 1:
        return "phone"
    if call_type == 8:
        return "facetime_video"
    if call_type == 16:
        return "facetime_audio"
    if call_type in (None, 0) and "facetime" in (service or "").lower():
        return "facetime_video"
    return "other"


def classify_direction(originated, answered, duration):
    if originated:
        return OUTGOING
    return INCOMING if answered or duration else MISSED


class CallsReader:
    """Reads one working copy of the call history database."""

    def __init__(self, conn, contacts=None):
        self.conn = conn
        self.contacts = contacts or ContactBook()
        self.cols = table_columns(conn, "ZCALLRECORD")
        self._calls = []

    def _col(self, name):
        return name if name in self.cols else "NULL"

    def calls(self):
        """Every call, newest first. Raises if the file is not a database."""
        self.conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        if not self.cols:
            return []
        rows = self.conn.execute(
            f"SELECT Z_PK, {self._col('ZADDRESS')}, {self._col('ZNAME')}, "
            f"{self._col('ZDATE')}, {self._col('ZDURATION')}, "
            f"{self._col('ZORIGINATED')}, {self._col('ZANSWERED')}, "
            f"{self._col('ZCALLTYPE')}, {self._col('ZSERVICE_PROVIDER')}, "
            f"{self._col('ZLOCATION')}, {self._col('ZISO_COUNTRY_CODE')}, "
            f"{self._col('ZREAD')} FROM ZCALLRECORD")
        calls = []
        for (pk, address, name, date, duration, originated, answered,
             call_type, service, location, country, read) in rows:
            address = decode_address(address)
            duration = float(duration or 0)
            calls.append(Call(
                pk, address,
                self.contacts.name_for(address) or (name or "").strip(),
                apple_time(date), duration,
                classify_direction(originated, answered, duration),
                classify_kind(call_type, service), service or "",
                (location or "").strip(), (country or "").strip(),
                read == 0 and not originated))
        calls.sort(key=lambda c: c.when or 0, reverse=True)
        self._calls = calls
        return calls

    def search(self, text, calls=None):
        """Calls whose name, number or place contains every word of *text*."""
        return search_calls(self._calls if calls is None else calls, text)


def search_calls(calls, text):
    """Calls whose name, number or place contains every word of *text*
    (digits also match a number written with spaces or dashes)."""
    words = text.casefold().split()
    found = []
    for call in calls:
        haystack = " ".join((call.display_name, call.address,
                             call.location, call.country)).casefold()
        digits = "".join(c for c in call.address if c.isdigit())
        if all(w in haystack or (w.isdigit() and w in digits)
               for w in words):
            found.append(call)
    return found


def summarize(calls):
    """Counts and talk time for a list of calls."""
    counts = {key: 0 for key in DIRECTIONS}
    talk = 0.0
    for call in calls:
        counts[call.direction] = counts.get(call.direction, 0) + 1
        talk += call.duration
    return {"total": len(calls), "talk_seconds": talk, **counts}


def filter_calls(calls, direction=None, kind=None):
    """Calls of one direction and/or kind (None: any)."""
    return [c for c in calls
            if (direction is None or c.direction == direction)
            and (kind is None or c.kind == kind or (
                kind == "facetime" and c.kind.startswith("facetime")))]
