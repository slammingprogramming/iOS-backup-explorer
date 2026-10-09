# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — exporting notes
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

"""Writes notes as plain text, Markdown, a web page, a PDF, JSON or a
spreadsheet. No GUI.

Notes go into folders named like the Notes app's folders. Attachments are
copied once into ``attachments/`` and linked from the text, the Markdown
and the web page (HEIC pictures are converted to JPEG if pillow-heif is
installed, so every browser can show them).
"""

import copy
import dataclasses
import html
import json
import os
import re
import shutil

from . import audio_tools, imaging, notes as nt
from .common import format_datetime
from .export_util import (href, html_page, iso_utc, safe_filename,
                          write_csv_file, write_text_file)

FORMATS = {
    "txt": "Text (.txt, one file per note)",
    "md": "Markdown (.md, one file per note)",
    "html": "Web page (open in any browser, with pictures)",
    "pdf": "PDF (one file per note)",
    "json": "JSON (all notes, for programs)",
    "csv": "Spreadsheet (CSV, one row per note)",
}

RECORDINGS = {
    "mixed": "The mixed recording (.m4a), the two sides on one track",
    "original": "The original file (.mov), with the separate tracks",
    "both": "Both",
}
"""Which file of a call recording to export, when it was saved as a mixed
audio file and as the original movie file with a track for each side."""

_STYLE_NAMES = {nt.TITLE: "title", nt.HEADING: "heading",
                nt.SUBHEADING: "subheading", nt.MONOSPACED: "monospaced",
                nt.BULLET: "bullet", nt.DASH: "dash", nt.NUMBERED: "numbered",
                nt.CHECKBOX: "checkbox", -1: "body"}


def formats():
    """The formats to offer; PDF is flagged when its library is missing."""
    from . import pdf_export
    result = dict(FORMATS)
    if not pdf_export.available():
        result["pdf"] += " - needs: pip install fpdf2"
    return result


# ── Where things go ──────────────────────────────────────────

def folder_path(note, folders_by_pk):
    """``Recipes/Soups`` for a note in the folder Soups inside Recipes."""
    parts, seen = [], set()
    folder = folders_by_pk.get(note.folder)
    while folder is not None and folder.pk not in seen:
        seen.add(folder.pk)
        parts.append(safe_filename(folder.title, "Notes"))
        folder = folders_by_pk.get(folder.parent)
    return "/".join(reversed(parts)) or "Notes"


class _Names:
    """Hands out file names that never collide, even on a case-insensitive
    file system."""

    def __init__(self):
        self._used = set()

    def unique(self, directory, stem, extension):
        base = safe_filename(stem, "Untitled note")
        name, number = f"{base}.{extension}", 1
        while (directory, name.lower()) in self._used:
            number += 1
            name = f"{base} ({number}).{extension}"
        self._used.add((directory, name.lower()))
        return name


def plan(notes, folders_by_pk, extension):
    """``[(note, relative path)]``: where each note's file goes."""
    names, result = _Names(), []
    for note in notes:
        directory = folder_path(note, folders_by_pk)
        name = names.unique(directory, note.title, extension)
        result.append((note, f"{directory}/{name}"))
    return result


# ── Text ─────────────────────────────────────────────────────

def attachment_text(attachment):
    """What an attachment looks like in plain text."""
    if attachment is None:
        return "[attachment]"
    if attachment.kind == "inline":
        return attachment.label
    if attachment.kind == "url":
        return (f"{attachment.title} <{attachment.url}>" if attachment.title
                and attachment.url else attachment.url or attachment.title
                or "[link]")
    return f"[{attachment.label}]"


def _prefix(paragraph):
    pad = "    " * paragraph.indent
    if paragraph.style == nt.CHECKBOX:
        return f"{pad}[{'x' if paragraph.checked else ' '}] "
    if paragraph.style == nt.BULLET:
        return f"{pad}• "
    if paragraph.style == nt.DASH:
        return f"{pad}- "
    if paragraph.style == nt.NUMBERED:
        return f"{pad}{paragraph.number}. "
    return ""


def _plain(paragraph, note):
    out = []
    for span in paragraph.spans:
        out.append(attachment_text(note.attachments.get(span.attachment))
                   if span.attachment else span.text)
    return "".join(out)


def transcripts(paragraph, note):
    """The words of the recordings in *paragraph* (a call recording carries
    what was said, as far as Notes wrote it down)."""
    found = []
    for span in paragraph.spans:
        attachment = note.attachments.get(span.attachment) \
            if span.attachment else None
        if attachment is not None and attachment.text:
            found.append(attachment.text)
    return found


def note_to_text(note):
    lines = []
    for paragraph in note.paragraphs:
        lines.append(_prefix(paragraph) + _plain(paragraph, note))
        for words in transcripts(paragraph, note):
            lines.extend("    " + line for line in words.splitlines())
    text = "\n".join(lines).rstrip("\n")
    if note.error and not note.paragraphs:
        text = note.error
    return text + "\n"


# ── Markdown ─────────────────────────────────────────────────

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>|~])")


_MD_LINE_START = re.compile(r"^\s*(\d+[.)]|[-+])(?=\s)")
_MD_HEADING_START = re.compile(r"^\s*(#{1,6})(?=\s|$)")


def _guard_list_syntax(body):
    """Keep a paragraph that starts like a list item ("1. ", "- ") or a
    heading ("# ") from turning into one."""
    match = _MD_LINE_START.match(body)
    if match:
        at = match.end(1) - 1      # before the "." / ")" / "-" / "+"
    else:
        match = _MD_HEADING_START.match(body)
        if not match:
            return body
        at = match.start(1)
    return body[:at] + "\\" + body[at:]


def _md_escape(text):
    return _MD_SPECIAL.sub(r"\\\1", text)


def _md_wrap(text, marker):
    """Put emphasis markers around *text*, keeping surrounding spaces
    outside them (Markdown does not emphasise ``** word **``)."""
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[:len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()):]
    return f"{lead}{marker}{stripped}{marker}{tail}"


def _md_span(span, note, files):
    if span.attachment:
        attachment = note.attachments.get(span.attachment)
        return _md_attachment(attachment, files)
    text = _md_escape(span.text)
    if span.strike:
        text = _md_wrap(text, "~~")
    if span.italic:
        text = _md_wrap(text, "*")
    if span.bold:
        text = _md_wrap(text, "**")
    if span.link and text.strip():
        text = f"[{text}]({span.link.replace(' ', '%20').replace(')', '%29')})"
    return text


def _md_attachment(attachment, files):
    if attachment is None:
        return "*[attachment]*"
    if attachment.kind == "inline":
        return _md_escape(attachment.label)
    if attachment.kind == "url":
        label = _md_escape(attachment.title or attachment.url)
        return f"[{label}]({attachment.url})" if attachment.url else label
    relative = files.get(attachment.ident)
    label = _md_escape(attachment.label)
    if not relative:
        return f"*[{label}]*"
    target = href(relative)
    if attachment.kind == "image" and imaging.extension(relative) in \
            imaging.BROWSER_EXTENSIONS:
        return f"![{_md_escape(attachment.name)}]({target})"
    link = f"[{label}]({target})"
    extra = files.get("also:" + attachment.ident)
    if extra:
        link += " (also: " + ", ".join(
            f"[{_md_escape(name)}]({href(rel)})" for name, rel in extra) + ")"
    return link


def note_to_markdown(note, files=None):
    """*files* maps an attachment identifier to a path relative to the
    note's file."""
    files = files or {}
    out, in_code, after_list = [], False, False
    for paragraph in note.paragraphs:
        mono = paragraph.style == nt.MONOSPACED
        if mono != in_code:
            out.append("```")
            in_code = mono
        if mono:
            out.append(_plain(paragraph, note))
            continue
        body = "".join(_md_span(s, note, files) for s in paragraph.spans)
        if paragraph.style not in nt.LIST_STYLES:
            if after_list:
                out.append("")        # or it would join the list item
            body = _guard_list_syntax(body)
        after_list = paragraph.style in nt.LIST_STYLES
        pad = "    " * paragraph.indent
        style = paragraph.style
        if style == nt.TITLE:
            out.append(f"# {body}")
        elif style == nt.HEADING:
            out.append(f"## {body}")
        elif style == nt.SUBHEADING:
            out.append(f"### {body}")
        elif style in (nt.BULLET, nt.DASH):
            out.append(f"{pad}- {body}")
        elif style == nt.NUMBERED:
            out.append(f"{pad}{paragraph.number}. {body}")
        elif style == nt.CHECKBOX:
            out.append(f"{pad}- [{'x' if paragraph.checked else ' '}] {body}")
        else:
            out.append(body)
        # headings and plain paragraphs need a blank line after them
        if style not in nt.LIST_STYLES:
            for words in transcripts(paragraph, note):
                out.append("")
                out.extend("> " + _md_escape(line)
                           for line in words.splitlines())
            out.append("")
    if in_code:
        out.append("```")
    if not note.paragraphs and note.error:
        out.append(f"*{note.error}*")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n") + "\n"


# ── HTML ─────────────────────────────────────────────────────

_CSS = """
h2{font-size:1.2rem}h3{font-size:1.05rem}
pre{background:var(--card);padding:10px 12px;border-radius:8px;
overflow-x:auto}
ul.check{list-style:none;padding-left:1.2em}
.note img{max-width:100%;border-radius:10px;display:block;margin:6px 0}
.note audio,.note video{max-width:100%;display:block;margin:6px 0}
.chip{background:var(--card);border-radius:6px;padding:1px 6px}
.locked{color:var(--muted);font-style:italic}
.transcript{color:var(--muted);margin:4px 0 8px}
"""


def _html_span(span, note, files):
    if span.attachment:
        return _html_attachment(note.attachments.get(span.attachment), files)
    text = html.escape(span.text)
    if span.bold:
        text = f"<strong>{text}</strong>"
    if span.italic:
        text = f"<em>{text}</em>"
    if span.underline:
        text = f"<u>{text}</u>"
    if span.strike:
        text = f"<s>{text}</s>"
    if span.link and _safe_url(span.link):
        text = (f"<a href=\"{html.escape(span.link, quote=True)}\" "
                f"rel=\"noopener noreferrer\">{text}</a>")
    return text


def _safe_url(url):
    """Links in notes are only followed if they are ordinary web, mail or
    phone links (never ``javascript:`` and the like)."""
    return url.strip().lower().startswith(("http://", "https://", "mailto:",
                                           "tel:"))


def _html_attachment(attachment, files):
    if attachment is None:
        return "<span class=\"chip\">[attachment]</span>"
    if attachment.kind == "inline":
        return f"<span class=\"chip\">{html.escape(attachment.label)}</span>"
    if attachment.kind == "url":
        label = html.escape(attachment.title or attachment.url)
        if attachment.url and _safe_url(attachment.url):
            return (f"<a href=\"{html.escape(attachment.url, quote=True)}\" "
                    f"rel=\"noopener noreferrer\">{label}</a>")
        return label
    relative = files.get(attachment.ident)
    label = html.escape(attachment.label)
    if not relative:
        return f"<span class=\"chip\">{label} (not exported)</span>"
    target = html.escape(href(relative), quote=True)
    ext = imaging.extension(relative)
    if attachment.kind == "image" and ext in imaging.BROWSER_EXTENSIONS:
        return (f"<a href=\"{target}\"><img loading=\"lazy\" src=\"{target}\""
                f" alt=\"{html.escape(attachment.name)}\"></a>")
    if attachment.kind == "audio":
        extra = "".join(
            f" &middot; <a href=\"{html.escape(href(rel), quote=True)}\">"
            f"{html.escape(name)}</a>"
            for name, rel in files.get("also:" + attachment.ident, ()))
        return (f"<audio controls preload=\"none\" src=\"{target}\"></audio>"
                f"<a href=\"{target}\">{label}</a>{extra}")
    if attachment.kind == "video":
        return (f"<video controls preload=\"none\" src=\"{target}\"></video>"
                f"<a href=\"{target}\">{label}</a>")
    return f"<a href=\"{target}\">{label}</a>"


_LIST_TAG = {nt.BULLET: "ul", nt.DASH: "ul", nt.CHECKBOX: "ul",
             nt.NUMBERED: "ol"}


def note_to_html_body(note, files=None):
    """The HTML for a note's content (without the page around it)."""
    files = files or {}
    out, stack, in_pre = [], [], False

    def close_lists(depth=0):
        while len(stack) > depth:
            out.append(f"</{stack.pop()[0]}>")

    for paragraph in note.paragraphs:
        style = paragraph.style
        mono = style == nt.MONOSPACED
        if in_pre and not mono:
            out.append("</pre>")
            in_pre = False
        if style in _LIST_TAG:
            tag = _LIST_TAG[style]
            kind = (tag, style == nt.CHECKBOX)
            depth = paragraph.indent + 1
            close_lists(depth)
            # a different kind of list at this level starts a new list
            if len(stack) == depth and stack[-1] != kind:
                out.append(f"</{stack.pop()[0]}>")
            while len(stack) < depth:
                css = " class=\"check\"" if kind[1] else ""
                out.append(f"<{tag}{css}>")
                stack.append(kind)
            body = "".join(_html_span(s, note, files)
                           for s in paragraph.spans)
            if style == nt.CHECKBOX:
                box = ("<input type=\"checkbox\" disabled"
                       + (" checked" if paragraph.checked else "") + "> ")
                body = box + body
            out.append(f"<li>{body}</li>")
            continue
        close_lists()
        if mono:
            if not in_pre:
                out.append("<pre>")
                in_pre = True
            out.append(html.escape(_plain(paragraph, note)) + "\n")
            continue
        body = "".join(_html_span(s, note, files) for s in paragraph.spans)
        tag = {nt.TITLE: "h1", nt.HEADING: "h2",
               nt.SUBHEADING: "h3"}.get(style, "p")
        out.append(f"<{tag}>{body}</{tag}>" if body.strip()
                   else "<p>&nbsp;</p>")
        for words in transcripts(paragraph, note):
            out.append("<details class=\"transcript\"><summary>Words of the "
                       "recording</summary><p>"
                       + html.escape(words).replace("\n", "<br>")
                       + "</p></details>")
    close_lists()
    if in_pre:
        out.append("</pre>")
    if note.error and not note.paragraphs:
        out.append(f"<p class=\"locked\">{html.escape(note.error)}</p>")
    return "".join(out)


def _meta_html(note, folders_by_pk):
    bits = [html.escape(folder_path(note, folders_by_pk).replace("/", " / "))]
    if note.modified:
        bits.append("edited " + html.escape(format_datetime(note.modified)))
    if note.created:
        bits.append("created " + html.escape(format_datetime(note.created)))
    return "<div class=\"meta\">" + " &middot; ".join(bits) + "</div>"


def note_to_html(note, folders_by_pk, files=None, index_link="index.html"):
    body = (f"<p><a href=\"{html.escape(index_link, quote=True)}\">"
            "&larr; All notes</a></p>"
            + _meta_html(note, folders_by_pk)
            + f"<div class=\"note\">{note_to_html_body(note, files)}</div>")
    return html_page(note.title, body, _CSS)


# ── JSON and spreadsheet ─────────────────────────────────────

def _note_dict(note, folders_by_pk, files):
    return {
        "id": note.pk, "title": note.title,
        "folder": folder_path(note, folders_by_pk),
        "created": iso_utc(note.created), "modified": iso_utc(note.modified),
        "pinned": note.pinned, "locked": note.locked,
        "recently_deleted": note.deleted, "text": note_to_text(note).rstrip(
            "\n") if note.paragraphs else "",
        "error": note.error,
        "paragraphs": [{
            "style": _STYLE_NAMES.get(p.style, str(p.style)),
            "indent": p.indent,
            **({"checked": p.checked} if p.style == nt.CHECKBOX else {}),
            **({"number": p.number} if p.style == nt.NUMBERED else {}),
            "spans": [{k: v for k, v in (
                ("text", s.text), ("bold", s.bold or None),
                ("italic", s.italic or None),
                ("underline", s.underline or None),
                ("strikethrough", s.strike or None),
                ("link", s.link or None),
                ("attachment", s.attachment or None)) if v is not None}
                for s in p.spans],
        } for p in note.paragraphs],
        "attachments": [{
            "id": a.ident, "kind": a.kind, "type": a.uti, "name": a.name,
            "url": a.url or None, "text": a.alt or None,
            "title": a.title or None,
            "duration_seconds": a.duration or None,
            "transcript": a.text or None,
            "file": files.get(a.key),
            "other_files": [files.get(v.key) for v in a.also
                            if files.get(v.key)] or None}
            for a in note.attachments.values()],
    }


def write_json(path, notes, folders_by_pk, files):
    data = [_note_dict(n, folders_by_pk, files) for n in notes]
    write_text_file(path, json.dumps(data, ensure_ascii=False, indent=2)
                    + "\n")
    return [path]


CSV_COLUMNS = ("title", "folder", "created", "modified", "pinned", "locked",
               "recently_deleted", "attachments", "text")


def write_csv(path, notes, folders_by_pk):
    rows = [[n.title, folder_path(n, folders_by_pk),
             format_datetime(n.created, seconds=True),
             format_datetime(n.modified, seconds=True),
             "yes" if n.pinned else "", "yes" if n.locked else "",
             "yes" if n.deleted else "",
             "; ".join(a.label for a in n.attachments.values()),
             note_to_text(n).rstrip("\n") if n.paragraphs else n.error]
            for n in notes]
    return write_csv_file(path, CSV_COLUMNS, rows)


# ── Putting it together ──────────────────────────────────────

def choose_recordings(notes, mode="mixed", can_mix=False):
    """Copies of *notes* in which each recording that exists in more than
    one form (see :func:`notes.recording_forms`) has just the file(s) *mode*
    asks for: ``mixed``, ``original`` (the one with separate tracks) or
    ``both`` (the mixed one is shown, the other is linked beside it). With
    *can_mix*, a recording that exists only as the original movie file also
    gets a mixed form, made on export. The notes given are not changed."""
    if mode not in RECORDINGS:
        raise ValueError(f"unknown recordings choice {mode!r}")
    chosen = []
    for note in notes:
        folded = {a.pk for a in note.attachments.values()
                  if a.pk and a.variants}
        attachments = {}
        for ident, attachment in note.attachments.items():
            if attachment.parent_pk and attachment.parent_pk in folded:
                continue                   # a file of its parent: see below
            forms = nt.recording_forms(attachment, can_mix)
            if len(forms) > 1:
                main, also = nt.pick_variants(attachment, mode, forms)
                attachment = dataclasses.replace(
                    attachment, path=main.path, name=main.name, mix=main.mix,
                    also=also)
            attachments[ident] = attachment
        copied = copy.copy(note)
        copied.attachments = attachments
        chosen.append(copied)
    return chosen


def attachment_plan(notes):
    """``{backup path: unique file name}`` and ``{backup path: Attachment}``
    for every attachment that has a file in the backup (and the further
    files of a recording to be exported in both forms)."""
    names, attachments = {}, {}
    for note in notes:
        for attachment in note.attachments.values():
            for item in [attachment] + list(attachment.also):
                key = item.key
                if not item.path or key in names:
                    continue
                names[key] = f"{len(names) + 1:05d}_" \
                    + safe_filename(item.name, "attachment", 100)
                attachments[key] = item
    return names, attachments


def _fetch_attachments(notes, folder, fetch, mixer=None):
    """Copy the attachments into ``folder/attachments`` and return
    ``{file key: relative file name}`` for those that arrived (HEIC
    pictures converted to JPEG where possible; a recording to be mixed
    is copied and mixed down with *mixer*, and when that fails the original
    file is kept instead)."""
    if fetch is None:
        return {}
    names, attachments = attachment_plan(notes)
    if not names:
        return {}
    directory = os.path.join(folder, "attachments")
    wanted, mixing = [], {}
    for path, name in names.items():
        if attachments[path].mix:
            # copy the original under a name of its own, then mix it down
            source = f"{os.path.splitext(name)[0]}.source" + \
                os.path.splitext(attachments[path].path)[1]
            mixing[path] = source
            wanted.append((attachments[path], source))
        else:
            wanted.append((attachments[path], name))
    arrived = set(fetch(wanted))
    result = {}
    for path, name in names.items():
        if path in mixing:
            source = mixing[path]
            if source not in arrived:
                continue
            made = mixer is not None and mixer(
                os.path.join(directory, source), os.path.join(directory, name))
            if made:
                os.remove(os.path.join(directory, source))
                result[path] = f"attachments/{name}"
            else:                      # keep what the phone recorded
                result[path] = f"attachments/{source}"
            continue
        if name not in arrived:
            continue
        final = name
        if imaging.extension(name) in imaging.HEIF_EXTENSIONS and \
                imaging.have_heif():
            source = os.path.join(folder, "attachments", name)
            jpeg = os.path.splitext(name)[0] + ".jpg"
            if imaging.to_jpeg(source, os.path.join(folder, "attachments",
                                                    jpeg)):
                final = jpeg
        result[path] = f"attachments/{final}"
    return result


def _relative_files(note, files, note_path):
    """The attachment links for *note*, relative to where its file is."""
    start = os.path.dirname(note_path) or "."

    def relative(path):
        return os.path.relpath(files[path], start).replace("\\", "/")

    links = {a.ident: relative(a.key)
             for a in note.attachments.values() if a.key in files}
    for a in note.attachments.values():
        extra = [(v.label, relative(v.key)) for v in a.also
                 if v.key in files]
        if extra:
            links["also:" + a.ident] = extra
    return links


def export(notes, folders_by_pk, fmt, folder, fetch_attachments=None,
           recordings="mixed", mixer=None):
    """Write *notes* (already loaded) as *fmt* into *folder*.

    *fetch_attachments(files)* is called with ``[(Attachment, file name)]``
    and must copy those files into ``folder/attachments`` and return the
    names that arrived. *recordings* says which file of a call recording to
    export: see :data:`RECORDINGS`. *mixer(source, destination)* mixes the
    tracks of a recording kept only as a movie file into one audio file
    (default: ffmpeg, if it is installed; when there is none, such a
    recording is exported as the original file whatever the choice).
    Returns the paths written.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    if mixer is None and audio_tools.available():
        mixer = audio_tools.mix_to_m4a
    notes = choose_recordings(notes, recordings, can_mix=mixer is not None)
    os.makedirs(folder, exist_ok=True)
    wants_files = fmt in ("md", "html", "json", "pdf")
    attachments_dir = os.path.join(folder, "attachments")
    had_attachments_dir = os.path.isdir(attachments_dir)
    files = _fetch_attachments(notes, folder, fetch_attachments, mixer) \
        if wants_files else {}
    if fmt == "json":
        return write_json(os.path.join(folder, "notes.json"), notes,
                          folders_by_pk, files)
    if fmt == "csv":
        return write_csv(os.path.join(folder, "notes.csv"), notes,
                         folders_by_pk)
    paths, listing = [], []
    for note, relative in plan(notes, folders_by_pk, fmt):
        target = os.path.join(folder, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if fmt == "txt":
            write_text_file(target, note_to_text(note))
        elif fmt == "md":
            write_text_file(target, note_to_markdown(
                note, _relative_files(note, files, relative)))
        elif fmt == "html":
            depth = relative.count("/")
            write_text_file(target, note_to_html(
                note, folders_by_pk, _relative_files(note, files, relative),
                "../" * depth + "index.html"))
            listing.append((note, relative))
        else:
            from . import pdf_export
            pdf_export.write_note_pdf(target, note, {
                a.ident: os.path.join(folder, *files[a.key].split("/"))
                for a in note.attachments.values()
                if a.kind == "image" and a.key in files})
        paths.append(target)
    if fmt == "pdf" and not had_attachments_dir:
        shutil.rmtree(attachments_dir, ignore_errors=True)  # only a means
    if fmt == "html":
        index = os.path.join(folder, "index.html")
        write_text_file(index, _index_html(listing, folders_by_pk))
        paths.insert(0, index)
    return paths


def _index_html(listing, folders_by_pk):
    groups = {}
    for note, relative in listing:
        groups.setdefault(folder_path(note, folders_by_pk), []).append(
            (note, relative))
    body = ["<h1>Notes</h1>",
            f"<div class=\"meta\">{len(listing):,} notes</div>"]
    for name in sorted(groups, key=str.lower):
        body.append(f"<h2>{html.escape(name.replace('/', ' / '))}</h2>"
                    "<ul class=\"list\">")
        for note, relative in groups[name]:
            when = format_datetime(note.modified)
            body.append(
                f"<li><a href=\"{html.escape(href(relative), quote=True)}\">"
                f"{html.escape(note.title)}</a>"
                + f"<div class=\"meta\">{html.escape(when)}"
                + "</div></li>")
        body.append("</ul>")
    return html_page("Notes", "".join(body), _CSS)
