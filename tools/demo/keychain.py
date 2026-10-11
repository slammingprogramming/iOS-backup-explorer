# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 slammingprogramming and contributors
"""The demo phone's keychain, and the key bag that opens it.

Every password here is invented and says so. The key bag is the one an
extraction by the program keeps (``Manifest.plist``): the Keychain tab asks for
``PASSWORD`` to open it.
"""

import plistlib

from . import ago

PASSWORD = "demo-backup-password"
"""The made-up backup password of the demo keychain."""


def keychain(writer):
    from tests import fixture_keychain as fk

    def item(kind, clas, created, changed, **attributes):
        attributes.setdefault("cdat", ago(**created))
        attributes.setdefault("mdat", ago(**changed))
        return kind, attributes, clas

    items = [
        item("genp", 7, dict(days=700), dict(days=30), svce="AirPort",
             acct="Morgan Home", agrp="apple", v_Data=b"demo-home-wifi-1"),
        item("genp", 7, dict(days=300), dict(days=300), svce="AirPort",
             acct="Cafe Aroma Guest", agrp="apple",
             v_Data=b"demo-cafe-wifi-2"),
        item("genp", 7, dict(days=60), dict(days=60), svce="AirPort",
             acct="Pine Ridge Lodge", agrp="apple",
             v_Data=b"demo-lodge-wifi-3"),
        item("inet", 6, dict(days=500), dict(days=45), srvr="www.example.com",
             ptcl="htps", port=443, path="/account", acct="taylor.morgan",
             atyp="form", agrp="com.apple.cfnetwork",
             v_Data=b"demo-password-example-com"),
        item("inet", 6, dict(days=400), dict(days=400),
             srvr="shop.example.net", ptcl="htps", port=443, path="/signin",
             acct="taylor.morgan@example.com", atyp="form",
             agrp="com.apple.cfnetwork", v_Data=b"demo-password-shop"),
        item("inet", 6, dict(days=250), dict(days=90),
             srvr="news.example.org", ptcl="htps", port=443, path="/",
             acct="tmorgan", atyp="form", agrp="com.apple.cfnetwork",
             v_Data=b"demo-password-news"),
        item("inet", 7, dict(days=800), dict(days=100),
             srvr="imap.example.com", ptcl="imps", port=993, path="",
             acct="taylor.morgan@example.com", agrp="com.apple.mobilemail",
             v_Data=b"demo-password-mail"),
        item("genp", 6, dict(days=200), dict(days=20),
             svce="Example Fitness", acct="taylor", labl="Example Fitness",
             agrp="com.example.fitness", sync=1,
             v_Data=bytes(range(1, 33))),
        item("genp", 8, dict(days=150), dict(days=150),
             svce="Example Notes sync token", acct="token",
             agrp="com.example.notes", v_Data=b"demo-token-0123456789abcdef"),
        item("cert", 7, dict(days=900), dict(days=900), labl="Example Root CA",
             agrp="apple", v_Data=b"0\x82demo-certificate"),
        item("keys", 7, dict(days=900), dict(days=900),
             labl="Example signing key", kcls=1, agrp="apple",
             v_Data=b"demo-key-material"),
        # tied to the phone: no backup can open these
        item("genp", 10, dict(days=600), dict(days=10),
             svce="Example device token", acct="this-phone",
             v_Data=b"demo"),
        item("genp", 11, dict(days=600), dict(days=10),
             svce="Example cloud session", acct="this-phone",
             v_Data=b"demo"),
        item("inet", 9, dict(days=600), dict(days=10),
             srvr="device.example.org", acct="this-phone", v_Data=b"demo"),
    ]
    writer.file("KeychainDomain", "keychain-backup.plist",
                fk.keychain_plist(items))
    writer.file_at_root("Manifest.plist", plistlib.dumps({
        "BackupKeyBag": fk.keybag_blob(PASSWORD),
        "IsEncrypted": True,
        "Note": "The key bag of the demo backup, kept so the keychain can "
                "be opened with the backup password."}))
