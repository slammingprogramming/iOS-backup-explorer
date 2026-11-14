# iOS versions

The goal of this project is to read backups of **every iOS version**. It cannot
be done from documentation: the databases inside a backup change between
versions, Apple does not document them, and a reader that is right for one
version can silently show nothing on another. So each version is checked
against a **real backup of that version**, and this page records which
versions have been, and what was found.

## What has been checked

| iOS | Device | Checked | Notes |
|---|---|---|---|
| 27.0.1 | iPhone14,7 | Every one of its 20 tabs run on the encrypted backup; the counts of Messages, Calls, Notes, Contacts, Calendar, Safari visits, Accounts, Voicemail, Apps and Photos compared with the raw tables; every keychain entry accounted for; every database the tabs read checked for completeness | No Screen Time activity or Podcasts data in the backup (see below); messages that belong to no conversation (see below) |
| 26.6 | iPhone14,7 | Every tab run on it; the counts of Photos, Voice Memos, Maps, Books, Reminders compared with the raw tables; Health in full (every table, the routes, the files of clinical documents) | |
| 16.7 | iPhone10,6 | Every tab run on it, Health in full | No Maps, Books, Photos or Voice Memos data in the backup |
| 17, 18 | | The first checks of Messages, Notes, Calls, Contacts, Safari, Calendar... | Before this page; not repeated |
| 12.4.8 | iPhone6,1 | Run again on a newer encrypted backup (14 tabs, all loaded, with the same counts as below). Earlier: every tab run on the encrypted backup and on a full copy; the counts of Messages (1,278), Calls, Contacts, Voicemail, Calendar, Reminders (67), Safari bookmarks, Voice Memos, Wi-Fi, Bluetooth, data usage, Accounts, Privacy (17), Apps and Keychain compared with the raw tables | No notes, history, tabs, photos, books or Screen Time data in the backup (see below) |
| 12.5.8 | iPad4,5 | Every tab run on the encrypted backup (15 tabs, all loaded); the counts of Messages, Contacts, Calls, Calendar (events and reminders), Photos, Voice Memos, Safari bookmarks, Privacy and Apps compared with the raw tables, and every keychain entry accounted for | An iPad: no Health, Voicemail, Recents, iCloud Drive or Screen Time tabs; no messages outside a conversation |
| 13, 14, 15, 19-25 | | **Not checked** | Backups of these are wanted, see below |

Newer and older versions of the same major number are expected to behave alike;
a tab that does not is exactly what this page is meant to find.

## What differs between versions

Found so far, and handled (each has a test that builds the older and the newer
layout):

- **Reminders**: iOS 26 keeps its databases in an app group
  (`AppDomainGroup-group.com.apple.reminders`) instead of in `HomeDomain`, and
  its lists in a table of their own (`ZREMCDBASELIST`) instead of among the
  other objects.
- **Data used by apps**: iOS 26 records only mobile data; the Wi-Fi columns are
  missing from the database. The table then shows no Wi-Fi columns.
- **Maps guides**: the table that joins guides to the places in them is named
  after the numbers of the two kinds it joins, which changed (`Z_5PLACES` to
  `Z_6PLACES`); it is found by its columns.
- **Health, workout routes**: iOS 26 names the columns of the table that links
  a workout to its route by direction (`destination_object_id` for the
  workout, `source_object_id` for the route, and a `deleted` flag) where iOS 16
  has `parent_id` and `child_id`. Before this was handled, no route was found
  on iOS 26 (16 of 179 workouts have one in the backups used).
- **Health, medications**: iOS 26 records the unit of a dose (`unit_string`,
  for example "tablet") and has a dose status that iOS 16 did not show.
- **Reminders, iOS 12 and earlier**: the reminders are in the Calendar
  database (`CalendarItem` of kind 3; the events are kind 2), and a reminder
  list is a calendar that can hold reminders. The **Calendar** tab shows them,
  as the tables *Reminders* and *Reminder lists* beside the events (only when
  the database holds some, so no empty tab appears). All 67 reminders of the
  iOS 12 backup were found.
- **Privacy, iOS 12 and earlier**: the permissions table has a column
  `allowed` (0 or 1) instead of `auth_value` and `auth_reason`. The 17
  permissions of the iOS 12 backup were not shown before this was handled.
- **Safari, iOS 12 and earlier**: the history is in Safari's own app folder
  (`AppDomain-com.apple.mobilesafari/Library/Safari/History.db`, the same
  tables) and the open tabs in `BrowserState.db`. The backup used has none of
  either, so this part is checked on generated data only.
- **Health, iOS 12 and earlier**: the database does not name its kinds. The
  names come from a table of the 172 kind numbers that the iOS 16.7 and 26.6
  databases both name, identically (see [Health data](HEALTH.md)); the five
  kinds of the iOS 12 backup (height, body mass, steps, walking distance,
  sleep) are in it. There is no daily summary of activity and no workouts in
  it.
- **Maps, iOS 12 and earlier**: the places are not in a database but in
  `Library/Maps/GeoBookmarks.plist`, which holds protocol buffer records in
  Apple's undocumented layout, and the history in `GeoHistory.mapsdata`. The
  Maps tab reads the places and the searches from the first, using fields
  identified on the iOS 12 backup: 5 saved places (2 places, 2 addresses, 1
  location), 3 searches; 17 entries were empty and 6 are of kinds not
  identified, so they are counted and not shown. The owner saw 2 favorites in
  Maps, so the table cannot be called favorites. The history file is not read.
- **Not in the iOS 12 backup used**: notes (the old `notes.sqlite` holds only
  its accounts), Photos (the library lists 36 albums and no pictures; the
  pictures were not backed up), Books, Podcasts and Screen Time.
- **Screen Time** and **Podcasts**: the iOS 26 backup had no Screen Time
  activity files and no Podcasts library, so those tabs show nothing there.
  The iOS 27.0.1 backup of the same phone is the same: it holds Screen Time's
  settings (three property lists) and the empty folder where the activity files
  would be, but no activity files, while the iOS 16.7 backup of another phone
  has them. Whether that is the version or the phone is still not known.

Found on iOS 27.0.1, and what was done about it:

- **Messages in no conversation**: 140 of the 54,226 messages of the database
  were listed by no chat (119 of them incoming texts, 139 with text). They are
  what a deleted conversation leaves, and no tab showed them. The Messages tab
  now ends with a conversation of them. Before this was handled, the tab's
  count was the number of messages that chats list, which is right but not all
  there is.
- **The decrypted file is not the size the manifest says** (the decryption
  library prints a note for each such file): of the 25 databases checked (all
  those the tabs read that are under 120 MB), 19 are smaller, some by a large
  part (a 25 MB `SafariTabs.db` is 580 KB), 5 are the same size and one is a
  little larger. Every one is **complete**: the page count in its header times
  the page size is exactly its size, and where SQLite's own check can run (not
  on the address book and the photo library, see below) it finds nothing wrong.
  Most likely the phone compacts a database as it backs it up, so that the
  manifest names the size of the live file. Nothing is missing that could be
  seen; the two largest databases (Health, Messages), also smaller than the
  manifest says, were not checked page by page.
- **The keychain, entry by entry**: 10,069 entries; 4,223 shown as passwords;
  1,217 deleted entries left by iCloud Keychain sync (not listed, and the tab
  says so); 306 certificates and keys opened; and 4,323 **locked to the phone
  they came from** (kept by iOS with a key that never leaves it, so no backup
  can open them: 3,939 generic passwords, nine web passwords, 361 keys and 14
  certificates). All 10,069 are accounted for.
- **Two databases this tool's SQLite cannot fully read**: the address book and
  the photo library each have a text-search table with a tokenizer of Apple's
  own (`ab_cf_tokenizer`, `_CoreDataTokenizer`) that Python's SQLite does not
  have. The program never touches those tables, so the tabs are not affected,
  but `tools/schema_report.py` used to give up on the whole file. It now lists
  every other table and says of these that their columns are not listed.

## Helping: reports that contain no personal data

Three tools print the shape of a backup and none of its contents, for pasting
into an issue. [How to help](HELPING.md) explains each, and the
[issue forms](https://github.com/slammingprogramming/iOS-backup-explorer/issues/new/choose)
ask for their output.

- `tools/compat_report.py` opens a backup in the real program (in a hidden
  window), visits every tab, and prints **only counts and the program's own
  messages**: the iOS version and kind of device, whether each tab loaded, how
  many rows each table has.
- `tools/schema_report.py` prints how the databases are built: tables, columns
  and row counts, and with `--sql` the `CREATE` statements. It is what shows
  why a tab is empty on a version.
- `tools/health_kinds_report.py` lists the Health data types that cannot be
  named.

```
python tools/compat_report.py "<backup folder>" --password-window --markdown
```

An encrypted backup asks for the password (`--password-window` in a small
window, `--password-prompt` on the terminal; it is not stored). For a folder
extracted by this program, say the version with `--ios 15.8`. The tools run on
Windows, macOS and Linux (`compat_report.py` needs a display).

A backup of an iOS version not in the table above is the most useful thing
anyone can bring; so is a version that is in the table but whose phone was used
differently (a different region, apps installed, a watch paired). **Do not post
the backup or anything from it.**
