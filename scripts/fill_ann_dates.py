# -*- coding: utf-8 -*-
"""Fill NULL announcement dates in docs/sf_fundamentals.json with the SEBI filing DEADLINE
(45 days after quarter-end; 60 for the Q4/annual). The deadline is the LATEST a result can be
published, so a quarter only becomes point-in-time-usable on/after that date -> conservative,
never look-ahead. Without this, a quarter with a missing date is skipped and the screen falls
back to a stale quarter (which wrongly excluded AIIL, and others, from month-end screens).

Run: python -X utf8 fill_ann_dates.py
"""
import os, json, datetime

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
F = os.path.join(ROOT, "docs", "sf_fundamentals.json")

def deadline(qe):
    y, mmdd = qe // 10000, qe % 10000
    d = datetime.date(y, mmdd // 100, mmdd % 100)
    lag = 60 if mmdd == 331 else 45                  # Q4 (annual) 60d, Q1-Q3 45d
    return int((d + datetime.timedelta(days=lag)).strftime("%Y%m%d"))

def main():
    data = json.load(open(F)); fixed = 0
    for arr in data.values():
        for q in arr:                                # q = [qe, npStd, annStd, npCon, annCon]
            est = None
            if q[1] is not None and q[2] is None: q[2] = est = deadline(q[0]); fixed += 1
            if q[3] is not None and q[4] is None: q[4] = est or deadline(q[0]); fixed += 1
    tmp = F + ".tmp"; json.dump(data, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, F)
    print("Filled %d null announcement dates (deadline estimate) in %s" % (fixed, F))

if __name__ == "__main__":
    main()
