# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — exporting Messages
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

"""Write conversations out as text, CSV, JSON or a browsable HTML page.

The *original, raw* data is always available separately (the database and
the attachments exactly as they are in the backup); these are the converted,
human-friendly forms. All of it is plain Python with no GUI, so it is tested
without one.
"""

import csv
import html
import json
import os

from .common import format_datetime
from .export_util import (describe_size, iso_utc,  # noqa: F401
                          safe_filename)
from .export_util import href as link_target

FORMATS = {
    "txt": "Text (one file per conversation)",
    "html": "Web page (open in any browser, with attachments)",
    "csv": "Spreadsheet (CSV, all messages)",
    "json": "JSON (all messages, for programs)",
}

_BROWSER_IMAGES = {"image/png", "image/jpeg", "image/gif", "image/webp",
                   "image/bmp"}


def conversation_filename(number, conversation, extension):
    """``003 - Alice Example.html``: numbered, so names never collide."""
    return f"{number:03d} - {safe_filename(conversation.title)}.{extension}"


def _who(message):
    return "Me" if message.from_me else message.sender


# ── Plain text ───────────────────────────────────────────────

def write_txt(folder, items):
    """One ``.txt`` file per conversation. Returns the paths."""
    paths = []
    for number, (conv, messages) in enumerate(items, 1):
        path = os.path.join(folder, conversation_filename(number, conv, "txt"))
        lines = [conv.title, "=" * len(conv.title)]
        if conv.participants:
            lines.append("With: " + ", ".join(conv.participants))
        lines.append(f"{len(messages)} messages"
                     + (f" ({conv.service_label})" if conv.services else ""))
        lines.append("")
        for message in messages:
            stamp = format_datetime(message.when, seconds=True)
            if message.kind == "event":
                lines.append(f"[{stamp}] *** {message.text} ***")
                continue
            body = message.text or ""
            first, *rest = body.split("\n") or [""]
            lines.append(f"[{stamp}] {_who(message)}: {first}")
            lines.extend("    " + line for line in rest)
            for att in message.attachments:
                detail = ", ".join(x for x in (att.mime,
                                               describe_size(att.size)) if x)
                lines.append(f"    [attachment: {att.name}"
                             + (f" ({detail})" if detail else "") + "]")
            for reaction in message.reactions:
                lines.append(f"    ({reaction.kind} by {reaction.sender})")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        paths.append(path)
    return paths


# ── CSV and JSON ─────────────────────────────────────────────

CSV_COLUMNS = ("conversation", "participants", "date", "date_utc", "sender",
               "direction", "service", "type", "text", "attachments",
               "reactions")


def write_csv(path, items):
    """Every message of every conversation in one spreadsheet file."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for conv, messages in items:
            people = "; ".join(conv.participants)
            for message in messages:
                writer.writerow([
                    conv.title, people,
                    format_datetime(message.when, seconds=True),
                    iso_utc(message.when), _who(message),
                    "sent" if message.from_me else "received",
                    message.service or "", message.kind, message.text,
                    "; ".join(a.name for a in message.attachments),
                    "; ".join(f"{r.kind} ({r.sender})"
                              for r in message.reactions)])
    return [path]


def write_json(path, items, attachment_files=None):
    """Structured data: conversations, each with its messages."""
    attachment_files = attachment_files or {}
    data = []
    for conv, messages in items:
        data.append({
            "title": conv.title,
            "participants": conv.participants,
            "is_group": conv.is_group,
            "services": sorted(conv.services),
            "messages": [{
                "id": m.rowid, "guid": m.guid,
                "date": iso_utc(m.when), "date_read": iso_utc(m.read_when),
                "sender": _who(m), "handle": m.handle,
                "from_me": m.from_me, "service": m.service, "type": m.kind,
                "text": m.text,
                "attachments": [{
                    "name": a.name, "mime_type": a.mime, "size": a.size,
                    "file": attachment_files.get(a.rowid)}
                    for a in m.attachments],
                "reactions": [{"kind": r.kind, "sender": r.sender}
                              for r in m.reactions],
            } for m in messages],
        })
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return [path]


# ── HTML ─────────────────────────────────────────────────────

_CSS = """
:root{--bg:#fff;--fg:#1c1c1e;--muted:#6b7280;--recv:#e9e9eb;--sent:#0b84fe;
--sms:#34c759;--card:#f5f5f7}
@media (prefers-color-scheme:dark){:root{--bg:#000;--fg:#f2f2f7;
--muted:#9ca3af;--recv:#262629;--card:#1c1c1e}}
body{font:16px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif;margin:0;
background:var(--bg);color:var(--fg)}
main{max-width:760px;margin:0 auto;padding:16px}
h1{font-size:1.3rem;margin:.2em 0}.meta{color:var(--muted);font-size:.85rem}
.day{text-align:center;color:var(--muted);font-size:.8rem;margin:18px 0 6px}
.row{display:flex;flex-direction:column;margin:3px 0}
.row.sent{align-items:flex-end}.row.received{align-items:flex-start}
.who{font-size:.72rem;color:var(--muted);margin:0 10px}
.bubble{max-width:78%;padding:8px 12px;border-radius:18px;
overflow-wrap:anywhere;background:var(--recv)}
.sent .bubble{background:var(--sent);color:#fff}
.sent.sms .bubble{background:var(--sms)}
.bubble img{max-width:100%;border-radius:12px;display:block;margin:4px 0}
.bubble a{color:inherit;text-decoration:underline}
.att{font-size:.85rem;opacity:.9}
.react{font-size:.72rem;color:var(--muted);margin:2px 10px}
.event{text-align:center;color:var(--muted);font-size:.8rem;margin:8px 0}
time{font-size:.68rem;opacity:.75;display:block;margin-top:3px}
ul.convs{list-style:none;padding:0}
ul.convs li{background:var(--card);margin:8px 0;padding:10px 14px;
border-radius:12px}
ul.convs a{color:inherit;font-weight:600;text-decoration:none}
"""


def _page(title, body):
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,"
            "initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
            f"<body><main>{body}</main></body></html>\n")


def _attachment_html(att, files):
    name = html.escape(att.name)
    relative = files.get(att.rowid)
    detail = html.escape(", ".join(
        x for x in (att.mime, describe_size(att.size)) if x))
    if not relative:
        return (f"<div class=\"att\">\U0001F4CE {name}"
                f" ({detail or 'not in the backup'}) &mdash; not exported"
                "</div>")
    href = html.escape(link_target(relative), quote=True)
    if att.mime in _BROWSER_IMAGES:
        return (f"<a href=\"{href}\"><img loading=\"lazy\" src=\"{href}\" "
                f"alt=\"{name}\"></a>")
    return (f"<div class=\"att\">\U0001F4CE <a href=\"{href}\">{name}</a>"
            f"{(' (' + detail + ')') if detail else ''}</div>")


def _message_html(message, group, files):
    stamp = html.escape(format_datetime(message.when, seconds=True))
    iso = html.escape(iso_utc(message.when), quote=True)
    if message.kind == "event":
        return f"<div class=\"event\">{html.escape(message.text)}</div>"
    direction = "sent" if message.from_me else "received"
    sms = " sms" if (message.service or "").upper() == "SMS" else ""
    parts = []
    if group and not message.from_me:
        parts.append(f"<div class=\"who\">{html.escape(message.sender)}</div>")
    inner = []
    if message.text:
        inner.append(html.escape(message.text).replace("\n", "<br>"))
    inner.extend(_attachment_html(a, files) for a in message.attachments)
    inner.append(f"<time datetime=\"{iso}\">{stamp}</time>")
    parts.append(f"<div class=\"bubble\">{''.join(inner)}</div>")
    if message.reactions:
        reactions = ", ".join(
            f"{html.escape(r.kind)} by {html.escape(r.sender)}"
            for r in message.reactions)
        parts.append(f"<div class=\"react\">{reactions}</div>")
    return f"<div class=\"row {direction}{sms}\">{''.join(parts)}</div>"


def write_html(folder, items, attachment_files=None):
    """A browsable page per conversation plus an ``index.html``."""
    files = attachment_files or {}
    paths, listing = [], []
    for number, (conv, messages) in enumerate(items, 1):
        name = conversation_filename(number, conv, "html")
        body = [f"<p><a href=\"index.html\">&larr; All conversations</a></p>",
                f"<h1>{html.escape(conv.title)}</h1>",
                f"<div class=\"meta\">{len(messages):,} messages"
                + (f" &middot; {html.escape(conv.service_label)}"
                   if conv.services else "") + "</div>"]
        if conv.participants and conv.is_group:
            body.append("<div class=\"meta\">With "
                        + html.escape(", ".join(conv.participants))
                        + "</div>")
        day = None
        for message in messages:
            this_day = (format_datetime(message.when) or "")[:10]
            if this_day and this_day != day:
                day = this_day
                body.append(f"<div class=\"day\">{html.escape(day)}</div>")
            body.append(_message_html(message, conv.is_group, files))
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_page(conv.title, "".join(body)))
        paths.append(path)
        listing.append(
            f"<li><a href=\"{html.escape(link_target(name), quote=True)}\">"
            f"{html.escape(conv.title)}</a><div class=\"meta\">"
            f"{len(messages):,} messages"
            + (f" &middot; last {html.escape(format_datetime(conv.last_when))}"
               if conv.last_when else "") + "</div></li>")
    index = os.path.join(folder, "index.html")
    with open(index, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(_page("Messages", "<h1>Messages</h1>"
                           f"<div class=\"meta\">{len(items)} conversations"
                           "</div><ul class=\"convs\">"
                           + "".join(listing) + "</ul>"))
    return [index] + paths


# ── Putting it together ──────────────────────────────────────

def attachment_export_names(items):
    """``{attachment rowid: unique file name}`` for every attachment that is
    in the backup, plus ``{rowid: Attachment}``."""
    names, attachments = {}, {}
    for _conv, messages in items:
        for message in messages:
            for att in message.attachments:
                if att.rowid in names or not att.backup_path:
                    continue
                names[att.rowid] = f"{att.rowid:06d}_" \
                    + safe_filename(att.name, "attachment", 100)
                attachments[att.rowid] = att
    return names, attachments


def export(items, fmt, folder, fetch_attachments=None):
    """Write *items* (``[(Conversation, [Message])]``) as *fmt* into *folder*.

    *fetch_attachments(files)*, if given, is called with
    ``[(Attachment, file name)]`` and must copy those files into
    ``folder/attachments`` and return the names that actually arrived. HTML
    and JSON then link to them. Returns the paths written.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    os.makedirs(folder, exist_ok=True)
    files = {}
    if fetch_attachments is not None and fmt in ("html", "json"):
        names, attachments = attachment_export_names(items)
        wanted = [(attachments[rowid], name) for rowid, name in names.items()]
        if wanted:
            arrived = set(fetch_attachments(wanted))
            files = {rowid: f"attachments/{name}"
                     for rowid, name in names.items() if name in arrived}
    if fmt == "txt":
        return write_txt(folder, items)
    if fmt == "csv":
        return write_csv(os.path.join(folder, "messages.csv"), items)
    if fmt == "json":
        return write_json(os.path.join(folder, "messages.json"), items, files)
    return write_html(folder, items, files)
