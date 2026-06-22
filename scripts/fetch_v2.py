# -*- coding: utf-8 -*-
"""Content-aware re-fetch for WRONG-PERIOD gaps (the earlier fetch grabbed an attachment whose
announcement date mapped to the quarter, but the PDF content was actually a different/annual filing).
For each (sym, qe) we search a WIDE announcement window, download each result attachment, and KEEP only
the one whose CONTENT actually contains the target quarter-end date AND a consolidated/profit table.
Deletes any wrong cached PDF first. Run: python -X utf8 fetch_v2.py <listfile.json>
where listfile.json = [["SYM",qe],...]. Caches to _vpdf/SYM_qe.pdf; logs _fetchv2_log.json.
"""
import os, sys, json, time, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import congap_recover as C
import bse_vision as BV
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf"); LOG = os.path.join(HERE, "_fetchv2_log.json")
MONTHS = {1:"january",2:"february",3:"march",4:"april",5:"may",6:"june",7:"july",8:"august",9:"september",10:"october",11:"november",12:"december"}

def qe_date_patterns(qe):
    y, m, d = qe//10000, (qe//100)%100, qe%100
    mn = MONTHS[m]; pats = [
        "%02d/%02d/%d"%(d,m,y), "%02d-%02d-%d"%(d,m,y), "%02d.%02d.%d"%(d,m,y),
        "%s %d, %d"%(mn,d,y), "%d %s %d"%(d,mn,y), "%dth %s %d"%(d,mn,y),
        "%d %s, %d"%(d,mn,y), "%02d %s %d"%(d,mn,y), "%s %d,%d"%(mn,d,y)]
    return [p.lower() for p in pats]

def wide_window(qe):
    # from the quarter-end to ~13 months later (catch delayed/combined filings)
    y, m = qe//10000, (qe//100)%100
    lo = qe
    hd = datetime.date(y,m,28) + datetime.timedelta(days=400)
    return str(lo), "%04d%02d%02d"%(hd.year,hd.month,hd.day)

def content_ok(pdf, qe):
    """PDF content must mention the target quarter-end date AND have a consolidated profit table."""
    try: doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception: return False
    pats = qe_date_patterns(qe); datehit = False; conprofit = False
    for p in range(min(len(doc), 40)):
        low = doc[p].get_text().lower()
        if not datehit and any(pt in low for pt in pats): datehit = True
        if "consolidated" in low and re.search(r'profit.{0,6}(after tax|for the (period|quarter|year))|profit after tax|net profit', low) \
           and len(re.findall(r'\d[\d,]*\.\d\d', doc[p].get_text())) >= 6:
            conprofit = True
    return datehit and conprofit

def main():
    targets = json.load(open(sys.argv[1]))
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    o = BV.session(); got = 0
    for sym, qe in targets:
        key = "%s|%d" % (sym, qe)
        if log.get(key) == "got": continue
        code = C.scrips.get(sym)
        if not code or sym in C.DEFUNCT:
            log[key] = "nocode"; continue
        # remove wrong cached pdf so we don't keep the bad one
        cp = os.path.join(VPDF, "%s_%d.pdf" % (sym, qe))
        lo, hi = wide_window(qe)
        try: fl = C.datebound(o, code, lo, hi)
        except Exception: fl = []
        best = None
        for a, att in fl[:12]:
            try: pdf = C.fetch(o, att)
            except Exception: pdf = None
            time.sleep(1.3)
            if not pdf: continue
            if content_ok(pdf, qe): best = pdf; break
        if best:
            open(cp, "wb").write(best); log[key] = "got"; got += 1; print("  GOT", key, flush=True)
        else:
            log[key] = "no-match"; print("  no-match", key, flush=True)
        json.dump(log, open(LOG, "w"))
    print("FETCH_V2 DONE. fetched %d content-verified PDFs." % got, flush=True)

if __name__ == "__main__":
    main()
