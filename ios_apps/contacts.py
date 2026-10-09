# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading the address book
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

"""Reads ``AddressBook.sqlitedb``: people and companies with their phone
numbers, email addresses, postal addresses, web pages and so on. No GUI.

Contact photos are kept in a separate database and are not read.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .common import apple_time, table_columns

DATABASE = "HomeDomain/Library/AddressBook/AddressBook.sqlitedb"

# ABMultiValue.property
PHONE, EMAIL, ADDRESS, INSTANT_MESSAGE, URL, RELATED = 3, 4, 5, 13, 22, 23
DATE = 12

_LABEL = re.compile(r"^_\$!<(.*)>!\$_$")
_DATE_TEXT = re.compile(r"^(\d{4}|-)-?(\d\d)-(\d\d)")


def clean_label(label):
    """``_$!<Mobile>!$_`` -> ``Mobile``; other labels are left alone."""
    label = (label or "").strip()
    match = _LABEL.match(label)
    return match.group(1) if match else label


def format_birthday(value):
    """``1990-05-17`` (or ``--05-17`` without a year) for a stored birthday,
    which is either a timestamp or text; ``""`` when there is none."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        stamp = apple_time(value)
        if stamp is None:
            return ""
        try:
            return datetime.fromtimestamp(stamp, timezone.utc).strftime(
                "%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return ""
    match = _DATE_TEXT.match(str(value).strip())
    if match:
        year, month, day = match.groups()
        return f"{'-' if year == '-' else year}-{month}-{day}"
    try:
        return format_birthday(float(value))
    except ValueError:
        return ""


@dataclass
class Address:
    label: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""

    @property
    def lines(self):
        """The address as it is written on an envelope."""
        locality = " ".join(p for p in (self.city, self.state, self.zip) if p)
        return [p for p in (self.street, locality, self.country) if p]

    def __str__(self):
        return ", ".join(self.lines)


@dataclass
class Contact:
    pk: int
    first: str = ""
    middle: str = ""
    last: str = ""
    prefix: str = ""
    suffix: str = ""
    nickname: str = ""
    organization: str = ""
    department: str = ""
    job_title: str = ""
    note: str = ""
    birthday: str = ""
    created: float = None
    modified: float = None
    is_company: bool = False
    phones: list = field(default_factory=list)       # [(label, value)]
    emails: list = field(default_factory=list)
    addresses: list = field(default_factory=list)    # [Address]
    urls: list = field(default_factory=list)
    related: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    messaging: list = field(default_factory=list)

    @property
    def person_name(self):
        return " ".join(p for p in (self.first, self.middle, self.last) if p)

    @property
    def display_name(self):
        if self.is_company and self.organization:
            return self.organization
        return (self.person_name or self.organization or self.nickname
                or (self.emails[0][1] if self.emails else "")
                or (self.phones[0][1] if self.phones else "")
                or "(No name)")

    def sort_key(self, by="last"):
        primary = (self.last or self.first) if by == "last" \
            else (self.first or self.last)
        primary = primary or self.organization or self.nickname \
            or self.display_name
        secondary = (self.first or self.last) if by == "last" \
            else (self.last or "")
        return (not bool(self.person_name or self.organization
                         or self.nickname),
                primary.casefold(), (secondary or "").casefold())

    @property
    def search_text(self):
        digits = " ".join("".join(c for c in v if c.isdigit())
                          for _l, v in self.phones)
        parts = [self.display_name, self.person_name, self.nickname,
                 self.organization, self.department, self.job_title,
                 self.note, digits]
        parts += [v for _l, v in self.phones + self.emails + self.urls
                  + self.related + self.messaging]
        parts += [str(a) for a in self.addresses]
        return " ".join(p for p in parts if p)


class ContactsReader:
    """Reads one working copy of the address book database."""

    def __init__(self, conn):
        self.conn = conn
        self.person_cols = table_columns(conn, "ABPerson")
        self._contacts = []

    def _col(self, name):
        return name if name in self.person_cols else "NULL"

    def contacts(self, by="last"):
        """Every contact, in address-book order. Raises if the file is not
        a database."""
        self.conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        if not self.person_cols:
            return []
        people = {}
        names = ("First Last Middle Prefix Suffix Nickname Organization "
                 "Department JobTitle Note Birthday CreationDate "
                 "ModificationDate Kind").split()
        for row in self.conn.execute(
                "SELECT ROWID, " + ", ".join(self._col(n) for n in names)
                + " FROM ABPerson"):
            pk, (first, last, middle, prefix, suffix, nick, org, dept, job,
                 note, birthday, created, modified, kind) = row[0], row[1:]
            people[pk] = Contact(
                pk, first or "", middle or "", last or "", prefix or "",
                suffix or "", nick or "", org or "", dept or "", job or "",
                note or "", format_birthday(birthday), apple_time(created),
                apple_time(modified), kind == 1)
        self._read_multivalues(people)
        self._contacts = sorted(people.values(),
                                key=lambda c: c.sort_key(by))
        return self._contacts

    def _read_multivalues(self, people):
        if not table_columns(self.conn, "ABMultiValue"):
            return
        labels = {}
        if table_columns(self.conn, "ABMultiValueLabel"):
            labels = {rowid: clean_label(value) for rowid, value in
                      self.conn.execute(
                          "SELECT ROWID, value FROM ABMultiValueLabel")}
        entries = {}
        if table_columns(self.conn, "ABMultiValueEntry") and \
                table_columns(self.conn, "ABMultiValueEntryKey"):
            for parent, key, value in self.conn.execute(
                    "SELECT e.parent_id, k.value, e.value "
                    "FROM ABMultiValueEntry e JOIN ABMultiValueEntryKey k "
                    "ON k.ROWID = e.key"):
                entries.setdefault(parent, {})[key] = value
        for uid, record, prop, label, value in self.conn.execute(
                "SELECT UID, record_id, property, label, value "
                "FROM ABMultiValue ORDER BY record_id, identifier, UID"):
            person = people.get(record)
            if person is None:
                continue
            label = labels.get(label, "")
            if prop == ADDRESS:
                parts = entries.get(uid, {})
                address = Address(
                    label, parts.get("Street") or "", parts.get("City") or "",
                    parts.get("State") or "", parts.get("ZIP") or "",
                    parts.get("Country") or "")
                if address.lines:
                    person.addresses.append(address)
            elif prop == INSTANT_MESSAGE:
                parts = entries.get(uid, {})
                name = parts.get("username") or parts.get("Username") or value
                service = parts.get("service") or parts.get("Service") or label
                if name:
                    person.messaging.append((service or "", str(name)))
            elif value is None or str(value).strip() == "":
                continue
            elif prop == PHONE:
                person.phones.append((label, str(value).strip()))
            elif prop == EMAIL:
                person.emails.append((label, str(value).strip()))
            elif prop == URL:
                person.urls.append((label, str(value).strip()))
            elif prop == RELATED:
                person.related.append((label, str(value).strip()))
            elif prop == DATE:
                text = format_birthday(value)
                if text:
                    person.dates.append((label, text))


def search_contacts(contacts, text):
    """Contacts matching every word of *text* (name, company, numbers,
    emails, addresses, notes); digits match a number however it is
    written."""
    words = text.casefold().split()
    found = []
    for contact in contacts:
        haystack = contact.search_text.casefold()
        if all(word in haystack for word in words):
            found.append(contact)
    return found
