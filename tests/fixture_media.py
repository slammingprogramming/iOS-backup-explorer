# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""A fake camera roll (pictures, videos and Photos.sqlite) and fake voice
recordings for tests.

Everything here is invented. The databases follow the layout iOS uses,
trimmed to what the readers look at. Pictures are real, tiny picture files:
a PNG always, a JPEG and a HEIC when Pillow (and pillow-heif) can make them.
"""

import io

from tests.fixture_apps import T0, database_bytes, make_png

CAMERA = "CameraRollDomain"
DCIM = "Media/DCIM"
LIBRARY = "Media/PhotoData/Photos.sqlite"

APPLE_EPOCH = 978_307_200
VIDEO_BYTES = b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  " + b"video" * 200


def picture_bytes(fmt, size=(48, 32), colour=(200, 60, 60)):
    """A small picture in *fmt* ("PNG", "JPEG", "HEIF") or None when this
    machine cannot make one."""
    if fmt == "PNG":
        return make_png(size[0], size[1], colour)
    try:
        from PIL import Image
        if fmt == "HEIF":
            import pillow_heif
            pillow_heif.register_heif_opener()
        buffer = io.BytesIO()
        Image.new("RGB", size, colour).save(buffer, fmt)
        return buffer.getvalue()
    except Exception:
        return None


# A fixed moment in 2026, as Unix time, for the dates the files carry
FILE_DATE = T0 + APPLE_EPOCH + 5000

SCHEMA = """
CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER,
    ZDIRECTORY VARCHAR, ZFILENAME VARCHAR, ZDATECREATED TIMESTAMP,
    ZKIND INTEGER, ZFAVORITE INTEGER, ZHIDDEN INTEGER, ZTRASHEDSTATE INTEGER,
    ZWIDTH INTEGER, ZHEIGHT INTEGER, ZDURATION FLOAT, ZLATITUDE FLOAT,
    ZLONGITUDE FLOAT);
CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER,
    ZTITLE VARCHAR, ZKIND INTEGER, ZTRASHEDSTATE INTEGER);
CREATE TABLE Z_26ASSETS (Z_26ALBUMS INTEGER, Z_3ASSETS INTEGER,
    PRIMARY KEY (Z_26ALBUMS, Z_3ASSETS));
"""


def build_library(conn):
    conn.executescript(SCHEMA)

    def asset(pk, directory, name, when, kind=0, favorite=0, hidden=0,
              trashed=0, size=(48, 32), duration=0.0, where=(None, None)):
        conn.execute(
            "INSERT INTO ZASSET (Z_PK, ZDIRECTORY, ZFILENAME, ZDATECREATED, "
            "ZKIND, ZFAVORITE, ZHIDDEN, ZTRASHEDSTATE, ZWIDTH, ZHEIGHT, "
            "ZDURATION, ZLATITUDE, ZLONGITUDE) VALUES (?,?,?,?,?,?,?,?,?,?,?,"
            "?,?)", (pk, directory, name, when, kind, favorite, hidden,
                     trashed, size[0], size[1], duration, *where))

    asset(1, "DCIM/100APPLE", "IMG_0001.PNG", T0, favorite=1,
          where=(47.6062, -122.3321))
    asset(2, "DCIM/100APPLE", "IMG_0002.JPG", T0 + 100, hidden=1)
    asset(3, "DCIM/100APPLE", "IMG_0003.HEIC", T0 + 200, size=(4032, 3024),
          where=(-34.9285, 138.6007))
    asset(4, "DCIM/100APPLE", "IMG_0004.MOV", T0 + 300, kind=1,
          size=(1920, 1080), duration=12.5, where=(-180.0, -180.0))
    asset(5, "DCIM/101APPLE", "IMG_0001.PNG", T0 + 400, trashed=1)
    conn.execute("INSERT INTO ZASSET (Z_PK, ZDIRECTORY, ZFILENAME) VALUES "
                 "(6, 'DCIM/100APPLE', 'IMG_9999.JPG')")   # in no backup
    conn.executemany(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZTITLE, ZKIND, ZTRASHEDSTATE) "
        "VALUES (?,?,?,?)", [(1, "Holiday", 2, 0), (2, "Empty album", 2, 0),
                             (3, "Deleted album", 2, 1), (4, None, 2, 0),
                             (5, "Favourites of 2026", 2, 0)])
    conn.executemany("INSERT INTO Z_26ASSETS VALUES (?, ?)",
                     [(1, 1), (1, 3), (3, 1), (5, 1), (5, 4), (1, 99)])
    conn.commit()


def camera_files(with_library=True):
    """``(domain, path, bytes, mtime)`` for a camera roll."""
    jpeg = picture_bytes("JPEG", colour=(60, 200, 60)) or picture_bytes("PNG")
    heic = picture_bytes("HEIF", (64, 48), (60, 60, 200)) \
        or b"not really a HEIC picture"
    files = [
        (CAMERA, f"{DCIM}/100APPLE/IMG_0001.PNG", picture_bytes("PNG"),
         FILE_DATE),
        (CAMERA, f"{DCIM}/100APPLE/IMG_0002.JPG", jpeg, FILE_DATE + 1),
        (CAMERA, f"{DCIM}/100APPLE/IMG_0003.HEIC", heic, FILE_DATE + 2),
        (CAMERA, f"{DCIM}/100APPLE/IMG_0004.MOV", VIDEO_BYTES, FILE_DATE + 3),
        (CAMERA, f"{DCIM}/100APPLE/IMG_E0002.JPG", jpeg, FILE_DATE + 4),
        (CAMERA, f"{DCIM}/100APPLE/IMG_0002.AAE", b"<plist/>", FILE_DATE),
        (CAMERA, f"{DCIM}/101APPLE/IMG_0001.PNG",
         picture_bytes("PNG", colour=(10, 10, 10)), FILE_DATE + 5),
        (CAMERA, f"{DCIM}/MISC/Foo.PLIST", b"<plist/>", FILE_DATE),
    ]
    if with_library:
        files.append((CAMERA, LIBRARY, database_bytes(build_library),
                      FILE_DATE))
    return files


# ── Voice memos ──────────────────────────────────────────────

MEMOS_NEW = "AppDomainGroup-group.com.apple.VoiceMemos.shared/Recordings"
MEMOS_OLD = "MediaDomain/Media/Recordings"
AUDIO = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A " + b"audio" * 100

MEMO_SCHEMA = """
CREATE TABLE ZCLOUDRECORDING (Z_PK INTEGER PRIMARY KEY, ZCUSTOMLABEL VARCHAR,
    ZDATE TIMESTAMP, ZDURATION FLOAT, ZPATH VARCHAR, ZUNIQUEID VARCHAR);
"""


def build_memos_db(conn):
    conn.executescript(MEMO_SCHEMA)
    conn.executemany(
        "INSERT INTO ZCLOUDRECORDING (ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH) "
        "VALUES (?,?,?,?)", [
            ("Interview with Sam", T0, 125.4,
             "/var/mobile/Containers/Shared/AppGroup/ABC/Recordings/"
             "20260901 100000-AAA.m4a"),
            ("", T0 + 3600, 12.0, "20260901 110000-BBB.m4a"),
            ("Song idea", T0 + 7200, 61.0, "20260901 120000-CCC.m4a"),
            ("Gone", T0, 5.0, "20260101 000000-ZZZ.m4a"),   # no such file
        ])
    conn.commit()


def memo_files(with_database=True):
    files = [
        ("AppDomainGroup-group.com.apple.VoiceMemos.shared",
         "Recordings/20260901 100000-AAA.m4a", AUDIO, FILE_DATE),
        ("AppDomainGroup-group.com.apple.VoiceMemos.shared",
         "Recordings/20260901 110000-BBB.m4a", AUDIO + b"!", FILE_DATE + 60),
        ("AppDomainGroup-group.com.apple.VoiceMemos.shared",
         "Recordings/20260901 120000-CCC.m4a", AUDIO * 2, FILE_DATE + 120),
        ("AppDomainGroup-group.com.apple.VoiceMemos.shared",
         "Recordings/20260901 130000-DDD.m4a", AUDIO * 3, FILE_DATE + 180),
        ("AppDomainGroup-group.com.apple.VoiceMemos.shared",
         "Recordings/notes.txt", b"not audio", FILE_DATE),
    ]
    if with_database:
        files.append(("AppDomainGroup-group.com.apple.VoiceMemos.shared",
                      "Recordings/CloudRecordings.db",
                      database_bytes(build_memos_db), FILE_DATE))
    return files


def backup_files():
    return camera_files() + memo_files()
