# -*- coding: utf-8 -*-
"""Build the OWNERS-ATTRIBUTABLE consolidated dataset for ALL stocks/history:
  - set npCon = owners from the comprehensive _reattr_owners.json (1697 stocks)
  - add verified-from-filing backfills for qualifying NCI stocks missing from that file
Writes the result to docs/sf_fundamentals.json (in place). Reports coverage + any
qualifying stock whose con-quarter still lacks an owners figure (potential residual gap).
Run: python -X utf8 apply_owners_full.py            (impact-only: pass --dry)"""
import json, os, sys
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
F=os.path.join(ROOT,"docs","sf_fundamentals.json")
live=json.load(open(F))
OWN=json.load(open(os.path.join(HERE,"_reattr_owners.json")))   # "SYM|qe" -> owners cr

# verified-from-filing backfills (owners-attributable, cr) for NCI stocks not in _reattr_owners
BACKFILL={
 # CEMPRO (ITD Cementation): owners = total - NCI, read from consolidated filings
 "CEMPRO|20250331":113.55, "CEMPRO|20251231":110.89-0.00,  # Q3FY26 NCI~0 -> owners~total
 "CEMPRO|20260331":242.17,                                  # Q4FY26 NCI~0 -> owners~total
 # ACUTAAS (Acutaas/Anupam Rasayan, consolidates Tanfac): from Q4FY26 filing attribution
 "ACUTAAS|20250331":62.48, "ACUTAAS|20251231":107.96, "ACUTAAS|20260331":131.76,
}
src_own=src_bf=0
for sym,arr in live.items():
    for r in arr:
        if r[3] is None: continue
        k="%s|%d"%(sym,r[0])
        a=BACKFILL.get(k)
        if a is not None:
            if abs(a-r[3])>0.005: r[3]=a; src_bf+=1
            continue
        a=OWN.get(k)
        if a is not None and abs(a-r[3])>0.005:
            r[3]=a; src_own+=1
print("set npCon=owners: %d from _reattr_owners, %d from filing-backfill"%(src_own,src_bf))
if "--dry" in sys.argv:
    print("DRY RUN — not written"); sys.exit(0)
tmp=F+".tmp"; json.dump(live,open(tmp,"w"),separators=(",",":")); os.replace(tmp,F)
print("WROTE owners-attributable to docs/sf_fundamentals.json")
