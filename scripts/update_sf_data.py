# -*- coding: utf-8 -*-
"""
Daily INCREMENTAL updater for docs/sf_stock_data.bin (the survivorship-free
backtest dataset: close/turnover/high/low/open/volume/delivery%/VWAP).

Run daily (GitHub Actions): appends only the trading days missing since the
file's `end` — no 30-year refetch, no git bloat (the workflow publishes the
bin as a GitHub Release asset instead of committing it).

Base file: tries the release asset first, falls back to docs/sf_stock_data.bin.
Touches docs/.sf_updated when (and only when) new data was appended.

Run: python -X utf8 update_sf_data.py
"""
import os, sys, json, gzip, datetime, urllib.request, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "sf_stock_data.bin")
MARK = os.path.join(ROOT, "docs", ".sf_updated")
RELEASE_URL = "https://github.com/dhruvan246/stocks-dashboard/releases/download/data/sf_stock_data.bin"

sys.path.insert(0, HERE)
import build_sf_data as B   # reuse fetch_day / parse_rows / jar (module-level code is harmless)

CA_FRACS = [1/2, 1/3, 2/3, 1/4, 3/4, 1/5, 2/5, 3/5, 1/6, 5/6, 1/8, 1/10, 1/20, 1/50,
            2.0, 3.0, 4.0, 5.0, 10.0]
def ca_factor(r):
    if 0.75 <= r <= 1.30: return 1.0
    for f in CA_FRACS:
        if abs(r / f - 1) <= 0.08: return f
    return 1.0

# Known FALSE corporate-action detections: a market crash whose overnight drop ca_factor mis-read as
# a split, divided it out, and (after re-anchoring) mis-scaled the pre-crash history. NSE's CA feed
# never lists these (they aren't real actions), so build_corp_actions can't surface them and the
# 28-day self_heal window can't reach them. self_heal reconciles these UNCONDITIONALLY every run
# (keep the drop as a genuine move). Idempotent: once the baked-in mis-scale is undone, the bin's
# ex-date ratio already equals the raw ratio, so applied_f == 1 and it no-ops.
#   ADANIENT 2023-02-01/02 — Hindenburg crash + FPO withdrawal (2/3 x 3/4 = 1/2 false halving of all
#   pre-crash history -> a too-low 52w high -> wrongly passes Distance-from-52w-High filters in 2023)
LEGACY_FALSE_CA = [("ADANIENT", 20230201), ("ADANIENT", 20230202)]

def load_base():
    # The release asset is the MERGED source-of-truth (renamed tickers consolidated). We do NOT fall
    # back to the in-repo docs copy — that copy is an old UN-merged build, and appending to it would
    # publish bad data (renamed tickers split into stubs). On 3 transient failures, fail loud so the
    # workflow stops rather than silently regressing.
    last = None
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(RELEASE_URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=180).read()
            print("Base: release asset (%.1f MB)" % (len(raw) / 1048576))
            return json.loads(gzip.decompress(raw))
        except Exception as e:
            last = e; print("Base: release fetch attempt %d failed (%s)" % (attempt + 1, e)); time.sleep(10)
    raise SystemExit("ABORT: could not fetch the merged release-asset base after 3 tries (%s) — refusing to build from the un-merged in-repo copy" % last)

def self_heal(data, CA_OFF, NOADJ, end_ymd, jar, window_days=28):
    """Belt-and-suspenders. Re-correct any split/bonus/demerger whose ex-date fell in the last
    ~4 weeks but was processed by an EARLIER daily run before NSE had published the action (so the
    incremental updater used inference and baked in the wrong treatment). For each recent official
    action we recover the factor the bin currently reflects (applied_f = raw_ratio / adjusted_ratio
    across the ex-date) and compare it to the official one; if they disagree we rescale the pre-ex
    history by correct_f/applied_f. Idempotent: once correct, applied_f == correct_f so it no-ops."""
    def od(y): return datetime.date(y // 10000, y // 100 % 100, y % 100).toordinal()
    cutoff = od(end_ymd) - window_days
    events = []   # (sym, exYmd, official_split_bonus_factor_or_None, is_demerger)
    for sym, fl in CA_OFF.items():
        for ex, fac in fl.items():
            if od(ex) >= cutoff: events.append((sym, ex, fac, False))
    for sym, exset in NOADJ.items():
        for ex in exset:
            if od(ex) >= cutoff: events.append((sym, ex, None, True))
    # Legacy false-CA corrections: reconciled every run regardless of age (idempotent), to converge
    # the release-asset loop on data the 28-day window + NSE-derived noadjust can never reach.
    for sym, ex in LEGACY_FALSE_CA:
        if not any(e[0] == sym and e[1] == ex for e in events):
            events.append((sym, ex, None, True))
    if not events: return 0
    daycache = {}
    def raw_close(ymd, sym):
        if ymd not in daycache:
            rows = B.fetch_day(datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100), jar) or []
            daycache[ymd] = {r[0]: r[1] for r in rows}
        return daycache[ymd].get(sym)
    healed = 0
    for sym, ex, off, is_dem in events:
        e = data.get(sym)
        if not e or not e.get("d"): continue
        ds = e["d"]
        j = next((k for k in range(len(ds)) if ds[k] >= ex), None)   # drop day = first day on/after ex
        if j is None or j < 1: continue
        re_ex, re_prev = raw_close(ds[j], sym), raw_close(ds[j - 1], sym)
        c = e["c"]
        if not re_ex or not re_prev or not c[j] or not c[j - 1]: continue
        adj_ratio, raw_ratio = c[j] / c[j - 1], re_ex / re_prev
        if adj_ratio <= 0: continue
        applied_f = raw_ratio / adj_ratio   # factor the bin currently reflects across the ex-date
        if applied_f <= 0: continue
        # correct_f = EXACTLY what the rebuild would apply now, given the official action AND the
        # real drop (same reconciliation guard — so combined split+bonus, ex-date moves and misparses
        # resolve to inference just like the rebuild, instead of being force-overridden).
        if off is not None and 0.75 <= raw_ratio / off <= 1.30:
            correct_f = off
        elif is_dem and not (0.75 <= raw_ratio <= 1.30):
            correct_f = 1.0
        else:
            correct_f = ca_factor(raw_ratio)
        corr = correct_f / applied_f
        if abs(corr - 1) > 0.02:   # baked-in treatment disagrees with the rebuild's -> fix
            for key in ("c", "h", "l", "op", "vw"):
                if key in e: e[key] = [round(x * corr, 2) for x in e[key][:j]] + e[key][j:]
            kind = "demerger:keep-drop" if correct_f == 1.0 else "split/bonus f=%.4f" % correct_f
            print("  SELF-HEAL %s ex %d: was f=%.4f -> %s  (rescaled %d pre-ex points x%.4f)"
                  % (sym, ex, applied_f, kind, j, corr))
            healed += 1
    return healed


def main():
    if os.path.exists(MARK): os.remove(MARK)
    D = load_base()
    last = datetime.datetime.strptime(D["end"], "%Y-%m-%d").date()
    today = datetime.date.today()
    days = []
    d = last + datetime.timedelta(days=1)
    while d <= today:
        if d.weekday() < 5: days.append(d)
        d += datetime.timedelta(days=1)
    if not days:
        print("Up to date (end=%s)" % D["end"]); return
    print("Missing trading-day candidates: %s" % ", ".join(x.isoformat() for x in days))

    data = D["data"]; meta = D["meta"]; j = B.jar(); appended = 0
    # OFFICIAL split/bonus ratios (refreshed by build_corp_actions.py in the workflow). Applied
    # exactly on the ex-date so a split/bonus with an ex-date price move (or a small bonus whose
    # drop stays inside [0.75,1.30]) is adjusted correctly instead of mis-inferred from the drop.
    try:
        _ca = json.load(open(os.path.join(HERE, "corp_actions.json")))
        CA_OFF = {s: {int(e[0]): e[1] for e in v} for s, v in _ca.get("factors", {}).items()}
        NOADJ  = {s: set(v) for s, v in _ca.get("noadjust", {}).items()}
    except Exception as ex:
        CA_OFF = {}; NOADJ = {}; print("  (corp_actions.json unavailable: %s — inference only)" % ex)
    # ISIN -> current ticker. When a NEW ticker appears carrying the same ISIN as an existing series,
    # it's a rename (same security) -> migrate the history onto the new ticker instead of starting a
    # fresh, truncated series (which would break 52w hi/lo etc. for ~a year). Same logic the full
    # build uses; this keeps future renames continuous between rebuilds.
    isin2sym = {meta[s]["isin"]: s for s in data if isinstance(meta.get(s), dict) and meta[s].get("isin")}
    # One-time format migration: old bins store per-mil offsets (hb/lb/ob/vw) + delivery x10; the
    # new format stores EXACT h/l/op/vw + delivery %. Convert on load so this updater works on either
    # (a freshly-rebuilt exact bin already has 'h' and is skipped).
    for e in data.values():
        if "h" not in e and "hb" in e:
            c = e["c"]; n = len(c)
            hb = e.get("hb", [0] * n); lb = e.get("lb", [0] * n); ob = e.get("ob", [0] * n); vwo = e.get("vw", [0] * n)
            e["h"] = [round(c[i] * (1000 + hb[i]) / 1000, 2) for i in range(n)]
            e["l"] = [round(c[i] * (1000 - lb[i]) / 1000, 2) for i in range(n)]
            e["op"] = [round(c[i] * (1000 + ob[i]) / 1000, 2) for i in range(n)]
            e["vw"] = [round(c[i] * (1000 + vwo[i]) / 1000, 2) for i in range(n)]
            e["dv"] = [round(x / 10, 2) for x in e.get("dv", [])]
            for kk in ("hb", "lb", "ob"): e.pop(kk, None)
    # MANUAL rename merges the ISIN-detector can't make: same security, but the ISIN CHANGED at the
    # rename so the ISIN-based auto-merge skips it (a safety guard against recycled tickers). These are
    # verified price-continuous. Idempotent: once the old series is folded in and dropped it's a no-op.
    MANUAL_MERGE = {"PCBL": "PHILIPCARB"}   # INE602A01023 -> INE602A01031 (Jan 2022, prices continuous)
    for new, old in MANUAL_MERGE.items():
        on = data.get(new); oo = data.get(old)
        if on and oo and on["d"] and oo["d"] and oo["d"][0] < on["d"][0]:
            idx = [i for i, dd in enumerate(oo["d"]) if dd < on["d"][0]]
            if idx:
                for f in ("d", "c", "t", "h", "l", "op", "v", "dv", "vw"):
                    if f in oo and f in on: on[f] = [oo[f][i] for i in idx] + on[f]
                data.pop(old, None); meta.pop(old, None)
                print("  MANUAL RENAME MERGE %s -> %s (%d pts prepended)" % (old, new, len(idx)))
    for day in days:
        rows = B.fetch_day(day, j)
        if not rows:
            print("  %s: no file (holiday or not yet published)" % day); continue
        # stale-file guard: NSE sometimes serves the prior day's file — if almost every
        # symbol's close equals its current last close, this is a duplicate; skip it.
        same = tot = 0
        for r in rows:
            o = data.get(r[0])
            if o and o["c"]:
                tot += 1
                if abs(o["c"][-1] - r[1]) < 0.005: same += 1
        if tot > 500 and same / tot > 0.99:
            print("  %s: duplicate of previous day (%d/%d identical) — skipped" % (day, same, tot)); continue

        ymd = int(day.strftime("%Y%m%d"))
        for r in rows:
            sym, c, p, t = r[0], r[1], r[2], r[3]
            h = r[4] if len(r) > 4 else c; l = r[5] if len(r) > 5 else c
            o_ = r[6] if len(r) > 6 else c; v = r[7] if len(r) > 7 else 0
            dlv = r[8] if len(r) > 8 else 0; vw = r[9] if len(r) > 9 else 0
            hi = round(max(h, c), 2); lo_ = round(min(l, c) if l > 0 else c, 2)   # EXACT intraday hi/lo
            opx = round(o_, 2) if o_ > 0 else round(c, 2); vwx = round(vw, 2) if vw > 0 else round(c, 2)
            dvx = round(dlv, 2) if dlv else 0
            e = data.get(sym)
            if e is None:
                isin = r[11] if len(r) > 11 and r[11] else ""
                old = isin2sym.get(isin) if isin else None
                if old and old in data and old != sym and data[old]["d"] and data[old]["d"][-1] < ymd:
                    # same ISIN as an existing older series -> ticker RENAME: migrate the history
                    data[sym] = data.pop(old); meta[sym] = meta.pop(old) if old in meta else {}
                    meta[sym]["isin"] = isin; isin2sym[isin] = sym
                    print("  %s: RENAME %s -> %s (ISIN %s) — history migrated" % (day, old, sym, isin))
                    e = data[sym]   # fall through to append today's row onto the migrated series
                else:               # genuine new listing (IPO / relist) — fresh series
                    data[sym] = {"d": [ymd], "c": [round(c, 2)], "t": [round(t, 1)], "h": [hi], "l": [lo_],
                                 "op": [opx], "v": [int(v)], "dv": [dvx], "vw": [vwx]}
                    meta.setdefault(sym, {"name": sym, "ind": "Unknown", "alive": True})
                    if isin: meta[sym]["isin"] = isin; isin2sym[isin] = sym
                    continue
            if e["d"] and e["d"][-1] >= ymd: continue   # already have this day
            prev_raw = e["c"][-1]   # series is re-anchored: last value == last RAW close
            ratio = (c / prev_raw) if prev_raw else 1.0
            off = (CA_OFF.get(sym) or {}).get(ymd)   # OFFICIAL split/bonus factor for this ex-date
            nd = NOADJ.get(sym)                       # official demerger/scheme ex-dates
            if off is not None and 0.75 <= (ratio / off) <= 1.30:
                f = off   # official split/bonus: divide out the exact ratio
            elif nd and not (0.75 <= ratio <= 1.30) and any(ymd - 3 <= e <= ymd for e in nd):
                # official demerger/scheme: real value left the stock -> keep the drop as a genuine move
                print("  %s: %s demerger/scheme drop ratio=%.3f kept (not divided out)" % (day, sym, ratio))
                f = 1.0
            else:
                f = ca_factor(ratio)
            if f != 1.0:   # corporate action: re-anchor history (prices scale by f; dv % does not)
                for key in ("c", "h", "l", "op", "vw"):
                    if key in e: e[key] = [round(x * f, 2) for x in e[key]]
                print("  %s: %s corporate action f=%s%s (history re-anchored)"
                      % (day, sym, f, " [official]" if off is not None and f == off else ""))
            e["d"].append(ymd); e["c"].append(round(c, 2)); e["t"].append(round(t, 1))
            e["h"].append(hi); e["l"].append(lo_); e["op"].append(opx)
            e["v"].append(int(v)); e["dv"].append(dvx); e["vw"].append(vwx)
            if sym in meta: meta[sym]["raw"] = round(c, 2)
        D["end"] = day.isoformat(); appended += 1
        print("  %s: appended %d rows" % (day, len(rows)))

    # Belt-and-suspenders: re-check the last ~4 weeks of official actions and fix any that an
    # earlier run mis-handled (action published after its ex-date was already processed).
    healed = self_heal(data, CA_OFF, NOADJ, int(D["end"].replace("-", "")), j)
    if healed: print("Self-heal corrected %d corporate action(s)." % healed)

    if not appended and not healed:
        print("No new trading days appended; nothing to self-heal."); return
    blob = gzip.compress(json.dumps(D, separators=(",", ":")).encode(), 6)
    open(OUT, "wb").write(blob)
    open(MARK, "w").write(D["end"])
    # tiny version marker — committed daily, lets the browser cache the big bin in IndexedDB
    # keyed to this `end` and skip re-downloading 80 MB until the data actually changes.
    json.dump({"end": D["end"]}, open(os.path.join(ROOT, "docs", "sf_meta.json"), "w"))
    print("Wrote %s (%.2f MB) + docs/sf_meta.json, end=%s" % (OUT, len(blob) / 1048576, D["end"]))

if __name__ == "__main__":
    main()
