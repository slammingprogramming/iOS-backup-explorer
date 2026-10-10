# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The demo phone's contacts, messages, calls, voicemail and recents."""

from . import ago, cocoa, unix
from . import pictures

NS = 1_000_000_000

# (first, last, nickname, organization, job, birthday (y, m, d) or None,
#  [(property, label, value)], note)
PHONE, EMAIL, ADDRESS, URL = 3, 4, 5, 22

PEOPLE = {
    "alex": dict(first="Alex", last="Rivera", org="Rivera Design",
                 job="Illustrator", birthday=(1991, 3, 14),
                 phones=[("Mobile", "+15550100101"),
                         ("Work", "(555) 010-0102")],
                 emails=[("Home", "alex.rivera@example.com")],
                 address=("Home", "48 Maple Street", "Springfield", "IL",
                          "62701", "United States", "us"),
                 note="Hiking buddy. Allergic to shellfish."),
    "jordan": dict(first="Jordan", last="Lee", birthday=(1988, 11, 2),
                   phones=[("Mobile", "+15550100103")],
                   emails=[("Work", "jordan.lee@example.org")],
                   org="Lee & Partners", job="Accountant"),
    "sam": dict(first="Sam", last="Patel", birthday=(1993, 7, 29),
                phones=[("Mobile", "+15550100104")],
                emails=[("Home", "sam.patel@example.net")]),
    "casey": dict(first="Casey", last="Nguyen", nickname="Case",
                  phones=[("Mobile", "+15550100105")],
                  emails=[("Home", "casey.n@example.com")],
                  birthday=(1995, 1, 21)),
    "riley": dict(first="Riley", last="Brooks",
                  phones=[("Mobile", "+15550100106")],
                  emails=[("Work", "riley.brooks@example.org")],
                  org="Brooks Bike Shop"),
    "morgan": dict(first="Morgan", last="Diaz", birthday=(1990, 9, 5),
                   phones=[("Mobile", "+15550100107")]),
    "pat": dict(first="Pat", last="Kim", phones=[("Mobile",
                                                 "+15550100108")],
                emails=[("Home", "pat.kim@example.com")]),
    "pizza": dict(org="Pizza Palace", kind=1,
                  phones=[("Main", "(555) 010-0110")],
                  address=("Work", "7 Oven Road", "Springfield", "IL",
                           "62702", "United States", "us"),
                  urls=[("Homepage", "https://www.example.com/pizza-palace")]),
    "quinn": dict(prefix="Dr.", first="Quinn", last="Harper",
                  job="Family doctor", org="Springfield Health Clinic",
                  phones=[("Work", "+15550100111")],
                  address=("Work", "100 Clinic Way", "Springfield", "IL",
                           "62703", "United States", "us")),
    "mom": dict(nickname="Mom", first="Dana", last="Morgan",
                birthday=(1962, 4, 18),
                phones=[("Mobile", "+15550100112"), ("Home",
                                                    "(555) 010-0113")],
                emails=[("Home", "dana.morgan@example.com")],
                address=("Home", "22 Orchard Lane", "Shelbyville", "IL",
                         "62565", "United States", "us"),
                note="Birthday dinner every April."),
    "dentist": dict(org="Bright Smiles Dental",
                    phones=[("Main", "+15550100114")], kind=1),
    "neighbor": dict(first="Lena", last="Ortiz",
                     phones=[("Mobile", "+15550100115")],
                     note="Waters the plants when I travel."),
}


def contacts(conn):
    from tests import fixture_contacts as fc
    conn.executescript(fc.SCHEMA)
    labels, keys = {}, {}

    def label(text):
        if text is None:
            return None
        text = f"_$!<{text}>!$_"
        if text not in labels:
            labels[text] = conn.execute(
                "INSERT INTO ABMultiValueLabel (value) VALUES (?)",
                (text,)).lastrowid
        return labels[text]

    for key in ("Street", "City", "State", "ZIP", "Country", "CountryCode"):
        keys[key] = conn.execute(
            "INSERT INTO ABMultiValueEntryKey (value) VALUES (?)",
            (key,)).lastrowid
    for number, person in enumerate(PEOPLE.values(), 1):
        birthday = person.get("birthday")
        cur = conn.execute(
            "INSERT INTO ABPerson (First, Last, Prefix, Nickname, "
            "Organization, JobTitle, Birthday, Note, CreationDate, "
            "ModificationDate, Kind) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (person.get("first"), person.get("last"), person.get("prefix"),
             person.get("nickname"), person.get("org"), person.get("job"),
             fc.apple_seconds(*birthday) if birthday else None,
             person.get("note"), cocoa(ago(days=400 - number)),
             cocoa(ago(days=20 + number)), person.get("kind", 0)))
        record = cur.lastrowid
        person["id"] = record
        for prop, items in ((PHONE, person.get("phones", ())),
                            (EMAIL, person.get("emails", ()))):
            for name, value in items:
                conn.execute("INSERT INTO ABMultiValue (record_id, property,"
                             " label, value) VALUES (?,?,?,?)",
                             (record, prop, label(name), value))
        for name, value in person.get("urls", ()):
            conn.execute("INSERT INTO ABMultiValue (record_id, property, "
                         "label, value) VALUES (?,?,?,?)",
                         (record, URL, label(name), value))
        if person.get("address"):
            name, street, city, state, zip_code, country, code = \
                person["address"]
            uid = conn.execute(
                "INSERT INTO ABMultiValue (record_id, property, label) "
                "VALUES (?,?,?)", (record, ADDRESS, label(name))).lastrowid
            for key, value in (("Street", street), ("City", city),
                               ("State", state), ("ZIP", zip_code),
                               ("Country", country),
                               ("CountryCode", code)):
                conn.execute("INSERT INTO ABMultiValueEntry (parent_id, "
                             "key, value) VALUES (?,?,?)",
                             (uid, keys[key], value))


def number_of(name):
    return PEOPLE[name]["phones"][0][1]


# ── Messages ─────────────────────────────────────────────────

def attachments(writer):
    """The pictures that go with the messages: ``{guid: (path, bytes)}``."""
    return {
        "GUID-TRAIL": ("Library/SMS/Attachments/3a/10/GUID-TRAIL/"
                       "IMG_2041.jpg", pictures.jpeg("mountains", seed=11)),
        "GUID-LAKE": ("Library/SMS/Attachments/7f/15/GUID-LAKE/IMG_2057.jpg",
                      pictures.jpeg("lake", seed=12)),
        "GUID-PIZZA": ("Library/SMS/Attachments/c1/09/GUID-PIZZA/"
                       "IMG_2102.jpg", pictures.jpeg("sunset", seed=13)),
    }


CONVERSATIONS = [
    # chat key: (who, text/None, minutes ago, from me, extras)
    ("alex", [
        ("alex", "Are we still on for the lake trail on Saturday?", 3050),
        ("me", "Yes! Leaving around 8. Want me to bring the coffee?", 3040),
        ("alex", "Please. I'll get the sandwiches \U0001F96A", 3035),
        ("me", "Perfect, see you at the trailhead.", 3030),
        ("alex", None, 2900, {"attach": "GUID-TRAIL",
                              "text": "Look at that view from last time"}),
        ("me", "Gorgeous. We should go back in autumn.", 2890),
        ("alex", "Agreed. Also, did you see the new bike lane on Maple?",
         1500),
        ("me", "Not yet \U0001F6B2 I'll try it tomorrow.", 1490),
        ("alex", "Loved “Not yet \U0001F6B2 I'll try it tomorrow.”",
         1489, {"tapback": ("GUID-ALEX-8", 2000)}),
        ("alex", "https://www.example.org/trail-guide/pine-ridge", 300),
        ("alex", "That's the route for Saturday ^", 299),
        ("me", "Thanks, saving it. How long is it?", 120),
        ("alex", "About 11 km, mostly shade. Bring water!", 118),
        ("me", "On it. See you at 8.", 110),
        ("alex", "Liked “On it. See you at 8.”", 109,
         {"tapback": ("GUID-ALEX-14", 2001)}),
    ]),
    ("group", [
        ("alex", "Okay everyone, Saturday hike — who is in?", 2700),
        ("jordan", "In! I'll drive.", 2690),
        ("sam", "Count me in. Can we start earlier than 8?", 2680),
        ("me", "I can do 7:30.", 2675),
        ("alex", "7:30 works. Meeting at the Pine Ridge trailhead.", 2670),
        ("sam", "Great. I'll bring the speaker \U0001F3B6", 2660),
        ("jordan", "Laughed at “I'll bring the speaker”", 2655,
         {"tapback": ("GUID-GROUP-6", 2003)}),
        ("jordan", None, 2650, {"event": 2, "title": "Hiking Crew"}),
        ("me", "Also bringing extra snacks.", 90),
    ]),
    ("jordan", [
        ("jordan", "Did you get a chance to look at the invoice?", 4200),
        ("me", "Yes, it looks right. I'll send the signed copy today.",
         4190),
        ("jordan", "Thank you!", 4185),
        ("jordan", "Also, lunch Thursday?", 600),
        ("me", "Thursday works. The usual place at noon?", 590),
        ("jordan", "See you there.", 585),
    ]),
    ("mom", [
        ("mom", "Don't forget Sunday dinner at five ❤️", 5200),
        ("me", "I'll be there! Should I bring dessert?", 5190),
        ("mom", "Just yourself. And maybe that lemon thing you made.", 5180),
        ("me", "Lemon cake it is.", 5170),
        ("mom", None, 1800, {"attach": "GUID-LAKE",
                             "text": "Saw this at the lake today"}),
    ]),
    ("pizza", [
        ("pizza", "Pizza Palace: your order #4821 is out for delivery. "
         "Estimated arrival 7:25 PM.", 1000, {"service": "SMS"}),
        ("pizza", None, 995, {"attach": "GUID-PIZZA", "service": "SMS",
                              "text": "Enjoy your dinner!"}),
    ]),
]

CODES = [("55501", "482910 is your verification code. Don't share it with "
          "anyone.", 4000)]


def messages(conn):
    from tests import fixture_apps as fa
    conn.executescript(fa.SMS_SCHEMA)
    handles = {}

    def handle(who, service="iMessage"):
        key = (who, service)
        if key not in handles:
            ident = number_of(who) if who in PEOPLE else who
            handles[key] = conn.execute(
                "INSERT INTO handle (id, service) VALUES (?, ?)",
                (ident, service)).lastrowid
        return handles[key]

    files = attachments(None)
    rowids = {}
    attachment_rows = {}

    def chat(guid, style, identifier, service, name=None, room=None):
        return conn.execute(
            "INSERT INTO chat (guid, style, chat_identifier, service_name, "
            "room_name, display_name) VALUES (?,?,?,?,?,?)",
            (guid, style, identifier, service, room, name)).lastrowid

    def add(chat_id, group, who, text, minutes, extras, index):
        extras = extras or {}
        service = extras.get("service", "iMessage")
        moment = ago(minutes=minutes)
        stamp = int(cocoa(moment) * NS)
        guid = f"GUID-{group.upper()}-{index}"
        body = None
        text = extras.get("text", text)
        item_type, title = 0, None
        assoc_guid, assoc_type = None, 0
        if "tapback" in extras:
            target, assoc_type = extras["tapback"]
            assoc_guid = f"p:0/{target}"
        if "attach" in extras:
            text = None
        if "event" in extras:
            item_type, title = extras["event"], extras["title"]
        if text and (any(ord(c) > 0x2000 for c in text)):
            body, text = fa.attributed_body(text), None
        from_me = 1 if who == "me" else 0
        handle_id = 0 if from_me else handle(who, service)
        if "attach" in extras:
            text = "￼"
        cur = conn.execute(
            "INSERT INTO message (guid, text, attributedBody, handle_id, "
            "service, date, date_read, is_from_me, cache_has_attachments, "
            "item_type, group_title, group_action_type, "
            "associated_message_guid, associated_message_type) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (guid, text, body, handle_id, service, stamp,
             stamp + 60 * NS if not from_me else 0, from_me,
             1 if "attach" in extras else 0, item_type, title, 0,
             assoc_guid, assoc_type))
        conn.execute("INSERT INTO chat_message_join VALUES (?, ?, ?)",
                     (chat_id, cur.lastrowid, stamp))
        rowids[guid] = cur.lastrowid
        if "attach" in extras:
            path, data = files[extras["attach"]]
            conn.execute(
                "INSERT INTO attachment (guid, filename, transfer_name, "
                "mime_type, uti, total_bytes) VALUES (?,?,?,?,?,?)",
                (extras["attach"], "~/" + path, path.rsplit("/", 1)[1],
                 "image/jpeg", "public.jpeg", len(data)))
            attachment_rows[extras["attach"]] = conn.execute(
                "SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT INTO message_attachment_join VALUES (?, ?)",
                         (cur.lastrowid, attachment_rows[extras["attach"]]))

    for group, items in CONVERSATIONS:
        if group == "group":
            chat_id = chat("iMessage;+;chat48213", 43, "chat48213",
                           "iMessage", name="Hiking Crew", room="chat48213")
            for who in ("alex", "jordan", "sam"):
                conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)",
                             (chat_id, handle(who)))
        else:
            service = "SMS" if group == "pizza" else "iMessage"
            number = number_of(group)
            chat_id = chat(f"{service};-;{number}", 45, number, service)
            conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)",
                         (chat_id, handle(group, service)))
        for index, entry in enumerate(items, 1):
            who, text, minutes = entry[:3]
            add(chat_id, group, who, text, minutes,
                entry[3] if len(entry) > 3 else None, index)
    for sender, text, minutes in CODES:
        chat_id = chat(f"SMS;-;{sender}", 45, sender, "SMS")
        conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)",
                     (chat_id, handle(sender, "SMS")))
        add(chat_id, "code", sender, text, minutes, {"service": "SMS"}, 1)


def message_files():
    return attachments(None)


# ── Calls ────────────────────────────────────────────────────

PHONE_SERVICE, FACETIME = "com.apple.Telephony", "com.apple.FaceTime"

CALLS = [
    # (who or raw number, minutes ago, seconds, outgoing, answered, kind,
    #  service, location)
    ("alex", 95, 421, 1, 1, 1, PHONE_SERVICE, "Springfield, IL"),
    ("mom", 380, 1260, 0, 1, 1, PHONE_SERVICE, "Shelbyville, IL"),
    ("neighbor", 540, 0, 0, 0, 1, PHONE_SERVICE, None),
    ("jordan", 1410, 305, 1, 1, 1, PHONE_SERVICE, None),
    ("casey", 1700, 2210, 0, 1, 8, FACETIME, None),
    ("pizza", 2150, 94, 1, 1, 1, PHONE_SERVICE, "Springfield, IL"),
    ("sam", 2900, 0, 1, 0, 1, PHONE_SERVICE, None),
    ("quinn", 4300, 612, 1, 1, 1, PHONE_SERVICE, "Springfield, IL"),
    ("riley", 5800, 187, 0, 1, 1, PHONE_SERVICE, None),
    ("+15550100178", 7300, 0, 0, 0, 1, PHONE_SERVICE, None),
    ("mom", 8700, 1904, 1, 1, 16, FACETIME, "Shelbyville, IL"),
    ("alex", 10100, 66, 0, 1, 1, PHONE_SERVICE, None),
    ("dentist", 12900, 158, 1, 1, 1, PHONE_SERVICE, "Springfield, IL"),
    ("morgan", 15500, 0, 0, 0, 1, PHONE_SERVICE, None),
    ("pat", 17200, 723, 0, 1, 1, PHONE_SERVICE, None),
    ("jordan", 20100, 49, 1, 1, 1, PHONE_SERVICE, None),
    ("casey", 24000, 905, 1, 1, 8, FACETIME, None),
    ("neighbor", 26500, 118, 0, 1, 1, PHONE_SERVICE, None),
    ("alex", 30000, 515, 0, 1, 1, PHONE_SERVICE, None),
    ("mom", 33800, 2650, 0, 1, 1, PHONE_SERVICE, "Shelbyville, IL"),
]


def calls(conn):
    from tests import fixture_calls as fcl
    conn.executescript(fcl.SCHEMA)
    for pk, (who, minutes, seconds, outgoing, answered, kind, service,
             place) in enumerate(CALLS, 1):
        number = number_of(who) if who in PEOPLE else who
        conn.execute(
            "INSERT INTO ZCALLRECORD (Z_PK, ZANSWERED, ZCALLTYPE, "
            "ZORIGINATED, ZREAD, ZDATE, ZDURATION, ZISO_COUNTRY_CODE, "
            "ZLOCATION, ZSERVICE_PROVIDER, ZUNIQUE_ID, ZADDRESS) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?)",
            (pk, answered, kind, outgoing, 1, cocoa(ago(minutes=minutes)),
             float(seconds), "us" if place else None, place, service,
             f"CALL-{pk}", number.encode("utf-8")))


# ── Voicemail ────────────────────────────────────────────────

VOICEMAILS = [
    (3, "neighbor", 540, 34,
     "Hi, this is Lena from next door. I wanted to let you know your "
     "package was left at my house. Come by whenever you are free. Thanks!"),
    (4, "pizza", 2160, 21,
     "Hello, this is Pizza Palace calling about your order. We are out "
     "of the gluten free crust. Please call us back. Thank you."),
    (5, "quinn", 4320, 28,
     "This is Doctor Harper's office with a reminder about your "
     "appointment next Tuesday at ten thirty. Please call to confirm."),
    (6, "+15550100178", 7300, 12,
     "Hi, I am calling about the delivery. Please call me back when you "
     "get this. Bye."),
]


def voicemail(writer):
    from tests import fixture_voicemail as fv
    folder = "Library/Voicemail"

    def build(conn):
        conn.executescript("""
            CREATE TABLE voicemail (ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
                remote_uid INTEGER, date INTEGER, token TEXT, sender TEXT,
                callback_num TEXT, duration INTEGER, expiration INTEGER,
                trashed_date INTEGER, flags INTEGER, receiver TEXT,
                label TEXT);
            CREATE TABLE map (ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
                account TEXT, label TEXT);
        """)
        for pk, who, minutes, seconds, _ in VOICEMAILS:
            number = number_of(who) if who in PEOPLE else who
            when = int(unix(ago(minutes=minutes)))
            conn.execute(
                "INSERT INTO voicemail (ROWID, remote_uid, date, sender, "
                "callback_num, duration, expiration, trashed_date, flags) "
                "VALUES (?,?,?,?,?,?,?,0,4354)",
                (pk, 100 + pk, when, number, number, seconds,
                 when + 30 * 86400))
    writer.database("HomeDomain", f"{folder}/voicemail.db", build)
    for pk, _who, minutes, _seconds, words in VOICEMAILS:
        when = ago(minutes=minutes)
        writer.file("HomeDomain", f"{folder}/{pk}.amr",
                    b"#!AMR\n" + bytes([pk]) * 1200, when)
        writer.file("HomeDomain", f"{folder}/{pk}.transcript",
                    fv.transcript_bytes(words), when)


# ── Recents ──────────────────────────────────────────────────

def recents(conn):
    conn.executescript("""
        CREATE TABLE contacts (ROWID INTEGER PRIMARY KEY, recent_id INTEGER,
            display_name TEXT, kind TEXT, address TEXT);
        CREATE TABLE recents (ROWID INTEGER PRIMARY KEY, display_name TEXT,
            bundle_identifier TEXT, sending_address TEXT,
            original_source TEXT, dates BLOB, last_date REAL, weight REAL,
            record_hash TEXT, count INTEGER, group_kind INTEGER);
    """)
    rows = [("alex", "com.apple.MobileSMS", 90, 14),
            ("jordan", "com.apple.mobilemail", 400, 6),
            ("mom", "com.apple.MobileSMS", 1800, 9),
            ("sam", "com.apple.mobilemail", 3300, 3),
            ("casey", "com.apple.MobileSMS", 6100, 4),
            ("riley", "com.apple.mobilemail", 9000, 2),
            ("pat", "com.apple.MobileSMS", 12000, 5),
            ("pizza", "com.apple.MobileSMS", 995, 2)]
    for pk, (who, bundle, minutes, count) in enumerate(rows, 1):
        person = PEOPLE[who]
        name = " ".join(x for x in (person.get("first"), person.get("last"))
                        if x) or person.get("org") or person.get("nickname")
        email = person.get("emails", [("", None)])[0][1]
        use_email = bundle == "com.apple.mobilemail" and email
        conn.execute(
            "INSERT INTO recents (ROWID, display_name, bundle_identifier, "
            "last_date, count) VALUES (?,?,?,?,?)",
            (pk, name, bundle, unix(ago(minutes=minutes)) * 1000, count))
        conn.execute(
            "INSERT INTO contacts (recent_id, display_name, kind, address) "
            "VALUES (?,?,?,?)", (pk, name, "email" if use_email else "phone",
                                 email if use_email else number_of(who)))
