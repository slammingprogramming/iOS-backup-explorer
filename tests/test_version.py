# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The version is written down in one place and checked everywhere else."""

import importlib.util
import io
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import ios_backup_explorer as app

ROOT = Path(__file__).resolve().parent.parent


def load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_version", ROOT / "tools" / "check_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.check = load_checker()

    def test_the_repository_is_consistent(self):
        self.assertEqual(self.check.problems(), [])

    def test_the_version_is_semantic(self):
        self.assertRegex(app.__version__, self.check.SEMVER)
        self.assertEqual(self.check.code_version(), app.__version__)

    def test_this_is_the_second_major_version_of_the_project(self):
        self.assertTrue(app.__version__.startswith("2."))

    def test_the_newest_release_is_the_version(self):
        self.assertEqual(self.check.releases()[0][0], app.__version__)

    def test_the_command_line_prints_it(self):
        out = io.StringIO()
        with redirect_stdout(out):
            app.main(["--version"])
        self.assertEqual(out.getvalue().strip(),
                         f"{app.APP_NAME} {app.__version__}")


class CheckerTests(unittest.TestCase):
    """The checker itself, on small made-up repositories."""

    def setUp(self):
        self.check = load_checker()
        self.root = Path(tempfile.mkdtemp(prefix="ibe-version-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def repo(self, code="2.1.0", changelog="## [2.1.0] - 2026-11-01\n",
             badge="2.1.0"):
        (self.root / "ios_backup_explorer.py").write_text(
            f'__version__ = "{code}"\n', encoding="utf-8")
        (self.root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n" + changelog,
            encoding="utf-8")
        (self.root / "README.md").write_text(
            f'<img src="https://img.shields.io/badge/version-{badge}-blue">',
            encoding="utf-8")
        return self.check.problems(self.root)

    def test_a_consistent_repository(self):
        self.assertEqual(self.repo(), [])

    def test_a_pre_release(self):
        self.assertEqual(self.repo(
            "2.1.0-rc.1", "## [2.1.0-rc.1] - 2026-11-01\n", "2.1.0--rc.1"),
            [])

    def test_not_a_semantic_version(self):
        for bad in ("2.1", "v2.1.0", "2.01.0", "2.1.0.0", "two"):
            with self.subTest(bad=bad):
                found = self.repo(bad, f"## [{bad}] - 2026-11-01\n", bad)
                self.assertTrue(any("Semantic" in p for p in found), found)

    def test_a_changelog_that_is_behind_or_ahead(self):
        found = self.repo("2.2.0", "## [2.1.0] - 2026-11-01\n", "2.2.0")
        self.assertTrue(any("newest release" in p for p in found), found)
        found = self.repo("2.1.0", "## [2.2.0] - 2026-11-01\n"
                          "## [2.1.0] - 2026-10-01\n", "2.1.0")
        self.assertTrue(any("newest release" in p for p in found), found)

    def test_no_release_heading(self):
        found = self.repo("2.1.0", "Nothing here.\n", "2.1.0")
        self.assertTrue(any("no '## [x.y.z]" in p for p in found), found)

    def test_a_version_listed_twice(self):
        found = self.repo("2.1.0", "## [2.1.0] - 2026-11-01\n"
                          "## [2.1.0] - 2026-10-01\n", "2.1.0")
        self.assertTrue(any("twice" in p for p in found), found)

    def test_a_badge_that_disagrees_or_is_missing(self):
        found = self.repo(badge="2.0.0")
        self.assertTrue(any("badge" in p for p in found), found)
        (self.root / "README.md").write_text("no badge", encoding="utf-8")
        self.assertTrue(any("no version badge" in p
                            for p in self.check.problems(self.root)))

    def test_no_version_in_the_code(self):
        (self.root / "ios_backup_explorer.py").write_text(
            "x = 1\n", encoding="utf-8")
        self.assertEqual(self.check.problems(self.root),
                         ["ios_backup_explorer.py has no __version__"])

    def test_the_regular_expression_for_releases(self):
        text = ("## [1.0.0 \u2014 BackupLens, original project] - 2026-04-03\n"
                "## [Unreleased]\n")
        self.assertEqual(
            [m.group("version") for m in self.check.RELEASE.finditer(text)],
            ["1.0.0 \u2014 BackupLens, original project"])


if __name__ == "__main__":
    unittest.main()
