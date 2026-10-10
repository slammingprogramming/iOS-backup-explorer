# Glossary

**AAE file.** A small file next to a photo (`IMG_0002.AAE`) holding how it was
edited. Not interpreted.

**Account (Accounts tab).** An iCloud, Google, Exchange or other account set
up on the phone, or one of the services that sign in behind it.

**Activity cache / summary.** The phone's own daily totals of steps, active
energy, exercise and stand hours. See [Health data](HEALTH.md).

**AppDomain.** The domain holding one app's data, named by the app's
*bundle identifier*: `AppDomain-com.apple.mobilesafari`.

**Backup index.** The list of every file of the backup with its size and dates
(`Manifest.db`). The program loads it once when you open a backup so that
browsing and searching are instant.

**Badge.** The number on an app's icon.

**Bundle identifier.** An app's unique name in reverse-domain form
(`com.apple.MobileSMS`). Apple's apps are shown by name; other apps by this.

**Cocoa time / Apple time.** Seconds since 2001-01-01 UTC, which most iOS
databases use. See [How an iPhone backup is built](HOW_BACKUPS_WORK.md).

**Dataclass.** A kind of data an account can sync (Mail, Contacts, Calendars).

**Decrypt.** Turn an encrypted backup's files back into readable files, using
your backup password.

**Demo backup.** An invented backup made by `tools/make_demo_backup.py`, used
for the screenshots and for trying the program. See
[SCREENSHOTS.md](SCREENSHOTS.md).

**Domain.** The part of the phone a file belongs to (`HomeDomain`,
`CameraRollDomain`...). A file's backup path is `domain/relative path`.

**Export.** Write what a tab shows in a format other programs read. Compare
*extract*.

**Extract.** Copy files out of the backup exactly as they were on the phone,
decrypted. Compare *export*.

**Extracted backup.** A folder of domain folders with no `Manifest.db`, made by
other tools or by *Extract Entire Backup*. The program opens it read-only.

**File ID.** The 40-character name a file has inside the backup: the SHA-1 of
`domain-relativePath`.

**GPX.** A file format for routes and places that mapping programs read.

**iCalendar (.ics).** A file format for calendar events and to-dos.

**Key bag.** The set of keys in `Manifest.plist`, locked with a key made from
your password.

**Keyed archive.** A property list in which objects refer to each other by
number (`NSKeyedArchiver`). Several phone files use it.

**Mount.** Make the open backup appear as a read-only drive or folder in your
file manager.

**Property list (plist).** Apple's settings file format, XML or binary.

**Record tab / table tab.** A tab built on the shared table framework: tables
you can search and sort, with details, export and extraction. See
[The app tabs](apps/README.md).

**Tapback.** A quick reaction to a message (love, like, laugh...).

**TCC.** The system that records which apps may use the camera, photos and so
on. The **Privacy** tab reads its database.

**vCard (.vcf).** A file format for contacts.

**WAL (write-ahead log).** A companion file (`-wal`) of a SQLite database that
may hold its newest changes. The program always copies it with the database.

**Workspace.** The private temporary folder where the program keeps working
copies of the databases it is showing. Deleted when you close the backup. See
[SECURITY.md](../SECURITY.md).
