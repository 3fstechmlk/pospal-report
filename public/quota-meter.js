/* ── 3FS API Quota Meter ────────────────────────────────────────────────────────
 *
 * The badge + ↻ button that shows how much of the merchant's daily Pospal API
 * quota is gone.  Shared by Sales Report, Payment Report and Transactions so the
 * three can't drift apart.
 *
 * Reading the true number from Pospal costs a call (queryDailyAccessTimesLog
 * counts against the same limit), so the button is deliberately two-stage:
 *
 *   1st click  →  /api/merchant/usage?peek=1   answers from memory, never calls
 *                 Pospal.  Shows the last reading plus this app's calls since.
 *   2nd click  →  /api/merchant/usage          reads the real figure, 1 call.
 *
 * After a real read it goes back to stage 1, so every call spent needs its own
 * deliberate second click.  The server also throttles the real read to once per
 * 5 minutes and the hint counts that down.
 *
 * Mount it with:
 *   QuotaMeter.mount({ into: el, headers: hdr, onData: d => {} })
 */
(function (global) {
  'use strict';

  const CSS = `
.qm { display: inline-flex; gap: 8px; align-items: center; white-space: nowrap;
       flex: 0 1 auto; min-width: 0; }
.qm-badge { font-size: 11px; padding: 3px 9px; border-radius: 10px; font-weight: 600;
            background: #dcfce7; color: #166534; white-space: nowrap; flex-shrink: 0; }
.qm-badge.warn   { background: #fef3c7; color: #92400e; }
.qm-badge.danger { background: #fee2e2; color: #991b1b; }
.qm-badge.unknown{ background: #f4f4f5; color: #52525b; }
.qm-hint { font-size: 11px; color: #71717a; white-space: nowrap;
            overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.qm-hint.armed { color: #92400e; font-weight: 600; }
.qm-hint.wait  { color: #92400e; }
.qm-btn { flex-shrink: 0;
          background: none; border: 1px solid #d4d4d8; border-radius: 6px; color: #71717a;
          font-size: 14px; width: 26px; height: 26px; cursor: pointer; display: flex;
          align-items: center; justify-content: center; padding: 0;
          transition: color .15s, border-color .15s, transform .3s; }
.qm-btn:hover { color: #18181b; border-color: #a1a1aa; }
.qm-btn:disabled { opacity: .4; cursor: not-allowed; }
.qm-btn.armed { color: #f60; border-color: #f60; }
/* A wrapping flex bar decides its rows from each item's un-shrunk width, so below
   this the whole meter jumps to a line of its own instead of the hint giving way.
   Drop the hint there -- its text is on the title attribute either way. */
@media (max-width: 1450px) { .qm-hint { display: none; } }
`;

  function injectCSS() {
    if (document.getElementById('qm-style')) return;
    const st = document.createElement('style');
    st.id = 'qm-style';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  function hhmm(ts) {
    const d = new Date(ts * 1000);
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function mss(sec) {
    return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
  }

  class Meter {
    constructor(opts) {
      this.headers = opts.headers || (() => ({}));
      this.onData  = opts.onData  || function () {};
      this.armed   = false;      // true once a peek has run: the next click spends a call
      this.timer   = null;

      injectCSS();
      const wrap = document.createElement('span');
      wrap.className = 'qm';
      wrap.innerHTML =
        '<span class="qm-badge unknown" style="display:none"></span>' +
        '<span class="qm-hint" style="display:none"></span>' +
        '<button class="qm-btn" title="Check API quota — first click shows the last known figure, ' +
        'a second click reads the exact one from Pospal (costs 1 API call)">↻</button>';
      opts.into.appendChild(wrap);

      this.badge = wrap.querySelector('.qm-badge');
      this.hint  = wrap.querySelector('.qm-hint');
      this.btn   = wrap.querySelector('.qm-btn');
      this.btn.addEventListener('click', () => this.refresh(this.armed, false));

      // A peek costs nothing, so run one on mount: the badge and the 5-minute
      // countdown then survive a page reload instead of resetting to blank.  It
      // does NOT arm the button -- spending a call still needs a deliberate click.
      this.refresh(false, true);
    }

    async refresh(spendACall, isAuto) {
      this.btn.disabled = true;
      this.btn.style.transform = 'rotate(180deg)';
      try {
        const url = '/api/merchant/usage' + (spendACall ? '' : '?peek=1');
        const r   = await fetch(url, { headers: this.headers() });
        const d   = await r.json();
        if (!d.ok) return;
        // An explicit peek arms the button; a real read and the mount peek don't.
        this.armed = !spendACall && !isAuto;
        this.render(d, spendACall, isAuto);
        this.onData(d);
      } catch (e) {
        if (isAuto) return;   // nothing on screen yet to contradict; stay quiet
        this.hint.textContent = 'Could not read the quota.';
        this.hint.className = 'qm-hint';
        this.hint.style.display = '';
      } finally {
        this.btn.disabled = false;
        this.btn.style.transform = '';
        this.btn.classList.toggle('armed', this.armed);
      }
    }

    render(d, wasLive, isAuto) {
      if (this.timer) { clearInterval(this.timer); this.timer = null; }
      const q = d.quota;

      // Badge: the estimate when there is a reading to build on, otherwise say so
      // plainly rather than showing a number that means something else.
      if (q) {
        this.badge.textContent = `≈${q.estUsed}/${q.limit} API today (${q.estLeft} left)`;
        this.badge.className = 'qm-badge' +
          (q.estLeft < 50 ? ' danger' : q.estLeft < 100 ? ' warn' : '');
        this.badge.title =
          `Pospal's own reading was ${q.baseUsed}/${q.limit} at ${hhmm(q.baseTs)}; this app has made ` +
          `${q.sinceBase} call${q.sinceBase === 1 ? '' : 's'} since. Anything else sharing this appId ` +
          `(member portal, other tools) counts at Pospal but not here, so the real figure can only be higher.`;
      } else {
        this.badge.textContent = 'quota not read yet today';
        this.badge.className = 'qm-badge unknown';
        this.badge.title = 'Nobody has read this merchant’s Pospal quota today.';
      }
      this.badge.style.display = '';

      // Hint: what this click did, and what the next one will do
      if (!wasLive && !isAuto) {
        this.hint.textContent = q
          ? `from memory · ↻ again = 1 call`
          : `not read today · ↻ again = 1 call`;
        this.hint.title = q
          ? `Shown from the last reading (${hhmm(q.baseTs)}) plus this app's calls since — no API call was spent. `
            + `Click ↻ again to read the exact figure from Pospal, which costs 1 call.`
          : `Nobody has read this merchant's Pospal quota today, so there is nothing to show from memory. `
            + `Click ↻ again to read it, which costs 1 call.`;
        this.hint.className = 'qm-hint armed';
        this.hint.style.display = '';
        return;
      }

      // Otherwise show where the server's 5-minute throttle stands.  On mount this
      // is what restores the countdown a reload would have thrown away.
      const fresh = (d.cacheAgeSecs || 0) <= 2 && !isAuto;
      let left = d.cooldownSecs || 0;
      if (!left) {
        this.hint.textContent = fresh ? 'just read' : 'refresh available';
        this.hint.title = '';
        this.hint.className = 'qm-hint';
        this.hint.style.display = '';
        return;
      }
      const tick = () => {
        if (left <= 0) {
          this.hint.textContent = 'refresh available';
          this.hint.className = 'qm-hint';
          this.hint.title = '';
          clearInterval(this.timer); this.timer = null;
          return;
        }
        this.hint.textContent = (fresh ? 'just read · next in ' : 'cached · next in ') + mss(left);
        this.hint.title = fresh
          ? 'Read from Pospal just now. The server throttles the real read to once per 5 minutes.'
          : "Served from the server's 5-minute cache, so this click cost no API call.";
        this.hint.className = 'qm-hint wait';
        left--;
      };
      this.hint.style.display = '';
      tick();
      this.timer = setInterval(tick, 1000);
    }
  }

  global.QuotaMeter = {
    mount(opts) { return new Meter(opts); }
  };
})(window);
