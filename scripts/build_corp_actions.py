# -*- coding: utf-8 -*-
"""Fetch NSE's OFFICIAL split/bonus ratios and write scripts/corp_actions.json
({SYMBOL: [[exYmd, factor], ...]}). The price builds (build_sf_data / update_sf_data)
apply these EXACT factors on each ex-date instead of inferring the factor from the
overnight price drop — which silently breaks whenever a stock moves on the ex-date
(e.g. Adani Power's 1:5 split read as 1:4 after a +20% ex-date pop) or when a small
bonus (1:4 / 1:5 / 1:10) only dips the price <25% and gets ignored entirely.

Cheap (≈9 API calls) — safe to run daily before update_sf_data.py.
Run: python -X utf8 build_corp_actions.py
"""
import os, re, json, datetime
import build_fundamentals as F

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "corp_actions.json")


# A demerger / scheme of arrangement is NOT a split: real value leaves the stock (it goes to the
# spun-off entity), so the ex-date price drop must NOT be divided out. We only need its ex-date to
# tell the price build "do not treat this drop as a split". (Vedanta 2026-04-30, Raymond, Siemens.)
DEMERGER_KW = ("demerger", "de-merger", "scheme of arrangement", "scheme of amalgamation",
               "spin off", "spin-off", "composite scheme", "reduction of capital", "capital reduction")

def is_demerger(subj):
    s = (subj or "").lower()
    return any(k in s for k in DEMERGER_KW)


# Hardcoded FALSE corporate-action detections that are NOT in NSE's corporate-actions feed: a market
# crash whose overnight drop ca_factor mis-reads as a split/bonus, so the build divides it out and
# (after re-anchoring) mis-scales the pre-crash history. NSE never lists these (they aren't real
# actions), so without this they'd be lost on every daily regeneration. Merged into `noadjust` =
# "keep the drop as a genuine move, do NOT divide it out".
#   ADANIENT  2023-02-01/02 — Hindenburg crash + FPO withdrawal (2/3 x 3/4 = 1/2 false halving)
#   ADANIPOWER 2020-03-12   — COVID crash mis-read as 3:4
MANUAL_NOADJUST = {"ADANIENT": [20230201, 20230202], "ADANIPOWER": [20200312]}

def official_factor(subj):
    """Return (price_factor, label) for a split/bonus subject, else (None, None).
    Split: face value Rs X -> Rs Y  => factor Y/X.   Bonus B:A (B new per A held) => A/(A+B)."""
    s = (subj or "").lower()
    m = re.search(r'from\s*(?:rs\.?\s*)?([\d.]+).*?to\s*(?:rs\.?\s*)?([\d.]+)', s)
    if m and ("split" in s or "sub-division" in s or "sub division" in s):
        x, y = float(m.group(1)), float(m.group(2))
        if x and 0 < y < x:
            return y / x, "split (FV %s->%s)" % (m.group(1), m.group(2))
    m = re.search(r'bonus[^0-9]*(\d+)\s*:\s*(\d+)', s)
    if m:
        b, a = int(m.group(1)), int(m.group(2))
        if a + b and b <= 50 and a <= 250:           # ignore absurd parses (stray digits)
            return a / (a + b), "bonus %d:%d" % (b, a)
    return None, None


def fetch():
    jar = F.nse_jar()
    h = {"User-Agent": F.UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
    cmap = {}; demap = {}
    for yr in range(2016, datetime.date.today().year + 1):
        url = ("https://www.nseindia.com/api/corporates-corporateActions?index=equities"
               "&from_date=01-01-%d&to_date=31-12-%d" % (yr, yr))
        try:
            d = json.loads(F._get(url, headers=h, jar=jar, timeout=40))
            rows = d if isinstance(d, list) else d.get("data", [])
        except Exception as e:
            print("  %d: fetch failed (%s)" % (yr, str(e)[:40])); continue
        n = dm = 0
        for r in rows:
            subj = r.get("subject") or r.get("purpose") or ""
            ex = F.iso(r.get("exDate"))
            if not ex: continue
            f, _ = official_factor(subj)
            if f and 0.05 < f < 0.95:
                dd = cmap.setdefault(r.get("symbol"), {})   # combine same-day actions (e.g. BAJFINANCE
                dd[int(ex)] = round(dd.get(int(ex), 1.0) * f, 6); n += 1   # 1:2 split x 4:1 bonus = 0.10
            elif is_demerger(subj):
                demap.setdefault(r.get("symbol"), set()).add(int(ex)); dm += 1
        print("  %d: %d split/bonus, %d demerger/scheme events" % (yr, n, dm))
    return cmap, demap


def main():
    cmap, demap = fetch()
    # Merge the hardcoded false-CA overrides so they survive this daily regeneration (NSE's feed
    # doesn't list market crashes, so they'd vanish otherwise).
    for sym, exs in MANUAL_NOADJUST.items():
        demap.setdefault(sym, set()).update(exs)
    out = {
        "factors":  {sym: sorted([k, v] for k, v in d.items()) for sym, d in cmap.items()},
        "noadjust": {sym: sorted(s) for sym, s in demap.items()},
    }
    tmp = OUT + ".tmp"
    json.dump(out, open(tmp, "w"))
    os.replace(tmp, OUT)
    print("Wrote %s: %d split/bonus symbols (%d events), %d demerger/scheme symbols (%d ex-dates)"
          % (OUT, len(out["factors"]), sum(len(v) for v in out["factors"].values()),
             len(out["noadjust"]), sum(len(v) for v in out["noadjust"].values())))


if __name__ == "__main__":
    main()
