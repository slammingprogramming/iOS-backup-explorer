# How an iPhone backup is built

Knowing how a backup is laid out explains most of what the program does, and
why some things look odd. This is a description of the format as the program
uses it, not a specification from Apple.

## The folder

A local backup is a folder named after the device (`00008030-001A2B3C4D5E6F78`)
that holds:

| File | What it is |
|---|---|
| `Manifest.plist` | A small property list. Says whether the backup is **encrypted**, and for an encrypted one holds the *key bag* (the keys, themselves locked with a key made from your password) |
| `Manifest.db` | A SQLite database: the **index** of the backup, one row for each file (see below). In an encrypted backup the database itself is encrypted |
| `Info.plist`, `Status.plist` | The device's name, model, iOS version, serial number, when the backup was made |
| Folders `00` to `ff`, with files inside | The files of the phone, stored under *meaningless names* (see below) |

## The index: `Manifest.db`

The `Files` table has a row for every file and folder on the phone that was
backed up:

| Column | Meaning |
|---|---|
| `fileID` | A 40-character name for the file in the backup (see below) |
| `domain` | Which part of the phone the file belongs to |
| `relativePath` | The path inside that domain |
| `flags` | 1 file, 2 folder (others exist and are ignored) |
| `file` | An archived record with the size, dates and, for an encrypted backup, the file's own *wrapped key* |

### Domains

A **domain** groups files by where they live on the phone:

- `HomeDomain`: the mobile user's home folder (`Library/SMS`, `Library/Safari`...)
- `CameraRollDomain`, `MediaDomain`: photos, videos, recordings, message attachments
- `AppDomain-<bundle id>`: an app's own data (`AppDomain-com.apple.mobilesafari`)
- `AppDomainGroup-<group id>`: data shared by an app and its extensions
  (Notes, Voice Memos, Health's group, Podcasts...)
- `AppDomainPlugin-...`: an app extension's data
- `SysContainerDomain-...`, `SysSharedContainerDomain-...`: system containers
  (Screen Time, Bluetooth, media)
- `HealthDomain`, `WirelessDomain`, `NetworkDomain`, `SystemPreferencesDomain`,
  `RootDomain`, `KeychainDomain`, `HomeKitDomain`, `ManagedPreferencesDomain`...

The file browser groups these into friendly categories (Apps, Camera Roll /
Photos, Health Data...).

### File IDs

A file is stored as `<first two characters of fileID>/<fileID>`, and the
`fileID` is the **SHA-1 hash of `domain-relativePath`**. That is why you cannot
find `sms.db` by looking at the backup folder: it is, for instance,
`3d/3d0d7e5fb2ce288813306e4d4636395e047a3d28`. The index is what maps names to
IDs.

## Encryption

In an encrypted backup:

1. Your password, with salt and iteration counts from the key bag, is turned
   into a key (PBKDF2, twice) that unlocks the key bag.
2. The key bag unlocks the **class keys**, one for each *protection class* a
   file can have.
3. A manifest key (from `Manifest.plist`) decrypts `Manifest.db`.
4. Each file has its own random key, stored *wrapped* by a class key in the
   file's record in `Manifest.db`. Unwrapping it lets the file (AES-CBC) be
   decrypted.

The program uses the open-source
[iphone_backup_decrypt](https://github.com/jsharkey13/iphone_backup_decrypt)
library for this. A wrong password fails at step 1 or 2; the program tells you
the password was wrong.

## Extracted backups

Some tools (and this program's **Extract Entire Backup**) write the decrypted
files out into `domain/relativePath` folders. Such a folder has *no* index, so
the program builds one in memory by walking the folders: it lists what is on
disk and gives each file the ID a real backup would, reading everything where
it is and never writing to the folder.

## The databases inside

Most of what the tabs show is read from SQLite databases and property lists
that the phone's apps keep. Their quirks are why a backup viewer is more than a
file lister.

### Dates

iOS counts time in several ways, and the program converts them all:

| Where | How time is counted |
|---|---|
| Most iOS databases (Calendar, Calls, Notes, Safari, Health...) | Seconds since **2001-01-01** UTC ("Cocoa" or "Apple" time) |
| Messages (`sms.db`) in newer iOS | **Nanoseconds** since 2001-01-01; older versions use seconds |
| Voicemail (`voicemail.db`), TCC, Recents | Seconds (or thousandths) since **1970-01-01** (Unix time) |
| Property lists | Real date values (UTC) |

All-day calendar events are stored as midnight UTC and must not be moved to
your time zone. Some dates use year 1604 for "no year" (a birthday without a
year), which some systems cannot represent; the program handles every year.

### Write-ahead logs

SQLite databases that are in use have companion files, `name.sqlite-wal` and
`name.sqlite-shm`. The **newest** changes may be only in the `-wal` file (the
newest messages often are). The program always copies a database together with
its `-wal` and `-shm` files so that nothing recent is lost.

### Archived values

Some text and settings are stored as **keyed archives** (`NSKeyedArchiver`
property lists, in which objects refer to each other by number), as protobuf
(notes), as an attributed string (message text since iOS 16 may be only in
`attributedBody`), or as compressed blobs. The program has small, dependency-free
decoders for these.

### Joined tables and numbers for names

Core Data databases (most of the phone's) name their tables `Z...` with
numeric entity codes, and may keep several kinds of row in one table told
apart by a number. Health goes further and names its data kinds with numbers
that are not published; see [Health data](HEALTH.md).

## What is *not* in a backup

Passwords and keys (the keychain is stored encrypted and is not opened here),
iCloud-only data, the apps themselves, and anything the phone did not keep
locally. See [Where the data comes from](DATA_SOURCES.md).
