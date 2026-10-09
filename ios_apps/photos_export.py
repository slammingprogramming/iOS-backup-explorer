# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — exporting pictures and videos
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

"""Copies camera roll items out of the backup: as they are, converted to
JPEG so every program can open them, as a web gallery, or just listed in a
spreadsheet. No GUI.

Every file gets its date taken as its modification time, so a file manager
sorts the export the way the camera roll is sorted.
"""

import html
import os
import shutil

from . import imaging
from .common import format_datetime
from .export_util import (describe_duration, describe_size, href, html_page,
                          iso_utc, safe_filename, write_csv_file,
                          write_text_file)
from .photos import PHOTO, VIDEO, unique_names

FORMATS = {
    "copy": "Original files (exactly as in the backup, named by what they are)",
    "jpeg": "Pictures as JPEG (HEIC and others converted; videos as they are)",
    "html": "Web gallery (open in any browser; JPEG pictures and thumbnails)",
    "csv": "A list of the files (CSV, nothing is copied)",
}

THUMBNAIL = (240, 240)
_JPEG = {".jpg", ".jpeg"}

CSV_COLUMNS = ("name", "folder", "date_taken", "date_taken_utc", "type",
               "size_bytes", "width", "height", "duration_seconds",
               "favorite", "hidden", "recently_deleted", "albums",
               "latitude", "longitude", "backup_path")


def _yes(flag):
    return "yes" if flag else ""


def write_csv(path, items):
    rows = [[i.name, i.directory, format_datetime(i.taken, seconds=True),
             iso_utc(i.taken), i.type_label, i.size, i.width or "",
             i.height or "", f"{i.duration:g}" if i.duration else "",
             _yes(i.favorite), _yes(i.hidden), _yes(i.trashed),
             "; ".join(i.albums),
             "" if i.latitude is None else i.latitude,
             "" if i.longitude is None else i.longitude, i.path]
            for i in items]
    return write_csv_file(path, CSV_COLUMNS, rows)


class _Used:
    """File names already given out, ignoring case."""

    def __init__(self):
        self.names = set()

    def release(self, name):
        self.names.discard(name.casefold())

    def take(self, name):
        base, ext = os.path.splitext(name)
        candidate, number = name, 1
        while candidate.casefold() in self.names:
            number += 1
            candidate = f"{base} ({number}){ext}"
        self.names.add(candidate.casefold())
        return candidate


def _touch(path, item):
    if item.taken:
        try:
            os.utime(path, (item.taken, item.taken))
        except (OSError, OverflowError, ValueError):
            pass


def _converted_name(name):
    return os.path.splitext(name)[0] + ".jpg"


def _make_jpeg(item, wanted, directory, copy_file, scratch, used):
    """Put *item* in *directory* as a JPEG picture. A video, a picture that
    is a JPEG already, and a picture that cannot be converted are put there
    as they are. *wanted* is the file's name. Returns ``(name, converted)``,
    or ``(None, False)`` if the backup does not have the file."""
    if item.kind == VIDEO or item.extension in _JPEG:
        name = used.take(wanted)
        if copy_file(item.path, directory, name):
            return name, False
        used.release(name)
        return None, False
    working = "working" + item.extension
    if not copy_file(item.path, scratch, working):
        return None, False
    source = os.path.join(scratch, working)
    try:
        final = used.take(_converted_name(wanted))
        if imaging.to_jpeg(source, os.path.join(directory, final)):
            return final, True
        used.release(final)
        name = used.take(wanted)
        shutil.copyfile(source, os.path.join(directory, name))
        return name, False
    finally:
        os.remove(source)


def _thumbnail(source, destination):
    """A small JPEG of the picture at *source*. True on success."""
    image = imaging.make_thumbnail(source, THUMBNAIL)
    if image is None:
        return False
    try:
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(destination, "JPEG", quality=80)
        return True
    except Exception:
        return False


def _gallery_html(entries):
    cells = []
    for item, photo, thumb in entries:
        caption = [html.escape(item.name)]
        if item.taken:
            caption.append(html.escape(format_datetime(item.taken)))
        if item.kind == VIDEO and item.duration:
            caption.append(html.escape(describe_duration(item.duration)))
        target = html.escape(href(photo), quote=True)
        if thumb:
            visual = (f"<img loading=\"lazy\" src=\""
                      f"{html.escape(href(thumb), quote=True)}\" alt=\"\">")
        elif item.kind == PHOTO and imaging.extension(photo) in \
                imaging.BROWSER_EXTENSIONS:
            visual = f"<img loading=\"lazy\" src=\"{target}\" alt=\"\">"
        else:
            visual = ("<span class=\"tile\">"
                      f"{'video' if item.kind == VIDEO else 'file'}</span>")
        badge = " class=\"video\"" if item.kind == VIDEO else ""
        cells.append(f"<figure{badge}><a href=\"{target}\">{visual}</a>"
                     f"<figcaption>{' &middot; '.join(caption)}"
                     "</figcaption></figure>")
    body = (f"<h1>Photos and videos</h1><div class=\"meta\">{len(entries):,} "
            f"items</div><div class=\"grid\">{''.join(cells)}</div>")
    return html_page("Photos and videos", body, _CSS)


_CSS = """
main{max-width:1100px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
gap:12px;margin-top:12px}
figure{margin:0;background:var(--card);border-radius:10px;padding:6px}
figure img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:6px;
display:block}
figure .tile{display:flex;align-items:center;justify-content:center;
aspect-ratio:1;color:var(--muted)}
figcaption{font-size:.72rem;color:var(--muted);margin-top:4px;
overflow-wrap:anywhere}
figure.video figcaption::before{content:"\\25B6  "}
"""


def export(items, fmt, folder, copy_file=None, scratch=None, progress=None):
    """Write *items* as *fmt* into *folder*.

    *copy_file(backup path, directory, name)* copies a file out of the
    backup and says whether it was there; *scratch* is a folder for working
    copies; *progress(done, total)* is called as items are finished.
    Returns ``(paths, notes)``: the files written and a text about anything
    that did not go perfectly (empty when all went well).
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    os.makedirs(folder, exist_ok=True)
    if fmt == "csv":
        return write_csv(os.path.join(folder, "photos.csv"), items), ""
    names = unique_names(items)
    used, paths = _Used(), []
    missing, unconverted = [], []
    total = len(items)
    if fmt == "copy":
        for done, item in enumerate(items, 1):
            name = used.take(names[item.path])
            if copy_file(item.path, folder, name):
                _touch(os.path.join(folder, name), item)
                paths.append(os.path.join(folder, name))
            else:
                missing.append(item.name)
            if progress:
                progress(done, total)
    else:
        gallery = fmt == "html"
        photo_dir = os.path.join(folder, "photos") if gallery else folder
        thumb_dir = os.path.join(folder, "thumbs")
        os.makedirs(photo_dir, exist_ok=True)
        if gallery:
            os.makedirs(thumb_dir, exist_ok=True)
        os.makedirs(scratch, exist_ok=True)
        entries = []
        for done, item in enumerate(items, 1):
            final, converted = _make_jpeg(item, names[item.path], photo_dir,
                                          copy_file, scratch, used)
            if final is None:
                missing.append(item.name)
            else:
                path = os.path.join(photo_dir, final)
                if item.kind == PHOTO and not converted \
                        and item.extension not in _JPEG:
                    unconverted.append(item.name)
                _touch(path, item)
                paths.append(path)
                thumb = ""
                if gallery and item.kind == PHOTO:
                    thumb_name = safe_filename(os.path.splitext(final)[0],
                                               "thumb") + ".jpg"
                    if _thumbnail(path, os.path.join(thumb_dir, thumb_name)):
                        thumb = f"thumbs/{thumb_name}"
                relative = f"photos/{final}" if gallery else final
                entries.append((item, relative, thumb))
            if progress:
                progress(done, total)
        if gallery:
            index = os.path.join(folder, "index.html")
            write_text_file(index, _gallery_html(entries))
            paths.insert(0, index)
    notes = []
    if missing:
        notes.append(f"{len(missing):,} item(s) are not in the backup and "
                     "were skipped: " + ", ".join(missing[:5])
                     + (", ..." if len(missing) > 5 else ""))
    if unconverted:
        notes.append(f"{len(unconverted):,} picture(s) could not be "
                     "converted and were copied as they are (HEIC needs "
                     "Pillow and pillow-heif: pip install Pillow "
                     "pillow-heif): " + ", ".join(unconverted[:5])
                     + (", ..." if len(unconverted) > 5 else ""))
    return paths, "\n".join(notes)
