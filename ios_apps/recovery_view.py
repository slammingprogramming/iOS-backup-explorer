# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the "Forgot password?" dialog
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

"""``ForgotPasswordDialog``: three tabs for someone locked out of their own
backup or their own locked note.

*Official* and *Workaround* are plain, static advice, written for each of
the two cases by the caller. *Hashcat* is only as able as the computer it
runs on: it needs hashcat itself (never bundled, never downloaded by this
program; see ``docs/RECOVERY.md``) and something worth trying — a wordlist
the person already has, one `CUPP <https://github.com/Mebus/cupp>`_ (also
optional, also never downloaded by this program) builds from things they
remember about themselves, or a mask for a short PIN-like password. None of
this reads anything this program could not already read with the right
password: the point is only to find that password faster than guessing it
by hand would.
"""

import os
import queue
import shutil
import tempfile
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import recovery as rec
from ui_util import weak_notifier

MASK_PRESETS = (
    ("A 4-digit PIN", "?d?d?d?d"),
    ("A 6-digit PIN", "?d?d?d?d?d?d"),
    ("An 8-digit date (DDMMYYYY)", "?d?d?d?d?d?d?d?d"),
)


class _Base(tk.Toplevel):
    """Shared plumbing: a self-contained, thread-safe way to hear back from
    a background thread, and cleanup when the window closes."""

    def __init__(self, parent):
        super().__init__(parent)
        self.transient(parent)
        self._queue = queue.Queue()
        self._poll_job = self.after(50, self._drain)
        self._temp_dirs = []
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())

    def new_temp_dir(self, prefix):
        """A temp folder this window (not just this tab) will remove when
        it closes. Shared with :class:`CuppDialog`, whose own wordlist
        needs to outlive that smaller dialog."""
        path = tempfile.mkdtemp(prefix=prefix)
        self._temp_dirs.append(path)
        return path

    def _post(self, func, *args):
        """Queue ``func(*args)`` to run on the Tk thread (thread-safe),
        the same contract :func:`ui_util.weak_notifier` expects."""
        self._queue.put((func, args))

    def _drain(self):
        try:
            while True:
                func, args = self._queue.get_nowait()
                func(*args)
        except queue.Empty:
            pass
        self._poll_job = self.after(50, self._drain)

    def _notifier(self, method):
        return weak_notifier(self._post, method)

    def _cleanup(self):
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        for path in self._temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        self._temp_dirs = []

    def _on_close(self):
        self._cleanup()
        self.destroy()


def _open_link(url):
    webbrowser.open(url)


def _link_button(parent, text, url):
    button = ttk.Button(parent, text=f"{text}  (opens in your browser)",
                        command=lambda: _open_link(url))
    return button


class ForgotPasswordDialog(_Base):
    """*title* names what is locked ("this backup", "this note"). *official*
    and *workaround* are lists of plain strings (one per paragraph/step);
    an item may instead be a ``(text, url)`` pair, shown as a link.
    *hash_factory* is called (off the Tk thread, the first time the
    Hashcat tab is opened) and must return a :class:`~ios_apps.recovery.RecoveryHash`
    or raise :class:`~ios_apps.recovery.RecoveryUnavailable`.
    *on_password_found* is called, on the Tk thread, with the password
    once the person chooses to use one hashcat found."""

    def __init__(self, parent, title, official, workaround, hash_factory,
                on_password_found):
        super().__init__(parent)
        self.title(f"Forgot the password to {title}?")
        self.geometry("620x520")
        self.minsize(560, 460)
        self._hash_factory = hash_factory
        self._on_password_found = on_password_found
        self._hash = None
        self._hash_error = None
        self._hashcat_path = rec.locate_hashcat()
        self._cupp_path = rec.locate_cupp()
        self._run = None
        self._wordlist_var = tk.StringVar()
        self._mask_var = tk.StringVar(value=MASK_PRESETS[0][1])
        self._rules_var = tk.StringVar()
        self._attack_var = tk.StringVar(value="wordlist")
        self._status_var = tk.StringVar(value="")
        self._show_var = tk.BooleanVar(value=False)
        self._found_var = tk.StringVar(value="")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=14, pady=(14, 8))
        notebook.add(self._build_official(notebook, official),
                     text="Official")
        notebook.add(self._build_workaround(notebook, workaround),
                     text="Workaround")
        notebook.add(self._build_hashcat(notebook), text="Hashcat")

        buttons = ttk.Frame(self, padding=(14, 0, 14, 14))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self._on_close).pack(
            side="right")

    # -- Official / Workaround: plain, static advice -----------

    def _build_paragraphs(self, parent, items):
        body = ttk.Frame(parent, padding=14)
        body.pack(fill="both", expand=True)
        for item in items:
            text, url = item if isinstance(item, tuple) else (item, None)
            ttk.Label(body, text=text, wraplength=560,
                     justify="left").pack(anchor="w", pady=(0, 8))
            if url:
                _link_button(body, "Open this", url).pack(
                    anchor="w", pady=(0, 8))
        return body

    def _build_official(self, notebook, items):
        return self._build_paragraphs(notebook, items)

    def _build_workaround(self, notebook, items):
        return self._build_paragraphs(notebook, items)

    # -- Hashcat -------------------------------------------------

    def _build_hashcat(self, notebook):
        body = ttk.Frame(notebook, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=(
            "This only works on a password that is short, or that you can "
            "narrow down — a strong, random password cannot be found this "
            "way in any useful time. hashcat and CUPP are separate, free "
            "programs you install yourself; this program never downloads "
            "or bundles either one."), wraplength=560, justify="left",
            style="Subtitle.TLabel").pack(anchor="w", pady=(0, 10))

        self._tool_frame = ttk.Frame(body)
        self._tool_frame.pack(fill="x")
        self._refresh_tool_status()

        self._run_frame = ttk.Frame(body)
        if self._hashcat_path:
            self._build_run_controls(self._run_frame)
        self._run_frame.pack(fill="both", expand=True, pady=(10, 0))
        return body

    def _refresh_tool_status(self):
        for child in self._tool_frame.winfo_children():
            child.destroy()
        if self._hashcat_path:
            version = rec.tool_version(self._hashcat_path) or "found"
            ttk.Label(self._tool_frame,
                     text=f"hashcat: {version}").pack(anchor="w")
        else:
            row = ttk.Frame(self._tool_frame)
            row.pack(fill="x")
            ttk.Label(row, text="hashcat was not found on this "
                      "computer.").pack(side="left")
            ttk.Button(row, text="Locate it...",
                      command=self._locate_hashcat).pack(side="left",
                                                          padx=(8, 0))
            _link_button(self._tool_frame, "Get hashcat",
                        "https://hashcat.net/hashcat/").pack(
                anchor="w", pady=(4, 0))

    def _locate_hashcat(self):
        path = filedialog.askopenfilename(title="Locate hashcat")
        if not path:
            return
        found = rec.locate_hashcat(explicit=path)
        if not found:
            messagebox.showerror("Locate hashcat",
                                 "That file could not be found.")
            return
        self._hashcat_path = found
        self._refresh_tool_status()
        for child in self._run_frame.winfo_children():
            child.destroy()
        self._build_run_controls(self._run_frame)

    def _build_run_controls(self, parent):
        ttk.Label(parent, text="What to try:").pack(anchor="w")

        wl_row = ttk.Frame(parent)
        wl_row.pack(fill="x", pady=(4, 0))
        ttk.Radiobutton(wl_row, text="A wordlist", variable=self._attack_var,
                        value="wordlist").pack(side="left")
        self._wl_entry = ttk.Entry(wl_row, textvariable=self._wordlist_var,
                                   width=34)
        self._wl_entry.pack(side="left", padx=(8, 4))
        ttk.Button(wl_row, text="Browse...",
                  command=self._browse_wordlist).pack(side="left")
        ttk.Button(wl_row, text="Build one with CUPP...",
                  command=self._open_cupp).pack(side="left", padx=(8, 0))

        rules_row = ttk.Frame(parent)
        rules_row.pack(fill="x", pady=(4, 0), padx=(20, 0))
        ttk.Label(rules_row, text="Rules file (optional):").pack(side="left")
        ttk.Entry(rules_row, textvariable=self._rules_var, width=30).pack(
            side="left", padx=(8, 4))
        ttk.Button(rules_row, text="Browse...",
                  command=self._browse_rules).pack(side="left")

        mask_row = ttk.Frame(parent)
        mask_row.pack(fill="x", pady=(8, 0))
        ttk.Radiobutton(mask_row, text="A pattern (a short PIN-like "
                        "password)", variable=self._attack_var,
                        value="mask").pack(side="left")
        mask_values = [text for text, _mask in MASK_PRESETS]
        self._mask_combo = ttk.Combobox(
            mask_row, textvariable=self._mask_var, width=26,
            values=[mask for _text, mask in MASK_PRESETS])
        preset_var = tk.StringVar(value=mask_values[0])
        preset = ttk.Combobox(mask_row, textvariable=preset_var,
                              values=mask_values, width=24, state="readonly")
        preset.pack(side="left", padx=(8, 4))
        preset.bind("<<ComboboxSelected>>", lambda e: self._mask_var.set(
            dict(MASK_PRESETS)[preset_var.get()]))
        self._mask_combo.pack(side="left", padx=(4, 0))

        start_row = ttk.Frame(parent)
        start_row.pack(fill="x", pady=(12, 0))
        self._start_button = ttk.Button(start_row, text="Start",
                                        command=self._start)
        self._start_button.pack(side="left")
        self._stop_button = ttk.Button(start_row, text="Stop",
                                       command=self._stop, state="disabled")
        self._stop_button.pack(side="left", padx=(8, 0))

        ttk.Label(parent, textvariable=self._status_var, wraplength=560,
                 justify="left").pack(anchor="w", pady=(8, 0))

        self._log = tk.Text(parent, height=8, width=70, state="disabled")
        self._log.pack(fill="both", expand=True, pady=(6, 0))

        self._found_row = ttk.Frame(parent)
        found_entry = ttk.Entry(self._found_row, textvariable=self._found_var,
                                show="•", width=30, state="readonly")
        found_entry.pack(side="left")
        ttk.Checkbutton(self._found_row, text="Show", variable=self._show_var,
                        command=lambda: found_entry.configure(
                            show="" if self._show_var.get() else "•")
                        ).pack(side="left", padx=(6, 0))
        ttk.Button(self._found_row, text="Use this password",
                  command=self._use_found).pack(side="left", padx=(10, 0))

    # -- the hash itself ------------------------------------------

    def _ensure_hash(self):
        if self._hash is not None or self._hash_error is not None:
            return
        try:
            self._hash = self._hash_factory()
        except rec.RecoveryUnavailable as exc:
            self._hash_error = str(exc)

    # -- wordlists and rules ---------------------------------------

    def _browse_wordlist(self):
        path = filedialog.askopenfilename(title="Choose a wordlist")
        if path:
            self._wordlist_var.set(path)
            self._attack_var.set("wordlist")

    def _browse_rules(self):
        path = filedialog.askopenfilename(title="Choose a rules file")
        if path:
            self._rules_var.set(path)

    def _open_cupp(self):
        CuppDialog(self, self._cupp_path, self._on_cupp_path_chosen,
                  self._on_wordlist_built)

    def _on_cupp_path_chosen(self, path):
        self._cupp_path = path

    def _on_wordlist_built(self, path):
        self._wordlist_var.set(path)
        self._attack_var.set("wordlist")

    # -- running hashcat ---------------------------------------------

    def _log_line(self, line):
        self._log.configure(state="normal")
        self._log.insert("end", line + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _start(self):
        self._ensure_hash()
        if self._hash_error:
            messagebox.showerror("Hashcat", self._hash_error)
            return
        attack = self._attack_var.get()
        wordlist = self._wordlist_var.get().strip()
        mask = self._mask_var.get().strip()
        rules = self._rules_var.get().strip() or None
        if attack == "wordlist" and not os.path.isfile(wordlist):
            messagebox.showerror("Hashcat", "Choose a wordlist file first.")
            return
        if attack == "mask" and not mask:
            messagebox.showerror("Hashcat", "Choose a pattern first.")
            return
        self._run = rec.HashcatRun(
            self._hashcat_path, self._hash,
            wordlist=wordlist if attack == "wordlist" else None,
            mask=mask if attack == "mask" else None,
            rules=rules if attack == "wordlist" else None,
            on_line=self._notifier(self._on_line),
            on_done=self._notifier(self._on_done))
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._found_var.set("")
        self._found_row.pack_forget()
        self._status_var.set("Running: " + " ".join(
            str(part) for part in self._run.command))
        self._start_button.configure(state="disabled")
        self._stop_button.configure(state="normal")
        self._run.start()

    def _stop(self):
        if self._run:
            self._run.stop()
            self._status_var.set("Stopping...")

    def _on_line(self, line):
        self._log_line(line)

    def _on_done(self, password, note):
        self._start_button.configure(state="normal")
        self._stop_button.configure(state="disabled")
        if password:
            self._status_var.set("Password found.")
            self._found_var.set(password)
            self._found_row.pack(fill="x", pady=(6, 0))
        elif note:
            self._status_var.set(note)
        else:
            self._status_var.set(
                "This did not find the password. Try a different "
                "wordlist, rules, or a pattern.")

    def _use_found(self):
        password = self._found_var.get()
        if password and self._on_password_found:
            self._on_password_found(password)
        self._on_close()

    def _on_close(self):
        if self._run:
            self._run.close()
            self._run = None
        super()._on_close()


class CuppDialog(_Base):
    """A short form, then CUPP's own interactive profiling run in the
    background. Nothing typed here is a secret: these are the kind of
    things CUPP turns into word guesses, not a password."""

    FIELDS = (
        ("first_name", "First name (needed)"),
        ("surname", "Surname"),
        ("nickname", "Nickname"),
        ("birthdate", "Birthdate (DDMMYYYY)"),
        ("partner_name", "Partner's name"),
        ("partner_nickname", "Partner's nickname"),
        ("partner_birthdate", "Partner's birthdate (DDMMYYYY)"),
        ("child_name", "Child's name"),
        ("child_nickname", "Child's nickname"),
        ("child_birthdate", "Child's birthdate (DDMMYYYY)"),
        ("pet_name", "Pet's name"),
        ("company", "Company name"),
    )

    def __init__(self, parent, cupp_path, on_path_chosen, on_wordlist_built):
        super().__init__(parent)
        self._owner = parent        # outlives this dialog; owns the cleanup
        self.title("Build a wordlist with CUPP")
        self.resizable(False, False)
        self._cupp_path = cupp_path
        self._on_path_chosen = on_path_chosen
        self._on_wordlist_built = on_wordlist_built
        self._vars = {field: tk.StringVar() for field, _label in self.FIELDS}
        self._extra_var = tk.StringVar()
        self._special_var = tk.BooleanVar()
        self._numbers_var = tk.BooleanVar()
        self._leet_var = tk.BooleanVar()
        self._status_var = tk.StringVar()

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)

        if not cupp_path:
            row = ttk.Frame(body)
            row.pack(fill="x", pady=(0, 10))
            ttk.Label(row, text="CUPP was not found on this "
                      "computer.").pack(side="left")
            ttk.Button(row, text="Locate it...",
                      command=self._locate).pack(side="left", padx=(8, 0))
            _link_button(body, "Get CUPP",
                        "https://github.com/Mebus/cupp").pack(
                anchor="w", pady=(0, 10))

        grid = ttk.Frame(body)
        grid.pack(fill="x")
        for row, (field, label) in enumerate(self.FIELDS):
            ttk.Label(grid, text=label + ":").grid(
                row=row, column=0, sticky="w", pady=2)
            ttk.Entry(grid, textvariable=self._vars[field], width=28).grid(
                row=row, column=1, sticky="w", padx=(8, 0), pady=2)

        words_row = ttk.Frame(body)
        words_row.pack(fill="x", pady=(8, 0))
        ttk.Label(words_row, text="Other words (comma separated):").pack(
            anchor="w")
        ttk.Entry(words_row, textvariable=self._extra_var, width=50).pack(
            fill="x", pady=(2, 0))

        checks = ttk.Frame(body)
        checks.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(checks, text="Add special characters",
                        variable=self._special_var).pack(side="left")
        ttk.Checkbutton(checks, text="Add numbers",
                        variable=self._numbers_var).pack(side="left",
                                                         padx=(10, 0))
        ttk.Checkbutton(checks, text="Leet substitutions (e -> 3...)",
                        variable=self._leet_var).pack(side="left",
                                                      padx=(10, 0))

        ttk.Label(body, textvariable=self._status_var, wraplength=440,
                 justify="left").pack(anchor="w", pady=(10, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        self._build_button = ttk.Button(buttons, text="Build",
                                        command=self._build,
                                        state="normal" if cupp_path
                                        else "disabled")
        self._build_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self._on_close).pack(
            side="right", padx=(0, 6))

    def _locate(self):
        path = filedialog.askopenfilename(title="Locate cupp.py")
        if not path:
            return
        found = rec.locate_cupp(explicit=path)
        if not found:
            messagebox.showerror("Locate CUPP",
                                 "That file could not be found.")
            return
        self._cupp_path = found
        self._on_path_chosen(found)
        self._build_button.configure(state="normal")

    def _build(self):
        profile = {field: var.get() for field, var in self._vars.items()}
        if not rec.cupp_answers_valid(profile):
            messagebox.showerror(
                "Build a wordlist",
                "A first name is needed, and every birthdate must be "
                "blank or exactly 8 digits (DDMMYYYY).")
            return
        self._build_button.configure(state="disabled")
        self._status_var.set("Running CUPP...")
        output = os.path.join(
            self._owner.new_temp_dir("ios-backup-explorer-cupp-"),
            "wordlist.txt")
        # Read every Tk variable here, on the Tk thread: the worker thread
        # below must touch no widget or variable of this window, the same
        # rule the rest of this program follows (see ui_util.post_when_done).
        cupp_path = self._cupp_path
        extra_words = self._extra_var.get()
        add_special_chars = self._special_var.get()
        add_numbers = self._numbers_var.get()
        use_leet = self._leet_var.get()

        def work():
            notify = self._notifier(self._on_built)
            try:
                rec.run_cupp(
                    cupp_path, profile, output, extra_words=extra_words,
                    add_special_chars=add_special_chars,
                    add_numbers=add_numbers, use_leet=use_leet)
            except rec.RecoveryUnavailable as exc:
                notify(None, str(exc))
                return
            notify(output, None)

        threading.Thread(target=work, daemon=True, name="cupp").start()

    def _on_built(self, path, error):
        self._build_button.configure(state="normal")
        if error:
            self._status_var.set(error)
            return
        self._on_wordlist_built(path)
        self._on_close()
