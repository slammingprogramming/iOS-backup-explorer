#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Makes an invented iPhone backup to try the app on and to take the
documentation's screenshots from.

    python tools/make_demo_backup.py "C:\\Demo\\Demo iPhone Backup"

The result is a folder of domain folders (``HomeDomain``,
``CameraRollDomain``, ...) holding made-up messages, notes, photos, calls,
contacts, calendar, reminders, health data and more for a made-up person,
"Taylor Morgan". Nothing in it is from a real device. Open the folder in
iOS Backup Explorer like any backup.

Needs Pillow (for the photos) and the project's own test fixtures, which
supply the layout of each database; run it from a clone of the repository.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))      # the repository's top folder
sys.path.insert(0, HERE)

from demo import Writer, communication, device, extras, health, media, web  # noqa: E402,E501


def make(root):
    """Write the demo backup into the (empty or new) folder *root*."""
    writer = Writer(root)
    # people, messages, calls
    writer.database("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb",
                    communication.contacts)
    writer.database("HomeDomain", "Library/SMS/sms.db",
                    communication.messages)
    for path, data in communication.message_files().values():
        writer.file("MediaDomain", path, data)
    writer.database("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata",
                    communication.calls)
    communication.voicemail(writer)
    writer.database("HomeDomain", "Library/Recents/Recents",
                    communication.recents)
    # photos, memos, notes
    media.photos(writer)
    media.voice_memos(writer)
    media.notes(writer)
    # web, calendar, reminders
    web.safari(writer)
    web.calendar(writer)
    web.reminders(writer)
    # the device
    device.information(writer)
    device.network(writer)
    device.accounts(writer)
    device.privacy(writer)
    device.apps(writer)
    device.icloud_drive(writer)
    device.screen_time(writer)
    health.health(writer)
    extras.maps(writer)
    extras.podcasts(writer)
    extras.books(writer)
    return writer.count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", help="where to make the demo backup "
                        "(it must be empty or not exist yet)")
    arguments = parser.parse_args(argv)
    folder = os.path.abspath(arguments.folder)
    if os.path.isdir(folder) and os.listdir(folder):
        parser.error(f"{folder} is not empty")
    count = make(folder)
    print(f"Wrote {count:,} files to {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
