#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Fail if the original author's credit or licensing notices are removed.

iOS Backup Explorer is a hard fork of BackupLens by Eyyup (Eric) Gunes (MIT).
The MIT License requires his copyright and permission notice to stay with the
software, and this project's policy is that his credit must never be dropped.
Run from anywhere:  python tools/check_attribution.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AUTHOR = "Eyyup (Eric) Gunes"
UPSTREAM = "https://github.com/mrgunes/BackupLens"
# First commit of the original project; must remain reachable in history.
ORIGINAL_ROOT_COMMIT = "96ddcc4"

# file -> substrings that must be present
REQUIRED = {
    "LICENSE-MIT": [
        "MIT License",
        "Copyright (c) 2026 Eyyup (Eric) Gunes",
        "The above copyright notice and this permission notice shall be included in all",
    ],
    "LICENSE": [
        "GNU AFFERO GENERAL PUBLIC LICENSE",
        "Version 3, 19 November 2007",
    ],
    "NOTICE": [AUTHOR, UPSTREAM, "LICENSE-MIT", "AGPL-3.0-or-later",
               "Nikhil-42"],
    "AUTHORS": [AUTHOR, "@mrgunes", UPSTREAM, "Nikhil-42", "jakubstetz",
                "heebeejeebees"],
    "README.md": [AUTHOR, UPSTREAM, "LICENSE-MIT", "AGPL-3.0-or-later",
                  "Nikhil-42"],
    "file_index.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ui_util.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/common.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/context.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/dialogs.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/messages.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/messages_export.py": [
        "SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/messages_view.py": [
        "SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/registry.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/panel_base.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/export_util.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/audio_tools.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/imaging.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/notes.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/notes_export.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/notes_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/pdf_export.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/calls.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/calls_export.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/calls_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/contacts.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/contacts_export.py": [
        "SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/contacts_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/photos.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/photos_export.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/photos_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/voice_memos.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/voice_memos_export.py": [
        "SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/voice_memos_view.py": [
        "SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/keyed_archive.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/records.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/records_export.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/records_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/ics.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/safari.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/safari_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/calendar_events.py": [
        "SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/calendar_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/voicemail.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/voicemail_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/reminders.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/reminders_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/network.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/network_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/accounts.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "ios_apps/accounts_view.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "folder_backup.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "browser_panel.py": ["SPDX-License-Identifier: AGPL-3.0-or-later"],
    "backup_mount.py": [
        "SPDX-License-Identifier: AGPL-3.0-or-later",
        "Nikhil-42",
        "https://github.com/mrgunes/BackupLens/pull/2",
    ],
    "ios_backup_explorer.py": [
        "SPDX-License-Identifier: AGPL-3.0-or-later",
        AUTHOR,
        UPSTREAM,
        "LICENSE-MIT",
    ],
}


def read(rel):
    path = ROOT / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def check_files():
    problems = []
    for rel, needles in REQUIRED.items():
        text = read(rel)
        if text is None:
            problems.append(f"{rel}: file is missing")
            continue
        for needle in needles:
            if needle not in text:
                problems.append(f"{rel}: missing required text {needle!r}")
    return problems


def check_history():
    """Original commits must still exist (history must not be rewritten)."""
    if not (ROOT / ".git").exists():
        return []
    try:
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip() == "true"
        if shallow:
            return []  # cannot judge history in a shallow clone
        subprocess.run(
            ["git", "cat-file", "-e", f"{ORIGINAL_ROOT_COMMIT}^{{commit}}"],
            cwd=ROOT, check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return [f"git history: original commit {ORIGINAL_ROOT_COMMIT} "
                "is missing; history must not be rewritten"]
    return []


def main():
    problems = check_files() + check_history()
    if problems:
        print("Attribution check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Attribution check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
