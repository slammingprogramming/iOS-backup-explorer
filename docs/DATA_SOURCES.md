# Where the data comes from

Every tab reads one or a few files from the backup. This page lists them, so
that you can find the raw data, know what to extract, and judge how far to
trust each tab.

## How well each tab was checked

| Level | Meaning |
|---|---|
| **Real** | Written against, and checked on, a real backup, and tested on generated data |
| **Layout only** | Written from the layout of the app's database (from a real backup's empty tables or from documentation), tested only on generated data; may miss what a real backup has |

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
| **Photos** | `CameraRollDomain/Media/DCIM/*`, `CameraRollDomain/Media/PhotoData/Photos.sqlite` | Layout (the real backup used had a library with no photos) |
| **Voice Memos** | `AppDomainGroup-group.com.apple.VoiceMemos.shared/Recordings/` (`CloudRecordings.db`, `*.m4a`); older: `MediaDomain/Media/Recordings` | Layout |
| **Safari** | `HomeDomain/Library/Safari/History.db`, `Bookmarks.db`, `SafariTabs.db` | Real |
| **Calendar** | `HomeDomain/Library/Calendar/Calendar.sqlitedb` | Real |
| **Voicemail** | `HomeDomain/Library/Voicemail/voicemail.db`, `<n>.amr`, `<n>.transcript` | Real |
| **Reminders** | `HomeDomain/Library/Reminders/Container_v1/Stores/Data-*.sqlite` | Real (both table layouts are tested) |
| **Network** | `SystemPreferencesDomain/com.apple.wifi.known-networks.plist` (older: `.../SystemConfiguration/com.apple.wifi.plist`); `SysSharedContainerDomain-systemgroup.com.apple.bluetooth/Library/Database/*.db` and `.../Preferences/com.apple.MobileBluetooth.devices.plist`; `WirelessDomain/Library/Databases/DataUsage.sqlite` | Real |
| **Accounts** | `HomeDomain/Library/Accounts/Accounts3.sqlite`; `SystemPreferencesDomain/SystemConfiguration/preferences.plist`; `Info.plist`, `Manifest.plist`, `Status.plist` in the backup folder (when it has them) | Real (the device-information files were checked on generated ones) |
| **Screen Time** | `SysSharedContainerDomain-systemgroup.com.apple.DeviceActivity/Library/com.apple.DeviceActivity/Cloud/.../{Daily,Weekly,Hourly}/ActivitySegments/*.plist` | Real |
| **Health** | `HealthDomain/Health/healthdb_secure.sqlite`, `healthdb.sqlite`, `HealthDomain/MedicalID/MedicalIDData.archive` | Real for the parts [listed](HEALTH.md) |
| **Maps** | `AppDomainGroup-group.com.apple.Maps/Maps/MapsSync_0.0.1` | Layout |
| **Podcasts** | Podcasts app group `Documents/MTLibrary.sqlite` (older: `AppDomain-com.apple.podcasts/...`) | Layout |
| **Books** | `AppDomainGroup-group.com.apple.iBooks/Documents/BKLibrary/*.sqlite`, `AEAnnotation/*.sqlite`, `BKJaliscoServerSource/*.sqlite`, `BCCloudData-BookDataStoreService/BCCloudCollections/BCCloudCollections` | Layout |
| **Recents** | `HomeDomain/Library/Recents/Recents` | Real |
| **Privacy** | `HomeDomain/Library/TCC/TCC.db`; `RootDomain/Library/Caches/locationd/clients.plist` | Real |
| **Apps** | `HomeDomain/Library/FrontBoard/applicationState.db` | Real |
| **iCloud Drive** | `HomeDomain/Library/Application Support/FileProvider/backup/backup_manifest.db` | Real |

"Real" means the reader's counts and values were compared with the raw
database of a real backup; none of that data is in this repository.

## iOS versions

The program reads backups of **iOS 13 and newer** (encrypted backups made by
iTunes, Finder or the Apple Devices app); the app layouts it reads were seen on
recent versions (iOS 17 and 18). The databases change between iOS versions; each
reader looks for the columns it needs and copes when one is missing, so a tab
may show less on an older or newer version rather than fail. If something that
is in your backup does not show, please report it.

## What backups leave out

- **iCloud-only data.** Photos with "Optimize iPhone Storage", messages with
  "Messages in iCloud" off-loaded, and anything else the phone did not keep
  locally is not in a local backup.
- **Unencrypted backups** leave out some data that encrypted ones hold, for
  example Health data and saved passwords, so some tabs show less (or do not
  appear).
- **Passwords and keys** are in the keychain, which this program does not open.
- **Locked notes** are stored encrypted inside the backup and cannot be shown.
- **Third-party apps'** own data is in their `AppDomain-...` folders and is not
  interpreted; the file browser can extract it.
