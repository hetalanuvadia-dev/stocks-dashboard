# -*- coding: utf-8 -*-
"""
Download NSE/niftyindices reconstitution press-release PDFs and parse them into a
per-index change log: {index: [{eff, excluded:[...], included:[...], src}]}.

Output: scripts/_changelog.json  (then reconstruct_validate.py checks it).
Run: python -X utf8 build_changelog.py
"""
import os, re, json, time, urllib.request
from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_pr_cache"); os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
BASE = "https://www.niftyindices.com/Press_Release/"

FILES = """
10062026 21052026_1 20052026_1 15052026 08052026 04052026 23042026 12032026 23022026 20022026_2 20012026_2
26122025 23122025 11122025 01122025 17112025_1 20102025 17102025 25092025_1 15092025 15092025_1 22082025 22082025_1
24072025 10072025 04072025 03072025 02072025 26062025_1 25062025_1 23062025_1 06062025 05062025 04062025 03062025_1
29052025 07052025 21042025_1 04042025_2 25032025 17032025 13032025 06032025 25022025_1 21022025 20022025 18022025
31122024 30122024_1 11122024 22112024 10102024 10102024_1 04102024 25092024 23092024 27082024 23082024 23082024_1
24072024 21062024_1 07062024 22052024 24042024 24042024_1 19032024 14032024 28022024 30012024 19012024 10012024
07122023 09112023 17102023 15092023 23082023 17082023 24072023 04072023 27062023 09062023 19042023_1 06032023 21022023 17022023_1 09022023_1
22122022 06122022 20102022 20102022_1 16092022 01092022 23082022 26072022 11072022 15062022 24052022 06042022 05042022 05042022_1 08032022 24022022_1
08122021 22102021 08102021 20092021 15092021 23082021 15062021 22042021 10032021 23022021
11122020 18112020 26102020 30092020 07092020 20082020 02072020_1 12032020 18022020 09012020
19122019 18122019 16122019 28112019 17092019 17092019_1 13032019
24092018 31082018 01082018 15062018 15062018_1 06032018
29082017 27042017 07032017
17102016 12082016 18072016 28042016 22042016 22022016_2 11012016
07122015 18092015 24082015 12082015 05062015 29042015 20042015 18032015_2 20022015 23012015 21012015
""".split()

CANON = {
    "nifty50": "Nifty 50", "niftynext50": "Nifty Next 50",
    "nifty100": "Nifty 100", "nifty200": "Nifty 200", "nifty500": "Nifty 500", "cnx500": "Nifty 500",
    "niftymidcap150": "Nifty Midcap 150", "niftysmallcap250": "Nifty Smallcap 250",
}
def canon_index(name):
    return CANON.get(re.sub(r"[^a-z0-9]", "", name.lower()))

def get(url, tries=5):
    last = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception as e:
            last = e; time.sleep(3)
    raise last
def download(stem, tries=5):
    fp = os.path.join(CACHE, stem + ".pdf")
    if os.path.exists(fp) and os.path.getsize(fp) > 1000:
        return fp
    try:
        raw = get(BASE + "ind_prs" + stem + ".pdf", tries=tries)
        if raw[:4] != b"%PDF": return None
        open(fp, "wb").write(raw); return fp
    except Exception:
        return None

def recent_stems(days=80):
    """FRESHNESS SAFEGUARD: auto-discover press releases published since the hand-maintained
    FILES list. Probe each recent weekday's PDF name (ind_prsDDMMYYYY.pdf, + _1/_2 variants),
    single attempt so 404s are fast. This is what makes a new reshuffle get captured WITHOUT a
    manual edit — the failure mode that mis-dated the 2026 March reshuffle."""
    import datetime
    out = []
    today = datetime.date.today()
    for i in range(days):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5: continue   # press releases come out on weekdays
        s = d.strftime("%d%m%Y")
        out += [s, s + "_1", s + "_2"]
    return out

DATE_RE = re.compile(r"effective\s+from\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
def to_iso(d):
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", d.strip())
    if not m: return None
    mo = MONTHS.get(m.group(1).capitalize())
    return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}" if mo else None

# index heading on its own line, numbered OR lettered: "1) Nifty Alpha 50", "c) Nifty 500"
HEAD_RE = re.compile(r"^\s*(?:\d+|[a-zA-Z])[\)\.]\s*((?:nifty|cnx)[\w &\-]*?)\s*$", re.I)
# a data row: serial number, company name, then the all-caps symbol as the LAST token.
# Requiring the leading serial number rejects boilerplate + page-break noise.
ROW_RE = re.compile(r"^\s*\d{1,3}\s+\S.*?\s([A-Z][A-Z0-9&\-]{1,14})\s*$")

def parse_pdf(fp):
    try:
        txt = "\n".join(p.extract_text() or "" for p in PdfReader(fp).pages)
    except Exception:
        return []
    md = DATE_RE.search(txt); eff_default = to_iso(md.group(1)) if md else None
    cur = None; mode = None; blocks = []
    for ln in txt.splitlines():
        h = HEAD_RE.match(ln)
        if h:
            ci = canon_index(h.group(1))
            cur = {"index": ci, "eff": eff_default, "excluded": [], "included": []} if ci else None
            if cur: blocks.append(cur)
            mode = None
            continue
        if cur is None: continue
        low = ln.lower()
        if "exclud" in low: mode = "excluded"; continue
        if "includ" in low: mode = "included"; continue
        if "no change" in low or "no replacement" in low: mode = None; continue
        if mode:
            m = ROW_RE.match(ln)
            if m and m.group(1) not in ("NSE","EQ","BE","NIFTY","CNX") and not m.group(1).startswith("DUMMY"):
                cur[mode].append(m.group(1))
    return [b for b in blocks if (b["excluded"] or b["included"]) and b["eff"]]

def main():
    known = set(FILES)
    stems = list(dict.fromkeys(FILES + recent_stems()))   # hand-maintained history + auto-probed recent
    print(f"Parsing {len(FILES)} known + {len(stems)-len(FILES)} auto-probed recent press releases...")
    ok = miss = 0; changelog = {}
    for stem in stems:
        fp = download(stem, tries=(5 if stem in known else 1))   # don't retry the speculative probes
        if not fp: miss += 1; continue
        ok += 1
        for b in parse_pdf(fp):
            changelog.setdefault(b["index"], []).append({"eff": b["eff"], "excluded": b["excluded"], "included": b["included"], "src": stem})
    print(f"Have {ok}/{len(FILES)} PDFs (missing {miss})")
    for idx in sorted(changelog):
        ch = changelog[idx]; ch.sort(key=lambda x: x["eff"])
        nx = sum(len(c["excluded"]) for c in ch); ni = sum(len(c["included"]) for c in ch)
        print(f"  {idx:22s}: {len(ch):3d} events, {nx:3d} out / {ni:3d} in   {ch[0]['eff']}..{ch[-1]['eff']}")
    json.dump(changelog, open(os.path.join(HERE, "_changelog.json"), "w"), indent=0)
    print("Wrote _changelog.json")

if __name__ == "__main__":
    main()
