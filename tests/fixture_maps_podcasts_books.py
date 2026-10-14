# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""Fake Maps, Podcasts and Books databases for tests. All invented."""

from tests.fixture_apps import T0, database_bytes

DAY = 86400

# ── Maps ─────────────────────────────────────────────────────

MAPS_DOMAIN = "AppDomainGroup-group.com.apple.Maps"
MAPS_DB = "Maps/MapsSync_0.0.1"


def build_maps(conn):
    conn.executescript("""
        CREATE TABLE ZFAVORITEITEM (Z_PK INTEGER PRIMARY KEY,
            ZHIDDEN INTEGER, ZPOSITIONINDEX INTEGER, ZCREATETIME REAL,
            ZLATITUDE REAL, ZLONGITUDE REAL, ZCUSTOMNAME TEXT,
            ZORIGINATINGADDRESSSTRING TEXT);
        CREATE TABLE ZCOLLECTION (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT);
        CREATE TABLE ZCOLLECTIONITEM (Z_PK INTEGER PRIMARY KEY,
            ZCREATETIME REAL, ZLATITUDE REAL, ZLONGITUDE REAL,
            ZCUSTOMNAME TEXT);
        CREATE TABLE Z_5PLACES (Z_5COLLECTIONS INTEGER, Z_6PLACES INTEGER);
        CREATE TABLE ZHISTORYITEM (Z_PK INTEGER PRIMARY KEY,
            ZCREATETIME REAL, ZLATITUDE REAL, ZLONGITUDE REAL, ZQUERY TEXT,
            ZLOCATIONDISPLAY TEXT);
    """)
    conn.executemany("INSERT INTO ZFAVORITEITEM VALUES (?,?,?,?,?,?,?,?)", [
        (1, 0, 2, T0, 12.5, -45.25, "Home <sweet>", "1 Main St"),
        (2, 1, 1, T0 + DAY, 13.0, -46.0, "Cafe", None),
        (3, 0, 3, None, None, None, None, "no coordinates"),
        (4, 0, 4, T0, 0.0, 0.0, "Null island", None),       # not a place
        (5, 0, 5, T0, 99.0, 200.0, "Off the map", None)])   # impossible
    conn.executemany("INSERT INTO ZCOLLECTION VALUES (?, ?)",
                     [(1, "Trip"), (2, None), (3, "Empty")])
    conn.executemany("INSERT INTO ZCOLLECTIONITEM VALUES (?,?,?,?,?)", [
        (10, T0, 40.0, -74.0, "Museum"), (11, T0 + 5, 41.0, -73.0, "Park"),
        (12, T0, None, None, "Somewhere")])
    conn.executemany("INSERT INTO Z_5PLACES VALUES (?, ?)",
                     [(1, 10), (1, 11), (2, 12), (1, 99)])   # (99: gone)
    conn.executemany("INSERT INTO ZHISTORYITEM VALUES (?,?,?,?,?,?)", [
        (1, T0, 50.0, 8.0, "pizza", "Pizza Place"),
        (2, T0 + 60, None, None, None, "A place"),
        (3, T0 + 120, None, None, "coffee near me", None)])
    conn.commit()


LEGACY_MAPS_DOMAIN = "AppDomain-com.apple.Maps"
LEGACY_MAPS = "Library/Maps/GeoBookmarks.plist"


def legacy_entries():
    """Entries of the kind iOS 12 keeps, with invented places."""
    from tests.protobuf_builder import field, message, nested
    park = message((1, 3), (2, 0), (4, 43200), (2000, 559000000.0),
                   (8, message(
                       (1, message((2, "+1 555 0100"),
                                   (6, "https://park.example.com"),
                                   (10, message((1, "x"), (3, "Example Park")),),
                                   (12, message((4, "Park")))),),
                       (2, message((1, message((1, 12.5), (2, -45.25)))))
                   )))
    cafe = message((1, 5), (4, 43200), (2000, 559000100.0), (9, "Food"),
                   (8, message(
                       (1, message((11, message((3, "Corner Cafe"))))))))
    home =message((1, 6), (8, message(
        (5, nested((1, 3), field(11, "1 Main St, Springfield"))))))
    home31 = message((1, 8), (8, message((31, nested(
        (1, 101, 2), field(11, "2 Side Rd, Shelbyville"))))))
    blank = message((1, 10), (8, message((1, message(
        (10, message((3, "   "))),
        (11, message((3, "Second Path Name"))))))))
    shop = message((1, 7), (8, message(
        (30, message((1, "The Shop"), (2, "Shopping"), (5, "Springfield")))),),
        (7, message((4, "ignored"))))
    unnamed_place = message((1, 9), (8, message(
        (2, message((1, message((1, 40.0), (2, -74.0)))))),))
    searches = message((1, 15), (8, message(
        (26, message((1, "first search"), (5, message((1, "x"))))),
        (26, message((1, "second search"))),
        (26, message((1, "third search"))))))
    unread = message((1, 17), (8, message((41, message((1, "unread kind"))))))
    empty = message((1, 11), (2, 0))
    stub = message((1, 13))
    return [park, cafe, home, home31, blank, shop, unnamed_place, searches,
            unread, empty, stub]


def legacy_maps_plist(entries=None, extra_records=0):
    import plistlib
    from tests.protobuf_builder import field, message
    entries = legacy_entries() if entries is None else entries
    body = message((1, 1 << 40), (2, 1),
                   *[(4, e) for e in entries])
    contents = message((1, 1), (2, "A1B2"), (5, message((1, message(
        (1, body))))))
    records = {"ACA6B299-F478-49AA-8837-19D0AD146386": {
        "contents": contents, "contentsTimestamp": b"x" * 20,
        "position": b"p", "positionTimestamp": b"y" * 20}}
    for number in range(extra_records):
        records[f"EXTRA-{number}"] = {"contents": contents}
    return plistlib.dumps({"MSPBookmarks": {
        "records": records, "clientIdentifier": "C"}, "MSPBookmarksVersion": 1})


def legacy_maps_files(**kw):
    return [(LEGACY_MAPS_DOMAIN, LEGACY_MAPS, legacy_maps_plist(**kw))]


def maps_files():
    return [(MAPS_DOMAIN, MAPS_DB, database_bytes(build_maps))]


# ── Podcasts ─────────────────────────────────────────────────

PODCASTS_DOMAIN = "AppDomainGroup-243LU875E5.groups.com.apple.podcasts"
PODCASTS_DB = "Documents/MTLibrary.sqlite"


def build_podcasts(conn):
    conn.executescript("""
        CREATE TABLE ZMTPODCAST (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT,
            ZAUTHOR TEXT, ZFEEDURL TEXT, ZWEBPAGEURL TEXT,
            ZSUBSCRIBED INTEGER, ZLASTDATEPLAYED REAL, ZADDEDDATE REAL);
        CREATE TABLE ZMTEPISODE (Z_PK INTEGER PRIMARY KEY, ZPODCAST INTEGER,
            ZTITLE TEXT, ZDURATION REAL, ZPUBDATE REAL,
            ZFIRSTTIMEAVAILABLE REAL, ZLASTDATEPLAYED REAL, ZPLAYCOUNT INTEGER,
            ZDOWNLOADDATE REAL, ZPLAYHEAD REAL, ZBOOKMARKTIME REAL,
            ZENCLOSUREURL TEXT, ZASSETURL TEXT);
    """)
    conn.executemany("INSERT INTO ZMTPODCAST VALUES (?,?,?,?,?,?,?,?)", [
        (1, "The Show <1>", "Host A", "https://example.com/feed",
         "https://example.com", 1, T0 + 100, T0 - DAY),
        (2, "Other Show", None, None, None, 0, None, None)])
    conn.executemany(
        "INSERT INTO ZMTEPISODE VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (1, 1, "Episode one", 1800.0, T0 - 10 * DAY, None, T0 + 100, 2,
             T0 - 9 * DAY, 600.0, None, "https://example.com/1.mp3", None),
            (2, 1, "Episode two", 3600.0, None, T0 - 5 * DAY, None, 0, None,
             None, 30.0, None, "file:///x.mp3"),
            (3, 2, "Lonely", 0.0, T0, None, None, None, None, None, None,
             None, None),
            (4, 77, "Orphan", None, None, None, None, 1, None, None, None,
             None, None)])
    conn.commit()


def podcasts_files(path=PODCASTS_DB, domain=PODCASTS_DOMAIN):
    return [(domain, path, database_bytes(build_podcasts))]


# ── Books ────────────────────────────────────────────────────

BOOKS_DOMAIN = "AppDomainGroup-group.com.apple.iBooks"
LIBRARY = "Documents/BKLibrary/BKLibrary-1-091020131601.sqlite"
ANNOTATIONS = "Documents/AEAnnotation/AEAnnotation_v10312011_1727_local.sqlite"
STORE_LIST = ("Documents/BKJaliscoServerSource/"
              "BKJaliscoServerSource-v09182016.sqlite")
COLLECTIONS = ("Documents/BCCloudData-BookDataStoreService/"
               "BCCloudCollections/BCCloudCollections")


def build_library(conn):
    conn.execute("""CREATE TABLE ZBKLIBRARYASSET (Z_PK INTEGER PRIMARY KEY,
        ZASSETID TEXT, ZTITLE TEXT, ZAUTHOR TEXT, ZGENRE TEXT,
        ZLASTOPENDATE REAL, ZREADINGPROGRESS REAL, ZPURCHASEDATE REAL,
        ZISSTOREAUDIOBOOK INTEGER, ZCONTENTTYPE INTEGER, ZPATH TEXT,
        ZISHIDDEN INTEGER, ZISSAMPLE INTEGER)""")
    conn.executemany(
        "INSERT INTO ZBKLIBRARYASSET VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (1, "111", "A Novel", "Writer One", "Fiction", T0, 0.43, T0 - DAY,
             0, 1, "/x", 0, 0),
            (2, "A2", "Heard Book", None, None, None, 1.0, None, 1, 1, None,
             1, 0),
            (3, "A3", "A Sample", "Writer Two", "Fiction", None, 7.5, None, 0,
             1, None, 0, 1)])
    conn.commit()


def build_annotations(conn):
    conn.execute("""CREATE TABLE ZAEANNOTATION (Z_PK INTEGER PRIMARY KEY,
        ZANNOTATIONASSETID TEXT, ZANNOTATIONSELECTEDTEXT TEXT,
        ZANNOTATIONNOTE TEXT, ZANNOTATIONCREATIONDATE REAL,
        ZANNOTATIONMODIFICATIONDATE REAL, ZANNOTATIONDELETED INTEGER)""")
    conn.executemany("INSERT INTO ZAEANNOTATION VALUES (?,?,?,?,?,?,?)", [
        (1, "111", "A line worth keeping", "my note", T0 + 10, None, 0),
        (2, "111", None, "only a note", None, T0 + 20, 0),
        (3, "111", "deleted one", None, T0, None, 1),
        (4, "111", "  ", None, T0, None, 0),                  # nothing
        (5, "Z9", "From a book not in the library", None, T0, None, 0)])
    conn.commit()


def build_store_list(conn):
    conn.execute("""CREATE TABLE ZBLJALISCOSERVERITEM (Z_PK INTEGER PRIMARY
        KEY, ZTITLE TEXT, ZARTIST TEXT, ZGENRE TEXT, ZPURCHASEDAT REAL,
        ZSTOREID INTEGER, ZISAUDIOBOOK INTEGER, ZISHIDDEN INTEGER)""")
    conn.executemany("INSERT INTO ZBLJALISCOSERVERITEM VALUES "
                     "(?,?,?,?,?,?,?,?)", [
        (1, "A Novel", "Writer One", "Fiction", T0 - DAY, 111, 0, 0),
        (2, "Only Bought", "Writer Three", "History", T0 - 2 * DAY, 222, 1,
         1)])
    conn.commit()


def build_collections(conn):
    conn.execute("""CREATE TABLE ZBCCOLLECTIONDETAIL (Z_PK INTEGER PRIMARY KEY,
        ZNAME TEXT, ZCOLLECTIONDESCRIPTION TEXT, ZHIDDEN INTEGER,
        ZMODIFICATIONDATE REAL, ZDELETEDFLAG INTEGER)""")
    conn.executemany("INSERT INTO ZBCCOLLECTIONDETAIL VALUES (?,?,?,?,?,?)", [
        (1, "Want to Read", None, 0, T0, 0), (2, "Gone", None, 0, T0, 1),
        (3, None, "no name", 1, None, 0)])
    conn.commit()


def books_files(library=True, annotations=True, store=True, collections=True):
    files = []
    if library:
        files.append((BOOKS_DOMAIN, LIBRARY, database_bytes(build_library)))
    if annotations:
        files.append((BOOKS_DOMAIN, ANNOTATIONS,
                      database_bytes(build_annotations)))
    if store:
        files.append((BOOKS_DOMAIN, STORE_LIST,
                      database_bytes(build_store_list)))
    if collections:
        files.append((BOOKS_DOMAIN, COLLECTIONS,
                      database_bytes(build_collections)))
    return files
