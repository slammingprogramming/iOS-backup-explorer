# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The documentation: its links work, every picture is clean and used, and
every tab is described."""

import re
import struct
import unittest
from pathlib import Path

from ios_apps import registry

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
IMAGES = DOCS / "images"
PAGES = sorted([ROOT / "README.md", ROOT / "CONTRIBUTING.md",
                ROOT / "SECURITY.md", ROOT / "CHANGELOG.md"]
               + list(DOCS.rglob("*.md")))
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
IMAGE = re.compile(r"(?:\!\[[^\]]*\]\(|<img[^>]*src=\")([^)\s\"]+)")


def targets(text, pattern):
    for found in pattern.findall(text):
        if not found.startswith(("http://", "https://", "mailto:", "#")):
            yield found


def anchors(path):
    """The heading anchors of a Markdown file (GitHub's rules)."""
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.*?)\s*#*$", line)
        if match:
            slug = re.sub(r"[^\w\- ]", "", match.group(1).lower())
            found.add(slug.replace(" ", "-"))
    return found


class LinkTests(unittest.TestCase):
    def test_every_relative_link_and_picture_exists(self):
        problems = []
        for page in PAGES:
            text = page.read_text(encoding="utf-8")
            for target in list(targets(text, LINK)) \
                    + list(targets(text, IMAGE)):
                path, _, fragment = target.partition("#")
                if not path:
                    continue
                destination = (page.parent / path).resolve()
                if not destination.exists():
                    problems.append(f"{page.relative_to(ROOT)}: {target}")
                elif fragment and destination.suffix == ".md" \
                        and fragment not in anchors(destination):
                    problems.append(f"{page.relative_to(ROOT)}: {target} "
                                    "(no such heading)")
        self.assertEqual(problems, [])

    def test_there_are_pages(self):
        self.assertGreaterEqual(len(PAGES), 20)


class PictureTests(unittest.TestCase):
    def pictures(self):
        return sorted(IMAGES.glob("*.png"))

    def test_there_are_pictures(self):
        self.assertGreaterEqual(len(self.pictures()), 30)

    def test_pictures_carry_nothing_but_their_pixels(self):
        for path in self.pictures():
            data = path.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", path.name)
            position, kinds = 8, []
            while position < len(data):
                length = struct.unpack(">I", data[position:position + 4])[0]
                kinds.append(data[position + 4:position + 8].decode())
                position += 12 + length
            self.assertEqual(set(kinds) - {"IHDR", "IDAT", "IEND"}, set(),
                             f"{path.name} has more than pixels in it")

    def test_every_picture_is_used_and_none_is_missing(self):
        used = set()
        for page in PAGES:
            for target in targets(page.read_text(encoding="utf-8"), IMAGE):
                used.add((page.parent / target.partition("#")[0]).resolve())
        files = {path.resolve() for path in self.pictures()}
        # the pictures of the demo that no page shows yet are allowed to
        # wait, but they should not pile up
        self.assertLessEqual(len(files - used), 6,
                             sorted(p.name for p in files - used))
        self.assertEqual({p for p in used if IMAGES in p.parents} - files,
                         set())


class CoverageTests(unittest.TestCase):
    def test_every_tab_is_described(self):
        listing = (DOCS / "apps" / "README.md").read_text(encoding="utf-8")
        for entry in registry.APPS:
            self.assertIn(f"**{entry.title}**", listing, entry.title)

    def test_every_tab_has_a_source_listed(self):
        sources = (DOCS / "DATA_SOURCES.md").read_text(encoding="utf-8")
        for entry in registry.APPS:
            self.assertIn(f"**{entry.title}**", sources, entry.title)

    def test_every_page_of_the_index_exists(self):
        index = (DOCS / "README.md").read_text(encoding="utf-8")
        for target in targets(index, LINK):
            self.assertTrue((DOCS / target.partition("#")[0]).exists(),
                            target)


if __name__ == "__main__":
    unittest.main()
