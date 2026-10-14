#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Create or update the repository's labels from ``.github/labels.yml``.

    python tools/sync_labels.py [--dry-run]

It uses the GitHub CLI (``gh``), which must be signed in (in the "Labels"
workflow it is, with the workflow's own token). Existing labels are updated
(``--force``), and nothing is ever deleted: a label that is not in the file is
left alone. ``--dry-run`` prints the commands instead of running them.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / ".github" / "labels.yml"
_ITEM = re.compile(r"^- name:\s*(?P<name>.+?)\s*$")
_FIELD = re.compile(r"^  (?P<key>color|description):\s*(?P<value>.*?)\s*$")


def read_labels(path=LABELS):
    """``[{"name", "color", "description"}]`` from the labels file (a plain
    list of three-line entries; no YAML package is needed)."""
    labels, current = [], None
    for number, line in enumerate(
            Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = _ITEM.match(line)
        field = _FIELD.match(line)
        if item:
            current = {"name": item.group("name").strip("'\""),
                       "color": "", "description": ""}
            labels.append(current)
        elif field and current is not None:
            current[field.group("key")] = field.group("value").strip("'\"")
        else:
            raise ValueError(f"{path}:{number}: cannot read {line!r}")
    return labels


def commands(labels):
    return [["gh", "label", "create", label["name"], "--color",
             label["color"], "--description", label["description"],
             "--force"] for label in labels]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(argv)
    labels = read_labels()
    for command in commands(labels):
        if options.dry_run:
            print(" ".join(f'"{c}"' if " " in c else c for c in command))
            continue
        result = subprocess.run(command, capture_output=True, text=True)
        status = "ok" if result.returncode == 0 else "FAILED"
        print(f"{status}: {command[3]}"
              + ("" if result.returncode == 0 else f" ({result.stderr.strip()})"))
        if result.returncode:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
