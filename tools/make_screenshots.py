#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Takes the screenshots for the documentation (Windows only).

    python tools/make_demo_backup.py "C:\\Demo\\Demo iPhone Backup"
    python tools/make_screenshots.py "C:\\Demo\\Demo iPhone Backup" docs/images

It opens the *invented* demo backup in the real window and saves a picture
of the window (nothing else on the screen) for each tab and a few dialogs.
Two things keep the pictures safe to publish:

* only the demo backup is opened, and the list of backups found on the
  computer is switched off, so no real folder or name is ever shown;
* every picture is re-saved without any metadata (no text chunks, no
  resolution, no colour profile).

The folder of the demo backup is shown in the first pictures, so put it
somewhere that says nothing about you (``C:\\Demo`` is fine, your home
folder is not).
"""

import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

WIDTH, HEIGHT = 1280, 860


def grab(hwnd):
    """A picture (PIL image) of the window *hwnd*, whatever is on top of
    it, through the window's own painting."""
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen = user32.GetDC(0)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    gdi32.SelectObject(memory, bitmap)
    user32.PrintWindow(hwnd, memory, 2)           # PW_RENDERFULLCONTENT

    class Header(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                    ("height", wintypes.LONG), ("planes", wintypes.WORD),
                    ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                    ("image_size", wintypes.DWORD),
                    ("x", wintypes.LONG), ("y", wintypes.LONG),
                    ("used", wintypes.DWORD), ("important", wintypes.DWORD)]

    header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0,
                    0, 0)
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header),
                    0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(0, screen)
    return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA",
                            0, 1).convert("RGB")


def save_clean(image, path):
    """Save *image* as a PNG with nothing but the pixels in it."""
    from PIL import Image
    clean = Image.new("RGB", image.size)
    clean.putdata(list(image.convert("RGB").getdata()))
    clean.save(path, "PNG", optimize=True)


class Shooter:
    def __init__(self, backup, out):
        import tkinter as tk
        import ios_backup_explorer as app
        self.app = app
        self.backup, self.out = backup, out
        os.makedirs(out, exist_ok=True)
        app.BackupExplorer.BACKUP_PATHS = {}      # (no real backups shown)
        self.root = tk.Tk()
        self.explorer = app.BackupExplorer(self.root)
        self.root.geometry(f"{WIDTH}x{HEIGHT}+20+20")
        self.taken = []

    # ── helpers ──────────────────────────────────────────────

    def pump(self, seconds=0.5, until=None, limit=90):
        end = time.monotonic() + (limit if until else seconds)
        while time.monotonic() < end:
            self.root.update()
            if until is not None and until():
                break
            time.sleep(0.02)
        self.root.update()

    def shoot(self, name, window=None):
        self.pump(0.6)
        window = window or self.root
        hwnd = int(window.wm_frame(), 16)
        path = os.path.join(self.out, f"{name}.png")
        save_clean(grab(hwnd), path)
        self.taken.append(path)
        print("  ", name)

    def panel(self, title):
        ex = self.explorer
        for panel in ex._app_panels:
            if ex.notebook.tab(panel, "text") == title:
                return panel
        raise KeyError(title)

    def show(self, title):
        panel = self.panel(title)
        self.explorer.notebook.select(panel)
        self.pump(0.3)
        return panel

    def loaded(self, panel, what):
        self.pump(until=lambda: bool(getattr(panel, what, None)), limit=120)

    def pick(self, tree, index=0):
        """Select a row of *tree* the way a click would."""
        rows = tree.get_children()
        if not rows:
            return
        tree.selection_set(rows[index])
        tree.see(rows[index])
        tree.event_generate("<<TreeviewSelect>>")
        self.pump(0.6)

    def table(self, title, name, dataset=None, row=0, wait=0.6):
        """Show a table tab (optionally another of its tables, with row
        number *row* chosen so that its details show)."""
        panel = self.show(title)
        self.loaded(panel, "datasets")
        if dataset:
            panel.choose_dataset(dataset)
        self.pump(wait)
        if row is not None:
            self.pick(panel.tree, row)
        self.shoot(name)
        return panel

    # ── the pictures ─────────────────────────────────────────

    def before_opening(self):
        ex = self.explorer
        ex.path_var.set(self.backup)
        self.pump(1.5)
        self.shoot("01-open-backup")

    def encrypted(self, folder):
        ex = self.explorer
        ex.path_var.set(folder)
        ex.pass_var.set("example-password")
        self.pump(1.5)
        self.shoot("02-encrypted-backup")
        ex.pass_var.set("")

    def open_backup(self):
        ex = self.explorer
        ex.path_var.set(self.backup)
        ex._decrypt()
        self.pump(until=lambda: ex.panel.index is not None)
        self.pump(until=lambda: bool(ex._app_panels), limit=30)
        self.pump(1.0)

    def files(self):
        ex = self.explorer
        index = ex.panel.index
        ex.panel.navigate(index.get("HomeDomain"))
        self.pump(0.8)
        self.shoot("03-files")
        ex.panel.navigate(index.get("HomeDomain/Library"))
        self.pump(0.8)
        self.shoot("04-files-folder")
        # (back to what the window says when a backup has just been opened)
        ex.status_var.set(f"{index.file_count:,} files ready. Choose a "
                          "folder on the left, or use the search box.")

    def messages(self):
        panel = self.show("Messages")
        self.loaded(panel, "conversations")
        self.pump(0.5)
        self.pick(panel.conversation_tree, 1)      # (the one with a photo)
        self.pump(2.5)
        panel.chat_text.yview_moveto(0)
        self.pump(0.5)
        self.shoot("10-messages")
        panel.search_var.set("trail")
        self.pump(1.5)
        self.shoot("11-messages-search")
        panel.search_var.set("")
        self.pump(0.5)

    def notes(self):
        panel = self.show("Notes")
        self.loaded(panel, "notes")
        wanted = {"Lemon cake": "12-notes", "Packing list \u2013 Lisbon":
                  "13-notes-checklist"}
        for note in panel.notes:
            if note.title in wanted:
                panel.select_note(note)
                self.pump(2.5)
                self.shoot(wanted[note.title])

    def contacts(self):
        panel = self.show("Contacts")
        self.loaded(panel, "contacts")
        self.pump(0.5)
        self.pick(panel.tree, -1)                  # (a full card)
        self.shoot("15-contacts")

    def photos(self):
        panel = self.show("Photos")
        self.loaded(panel, "items")
        self.pump(5)
        self.shoot("16-photos")

    def calls(self):
        panel = self.show("Calls")
        self.loaded(panel, "calls")
        self.pump(0.6)
        self.shoot("14-calls")

    def voice_memos(self):
        panel = self.show("Voice Memos")
        self.loaded(panel, "memos")
        self.pick(panel.tree, 1)
        self.shoot("17-voice-memos")

    def find_dialog(self, widget):
        """The dialog window (it belongs to the tab that asked, not to the
        main window), or None."""
        from tkinter import Toplevel
        for child in widget.winfo_children():
            if isinstance(child, Toplevel):
                return child
            found = self.find_dialog(child)
            if found is not None:
                return found
        return None

    def export_dialog(self):
        panel = self.show("Calendar")
        self.loaded(panel, "datasets")
        attempts = []

        def capture():
            window = self.find_dialog(self.root)
            if window is None and len(attempts) < 40:
                attempts.append(1)
                self.root.after(250, capture)
                return
            if window is not None:
                window.folder_var.set(r"C:\Demo\Exports")
                window.update()
                self.shoot("40-export-dialog", window)
                window.destroy()      # (the question was only for show)

        self.root.after(800, capture)
        panel.export()                # (waits until the dialog is closed)

    def everything(self, encrypted_folder):
        print("Taking the screenshots:")
        self.before_opening()
        if encrypted_folder:
            self.encrypted(encrypted_folder)
        self.open_backup()
        self.files()
        self.messages()
        self.notes()
        self.calls()
        self.contacts()
        self.photos()
        self.voice_memos()
        self.table("Safari", "18-safari-history")
        self.table("Safari", "19-safari-bookmarks", "bookmarks")
        self.table("Calendar", "20-calendar", row=3)
        self.table("Voicemail", "21-voicemail")
        self.table("Reminders", "22-reminders", row=0)
        self.table("Network", "23-network-wifi")
        self.table("Network", "24-network-usage", "usage")
        self.table("Accounts", "25-accounts-device", "device", row=None)
        self.table("Accounts", "25b-accounts", "accounts", row=0)
        self.table("Screen Time", "26-screen-time-days")
        self.table("Screen Time", "27-screen-time-apps", "apps", row=None)
        self.table("Health", "28-health-medical-id", "medical_id", row=None)
        self.table("Health", "29-health-activity", "activity")
        self.table("Health", "30-health-workouts", "workouts", row=1)
        self.table("Health", "31-health-vitals", "measurements", row=None)
        self.table("Maps", "32-maps")
        self.table("Podcasts", "33-podcasts", "episodes")
        self.table("Books", "34-books", "books", row=0)
        self.table("Books", "34b-books-notes", "notes")
        self.table("Recents", "35-recents")
        self.table("Privacy", "36-privacy")
        self.table("Privacy", "37-privacy-location", "location",
                   row=None)
        self.table("Apps", "38-apps", row=None)
        self.table("iCloud Drive", "39-icloud-drive")
        self.export_dialog()
        self.pump(0.5)
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("backup", help="the demo backup folder")
    parser.add_argument("out", help="where to put the pictures")
    parser.add_argument("--encrypted", help="an encrypted demo backup, for "
                        "the picture of the password box")
    arguments = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("the screenshots are taken on Windows")
    shooter = Shooter(os.path.abspath(arguments.backup),
                      os.path.abspath(arguments.out))
    shooter.everything(arguments.encrypted and os.path.abspath(
        arguments.encrypted))
    print(f"Saved {len(shooter.taken)} pictures in {arguments.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
