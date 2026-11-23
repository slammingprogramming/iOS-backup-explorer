# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The "Devices & backups" window, in the real main window (skipped without a
display). The toolbox is a stand-in that answers as a device would, so every
state (no tools, no device, not trusted, trusted, backing up, failing) is
reached without hardware."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

import app_settings
import backup_library as lib
import device_tools as dt
import devices_view as dv
import ios_backup_explorer as app
from tests.gui_apps import AppGuiCase
from tests.test_backup_library import make_backup

UDID = "00008030-001A2B3C4D5E6F78"


class FakeRun:
    def __init__(self, folder, udid, callbacks):
        self.folder, self.udid = folder, udid
        self.callbacks = callbacks
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.callbacks["on_done"](dt.BackupOutcome(
            False, dt.CANCELLED, "The backup was stopped.", "", 0))

    def wait(self, timeout=None):
        return True


class FakeToolbox:
    """Answers like a Toolbox with a device on the cable."""

    def __init__(self, devices=(UDID,), paired=True, encrypts=False,
                 missing=(), error=None):
        self.devices_list = list(devices)
        self.paired = paired
        self.encrypts = encrypts
        self.missing = list(missing)
        self.error = error
        self.calls = []
        self.runs = []

    @property
    def can_list(self):
        return "idevice_id" not in self.missing

    @property
    def can_backup(self):
        return "idevicebackup2" not in self.missing and self.can_list

    def has(self, name):
        return name not in self.missing

    def devices(self):
        if self.error:
            raise self.error
        return list(self.devices_list)

    def pairing(self, udid):
        self.calls.append(("pairing", udid))
        return dt.PAIRED if self.paired else dt.UNPAIRED

    def pair(self, udid):
        self.calls.append(("pair", udid))
        self.paired = True
        return dt.PAIRED

    def info(self, udid):
        return dt.DeviceInfo(
            udid=udid, name="Taylor's iPhone", model="iPhone15,4",
            version="18.5", build="22F76", serial="DEMO",
            passcode_set=True, storage_total=128_000_000_000,
            storage_free=40_000_000_000, battery=81,
            encrypts_backups=self.encrypts)

    def set_encryption(self, udid, enable, password):
        self.calls.append(("encryption", udid, enable, password))
        self.encrypts = enable
        return True

    def change_password(self, udid, old, new):
        self.calls.append(("changepw", udid, old, new))
        return True

    def crash_reports(self, udid, folder, keep=True):
        self.calls.append(("crash", udid, folder, keep))
        return 3

    def start_backup(self, udid, folder, full=False, **callbacks):
        self.calls.append(("backup", udid, folder, full))
        run = FakeRun(folder, udid, callbacks)
        self.runs.append(run)
        return run


class WindowCase(AppGuiCase):
    def setUp(self):
        super().setUp()
        self.libroot = tempfile.mkdtemp(dir=self.tmp)
        self.settings_dir = tempfile.mkdtemp(dir=self.tmp)
        self.settings = app_settings.Settings(self.settings_dir)
        self.opened = []
        self.windows = []
        # (runs before the base class's own teardown: close the windows and
        # collect their garbage here, on the Tk thread, never in a worker)
        self.addCleanup(self._drop_windows)
        patcher = mock.patch.object(dv.DevicesWindow, "COLLECT_AFTER_CLOSE",
                                    None)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("askyesno",):
            patcher = mock.patch.object(dv.messagebox, name,
                                        return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _drop_windows(self):
        import gc
        for window in self.windows:
            if window.winfo_exists():
                window.destroy()
        self.windows.clear()
        self.root.update()
        gc.collect()

    def make_window(self, toolbox=None, locations=None):
        toolbox = toolbox or FakeToolbox()
        locs = locations if locations is not None else [
            (self.libroot, "Test folder")]
        window = dv.DevicesWindow(
            self.root, settings=self.settings, locations=lambda: list(locs),
            toolbox=toolbox, open_backup=self.opened.append,
            default_folder=os.path.join(self.tmp, "new-backups"),
            make_toolbox=lambda folder=None: toolbox)
        self.windows.append(window)
        self.addCleanup(lambda: window.winfo_exists() and window.destroy())
        self.wait_for(lambda: window.status_var.get() != "", "a status")
        return window

    def listed(self, window, count):
        self.wait_for(lambda: len(window.tree.get_children()) == count,
                      f"{count} backups listed")


class BackupsTabTests(WindowCase):
    def test_every_backup_is_listed_with_what_it_is(self):
        make_backup(self.libroot, "AAA", device="Taylor's iPhone")
        make_backup(self.libroot, "BBB", device="Alex's iPad",
                    encrypted=True, finished=False)
        window = self.make_window()
        self.listed(window, 2)
        rows = {window.tree.item(i, "values")[0]:
                window.tree.item(i, "values") for i in
                window.tree.get_children()}
        taylor, alex = rows["Taylor's iPhone"], rows["Alex's iPad"]
        self.assertEqual(taylor[4], "No")
        self.assertEqual(taylor[5], "Complete")
        self.assertEqual(alex[4], "Yes")
        self.assertEqual(alex[5], "Interrupted")
        self.assertEqual(taylor[6], "Test folder")

    def test_sizes_arrive_after_the_list(self):
        make_backup(self.libroot, "AAA")
        window = self.make_window()
        self.listed(window, 1)
        iid = window.tree.get_children()[0]
        self.wait_for(lambda: window.tree.set(iid, "size") != "", "a size")

    def test_no_backups_says_how_to_add_a_folder(self):
        window = self.make_window()
        self.wait_for(lambda: "Add a folder" in window.status_var.get(),
                      "the empty-list advice")

    def test_a_folder_that_is_added_is_remembered_and_searched(self):
        extra = tempfile.mkdtemp(dir=self.tmp)
        make_backup(extra, "XXX")
        window = self.make_window()
        with mock.patch.object(dv.filedialog, "askdirectory",
                               return_value=extra):
            window.add_folder()
        self.assertEqual(self.settings.backup_folders,
                         [os.path.abspath(extra)])
        self.assertEqual(app_settings.Settings.load(
            self.settings_dir).backup_folders, [os.path.abspath(extra)])

    def test_buttons_follow_the_selection(self):
        make_backup(self.libroot, "AAA")
        window = self.make_window()
        self.listed(window, 1)
        self.assertEqual(str(window.backup_buttons["delete"]["state"]),
                         "disabled")
        window.tree.selection_set(window.tree.get_children()[0])
        self.root.update()
        self.assertEqual(str(window.backup_buttons["delete"]["state"]),
                         "normal")

    def select_first(self, window):
        self.listed(window, 1)
        window.tree.selection_set(window.tree.get_children()[0])
        self.root.update()

    def test_open_hands_the_backup_to_the_main_window(self):
        path = make_backup(self.libroot, "AAA")
        window = self.make_window()
        self.select_first(window)
        window.open_selected()
        self.assertEqual(self.opened, [os.path.abspath(path)])

    def test_check_reports_a_missing_file(self):
        path = make_backup(self.libroot, "AAA")
        from tests import fixture_backup as fb
        file_id = fb.file_id_for("HomeDomain", "Library/a.txt")
        os.remove(os.path.join(path, file_id[:2], file_id))
        window = self.make_window()
        self.select_first(window)
        window.check_selected()
        self.wait_for(lambda: any(d[0] == "showwarning"
                                  for d in self.dialogs), "the warning")
        self.assertIn("Missing", self.dialogs[-1][1][1])

    def test_check_of_a_whole_backup_says_so(self):
        make_backup(self.libroot, "AAA")
        window = self.make_window()
        self.select_first(window)
        window.check_selected()
        self.wait_for(lambda: any(d[0] == "showinfo" for d in self.dialogs),
                      "the all-clear")

    def test_copy_makes_a_second_complete_backup(self):
        make_backup(self.libroot, "AAA")
        dest = tempfile.mkdtemp(dir=self.tmp)
        window = self.make_window()
        self.select_first(window)
        with mock.patch.object(dv.filedialog, "askdirectory",
                               return_value=dest):
            window.copy_selected(move=False)
        self.wait_for(lambda: os.path.isdir(os.path.join(dest, "AAA"))
                      and window._busy is None, "the copy")
        self.assertTrue(os.path.isdir(os.path.join(self.libroot, "AAA")))

    def test_move_removes_the_original_after_the_copy(self):
        make_backup(self.libroot, "AAA")
        dest = tempfile.mkdtemp(dir=self.tmp)
        window = self.make_window()
        self.select_first(window)
        with mock.patch.object(dv.filedialog, "askdirectory",
                               return_value=dest):
            window.copy_selected(move=True)
        self.wait_for(lambda: os.path.isdir(os.path.join(dest, "AAA"))
                      and window._busy is None, "the move")
        self.assertFalse(os.path.exists(os.path.join(self.libroot, "AAA")))

    def test_delete_asks_first_and_names_what_it_deletes(self):
        make_backup(self.libroot, "AAA", device="Taylor's iPhone")
        window = self.make_window()
        self.select_first(window)
        with mock.patch.object(dv.messagebox, "askyesno",
                               return_value=False) as ask:
            window.delete_selected()
        self.assertTrue(os.path.isdir(os.path.join(self.libroot, "AAA")))
        text = ask.call_args.args[1]
        self.assertIn("Taylor's iPhone", text)
        self.assertIn("cannot be undone", text)
        self.assertEqual(ask.call_args.kwargs["default"], "no")

    def test_delete_removes_it_when_confirmed(self):
        make_backup(self.libroot, "AAA")
        window = self.make_window()
        self.select_first(window)
        window.delete_selected()
        self.assertFalse(os.path.exists(os.path.join(self.libroot, "AAA")))
        self.wait_for(lambda: not window.tree.get_children(),
                      "the empty list")


class DeviceTabTests(WindowCase):
    def buttons(self, window):
        return {name: str(getattr(window, name + "_button")["state"])
                for name in ("pair", "backup", "stop", "crash")}

    def ready(self, window):
        self.wait_for(lambda: window.info_vars["pairing"].get() != "",
                      "the device's answer")

    def test_a_trusted_device_shows_what_it_says_and_can_be_backed_up(self):
        window = self.make_window()
        self.ready(window)
        self.wait_for(lambda: window.info_vars["name"].get() != "", "info")
        v = window.info_vars
        self.assertEqual(v["name"].get(), "Taylor's iPhone")
        self.assertIn("22F76", v["version"].get())
        self.assertEqual(v["pairing"].get(), "Trusted")
        self.assertEqual(v["battery"].get(), "81%")
        self.assertEqual(v["encryption"].get(), "No")
        self.assertEqual(self.buttons(window)["backup"], "normal")
        self.assertEqual(self.buttons(window)["pair"], "disabled")

    def test_a_device_that_does_not_trust_us_must_be_paired_first(self):
        window = self.make_window(FakeToolbox(paired=False))
        self.ready(window)
        self.assertEqual(window.info_vars["pairing"].get(),
                         "Not trusted yet")
        self.assertEqual(self.buttons(window)["pair"], "normal")
        self.assertEqual(self.buttons(window)["backup"], "disabled")
        window.pair()
        self.wait_for(lambda: window.info_vars["pairing"].get() == "Trusted",
                      "the pairing")
        self.assertEqual(self.buttons(window)["backup"], "normal")

    def test_no_device_says_how_to_connect_one(self):
        window = self.make_window(FakeToolbox(devices=()))
        self.wait_for(lambda: "plugged in" in window.device_status_var.get(),
                      "the advice")
        self.assertEqual(self.buttons(window)["backup"], "disabled")

    def test_without_the_tools_the_tab_says_what_to_install(self):
        window = self.make_window(FakeToolbox(
            missing=list(dt.TOOL_NAMES)))
        self.assertIn("apt install libimobiledevice-utils",
                      window.tools_var.get())
        self.assertEqual(self.buttons(window)["backup"], "disabled")
        # ... and the backups tab still works
        make_backup(self.libroot, "AAA")
        window.refresh_backups()
        self.listed(window, 1)

    def test_an_error_from_the_tool_is_shown(self):
        window = self.make_window(FakeToolbox(
            error=dt.DeviceError(dt.NO_DEVICE)))
        self.wait_for(lambda: "usbmuxd" in window.device_status_var.get(),
                      "the error")

    def test_backup_runs_into_the_chosen_folder_and_reports(self):
        toolbox = FakeToolbox()
        window = self.make_window(toolbox)
        self.ready(window)
        window.dest_var.set(os.path.join(self.tmp, "mine"))
        window.full_var.set(True)
        window.start_backup()
        call = toolbox.calls[-1]
        self.assertEqual(call, ("backup", UDID,
                                os.path.join(self.tmp, "mine"), True))
        self.assertEqual(self.buttons(window)["stop"], "normal")
        self.assertEqual(self.buttons(window)["backup"], "disabled")
        callbacks = toolbox.runs[0].callbacks
        callbacks["on_progress"](42.0)
        callbacks["on_line"]("Received 3 files from device.")
        self.wait_for(lambda: float(window.bk_bar["value"]) == 42.0,
                      "the progress")
        self.assertIn("Received 3 files", window.log.get("1.0", "end"))
        outcome = dt.BackupOutcome(True, None, "The backup is complete.",
                                   os.path.join(self.tmp, "mine", UDID), 0)
        with mock.patch.object(dv.messagebox, "askyesno",
                               return_value=True):
            callbacks["on_done"](outcome)
            self.wait_for(lambda: self.opened, "the offer to open it")
        self.assertEqual(self.opened, [outcome.folder])
        self.assertEqual(self.buttons(window)["backup"], "normal")

    def test_a_failed_backup_says_why_and_can_be_retried(self):
        toolbox = FakeToolbox()
        window = self.make_window(toolbox)
        self.ready(window)
        window.start_backup()
        toolbox.runs[0].callbacks["on_done"](dt.BackupOutcome(
            False, dt.LOCKED, "The device is locked. Unlock it.", "", 255))
        self.wait_for(lambda: "Unlock it" in window.device_status_var.get(),
                      "the reason")
        self.assertEqual(self.opened, [])
        self.assertEqual(self.buttons(window)["backup"], "normal")

    def test_stop_stops_the_run(self):
        toolbox = FakeToolbox()
        window = self.make_window(toolbox)
        self.ready(window)
        window.start_backup()
        window.stop_backup()
        self.assertTrue(toolbox.runs[0].stopped)
        self.wait_for(lambda: window._run is None, "the stop")

    def test_closing_during_a_backup_asks_and_can_be_cancelled(self):
        toolbox = FakeToolbox()
        window = self.make_window(toolbox)
        self.ready(window)
        window.start_backup()
        with mock.patch.object(dv.messagebox, "askyesno",
                               return_value=False):
            window._on_close()
        self.assertTrue(window.winfo_exists())
        self.assertFalse(toolbox.runs[0].stopped)
        with mock.patch.object(dv.messagebox, "askyesno",
                               return_value=True):
            window._on_close()
        self.assertTrue(toolbox.runs[0].stopped)

    def test_the_destination_is_remembered(self):
        window = self.make_window()
        folder = tempfile.mkdtemp(dir=self.tmp)
        with mock.patch.object(dv.filedialog, "askdirectory",
                               return_value=folder):
            window.choose_destination()
        self.assertEqual(window.dest_var.get(), folder)
        self.assertEqual(app_settings.Settings.load(
            self.settings_dir).backup_destination, folder)

    def test_the_default_destination_is_the_programs_own_folder(self):
        window = self.make_window()
        self.assertEqual(window.dest_var.get(),
                         os.path.join(self.tmp, "new-backups"))

    def test_turning_encryption_on_passes_the_password_on(self):
        toolbox = FakeToolbox()
        window = self.make_window(toolbox)
        self.wait_for(lambda: window.info_vars["name"].get() != "", "info")
        with mock.patch.object(dv, "ask_passwords",
                               return_value=["pw1", "pw1"]) as ask:
            window.enable_encryption()
        self.assertIn("forgotten", ask.call_args.kwargs["warning"])
        self.wait_for(lambda: ("encryption", UDID, True, "pw1")
                      in toolbox.calls, "the call")
        self.wait_for(lambda: window.info_vars["encryption"].get() == "Yes",
                      "the new state")

    def test_the_password_buttons_follow_the_encryption_state(self):
        window = self.make_window(FakeToolbox(encrypts=True))
        self.wait_for(lambda: window.info_vars["encryption"].get() == "Yes",
                      "info")
        self.assertEqual(str(window.enc_on["state"]), "disabled")
        self.assertEqual(str(window.enc_off["state"]), "normal")
        self.assertEqual(str(window.enc_change["state"]), "normal")

    def test_changing_the_password_asks_for_old_and_new(self):
        toolbox = FakeToolbox(encrypts=True)
        window = self.make_window(toolbox)
        self.wait_for(lambda: window.info_vars["name"].get() != "", "info")
        with mock.patch.object(dv, "ask_passwords",
                               return_value=["old", "new", "new"]):
            window.change_password()
        self.wait_for(lambda: ("changepw", UDID, "old", "new")
                      in toolbox.calls, "the call")

    def test_a_cancelled_password_box_changes_nothing(self):
        toolbox = FakeToolbox()
        window = self.make_window(toolbox)
        self.wait_for(lambda: window.info_vars["name"].get() != "", "info")
        with mock.patch.object(dv, "ask_passwords", return_value=None):
            window.enable_encryption()
        self.assertFalse([c for c in toolbox.calls
                          if c[0] == "encryption"])

    def test_crash_reports_are_copied_and_left_on_the_device(self):
        toolbox = FakeToolbox()
        window = self.make_window(toolbox)
        self.wait_for(lambda: window.info_vars["name"].get() != "", "info")
        folder = tempfile.mkdtemp(dir=self.tmp)
        with mock.patch.object(dv.filedialog, "askdirectory",
                               return_value=folder):
            window.copy_crash_reports()
        self.wait_for(lambda: "3 crash reports" in window.device_status_var.get(),
                      "the count")
        self.assertEqual(toolbox.calls[-1], ("crash", UDID, folder, True))


class ClosingTests(WindowCase):
    def test_a_closed_window_has_its_garbage_collected_on_the_tk_thread(self):
        window = self.make_window()
        with mock.patch.object(dv.DevicesWindow, "COLLECT_AFTER_CLOSE", 100), \
                mock.patch.object(window.master, "after") as after:
            window.destroy()
            self.root.update()
        self.assertTrue([c for c in after.call_args_list
                         if c.args[:2] == (100, dv.gc.collect)])


class PasswordBoxTests(AppGuiCase):
    def box(self, fields, confirm=False):
        dialog = dv.PasswordFieldsDialog(self.root, "T", "msg", fields,
                                         confirm_last=confirm,
                                         warning="warn")
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        return dialog

    def test_all_the_boxes_must_be_filled(self):
        dialog = self.box(["a", "b"])
        dialog._vars[0].set("x")
        dialog._ok()
        self.assertIsNone(dialog.result)
        self.assertIn("Fill in", dialog.error_var.get())

    def test_two_new_passwords_must_match(self):
        dialog = self.box(["new", "again"], confirm=True)
        dialog._vars[0].set("one")
        dialog._vars[1].set("two")
        dialog._ok()
        self.assertIsNone(dialog.result)
        self.assertIn("not the same", dialog.error_var.get())

    def test_matching_passwords_are_returned_untouched(self):
        dialog = self.box(["new", "again"], confirm=True)
        dialog._vars[0].set(" a b ")
        dialog._vars[1].set(" a b ")
        dialog._ok()
        self.assertEqual(dialog.result, [" a b ", " a b "])


class ThreadRuleTests(unittest.TestCase):
    """A thread that held the window (through a bound method) could free
    it, and its Tk variables, off the Tk thread, which Tk forbids."""

    def test_no_thread_is_started_on_a_method_of_the_window(self):
        import inspect
        import re
        source = inspect.getsource(dv.DevicesWindow)
        targets = re.findall(r"self\._work\(self\.(\w+)", source)
        self.assertTrue(targets)
        for name in targets:
            self.assertIsInstance(
                inspect.getattr_static(dv.DevicesWindow, name), staticmethod,
                f"{name} is started on a thread but is not static")

    def test_a_thread_is_never_given_the_window_itself(self):
        import inspect
        import re
        source = inspect.getsource(dv.DevicesWindow)
        for call in re.findall(r"self\._work\([^)]*\)", source, re.S):
            self.assertNotRegex(call, r"(?<![\w.])self(?![\w.])", call)


class LinuxDefaultTests(unittest.TestCase):
    def test_linux_has_a_default_place_for_backups(self):
        # (the window tests blank this table; here it is as shipped)
        self.assertEqual(
            app.BackupExplorer.BACKUP_PATHS["Linux"],
            [lib.own_backup_folder("Linux", os.environ,
                                   os.path.expanduser("~"))])


class MainWindowTests(AppGuiCase):
    def test_a_button_opens_the_window_once(self):
        folder = tempfile.mkdtemp(dir=self.tmp)
        with mock.patch.object(app.BackupExplorer, "SETTINGS_FOLDER",
                               folder), \
                mock.patch.object(app.device_tools, "Toolbox",
                                  return_value=FakeToolbox()):
            self.assertEqual(self.explorer.devices_btn.cget("text"),
                             "Devices & backups...")
            self.explorer.devices_btn.invoke()
            first = self.explorer._devices_window
            self.explorer.devices_btn.invoke()
            self.assertIs(self.explorer._devices_window, first)
            first.destroy()

    def test_a_backup_made_here_is_found_on_linux_at_start(self):
        base = tempfile.mkdtemp(dir=self.tmp)
        make_backup(base, "OLDER")
        with mock.patch.object(app.platform, "system",
                               return_value="Linux"), \
                mock.patch.object(app.BackupExplorer, "BACKUP_PATHS",
                                  {"Linux": [base]}):
            self.explorer._auto_detect_backup()
        self.assertTrue(self.explorer.path_var.get().endswith("OLDER"))

    def test_open_from_the_window_opens_an_unencrypted_backup(self):
        base = tempfile.mkdtemp(dir=self.tmp)
        path = make_backup(base, "AAA")
        with mock.patch.object(self.explorer, "_decrypt") as decrypt:
            self.explorer._open_from_library(path)
        self.assertEqual(self.explorer.path_var.get(), path)
        decrypt.assert_called_once()

    def test_open_from_the_window_asks_for_the_password_when_needed(self):
        base = tempfile.mkdtemp(dir=self.tmp)
        path = make_backup(base, "AAA", encrypted=True)
        with mock.patch.object(self.explorer, "_decrypt") as decrypt:
            self.explorer._open_from_library(path)
        decrypt.assert_not_called()
        self.assertEqual(self.explorer.path_var.get(), path)


if __name__ == "__main__":
    unittest.main()
