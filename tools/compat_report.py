#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A compatibility report: which tabs a backup gives, and whether each loads.

    python tools/compat_report.py "<backup folder>" [--ios 16.7]
                                  [--password-prompt | --password-window]
                                  [--markdown]

It opens the backup in the real program (in a hidden window), visits every tab
and writes **only counts and the program's own messages**: no names, texts,
numbers, places or dates from the backup. The report is meant to be pasted into
an issue ("tab X loads nothing on iOS 14"), which is how support for each
iOS version is checked; see ``docs/IOS_VERSIONS.md``.

The iOS version is read from the backup's ``Info.plist`` when it has one; for an
extracted folder, say it with ``--ios``. An encrypted backup asks for its
password on the terminal (``--password-prompt``) or in a small window
(``--password-window``, for when there is no terminal to type in); the password
is used to open the backup and is not stored. An extracted folder that holds the
backup's key bag (a ``Manifest.plist``) needs the password too, for its
keychain.

Needs a display (the program is a window).
"""

import argparse
import getpass
import os
import plistlib
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# a state text that means the tab did not load what it should have
_PROBLEM_STARTS = ("Could not", "Search failed", "Error")
# a state text that is an answer, not a failure (the data is not in this kind
# of backup)
_ANSWERS = ("This folder was extracted without", "This backup is not "
            "encrypted", "The keychain stays closed")


class PasswordDialog:
    """A small window that asks for a password, with a box to show what is
    typed. ``ask()`` returns the text, or None if it was cancelled."""

    def __init__(self, root, message):
        import tkinter as tk
        from tkinter import ttk
        self.root = root
        self.value = None
        self.window = tk.Toplevel(root)
        self.window.title("iOS Backup Explorer: compatibility report")
        self.window.attributes("-topmost", True)
        self.window.resizable(False, False)
        frame = ttk.Frame(self.window, padding=14)
        frame.pack()
        ttk.Label(frame, text=message, wraplength=420,
                  justify="left").pack(anchor="w")
        self.var, shown = tk.StringVar(), tk.BooleanVar(value=False)
        self.entry = ttk.Entry(frame, textvariable=self.var, show="\u2022",
                               width=44)
        self.entry.pack(fill="x", pady=(10, 2))
        ttk.Checkbutton(
            frame, text="Show what I type (to check it)", variable=shown,
            command=lambda: self.entry.configure(
                show="" if shown.get() else "\u2022")).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="OK", command=self.ok).pack(side="right")
        ttk.Button(row, text="Cancel", command=self.cancel).pack(
            side="right", padx=6)
        self.window.bind("<Return>", lambda _event: self.ok())
        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.update_idletasks()
        self.window.lift()
        self.entry.focus_set()

    def ok(self):
        if self.var.get():
            self.value = self.var.get()
            self.window.destroy()

    def cancel(self):
        self.value = None
        self.window.destroy()

    def ask(self):
        self.root.wait_window(self.window)
        return self.value


def ask_password(message):
    """Ask for a password in a window; None if cancelled."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    try:
        return PasswordDialog(root, message).ask()
    finally:
        root.destroy()


def backup_facts(folder):
    """What the backup's own plists say (never personal details): the iOS
    version, the kind of device, and whether it is encrypted."""
    facts = {"ios": None, "device": None, "encrypted": None}
    for name in ("Info.plist", "Manifest.plist"):
        try:
            with open(os.path.join(folder, name), "rb") as handle:
                data = plistlib.load(handle)
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        if not isinstance(data, dict):
            continue
        facts["ios"] = facts["ios"] or data.get("Product Version")
        facts["device"] = facts["device"] or data.get("Product Type")
        if "IsEncrypted" in data:
            facts["encrypted"] = bool(data["IsEncrypted"])
    return facts


def dataset_counts(panel):
    datasets = getattr(panel, "datasets", None)
    if isinstance(datasets, dict):
        return {key: len(table.rows) for key, table in datasets.items()}
    return {}


def run(folder, password=None, ios=None, patience=90, say=print):
    """Open *folder* and visit every tab. Returns the report as a dict."""
    import tkinter as tk
    import ios_backup_explorer as app
    from unittest import mock

    root = tk.Tk()
    root.withdraw()
    started = time.monotonic()
    errors = []                      # what the window would have shown
    with mock.patch.object(app.BackupExplorer, "BACKUP_PATHS", {}), \
            mock.patch.object(app.messagebox, "showerror",
                              side_effect=lambda *a, **k: errors.append(a)), \
            mock.patch.object(app.messagebox, "showinfo"), \
            mock.patch.object(app.messagebox, "showwarning"):
        explorer = app.BackupExplorer(root)

        def pump(seconds=0.2, until=None, limit=patience):
            end = time.monotonic() + (limit if until else seconds)
            while time.monotonic() < end:
                root.update()
                if until is not None and until():
                    return True
                time.sleep(0.02)
            root.update()
            return False

        facts = backup_facts(folder)
        try:
            kind = app.detect_backup(folder)
        except app.BackupFormatError as error:
            root.destroy()
            return {"opened": False, "reason": str(error)}
        if kind == app.ENCRYPTED and not password:
            root.destroy()
            return {"opened": False, "reason": "the backup is encrypted: "
                    "use --password-prompt or --password-window"}
        if kind != app.ENCRYPTED and facts["encrypted"] and not password \
                and os.path.isfile(os.path.join(folder, "Manifest.plist")):
            # an extracted folder with the key bag: the keychain tab would
            # wait for the password, in a window nobody can see
            root.destroy()
            return {"opened": False, "reason": "this folder holds the "
                    "backup's key bag (Manifest.plist), which needs the "
                    "backup password: use --password-prompt or "
                    "--password-window"}
        explorer.path_var.set(folder)
        if password:
            explorer.pass_var.set(password)
        explorer._decrypt()
        # opened, or the window complained (a wrong password, say)
        pump(until=lambda: explorer.panel.index is not None or errors,
             limit=1800)
        if explorer.panel.index is None:
            reason = " ".join(str(x) for x in (errors[0][1:] if errors
                                               else ())) \
                or explorer.status_var.get()
            root.destroy()
            return {"opened": False, "reason": reason}
        pump(until=lambda: bool(explorer._app_panels), limit=120)
        pump(1.0)
        report = {
            "opened": True, "ios": ios or facts["ios"] or "unknown",
            "device": facts["device"] or "unknown",
            "encrypted": facts["encrypted"],
            "tabs": []}
        for panel in list(explorer._app_panels):
            title = explorer.notebook.tab(panel, "text")
            explorer.notebook.select(panel)
            pump(0.3)
            began = time.monotonic()

            def settled():
                text = panel.state_var.get()
                return panel._loaded and bool(text) \
                    and not text.startswith("Loading") \
                    and not text.startswith("Checking") \
                    and not text.startswith("Unlocking")

            finished = pump(until=settled, limit=patience)
            pump(0.5)
            text = panel.state_var.get()
            report["tabs"].append({
                "tab": title, "finished": finished,
                "state": text,
                "problem": (not finished or text.startswith(_PROBLEM_STARTS))
                and not text.startswith(_ANSWERS),
                "tables": dataset_counts(panel),
                "seconds": round(time.monotonic() - began, 1)})
            say(f"  {title}: {text}")
        report["seconds"] = round(time.monotonic() - started, 1)
        try:
            explorer.session.close()
            explorer.session._executor.shutdown(wait=True)
        except Exception:                              # (best effort)
            pass
        root.destroy()
    return report


def markdown(report):
    if not report.get("opened"):
        return f"The backup did not open: {report.get('reason', '')}\n"
    lines = [f"iOS {report['ios']} ({report['device']}), "
             f"{'encrypted' if report['encrypted'] else 'not encrypted'}"
             if report["encrypted"] is not None else
             f"iOS {report['ios']} ({report['device']})",
             "", "| Tab | Loaded | What it says | Tables (rows) |",
             "|---|---|---|---|"]
    for tab in report["tabs"]:
        tables = ", ".join(f"{k} {v:,}" for k, v in tab["tables"].items())
        lines.append(
            f"| {tab['tab']} | {'no' if tab['problem'] else 'yes'} | "
            f"{tab['state']} | {tables} |")
    lines.append("")
    lines.append(f"{len(report['tabs'])} tabs in {report['seconds']} s.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder")
    parser.add_argument("--ios", help="the iOS version, if the folder has no "
                        "Info.plist (an extracted backup)")
    parser.add_argument("--password-prompt", action="store_true",
                        help="ask for the password of an encrypted backup "
                        "on the terminal")
    parser.add_argument("--password-window", action="store_true",
                        help="ask for it in a small window instead")
    parser.add_argument("--markdown", action="store_true",
                        help="print a Markdown table")
    options = parser.parse_args(argv)
    password = None
    if options.password_prompt:
        password = getpass.getpass("Backup password: ")
    elif options.password_window:
        password = ask_password(
            "Enter the password of this backup. It is used only to open it, "
            "then dropped (never saved or printed).")
        if password is None:
            sys.stdout.write("The backup did not open: no password given.\n")
            return 1
    report = run(os.path.abspath(options.folder), password, options.ios)
    sys.stdout.write(markdown(report))
    return 0 if report.get("opened") else 1


if __name__ == "__main__":
    sys.exit(main())
