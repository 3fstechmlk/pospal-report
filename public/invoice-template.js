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
  const BLOCK_TYPES = ['header', 'meta', 'items', 'totals', 'payment', 'footer', 'text', 'divider', 'spacer'];
  const BLOCK_NAMES = {header: 'Header', meta: 'Info Fields', items: 'Items Table', totals: 'Totals',
                       payment: 'Payment Method', footer: 'Footer', text: 'Text', divider: 'Divider', spacer: 'Spacer'};

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
    return {t, s, el: s.el || {}, edit: !!opts.edit, member, remark, posRemark, dateStr, tp,
            tax, svc, rnd, disc, net, gross, accent, title, merch, addrParts, vars, PM: opts.PM || {}};
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
    return `<${tag} data-el="${key}"${cls}${st ? ` style="${st}"` : ''}${ed}>${html}</${tag}>`;
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
    const invNo   = E(c, 'inv_no',   'Invoice No',   'No: {invoice_no}',   null, {tag: 'div', cls: 'inv-no'});
    const invDate = E(c, 'inv_date', 'Invoice Date', 'Date: {date} · {time}', null, {tag: 'div', cls: 'inv-date'});
    if (o.layout === 'center') {
      return `<div style="text-align:center;margin-bottom:4px;padding-bottom:14px;border-bottom:2px solid ${c.accent}">
        ${E(c, 'co_name', 'Company Name', '{company_name}', null, {tag: 'div', cls: 'co-name', style: 'font-size:18px;'})}
        ${E(c, 'co_info', 'Company Details', infoText, infoHtml, {tag: 'div', cls: 'co-info'})}
        ${(regsText || c.el.co_regs) ? E(c, 'co_regs', 'Registration Nos', regsText, regsHtml, {tag: 'div', style: 'margin-top:4px;font-size:10px;color:#52525b;display:flex;gap:16px;flex-wrap:wrap;justify-content:center;'}) : ''}
        ${E(c, 'title', 'Document Title', c.title, null, {tag: 'h1', style: 'font-size:22px;font-weight:800;letter-spacing:.5px;margin-top:12px;'})}
        <div style="font-size:11px;color:#71717a;margin-top:4px;font-family:monospace">${E(c, 'inv_no', 'Invoice No', 'No: {invoice_no}')} · ${E(c, 'inv_date', 'Invoice Date', 'Date: {date} · {time}')}</div>
      </div>`;
    }
    return `<div class="inv-hdr">
      <div>
        ${E(c, 'co_name', 'Company Name', '{company_name}', null, {tag: 'div', cls: 'co-name'})}
        ${E(c, 'co_info', 'Company Details', infoText, infoHtml, {tag: 'div', cls: 'co-info'})}
        ${(regsText || c.el.co_regs) ? E(c, 'co_regs', 'Registration Nos', regsText, regsHtml, {tag: 'div', style: 'margin-top:8px;font-size:10px;color:#52525b;display:flex;gap:16px;flex-wrap:wrap;'}) : ''}
      </div>
      <div class="inv-title">
        ${E(c, 'title', 'Document Title', c.title, null, {tag: 'h1'})}
        ${invNo}
        ${invDate}
      </div>
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
    return rows;
  }

  function renderMeta(o, c) {
    const rows = metaRows(o, c);
    if (!rows.length) return '';
    const lblE = r => E(c, 'lbl_' + r.key, r.lbl + ' · Label', r.lbl, null,
      {tag: 'div', cls: 'lbl', style: r.accent ? `color:${c.accent};` : ''});
    const valE = (r, extra) => E(c, 'val_' + r.key, r.lbl + ' · Value', '', esc(r.val),
      {tag: 'div', cls: 'val', text: false, style: extra || ''});
    if (o.style === 'lines') {
      return `<div style="font-size:12px;line-height:2">${rows.map(r =>
        `<div style="display:flex;gap:6px;align-items:baseline">${E(c, 'lbl_' + r.key, r.lbl + ' · Label', r.lbl, null, {style: 'color:#71717a;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;'})}${E(c, 'val_' + r.key, r.lbl + ' · Value', '', esc(r.val), {text: false, style: 'font-weight:700;'})}</div>`).join('')}</div>`;
    }
    return `<div class="meta-grid">${rows.map(r =>
      `<div class="meta-item"${r.accent ? ` style="border-left:2px solid ${c.accent};padding-left:10px"` : ''}>${lblE(r)}${valE(r)}</div>`).join('')}</div>`;
  }

  function renderItems(o, c) {
    const off = k => (c.el[k] || {}).show === false;
    const showQty = !off('th_qty'), showPrice = !off('th_price'), showAmt = !off('th_amount');
    const showDisc = o.discount !== false && !off('th_disc');
    const showItemRmk = !off('item_remark');
    const irows = (c.t.items || []).map(i => {
      const act = r2(i.totalAmount || 0);
      const dis = r2(r2((i.sellPrice || 0) * (i.quantity || 0)) - act);
      const rmk = showItemRmk ? (i.remark || '').trim() : '';
      const desc = esc(i.name || '—') +
        (rmk ? `<div style="font-size:9.5px;color:#a16207;margin-top:1px">${esc(rmk)}</div>` : '');
      return `<tr><td>${desc}</td>${showQty ? `<td class="r">${i.quantity}</td>` : ''}${showPrice ? `<td class="r">${fm(i.sellPrice || 0)}</td>` : ''}${showAmt ? `<td class="r">${fm(act)}</td>` : ''}${showDisc ? `<td class="r" style="color:${dis > 0.005 ? '#dc2626' : '#a1a1aa'}">${dis > 0.005 ? fm(dis) : '—'}</td>` : ''}</tr>`;
    }).join('');
    return `<table>
      <thead><tr>${E(c, 'th_desc', 'Column · Description', 'Description', null, {tag: 'th'})}${showQty ? E(c, 'th_qty', 'Column · Qty', 'Qty', null, {tag: 'th', cls: 'r', style: 'width:44px;'}) : ''}${showPrice ? E(c, 'th_price', 'Column · Unit Price', 'Unit Price', null, {tag: 'th', cls: 'r', style: 'width:88px;'}) : ''}${showAmt ? E(c, 'th_amount', 'Column · Amount', 'Amount', null, {tag: 'th', cls: 'r', style: 'width:88px;'}) : ''}${showDisc ? E(c, 'th_disc', 'Column · Discount', 'Discount', null, {tag: 'th', cls: 'r', style: 'width:76px;'}) : ''}</tr></thead>
      ${E(c, 'items_rows', 'Item Rows', '', irows, {tag: 'tbody', text: false})}
    </table>`;
  }

  function renderTotals(o, c) {
    const off = k => (c.el[k] || {}).show === false;
    const lbl = (key, name, def) => E(c, key, name + ' · Label', def, null, {cls: 'lbl'});
    const val = (key, name, html, extra) => E(c, key, name + ' · Value', '', html, {cls: 'val', text: false, style: extra || ''});
    return `<div class="totals-wrap"><div class="totals">
      ${o.subtotal !== false && !off('tot_subtotal_lbl') ? `<div class="trow" style="border-bottom:1px dashed #d4d4d8;padding-bottom:8px;margin-bottom:4px">${E(c, 'tot_subtotal_lbl', 'Subtotal · Label', 'Subtotal', null, {cls: 'lbl', style: 'font-weight:600;color:#52525b;'})}${val('tot_subtotal_val', 'Subtotal', 'RM ' + fm(c.gross))}</div>` : ''}
      ${c.disc > 0.005 && !off('tot_discount_lbl') ? `<div class="trow">${lbl('tot_discount_lbl', 'Discount', 'Discount')}${val('tot_discount_val', 'Discount', '−RM ' + fm(c.disc), 'color:#dc2626;')}</div>` : ''}
      ${c.svc > 0.001 && !off('tot_service_lbl') ? `<div class="trow">${lbl('tot_service_lbl', 'Service Charge', 'Service Charge')}${val('tot_service_val', 'Service Charge', 'RM ' + fm(c.svc))}</div>` : ''}
      ${Math.abs(c.rnd) > 0.001 && !off('tot_rounding_lbl') ? `<div class="trow">${lbl('tot_rounding_lbl', 'Rounding', 'Rounding')}${val('tot_rounding_val', 'Rounding', c.rnd > 0 ? '(' + fm(c.rnd) + ')' : '+' + fm(Math.abs(c.rnd)))}</div>` : ''}
      ${c.tax > 0.001 && !off('tot_tax_lbl') ? `<div class="trow tax">${lbl('tot_tax_lbl', 'Service Tax', 'Service Tax (SST)')}${val('tot_tax_val', 'Service Tax', 'RM ' + fm(c.tax), 'color:#0369a1;')}</div>` : ''}
      ${!off('tot_total_lbl') ? `<div class="trow tot">${E(c, 'tot_total_lbl', 'Total · Label', 'TOTAL')}${val('tot_total_val', 'Total', 'RM ' + fm(c.net), `color:${c.accent};`)}</div>` : ''}
    </div></div>`;
  }

  function renderPayment(o, c) {
    const pills = (c.t.payments || []).map(p => `<span class="pill">${esc(c.PM[p.code] || p.code)} · RM ${fm(p.amount || 0)}</span>`).join('');
    return `<div class="pay-section">
      ${E(c, 'pay_lbl', 'Payment · Label', 'Payment Method', null, {tag: 'div', cls: 'pay-lbl'})}
      ${E(c, 'pay_items', 'Payment · Values', '', pills, {tag: 'div', text: false})}
    </div>`;
  }

  function renderFooter(o, c) {
    const s = c.s;
    const regDef = 'This is a tax invoice issued by {company_name}. SST Registration No: {sst}';
    return `${(s.sst || (c.el.reg_note || {}).text) ? E(c, 'reg_note', 'Tax Note', regDef, null, {tag: 'div', cls: 'reg-note'}) : ''}
      ${(c.posRemark && (c.el.pos_remark || {}).show !== false) ? `<div style="margin-bottom:12px;padding:10px 12px;background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;font-size:12px;color:#78350f"><span style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:#b45309;display:block;margin-bottom:4px">Transaction Remark</span>${esc(c.posRemark)}</div>` : ''}
      ${c.remark ? `<div style="margin-bottom:12px;padding:10px 12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;color:#334155"><span style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:#64748b;display:block;margin-bottom:4px">Additional Remark</span>${esc(c.remark)}</div>` : ''}
      ${E(c, 'footer_text', 'Footer Text', s.footer || 'Thank you for your purchase!', null, {tag: 'div', cls: 'footer-note'})}`;
  }

  function renderText(o, c) {
    const sz = {sm: '11px', md: '13px', lg: '18px'}[o.size || 'md'] || '13px';
    const st = `font-size:${sz};text-align:${o.align || 'left'};` +
      `${o.bold ? 'font-weight:700;' : ''}${o.italic ? 'font-style:italic;' : ''}` +
      `color:${o.muted ? '#71717a' : '#18181b'};line-height:1.7`;
    return `<div style="${st}">${subst(o.text, c.vars)}</div>`;
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
  // Press on blank space (not an element, not the handle) → deselect + close
  // popover. mousedown, not click: a blur of the previously edited element can
  // reflow the page between mousedown and mouseup, which suppresses click.
  document.addEventListener('mousedown',function(ev){
    if(ev.button!==0||ev.target===rsz)return;
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

  return {build, defaultBlocks, normalizeBlocks, BLOCK_NAMES, PLACEHOLDERS, BLOCK_ELEMENTS};
})();
