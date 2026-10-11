# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the Keychain tab
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

"""The Keychain tab: saved passwords, Wi-Fi passwords, certificates and keys.

The keychain is only opened when this tab is first shown. An encrypted backup
that was opened with its password needs nothing more. A folder that was
extracted with this program keeps the backup's key bag (``Manifest.plist``),
and the backup password is asked for here. Nothing is stored: the password is
used to unlock the key bag and then dropped, and the opened items stay in
memory only. Exports that hold passwords are confirmed first.
"""

import concurrent.futures
import tkinter as tk
from tkinter import messagebox, ttk

from . import keychain as kn
from . import keychain_crypto as kc
from .common import own_path
from .notes_unlock import ask_password
from .panel_base import AppPanel
from .records_view import RecordsPanel
from ui_util import post_when_done

ASK = ("This backup's keychain is locked with the backup password (the one "
       "you chose when you made the encrypted backup). Enter it to open the "
       "passwords. It is used to unlock the keys and then dropped; it is not "
       "stored anywhere.")


def _loader(keys):
    """The loader for a panel whose class keys are *keys*."""
    def load(conn, _book, _index):
        reader = kn.KeychainReader(own_path(conn), keys)
        return reader, reader.datasets()
    return load


class KeychainPanel(RecordsPanel):
    FOLDER = "keychain"
    DATABASE = kn.PATH
    ORIGINALS = (kn.PATH,)
    MISSING = "This backup has no keychain file."

    def __init__(self, master, context):
        super().__init__(master, context)
        self._started = False
        self._keys = None
        self._key_bag = None
        self._pool = None
        self.password_button = ttk.Button(
            self._top, text="Enter the backup password...",
            command=self.ask_for_password)

    @property
    def LOADER(self):                       # (the keys are known by now)
        return _loader(self._keys)

    # -- getting the keys -------------------------------------

    def activate(self):
        if self._started:
            return
        self._started = True
        self.state_var.set("Checking the backup...")
        post_when_done(self.ctx.post, self.ctx.session.keychain_source(),
                       self._source_known)

    def _source_known(self, done):
        if self._closed:
            return
        error = done.exception()
        if error is not None:
            self.fail("Could not open the keychain", error)
            return
        mode, payload = done.result()
        if mode == "keys":
            self._keys = payload
            self._read()
        elif mode == "keybag":
            self._key_bag = payload
            self.after_idle(self.ask_for_password)
        else:
            self.state_var.set(payload)

    def ask_for_password(self):
        """Ask for the backup password and unlock the key bag with it."""
        if self._closed or self._key_bag is None or self._keys is not None:
            return
        self.password_button.pack(side="left", padx=(0, 8))
        password = ask_password(self, "Backup password", ASK)
        if password is None:
            self.state_var.set("The keychain stays closed without the "
                               "backup password.")
            return
        self.password_button.pack_forget()
        self.state_var.set("Unlocking the keys (this takes a few seconds)...")
        pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="keybag")
        self._pool = pool
        future = pool.submit(kc.unlock_keybag, self._key_bag, password)
        pool.shutdown(wait=False)
        post_when_done(self.ctx.post, future, self._unlocked)

    def _unlocked(self, done):
        if self._closed:
            return
        error = done.exception()
        if isinstance(error, kc.WrongBackupPassword):
            messagebox.showwarning(
                "Keychain", "That is not the password of this backup.")
            self.after_idle(self.ask_for_password)
            return
        if error is not None:
            self.fail("Could not unlock the keychain", error)
            return
        self._keys = done.result()
        self._read()

    def _read(self):
        self.password_button.pack_forget()
        AppPanel.activate(self)

    def destroy(self):
        self._keys = self._key_bag = None
        super().destroy()

    # -- exporting --------------------------------------------

    def export(self):
        dataset = self.dataset
        if dataset is not None and dataset.key in ("passwords",
                                                   "certificates", "keys"):
            if not messagebox.askokcancel(
                    "Export passwords",
                    "The files you export will hold your passwords and keys "
                    "in readable form, with no protection.\n\nOnly export "
                    "them to a folder you trust, and delete the files when "
                    "you are done.\n\nContinue?",
                    icon="warning"):
                return
        super().export()
