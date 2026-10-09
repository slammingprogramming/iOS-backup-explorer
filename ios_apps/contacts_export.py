# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — exporting contacts
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

"""Writes contacts as a vCard file (which phones, Google, Outlook and
others import), a spreadsheet, JSON, text or a web page. No GUI."""

import html
import json
import os

from .common import format_datetime
from .export_util import (html_page, iso_utc, write_csv_file,
                          write_text_file)

FORMATS = {
    "vcf": "vCard (.vcf, imports into most address books)",
    "csv": "Spreadsheet (CSV)",
    "html": "Web page (open in any browser)",
    "txt": "Text",
    "json": "JSON (for programs)",
}

# vCard TYPE values for the labels iOS uses
_PHONE_TYPES = {"mobile": ["CELL"], "iphone": ["CELL", "IPHONE"],
                "home": ["HOME"], "work": ["WORK"], "main": ["MAIN"],
                "homefax": ["HOME", "FAX"], "workfax": ["WORK", "FAX"],
                "otherfax": ["FAX"], "pager": ["PAGER"], "other": []}
_EMAIL_TYPES = {"home": ["HOME"], "work": ["WORK"], "other": [],
                "icloud": ["INTERNET"]}
_ADDRESS_TYPES = {"home": ["HOME"], "work": ["WORK"], "other": []}
_URL_TYPES = {"homepage": [], "home": ["HOME"], "work": ["WORK"],
              "other": []}


# ── vCard ────────────────────────────────────────────────────

def escape_text(text):
    """A text value as vCard 3.0 writes it (RFC 2426)."""
    return (str(text).replace("\\", "\\\\").replace("\r\n", "\n")
            .replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;")
            .replace(",", "\\,"))


def fold(line, limit=75):
    """Split a vCard line into lines of at most *limit* bytes, each
    continuation starting with a space, never inside a UTF-8 character."""
    raw = line.encode("utf-8")
    if len(raw) <= limit:
        return [line]
    parts, start, width = [], 0, limit
    while start < len(raw):
        end = min(start + width, len(raw))
        while end < len(raw) and raw[end] & 0xC0 == 0x80:
            end -= 1                      # do not cut a character in two
        parts.append(raw[start:end].decode("utf-8"))
        start, width = end, limit - 1     # (the leading space counts)
    return [parts[0]] + [" " + p for p in parts[1:]]


def _typed(label, table):
    """``(TYPE parameters, custom label)`` for an iOS label."""
    key = label.replace(" ", "").casefold()
    if not label or key in table:
        return table.get(key, []), ""
    return [], label


def vcard(contact):
    """The lines of one vCard for *contact*."""
    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    lines.append("N:" + ";".join(escape_text(p) for p in (
        contact.last, contact.first, contact.middle, contact.prefix,
        contact.suffix)))
    lines.append("FN:" + escape_text(contact.display_name))
    if contact.nickname:
        lines.append("NICKNAME:" + escape_text(contact.nickname))
    if contact.organization or contact.department:
        lines.append("ORG:" + escape_text(contact.organization)
                     + (";" + escape_text(contact.department)
                        if contact.department else ""))
    if contact.job_title:
        lines.append("TITLE:" + escape_text(contact.job_title))
    if contact.is_company:
        lines.append("X-ABShowAs:COMPANY")
    groups = [0]

    def add(prop, value_text, types, custom):
        params = "".join(f";TYPE={t}" for t in types)
        if custom:
            groups[0] += 1
            lines.append(f"item{groups[0]}.{prop}{params}:{value_text}")
            lines.append(f"item{groups[0]}.X-ABLabel:{escape_text(custom)}")
        else:
            lines.append(f"{prop}{params}:{value_text}")

    for label, number in contact.phones:
        types, custom = _typed(label, _PHONE_TYPES)
        add("TEL", escape_text(number), types, custom)
    for label, address in contact.emails:
        types, custom = _typed(label, _EMAIL_TYPES)
        add("EMAIL", escape_text(address), ["INTERNET"] + types, custom)
    for address in contact.addresses:
        types, custom = _typed(address.label, _ADDRESS_TYPES)
        add("ADR", ";;" + ";".join(escape_text(p) for p in (
            address.street, address.city, address.state, address.zip,
            address.country)), types, custom)
    for label, url in contact.urls:
        types, custom = _typed(label, _URL_TYPES)
        add("URL", escape_text(url), types, custom)
    for label, name in contact.related:
        add("X-ABRELATEDNAMES", escape_text(name), [], label)
    for label, day in contact.dates:
        add("X-ABDATE", day, [], label)
    for service, name in contact.messaging:
        add("X-" + (service.upper().replace(" ", "") or "IM"),
            escape_text(name), [], "")
    if contact.birthday and not contact.birthday.startswith("-"):
        lines.append("BDAY:" + contact.birthday)
    if contact.note:
        lines.append("NOTE:" + escape_text(contact.note))
    revised = iso_utc(contact.modified)
    if revised:                      # 2026-09-01T12:00:00+00:00
        lines.append("REV:" + revised[:19].replace("-", "").replace(
            ":", "") + "Z")
    lines.append("END:VCARD")
    folded = []
    for line in lines:
        folded.extend(fold(line))
    return folded


def write_vcf(path, contacts):
    text = "".join(line + "\r\n" for c in contacts for line in vcard(c))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return [path]


# ── The other formats ────────────────────────────────────────

def _labelled(pairs):
    return "; ".join(f"{label}: {value}" if label else value
                     for label, value in pairs)


CSV_COLUMNS = ("name", "first_name", "middle_name", "last_name", "prefix",
               "suffix", "nickname", "company", "department", "job_title",
               "phones", "emails", "addresses", "websites", "birthday",
               "note", "created", "modified")


def write_csv(path, contacts):
    rows = [[c.display_name, c.first, c.middle, c.last, c.prefix, c.suffix,
             c.nickname, c.organization, c.department, c.job_title,
             _labelled(c.phones), _labelled(c.emails),
             "; ".join((f"{a.label}: " if a.label else "") + str(a)
                       for a in c.addresses),
             _labelled(c.urls), c.birthday, c.note,
             format_datetime(c.created, seconds=True),
             format_datetime(c.modified, seconds=True)] for c in contacts]
    return write_csv_file(path, CSV_COLUMNS, rows)


def _dict(contact):
    return {
        "name": contact.display_name, "first_name": contact.first or None,
        "middle_name": contact.middle or None, "last_name": contact.last or None,
        "prefix": contact.prefix or None, "suffix": contact.suffix or None,
        "nickname": contact.nickname or None,
        "company": contact.organization or None,
        "is_company": contact.is_company,
        "department": contact.department or None,
        "job_title": contact.job_title or None,
        "birthday": contact.birthday or None,
        "phones": [{"label": l, "value": v} for l, v in contact.phones],
        "emails": [{"label": l, "value": v} for l, v in contact.emails],
        "addresses": [{"label": a.label, "street": a.street, "city": a.city,
                       "state": a.state, "zip": a.zip, "country": a.country}
                      for a in contact.addresses],
        "websites": [{"label": l, "value": v} for l, v in contact.urls],
        "related": [{"label": l, "value": v} for l, v in contact.related],
        "dates": [{"label": l, "value": v} for l, v in contact.dates],
        "messaging": [{"service": s, "name": n}
                      for s, n in contact.messaging],
        "note": contact.note or None,
        "created": iso_utc(contact.created) or None,
        "modified": iso_utc(contact.modified) or None,
        "id": contact.pk,
    }


def write_json(path, contacts):
    write_text_file(path, json.dumps([_dict(c) for c in contacts],
                                     ensure_ascii=False, indent=2) + "\n")
    return [path]


def card_lines(contact):
    """A contact as readable lines."""
    lines = [contact.display_name]
    if contact.person_name and contact.display_name != contact.person_name:
        lines.append(contact.person_name)
    if contact.nickname and contact.nickname != contact.display_name:
        lines.append(f"Nickname: {contact.nickname}")
    company = " - ".join(p for p in (contact.organization,
                                     contact.department) if p)
    if contact.job_title:
        company = f"{contact.job_title}, {company}" if company \
            else contact.job_title
    if company and company != contact.display_name:
        lines.append(company)
    for label, number in contact.phones:
        lines.append(f"{label or 'phone'}: {number}")
    for label, address in contact.emails:
        lines.append(f"{label or 'email'}: {address}")
    for address in contact.addresses:
        lines.append(f"{address.label or 'address'}: {address}")
    for label, url in contact.urls:
        lines.append(f"{label or 'web'}: {url}")
    for label, name in contact.related:
        lines.append(f"{label or 'related'}: {name}")
    for label, day in contact.dates:
        lines.append(f"{label or 'date'}: {day}")
    for service, name in contact.messaging:
        lines.append(f"{service or 'messaging'}: {name}")
    if contact.birthday:
        lines.append(f"Birthday: {contact.birthday}")
    if contact.note:
        lines.append("Note: " + contact.note.replace("\n", "\n      "))
    return lines


def write_txt(path, contacts):
    blocks = ["\n".join(card_lines(c)) for c in contacts]
    write_text_file(path, "\n\n".join(blocks) + ("\n" if blocks else ""))
    return [path]


_CSS = """
.card{background:var(--card);border-radius:12px;padding:10px 14px;margin:10px 0}
.card h2{margin:.1em 0;font-size:1.1rem}
.card dl{margin:.3em 0;display:grid;grid-template-columns:max-content 1fr;
gap:2px 12px}
.card dt{color:var(--muted)}.card dd{margin:0;overflow-wrap:anywhere}
"""


def _card_html(contact, index):
    rows = []

    def add(label, text):
        rows.append(f"<dt>{html.escape(label)}</dt>"
                    f"<dd>{html.escape(text).replace(chr(10), '<br>')}</dd>")

    company = " - ".join(p for p in (contact.organization,
                                     contact.department) if p)
    if contact.job_title:
        company = f"{contact.job_title}, {company}" if company \
            else contact.job_title
    if company and company != contact.display_name:
        add("work", company)
    if contact.nickname and contact.nickname != contact.display_name:
        add("nickname", contact.nickname)
    for label, number in contact.phones:
        add(label or "phone", number)
    for label, address in contact.emails:
        add(label or "email", address)
    for address in contact.addresses:
        add(address.label or "address", str(address))
    for label, url in contact.urls:
        add(label or "web", url)
    for label, name in contact.related:
        add(label or "related", name)
    for label, day in contact.dates:
        add(label or "date", day)
    for service, name in contact.messaging:
        add(service or "messaging", name)
    if contact.birthday:
        add("birthday", contact.birthday)
    if contact.note:
        add("note", contact.note)
    return (f"<div class=\"card\" id=\"c{index}\">"
            f"<h2>{html.escape(contact.display_name)}</h2>"
            f"<dl>{''.join(rows)}</dl></div>")


def write_html(path, contacts):
    body = ["<h1>Contacts</h1>",
            f"<div class=\"meta\">{len(contacts):,} contacts</div>"]
    body += [_card_html(c, n) for n, c in enumerate(contacts, 1)]
    write_text_file(path, html_page("Contacts", "".join(body), _CSS))
    return [path]


def export(contacts, fmt, folder):
    """Write *contacts* as *fmt* into *folder*. Returns the paths written."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    os.makedirs(folder, exist_ok=True)
    name = "contacts." + fmt
    path = os.path.join(folder, name)
    return {"vcf": write_vcf, "csv": write_csv, "json": write_json,
            "txt": write_txt, "html": write_html}[fmt](path, contacts)
