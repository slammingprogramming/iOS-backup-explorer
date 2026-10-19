# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Two tiny stand-in scripts, for testing ``ios_apps.recovery`` without the
real hashcat or CUPP (neither of which this project depends on, or can
assume a test machine has).

They are not hashcat or CUPP, and prove nothing about either program's own
behaviour; they stand in only to run ``ios_apps.recovery``'s own code
(building the command line, reading its output file, feeding CUPP's
question-and-answer order) against something that behaves enough like the
real thing to notice if that code sends the wrong arguments, parses the
wrong file or gets the order of an answer wrong.
"""

import os
import sys
import textwrap

FAKE_HASHCAT = textwrap.dedent("""\
    import itertools, sys, time
    args = sys.argv[1:]
    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default
    mode = opt("-m")
    attack = opt("-a")
    outfile = opt("--outfile")
    sleep_for = float(opt("--fake-sleep", "0"))
    hash_path = args[args.index("-a") + 2]
    with open(hash_path, encoding="utf-8") as handle:
        hash_text = handle.read().strip()
    print(f"hashcat (fake) mode={mode}", flush=True)
    print(f"Hash.Target......: {hash_text[:20]}...", flush=True)
    if sleep_for:
        time.sleep(sleep_for)
    password = None
    if attack == "0":
        wordlist = args[args.index(hash_path) + 1]
        with open(wordlist, encoding="utf-8") as handle:
            candidates = [line.rstrip("\\n") for line in handle]
        password = "FOUND-ME" if ("FOUND-ME" in hash_text
                                  and "FOUND-ME" in candidates) else None
    elif attack == "3":
        # Only "?d" (one digit) placeholders are expanded, which is all a
        # real mask this fixture is given in tests ever uses: enough to
        # notice a wrong argument order or a missing/extra one, without
        # reimplementing hashcat's own mask language. A candidate "cracks"
        # the hash when it is the exact digit string the test embedded in
        # the hash text (never a looser, accidental substring match).
        mask = args[args.index(hash_path) + 1]
        assert set(mask.replace("?d", "")) == set(), mask
        digits = mask.count("?d")
        candidates = ["".join(d) for d in
                      itertools.product("0123456789", repeat=digits)]
        marker = hash_text.split("*")[1] if "*" in hash_text else ""
        password = marker if marker in candidates else None
    if "--fake-fail" in args:
        sys.exit(2)
    if password:
        with open(outfile, "w", encoding="utf-8") as handle:
            handle.write(password + "\\n")
        print("Status...........: Cracked", flush=True)
        sys.exit(0)
    print("Status...........: Exhausted", flush=True)
    sys.exit(1)
    """)

FAKE_CUPP = textwrap.dedent("""\
    import sys
    fields = ["first_name", "surname", "nickname", "birthdate",
              "partner_name", "partner_nickname", "partner_birthdate",
              "child_name", "child_nickname", "child_birthdate",
              "pet_name", "company"]
    answers = {}
    for field in fields:
        answers[field] = input(f"> {field}: ")
    extra = input("> words? ")
    words = input("> which words: ") if extra == "y" else ""
    special = input("> special? ")
    numbers = input("> numbers? ")
    leet = input("> leet? ")
    name = answers["first_name"] or "wordlist"
    out = []
    for key in ("first_name", "surname", "nickname", "pet_name", "company"):
        if answers[key]:
            out.append(answers[key])
    if words:
        out.extend(w.strip() for w in words.split(","))
    if special == "y":
        out.append(name + "!")
    if numbers == "y":
        out.append(name + "123")
    if leet == "y":
        out.append(name.replace("e", "3"))
    with open(f"{name}.txt", "w", encoding="utf-8") as handle:
        handle.write("\\n".join(out) + "\\n")
    print("wordlist saved as " + name + ".txt")
    """)


def write(folder, name, source):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    return path


def fake_hashcat(folder):
    """A script path to run with ``sys.executable`` that behaves like
    hashcat only enough for :class:`ios_apps.recovery.HashcatRun`'s own
    plumbing to be tested: it "cracks" a wordlist attack whose hash text
    contains ``FOUND-ME`` and whose wordlist holds that same word, and
    otherwise reports exhausted."""
    return write(folder, "fake_hashcat.py", FAKE_HASHCAT)


def fake_cupp(folder):
    """A script path that asks the same questions, in the same order, as
    ``Mebus/cupp``'s ``interactive()`` (see ``CUPP_PROFILE_FIELDS``), and
    writes a short wordlist from the answers."""
    return write(folder, "fake_cupp.py", FAKE_CUPP)
