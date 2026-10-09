# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — PDF output (optional fpdf2)
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

"""Writes a note as a PDF with the optional ``fpdf2`` package
(``pip install fpdf2``).

Text in any language needs a font that has the letters. A common one is
looked up on the computer (Arial, DejaVu Sans...). Without one the PDF uses
the built-in Helvetica, which only has Western European letters; other
characters become ``?``. Emoji are left out either way.
"""

import os
import re
import tempfile

from . import imaging, notes as nt
from .notes_export import attachment_text, transcripts

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:                    # fpdf2 is optional
    FPDF = None

_FONT_SETS = [
    # (regular, bold, italic) in common places on Windows, macOS and Linux
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf",
     "C:/Windows/Fonts/ariali.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf",
     "C:/Windows/Fonts/segoeuii.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf",
     "/Library/Fonts/Arial Italic.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Oblique.ttf"),
]

_ASTRAL = re.compile("[\U00010000-\U0010ffff\u200d\ufe0f\u20e3]")
_SIZES = {nt.TITLE: 20, nt.HEADING: 16, nt.SUBHEADING: 13}


def available():
    return FPDF is not None


def find_font():
    """``(regular, bold, italic)`` font file paths (the last two may be
    None) of a font on this computer, or None."""
    for regular, bold, italic in _FONT_SETS:
        if os.path.isfile(regular):
            return (regular, bold if os.path.isfile(bold) else None,
                    italic if os.path.isfile(italic) else None)
    return None


class _Writer:
    def __init__(self):
        self.pdf = FPDF(format="A4")
        self.pdf.set_auto_page_break(True, 15)
        self.pdf.set_margins(18, 18, 18)
        self.family, self.unicode = "Helvetica", False
        fonts = find_font()
        if fonts:
            try:
                self.pdf.add_font("Body", "", fonts[0])
                self.pdf.add_font("Body", "B", fonts[1] or fonts[0])
                self.pdf.add_font("Body", "I", fonts[2] or fonts[0])
                self.pdf.add_font("Body", "BI", fonts[1] or fonts[0])
                self.family, self.unicode = "Body", True
            except Exception:          # a font we cannot use: fall back
                self.family, self.unicode = "Helvetica", False
        self.pdf.add_page()

    def clean(self, text):
        text = _ASTRAL.sub("", text.replace("\ufffc", ""))
        text = text.replace("\t", "    ")
        if not self.unicode:
            text = text.encode("latin-1", "replace").decode("latin-1")
        return text

    def font(self, size, bold=False, italic=False, mono=False):
        if mono and not self.unicode:
            self.pdf.set_font("Courier", "", size)
            return
        style = ("B" if bold else "") + ("I" if italic else "")
        self.pdf.set_font("Courier" if mono else self.family, style, size)

    def newline(self, height):
        self.pdf.ln(height)

    def paragraph(self, note, paragraph, images):
        pdf = self.pdf
        style = paragraph.style
        size = _SIZES.get(style, 11)
        height = size * 0.5 + 1.5
        indent = 6 * paragraph.indent
        if style in nt.LIST_STYLES:
            indent += 5
        left = pdf.l_margin
        pdf.set_left_margin(left + indent)
        pdf.set_x(left + indent)
        bold = style in _SIZES
        mono = style == nt.MONOSPACED
        if style in nt.LIST_STYLES:
            marker = {nt.BULLET: "\u2022", nt.DASH: "-",
                      nt.NUMBERED: f"{paragraph.number}.",
                      nt.CHECKBOX: "[x]" if paragraph.checked
                      else "[ ]"}[style]
            self.font(size)
            pdf.set_x(left + indent - 5)
            pdf.write(height, self.clean(marker) + " ")
        wrote = False
        for span in paragraph.spans:
            if span.attachment:
                attachment = note.attachments.get(span.attachment)
                image = images.get(span.attachment)
                if image:
                    self._image(image, height)
                    pdf.set_left_margin(left + indent)
                    pdf.set_x(left + indent)
                else:
                    self.font(size, italic=True)
                    pdf.write(height, self.clean(attachment_text(attachment)))
                wrote = True
                continue
            self.font(size, bold or span.bold, span.italic, mono)
            text = self.clean(span.text)
            if span.link and text.strip():
                pdf.set_text_color(11, 90, 200)
                pdf.write(height, text, link=span.link)
                pdf.set_text_color(0, 0, 0)
            else:
                pdf.write(height, text)
            wrote = True
        pdf.ln(height + (1 if wrote else 2))
        for words in transcripts(paragraph, note):
            self.font(size - 1, italic=True)
            pdf.multi_cell(0, height, self.clean(words),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_left_margin(left)
        pdf.set_x(left)

    def _image(self, path, height):
        pdf = self.pdf
        pdf.ln(height)
        width = pdf.w - pdf.l_margin - pdf.r_margin
        try:
            pdf.image(path, w=min(width, 120), x=pdf.l_margin)
        except Exception:
            self.font(10, italic=True)
            pdf.write(height, "[picture could not be shown]")
        pdf.ln(2)


def write_note_pdf(path, note, image_files=None):
    """Write *note* to *path*. *image_files* maps an attachment identifier
    to a local picture file to draw in the text."""
    if FPDF is None:
        raise RuntimeError("PDF export needs the fpdf2 package: "
                           "pip install fpdf2")
    writer = _Writer()
    images = {}
    scratch = tempfile.mkdtemp(prefix="ibe-pdf-")
    try:
        for ident, source in (image_files or {}).items():
            if imaging.extension(source) in (".png", ".jpg", ".jpeg"):
                images[ident] = source
            elif imaging.can_show(source):        # HEIC, WEBP...
                converted = os.path.join(scratch, f"{len(images)}.jpg")
                if imaging.to_jpeg(source, converted):
                    images[ident] = converted
        writer.font(20, bold=True)
        if not note.paragraphs:
            writer.pdf.write(10, writer.clean(note.title))
            writer.pdf.ln(12)
            if note.error:
                writer.font(11, italic=True)
                writer.pdf.multi_cell(0, 6, writer.clean(note.error),
                                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for paragraph in note.paragraphs:
            writer.paragraph(note, paragraph, images)
        writer.pdf.set_title(writer.clean(note.title))
        writer.pdf.output(path)
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
    return path
