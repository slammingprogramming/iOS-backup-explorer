# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""What a release is made of (tools/release.py) and the workflow that
publishes it (.github/workflows/release.yml)."""

import hashlib
import importlib.util
import io
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import ios_backup_explorer as app

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "release_tool", ROOT / "tools" / "release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def have_git():
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


CHANGELOG = """# Changelog

## [Unreleased]

Nothing yet.

## [2.1.0-rc.1] - 2026-12-01

Candidate.

### Added
- the new thing

## [2.0.0] - 2026-10-10

Summary of two.

### Fixed
- an old thing

## [1.0.0 — BackupLens, original project] - 2026-04-03

The first.
"""


class TagTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_version_of_a_tag(self):
        self.assertEqual(self.tool.version_of("v2.1.0"), "2.1.0")
        self.assertEqual(self.tool.version_of("v2.1.0-rc.1"), "2.1.0-rc.1")

    def test_what_is_not_a_version_tag(self):
        for bad in ("2.1.0", "v2.1", "v2.1.0.0", "vx", "release-2.1.0", "v",
                    "v02.1.0"):
            with self.subTest(tag=bad), self.assertRaises(ValueError):
                self.tool.version_of(bad)

    def test_pre_releases(self):
        self.assertTrue(self.tool.is_prerelease("2.1.0-rc.1"))
        self.assertTrue(self.tool.is_prerelease("3.0.0-alpha"))
        self.assertFalse(self.tool.is_prerelease("2.1.0"))
        # build metadata does not make a pre-release; a dash inside it too
        self.assertFalse(self.tool.is_prerelease("2.1.0+build-5"))
        self.assertTrue(self.tool.is_prerelease("2.1.0-rc.1+build-5"))


class FakeRepository(unittest.TestCase):
    def repo(self, code="2.0.0", changelog=CHANGELOG, badge=None):
        root = Path(tempfile.mkdtemp(prefix="ibe-release-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "ios_backup_explorer.py").write_text(
            f'__version__ = "{code}"\n', encoding="utf-8")
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        (root / "README.md").write_text(
            '<img src="https://img.shields.io/badge/version-'
            f'{(badge or code).replace("-", "--")}-blue">', encoding="utf-8")
        return root


class NotesTests(FakeRepository):
    def setUp(self):
        self.tool = load_tool()
        self.root = self.repo()

    def test_the_section_of_a_version(self):
        text = self.tool.section("2.0.0", self.root)
        self.assertTrue(text.startswith("Summary of two."), text)
        self.assertIn("- an old thing", text)
        self.assertNotIn("the new thing", text)
        self.assertNotIn("The first.", text)

    def test_the_first_and_the_last_section(self):
        self.assertIn("the new thing",
                      self.tool.section("2.1.0-rc.1", self.root))
        self.assertEqual(self.tool.section("1.0.0 — BackupLens, "
                                           "original project", self.root),
                         "The first.")

    def test_a_version_is_not_a_pattern(self):
        # the dots are dots, not "any character"
        self.assertIsNone(self.tool.section("2x0y0", self.root))
        self.assertIsNone(self.tool.section("2.0", self.root))
        self.assertIsNone(self.tool.section("3.0.0", self.root))
        root = self.repo("2.0.0", "## [2a0b0] - 2026-10-10\n\ntext\n")
        self.assertIsNone(self.tool.section("2.0.0", root))

    def test_notes_have_the_section_and_the_download_guide(self):
        notes = self.tool.notes("2.0.0", self.root)
        self.assertIn("Summary of two.", notes)
        self.assertIn("iOS-Backup-Explorer-2.0.0.zip", notes)
        self.assertIn("SHA256SUMS", notes)
        self.assertIn("python ios_backup_explorer.py", notes)
        self.assertIn("/blob/v2.0.0/docs/INSTALL.md", notes)
        self.assertNotIn("Nothing yet.", notes)

    def test_notes_for_a_missing_version(self):
        with self.assertRaises(ValueError):
            self.tool.notes("9.9.9", self.root)

    def test_an_empty_section_is_missing(self):
        root = self.repo("2.0.0", "## [2.0.0] - 2026-10-10\n\n## [1.0.0] - "
                         "2026-01-01\n\nold\n")
        self.assertIsNone(self.tool.section("2.0.0", root))


class VerifyTests(FakeRepository):
    def setUp(self):
        self.tool = load_tool()

    def test_a_tag_that_matches(self):
        root = self.repo("2.1.0-rc.1")
        self.assertEqual(self.tool.problems("v2.1.0-rc.1", root), [])

    def test_a_tag_that_is_not_the_version(self):
        found = self.tool.problems("v2.0.1", self.repo("2.0.0"))
        self.assertTrue(any("the tag is v2.0.1 but __version__ is 2.0.0" in p
                            for p in found),
                        found)

    def test_a_tag_that_is_not_a_tag(self):
        found = self.tool.problems("main", self.repo())
        self.assertEqual(len(found), 1)
        self.assertIn("not a version tag", found[0])

    def test_a_version_the_changelog_does_not_know(self):
        root = self.repo("2.2.0", CHANGELOG)
        found = self.tool.problems("v2.2.0", root)
        self.assertTrue(any("no section for 2.2.0" in p for p in found),
                        found)

    def test_this_repository_can_be_released_as_it_is(self):
        self.assertEqual(self.tool.problems(f"v{app.__version__}"), [])

    def test_the_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.tool.main(["verify", f"v{app.__version__}"]),
                             0)
            self.assertEqual(self.tool.main(["prerelease", "v2.1.0-rc.1"]), 0)
            self.assertEqual(self.tool.main(["prerelease", "v2.1.0"]), 0)
        self.assertEqual(out.getvalue().split("\n")[1:3], ["true", "false"])
        with redirect_stdout(out):
            self.assertEqual(self.tool.main(["verify", "v0.0.1"]), 1)
        with redirect_stderr(err), self.assertRaises(SystemExit):
            self.tool.main(["notes", "nonsense"])


@unittest.skipUnless(have_git(), "needs git")
class BuildTests(FakeRepository):
    def setUp(self):
        self.tool = load_tool()
        self.root = self.repo()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "page.md").write_text("page\n", encoding="utf-8")
        (self.root / "scratch.txt").write_text("not committed\n")
        self.git("init", "-q")
        self.git("add", "ios_backup_explorer.py", "CHANGELOG.md", "README.md",
                 "docs")
        self.git("-c", "user.name=T", "-c", "user.email=t@example.com",
                 "-c", "commit.gpgsign=false", "commit", "-q", "-m", "x")
        self.git("-c", "user.name=T", "-c", "user.email=t@example.com",
                 "-c", "tag.gpgsign=false", "tag", "-a", "v2.0.0", "-m", "x")
        self.out = self.root / "dist"

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root)] + list(args),
                       check=True, capture_output=True)

    def test_what_is_made(self):
        made = self.tool.build("2.0.0", "v2.0.0", self.out, self.root)
        self.assertEqual([p.name for p in made],
                         ["iOS-Backup-Explorer-2.0.0.zip",
                          "iOS-Backup-Explorer-2.0.0.tar.gz", "SHA256SUMS"])
        self.assertTrue(all(p.exists() for p in made))

    def test_only_committed_files_in_a_folder_named_for_the_version(self):
        self.tool.build("2.0.0", "v2.0.0", self.out, self.root)
        with zipfile.ZipFile(self.out / "iOS-Backup-Explorer-2.0.0.zip") as z:
            names = sorted(n for n in z.namelist() if not n.endswith("/"))
        self.assertEqual(names, [
            "iOS-Backup-Explorer-2.0.0/CHANGELOG.md",
            "iOS-Backup-Explorer-2.0.0/README.md",
            "iOS-Backup-Explorer-2.0.0/docs/page.md",
            "iOS-Backup-Explorer-2.0.0/ios_backup_explorer.py"])
        with tarfile.open(self.out / "iOS-Backup-Explorer-2.0.0.tar.gz") as t:
            self.assertEqual(
                sorted(m.name for m in t.getmembers() if m.isfile()), names)

    def test_the_files_are_what_their_names_say(self):
        self.tool.build("2.0.0", "v2.0.0", self.out, self.root)
        zipped = (self.out / "iOS-Backup-Explorer-2.0.0.zip").read_bytes()
        gzipped = (self.out / "iOS-Backup-Explorer-2.0.0.tar.gz").read_bytes()
        self.assertEqual(zipped[:2], b"PK")
        self.assertEqual(gzipped[:2], b"\x1f\x8b")          # gzip

    def test_the_checksums_are_right_and_in_the_usual_format(self):
        self.tool.build("2.0.0", "v2.0.0", self.out, self.root)
        lines = (self.out / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            digest, name = re.match(r"^([0-9a-f]{64})  (\S+)$", line).groups()
            data = (self.out / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
        self.assertNotIn(b"\r", (self.out / "SHA256SUMS").read_bytes())

    def test_building_twice_gives_the_same_bytes(self):
        self.tool.build("2.0.0", "v2.0.0", self.out, self.root)
        first = (self.out / "SHA256SUMS").read_text()
        self.tool.build("2.0.0", "v2.0.0", self.root / "again", self.root)
        self.assertEqual((self.root / "again" / "SHA256SUMS").read_text(),
                         first)

    def test_an_unknown_tag_fails_and_leaves_no_checksums(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.tool.build("9.9.9", "v9.9.9", self.out, self.root)
        self.assertFalse((self.out / "SHA256SUMS").exists())


class WorkflowTests(unittest.TestCase):
    """The workflow is not run here, but its shape is what keeps a release
    safe, so it is checked."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def job(self, name):
        match = re.search(r"^  " + name + r":\n(.*?)(?=^  \w[\w-]*:\n|\Z)",
                          self.text, re.M | re.S)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_it_runs_for_version_tags_only(self):
        self.assertRegex(self.text, r'tags:\s+- "v\[0-9\]\+\.\[0-9\]\+\.'
                                    r'\[0-9\]\+\*"')
        self.assertNotIn("branches:", self.text)

    def test_only_the_publishing_job_can_write(self):
        self.assertRegex(self.text, re.compile(
            r"^permissions:\n  contents: read\n", re.M))
        self.assertEqual(self.text.count("contents: write"), 1)
        self.assertIn("contents: write", self.job("publish"))

    def test_nothing_is_published_before_the_checks_pass(self):
        self.assertRegex(self.job("publish"),
                         r"needs: \[verify, tests, attribution\]")
        self.assertIn("needs: verify", self.job("tests"))
        self.assertIn("uses: ./.github/workflows/tests.yml",
                      self.job("tests"))
        self.assertIn("uses: ./.github/workflows/attribution.yml",
                      self.job("attribution"))

    def test_the_reused_workflows_can_be_called(self):
        for name in ("tests.yml", "attribution.yml"):
            text = (WORKFLOW.parent / name).read_text(encoding="utf-8")
            self.assertIn("workflow_call:", text, name)

    def test_the_tag_must_be_the_version_and_on_the_default_branch(self):
        verify = self.job("verify")
        self.assertIn('tools/release.py verify "$GITHUB_REF_NAME"', verify)
        self.assertIn("merge-base --is-ancestor", verify)

    def test_a_tag_is_never_moved(self):
        publish = self.job("publish")
        self.assertIn("--verify-tag", publish)
        self.assertNotIn("git tag", publish)
        self.assertNotIn("git push", publish)

    def test_every_tool_it_calls_exists(self):
        for name in set(re.findall(r"tools/([\w.]+\.py)", self.text)):
            self.assertTrue((ROOT / "tools" / name).exists(), name)

    def test_the_actions_are_pinned_to_a_major_version(self):
        for use in re.findall(r"uses: (\S+@\S+)", self.text):
            self.assertRegex(use, r"@v\d+$", use)

    def test_untrusted_text_is_not_spliced_into_scripts(self):
        # ${{ }} inside a "run:" block would let a tag name inject commands;
        # values reach the scripts through environment variables
        script = None                      # the indent of the "run:" key
        for line in self.text.splitlines():
            indent = len(line) - len(line.lstrip())
            if script is not None and line.strip() and indent <= script:
                script = None
            if script is not None:
                self.assertNotIn("${{", line)
            key = re.match(r"^(\s*)(?:- )?run:(.*)$", line)
            if key:
                self.assertNotIn("${{", key.group(2))
                script = len(key.group(1))


if __name__ == "__main__":
    unittest.main()
