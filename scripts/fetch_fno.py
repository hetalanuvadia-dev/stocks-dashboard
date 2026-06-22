#!/usr/bin/env python3
"""Fetch the current NSE F&O underlyings list from fo_mktlots.csv.

Produces scripts/fno_list.json with shape:
  { "asOf": "YYYY-MM-DD", "stocks": ["RELIANCE", "TCS", ...] }

NOTE: This is TODAY's list. Historical F&O membership (which stocks were in F&O
on a past date) is not yet tracked — see fetch_fno_history.py for that.
The dashboard falls back to today's list when no historical snapshot exists.
"""
import subprocess, csv, io, json
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "scripts" / "fno_list.json"
URL  = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
UA   = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Index underlyings are filtered out — we only want stock F&O
INDEX_UNDERLYINGS = {
    'NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','NIFTYNXT50','NIFTYIT','NIFTYBANK',
    'BANKEX','SENSEX','SENSEX50','BANKEX',
}

print(f"Fetching {URL}...")
r = subprocess.run(["curl","-s","-A",UA,"--max-time","20",URL], capture_output=True, timeout=30)
text = r.stdout.decode("utf-8", errors="ignore")
if len(text) < 1000:
    print(f"  WARN: response too short ({len(text)} bytes), keeping existing fno_list.json")
    raise SystemExit(0)

# NSE's CSV actually has TWO header rows:
#   1) "UNDERLYING, SYMBOL, MAY-26, JUN-26, ..."
#   2) "Derivatives on Individual Securities, Symbol, ..." (sub-section header)
# The case differs ("SYMBOL" vs "Symbol") so we need both forms in the skip list.
BOGUS_HEADERS = {"SYMBOL", "Symbol", "symbol", "TckrSymb", "TCKR"}
rows = list(csv.reader(io.StringIO(text)))
stocks = []
for r in rows[1:]:
    if len(r) < 2: continue
    sym = r[1].strip().strip('"')
    if not sym or sym in BOGUS_HEADERS: continue
    if sym in INDEX_UNDERLYINGS: continue
    stocks.append(sym)

stocks = sorted(set(stocks))
print(f"  Parsed {len(stocks)} stock F&O underlyings")
OUT.write_text(json.dumps({
    "asOf":   date.today().strftime("%Y-%m-%d"),
    "stocks": stocks,
}, indent=2))
print(f"Saved → {OUT}")
