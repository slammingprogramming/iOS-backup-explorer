# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The Messages reader against fake databases (no GUI)."""

import os
import shutil
import sqlite3
import tempfile
import unittest

import file_index as fi
import ios_backup_explorer as app
from ios_apps import common
from ios_apps import messages as ms
from tests import fixture_apps as fa
from tests import fixture_backup as fb


def open_scenario(builder=fa.build_sms_db):
    conn = sqlite3.connect(":memory:")
    builder(conn)
    return conn


def contact_book():
    conn = sqlite3.connect(":memory:")
    fa.build_addressbook(conn)
    book = common.ContactBook.from_connection(conn)
    conn.close()
    return book


class DecodeAttributedBodyTests(unittest.TestCase):
    def test_short_text(self):
        self.assertEqual(
            ms.decode_attributed_body(fa.attributed_body("hello")), "hello")

    def test_text_longer_than_a_byte_can_count(self):
        text = "x" * 300
        self.assertEqual(
            ms.decode_attributed_body(fa.attributed_body(text)), text)
        self.assertEqual(
            ms.decode_attributed_body(fa.attributed_body(fa.LONG_TEXT)),
            fa.LONG_TEXT)

    def test_very_long_text(self):
        text = "y" * 70_000
        self.assertEqual(
            ms.decode_attributed_body(fa.attributed_body(text)), text)

    def test_length_counts_bytes_not_characters(self):
        text = "café — \U0001F389\U0001F389 日本語"
        self.assertGreater(len(text.encode()), len(text))
        self.assertEqual(
            ms.decode_attributed_body(fa.attributed_body(text)), text)

    def test_exactly_at_the_one_byte_limit(self):
        for size in (127, 128, 129):
            text = "z" * size
            self.assertEqual(
                ms.decode_attributed_body(fa.attributed_body(text)), text,
                size)

    def test_no_text_to_find(self):
        for blob in (None, b"", b"no marker here", b"NSString",
                     b"NSString\x01\x94\x84\x01", memoryview(b"")):
            self.assertIsNone(ms.decode_attributed_body(blob), blob)

    def test_an_unknown_length_form_is_not_guessed_at(self):
        self.assertIsNone(ms.decode_attributed_body(
            b"NSString\x01\x94\x84\x01+\x90abc"))

    def test_a_truncated_blob_gives_what_is_there(self):
        blob = fa.attributed_body("hello world")
        cut = blob[:blob.index(b"hello") + 5]
        self.assertEqual(ms.decode_attributed_body(cut), "hello")

    def test_accepts_a_memoryview(self):
        self.assertEqual(ms.decode_attributed_body(
            memoryview(fa.attributed_body("hi"))), "hi")


class AttachmentPathTests(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(
            ms.attachment_backup_path("~/Library/SMS/Attachments/ab/11/G/a.png"),
            "MediaDomain/Library/SMS/Attachments/ab/11/G/a.png")
        self.assertEqual(
            ms.attachment_backup_path("/var/mobile/Library/SMS/Attachments/x"),
            "MediaDomain/Library/SMS/Attachments/x")
        self.assertEqual(
            ms.attachment_backup_path("Library/SMS/Attachments/x"),
            "MediaDomain/Library/SMS/Attachments/x")
        self.assertIsNone(ms.attachment_backup_path(None))
        self.assertIsNone(ms.attachment_backup_path(""))


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.conn = open_scenario()
        self.addCleanup(self.conn.close)
        self.reader = ms.MessagesReader(self.conn, contact_book())
        self.convs = {c.title: c for c in self.reader.conversations()}

    def test_chats_with_no_messages_are_not_listed(self):
        self.assertEqual(len(self.convs), 4)          # 6 chats, 1 empty, 2 merged

    def test_titles_use_contact_names(self):
        self.assertEqual(sorted(self.convs), [
            "+15550109999", "Alice Example", "Bob Sample", "Weekend Plans"])

    def test_imessage_and_sms_with_the_same_number_are_one_conversation(self):
        alice = self.convs["Alice Example"]
        self.assertEqual(sorted(alice.chat_ids), [1, 2])
        self.assertEqual(alice.services, {"iMessage", "SMS"})
        self.assertEqual(alice.service_label, "SMS + iMessage")
        self.assertEqual(alice.count, 9)              # 8 in chat 1 + 1 SMS
        self.assertFalse(alice.is_group)

    def test_group_conversation(self):
        group = self.convs["Weekend Plans"]
        self.assertTrue(group.is_group)
        self.assertEqual(group.participants,
                         ["Alice Example", "Bob Sample", "+15550109999"])

    def test_newest_conversation_first(self):
        convs = self.reader.conversations()
        times = [c.last_when for c in convs]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(convs[0].title, "+15550109999")   # +400 s

    def test_previews(self):
        self.assertEqual(self.convs["+15550109999"].preview,
                         "Your code is 123456")
        self.assertEqual(self.convs["Bob Sample"].preview,
                         fa.LONG_TEXT.strip()[:120])       # from the blob
        self.assertEqual(self.convs["Alice Example"].preview,
                         "A caption with the photo")

    def test_without_an_address_book_the_raw_handles_show(self):
        reader = ms.MessagesReader(self.conn)
        titles = {c.title for c in reader.conversations()}
        self.assertEqual(titles, {"+15550101234", "friend@example.com",
                                  "Weekend Plans", "+15550109999"})

    def test_an_unnamed_group_is_titled_by_its_members(self):
        self.conn.execute("UPDATE chat SET display_name = NULL WHERE ROWID=4")
        reader = ms.MessagesReader(self.conn, contact_book())
        titles = {c.title for c in reader.conversations()}
        self.assertIn("Alice Example, Bob Sample, +15550109999", titles)

    def test_a_long_member_list_is_shortened(self):
        for n in range(6, 10):
            self.conn.execute("INSERT INTO handle (id, service) VALUES (?, "
                              "'iMessage')", (f"+1555019{n:04d}",))
            self.conn.execute("INSERT INTO chat_handle_join VALUES (4, ?)",
                              (n,))
        self.conn.execute("UPDATE chat SET display_name = NULL WHERE ROWID=4")
        reader = ms.MessagesReader(self.conn, contact_book())
        title = next(c.title for c in reader.conversations() if c.is_group)
        self.assertTrue(title.endswith("and 4 more"), title)


class MessageTests(unittest.TestCase):
    def setUp(self):
        self.conn = open_scenario()
        self.addCleanup(self.conn.close)
        self.reader = ms.MessagesReader(self.conn, contact_book())
        self.convs = {c.title: c for c in self.reader.conversations()}

    def messages(self, title):
        return self.reader.messages(self.convs[title])

    def test_order_and_senders(self):
        texts = [(m.sender, m.text) for m in self.messages("Alice Example")]
        self.assertEqual(texts[0], ("Alice Example",
                                    "Old SMS from before iMessage"))
        self.assertEqual(texts[1], ("Alice Example",
                                    "Hey, are you free tonight?"))
        self.assertEqual(texts[2], ("Me", "Yes! What time?"))

    def test_text_that_only_exists_in_the_archived_blob(self):
        by_guid = {m.guid: m for m in self.messages("Alice Example")}
        self.assertEqual(by_guid["G-M3"].text,
                         "Around 7 — see you there \U0001F389")

    def test_a_long_archived_message_is_complete(self):
        (message,) = self.messages("Bob Sample")
        self.assertEqual(message.text, fa.LONG_TEXT.strip())

    def test_times_in_seconds_and_in_nanoseconds(self):
        by_guid = {m.guid: m for m in self.messages("Alice Example")}
        self.assertEqual(by_guid["G-M1"].when,
                         common.APPLE_EPOCH + fa.T0)
        self.assertEqual(by_guid["G-M8"].when,
                         common.APPLE_EPOCH + fa.T0 - 5_000_000)
        self.assertEqual(by_guid["G-M1"].read_when,
                         common.APPLE_EPOCH + fa.T0 + 5)
        self.assertIsNone(by_guid["G-M2"].read_when)

    def test_tapbacks_attach_to_the_message_they_react_to(self):
        by_guid = {m.guid: m for m in self.messages("Alice Example")}
        (liked,) = by_guid["G-M3"].reactions
        self.assertEqual((liked.kind, liked.sender, liked.from_me),
                         ("Liked", "Me", True))
        self.assertNotIn("G-T1", by_guid)             # not a message itself

    def test_a_removed_tapback_does_not_show(self):
        by_guid = {m.guid: m for m in self.messages("Alice Example")}
        self.assertEqual(by_guid["G-M2"].reactions, [])

    def test_attachments(self):
        by_guid = {m.guid: m for m in self.messages("Alice Example")}
        message = by_guid["G-M5"]
        self.assertEqual(message.text, "")             # only the placeholder
        photo, notes = message.attachments
        self.assertEqual((photo.name, photo.mime, photo.size),
                         ("photo.png", "image/png", len(fa.PNG_BYTES)))
        self.assertTrue(photo.is_image)
        self.assertEqual(photo.backup_path,
                         "MediaDomain/" + fa.ATTACHMENT_PATHS["photo"])
        self.assertFalse(notes.is_image)
        self.assertEqual(notes.backup_path,
                         "MediaDomain/" + fa.ATTACHMENT_PATHS["notes"])
        self.assertEqual(by_guid["G-M5b"].attachments, [])

    def test_group_events_and_unmatched_reactions(self):
        group = self.messages("Weekend Plans")
        by_guid = {m.guid: m for m in group}
        self.assertEqual(by_guid["G-M12"].kind, "event")
        self.assertEqual(
            by_guid["G-M12"].text,
            "Alice Example named the conversation “Weekend Plans”")
        self.assertEqual(by_guid["G-M13"].text,
                         "+15550109999 left the conversation")
        self.assertEqual(by_guid["G-T4"].kind, "event")
        self.assertEqual(by_guid["G-T4"].text,
                         "Bob Sample laughed at a message")
        self.assertEqual(by_guid["G-M10"].sender, "Bob Sample")
        self.assertEqual(by_guid["G-M11"].sender, "Me")
        self.assertEqual([m.guid for m in group],
                         ["G-M10", "G-M11", "G-M12", "G-M13", "G-T4"])

    def test_services(self):
        by_guid = {m.guid: m for m in self.messages("Alice Example")}
        self.assertEqual(by_guid["G-M8"].service, "SMS")
        self.assertEqual(by_guid["G-M1"].service, "iMessage")

    def test_messages_belong_to_their_chat(self):
        chats = {m.guid: m.chat_id for m in self.messages("Alice Example")}
        self.assertEqual(chats["G-M8"], 2)
        self.assertEqual(chats["G-M1"], 1)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.conn = open_scenario()
        self.addCleanup(self.conn.close)
        self.reader = ms.MessagesReader(self.conn, contact_book())
        self.reader.conversations()

    def titles(self, text):
        return [(c.title, m.text) for c, m in self.reader.search(text)]

    def test_plain_text(self):
        self.assertEqual(self.titles("snacks"),
                         [("Weekend Plans", "Who's bringing snacks?")])

    def test_text_that_only_exists_in_the_archived_blob(self):
        for typed in ("Around 7", "around 7", "SEE YOU THERE", "🎉"):
            texts = [t for _title, t in self.titles(typed)]
            self.assertTrue(any("see you there" in t for t in texts), typed)

    def test_the_archive_bookkeeping_inside_the_blob_is_not_searched(self):
        for noise in ("NSString", "NSAttributedString", "kIMMessagePart", "_"):
            self.assertEqual(self.reader.search(noise), [], noise)

    def test_newest_first_and_limited(self):
        both = self.reader.search("e")
        times = [m.when for _c, m in both]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(len(self.reader.search("e", limit=2)), 2)

    def test_wildcards_are_taken_literally(self):
        self.assertEqual(self.reader.search("%"), [])
        self.assertEqual(self.reader.search("_"), [])
        self.assertEqual(self.reader.search("   "), [])
        self.assertEqual(self.reader.search(""), [])

    def test_nothing_found(self):
        self.assertEqual(self.reader.search("zzzzzz"), [])

    def test_results_carry_their_conversation_and_sender(self):
        (conv, message), = self.reader.search("123456")
        self.assertEqual(conv.title, "+15550109999")
        self.assertEqual(message.sender, "+15550109999")


class OldSchemaTests(unittest.TestCase):
    def test_a_database_from_an_old_ios_version(self):
        conn = open_scenario(fa.build_old_sms_db)
        self.addCleanup(conn.close)
        reader = ms.MessagesReader(conn)
        (conv,) = reader.conversations()
        self.assertEqual(conv.title, "+15550101234")
        self.assertEqual(conv.count, 2)
        messages = reader.messages(conv)
        self.assertEqual([(m.sender, m.text) for m in messages],
                         [("+15550101234", "hello from 2015"),
                          ("Me", "hi!")])
        self.assertEqual(messages[0].when,
                         common.APPLE_EPOCH + 450_000_000)
        self.assertEqual(reader.search("hello")[0][1].text, "hello from 2015")

    def test_an_empty_database(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        fa.SMS_SCHEMA and conn.executescript(fa.SMS_SCHEMA)
        self.assertEqual(ms.MessagesReader(conn).conversations(), [])


class FromARealBackupTests(unittest.TestCase):
    """The full path: backup -> working copy of the files -> reader."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-msg-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def open_backup(self, encrypted, with_wal=False):
        db = fa.database_bytes(fa.build_sms_db)
        files = [("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb",
                  fa.database_bytes(fa.build_addressbook)),
                 ("MediaDomain", fa.ATTACHMENT_PATHS["photo"], fa.PNG_BYTES),
                 ("MediaDomain", fa.ATTACHMENT_PATHS["notes"], fa.NOTES_TXT)]
        if with_wal:
            db, wal, shm = fa.sms_db_with_wal()
            files += [("HomeDomain", "Library/SMS/sms.db-wal", wal),
                      ("HomeDomain", "Library/SMS/sms.db-shm", shm)]
        files.append(("HomeDomain", "Library/SMS/sms.db", db))
        backup_dir, _ids = fb.build_backup(self.tmp, files=files,
                                           encrypted=encrypted)
        session = app.BackupSession()
        self.addCleanup(lambda: (session.close(),
                                 session._executor.shutdown(wait=True)))
        session.open(backup_dir, fb.PASSPHRASE if encrypted else None) \
            .result(60)
        index = fi.FileIndex(session.scan().result(60))
        return session, index

    def read_all(self, session, index):
        space = common.Workspace()
        self.addCleanup(space.close)
        items = common.locate_database(index, ms.DATABASE)
        folder = space.subfolder("messages")
        session.export_files(items, folder).result(60)
        book_items = common.locate_database(
            index, "HomeDomain/Library/AddressBook/AddressBook.sqlitedb")
        book_folder = space.subfolder("contacts")
        session.export_files(book_items, book_folder).result(60)

        book_source = common.SqliteSource(
            os.path.join(book_folder, "AddressBook.sqlitedb"))
        self.addCleanup(book_source.close)
        book = book_source.run(common.ContactBook.from_connection).result(30)
        source = common.SqliteSource(os.path.join(folder, "sms.db"))
        self.addCleanup(source.close)

        def read(conn):
            reader = ms.MessagesReader(conn, book)
            convs = reader.conversations()
            return {c.title: reader.messages(c) for c in convs}

        return source.run(read).result(30)

    def check(self, encrypted):
        session, index = self.open_backup(encrypted)
        by_title = self.read_all(session, index)
        self.assertEqual(sorted(by_title), [
            "+15550109999", "Alice Example", "Bob Sample", "Weekend Plans"])
        photo = next(a for m in by_title["Alice Example"]
                     for a in m.attachments if a.name == "photo.png")
        node = index.get(photo.backup_path)
        self.assertIsNotNone(node, "the attachment is in the backup")
        self.assertEqual(node.size, len(fa.PNG_BYTES))

    def test_encrypted(self):
        self.check(True)

    def test_unencrypted(self):
        self.check(False)

    def test_messages_that_are_only_in_the_wal_file_are_found(self):
        session, index = self.open_backup(encrypted=False, with_wal=True)
        self.assertEqual(
            [name for _id, name in common.locate_database(index,
                                                          ms.DATABASE)],
            ["sms.db", "sms.db-wal", "sms.db-shm"])
        by_title = self.read_all(session, index)
        texts = [m.text for m in by_title["Alice Example"]]
        self.assertIn("Only in the WAL", texts)

    def test_without_the_wal_that_message_would_have_been_lost(self):
        db, _wal, _shm = fa.sms_db_with_wal()
        path = os.path.join(self.tmp, "alone.db")
        with open(path, "wb") as handle:
            handle.write(db)
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        reader = ms.MessagesReader(conn)
        texts = [m.text for c in reader.conversations()
                 for m in reader.messages(c)]
        self.assertNotIn("Only in the WAL", texts)


if __name__ == "__main__":
    unittest.main()
