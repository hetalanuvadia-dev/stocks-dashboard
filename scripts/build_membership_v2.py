# -*- coding: utf-8 -*-
"""
FINAL point-in-time index membership builder (all 7 backtest indexes).

Sources, in order of authority:
  1. Parsed NSE reconstitution press releases (_changelog.json) — exact effective
     dates for every captured add/drop, 2015-2026.
  2. Archived official full lists (_wb_n500_snaps.json, Nifty 500 only) — pinned
     as hard checkpoints; reconstruction is forced exact at those dates.
  3. Today's official NSE constituent CSVs — the anchor each walk starts from.
  4. Old scrapbook (indices_history.json) — kept ONLY for dates before the
     earliest accurate event (deep history fallback).

Symbols are converted to the ERA-CORRECT ticker (the symbol that actually traded
on that date) using symchg.csv + a supplement, so membership matches the
survivorship-free bhavcopy price series keys of that period.

Writes: scripts/indices_history.json  +  docs/stock_data.bin (indicesHistory).
Run: python -X utf8 build_membership_v2.py
"""
import os, re, csv, json, gzip, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

SLUGS = {  # index display name -> NSE current-list slug
    "Nifty 50": "nifty50", "Nifty Next 50": "niftynext50", "Nifty 100": "nifty100",
    "Nifty 200": "nifty200", "Nifty 500": "nifty500",
    "Nifty Midcap 150": "niftymidcap150", "Nifty Smallcap 250": "niftysmallcap250",
}

# ---------- renames (old -> new, with the date the NEW symbol started) ----------
MON = {m: i for i, m in enumerate(["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"], 1)}
def dmy_iso(s):
    m = re.match(r"(\d{1,2})-([A-Z]{3})-(\d{4})", s.strip().upper())
    return f"{int(m.group(3)):04d}-{MON[m.group(2)]:02d}-{int(m.group(1)):02d}" if m and m.group(2) in MON else None

def load_renames():
    ren = {}  # old -> (new, date)
    try:
        sc = os.path.join(HERE, "symchg.csv")                       # repo copy first (works in CI)
        if not os.path.exists(sc): sc = os.path.join(os.path.dirname(ROOT), "symchg.csv")
        for r in csv.reader(open(sc, encoding="utf-8", errors="replace")):
            if len(r) >= 4 and r[1].strip() and r[2].strip():
                d = dmy_iso(r[3]) if r[3].strip() else None
                ren[r[1].strip().upper()] = (r[2].strip().upper(), d or "1900-01-01")
    except Exception as e:
        print("(symchg.csv not loaded:", e, ")")
    # supplement: recent renames missing from symchg.csv; date resolved from SF price data below
    for old, new in [("GMRINFRA","GMRAIRPORT"), ("GET&D","GVT&D"), ("HBLPOWER","HBLENGINE"),
                     ("AKZOINDIA","JSWDULUX"), ("SWANENERGY","SWANCORP"), ("MFL","EPIGRAL"),
                     ("GLS","ALIVUS"), ("ADANITRANS","ADANIENSOL"), ("MOTHERSUMI","MOTHERSON")]:
        ren.setdefault(old, (new, None))
    return ren

def resolve_supplement_dates(ren):
    """date of a rename ~= first trading day of the NEW symbol in the SF data."""
    try:
        D = json.loads(gzip.decompress(open(os.path.join(ROOT, "docs", "sf_stock_data.bin"), "rb").read()))
        first = {sym: str(o["d"][0]) for sym, o in D["data"].items() if o["d"]}
        for old, (new, d) in list(ren.items()):
            if d is None:
                f = first.get(new)
                ren[old] = (new, f"{f[:4]}-{f[4:6]}-{f[6:]}" if f else "2099-01-01")
    except Exception as e:
        print("(SF data not loaded for rename dates:", e, ")")
        for old, (new, d) in list(ren.items()):
            if d is None: ren[old] = (new, "2099-01-01")
    return ren

REN = resolve_supplement_dates(load_renames())          # old -> (new, date)
FWD = {}                                                # canonical resolution old->latest
def canon(s):
    seen = set()
    while s in REN and s not in seen: seen.add(s); s = REN[s][0]
    return s
BACK = {}                                               # new -> (old, date)
for o, (n, d) in REN.items(): BACK.setdefault(n, (o, d))
def era_symbol(c, date):
    """era-correct ticker for canonical symbol c at `date` (walk rename chain backward)."""
    seen = set()
    while c in BACK and c not in seen:
        old, d = BACK[c]
        if date < d: seen.add(c); c = old
        else: break
    return c

# ---------- fetch today's official lists ----------
def get(url, tries=5):
    last = None
    for _ in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception as e: last = e; time.sleep(3)
    raise last
def today_list(slug):
    raw = get(f"https://archives.nseindia.com/content/indices/ind_{slug}list.csv")
    if raw[:2] == b"\x1f\x8b": raw = gzip.decompress(raw)
    rows = list(csv.reader(raw.decode("utf-8", "ignore").splitlines()))
    si = rows[0].index("Symbol") if "Symbol" in rows[0] else 2
    return sorted({r[si].strip() for r in rows[1:] if len(r) > si and r[si].strip()})

# ---------- reconstruction ----------
def merge_same_eff(events):
    """combine events sharing an effective date (fixes the overwrite bug)."""
    by = {}
    for c in events:
        e = by.setdefault(c["eff"], {"eff": c["eff"], "excluded": [], "included": []})
        e["excluded"] += c["excluded"]; e["included"] += c["included"]
    return [by[k] for k in sorted(by)]

def reconstruct(anchor_today, events, checkpoints=None):
    """Backward walk from today's anchor; returns {eff: set(canonical members)}.
       checkpoints {date: set} are pinned exact afterwards."""
    ev = merge_same_eff(events)
    snaps = {}
    m = {canon(s) for s in anchor_today}
    for c in reversed(ev):
        inc = {canon(x) for x in c["included"]}; exc = {canon(x) for x in c["excluded"]}
        snaps[c["eff"]] = set(m)         # membership in force FROM c.eff
        m = (m - inc) | exc              # roll back to before this event
    snaps["1900-01-01"] = set(m)         # pre-changelog baseline
    if checkpoints:
        for d, S in checkpoints.items(): snaps[d] = {canon(x) for x in S}
    return snaps

def validate_n500(snaps, wb):
    def asof(d):
        best = None
        for k in sorted(snaps):
            if k <= d: best = k
        return snaps[best]
    print("  validation vs archived official lists (canonical symbols):")
    worst = 100.0
    for d in sorted(wb):
        off = {canon(x) for x in wb[d]}; rec = asof(d)
        pct = 100 * len(off & rec) / len(off)
        print("    %s  match %.1f%%  off-by %d" % (d, pct, len(off ^ rec)))
        worst = min(worst, pct)
    return worst

def main():
    changelog = json.load(open(os.path.join(HERE, "_changelog.json")))
    wb = json.load(open(os.path.join(HERE, "_wb_n500_snaps.json")))
    hist_path = os.path.join(HERE, "indices_history.json")
    H = json.load(open(hist_path, encoding="utf-8"))
    # old->current map from the PRICE build (build_sf_data merges renamed series by ISIN). Membership
    # must key on the SAME current tickers the merged price series uses, else renamed stocks vanish
    # from historical backtests. This supersedes the old era_symbol() (which deliberately used the OLD
    # ticker to match the previously-split price series — no longer how the price data is keyed).
    try:
        RENAME = json.load(open(os.path.join(HERE, "_rename_map.json")))
    except Exception:
        RENAME = {}; print("(_rename_map.json not found — membership keeps era symbols)")
    def to_current(s):
        seen = set()
        while s in RENAME and s not in seen: seen.add(s); s = RENAME[s]
        return s

    for idx, slug in SLUGS.items():
        events = changelog.get(idx, [])
        if not events:
            print(f"{idx}: no change events — left as-is"); continue
        anchor = today_list(slug)
        cps = {d: set(v) for d, v in wb.items()} if idx == "Nifty 500" else None
        snaps = reconstruct(anchor, events, cps)
        if idx == "Nifty 500":
            worst = validate_n500(snaps, wb)
            if worst < 99.0:   # SAFETY GATE: never overwrite good membership with a degraded rebuild
                raise SystemExit("ABORT: Nifty500 validation %.1f%% < 99%% — refusing to write "
                                 "(likely a missing input or NSE fetch issue); keeping committed data." % worst)
        # era-correct symbols per snapshot date so they match that period's bhavcopy series
        new_snaps = [{"effectiveDate": d, "symbols": sorted(set(to_current(s) for s in S))}
                     for d, S in snaps.items() if d != "1900-01-01"]
        new_snaps.sort(key=lambda x: x["effectiveDate"])
        earliest = new_snaps[0]["effectiveDate"]
        kept_old = [s for s in H.get(idx, []) if s["effectiveDate"] < earliest]
        H[idx] = sorted(kept_old + new_snaps, key=lambda s: s["effectiveDate"])
        print(f"{idx}: {len(kept_old)} scrapbook (pre-{earliest}) + {len(new_snaps)} accurate = {len(H[idx])} snapshots")

    json.dump(H, open(hist_path, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"\nWrote {hist_path}")
    binp = os.path.join(ROOT, "docs", "stock_data.bin")
    D = json.loads(gzip.decompress(open(binp, "rb").read()))
    D["indicesHistory"] = {**D.get("indicesHistory", {}), **{k: H[k] for k in SLUGS if k in H}}
    open(binp, "wb").write(gzip.compress(json.dumps(D, separators=(",", ":")).encode(), 6))
    print(f"Wrote {binp} ({os.path.getsize(binp)/1048576:.1f} MB)")

    # spot checks
    n5 = H["Nifty 500"]
    def asof(d):
        best = None
        for s in n5:
            if s["effectiveDate"] <= d and (not best or s["effectiveDate"] > best["effectiveDate"]): best = s
        return set(best["symbols"])
    print("\nSpot checks (Nifty 500):")
    print("  2023-03-30 SCI (should be True - pre-reshuffle):", "SCI" in asof("2023-03-30"))
    print("  2023-03-31 SCI (should be False - new list live):", "SCI" in asof("2023-03-31"))
    print("  2022-10-09 AWL (Sept-22 add, was broken before):", "AWL" in asof("2022-10-09"))
    print("  2022-06-01 GMRINFRA era-symbol (not GMRAIRPORT):", "GMRINFRA" in asof("2022-06-01"), "/", "GMRAIRPORT" in asof("2022-06-01"))

if __name__ == "__main__":
    main()
