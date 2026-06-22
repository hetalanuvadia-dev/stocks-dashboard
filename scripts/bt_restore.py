# -*- coding: utf-8 -*-
"""Restore the shared (open) backtest history from a daily backup, if it ever gets wiped/vandalised.
Pushes the chosen backup back into Supabase via the open write RPC.

  python scripts/bt_restore.py                       # restore from the NEWEST backup in backups/
  python scripts/bt_restore.py backups/bt_history_2026-06-19.json   # restore a specific day
  python scripts/bt_restore.py --list                # just list available backups
"""
import sys, os, json, glob, urllib.request

URL = "https://nebjnsndgrhumnkuipqy.supabase.co/rest/v1/rpc/bt_owner_set"
KEY = "sb_publishable_MDlQwiVc5deii91__UNeDg_z9r4Fk98"
SECRET = "sw_owner_8Kq2Lm9Xp4Rt7v"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAK = sorted(glob.glob(os.path.join(ROOT, "backups", "bt_history_*.json")))

if "--list" in sys.argv:
    for f in BAK:
        try: n = len(json.load(open(f)))
        except Exception: n = "?"
        print("  %s  (%s entries)" % (os.path.basename(f), n))
    print("%d backups available" % len(BAK)); sys.exit(0)

arg = [a for a in sys.argv[1:] if not a.startswith("-")]
path = arg[0] if arg else (BAK[-1] if BAK else None)
if not path or not os.path.exists(path):
    sys.exit("No backup file found. Run with --list to see options.")

data = json.load(open(path))
if not isinstance(data, list) or not data:
    sys.exit("Backup is empty/invalid: %s" % path)
body = json.dumps({"secret": SECRET, "payload": data}).encode()
req = urllib.request.Request(URL, body, {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
resp = urllib.request.urlopen(req, timeout=30).read().decode()
print("Restored %d entries from %s  (server: %s)" % (len(data), os.path.basename(path), resp or "ok"))
