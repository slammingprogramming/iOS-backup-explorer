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

from . import messages


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


APPS = [
    AppEntry("messages", "Messages",
             lambda index: _has_file(index, messages.DATABASE),
             _create_messages),
]


def available_apps(index):
    """The app views whose data is present in the backup behind *index*."""
    return [entry for entry in APPS if entry.detect(index)]
