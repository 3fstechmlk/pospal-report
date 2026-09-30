/* ── 3FS Date Range Picker ──────────────────────────────────────────────────── */
(function(global) {
  'use strict';

  const WDAYS  = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  function fmt(d) {
    return d.getFullYear() + '-' +
           String(d.getMonth() + 1).padStart(2, '0') + '-' +
           String(d.getDate()).padStart(2, '0');
  }
  function today()     { return fmt(new Date()); }
  function offset(n)   { const d = new Date(); d.setDate(d.getDate() + n); return fmt(d); }
  function firstOfMonth(y, m) { return fmt(new Date(y, m, 1)); }
  function lastOfMonth (y, m) { return fmt(new Date(y, m + 1, 0)); }

  function thisWeek() {
    const d = new Date(), dow = d.getDay() === 0 ? 6 : d.getDay() - 1;
    const mon = new Date(d); mon.setDate(d.getDate() - dow);
    const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
    return [fmt(mon), fmt(sun)];
  }
  function lastWeek() {
    const d = new Date(), dow = d.getDay() === 0 ? 6 : d.getDay() - 1;
    const mon = new Date(d); mon.setDate(d.getDate() - dow - 7);
    const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
    return [fmt(mon), fmt(sun)];
  }
  // Last date whose sales have been generated (business day closes at 6 AM MY time = UTC+8)
  function lastSafeDate() {
    const now = new Date();
    const myHour = (now.getUTCHours() + 8) % 24;
    return myHour >= 6 ? offset(-1) : offset(-2);
  }

  function thisMonth() {
    const d = new Date();
    return [firstOfMonth(d.getFullYear(), d.getMonth()), lastSafeDate()];
  }
  function lastMonth() {
    const d = new Date();
    return [firstOfMonth(d.getFullYear(), d.getMonth() - 1),
            lastOfMonth (d.getFullYear(), d.getMonth() - 1)];
  }

  const SHORTCUTS = [
    { label: 'Yesterday',   range: () => { const d = offset(-1); return [d, d]; } },
    { label: '2 Days Ago',  range: () => { const d = offset(-2); return [d, d]; } },
    { label: 'This Week',   range: () => { const [s] = thisWeek(); return [s, offset(-1)]; } },
    { label: 'Last Week',   range: lastWeek  },
    { label: 'This Month',  range: thisMonth },
    { label: 'Last Month',  range: lastMonth },
    { label: 'Last 7 Days', range: () => [offset(-7), offset(-1)] },
  ];

  class DateRangePicker {
    constructor(startId, endId, onChange) {
      this._sEl      = document.getElementById(startId);
      this._eEl      = document.getElementById(endId);
      this._onChange = onChange || function(){};
      this._popup    = null;
      this._curEl    = null;
      this._calY     = new Date().getFullYear();
      this._calM     = new Date().getMonth();
      this._mpY      = new Date().getFullYear();   // month-picker year (independent)
      this._init();
    }

    _init() {
      [this._sEl, this._eEl].forEach(el => {
        el.style.cssText = 'position:absolute;opacity:0;pointer-events:none;width:1px;height:1px;overflow:hidden';
        const disp = document.createElement('div');
        disp.className = 'dp-input';
        disp.setAttribute('tabindex', '0');
        el._dpDisp = disp;
        el.parentNode.insertBefore(disp, el.nextSibling);
        this._updateDisp(el);
        disp.addEventListener('click', e => { e.stopPropagation(); this._toggle(el, disp); });
        disp.addEventListener('keydown', e => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this._toggle(el, disp); }
        });
      });
      document.addEventListener('click', () => { if (this._popup) this._close(); });
    }

    _updateDisp(el) {
      if (el._dpDisp) el._dpDisp.textContent = el.value ? el.value.replace(/-/g, '.') : '–';
    }

    _toggle(el, disp) {
      if (this._popup) {
        if (this._curEl === el) { this._close(); return; }
        this._close();
      }
      this._open(el, disp);
    }

    _open(el, disp) {
      this._curEl = el;
      const ref = el.value ? new Date(el.value + 'T00:00:00') : new Date();
      this._calY = ref.getFullYear();
      this._calM = ref.getMonth();
      this._mpY  = this._calY;

      const pop = this._buildPopup();
      this._popup = pop;
      document.body.appendChild(pop);

      const rect = disp.getBoundingClientRect();
      pop.style.top  = (rect.bottom + 4) + 'px';
      pop.style.left = rect.left + 'px';

      requestAnimationFrame(() => {
        const pw = pop.offsetWidth, ph = pop.offsetHeight;
        const vw = window.innerWidth,  vh = window.innerHeight;
        if (rect.left + pw > vw - 8)
          pop.style.left = Math.max(8, rect.right - pw) + 'px';
        if (rect.bottom + 4 + ph > vh - 8)
          pop.style.top  = Math.max(8, rect.top - ph - 4) + 'px';
      });
    }

    _close() {
      if (this._popup) { this._popup.remove(); this._popup = null; this._curEl = null; }
    }

    _buildPopup() {
      const pop = document.createElement('div');
      pop.className = 'dp-popup';
      pop.addEventListener('click', e => e.stopPropagation());

      pop.innerHTML = `
        <div class="dp-cal">
          <div class="dp-nav">
            <button class="dp-arr" id="dp-p">&#8249;</button>
            <span class="dp-nav-lbl" id="dp-ym"></span>
            <button class="dp-arr" id="dp-n">&#8250;</button>
          </div>
          <div class="dp-wdays">${WDAYS.map(d => `<span>${d}</span>`).join('')}</div>
          <div class="dp-grid" id="dp-grid"></div>
          <div class="dp-foot"><button class="dp-cls" id="dp-close">Close</button></div>
        </div>
        <div class="dp-mcol">
          <div class="dp-nav">
            <button class="dp-arr" id="dp-yp">&#8249;</button>
            <span class="dp-ynav-lbl" id="dp-yr"></span>
            <button class="dp-arr" id="dp-yn">&#8250;</button>
          </div>
          <div class="dp-mgrid" id="dp-mgrid"></div>
        </div>
        <div class="dp-sh-col">
          ${SHORTCUTS.map(s => `<button class="dp-sh" data-sh="${s.label}">${s.label}</button>`).join('')}
        </div>`;

      // Day calendar nav
      pop.querySelector('#dp-p').onclick = () => {
        if (--this._calM < 0) { this._calM = 11; this._calY--; }
        this._renderGrid(pop);
      };
      pop.querySelector('#dp-n').onclick = () => {
        if (++this._calM > 11) { this._calM = 0; this._calY++; }
        this._renderGrid(pop);
      };
      pop.querySelector('#dp-close').onclick = () => this._close();

      // Month picker year nav
      pop.querySelector('#dp-yp').onclick = () => { this._mpY--; this._renderMonthGrid(pop); };
      pop.querySelector('#dp-yn').onclick = () => { this._mpY++; this._renderMonthGrid(pop); };

      // Shortcuts
      pop.querySelectorAll('.dp-sh').forEach(btn => {
        btn.onclick = () => {
          const sh = SHORTCUTS.find(s => s.label === btn.dataset.sh);
          if (sh) { const [s, e] = sh.range(); this.setRange(s, e); this._close(); }
        };
      });

      this._renderGrid(pop);
      this._renderMonthGrid(pop);
      return pop;
    }

    _renderGrid(pop) {
      const y = this._calY, m = this._calM;
      pop.querySelector('#dp-ym').textContent = `${MONTHS[m]} ${y}`;

      const sVal   = this._sEl.value;
      const eVal   = this._eEl.value;
      const todayS = today();
      const dow1   = (new Date(y, m, 1).getDay() + 6) % 7;
      const days   = new Date(y, m + 1, 0).getDate();

      let html = '<span></span>'.repeat(dow1);
      for (let d = 1; d <= days; d++) {
        const ds = `${y}-${String(m+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        let cls = 'dp-d';
        // A day that hasn't arrived yet has nothing to report, so don't let it be
        // picked at all (the month shortcuts below already cap themselves).
        if (ds > todayS) cls += ' dp-dis';
        if (ds === todayS) cls += ' dp-today';
        if (ds === sVal || ds === eVal) cls += ' dp-sel';
        else if (sVal && eVal && ds > sVal && ds < eVal) cls += ' dp-range';
        html += `<span class="${cls}" data-d="${ds}">${d}</span>`;
      }

      const grid = pop.querySelector('#dp-grid');
      grid.innerHTML = html;
      grid.querySelectorAll('.dp-d').forEach(cell => {
        if (cell.classList.contains('dp-dis')) return;
        cell.onclick = () => {
          this._curEl.value = cell.dataset.d;
          this._updateDisp(this._curEl);
          this._close();
          this._onChange();
        };
      });

      // Keep month grid in sync with calendar year
      this._mpY = y;
      this._renderMonthGrid(pop);
    }

    _renderMonthGrid(pop) {
      pop.querySelector('#dp-yr').textContent = this._mpY;
      const grid = pop.querySelector('#dp-mgrid');
      grid.innerHTML = MONTHS.map((mn, i) => {
        const active = (i === this._calM && this._mpY === this._calY) ? ' dp-msel' : '';
        return `<button class="dp-mb${active}" data-y="${this._mpY}" data-m="${i}">${mn}</button>`;
      }).join('');
      grid.querySelectorAll('.dp-mb').forEach(btn => {
        btn.onclick = () => {
          const y    = parseInt(btn.dataset.y);
          const m    = parseInt(btn.dataset.m);
          const first = firstOfMonth(y, m);
          const safe  = lastSafeDate();
          if (first > safe) return;            // future month — no generated data, do nothing
          const fullLast = lastOfMonth(y, m);
          const last = fullLast <= safe ? fullLast : safe;   // cap at last generated date
          this.setRange(first, last);
          this._close();
        };
      });
    }

    /** Set both start and end, update displays, fire onChange */
    setRange(start, end) {
      this._sEl.value = start;
      this._eEl.value = end;
      this._updateDisp(this._sEl);
      this._updateDisp(this._eEl);
      this._onChange();
    }

    getStart() { return this._sEl.value; }
    getEnd()   { return this._eEl.value; }
  }

  global.DateRangePicker = DateRangePicker;
})(window);
