# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Photos and Voice Memos tabs in the real window (skipped without a
display)."""

import os
import types
import unittest
from unittest import mock

from ios_apps import common, imaging
from ios_apps import photos as ph
from ios_apps import photos_view as pv
from ios_apps import voice_memos_view as vv
from tests import fixture_media as fm
from tests.gui_apps import AppGuiCase

LIBRARY_ID = (fm.CAMERA, fm.LIBRARY)


def read(path, mode="r", encoding=None):
    with open(path, mode, encoding=encoding) as handle:
        return handle.read()


class PhotosGuiCase(AppGuiCase):
    WIDTH, HEIGHT = 600, 400                      # what the grid thinks it has

    def open_photos(self, encrypted=False, with_library=True, extra=()):
        self.open_files(fm.camera_files(with_library) + list(extra),
                        encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Photos")

    def show(self):
        tab = self.show_tab("Photos")
        self.wait_for(lambda: tab.items, "the pictures")
        # a window that is not shown has no size: give the grid one
        patcher = mock.patch.multiple(
            tab.canvas, winfo_width=lambda: self.WIDTH,
            winfo_height=lambda: self.HEIGHT)
        patcher.start()
        self.addCleanup(patcher.stop)
        tab._layout()
        return tab

    def albums(self):
        tree = self.tab.album_tree
        rows = []
        for row in tree.get_children():
            rows.append(tree.item(row, "text"))
            rows += ["  " + tree.item(c, "text")
                     for c in tree.get_children(row)]
        return rows

    def names(self):
        return [i.name for i in self.tab.shown]

    def choose_album(self, key):
        tab = self.tab
        row = next(r for r, k in tab._album_rows.items() if k == key)
        tab.album_tree.selection_set(row)
        self.root.update()

    def click(self, index, **kw):
        tab = self.tab
        col, row = index % tab._cols, index // tab._cols
        event = types.SimpleNamespace(x=col * pv.CELL + 10,
                                      y=row * pv.CELL + 10, x_root=0,
                                      y_root=0)
        tab._on_click(event, **kw)


class TabTests(PhotosGuiCase):
    def test_tabs_appear_only_for_what_the_backup_has(self):
        self.open_files([("HomeDomain", "Library/x.txt", b"x")])
        self.assertEqual(self.tab_titles(), ["Files"])
        self.open_files(fm.camera_files())
        self.assertEqual(self.tab_titles(), ["Files", "Photos"])
        self.open_files(fm.memo_files())
        self.assertEqual(self.tab_titles(), ["Files", "Voice Memos"])
        self.open_files(fm.backup_files())
        self.assertEqual(self.tab_titles(), ["Files", "Photos",
                                             "Voice Memos"])

    def test_it_loads_when_first_shown(self):
        self.open_photos()
        tab = self.tab
        self.assertFalse(tab._loaded)
        self.show()
        self.assertTrue(tab._loaded)
        self.assertEqual(len(tab.items), 6)

    def test_it_works_for_an_encrypted_backup(self):
        self.open_photos(encrypted=True)
        tab = self.show()
        self.assertEqual(len(tab.items), 6)
        self.wait_for(lambda: any(tab._thumbs.values()), "a thumbnail")


class AlbumTests(PhotosGuiCase):
    def test_smart_albums_with_counts_user_albums(self):
        self.open_photos()
        self.show()
        self.assertEqual(self.albums(), [
            "All items  (4)", "Photos  (3)", "Videos  (1)", "Favorites  (1)",
            "Hidden  (1)", "Recently Deleted  (1)", "My albums",
            "  Favourites of 2026  (2)", "  Holiday  (2)"])

    def test_choosing_an_album_shows_only_its_items(self):
        self.open_photos()
        tab = self.show()
        self.assertEqual(len(tab.shown), 4)
        self.choose_album(ph.VIDEOS)
        self.assertEqual(self.names(), ["IMG_0004.MOV"])
        self.choose_album(ph.DELETED)
        self.assertEqual(self.names(), ["IMG_0001.PNG"])
        self.choose_album(ph.HIDDEN)
        self.assertEqual(self.names(), ["IMG_0002.JPG"])
        self.choose_album(("album", "Holiday"))
        self.assertEqual(sorted(self.names()),
                         ["IMG_0001.PNG", "IMG_0003.HEIC"])
        self.assertEqual(tab.state_var.get(), "2 of 6 items")

    def test_without_the_library_every_file_is_listed_by_folder(self):
        self.open_photos(with_library=False)
        tab = self.show()
        self.assertEqual(self.albums(), [
            "All items  (6)", "Photos  (5)", "Videos  (1)",
            "Folders on the phone", "  100APPLE  (5)", "  101APPLE  (1)"])
        self.assertEqual(len(tab.shown), 6)
        self.assertEqual(tab.state_var.get(), "6 of 6 items")

    def test_a_damaged_library_still_lists_the_files(self):
        files = [f for f in fm.camera_files(with_library=False)] + [
            (fm.CAMERA, fm.LIBRARY, b"not a database", fm.FILE_DATE)]
        self.open_files(files)
        tab = self.show_tab("Photos")
        self.wait_for(lambda: tab.items, "the pictures")
        self.assertEqual(len(tab.items), 6)
        self.assertIn("could not be read", tab.state_var.get())


class GridTests(PhotosGuiCase):
    def setUp(self):
        super().setUp()
        self.open_photos()
        self.panel = self.show()

    def test_the_columns_follow_the_width(self):
        panel = self.panel
        self.assertEqual(panel._cols, 600 // pv.CELL)
        self.WIDTH = 2 * pv.CELL + 5
        panel._layout()
        self.assertEqual(panel._cols, 2)
        region = [int(float(v)) for v in panel.canvas.cget("scrollregion")
                  .split()]
        self.assertEqual(region[3], 2 * pv.CELL)       # 4 items, 2 columns

    def test_only_the_visible_rows_are_drawn(self):
        panel = self.panel
        items = [ph.MediaItem(f"D/{n}.jpg", f"{n}.jpg", "DCIM/1", taken=n)
                 for n in range(400)]
        panel.items = items
        panel.refresh()
        self.assertLess(len(panel._visible), 60)
        first = panel._visible[0]
        panel.canvas.yview_moveto(0.5)
        panel._draw()
        self.assertNotIn(first, panel._visible)
        self.assertTrue(panel._visible)

    def wait_thumbnails(self, panel):
        """Until every picture on screen that can be previewed has had its
        turn (a thumbnail, or a note that it could not be made)."""
        def wanted():
            return [i for i in panel._visible if i.kind == ph.PHOTO
                    and imaging.can_show(i.name)]

        self.wait_for(lambda: panel._inflight == 0 and not panel._queue
                      and all(i.path in panel._thumbs for i in wanted()),
                      "the thumbnails")

    def test_thumbnails_are_made_for_the_pictures_shown(self):
        panel = self.panel
        self.wait_thumbnails(panel)
        by_name = {i.name: panel._thumbs.get(i.path) for i in panel.shown}
        self.assertTrue(by_name["IMG_0001.PNG"])
        self.assertIsNone(by_name["IMG_0004.MOV"])       # a video: no preview
        if imaging.have_pillow():
            self.assertTrue(by_name["IMG_E0002.JPG"])
        if imaging.have_heif():
            self.assertTrue(by_name["IMG_0003.HEIC"])
        self.assertEqual(panel._inflight, 0)

    def test_the_working_copies_of_thumbnails_are_removed(self):
        panel = self.panel
        self.wait_thumbnails(panel)
        base = os.path.join(self.explorer.apps.workspace.path, "photo-thumbs")
        left = [f for _r, _d, files in os.walk(base) for f in files]
        self.assertEqual(left, [])

    def test_without_pillow_png_files_still_get_thumbnails(self):
        with mock.patch.object(imaging, "have_pillow", return_value=False), \
                mock.patch.object(imaging, "Image", None):
            panel = self.panel
            panel._thumbs.clear()
            panel._draw()
            self.wait_for(lambda: panel._thumbs.get(
                next(i.path for i in panel.shown
                     if i.name == "IMG_0001.PNG")), "the PNG thumbnail")
            self.assertNotIn(next(i.path for i in panel.items
                                  if i.name == "IMG_0002.JPG"),
                             [p for p, t in panel._thumbs.items() if t])

    def test_pictures_scrolled_away_are_not_fetched(self):
        panel = self.panel
        self.wait_thumbnails(panel)
        fetched = []
        panel.ctx.fetch_local = lambda paths, name: fetched.append(paths)
        gone = ph.MediaItem("D/gone.jpg", "gone.jpg", "DCIM/1")
        panel._queue.append(gone)                  # not among the visible
        panel._pending.add(gone.path)
        panel._pump()
        self.assertEqual(fetched, [])
        self.assertNotIn(gone.path, panel._pending)

    def test_the_thumbnails_kept_are_limited(self):
        panel = self.panel
        with mock.patch.object(pv, "CACHE", 3):
            for n in range(10):
                panel._thumb_ready(f"D/{n}.jpg", None, None)
        self.assertLessEqual(len(panel._thumbs), 3)
        self.assertIn("D/9.jpg", panel._thumbs)            # the newest stay

    def test_the_hint_appears_when_pillow_is_missing(self):
        panel = self.panel
        self.assertEqual(panel.hint_var.get() == "",
                         imaging.have_pillow() and imaging.have_heif())
        with mock.patch.object(imaging, "have_pillow", return_value=False):
            panel._set_hint()
        self.assertIn("Install Pillow", panel.hint_var.get())

    def test_a_broken_picture_does_not_stop_the_others(self):
        broken = [(fm.CAMERA, f"{fm.DCIM}/100APPLE/IMG_0001.PNG",
                   b"\x89PNG broken", fm.FILE_DATE)]
        files = [f for f in fm.camera_files(with_library=False)
                 if not f[1].endswith("100APPLE/IMG_0001.PNG")] + broken
        self.open_files(files)
        panel = self.show()
        self.wait_thumbnails(panel)
        broken_item = next(i for i in panel.shown if i.name == "IMG_0001.PNG"
                           and i.directory.endswith("100APPLE"))
        # noted as not possible, rather than tried again and again
        self.assertIs(panel._thumbs[broken_item.path], False)
        if imaging.have_pillow():
            good = [i for i in panel.shown if panel._thumbs.get(i.path)]
            self.assertTrue(good)


class SelectionTests(PhotosGuiCase):
    def setUp(self):
        super().setUp()
        self.open_photos()
        self.panel = self.show()

    def selected_names(self):
        return [i.name for i in self.panel.selected_items()]

    def test_click_ctrl_click_shift_click_and_empty_space(self):
        panel = self.panel
        self.click(1)
        self.assertEqual(len(panel.selected), 1)
        self.click(3, toggle=True)
        self.assertEqual(len(panel.selected), 2)
        self.click(3, toggle=True)
        self.assertEqual(len(panel.selected), 1)
        self.click(0)
        self.click(2, extend=True)
        self.assertEqual(len(panel.selected), 3)
        event = types.SimpleNamespace(x=5, y=4 * pv.CELL + 50, x_root=0,
                                      y_root=0)
        panel._on_click(event)
        self.assertEqual(panel.selected, [])

    def test_select_all_and_the_description(self):
        panel = self.panel
        panel.select_all()
        self.assertEqual(len(panel.selected), 4)
        self.assertRegex(panel.info_var.get(), r"^4 selected, ")
        item = next(i for i in panel.shown if i.name == "IMG_0001.PNG")
        panel.set_selection([item.path])
        text = panel.info_var.get()
        for expected in ("IMG_0001.PNG", "taken ", "favorite",
                         "DCIM/100APPLE"):
            self.assertIn(expected, text)
        orphan = next(i for i in panel.shown if i.name == "IMG_E0002.JPG")
        panel.set_selection([orphan.path])
        self.assertIn("file date ", panel.info_var.get())      # not "taken"

    def test_the_description_of_one_item(self):
        panel = self.panel
        item = next(i for i in panel.shown if i.name == "IMG_0003.HEIC")
        panel.set_selection([item.path])
        text = panel.info_var.get()
        for expected in ("Photo (HEIC)", "4032 \u00d7 3024", "in Holiday",
                         "-34.92850, 138.60070"):
            self.assertIn(expected, text)
        video = next(i for i in panel.shown if i.name == "IMG_0004.MOV")
        panel.set_selection([video.path])
        self.assertIn("0:12", panel.info_var.get())
        self.assertIn("in Favourites of 2026", panel.info_var.get())

    def test_the_arrow_keys(self):
        panel = self.panel
        self.assertEqual(panel._move(1), "break")
        self.assertEqual(panel.selected, [panel.shown[0].path])
        panel._move(1)
        self.assertEqual(panel.selected, [panel.shown[1].path])
        panel._move(panel._cols)
        self.assertEqual(panel.selected, [panel.shown[min(
            1 + panel._cols, 3)].path])
        panel._move(-100)
        self.assertEqual(panel.selected, [panel.shown[0].path])
        panel._move(100)
        self.assertEqual(panel.selected, [panel.shown[3].path])

    def test_a_search_drops_what_is_no_longer_shown_from_the_selection(self):
        panel = self.panel
        panel.select_all()
        panel.search_var.set("heic")
        panel.refresh()
        self.assertEqual(self.selected_names(), ["IMG_0003.HEIC"])

    def test_double_click_opens_the_picture(self):
        panel = self.panel
        opened = []
        panel.open_backup_file = opened.append
        index = 2
        col, row = index % panel._cols, index // panel._cols
        panel._on_double(types.SimpleNamespace(
            x=col * pv.CELL + 5, y=row * pv.CELL + 5))
        self.assertEqual(opened, [panel.shown[2].path])

    def test_open_and_save_want_exactly_one_picture(self):
        panel = self.panel
        panel.open_selected()
        panel.save_selected()
        self.assertEqual([d[0] for d in self.dialogs], ["showinfo"] * 2)
        panel.select_all()
        panel.open_selected()
        self.assertEqual(len(self.dialogs), 3)

    def test_opening_a_picture_makes_a_working_copy_and_launches_it(self):
        panel = self.panel
        opened = []
        self.click(0)
        with mock.patch.object(common, "open_file", opened.append):
            panel.open_selected()
            self.wait_for(lambda: opened, "the viewer")
        self.assertTrue(os.path.isfile(opened[0]))
        self.assertEqual(os.path.splitext(opened[0])[1].lower(),
                         os.path.splitext(panel.selected_items()[0].name)[1]
                         .lower())

    def test_saving_a_picture(self):
        panel = self.panel
        self.click(0)
        item = panel.selected_items()[0]
        target = os.path.join(self.tmp, "saved" + item.extension)
        with mock.patch("tkinter.filedialog.asksaveasfilename",
                        return_value=target):
            panel.save_selected()
            self.wait_for(lambda: os.path.exists(target)
                          and os.path.getsize(target), "the saved picture")
        self.assertEqual(os.path.getsize(target), item.size)

    @unittest.skipUnless(imaging.have_pillow(), "Pillow is not installed")
    def test_saving_a_picture_as_jpeg(self):
        panel = self.panel
        item = next(i for i in panel.shown if i.name == "IMG_0001.PNG")
        panel.set_selection([item.path])
        target = os.path.join(self.tmp, "converted.jpg")
        with mock.patch("tkinter.filedialog.asksaveasfilename",
                        return_value=target):
            panel.save_selected_as_jpeg()
            self.wait_for(lambda: os.path.exists(target)
                          and "Saved" in self.explorer.status_var.get(),
                          "the converted picture")
        from PIL import Image
        with Image.open(target) as image:
            self.assertEqual(image.format, "JPEG")

    def test_a_failed_conversion_is_reported(self):
        panel = self.panel
        self.click(0)
        target = os.path.join(self.tmp, "x.jpg")
        before = len(self.dialogs)
        with mock.patch("tkinter.filedialog.asksaveasfilename",
                        return_value=target), \
                mock.patch.object(imaging, "to_jpeg", return_value=False):
            panel.save_selected_as_jpeg()
            self.wait_for(lambda: len(self.dialogs) > before, "the report")
        self.assertEqual(self.dialogs[-1][0], "showerror")
        self.assertIn("pillow-heif", self.dialogs[-1][1][1])


class SearchAndSortTests(PhotosGuiCase):
    def setUp(self):
        super().setUp()
        self.open_photos()
        self.panel = self.show()

    def test_sorting(self):
        panel = self.panel
        panel.sort_var.set("Name")
        panel.refresh()
        self.assertEqual(self.names(), sorted(self.names()))
        panel.sort_var.set("Date taken, oldest first")
        panel.refresh()
        stamps = [i.taken for i in panel.shown]
        self.assertEqual(stamps, sorted(stamps))
        panel.sort_var.set("Date taken, newest first")
        panel.refresh()
        stamps = [i.taken for i in panel.shown]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_every_sort_works(self):
        for how in ph.SORTS:
            with self.subTest(how=how):
                self.panel.sort_var.set(how)
                self.panel.refresh()
                self.assertEqual(len(self.panel.shown), 4)

    def test_search(self):
        panel = self.panel
        panel.search_var.set("holiday")
        panel.refresh()
        self.assertEqual(sorted(self.names()),
                         ["IMG_0001.PNG", "IMG_0003.HEIC"])
        panel.search_var.set("nothing like it")
        panel.refresh()
        self.assertEqual(panel.shown, [])
        panel.canvas.delete("all")
        panel._draw()
        self.assertTrue(panel.canvas.find_all())            # a message
        panel.search_var.set("")
        panel.refresh()
        self.assertEqual(len(panel.shown), 4)

    def test_typing_waits_a_moment(self):
        panel = self.panel
        panel.search_var.set("heic")
        self.assertIn("search", panel._timers)
        self.wait_for(lambda: self.names() == ["IMG_0003.HEIC"],
                      "the filtered grid")


class ExportTests(PhotosGuiCase):
    def setUp(self):
        super().setUp()
        self.open_photos()
        self.panel = self.show()
        self.out = os.path.join(self.tmp, "export")

    def run_export(self, scope, fmt):
        before = len(self.dialogs)
        with mock.patch.object(pv, "ask_export",
                               return_value=(fmt, scope, self.out)) as ask:
            self.panel.export()
        self.wait_for(lambda: len(self.dialogs) > before, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        return ask

    def test_originals_of_everything_with_unique_names(self):
        self.run_export("all", "copy")
        self.assertEqual(sorted(os.listdir(self.out)), sorted([
            "DCIM_101APPLE_IMG_0001.PNG", "IMG_0001.PNG", "IMG_0002.JPG",
            "IMG_0003.HEIC", "IMG_0004.MOV", "IMG_E0002.JPG"]))
        self.assertEqual(read(os.path.join(self.out, "IMG_0004.MOV"), "rb"),
                         fm.VIDEO_BYTES)

    def test_the_scopes(self):
        panel = self.panel
        ask = self.run_export("view", "csv")
        self.assertEqual(list(ask.call_args.args[3]), ["view", "all"])
        self.assertEqual(len(read(os.path.join(self.out, "photos.csv"),
                                  encoding="utf-8-sig").splitlines()), 5)
        self.click(0)
        self.click(1, toggle=True)
        ask = self.run_export("selected", "csv")
        self.assertEqual(list(ask.call_args.args[3]),
                         ["selected", "view", "all"])
        self.assertEqual(len(read(os.path.join(self.out, "photos.csv"),
                                  encoding="utf-8-sig").splitlines()), 3)
        self.run_export("all", "csv")
        self.assertEqual(len(read(os.path.join(self.out, "photos.csv"),
                                  encoding="utf-8-sig").splitlines()), 7)
        self.assertTrue(panel)

    @unittest.skipUnless(imaging.have_pillow(), "Pillow is not installed")
    def test_jpeg_and_the_gallery(self):
        self.run_export("all", "jpeg")
        self.assertIn("IMG_0001.jpg", os.listdir(self.out))
        self.out = os.path.join(self.tmp, "gallery")
        self.run_export("all", "html")
        self.assertTrue(os.path.isfile(os.path.join(self.out, "index.html")))
        self.assertTrue(os.listdir(os.path.join(self.out, "thumbs")))

    def test_notes_about_problems_reach_the_final_message(self):
        with mock.patch.object(imaging, "to_jpeg", return_value=False):
            self.run_export("all", "jpeg")
        text = self.dialogs[-1][1][1]
        if imaging.have_pillow():
            self.assertIn("could not be converted", text)

    def test_the_progress_is_shown(self):
        seen = []
        self.explorer.apps.set_status = seen.append
        self.run_export("all", "copy")
        self.assertIn("Exporting 6 of 6...", seen)

    def test_cancelling_exports_nothing(self):
        with mock.patch.object(pv, "ask_export", return_value=None):
            self.panel.export()
        self.root.update()
        self.assertFalse(os.path.exists(self.out))

    def test_originals_through_the_normal_extraction(self):
        extracted = []
        self.explorer.apps.extract = extracted.append
        self.click(0)
        self.panel.extract_originals()
        (ids,) = extracted
        first = self.panel.selected_items()[0]
        node = self.explorer.apps.index.get(first.path)
        self.assertIn(node.file_id, ids)
        self.assertIn(self.ids[LIBRARY_ID], ids)
        self.assertEqual(len(ids), 2)             # the picture and the library

    def test_originals_of_everything_shown_when_nothing_is_selected(self):
        extracted = []
        self.explorer.apps.extract = extracted.append
        self.panel.extract_originals()
        (ids,) = extracted
        self.assertEqual(len(ids), 4 + 1)


class VoiceMemoGuiCase(AppGuiCase):
    def open_memos(self, encrypted=False, with_database=True):
        self.open_files(fm.memo_files(with_database), encrypted=encrypted)

    @property
    def tab(self):
        return self.panel_titled("Voice Memos")

    def show(self):
        tab = self.show_tab("Voice Memos")
        self.wait_for(lambda: tab.memos, "the recordings")
        return tab

    def titles(self):
        tree = self.tab.tree
        return [tree.item(i, "text") for i in tree.get_children()]


class VoiceMemoTests(VoiceMemoGuiCase):
    def test_the_list_newest_first_with_titles_dates_lengths_and_sizes(self):
        self.open_memos()
        tab = self.show()
        self.assertEqual(tab.state_var.get(), "4 recordings")
        self.assertEqual(self.titles(), [
            "Song idea", "20260901 130000-DDD", "20260901 110000-BBB",
            "Interview with Sam"])
        tree = tab.tree
        row = next(r for r, m in tab._rows.items()
                   if m.title == "Interview with Sam")
        self.assertEqual(tree.set(row, "length"), "2:05")
        self.assertRegex(tree.set(row, "when"), r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertRegex(tree.set(row, "size"), r"B$")

    def test_it_works_without_the_database(self):
        self.open_memos(with_database=False)
        tab = self.show()
        self.assertEqual(len(self.titles()), 4)
        self.assertEqual(self.titles()[0], "20260901 130000-DDD")
        self.assertEqual(tab.state_var.get(), "4 recordings")

    def test_an_encrypted_backup(self):
        self.open_memos(encrypted=True)
        tab = self.show()
        self.assertEqual(len(tab.memos), 4)
        self.assertIn("Interview with Sam", self.titles())

    def test_a_damaged_database_still_lists_the_files(self):
        files = fm.memo_files(with_database=False) + [
            ("AppDomainGroup-group.com.apple.VoiceMemos.shared",
             "Recordings/CloudRecordings.db", b"not a database",
             fm.FILE_DATE)]
        self.open_files(files)
        tab = self.show_tab("Voice Memos")
        self.wait_for(lambda: tab.memos, "the recordings")
        self.assertEqual(len(tab.memos), 4)
        self.assertIn("could not be read", tab.state_var.get())

    def test_sorting_by_clicking_the_headings(self):
        self.open_memos()
        tab = self.show()
        tab.sort_by("title")
        titles = self.titles()
        self.assertEqual(titles, sorted(titles, key=str.casefold))
        self.assertIn("\u25B2", tab.tree.heading("#0", "text"))
        tab.sort_by("title")
        self.assertEqual(self.titles(), titles[::-1])
        tab.sort_by("length")
        self.assertEqual(self.titles()[0], "Interview with Sam")
        tab.sort_by("size")
        sizes = [m.size for m in (tab._rows[r] for r in
                                  tab.tree.get_children())]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        tab.sort_by("when")
        whens = [m.when for m in (tab._rows[r] for r in
                                  tab.tree.get_children())]
        self.assertEqual(whens, sorted(whens, reverse=True))

    def test_search(self):
        self.open_memos()
        tab = self.show()
        tab.search_var.set("sam")
        tab.refresh()
        self.assertEqual(self.titles(), ["Interview with Sam"])
        self.assertEqual(tab.state_var.get(), "1 of 4 recordings")
        tab.search_var.set("")
        tab.refresh()
        self.assertEqual(len(self.titles()), 4)

    def test_selecting_and_describing(self):
        self.open_memos()
        tab = self.show()
        tab.tree.selection_set(tab.tree.get_children()[1])
        self.root.update()
        self.assertIn("20260901 130000-DDD.m4a", tab.info_var.get())
        tab.tree.selection_set(tab.tree.get_children()[:2])
        self.root.update()
        self.assertEqual(tab.info_var.get(), "2 selected")

    def test_playing_a_recording(self):
        self.open_memos()
        tab = self.show()
        opened = []
        tab.tree.selection_set(tab.tree.get_children()[1])        # DDD
        with mock.patch.object(common, "open_file", opened.append):
            tab.play_selected()
            self.wait_for(lambda: opened, "the player")
        self.assertEqual(read(opened[0], "rb"), fm.AUDIO * 3)
        self.assertTrue(opened[0].endswith(".m4a"))

    def test_play_and_save_want_exactly_one_recording(self):
        self.open_memos()
        tab = self.show()
        tab.play_selected()
        tab.save_selected()
        self.assertEqual([d[0] for d in self.dialogs], ["showinfo"] * 2)

    def test_saving_suggests_a_good_name(self):
        self.open_memos()
        tab = self.show()
        row = next(r for r, m in tab._rows.items()
                   if m.title == "Interview with Sam")
        tab.tree.selection_set(row)
        target = os.path.join(self.tmp, "memo.m4a")
        with mock.patch("tkinter.filedialog.asksaveasfilename",
                        return_value=target) as ask:
            tab.save_selected()
            self.wait_for(lambda: os.path.exists(target)
                          and os.path.getsize(target), "the saved file")
        self.assertRegex(ask.call_args.kwargs["initialfile"],
                         r"Interview with Sam\.m4a$")
        self.assertEqual(read(target, "rb"), fm.AUDIO)


class VoiceMemoExportTests(VoiceMemoGuiCase):
    def setUp(self):
        super().setUp()
        self.open_memos()
        self.tab_ = self.show()
        self.out = os.path.join(self.tmp, "memos")

    def run_export(self, scope, fmt):
        before = len(self.dialogs)
        with mock.patch.object(vv, "ask_export",
                               return_value=(fmt, scope, self.out)) as ask:
            self.tab_.export()
        self.wait_for(lambda: len(self.dialogs) > before, "the export")
        self.assertEqual(self.dialogs[-1][0], "showinfo", self.dialogs[-1])
        return ask

    def test_audio_files(self):
        self.run_export("all", "audio")
        names = sorted(os.listdir(self.out))
        self.assertEqual(len(names), 4)
        self.assertTrue(any("Interview with Sam" in n for n in names))

    def test_the_web_page_and_the_list(self):
        self.run_export("all", "html")
        self.assertEqual(len(os.listdir(os.path.join(self.out,
                                                     "recordings"))), 4)
        self.out = os.path.join(self.tmp, "memos-csv")
        self.run_export("all", "csv")
        self.assertEqual(os.listdir(self.out), ["voice-memos.csv"])

    def test_the_scopes(self):
        tab = self.tab_
        ask = self.run_export("all", "csv")
        self.assertEqual(list(ask.call_args.args[3]), ["all"])
        tab.search_var.set("song")
        tab.refresh()
        ask = self.run_export("view", "csv")
        self.assertEqual(list(ask.call_args.args[3]), ["view", "all"])
        tab.tree.selection_set(tab.tree.get_children()[0])
        ask = self.run_export("selected", "audio")
        self.assertEqual(list(ask.call_args.args[3]),
                         ["selected", "view", "all"])
        self.assertEqual(len(os.listdir(self.out)), 2)    # csv + 1 recording

    def test_original_files_with_the_database(self):
        extracted = []
        self.explorer.apps.extract = extracted.append
        self.tab_.extract_originals()
        (ids,) = extracted
        self.assertEqual(len(ids), 4 + 1)
        db = ("AppDomainGroup-group.com.apple.VoiceMemos.shared",
              "Recordings/CloudRecordings.db")
        self.assertIn(self.ids[db], ids)

    def test_cancelling(self):
        with mock.patch.object(vv, "ask_export", return_value=None):
            self.tab_.export()
        self.root.update()
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
