# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the "Devices & backups" window
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

"""One window for everything about backups that is not reading one:

**Backups**: every backup on the computer, wherever kept (Apple's folders, this
program's own, and any folder added), with what each one is and how big it
is; open it, check that its files are all there, copy or move it to another
drive, delete it. Needs no device and no extra program.

**Device**: a phone or tablet plugged in by USB: pair with it (tap Trust),
see what it says about itself, make a backup into any folder, turn the
backup encryption on or off or change its password, copy its crash reports.
This part needs libimobiledevice's tools (see ``device_tools``); without
them the tab says what to install and the rest of the window still works.

All the work happens off the Tk thread and comes back through a queue, as
in the other windows. The window never restores a backup to a device.
"""

import gc
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import backup_library as lib
import device_tools as dt
from file_index import format_size
from ui_util import count_text, weak_notifier

PASSWORD_WARNING = (
    "Write this password down somewhere safe. If it is forgotten, nobody "
    "can open the backups it protects: not Apple, and not this program.")


def _when(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _yes_no(value):
    return "" if value is None else ("Yes" if value else "No")


class PasswordFieldsDialog(tk.Toplevel):
    """Ask for one or more passwords (*fields* are labels; the last two
    of a "new password" pair are checked against each other when
    *confirm_last* is true). ``result`` is a list of the texts typed, in
    order, or None."""

    def __init__(self, parent, title, message, fields, confirm_last=False,
                 warning=""):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self._confirm = confirm_last
        self._vars = [tk.StringVar() for _ in fields]
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=message, wraplength=420,
                  justify="left").pack(anchor="w")
        self.entries = []
        for label, var in zip(fields, self._vars):
            ttk.Label(body, text=label).pack(anchor="w", pady=(10, 0))
            entry = ttk.Entry(body, textvariable=var, show="•", width=40)
            entry.pack(fill="x")
            self.entries.append(entry)
        self.show = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Show the passwords", variable=self.show,
                        command=self._toggle).pack(anchor="w", pady=(6, 0))
        self.error_var = tk.StringVar()
        ttk.Label(body, textvariable=self.error_var,
                  style="Subtitle.TLabel", wraplength=420).pack(anchor="w")
        if warning:
            ttk.Label(body, text=warning, wraplength=420, justify="left",
                      style="Subtitle.TLabel").pack(anchor="w", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        self.ok_button = ttk.Button(buttons, text="OK", command=self._ok)
        self.ok_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())
        self.entries[0].focus_set()

    def _toggle(self):
        for entry in self.entries:
            entry.configure(show="" if self.show.get() else "•")

    def _ok(self):
        values = [v.get() for v in self._vars]
        if not all(values):
            self.error_var.set("Fill in every box.")
            return
        if self._confirm and values[-1] != values[-2]:
            self.error_var.set("The two new passwords are not the same.")
            return
        self.result = values
        self.destroy()


def ask_passwords(parent, title, message, fields, confirm_last=False,
                  warning=""):
    dialog = PasswordFieldsDialog(parent, title, message, fields,
                                  confirm_last, warning)
    dialog.grab_set()
    dialog.wait_window()
    return dialog.result


def _poster(work_queue):
    """``post(func, *args)`` for a thread: it queues the call for the Tk
    thread and holds nothing but the queue."""
    def post(func, *args):
        work_queue.put((func, args))
    return post


class _State:
    """What the worker threads are allowed to look at: plain values and
    nothing of Tk. A thread must never hold the window (or a bound method of
    it): if it held the last reference, the window and its Tk variables
    would be freed inside the thread, and Tk only allows that on its own
    thread (the rule is in docs/ARCHITECTURE.md)."""

    def __init__(self):
        self.generation = 0
        self.closing = False
        self.cancel = threading.Event()


class DevicesWindow(tk.Toplevel):
    """The window. *settings* is an :class:`app_settings.Settings`;
    *locations* a function giving the folders to look for backups in
    (``[(path, who)]``); *toolbox* a :class:`device_tools.Toolbox` (a
    function making one, when the person points to another folder of tools);
    *open_backup(path)* opens a backup in the main window; *default_folder*
    is where new backups go unless another is chosen."""

    #: Milliseconds after the window closes at which its garbage is collected
    #: on the Tk thread (None: not scheduled; the tests collect for
    #: themselves, which a timer firing after their root is gone would disturb).
    COLLECT_AFTER_CLOSE = 100

    def __init__(self, parent, *, settings, locations, toolbox, open_backup,
                 default_folder, make_toolbox=None):
        super().__init__(parent)
        self.title("Devices & backups")
        self.geometry("980x740")
        self.minsize(820, 660)
        self.transient(parent)
        self.settings = settings
        self._locations = locations
        self.toolbox = toolbox
        self._make_toolbox = make_toolbox
        self._open_backup = open_backup
        self._default_folder = default_folder
        self._queue = queue.Queue()
        self._poll_job = self.after(50, self._drain)
        self._state = _State()
        self._cancel = self._state.cancel
        self._entries = {}              # path -> BackupEntry
        self._busy = None               # what the backups tab is doing
        self._udids = []
        self._info = None
        self._run = None                # the BackupRun in progress
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())
        self.bind("<Destroy>", self._destroyed)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)
        # one status line for each tab, so that one never overwrites the
        # other when both are busy
        self.status_var = tk.StringVar()
        self.device_status_var = tk.StringVar()
        self._build_backups_tab()
        self._build_device_tab()
        self.refresh_backups()
        self.refresh_devices()

    # ── Plumbing ──────────────────────────────────────────────

    def _post(self, func, *args):
        self._queue.put((func, args))

    def _drain(self):
        try:
            while True:
                func, args = self._queue.get_nowait()
                func(*args)
        except queue.Empty:
            pass
        if not self._closing:
            self._poll_job = self.after(50, self._drain)

    def _notifier(self, method):
        # (a poster that holds only the queue, not the window: see _State)
        return weak_notifier(_poster(self._queue), method)

    @property
    def _closing(self):
        return self._state.closing

    @_closing.setter
    def _closing(self, value):
        self._state.closing = value

    @property
    def _generation(self):
        return self._state.generation

    @_generation.setter
    def _generation(self, value):
        self._state.generation = value

    def _destroyed(self, event):
        # (however the window goes: its own close button, or its parent)
        if event.widget is self:
            self._closing = True
            self._cancel.set()
            if self._poll_job is not None:
                try:
                    self.after_cancel(self._poll_job)
                except tk.TclError:
                    pass
                self._poll_job = None
            # A closed window is cyclic garbage, which Python may collect in
            # any thread that happens to allocate, a worker included; Tk
            # only lets its variables be freed on its own thread. So collect
            # it here, on the Tk thread, soon after it is gone.
            if self.COLLECT_AFTER_CLOSE is not None:
                try:
                    self.master.after(self.COLLECT_AFTER_CLOSE, gc.collect)
                except (tk.TclError, AttributeError):
                    pass

    @staticmethod
    def _work(target, *args):
        """Run ``target(*args)`` on a thread. *target* must not be a bound
        method of the window, nor may *args* hold it (see :class:`_State`)."""
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        return thread

    def _say(self, text):
        """A line for the Backups tab."""
        self.status_var.set(text)

    def _say_device(self, text):
        """A line for the Device tab."""
        self.device_status_var.set(text)

    # ── The Backups tab ───────────────────────────────────────

    COLUMNS = (("device", "Device", 190, "w"), ("ios", "iOS", 60, "w"),
               ("made", "Made", 125, "w"), ("size", "Size", 85, "e"),
               ("enc", "Encrypted", 75, "center"),
               ("state", "State", 100, "w"), ("where", "Kept by", 230, "w"))

    def _build_backups_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Backups")
        ttk.Label(tab, text="Every backup on this computer, wherever it is "
                  "kept. Nothing here needs a device, iTunes, Finder or the "
                  "Apple Devices app.", wraplength=900,
                  style="Subtitle.TLabel").pack(anchor="w")
        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True, pady=6)
        self.tree = ttk.Treeview(
            frame, columns=[c[0] for c in self.COLUMNS], show="headings",
            selectmode="browse")
        for key, heading, width, anchor in self.COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._sync_buttons())
        self.tree.bind("<Double-1>", lambda e: self.open_selected())

        row = ttk.Frame(tab)
        row.pack(fill="x")
        self.backup_buttons = {}
        for key, text, command in (
                ("open", "Open", self.open_selected),
                ("check", "Check", self.check_selected),
                ("copy", "Copy to...", lambda: self.copy_selected(False)),
                ("move", "Move to...", lambda: self.copy_selected(True)),
                ("delete", "Delete...", self.delete_selected),
                ("folder", "Show in folder", self.show_selected)):
            button = ttk.Button(row, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self.backup_buttons[key] = button
        ttk.Button(row, text="Refresh", command=self.refresh_backups).pack(
            side="right")
        self.add_folder_button = ttk.Button(
            row, text="Add a folder...", command=self.add_folder)
        self.add_folder_button.pack(side="right", padx=6)

        ttk.Label(tab, textvariable=self.status_var,
                  style="Status.TLabel").pack(fill="x", pady=(6, 0))
        self.op_var = tk.StringVar()
        ttk.Label(tab, textvariable=self.op_var, wraplength=900).pack(
            anchor="w", pady=(4, 0))
        bar_row = ttk.Frame(tab)
        bar_row.pack(fill="x")
        self.op_bar = ttk.Progressbar(bar_row, maximum=100)
        self.op_bar.pack(side="left", fill="x", expand=True)
        self.op_cancel = ttk.Button(bar_row, text="Stop",
                                    command=self._cancel.set,
                                    state="disabled")
        self.op_cancel.pack(side="left", padx=(8, 0))
        self._sync_buttons()

    def refresh_backups(self):
        """Look again at every folder, in the background."""
        self._generation += 1
        generation = self._generation
        locations = list(self._locations())
        self._say("Looking for backups...")
        self._work(self._find, generation, locations,
                   self._notifier(self._show_backups))

    @staticmethod
    def _find(generation, locations, notify):
        notify(generation, lib.find_backups(locations))

    def _show_backups(self, generation, entries):
        if generation != self._generation or self._closing:
            return
        self._entries = {e.path: e for e in entries}
        self.tree.delete(*self.tree.get_children())
        for entry in entries:
            self.tree.insert("", "end", iid=entry.path,
                             values=self._row(entry))
        self._say(count_text(len(entries), "backup") + " found."
                  if entries else "No backups were found in the folders "
                  "this program knows. Use Add a folder... to point to one.")
        self._sync_buttons()
        # sizes take a while on a big drive: filled in as each is known
        self._work(self._measure, self._state, generation,
                   [e.path for e in entries], self._notifier(self._set_size))

    @staticmethod
    def _measure(state, generation, paths, notify):
        def stale():
            return generation != state.generation or state.closing

        for path in paths:
            if stale():
                return
            try:
                notify(generation, path, lib.folder_size(path, cancel=stale))
            except lib.Cancelled:
                return

    def _set_size(self, generation, path, size):
        if generation != self._generation or path not in self._entries:
            return
        self._entries[path].size = size
        if self.tree.exists(path):
            self.tree.set(path, "size", format_size(size))

    @staticmethod
    def _row(entry):
        state = {True: "Complete", False: "Interrupted",
                 None: ""}[entry.complete]
        return (entry.title, entry.version, _when(entry.made),
                "" if entry.size is None else format_size(entry.size),
                _yes_no(entry.encrypted), state, entry.location)

    def selected_entry(self):
        chosen = self.tree.selection()
        return self._entries.get(chosen[0]) if chosen else None

    def _sync_buttons(self):
        selected = self.selected_entry() is not None
        free = self._busy is None
        for key, button in self.backup_buttons.items():
            button.configure(state="normal" if selected and free
                             else "disabled")
        self.add_folder_button.configure(
            state="normal" if free else "disabled")
        self.op_cancel.configure(state="disabled" if free else "normal")

    def open_selected(self):
        entry = self.selected_entry()
        if entry:
            self._open_backup(entry.path)

    def show_selected(self):
        entry = self.selected_entry()
        if entry:
            _reveal(entry.path)

    def add_folder(self):
        folder = filedialog.askdirectory(
            parent=self, title="A folder that holds backups")
        if not folder:
            return
        self.settings.add_folder(folder)
        self.settings.save()
        self.refresh_backups()

    # Longer operations: one at a time, with a progress bar and a Stop.

    def _begin(self, what):
        self._busy = what
        self._cancel.clear()
        self.op_bar.configure(value=0)
        self.op_var.set(what)
        self._sync_buttons()

    def _progress(self, done, total):
        if total:
            self.op_bar.configure(value=100.0 * done / total)

    def _end(self, message):
        self._busy = None
        self.op_var.set(message)
        self.op_bar.configure(value=0)
        self._sync_buttons()

    def check_selected(self):
        entry = self.selected_entry()
        if not entry or self._busy:
            return
        self._begin(f"Checking {entry.title}...")
        self._work(self._check, self._cancel, entry.path,
                   self._notifier(self._checked),
                   self._notifier(self._progress_count))

    @staticmethod
    def _check(cancel, path, done, progress):
        try:
            report = lib.check_backup(
                path, progress=lambda n: progress(n, 0),
                cancel=cancel.is_set)
            done(path, report, None)
        except lib.Cancelled:
            done(path, None, "Stopped.")
        except Exception as error:
            done(path, None, str(error))

    def _progress_count(self, count, _total):
        self.op_var.set(f"Checking... {count:,} files looked at")

    def _checked(self, path, report, error):
        if self._closing:
            return
        if error:
            self._end(error)
            return
        lines = [f"{report.files:,} files looked at, "
                 f"{report.missing:,} missing."]
        if report.problems:
            lines += report.problems[:8]
        if report.note:
            lines.append(report.note)
        text = "\n".join(lines)
        self._end(lines[0])
        if report.ok:
            messagebox.showinfo("Check", "Nothing is wrong that could be "
                                "looked at.\n\n" + text, parent=self)
        else:
            messagebox.showwarning("Check", "Something is wrong.\n\n"
                                   + text, parent=self)

    def copy_selected(self, move):
        entry = self.selected_entry()
        if not entry or self._busy:
            return
        folder = filedialog.askdirectory(
            parent=self, title="Move the backup into which folder?" if move
            else "Copy the backup into which folder?")
        if not folder:
            return
        verb = "Moving" if move else "Copying"
        self._begin(f"{verb} {entry.title}...")
        self._work(self._transfer, self._cancel, entry.path, folder, move,
                   list(self._locations()),
                   self._notifier(self._transferred),
                   self._notifier(self._progress))

    @staticmethod
    def _transfer(cancel, path, folder, move, locations, done, progress):
        try:
            if move:
                target = lib.move_backup(
                    path, folder, locations, progress=progress,
                    cancel=cancel.is_set)
            else:
                target = lib.copy_backup(path, folder, progress=progress,
                                         cancel=cancel.is_set)
            done(move, target, None)
        except lib.Cancelled:
            done(move, None, "Stopped. Nothing was left behind.")
        except Exception as error:
            done(move, None, str(error))

    def _transferred(self, move, target, error):
        if self._closing:
            return
        if error:
            self._end(error)
            return
        self._end(("Moved" if move else "Copied") + f" to {target}.")
        self.refresh_backups()

    def delete_selected(self):
        entry = self.selected_entry()
        if not entry or self._busy:
            return
        size = "" if entry.size is None else f" ({format_size(entry.size)})"
        if not messagebox.askyesno(
                "Delete this backup?",
                f"Delete the backup of {entry.title}{size}, made "
                f"{_when(entry.made) or 'at an unknown time'}?\n\n"
                f"{entry.path}\n\nThis cannot be undone: it does not go to "
                "the recycle bin.", icon="warning", default="no",
                parent=self):
            return
        try:
            lib.delete_backup(entry.path, list(self._locations()))
        except Exception as error:
            messagebox.showerror("Delete", str(error), parent=self)
            return
        self._say(f"Deleted the backup of {entry.title}.")
        self.refresh_backups()

    # ── The Device tab ────────────────────────────────────────

    INFO_FIELDS = (("name", "Name"), ("model", "Model"),
                   ("version", "iOS"), ("serial", "Serial number"),
                   ("udid", "UDID"), ("storage", "Free space"),
                   ("battery", "Battery"), ("passcode", "Passcode"),
                   ("pairing", "This computer"),
                   ("encryption", "Backups are encrypted"))

    def _build_device_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Device")
        self.tools_var = tk.StringVar()
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, textvariable=self.tools_var, wraplength=760,
                  justify="left").pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Tools folder...",
                   command=self.choose_tools_folder).pack(side="right")

        pick = ttk.Frame(tab)
        pick.pack(fill="x", pady=(8, 0))
        ttk.Label(pick, text="Device:").pack(side="left")
        self.device_var = tk.StringVar()
        self.device_box = ttk.Combobox(pick, textvariable=self.device_var,
                                       state="readonly", width=60)
        self.device_box.pack(side="left", padx=8)
        self.device_box.bind("<<ComboboxSelected>>",
                             lambda e: self._device_chosen())
        ttk.Button(pick, text="Refresh", command=self.refresh_devices).pack(
            side="left")

        grid = ttk.Frame(tab)
        grid.pack(fill="x", pady=8)
        self.info_vars = {}
        for index, (key, label) in enumerate(self.INFO_FIELDS):
            ttk.Label(grid, text=label + ":").grid(
                row=index // 2, column=(index % 2) * 2, sticky="e",
                padx=(0, 6), pady=1)
            var = tk.StringVar()
            self.info_vars[key] = var
            ttk.Label(grid, textvariable=var).grid(
                row=index // 2, column=(index % 2) * 2 + 1, sticky="w",
                padx=(0, 30), pady=1)

        actions = ttk.Frame(tab)
        actions.pack(fill="x")
        self.pair_button = ttk.Button(actions, text="Trust this computer",
                                      command=self.pair)
        self.pair_button.pack(side="left")
        self.crash_button = ttk.Button(actions, text="Copy crash reports...",
                                       command=self.copy_crash_reports)
        self.crash_button.pack(side="left", padx=6)

        enc = ttk.LabelFrame(tab, text="Backup encryption", padding=6)
        enc.pack(fill="x", pady=(10, 0))
        self.enc_on = ttk.Button(enc, text="Turn on...",
                                 command=self.enable_encryption)
        self.enc_off = ttk.Button(enc, text="Turn off...",
                                  command=self.disable_encryption)
        self.enc_change = ttk.Button(enc, text="Change password...",
                                     command=self.change_password)
        for button in (self.enc_on, self.enc_off, self.enc_change):
            button.pack(side="left", padx=(0, 6))
        ttk.Label(enc, text="Encrypted backups also keep your health data "
                  "and saved passwords.", style="Subtitle.TLabel").pack(
            side="left", padx=8)

        make = ttk.LabelFrame(tab, text="Make a backup", padding=6)
        make.pack(fill="both", expand=True, pady=(10, 0))
        where = ttk.Frame(make)
        where.pack(fill="x")
        ttk.Label(where, text="Into:").pack(side="left")
        self.dest_var = tk.StringVar(
            value=self.settings.backup_destination or self._default_folder)
        ttk.Label(where, textvariable=self.dest_var).pack(
            side="left", padx=6, fill="x", expand=True)
        ttk.Button(where, text="Choose...",
                   command=self.choose_destination).pack(side="right")
        controls = ttk.Frame(make)
        controls.pack(fill="x", pady=4)
        self.full_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Full backup (not only what changed)",
                        variable=self.full_var).pack(side="left")
        self.stop_button = ttk.Button(controls, text="Stop",
                                      command=self.stop_backup,
                                      state="disabled")
        self.stop_button.pack(side="right")
        self.backup_button = ttk.Button(controls, text="Back up now",
                                        command=self.start_backup)
        self.backup_button.pack(side="right", padx=6)
        self.bk_bar = ttk.Progressbar(make, maximum=100)
        self.bk_bar.pack(fill="x")
        ttk.Label(make, textvariable=self.device_status_var,
                  style="Status.TLabel", wraplength=900).pack(
            fill="x", pady=(4, 0))
        self.log = tk.Text(make, height=6, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, pady=(6, 0))
        self._refresh_tools_text()
        self._sync_device_buttons()

    def _refresh_tools_text(self):
        if not self.toolbox.missing:
            self.tools_var.set("The libimobiledevice tools were found.")
        elif len(self.toolbox.missing) == len(dt.TOOL_NAMES):
            self.tools_var.set(dt.HINTS[dt.TOOL_MISSING])
        else:
            self.tools_var.set("Some tools are missing ("
                               + ", ".join(self.toolbox.missing) + "). "
                               + dt.HINTS[dt.TOOL_MISSING])

    def choose_tools_folder(self):
        folder = filedialog.askdirectory(
            parent=self, title="The folder that holds idevicebackup2 and "
            "the other libimobiledevice tools")
        if not folder or not self._make_toolbox:
            return
        self.settings.tools_folder = folder
        self.settings.save()
        self.toolbox = self._make_toolbox(folder)
        self._refresh_tools_text()
        self.refresh_devices()

    def choose_destination(self):
        folder = filedialog.askdirectory(
            parent=self, title="Where to keep new backups")
        if folder:
            self.dest_var.set(folder)
            self.settings.backup_destination = folder
            self.settings.save()

    def refresh_devices(self):
        if not self.toolbox.can_list:
            self._show_devices([], dt.DeviceError(dt.TOOL_MISSING))
            return
        self._work(self._list_devices, self.toolbox,
                   self._notifier(self._show_devices))

    @staticmethod
    def _list_devices(toolbox, notify):
        try:
            notify(toolbox.devices(), None)
        except dt.DeviceError as error:
            notify([], error)

    def _show_devices(self, udids, error):
        if self._closing:
            return
        previous = self.device_var.get()
        self._udids = list(udids)
        self.device_box.configure(values=self._udids)
        if error is not None:
            self.device_var.set("")
            self._clear_info()
            self._say_device(str(error))
        elif not udids:
            self.device_var.set("")
            self._clear_info()
            self._say_device("No device is plugged in. " + dt.HINTS[dt.NO_DEVICE])
        else:
            chosen = previous if previous in udids else udids[0]
            self.device_var.set(chosen)
            self._device_chosen()
        self._sync_device_buttons()

    def _clear_info(self):
        for var in self.info_vars.values():
            var.set("")
        self._info = None

    @property
    def udid(self):
        return self.device_var.get()

    def _device_chosen(self):
        udid = self.udid
        if not udid:
            return
        self._clear_info()
        self.info_vars["udid"].set(udid)
        self._say_device("Asking the device...")
        self._work(self._read_device, self.toolbox, udid,
                   self._notifier(self._shown_info))

    @staticmethod
    def _read_device(toolbox, udid, notify):
        pairing, info, error = None, None, None
        try:
            pairing = toolbox.pairing(udid)
        except dt.DeviceError as caught:
            error = caught
        if pairing == dt.PAIRED:
            try:
                info = toolbox.info(udid)
            except dt.DeviceError as caught:
                error = caught
        notify(udid, pairing, info, error)

    def _shown_info(self, udid, pairing, info, error):
        if self._closing or udid != self.udid:
            return
        self.info_vars["pairing"].set({
            dt.PAIRED: "Trusted", dt.UNPAIRED: "Not trusted yet",
            None: "Unknown"}[pairing])
        if info is not None:
            self._info = info
            v = self.info_vars
            v["name"].set(info.name)
            v["model"].set(info.model)
            v["version"].set(f"{info.version} ({info.build})"
                             if info.build else info.version)
            v["serial"].set(info.serial)
            v["udid"].set(info.udid)
            v["storage"].set(
                "" if info.storage_free is None else
                format_size(info.storage_free) + (
                    "" if info.storage_total is None else
                    " of " + format_size(info.storage_total)))
            v["battery"].set("" if info.battery is None
                             else f"{info.battery}%")
            v["passcode"].set(_yes_no(info.passcode_set).replace(
                "Yes", "Set").replace("No", "Not set"))
            v["encryption"].set(_yes_no(info.encrypts_backups))
            self._say_device(f"{info.name or udid} is ready.")
        elif error is not None:
            self._say_device(str(error))
        elif pairing == dt.UNPAIRED:
            self._say_device("Press Trust this computer, then tap Trust on the "
                      "device.")
        self._sync_device_buttons()

    def _sync_device_buttons(self):
        have = bool(self.udid)
        running = self._run is not None
        paired = self.info_vars["pairing"].get() == "Trusted"
        can = have and not running and not self._closing
        self.pair_button.configure(
            state="normal" if can and not paired else "disabled")
        self.backup_button.configure(
            state="normal" if can and paired and self.toolbox.can_backup
            else "disabled")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.crash_button.configure(
            state="normal" if can and paired and self.toolbox.has(
                "idevicecrashreport") else "disabled")
        known = self._info is not None
        enabled = can and paired and known and self.toolbox.has(
            "idevicebackup2")
        encrypted = known and self._info.encrypts_backups
        self.enc_on.configure(
            state="normal" if enabled and not encrypted else "disabled")
        self.enc_off.configure(
            state="normal" if enabled and encrypted else "disabled")
        self.enc_change.configure(
            state="normal" if enabled and encrypted else "disabled")

    # Pairing

    def pair(self):
        udid = self.udid
        if not udid:
            return
        self._say_device("Unlock the device and tap Trust when it asks...")
        self.pair_button.configure(state="disabled")
        self._cancel.clear()
        self._work(self._pair, self._state, self.toolbox, udid,
                   self._notifier(self._paired))

    @staticmethod
    def _pair(state, toolbox, udid, notify):
        for _ in range(30):                 # about a minute to tap Trust
            try:
                toolbox.pair(udid)
                notify(udid, None)
                return
            except dt.DeviceError as error:
                if error.kind != dt.NOT_TRUSTED or state.closing:
                    notify(udid, error)
                    return
            time.sleep(2)
        notify(udid, dt.DeviceError(dt.NOT_TRUSTED))

    def _paired(self, udid, error):
        if self._closing:
            return
        if error is not None:
            self._say_device(str(error))
            self._sync_device_buttons()
            return
        self._device_chosen()

    # Encryption

    def enable_encryption(self):
        values = ask_passwords(
            self, "Turn on backup encryption",
            "The device will encrypt its backups with this password. It may "
            "ask for its own passcode to confirm.",
            ["New backup password", "The same again"], confirm_last=True,
            warning=PASSWORD_WARNING)
        if values:
            # (read here: Tk is for the Tk thread, and a closure that
            # captured self would let a thread hold the window)
            udid, toolbox = self.udid, self.toolbox
            self._encryption_job("Turning encryption on...",
                                 lambda: toolbox.set_encryption(
                                     udid, True, values[0]))

    def disable_encryption(self):
        values = ask_passwords(
            self, "Turn off backup encryption",
            "Enter the current backup password. Later backups will not be "
            "encrypted, and will not hold health data or saved passwords.",
            ["Current backup password"])
        if values:
            udid, toolbox = self.udid, self.toolbox
            self._encryption_job("Turning encryption off...",
                                 lambda: toolbox.set_encryption(
                                     udid, False, values[0]))

    def change_password(self):
        values = ask_passwords(
            self, "Change the backup password",
            "The device may ask for its own passcode to confirm.",
            ["Current backup password", "New backup password",
             "The new one again"], confirm_last=True,
            warning=PASSWORD_WARNING)
        if values:
            udid, toolbox = self.udid, self.toolbox
            self._encryption_job("Changing the password...",
                                 lambda: toolbox.change_password(
                                     udid, values[0], values[1]))

    def _encryption_job(self, message, action):
        self._say_device(message + " (the device may ask for its passcode)")
        for button in (self.enc_on, self.enc_off, self.enc_change):
            button.configure(state="disabled")
        notify = self._notifier(self._encryption_done)

        def run():
            try:
                action()
                notify(None)
            except dt.DeviceError as error:
                notify(error)

        self._work(run)

    def _encryption_done(self, error):
        if self._closing:
            return
        if error is not None:
            self._say_device(str(error))
            messagebox.showerror("Backup encryption", str(error),
                                 parent=self)
            self._sync_device_buttons()
            return
        self._say_device("Done.")
        self._device_chosen()

    # Crash reports

    def copy_crash_reports(self):
        folder = filedialog.askdirectory(
            parent=self, title="Copy the device's crash reports into")
        if not folder or not self.udid:
            return
        self._say_device("Copying the crash reports (they stay on the device)...")
        notify = self._notifier(self._crash_done)
        udid, toolbox = self.udid, self.toolbox

        def run():
            try:
                notify(toolbox.crash_reports(udid, folder, keep=True),
                       folder, None)
            except dt.DeviceError as error:
                notify(0, folder, error)

        self._work(run)

    def _crash_done(self, count, folder, error):
        if self._closing:
            return
        self._say_device(str(error) if error else
                  f"{count_text(count, 'crash report')} copied to {folder}.")

    # Backing up

    def start_backup(self):
        udid = self.udid
        if not udid or self._run is not None:
            return
        folder = self.dest_var.get()
        self._append_log(f"Backing up to {folder}")
        self.bk_bar.configure(value=0)
        try:
            self._run = self.toolbox.start_backup(
                udid, folder, full=self.full_var.get(),
                on_progress=self._notifier(self._backup_progress),
                on_line=self._notifier(self._append_log),
                on_done=self._notifier(self._backup_done))
        except (dt.DeviceError, OSError) as error:
            self._say_device(str(error))
            messagebox.showerror("Back up", str(error), parent=self)
            return
        self._say_device("Backing up. Keep the device unlocked and plugged in.")
        self._sync_device_buttons()

    def _backup_progress(self, percent):
        self.bk_bar.configure(value=percent)

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def stop_backup(self):
        if self._run is not None:
            self._say_device("Stopping...")
            self._run.stop()

    def _backup_done(self, outcome):
        self._run = None
        if self._closing:
            return
        self._say_device(outcome.message)
        self._append_log(outcome.message)
        self._sync_device_buttons()
        if outcome.ok:
            self.bk_bar.configure(value=100)
            self.refresh_backups()
            if messagebox.askyesno(
                    "Backup finished", "The backup is complete. Open it "
                    "now?", parent=self):
                self._open_backup(outcome.folder)
        else:
            self.bk_bar.configure(value=0)

    # ── Closing ───────────────────────────────────────────────

    def _on_close(self):
        if self._run is not None:
            if not messagebox.askyesno(
                    "Backup in progress", "A backup is running. Stop it and "
                    "close the window? (What was copied is kept, and the "
                    "next backup carries on from it.)", parent=self):
                return
            self._run.stop()
            self._run.wait(10)
        self._closing = True
        self._cancel.set()
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        self.destroy()


def _reveal(path):
    """Show *path* in the system's file manager."""
    import subprocess
    import sys
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)             # noqa: S606 (a folder we listed)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass
