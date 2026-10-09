# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — what the app panels have in common
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

"""The common part of the app panels (Notes, Calls, Contacts, ...).

A panel is shown as a tab. When it is first shown it makes a working copy of
its database, builds its reader on the database thread, and hands the first
results to :meth:`on_loaded`. This class also runs exports in the background
and extracts the original files, so each panel only describes what is
specific to it.

Threads: the reader and every database query live on one worker thread. No
worker thread touches Tk; results come back through ``ctx.post``. Callbacks
refer to their panel only weakly (see :mod:`ui_util`).
"""

import concurrent.futures
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ui_util import post_when_done, weak_notifier

from . import common
from .common import SqliteSource


class _ReaderHolder:
    """Where the reader (made on the database thread) is kept."""

    reader = None


class AppPanel(ttk.Frame):
    DATABASE = None             # "Domain/dir/file" in the backup
    FOLDER = "app"              # the working-copy folder's name
    WITH_CONTACTS = False       # wait for the address book before loading
    LOADER = None               # staticmethod: (conn, contacts, ctx) ->
                                #   (reader, first data); runs on the db thread
    MISSING = "This backup has no data for this app."
    OPTIONAL = False            # a panel that also works without a database

    def __init__(self, master, context):
        super().__init__(master)
        self.ctx = context
        self.source = None
        self._holder = _ReaderHolder()   # closures use the holder, never
                                         # the panel (see the module notes)
        self._loaded = False
        self._closed = False        # set once the tab is gone; late results
                                    # from worker threads are then ignored
        self._timers = {}
        self.state_var = tk.StringVar(value="")

    @property
    def _reader(self):
        return self._holder.reader

    # -- loading ----------------------------------------------

    def activate(self):
        """Called when the tab is first shown; loads the data once."""
        if self._loaded:
            return
        self._loaded = True
        self.state_var.set("Loading...")
        path = self.database_path()
        future = self.ctx.copy_database(path, self.FOLDER) if path else None
        if future is None:
            if self.OPTIONAL:
                self.on_loaded(self.load_without_database())
            else:
                self.state_var.set(self.MISSING)
            return
        post_when_done(self.ctx.post, future, self._database_copied)

    def database_path(self):
        """The database to copy (``Domain/dir/file``), or None. Panels that
        may find one of several databases override this."""
        return self.DATABASE

    def load_without_database(self):
        """For an OPTIONAL panel: the data to show when there is no
        database (runs on the Tk thread)."""
        raise NotImplementedError

    def _database_copied(self, done):
        error = done.exception()
        if error is not None:
            if self.OPTIONAL:        # show what the files alone tell
                self.on_loaded(self.load_without_database(
                    f"The library database could not be copied: {error}"))
                return
            self.fail("Could not read this data", error)
            return
        if self.WITH_CONTACTS:
            self.ctx.load_contacts(self._with_contacts)
        else:
            self._with_contacts(None)

    def _with_contacts(self, book):
        path = os.path.join(self.ctx.workspace.subfolder(self.FOLDER),
                            os.path.basename(self.database_path()))
        self.source = SqliteSource(path)
        holder, loader, ctx_index = self._holder, self.LOADER, self.ctx.index

        def start(conn):
            holder.reader, data = loader(conn, book, ctx_index)
            return data

        post_when_done(self.ctx.post, self.source.run(start), self._first_data)

    def _first_data(self, done):
        error = done.exception()
        if error is not None:
            self.fail("Could not read this data", error)
            return
        self.on_loaded(done.result())

    def on_loaded(self, data):
        raise NotImplementedError

    def fail(self, what, error):
        self.state_var.set(f"{what}: {str(error) or type(error).__name__}")

    def run_query(self, func, method, *args):
        """Run ``func(reader)`` on the database thread and call
        ``method(future, *args)`` on the Tk thread with the outcome. A panel
        that works without a database (OPTIONAL) has no such thread; its
        *func* is then run right here, which is fine because there is no
        database to wait for."""
        reader = self._reader
        if self.source is None:
            done = concurrent.futures.Future()
            try:
                done.set_result(func(reader))
            except Exception as exc:       # the caller looks at the outcome
                done.set_exception(exc)
            method(done, *args)
            return
        post_when_done(self.ctx.post,
                       self.source.run(lambda conn: func(reader)),
                       method, *args)

    # -- timers -----------------------------------------------

    def schedule(self, key, delay, func):
        """Run *func* after *delay* ms; a new call with the same *key*
        replaces the one still waiting."""
        self.cancel_timer(key)
        self._timers[key] = self.after(delay, lambda: self._fire(key, func))

    def _fire(self, key, func):
        self._timers.pop(key, None)
        func()

    def cancel_timer(self, key):
        job = self._timers.pop(key, None)
        if job is not None:
            self.after_cancel(job)

    def cancel_timers(self):
        for key in list(self._timers):
            self.cancel_timer(key)

    # -- exporting --------------------------------------------

    def start_export(self, load, write, folder, path_of=None):
        """Export in the background.

        ``load(reader)`` runs on the database thread and returns the data.
        ``write(data, fetch)`` runs on a new thread and returns the paths
        written; ``fetch`` copies attachments out of the backup (see
        :meth:`AppContext.fetcher`).
        """
        self.ctx.set_status("Exporting...")
        self.run_query(load, self._export_loaded, write, folder, path_of)

    def _export_loaded(self, done, write, folder, path_of):
        error = done.exception()
        if error is not None:
            self._export_finished(error, None, folder)
            return
        data = done.result()
        fetch = self.ctx.fetcher(folder, path_of) if path_of \
            else self.ctx.fetcher(folder)
        notify = weak_notifier(self.ctx.post, self._export_finished)

        def work():
            try:
                paths = write(data, fetch)
            except Exception as exc:       # reported in the window
                notify(exc, None, folder)
            else:
                notify(None, paths, folder)

        threading.Thread(target=work, daemon=True, name="export").start()

    def _export_finished(self, error, result, folder):
        if error is not None:
            self.ctx.set_status("Export failed.")
            messagebox.showerror("Export failed",
                                 str(error) or type(error).__name__)
            return
        # a writer may return (paths, notes) to report things that went less
        # than perfectly, such as a picture that could not be converted
        paths, notes = result if isinstance(result, tuple) else (result, "")
        self.ctx.set_status(f"Exported {len(paths):,} file(s) to {folder}")
        message = f"Wrote {len(paths):,} file(s) to:\n{folder}"
        messagebox.showinfo("Export finished",
                            message + (f"\n\n{notes}" if notes else ""))

    def extract_originals_of(self, backup_paths):
        """Extract these files exactly as the backup has them, using the
        normal extraction (it asks for a folder)."""
        ids = [self.ctx.file_id_for(p) for p in backup_paths]
        ids = list(dict.fromkeys(i for i in ids if i))
        if not ids:
            messagebox.showinfo("Original files", "Nothing to extract.")
            return
        self.ctx.extract(ids)

    # -- single files -----------------------------------------

    def save_backup_file(self, backup_path, suggested_name, title="Save as"):
        """Ask where to put one file from the backup and copy it there."""
        from tkinter import filedialog
        if self.ctx.file_id_for(backup_path) is None:
            messagebox.showinfo("Save", "This file is not in the backup.")
            return
        destination = filedialog.asksaveasfilename(
            initialfile=suggested_name, title=title)
        if not destination:
            return
        post_when_done(self.ctx.post,
                       self.ctx.save_file(backup_path, destination),
                       self._file_saved, destination)

    def _file_saved(self, done, destination):
        error = done.exception()
        if error is not None:
            messagebox.showerror("Save", f"Could not save it: {error}")
        else:
            self.ctx.set_status(f"Saved {destination}")

    def open_backup_file(self, backup_path):
        """Open a file from the backup with the program the computer uses
        for it (a working copy is made first)."""
        if self.ctx.file_id_for(backup_path) is None:
            messagebox.showinfo("Open", "This file is not in the backup.")
            return
        post_when_done(self.ctx.post,
                       self.ctx.fetch_local([backup_path], "open"),
                       self._file_ready, backup_path)

    def _file_ready(self, done, backup_path):
        error = done.exception()
        local = None if error is not None else done.result().get(backup_path)
        if not local:
            messagebox.showerror("Open", f"Could not open it: {error}"
                                 if error else "Could not open it.")
            return
        self.launch_local(local)

    def launch_local(self, local):
        """Open a working copy with the computer's own program for it."""
        try:
            common.open_file(local)
        except common.NotOpened as exc:
            messagebox.showinfo("Open", f"It was not opened: {exc}.")
        except OSError as exc:
            messagebox.showerror("Open", f"Could not open it: {exc}")

    # -- shutdown ---------------------------------------------

    def close(self):
        self._closed = True
        self.cancel_timers()
        if self.source is not None:
            self.source.close()
            self.source = None
