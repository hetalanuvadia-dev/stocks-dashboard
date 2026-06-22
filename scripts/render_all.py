# -*- coding: utf-8 -*-
"""Render EVERY page of a sym+qe filing at 300 DPI (no scoring) so a P&L on a low-OCR-score page
can still be read. Writes _deepgap/<SYM>_<qe>_allpN.png. Run: python render_all.py SYM qe"""
import bse_vision as V, bse_text as T, fitz, json, os, sys
SC = json.load(open("bse_scrips.json"))["by_id"]; OUT = "_deepgap"; os.makedirs(OUT, exist_ok=True)
sym = sys.argv[1]; qe = int(sys.argv[2]); code = SC[sym]; o = V.session()
fl = sorted(V.filings(o, code, pages=30, since="20180101"))
atts = [a for ann, a in fl if T.qe_from_ann(ann) == qe]
print("atts", len(atts))
for ai, att in enumerate(atts[:3]):
    pdf = None
    for base in ("AttachHis", "AttachLive"):
        try:
            dd = V.get(o, "https://www.bseindia.com/xml-data/corpfiling/%s/%s" % (base, att), b=True)
            if dd[:4] == b"%PDF": pdf = dd; break
        except Exception: pass
    if not pdf:
        print("att", ai, "not pdf"); continue
    doc = fitz.open(stream=pdf, filetype="pdf")
    print("att", ai, "pages", len(doc))
    for p in range(min(len(doc), 16)):
        doc[p].get_pixmap(dpi=300).save(os.path.join(OUT, "%s_%d_a%dp%d.png" % (sym, qe, ai, p)))
