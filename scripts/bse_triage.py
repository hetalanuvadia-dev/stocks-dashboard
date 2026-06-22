# -*- coding: utf-8 -*-
"""Shallow triage of the BSE >=100cr empties: does each have result-filings at all?
Classifies recoverable (filings exist) vs genuinely-empty (none). Writes _bse_triage.json."""
import bse_vision as V, json, os, glob, re
HERE=os.path.dirname(os.path.abspath(__file__))
MISS={s['sym']:s for s in json.load(open('_bse_missing.json'))}
empties=[]
for f in glob.glob(os.path.join(HERE,'_bse_bulk','[0-9]*_[0-9]*.json')):
    for sym,q in json.load(open(f)).items():
        if not q: empties.append(sym)
out=json.load(open('_bse_triage.json')) if os.path.exists('_bse_triage.json') else {}
o=V.session()
MF=re.compile(r'mutual fund|permitted|etf|index fund|liquidbees|gold bees|nifty', re.I)
for i,sym in enumerate(empties):
    if sym in out: continue
    m=MISS.get(sym,{}); name=m.get('name','')
    if MF.search(name): out[sym]={'n':0,'cls':'nonstock','name':name}; continue
    try:
        fl=V.filings(o, m['code'], pages=4, since='20180101')
        n=len(fl)
    except Exception:
        n=-1
    out[sym]={'n':n,'cls':('recoverable' if n>0 else ('err' if n<0 else 'no-filings')),'name':name,'mcap':m.get('mcap',0)}
    json.dump(out, open('_bse_triage.json','w'))
    if (i+1)%20==0: print('triaged %d/%d'%(i+1,len(empties)),flush=True)
from collections import Counter
c=Counter(v['cls'] for v in out.values())
print('TRIAGE DONE:', dict(c), flush=True)
