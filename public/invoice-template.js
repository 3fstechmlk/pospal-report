// ── Shared Invoice Template (block-based + element overrides) ───────────────
// Used by orders.html (Print / PDF / WhatsApp link) and admin.html (Edit Report
// editor + live preview) so the preview always matches the real invoice.
// A template is a list of blocks (header/meta/items/totals/payment/footer plus
// custom text/divider/spacer) stored per merchant in data/inv_settings_<mid>.json.
// Every rendered element carries a data-el key; per-element overrides in
// settings.el = {key: {text, size, bold, italic, color, family}} let the admin
// re-write any label / value style, including the defaults.
window.InvoiceTemplate = (function () {
  const r2  = n => Math.round((parseFloat(n) || 0) * 100) / 100;
  const fm  = n => (parseFloat(n) || 0).toLocaleString('en-MY', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const esc = s => (s + '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const escA = s => esc(s).replace(/"/g, '&quot;').replace(/\n/g, '&#10;');

  // on(s, 'show_member') → true unless explicitly false (legacy toggle fields)
  const on = (s, k) => s[k] !== false && s[k] !== 'false' && s[k] !== 0;

  // Discount from Pospal discountDetails (matches 折扣分析: types 6=单品, 11=积分兑换, 12=整单)
  function itemDiscount(t) {
    return r2((t.items || []).reduce((s, i) => {
      const dd = i.discountDetails || [];
      if (dd.length) return s + r2(dd.reduce((ds, d) => ds + r2(d.discountTotalAmount || d.discountAmount || 0), 0));
      const d = r2(r2((i.sellPrice || 0) * (i.quantity || 0)) - r2(i.totalAmount || 0));
      return s + (d > 0 ? d : 0);
    }, 0));
  }

  // ── Blocks ──────────────────────────────────────────────────────────────────
  // 'input' = TextBox: the admin sets its title, the merchant fills in the content
  // on the Report page (default in settings.inputs[blockId], editable per invoice).
  const BLOCK_TYPES = ['header', 'meta', 'items', 'totals', 'payment', 'footer', 'text', 'divider', 'spacer', 'input'];
  const BLOCK_NAMES = {header: 'Header', meta: 'Info Fields', items: 'Items Table', totals: 'Totals',
                       payment: 'Payment Method', footer: 'Footer', text: 'Text', divider: 'Divider', spacer: 'Spacer',
                       input: 'TextBox'};

  // Placeholder variables usable inside Text blocks and element overrides
  const PLACEHOLDERS = ['invoice_no', 'date', 'time', 'cashier', 'table', 'member_name', 'member_phone',
                        'points', 'balance', 'company_name', 'ssm', 'sst', 'phone', 'email', 'address',
                        'subtotal', 'discount', 'tax', 'service_charge', 'rounding', 'total',
                        'items_count', 'qty_total', 'remark', 'ticket_remark'];

  // Per-block toggleable values shown in the editor's Layout panel.
  // Each entry is [element key, label]; visibility is stored as el[key].show === false.
  const BLOCK_ELEMENTS = {
    header:  [['co_name', 'Company Name'], ['co_info', 'Company Details'], ['co_regs', 'SSM / SST'],
              ['title', 'Title'], ['inv_no', 'Invoice No'], ['inv_date', 'Invoice Date']],
    items:   [['th_qty', 'Qty'], ['th_price', 'Unit Price'], ['th_amount', 'Amount'],
              ['item_remark', 'Item Remark']],
    totals:  [['tot_discount_lbl', 'Discount'], ['tot_service_lbl', 'Service Charge'],
              ['tot_rounding_lbl', 'Rounding'], ['tot_tax_lbl', 'Tax'], ['tot_total_lbl', 'Total']],
    payment: [['pay_lbl', 'Label'], ['pay_items', 'Amounts']],
    footer:  [['pos_remark', 'Transaction Remark'], ['reg_note', 'Tax Note'],
              ['footer_text', 'Footer Text']],
  };

  // Per-block fields shown as chips in the editor, in default render order.
  //   k     — order key (also the element key toggled via el[k].show unless opt is set)
  //   opt   — visibility lives in block.opts[opt] instead (def = default when unset)
  //   g     — group: fields can only be reordered within the same group
  //   fixed — keeps its place (not reorderable)
  // The admin's custom order is stored per block as opts.order = [k, ...].
  const BLOCK_FIELDS = {
    header:  [{k: 'co_name', l: 'Company Name', g: 'co'}, {k: 'co_info', l: 'Company Details', g: 'co'},
              {k: 'co_regs', l: 'SSM / SST', g: 'co'},
              {k: 'title', l: 'Title', g: 'doc'}, {k: 'inv_no', l: 'Invoice No', g: 'doc'},
              {k: 'inv_date', l: 'Invoice Date', g: 'doc'}],
    meta:    [{k: 'invoice_no', l: 'Invoice No', opt: 'invoice_no', def: false},
              {k: 'date', l: 'Date', opt: 'date', def: false},
              {k: 'cashier', l: 'Cashier', opt: 'cashier', def: true},
              {k: 'table', l: 'Table', opt: 'table', def: true},
              {k: 'member', l: 'Member', opt: 'member', def: true},
              {k: 'points', l: 'Points', opt: 'points', def: true}],
    items:   [{k: 'th_qty', l: 'Qty'}, {k: 'th_price', l: 'Unit Price'}, {k: 'th_amount', l: 'Amount'},
              {k: 'th_disc', l: 'Discount', opt: 'discount', def: true},
              {k: 'item_remark', l: 'Item Remark', fixed: true}],
    totals:  [{k: 'tot_subtotal_lbl', l: 'Subtotal', opt: 'subtotal', def: true},
              {k: 'tot_discount_lbl', l: 'Discount'}, {k: 'tot_service_lbl', l: 'Service Charge'},
              {k: 'tot_rounding_lbl', l: 'Rounding'}, {k: 'tot_tax_lbl', l: 'Tax'},
              {k: 'tot_total_lbl', l: 'Total', fixed: true}],
    payment: [{k: 'pay_lbl', l: 'Label'}, {k: 'pay_items', l: 'Amounts'}],
    footer:  [{k: 'reg_note', l: 'Tax Note'}, {k: 'pos_remark', l: 'Transaction Remark'},
              {k: 'footer_text', l: 'Footer Text'}],
  };
  const FIELD_GROUPS = {co: 'Company', doc: 'Title'};

  // Fields the admin can add to Info Fields / Totals (opts.extra):
  //   data field   {k: src, src}            — value comes from the transaction
  //   custom field {k: 'c…', label, value}  — admin's own label + fixed value ({variables} allowed)
  const EXTRA_DATA = {
    meta:    [['time', 'Time'], ['member_name', 'Member Name'], ['member_phone', 'Member Phone'],
              ['balance', 'Balance'], ['items_count', 'Items Count'], ['qty_total', 'Total Qty'],
              ['ticket_remark', 'Ticket Remark'], ['subtotal', 'Subtotal'], ['total', 'Total']],
    totals:  [['items_count', 'Items Count'], ['qty_total', 'Total Qty']],
    header:  [['phone', 'Phone'], ['email', 'Email'], ['address', 'Address'],
              ['invoice_no', 'Invoice No'], ['date', 'Date'], ['time', 'Time']],
    payment: [['total', 'Total Paid'], ['date', 'Date'], ['time', 'Time']],
    footer:  [['company_name', 'Company Name'], ['phone', 'Phone'], ['email', 'Email'],
              ['address', 'Address'], ['total', 'Total'], ['ticket_remark', 'Ticket Remark']],
    items:   [['barcode', 'Barcode']],   // per-item column; items takes no custom field
  };
  // Where a block's added fields live (group, for reorder) and their key prefix
  // (so keys never clash across blocks or with built-ins).
  const EXTRA_GROUP  = {header: 'co'};
  const EXTRA_PREFIX = {totals: 'tx_', header: 'hx_', payment: 'px_', footer: 'fx_', items: 'ix_'};
  const EXTRA_KEY_RE = /^[a-z0-9_]{1,20}$/;
  function extras(type, o) {
    const data = (EXTRA_DATA[type] || []).map(d => d[0]);
    const builtin = (BLOCK_FIELDS[type] || []).map(f => f.k);
    const seen = {};
    return (Array.isArray(o && o.extra) ? o.extra : []).filter(e => {
      if (!e || typeof e.k !== 'string' || !EXTRA_KEY_RE.test(e.k) || seen[e.k] || builtin.includes(e.k)) return false;
      if (e.src ? !data.includes(e.src) : typeof e.label !== 'string') return false;
      return (seen[e.k] = true);
    });
  }
  // Order key of an added field (per-block prefix keeps keys unique)
  const extraKey = (type, e) => (EXTRA_PREFIX[type] || '') + e.k;
  const extraLabel = (type, e) => e.src ? ((EXTRA_DATA[type] || []).find(d => d[0] === e.src) || [, e.src])[1] : e.label;
  // Built-in fields + added fields of a block, as {k, l, g, extra}
  function blockFields(type, o) {
    const g = EXTRA_GROUP[type] || '';
    return (BLOCK_FIELDS[type] || []).concat(extras(type, o).map(e =>
      ({k: extraKey(type, e), l: extraLabel(type, e), g, extra: e})));
  }
  // Row data of an added field, or null when it has nothing to show
  function extraRow(type, e, c, valKey) {
    if (e.src) {
      const v = e.src === 'ticket_remark' ? c.posRemark : c.vars[e.src];
      const val = v == null ? '' : String(v);
      return val ? {lbl: extraLabel(type, e), val} : null;
    }
    const tpl = (c.el[valKey] || {}).text || e.value || '';
    if (!c.edit && !subst(tpl, c.vars).replace(/<br>/g, '').trim()) return null;
    return {lbl: e.label, custom: true, tpl: e.value || ''};
  }

  // Reorderable keys of a block in display order: the saved opts.order (unknown
  // / duplicate keys dropped), then any fields it doesn't mention, in default order.
  function fieldOrder(type, o) {
    const known = blockFields(type, o).filter(f => !f.fixed).map(f => f.k);
    const saved = Array.isArray(o && o.order)
      ? o.order.filter((k, i, a) => known.includes(k) && a.indexOf(k) === i) : [];
    return saved.concat(known.filter(k => !saved.includes(k)));
  }
  function fieldGroup(type, k, o) {
    const f = blockFields(type, o).find(x => x.k === k);
    return (f && f.g) || '';
  }
  // One labeled line for a header / payment / footer added field (or '' if empty).
  // The wrapper carries data-ord so it can be reordered on the preview.
  function extraLine(type, e, c, opts) {
    opts = opts || {};
    const key = extraKey(type, e);
    if ((c.el['f_' + key] || {}).show === false) return '';
    const r = extraRow(type, e, c, 'val_' + key);
    if (!r) return '';
    const lbl = E(c, 'lbl_' + key, r.lbl + ' · Label', r.lbl, null, {tag: 'span', style: 'font-weight:600;'});
    const val = r.custom ? E(c, 'val_' + key, r.lbl + ' · Value', r.tpl, null, {tag: 'span'})
                         : E(c, 'val_' + key, r.lbl + ' · Value', '', esc(r.val), {tag: 'span', text: false});
    const od = c.edit ? ` data-ord="${key}"${opts.og ? ` data-og="${opts.og}"` : ''}` : '';
    return `<div${od} style="${opts.style || ''}">${lbl}: ${val}</div>`;
  }
  // Edit-mode attributes marking a reorderable unit for the preview's drag grip
  const ordA = (c, k, g) => c.edit ? ` data-ord="${k}"${g ? ` data-og="${g}"` : ''}` : '';

  // Default template = the classic design; legacy show_* toggles map onto it.
  function defaultBlocks(s) {
    s = s || {};
    return [
      {id: 'd0', type: 'header',  show: true, opts: {layout: 'split'}},
      {id: 'd1', type: 'meta',    show: true, opts: {style: 'grid', invoice_no: false, date: false,
                                                     cashier: on(s, 'show_cashier'), table: on(s, 'show_table'),
                                                     member: on(s, 'show_member'), points: on(s, 'show_member')}},
      {id: 'd2', type: 'items',   show: true, opts: {discount: on(s, 'show_discount')}},
      {id: 'd3', type: 'totals',  show: true, opts: {subtotal: on(s, 'show_subtotal')}},
      {id: 'd4', type: 'payment', show: on(s, 'show_payment'), opts: {}},
      {id: 'd5', type: 'footer',  show: true, opts: {}},
    ];
  }

  function normalizeBlocks(s) {
    const src = (Array.isArray(s.blocks) && s.blocks.length) ? s.blocks : defaultBlocks(s);
    return src.filter(b => b && BLOCK_TYPES.includes(b.type)).map((b, i) => ({
      id: b.id || ('b' + i), type: b.type, show: b.show !== false, opts: b.opts || {},
    }));
  }

  // ── Render context ──────────────────────────────────────────────────────────
  function makeCtx(t, s, opts) {
    const member = opts.member || null;
    const [dp, tp]    = (t.datetime || '').split(' ');
    const [y, mo, dd] = (dp || '').split('-');
    const dateStr = dp ? `${dd}/${mo}/${y}` : '—';
    const items = t.items || [];
    const tax  = r2(t.taxFee || 0), svc = r2(t.serviceFee || 0), rnd = r2(t.rounding || 0);
    const disc = itemDiscount(t),   net = r2(t.totalAmount || 0);
    const gross = r2(items.reduce((sm, i) => sm + r2((i.sellPrice || 0) * (i.quantity || 0)), 0));
    const accent = ((s.accent || '').trim()) || '#f60';
    const title  = ((s.title  || '').trim()) || 'TAX INVOICE';
    const merch  = s.name || opts.fallbackName || '3FS Technology';
    const addrParts = [s.addr1, s.addr2, [s.post, s.city].filter(Boolean).join(' '), s.state].filter(Boolean);
    const remark    = (opts.remark || '').trim();     // typed by the user for this invoice
    const posRemark = (t.remark   || '').trim();     // typed into Pospal on the ticket

    const vars = {
      invoice_no: t.sn || '—', date: dateStr, time: tp ? tp.slice(0, 5) : '',
      cashier: (t.cashier || {}).name || '', table: (t.ticketOnTable || {}).tableCardNo || '',
      member_name: member ? (member.name || '') : '', member_phone: member ? (member.phone || '') : '',
      points: member && member.point != null ? member.point : '',
      balance: member && member.balance != null ? 'RM ' + parseFloat(member.balance).toFixed(2) : '',
      company_name: merch, ssm: s.ssm || '', sst: s.sst || '', phone: s.phone || '', email: s.email || '',
      address: addrParts.join(', '),
      subtotal: 'RM ' + fm(gross), discount: 'RM ' + fm(disc), tax: 'RM ' + fm(tax),
      service_charge: 'RM ' + fm(svc), rounding: fm(rnd), total: 'RM ' + fm(net),
      items_count: items.length, qty_total: items.reduce((sm, i) => sm + (parseFloat(i.quantity) || 0), 0),
      remark: remark, ticket_remark: posRemark,
    };
    // TextBox content: saved per-merchant defaults (s.inputs) merged with any
    // per-invoice overrides passed in opts.inputs (the Report page print flow).
    const inputs = Object.assign({}, s.inputs || {}, opts.inputs || {});
    return {t, s, el: s.el || {}, edit: !!opts.edit, member, remark, posRemark, dateStr, tp,
            tax, svc, rnd, disc, net, gross, accent, title, merch, addrParts, vars, inputs, PM: opts.PM || {}};
  }

  // Substitute {placeholder} vars in user text (escaped, newlines → <br>)
  function subst(text, vars) {
    return esc(text || '')
      .replace(/\{(\w+)\}/g, (m, k) => (k in vars) ? esc(String(vars[k])) : m)
      .replace(/\n/g, '<br>');
  }

  // Inline style from a per-element override
  function ovStyle(o) {
    if (!o) return '';
    let st = '';
    if (o.size) st += `font-size:${parseFloat(o.size)}px;`;
    if (o.bold === true) st += 'font-weight:700;'; else if (o.bold === false) st += 'font-weight:400;';
    if (o.italic === true) st += 'font-style:italic;'; else if (o.italic === false) st += 'font-style:normal;';
    if (o.color) st += `color:${o.color};`;
    if (o.family === 'serif') st += "font-family:Georgia,'Times New Roman',serif;";
    else if (o.family === 'mono') st += "font-family:Menlo,Consolas,monospace;";
    if (o.width)  st += `width:${parseFloat(o.width)}px;`;
    if (o.height) st += `height:${parseFloat(o.height)}px;`;
    return st;
  }

  // Editable element. name → shown in the editor popover; defText → raw default
  // template (placeholders allowed) used to prefill the popover; defHtml → the
  // rendered default when no text override (falls back to subst(defText)).
  // opts: {tag, cls, style, text:false → content not text-editable (data value)}
  function E(c, key, name, defText, defHtml, opts) {
    opts = opts || {};
    const o = c.el[key] || {};
    if (o.show === false) return '';
    const textEditable = opts.text !== false;
    const html = (textEditable && o.text) ? subst(o.text, c.vars)
               : (defHtml != null ? defHtml : subst(defText || '', c.vars));
    const tag = opts.tag || 'span';
    const cls = opts.cls ? ` class="${opts.cls}"` : '';
    let st  = (opts.style || '') + ovStyle(o);
    if ((o.width || o.height) && tag === 'span') st += 'display:inline-block;vertical-align:top;';
    const raw = (textEditable && o.text) ? o.text : (defText || '');
    const ed  = c.edit ? ` data-en="${escA(name)}" data-ed="${escA(raw)}" data-et="${textEditable ? 1 : 0}" data-ot="${(textEditable && o.text) ? 1 : 0}"` : '';
    const od  = opts.ord ? ordA(c, opts.ord, opts.og) : '';
    return `<${tag} data-el="${key}"${cls}${st ? ` style="${st}"` : ''}${ed}${od}>${html}</${tag}>`;
  }

  // ── Block renderers ─────────────────────────────────────────────────────────
  function renderHeader(o, c) {
    const s = c.s;
    const infoText = [c.addrParts.join('\n'), s.phone ? 'Tel: ' + s.phone : '', s.email ? 'Email: ' + s.email : ''].filter(Boolean).join('\n');
    // When the admin has resized the Company Details box (and not overridden its
    // text), render the address as flowing text so it re-wraps to fit the box.
    const ci = c.el.co_info || {};
    const infoFlow = (ci.width || ci.height) && !ci.text;
    const infoHtml = infoFlow ? esc(infoText.replace(/\n/g, ', '))
      : `${c.addrParts.map(a => `<div>${esc(a)}</div>`).join('')}` +
        `${s.phone ? '<div>Tel: ' + esc(s.phone) + '</div>' : ''}${s.email ? '<div>Email: ' + esc(s.email) + '</div>' : ''}`;
    const regsHtml = `${s.ssm ? '<span><strong>SSM:</strong> ' + esc(s.ssm) + '</span>' : ''}` +
      `${s.sst ? '<span><strong>SST Reg:</strong> ' + esc(s.sst) + '</span>' : ''}`;
    const regsText = [s.ssm ? 'SSM: ' + s.ssm : '', s.sst ? 'SST Reg: ' + s.sst : ''].filter(Boolean).join('   ');
    const ctr = o.layout === 'center';
    const hasRegs = !!(regsText || c.el.co_regs);
    const co = {
      co_name: () => E(c, 'co_name', 'Company Name', '{company_name}', null,
        {tag: 'div', cls: 'co-name', style: ctr ? 'font-size:20px;letter-spacing:.3px;margin-bottom:6px;' : '', ord: 'co_name', og: 'co'}),
      co_info: () => E(c, 'co_info', 'Company Details', infoText, infoHtml,
        {tag: 'div', cls: 'co-info', ord: 'co_info', og: 'co'}),
      co_regs: () => hasRegs ? E(c, 'co_regs', 'Registration Nos', regsText, regsHtml, {tag: 'div', ord: 'co_regs', og: 'co',
        style: ctr ? 'margin-top:4px;font-size:10px;color:#52525b;display:flex;gap:16px;flex-wrap:wrap;justify-content:center;'
                   : 'margin-top:8px;font-size:10px;color:#52525b;display:flex;gap:16px;flex-wrap:wrap;'}) : '',
    };
    extras('header', o).forEach(e => {
      const key = extraKey('header', e);
      co[key] = () => extraLine('header', e, c, {og: 'co',
        style: 'font-size:11px;color:#52525b;margin-top:' + (ctr ? '3px' : '4px') + ';'});
    });
    const ord = fieldOrder('header', o);
    const coHtml = ord.filter(k => co[k]).map(k => co[k]()).join('');
    const docKeys = ord.filter(k => fieldGroup('header', k, o) === 'doc');
    if (ctr) {
      // Centered receipt look: company block on top, a hairline, then the title
      // (uppercase, spaced) with a muted No · Date line beneath it.
      const lineE = k => k === 'inv_no'
        ? E(c, 'inv_no', 'Invoice No', 'No: {invoice_no}', null, {ord: 'inv_no', og: 'doc'})
        : E(c, 'inv_date', 'Invoice Date', 'Date: {date} · {time}', null, {ord: 'inv_date', og: 'doc'});
      let doc = '', run = [];
      const flush = () => {
        const parts = run.filter(Boolean);
        if (parts.length) doc += `<div style="font-size:11px;color:#71717a;margin-top:6px;letter-spacing:.3px">${parts.join('&nbsp;&nbsp;·&nbsp;&nbsp;')}</div>`;
        run = [];
      };
      docKeys.forEach(k => {
        if (k === 'title') {
          flush();
          doc += E(c, 'title', 'Document Title', c.title, null, {tag: 'h1', ord: 'title', og: 'doc',
            style: 'font-size:18px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#18181b;margin:0;'});
        } else run.push(lineE(k));
      });
      flush();
      const docBlock = doc ? `<div style="margin-top:14px;padding-top:13px;border-top:1px solid #ececef">${doc}</div>` : '';
      return `<div class="inv-hdr-ctr" style="text-align:center;padding-bottom:16px;border-bottom:2px solid ${c.accent}">
        ${coHtml}${docBlock}
      </div>`;
    }
    const docE = {
      title:    () => E(c, 'title', 'Document Title', c.title, null, {tag: 'h1', ord: 'title', og: 'doc'}),
      inv_no:   () => E(c, 'inv_no', 'Invoice No', 'No: {invoice_no}', null, {tag: 'div', cls: 'inv-no', ord: 'inv_no', og: 'doc'}),
      inv_date: () => E(c, 'inv_date', 'Invoice Date', 'Date: {date} · {time}', null, {tag: 'div', cls: 'inv-date', ord: 'inv_date', og: 'doc'}),
    };
    return `<div class="inv-hdr">
      <div>${coHtml}</div>
      <div class="inv-title">${docKeys.map(k => docE[k]()).join('')}</div>
    </div>`;
  }

  function metaRows(o, c) {
    const v = c.vars, rows = [];
    if (o.invoice_no) rows.push({key: 'invoice_no', lbl: 'Invoice No', val: v.invoice_no});
    if (o.date)       rows.push({key: 'date', lbl: 'Date', val: v.date + (v.time ? ' · ' + v.time : '')});
    if (o.cashier !== false && v.cashier) rows.push({key: 'cashier', lbl: 'Cashier', val: v.cashier});
    if (o.table   !== false && v.table)   rows.push({key: 'table',   lbl: 'Table',   val: v.table});
    if (o.member  !== false && c.member)  rows.push({key: 'member',  lbl: 'Member',  val: (v.member_name || v.member_phone || '—') + (v.member_name && v.member_phone ? ' · ' + v.member_phone : ''), accent: true});
    if (o.points  !== false && c.member && (c.member.point != null || c.member.balance != null))
      rows.push({key: 'points', lbl: 'Points / Balance', val: [c.member.point != null ? c.member.point + ' pts' : '', v.balance].filter(Boolean).join(' · ')});
    extras('meta', o).forEach(e => {
      if ((c.el['f_' + e.k] || {}).show === false) return;
      const r = extraRow('meta', e, c, 'val_' + e.k);
      if (r) rows.push(Object.assign({key: e.k}, r));
    });
    const ord = fieldOrder('meta', o);
    return rows.sort((a, b) => ord.indexOf(a.key) - ord.indexOf(b.key));
  }

  function renderMeta(o, c) {
    const rows = metaRows(o, c);
    if (!rows.length) return '';
    const lblE = r => E(c, 'lbl_' + r.key, r.lbl + ' · Label', r.lbl, null,
      {tag: 'div', cls: 'lbl', style: r.accent ? `color:${c.accent};` : ''});
    // Custom fields carry a typed value template ({variables} allowed) → text-editable
    const valE = (r, extra, tag, cls) => r.custom
      ? E(c, 'val_' + r.key, r.lbl + ' · Value', r.tpl, null, {tag, cls, style: extra || ''})
      : E(c, 'val_' + r.key, r.lbl + ' · Value', '', esc(r.val), {tag, cls, text: false, style: extra || ''});
    if (o.style === 'lines') {
      return `<div style="font-size:12px;line-height:2">${rows.map(r =>
        `<div style="display:flex;gap:6px;align-items:baseline"${ordA(c, r.key)}>${E(c, 'lbl_' + r.key, r.lbl + ' · Label', r.lbl, null, {style: 'color:#71717a;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;'})}${valE(r, 'font-weight:700;', 'span')}</div>`).join('')}</div>`;
    }
    return `<div class="meta-grid">${rows.map(r =>
      `<div class="meta-item"${r.accent ? ` style="border-left:2px solid ${c.accent};padding-left:10px"` : ''}${ordA(c, r.key)}>${lblE(r)}${valE(r, '', 'div', 'val')}</div>`).join('')}</div>`;
  }

  function renderItems(o, c) {
    const off = k => (c.el[k] || {}).show === false;
    const showQty = !off('th_qty'), showPrice = !off('th_price'), showAmt = !off('th_amount');
    const showDisc = o.discount !== false && !off('th_disc');
    const showItemRmk = !off('item_remark');
    // Description stays the first column; the rest follow the block's field order.
    const COLS = {
      th_qty:    {on: showQty,   name: 'Qty',        w: 44, td: r => `<td class="r">${r.i.quantity}</td>`},
      th_price:  {on: showPrice, name: 'Unit Price', w: 88, td: r => `<td class="r">${fm(r.i.sellPrice || 0)}</td>`},
      th_amount: {on: showAmt,   name: 'Amount',     w: 88, td: r => `<td class="r">${fm(r.act)}</td>`},
      th_disc:   {on: showDisc,  name: 'Discount',   w: 76, td: r =>
        `<td class="r" style="color:${r.dis > 0.005 ? '#dc2626' : '#a1a1aa'}">${r.dis > 0.005 ? fm(r.dis) : '—'}</td>`},
    };
    // Admin-added columns (currently just Barcode): one cell per item.
    extras('items', o).forEach(e => {
      const key = extraKey('items', e);
      COLS[key] = {on: !off('f_' + key), name: extraLabel('items', e), w: 90,
        td: r => `<td class="r" style="font-family:inherit">${e.src === 'barcode' ? esc((r.i.productBarcode || '').trim() || '—') : ''}</td>`};
    });
    const cols = fieldOrder('items', o).filter(k => COLS[k] && COLS[k].on);
    const irows = (c.t.items || []).map(i => {
      const act = r2(i.totalAmount || 0);
      const dis = r2(r2((i.sellPrice || 0) * (i.quantity || 0)) - act);
      const rmk = showItemRmk ? (i.remark || '').trim() : '';
      const desc = esc(i.name || '—') +
        (rmk ? `<div style="font-size:9.5px;color:#a16207;margin-top:1px">${esc(rmk)}</div>` : '');
      const row = {i, act, dis};
      return `<tr><td>${desc}</td>${cols.map(k => COLS[k].td(row)).join('')}</tr>`;
    }).join('');
    const ths = cols.map(k => E(c, k, 'Column · ' + COLS[k].name, COLS[k].name, null,
      {tag: 'th', cls: 'r', style: `width:${COLS[k].w}px;`, ord: k})).join('');
    return `<table>
      <thead><tr>${E(c, 'th_desc', 'Column · Description', 'Description', null, {tag: 'th'})}${ths}</tr></thead>
      ${E(c, 'items_rows', 'Item Rows', '', irows, {tag: 'tbody', text: false})}
    </table>`;
  }

  function renderTotals(o, c) {
    const off = k => (c.el[k] || {}).show === false;
    const lbl = (key, name, def) => E(c, key, name + ' · Label', def, null, {cls: 'lbl'});
    const val = (key, name, html, extra) => E(c, key, name + ' · Value', '', html, {cls: 'val', text: false, style: extra || ''});
    const ROWS = {
      tot_subtotal_lbl: () => o.subtotal !== false && !off('tot_subtotal_lbl') ? `<div class="trow" style="border-bottom:1px dashed #d4d4d8;padding-bottom:8px;margin-bottom:4px"${ordA(c, 'tot_subtotal_lbl')}>${E(c, 'tot_subtotal_lbl', 'Subtotal · Label', 'Subtotal', null, {cls: 'lbl', style: 'font-weight:600;color:#52525b;'})}${val('tot_subtotal_val', 'Subtotal', 'RM ' + fm(c.gross))}</div>` : '',
      tot_discount_lbl: () => c.disc > 0.005 && !off('tot_discount_lbl') ? `<div class="trow"${ordA(c, 'tot_discount_lbl')}>${lbl('tot_discount_lbl', 'Discount', 'Discount')}${val('tot_discount_val', 'Discount', '−RM ' + fm(c.disc), 'color:#dc2626;')}</div>` : '',
      tot_service_lbl:  () => c.svc > 0.001 && !off('tot_service_lbl') ? `<div class="trow"${ordA(c, 'tot_service_lbl')}>${lbl('tot_service_lbl', 'Service Charge', 'Service Charge')}${val('tot_service_val', 'Service Charge', 'RM ' + fm(c.svc))}</div>` : '',
      tot_rounding_lbl: () => Math.abs(c.rnd) > 0.001 && !off('tot_rounding_lbl') ? `<div class="trow"${ordA(c, 'tot_rounding_lbl')}>${lbl('tot_rounding_lbl', 'Rounding', 'Rounding')}${val('tot_rounding_val', 'Rounding', c.rnd > 0 ? '(' + fm(c.rnd) + ')' : '+' + fm(Math.abs(c.rnd)))}</div>` : '',
      tot_tax_lbl:      () => c.tax > 0.001 && !off('tot_tax_lbl') ? `<div class="trow tax"${ordA(c, 'tot_tax_lbl')}>${lbl('tot_tax_lbl', 'Service Tax', 'Service Tax (SST)')}${val('tot_tax_val', 'Service Tax', 'RM ' + fm(c.tax), 'color:#0369a1;')}</div>` : '',
    };
    extras('totals', o).forEach(e => {
      const k = extraKey('totals', e);
      ROWS[k] = () => {
        if ((c.el['f_' + k] || {}).show === false) return '';
        const r = extraRow('totals', e, c, 'val_' + k);
        if (!r) return '';
        return `<div class="trow"${ordA(c, k)}>${E(c, 'lbl_' + k, r.lbl + ' · Label', r.lbl, null, {cls: 'lbl'})}${
          r.custom ? E(c, 'val_' + k, r.lbl + ' · Value', r.tpl, null, {cls: 'val'})
                   : E(c, 'val_' + k, r.lbl + ' · Value', '', esc(r.val), {cls: 'val', text: false})}</div>`;
      };
    });
    // TOTAL is always the last row.
    return `<div class="totals-wrap"><div class="totals">
      ${fieldOrder('totals', o).filter(k => ROWS[k]).map(k => ROWS[k]()).join('')}
      ${!off('tot_total_lbl') ? `<div class="trow tot">${E(c, 'tot_total_lbl', 'Total · Label', 'TOTAL')}${val('tot_total_val', 'Total', 'RM ' + fm(c.net), `color:${c.accent};`)}</div>` : ''}
    </div></div>`;
  }

  function renderPayment(o, c) {
    const pills = (c.t.payments || []).map(p => `<span class="pill">${esc(c.PM[p.code] || p.code)} · RM ${fm(p.amount || 0)}</span>`).join('');
    const PARTS = {
      pay_lbl:   () => E(c, 'pay_lbl', 'Payment · Label', 'Payment Method', null, {tag: 'div', cls: 'pay-lbl', ord: 'pay_lbl'}),
      pay_items: () => E(c, 'pay_items', 'Payment · Values', '', pills, {tag: 'div', text: false, ord: 'pay_items'}),
    };
    const xm = {}; extras('payment', o).forEach(e => { xm[extraKey('payment', e)] = e; });
    return `<div class="pay-section">
      ${fieldOrder('payment', o).map(k => PARTS[k] ? PARTS[k]()
          : (xm[k] ? extraLine('payment', xm[k], c, {og: 'pay', style: 'font-size:12px;color:#52525b;margin-top:6px;'}) : '')).join('')}
    </div>`;
  }

  function renderFooter(o, c) {
    const s = c.s;
    const regDef = 'This is a tax invoice issued by {company_name}. SST Registration No: {sst}';
    // The per-invoice Additional Remark always follows the Transaction Remark.
    const PARTS = {
      reg_note: () => (s.sst || (c.el.reg_note || {}).text) ? E(c, 'reg_note', 'Tax Note', regDef, null, {tag: 'div', cls: 'reg-note', ord: 'reg_note'}) : '',
      pos_remark: () => `${(c.posRemark && (c.el.pos_remark || {}).show !== false) ? `<div style="margin-bottom:12px;padding:10px 12px;background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;font-size:12px;color:#78350f"${ordA(c, 'pos_remark')}><span style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:#b45309;display:block;margin-bottom:4px">Transaction Remark</span>${esc(c.posRemark)}</div>` : ''}
      ${c.remark ? `<div style="margin-bottom:12px;padding:10px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;color:#334155"><span style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:#64748b;display:block;margin-bottom:4px">Additional Remark</span>${esc(c.remark)}</div>` : ''}`,
      footer_text: () => E(c, 'footer_text', 'Footer Text', s.footer || 'Thank you for your purchase!', null, {tag: 'div', cls: 'footer-note', ord: 'footer_text'}),
    };
    const xm = {}; extras('footer', o).forEach(e => { xm[extraKey('footer', e)] = e; });
    return fieldOrder('footer', o).map(k => PARTS[k] ? PARTS[k]()
        : (xm[k] ? extraLine('footer', xm[k], c, {og: 'ft', style: 'font-size:11px;color:#71717a;margin-bottom:12px;'}) : '')).join('');
  }

  function renderText(o, c) {
    const sz = {sm: '11px', md: '13px', lg: '18px'}[o.size || 'md'] || '13px';
    const st = `font-size:${sz};text-align:${o.align || 'left'};` +
      `${o.bold ? 'font-weight:700;' : ''}${o.italic ? 'font-style:italic;' : ''}` +
      `color:${o.muted ? '#71717a' : '#18181b'};line-height:1.7`;
    return `<div style="${st}">${subst(o.text, c.vars)}</div>`;
  }

  // TextBox: the admin sets the title in /admin; the merchant types the content
  // on the Report page (default per-merchant, editable per invoice). c.inputs[id]
  // holds the resolved content. Empty content hides the whole block off-editor.
  function renderInput(b, c) {
    const o = b.opts || {};
    const title = (o.title || '').trim();
    const content = ((c.inputs || {})[b.id] || '').trim();
    if (!c.edit && !content) return '';
    const titleHtml = title
      ? `<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:#64748b;margin-bottom:4px">${esc(title)}</div>`
      : '';
    const body = content ? esc(content).replace(/\n/g, '<br>')
      : (c.edit ? `<span style="color:#a1a1aa;font-style:italic">${esc(title || 'TextBox')} — filled in on the Report page</span>` : '');
    return `<div style="padding:10px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;color:#334155">${titleHtml}${body}</div>`;
  }

  function renderBlock(b, c) {
    switch (b.type) {
      case 'header':  return renderHeader(b.opts, c);
      case 'meta':    return renderMeta(b.opts, c);
      case 'items':   return renderItems(b.opts, c);
      case 'totals':  return renderTotals(b.opts, c);
      case 'payment': return renderPayment(b.opts, c);
      case 'footer':  return renderFooter(b.opts, c);
      case 'text':    return renderText(b.opts, c);
      case 'input':   return renderInput(b, c);
      case 'divider': return `<div style="border-top:1.5px ${b.opts.style === 'dashed' ? 'dashed' : 'solid'} #d4d4d8"></div>`;
      case 'spacer':  return `<div style="height:${Math.max(2, Math.min(120, parseInt(b.opts.height) || 16))}px"></div>`;
      default:        return '';
    }
  }

  // Script injected into the preview iframe: drag blocks to reorder, click a
  // block to select its card, click any [data-el] element to edit it in place.
  function editScript(accent, vars) {
    return `<style>
.blk{position:relative;border-radius:4px;transition:box-shadow .1s}
.blk:hover{outline:1.5px dashed ${accent};outline-offset:5px}
.blk.dragging{opacity:.35}
.blk.drop-above{box-shadow:0 -3px 0 0 ${accent}}
.blk.drop-below{box-shadow:0 3px 0 0 ${accent}}
[data-el]{border-radius:2px}
[data-el]:hover{outline:1.5px solid ${accent};outline-offset:1px;cursor:pointer;box-shadow:inset 0 0 0 999px rgba(255,166,0,.07)}
[data-el].el-sel{outline:2px solid ${accent};outline-offset:1px;box-shadow:inset 0 0 0 999px rgba(255,166,0,.1)}
thead th[data-el]:hover{box-shadow:inset 0 0 0 999px rgba(255,255,255,.22)}
thead th[data-el].el-sel{outline-color:#fff;box-shadow:inset 0 0 0 999px rgba(255,255,255,.32)}
[data-el][contenteditable]:focus{outline:2px solid ${accent};outline-offset:1px;cursor:text}
#ir-rsz{position:fixed;width:12px;height:12px;background:#fff;border:2px solid ${accent};border-radius:3px;cursor:nwse-resize;z-index:99;display:none;box-shadow:0 1px 3px rgba(0,0,0,.35)}
#ir-grip{position:fixed;width:16px;height:16px;display:none;align-items:center;justify-content:center;background:${accent};color:#fff;border-radius:4px;font-size:11px;line-height:1;cursor:grab;z-index:100;box-shadow:0 1px 3px rgba(0,0,0,.35);user-select:none;touch-action:none}
#ir-grip.on{cursor:grabbing;opacity:0}
#ir-ordline{position:fixed;display:none;background:${accent};border-radius:2px;z-index:99;pointer-events:none}
[data-ord].ord-drag{opacity:.35}
/* Hovering the grip outlines every field that reorders together with it. */
[data-ord].ord-group{outline:1.5px dashed ${accent};outline-offset:2px;border-radius:3px}
/* While dragging a field, hide decorative accent borders (e.g. the Member row's
   left bar) so only the drop line reads as an orange line. */
.ir-fdrag .meta-item{border-left-color:transparent!important}
</style>
<script>
(function(){
  var VARS=${JSON.stringify(vars || {}).replace(/</g, '\\u003c')};
  function substLocal(t){return String(t).replace(/\\{(\\w+)\\}/g,function(m,k){return k in VARS?String(VARS[k]):m;});}
  var from=null;
  function clearMarks(){document.querySelectorAll('.blk').forEach(function(x){x.classList.remove('drop-above','drop-below');});}
  document.querySelectorAll('.blk').forEach(function(el){
    el.draggable=true;
    el.addEventListener('dragstart',function(){from=+el.dataset.bi;el.classList.add('dragging');});
    el.addEventListener('dragend',function(){el.classList.remove('dragging');clearMarks();});
    el.addEventListener('dragover',function(ev){
      ev.preventDefault();clearMarks();
      var r=el.getBoundingClientRect();
      el.classList.add(ev.clientY < r.top + r.height/2 ? 'drop-above' : 'drop-below');
    });
    el.addEventListener('drop',function(ev){
      ev.preventDefault();
      var r=el.getBoundingClientRect();
      var to=+el.dataset.bi + (ev.clientY < r.top + r.height/2 ? 0 : 1);
      clearMarks();
      if(from!=null) parent.postMessage({ir:'reorder',from:from,to:to},'*');
      from=null;
    });
    el.addEventListener('click',function(){parent.postMessage({ir:'select',id:el.dataset.id},'*');});
  });
  // Corner resize handle: follows the selected element; drag to set box size.
  var rsz=document.createElement('div');rsz.id='ir-rsz';document.body.appendChild(rsz);
  var selEl=null,drag=null;
  function placeRsz(){
    if(!selEl){rsz.style.display='none';return;}
    var r=selEl.getBoundingClientRect();
    rsz.style.display='block';
    rsz.style.left=(r.right-6)+'px';rsz.style.top=(r.bottom-6)+'px';
  }
  window.addEventListener('scroll',placeRsz,true);
  window.addEventListener('resize',placeRsz);
  // Field reorder: hovering a [data-ord] unit shows a grip; dragging the grip
  // moves that field among the units of the same block + group (data-og).
  var grip=document.createElement('div');grip.id='ir-grip';grip.textContent='\\u283f';
  grip.title='Drag to reorder';document.body.appendChild(grip);
  var oline=document.createElement('div');oline.id='ir-ordline';document.body.appendChild(oline);
  var gUnit=null,gHide=null,fd=null;
  function groupUnits(u){
    var b=u.closest('.blk'),g=u.dataset.og||'';
    return b?[].slice.call(b.querySelectorAll('[data-ord]')).filter(function(x){return (x.dataset.og||'')===g;}):[];
  }
  // Horizontal when another unit of the group shares this unit's row
  function inRow(u,list){
    var r=u.getBoundingClientRect();
    return list.some(function(x){return x!==u&&Math.abs(x.getBoundingClientRect().top-r.top)<6;});
  }
  // Outline just the field this grip will move, so the user knows what it grabs.
  function clearGroupHi(){document.querySelectorAll('.ord-group').forEach(function(x){x.classList.remove('ord-group');});}
  function showGroupHi(u){clearGroupHi();if(u)u.classList.add('ord-group');}
  function placeGrip(){
    if(!gUnit||!document.body.contains(gUnit)){gUnit=null;grip.style.display='none';return;}
    var r=gUnit.getBoundingClientRect(),h=inRow(gUnit,groupUnits(gUnit));
    grip.style.display='flex';
    grip.style.left=Math.max(0,h?r.left+r.width/2-8:r.left-17)+'px';
    grip.style.top=Math.max(0,h?r.top-17:r.top+Math.min(r.height,40)/2-8)+'px';
  }
  window.addEventListener('scroll',function(){if(!fd)placeGrip();},true);
  document.addEventListener('mousemove',function(ev){
    if(fd)return;
    if(ev.target===grip){clearTimeout(gHide);return;}
    var u=ev.target.closest&&ev.target.closest('[data-ord]');
    if(u){clearTimeout(gHide);if(u!==gUnit){gUnit=u;placeGrip();}}
    else if(gUnit){clearTimeout(gHide);gHide=setTimeout(function(){if(!fd){gUnit=null;placeGrip();}},300);}
  });
  document.addEventListener('mouseleave',function(){if(!fd){gUnit=null;placeGrip();}});
  // Point at the grip → show which fields drag together; leaving it clears them.
  grip.addEventListener('mouseenter',function(){if(gUnit)showGroupHi(gUnit);});
  grip.addEventListener('mouseleave',function(){if(!fd)clearGroupHi();});
  grip.addEventListener('pointerdown',function(ev){
    if(!gUnit||ev.button!==0)return;
    ev.preventDefault();ev.stopPropagation();
    fd={u:gUnit,list:groupUnits(gUnit),tgt:null,after:false};
    gUnit.classList.add('ord-drag');grip.classList.add('on');
    showGroupHi(gUnit);
    document.documentElement.classList.add('ir-fdrag');
    try{grip.setPointerCapture(ev.pointerId);}catch(e){}
  });
  grip.addEventListener('pointermove',function(ev){
    if(!fd)return;
    grip.style.left=(ev.clientX-8)+'px';grip.style.top=(ev.clientY-8)+'px';
    // nearest unit of the group (the dragged one itself = drop back in place)
    var best=null,bd=1e12;
    fd.list.forEach(function(x){
      var r=x.getBoundingClientRect();
      var dx=Math.max(r.left-ev.clientX,0,ev.clientX-r.right),dy=Math.max(r.top-ev.clientY,0,ev.clientY-r.bottom);
      if(dx*dx+dy*dy<bd){bd=dx*dx+dy*dy;best=x;}
    });
    if(!best||best===fd.u){fd.tgt=null;oline.style.display='none';return;}
    var r=best.getBoundingClientRect(),h=inRow(best,fd.list);
    var after=h?ev.clientX>r.left+r.width/2:ev.clientY>r.top+r.height/2;
    // Dropping right next to where it already is (after the previous unit /
    // before the next one) changes nothing — show no line so it doesn't promise a move.
    var i=fd.list.indexOf(fd.u),j=fd.list.indexOf(best);
    if((after&&j===i-1)||(!after&&j===i+1)){fd.tgt=null;oline.style.display='none';return;}
    fd.tgt=best;fd.after=after;
    var s=oline.style;s.display='block';
    if(h){
      // Centre the line in the gap between the two cells that will flank the
      // dropped field. "After Cashier" and "before Table" are the same drop, so
      // both must resolve to one position instead of jumping across the gap.
      var listNoU=fd.list.filter(function(x){return x!==fd.u;});
      var bi=listNoU.indexOf(best), insAt=after?bi+1:bi;
      var L=listNoU[insAt-1], R=listNoU[insAt];
      var lr=L&&L.getBoundingClientRect(), rr=R&&R.getBoundingClientRect(), x;
      if(lr&&rr&&Math.abs(lr.top-rr.top)<6){x=(lr.right+rr.left)/2;}
      else if(rr){x=rr.left;} else if(lr){x=lr.right;} else {x=r.left;}
      s.left=(x-1.5)+'px';s.top=r.top+'px';s.width='3px';s.height=r.height+'px';
    }
    else{s.left=r.left+'px';s.top=((after?r.bottom:r.top)-1.5)+'px';s.width=r.width+'px';s.height='3px';}
  });
  function endFieldDrag(commit){
    if(!fd)return;
    var f=fd;fd=null;
    f.u.classList.remove('ord-drag');grip.classList.remove('on');oline.style.display='none';
    clearGroupHi();
    document.documentElement.classList.remove('ir-fdrag');
    // Always snap the grip back to its field: if the move goes through, the
    // editor rebuilds the preview anyway; if not, the grip must not stay under the cursor.
    gUnit=f.u;placeGrip();
    if(commit&&f.tgt){
      var b=f.u.closest('.blk');
      parent.postMessage({ir:'ford',id:b.dataset.id,key:f.u.dataset.ord,ref:f.tgt.dataset.ord,after:f.after},'*');
    }
  }
  grip.addEventListener('pointerup',function(){endFieldDrag(true);});
  grip.addEventListener('pointercancel',function(){endFieldDrag(false);});
  // Press on blank space (not an element, not the handle) → deselect + close
  // popover. mousedown, not click: a blur of the previously edited element can
  // reflow the page between mousedown and mouseup, which suppresses click.
  document.addEventListener('mousedown',function(ev){
    if(ev.button!==0||ev.target===rsz||ev.target===grip)return;
    if(ev.target.closest&&ev.target.closest('[data-el]'))return;
    document.querySelectorAll('[data-el].el-sel').forEach(function(x){x.classList.remove('el-sel');});
    selEl=null;placeRsz();
    parent.postMessage({ir:'eldesel'},'*');
  });
  var rawBak=null;
  rsz.addEventListener('pointerdown',function(ev){
    if(!selEl)return;
    ev.preventDefault();ev.stopPropagation();
    var r=selEl.getBoundingClientRect();
    drag={x:ev.clientX,y:ev.clientY,w:r.width,h:r.height};
    // While resizing, show the substituted result (not the raw {placeholders})
    // so the box can be sized against the real content.
    rawBak=null;
    if(selEl.dataset.el==='co_info'&&selEl.dataset.ot!=='1'){
      // Sized Company Details renders as flowing text — switch now so the drag
      // shows exactly what will be saved, and keep it after the drag.
      selEl.innerText=substLocal(selEl.dataset.ed||'').replace(/\\n/g,', ');
      selEl.__origHtml=selEl.innerHTML;
    }else if(/\\{\\w+\\}/.test(selEl.innerText)){
      rawBak=selEl.innerText;
      selEl.innerText=substLocal(rawBak);
    }
    try{rsz.setPointerCapture(ev.pointerId);}catch(e){}
    var b=selEl.closest('.blk');if(b)b.draggable=false;
  });
  rsz.addEventListener('pointermove',function(ev){
    if(!drag||!selEl)return;
    var w=Math.max(10,Math.round(drag.w+ev.clientX-drag.x));
    var h=Math.max(8,Math.round(drag.h+ev.clientY-drag.y));
    if(getComputedStyle(selEl).display==='inline')selEl.style.display='inline-block';
    selEl.style.width=w+'px';selEl.style.height=h+'px';
    placeRsz();
  });
  rsz.addEventListener('pointerup',function(ev){
    if(!drag||!selEl){drag=null;return;}
    drag=null;
    var b=selEl.closest('.blk');if(b)b.draggable=true;
    if(rawBak!=null&&selEl.dataset.editing)selEl.innerText=rawBak;
    rawBak=null;
    var r=selEl.getBoundingClientRect();
    parent.postMessage({ir:'elsize',key:selEl.dataset.el,width:Math.round(r.width),height:Math.round(r.height)},'*');
  });
  document.querySelectorAll('[data-el]').forEach(function(el){
    if(el.dataset.et==='1'){
      // Type directly on the invoice: while focused the element shows its raw
      // template ({placeholders} visible); the rendered view is restored on blur.
      try{el.contentEditable='plaintext-only';}catch(e){}
      if(el.contentEditable!=='plaintext-only')el.contentEditable='true';
      el.spellcheck=false;
      el.addEventListener('focus',function(){
        if(el.dataset.editing)return;
        el.dataset.editing='1';
        el.__dirty=false;
        el.__origHtml=el.innerHTML;
        // Only swap to the raw template when it contains {placeholders} — plain
        // text is edited as-is (WYSIWYG), so the view never changes on click.
        var raw=el.dataset.ed||'';
        if(/\\{\\w+\\}/.test(raw)){
          el.innerText=raw;
          var rg=document.createRange();rg.selectNodeContents(el);rg.collapse(false);
          var sl=getSelection();sl.removeAllRanges();sl.addRange(rg);
        }
      });
      el.addEventListener('input',function(){
        el.__dirty=true;
        placeRsz();
        parent.postMessage({ir:'eltext',key:el.dataset.el,text:el.innerText},'*');
      });
      el.addEventListener('blur',function(){
        delete el.dataset.editing;
        var b=el.closest('.blk');if(b)b.draggable=true;
        // Restore the rendered view locally — rebuilding the iframe here would
        // swallow the click when the user is selecting another element.
        if(!el.__dirty){
          el.innerHTML=el.__origHtml;
        }else{
          var raw=el.innerText;
          el.innerText=substLocal(raw);
          el.dataset.ed=raw;
          el.dataset.ot='1';
        }
        el.__dirty=false;
      });
    }
    // Select on mousedown (not click): the previous element's blur can reflow
    // the page mid-press, which would make the browser drop the click event.
    el.addEventListener('mousedown',function(ev){
      if(ev.button!==0)return;
      ev.stopPropagation();
      if(el.dataset.et==='1'){var b=el.closest('.blk');if(b)b.draggable=false;}
      document.querySelectorAll('[data-el].el-sel').forEach(function(x){x.classList.remove('el-sel');});
      el.classList.add('el-sel');
      selEl=el;placeRsz();
      var r=el.getBoundingClientRect();
      parent.postMessage({ir:'el', key:el.dataset.el, name:el.dataset.en||el.dataset.el,
        def:el.dataset.ed||'', editable:el.dataset.et==='1',
        rect:{x:r.left,y:r.top,w:r.width,h:r.height}}, '*');
    });
    el.addEventListener('click',function(ev){ev.stopPropagation();});
  });
})();
<\/script>`;
  }

  // ── Page builder ────────────────────────────────────────────────────────────
  // t: ticket, s: invoice settings, opts: {autoprint, remark, member, PM, fallbackName, edit}
  // The WhatsApp share link gets opened on a phone far more often than on a
  // desktop, and this document is laid out for 680px.  Screen-only on purpose:
  // printing keeps the desktop layout, and `.pdfing` — set on <body> only while
  // html2pdf rasterises — pulls the few layout-defining rules back, so a phone
  // still downloads an A4-shaped PDF rather than a tall narrow one.
  const MOBILE_CSS = `
@media screen and (max-width:600px){
#inv-content{padding:14px 12px}
.inv-hdr{flex-direction:column;gap:10px}
.inv-title h1,.inv-title .inv-no,.inv-title .inv-date{text-align:left}
.inv-title h1{font-size:21px}
.co-name{font-size:16px}
.co-info{font-size:11.5px;line-height:1.6}
thead th{padding:6px 5px;font-size:9px;letter-spacing:.3px}
thead th.r{width:auto!important}
tbody td{padding:7px 5px;font-size:11.5px}
tbody td.r{white-space:nowrap}
.totals{width:100%}
.pill{margin-bottom:5px}
.dl-bar{position:sticky;top:0;z-index:20;padding:9px 12px}
.dl-bar button{padding:9px 15px;font-size:13px}
}
.pdfing{width:680px!important;max-width:none!important}
.pdfing #inv-content{padding:20px 28px!important}
.pdfing .inv-hdr{flex-direction:row!important}
.pdfing .inv-title h1{font-size:24px!important;text-align:right!important}
.pdfing .inv-title .inv-no,.pdfing .inv-title .inv-date{text-align:right!important}
.pdfing .totals{width:280px!important}`;

  function build(t, s, opts) {
    opts = opts || {};
    s    = s    || {};
    const c = makeCtx(t, s, opts);
    const blocks = normalizeBlocks(s);
    const visible = opts.edit ? blocks : blocks.filter(b => b.show);
    const body = visible.map((b, i) =>
      `<div class="blk" data-bi="${i}" data-id="${esc(b.id)}"${opts.edit && !b.show ? ' style="opacity:.25"' : ''}>${renderBlock(b, c)}</div>`
    ).join('');

    return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(c.title)} ${esc(t.sn || '')}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,Arial,sans-serif;font-size:13px;color:#18181b;background:#fff;padding:0;max-width:680px;margin:0 auto;-webkit-text-size-adjust:100%}
#inv-content{padding:20px 28px}
#inv-content>.blk{margin-bottom:14px}
.inv-hdr{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:2px solid ${c.accent}}
.co-name{font-size:17px;font-weight:800;color:${c.accent};margin-bottom:4px}
.co-info{font-size:11px;color:#71717a;line-height:1.7}
.inv-title h1{font-size:24px;font-weight:800;letter-spacing:.5px;text-align:right}
.inv-title .inv-no{font-size:11px;color:#71717a;text-align:right;margin-top:6px;font-family:monospace}
.inv-title .inv-date{font-size:11px;color:#71717a;text-align:right;margin-top:2px}
.meta-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;padding:10px 12px;background:#f9f9f9;border-radius:6px;border:1px solid #e4e4e7}
.meta-item .lbl{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:#a1a1aa}
.meta-item .val{font-size:12px;font-weight:600;margin-top:2px}
table{width:100%;border-collapse:collapse}
thead th{background:#18181b;color:#fff;padding:7px 10px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;text-align:left}
thead th.r{text-align:right}
tbody tr{border-bottom:1px solid #f0f0f0}
tbody tr:nth-child(even){background:#fafafa}
tbody td{padding:7px 10px;font-size:12px}
tbody td.r{text-align:right;font-family:monospace}
.totals-wrap{display:flex;justify-content:flex-end}
.totals{width:280px}
.trow{display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid #f0f0f0}
.trow .lbl{color:#71717a}.trow .val{font-family:monospace}
.trow.tot{border-top:2px solid #18181b;border-bottom:none;margin-top:6px;padding-top:8px;font-size:15px;font-weight:700}
.trow.tot .lbl{color:#18181b}
.pay-section{padding:11px;background:#f9f9f9;border-radius:6px;border:1px solid #e4e4e7}
.pay-lbl{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#a1a1aa;margin-bottom:7px}
.pill{display:inline-flex;align-items:center;gap:4px;background:#fff;border:1px solid #e4e4e7;border-radius:20px;padding:3px 12px;font-size:12px;font-weight:600;margin-right:6px}
.reg-note{font-size:10px;color:#71717a;padding:8px;border:1px dashed #e4e4e7;border-radius:4px;margin-bottom:12px}
.footer-note{text-align:center;font-size:11px;color:#a1a1aa;padding-top:12px;border-top:1px solid #e4e4e7}
.footer-note:not(:last-child){margin-bottom:12px}
@media print{#inv-content{padding:12px}.dl-bar{display:none!important}}
.dl-bar{display:flex;gap:8px;justify-content:flex-end;align-items:center;padding:10px 16px;background:#f4f4f5;border-bottom:1px solid #e4e4e7;flex-wrap:wrap}
${opts.edit ? '' : MOBILE_CSS}
</style></head><body>
${opts.edit ? '' : `<div class="dl-bar">
  <span style="flex:1;font-size:11px;color:#71717a;font-family:monospace">${esc(t.sn || '')}</span>
  <button id="dlBtn" onclick="downloadPdf()" style="background:${c.accent};color:#fff;border:none;border-radius:6px;padding:7px 16px;font-size:13px;font-weight:700;cursor:pointer">⬇ Download PDF</button>
  <button onclick="window.print()" style="background:#fff;border:1px solid #d4d4d8;border-radius:6px;padding:7px 13px;font-size:12px;cursor:pointer;color:#52525b">🖨 Print</button>
</div>`}
<div id="inv-content">
${body}
</div>
${opts.edit ? editScript(c.accent, c.vars) : `<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"><\/script>
<script>
function downloadPdf(){
  var b=document.getElementById('dlBtn');
  b.disabled=true;b.textContent='Generating…';
  var done=function(){document.body.classList.remove('pdfing');b.disabled=false;b.textContent='⬇ Download PDF'};
  var sn=${JSON.stringify(t.sn || 'invoice')};
  var filename=${JSON.stringify((c.title || 'INVOICE').replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-+|-+$/g, '').toUpperCase())}+'-'+sn.replace(/[^a-zA-Z0-9]/g,'-')+'.pdf';
  document.body.classList.add('pdfing');
  html2pdf().set({
    margin:[10,10,10,10],
    filename:filename,
    image:{type:'jpeg',quality:0.98},
    html2canvas:{scale:2,useCORS:true,windowWidth:720},
    jsPDF:{unit:'mm',format:'a4',orientation:'portrait'}
  }).from(document.getElementById('inv-content')).save().then(done,done);
}
<\/script>`}
${!opts.edit && opts.autoprint ? `<script>window.onload=function(){window.print()}<\/script>` : ''}
</body></html>`;
  }

  return {build, defaultBlocks, normalizeBlocks, BLOCK_NAMES, PLACEHOLDERS, BLOCK_ELEMENTS,
          BLOCK_FIELDS, FIELD_GROUPS, fieldOrder, fieldGroup, EXTRA_DATA, EXTRA_GROUP, extras, extraKey, extraLabel};
})();
