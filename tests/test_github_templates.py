# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The issue forms and the other files in .github: well formed, consistent with
the tools they tell people to run, and never asking for anything private.

GitHub validates a form only when someone opens it, so a mistake would be found
by the first person who tried to help. These checks read the files as text (no
YAML package is needed) so that a mistake is found here instead."""

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITHUB = ROOT / ".github"
FORMS = sorted(p for p in (GITHUB / "ISSUE_TEMPLATE").glob("*.yml")
               if p.name != "config.yml")
REPO = "https://github.com/slammingprogramming/iOS-backup-explorer"
TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}


def text(path):
    return Path(path).read_text(encoding="utf-8")


def items(form):
    """The body of a form as ``[{"type", "id", "lines"}]``."""
    body = text(form).split("\nbody:\n", 1)[1]
    result = []
    for line in body.splitlines():
        match = re.match(r"^  - type: (\S+)\s*$", line)
        if match:
            result.append({"type": match.group(1), "id": None, "lines": []})
        elif result:
            result[-1]["lines"].append(line)
            ident = re.match(r"^    id: (\S+)\s*$", line)
            if ident:
                result[-1]["id"] = ident.group(1)
    return result


def label_names():
    return set(re.findall(r"^- name: (.+?)\s*$", text(GITHUB / "labels.yml"),
                          re.M))


def load_tool(name):
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FormTests(unittest.TestCase):
    def test_the_expected_forms_exist(self):
        self.assertEqual(
            {p.name for p in FORMS},
            {"bug_report.yml", "feature_request.yml",
             "compatibility_report.yml", "tab_layout.yml", "health_kind.yml",
             "volunteer_tester.yml", "documentation.yml"})

    def test_every_form_has_what_github_needs(self):
        for form in FORMS:
            with self.subTest(form.name):
                source = text(form)
                for key in ("name", "description", "title", "labels"):
                    self.assertRegex(source, rf"(?m)^{key}: .+", key)
                self.assertIn("\nbody:\n", source)
                self.assertNotIn("\t", source)

    def test_the_fields_are_valid_and_their_ids_are_unique(self):
        for form in FORMS:
            with self.subTest(form.name):
                body = items(form)
                self.assertTrue(body)
                ids = [i["id"] for i in body if i["type"] != "markdown"]
                self.assertEqual(len(ids), len(set(ids)), ids)
                for item in body:
                    self.assertIn(item["type"], TYPES)
                    if item["type"] != "markdown":
                        self.assertRegex(item["id"] or "", r"^[a-z0-9_-]+$")
                        joined = "\n".join(item["lines"])
                        self.assertIn("label:", joined, item["id"])
                    if item["type"] == "dropdown":
                        self.assertIn("options:", "\n".join(item["lines"]))

    def test_every_form_starts_with_the_privacy_rule(self):
        for form in FORMS:
            with self.subTest(form.name):
                first = items(form)[0]
                self.assertEqual(first["type"], "markdown")
                words = " ".join(first["lines"]).replace("*", "")
                self.assertRegex(words, r"(?i)do not post your backup")
                self.assertRegex(words, r"(?i)backup")

    def test_every_form_ends_with_a_required_privacy_check(self):
        for form in FORMS:
            with self.subTest(form.name):
                last = items(form)[-1]
                self.assertEqual((last["type"], last["id"]),
                                 ("checkboxes", "privacy"))
                self.assertIn("required: true", "\n".join(last["lines"]))
                self.assertRegex("\n".join(last["lines"]), r"(?i)backup")

    def test_nothing_asks_for_a_backup_or_a_password(self):
        for form in FORMS:
            with self.subTest(form.name):
                source = text(form).lower()
                for phrase in ("upload your backup", "attach your backup",
                               "send your backup", "paste your password",
                               "share your backup", "zip of your backup"):
                    self.assertNotIn(phrase, source)
                # the only inputs that could take a secret are the ones that
                # are asked for on purpose, and none is a password
                self.assertNotRegex(source, r"(?m)^\s+label: .*password")

    def test_the_labels_they_use_exist(self):
        known = label_names()
        for form in FORMS:
            with self.subTest(form.name):
                line = re.search(r"(?m)^labels: \[(.*)\]\s*$", text(form))
                self.assertIsNotNone(line)
                used = re.findall(r'"([^"]+)"', line.group(1))
                self.assertTrue(used)
                self.assertFalse(set(used) - known, set(used) - known)

    def test_the_links_in_the_forms_go_to_this_repository_and_to_real_files(self):
        for form in FORMS:
            source = text(form)
            with self.subTest(form.name):
                for url in re.findall(r"\]\((https://[^)\s]+)\)", source):
                    self.assertTrue(url.startswith(REPO), url)
                    match = re.match(
                        re.escape(REPO) + r"/blob/main/(.+?)(#.*)?$", url)
                    if match:
                        self.assertTrue((ROOT / match.group(1)).is_file(),
                                        url)
                    template = re.search(r"template=(\S+\.yml)", url)
                    if template:
                        self.assertTrue(
                            (GITHUB / "ISSUE_TEMPLATE"
                             / template.group(1)).is_file(), url)

    def test_the_commands_they_give_exist(self):
        for form in FORMS:
            source = text(form)
            for script in set(re.findall(r"python tools/(\w+)\.py", source)):
                with self.subTest(form.name, script=script):
                    tool = (ROOT / "tools" / f"{script}.py")
                    self.assertTrue(tool.is_file(), script)
                    code = tool.read_text(encoding="utf-8")
                    code += (ROOT / "tools" / "backup_access.py").read_text(
                        encoding="utf-8")
                    for line in source.splitlines():
                        if f"tools/{script}.py" in line:
                            for flag in re.findall(r"--[a-z][a-z-]*", line):
                                self.assertIn(flag, code, f"{script} {flag}")

    def test_the_tab_list_covers_every_tab_of_the_program(self):
        from ios_apps import registry
        dropdown = "\n".join(
            "\n".join(i["lines"]) for i in items(
                GITHUB / "ISSUE_TEMPLATE" / "tab_layout.yml")
            if i["id"] == "tab")
        for entry in registry.APPS:
            self.assertIn(f"- {entry.title}\n", dropdown + "\n", entry.title)

    def test_the_form_names_are_the_ones_the_guide_uses(self):
        guide = text(ROOT / "docs" / "HELPING.md").lower()
        for form in FORMS:
            name = re.search(r"(?m)^name: (.+)$", text(form)).group(1).lower()
            with self.subTest(name):
                self.assertIn(name, guide)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = text(GITHUB / "ISSUE_TEMPLATE" / "config.yml")

    def test_blank_issues_are_off(self):
        self.assertRegex(self.config, r"(?m)^blank_issues_enabled: false\s*$")

    def test_there_is_a_private_way_to_report_a_security_problem(self):
        self.assertIn(f"{REPO}/security/advisories/new", self.config)

    def test_the_contact_links_are_complete(self):
        entries = re.findall(r"(?m)^  - name: (.+)$", self.config)
        self.assertGreaterEqual(len(entries), 3)
        self.assertEqual(len(re.findall(r"(?m)^    url: https://", self.config)),
                         len(entries))
        self.assertEqual(len(re.findall(r"(?m)^    about: .+", self.config)),
                         len(entries))
        for path in re.findall(re.escape(REPO) + r"/blob/main/(\S+)",
                               self.config):
            self.assertTrue((ROOT / path).is_file(), path)


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool("sync_labels")
        self.labels = self.tool.read_labels()

    def test_the_file_is_well_formed(self):
        names = [l["name"] for l in self.labels]
        self.assertEqual(len(names), len(set(names)))
        for label in self.labels:
            self.assertRegex(label["color"], r"^[0-9a-f]{6}$", label["name"])
            self.assertTrue(label["description"], label["name"])
            self.assertLessEqual(len(label["description"]), 100)

    def test_dependabot_uses_labels_that_exist(self):
        used = set(re.findall(r'"([^"]+)"', "".join(re.findall(
            r"(?m)^    labels: \[(.*)\]", text(GITHUB / "dependabot.yml")))))
        self.assertTrue(used)
        self.assertFalse(used - label_names(), used - label_names())

    def test_the_commands_create_or_update_and_never_delete(self):
        commands = self.tool.commands(self.labels)
        self.assertEqual(len(commands), len(self.labels))
        for command in commands:
            self.assertEqual(command[:3], ["gh", "label", "create"])
            self.assertIn("--force", command)
            self.assertNotIn("delete", command)

    def test_a_dry_run_prints_and_runs_nothing(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        out = io.StringIO()
        with mock.patch("subprocess.run") as run, redirect_stdout(out):
            self.assertEqual(self.tool.main(["--dry-run"]), 0)
        run.assert_not_called()
        self.assertEqual(len(out.getvalue().splitlines()), len(self.labels))
        self.assertIn('"help wanted"', out.getvalue())

    def test_a_failing_command_stops_with_a_message(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        failed = mock.Mock(returncode=1, stderr="not signed in")
        out = io.StringIO()
        with mock.patch("subprocess.run", return_value=failed), \
                redirect_stdout(out):
            self.assertEqual(self.tool.main([]), 1)
        self.assertIn("FAILED", out.getvalue())
        self.assertIn("not signed in", out.getvalue())

    def test_a_malformed_file_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "labels.yml"
            path.write_text("- name: a\n  colour: 000000\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.tool.read_labels(path)

    def test_quoted_values_are_read(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "labels.yml"
            path.write_text("# c\n- name: 'a b'\n  color: \"00ff00\"\n"
                            "  description: 'x: y'\n", encoding="utf-8")
            self.assertEqual(self.tool.read_labels(path), [
                {"name": "a b", "color": "00ff00", "description": "x: y"}])


class OtherFileTests(unittest.TestCase):
    def test_the_workflow_only_uses_official_actions_and_minimal_rights(self):
        source = text(GITHUB / "workflows" / "labels.yml")
        for action in re.findall(r"uses: (\S+)", source):
            self.assertTrue(action.startswith("actions/"), action)
        self.assertRegex(source, r"(?m)^permissions:\n  issues: write\s*$")
        self.assertIn("tools/sync_labels.py", source)
        self.assertIn("workflow_dispatch", source)

    def test_the_pull_request_template_asks_for_the_important_things(self):
        source = text(GITHUB / "PULL_REQUEST_TEMPLATE.md")
        for phrase in ("invented", "Mutation", "unittest", "No real data",
                       "No network access", "credited"):
            self.assertIn(phrase, source)

    def test_support_links_resolve(self):
        source = text(GITHUB / "SUPPORT.md")
        for target in re.findall(r"\]\((\.\./[^)#\s]+)", source):
            self.assertTrue((GITHUB / target).resolve().is_file(), target)

    def test_codeowners_watch_the_credit_files(self):
        source = text(GITHUB / "CODEOWNERS")
        for path in ("/LICENSE*", "/NOTICE", "/AUTHORS", "/SECURITY.md"):
            self.assertRegex(source, rf"(?m)^{re.escape(path)}\s+@\S+")

    def test_dependabot_covers_actions_and_python(self):
        source = text(GITHUB / "dependabot.yml")
        self.assertIn('package-ecosystem: "github-actions"', source)
        self.assertIn('package-ecosystem: "pip"', source)

    def test_dependabot_does_not_raise_the_minimum_versions(self):
        # fpdf2 2.8.9 and pillow-heif 1.8.1 need Python 3.10; raising the
        # minimum in requirements-optional.txt would lock out Python 3.9
        self.assertIn("versioning-strategy: increase-if-necessary",
                      text(GITHUB / "dependabot.yml"))

    def test_every_workflow_uses_the_same_version_of_an_action(self):
        found = {}
        for path in (GITHUB / "workflows").glob("*.yml"):
            for action, version in re.findall(
                    r"uses: ([\w./-]+)@(\S+)", text(path)):
                found.setdefault(action, set()).add(version)
        for action, versions in found.items():
            self.assertEqual(len(versions), 1, (action, versions))

    def test_the_helping_guide_is_linked_from_where_people_look(self):
        for path in ("README.md", "CONTRIBUTING.md", "docs/README.md",
                     "docs/IOS_VERSIONS.md", ".github/SUPPORT.md"):
            self.assertIn("HELPING.md", text(ROOT / path), path)

    def test_the_guide_names_every_tool_it_tells_people_to_run(self):
        guide = text(ROOT / "docs" / "HELPING.md")
        for script in re.findall(r"python tools/(\w+)\.py", guide):
            self.assertTrue((ROOT / "tools" / f"{script}.py").is_file())
        for tool in ("compat_report", "schema_report", "health_kinds_report"):
            self.assertIn(f"{tool}.py", guide)


if __name__ == "__main__":
    unittest.main()
