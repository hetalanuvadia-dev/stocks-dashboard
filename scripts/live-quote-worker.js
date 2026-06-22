/* =============================================================================
 * STOCKSWORLD — live quote proxy (Cloudflare Worker)
 *
 * WHY THIS EXISTS
 *   The dashboard is a static GitHub Pages site, so it can't fetch live quotes
 *   itself: quote endpoints block cross-origin browser calls (CORS). This tiny
 *   Worker runs on Cloudflare's free tier, fetches prices server-side, and
 *   returns them to the page with CORS enabled.
 *
 * SOURCE
 *   Yahoo Finance NSE feed (query1.finance.yahoo.com). Free, no account, works
 *   from Cloudflare's IPs. NOTE: free Yahoo NSE data is ~15 min delayed — fine
 *   for placing limit orders, NOT tick-by-tick. For true real-time, swap the
 *   fetch below for a broker API (Dhan / Angel One / Upstox / Zerodha).
 *
 * USAGE (from the page)
 *   GET  https://<your-worker>.workers.dev/?symbols=RELIANCE,TCS,INFY
 *   ->   {"asOf":<ms>,"source":"yahoo-nse","data":{"RELIANCE":{"ltp":2945.6,"prevClose":2930.1}, ...}}
 *
 * DEPLOY:  see scripts/LIVE_FEED_SETUP.md
 * ========================================================================== */

const CORS = {
  'Access-Control-Allow-Origin': '*',          // tighten to your Pages URL if you like
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': '*',
};

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });

    const url = new URL(request.url);
    const symbols = (url.searchParams.get('symbols') || '')
      .split(',').map(s => s.trim().toUpperCase()).filter(Boolean).slice(0, 30); // cap per call

    if (!symbols.length) return json({ error: 'pass ?symbols=RELIANCE,TCS' }, 400);

    const data = {};
    await Promise.all(symbols.map(async sym => {
      try {
        const r = await fetch(
          `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}.NS?interval=1d&range=1d`,
          { headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' } }
        );
        if (!r.ok) return;
        const d = await r.json();
        const m = d && d.chart && d.chart.result && d.chart.result[0] && d.chart.result[0].meta;
        if (m && m.regularMarketPrice != null) {
          data[sym] = {
            ltp: m.regularMarketPrice,
            prevClose: m.chartPreviousClose != null ? m.chartPreviousClose : (m.previousClose != null ? m.previousClose : null),
          };
        }
      } catch (e) { /* skip this symbol */ }
    }));

    return json({ asOf: Date.now(), source: 'yahoo-nse', data });
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { ...CORS, 'content-type': 'application/json' } });
}
