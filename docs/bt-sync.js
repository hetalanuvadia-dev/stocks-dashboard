// Shared Backtest-History for STOCKSWORLD.
// OPEN TO ADD: every visitor auto-loads the shared history and can run a backtest to add to it
// (no login, no code). ERASING is owner-only in the UI: the Delete / Clear-all controls render only
// in a browser that holds 'bt_owner_key' (set once via ?ownerkey=…), so visitors can add but not
// wipe. (Writes are open at the API level — the owner-key just gates the erase UI; daily backups
// cover recovery.) The publishable key + write token below are public on purpose.
(function (g) {
  'use strict';
  const URL = 'https://nebjnsndgrhumnkuipqy.supabase.co';
  const ANON = 'sb_publishable_MDlQwiVc5deii91__UNeDg_z9r4Fk98';
  const WRITE = 'sw_owner_8Kq2Lm9Xp4Rt7v';
  const HIST_KEY = 'bt_history', OWNER_KEY = 'bt_owner_key', CAP = 300;
  let _sb = null;
  function client() { if (!_sb && g.supabase) { try { _sb = g.supabase.createClient(URL, ANON); } catch (e) { console.warn('supabase init', e); } } return _sb; }
  const _local = () => { try { return JSON.parse(localStorage.getItem(HIST_KEY) || '[]'); } catch (e) { return []; } };
  const _saveLocal = a => { try { localStorage.setItem(HIST_KEY, JSON.stringify(a.slice(0, CAP))); } catch (e) {} };
  const ownerKey = () => { try { return localStorage.getItem(OWNER_KEY) || ''; } catch (e) { return ''; } };
  // Read the shared history — auto-loaded for everyone.
  async function pull() {
    const sb = client(); if (!sb) return _local();
    try { const { data, error } = await sb.rpc('bt_public'); if (error) throw error;
      const remote = Array.isArray(data) ? data : (data || []); _saveLocal(remote); return remote;
    } catch (e) { console.warn('bt pull', e && e.message || e); return _local(); }
  }
  // Write the shared history — open (anyone can add; the owner can also erase via the UI).
  async function push() {
    const sb = client(); if (!sb) return false;
    try { const { data, error } = await sb.rpc('bt_owner_set', { secret: WRITE, payload: _local() }); if (error) throw error; return data === true; }
    catch (e) { console.warn('bt push', e && e.message || e); return false; }
  }
  // ---- Shared SAVED STRATEGIES (owner-curated: everyone reads; the owner publishes) ----
  const STRAT_KEY = 'bt_strategies';
  const _localStr = () => { try { return JSON.parse(localStorage.getItem(STRAT_KEY) || '[]'); } catch (e) { return []; } };
  const _saveLocalStr = a => { try { localStorage.setItem(STRAT_KEY, JSON.stringify(a.slice(0, CAP))); } catch (e) {} };
  async function pullStrategies() {
    const sb = client(); if (!sb) return _localStr();
    try {
      const { data, error } = await sb.rpc('bt_strats_public'); if (error) throw error;
      const remote = Array.isArray(data) ? data : (data || []);
      // first run: if the shared list is empty but this (owner) browser has strategies, seed it up
      if (!remote.length && ownerKey() && _localStr().length) { await pushStrategies(); return _localStr(); }
      _saveLocalStr(remote); return remote;
    } catch (e) { console.warn('strat pull', e && e.message || e); return _localStr(); }
  }
  async function pushStrategies() {
    const sb = client(); if (!sb) return false;
    try { const { data, error } = await sb.rpc('bt_strats_set', { secret: WRITE, payload: _localStr() }); if (error) throw error; return data === true; }
    catch (e) { console.warn('strat push', e && e.message || e); return false; }
  }
  g.btSync = { pull, push, pullStrategies, pushStrategies, isOwner: () => !!ownerKey(), configured: () => !!client(),
    setOwnerKey: k => { try { k ? localStorage.setItem(OWNER_KEY, k) : localStorage.removeItem(OWNER_KEY); } catch (e) {} } };
  // Owner-UI unlock: open any page with ?ownerkey=YOURKEY once on a PC to reveal the Delete/Clear controls there.
  try {
    const u = new URL(location.href), ok = u.searchParams.get('ownerkey');
    if (ok) { localStorage.setItem(OWNER_KEY, ok); u.searchParams.delete('ownerkey'); history.replaceState(null, '', u.pathname + u.search + u.hash); }
  } catch (e) {}
})(window);
