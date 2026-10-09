# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — reading the Notes app's database
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

"""Reads ``NoteStore.sqlite``: folders, notes, their formatting and their
attachments. No GUI.

A note's text is stored as a gzip-compressed Protocol Buffers message: the
plain text, plus "attribute runs" that say, for each stretch of text, its
paragraph style (title, heading, list, checkbox...), its font traits, its
link, and whether it stands for an attachment. The run lengths count
UTF-16 code units, not characters. There is a tiny decoder for exactly the
parts needed here, so nothing has to be installed.
"""

import os
import re
import sqlite3
import zlib
from dataclasses import dataclass, field

from .common import apple_time, table_columns

DOMAIN = "AppDomainGroup-group.com.apple.notes"
DATABASE = f"{DOMAIN}/NoteStore.sqlite"
OBJECT_REPLACEMENT = "\ufffc"

# Paragraph styles
TITLE, HEADING, SUBHEADING, MONOSPACED = 0, 1, 2, 4
BULLET, DASH, NUMBERED, CHECKBOX = 100, 101, 102, 103
LIST_STYLES = (BULLET, DASH, NUMBERED, CHECKBOX)

_IMAGE_UTIS = {"public.jpeg", "public.png", "public.heic", "public.heif",
               "public.tiff", "com.compuserve.gif", "public.jpeg-2000",
               "org.webmproject.webp", "com.microsoft.bmp", "public.image"}
_VIDEO_UTIS = {"public.movie", "com.apple.quicktime-movie", "public.mpeg-4",
               "public.video"}


# ── A minimal Protocol Buffers reader ────────────────────────

def _varint(data, pos):
    shift = result = 0
    while True:
        if pos >= len(data) or shift > 70:
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _signed(value):
    """A varint read as a (possibly negative) 64-bit integer."""
    return value - (1 << 64) if value >= 1 << 63 else value


def parse_fields(data):
    """``[(field number, value)]`` for a protobuf message: integers for
    varints and fixed-size values, bytes for length-delimited ones.
    Raises ValueError when the data is not a valid message."""
    fields, pos = [], 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 2:
            length, pos = _varint(data, pos)
            if pos + length > len(data):
                raise ValueError("truncated field")
            value, pos = bytes(data[pos:pos + length]), pos + length
        elif wire == 1:
            value, pos = int.from_bytes(data[pos:pos + 8], "little"), pos + 8
        elif wire == 5:
            value, pos = int.from_bytes(data[pos:pos + 4], "little"), pos + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        if number == 0:
            raise ValueError("field number 0")
        fields.append((number, value))
    return fields


def _first(fields, number, default=None):
    for key, value in fields:
        if key == number:
            return value
    return default


# ── The text of a note ───────────────────────────────────────

@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    link: str = ""
    attachment: str = ""      # identifier, for the object-replacement char
    attachment_uti: str = ""


@dataclass
class Paragraph:
    style: int = -1           # -1: body text
    indent: int = 0
    checked: bool = False
    number: int = 0           # for numbered lists
    spans: list = field(default_factory=list)

    @property
    def text(self):
        return "".join(s.text for s in self.spans)


def decode_note_data(blob):
    """The paragraphs of a note from its ``ZDATA`` column.
    Raises ValueError if the blob is not readable note data (for example
    because the note is locked with a password)."""
    if not blob:
        raise ValueError("no note data")
    blob = bytes(blob)
    try:
        raw = zlib.decompress(blob, 16 + zlib.MAX_WBITS) \
            if blob[:2] == b"\x1f\x8b" else blob
        top = parse_fields(raw)
        document = parse_fields(_first(top, 2, b""))
        note = parse_fields(_first(document, 3, b""))
        text = (_first(note, 2, b"") or b"").decode("utf-8", "replace")
        runs = [parse_fields(v) for k, v in note if k == 5]
    except (zlib.error, ValueError) as exc:
        raise ValueError(f"not readable note data: {exc}") from exc
    return _paragraphs(text, runs)


def _run_properties(fields):
    length = _first(fields, 1, 0)
    style, indent, checked = -1, 0, False
    paragraph = _first(fields, 2)
    if paragraph:
        inner = parse_fields(paragraph)
        style = _signed(_first(inner, 1, -1))
        indent = _first(inner, 4, 0)
        checklist = _first(inner, 5)
        if checklist:
            checked = bool(_first(parse_fields(checklist), 2, 0))
    hints = _first(fields, 5, 0)
    attachment = _first(fields, 12)
    ident = uti = ""
    if attachment:
        info = parse_fields(attachment)
        ident = (_first(info, 1, b"") or b"").decode("utf-8", "replace")
        uti = (_first(info, 2, b"") or b"").decode("utf-8", "replace")
    return length, dict(
        style=style, indent=indent, checked=checked,
        bold=bool(hints & 1), italic=bool(hints & 2),
        underline=bool(_first(fields, 6, 0)),
        strike=bool(_first(fields, 7, 0)),
        link=(_first(fields, 9, b"") or b"").decode("utf-8", "replace"),
        attachment=ident, attachment_uti=uti)


def _paragraphs(text, runs):
    units = text.encode("utf-16-le", "surrogatepass")
    total = len(units) // 2
    pieces, position = [], 0          # (string, properties)
    for run in runs:
        length, props = _run_properties(run)
        length = min(length, total - position)
        if length <= 0:
            continue
        chunk = units[position * 2:(position + length) * 2]
        pieces.append((chunk.decode("utf-16-le", "replace"), props))
        position += length
    if position < total:              # text the runs do not cover
        pieces.append((units[position * 2:].decode("utf-16-le", "replace"),
                       dict(style=-1, indent=0, checked=False, bold=False,
                            italic=False, underline=False, strike=False,
                            link="", attachment="", attachment_uti="")))
    paragraphs, current = [], None
    for chunk, props in pieces:
        parts = chunk.split("\n")
        for number, part in enumerate(parts):
            if current is None:
                current = Paragraph(props["style"], props["indent"],
                                    props["checked"])
            elif not current.spans and not current.text:
                # first piece of a paragraph decides its style
                current.style, current.indent = props["style"], props["indent"]
                current.checked = props["checked"]
            if part:
                for segment in _split_attachments(part, props):
                    current.spans.append(segment)
            if number < len(parts) - 1:        # a line break ends it
                paragraphs.append(current)
                current = None
    if current is not None and current.spans:
        paragraphs.append(current)
    _number_lists(paragraphs)
    return paragraphs


def _split_attachments(part, props):
    """Text with attachment characters cut out as spans of their own."""
    style = {k: props[k] for k in ("bold", "italic", "underline", "strike",
                                   "link")}
    pieces = re.split(f"({OBJECT_REPLACEMENT})", part)
    for piece in pieces:
        if not piece:
            continue
        if piece == OBJECT_REPLACEMENT and props["attachment"]:
            yield Span(piece, attachment=props["attachment"],
                       attachment_uti=props["attachment_uti"], **style)
        else:
            yield Span(piece, **style)


def _number_lists(paragraphs):
    counters = {}
    for paragraph in paragraphs:
        if paragraph.style != NUMBERED:
            counters = {k: v for k, v in counters.items()
                        if k < paragraph.indent} \
                if paragraph.style in LIST_STYLES else {}
            continue
        # deeper levels restart whenever a shallower item appears
        counters = {k: v for k, v in counters.items()
                    if k <= paragraph.indent}
        counters[paragraph.indent] = counters.get(paragraph.indent, 0) + 1
        paragraph.number = counters[paragraph.indent]


# ── Attachments, notes, folders ──────────────────────────────

@dataclass
class Attachment:
    ident: str
    uti: str = ""
    kind: str = "other"        # image audio video file url inline table ...
    name: str = ""
    path: str = ""             # in the backup, "" if it is not there
    url: str = ""
    alt: str = ""              # text of a hashtag or mention
    title: str = ""

    @property
    def label(self):
        if self.kind == "inline":
            return self.alt or self.title or "(mention)"
        if self.kind == "url":
            return self.title or self.url
        names = {"table": "Table", "drawing": "Drawing", "scan": "Scan",
                 "image": "Image", "audio": "Recording", "video": "Video"}
        base = names.get(self.kind, "Attachment")
        return f"{base}: {self.name}" if self.name else base


def classify(uti, name=""):
    uti = (uti or "").lower()
    lower = (name or "").lower()
    if uti.startswith("com.apple.notes.inlinetextattachment"):
        return "inline"
    if uti == "public.url":
        return "url"
    if uti == "com.apple.notes.table":
        return "table"
    if uti.startswith("com.apple.paper.doc.scan") \
            or uti == "com.apple.notes.gallery":
        return "scan"
    if uti.startswith(("com.apple.paper", "com.apple.drawing")):
        return "drawing"
    if uti in _IMAGE_UTIS or uti.endswith(("jpeg", "png", "heic")):
        return "image"
    if "audio" in uti or "audio" in lower or lower.endswith(
            (".m4a", ".mp3", ".wav", ".caf", ".aac")):
        return "audio"
    if uti in _VIDEO_UTIS or lower.endswith((".mov", ".mp4", ".m4v")):
        return "video"
    return "file" if name else "other"


@dataclass
class Folder:
    pk: int
    title: str
    account: str = ""
    parent: int = 0
    is_trash: bool = False
    count: int = 0


@dataclass
class Note:
    pk: int
    title: str
    folder: int = 0
    snippet: str = ""
    created: float = None
    modified: float = None
    locked: bool = False
    pinned: bool = False
    deleted: bool = False
    has_data: bool = True
    # filled in by NotesReader.load()
    loaded: bool = False
    paragraphs: list = field(default_factory=list)
    attachments: dict = field(default_factory=dict)
    error: str = ""

    @property
    def text(self):
        return "\n".join(p.text for p in self.paragraphs)

    @property
    def display_title(self):
        return self.title or self.snippet or "Untitled note"

    @property
    def search_text(self):
        """The words in the note, with each attachment replaced by what a
        person would look for (a hashtag, a link title, a file name)."""
        lines = []
        for paragraph in self.paragraphs:
            parts = []
            for span in paragraph.spans:
                if not span.attachment:
                    parts.append(span.text)
                    continue
                attachment = self.attachments.get(span.attachment)
                if attachment is not None:
                    parts.append(" ".join(x for x in (
                        attachment.alt, attachment.title, attachment.url,
                        attachment.name) if x))
            lines.append("".join(parts))
        return "\n".join(lines)


class NotesReader:
    """Reads one working copy of ``NoteStore.sqlite``.

    *resolve_media(media_id, file_name)* turns an attachment's media folder
    into a path inside the backup (or ``""``); see :func:`media_resolver`.
    """

    def __init__(self, conn, resolve_media=None):
        self.conn = conn
        self.resolve_media = resolve_media or (lambda *a: "")
        self.cols = table_columns(conn, "ZICCLOUDSYNCINGOBJECT")
        self._has_data_table = bool(table_columns(conn, "ZICNOTEDATA"))
        self._entities = self._read_entities()
        self.folders_by_pk = {}
        self._notes = []
        self._notes_read = False

    # -- schema -----------------------------------------------

    def _read_entities(self):
        try:
            return {name: ent for ent, name in self.conn.execute(
                "SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY")}
        except sqlite3.Error:
            return {}

    def _col(self, name, alias="n"):
        return f"{alias}.{name}" if name in self.cols else "NULL"

    def _first_of(self, names, alias="n"):
        present = [f"{alias}.{n}" for n in names if n in self.cols]
        if not present:
            return "NULL"
        return present[0] if len(present) == 1 \
            else f"COALESCE({', '.join(present)})"

    def _entity_filter(self, name, alias="n"):
        ent = self._entities.get(name)
        return f"{alias}.Z_ENT = {int(ent)}" if ent is not None else None

    # -- folders ----------------------------------------------

    def folders(self):
        """The folders, with the number of notes in each."""
        if not self._notes_read:
            self.notes()
        return list(self.folders_by_pk.values())

    def _read_folders(self):
        folder_filter = self._entity_filter("ICFolder")
        if folder_filter is None or "ZTITLE2" not in self.cols:
            return []
        accounts = {}
        account_filter = self._entity_filter("ICAccount")
        if account_filter:
            for pk, name in self.conn.execute(
                    f"SELECT n.Z_PK, {self._first_of(['ZNAME', 'ZTITLE'])} "
                    f"FROM ZICCLOUDSYNCINGOBJECT n WHERE {account_filter}"):
                accounts[pk] = name or ""
        account_col = self._first_of(["ZACCOUNT4", "ZACCOUNT3", "ZACCOUNT2",
                                      "ZACCOUNT1", "ZACCOUNT"])
        folders = []
        for pk, title, parent, kind, account in self.conn.execute(
                f"SELECT n.Z_PK, n.ZTITLE2, {self._col('ZPARENT')}, "
                f"{self._col('ZFOLDERTYPE')}, {account_col} "
                f"FROM ZICCLOUDSYNCINGOBJECT n WHERE {folder_filter} AND "
                f"COALESCE({self._col('ZMARKEDFORDELETION')}, 0) = 0"):
            folders.append(Folder(pk, title or "Notes", accounts.get(account, ""),
                                  parent or 0, kind == 1))
        self.folders_by_pk = {f.pk: f for f in folders}
        return folders

    # -- notes ------------------------------------------------

    def notes(self):
        """All notes, newest first (without their text; see :meth:`load`)."""
        self._read_folders()
        note_filter = self._entity_filter("ICNote")
        if note_filter is None:
            note_filter = "n.ZNOTEDATA IS NOT NULL" \
                if "ZNOTEDATA" in self.cols else "1 = 0"
        created = self._first_of(["ZCREATIONDATE3", "ZCREATIONDATE1",
                                  "ZCREATIONDATE"])
        modified = self._first_of(["ZMODIFICATIONDATE1", "ZMODIFICATIONDATE"])
        data_exists = ("EXISTS(SELECT 1 FROM ZICNOTEDATA d "
                       "WHERE d.ZNOTE = n.Z_PK)"
                       if self._has_data_table else "0")
        notes = []
        for (pk, title, snippet, folder, made, changed, locked, pinned,
             removed, has_data) in self.conn.execute(
                f"SELECT n.Z_PK, {self._first_of(['ZTITLE1', 'ZTITLE'])}, "
                f"{self._col('ZSNIPPET')}, {self._col('ZFOLDER')}, "
                f"{created}, {modified}, {self._col('ZISPASSWORDPROTECTED')}, "
                f"{self._col('ZISPINNED')}, {self._col('ZMARKEDFORDELETION')},"
                f" {data_exists} "
                f"FROM ZICCLOUDSYNCINGOBJECT n WHERE {note_filter}"):
            if removed:
                continue
            folder_row = self.folders_by_pk.get(folder)
            notes.append(Note(
                pk, title or "", folder or 0, snippet or "",
                apple_time(made), apple_time(changed), bool(locked),
                bool(pinned), bool(folder_row and folder_row.is_trash),
                bool(has_data)))
        notes.sort(key=lambda n: (n.modified or 0), reverse=True)
        for note in notes:
            folder = self.folders_by_pk.get(note.folder)
            if folder is not None:
                folder.count += 1
        self._notes = notes
        self._notes_read = True
        return notes

    # -- one note ---------------------------------------------

    def load(self, note):
        """Fill in *note*'s paragraphs and attachments (once)."""
        if note.loaded:
            return note
        note.loaded = True
        if note.locked:
            note.error = ("This note is locked with a password. Its text is "
                          "encrypted in the backup and cannot be shown.")
        else:
            row = self.conn.execute(
                "SELECT ZDATA FROM ZICNOTEDATA WHERE ZNOTE = ?",
                (note.pk,)).fetchone() if self._has_data_table else None
            try:
                note.paragraphs = decode_note_data(row[0] if row else None)
            except ValueError as exc:
                note.error = f"The text of this note could not be read ({exc})."
                if note.snippet:
                    note.paragraphs = [Paragraph(spans=[Span(note.snippet)])]
        if not note.title:
            first = next((p.text.strip() for p in note.paragraphs
                          if p.text.strip()), "")
            note.title = (first or note.snippet or "Untitled note")[:80]
        note.attachments = self._attachments(note)
        return note

    def _attachments(self, note):
        if "ZNOTE" not in self.cols or "ZIDENTIFIER" not in self.cols:
            return {}
        sql = (
            f"SELECT a.ZIDENTIFIER, {self._col('ZTYPEUTI', 'a')}, "
            f"{self._col('ZTITLE', 'a')}, {self._col('ZURLSTRING', 'a')}, "
            f"{self._first_of(['ZALTTEXT', 'ZTOKENCONTENTIDENTIFIER'], 'a')}, "
            f"{self._col('ZIDENTIFIER', 'm') if 'ZMEDIA' in self.cols else 'NULL'},"
            f" {self._col('ZFILENAME', 'm') if 'ZMEDIA' in self.cols else 'NULL'}"
            " FROM ZICCLOUDSYNCINGOBJECT a "
            + ("LEFT JOIN ZICCLOUDSYNCINGOBJECT m ON m.Z_PK = a.ZMEDIA "
               if "ZMEDIA" in self.cols else "")
            + "WHERE a.ZNOTE = ?")
        found = {}
        for ident, uti, title, url, alt, media_id, filename in \
                self.conn.execute(sql, (note.pk,)):
            if not ident:
                continue
            path = self.resolve_media(media_id, filename) \
                if media_id else ""
            name = filename or (os.path.basename(path) if path else "")
            kind = classify(uti, name)
            found[ident] = Attachment(
                ident, uti or "", kind, name, path, url or "", alt or "",
                title or "")
        return found

    # -- searching and originals ------------------------------

    def search(self, text):
        """Notes whose title or text contains every word of *text*."""
        words = text.casefold().split()
        if not words:
            return []
        found = []
        for note in self._notes:
            self.load(note)
            haystack = f"{note.title}\n{note.search_text}".casefold()
            if all(word in haystack for word in words):
                found.append(note)
        return found

    def attachment_paths(self, notes=None):
        """Backup paths of the attachment files of *notes* (default: all)."""
        paths = []
        for note in (self._notes if notes is None else notes):
            self.load(note)
            paths.extend(a.path for a in note.attachments.values() if a.path)
        return list(dict.fromkeys(paths))


# ── Finding attachment files in the backup ───────────────────

def media_resolver(index):
    """A function ``(media folder id, file name) -> backup path or ""``.

    Attachments live in ``Accounts/<account>/Media/<id>/[<n>_<uuid>/]<name>``.
    When there are several versions of a file, the highest generation wins.
    """
    root = index.get(DOMAIN)
    by_id = {}
    accounts = root.children.get("Accounts") if root is not None else None
    for account in (accounts.children.values() if accounts is not None
                    and accounts.is_dir else ()):
        media = account.children.get("Media") if account.is_dir else None
        if media is None or not media.is_dir:
            continue
        for folder in media.children.values():
            if folder.is_dir:
                by_id.setdefault(folder.name, []).append(folder)

    def generation(node):
        match = re.match(r"(\d+)_", node.parent.name or "")
        return int(match.group(1)) if match else 0

    def resolve(media_id, file_name):
        best = None
        for folder in by_id.get(media_id or "", ()):
            for node in index.walk_files(folder):
                rank = (node.name == file_name, generation(node))
                if best is None or rank > best[0]:
                    best = (rank, node)
        return index.path_of(best[1]) if best else ""

    return resolve
