# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Visual Voicemail reader
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

"""Reads the voicemails: the list in ``voicemail.db``, the audio next to it
(``<id>.amr``) and the words the phone wrote down (``<id>.transcript``, an
archived object). No GUI."""

import os
import re
import sqlite3

from . import keyed_archive
from .export_util import describe_duration, safe_filename, write_text_file
from .records import Column, Dataset, fetch_dicts

FOLDER = "HomeDomain/Library/Voicemail"
DATABASE = f"{FOLDER}/voicemail.db"
AUDIO_EXTENSIONS = (".amr", ".m4a", ".caf", ".wav", ".mp3", ".aac")
_NAME = re.compile(r"^(\d+)\.([A-Za-z0-9]+)$")


def folder_files(index):
    """``({id: audio path}, {id: transcript path})`` for what the voicemail
    folder of the backup holds."""
    folder = index.get(FOLDER) if index is not None else None
    audio, words = {}, {}
    if folder is None or not folder.is_dir:
        return audio, words
    for name, node in folder.children.items():
        match = _NAME.match(name)
        if node.is_dir or not match:
            continue
        number, extension = int(match.group(1)), "." + match.group(2).lower()
        if extension == ".transcript":
            words[number] = f"{FOLDER}/{name}"
        elif extension in AUDIO_EXTENSIONS:
            audio.setdefault(number, f"{FOLDER}/{name}")
    return audio, words


def discover(index):
    """The files a Voicemail tab copies: the database first, then the
    transcripts."""
    if index is None:
        return []
    node = index.get(DATABASE)
    if node is None or node.is_dir:
        return []
    _audio, words = folder_files(index)
    return [DATABASE] + [words[k] for k in sorted(words)]


def read_transcript(path):
    """The words of a ``.transcript`` file, or ``""`` if it is not one we
    can read."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        if keyed_archive.is_keyed_archive(data):
            value = keyed_archive.load(data)
        else:
            return ""
    except (OSError, keyed_archive.ArchiveError, ValueError):
        return ""
    return transcript_text(value)


def transcript_text(value):
    """The text inside an unarchived transcript: the whole string when it
    has one, else the pieces it is made of."""
    if isinstance(value, dict):
        whole = value.get("transcriptionString")
        if isinstance(whole, str) and whole.strip():
            return whole.strip()
        pieces = value.get("segments")
        if isinstance(pieces, list):
            words = [p.get("substring") for p in pieces
                     if isinstance(p, dict)
                     and isinstance(p.get("substring"), str)]
            return " ".join(w.strip() for w in words if w.strip())
    return ""


def _stamp(value):
    """Voicemail databases count from 1970, unlike most iOS ones."""
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def voicemail_rows(conn, book, index, folder=None):
    """Every voicemail as a dict, newest first. *folder* is where working
    copies of the transcripts are (default: next to the database)."""
    if folder is None:
        try:
            folder = os.path.dirname(
                conn.execute("PRAGMA database_list").fetchone()[2])
        except sqlite3.Error:
            folder = ""
    audio, words = folder_files(index)
    rows = []
    for item in fetch_dicts(conn, "voicemail", [
            "ROWID", "remote_uid", "date", "sender", "callback_num",
            "duration", "expiration", "trashed_date", "flags", "receiver",
            "label"], order="date DESC, ROWID DESC"):
        number = item["sender"] or item["callback_num"] or ""
        number = str(number).strip()
        name = book.name_for(number) if book is not None and number else None
        local = os.path.join(folder, f"{item['ROWID']}.transcript")
        text = read_transcript(local) if folder and os.path.isfile(local) \
            else ""
        path = audio.get(item["ROWID"], "")
        node = index.get(path) if path and index is not None else None
        rows.append({
            "id": item["ROWID"],
            "when": _stamp(item["date"]),
            "from": name or number or "(unknown caller)",
            "name": name or "",
            "number": number,
            "callback": str(item["callback_num"] or "").strip(),
            "length": item["duration"] if item["duration"] else None,
            "expires": _stamp(item["expiration"]),
            "deleted": _stamp(item["trashed_date"]),
            "transcript": text,
            "has_transcript": item["ROWID"] in words,
            "audio": path if node is not None else "",
            "size": node.size if node is not None else None,
            "label": (item["label"] or "").strip(),
        })
    return rows


def friendly_name(row, extension=".amr"):
    """``2026-09-01 100000 - Sam.amr``, for saving a voicemail."""
    from .common import format_datetime
    stamp = format_datetime(row["when"], seconds=True).replace(":", "")
    title = row["name"] or row["number"] or "Voicemail"
    return (f"{stamp} - " if stamp else "") \
        + safe_filename(title, "Voicemail", 60) + extension


def extension_of(row):
    return os.path.splitext(row["audio"])[1].lower() or ".amr"


def write_audio(folder, rows, copy_file):
    """Copy the voicemails' audio into *folder* (named by date and caller)
    with the words of each beside it as a text file. Returns
    ``(paths, notes)``."""
    os.makedirs(folder, exist_ok=True)
    used, paths, missing = set(), [], []
    for row in rows:
        base = friendly_name(row, "")
        name = base + extension_of(row)
        number = 1
        while name.casefold() in used:
            number += 1
            name = f"{base} ({number}){extension_of(row)}"
        used.add(name.casefold())
        if row["audio"] and copy_file(row["audio"], folder, name):
            paths.append(os.path.join(folder, name))
        else:
            missing.append(base)
        if row["transcript"]:
            stem = os.path.splitext(name)[0]
            target = os.path.join(folder, stem + ".txt")
            write_text_file(target, row["transcript"] + "\n")
            paths.append(target)
    notes = ""
    if missing:
        notes = (f"{len(missing):,} voicemail(s) have no audio in the "
                 "backup and were skipped: " + ", ".join(missing[:5])
                 + (", ..." if len(missing) > 5 else ""))
    return paths, notes


def _details(row):
    from .common import format_datetime
    lines = [row["from"]]
    if row["name"] and row["number"]:
        lines.append(f"Number: {row['number']}")
    if row["callback"] and row["callback"] != row["number"]:
        lines.append(f"Call back: {row['callback']}")
    lines.append(format_datetime(row["when"]))
    if row["length"]:
        lines.append(f"Length: {describe_duration(row['length'])}")
    if row["deleted"]:
        lines.append(f"Deleted: {format_datetime(row['deleted'])}")
    lines.append("")
    lines.append(row["transcript"] or (
        "(no transcript)" if row["has_transcript"] is False
        else "(the transcript is empty)"))
    return "\n".join(lines)


def datasets(conn, book, index, folder=None):
    rows = voicemail_rows(conn, book, index, folder)
    if not rows:
        return []
    return [Dataset(
        "voicemail", "Voicemail", [
            Column("when", "When", 140, "date"),
            Column("from", "From", 200),
            Column("number", "Number", 130),
            Column("length", "Length", 70, "duration", "e"),
            Column("transcript", "What was said", 420),
            Column("deleted", "Deleted", 130, "date")],
        rows, sort=("when", True), details=_details,
        actions=(("Play", "play"), ("Save audio...", "save")),
        note="Double-click a voicemail to play it. The words are the "
             "phone's own transcript, written on the phone, so they can be "
             "wrong.",
        file_formats={"audio": (
            "Audio files with the words as text (named by date and caller)",
            write_audio)})]


class VoicemailReader:
    def __init__(self, conn, book, index):
        self.conn, self.book, self.index = conn, book, index

    def datasets(self):
        return datasets(self.conn, self.book, self.index)
