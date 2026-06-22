# -*- coding: utf-8 -*-
"""Rebuild scripts/_wb_n500_snaps.json — the archived OFFICIAL Nifty500 (a.k.a. CNX 500 pre-2015)
constituent lists used as hard validation/pin checkpoints by build_membership_v2.py.

Pulls every distinct-content capture the Internet Archive has of the index's constituent CSV
(both the modern ind_nifty500list.csv and the legacy ind_cnx500list.csv), so membership can be
pinned + validated as far back as real archives exist (2006), not just 2022.

Run: python -X utf8 build_wb_snaps.py
"""
import os, csv, json, gzip, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_wb_n500_snaps.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
URLS = [
    "archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "www.nseindia.com/content/indices/ind_nifty500list.csv",
    "www.nseindia.com/content/indices/ind_cnx500list.csv",
    "nseindia.com/content/indices/ind_cnx500list.csv",
]

def cdx(u):
    api = "http://web.archive.org/cdx/search/cdx?url=%s&output=json&collapse=digest&fl=timestamp,original,statuscode" % u
    try:
        rows = json.loads(urllib.request.urlopen(urllib.request.Request(api, headers=UA), timeout=90).read())
        return rows[1:] if rows else []
    except Exception as e:
        print("  cdx fail %-50s %s" % (u, str(e)[:30])); return []

def fetch(ts, original):
    wb = "http://web.archive.org/web/%sid_/%s" % (ts, original)
    for _ in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(wb, headers=UA), timeout=60).read()
        except Exception:
            time.sleep(3)
    return None

def parse(raw):
    if not raw: return []
    if raw[:2] == b"\x1f\x8b": raw = gzip.decompress(raw)
    rows = list(csv.reader(raw.decode("utf-8", "ignore").splitlines()))
    if not rows: return []
    hdr = [h.strip() for h in rows[0]]
    si = hdr.index("Symbol") if "Symbol" in hdr else 2
    return sorted({r[si].strip() for r in rows[1:] if len(r) > si and r[si].strip()})

def main():
    snaps = {}
    try:
        snaps = json.load(open(OUT))   # keep existing; only add/upgrade
        print("existing checkpoints:", len(snaps))
    except Exception:
        pass
    for u in URLS:
        rows = cdx(u)
        print("%-52s %d captures" % (u, len(rows)))
        for r in rows:
            ts = r[0]; orig = r[1] if len(r) > 1 else ("http://" + u); sc = r[2] if len(r) > 2 else "200"
            if sc not in ("200", "-"): continue
            d = "%s-%s-%s" % (ts[:4], ts[4:6], ts[6:8])
            if d in snaps: continue
            syms = parse(fetch(ts, orig))
            if len(syms) >= 400 and "RELIANCE" in syms:
                snaps[d] = syms
                print("   + %s  %d symbols  (TCS=%s)" % (d, len(syms), "TCS" in syms))
            elif syms:
                print("   - %s rejected (%d symbols)" % (d, len(syms)))
    tmp = OUT + ".tmp"; json.dump(snaps, open(tmp, "w")); os.replace(tmp, OUT)
    print("\nWrote %s: %d checkpoints %s" % (OUT, len(snaps), sorted(snaps)))

if __name__ == "__main__":
    main()
