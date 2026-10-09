# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — what an app view gets from the main window
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

"""The bridge between the main window and an app view.

An app panel gets one :class:`AppContext`. Through it the panel can reach
the backup (to make working copies of databases and attachments), show a
status line, run the normal "extract these files" flow, and look up contact
names, without knowing anything about the rest of the window.
"""

import os
import shutil

from .common import (ContactBook, SqliteSource, Workspace, locate_database)

ADDRESS_BOOK = "HomeDomain/Library/AddressBook/AddressBook.sqlitedb"


class AppContext:
    """*session* is the BackupSession; *post(func, *args)* runs ``func`` on
    the Tk thread; *set_status(text)* shows a message; *extract(file_ids)*
    starts the normal extraction flow for those files."""

    def __init__(self, session, post, set_status, extract):
        self.session = session
        self.post = post
        self.set_status = set_status
        self.extract = extract
        self.index = None
        self._workspace = None
        self._contacts = None            # the ContactBook, once loaded
        self._contact_source = None
        self._contact_callbacks = None   # waiting for it, while loading

    # -- lifetime ---------------------------------------------

    def reset(self, index=None):
        """Forget everything (a different backup was opened) and remove the
        working copies."""
        if self._contact_source is not None:
            self._contact_source.close()
        self._contact_source = None
        self._contacts = None
        self._contact_callbacks = None
        if self._workspace is not None:
            self._workspace.close()
            self._workspace = None
        self.index = index

    @property
    def workspace(self):
        if self._workspace is None:
            self._workspace = Workspace()
        return self._workspace

    # -- helpers for panels -----------------------------------

    def copy_database(self, path, folder_name):
        """Make a working copy of the database at *path* (``Domain/dir/db``)
        together with its journal files. Future -> the folder, or None if
        the backup has no such database."""
        items = locate_database(self.index, path)
        if not items:
            return None
        return self.session.export_files(
            items, self.workspace.subfolder(folder_name))

    def file_id_for(self, path):
        """The file ID of the file at *path* in the backup, or None."""
        node = self.index.get(path) if self.index is not None else None
        return None if node is None or node.is_dir else node.file_id

    def save_file(self, path, destination):
        """Copy the file at *path* in the backup to *destination*.
        Future -> None."""
        file_id = self.file_id_for(path)
        if file_id is None:
            raise FileNotFoundError(path)
        folder = self.workspace.subfolder("save")
        name = "saving" + os.path.splitext(destination)[1]
        future = self.session.export_files([(file_id, name)], folder)

        def finish(done):
            done.result()
            shutil.copyfile(os.path.join(folder, name), destination)
            os.remove(os.path.join(folder, name))

        return _chain(future, finish)

    def load_contacts(self, callback):
        """Call ``callback(book)`` on the Tk thread with the address book
        (an empty one if the backup has none). Loaded once, then reused."""
        if self._contacts is not None:
            callback(self._contacts)
            return
        if self._contact_callbacks is not None:
            self._contact_callbacks.append(callback)
            return
        self._contact_callbacks = [callback]
        future = self.copy_database(ADDRESS_BOOK, "contacts")
        if future is None:
            self._contacts_ready(ContactBook())
            return
        future.add_done_callback(
            lambda done: self.post(self._contacts_copied, done))

    def _contacts_copied(self, done):
        if self._contact_callbacks is None:
            return                       # reset() while we were loading
        if done.exception() is not None:
            self._contacts_ready(ContactBook())
            return
        source = SqliteSource(os.path.join(
            self.workspace.subfolder("contacts"), "AddressBook.sqlitedb"))
        self._contact_source = source
        source.run(ContactBook.from_connection).add_done_callback(
            lambda built: self.post(self._contacts_built, built))

    def _contacts_built(self, built):
        if self._contact_callbacks is None:
            return
        self._contacts_ready(
            ContactBook() if built.exception() is not None
            else built.result())

    def _contacts_ready(self, book):
        self._contacts = book
        waiting, self._contact_callbacks = self._contact_callbacks, None
        for callback in waiting or ():
            callback(book)


def _chain(future, func):
    """A Future that is *func(future)*'s outcome, run on a worker thread."""
    import concurrent.futures
    result = concurrent.futures.Future()

    def run(done):
        try:
            result.set_result(func(done))
        except BaseException as exc:  # noqa: BLE001
            result.set_exception(exc)

    future.add_done_callback(run)
    return result
