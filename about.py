# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the "About & support" window
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

"""Where to say thanks, and the small window that shows it.

This file is the one list of the project's donation details. The README,
``docs/DONATE.md`` and ``.github/FUNDING.yml`` repeat them, and a test
(``tests/test_about.py``) fails if any of them differs from what is here.

The window is reached from a small link at the top of the main window and is
meant to be found, not to be in the way: nothing in the program asks for
anything, no feature depends on a donation, and showing the window opens
nothing. The two buttons that open a page hand the link to the person's own
browser when they click; the program itself never contacts anyone.
"""

import tkinter as tk
import webbrowser
from tkinter import ttk

REPOSITORY_URL = "https://github.com/slammingprogramming/iOS-backup-explorer"
DONATE_PAGE_URL = REPOSITORY_URL + "/blob/main/docs/DONATE.md"
KOFI_URL = "https://ko-fi.com/scenprogramming"

# (name, short name, address). The Bitcoin address is a Silent Payments
# address (BIP 352, "sp1..."): only wallets that support them can send to it.
ADDRESSES = (
    ("Bitcoin", "BTC",
     "sp1qq2637t6ve9zp4wh0e4ly2u7h7jwfn0k6c4535lxpp3wrqvmkua6xjqkwevyz0wwqx5l"
     "y2f0q29qh48wgf9gl0zt049za9kr9m8xgkey4cyggxa0x"),
    ("Ethereum", "ETH", "0x8F238db898102125Fd968ed7CaD959Cb594a7e93"),
    ("Monero", "XMR",
     "8AYK93mQEzsFFEFkuPN7wC9rPcXCyEXa1Ye5bH9U2GR3PpaZiYc84SxjMcdSdVMaaQUGmCXY"
     "kuxdDSG5bM3EVyqR25nbumV"),
)

WIDTH = 520          # (the wrap width of the text, in pixels)


def _open(url):
    webbrowser.open(url)


class AboutDialog(tk.Toplevel):
    """About the program, and the ways to support it. *name* and *version*
    are the program's own (it is not imported here: the main window imports
    this file)."""

    def __init__(self, parent, name, version):
        super().__init__(parent)
        self.title(f"About {name}")
        self.resizable(False, False)
        self.transient(parent)
        self.entries = {}            # short name -> the entry showing it
        self.copy_buttons = {}       # short name -> its Copy button
        self.note_var = tk.StringVar(value="")
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=f"{name} {version}",
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(
            body, wraplength=WIDTH, justify="left",
            text="Free and open source (AGPL-3.0-or-later). It is a fork of "
                 "BackupLens by Eyyup (Eric) Gunes, whose MIT-licensed work "
                 "it builds on. It works entirely offline: it reads your "
                 "backup on this computer and sends nothing anywhere."
        ).pack(anchor="w", pady=(6, 0))
        ttk.Button(body, text="Project page on GitHub  (opens in your "
                              "browser)",
                   command=lambda: _open(REPOSITORY_URL)).pack(
            anchor="w", pady=(10, 0))

        ttk.Separator(body).pack(fill="x", pady=14)

        ttk.Label(body, text="Support the project",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(
            body, wraplength=WIDTH, justify="left",
            text="The program is free, and nothing in it depends on a "
                 "donation. If it was useful to you and you would like to "
                 "say thanks, you can:"
        ).pack(anchor="w", pady=(6, 0))
        self.kofi_button = ttk.Button(
            body, text="Ko-fi  (opens in your browser)",
            command=lambda: _open(KOFI_URL))
        self.kofi_button.pack(anchor="w", pady=(10, 0))
        ttk.Label(body, text="or send crypto to one of these addresses:",
                  justify="left").pack(anchor="w", pady=(12, 4))

        for label, symbol, address in ADDRESSES:
            row = ttk.Frame(body)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=9).pack(side="left")
            entry = ttk.Entry(row, width=58)
            entry.insert(0, address)
            entry.configure(state="readonly")     # (selectable, not editable)
            entry.pack(side="left", padx=(0, 6))
            button = ttk.Button(
                row, text="Copy",
                command=lambda s=symbol, a=address: self._copy(s, a))
            button.pack(side="left")
            self.entries[symbol] = entry
            self.copy_buttons[symbol] = button

        ttk.Label(
            body, wraplength=WIDTH, justify="left",
            style="Subtitle.TLabel",
            text="The Bitcoin address is a Silent Payments address: only a "
                 "wallet that supports Silent Payments can send to it. The "
                 "same addresses are in the README and in docs/DONATE.md on "
                 "GitHub; check one against the other before you send "
                 "anything, because a payment cannot be taken back."
        ).pack(anchor="w", pady=(10, 0))

        ttk.Label(body, textvariable=self.note_var,
                  style="Subtitle.TLabel").pack(anchor="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(
            side="right")
        self.bind("<Escape>", lambda e: self.destroy())

    def _copy(self, symbol, address):
        self.clipboard_clear()
        self.clipboard_append(address)
        self.note_var.set(f"The {symbol} address is on your clipboard.")
