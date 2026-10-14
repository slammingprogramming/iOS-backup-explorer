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
| 26.6 | iPhone14,7 | Every tab run on it; the counts of Photos, Voice Memos, Maps, Books, Reminders compared with the raw tables; Health in full (every table, the routes, the files of clinical documents) | |
| 16.7 | iPhone10,6 | Every tab run on it, Health in full | No Maps, Books, Photos or Voice Memos data in the backup |
| 17, 18 | | The first checks of Messages, Notes, Calls, Contacts, Safari, Calendar... | Before this page; not repeated |
| 12.4.8 | iPhone6,1 | Every tab run on the encrypted backup and on a full copy; the counts of Messages (1,278), Calls, Contacts, Voicemail, Calendar, Reminders (67), Safari bookmarks, Voice Memos, Wi-Fi, Bluetooth, data usage, Accounts, Privacy (17), Apps and Keychain compared with the raw tables | No notes, history, tabs, photos, books or Screen Time data in the backup (see below) |
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
- **Maps, iOS 12 and earlier**: favorites and history are not in a database
  but in `Library/Maps/GeoBookmarks.plist` and `GeoHistory.mapsdata`, which
  hold nested records in Apple's own binary format. **Not read yet**: the
  layout was looked at (29 favorites stored) but its fields could not be
  named with certainty. The Maps tab shows nothing for such a backup.
- **Not in the iOS 12 backup used**: notes (the old `notes.sqlite` holds only
  its accounts), Photos (the library lists 36 albums and no pictures; the
  pictures were not backed up), Books, Podcasts and Screen Time.
- **Screen Time** and **Podcasts**: the iOS 26 backup had no Screen Time
  activity files and no Podcasts library, so those tabs show nothing there.
  Whether that is the version or the phone is not known yet.

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
