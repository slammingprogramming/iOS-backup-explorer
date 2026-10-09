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
- The entire codebase is a few plain Python files — small enough to read in an afternoon.
- We encourage security researchers to audit the code.
- All dependencies are listed in `requirements.txt` and are open source themselves.

## Your Backup Password

The password you enter into iOS Backup Explorer is the **encryption password you set in iTunes or Finder** when you enabled encrypted backups. This is NOT your Apple ID password.

- If you don't remember your backup password, check your system keychain:
  - **macOS:** Keychain Access app, search for "iOS Backup"
  - **Windows:** The password is not stored in Windows Credential Manager by default
- iOS Backup Explorer cannot recover or bypass your password. This is by design — it means no one else can either.

## Unencrypted Backups

Unencrypted backups need no password, so none is asked for or used. They are opened read-only (the backup folder is never written to, and no temporary copy of its index is made), and extracted files are copied out as they are.

## Messages and Other App Views

To show an app such as Messages, Notes, Calls, Contacts, Photos or Voice Memos, iOS Backup Explorer makes a **working copy** of that app's database (and of the address book, to show names instead of numbers) in a private temporary folder. Pictures shown in a note, the thumbnails of the Photos tab and anything you open (a picture, a recording, an attachment) are copied there too, and the thumbnail copies are deleted again as soon as the thumbnail is made. For an encrypted backup all these copies are decrypted. The folder is deleted when you close the app or open another backup; if the app is killed it may be left behind in your system temp folder (named `ios-backup-explorer-apps-...`), so delete it if so.

Exports you create (text, Markdown, web page, PDF, vCard, CSV, JSON, converted pictures, audio files) are ordinary files in the folder you choose and contain your data in readable form. Protect or delete them yourself. The exported web pages load nothing from the internet and contain no scripts; links inside notes are only made clickable if they are web, mail or phone links. Only pictures, videos, audio and ordinary documents (PDF, text, Office files and the like) are opened from the app, in the program your computer uses for them, which is then outside this app's control. Anything else, such as a program, a script or a web page that someone attached to a note or message, is never started from here: use **Save as...** and open it yourself if you trust it.

## Mounting a Backup

Mounting (optional, see the README) makes the open backup's contents available as a read-only drive or folder. Be aware that:

- While it is mounted, **programs running as your user can read the backup's decrypted contents.** Unmount when you are done.
- Files from an *encrypted* backup are decrypted into a temporary folder created just for the mount (private to your account) the first time they are opened. It is deleted when you unmount or quit. If the app is killed it may be left in your system temp folder (named `ios-backup-explorer-...`); delete it if so. Files from an *unencrypted* backup are read from the backup folder and nothing is copied.
- On Windows the files are owned by the account that mounted them and are not readable by other accounts. The `\\ios-backup\...` path is served by WinFsp on this computer only; the app makes no network connections.
- The mount is read-only; nothing can change the backup through it.

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
- **Python 3.8+** — [python.org](https://python.org)
- **tkinter** — Included with Python (standard library GUI toolkit)
- **iphone_backup_decrypt** — [GitHub](https://github.com/jsharkey13/iphone_backup_decrypt) — MIT licensed, open source library for decrypting iOS backups

We monitor our dependencies for known vulnerabilities.
- **Pillow**, **pillow-heif** and **fpdf2** (optional) — only for picture previews, HEIC photos and PDF export. They are installed separately, run only on this computer, and are not needed for anything else.
- **mfusepy** (optional, only for mounting) — ISC licensed Python bindings for FUSE/WinFsp.
- **WinFsp / macFUSE / FUSE-T / libfuse** (optional, only for mounting) — third-party drivers you 
  install yourself; they are not bundled with this app.
