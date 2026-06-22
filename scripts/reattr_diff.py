# -*- coding: utf-8 -*-
"""DRY-RUN impact scan for switching the consolidated profit factor from total PAT
(ProfitLossForPeriod) to attributable-to-owners (ProfitOrLossAttributableToOwnersOfParent).

For every symbol in docs/sf_fundamentals.json, re-read its consolidated integrated-filing XBRLs
(cached) and report each quarter where owners' share != total PAT (i.e. has minority interest).
Writes nothing live — just _reattr_diffs.json + a printed summary so the change can be reviewed.

Run: python -X utf8 reattr_diff.py
"""
import build_fundamentals as B, json, re, os, time, collections

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
live = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))

def g(xml, tag):
    m = re.search(r'<in-capmkt:' + tag + r' contextRef="OneD"[^>]*>([-0-9.eE+]+)<', xml)
    try: return round(float(m.group(1)) / 1e7, 2) if m else None
    except Exception: return None

def main():
    jar = B.nse_jar(); diffs = []; syms = list(live.keys()); done = 0
    for sym in syms:
        done += 1
        if done % 250 == 0: print("  ...%d/%d scanned, %d changed quarters so far" % (done, len(syms), len(diffs)), flush=True)
        url = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=%s&period=Quarterly"
               % B.urllib.parse.quote(sym))
        try:
            rows = json.loads(B._get(url, headers={"User-Agent": B.UA, "Accept": "application/json",
                                                   "Referer": "https://www.nseindia.com/"}, jar=jar, timeout=25)).get("data", [])
        except Exception:
            continue
        livemap = {q[0]: q for q in live.get(sym, [])}
        for r in rows:
            if r.get("type") != "Integrated Filing- Financials" or "consol" not in (r.get("consolidated") or "").lower():
                continue
            qe = B.iso(r.get("qe_Date")); xb = r.get("xbrl")
            if not qe or not xb: continue
            cf = os.path.join(B.CACHE, re.sub(r"[^A-Za-z0-9]", "_", xb.rsplit("/", 1)[-1]))
            try:
                if os.path.exists(cf) and os.path.getsize(cf) > 500:
                    xml = open(cf, encoding="utf-8").read()
                else:
                    xml = B._get(xb, headers={"User-Agent": B.UA, "Referer": "https://www.nseindia.com/"}, timeout=40)
                    open(cf, "w", encoding="utf-8").write(xml)
            except Exception:
                continue
            total = g(xml, "ProfitLossForPeriod")
            if total is None: total = g(xml, "ProfitLossForThePeriod")
            attr = g(xml, "ProfitOrLossAttributableToOwnersOfParent")
            if attr is not None and total is not None and abs(attr - total) > 0.5:
                live_con = livemap.get(int(qe), [None, None, None, None, None])[3]
                diffs.append([sym, int(qe), total, attr, round(total - attr, 2), live_con])
        time.sleep(0.12)
    diffs.sort(key=lambda d: abs(d[4]), reverse=True)
    json.dump(diffs, open(os.path.join(HERE, "_reattr_diffs.json"), "w"))
    print("\n=== IMPACT: consolidated quarters where attributable-to-owners != total PAT ===")
    print("changed quarters: %d  |  distinct stocks: %d" % (len(diffs), len(set(d[0] for d in diffs))))
    recent = [d for d in diffs if d[1] >= 20250101]
    print("of which 2025+ quarters: %d  (%d stocks)" % (len(recent), len(set(d[0] for d in recent))))
    print("\nTop 35 by minority size (sym, qe, totalPAT -> owners, minority):")
    for d in diffs[:35]:
        print("  %-12s %d  %8.1f -> %8.1f   minority %7.1f" % (d[0], d[1], d[2], d[3], d[4]))

if __name__ == "__main__":
    main()
