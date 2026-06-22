/* STOCKSWORLD service worker — makes the installed app launch fast & work offline.
 * Strategy:
 *   - HTML pages: network-first (online users always get the latest), cache fallback offline.
 *   - css/js/png: stale-while-revalidate (instant, refreshes in the background).
 *   - NEVER cache the big price blobs (*.bin) or live/data JSON, and ignore cross-origin
 *     requests (the sf-data repo, Supabase, the live-quote Worker) — those stay network-only
 *     so data is always fresh and the cache never bloats.
 * Bump CACHE when the shell asset list changes. */
const CACHE = 'sw-shell-v2';
const SHELL = [
  './', './nse-bse-dashboard.html', './stock-backtest.html', './saved-strategies.html',
  './backtest-history.html', './mutual-funds.html', './fii-dii.html', './backtest.html',
  './theme.css', './theme.js', './backtest-engine.js', './manifest.webmanifest',
  './icon-192.png', './icon-512.png', './icon-512-maskable.png', './apple-touch-icon.png'
];

self.addEventListener('install', function (e) {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL).catch(function () {}); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;                       // leave cross-origin (data repo / Supabase / Worker) alone
  if (url.pathname.endsWith('.bin') || url.pathname.endsWith('.json')) return;  // never cache big blobs / live data

  // Network-first for everything cacheable (HTML / CSS / JS / PNG): always fresh when online,
  // so fixes land immediately; fall back to cache only when offline.
  e.respondWith(
    fetch(req).then(function (r) {
      if (r && r.status === 200) { const cp = r.clone(); caches.open(CACHE).then(function (c) { c.put(req, cp); }); }
      return r;
    }).catch(function () {
      return caches.match(req).then(function (m) {
        if (m) return m;
        const wantsHTML = req.mode === 'navigate' || (req.headers.get('accept') || '').indexOf('text/html') >= 0;
        return wantsHTML ? caches.match('./nse-bse-dashboard.html') : undefined;
      });
    })
  );
});
