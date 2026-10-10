# Frequently asked questions

## Safety and privacy

**Is this safe to use?**
Yes. iOS Backup Explorer is 100% offline, open source, and makes no network
connections. Your password never leaves your machine. You can verify this by
reading the source, which is plain Python without a build step, and with the
steps in [SECURITY.md](../SECURITY.md) and the README's *Verify it yourself*.

**Can it crack or bypass my backup password?**
No. It needs the correct encryption password to decrypt the backup, and it
cannot guess, crack or bypass it. This is a feature: it means nobody else can
read your backup without the password either.

**What does it write to my computer?**
Only what you ask for (exports and extractions, in the folder you choose) and
private temporary working copies of the databases it shows, which it deletes
when you close the backup. Details are in [SECURITY.md](../SECURITY.md).

**Does it work with iCloud backups?**
No. It reads **local** backups made by iTunes, Finder or the Apple Devices
app. iCloud backups are stored on Apple's servers and cannot be reached by this
tool.

## Backups

**What iOS versions are supported?**
Encrypted backups from **iOS 13 and newer** (including iOS 17 and 18), which
covers the iPhone 6s and later. The app layouts it reads were seen on recent
versions; see [Where the data comes from](DATA_SOURCES.md#ios-versions).

**Does it work with unencrypted backups?**
Yes; they are detected and opened without a password, read-only. They must use
the `Manifest.db` layout (iTunes/Finder backups of iOS 10 and later); very old
`Manifest.mbdb` backups are not supported. Apple leaves some data out of
unencrypted backups (for example Health data and saved passwords), so you may
find less in them.

**Can it open a folder that was already decrypted and extracted?**
Yes: a folder of `HomeDomain`, `CameraRollDomain`, `AppDomain-...` folders with
no `Manifest.db` opens like a backup, read-only, with every tab working. The
dates shown for files are those of the extracted files, because extraction does
not keep the original backup's dates.

**I forgot my backup password. Can you help?**
It cannot be recovered or bypassed. Try your password manager; on macOS look in
Keychain Access for "iOS Backup". As a last resort you can
[reset the backup password](https://support.apple.com/en-us/102566) by resetting
the phone's settings (your data is kept, but you must make a new backup).

**Some files show warnings during extraction. Is that normal?**
Yes. Some files (especially app databases) can show size-mismatch warnings. It
usually means the file was being written when the backup was made; the
extracted data is still usable in most cases.

## What is shown

**Are my messages complete?**
The newest messages are often in a companion `-wal` file rather than the main
database. The program copies both together, so nothing recent is lost. Messages
you deleted before the backup was made are not in it. Text that iOS stores only
in its archived form is decoded; if some looks wrong or is missing, please
report it.

**Why is a note, photo, call or message missing?**
A backup holds what was on the phone when it was made. Notes locked with a
password are listed but cannot be shown. Photos that live only in iCloud
("Optimize iPhone Storage") are not on the phone. Unencrypted backups leave out
some data. And the apps' layouts change between iOS versions, so if something
that is in your backup does not show, please report it (without sending your
data).

**Why do my photos show as grey tiles?**
Picture previews need the optional Pillow package, and HEIC pictures also need
pillow-heif: `pip install Pillow pillow-heif`. Videos always show a play
symbol. The files themselves are never affected: you can still open, save,
export and extract them.

**Why does a tab not appear?**
A tab appears only when its data is in the backup. See
[Troubleshooting](TROUBLESHOOTING.md#a-tab-is-missing).

**Why are some Health kinds called "Type 123"?**
Apple does not publish the numbers the Health database uses for its kinds; the
program names those it can prove from the database. See
[Health data](HEALTH.md).

**Why does Screen Time show `com.example.app` instead of a name?**
The backup holds only the app's identifier; the name would have to come from
the App Store. Apple's own apps are named.

## Using it

**Can I use this on Linux?**
Yes. Install `python3-tk` (`sudo apt install python3-tk` on Debian/Ubuntu) and
follow the normal [installation](INSTALL.md). You will need to copy your backup
folder from a Windows or macOS computer first.

**Can I run it without the window?**
Not for the app tabs: they are part of the window. `python
ios_backup_explorer.py --version` prints the version without opening it. The
readers are plain modules with no window code (see
[Architecture](ARCHITECTURE.md)), so a script can import them.

**Where can I try it without a real backup?**
Make the invented demo backup: `python tools/make_demo_backup.py "C:\Demo\Demo
iPhone Backup"` and open that folder. See [SCREENSHOTS.md](SCREENSHOTS.md).

**How do I report a problem?**
See [Contributing](../CONTRIBUTING.md#reporting-a-problem). Never include your
password or your data.
