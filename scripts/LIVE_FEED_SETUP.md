# Live price feed — setup (≈10 minutes, ₹0)

Your dashboard is a **static** site, so it can't fetch live quotes by itself.
We deploy a tiny free **Cloudflare Worker** that fetches prices and hands them to
the page. The Worker code is in `scripts/live-quote-worker.js`.

Source = **Yahoo Finance NSE feed** (free, no broker). It's **~15 minutes delayed** —
fine for placing limit orders, not tick-by-tick. (Want true real-time? See the
bottom of this file.)

---

## Step 1 — Create a free Cloudflare account
1. Go to https://dash.cloudflare.com/sign-up and sign up (free, no card).

## Step 2 — Create the Worker
1. In the dashboard left menu: **Workers & Pages** → **Create application** → **Create Worker**.
2. Give it a name, e.g. `stocksworld-quotes`. Click **Deploy** (it deploys a hello-world).
3. Click **Edit code**.
4. Delete everything in the editor, then **paste the entire contents** of
   `scripts/live-quote-worker.js`.
5. Click **Deploy** (top right).

## Step 3 — Copy your Worker URL
After deploy you'll see a URL like:
```
https://stocksworld-quotes.<your-subdomain>.workers.dev
```
Copy it. Test it in your browser:
```
https://stocksworld-quotes.<your-subdomain>.workers.dev/?symbols=RELIANCE,TCS
```
You should see JSON with `ltp` values.

## Step 4 — Connect it to the dashboard
1. Open the **Saved Strategies** page → click **🎯 Today's Picks** on any card.
2. Click **⚡ Go Live** → it asks for your Worker URL the first time → paste it.
3. Done. The basket now shows **Live ₹**, **Δ% vs close**, and re-allocates shares
   at live prices. The URL is saved in your browser for next time.

To change it later: click the **⚙** next to **Go Live**.

---

## Notes & limits
- **Free Cloudflare Workers** allow 100,000 requests/day — far more than you'll use.
- Each **Go Live** click = one request (covers all basket symbols at once).
- Yahoo NSE data is **~15 min delayed**. The "as of" time shown is when you clicked.
- If a symbol is BSE-only (no `.NS` listing) it may be missing — those rows keep
  their daily close.
- **Never put broker API keys in the website.** They'd be public. Keys belong only
  inside the Worker (Cloudflare keeps them private).

## Want true real-time (tick) prices?
Swap the Yahoo fetch in `live-quote-worker.js` for a broker quote API:
- **Free with an account (need a daily login token):** Dhan, Angel One SmartAPI, Upstox.
- **Paid:** Zerodha Kite Connect (₹2,000/mo).
Tell me which broker and I'll rewrite the Worker for it (the page side won't change).
