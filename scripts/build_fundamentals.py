# -*- coding: utf-8 -*-
"""
Build a POINT-IN-TIME quarterly net-profit dataset for the stock backtest, to add
StockView's two fundamental factors: profitYoyPct (Net Profit Qtr Growth YoY %) and
profitBase (year-ago-quarter net profit).

Source = NSE (free, official):
  - corporates-financial-results?symbol=X&period=Quarterly  → every quarterly filing
    with its broadcast/announcement date (point-in-time!), quarter period, and XBRL link.
  - XBRL  → ProfitLossForPeriod for the quarter. NSE Ind-AS context convention:
    context "OneD" = STANDALONE current quarter, "FourD" = CONSOLIDATED current quarter
    (we also fall back to any context whose period == the quarter).

Output: scripts/fundamentals.json = { SYM: [ [qEndYYYYMMDD, npStd_cr, annStd, npCon_cr, annCon], ... ] }
(np in ₹ crore; ann = announcement date YYYYMMDD; null where a basis wasn't filed). Sorted by
quarter end. Standalone and consolidated each carry their OWN announcement date (they're often
filed separately), so the backtest can honour StockView's Standalone/Consolidated basis toggle
point-in-time.

Run:  python -X utf8 build_fundamentals.py [SYM1 SYM2 ...]   (default = a small test set)
Cache: scripts/_xbrl_cache/ (gitignored via scripts/_*). Resumable.
"""
import os, sys, re, json, time, gzip, threading, concurrent.futures, urllib.request, urllib.parse, http.cookiejar

MIN_QE = 20170101   # skip quarters ending before this — NSE's XBRL archive is sparse pre-2016
                    # and the backtest default starts 2020 (year-ago bases need ~2018). Cuts the 404 storm.

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_xbrl_cache"); os.makedirs(CACHE, exist_ok=True)
OUT = os.path.join(HERE, "fundamentals.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}

def _get(url, headers=None, jar=None, timeout=30, binary=False):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)) if jar is not None else urllib.request.build_opener()
    r = op.open(req, timeout=timeout); data = r.read()
    if r.headers.get("Content-Encoding") == "gzip": data = gzip.decompress(data)
    return data if binary else data.decode("utf-8", "replace")

def nse_jar():
    jar = http.cookiejar.CookieJar()
    for u in ("https://www.nseindia.com/",
              "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"):
        try: _get(u, headers={"User-Agent": UA, "Accept": "text/html"}, jar=jar, timeout=20)
        except Exception: pass
    return jar

def iso(d):  # "16-Jan-2025 20:20" or "31-Mar-2024" -> "20240331"
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", d or "")
    if not m: return None
    return "%04d%02d%02d" % (int(m.group(3)), MONTHS[m.group(2).title()], int(m.group(1)))

def xbrl_profit(xml, basis_hint=None):
    """Return (np_standalone_cr, np_consolidated_cr) for the CURRENT QUARTER from one filing.

    NSE Ind-AS quirk: context PERIOD dates are unreliable (a 9-month value can be tagged with
    the quarter's dates), so we don't trust them. What IS reliable:
      - context 'OneD' = the current 3-month quarter (its basis varies by filing type);
      - each context carries a NatureOfReportStandaloneConsolidated fact (Standalone/Consolidated);
      - in a COMBINED filing, 'FourD' is the consolidated current quarter (different nature to OneD);
        in a single-basis filing, 'FourD' is the YTD of the SAME nature → ignore it.
    Net-profit tag namespace varies: `in-bse-fin:` (old corporates-financial-results) vs
    `in-capmkt:` (new integrated-filing, used by all 2025+ quarters & recent IPOs). Banks/NBFCs
    use ...ForThePeriod. basis_hint (the API 'consolidated' field) is the fallback when the XBRL
    omits the nature tag — integrated filings file each basis as a SEPARATE filing.
    """
    nat = {}
    for m in re.finditer(r'NatureOfReportStandaloneConsolidated contextRef="([^"]+)"[^>]*>([^<]+)<', xml):
        nat[m.group(1)] = m.group(2).strip().lower()
    hint = (basis_hint or "").lower()
    plp = {}
    for m in re.finditer(r'<in-(?:bse-fin|capmkt):ProfitLossFor(?:The)?Period contextRef="([^"]+)"[^>]*>([^<]+)<', xml):
        if m.group(1) not in plp:
            plp[m.group(1)] = round(float(m.group(2)) / 1e7, 2)   # rupees -> crore
    attr = {}                                            # owners' share (consolidated only)
    for m in re.finditer(r'<in-(?:bse-fin|capmkt):ProfitOrLossAttributableToOwnersOfParent contextRef="([^"]+)"[^>]*>([^<]+)<', xml):
        if m.group(1) not in attr:
            try: attr[m.group(1)] = round(float(m.group(2)) / 1e7, 2)
            except Exception: pass
    std = con = None
    one, one_nat = plp.get("OneD"), nat.get("OneD", "") or hint
    if one is not None:
        if "consol" in one_nat: con = attr.get("OneD", one)   # consolidated -> attributable to owners
        else: std = one                                  # standalone or unlabelled
    four, four_nat = plp.get("FourD"), nat.get("FourD", "") or hint
    if four is not None and four_nat != one_nat:         # combined filing: other basis, current Q
        if "consol" in four_nat: con = con if con is not None else attr.get("FourD", four)
        else: std = std if std is not None else four
    return std, con

# ---- NSE Integrated Filing (recent quarters) ----------------------------------------------
# In early 2025 NSE moved quarterly results to the "Integrated Filing" system. The old
# corporates-financial-results endpoint above STOPS at the Dec-2024 quarter, so we also pull
# from integrated-filing-results. Same OneD=current-quarter context convention, in-capmkt: ns.
def integrated_profit(xml, con=False):
    """Net profit (₹ crore) for the CURRENT quarter from an Integrated-Filing INDAS iXBRL.
    For CONSOLIDATED filings use profit ATTRIBUTABLE TO OWNERS OF THE PARENT (excludes minority /
    non-controlling interest) — this is what Trendlyne/StockView report; fall back to the total
    ProfitLossForPeriod when the tag is absent (standalone, or no minority). Banks/NBFCs tag the
    total as ProfitLossForThePeriod (with "The")."""
    if con:
        m = re.search(r'ProfitOrLossAttributableToOwnersOfParent contextRef="OneD"[^>]*>([-0-9.eE+]+)<', xml)
        if m:
            try: return round(float(m.group(1)) / 1e7, 2)
            except Exception: pass
    m = re.search(r'ProfitLossFor(?:The)?Period contextRef="OneD"[^>]*>([-0-9.eE+]+)<', xml)
    if not m:   # insurers: general -> ProfitLossAfterTax; life -> ProfitLossAfterTaxAndExtraordinaryItems
        m = re.search(r'ProfitLossAfterTax(?:AndExtraordinaryItems)? contextRef="OneD"[^>]*>([-0-9.eE+]+)<', xml)
    try: return round(float(m.group(1)) / 1e7, 2) if m else None
    except Exception: return None

def fetch_integrated(sym, jar, skip=()):
    """Recent quarters from the Integrated Filing endpoint. `skip` = qEnds already stored, so
    their (1 MB) iXBRL isn't re-downloaded — keeps the weekly refresh cheap. Returns
    {qEndYYYYMMDD: {'std':(np,ann), 'con':(np,ann)}}. None on a fetch error (caller retries)."""
    skip = {int(q) for q in skip}
    url = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=%s&period=Quarterly"
           % urllib.parse.quote(sym))
    try:
        rows = json.loads(_get(url, headers={"User-Agent": UA, "Accept": "application/json",
                                             "Referer": "https://www.nseindia.com/"}, jar=jar, timeout=30)).get("data", [])
    except Exception:
        return None
    byq = {}
    # NSE returns duplicate rows per (qe,basis) — one dated, one broadcast_Date=None. Take the dated
    # one first so the announcement date isn't lost (engine skips quarters with no date).
    rows.sort(key=lambda r: 0 if r.get("broadcast_Date") else 1)
    for r in rows:
        xb = r.get("xbrl") or ""
        # Financials only (skip GOVERNANCE). _INDAS (most), _BANKING (banks), _NBFC_INDAS (NBFCs).
        if r.get("type") != "Integrated Filing- Financials" or not xb: continue
        qe = iso(r.get("qe_Date"))
        if not qe or int(qe) in skip: continue
        key = "con" if "consol" in (r.get("consolidated") or "").lower() else "std"
        d = byq.setdefault(qe, {})
        if key in d: continue
        cf = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9]", "_", xb.rsplit("/", 1)[-1]))
        try:
            if os.path.exists(cf) and os.path.getsize(cf) > 500:
                xml = open(cf, encoding="utf-8").read()
            else:
                xml = _get(xb, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"}, timeout=45)
                open(cf, "w", encoding="utf-8").write(xml); time.sleep(0.1)
        except Exception:
            continue
        np = integrated_profit(xml, con=(key == "con")); ann = iso(r.get("broadcast_Date"))
        if np is not None:
            d[key] = (np, int(ann) if ann else None)
    return byq

def merge_integrated(out, sym, jar):
    """Merge integrated recent quarters into `out` ([qEnd,npStd,annStd,npCon,annCon] rows, in place)."""
    byq = fetch_integrated(sym, jar, skip={row[0] for row in out})
    if not byq: return
    by = {row[0]: row for row in out}
    for qe, d in byq.items():
        qi = int(qe); row = by.get(qi) or [qi, None, None, None, None]
        if "std" in d and row[1] is None: row[1], row[2] = d["std"]
        if "con" in d and row[3] is None: row[3], row[4] = d["con"]
        by[qi] = row
    out[:] = [by[k] for k in sorted(by)]

def qstart(qe):
    """First day of the 3-month quarter ENDING on qe (ISO yyyy-mm-dd). Q4 filings also carry
    the annual period — we always want the 3-month window, so derive it from the end date."""
    y, mo = int(qe[:4]), int(qe[5:7])
    sm = mo - 2
    sy = y
    if sm <= 0: sm += 12; sy -= 1
    return "%04d-%02d-01" % (sy, sm)

def fetch_symbol(sym, jar):
    h = {"User-Agent": UA, "Accept": "application/json",
         "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"}
    enc = urllib.parse.quote(sym)   # encode & in M&M, ARE&M, etc.
    # TWO sources, merged by quarter: (A) classic financial-results (covers ~2018..2024);
    # (B) integrated-filing-results — NSE moved every company to "Integrated Filing" in early
    # 2025, so ALL post-2024 quarters AND new IPOs (GROWW, LENSKART…) live ONLY here.
    byq = {}; errors = 0
    def add(rows, qe_key, ann_key):
        for r in rows:
            qe = iso(r.get(qe_key)); xb = r.get("xbrl", "")
            if not qe or not xb.startswith("http"): continue
            if "governance" in (r.get("type", "") or "").lower(): continue   # integrated Governance filing has no P&L
            byq.setdefault(qe, []).append({"ann": iso(r.get(ann_key)) or "99999999",
                                           "xbrl": xb, "basis": r.get("consolidated", "")})
    try:
        add(json.loads(_get("https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=%s&period=Quarterly" % enc,
                            headers=h, jar=jar, timeout=30)), "toDate", "broadCastDate")
    except Exception: errors += 1
    try:
        jb = json.loads(_get("https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=%s&period=Quarterly" % enc,
                             headers=h, jar=jar, timeout=30))
        add(jb if isinstance(jb, list) else jb.get("data", []), "qe_Date", "broadcast_Date")
    except Exception: errors += 1
    if errors == 2:                  # both endpoints errored (network) — signal jar re-warm
        return None
    out = []
    for qe in sorted(byq):
        if int(qe) < MIN_QE: continue       # skip ancient quarters (no XBRL archive / not needed)
        std = con = None; annStd = annCon = None
        for f in sorted(byq[qe], key=lambda x: x["ann"]):   # earliest filing first
            if std is not None and con is not None: break
            cf = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9]", "_", f["xbrl"].rsplit("/", 1)[-1]))
            try:
                if os.path.exists(cf) and os.path.getsize(cf) > 500:
                    xml = open(cf, encoding="utf-8").read()
                else:
                    xml = _get(f["xbrl"], headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"}, timeout=30)
                    open(cf, "w", encoding="utf-8").write(xml); time.sleep(0.15)
            except Exception:
                continue
            s, c = xbrl_profit(xml, basis_hint=f.get("basis"))
            a = None if f["ann"] == "99999999" else int(f["ann"])
            if std is None and s is not None: std, annStd = s, a
            if con is None and c is not None: con, annCon = c, a
        if std is None and con is None: continue
        out.append([int(qe), std, annStd, con, annCon])
    merge_integrated(out, sym, jar)   # recent quarters (old endpoint stops ~Dec-2024)
    return out

def load_index(name):
    """Fetch an NSE index constituent list, e.g. nifty500 / nifty100 / nifty50."""
    slug = {"nifty500": "ind_nifty500list.csv", "nifty100": "ind_nifty100list.csv",
            "nifty200": "ind_nifty200list.csv", "nifty50": "ind_nifty50list.csv"}.get(name)
    if not slug: return []
    txt = _get("https://nsearchives.nseindia.com/content/indices/" + slug,
               headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"}, timeout=30)
    syms = []
    for line in txt.splitlines()[1:]:
        cols = line.split(",")
        if len(cols) >= 3 and cols[2].strip(): syms.append(cols[2].strip())
    return syms

def load_sf_universe():
    """All symbols in the survivorship-free dataset (incl. delisted) — the truly
    survivorship-free fundamentals universe. Delisted names are fetched first (current
    index members are already built), so coverage of dropped stocks fills in fastest."""
    import gzip
    binp = os.path.join(os.path.dirname(HERE), "docs", "sf_stock_data.bin")
    D = json.loads(gzip.decompress(open(binp, "rb").read()))
    meta = D.get("meta", {})
    syms = list(D.get("data", {}).keys())
    # dead (delisted) stocks first — they're the survivorship-bias gap
    syms.sort(key=lambda s: (0 if meta.get(s, {}).get("alive") is False else 1, s))
    return syms

def main():
    args = sys.argv[1:]
    REFRESH = any(a.lower() == "refresh" for a in args)   # also top up recent quarters of already-built symbols
    args = [a for a in args if a.lower() != "refresh"]
    if args and args[0].lower() in ("sf", "all", "survivorship"):
        syms = load_sf_universe()
        print("Survivorship-free universe (from sf_stock_data.bin): %d symbols" % len(syms))
    elif args and args[0].lower() in ("nifty500", "nifty100", "nifty200", "nifty50"):
        syms = load_index(args[0].lower())
        print("Universe %s: %d symbols" % (args[0], len(syms)))
    else:
        syms = args or ["RELIANCE", "TCS", "HDFCBANK", "INFY", "CGCL", "TATAMOTORS"]
    data = {}
    if os.path.exists(OUT):
        try: data = json.load(open(OUT))
        except Exception: pass
    # "attempted" set: symbols we've already tried (incl. ones that returned empty — delisted
    # pre-2018 etc.) so restarts don't re-fetch the thousands with no data. Resumability.
    ATT = os.path.join(HERE, "_fund_attempted.json")
    try: attempted = set(json.load(open(ATT)))
    except Exception: attempted = set()
    attempted |= set(data.keys())   # anything already built counts as attempted
    todo = [s for s in syms if s not in data and s not in attempted]
    print("  %d symbols, %d built, %d attempted-empty, %d to fetch" % (
        len(syms), len(data), len(attempted) - len(data), len(todo)))

    _tl = threading.local()
    def worker_jar():
        if not getattr(_tl, "jar", None): _tl.jar = nse_jar()
        return _tl.jar
    def do_sym(sym):
        rec = fetch_symbol(sym, worker_jar())
        if rec is None:                        # cookie likely stale — re-warm this thread once
            _tl.jar = nse_jar(); rec = fetch_symbol(sym, _tl.jar)
        return sym, rec

    docs = os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")
    def flush():
        json.dump(data, open(OUT, "w"), separators=(",", ":"))
        json.dump(data, open(docs, "w"), separators=(",", ":"))   # web copy stays usable mid-build
        json.dump(sorted(attempted), open(ATT, "w"))

    lock = threading.Lock(); done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for sym, rec in ex.map(do_sym, todo):
            done += 1
            with lock:
                attempted.add(sym)
                if rec:
                    data[sym] = rec
                    print("  [%d/%d] %s: %d quarters  latest=%s npStd=%s npCon=%s" % (
                        done, len(todo), sym, len(rec), rec[-1][0], rec[-1][1], rec[-1][3]))
                if done % 50 == 0 or done == len(todo):
                    flush()
    flush()

    if REFRESH:   # top up recent quarters for every already-built symbol (cheap: only fetches NEW quarters)
        existing = list(data.keys())
        print("  refresh: topping up %d existing symbols with recent quarters" % len(existing))
        def do_ref(sym):
            byq = fetch_integrated(sym, worker_jar(), skip={q[0] for q in data[sym]})
            if byq is None:
                _tl.jar = nse_jar(); byq = fetch_integrated(sym, _tl.jar, skip={q[0] for q in data[sym]})
            return sym, byq
        rdone = upd = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex2:
            for sym, byq in ex2.map(do_ref, existing):
                rdone += 1
                with lock:
                    if byq:
                        by = {row[0]: row for row in data[sym]}
                        for qe, d in byq.items():
                            qi = int(qe); row = by.get(qi) or [qi, None, None, None, None]
                            if "std" in d and row[1] is None: row[1], row[2] = d["std"]
                            if "con" in d and row[3] is None: row[3], row[4] = d["con"]
                            by[qi] = row
                        new = [by[k] for k in sorted(by)]
                        if new[-1][0] > data[sym][-1][0]: upd += 1
                        data[sym] = new
                    if rdone % 100 == 0 or rdone == len(existing):
                        flush(); print("    refreshed %d/%d (%d got newer quarters)" % (rdone, len(existing), upd))
        flush()
        print("  refresh complete: %d symbols got newer quarters" % upd)

    sz = os.path.getsize(docs) / 1024
    print("Wrote %s (%d symbols) + docs/sf_fundamentals.json (%.0f KB)" % (OUT, len(data), sz))

if __name__ == "__main__":
    main()
