# -*- coding: utf-8 -*-
"""
FULL survivorship-free price+turnover database from NSE daily bhavcopies.

  * Fetches DAILY (one bhavcopy = all stocks for that day) from START..today, so
    splits/bonuses adjust correctly via NSE's corporate-action-adjusted PREV_CLOSE
    (we chain daily returns close/prev_close into a clean adjusted index).
  * STORES weekly samples before DAILY_FROM (deep history, small) and daily after.
  * Includes every stock that ever traded — delisted ones too (kills survivorship bias).

Resumable: caches each day's parsed rows under scripts/_bhav_cache/ so re-runs skip
already-downloaded days. Output: docs/sf_stock_data.bin (gzip JSON the backtest fetches).

Run:  python -X utf8 build_sf_data.py [START=1996-01-01] [DAILY_FROM=2018-01-01]
"""
import os, sys, io, csv, json, gzip, time, zipfile, datetime, urllib.request, http.cookiejar

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "_bhav_cache"); os.makedirs(CACHE, exist_ok=True)
OUT = os.path.join(ROOT, "docs", "sf_stock_data.bin")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
MON = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]

START = datetime.date(1996, 1, 1)
DAILY_FROM = datetime.date(2018, 1, 1)
if len(sys.argv) > 1: START = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
if len(sys.argv) > 2: DAILY_FROM = datetime.datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
END = datetime.date.today()


def jar():
    j = http.cookiejar.CookieJar()
    try:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
        op.open(urllib.request.Request("https://www.nseindia.com/", headers={"User-Agent": UA}), timeout=20).read()
    except Exception:
        pass
    return j


def get(url, j, timeout=30):
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
    with op.open(req, timeout=timeout) as r:
        return r.read()


def parse_rows(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows: return []
    hdr = [h.strip().upper() for h in rows[0]]
    def idx(*ns):
        for n in ns:
            if n in hdr: return hdr.index(n)
        return -1
    iS, iSer = idx("SYMBOL"), idx("SERIES")
    iC, iP, iT = idx("CLOSE_PRICE", "CLOSE"), idx("PREV_CLOSE", "PREVCLOSE"), idx("TURNOVER_LACS", "TOTTRDVAL")
    iH, iL, iO = idx("HIGH_PRICE", "HIGH"), idx("LOW_PRICE", "LOW"), idx("OPEN_PRICE", "OPEN")
    iV, iN = idx("TTL_TRD_QNTY", "TOTTRDQTY"), idx("NO_OF_TRADES", "TOTALTRADES")
    iD, iW, iI = idx("DELIV_PER"), idx("AVG_PRICE"), idx("ISIN")
    if iS < 0 or iC < 0: return []
    def num(r, i, dflt=0.0):
        if i < 0 or i >= len(r): return dflt
        s = r[i].strip()
        if not s or s == "-": return dflt
        try: return float(s)
        except ValueError: return dflt
    out = []
    for r in rows[1:]:
        if len(r) <= max(iS, iC): continue
        if (r[iSer].strip() if iSer >= 0 else "EQ") not in ("EQ", "BE"): continue
        c = num(r, iC)
        if c <= 0: continue
        # FULL row cached so future factor additions never need a refetch:
        # [sym, close, prevclose, turnover, high, low, open, volume, deliv%, vwap, trades, isin]
        out.append([r[iS].strip(), c, num(r, iP), num(r, iT), num(r, iH, c), num(r, iL, c),
                    num(r, iO, c), num(r, iV), num(r, iD), num(r, iW), num(r, iN),
                    (r[iI].strip() if 0 <= iI < len(r) else "")])
    return out


def fetch_day(d, j):
    cf = os.path.join(CACHE, d.strftime("%Y%m%d") + ".json")
    if os.path.exists(cf):
        try:
            rows = json.load(open(cf))
            # older cache rows lack the full column set (v3 = 12 cols) — refetch; holiday [] reusable
            if not rows or len(rows[0]) >= 12:
                return rows
        except Exception: pass
    ddmmyyyy = d.strftime("%d%m%Y")
    new = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_%s.csv" % ddmmyyyy
    old = "https://nsearchives.nseindia.com/content/historical/EQUITIES/%d/%s/cm%02d%s%dbhav.csv.zip" % (
        d.year, MON[d.month-1], d.day, MON[d.month-1], d.year)
    for url in ([new, old] if d.year >= 2020 else [old, new]):
        try:
            blob = get(url, j)
            text = (zipfile.ZipFile(io.BytesIO(blob)).read(zipfile.ZipFile(io.BytesIO(blob)).namelist()[0]).decode("utf-8","replace")
                    if url.endswith(".zip") else blob.decode("utf-8","replace"))
            if "SYMBOL" in text[:200].upper():
                rows = parse_rows(text)
                json.dump(rows, open(cf, "w"))
                return rows
        except Exception:
            continue
    # cache the miss (holiday) so we don't refetch — but NOT for the last few days:
    # a same-evening build can run before NSE publishes today's file (~7 pm IST),
    # and a cached empty marker would wrongly freeze that day as a holiday forever.
    if d < datetime.date.today() - datetime.timedelta(days=4):
        json.dump([], open(cf, "w"))
    return []


def needs_fetch(d):
    cf = os.path.join(CACHE, d.strftime("%Y%m%d") + ".json")
    if not os.path.exists(cf): return True
    try:
        rows = json.load(open(cf))
        return bool(rows) and len(rows[0]) < 12   # pre-v3 cache (missing columns) -> refetch
    except Exception:
        return True

def prefetch_parallel(dates, workers=6):
    """Fill the cache in parallel (nsearchives is a static CDN; modest concurrency is fine)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    local = threading.local()
    def work(d):
        if not hasattr(local, "jar"): local.jar = jar()
        try: fetch_day(d, local.jar)
        except Exception: pass
        time.sleep(0.05)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in ex.map(work, dates):
            done += 1
            if done % 500 == 0: print("  prefetch %d/%d" % (done, len(dates)), flush=True)

def main():
    all_days = []
    d = START
    while d <= END:
        if d.weekday() < 5: all_days.append(d)
        d += datetime.timedelta(days=1)
    todo = [d for d in all_days if needs_fetch(d)]
    print("Trading-day candidates: %d | needing (re)fetch: %d" % (len(all_days), len(todo)), flush=True)
    if todo: prefetch_parallel(todo)

    j = jar(); acc = {}; isin_of = {}; tried = got = 0; prev_sig = None; skipped_dupes = 0
    for d in all_days:
        tried += 1
        rows = fetch_day(d, j)   # cache hit for nearly all after prefetch
        if rows:
            # NSE's per-day URL returns the PRIOR trading day's file on holidays (wrong URL date,
            # correct date inside). Two real trading days are never byte-identical across 2600+ stocks,
            # so an exact duplicate of the previous accepted day == a holiday → skip it (else it injects
            # a fake flat day that corrupts RSI/returns).
            sig = hash(tuple((r[0], r[1]) for r in rows))
            if sig == prev_sig:
                skipped_dupes += 1
                continue
            prev_sig = sig
            got += 1; ymd = int(d.strftime("%Y%m%d"))
            for row in rows:
                sym, c, p, t = row[0], row[1], row[2], row[3]
                h = row[4] if len(row) > 4 else c
                l = row[5] if len(row) > 5 else c
                o = row[6] if len(row) > 6 else c
                v = row[7] if len(row) > 7 else 0
                dlv = row[8] if len(row) > 8 else 0
                vw = row[9] if len(row) > 9 else 0
                if len(row) > 11 and row[11]: isin_of[sym] = row[11]   # last ISIN seen (old-format files carry it)
                acc.setdefault(sym, []).append((ymd, c, p, t, h, l, o, v, dlv, vw))
        if tried % 1000 == 0:
            print("  ...%s  days=%d/%d  symbols=%d" % (d, got, tried, len(acc)), flush=True)
    print("Fetched %d/%d trading days; %d symbols; skipped %d holiday-duplicate days" % (got, tried, len(acc), skipped_dupes), flush=True)

    # ---- MERGE renamed tickers into ONE continuous series under the current ticker ----
    # A rename (Ami Organics AMIORG -> Acutaas ACUTAAS, GET&D -> GVT&D, ADANITRANS -> ADANIENSOL, ...)
    # starts a fresh bhavcopy series under the new ticker, which truncates every lookback window
    # (52w hi/lo, returns, RSI) and splits corporate actions for up to a year. Tickers sharing an
    # ISIN are the SAME security across the rename (a recycled ticker keeps a DIFFERENT ISIN, so this
    # never merges two real companies); symchg.csv fills pre-2020 gaps where the file carried no ISIN.
    rename_to = {}
    by_isin = {}
    for sym in acc:
        isin = isin_of.get(sym)
        if isin: by_isin.setdefault(isin, []).append(sym)
    for isin, syms in by_isin.items():
        if len(syms) < 2: continue
        canon = max(syms, key=lambda s: max(o[0] for o in acc[s]))   # latest-trading ticker = current
        for s in syms:
            if s != canon: rename_to[s] = canon
    try:                                                             # symchg.csv supplement (old,new)
        sc = os.path.join(HERE, "symchg.csv")
        if not os.path.exists(sc): sc = os.path.join(os.path.dirname(ROOT), "symchg.csv")
        for r in csv.reader(open(sc, encoding="utf-8", errors="replace")):
            if len(r) >= 3 and r[1].strip() and r[2].strip():
                o2, n2 = r[1].strip().upper(), r[2].strip().upper()
                if o2 in acc and o2 not in rename_to:
                    tgt = rename_to.get(n2, n2)
                    if tgt in acc and tgt != o2: rename_to[o2] = tgt
    except Exception as e:
        print("  (symchg.csv not loaded for merge: %s)" % e, flush=True)
    if rename_to:
        merged = {}
        for sym, obs in acc.items():
            merged.setdefault(rename_to.get(sym, sym), []).extend(obs)
        for sym in merged:
            dd = {}
            for rec in sorted(merged[sym]): dd[rec[0]] = rec        # sort by date + dedup same-day overlap
            merged[sym] = [dd[k] for k in sorted(dd)]
        acc = merged
        ex = ", ".join("%s->%s" % (o, n) for o, n in list(rename_to.items())[:6])
        print("Merged %d renamed tickers into their current symbol (e.g. %s)" % (len(rename_to), ex), flush=True)
    # export old->current map so membership (build_membership_v2) keys on the SAME current tickers
    # the merged price series uses — otherwise renamed stocks vanish from historical backtests.
    json.dump(rename_to, open(os.path.join(HERE, "_rename_map.json"), "w"))

    cur = {}
    try:
        import re, base64
        h = open(os.path.join(ROOT, "docs", "nse-bse-dashboard.html"), encoding="utf-8").read()
        b64 = re.search(r'<script id="compressedData"[^>]*>([A-Za-z0-9+/=]+)</script>', h).group(1)
        D = json.loads(gzip.decompress(base64.b64decode(b64)))
        for m in D["meta"].values():
            cur[m["symbol"]] = {"name": m.get("name"), "industry": m.get("industry") or m.get("sector")}
    except Exception as e:
        print("  (current meta unavailable:", e, ")")

    df = int(DAILY_FROM.strftime("%Y%m%d"))
    # Corporate-action ratios: bonus/split ex-dates appear as huge overnight "drops" because
    # NSE's PREV_CLOSE is NOT adjusted (verified: HDFCBANK 1:1 bonus 2025-08-26, prev_close
    # left at the raw prior close). Cash-segment circuit filters cap genuine daily moves at
    # ~20%, so a ratio far outside [0.75, 1.30] that sits within 8% of a canonical fraction
    # is a corporate action — divide it out; anything else (e.g. a real F&O-stock crash at a
    # non-fraction ratio) is kept as a genuine market move.
    CA_FRACS = [1/2, 1/3, 2/3, 1/4, 3/4, 1/5, 2/5, 3/5, 1/6, 5/6, 1/8, 1/10, 1/20, 1/50,
                2.0, 3.0, 4.0, 5.0, 10.0]
    def ca_factor(r):
        if 0.75 <= r <= 1.30: return 1.0
        for f in CA_FRACS:
            if abs(r / f - 1) <= 0.08: return f
        return 1.0
    # OFFICIAL corporate actions (scripts/corp_actions.json, from NSE corporate-actions API).
    # 3-way priority on each ex-date drop:
    #   1) official split/bonus -> divide out the EXACT factor (fixes Adani Power's 1:5-read-as-1:4
    #      and small bonuses whose drop hides inside [0.75,1.30]);
    #   2) official demerger/scheme -> do NOT divide out (real value left the stock, e.g. Vedanta
    #      2026-04-30 773->271; dividing it out fabricated a fake 1/3 low);
    #   3) otherwise -> ca_factor inference (covers splits the API/parse missed, e.g. GRASIM).
    try:
        _ca = json.load(open(os.path.join(HERE, "corp_actions.json")))
        CA_OFF = {s: sorted(map(tuple, v)) for s, v in _ca.get("factors", {}).items()}
        NOADJ  = {s: set(v) for s, v in _ca.get("noadjust", {}).items()}
        print("Official corporate actions: %d split/bonus symbols, %d demerger symbols" %
              (len(CA_OFF), len(NOADJ)), flush=True)
    except Exception as e:
        CA_OFF = {}; NOADJ = {}; print("  (corp_actions.json unavailable: %s — inference only)" % e, flush=True)
    applied_off = bad_recon = demerger_skipped = 0
    skip_log = []
    data, meta, dead = {}, {}, 0
    for sym, obs in acc.items():
        obs.sort(); ds, cs, ts, hr, lr, orr, vol, dv, vr = [], [], [], [], [], [], [], [], []
        adj = None; lastWeek = None
        offlist = CA_OFF.get(sym, []); oi = 0
        while oi < len(offlist) and obs and offlist[oi][0] <= obs[0][0]:
            oi += 1   # ex-dates on/before the first data day already happened — nothing to adjust
        for i, (ymd, c, p, t, h, l, o, v, dlv, vw) in enumerate(obs):
            if adj is None:
                adj = c
            else:
                # Chain on ACTUAL close-to-close ratios — NOT the file's PREV_CLOSE, which NSE
                # sometimes mis-states by ±1-6% on random days (verified on CGCL), silently
                # drifting the series. Within any CA-free stretch the adjusted series equals raw
                # NSE prices exactly; on an ex-date we divide out the OFFICIAL factor (fallback:
                # inference) so 52w hi/lo and price filters stay paisa-exact.
                base = obs[i-1][1] or 0
                r = (c / base) if base else 1.0
                f = None
                while oi < len(offlist) and offlist[oi][0] <= ymd:
                    cand = offlist[oi][1]; oi += 1
                    if 0.75 <= (r / cand) <= 1.30:   # implied ex-date move within circuit-ish bounds
                        f = cand; applied_off += 1
                    else:
                        bad_recon += 1   # official ratio doesn't reconcile with the drop -> use inference
                if f is None:
                    nd = NOADJ.get(sym)
                    if nd and not (0.75 <= r <= 1.30) and any(ymd - 3 <= e <= ymd for e in nd):
                        # official demerger/scheme ex-date -> real value left the stock; keep the
                        # drop as a genuine move (do NOT divide it out).
                        demerger_skipped += 1
                        if len(skip_log) < 80: skip_log.append((sym, ymd, round(r, 3)))
                        f = 1.0
                    else:
                        f = ca_factor(r)
                adj = adj * (r / f)
            if ymd >= df:
                keep = True                              # daily for recent
            else:
                wk = datetime.date(ymd//10000, ymd//100 % 100, ymd % 100).isocalendar()[:2]
                keep = (wk != lastWeek); lastWeek = wk   # weekly for old
            if keep:
                ds.append(ymd); cs.append(adj); ts.append(round(t, 1)); raw_last = c
                # high/low/open/vwap kept as RATIOS to close (CA-adjustment cancels in the ratio) —
                # converted to EXACT adjusted ₹ below so 52w hi/lo and other filters are paisa-exact.
                hr.append((h / c) if (h >= c and c) else 1.0)
                lr.append((l / c) if (0 < l <= c and c) else 1.0)
                orr.append((o / c) if (o > 0 and c) else 1.0)
                vol.append(int(v))
                dv.append(round(dlv, 2) if dlv else 0)              # delivery % (exact; 0 = unavailable)
                vr.append((vw / c) if (vw > 0 and c) else 1.0)
        if len(ds) < 12: continue
        # Re-anchor (Yahoo-style adjusted prices): scale so the LAST value equals the latest RAW
        # close. EXACT high/low/open/vwap = adjusted-close x ratio, rounded to paise.
        k = (raw_last / cs[-1]) if cs[-1] else 1.0
        hs = [round(cs[i] * k * hr[i], 2) for i in range(len(ds))]
        ls = [round(cs[i] * k * lr[i], 2) for i in range(len(ds))]
        ops = [round(cs[i] * k * orr[i], 2) for i in range(len(ds))]
        vws = [round(cs[i] * k * vr[i], 2) for i in range(len(ds))]
        cs = [round(x * k, 2) for x in cs]
        data[sym] = {"d": ds, "c": cs, "t": ts, "h": hs, "l": ls, "op": ops, "v": vol, "dv": dv, "vw": vws}
        alive = sym in cur
        dead += (not alive)
        meta[sym] = {"name": (cur.get(sym) or {}).get("name") or sym,
                     "ind": (cur.get(sym) or {}).get("industry") or "Unknown", "alive": alive,
                     "raw": round(obs[-1][1], 2)}   # latest RAW market close (adjusted series level can drift from market price)
        if sym in isin_of: meta[sym]["isin"] = isin_of[sym]
    print("Stored %d symbols (%d delisted/absent today); official split/bonus applied=%d, non-reconciling=%d, "
          "demerger/scheme drops kept (not divided out)=%d"
          % (len(data), dead, applied_off, bad_recon, demerger_skipped), flush=True)
    if skip_log:
        print("  demerger/scheme ex-dates kept as real drops (sym, date, ratio):", flush=True)
        for s, y, rr in skip_log: print("    %-12s %d  ratio=%.3f" % (s, y, rr), flush=True)
    blob = gzip.compress(json.dumps({"start": START.isoformat(), "dailyFrom": DAILY_FROM.isoformat(),
                                     "end": END.isoformat(), "meta": meta, "data": data},
                                    separators=(",", ":")).encode(), 6)
    open(OUT, "wb").write(blob)
    print("Wrote %s (%.2f MB)" % (OUT, len(blob)/1048576), flush=True)


if __name__ == "__main__":
    main()
