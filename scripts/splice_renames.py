# -*- coding: utf-8 -*-
"""Splice pre-rename old-ticker price history into renamed symbols so the 2020-21 backtest
window can screen them. Surviving-entity renames -> prices continuous for that window."""
import json, gzip
path='docs/sf_stock_data.bin'
D=json.loads(gzip.decompress(open(path,'rb').read()))
data=D['data']
renames=[('ADANIENSOL','ADANITRANS'),('ANGELONE','ANGELBRKG'),('COHANCE','SUVENPHAR'),
         ('SHRIRAMFIN','SRTRANSFIN'),('PCBL','PHILIPCARB')]
FIELDS=['d','c','t','hb','lb','ob','v','dv','vw']
for new,old in renames:
    n=data[new]; o=data.get(old)
    if not o:
        print('SKIP',new,'no',old); continue
    new_start=n['d'][0]
    idx=[i for i,dd in enumerate(o['d']) if dd<new_start]
    if not idx:
        print('SKIP',new,'no older pts'); continue
    flds=[f for f in FIELDS if f in o and f in n]
    for f in flds:
        n[f]=[o[f][i] for i in idx]+n[f]
    print('%s spliced %d pts from %s -> starts %d n=%d'%(new,len(idx),old,n['d'][0],len(n['d'])))
buf=gzip.compress(json.dumps(D,separators=(',',':')).encode())
open(path,'wb').write(buf)
print('SAVED',len(buf),'bytes')
