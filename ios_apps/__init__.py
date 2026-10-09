# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""iOS-style views of what is inside a backup: Messages, Notes, Calls, ...

Each app has a *reader* (plain Python, no GUI, works on a working copy of the
app's database), exporters (text, CSV, JSON, HTML...) and a panel for the
main window.
"""
