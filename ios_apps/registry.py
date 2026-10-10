# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — which app views exist
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

"""The list of app views. To add one, write a reader and a panel and add a
line to :data:`APPS`; a tab appears for it whenever the backup has its data.
"""

from . import (accounts, calendar_events, calls, contacts, messages, network,
               notes, photos, reminders, safari, voicemail, voice_memos)


def _has_file(index, path):
    node = index.get(path)
    return node is not None and not node.is_dir


class AppEntry:
    def __init__(self, key, title, detect, create):
        self.key, self.title = key, title
        self.detect = detect          # detect(index) -> bool
        self.create = create          # create(master, context) -> panel


def _create_messages(master, context):
    from .messages_view import MessagesPanel
    return MessagesPanel(master, context)


def _create_notes(master, context):
    from .notes_view import NotesPanel
    return NotesPanel(master, context)


def _create_calls(master, context):
    from .calls_view import CallsPanel
    return CallsPanel(master, context)


def _create_contacts(master, context):
    from .contacts_view import ContactsPanel
    return ContactsPanel(master, context)


def _create_safari(master, context):
    from .safari_view import SafariPanel
    return SafariPanel(master, context)


def _create_calendar(master, context):
    from .calendar_view import CalendarPanel
    return CalendarPanel(master, context)


def _create_voicemail(master, context):
    from .voicemail_view import VoicemailPanel
    return VoicemailPanel(master, context)


def _create_reminders(master, context):
    from .reminders_view import RemindersPanel
    return RemindersPanel(master, context)


def _create_network(master, context):
    from .network_view import NetworkPanel
    return NetworkPanel(master, context)


def _create_accounts(master, context):
    from .accounts_view import AccountsPanel
    return AccountsPanel(master, context)


def _create_photos(master, context):
    from .photos_view import PhotosPanel
    return PhotosPanel(master, context)


def _create_voice_memos(master, context):
    from .voice_memos_view import VoiceMemosPanel
    return VoiceMemosPanel(master, context)


APPS = [
    AppEntry("messages", "Messages",
             lambda index: _has_file(index, messages.DATABASE),
             _create_messages),
    AppEntry("notes", "Notes",
             lambda index: _has_file(index, notes.DATABASE),
             _create_notes),
    AppEntry("calls", "Calls",
             lambda index: _has_file(index, calls.DATABASE),
             _create_calls),
    AppEntry("contacts", "Contacts",
             lambda index: _has_file(index, contacts.DATABASE),
             _create_contacts),
    AppEntry("photos", "Photos", lambda index: bool(photos.scan(index)),
             _create_photos),
    AppEntry("voice_memos", "Voice Memos", voice_memos.has_recordings,
             _create_voice_memos),
    AppEntry("safari", "Safari",
             lambda index: any(_has_file(index, p) for p in safari.DATABASES),
             _create_safari),
    AppEntry("calendar", "Calendar",
             lambda index: _has_file(index, calendar_events.DATABASE),
             _create_calendar),
    AppEntry("voicemail", "Voicemail",
             lambda index: _has_file(index, voicemail.DATABASE),
             _create_voicemail),
    AppEntry("reminders", "Reminders",
             lambda index: bool(reminders.discover(index)),
             _create_reminders),
    AppEntry("network", "Network",
             lambda index: bool(network.discover(index)),
             _create_network),
    AppEntry("accounts", "Accounts",
             lambda index: bool(accounts.discover(index)),
             _create_accounts),
]


def available_apps(index):
    """The app views whose data is present in the backup behind *index*."""
    return [entry for entry in APPS if entry.detect(index)]
