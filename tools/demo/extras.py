# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The demo phone's Maps, Podcasts and Books."""

from . import ago, clone_schema, cocoa


def maps(writer):
    from tests import fixture_maps_podcasts_books as fx

    def build(conn):
        clone_schema(fx.build_maps, conn)
        conn.executemany(
            "INSERT INTO ZFAVORITEITEM VALUES (?,?,?,?,?,?,?,?)", [
                (1, 0, 1, cocoa(ago(days=400)), 39.7990, -89.6440, "Home",
                 "48 Maple Street, Springfield"),
                (2, 0, 2, cocoa(ago(days=380)), 39.7790, -89.6550, "Work",
                 "100 Commerce Avenue, Springfield"),
                (3, 0, 3, cocoa(ago(days=120)), 39.7817, -89.6501,
                 "Cafe Aroma", "5 Market Square, Springfield"),
                (4, 0, 4, cocoa(ago(days=60)), 39.9152, -89.7203,
                 "Pine Ridge trailhead", "Pine Ridge Road"),
                (5, 0, 5, cocoa(ago(days=30)), 39.8213, -89.5907,
                 "Lake Shore picnic area", None),
                (6, 1, 6, cocoa(ago(days=200)), 39.7700, -89.6700,
                 "Old apartment", "9 Elm Court, Springfield")])
        conn.executemany("INSERT INTO ZCOLLECTION VALUES (?, ?)",
                         [(1, "Lisbon weekend"), (2, "Coffee shops"),
                          (3, "Weekend hikes")])
        items = [
            (10, 1, "Belem Tower", 38.6916, -9.2160),
            (11, 1, "Alfama district", 38.7110, -9.1296),
            (12, 1, "LX Factory", 38.7033, -9.1783),
            (13, 1, "Time Out Market", 38.7068, -9.1460),
            (14, 1, "Miradouro da Senhora do Monte", 38.7197, -9.1327),
            (20, 2, "Cafe Aroma", 39.7817, -89.6501),
            (21, 2, "Corner Roasters", 39.7840, -89.6480),
            (22, 2, "Bean There", 39.7760, -89.6590),
            (30, 3, "Pine Ridge loop", 39.9152, -89.7203),
            (31, 3, "Lake Shore trail", 39.8213, -89.5907)]
        for pk, collection, name, lat, lon in items:
            conn.execute("INSERT INTO ZCOLLECTIONITEM VALUES (?,?,?,?,?)",
                         (pk, cocoa(ago(days=40 + pk)), lat, lon, name))
            conn.execute("INSERT INTO Z_5PLACES VALUES (?, ?)",
                         (collection, pk))
        searches = [("coffee near me", None, 39.7817, -89.6501, 1),
                    ("pharmacy", "Springfield Pharmacy", 39.7810, -89.6520,
                     3),
                    ("Pine Ridge trailhead", "Pine Ridge trailhead", 39.9152,
                     -89.7203, 14),
                    ("Lisbon airport", "Humberto Delgado Airport", 38.7742,
                     -9.1342, 25),
                    ("gas station", None, None, None, 33),
                    ("Time Out Market", "Time Out Market Lisboa", 38.7068,
                     -9.1460, 44)]
        for pk, (query, name, lat, lon, days) in enumerate(searches, 1):
            conn.execute("INSERT INTO ZHISTORYITEM VALUES (?,?,?,?,?,?)",
                         (pk, cocoa(ago(days=days)), lat, lon, query, name))
    writer.database(fx.MAPS_DOMAIN, fx.MAPS_DB, build)


def podcasts(writer):
    from tests import fixture_maps_podcasts_books as fx

    shows = [
        (1, "The Daily Trail", "Pine Ridge Media", 1),
        (2, "Cooking with Curiosity", "Test Kitchen Radio", 1),
        (3, "Space Hour", "Observatory Network", 1),
        (4, "Tech Tidbits", "Bit by Bit", 0),
    ]
    episodes = [
        (1, "Ep. 112: Autumn trails to try", 2400, 3, 1),
        (1, "Ep. 111: Packing light", 2160, 10, 1),
        (1, "Ep. 110: Trail etiquette", 1980, 17, 0),
        (2, "Sourdough, step by step", 3100, 4, 1),
        (2, "Why lemon belongs in everything", 1700, 11, 1),
        (2, "Soup season", 2050, 18, 0),
        (3, "The Moon's far side", 2850, 6, 0),
        (3, "Meteor showers of autumn", 2600, 13, 1),
        (3, "How telescopes work", 3000, 20, 0),
        (4, "Passkeys explained", 1500, 5, 0),
        (4, "What is a backup, really?", 1900, 12, 1),
    ]

    def build(conn):
        clone_schema(fx.build_podcasts, conn)
        for pk, title, author, following in shows:
            conn.execute(
                "INSERT INTO ZMTPODCAST VALUES (?,?,?,?,?,?,?,?)",
                (pk, title, author,
                 f"https://feeds.example.com/{pk}.xml",
                 f"https://www.example.com/podcasts/{pk}", following,
                 cocoa(ago(days=3)) if following else None,
                 cocoa(ago(days=300))))
        for number, (show, title, seconds, days, played) in enumerate(
                episodes, 1):
            conn.execute(
                "INSERT INTO ZMTEPISODE VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (number, show, title, float(seconds), cocoa(ago(days=days)),
                 None, cocoa(ago(days=days - 1)) if played else None,
                 1 if played else 0, cocoa(ago(days=days))
                 if played else None, seconds * .4 if not played else None,
                 None, f"https://cdn.example.com/{show}/{number}.mp3", None))
    writer.database(fx.PODCASTS_DOMAIN, fx.PODCASTS_DB, build)


def books(writer):
    from tests import fixture_maps_podcasts_books as fx

    library = [
        ("1342", "Pride and Prejudice", "Jane Austen", "Classics", .62, 3,
         0),
        ("2701", "Moby-Dick", "Herman Melville", "Classics", .08, 40, 0),
        ("1184", "The Count of Monte Cristo", "Alexandre Dumas", "Classics",
         1.0, 90, 0),
        ("205", "Walden", "Henry David Thoreau", "Non-fiction", .35, 12, 0),
        ("11", "Alice's Adventures in Wonderland", "Lewis Carroll",
         "Children's", 1.0, 150, 0),
        ("120", "Treasure Island", "Robert Louis Stevenson", "Adventure",
         .0, 8, 1),
    ]

    def build_library(conn):
        clone_schema(fx.build_library, conn)
        for pk, (asset, title, author, genre, progress, days,
                 audio) in enumerate(library, 1):
            conn.execute(
                "INSERT INTO ZBKLIBRARYASSET VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pk, asset, title, author, genre,
                 cocoa(ago(days=days)) if progress else None, progress,
                 cocoa(ago(days=days + 300)), audio, 1, None, 0, 0))

    def build_annotations(conn):
        clone_schema(fx.build_annotations, conn)
        notes = [
            ("1342", "It is a truth universally acknowledged, that a single "
             "man in possession of a good fortune, must be in want of a "
             "wife.", "Famous first line", 40),
            ("1342", "I declare after all there is no enjoyment like "
             "reading!", None, 12),
            ("205", "I went to the woods because I wished to live "
             "deliberately.", "For the hiking trip reading list", 20),
            ("1184", "All human wisdom is contained in these two words "
             "– Wait and Hope.", None, 85)]
        for pk, (asset, text, note, days) in enumerate(notes, 1):
            conn.execute("INSERT INTO ZAEANNOTATION VALUES (?,?,?,?,?,?,?)",
                         (pk, asset, text, note, cocoa(ago(days=days)), None,
                          0))

    def build_store(conn):
        clone_schema(fx.build_store_list, conn)
        for pk, (asset, title, author, genre, _p, days, audio) in enumerate(
                library, 1):
            conn.execute(
                "INSERT INTO ZBLJALISCOSERVERITEM VALUES (?,?,?,?,?,?,?,0)",
                (pk, title, author, genre, cocoa(ago(days=days + 300)),
                 int(asset), audio))

    def build_collections(conn):
        clone_schema(fx.build_collections, conn)
        for pk, name in enumerate(("Want to Read", "Classics", "Audiobooks"),
                                  1):
            conn.execute(
                "INSERT INTO ZBCCOLLECTIONDETAIL VALUES (?,?,?,?,?,0)",
                (pk, name, None, 0, cocoa(ago(days=pk * 30))))

    writer.database(fx.BOOKS_DOMAIN, fx.LIBRARY, build_library)
    writer.database(fx.BOOKS_DOMAIN, fx.ANNOTATIONS, build_annotations)
    writer.database(fx.BOOKS_DOMAIN, fx.STORE_LIST, build_store)
    writer.database(fx.BOOKS_DOMAIN, fx.COLLECTIONS, build_collections)
