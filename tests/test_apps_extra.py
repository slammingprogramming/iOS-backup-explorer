# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The shared helpers of the app views: export utilities, picture handling
and the working-copy plumbing."""

import concurrent.futures
import os
import shutil
import tempfile
import unittest
from unittest import mock

from file_index import FileIndex
from ios_apps import common
from ios_apps import export_util as eu
from ios_apps import imaging
from ios_apps.context import AppContext
from tests.fixture_apps import make_png


class OpenFileTests(unittest.TestCase):
    """Only pictures, video, audio and ordinary documents are handed to the
    computer's own programs: a file in a backup could be a program."""

    def run_open(self, name, platform="win32"):
        launched = []
        with mock.patch("sys.platform", platform), \
                mock.patch.object(os, "startfile", launched.append,
                                  create=True), \
                mock.patch("subprocess.Popen", launched.append):
            common.open_file(os.path.join("somewhere", name))
        return launched

    def test_ordinary_files_are_opened(self):
        for name in ("photo.JPG", "clip.mov", "memo.m4a", "doc.pdf",
                     "notes.txt", "sheet.xlsx", "a.heic"):
            with self.subTest(name=name):
                self.assertEqual(len(self.run_open(name)), 1)

    def test_programs_scripts_and_pages_are_not(self):
        for name in ("run.exe", "run.bat", "run.cmd", "run.com", "run.scr",
                     "run.js", "run.vbs", "run.ps1", "run.msi", "run.lnk",
                     "run.sh", "run.command", "run.app", "run.jar",
                     "run.py", "page.html", "page.svg", "page.htm",
                     "macro.docm", "noextension", "x.exe.txt.exe", ""):
            with self.subTest(name=name):
                launched = []
                with mock.patch.object(os, "startfile", launched.append,
                                       create=True), \
                        mock.patch("subprocess.Popen", launched.append):
                    with self.assertRaises(common.NotOpened):
                        common.open_file(os.path.join("somewhere", name))
                self.assertEqual(launched, [])

    def test_each_system_has_its_own_way(self):
        self.assertEqual(self.run_open("a.pdf", "darwin")[0][0], "open")
        self.assertEqual(self.run_open("a.pdf", "linux")[0][0], "xdg-open")

    def test_the_reason_is_in_the_message(self):
        with self.assertRaises(common.NotOpened) as caught:
            common.open_file("evil.exe")
        self.assertIn(".exe", str(caught.exception))
        self.assertIn("Save as", str(caught.exception))


class ExportUtilTests(unittest.TestCase):
    def test_durations(self):
        cases = {None: "", 0: "0:00", 5: "0:05", 59.4: "0:59", 65: "1:05",
                 600: "10:00", 3599: "59:59", 3600: "1:00:00",
                 3725.5: "1:02:06", 36000: "10:00:00"}
        for seconds, expected in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(eu.describe_duration(seconds), expected)

    def test_names_that_keep_their_extension(self):
        self.assertEqual(eu.safe_name_with_extension("IMG_0001.JPG"),
                         "IMG_0001.JPG")
        self.assertEqual(eu.safe_name_with_extension('a<b>:c?.png'),
                         "a_b__c_.png")
        long = eu.safe_name_with_extension("x" * 400 + ".heic", limit=50)
        self.assertEqual(len(long), 50)
        self.assertTrue(long.endswith(".heic"))
        self.assertEqual(eu.safe_name_with_extension("", "item"), "item")
        self.assertEqual(eu.safe_name_with_extension("CON.txt"), "_CON.txt")
        self.assertEqual(eu.safe_name_with_extension("noext"), "noext")
        weird = eu.safe_name_with_extension("a.p<n>g")
        self.assertNotRegex(weird, r"[<>]")

    def test_numbered_names(self):
        self.assertEqual(eu.numbered_filename(3, "Shopping: list", "html"),
                         "003 - Shopping_ list.html")

    def test_links(self):
        self.assertEqual(eu.href("a b/c#d.png"), "a%20b/c%23d.png")
        self.assertEqual(eu.href("a\\b.png"), "a/b.png")

    def test_a_page_is_standalone_and_escaped(self):
        page = eu.html_page("<b>T</b>", "<p>body</p>", "p{color:red}")
        self.assertIn("<title>&lt;b&gt;T&lt;/b&gt;</title>", page)
        self.assertIn("<p>body</p>", page)
        self.assertIn("p{color:red}", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("http", page)           # nothing is loaded from out

    def test_files(self):
        folder = tempfile.mkdtemp(prefix="ibe-eu-")
        self.addCleanup(shutil.rmtree, folder, True)
        csv_path = os.path.join(folder, "a.csv")
        self.assertEqual(eu.write_csv_file(csv_path, ["a", "b"],
                                           [[1, "x,y"], [2, 'q"r']]),
                         [csv_path])
        with open(csv_path, "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw[:3], b"\xef\xbb\xbf")
        self.assertIn(b'"x,y"', raw)
        nested = os.path.join(folder, "deep", "er", "t.txt")
        eu.write_text_file(nested, "héllo\n")
        with open(nested, "rb") as handle:
            self.assertEqual(handle.read(), "héllo\n".encode("utf-8"))


@unittest.skipUnless(imaging.have_pillow(), "Pillow is not installed")
class ImagingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="ibe-img-")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def write(self, name, data):
        path = os.path.join(self.folder, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_what_can_be_shown(self):
        for name, expected in (("a.png", True), ("a.JPG", True),
                               ("a.gif", True), ("a.mov", False),
                               ("a.txt", False), ("a", False)):
            with self.subTest(name=name):
                self.assertEqual(imaging.can_show(name), expected)
        self.assertEqual(imaging.can_show("a.heic"), imaging.have_heif())

    def test_a_thumbnail_fits_the_box(self):
        path = self.write("big.png", make_png(300, 150))
        image = imaging.make_thumbnail(path, (64, 64))
        self.assertEqual(image.size, (64, 32))
        small = imaging.make_thumbnail(self.write("s.png", make_png(10, 10)),
                                       (64, 64))
        self.assertEqual(small.size, (10, 10))              # never enlarged

    def test_a_thumbnail_does_not_leave_the_file_open(self):
        path = self.write("a.png", make_png(20, 20))
        imaging.make_thumbnail(path, (8, 8))
        os.remove(path)                    # fails on Windows if still open

    def test_pictures_that_cannot_be_read_give_nothing(self):
        broken = self.write("b.png", b"\x89PNG not really")
        self.assertIsNone(imaging.make_thumbnail(broken, (8, 8)))
        self.assertIsNone(imaging.make_thumbnail(self.write("v.mov", b"x"),
                                                 (8, 8)))
        self.assertIsNone(imaging.image_size(broken))
        os.remove(broken)                   # and the file was closed again

    def test_size(self):
        self.assertEqual(imaging.image_size(
            self.write("a.png", make_png(30, 20))), (30, 20))

    def test_conversion_to_jpeg(self):
        source = self.write("a.png", make_png(30, 20, (10, 200, 30)))
        target = os.path.join(self.folder, "a.jpg")
        self.assertTrue(imaging.to_jpeg(source, target))
        from PIL import Image
        with Image.open(target) as image:
            self.assertEqual((image.format, image.size), ("JPEG", (30, 20)))
        self.assertFalse(imaging.to_jpeg(self.write("x.png", b"junk"),
                                         os.path.join(self.folder, "x.jpg")))
        self.assertFalse(imaging.to_jpeg(
            os.path.join(self.folder, "missing.png"),
            os.path.join(self.folder, "m.jpg")))

    def test_transparent_pictures_convert_too(self):
        from PIL import Image
        source = os.path.join(self.folder, "t.png")
        Image.new("RGBA", (8, 8), (255, 0, 0, 80)).save(source)
        self.assertTrue(imaging.to_jpeg(source,
                                        os.path.join(self.folder, "t.jpg")))

    def test_the_way_the_camera_was_held_is_respected(self):
        from PIL import Image
        source = os.path.join(self.folder, "r.jpg")
        image = Image.new("RGB", (40, 20), (200, 0, 0))
        exif = Image.Exif()
        exif[0x0112] = 6                     # rotated a quarter turn
        image.save(source, "JPEG", exif=exif)
        self.assertEqual(imaging.image_size(source), (20, 40))

    def test_without_pillow_nothing_is_converted_and_png_is_left_to_tk(self):
        path = self.write("a.png", make_png(5, 5))
        with mock.patch.object(imaging, "Image", None), \
                mock.patch.object(imaging, "have_pillow",
                                  return_value=False):
            self.assertIsNone(imaging.make_thumbnail(path, (8, 8)))
            self.assertFalse(imaging.to_jpeg(path, path + ".jpg"))
            self.assertIsNone(imaging.image_size(path))
            self.assertTrue(imaging.can_show("a.png"))
            self.assertFalse(imaging.can_show("a.jpg"))
            self.assertIsNone(imaging.photo_for_tk(
                self.write("a.jpg", b"x"), (8, 8)))


class FakeSession:
    def __init__(self):
        self.calls = []

    def export_files(self, items, directory):
        self.calls.append((list(items), directory))
        os.makedirs(directory, exist_ok=True)
        for _id, name in items:
            with open(os.path.join(directory, name), "wb") as handle:
                handle.write(b"data")
        future = concurrent.futures.Future()
        future.set_result([name for _id, name in items])
        return future


class ContextTests(unittest.TestCase):
    def setUp(self):
        rows = [("id1", "D", "a/one.jpg", 1, 4, 0, 0),
                ("id2", "D", "a/two.m4a", 1, 4, 0, 0),
                ("id3", "D", "a/noext", 1, 4, 0, 0)]
        self.session = FakeSession()
        self.ctx = AppContext(self.session, lambda *a: None,
                              lambda text: None, lambda ids: None)
        self.ctx.index = FileIndex(rows)
        self.addCleanup(self.ctx.reset)

    def test_every_fetch_gets_a_folder_of_its_own(self):
        first = self.ctx.fetch_local(["D/a/one.jpg"], "x").result()
        second = self.ctx.fetch_local(["D/a/one.jpg"], "x").result()
        one, two = first["D/a/one.jpg"], second["D/a/one.jpg"]
        self.assertNotEqual(os.path.dirname(one), os.path.dirname(two))
        self.assertTrue(os.path.isfile(one) and os.path.isfile(two))
        self.assertTrue(one.endswith(".jpg"))               # extension kept

    def test_what_is_not_in_the_backup_is_left_out(self):
        got = self.ctx.fetch_local(
            ["D/a/one.jpg", "D/nowhere.txt", "D/a/noext", "D/a/one.jpg"],
            "x").result()
        self.assertEqual(sorted(got), ["D/a/noext", "D/a/one.jpg"])
        self.assertEqual(len(self.session.calls[0][0]), 2)   # no duplicates
        self.assertEqual(self.ctx.fetch_local([], "x").result(), {})
        self.assertEqual(self.ctx.fetch_local(["D/nope"], "x").result(), {})

    def test_the_copier_says_whether_the_file_was_there(self):
        copy = self.ctx.copier()
        folder = tempfile.mkdtemp(prefix="ibe-ctx-")
        self.addCleanup(shutil.rmtree, folder, True)
        self.assertTrue(copy("D/a/two.m4a", folder, "x.m4a"))
        self.assertTrue(os.path.isfile(os.path.join(folder, "x.m4a")))
        self.assertFalse(copy("D/missing", folder, "y"))
        self.assertFalse(copy("D/a", folder, "z"))           # a folder

    def test_the_fetcher_returns_the_names_that_arrived(self):
        folder = tempfile.mkdtemp(prefix="ibe-ctx-")
        self.addCleanup(shutil.rmtree, folder, True)

        class Thing:
            def __init__(self, path):
                self.path = path

        fetch = self.ctx.fetcher(folder)
        names = fetch([(Thing("D/a/one.jpg"), "1.jpg"),
                       (Thing("D/gone"), "2.jpg"),
                       (Thing(""), "3.jpg")])
        self.assertEqual(names, ["1.jpg"])
        self.assertTrue(os.path.isfile(os.path.join(folder, "attachments",
                                                    "1.jpg")))
        self.assertEqual(fetch([]), [])
        loose = self.ctx.fetcher(folder, subfolder="")
        self.assertEqual(loose([(Thing("D/a/two.m4a"), "t.m4a")]), ["t.m4a"])
        self.assertTrue(os.path.isfile(os.path.join(folder, "t.m4a")))


if __name__ == "__main__":
    unittest.main()
