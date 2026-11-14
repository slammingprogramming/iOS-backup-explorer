# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Where people can say thanks: the one list of addresses (``about.py``), the
window that shows it, and every place that repeats it, which must agree."""

import re
import unittest
from pathlib import Path
from unittest import mock

import about
from tests.gui_apps import AppGuiCase

ROOT = Path(__file__).resolve().parent.parent
PAGES = [ROOT / "README.md", ROOT / "docs" / "DONATE.md"]

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_check(address):
    """``"bech32"``, ``"bech32m"`` or None for the checksum of *address*."""
    def polymod(values):
        generator = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd,
                     0x2a1462b3]
        check = 1
        for value in values:
            top = check >> 25
            check = (check & 0x1ffffff) << 5 ^ value
            for bit in range(5):
                if (top >> bit) & 1:
                    check ^= generator[bit]
        return check

    position = address.rfind("1")
    hrp, data = address[:position], address[position + 1:]
    if not hrp or any(c not in CHARSET for c in data):
        return None
    values = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    values += [CHARSET.index(c) for c in data]
    return {1: "bech32", 0x2bc830a3: "bech32m"}.get(polymod(values))


def read(path):
    return Path(path).read_text(encoding="utf-8")


class TheListTests(unittest.TestCase):
    def address(self, symbol):
        return next(a for _l, s, a in about.ADDRESSES if s == symbol)

    def test_there_are_three_coins_and_a_page(self):
        self.assertEqual([s for _l, s, _a in about.ADDRESSES],
                         ["BTC", "ETH", "XMR"])
        self.assertEqual(about.KOFI_URL, "https://ko-fi.com/scenprogramming")

    def test_the_addresses_are_well_formed(self):
        # (a mistyped character would send a donor's money nowhere)
        btc = self.address("BTC")
        self.assertTrue(btc.startswith("sp1q"))        # Silent Payments
        self.assertEqual(bech32_check(btc), "bech32m")
        self.assertRegex(self.address("ETH"), r"^0x[0-9a-fA-F]{40}$")
        self.assertRegex(self.address("XMR"),
                         r"^[1-9A-HJ-NP-Za-km-z]{95}$")

    def test_the_page_and_the_readme_hold_exactly_these_addresses(self):
        for page in PAGES:
            text = read(page)
            self.assertIn(about.KOFI_URL, text, page.name)
            for _label, symbol, address in about.ADDRESSES:
                self.assertEqual(text.count(address), 1,
                                 f"{symbol} in {page.name}")

    def test_no_other_address_is_written_anywhere(self):
        # (a near copy that differs by a character is how money gets lost)
        known = {a for _l, _s, a in about.ADDRESSES}
        shapes = (r"\bsp1[0-9a-z]{40,}\b", r"\b0x[0-9a-fA-F]{40}\b",
                  r"\b[48][1-9A-HJ-NP-Za-km-z]{94}\b",
                  r"\b(?:bc1|1|3)[0-9A-Za-z]{25,60}\b")
        for path in [*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"),
                     *(ROOT / ".github").rglob("*")]:
            if not path.is_file() or path.suffix == ".png":
                continue
            text = read(path)
            for shape in shapes:
                for found in re.findall(shape, text):
                    if shape.startswith(r"\b(?:bc1"):
                        continue      # (too loose for ordinary words)
                    self.assertIn(found, known, f"{path.name}: {found}")

    def test_the_sponsor_file_points_to_ko_fi_and_to_the_page(self):
        text = read(ROOT / ".github" / "FUNDING.yml")
        self.assertRegex(text, r"(?m)^ko_fi: scenprogramming\s*$")
        self.assertIn(about.DONATE_PAGE_URL, text)
        self.assertTrue(about.DONATE_PAGE_URL.endswith("docs/DONATE.md"))
        self.assertTrue((ROOT / "docs" / "DONATE.md").is_file())

    def test_the_page_says_what_the_bitcoin_address_needs(self):
        text = " ".join(read(ROOT / "docs" / "DONATE.md").split())
        self.assertIn("Silent Payments", text)
        self.assertIn("never contacts", text)       # (the offline promise)
        self.assertRegex(text, r"(?i)nothing in the program depends")

    def test_the_support_page_is_reachable_from_where_people_look(self):
        for path in ("README.md", "docs/README.md", "docs/FAQ.md",
                     ".github/SUPPORT.md"):
            self.assertIn("DONATE.md", read(ROOT / path), path)

    def test_the_module_never_touches_the_network_itself(self):
        source = read(ROOT / "about.py")
        for name in ("socket", "urllib", "http.client", "requests",
                     "ftplib"):
            self.assertNotRegex(source, rf"(?m)^\s*(import|from) {name}\b")
        # the only thing it may do with a link is open it in the browser
        self.assertEqual(len(re.findall(r"webbrowser\.open", source)), 1)


class WindowTests(AppGuiCase):
    def test_the_main_window_has_a_small_link_to_it(self):
        ex = self.explorer
        self.assertEqual(ex.about_link.cget("text"), "About & support")
        with mock.patch.object(about, "AboutDialog") as dialog:
            ex.about_link.event_generate("<Button-1>")
            ex.root.update()
        dialog.assert_called_once()
        self.assertEqual(dialog.call_args.args[1:],
                         (app_name(), version()))

    def test_the_window_shows_each_address_and_copies_it(self):
        dialog = about.AboutDialog(self.root, "Name", "9.9.9")
        self.addCleanup(dialog.destroy)
        for _label, symbol, address in about.ADDRESSES:
            self.assertEqual(dialog.entries[symbol].get(), address)
            dialog.copy_buttons[symbol].invoke()
            self.assertEqual(dialog.clipboard_get(), address)
            self.assertIn(symbol, dialog.note_var.get())

    def test_the_ko_fi_button_opens_the_page_in_the_browser(self):
        dialog = about.AboutDialog(self.root, "Name", "9.9.9")
        self.addCleanup(dialog.destroy)
        with mock.patch.object(about.webbrowser, "open") as opened:
            dialog.kofi_button.invoke()
        opened.assert_called_once_with(about.KOFI_URL)

    def test_nothing_is_opened_by_showing_the_window(self):
        with mock.patch.object(about.webbrowser, "open") as opened:
            dialog = about.AboutDialog(self.root, "Name", "9.9.9")
            self.addCleanup(dialog.destroy)
            dialog.update()
        opened.assert_not_called()

    def test_it_says_the_bitcoin_address_needs_a_wallet_that_can(self):
        dialog = about.AboutDialog(self.root, "Name", "9.9.9")
        self.addCleanup(dialog.destroy)
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                if "text" in child.keys():
                    texts.append(str(child.cget("text")))
                walk(child)

        walk(dialog)
        self.assertTrue(any("Silent Payments" in t for t in texts))


def app_name():
    import ios_backup_explorer as app
    return app.APP_NAME


def version():
    import ios_backup_explorer as app
    return app.__version__


if __name__ == "__main__":
    unittest.main()
