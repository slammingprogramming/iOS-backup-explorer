## What changed and why

<!-- Link the issue it answers, if there is one. -->

## How it was checked

- [ ] Tests added or updated, on **invented** data (no real data anywhere)
- [ ] Mutation-checked: I broke the code on purpose and the tests noticed (see docs/TESTING.md)
- [ ] `python -m unittest discover -s tests -t .` passes
- [ ] `python tools/check_attribution.py` and `python tools/check_version.py` pass
- [ ] Docs updated (docs/, docs/DATA_SOURCES.md) and CHANGELOG.md has an entry under *Unreleased*

## What it was verified on

<!-- Be honest: "tested on generated data only" is a fine answer, and the docs must then say it. -->

- iOS versions of real backups it was run against, if any:
- Anything that is layout-only (written from a documented layout, not a real backup):

## Privacy and credit

- [ ] No real data in code, tests, fixtures, screenshots, the description or the commit messages (counts and shapes may be described; contents may not)
- [ ] No network access, no new required dependency, original author's notices untouched
- [ ] Ideas or research taken from other projects are credited (AUTHORS, NOTICE, README)
