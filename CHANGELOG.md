# Changelog

All notable changes to iOS Backup Explorer will be documented in this file.

iOS Backup Explorer is a hard fork of [BackupLens](https://github.com/mrgunes/BackupLens) by
Eyyup (Eric) Gunes. Entries below the fork point record the original project's history.

## [Unreleased]

### Changed
- Hard fork of BackupLens 1.0.0, renamed to **iOS Backup Explorer**
- Relicensed from MIT to **AGPL-3.0-or-later**; the original MIT notice is preserved in
  `LICENSE-MIT` and `NOTICE`, and the original author is credited in `AUTHORS`
- Renamed `backuplens.py` to `ios_backup_explorer.py` and the main class to `BackupExplorer`

### Fixed
- Dates before 1970 (such as the placeholder year birthdays use) made some views fail on Windows; they are now shown correctly
- Buttons that cannot be used now look disabled, the password box greys out for an unencrypted backup, and the buttons under the file list were squashed away on a short window
- An error raised inside the library's manifest cursor could keep the library object alive (through its traceback) until it was finalised on another thread, leaving the decrypted temporary `Manifest.db` behind. The backup is now cleaned up explicitly on the thread that owns it
- **Extracted files were the still-encrypted backup blobs** (unplayable videos, unreadable
  databases). Extraction passed `domain=` instead of `domain_like=` to `iphone_backup_decrypt`;
  the resulting `TypeError` was swallowed and the raw encrypted file was copied out instead.
  Files are now really decrypted, and a failure is reported instead of silently copying
  encrypted data
- `SQLite objects created in a thread can only be used in that same thread` when browsing a
  backup: every backup operation now runs on one dedicated worker thread
- Errors while loading files were replaced by `NameError: cannot access free variable 'e'`,
  hiding the real message
- File lists were silently cut off at 10,000 rows, and search only filtered those rows. The
  status bar now says when a list is truncated, and search queries the whole backup
- Backup passwords with leading or trailing spaces were rejected (the password was stripped)
- Extraction failed for names Windows cannot store (`? : *` ...) and for paths over 260
  characters, such as Notes attachments
- Auto-detect missed backups made by Microsoft Store iTunes / the Apple Devices app
  (`%USERPROFILE%\Apple\MobileSync\Backup`)
- Startup crash on macOS when the OS refuses to list `MobileSync/Backup`; the app now asks you
  to use Browse instead (also reported and fixed upstream in
  [mrgunes/BackupLens#5](https://github.com/mrgunes/BackupLens/pull/5))
- Wrong-password detection no longer matches any error that merely contains "key"
- Two domains differing only at a `_`/`%` could extract the wrong domain's file
- Zero-byte files failed to extract
- The decrypted temporary `Manifest.db` was never deleted; it is now removed on exit or when
  another backup is opened, and `SECURITY.md` documents it
- Extraction now shows progress and lists which files failed and why

### Added
- **A Voicemail tab.** Who called (with names from the address book), when, how long, and the words the phone wrote down; play or save the recording, or export the audio with the words beside it
- **A Reminders tab.** Every reminder from every account (list, due date, priority, flag, notes, sub-tasks, completed and deleted ones) and the lists; export as a to-do file (.ics) that task programs import
- **A Network tab.** The Wi-Fi networks the phone joined (security, when joined, the last place it was seen at), the Bluetooth devices it knows, and the data each app used over Wi-Fi and the mobile network
- **An Accounts tab.** The accounts set up on the phone (iCloud, calendars, Game Center and the services behind them) and what the backup says about the device: name, model, iOS version, serial number, when it was backed up
- Tabs whose data is spread over many files (one database for each account, one file for each recording) copy the files they find; export formats that copy files out of the backup (the voicemail audio) join the table formats
- **A Safari tab and a Calendar tab.** Safari: history, sites visited, bookmarks (with folders), the reading list and the open tabs, each a sortable, searchable table with details; bookmarks export as a file browsers import. Calendar: the events and calendars, with repeats and places, all-day events kept as dates, and birthdays without a year; export as an iCalendar (.ics) file or as a spreadsheet, web page, text or JSON
- **Backups that were already decrypted and extracted** (a folder of `HomeDomain`, `AppDomain-...` folders and so on, with no `Manifest.db`) open like any other backup, read-only. The index is made in memory from what is on disk, so every tab and extraction works, and symbolic links are never followed
- A shared table framework (`ios_apps/records*.py`) that new tabs use: columns, sorting, searching, a details pane, exports and extracting the originals, plus a reader for the archives iOS stores some values in (`keyed_archive.py`)
- **A Notes tab.** Folders, sub-folders and *Recently Deleted*; the formatting of a note (title and headings, bullet, dashed, numbered and checklist items, bold, italic, links) and the pictures in it; voice recordings and other attachments you can open or save; search; notes locked with a password are listed with an explanation. Export as text, Markdown, a web page, PDF (optional fpdf2), JSON or a spreadsheet, with the attachments, following the Notes folders; the originals can always be extracted
- Call recordings are kept by the phone as a movie file with a separate track for each side of the call. Choose when you export (and when you extract the originals) between the mixed audio, the original file with the separate tracks, or both; opening or saving a recording offers the same. The mixed `.m4a` is made from the tracks with ffmpeg when it is installed; the original is never changed
- Call recordings in Notes (iOS 18): the audio file, title, length and the words that were said are found, shown under the recording and included in exports and search. They are stored as a recording with no file of its own and a child entry that holds the audio, which was missed at first
- **A Calls tab and a Contacts tab.** The call history as a sortable, filterable, searchable table with names from the address book and missed calls marked; contacts with their full cards. Export calls as CSV, a web page, text or JSON, and contacts as a **vCard (.vcf) file**, CSV, a web page, text or JSON
- **A Photos tab and a Voice Memos tab.** The camera roll as a thumbnail grid made only for what is on screen (optional Pillow and pillow-heif; HEIC supported), with the library's albums, favourites, hidden and recently deleted items; recordings with title, date and length. Open, save, export as originals, JPEG, a web gallery or a list, or extract the originals with the normal extraction
- Optional packages in `requirements-optional.txt`: Pillow, pillow-heif, fpdf2
- **A Messages tab** (the first of the iOS-style app views). Conversations with contact names, chat bubbles (blue for iMessage, green for SMS), tapbacks, group events, attachments you can save, paging for long conversations, and a search that jumps to the match. iMessage and SMS chats with the same number are merged like in the Messages app. Text that newer iOS versions keep only in `attributedBody` is decoded, and the database's `-wal` file is copied with it so recent messages are not lost
- **Export Messages** to text (a file per conversation), a web page with the attachments beside it, a CSV spreadsheet or JSON, and **Extract original files** for the untouched database and attachments
- Tabs: the Files view and each app view are tabs. The connection box folds away once a backup is open
- **A file-manager style browser.** Folders on the left, a sortable list on the right, back / forward / up navigation, a typeable location bar, file-type icons, a context menu (extract, copy name, copy path, properties) and keyboard shortcuts. The whole backup is indexed once when it is opened, so browsing, sorting and searching are instant and no longer wait behind a running extraction
- **Sort by Name, Kind, Size, Date Modified, Date Created or Location**, ascending or descending. Names sort naturally, folders can be kept on top, a folder's size is the total of what is in it, and items with an unknown date always sort last. Creation dates are shown where iOS recorded them
- Folders can be extracted (everything inside them), "Include subfolders" shows a flat list, and long lists are paged instead of being cut off
- **Extract Entire Backup** button: writes every file in the backup into `domain/relativePath` folders straight from the manifest, so it is not limited by the file list's row cap (idea from [mrgunes/BackupLens#1](https://github.com/mrgunes/BackupLens/pull/1) by Nikhil-42)
- **Mount Backup** (optional): mount the open backup as a read-only drive or folder with FUSE. Linux and macOS mount on an empty folder; on Windows (WinFsp) the backup appears as a UNC path `\\ios-backup\<name>` with no drive letter. Encrypted files are decrypted into a private cache on first open and the cache is deleted on unmount; unencrypted files are served in place. Needs `pip install -r requirements-mount.txt`. Idea from [mrgunes/BackupLens#2](https://github.com/mrgunes/BackupLens/pull/2) by Nikhil-42; this is an independent implementation that also works on Windows, keeps all backup access on the single worker thread, reads in binary mode and does not rely on `os.O_ACCMODE` or `os.statvfs` (neither exists on Windows)
- **Unencrypted backups** can be opened, browsed and extracted without a password. The backup type is detected from `Manifest.plist`; the password box is disabled for unencrypted backups. They are opened read-only and `immutable`, so the backup folder is never modified (closes [mrgunes/BackupLens#4](https://github.com/mrgunes/BackupLens/issues/4); [#1](https://github.com/mrgunes/BackupLens/pull/1) takes a similar approach)
- Clear messages for folders that are not backups and for old `Manifest.mbdb` backups
- Test suite (`tests/`) that builds a real encrypted backup and runs it end to end, plus CI
- `NOTICE`, `AUTHORS`, `LICENSE-MIT`, SPDX license headers
- CI check that fails if the original author's attribution is removed

## [1.0.0 — BackupLens, original project] - 2026-04-03

### Added
- Initial release
- Decrypt encrypted iPhone/iPad backups (iOS 13+)
- Browse files by category (Camera Roll, Apps, Health, Messages, etc.)
- Search across all files
- Extract individual files or bulk export
- Auto-detect backup location on Windows and macOS
- Cross-platform support (Windows, macOS, Linux)
- Path traversal protection during extraction
- Warm, trustworthy GUI with platform-native fonts
