# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Talking to a device through libimobiledevice's tools. No device and no
real tool is needed: the output tested is what the tools' own source prints
(read from libimobiledevice 1.4), and the backup runs through a stand-in
program that draws its progress the same way."""

import os
import plistlib
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

import device_tools as dt

UDID = "00008030-001A2B3C4D5E6F78"
OLD_UDID = "a" * 40


def fake_which(present=dt.TOOL_NAMES):
    def which(name, path=None):
        return f"/usr/bin/{name}" if name in present else None
    return which


class Recorder:
    """A runner that answers from a table and remembers what it was asked."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, argv, env, timeout):
        self.calls.append((argv, env, timeout))
        key = (os.path.basename(argv[0]), *argv[1:])
        for pattern, reply in self.answers.items():
            if all(part in key for part in pattern):
                code, out, err = reply
                return code, out.encode(), err.encode()
        return 1, b"", b"ERROR: nothing was set up for this call\n"


def box(answers=None, present=dt.TOOL_NAMES):
    recorder = Recorder(answers)
    return dt.Toolbox(which=fake_which(present), runner=recorder), recorder


def plist_text(data):
    return plistlib.dumps(data).decode()


class FindingTheToolsTests(unittest.TestCase):
    def test_every_tool_is_found_on_the_path(self):
        toolbox, _ = box()
        self.assertEqual(toolbox.missing, [])
        self.assertTrue(toolbox.can_backup)

    def test_a_missing_tool_is_named_with_how_to_install_it(self):
        toolbox, _ = box(present=("idevice_id",))
        self.assertIn("idevicebackup2", toolbox.missing)
        self.assertFalse(toolbox.can_backup)
        with self.assertRaises(dt.DeviceError) as caught:
            toolbox.pairing(UDID)
        self.assertEqual(caught.exception.kind, dt.TOOL_MISSING)
        self.assertIn("apt install libimobiledevice-utils",
                      str(caught.exception))

    def test_a_folder_chosen_by_the_person_comes_first(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "idevicebackup2.exe")
            open(path, "w").close()
            toolbox = dt.Toolbox(folder=folder, which=fake_which(()))
            self.assertEqual(toolbox.paths["idevicebackup2"], path)
            self.assertIsNone(toolbox.paths["ideviceinfo"])

    def test_nothing_is_ever_run_through_a_shell(self):
        toolbox, recorder = box({("idevice_id", "-l"): (0, UDID + "\n", "")})
        toolbox.devices()
        argv = recorder.calls[0][0]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[1:], ["-l"])


class ListingDevicesTests(unittest.TestCase):
    def test_the_udids_are_read(self):
        toolbox, _ = box({("idevice_id", "-l"):
                          (0, f"{UDID}\n{OLD_UDID}\n", "")})
        self.assertEqual(toolbox.devices(), [UDID, OLD_UDID])

    def test_the_connection_label_of_newer_tools_is_ignored(self):
        toolbox, _ = box({("idevice_id", "-l"): (0, f"{UDID} (USB)\n", "")})
        self.assertEqual(toolbox.devices(), [UDID])

    def test_no_device_is_an_empty_list(self):
        toolbox, _ = box({("idevice_id", "-l"): (0, "", "")})
        self.assertEqual(toolbox.devices(), [])

    def test_a_stopped_usbmuxd_says_what_to_check(self):
        toolbox, _ = box({("idevice_id", "-l"): (
            255, "", "ERROR: Unable to retrieve device list!\n")})
        with self.assertRaises(dt.DeviceError) as caught:
            toolbox.devices()
        self.assertEqual(caught.exception.kind, dt.NO_DEVICE)
        self.assertIn("usbmuxd", str(caught.exception))

    def test_only_real_identifiers_are_taken_from_the_output(self):
        toolbox, _ = box({("idevice_id", "-l"): (
            0, "WARNING: something\n-rf\n" + UDID + "\n", "")})
        self.assertEqual(toolbox.devices(), [UDID])


class DeviceInfoTests(unittest.TestCase):
    def answers(self):
        return {
            ("ideviceinfo", "-x", "com.apple.disk_usage"): (
                0, plist_text({"TotalDataCapacity": 128_000_000_000,
                               "TotalDataAvailable": 40_000_000_000}), ""),
            ("ideviceinfo", "-x", "com.apple.mobile.battery"): (
                0, plist_text({"BatteryCurrentCapacity": 81}), ""),
            ("ideviceinfo", "-x", "com.apple.mobile.backup"): (
                0, plist_text({"WillEncrypt": True}), ""),
            ("ideviceinfo", "-x"): (0, plist_text({
                "DeviceName": "Taylor's iPhone", "ProductType": "iPhone14,2",
                "ProductName": "iPhone OS", "ProductVersion": "17.5.1",
                "BuildVersion": "21F90", "SerialNumber": "SERIAL123",
                "UniqueDeviceID": UDID, "PasswordProtected": True}), ""),
        }

    def test_the_details_are_read(self):
        toolbox, recorder = box(self.answers())
        info = toolbox.info(UDID)
        self.assertEqual((info.name, info.model, info.version, info.build),
                         ("Taylor's iPhone", "iPhone14,2", "17.5.1", "21F90"))
        self.assertEqual(info.udid, UDID)
        self.assertTrue(info.passcode_set)
        self.assertEqual(info.storage_free, 40_000_000_000)
        self.assertEqual(info.battery, 81)
        self.assertIs(info.encrypts_backups, True)

    def test_the_extra_parts_may_be_missing(self):
        answers = {k: v for k, v in self.answers().items() if len(k) == 2}
        toolbox, _ = box(answers)
        info = toolbox.info(UDID)
        self.assertEqual(info.name, "Taylor's iPhone")
        self.assertIsNone(info.battery)
        self.assertIsNone(info.encrypts_backups)

    def test_a_device_that_has_not_trusted_us_says_so(self):
        toolbox, _ = box({("ideviceinfo", "-x"): (
            255, "", "ERROR: Could not connect to lockdownd. Please accept "
            "the trust dialog on the device.\n")})
        with self.assertRaises(dt.DeviceError) as caught:
            toolbox.info(UDID)
        self.assertEqual(caught.exception.kind, dt.NOT_TRUSTED)

    def test_an_identifier_that_looks_like_an_option_is_refused(self):
        toolbox, recorder = box(self.answers())
        for bad in ("--debug", "-u", "", "x; rm -rf /"):
            with self.assertRaises(dt.DeviceError):
                toolbox.info(bad)
        self.assertEqual(recorder.calls, [])


class PairingTests(unittest.TestCase):
    def test_validated_pairing_is_paired(self):
        toolbox, _ = box({("idevicepair", "validate"): (
            0, f"SUCCESS: Validated pairing with device {UDID}\n", "")})
        self.assertEqual(toolbox.pairing(UDID), dt.PAIRED)

    def test_a_device_not_paired_with_us_is_unpaired(self):
        toolbox, _ = box({("idevicepair", "validate"): (
            255, f"ERROR: Device {UDID} is not paired with this host\n", "")})
        self.assertEqual(toolbox.pairing(UDID), dt.UNPAIRED)

    def test_a_locked_device_cannot_be_asked(self):
        toolbox, _ = box({("idevicepair", "validate"): (
            255, f"ERROR: Could not validate with device {UDID} because a "
            "passcode is set. Please enter the passcode on the device and "
            "retry.\n", "")})
        with self.assertRaises(dt.DeviceError) as caught:
            toolbox.pairing(UDID)
        self.assertEqual(caught.exception.kind, dt.LOCKED)

    def test_pairing_waits_for_the_tap_on_trust(self):
        toolbox, _ = box({("idevicepair", "pair"): (
            255, f"ERROR: Please accept the trust dialog on the screen of "
            f"device {UDID}, then attempt to pair again.\n", "")})
        with self.assertRaises(dt.DeviceError) as caught:
            toolbox.pair(UDID)
        self.assertEqual(caught.exception.kind, dt.NOT_TRUSTED)

    def test_a_refused_trust_question_is_told_apart(self):
        toolbox, _ = box({("idevicepair", "pair"): (
            255, f"ERROR: Device {UDID} said that the user denied the trust "
            "dialog.\n", "")})
        with self.assertRaises(dt.DeviceError) as caught:
            toolbox.pair(UDID)
        self.assertEqual(caught.exception.kind, dt.DENIED)

    def test_pairing_succeeds(self):
        toolbox, _ = box({("idevicepair", "pair"): (
            0, f"SUCCESS: Paired with device {UDID}\n", "")})
        self.assertEqual(toolbox.pair(UDID), dt.PAIRED)

    def test_unpairing(self):
        toolbox, recorder = box({("idevicepair", "unpair"): (
            0, f"SUCCESS: Unpaired with device {UDID}\n", "")})
        self.assertEqual(toolbox.unpair(UDID), dt.UNPAIRED)
        self.assertEqual(recorder.calls[0][0][1:],
                         ["-u", UDID, "unpair"])


class BackupPasswordTests(unittest.TestCase):
    def test_the_password_goes_in_the_environment_not_on_the_command_line(
            self):
        toolbox, recorder = box({("idevicebackup2", "encryption"): (
            0, "Backup encryption has been enabled successfully.\n", "")})
        toolbox.set_encryption(UDID, True, "s3cret pass")
        argv, env, _ = recorder.calls[0]
        self.assertNotIn("s3cret pass", " ".join(argv))
        self.assertEqual(env["BACKUP_PASSWORD"], "s3cret pass")
        self.assertEqual(argv[1:], ["-u", UDID, "encryption", "on"])

    def test_turning_it_off_needs_the_current_password(self):
        toolbox, recorder = box({("idevicebackup2", "encryption"): (
            0, "Backup encryption has been disabled successfully.\n", "")})
        toolbox.set_encryption(UDID, False, "current")
        self.assertEqual(recorder.calls[0][0][-1], "off")
        self.assertEqual(recorder.calls[0][1]["BACKUP_PASSWORD"], "current")

    def test_a_refusal_does_not_leak_the_password_into_the_error(self):
        toolbox, _ = box({("idevicebackup2", "encryption"): (
            255, "Could not enable backup encryption. hunter2\n", "")})
        with self.assertRaises(dt.DeviceError) as caught:
            toolbox.set_encryption(UDID, True, "hunter2")
        self.assertNotIn("hunter2", str(caught.exception))
        self.assertNotIn("hunter2", caught.exception.detail)

    def test_changing_the_password_passes_both_in_the_environment(self):
        toolbox, recorder = box({("idevicebackup2", "changepw"): (
            0, "Backup encryption password has been changed "
            "successfully.\n", "")})
        toolbox.change_password(UDID, "old one", "new one")
        argv, env, _ = recorder.calls[0]
        self.assertNotIn("old one", " ".join(argv))
        self.assertNotIn("new one", " ".join(argv))
        self.assertEqual(env["BACKUP_PASSWORD"], "old one")
        self.assertEqual(env["BACKUP_PASSWORD_NEW"], "new one")

    def test_a_wrong_old_password_is_an_error(self):
        toolbox, _ = box({("idevicebackup2", "changepw"): (
            255, "Could not change backup encryption password.\n", "")})
        with self.assertRaises(dt.DeviceError):
            toolbox.change_password(UDID, "wrong", "new")

    def test_an_empty_password_is_not_sent(self):
        toolbox, recorder = box()
        with self.assertRaises(dt.DeviceError):
            toolbox.set_encryption(UDID, True, "")
        with self.assertRaises(dt.DeviceError):
            toolbox.change_password(UDID, "old", "")
        self.assertEqual(recorder.calls, [])


class OutputTests(unittest.TestCase):
    def test_colour_and_cursor_codes_are_removed(self):
        text = "\x1b7\x1b[2K\x1b[1G\x1b[32mBackup\x1b[0m \x1b[3A  4%\r\n"
        self.assertEqual(dt.clean_output(text), "Backup   4%\n")

    def test_the_overall_progress_of_new_and_old_versions(self):
        self.assertEqual(dt.parse_progress("Backup     [####      ]  42%"), 42)
        self.assertEqual(dt.parse_progress("Backup  [##] 12.5%"), 12.5)
        self.assertEqual(dt.parse_progress("[=====>    ]  63%  Finished"), 63)
        self.assertIsNone(dt.parse_progress("Receiving   IMG_1.jpg"))
        self.assertIsNone(dt.parse_progress("   [#####    ]  80.0%  1 MB / 2 MB"))
        self.assertIsNone(dt.parse_progress("Backup Successful."))
        self.assertEqual(dt.parse_progress("Backup  [##]  250%"), 100)


FAKE_BACKUP = r'''
import os, sys, time
mode = os.environ.get("FAKE_MODE", "ok")
args = sys.argv[1:]
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "w") as f:
        f.write(repr(args) + "\n")
        f.write("password-in-env=" + repr(os.environ.get("BACKUP_PASSWORD")) + "\n")
out = sys.stdout
def frame(percent, name):
    out.write("\x1b8\x1b[3A\x1b[2K\x1b[1GBackup     [####      ] %3d%%\n" % percent)
    out.write("\x1b[2K\x1b[1GReceiving  %s\n" % name)
    out.write("\x1b[2K\x1b[1G           [##########]  100.0%\n")
    out.flush()
out.write("Backup directory is \"%s\"\n" % args[-1])
out.write("Starting backup...\nBackup will be unencrypted.\nIncremental backup mode.\n")
out.flush()
if mode == "hang":
    out.write("Waiting\n"); out.flush()
    time.sleep(60)
for p, n in ((5, "Manifest.db"), (50, "a/b.jpg"), (100, "c.png")):
    frame(p, n)
    time.sleep(0.02)
if mode == "fail":
    out.write("ErrorCode 211: device out of space\nBackup Failed (Error Code 211).\n")
    sys.exit(211)
if mode == "locked":
    out.write("ERROR: Could not start service: Please enter the passcode on the device and retry.\n")
    sys.exit(255)
out.write("Received 3 files from device.\nBackup Successful.\n")
'''


class RunningABackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-devtools-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.script = os.path.join(self.tmp, "fake_idevicebackup2.py")
        with open(self.script, "w", encoding="utf-8") as f:
            f.write(FAKE_BACKUP)
        self.folder = os.path.join(self.tmp, "Backups")
        self.toolbox, _ = box()
        patcher = mock.patch.object(
            dt.Toolbox, "argv",
            lambda s, name, *a: [sys.executable, self.script, *a])
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_backup(self, mode="ok", full=False, wait=20):
        progress, lines, done = [], [], threading.Event()
        outcome = []
        env = {"FAKE_MODE": mode,
               "FAKE_LOG": os.path.join(self.tmp, "log.txt")}
        with mock.patch.dict(os.environ, env):
            run = self.toolbox.start_backup(
                UDID, self.folder, full=full, on_progress=progress.append,
                on_line=lines.append,
                on_done=lambda o: (outcome.append(o), done.set()))
        return run, progress, lines, done, outcome

    def test_a_backup_reports_its_progress_and_succeeds(self):
        run, progress, lines, done, outcome = self.run_backup()
        self.assertTrue(done.wait(20))
        self.assertTrue(outcome[0].ok, outcome[0])
        self.assertEqual(progress[-1], 100)
        self.assertEqual(sorted(set(progress)), [5, 50, 100])
        self.assertIn("Backup Successful.", lines)
        self.assertEqual(outcome[0].folder,
                         os.path.join(self.folder, UDID))
        self.assertTrue(os.path.isdir(self.folder))

    def test_the_command_is_the_documented_one(self):
        run, *_rest, done, outcome = self.run_backup(full=True)
        self.assertTrue(done.wait(20))
        with open(os.path.join(self.tmp, "log.txt")) as f:
            args = eval(f.readline())
        self.assertEqual(args, ["-u", UDID, "backup", "--full", self.folder])

    def test_a_failure_is_reported_with_what_the_tool_said(self):
        run, progress, lines, done, outcome = self.run_backup("fail")
        self.assertTrue(done.wait(20))
        self.assertFalse(outcome[0].ok)
        self.assertEqual(outcome[0].kind, dt.FAILED)
        self.assertIn("211", outcome[0].message)

    def test_a_locked_device_is_told_apart(self):
        run, progress, lines, done, outcome = self.run_backup("locked")
        self.assertTrue(done.wait(20))
        self.assertEqual(outcome[0].kind, dt.LOCKED)
        self.assertIn("Unlock", outcome[0].message)

    def test_a_backup_can_be_stopped(self):
        run, progress, lines, done, outcome = self.run_backup("hang")
        deadline = 0
        while "Waiting" not in lines and deadline < 400:
            threading.Event().wait(0.05)
            deadline += 1
        run.stop()
        self.assertTrue(done.wait(20))
        self.assertEqual(outcome[0].kind, dt.CANCELLED)
        self.assertFalse(outcome[0].ok)

    def test_exiting_cleanly_without_saying_so_is_not_success(self):
        # (the tool can exit 0 and still not have finished the backup)
        outcomes = []
        done = threading.Event()
        script = os.path.join(self.tmp, "quiet.py")
        with open(script, "w") as f:
            f.write("print('Starting backup...')\n")
        run = dt.BackupRun([sys.executable, script], UDID, self.folder,
                           on_done=lambda o: (outcomes.append(o), done.set()))
        run.start()
        self.assertTrue(done.wait(20))
        self.assertFalse(outcomes[0].ok)



class WithoutTheToolTests(unittest.TestCase):
    def test_a_backup_cannot_start_without_the_tool(self):
        toolbox = dt.Toolbox(which=fake_which(()))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(dt.DeviceError) as caught:
                toolbox.start_backup(UDID, folder)
        self.assertEqual(caught.exception.kind, dt.TOOL_MISSING)


class CrashReportTests(unittest.TestCase):
    def test_reports_are_copied_and_kept_on_the_device_by_default(self):
        tmp = tempfile.mkdtemp(prefix="ibe-crash-")
        self.addCleanup(shutil.rmtree, tmp, True)

        def runner(argv, env, timeout):
            self.assertIn("-k", argv)
            self.assertEqual(argv[-1], tmp)
            for n in ("a.ips", "b.ips"):
                open(os.path.join(tmp, n), "w").close()
            return 0, b"", b""

        toolbox = dt.Toolbox(which=fake_which(), runner=runner)
        self.assertEqual(toolbox.crash_reports(UDID, tmp), 2)

    def test_removal_from_the_device_is_only_when_asked_for(self):
        tmp = tempfile.mkdtemp(prefix="ibe-crash-")
        self.addCleanup(shutil.rmtree, tmp, True)
        seen = []

        def runner(argv, env, timeout):
            seen.append(argv)
            return 0, b"", b""

        toolbox = dt.Toolbox(which=fake_which(), runner=runner)
        toolbox.crash_reports(UDID, tmp, keep=False)
        self.assertNotIn("-k", seen[0])


if __name__ == "__main__":
    unittest.main()
