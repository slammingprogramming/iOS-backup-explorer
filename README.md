<h1 align="center">iOS Backup Explorer</h1>

<p align="center">
  <strong>Your data. Your eyes only.</strong><br>
  A free, open-source GUI tool to decrypt, browse, and extract files from iPhone and iPad backups, encrypted or not.
</p>

<p align="center">
  <a href="#-installation"><img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue" alt="Platform"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0--or--later-blue" alt="License: AGPL-3.0-or-later"></a>
  <a href="#-security--privacy"><img src="https://img.shields.io/badge/network-100%25%20offline-brightgreen" alt="Offline"></a>
  <a href="#-security--privacy"><img src="https://img.shields.io/badge/tracking-none-brightgreen" alt="No Tracking"></a>
  <img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python">
</p>

<p align="center">
  <img src="assets/screenshot.png" alt="Screenshot of the original BackupLens 1.0.0 interface" width="800"><br>
  <sub>Screenshot of the original BackupLens 1.0.0 by Eyyup (Eric) Gunes; this fork's interface has since been renamed.</sub>
</p>

> **iOS Backup Explorer is a hard fork of [BackupLens](https://github.com/mrgunes/BackupLens)**
> by [Eyyup (Eric) Gunes](https://github.com/mrgunes), originally released under the MIT License.
> The original author's copyright is preserved in [LICENSE-MIT](LICENSE-MIT) and [NOTICE](NOTICE).
> This fork is licensed under [AGPL-3.0-or-later](LICENSE).

---

## Why iOS Backup Explorer?

You made an encrypted iPhone backup with iTunes, Finder, or the Apple Devices app. Now you need to get your photos, messages, or health data out of it. You search online and find tools that:

- Cost $30–$80 for a license
- Upload your data to unknown servers
- Are closed source — you have no idea what they do with your passwords
- Haven't been updated since 2019

**iOS Backup Explorer is different.**

| | iOS Backup Explorer | Paid alternatives |
|---|---|---|
| **Price** | Free forever | $30–$80 |
| **Open source** | Yes — read every line | No |
| **Network access** | None. Zero. Offline only. | Often phones home |
| **Your password** | Never stored, never sent | Who knows? |
| **Platform** | Windows, macOS, Linux | Usually one platform |

---

## Features

- **Decrypt encrypted backups** — Supports iOS 13+ encrypted local backups
- **Unencrypted backups too** — Detected automatically; no password needed
- **Browse your phone's apps the way the phone shows them** — A tab each for **Messages** (chat bubbles, tapbacks, attachments), **Notes** (formatting, checklists, pictures, folders), **Calls**, **Contacts**, **Photos** (a thumbnail grid with albums) and **Voice Memos**, with names from your address book and search everywhere
- **Export what you find in the format you need** — Text, Markdown, web pages, PDF, CSV spreadsheets, JSON, vCard (.vcf) for contacts, JPEG for HEIC photos, web galleries. **The original files can always be extracted untouched**, too
- **A real file manager** — Folders on the left, files on the right, with back / forward / up, a location bar you can type a path into, and file-type icons
- **Sort by anything** — Click Name, Kind, Size, Date Modified or Date Created (clicking again reverses it); names sort naturally (`IMG_2` before `IMG_10`), folders can stay on top, and folder sizes are the total of what is inside
- **Browse by category** — Camera Roll, Messages, Health, Apps, and more
- **Search across all files** — Instant, searches the folder you are in and everything below it
- **Right-click** a file or folder to extract it, copy its name or path, or see its properties
- **Extract individual files or bulk export** — Save to any folder
- **Extract the entire backup** — One click, straight from the backup index, with no limit on how many files
- **Mount a backup as a read-only drive or folder** (optional) — Browse it in your file manager; on Windows as `\\ios-backup\...` with no drive letter
- **Auto-detects backups** — Finds your backup folder automatically
- **Cross-platform** — Works on Windows, macOS, and Linux
- **Auditable** — Plain Python files, no build step; read them

---

## Installation

### Prerequisites

- **Python 3.8 or newer** — [Download Python](https://www.python.org/downloads/)
- **tkinter** — Included with Python on Windows and macOS. On Linux: `sudo apt install python3-tk`

### Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/slammingprogramming/iOS-backup-explorer.git
cd iOS-backup-explorer

# 2. Install dependencies (just one is required)
pip install -r requirements.txt

# Optional: picture previews, HEIC photos and PDF export (see "Optional extras")
# pip install -r requirements-optional.txt

# 3. Run iOS Backup Explorer
python ios_backup_explorer.py
```

That's it. No build step, no Docker, no config files.

---

## Usage

### 1. Find your backup

iOS Backup Explorer auto-detects your backup location. If it doesn't, here's where iTunes/Finder stores them:

| Platform | Default backup location |
|---|---|
| **Windows** | `%APPDATA%\Apple Computer\MobileSync\Backup\` (iTunes installer) or `%USERPROFILE%\Apple\MobileSync\Backup\` (Microsoft Store iTunes / Apple Devices app) |
| **macOS** | `~/Library/Application Support/MobileSync/Backup/` |
| **Linux** | Backups must be copied from a Windows/Mac machine |

### 2. Enter your password (encrypted backups only)

iOS Backup Explorer detects whether the backup is encrypted. If it is not, the password box is disabled and you can just click **Open Backup**.

For an encrypted backup, this is the **encryption password you set in iTunes, Finder, or the Apple Devices app**, NOT your Apple ID password.

**Forgot your password?**
- **macOS:** Open Keychain Access, search for `iOS Backup` — the password is stored there
- **Windows:** Check if you saved it in your password manager

### 3. Browse and extract

- Click a category, domain or folder on the left, or double-click a folder in the list, to open it. Use the arrow buttons (or `Alt+Left` / `Alt+Right`, `Backspace`) to go back, forward and up
- Click a column heading to sort. **Include subfolders** lists every file below the current folder in one flat list; **Folders first** keeps folders above files
- Use the search bar to find files in the current folder and below (several words must all match). `Ctrl+F` jumps to it
- Select files or folders and click **Extract Selected** (a folder extracts everything in it), or export what you see with **Extract All in View**. Very long lists are split into pages

### 4. Read your messages

If the backup contains Messages, a **Messages** tab appears next to **Files**.

- Conversations are listed newest first, with names taken from the backup's address book. An iMessage chat and an SMS chat with the same number are shown as one conversation, like on the phone
- Your messages are on the right in blue (green for SMS), theirs on the left in grey, with tapbacks, group events and day headings. Click an attachment to save it. Long conversations load a page at a time
- **Search messages** looks inside every conversation, including messages iOS 16 and later keep only in their archived form, and jumps to the match
- **Export this conversation / Export all** writes text files, a web page (with the attachments beside it, opens in any browser, no internet needed), a CSV spreadsheet, or JSON
- **Extract original files** copies the Messages database (with its recent-changes files) and the attachments exactly as the backup holds them, so you always have the raw data too

### 5. Notes

If the backup contains Notes, a **Notes** tab appears.

- Folders (and sub-folders, and *Recently Deleted*) on the left, with the number of notes in each; pinned notes first. Sort by date edited, date created or title
- A note looks like it does on the phone: title and headings, bullet, dashed, numbered and checklist items (checked items are struck through), bold, italic, underlined and struck-through text, links, and the pictures in it. Click a voice recording or another attachment to open it or save it
- **Search** looks in titles and in the text (and in hashtags and link titles)
- Notes locked with a password are listed, but their text is encrypted in the backup and cannot be shown
- **Export** one note, a folder or everything as **text**, **Markdown**, a **web page** (with the pictures; HEIC pictures are converted to JPEG when Pillow and pillow-heif are installed), **PDF**, **JSON** or a **spreadsheet**. Exports follow the Notes folders

### 6. Calls and Contacts

- **Calls** is the call history as a table: click a heading to sort, filter by missed, incoming, outgoing, phone or FaceTime, and search by name, number or place. Names come from the address book. Export what you see, or everything, as a spreadsheet, web page, text or JSON
- **Contacts** is a list (sorted by last or first name) with each person's card: numbers, emails, addresses, web pages, birthday, notes and more. Export as a **vCard (.vcf) file** that other address books import, a spreadsheet, a web page, text or JSON. Contact photos are not included

### 7. Photos and Voice Memos

- **Photos** shows the camera roll as a grid of thumbnails, made only for what is on screen, so a large library opens at once. The left side lists *All items*, *Photos*, *Videos*, *Favorites*, *Hidden*, *Recently Deleted* and your own albums, as the phone's library records them (without the library database, the DCIM folders are listed instead). Click to select, Ctrl-click and Shift-click for more, double-click to open a picture in your usual viewer
- **Export** copies the original files (named by what they are, with the date taken as their file date), converts them to **JPEG** so every program can open them, makes a **web gallery**, or lists them in a spreadsheet. **Extract original files** uses the normal extraction (with progress) and keeps the backup's own folders
- **Voice Memos** lists the recordings with title, date and length; **Play** opens one in your usual audio player. Export them as audio files named by date and title, a web page with a player for each, or a list. The audio is never converted; it is exactly what the phone recorded

### Optional extras

Everything above works with the one required package. These optional ones add more:

```bash
pip install -r requirements-optional.txt
```

- **Pillow** — picture previews (JPEG and others) and conversion to JPEG
- **pillow-heif** — the same for the HEIC pictures iPhones take
- **fpdf2** — PDF export of notes

Without them the app says what is missing and the originals can still be extracted or saved.

---

## Mounting a backup (optional)

Instead of extracting, you can **mount** the open backup as a read-only drive or folder and browse it with your normal file manager and programs. Click **Mount Backup**; click it again (now **Unmount Backup**) when you are done.

| Platform | What you get | What you need |
|---|---|---|
| **Windows** | A network-style path, `\\ios-backup\<backup name>`, with **no drive letter**. Type it into File Explorer's address bar | [WinFsp](https://winfsp.dev) |
| **macOS** | An empty folder you choose | [macFUSE](https://macfuse.github.io) or [FUSE-T](https://www.fuse-t.org) |
| **Linux** | An empty folder you choose | FUSE (e.g. `sudo apt install fuse3`) |

On every platform you also need the small Python package (Python 3.9 or newer):

```bash
pip install -r requirements-mount.txt
```

Files from an encrypted backup are decrypted into a private temporary folder the first time you open them, and that folder is deleted when you unmount. Files from an unencrypted backup are read straight from the backup folder, with nothing copied. While a backup is mounted, programs running as you can read its decrypted contents; see [SECURITY.md](SECURITY.md). Mounting adds no network access: the Windows path is served by WinFsp on your own computer.

Mounting was tested on Windows 10 with WinFsp. The macOS and Linux code paths follow the same design but have not been run on those systems yet, so please report problems.

---

## Security & Privacy

> **iPhone backups contain your most sensitive data — photos, messages, health records, passwords, financial apps, and more. You should be extremely careful about which tools you trust with this data.**

### Our security promises:

1. **100% Offline** — iOS Backup Explorer makes zero network connections. Disconnect your internet and it works identically. [Verify it yourself.](SECURITY.md)

2. **Your password is never stored** — It's held in memory only while the app runs. When you close iOS Backup Explorer, it's gone.

3. **No telemetry, no analytics, no tracking** — We don't know you exist. We don't want to.

4. **Fully auditable** — The app is plain Python (about 10,000 lines in all, with no build step): the app itself, the file browser, the file index, a reader, exporter and view for each app (Messages, Notes, Calls, Contacts, Photos, Voice Memos), and an optional module that is only used if you mount a backup. Read them. We encourage it.

5. **Open source dependencies** — Our only required dependency ([iphone_backup_decrypt](https://github.com/jsharkey13/iphone_backup_decrypt)) is also open source and MIT licensed.

For our full security policy, see [SECURITY.md](SECURITY.md).

---

## Where are my backups?

### Windows

1. Press `Win + R`, type `%APPDATA%\Apple Computer\MobileSync\Backup`, press Enter (or `%USERPROFILE%\Apple\MobileSync\Backup` if you installed iTunes from the Microsoft Store)
2. Each subfolder (long alphanumeric name) is one device backup

### macOS

1. Open Finder, press `Cmd + Shift + G`
2. Paste: `~/Library/Application Support/MobileSync/Backup/`
3. Each subfolder is one device backup

### How to create an encrypted backup

1. Connect your iPhone/iPad to your computer
2. Open **iTunes** (Windows) or **Finder** (macOS)
3. Select your device
4. Check **"Encrypt local backup"**
5. Set a password — **remember this password!**
6. Click **Back Up Now**

---

## FAQ

<details>
<summary><strong>Is this safe to use?</strong></summary>

Yes. iOS Backup Explorer is 100% offline, open source, and makes no network connections. Your password never leaves your machine. You can verify all of this by reading the source code — it's a single file.
</details>

<details>
<summary><strong>Can iOS Backup Explorer crack/bypass my backup password?</strong></summary>

No. iOS Backup Explorer requires your correct encryption password to decrypt the backup. It cannot guess, crack, or bypass passwords. This is a feature, not a limitation — it means no one else can access your data without the password either.
</details>

<details>
<summary><strong>Are my messages complete?</strong></summary>

The newest messages on a phone are often not yet in the main database file but in a small companion "-wal" file. iOS Backup Explorer copies both together, so nothing recent is lost. Messages that you deleted on the phone before the backup was made are not in the backup. Message text that iOS stores only in its archived form is decoded; if some text looks wrong or is missing, please report it.
</details>

<details>
<summary><strong>Why is a note, photo or call missing?</strong></summary>

A backup holds what was on the phone when it was made. Notes locked with a password are listed but cannot be shown. Photos that live only in iCloud (when "Optimize iPhone Storage" is on) are not on the phone and so not in the backup. Unencrypted backups leave out some data that encrypted backups hold. The apps are read from the databases iOS uses; the layouts change between iOS versions, so if something that is in your backup does not show, please report it (without sending your data).
</details>

<details>
<summary><strong>Why do my photos show as grey tiles?</strong></summary>

Picture previews need the optional Pillow package, and HEIC pictures (what iPhones take by default) also need pillow-heif: `pip install Pillow pillow-heif`. Videos always show a play symbol. The files themselves are never affected; you can still open, save, export and extract them.
</details>

<details>
<summary><strong>Does this work with iCloud backups?</strong></summary>

No. iOS Backup Explorer only works with **local backups** (encrypted or not) created by iTunes, Finder, or the Apple Devices app. iCloud backups are stored on Apple's servers and cannot be accessed by this tool.
</details>

<details>
<summary><strong>Does it work with unencrypted backups?</strong></summary>

Yes. Unencrypted backups are detected automatically and opened without a password, read-only: the backup folder is never modified and no temporary copy of its index is made. They must use the `Manifest.db` layout (iTunes/Finder backups of iOS 10 and later); very old `Manifest.mbdb` backups are not supported.

Note that Apple leaves some data out of unencrypted backups (for example Health data and saved passwords), so you may find less in them than in an encrypted backup of the same device.
</details>

<details>
<summary><strong>What iOS versions are supported?</strong></summary>

iOS Backup Explorer supports encrypted backups from **iOS 13 and newer** (including iOS 17, 18). This covers iPhone 6s and later.
</details>

<details>
<summary><strong>I forgot my backup password. Can iOS Backup Explorer help?</strong></summary>

iOS Backup Explorer cannot recover forgotten passwords. However:
- **macOS users:** Check Keychain Access (search for "iOS Backup")
- **All users:** Try common passwords you may have used, or check your password manager
- As a last resort, you can [reset your backup password](https://support.apple.com/en-us/102566) by resetting all settings on your iPhone (this won't delete your data, but you'll need to create a new backup)
</details>

<details>
<summary><strong>Some files show warnings during extraction. Is that normal?</strong></summary>

Yes. Some files (especially app databases) may show size mismatch warnings. This is normal and usually means the file was being written to when the backup was created. The extracted data is still usable in most cases.
</details>

<details>
<summary><strong>Can I use this on Linux?</strong></summary>

Yes! Install `python3-tk` (`sudo apt install python3-tk` on Ubuntu/Debian) and follow the normal installation steps. You'll need to copy your backup folder from a Windows or Mac machine first.
</details>

---

## Contributing

Contributions are welcome! Whether it's bug fixes, new features, or documentation improvements.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

Please keep in mind:
- **Security is paramount.** Any PR that adds network access will be rejected.
- **Keep it simple.** The app should stay a few plain Python files that anyone can audit, with no build step.
- **Test on multiple platforms** if possible.
- **Run the tests** before opening a PR: `python -m unittest discover -s tests -t .` (they build a small encrypted backup and run it through the real decryption library).
- **Licensing and credit.** By contributing you agree your contribution is licensed under
  AGPL-3.0-or-later. Never remove or alter the original author's copyright notices
  ([LICENSE-MIT](LICENSE-MIT), [NOTICE](NOTICE), [AUTHORS](AUTHORS)); CI enforces this.

---

## Verify It Yourself

Don't trust us? Good. Here's how to confirm iOS Backup Explorer makes zero network connections:

```bash
# Option 1: Disconnect from the internet and run the app — it works identically.

# Option 2: Monitor network activity (macOS)
sudo lsof -i -P | grep python

# Option 3: Monitor network activity (Windows PowerShell)
Get-NetTCPConnection | Where-Object { $_.OwningProcess -eq (Get-Process python).Id }

# Option 4: Read the source — it's plain Python, about 10,000 lines in all.
```

---

## Acknowledgements

iOS Backup Explorer is a hard fork of [BackupLens](https://github.com/mrgunes/BackupLens), created by
[Eyyup (Eric) Gunes](https://github.com/mrgunes). The application design, user interface, documentation
and original code are his work, and this project would not exist without it. See [AUTHORS](AUTHORS)
and [NOTICE](NOTICE).

Several features here were inspired by open pull requests and issues on the original project, and are credited to the people behind them:

- [Nikhil-42](https://github.com/Nikhil-42), whose pull requests [#1](https://github.com/mrgunes/BackupLens/pull/1) and [#2](https://github.com/mrgunes/BackupLens/pull/2) proposed unencrypted-backup support, extracting the entire backup, and mounting a backup as a file system
- [jakubstetz](https://github.com/jakubstetz), whose pull request [#5](https://github.com/mrgunes/BackupLens/pull/5) found and fixed the same extraction, threading and macOS startup bugs
- [heebeejeebees](https://github.com/heebeejeebees), who asked for unencrypted-backup support in [issue #4](https://github.com/mrgunes/BackupLens/issues/4)

iOS Backup Explorer is built on top of the excellent [iphone_backup_decrypt](https://github.com/jsharkey13/iphone_backup_decrypt) library by James Sharkey. Thank you for making encrypted backup decryption accessible to everyone.

---

## License

iOS Backup Explorer is free software, licensed under the
[GNU Affero General Public License, version 3 or (at your option) any later version](LICENSE)
(AGPL-3.0-or-later). You may use, modify and share it, provided derivative works stay under the same license
and source is made available to their users.

The original BackupLens code is Copyright (c) 2026 Eyyup (Eric) Gunes and was released under the
[MIT License](LICENSE-MIT), whose notice is preserved and must remain with this software.
See [NOTICE](NOTICE) for details.

---

<p align="center">
  <strong>Originally created as BackupLens by <a href="https://github.com/mrgunes">Eyyup (Eric) Gunes</a></strong><br>
  <sub>Because your data should be yours — no subscriptions, no surveillance.</sub><br><br>
  Maintained by <a href="https://github.com/slammingprogramming">slammingprogramming</a> and contributors.<br>
  Please also star the <a href="https://github.com/mrgunes/BackupLens">original BackupLens</a> project.
</p>
