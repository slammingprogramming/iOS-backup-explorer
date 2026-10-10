# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The demo phone's photos, voice memos and notes."""

from . import ago, cocoa, pictures

CAMERA = "CameraRollDomain"
VIDEO = b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  " + b"video" * 400
AUDIO = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A " + b"audio" * 600

# (scene, days ago, favourite, hidden, trashed, place, albums)
PLACE = {"home": (39.7990, -89.6440), "lake": (39.8213, -89.5907),
         "ridge": (39.9152, -89.7203), "city": (39.7817, -89.6501)}
PHOTOS = [
    ("sunset", 1, 1, 0, 0, "home", ("Favourites",)),
    ("lake", 2, 0, 0, 0, "lake", ("Hiking",)),
    ("mountains", 2, 1, 0, 0, "ridge", ("Hiking", "Favourites")),
    ("forest", 2, 0, 0, 0, "ridge", ("Hiking",)),
    ("flowers", 4, 0, 0, 0, "home", ("Garden",)),
    ("city", 5, 0, 0, 0, "city", ()),
    ("night", 5, 0, 0, 0, "city", ()),
    ("beach", 9, 1, 0, 0, None, ("Lisbon Trip", "Favourites")),
    ("sunset", 9, 0, 0, 0, None, ("Lisbon Trip",)),
    ("city", 10, 0, 0, 0, None, ("Lisbon Trip",)),
    ("beach", 10, 0, 0, 0, None, ("Lisbon Trip",)),
    ("night", 11, 0, 0, 0, None, ("Lisbon Trip",)),
    ("lake", 14, 0, 0, 0, "lake", ("Hiking",)),
    ("forest", 14, 0, 0, 0, "ridge", ("Hiking",)),
    ("flowers", 17, 0, 0, 0, "home", ("Garden",)),
    ("mountains", 20, 0, 0, 0, "ridge", ("Hiking",)),
    ("sunset", 23, 0, 0, 0, "home", ()),
    ("flowers", 26, 1, 0, 0, "home", ("Garden", "Favourites")),
    ("lake", 31, 0, 0, 0, "lake", ()),
    ("city", 36, 0, 0, 0, "city", ()),
    ("beach", 41, 0, 0, 0, None, ()),
    ("night", 44, 0, 1, 0, "city", ()),
    ("forest", 52, 0, 0, 0, "ridge", ("Hiking",)),
    ("mountains", 58, 0, 0, 0, "ridge", ()),
    ("sunset", 63, 0, 0, 1, "home", ()),
    ("lake", 70, 0, 0, 0, "lake", ()),
]
VIDEOS = [(3, 12.4, "lake"), (10, 31.0, None), (21, 8.2, "home")]
ALBUMS = ("Favourites", "Hiking", "Lisbon Trip", "Garden")


def photos(writer):
    from tests import fixture_media as fm
    names = {}

    def build(conn):
        conn.executescript(fm.SCHEMA)
        for number, title in enumerate(ALBUMS, 1):
            conn.execute("INSERT INTO ZGENERICALBUM (Z_PK, ZTITLE, ZKIND, "
                         "ZTRASHEDSTATE) VALUES (?,?,2,0)", (number, title))
        pk = 0
        entries = []
        for scene, days, favourite, hidden, trashed, place, albums in PHOTOS:
            pk += 1
            name = f"IMG_{3000 + pk}.JPG"
            when = ago(days=days, hours=pk % 7, minutes=pk * 3)
            entries.append((pk, name, when, favourite, hidden, trashed,
                            place, albums, scene, 0, 0.0))
        for days, seconds, place in VIDEOS:
            pk += 1
            entries.append((pk, f"IMG_{3000 + pk}.MOV",
                            ago(days=days, hours=3), 0, 0, 0, place, (),
                            None, 1, seconds))
        for (pk, name, when, favourite, hidden, trashed, place, albums,
             scene, kind, duration) in entries:
            lat, lon = PLACE[place] if place else (None, None)
            conn.execute(
                "INSERT INTO ZASSET (Z_PK, ZDIRECTORY, ZFILENAME, "
                "ZDATECREATED, ZKIND, ZFAVORITE, ZHIDDEN, ZTRASHEDSTATE, "
                "ZWIDTH, ZHEIGHT, ZDURATION, ZLATITUDE, ZLONGITUDE) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pk, "DCIM/100APPLE", name, cocoa(when), kind, favourite,
                 hidden, trashed, 640, 480, duration, lat, lon))
            for title in albums:
                conn.execute("INSERT INTO Z_26ASSETS VALUES (?, ?)",
                             (ALBUMS.index(title) + 1, pk))
            names[pk] = (name, when, scene)

    writer.database(CAMERA, "Media/PhotoData/Photos.sqlite", build)
    for pk, (name, when, scene) in names.items():
        data = (pictures.jpeg(scene, seed=pk * 7) if scene else VIDEO)
        writer.file(CAMERA, f"Media/DCIM/100APPLE/{name}", data, when)


# ── Voice memos ──────────────────────────────────────────────

MEMOS = [
    ("Meeting notes – Q4 planning", 1, 1860.0),
    ("Song idea 7", 3, 74.5),
    ("Grocery list", 4, 22.0),
    ("Recipe: lemon cake", 9, 188.0),
    ("Intro to Astronomy, lecture 3", 12, 3120.0),
    ("Birthday surprise ideas", 18, 96.0),
    ("Voice memo 14", 25, 8.0),
]


def voice_memos(writer):
    group = "AppDomainGroup-group.com.apple.VoiceMemos.shared"
    rows = []
    for number, (title, days, seconds) in enumerate(MEMOS, 1):
        when = ago(days=days, hours=number)
        stamp = when.strftime("%Y%m%d %H%M%S")
        name = f"{stamp}-{number:04X}ABCD.m4a"
        rows.append((title, when, seconds, name))
        writer.file(group, f"Recordings/{name}",
                    AUDIO * (1 + number % 3), when)

    def build(conn):
        from tests import fixture_media as fm
        conn.executescript(fm.MEMO_SCHEMA)
        for title, when, seconds, name in rows:
            conn.execute(
                "INSERT INTO ZCLOUDRECORDING (ZCUSTOMLABEL, ZDATE, "
                "ZDURATION, ZPATH) VALUES (?,?,?,?)",
                (title, cocoa(when), seconds, name))
    writer.database(group, "Recordings/CloudRecordings.db", build)


# ── Notes ────────────────────────────────────────────────────

NOTES_DOMAIN = "AppDomainGroup-group.com.apple.notes"
ACCOUNT = "Accounts/AAAAAAAA-0000-0000-0000-00000000DEMO"


def notes(writer):
    from tests import fixture_notes as fn
    media = {
        "MEDIA-CAKE": ("lemon-cake.jpg", pictures.jpeg("flowers", seed=5)),
        "MEDIA-MAP": ("route.jpg", pictures.jpeg("mountains", seed=6)),
        "MEDIA-VOICE": ("Recording.m4a", AUDIO),
        "MEDIA-CALL": ("call-audio.MOV", VIDEO),
    }
    paths = {key: f"{ACCOUNT}/Media/{key}/1_GEN/{name}"
             for key, (name, _data) in media.items()}
    run = fn.run

    def build(conn):
        conn.executescript(fn.SCHEMA)
        conn.executemany(
            "INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME) VALUES (?, ?)",
            [(3, "ICAttachment"), (8, "ICNote"), (11, "ICMedia"),
             (12, "ICAccount"), (15, "ICFolder")])

        def row(pk, ent, **kw):
            conn.execute(fn._INSERT, (pk, ent) + tuple(
                kw.get(n) for n in fn._COLUMNS))

        def note(pk, folder, title, runs, days, snippet="", pinned=0,
                 locked=0, deleted=0, data=None):
            created = cocoa(ago(days=days + 20))
            changed = cocoa(ago(days=days))
            row(pk, 8, title1=title, snippet=snippet, folder=folder,
                account=1, created=created, modified=changed,
                ident=f"NOTE-{pk}", deleted=deleted, pinned=pinned,
                locked=locked)
            cur = conn.execute(
                "INSERT INTO ZICNOTEDATA (ZNOTE, ZDATA) VALUES (?, ?)",
                (pk, data if data is not None else fn.blob(runs)))
            conn.execute("UPDATE ZICCLOUDSYNCINGOBJECT SET ZNOTEDATA = ? "
                         "WHERE Z_PK = ?", (cur.lastrowid, pk))

        row(1, 12, name="iCloud")
        row(2, 15, title2="Notes", account=1, foldertype=0)
        row(3, 15, title2="Recipes", account=1, foldertype=0)
        row(4, 15, title2="Recently Deleted", account=1, foldertype=1)
        row(5, 15, title2="Soups", account=1, foldertype=0, parent=3)
        row(6, 15, title2="Travel", account=1, foldertype=0)
        row(7, 15, title2="Work", account=1, foldertype=0)

        note(10, 6, "Packing list – Lisbon", [
            run("Packing list – Lisbon\n", style=0),
            run("Documents\n", style=1),
            run("Passport\n", style=103, done=True),
            run("Boarding passes\n", style=103, done=True),
            run("Travel insurance\n", style=103, done=False),
            run("Clothes\n", style=1),
            run("Light jacket\n", style=103, done=True),
            run("Comfortable walking shoes\n", style=103, done=False),
            run("Sunglasses\n", style=103, done=False),
            run("Remember to ", style=-1), run("charge the camera", bold=True),
            run(" the night before.\n"),
        ], 8, snippet="Documents", pinned=1)
        note(11, 3, "Lemon cake", [
            run("Lemon cake\n", style=0),
            run("Ingredients\n", style=1),
            run("200 g flour\n", style=100),
            run("150 g sugar\n", style=100),
            run("3 eggs\n", style=100),
            run("2 lemons, zest and juice\n", style=100),
            run("Method\n", style=1),
            run("Mix the dry ingredients.\n", style=102),
            run("Whisk in the eggs, zest and juice.\n", style=102),
            run("Bake for 40 minutes at 175 °C.\n", style=102),
            run("￼", attachment=("ATT-CAKE", "public.jpeg")),
            run("\n"),
            run("Recipe from ", style=-1),
            run("Mom's kitchen", link="https://www.example.com/recipes",
                underline=True),
            run(". Best served warm.\n"),
        ], 12, snippet="Ingredients")
        note(12, 5, "Tomato soup", [
            run("Tomato soup\n", style=0),
            run("1 kg ripe tomatoes\n", style=100),
            run("1 onion, 2 garlic cloves\n", style=100),
            run("Roast, blend, season. Add basil at the end.\n")], 30)
        note(13, 7, "Q4 planning – meeting notes", [
            run("Q4 planning – meeting notes\n", style=0),
            run("Decisions\n", style=1),
            run("Ship the reports redesign by mid-November\n", style=100),
            run("Freeze scope on 1 November\n", style=100),
            run("Action items\n", style=1),
            run("Send draft schedule to Jordan\n", style=103, done=False),
            run("Book the review room\n", style=103, done=True),
            run("Update the roadmap page\n", style=103, done=False),
        ], 1, snippet="Decisions")
        note(14, 2, "Gift ideas", [
            run("Gift ideas\n", style=0),
            run("Mom: ", style=-1), run("gardening gloves", italic=True),
            run(", a new tea set\n"),
            run("Alex: trail map of Pine Ridge\n"),
            run("Sam: board game night bundle\n")], 6, pinned=1)
        note(15, 2, "Hike route", [
            run("Hike route\n", style=0),
            run("￼", attachment=("ATT-MAP", "public.jpeg")),
            run("\n"),
            run("About 11 km, mostly shade. Start at the Pine Ridge "
                "trailhead at 7:30.\n")], 3)
        note(16, 2, "Book list", [
            run("Book list\n", style=0),
            run("Pride and Prejudice\n", style=100),
            run("Moby-Dick\n", style=100),
            run("The Count of Monte Cristo\n", style=100)], 40)
        note(17, 2, "Call with Pizza Palace", [
            run("Call with Pizza Palace\n", style=0),
            run("￼", attachment=("ATT-CALL", "com.apple.m4a-audio")),
            run("\n")], 2)
        note(18, 2, "Private", [], 55, locked=1,
             data=b"\x01\x02 encrypted bytes, not a note")
        note(19, 4, "Old shopping list", [run("Old shopping list\n", style=0),
                                         run("nothing important\n")], 70)
        for pk, key, name in ((20, "MEDIA-CAKE", "lemon-cake.jpg"),
                              (21, "MEDIA-MAP", "route.jpg"),
                              (22, "MEDIA-VOICE", "Recording.m4a"),
                              (23, "MEDIA-CALL", "call-audio.MOV")):
            row(pk, 11, ident=key, filename=name)
        row(30, 3, note=11, ident="ATT-CAKE", uti="public.jpeg", media=20)
        row(31, 3, note=15, ident="ATT-MAP", uti="public.jpeg", media=21)
        row(32, 3, note=17, ident="ATT-CALL", uti="com.apple.m4a-audio",
            title="Call with Pizza Palace")
        conn.execute("UPDATE ZICCLOUDSYNCINGOBJECT SET "
                     "ZADDITIONALINDEXABLETEXT = ? WHERE Z_PK = 32",
                     ("Hello, I would like to change my order please. "
                      "Yes, a large margherita with no olives.",))
        row(33, 3, ident="ATT-CALL-MOV", uti="public.mpeg-4-audio", media=23)
        conn.execute("UPDATE ZICCLOUDSYNCINGOBJECT SET ZPARENTATTACHMENT = "
                     "32, ZDURATION = 94.0, ZNOTE = 17 WHERE Z_PK = 33")

    writer.database(NOTES_DOMAIN, "NoteStore.sqlite", build)
    for key, path in paths.items():
        writer.file(NOTES_DOMAIN, path, media[key][1], ago(days=3))
