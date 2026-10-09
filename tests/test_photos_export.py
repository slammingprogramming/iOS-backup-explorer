# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Exporting pictures, videos and voice recordings."""

import csv
import io
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from ios_apps import imaging
from ios_apps import photos as ph
from ios_apps import photos_export as px
from ios_apps import voice_memos as vm
from ios_apps import voice_memos_export as vx
from tests import fixture_media as fm
from tests.test_photos import connect, index_of


def read(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


def fake_backup(files):
    """A ``copy_file`` that serves *files* (``(domain, path, bytes, ...)``)."""
    store = {f"{entry[0]}/{entry[1]}": entry[2] for entry in files}

    def copy(path, directory, name):
        data = store.get(path)
        if data is None:
            return False
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, name), "wb") as handle:
            handle.write(data)
        return True

    return copy


class ExportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-photox-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.files = fm.camera_files()
        self.items = ph.scan(index_of(self.files))
        ph.enrich(self.items, connect(self, fm.build_library))
        self.copy = fake_backup(self.files)
        self.out = os.path.join(self.tmp, "out")
        self.scratch = os.path.join(self.tmp, "scratch")

    def export(self, fmt, items=None, **kw):
        return px.export(self.items if items is None else items, fmt,
                         self.out, self.copy, self.scratch, **kw)

    def listing(self, folder=None):
        folder = folder or self.out
        return sorted(os.path.relpath(os.path.join(root, name), folder)
                      .replace("\\", "/")
                      for root, _dirs, names in os.walk(folder)
                      for name in names)


class CopyTests(ExportCase):
    def test_originals_with_unique_names_and_the_date_taken(self):
        paths, notes = self.export("copy")
        self.assertEqual(notes, "")
        self.assertEqual(self.listing(), sorted([
            "DCIM_101APPLE_IMG_0001.PNG", "IMG_0001.PNG", "IMG_0002.JPG",
            "IMG_0003.HEIC", "IMG_0004.MOV", "IMG_E0002.JPG"]))
        self.assertEqual(len(paths), 6)
        by = {i.path: i for i in self.items}
        first = next(i for i in self.items
                     if i.path.endswith("100APPLE/IMG_0001.PNG"))
        self.assertEqual(read(os.path.join(self.out, "IMG_0001.PNG"), "rb"),
                         fm.picture_bytes("PNG"))
        self.assertAlmostEqual(
            os.path.getmtime(os.path.join(self.out, "IMG_0001.PNG")),
            first.taken, delta=2)
        self.assertEqual(len(by), 6)

    def test_bytes_are_untouched(self):
        self.export("copy")
        store = {os.path.basename(e[1]): e[2] for e in self.files
                 if e[1].startswith(f"{fm.DCIM}/100APPLE/")}
        for name in ("IMG_0002.JPG", "IMG_0003.HEIC", "IMG_0004.MOV"):
            self.assertEqual(read(os.path.join(self.out, name), "rb"),
                             store[name], name)

    def test_items_the_backup_lacks_are_skipped_and_reported(self):
        ghost = ph.MediaItem(f"{fm.CAMERA}/{fm.DCIM}/100APPLE/IMG_9999.JPG",
                             "IMG_9999.JPG", "DCIM/100APPLE")
        paths, notes = self.export("copy", self.items + [ghost])
        self.assertEqual(len(paths), 6)
        self.assertIn("1 item(s) are not in the backup", notes)
        self.assertIn("IMG_9999.JPG", notes)

    def test_progress(self):
        calls = []
        self.export("copy", progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls, [(n, 6) for n in range(1, 7)])

    def test_an_item_with_no_date_still_exports(self):
        item = ph.MediaItem(self.items[0].path, "x.png", "DCIM/100APPLE")
        paths, _ = self.export("copy", [item])
        self.assertEqual(len(paths), 1)


class CsvTests(ExportCase):
    def test_the_list(self):
        paths, notes = self.export("csv")
        self.assertEqual(notes, "")
        raw = read(paths[0], "rb")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"),
                                           newline="")))
        self.assertEqual(rows[0], list(px.CSV_COLUMNS))
        self.assertEqual(len(rows), 7)
        first = dict(zip(rows[0], next(
            r for r in rows[1:] if r[0] == "IMG_0001.PNG"
            and r[1].endswith("100APPLE"))))
        self.assertEqual((first["favorite"], first["albums"]),
                         ("yes", "Holiday; Favourites of 2026"))
        self.assertEqual(first["type"], "Photo (PNG)")
        self.assertEqual(first["latitude"], "47.6062")
        video = dict(zip(rows[0], next(r for r in rows[1:]
                                       if r[0] == "IMG_0004.MOV")))
        self.assertEqual(video["duration_seconds"], "12.5")
        trashed = [r for r in rows[1:] if r[11] == "yes"]
        self.assertEqual(len(trashed), 1)
        self.assertEqual(os.listdir(self.out), ["photos.csv"])    # no copies


@unittest.skipUnless(imaging.have_pillow(), "Pillow is not installed")
class JpegTests(ExportCase):
    def test_pictures_become_jpeg_and_the_rest_stays(self):
        paths, notes = self.export("jpeg")
        names = self.listing()
        self.assertIn("IMG_0001.jpg", names)               # from the PNG
        self.assertNotIn("IMG_0001.PNG", names)
        self.assertIn("IMG_0002.JPG", names)               # already JPEG
        self.assertIn("IMG_0004.MOV", names)               # a video
        self.assertIn("DCIM_101APPLE_IMG_0001.jpg", names)
        self.assertEqual(read(os.path.join(self.out, "IMG_0002.JPG"), "rb"),
                         fm.picture_bytes("JPEG", colour=(60, 200, 60)))
        self.assertEqual(read(os.path.join(self.out, "IMG_0004.MOV"), "rb"),
                         fm.VIDEO_BYTES)
        from PIL import Image
        with Image.open(os.path.join(self.out, "IMG_0001.jpg")) as image:
            self.assertEqual((image.format, image.size), ("JPEG", (48, 32)))
        self.assertEqual(len(paths), 6)

    @unittest.skipUnless(imaging.have_heif(), "pillow-heif is not installed")
    def test_heic_pictures_are_converted(self):
        self.export("jpeg")
        from PIL import Image
        with Image.open(os.path.join(self.out, "IMG_0003.jpg")) as image:
            self.assertEqual(image.format, "JPEG")
        self.assertNotIn("IMG_0003.HEIC", self.listing())

    def test_the_working_copies_are_cleaned_up(self):
        self.export("jpeg")
        self.assertEqual(os.listdir(self.scratch), [])

    def test_a_converted_name_never_replaces_another_file(self):
        png = ph.MediaItem(f"{fm.CAMERA}/{fm.DCIM}/100APPLE/IMG_0001.PNG",
                           "IMG_0001.PNG", "DCIM/100APPLE")
        jpg = ph.MediaItem(f"{fm.CAMERA}/{fm.DCIM}/100APPLE/IMG_0002.JPG",
                           "IMG_0002.JPG", "DCIM/100APPLE")
        same = ph.MediaItem(f"{fm.CAMERA}/{fm.DCIM}/100APPLE/IMG_0002.JPG",
                            "IMG_0001.JPG", "DCIM/100APPLE")
        files = [(fm.CAMERA, png.path[len(fm.CAMERA) + 1:], fm.picture_bytes(
            "PNG")), (fm.CAMERA, jpg.path[len(fm.CAMERA) + 1:],
                      fm.picture_bytes("JPEG"))]
        copy = fake_backup(files)
        # the PNG will be IMG_0001.jpg; a real JPEG named IMG_0001.JPG
        # (differing only in case) must not be overwritten by it
        jpeg_named_like_it = ph.MediaItem(jpg.path, "IMG_0001.JPG",
                                          "DCIM/101APPLE")
        paths, _ = px.export([jpeg_named_like_it, png], "jpeg", self.out,
                             copy, self.scratch)
        self.assertEqual(len(paths), 2)
        names = [n.casefold() for n in os.listdir(self.out)]
        self.assertEqual(len(set(names)), 2)
        self.assertTrue(same)

    def test_a_name_given_up_can_be_used_by_the_next_picture(self):
        # x.png cannot be converted, so it is kept as x.png and the name
        # x.jpg it had been given is free again for the real JPEG after it
        png = ph.MediaItem(f"{fm.CAMERA}/{fm.DCIM}/100APPLE/x.png", "x.png",
                           "DCIM/100APPLE")
        jpg = ph.MediaItem(f"{fm.CAMERA}/{fm.DCIM}/101APPLE/x.jpg", "x.jpg",
                           "DCIM/101APPLE")
        copy = fake_backup([
            (fm.CAMERA, f"{fm.DCIM}/100APPLE/x.png", fm.picture_bytes("PNG")),
            (fm.CAMERA, f"{fm.DCIM}/101APPLE/x.jpg",
             fm.picture_bytes("JPEG"))])
        with mock.patch.object(imaging, "to_jpeg", return_value=False):
            px.export([png, jpg], "jpeg", self.out, copy, self.scratch)
        self.assertEqual(sorted(os.listdir(self.out)), ["x.jpg", "x.png"])

    def test_pictures_that_cannot_be_converted_are_copied_and_reported(self):
        with mock.patch.object(imaging, "to_jpeg", return_value=False):
            paths, notes = self.export("jpeg")
        self.assertIn("IMG_0001.PNG", self.listing())
        self.assertEqual(len(paths), 6)
        self.assertIn("could not be converted", notes)
        self.assertIn("pillow-heif", notes)
        self.assertEqual(os.listdir(self.scratch), [])

    def test_the_date_taken_is_kept(self):
        self.export("jpeg")
        taken = next(i.taken for i in self.items if i.name == "IMG_0004.MOV")
        self.assertAlmostEqual(
            os.path.getmtime(os.path.join(self.out, "IMG_0004.MOV")), taken,
            delta=2)


@unittest.skipUnless(imaging.have_pillow(), "Pillow is not installed")
class GalleryTests(ExportCase):
    def test_a_page_with_thumbnails_and_working_links(self):
        paths, notes = self.export("html")
        index = os.path.join(self.out, "index.html")
        self.assertEqual(paths[0], index)
        page = read(index, encoding="utf-8")
        self.assertIn("6 items", page)
        self.assertNotIn("<script", page)
        for target in re.findall(r"(?:href|src)=\"([^\"]+)\"", page):
            self.assertTrue(os.path.isfile(os.path.join(
                self.out, *target.replace("%20", " ").split("/"))), target)
        thumbs = os.listdir(os.path.join(self.out, "thumbs"))
        self.assertEqual(len(thumbs), 5)                    # not the video
        from PIL import Image
        with Image.open(os.path.join(self.out, "thumbs", thumbs[0])) as thumb:
            self.assertLessEqual(max(thumb.size), 240)
        self.assertIn("class=\"video\"", page)
        self.assertIn("0:12", page)

    def test_names_are_escaped(self):
        hostile = ph.MediaItem(
            f"{fm.CAMERA}/{fm.DCIM}/100APPLE/IMG_0001.PNG",
            "<img src=x onerror=alert(1)>.png", "DCIM/100APPLE")
        copy = fake_backup(self.files)
        px.export([hostile], "html", self.out, copy, self.scratch)
        page = read(os.path.join(self.out, "index.html"), encoding="utf-8")
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;.png", page)

    def test_without_thumbnails_the_pictures_themselves_are_shown(self):
        with mock.patch.object(px, "_thumbnail", return_value=False):
            self.export("html")
        page = read(os.path.join(self.out, "index.html"), encoding="utf-8")
        self.assertIn("src=\"photos/IMG_0001.jpg\"", page)


class OtherTests(ExportCase):
    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            self.export("zip")

    def test_nothing_to_export(self):
        for fmt in ("copy", "jpeg", "csv"):
            with self.subTest(fmt=fmt):
                paths, notes = px.export([], fmt, os.path.join(self.tmp, fmt),
                                         self.copy, self.scratch)
                self.assertEqual(notes, "")
                self.assertEqual(len(paths), 1 if fmt == "csv" else 0)


class VoiceMemoExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-memox-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.files = fm.memo_files()
        self.memos = vm.scan(index_of(self.files))
        vm.enrich(self.memos, connect(self, fm.build_memos_db))
        self.copy = fake_backup(self.files)
        self.out = os.path.join(self.tmp, "out")

    def test_friendly_names(self):
        by = {m.name: m for m in self.memos}
        name = vx.friendly_name(by["20260901 100000-AAA.m4a"])
        self.assertRegex(name,
                         r"^\d{4}-\d\d-\d\d \d{6} - Interview with Sam\.m4a$")
        self.assertRegex(vx.friendly_name(by["20260901 110000-BBB.m4a"]),
                         r" - 20260901 110000-BBB\.m4a$")
        bare = vm.Memo("D/a.m4a", "a.M4A", title='What?: "now"/<then>')
        self.assertEqual(vx.friendly_name(bare), 'What__ _now___then_.m4a')
        self.assertEqual(vx.friendly_name(vm.Memo("D/x.m4a", "x.m4a")),
                         "x.m4a")

    def test_audio_files_as_recorded(self):
        paths, notes = vx.export(self.memos, "audio", self.out, self.copy)
        self.assertEqual(notes, "")
        self.assertEqual(len(paths), 4)
        names = sorted(os.listdir(self.out))
        self.assertEqual(len(names), 4)
        interview = next(n for n in names if "Interview" in n)
        self.assertEqual(read(os.path.join(self.out, interview), "rb"),
                         fm.AUDIO)
        memo = next(m for m in self.memos if m.title == "Interview with Sam")
        self.assertAlmostEqual(
            os.path.getmtime(os.path.join(self.out, interview)), memo.when,
            delta=2)

    def test_two_recordings_with_the_same_title_and_second(self):
        same = [vm.Memo("D/1.m4a", "1.m4a", title="Same", when=1000.0),
                vm.Memo("D/2.m4a", "2.m4a", title="Same", when=1000.0)]
        copy = fake_backup([("D", "1.m4a", b"one"), ("D", "2.m4a", b"two")])
        vx.export(same, "audio", self.out, copy)
        names = sorted(os.listdir(self.out))
        self.assertEqual(len(names), 2)
        self.assertEqual({read(os.path.join(self.out, n), "rb")
                          for n in names}, {b"one", b"two"})

    def test_a_web_page_with_players(self):
        paths, _ = vx.export(self.memos, "html", self.out, self.copy)
        page = read(os.path.join(self.out, "index.html"), encoding="utf-8")
        self.assertEqual(paths[0], os.path.join(self.out, "index.html"))
        self.assertEqual(page.count("<audio controls"), 4)
        self.assertIn("Interview with Sam", page)
        self.assertIn("2:05", page)
        self.assertNotIn("<script", page)
        for target in re.findall(r"src=\"([^\"]+)\"", page):
            self.assertTrue(os.path.isfile(os.path.join(
                self.out, *target.replace("%20", " ").split("/"))), target)

    def test_titles_are_escaped_on_the_page(self):
        hostile = [vm.Memo("D/1.m4a", "1.m4a", title="<script>alert(1)"
                           "</script>", when=1000.0)]
        vx.export(hostile, "html", self.out,
                  fake_backup([("D", "1.m4a", b"x")]))
        page = read(os.path.join(self.out, "index.html"), encoding="utf-8")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_the_list(self):
        paths, notes = vx.export(self.memos, "csv", self.out, self.copy)
        rows = list(csv.reader(io.StringIO(
            read(paths[0], encoding="utf-8-sig"), newline="")))
        self.assertEqual(rows[0], list(vx.CSV_COLUMNS))
        self.assertEqual(len(rows), 5)
        interview = dict(zip(rows[0], next(
            r for r in rows[1:] if r[0] == "Interview with Sam")))
        self.assertEqual((interview["length_seconds"], interview["length"]),
                         ("125.4", "2:05"))
        self.assertEqual(os.listdir(self.out), ["voice-memos.csv"])

    def test_recordings_the_backup_lacks_are_skipped_and_reported(self):
        ghost = vm.Memo("D/ghost.m4a", "ghost.m4a", title="Ghost")
        paths, notes = vx.export(self.memos + [ghost], "audio", self.out,
                                 self.copy)
        self.assertEqual(len(paths), 4)
        self.assertIn("1 recording(s) are not in the backup", notes)
        self.assertIn("Ghost", notes)

    def test_progress_and_unknown_format(self):
        calls = []
        vx.export(self.memos, "audio", self.out, self.copy,
                  progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls, [(n, 4) for n in range(1, 5)])
        with self.assertRaises(ValueError):
            vx.export(self.memos, "mp3", self.out, self.copy)


if __name__ == "__main__":
    unittest.main()
