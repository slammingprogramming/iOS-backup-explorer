# Security Policy

> iOS Backup Explorer is a hard fork of [BackupLens](https://github.com/mrgunes/BackupLens) by
> Eyyup (Eric) Gunes. This policy applies to this fork; see [NOTICE](NOTICE) for attribution.

## Our Commitment

iOS Backup Explorer is designed from the ground up with your privacy and security as the top priority. We understand that iPhone backups contain some of the most sensitive data on your devices — photos, messages, health data, passwords, and more.

## How iOS Backup Explorer Protects You

### 100% Offline
- iOS Backup Explorer makes **zero network connections**. None. Ever.
- No HTTP requests, no DNS lookups, no telemetry, no analytics.
- You can verify this yourself: disconnect from the internet and the app works identically.
- You can also verify by reading every line of the source code — it's intentionally small and auditable.

### No Data Storage
- Your backup password is **never saved** to disk, logs, or any file.
- The password is discarded from the UI immediately after successful decryption and is not retained when you close the app.
- iOS Backup Explorer creates no config files, logs, or caches.
- While a backup is open, the decryption library keeps a **decrypted copy of `Manifest.db`** (the backup's file index: names, paths and wrapped per-file keys, not your file contents) in a temporary folder. It is deleted when you close the app or open a different backup. If the app is killed or crashes it may be left behind in your system temp folder, so delete stray `Manifest.db` copies there if that happens, and use full-disk encryption.
- Files you extract are written, **decrypted**, to the folder you choose. Protect or delete them yourself.

### No Tracking
- No usage analytics. No crash reporting. No fingerprinting.
- We don't know who you are, what you're extracting, or that you even use this tool.

### Open Source & Auditable
- The entire codebase is plain Python with no build step (about 17,000 lines in 70 files, tests excluded), organised so that each app's reader is a small file of its own. Read it.
- We encourage security researchers to audit the code.
- All dependencies are listed in `requirements.txt` and are open source themselves.

## Your Backup Password

The password you enter into iOS Backup Explorer is the **encryption password you set in iTunes or Finder** when you enabled encrypted backups. This is NOT your Apple ID password.

- If you don't remember your backup password, check your system keychain:
  - **macOS:** Keychain Access app, search for "iOS Backup"
  - **Windows:** The password is not stored in Windows Credential Manager by default
- iOS Backup Explorer cannot recover or bypass your password. This is by design — it means no one else can either.

## Passwords of Locked Notes

A note locked with a password in the Notes app is opened with that password, which you type into the program when you click the note, use *Unlock notes...* or export. **Passwords are kept in memory only**, in the program that has the backup open: they are never written to a file, a log or the working copies, and they are dropped with *Forget passwords*, when another backup is opened and when the program closes. A wrong password never produces wrong text (the encryption is authenticated), and the program never guesses passwords. Opened notes are shown, searched and exported in readable form: exported files carry no password, so protect or delete them yourself.

## The Keychain Tab

The Keychain tab opens the saved passwords of an **encrypted** backup and shows them **in the clear**. Use it on a computer you trust. The backup password (asked for only when you open a folder this program extracted, which keeps the backup's key bag in `Manifest.plist`) unlocks the keys and is then dropped; **opened passwords exist only in memory**, never in a file, a log or the working copies (the working copy is the locked file as the backup has it). Exporting the Passwords, Certificates or Keys table asks you to confirm first, because the exported files hold your secrets with no protection. Items marked "this device only" cannot be opened by any program from a backup.

## Unencrypted and Extracted Backups

Unencrypted backups need no password, so none is asked for or used. They are opened read-only (the backup folder is never written to, and no temporary copy of its index is made), and extracted files are copied out as they are.

A folder that was already decrypted and extracted (domain folders such as `HomeDomain`, with no `Manifest.db`) is opened the same way: it is only read, the index is built in memory from what is on disk, symbolic links are never followed, and a path that would leave the folder is refused. Note that such a folder holds your data **decrypted**; protect it as you would the exports.

## Messages and Other App Views

To show an app such as Messages, Notes, Calls, Contacts, Photos, Voice Memos, Safari, Calendar, Voicemail, Reminders, Network, Accounts, Screen Time, Health, Maps, Podcasts, Books, Recents, Privacy, Apps or iCloud Drive, iOS Backup Explorer makes a **working copy** of that app's database or files (and of the address book, to show names instead of numbers) in a private temporary folder. Pictures shown in a note, the thumbnails of the Photos tab and anything you open (a picture, a recording, an attachment) are copied there too, and the thumbnail copies are deleted again as soon as the thumbnail is made. For an encrypted backup all these copies are decrypted. The Health database can be hundreds of megabytes, so its working copy can be too (and, for an encrypted backup, it is decrypted into that folder); make sure there is room, and that your disk is encrypted if the data is sensitive. The folder is deleted when you close the app or open another backup; if the app is killed it may be left behind in your system temp folder (named `ios-backup-explorer-apps-...`), so delete it if so.

Exports you create (text, Markdown, web page, PDF, vCard, iCalendar, GPX routes and places, bookmarks, CSV, JSON, converted pictures, audio files) are ordinary files in the folder you choose and contain your data in readable form. Protect or delete them yourself. The exported web pages load nothing from the internet and contain no scripts; links inside notes are only made clickable if they are web, mail or phone links. Only `http` and `https` addresses are opened in your browser (Safari history and bookmarks, links in notes are limited to web, mail and phone links). Only pictures, videos, audio and ordinary documents (PDF, text, Office files and the like) are opened from the app, in the program your computer uses for them, which is then outside this app's control. Anything else, such as a program, a script or a web page that someone attached to a note or message, is never started from here: use **Save as...** and open it yourself if you trust it.

## Mounting a Backup

Mounting (optional, see the README) makes the open backup's contents available as a read-only drive or folder. Be aware that:

- While it is mounted, **programs running as your user can read the backup's decrypted contents.** Unmount when you are done.
- Files from an *encrypted* backup are decrypted into a temporary folder created just for the mount (private to your account) the first time they are opened. It is deleted when you unmount or quit. If the app is killed it may be left in your system temp folder (named `ios-backup-explorer-...`); delete it if so. Files from an *unencrypted* backup are read from the backup folder and nothing is copied.
- On Windows the files are owned by the account that mounted them and are not readable by other accounts. The `\\ios-backup\...` path is served by WinFsp on this computer only; the app makes no network connections.
- The mount is read-only; nothing can change the backup through it.

## Code-scanning findings that are by design

GitHub's CodeQL scan reports a few findings in this project. They were looked at one by one and are not weaknesses; the reasons are written down here so that anyone reviewing them can check:

- **"Use of a broken or weak cryptographic algorithm" (AES in ECB mode)** in `ios_apps/notes_crypto.py` and `ios_apps/keychain_crypto.py`. The program does not choose to encrypt anything with ECB. It *reads* what Apple wrote. ECB appears only as the plain AES block operation inside two published constructions that Apple's formats use: the RFC 3394 key wrap (locked notes and keychain item keys) and AES-GCM, which is built from that block operation and is done here because the keychain's GCM has an empty nonce, which common libraries refuse. Each use handles exactly one 16-byte block; the tests check both against `pycryptodome` and the RFC 3394 test vector.
- **"Clear-text storage of sensitive information"** in `ios_apps/export_util.py` and `ios_apps/contacts_export.py`: exporting your own data to files you choose is what these functions are for, and is described above (exports are readable files; exporting passwords asks you to confirm first). The same finding in `tools/demo/__init__.py` and `tests/test_health.py` is the invented data of the demo backup and of the tests.

If a scan finds something that is *not* described here, please report it (see below).

## Supported Backup Sources

iOS Backup Explorer only reads **local iPhone/iPad backups** created by:
- iTunes (Windows)
- Finder (macOS 10.15+)
- Apple Devices app (Windows 11)

It does **not** access iCloud backups, which are stored on Apple's servers.

## Reporting Security Issues

If you discover a security vulnerability in iOS Backup Explorer, please report it responsibly:

1. **Do NOT open a public GitHub issue** for security vulnerabilities.
2. Use [GitHub's private security advisory feature](https://github.com/slammingprogramming/iOS-backup-explorer/security/advisories/new) to report the issue.
3. Include steps to reproduce, the potential impact, and any suggested fixes.

We will respond within 48 hours and work with you to address the issue before any public disclosure.

## Dependencies

iOS Backup Explorer depends on:
- **Python 3.9+** — [python.org](https://python.org)
- **tkinter** — Included with Python (standard library GUI toolkit)
- **iphone_backup_decrypt** — [GitHub](https://github.com/jsharkey13/iphone_backup_decrypt) — MIT licensed, open source library for decrypting iOS backups

We monitor our dependencies for known vulnerabilities.
- **Pillow**, **pillow-heif** and **fpdf2** (optional) — only for picture previews, HEIC photos and PDF export. They are installed separately, run only on this computer, and are not needed for anything else.
- **ffmpeg** (optional, a separate program you install yourself) — only to mix the tracks of a call recording into one audio file. It is started without a shell, on a working copy of the recording, only when you ask for the mixed audio; the original file is never changed.
- **mfusepy** (optional, only for mounting) — ISC licensed Python bindings for FUSE/WinFsp.
- **WinFsp / macFUSE / FUSE-T / libfuse** (optional, only for mounting) — third-party drivers you 
  install yourself; they are not bundled with this app.
