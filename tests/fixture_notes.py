# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake Notes database (NoteStore.sqlite) for tests.

Everything here is invented. The tables and columns follow the layout iOS
uses, trimmed to what the reader looks at. The note text is encoded by
the small protobuf writer below, following the layout the reader decodes
(the same understanding of the format on both sides: there is no real
iPhone data in the tests).
"""

import gzip

from tests.fixture_apps import PNG_BYTES, database_bytes

NOTES_DOMAIN = "AppDomainGroup-group.com.apple.notes"
NOTES_ACCOUNT = "Accounts/AAAAAAAA-0000-0000-0000-000000000001"
NOTES_FILES = {
    # (an older version of a file, then the newest)
    "photo_old": f"{NOTES_ACCOUNT}/Media/MEDIA-PHOTO/0_GEN-OLD/photo.png",
    "photo": f"{NOTES_ACCOUNT}/Media/MEDIA-PHOTO/1_GEN-NEW/photo.png",
    "voice": f"{NOTES_ACCOUNT}/Media/MEDIA-VOICE/1_GEN-V/Recording.m4a",
}
OLD_PHOTO = b"old version of the photo"
VOICE = b"\x00\x00\x00\x18ftypM4A voice recording"


def pb_varint(number):
    number &= (1 << 64) - 1                  # negative numbers: 64 bits
    out = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        out.append(byte | (0x80 if number else 0))
        if not number:
            return bytes(out)


def pb_field(number, value):
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        return pb_varint(number << 3) + pb_varint(value)
    if isinstance(value, str):
        value = value.encode("utf-8")
    return pb_varint(number << 3 | 2) + pb_varint(len(value)) + value


def run(text, style=-1, indent=0, done=None, bold=False, italic=False,
        underline=False, strike=False, link=None, attachment=None):
    """One attribute run covering *text*, as iOS stores it."""
    length = len(text.encode("utf-16-le", "surrogatepass")) // 2
    paragraph = pb_field(1, style)
    if indent:
        paragraph += pb_field(4, indent)
    if done is not None:
        paragraph += pb_field(5, pb_field(1, b"\x01" * 16)
                              + pb_field(2, int(done)))
    out = pb_field(1, length) + pb_field(2, paragraph)
    hints = int(bold) | int(italic) << 1
    if hints:
        out += pb_field(5, hints)
    if underline:
        out += pb_field(6, 1)
    if strike:
        out += pb_field(7, 1)
    if link:
        out += pb_field(9, link)
    if attachment:
        out += pb_field(12, pb_field(1, attachment[0])
                        + pb_field(2, attachment[1]))
    return text, out


def blob(runs, gzip_it=True):
    """``ZDATA`` for a note made of ``run(...)`` results."""
    text = "".join(t for t, _ in runs)
    note = pb_field(2, text) + b"".join(pb_field(5, r) for _, r in runs)
    data = pb_field(2, pb_field(2, 0) + pb_field(3, note))
    return gzip.compress(data) if gzip_it else data


SCHEMA = """
CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR,
    Z_SUPER INTEGER, Z_MAX INTEGER);
CREATE TABLE ZICCLOUDSYNCINGOBJECT (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZTITLE1 VARCHAR,
    ZTITLE2 VARCHAR, ZTITLE VARCHAR, ZNAME VARCHAR, ZSNIPPET VARCHAR,
    ZFOLDER INTEGER, ZPARENT INTEGER, ZACCOUNT3 INTEGER, ZNOTEDATA INTEGER,
    ZCREATIONDATE3 TIMESTAMP, ZMODIFICATIONDATE1 TIMESTAMP,
    ZIDENTIFIER VARCHAR, ZMARKEDFORDELETION INTEGER, ZISPINNED INTEGER,
    ZISPASSWORDPROTECTED INTEGER, ZFOLDERTYPE INTEGER,
    ZNOTE INTEGER, ZMEDIA INTEGER, ZTYPEUTI VARCHAR, ZFILENAME VARCHAR,
    ZURLSTRING VARCHAR, ZALTTEXT VARCHAR);
CREATE TABLE ZICNOTEDATA (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER,
    ZNOTE INTEGER, ZDATA BLOB);
"""

_COLUMNS = ("title1 title2 title name snippet folder account created modified "
            "ident deleted pinned locked foldertype note media uti filename "
            "url alt parent").split()
_INSERT = ("INSERT INTO ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZTITLE1, ZTITLE2, "
           "ZTITLE, ZNAME, ZSNIPPET, ZFOLDER, ZACCOUNT3, ZCREATIONDATE3, "
           "ZMODIFICATIONDATE1, ZIDENTIFIER, ZMARKEDFORDELETION, ZISPINNED, "
           "ZISPASSWORDPROTECTED, ZFOLDERTYPE, ZNOTE, ZMEDIA, ZTYPEUTI, "
           "ZFILENAME, ZURLSTRING, ZALTTEXT, ZPARENT) VALUES ("
           + ",".join("?" * 23) + ")")

PHOTO = ("ATT-PHOTO", "public.png")
TAG = ("ATT-TAG", "com.apple.notes.inlinetextattachment.hashtag")
LINK = ("ATT-LINK", "public.url")
VOICE_ATT = ("ATT-VOICE", "com.apple.m4a-audio")


def build(conn):
    """Folders: 2 Notes, 3 Recipes (with 5 Soups inside), 4 Recently
    Deleted, all in the account 1 "iCloud"."""
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, ?)",
                     [(3, "ICAttachment"), (8, "ICNote"), (11, "ICMedia"),
                      (12, "ICAccount"), (15, "ICFolder")])

    def row(pk, ent, **kw):
        conn.execute(_INSERT, (pk, ent) + tuple(kw.get(n) for n in _COLUMNS))

    def note(pk, folder, title, runs, created, modified, snippet="",
             locked=0, pinned=0, deleted=0, data=None):
        row(pk, 8, title1=title, snippet=snippet, folder=folder, account=1,
            created=created, modified=modified, ident=f"NOTE-{pk}",
            deleted=deleted, pinned=pinned, locked=locked)
        cur = conn.execute(
            "INSERT INTO ZICNOTEDATA (ZNOTE, ZDATA) VALUES (?, ?)",
            (pk, data if data is not None else blob(runs)))
        conn.execute("UPDATE ZICCLOUDSYNCINGOBJECT SET ZNOTEDATA = ? "
                     "WHERE Z_PK = ?", (cur.lastrowid, pk))

    row(1, 12, name="iCloud")
    row(2, 15, title2="Notes", account=1, foldertype=0)
    row(3, 15, title2="Recipes", account=1, foldertype=0)
    row(4, 15, title2="Recently Deleted", account=1, foldertype=1)
    row(5, 15, title2="Soups", account=1, foldertype=0, parent=3)

    note(10, 2, "Shopping list", [
        run("Shopping list\n", style=0),
        run("Things to get\n", style=1),
        run("Milk\n", style=103, done=False),
        run("Eggs\n", style=103, done=True),
        run("Apples\n", style=100),
        run("Green ones\n", style=100, indent=1),
        run("Wash up\n", style=102),
        run("Cook dinner\n", style=102),
        run("Party \U0001F389 ", style=-1),
        run("time", bold=True),
        run(" and ", style=-1),
        run("site", link="https://example.com/shop", underline=True),
        run("\n"),
        run("\ufffc", attachment=PHOTO),
        run("\n"),
        run("\ufffc", attachment=TAG),
        run(" ", style=-1),
        run("\ufffc", attachment=LINK),
        run("\n"),
    ], created=770_000_000, modified=778_100_000, snippet="Things to get",
        pinned=1)
    note(11, 3, "Pancakes", [
        run("Pancakes\n", style=0),
        run("Mix flour\n", style=102),
        run("Pour batter\n", style=102),
        run("\ufffc", attachment=VOICE_ATT),
        run("\n"),
    ], created=760_000_000, modified=777_000_000)
    note(12, 2, "Secret", [], created=750_000_000, modified=776_000_000,
         locked=1, data=b"\x01\x02 encrypted bytes, not a note")
    note(13, 4, "Old idea", [run("Old idea\n", style=0), run("never mind\n")],
         created=740_000_000, modified=775_000_000)
    note(14, 2, None, [run("No stored title here\n"), run("second line\n")],
         created=730_000_000, modified=779_000_000)
    note(15, 2, "Broken", [], created=720_000_000, modified=774_000_000,
         snippet="what is left of it", data=b"\x1f\x8bnot really gzip")
    note(16, 2, "Removed", [run("gone\n")], created=1, modified=2, deleted=1)
    note(17, 5, "Tomato soup", [run("Tomato soup\n", style=0),
                                run("2 tomatoes\n")],
         created=710_000_000, modified=773_000_000)
    note(18, 2, "Empty", [], created=700_000_000, modified=772_000_000,
         data=blob([]))
    # media rows and attachment rows
    row(20, 11, ident="MEDIA-PHOTO", filename="photo.png")
    row(21, 11, ident="MEDIA-VOICE", filename="Recording.m4a")
    row(22, 3, note=10, ident=PHOTO[0], uti=PHOTO[1], media=20)
    row(23, 3, note=10, ident=TAG[0], uti=TAG[1], alt="#home")
    row(24, 3, note=10, ident=LINK[0], uti=LINK[1],
        url="https://example.com/", title="Example site")
    row(25, 3, note=11, ident=VOICE_ATT[0], uti=VOICE_ATT[1], media=21)
    conn.commit()


def backup_files(include_media=True):
    """The ``(domain, path, bytes)`` list for a backup that has the notes."""
    files = [(NOTES_DOMAIN, "NoteStore.sqlite", database_bytes(build))]
    if include_media:
        files += [(NOTES_DOMAIN, NOTES_FILES["photo_old"], OLD_PHOTO),
                  (NOTES_DOMAIN, NOTES_FILES["photo"], PNG_BYTES),
                  (NOTES_DOMAIN, NOTES_FILES["voice"], VOICE)]
    return files
