# -*- coding: utf-8 -*-
"""
Daily INCREMENTAL refresh for docs/sf_fundamentals.json (the backtest's quarterly
net-profit dataset). Instead of re-fetching all 5,000+ stocks, it asks NSE's
integrated-filing-results endpoint for everything filed in the last ~21 days
(ALL companies, one date-range call), parses net profit from each new filing, and
upserts the quarter into the dataset. Light: one list call + a handful of XBRL
fetches during earnings season, ~nothing otherwise.

Picks up automatically: new quarters for existing stocks AND brand-new IPOs
(GROWW, LENSKART, …) the day they first file.

Run: python -X utf8 update_fundamentals.py
"""
import os, sys, json, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B   # reuse _get / nse_jar / iso / xbrl_profit / MIN_QE

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MARK = os.path.join(ROOT, "docs", ".fund_updated")
WINDOW_DAYS = 120  # wide overlap: a full quarter, so even if the workflow misses a few runs the
                   # next one self-heals. Cheap because we SKIP the iXBRL fetch for quarters/bases
                   # already stored (see loop) — most filings in the window are already on file.

def main():
    if os.path.exists(MARK): os.remove(MARK)
    data = json.load(open(DOCS))
    jar = B.nse_jar()
    h = {"User-Agent": B.UA, "Accept": "application/json",
         "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"}
    today = datetime.date.today()
    frm = (today - datetime.timedelta(days=WINDOW_DAYS)).strftime("%d-%m-%Y")
    to = today.strftime("%d-%m-%Y")
    url = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&period=Quarterly"
           "&from_date=%s&to_date=%s" % (frm, to))
    try:
        jb = json.loads(B._get(url, headers=h, jar=jar, timeout=40))
        rows = jb if isinstance(jb, list) else jb.get("data", [])
    except Exception as e:
        print("recent-filings fetch failed:", e); return
    print("filings in last %d days: %d" % (WINDOW_DAYS, len(rows)))

    byq = {}
    for r in rows:
        sym = r.get("symbol"); qe = B.iso(r.get("qe_Date")); xb = r.get("xbrl", "")
        if not sym or not qe or not xb.startswith("http") or int(qe) < B.MIN_QE: continue
        if "governance" in (r.get("type", "") or "").lower(): continue   # Governance filing has no P&L
        byq.setdefault((sym, qe), []).append(
            {"ann": B.iso(r.get("broadcast_Date")) or "99999999", "xbrl": xb, "basis": r.get("consolidated", "")})

    changed = newsyms = 0
    for (sym, qe), filings in byq.items():
        existing = next((x for x in data.get(sym, []) if x[0] == int(qe)), None)
        std = con = None; annStd = annCon = None
        for f in sorted(filings, key=lambda x: x["ann"]):
            if std is not None and con is not None: break
            is_con = "consol" in (f.get("basis") or "").lower()
            # already stored for this basis? skip the ~1 MB iXBRL fetch — lets the window be wide & cheap
            if existing and ((is_con and existing[3] is not None) or (not is_con and existing[1] is not None)):
                continue
            try:
                xml = B._get(f["xbrl"], headers={"User-Agent": B.UA, "Referer": "https://www.nseindia.com/"}, timeout=30)
            except Exception:
                continue
            s, c = B.xbrl_profit(xml, basis_hint=f.get("basis"))
            a = None if f["ann"] == "99999999" else int(f["ann"])
            if std is None and s is not None: std, annStd = s, a
            if con is None and c is not None: con, annCon = c, a
        if std is None and con is None: continue
        if sym not in data: data[sym] = []; newsyms += 1
        rec = data[sym]
        row = next((x for x in rec if x[0] == int(qe)), None)
        if row:   # upsert: only FILL missing fields (keep original point-in-time announcement)
            upd = False
            if std is not None and row[1] is None: row[1], row[2] = std, annStd; upd = True
            if con is not None and row[3] is None: row[3], row[4] = con, annCon; upd = True
            if upd: changed += 1
        else:
            rec.append([int(qe), std, annStd, con, annCon]); rec.sort(key=lambda x: x[0]); changed += 1

    if not changed and not newsyms:
        print("no new earnings — nothing to update"); return
    json.dump(data, open(DOCS, "w"), separators=(",", ":"))
    open(MARK, "w").write(today.isoformat())
    print("upserted %d quarters (%d new symbols); %d symbols total" % (changed, newsyms, len(data)))

if __name__ == "__main__":
    main()
