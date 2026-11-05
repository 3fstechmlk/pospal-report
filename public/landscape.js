/* ── 3FS Landscape report view (phones) ─────────────────────────────────────────
 *
 * Adds a "rotate" button to a report card's .tc-head. Tapping it shows ONLY that
 * card (title + table) full screen and in landscape; the same button (now "Exit")
 * puts everything back. Used by Sales Report and Payment Report.
 *
 * It always opens turned LEFT (top of the phone on the left); after that the phone's
 * own orientation decides between left and right.
 *
 *   Android Chrome : real Fullscreen API on <html>, lock 'landscape-primary' (left),
 *                    then relax the lock to 'landscape' (left or right, by sensor).
 *   iPhone Safari  : has neither API for a page, so the card is pinned over the page
 *                    with position:fixed and, while the phone is still upright,
 *                    rotated 90° clockwise with CSS -- turn the phone left to read it.
 *                    Once the phone really turns landscape (either way) Safari lays the
 *                    page out upright itself and the CSS rotation drops off (it only
 *                    applies under orientation:portrait).
 *
 * The button only shows on phones (≤640px wide, or a touch screen ≤500px tall,
 * i.e. a phone already held sideways).
 *
 * Mount it with:   LandscapeView.mount(cardElement)
 */
(function (global) {
  'use strict';

  const CSS = `
.ls-btn { display: none; position: absolute; top: 50%; right: 12px; margin-top: -21px;
          height: 42px; min-width: 46px; padding: 0 10px; gap: 6px;
          align-items: center; justify-content: center;
          border: 0; border-radius: 10px; background: #f60; color: #fff; cursor: pointer;
          font: 700 13px/1 -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
          box-shadow: 0 3px 10px rgba(255,102,0,.4); -webkit-tap-highlight-color: transparent; }
.ls-btn svg { width: 26px; height: 26px; display: block; flex-shrink: 0; }
.ls-btn:active { opacity: .85; }
.ls-btn:focus-visible { outline: 2px solid #18181b; outline-offset: 2px; }
.ls-btn .ls-hint { animation: ls-hint 1.6s ease-in-out .6s 2; transform-origin: 50% 50%; }
@keyframes ls-hint { 0%, 55%, 100% { transform: rotate(0); } 25% { transform: rotate(-90deg); } }
@media (prefers-reduced-motion: reduce) { .ls-btn .ls-hint { animation: none; } }

@media (max-width: 640px), (pointer: coarse) and (max-height: 500px) {
  .ls-btn { display: inline-flex; }
  .ls-card .tc-head { position: relative; padding-right: 72px; }
}

/* ── Full-screen card ── */
html.ls-on, html.ls-on body { overflow: hidden; }
.tc.ls-full { position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 1000;
              margin: 0; border: 0; border-radius: 0; box-shadow: none;
              display: flex; flex-direction: column; background: #fff; }
.tc.ls-full .ls-btn { display: inline-flex; background: #18181b; box-shadow: none; padding: 0 12px; }
.tc.ls-full .tc-head { flex: 0 0 auto; position: relative; padding: 8px 112px 8px 14px; }
/* Payment Report wraps title + date in one <div> (stacked); flatten it so every report
   shows one line in full screen: title on the left, date range on the right */
.tc.ls-full .tc-head > div { display: contents; }
.tc.ls-full .sw { flex: 1 1 auto; min-height: 0; overflow: auto; overscroll-behavior: contain;
                  -webkit-overflow-scrolling: touch; }
.tc.ls-full .sv { flex: 1 1 auto; }
/* Header row stays on top while scrolling down; date column stays left while scrolling sideways */
.tc.ls-full thead th { position: sticky; top: 0; z-index: 2; }
.tc.ls-full .sticky-c1 th:first-child,
.tc.ls-full .sticky-c1 td:first-child { position: sticky; left: 0; box-shadow: inset -1px 0 0 #e4e4e7; }
.tc.ls-full .sticky-c1 td:first-child { z-index: 1; background: #fff; }
.tc.ls-full .sticky-c1 .tot td:first-child { background: #fff7ed; }
.tc.ls-full .sticky-c1 thead th:first-child { z-index: 3; }

/* Phone still upright (iPhone, or Android without the orientation lock):
   lay the card out landscape-sized and turn it 90° clockwise to fill the screen,
   so its top sits on the right edge -- it reads upright once the phone turns LEFT. */
@media (orientation: portrait) {
  .tc.ls-full { right: auto; bottom: auto;
                width: 100vh; width: 100dvh; height: 100vw;
                transform-origin: 0 0; transform: translateX(100vw) rotate(90deg); }
}
`;

  // Turn LEFT (counter-clockwise): phone upright (faint, top right) → phone sideways
  // (solid, bottom left), with an arrow turning anticlockwise over the top left.
  const ICON_ROTATE = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <g class="ls-hint">
      <rect x="13.5" y="2" width="8" height="13" rx="1.6" opacity=".55"/>
      <rect x="2.5" y="13" width="13" height="8.5" rx="1.6" fill="rgba(255,255,255,.22)"/>
      <path d="M6.5 17.25h.01"/>
    </g>
    <path d="M10 2.6a7.4 7.4 0 0 0-6.9 6.6"/>
    <path d="M5.3 7.9L3.1 9.5 1.7 7.1"/>
  </svg>`;

  // Four corners pointing inwards = leave full screen
  const ICON_EXIT = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path d="M9 3.5V9H3.5M15 3.5V9h5.5M9 20.5V15H3.5M15 20.5V15h5.5"/>
  </svg>`;

  function injectCSS() {
    if (document.getElementById('ls-css')) return;
    const st = document.createElement('style');
    st.id = 'ls-css';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  function mount(card) {
    if (!card || card.querySelector('.ls-btn')) return;
    const head = card.querySelector('.tc-head');
    if (!head) return;
    injectCSS();
    card.classList.add('ls-card');

    const root = document.documentElement;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ls-btn';
    head.appendChild(btn);

    let on = false;
    let fsByUs = false;          // true only while a fullscreen WE requested is active
    let savedY = 0;              // page scroll to return to (overflow:hidden + fullscreen reset it)

    function paint() {
      btn.innerHTML = on ? ICON_EXIT + '<span>Exit</span>' : ICON_ROTATE;
      const label = on ? 'Exit full screen' : 'Full screen, landscape';
      btn.title = label;
      btn.setAttribute('aria-label', label);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    }

    const fsElement = () => document.fullscreenElement || document.webkitFullscreenElement || null;

    async function enter() {
      if (on) return;
      on = true;
      savedY = window.scrollY;
      card.classList.add('ls-full');
      root.classList.add('ls-on');
      paint();
      // Real fullscreen + landscape lock where the browser allows it (Android).
      // Both must start inside this tap, and both fail quietly on iPhone.
      const req = root.requestFullscreen || root.webkitRequestFullscreen;
      if (req) {
        try { await req.call(root, { navigationUI: 'hide' }); fsByUs = !!fsElement(); } catch (e) { fsByUs = false; }
      }
      if (fsByUs && screen.orientation && screen.orientation.lock) {
        // Open turned LEFT first ('landscape-primary' = top of the phone on the left),
        // then widen the lock to either landscape so it follows which way the phone is held.
        try {
          await screen.orientation.lock('landscape-primary');
          setTimeout(() => {
            if (on && fsByUs) screen.orientation.lock('landscape').catch(() => {});
          }, 1200);
        } catch (e) { /* CSS rotation covers it */ }
      }
      if (!on) leaveFullscreen();   // user tapped Exit while the requests were pending
    }

    function leaveFullscreen() {
      try { if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); } catch (e) {}
      if (fsByUs && fsElement()) {
        const ex = document.exitFullscreen || document.webkitExitFullscreen;
        try { const p = ex && ex.call(document); if (p && p.catch) p.catch(() => {}); } catch (e) {}
      }
      fsByUs = false;
    }

    function exit() {
      if (!on) return;
      on = false;
      card.classList.remove('ls-full');
      root.classList.remove('ls-on');
      paint();
      leaveFullscreen();
      // Leaving fullscreen / rotating back re-lays the page out, so restore after it settles
      const back = () => window.scrollTo(0, savedY);
      back();
      setTimeout(back, 350);
    }

    btn.addEventListener('click', () => (on ? exit() : enter()));
    // Android back gesture / Esc ends the browser's fullscreen -- leave our view with it
    const onFsChange = () => { if (on && fsByUs && !fsElement()) { fsByUs = false; exit(); } };
    document.addEventListener('fullscreenchange', onFsChange);
    document.addEventListener('webkitfullscreenchange', onFsChange);
    document.addEventListener('keydown', e => { if (on && e.key === 'Escape') exit(); });

    paint();
  }

  global.LandscapeView = { mount };
})(window);
