# Where the data comes from

Every tab reads one or a few files from the backup. This page lists them, so
that you can find the raw data, know what to extract, and judge how far to
trust each tab.

## How well each tab was checked

| Level | Meaning |
|---|---|
| **Real** | Written against, and checked on, a real backup (the iOS versions are named where they matter), and tested on generated data |
| **Layout only** | Written from the layout of the app's database (from a real backup's empty tables or from documentation), tested only on generated data; may miss what a real backup has |

Every tab is also run against each real backup that is at hand, with
`tools/compat_report.py`, and the counts the tab reports are compared with the
raw tables of the app's own database; [iOS versions](IOS_VERSIONS.md) says which
versions that was done for.

All tabs are covered by automated tests on generated data and by *mutation
checks* (the code is broken on purpose to confirm the tests notice); see
[Testing](TESTING.md).

## The sources

Paths are `Domain/path inside the domain`. See
[How an iPhone backup is built](HOW_BACKUPS_WORK.md) for what a domain is.

| Tab | Files read | Checked |
|---|---|---|
| **Messages** | `HomeDomain/Library/SMS/sms.db` (+ `-wal`, `-shm`); attachments in `MediaDomain/Library/SMS/Attachments/`; names from the address book | Real |
| **Notes** | `AppDomainGroup-group.com.apple.notes/NoteStore.sqlite` (+ journals) and `Accounts/<id>/Media/...` | Real (call recordings against iOS 18 data; the backup used had no notes, so formatting is covered by generated notes) |
| **Calls** | `HomeDomain/Library/CallHistoryDB/CallHistory.storedata` | Real |
| **Contacts** | `HomeDomain/Library/AddressBook/AddressBook.sqlitedb` | Real |
| **Photos** | `CameraRollDomain/Media/DCIM/*`, `CameraRollDomain/Media/PhotoData/Photos.sqlite` | Real on iOS 26 (all 40 of the files sampled matched a row of the library; albums were not compared one by one); the backup checked before had a library with no photos |
| **Voice Memos** | `AppDomainGroup-group.com.apple.VoiceMemos.shared/Recordings/` (`CloudRecordings.db`, `*.m4a`); older: `MediaDomain/Media/Recordings` | Real on iOS 26 (3 recordings, each matching its row in the library); the older location is layout only |
| **Safari** | `HomeDomain/Library/Safari/History.db`, `Bookmarks.db`, `SafariTabs.db`; iOS 12: history and tabs in `AppDomain-com.apple.mobilesafari/Library/Safari/History.db` and `BrowserState.db` | Real (bookmarks also on iOS 12; the iOS 12 history and tabs are layout only, the backup had none) |
| **Calendar** | `HomeDomain/Library/Calendar/Calendar.sqlitedb` | Real |
| **Voicemail** | `HomeDomain/Library/Voicemail/voicemail.db`, `<n>.amr`, `<n>.transcript` | Real |
| **Reminders** | `HomeDomain/Library/Reminders/Container_v1/Stores/Data-*.sqlite`; on iOS 26 `AppDomainGroup-group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite` | Real on iOS 16.7 and 26.6 (the lists of iOS 26 are kept in a different table, which is read too); on iOS 12 and earlier the reminders are in `HomeDomain/Library/Calendar/Calendar.sqlitedb` and are shown by the Calendar tab (67 of 67 on iOS 12.4) |
| **Network** | `SystemPreferencesDomain/com.apple.wifi.known-networks.plist` (older: `.../SystemConfiguration/com.apple.wifi.plist`); `SysSharedContainerDomain-systemgroup.com.apple.bluetooth/Library/Database/*.db` and `.../Preferences/com.apple.MobileBluetooth.devices.plist`; `WirelessDomain/Library/Databases/DataUsage.sqlite` | Real (iOS 26 counts only the mobile network: the Wi-Fi columns are missing there and the table shows none) |
| **Accounts** | `HomeDomain/Library/Accounts/Accounts3.sqlite`; `SystemPreferencesDomain/SystemConfiguration/preferences.plist`; `Info.plist`, `Manifest.plist`, `Status.plist` in the backup folder (when it has them) | Real (the device-information files were checked on generated ones) |
| **Keychain** | `KeychainDomain/keychain-backup.plist`, opened with the class keys of the backup's key bag (`Manifest.plist`) | Real (a real encrypted backup opened every item a backup can open; also tested on generated keychains) |
| **Screen Time** | `SysSharedContainerDomain-systemgroup.com.apple.DeviceActivity/Library/com.apple.DeviceActivity/Cloud/.../{Daily,Weekly,Hourly}/ActivitySegments/*.plist` | Real |
| **Health** | `HealthDomain/Health/healthdb_secure.sqlite`, `healthdb.sqlite`, `HealthDomain/MedicalID/MedicalIDData.archive`; the files of clinical documents in `HealthDomain/Health/Files/` (opened with keys from the database) | Real for the parts [listed](HEALTH.md), on iOS 16.7 and 26.6 |
| **Maps** | `AppDomainGroup-group.com.apple.Maps/Maps/MapsSync_0.0.1`; iOS 12 and earlier keep them in `AppDomain-com.apple.Maps/Library/Maps/GeoBookmarks.plist` (read, in part: see [Maps](apps/maps-podcasts-books.md#maps)) and `GeoHistory.mapsdata` (**not read yet**) | Real on iOS 26 for favorites, guides and history (the counts equal the database's own); the places inside guides are layout only, because the join table was empty in every backup |
| **Podcasts** | Podcasts app group `Documents/MTLibrary.sqlite` (older: `AppDomain-com.apple.podcasts/...`) | Layout (no backup so far has a Podcasts library) |
| **Books** | `AppDomainGroup-group.com.apple.iBooks/Documents/BKLibrary/*.sqlite`, `AEAnnotation/*.sqlite`, `BKJaliscoServerSource/*.sqlite`, `BCCloudData-BookDataStoreService/BCCloudCollections/BCCloudCollections` | Real on iOS 26 for collections (8 of 8); the book library, notes and purchases are layout only (the backups checked gave none) |
| **Recents** | `HomeDomain/Library/Recents/Recents` | Real |
| **Privacy** | `HomeDomain/Library/TCC/TCC.db`; `RootDomain/Library/Caches/locationd/clients.plist` | Real (also the older table of iOS 12: 17 of 17) |
| **Apps** | `HomeDomain/Library/FrontBoard/applicationState.db` | Real |
| **iCloud Drive** | `HomeDomain/Library/Application Support/FileProvider/backup/backup_manifest.db` | Real |

"Real" means the reader's counts and values were compared with the raw
database of a real backup; none of that data is in this repository.

## iOS versions

The goal is to read backups of **every iOS version**, over time. Today the
program is built for **iOS 13 and newer** (encrypted backups made by iTunes,
Finder or the Apple Devices app; unencrypted ones with the `Manifest.db` layout
of iOS 10 and newer). The app layouts it reads were first seen on iOS 17 and
18, then on **iOS 16.7 and 26.6**, which every tab was run against for this
page; some of the backups used in earlier checks were made on **iOS 12**, which
is older than the program claims to support, and more backups of each major
iOS version are being collected to test and build against.

The databases change between iOS versions. Each reader looks for the columns
and tables it needs and copes when one is missing, so a tab may show less on an
older or newer version rather than fail. Differences found so far (iOS 26
against iOS 16): the Reminders databases moved to an app group and the lists to
another table, the data-usage database no longer counts Wi-Fi, and the table
that says which places are in a Maps guide is numbered differently. Each is
read now, and tested.

[iOS versions](IOS_VERSIONS.md) lists what was checked on which version, and how
to produce a report that shows, without any of your data, which tabs a backup
fills. If something that is in your backup does not show, please report it.

## What backups leave out

- **iCloud-only data.** Photos with "Optimize iPhone Storage", messages with
  "Messages in iCloud" off-loaded, and anything else the phone did not keep
  locally is not in a local backup.
- **Unencrypted backups** leave out some data that encrypted ones hold, for
  example Health data and saved passwords, so some tabs show less (or do not
  appear).
- **Passwords and keys** are in the keychain, which opens only from an
  encrypted backup (or a folder this program extracted from one). Items marked
  "this device only" cannot be opened from any backup. See
  [Keychain](apps/keychain.md).
- **Locked notes** are stored encrypted inside the backup; they open with the
  note's own password (see [Notes](apps/notes.md#locked-notes)), and so do the
  files attached to them.
- **Third-party apps'** own data is in their `AppDomain-...` folders and is not
  interpreted; the file browser can extract it.
