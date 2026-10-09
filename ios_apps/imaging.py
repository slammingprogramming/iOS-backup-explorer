# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — pictures (optional Pillow / pillow-heif)
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

"""Showing and converting pictures, with optional help from Pillow and
pillow-heif (``pip install Pillow pillow-heif``).

Without Pillow, PNG and GIF pictures can still be shown by Tk itself; JPEG
and HEIC cannot, and the views fall back to a plain file entry. The original
file can always be extracted untouched. Nothing here needs a window except
:func:`photo_for_tk`.
"""

import os

try:
    from PIL import Image, ImageOps
except ImportError:                    # Pillow is optional
    Image = ImageOps = None

_heif_checked = False
_heif_ok = False

BROWSER_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
HEIF_EXTENSIONS = {".heic", ".heif", ".hif"}
IMAGE_EXTENSIONS = BROWSER_EXTENSIONS | HEIF_EXTENSIONS | {
    ".tif", ".tiff", ".dng"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".3gp"}


def have_pillow():
    return Image is not None


def have_heif():
    """True when HEIC pictures can be opened (pillow-heif is installed)."""
    global _heif_checked, _heif_ok
    if not _heif_checked:
        _heif_checked = True
        if Image is not None:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
                _heif_ok = True
            except Exception:          # not installed, or no working codec
                _heif_ok = False
    return _heif_ok


def extension(name):
    return os.path.splitext(name or "")[1].lower()


def can_show(name):
    """Whether a picture file called *name* can be drawn in a window."""
    ext = extension(name)
    if ext in HEIF_EXTENSIONS:
        return have_heif()
    if have_pillow():
        return ext in IMAGE_EXTENSIONS
    return ext in (".png", ".gif")


def open_image(path, draft=None):
    """The picture at *path* as a Pillow image, turned the way the camera
    was held. Raises if it cannot be read. *draft*, a ``(width, height)``,
    lets JPEGs be read at a reduced size, which is much faster when only a
    thumbnail is wanted."""
    if Image is None:
        raise RuntimeError("Pillow is not installed")
    if extension(path) in HEIF_EXTENSIONS:
        have_heif()
    with Image.open(path) as image:       # (closed again, even on failure)
        if draft:
            image.draft("RGB", draft)
        image.load()
        turned = ImageOps.exif_transpose(image)
        return turned if turned is not None else image.copy()


def make_thumbnail(path, box):
    """A Pillow image of *path* that fits in *box* ``(width, height)``, or
    None if the picture cannot be read. Safe to call on a worker thread."""
    if not can_show(path) or Image is None:
        return None
    try:
        image = open_image(path, draft=(box[0] * 2, box[1] * 2))
        image.thumbnail(box)
        return image.convert("RGB") if image.mode not in ("RGB", "RGBA") \
            else image
    except Exception:                  # damaged, truncated, unsupported
        return None


def photo_for_tk(path_or_image, box):
    """A Tk image for a file path or Pillow image, scaled down to *box*, or
    None. Call on the Tk thread (after a window exists)."""
    import tkinter as tk
    if Image is not None:
        image = path_or_image
        if isinstance(path_or_image, str):
            image = make_thumbnail(path_or_image, box)
        if image is None:
            return None
        from PIL import ImageTk
        return ImageTk.PhotoImage(image)
    if not isinstance(path_or_image, str) or \
            extension(path_or_image) not in (".png", ".gif"):
        return None
    try:
        photo = tk.PhotoImage(file=path_or_image)
    except tk.TclError:
        return None
    factor = max(1, -(-photo.width() // box[0]), -(-photo.height() // box[1]))
    return photo.subsample(factor) if factor > 1 else photo


def to_jpeg(source, destination, quality=92):
    """Convert a picture (such as a HEIC) to a JPEG file that every browser
    can show. Returns True on success."""
    if Image is None:
        return False
    try:
        image = open_image(source)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(destination, "JPEG", quality=quality)
        return True
    except Exception:
        return False


def image_size(path):
    """``(width, height)`` of a picture, or None."""
    try:
        return open_image(path).size
    except Exception:
        return None
