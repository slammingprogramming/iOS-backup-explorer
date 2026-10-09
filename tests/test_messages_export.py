# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Exporting Messages as text, CSV, JSON and HTML (no GUI)."""

import csv
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
import urllib.parse

import file_index as fi
import ios_backup_explorer as app
from ios_apps import common
from ios_apps import messages as ms
from ios_apps import messages_export as mx
from tests import fixture_apps as fa
from tests import fixture_backup as fb


def scenario_items(with_contacts=True):
    conn = sqlite3.connect(":memory:")
    fa.build_sms_db(conn)
    book = None
    if with_contacts:
        ab = sqlite3.connect(":memory:")
        fa.build_addressbook(ab)
        book = common.ContactBook.from_connection(ab)
        ab.close()
    reader = ms.MessagesReader(conn, book)
    items = [(c, reader.messages(c)) for c in reader.conversations()]
    conn.close()
    return items


def message(**fields):
    defaults = dict(rowid=1, guid="g", chat_id=1, when=1_756_307_200,
                    from_me=False, sender="Alice", text="hi",
                    service="iMessage")
    defaults.update(fields)
    return ms.Message(**defaults)


def conversation(title="Chat", group=False, **fields):
    return ms.Conversation(title=title, is_group=group, chat_ids=[1],
                           services={"iMessage"}, participants=["Alice"],
                           **fields)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-mx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def read(self, path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()


class NamingTests(unittest.TestCase):
    def test_safe_filename(self):
        self.assertEqual(mx.safe_filename('a<b>c:d"e/f\\g|h?i*j'),
                         "a_b_c_d_e_f_g_h_i_j")
        self.assertEqual(mx.safe_filename("  dots...  "), "dots")
        self.assertEqual(mx.safe_filename(""), "untitled")
        self.assertEqual(mx.safe_filename(None, "x"), "x")
        self.assertEqual(mx.safe_filename("CON"), "_CON")
        self.assertEqual(mx.safe_filename("nul.txt"), "_nul.txt")
        self.assertEqual(len(mx.safe_filename("a" * 500)), 80)
        self.assertEqual(mx.safe_filename("..."), "untitled")

    def test_conversation_filenames_are_numbered(self):
        self.assertEqual(
            mx.conversation_filename(3, conversation("A/B"), "txt"),
            "003 - A_B.txt")

    def test_sizes_and_times(self):
        self.assertEqual(mx.describe_size(0), "")
        self.assertEqual(mx.describe_size(None), "")
        self.assertEqual(mx.describe_size(900), "900 B")
        self.assertEqual(mx.describe_size(2048), "2.0 KB")
        self.assertEqual(mx.iso_utc(1_756_307_200), "2025-08-27T15:06:40+00:00")
        self.assertEqual(mx.iso_utc(None), "")
        self.assertEqual(mx.iso_utc(10 ** 20), "")


class TextExportTests(TempCase):
    def test_one_file_per_conversation_with_every_part(self):
        items = scenario_items()
        paths = mx.write_txt(self.tmp, items)
        self.assertEqual(len(paths), len(items))
        names = [os.path.basename(p) for p in paths]
        self.assertEqual(len(set(names)), len(names))
        alice = next(p for p in paths if "Alice Example" in p)
        text = self.read(alice)
        self.assertTrue(text.startswith("Alice Example\n=============\n"))
        self.assertIn("With: Alice Example", text)
        self.assertRegex(text, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] "
                               r"Alice Example: Hey, are you free tonight\?")
        self.assertIn("] Me: Yes! What time?", text)
        self.assertIn("Around 7 — see you there \U0001F389", text)
        self.assertIn("    (Liked by Me)", text)
        self.assertIn(f"    [attachment: photo.png (image/png, "
                      f"{len(fa.PNG_BYTES)} B)]", text)
        self.assertIn("    [attachment: notes.txt (text/plain, 18 B)]", text)

    def test_events_and_multiline_messages(self):
        conv = conversation()
        messages = [
            message(text="line one\nline two\n\nline four"),
            message(kind="event", text="Alice left the conversation")]
        (path,) = mx.write_txt(self.tmp, [(conv, messages)])
        text = self.read(path)
        self.assertIn("Alice: line one\n    line two\n    \n    line four",
                      text)
        self.assertRegex(text, r"\*\*\* Alice left the conversation \*\*\*")

    def test_hostile_titles_cannot_escape_the_folder(self):
        conv = conversation("../../evil")
        (path,) = mx.write_txt(self.tmp, [(conv, [message()])])
        self.assertEqual(os.path.dirname(path), self.tmp)
        self.assertEqual(os.listdir(self.tmp), [os.path.basename(path)])


class CsvExportTests(TempCase):
    def rows(self, items):
        (path,) = mx.write_csv(os.path.join(self.tmp, "m.csv"), items)
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle)), path

    def test_every_message_is_a_row(self):
        items = scenario_items()
        rows, path = self.rows(items)
        self.assertEqual(len(rows), sum(len(m) for _c, m in items))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(3), b"\xef\xbb\xbf")   # Excel
        self.assertEqual(tuple(rows[0]), mx.CSV_COLUMNS)

    def test_columns(self):
        rows, _ = self.rows(scenario_items())
        sent = next(r for r in rows if r["text"] == "Yes! What time?")
        self.assertEqual((sent["sender"], sent["direction"],
                          sent["service"], sent["type"]),
                         ("Me", "sent", "iMessage", "message"))
        self.assertEqual(sent["conversation"], "Alice Example")
        self.assertRegex(sent["date_utc"], r"^\d{4}-\d{2}-\d{2}T.*\+00:00$")
        photo = next(r for r in rows if r["attachments"])
        self.assertEqual(photo["attachments"], "photo.png; notes.txt")
        liked = next(r for r in rows if "Around 7" in r["text"])
        self.assertEqual(liked["reactions"], "Liked (Me)")
        self.assertTrue(any(r["type"] == "event" for r in rows))

    def test_awkward_text_survives_the_round_trip(self):
        text = 'she said, "no"\nthen left;\t\U0001F600 日本'
        rows, _ = self.rows([(conversation(), [message(text=text)])])
        self.assertEqual(rows[0]["text"], text)


class JsonExportTests(TempCase):
    def load(self, items, files=None):
        (path,) = mx.write_json(os.path.join(self.tmp, "m.json"), items,
                                files)
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        return json.loads(raw), raw

    def test_structure(self):
        data, raw = self.load(scenario_items())
        titles = {c["title"] for c in data}
        self.assertIn("Weekend Plans", titles)
        group = next(c for c in data if c["title"] == "Weekend Plans")
        self.assertTrue(group["is_group"])
        self.assertEqual(group["participants"],
                         ["Alice Example", "Bob Sample", "+15550109999"])
        first = group["messages"][0]
        self.assertEqual(set(first), {
            "id", "guid", "date", "date_read", "sender", "handle", "from_me",
            "service", "type", "text", "attachments", "reactions"})
        self.assertIn("\U0001F389", raw)            # not 🎉 escapes

    def test_attachments_and_reactions(self):
        data, _ = self.load(scenario_items(), {1: "attachments/000001_photo.png"})
        alice = next(c for c in data if c["title"] == "Alice Example")
        by_guid = {m["guid"]: m for m in alice["messages"]}
        photo, notes = by_guid["G-M5"]["attachments"]
        self.assertEqual((photo["name"], photo["file"]),
                         ("photo.png", "attachments/000001_photo.png"))
        self.assertIsNone(notes["file"])
        self.assertEqual(by_guid["G-M3"]["reactions"],
                         [{"kind": "Liked", "sender": "Me"}])
        self.assertTrue(by_guid["G-M2"]["from_me"])


class HtmlExportTests(TempCase):
    def pages(self, items, files=None):
        paths = mx.write_html(self.tmp, items, files)
        return paths, {os.path.basename(p): self.read(p) for p in paths}

    def test_an_index_and_a_page_per_conversation(self):
        items = scenario_items()
        paths, pages = self.pages(items)
        self.assertEqual(os.path.basename(paths[0]), "index.html")
        self.assertEqual(len(paths), len(items) + 1)
        index = pages["index.html"]
        for number, (conv, _m) in enumerate(items, 1):
            name = mx.conversation_filename(number, conv, "html")
            self.assertIn(urllib.parse.quote(name, safe="/"), index)
            self.assertIn(conv.title, index)
            self.assertIn("<h1>" + conv.title.replace("&", "&amp;"),
                          pages[name])

    def test_bubbles_directions_and_services(self):
        conv = conversation()
        messages = [message(text="in"),
                    message(text="out", from_me=True),
                    message(text="sms out", from_me=True, service="SMS")]
        _paths, pages = self.pages([(conv, messages)])
        page = pages["001 - Chat.html"]
        self.assertIn('class="row received"', page)
        self.assertIn('class="row sent"', page)
        self.assertIn('class="row sent sms"', page)

    def test_group_pages_name_the_sender_but_direct_ones_do_not(self):
        direct = conversation("Direct")
        group = conversation("Group", group=True)
        msgs = [message(sender="Bob Sample", text="yo")]
        _p, pages = self.pages([(direct, msgs), (group, msgs)])
        self.assertNotIn('class="who"', pages["001 - Direct.html"])
        self.assertIn('<div class="who">Bob Sample</div>',
                      pages["002 - Group.html"])

    def test_day_headings_events_and_reactions(self):
        items = scenario_items()
        _p, pages = self.pages(items)
        group = next(v for k, v in pages.items() if "Weekend" in k)
        self.assertIn('class="day">', group)
        self.assertIn("named the conversation “Weekend Plans”", group)
        alice = next(v for k, v in pages.items() if "Alice" in k)
        self.assertIn("Liked by Me", alice)

    def test_everything_typed_by_other_people_is_escaped(self):
        evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
        att = ms.Attachment(7, 'x"><script>bad()</script>.png', "image/png",
                            None, 10, "MediaDomain/a")
        conv = conversation("<b>title</b> & co")
        msg = message(text=evil, sender=evil, attachments=[att],
                      reactions=[ms.Reaction("<i>Loved</i>", evil, False)])
        group = conversation("<G>", group=True)
        _p, pages = self.pages(
            [(conv, [msg]), (group, [msg])],
            {7: 'attachments/7_x"><script>bad()</script>.png'})
        for name, page in pages.items():
            self.assertNotIn("<script", page, name)
            self.assertNotIn("<img src=x", page, name)
            self.assertNotIn("<b>title</b>", page, name)
            self.assertNotIn("<i>Loved</i>", page, name)
        first = next(v for k, v in pages.items() if k.startswith("001"))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", first)
        self.assertIn("&lt;b&gt;title&lt;/b&gt; &amp; co", first)

    def test_attachments_are_images_links_or_marked_missing(self):
        items = scenario_items()
        files = {1: "attachments/000001_photo.png",
                 2: "attachments/000002_notes.txt"}
        _p, pages = self.pages(items, files)
        alice = next(v for k, v in pages.items() if "Alice" in k)
        self.assertIn('<img loading="lazy" src="attachments/000001_photo.png"',
                      alice)
        self.assertIn('<a href="attachments/000002_notes.txt">notes.txt</a>',
                      alice)
        _p, pages = self.pages(items, {})                # nothing exported
        alice = next(v for k, v in pages.items() if "Alice" in k)
        self.assertIn("photo.png", alice)
        self.assertIn("not exported", alice)
        self.assertNotIn("<img", alice)

    def test_links_are_percent_encoded(self):
        att = ms.Attachment(9, "my photo #1?.png", "image/png", None, 5, "p")
        _p, pages = self.pages(
            [(conversation("A B#C"), [message(attachments=[att])])],
            {9: "attachments/000009_my photo #1?.png"})
        page = pages["001 - A B#C.html"]
        self.assertIn("attachments/000009_my%20photo%20%231%3F.png", page)
        self.assertIn("001%20-%20A%20B%23C.html", pages["index.html"])

    def test_multiline_text_keeps_its_line_breaks(self):
        _p, pages = self.pages([(conversation(),
                                 [message(text="a\nb")])])
        self.assertIn("a<br>b", pages["001 - Chat.html"])

    def test_no_external_resources(self):
        _p, pages = self.pages(scenario_items())
        for page in pages.values():
            self.assertNotRegex(page, r"(src|href)=\"https?://")
            self.assertNotIn("<script", page)


class ExportTests(TempCase):
    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            mx.export(scenario_items(), "docx", self.tmp)

    def test_every_format(self):
        items = scenario_items()
        for fmt, expected in (("txt", len(items)), ("csv", 1), ("json", 1),
                              ("html", len(items) + 1)):
            folder = os.path.join(self.tmp, fmt)
            paths = mx.export(items, fmt, folder)
            self.assertEqual(len(paths), expected, fmt)
            for path in paths:
                self.assertTrue(os.path.isfile(path), path)
                self.assertTrue(path.startswith(folder))

    def test_attachments_are_fetched_only_for_html_and_json(self):
        items = scenario_items()
        calls = []

        def fetch(files):
            calls.append(files)
            return [name for _att, name in files]

        for fmt in ("txt", "csv"):
            mx.export(items, fmt, os.path.join(self.tmp, fmt), fetch)
        self.assertEqual(calls, [])
        mx.export(items, "html", os.path.join(self.tmp, "html"), fetch)
        self.assertEqual(len(calls), 1)
        names = [name for _att, name in calls[0]]
        self.assertEqual(names, ["000001_photo.png", "000002_notes.txt"])
        self.assertEqual(len(set(names)), len(names))

    def test_only_what_arrived_is_linked(self):
        items = scenario_items()
        mx.export(items, "html", self.tmp,
                  lambda files: ["000001_photo.png"])
        alice = next(f for f in os.listdir(self.tmp) if "Alice" in f)
        page = self.read(os.path.join(self.tmp, alice))
        self.assertIn("attachments/000001_photo.png", page)
        self.assertNotIn("attachments/000002_notes.txt", page)
        self.assertIn("not exported", page)

    def test_without_a_fetcher_attachments_are_not_linked(self):
        mx.export(scenario_items(), "html", self.tmp)
        alice = next(f for f in os.listdir(self.tmp) if "Alice" in f)
        self.assertNotIn("attachments/", self.read(
            os.path.join(self.tmp, alice)))

    def test_attachments_with_no_backup_path_are_skipped(self):
        att = ms.Attachment(3, "x.png", "image/png", None, 1, None)
        seen = []
        mx.export([(conversation(), [message(attachments=[att])])], "html",
                  self.tmp, lambda files: seen.append(files) or [])
        self.assertEqual(seen, [])


class EndToEndTests(TempCase):
    def check(self, encrypted):
        db = fa.database_bytes(fa.build_sms_db)
        book = fa.database_bytes(fa.build_addressbook)
        files = [("HomeDomain", "Library/SMS/sms.db", db),
                 ("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb",
                  book),
                 ("MediaDomain", fa.ATTACHMENT_PATHS["photo"], fa.PNG_BYTES),
                 ("MediaDomain", fa.ATTACHMENT_PATHS["notes"], fa.NOTES_TXT)]
        backup_dir, _ids = fb.build_backup(self.tmp, files=files,
                                           encrypted=encrypted)
        session = app.BackupSession()
        self.addCleanup(lambda: (session.close(),
                                 session._executor.shutdown(wait=True)))
        session.open(backup_dir, fb.PASSPHRASE if encrypted else None) \
            .result(60)
        index = fi.FileIndex(session.scan().result(60))

        work = os.path.join(self.tmp, "work")
        session.export_files(common.locate_database(index, ms.DATABASE),
                             work).result(60)
        conn = sqlite3.connect(os.path.join(work, "sms.db"))
        self.addCleanup(conn.close)
        reader = ms.MessagesReader(conn)
        items = [(c, reader.messages(c)) for c in reader.conversations()]

        out = os.path.join(self.tmp, "out")

        def fetch(wanted):
            pairs = []
            for att, name in wanted:
                node = index.get(att.backup_path)
                if node is not None:
                    pairs.append((node.file_id, name))
            return session.export_files(
                pairs, os.path.join(out, "attachments")).result(60)

        paths = mx.export(items, "html", out, fetch)
        self.assertTrue(paths)
        with open(os.path.join(out, "attachments", "000001_photo.png"),
                  "rb") as handle:
            self.assertEqual(handle.read(), fa.PNG_BYTES)
        with open(os.path.join(out, "attachments", "000002_notes.txt"),
                  "rb") as handle:
            self.assertEqual(handle.read(), fa.NOTES_TXT)
        alice = next(p for p in paths if "+15550101234" in p)
        page = self.read(alice)
        self.assertIn('src="attachments/000001_photo.png"', page)
        self.assertRegex(page, r"attachments/000002_notes\.txt")

    def test_encrypted(self):
        self.check(True)

    def test_unencrypted(self):
        self.check(False)


if __name__ == "__main__":
    unittest.main()
