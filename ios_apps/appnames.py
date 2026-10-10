# SPDX-License-Identifier: AGPL-3.0-or-later
#
# iOS Backup Explorer — the names of apps
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

"""Readable names for the identifiers of Apple's own apps."""

APPLE_APPS = {
    "com.apple.mobilesafari": "Safari", "com.apple.MobileSMS": "Messages",
    "com.apple.mobilephone": "Phone", "com.apple.mobilemail": "Mail",
    "com.apple.camera": "Camera", "com.apple.mobileslideshow": "Photos",
    "com.apple.Maps": "Maps", "com.apple.mobilenotes": "Notes",
    "com.apple.reminders": "Reminders", "com.apple.mobilecal": "Calendar",
    "com.apple.Music": "Music", "com.apple.podcasts": "Podcasts",
    "com.apple.Health": "Health", "com.apple.Preferences": "Settings",
    "com.apple.AppStore": "App Store", "com.apple.facetime": "FaceTime",
    "com.apple.weather": "Weather", "com.apple.stocks": "Stocks",
    "com.apple.news": "News", "com.apple.iBooks": "Books",
    "com.apple.tv": "TV", "com.apple.Passbook": "Wallet",
    "com.apple.calculator": "Calculator", "com.apple.mobiletimer": "Clock",
    "com.apple.Fitness": "Fitness", "com.apple.findmy": "Find My",
    "com.apple.shortcuts": "Shortcuts", "com.apple.DocumentsApp": "Files",
    "com.apple.VoiceMemos": "Voice Memos", "com.apple.compass": "Compass",
    "com.apple.Translate": "Translate", "com.apple.Home": "Home",
}


def app_name(bundle):
    """A readable name for an app's identifier (Apple's own apps)."""
    return APPLE_APPS.get(bundle, bundle)
