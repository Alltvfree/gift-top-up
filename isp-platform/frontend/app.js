'use strict';
/* IslandNet operations UI. No inline handlers (strict CSP): clicks/submits go through data-act / data-form. */
const $ = s => document.querySelector(s);
const ESC = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
const esc = v => (v === null || v === undefined || v === '') ? '—' : String(v).replace(/[&<>"']/g, c => ESC[c]);
const val = v => (v === null || v === undefined) ? '' : String(v).replace(/[&<>"']/g, c => ESC[c]);
let ME = null;
const cache = {};

// ---------------------------------------------------------------- API
async function api(path, method = 'GET', body) {
  const r = await fetch(path, {
    method, credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'islandnet'},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = (r.headers.get('content-type') || '').includes('json') ? await r.json() : null;
  if (r.status === 401 && !path.startsWith('/api/auth/login')) { showLogin(); throw new Error('Session expired, sign in again'); }
  if (r.status === 403 && data && /Two-factor authentication must be set up/.test(data.detail)) { start(); throw new Error(data.detail); }
  if (!r.ok) {
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map(x => `${(x.loc || []).slice(-1)[0]}: ${x.msg}`).join('; ');
    throw new Error(d || `HTTP ${r.status}`);
  }
  return data;
}
const can = p => ME && ME.permissions.includes(p);

// ---------------------------------------------------------------- formatting
const tag = s => s ? `<span class="tag s-${val(s)}">${esc(s)}</span>` : '—';
const dt = v => v ? esc(new Date(v).toLocaleString()) : '—';
const ago = v => {
  if (!v) return '—';
  const s = (Date.now() - new Date(v)) / 1000;
  return esc(s < 90 ? `${Math.round(s)}s ago` : s < 5400 ? `${Math.round(s / 60)}m ago` : s < 172800 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`);
};
const bytes = n => { if (n == null) return '—'; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; n = Number(n); while (n >= 1024 && i < 4) { n /= 1024; i++; } return `${n.toFixed(1)} ${u[i]}`; };
const mvr = n => n == null ? '—' : `MVR ${Number(n).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
const dbm = n => n == null ? '—' : `<span class="${n < -27 ? 's-critical' : n < -25 ? 's-warning' : 's-ok'}">${esc(n)} dBm</span>`;

function table(rows, cols, opts = {}) {
  const head = cols.map(c => `<th>${esc(c[1])}</th>`).join('');
  if (!rows || !rows.length) return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody><tr><td colspan="${cols.length}" class="empty">${esc(opts.empty || 'Nothing here yet.')}</td></tr></tbody></table></div>`;
  const body = rows.map(r => {
    const attrs = opts.href ? ` class="click" data-act="go" data-href="${val(opts.href(r))}"` : '';
    return `<tr${attrs}>${cols.map(c => `<td>${c[2] ? c[2](r[c[0]], r) : esc(r[c[0]])}</td>`).join('')}</tr>`;
  }).join('');
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function panel(title, inner, right = '', sub = '') {
  return `<section class="panel"><div class="panel-head"><div><h2>${esc(title)}</h2>${sub ? `<div class="muted">${esc(sub)}</div>` : ''}</div><div class="actions">${right}</div></div>${inner}</section>`;
}
const btn = (label, act, data = {}, cls = '') =>
  `<button class="btn small ${cls}" data-act="${act}" ${Object.entries(data).map(([k, v]) => `data-${k}="${val(v)}"`).join(' ')}>${esc(label)}</button>`;

// fields: [name, label, type, extra]  type: text|number|password|select|check|textarea|list|json|date
function fields(defs, values = {}) {
  return defs.map(([name, label, type = 'text', x = {}]) => {
    const v = values[name];
    const req = x.required ? ' required' : '';
    const ph = x.placeholder ? ` placeholder="${val(x.placeholder)}"` : '';
    if (type === 'select') {
      const opts = (x.options || []).map(([ov, ol]) => `<option value="${val(ov)}"${String(ov) === String(v ?? x.default ?? '') ? ' selected' : ''}>${esc(ol)}</option>`).join('');
      return `<label>${esc(label)}<select name="${name}" data-type="select"${req}>${opts}</select></label>`;
    }
    if (type === 'check') return `<label class="check"><input type="checkbox" name="${name}" data-type="check"${(v ?? x.default) ? ' checked' : ''}> ${esc(label)}</label>`;
    if (type === 'textarea' || type === 'json' || type === 'list') {
      const text = type === 'json' ? JSON.stringify(v ?? x.default ?? {}, null, 1) : type === 'list' ? (v || x.default || []).join('\n') : (v ?? '');
      return `<label class="full">${esc(label)}<textarea name="${name}" data-type="${type}"${ph}${req}>${val(text)}</textarea></label>`;
    }
    return `<label>${esc(label)}<input name="${name}" type="${type}" data-type="${type}" value="${val(v ?? x.default ?? '')}"${ph}${req}${x.step ? ` step="${x.step}"` : ''}></label>`;
  }).join('');
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    const t = el.dataset.type;
    if (t === 'check') out[el.name] = el.checked;
    else if (t === 'number') out[el.name] = el.value === '' ? null : Number(el.value);
    else if (t === 'list') out[el.name] = el.value.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
    else if (t === 'json') { try { out[el.name] = el.value.trim() ? JSON.parse(el.value) : {}; } catch { throw new Error(`${el.name}: invalid JSON`); } }
    else out[el.name] = el.value.trim() === '' ? null : el.value.trim();
  }
  return out;
}
const form = (name, inner, submit = 'Save', data = {}) =>
  `<form class="grid-form" data-form="${name}" ${Object.entries(data).map(([k, v]) => `data-${k}="${val(v)}"`).join(' ')}>${inner}<div class="full actions"><button class="btn primary" type="submit">${esc(submit)}</button></div></form>`;

function modal(html) { $('#modal-content').innerHTML = html; $('#modal').classList.remove('hidden'); }
function closeModal() { $('#modal').classList.add('hidden'); $('#modal-content').innerHTML = ''; }
let toastTimer;
function toast(msg, err = false) {
  const t = $('#toast'); t.textContent = msg; t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add('hidden'), err ? 8000 : 4000);
}

async function options(kind) {
  if (kind === 'islands') return (cache.islands = await api('/api/islands')).map(i => [i.id, `${i.name} (${i.code})`]);
  if (kind === 'devices') return (cache.devices = await api('/api/devices')).map(d => [d.id, `${d.name}${d.island_name ? ' · ' + d.island_name : ''}`]);
  if (kind === 'plans') return (await api('/api/plans')).filter(p => p.active).map(p => [p.id, `${p.name} · ${p.download_mbps}/${p.upload_mbps} Mbps · MVR ${p.monthly_price_mvr}`]);
  return [];
}
const none = label => [['', label]];

// ---------------------------------------------------------------- pages
const PAGES = {
  dashboard: {title: 'Network control center', group: 'OVERVIEW', nav: '▦ Dashboard', perm: 'read', async render() {
    const [s, islands, alerts] = await Promise.all([api('/api/summary'), api('/api/islands'), api('/api/alerts')]);
    const card = (l, v, n) => `<div class="card"><div class="label">${esc(l)}</div><div class="value">${v}</div><div class="note">${n}</div></div>`;
    return `<div class="cards">
      ${card('Islands online', `${s.islands.online}/${s.islands.total}`, `${esc(s.islands.degraded)} degraded · <span class="s-offline">${esc(s.islands.offline)} offline</span>`)}
      ${card('Devices online', `${s.devices.online}/${s.devices.total}`, `${esc(s.devices.offline)} offline`)}
      ${card('Active subscribers', esc(s.subscribers.active), `${esc(s.subscribers.suspended)} suspended · ${esc(s.subscribers.pending)} pending`)}
      ${card('PPPoE sessions', esc(s.online_sessions), `${esc(s.auth_rejects_1h)} auth rejects in last hour`)}
      ${card('Open alerts', `<span class="s-critical">${esc(s.alerts.critical)}</span> / <span class="s-warning">${esc(s.alerts.warning)}</span>`, 'critical / warning')}
      ${card('Receivable', esc(mvr(s.receivable_mvr)), 'unpaid + overdue invoices')}
      ${card('Pending changes', esc(s.pending_changes), 'awaiting approval')}
      ${card('Islands', esc(s.islands.total), 'in inventory')}
    </div>
    <div class="grid2">
      ${panel('Islands', islands.length ? `<div class="island-grid">${islands.map(i => `<div class="island ${val(i.status)}" data-act="go" data-href="#/devices?island=${val(i.id)}"><b>${esc(i.name)}</b>${tag(i.status)} <span class="muted">${esc(i.active_subscribers)} subs${i.open_alerts ? ` · ${esc(i.open_alerts)} alerts` : ''}</span></div>`).join('')}</div>` : '<div class="empty">Add islands under Island network.</div>', '', 'status rolls up from each island\'s devices')}
      ${panel('Open alerts', table(alerts.slice(0, 15), [['severity', 'Sev', tag], ['device_name', 'Device'], ['message', 'Alert'], ['opened_at', 'Since', ago]], {empty: 'No open alerts'}), `<button class="btn small" data-act="go" data-href="#/alerts">All</button>`)}
    </div>`;
  }},

  islands: {title: 'Island network', group: 'OVERVIEW', nav: '⌖ Island network', perm: 'read', async render() {
    const rows = await api('/api/islands');
    return panel(`Islands (${rows.length})`, table(rows, [['code', 'Code'], ['name', 'Name'], ['atoll', 'Atoll'], ['status', 'Status', tag],
      ['device_count', 'Devices'], ['active_subscribers', 'Active subs'], ['open_alerts', 'Alerts'],
      ['id', '', (id, r) => can('network') ? btn('Edit', 'island-edit', {id}) : '']]), can('network') ? btn('Add island', 'island-edit', {}, 'primary') : '');
  }},

  alerts: {title: 'Alerts', group: 'OVERVIEW', nav: '⚠ Alerts', perm: 'read', async render(q) {
    const all = q.get('all') === '1';
    const rows = await api(`/api/alerts?open_only=${!all}`);
    return panel(all ? 'All alerts (latest 500)' : 'Open alerts', table(rows, [['severity', 'Sev', tag], ['island_name', 'Island'], ['device_name', 'Device'], ['kind', 'Kind'],
      ['message', 'Message'], ['opened_at', 'Opened', dt], ['resolved_at', 'Resolved', dt],
      ['acknowledged_by', 'Ack', (v, r) => v ? esc(v) : (!r.resolved_at && can('network') ? btn('Ack', 'alert-ack', {id: r.id}) : '—')]], {empty: 'No alerts'}),
      `<button class="btn small" data-act="go" data-href="${all ? '#/alerts' : '#/alerts?all=1'}">${all ? 'Open only' : 'Show history'}</button>`);
  }},

  subscribers: {title: 'Subscribers', group: 'CUSTOMERS', nav: '♙ Subscribers', perm: 'read', async render(q) {
    const params = new URLSearchParams();
    for (const k of ['q', 'status', 'island_id']) if (q.get(k)) params.set(k, q.get(k));
    const [rows, islands] = await Promise.all([api('/api/subscribers?' + params), options('islands')]);
    const filters = `<form class="grid-form" data-form="sub-filter">${fields([['q', 'Search name / account / username / phone', 'text'],
      ['status', 'Status', 'select', {options: [['', 'Any'], ['active', 'Active'], ['suspended', 'Suspended'], ['pending', 'Pending'], ['cancelled', 'Cancelled']]}],
      ['island_id', 'Island', 'select', {options: none('Any island').concat(islands)}]], Object.fromEntries(q))}<div class="actions end"><button class="btn" type="submit">Filter</button></div></form>`;
    return panel('Find', filters) + panel(`Subscribers (${rows.length})`, table(rows, [['account_number', 'Account'], ['full_name', 'Name'], ['island_name', 'Island'],
      ['plan_name', 'Plan'], ['pppoe_username', 'PPPoE user'], ['online', 'Online', v => v ? '<span class="s-online">●</span>' : '<span class="muted">○</span>'],
      ['status', 'Status', tag], ['balance_mvr', 'Balance', v => Number(v) > 0 ? `<span class="s-overdue">${esc(mvr(v))}</span>` : esc(mvr(v))]],
      {href: r => `#/subscriber/${r.id}`}), can('subscribers') ? btn('New subscriber', 'sub-edit', {}, 'primary') : '');
  }},

  subscriber: {title: 'Subscriber', hidden: true, perm: 'read', async render(q, id) {
    const s = await api(`/api/subscribers/${id}`);
    const acts = can('subscribers') ? [
      s.status !== 'active' && s.status !== 'cancelled' ? btn('Activate', 'sub-status', {id, status: 'active'}, 'primary') : '',
      s.status === 'active' ? btn('Suspend', 'sub-status', {id, status: 'suspended'}, 'danger') : '',
      s.status !== 'cancelled' ? btn('Cancel service', 'sub-status', {id, status: 'cancelled'}, 'danger') : '',
      btn('Edit', 'sub-edit', {id}), btn('Reset PPPoE password', 'sub-reset', {id}), btn('Disconnect session', 'sub-disconnect', {id}),
    ].join('') : '';
    const billingActs = can('billing') ? btn('Record payment', 'pay', {id, name: s.full_name}, 'primary') : '';
    const ontActs = can('network') ? btn('Provision ONT', 'ont-provision', {sub: id}) : '';
    return panel(`${s.full_name} · ${s.account_number}`, `
      <div class="cards">
        <div class="card"><div class="label">Status</div><div class="value">${tag(s.status)}</div><div class="note">${esc(s.suspended_reason || '')}</div></div>
        <div class="card"><div class="label">PPPoE username</div><div class="value v-md">${esc(s.pppoe_username)}</div><div class="note">RADIUS group: ${esc(s.radius_group.map(g => g.groupname).join(', '))}</div></div>
        <div class="card"><div class="label">Contact</div><div class="value v-sm">${esc(s.phone)}</div><div class="note">${esc(s.address)}</div></div>
        <div class="card"><div class="label">Static IP</div><div class="value v-md">${esc(s.static_ip)}</div><div class="note">created ${dt(s.created_at)}</div></div>
      </div>`, acts) +
      panel('Sessions', table(s.sessions, [['acctstarttime', 'Start', dt], ['acctstoptime', 'Stop', v => v ? dt(v) : '<span class="s-online">online</span>'], ['ip', 'IP'], ['mac', 'MAC / ONT'],
        ['nas', 'NAS'], ['acctinputoctets', 'Up', bytes], ['acctoutputoctets', 'Down', bytes], ['acctterminatecause', 'Cause']], {empty: 'No sessions yet'})) +
      `<div class="grid2">${panel('Invoices', table(s.invoices, [['invoice_number', 'Invoice'], ['period_start', 'Period'], ['amount_mvr', 'Amount', mvr], ['paid_mvr', 'Paid', mvr], ['due_at', 'Due'], ['status', 'Status', tag]]), billingActs)}
       ${panel('Login attempts', table(s.auth_log, [['authdate', 'When', dt], ['reply', 'Result', v => v === 'Access-Accept' ? '<span class="s-ok">accept</span>' : `<span class="s-critical">${esc(v)}</span>`], ['callingstationid', 'From']], {empty: 'No RADIUS attempts'}))}</div>` +
      panel('ONT', table(s.onts, [['serial', 'Serial'], ['frame', 'F/S/P:ID', (v, r) => esc(`${r.frame}/${r.slot}/${r.port}:${r.ont_id ?? '?'}`)], ['run_state', 'State', tag], ['rx_power_dbm', 'ONT Rx', dbm], ['olt_rx_power_dbm', 'OLT Rx', dbm], ['last_seen_at', 'Seen', ago]], {empty: 'No ONT linked'}), ontActs) +
      panel('Payments', table(s.payments, [['received_at', 'Date', dt], ['amount_mvr', 'Amount', mvr], ['method', 'Method'], ['reference', 'Reference'], ['recorded_by', 'By']]));
  }},

  plans: {title: 'Plans', group: 'CUSTOMERS', nav: '▤ Plans', perm: 'read', async render() {
    const rows = await api('/api/plans');
    return panel('Service plans', table(rows, [['name', 'Plan'], ['download_mbps', 'Down Mbps'], ['upload_mbps', 'Up Mbps'], ['monthly_price_mvr', 'Monthly', mvr],
      ['active_subscribers', 'Active subs'], ['active', 'Sellable', v => v ? 'yes' : 'no'], ['id', '', id => can('billing') ? btn('Edit', 'plan-edit', {id}) : '']]),
      can('billing') ? btn('Add plan', 'plan-edit', {}, 'primary') : '', 'speed is pushed to MikroTik as Mikrotik-Rate-Limit via RADIUS');
  }},

  billing: {title: 'Billing', group: 'CUSTOMERS', nav: '◫ Billing', perm: 'read', async render(q) {
    const status = q.get('status') || '';
    const [inv, pays] = await Promise.all([api('/api/invoices' + (status ? `?status=${encodeURIComponent(status)}` : '')), api('/api/payments')]);
    const filter = ['', 'unpaid', 'overdue', 'paid', 'void'].map(s => `<button class="btn small" data-act="go" data-href="#/billing${s ? '?status=' + s : ''}">${esc(s || 'all')}</button>`).join('');
    return panel('Invoices', table(inv, [['invoice_number', 'Invoice'], ['account_number', 'Account'], ['full_name', 'Name'], ['period_start', 'Period'], ['amount_mvr', 'Amount', mvr],
      ['paid_mvr', 'Paid', mvr], ['due_at', 'Due'], ['status', 'Status', tag],
      ['id', '', (id, r) => can('approve') && r.status !== 'void' && Number(r.paid_mvr) === 0 ? btn('Void', 'inv-void', {id}, 'danger') : '']], {href: r => `#/subscriber/${r.subscriber_id}`}),
      filter + (can('billing') ? btn('Run billing now', 'billing-run', {}, 'primary') : ''), 'Invoices are created on the 1st; unpaid ones go overdue after the due date and service is suspended after the grace period. Payment restores service automatically.') +
      panel('Recent payments', table(pays, [['received_at', 'Date', dt], ['account_number', 'Account'], ['full_name', 'Name'], ['amount_mvr', 'Amount', mvr], ['method', 'Method'], ['reference', 'Ref'], ['recorded_by', 'By']]));
  }},

  radius: {title: 'RADIUS', group: 'CUSTOMERS', nav: '◉ RADIUS', perm: 'read', async render() {
    const [sessions, rejects, nas] = await Promise.all([api('/api/radius/sessions'), api('/api/radius/auth-log?rejects_only=true'), can('network') ? api('/api/radius/nas') : []]);
    return panel(`Online PPPoE sessions (${sessions.length})`, table(sessions, [['username', 'User'], ['full_name', 'Name'], ['nas_name', 'NAS', (v, r) => esc(v || r.nas)], ['ip', 'IP'], ['mac', 'MAC'],
      ['acctstarttime', 'Since', ago], ['acctinputoctets', 'Up', bytes], ['acctoutputoctets', 'Down', bytes]], {empty: 'No sessions online'})) +
      `<div class="grid2">${panel('Recent rejects', table(rejects.slice(0, 50), [['authdate', 'When', dt], ['username', 'User'], ['callingstationid', 'From']], {empty: 'No rejects'}), '', 'wrong password, suspended/pending account, or duplicate session')}
      ${can('network') ? panel('NAS clients (island routers)', table(nas, [['shortname', 'Name'], ['nasname', 'IP'], ['description', 'Notes'], ['id', '', id => btn('Remove', 'nas-del', {id}, 'danger')]]), btn('Add NAS', 'nas-add', {}, 'primary'), 'restart the radius container after changes') : ''}</div>`;
  }},

  devices: {title: 'Devices', group: 'INFRASTRUCTURE', nav: '⌘ Devices', perm: 'read', async render(q) {
    let rows = await api('/api/devices');
    const role = q.get('role'), island = q.get('island');
    if (role) rows = rows.filter(r => r.role === role);
    if (island) rows = rows.filter(r => r.island_id === island);
    const roles = ['', 'core_router', 'island_router', 'olt', 'backhaul', 'radius', 'other'].map(r => `<button class="btn small" data-act="go" data-href="#/devices${r ? '?role=' + r : ''}">${esc(r || 'all')}</button>`).join('');
    return panel(`Devices (${rows.length})`, table(rows, [['name', 'Name'], ['island_name', 'Island'], ['vendor', 'Vendor'], ['role', 'Role'], ['management_ip', 'Mgmt IP'],
      ['model', 'Model'], ['software_version', 'Version'], ['status', 'Status', tag], ['last_seen_at', 'Seen', ago],
      ['last_poll_error', 'Last error', v => v ? `<span class="s-warning">${esc(String(v).slice(0, 60))}</span>` : '']], {href: r => `#/device/${r.id}`}),
      roles + (can('network') ? btn('Add device', 'device-edit', {}, 'primary') : ''));
  }},

  device: {title: 'Device', hidden: true, perm: 'read', async render(q, id) {
    const d = await api(`/api/devices/${id}`);
    const acts = can('network') ? [btn('Edit', 'device-edit', {id}), btn('Poll now', 'device-poll', {id}),
      d.vendor === 'mikrotik' ? btn('Security audit', 'device-audit', {id}, 'primary') : '',
      d.vendor === 'mikrotik' ? btn('Generate firewall', 'go', {href: `#/security?device=${id}`}) : '',
      d.vendor === 'huawei' && d.role === 'olt' ? btn('ONT autofind', 'olt-autofind', {id}, 'primary') : '',
      can('approve') ? btn('Delete', 'device-del', {id}, 'danger') : ''].join('') : '';
    const m = d.metrics[0] || {};
    return panel(`${d.name}`, `<div class="cards">
        <div class="card"><div class="label">Status</div><div class="value">${tag(d.status)}</div><div class="note">seen ${ago(d.last_seen_at)}</div></div>
        <div class="card"><div class="label">Latency / loss</div><div class="value v-lg">${esc(m.latency_ms)} ms</div><div class="note">${esc(m.packet_loss_pct)}% loss</div></div>
        <div class="card"><div class="label">CPU / memory</div><div class="value v-lg">${esc(m.cpu_load_pct)}%</div><div class="note">${esc(m.mem_used_pct)}% memory</div></div>
        <div class="card"><div class="label">Identity</div><div class="value v-sm">${esc(d.vendor)} · ${esc(d.role)}</div><div class="note">${esc(d.management_ip)} · ${esc(d.model)} ${esc(d.software_version)} · creds ${d.has_credentials ? 'stored' : 'missing'}</div></div>
      </div>${d.last_poll_error ? `<div class="error">Last poll: ${esc(d.last_poll_error)}</div>` : ''}${m.extra ? `<pre>${esc(JSON.stringify(m.extra, null, 1))}</pre>` : ''}`, acts) +
      panel('Recent polls', table(d.metrics.slice(0, 30), [['at', 'When', dt], ['reachable', 'Up', v => v ? '<span class="s-ok">yes</span>' : '<span class="s-critical">no</span>'],
        ['latency_ms', 'Latency ms'], ['packet_loss_pct', 'Loss %'], ['cpu_load_pct', 'CPU %'], ['mem_used_pct', 'Mem %'], ['extra', 'PPPoE', v => esc(v && v.pppoe_active)]], {empty: 'Not polled yet'})) +
      panel('Alerts', table(d.alerts, [['severity', 'Sev', tag], ['kind', 'Kind'], ['message', 'Message'], ['opened_at', 'Opened', dt], ['resolved_at', 'Resolved', dt]], {empty: 'No alerts'})) +
      `<div id="device-extra"></div>`;
  }},

  links: {title: 'Backhaul links', group: 'INFRASTRUCTURE', nav: '⇄ Backhaul links', perm: 'read', async render() {
    const rows = await api('/api/links');
    return panel('Fiber & airFiber links', table(rows, [['name', 'Link'], ['kind', 'Type'], ['a_name', 'Side A', (v, r) => esc(`${v || '—'} (${r.a_island || '—'})`)],
      ['b_name', 'Side B', (v, r) => esc(`${v || '—'} (${r.b_island || '—'})`)], ['capacity_mbps', 'Capacity Mbps'], ['status', 'Status', tag],
      ['id', '', id => can('network') ? btn('Remove', 'link-del', {id}, 'danger') : '']]), can('network') ? btn('Add link', 'link-add', {}, 'primary') : '', 'status follows the devices at both ends');
  }},

  olt: {title: 'Smart OLT', group: 'INFRASTRUCTURE', nav: '⌁ Smart OLT', perm: 'read', async render() {
    const [onts, devices] = await Promise.all([api('/api/olt/onts'), api('/api/devices')]);
    const olts = devices.filter(d => d.vendor === 'huawei' && d.role === 'olt');
    const autofind = can('network') ? olts.map(o => btn(`Autofind · ${o.name}`, 'olt-autofind', {id: o.id})).join('') : '';
    const low = onts.filter(o => o.rx_power_dbm != null && o.rx_power_dbm < -27).length;
    return panel(`ONTs (${onts.length}) · ${low} with weak signal`, table(onts, [['olt_name', 'OLT'], ['frame', 'F/S/P:ID', (v, r) => esc(`${r.frame}/${r.slot}/${r.port}:${r.ont_id ?? '?'}`)],
      ['serial', 'Serial'], ['account_number', 'Account', (v, r) => r.subscriber_id ? `<a href="#/subscriber/${val(r.subscriber_id)}">${esc(v)}</a> ${esc(r.full_name)}` : '<span class="muted">unlinked</span>'],
      ['run_state', 'State', tag], ['rx_power_dbm', 'ONT Rx', dbm], ['olt_rx_power_dbm', 'OLT Rx', dbm], ['last_seen_at', 'Seen', ago],
      ['id', '', id => can('network') ? btn('Reboot', 'ont-reboot', {id}) : '']], {empty: 'No ONTs yet. Add your Huawei OLT under Devices with settings {"gpon_slots":[1]}.'}),
      autofind, 'optical levels refresh every few polling cycles; below −27 dBm raises an alert');
  }},

  changes: {title: 'Config changes', group: 'INFRASTRUCTURE', nav: '⎇ Changes', perm: 'network', async render() {
    const rows = await api('/api/changes');
    return panel('Change requests', table(rows, [['id', '#'], ['title', 'Change'], ['device_name', 'Device'], ['kind', 'Type'], ['status', 'Status', tag],
      ['requested_by', 'Requested'], ['approved_by', 'Approved'], ['created_at', 'Created', dt]], {href: r => `#/change/${r.id}`, empty: 'No changes requested'}),
      btn('New manual change', 'change-new', {}, 'primary'), 'every write to a router or OLT is reviewed by a second admin and applied with a rollback');
  }},

  change: {title: 'Change', hidden: true, perm: 'network', async render(q, id) {
    const c = await api(`/api/changes/${id}`);
    const acts = [
      c.status === 'pending' && can('approve') ? btn('Approve', 'change-approve', {id}, 'primary') : '',
      ['pending', 'approved'].includes(c.status) && can('approve') ? btn('Reject', 'change-reject', {id}, 'danger') : '',
      c.status === 'approved' ? btn('Apply to device', 'change-apply', {id}, 'primary') : '',
    ].join('');
    return panel(`#${c.id} ${c.title}`, `<p class="muted">${esc(c.device_name)} · ${esc(c.kind)} · ${tag(c.status)} · requested by ${esc(c.requested_by)} ${dt(c.created_at)}${c.approved_by ? ` · reviewed by ${esc(c.approved_by)}` : ''}</p>
      ${c.kind === 'mikrotik_script' ? '<p class="muted">Apply saves a backup + export on the router and arms an auto-restore. If the platform cannot reach the router afterwards, the router restores the backup on its own.</p>' : ''}
      <h3>Plan</h3><pre>${esc(c.plan)}</pre>${c.rollback ? `<h3>Rollback</h3><pre>${esc(c.rollback)}</pre>` : ''}${c.result ? `<h3>Result</h3><pre>${esc(c.result)}</pre>` : ''}`, acts);
  }},

  security: {title: 'Security & firewall', group: 'INFRASTRUCTURE', nav: '⛨ Security', perm: 'network', async render(q) {
    const devs = (await api('/api/devices')).filter(d => d.vendor === 'mikrotik');
    const pre = q.get('device') || '';
    const d = devs.find(x => x.id === pre);
    const defs = [
      ['device_id', 'Create change for router (optional)', 'select', {options: none('— just show the script —').concat(devs.map(x => [x.id, `${x.name} · ${x.role}`]))}],
      ['role', 'Router role', 'select', {options: [['island_router', 'Island router (PPPoE NAS)'], ['core_router', 'Core router']], default: d && d.role === 'core_router' ? 'core_router' : 'island_router'}],
      ['routing_protocol', 'Routing between routers', 'select', {options: [['ospf', 'OSPF'], ['bgp', 'BGP'], ['none', 'Static']]}],
      ['mgmt_networks', 'Management networks (NOC/VPN), one per line', 'list', {placeholder: '10.255.0.0/24'}],
      ['nms_addresses', 'This platform\'s IP(s)', 'list', {placeholder: '10.255.0.10'}],
      ['uplink_interfaces', 'Uplink interface(s) — to core / internet', 'list', {placeholder: 'sfp1'}],
      ['customer_interfaces', 'Customer/OLT-facing interface(s) or VLANs', 'list', {placeholder: 'vlan100-olt'}],
      ['backhaul_interfaces', 'Backhaul interfaces to islands (core only)', 'list'],
      ['mgmt_interfaces', 'Out-of-band management ports', 'list'],
      ['customer_pools', 'Customer PPPoE pools (anti-spoofing)', 'list', {placeholder: '100.64.16.0/20'}],
      ['radius_servers', 'RADIUS server IP(s)', 'list'],
      ['portal_ip', 'Payment portal IP (suspended redirect)', 'text'],
      ['local_address', 'PPP local address (router side)', 'text'],
      ['radius_secret', 'RADIUS secret (island)', 'password'],
      ['radius_src_address', 'RADIUS source address', 'text'],
      ['radius_auth_port', 'RADIUS auth port (RADIUS_AUTH_PORT)', 'number', {default: 1812}],
      ['radius_acct_port', 'RADIUS accounting port (RADIUS_ACCT_PORT)', 'number', {default: 1813}],
      ['snmp_community', 'SNMP community (not public)', 'password'],
      ['pppoe_service_name', 'PPPoE service name', 'text', {default: 'isp'}],
      ['dns_cache', 'Router is DNS cache for customers', 'check', {default: true}],
      ['isolate_customers', 'Block customer-to-customer traffic', 'check', {default: true}],
      ['block_smtp_from_customers', 'Block outbound SMTP (spam bots)', 'check', {default: true}],
      ['customers_have_public_ip', 'Customers have public IPs (allow inbound)', 'check'],
    ];
    return panel('MikroTik firewall & hardening generator', `<p class="muted">Locks management to your NOC, disables plaintext services, drops spoofed and bogon traffic,
      blocklists brute-force and port-scan sources, protects ONTs from botnet scanning (telnet/TR-069), isolates customers, caps per-customer connections,
      redirects suspended customers to the payment page and configures PPPoE + RADIUS with CoA. Run <b>Security audit</b> on a device to check a live router.</p>` +
      form('firewall', fields(defs, {device_id: pre}), 'Generate') + '<div id="fw-out"></div>');
  }},

  users: {title: 'Users', group: 'ADMIN', nav: '⚇ Users', perm: 'users', async render() {
    const rows = await api('/api/users');
    return panel('Platform users', table(rows, [['username', 'User'], ['full_name', 'Name'], ['role', 'Role'], ['active', 'Active', v => v ? 'yes' : '<span class="s-offline">disabled</span>'],
      ['totp_enabled', '2FA', (v, r) => v ? '<span class="s-ok">on</span>' : (r.role === 'admin' ? '<span class="s-warning">not set up</span>' : '<span class="muted">off</span>')],
      ['last_login_at', 'Last login', dt], ['locked_until', 'Locked until', dt],
      ['id', '', (id, r) => [btn('Reset password', 'user-pw', {id}), r.totp_enabled && id !== ME.id ? btn('Reset 2FA', 'user-mfa-reset', {id, name: r.username}, 'danger') : '', btn(r.active ? 'Disable' : 'Enable', 'user-active', {id, active: r.active ? '' : '1'}, r.active ? 'danger' : ''),
        `<select data-act-change="user-role" data-id="${val(id)}">${['admin', 'noc', 'billing', 'support'].map(x => `<option${x === r.role ? ' selected' : ''}>${x}</option>`).join('')}</select>`].join(' ')]]),
      btn('Add user', 'user-add', {}, 'primary'), 'admin: everything (two-factor required) · noc: network + subscribers · billing: plans, invoices, payments · support: read only');
  }},

  audit: {title: 'Audit log', group: 'ADMIN', nav: '☰ Audit log', perm: 'approve', async render() {
    const rows = await api('/api/audit');
    return panel('Who did what', table(rows, [['created_at', 'When', dt], ['actor', 'User'], ['action', 'Action'], ['target_type', 'Target'], ['detail', 'Detail', v => `<code>${esc(JSON.stringify(v)).slice(0, 300)}</code>`]]));
  }},

  account: {title: 'My account', group: 'ADMIN', nav: '⚙ My account', perm: 'read', async render() {
    const codeField = [['code', 'Current 6-digit code', 'text', {required: true}]];
    const mfa = !ME.totp_enabled ? mfaSetupPanel('Optional for your role, but strongly recommended.') :
      panel('Two-factor sign-in', `<p>Status: <span class="s-ok">on</span></p>
        <h3>New recovery codes</h3><p class="muted">Replaces all old codes. Do this if you used several or think they leaked.</p>` +
        form('mfa-regen', fields(codeField), 'Generate new codes') +
        (ME.mfa_required_for_role
          ? `<p class="muted">Two-factor is required for the ${esc(ME.role)} role. Lost your phone? Sign in with a recovery code, or ask another admin to reset your two-factor.</p>`
          : '<h3>Turn off</h3>' + form('mfa-disable', fields([['password', 'Password', 'password', {required: true}], ...codeField]), 'Turn off two-factor')));
    return mfa + panel('Change password', form('my-password', fields([['current_password', 'Current password', 'password', {required: true}], ['new_password', 'New password (12+, upper/lower/digit)', 'password', {required: true}]]), 'Change password'));
  }},
};

// ---------------------------------------------------------------- two-factor
let lastRecoveryCodes = [];
function mfaSetupPanel(intro) {
  return panel('Set up two-factor sign-in', `<p class="muted">${esc(intro)}</p>
    <ol class="steps"><li>Install an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy, 1Password…).</li>
    <li>Press <b>Start</b> and scan the QR code with the app.</li><li>Type the 6-digit code the app shows.</li></ol>
    <div id="mfa-setup">${btn('Start', 'mfa-start', {}, 'primary')}</div>`);
}
function showRecoveryCodes(codes, finishAct) {
  lastRecoveryCodes = codes;
  modal(`<h2>Save your recovery codes</h2><p>If you lose your phone, each code signs you in <b>once</b>. Keep them in a password manager or print them.
    They will not be shown again.</p><pre id="recovery-codes">${esc(codes.join('\n'))}</pre>
    <div class="actions">${btn('Copy', 'copy', {target: 'recovery-codes'})}${btn('Download .txt', 'mfa-download')}${btn("I've saved them", finishAct, {}, 'primary')}</div>`);
}

// ---------------------------------------------------------------- actions
const reload = () => route();
const confirmAct = msg => window.confirm(msg);
const ACTIONS = {
  go: d => { closeModal(); location.hash = d.href; },

  async 'mfa-start'() {
    const r = await api('/api/auth/mfa/setup', 'POST');
    const qr = qrcode(0, 'M'); qr.addData(r.uri); qr.make();
    $('#mfa-setup').innerHTML = `<img class="qr" alt="QR code for your authenticator app" src="${qr.createDataURL(5, 4)}">
      <p class="muted">Can't scan? Add an account in the app and type this key (time-based):</p>
      <div class="secret">${esc(r.secret.match(/.{1,4}/g).join(' '))}</div>` +
      form('mfa-enable', fields([['code', '6-digit code from the app', 'text', {required: true}]]), 'Turn on two-factor');
    const input = document.querySelector('form[data-form="mfa-enable"] input'); input.setAttribute('autocomplete', 'one-time-code'); input.focus();
  },
  'mfa-download'() {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([`IslandNet recovery codes for ${ME.username}\n\n${lastRecoveryCodes.join('\n')}\n`], {type: 'text/plain'}));
    a.download = `islandnet-recovery-codes-${ME.username}.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  },
  'mfa-finish'() { closeModal(); lastRecoveryCodes = []; start(); },
  async 'user-mfa-reset'(d) {
    if (!confirmAct(`Reset two-factor for ${d.name}? They are signed out and must set it up again at next sign-in.`)) return;
    await api(`/api/users/${d.id}`, 'PATCH', {reset_mfa: true}); toast('Two-factor reset'); reload();
  },

  async 'island-edit'(d) {
    const i = d.id ? (await api('/api/islands')).find(x => x.id === d.id) : {};
    modal(`<h2>${d.id ? 'Edit' : 'Add'} island</h2>` + form('island', fields([['code', 'Code', 'text', {required: true, placeholder: 'HDH-KUL'}], ['name', 'Name', 'text', {required: true}], ['atoll', 'Atoll', 'text']], i), 'Save', {id: d.id || ''}));
  },
  async 'alert-ack'(d) { await api(`/api/alerts/${d.id}/ack`, 'POST'); reload(); },

  async 'sub-edit'(d) {
    const [s, islands, plans] = await Promise.all([d.id ? api(`/api/subscribers/${d.id}`) : {}, options('islands'), options('plans')]);
    modal(`<h2>${d.id ? 'Edit subscriber' : 'New subscriber'}</h2>` + form('subscriber', fields([
      ['full_name', 'Full name', 'text', {required: true}], ['phone', 'Phone', 'text'], ['address', 'Address', 'text'],
      ['island_id', 'Island', 'select', {options: none('—').concat(islands)}], ['plan_id', 'Plan', 'select', {options: none('— no plan —').concat(plans)}],
      ['pppoe_username', 'PPPoE username', 'text', {required: true, placeholder: 'a1001.hdh'}], ['static_ip', 'Static IP (optional)', 'text']], s), 'Save', {id: d.id || ''}));
  },
  async 'sub-status'(d) {
    let reason = null;
    if (d.status === 'suspended') { reason = window.prompt('Reason for suspension?', 'manual'); if (reason === null) return; }
    if (d.status === 'cancelled' && !confirmAct('Cancel service? This removes the RADIUS account.')) return;
    const r = await api(`/api/subscribers/${d.id}/status`, 'POST', {status: d.status, reason});
    toast(`Status ${d.status}. Disconnect: ${r.disconnect.map(x => x.result).join(', ') || 'no open session'}`); reload();
  },
  async 'sub-reset'(d) {
    if (!confirmAct('Generate a new PPPoE password? The ONT must be updated with it.')) return;
    const r = await api(`/api/subscribers/${d.id}/reset-password`, 'POST');
    modal(`<h2>New PPPoE password</h2><div class="secret">${esc(r.pppoe_password)}</div><p class="muted">Shown once. Update the ONT (re-provision) or tell the customer.</p>`);
  },
  async 'sub-disconnect'(d) { const r = await api(`/api/subscribers/${d.id}/disconnect`, 'POST'); toast(r.results.map(x => `${x.nas}: ${x.result}`).join(', ') || 'No open session'); },
  async pay(d) {
    modal(`<h2>Record payment · ${esc(d.name)}</h2>` + form('payment', fields([['amount_mvr', 'Amount (MVR)', 'number', {required: true, step: '0.01'}],
      ['method', 'Method', 'select', {options: [['cash', 'Cash'], ['bank_transfer', 'Bank transfer'], ['card', 'Card'], ['online', 'Online'], ['other', 'Other']]}],
      ['reference', 'Reference', 'text']]), 'Record', {sub: d.id}));
  },
  async 'plan-edit'(d) {
    const p = d.id ? (await api('/api/plans')).find(x => x.id === d.id) : {active: true};
    modal(`<h2>${d.id ? 'Edit' : 'Add'} plan</h2>` + form('plan', fields([['name', 'Name', 'text', {required: true}], ['download_mbps', 'Download Mbps', 'number', {required: true}],
      ['upload_mbps', 'Upload Mbps', 'number', {required: true}], ['monthly_price_mvr', 'Monthly price (MVR)', 'number', {required: true, step: '0.01'}], ['active', 'Sellable', 'check']], p), 'Save', {id: d.id || ''}));
  },
  async 'billing-run'() {
    if (!confirmAct('Generate this month\'s invoices and suspend customers past the grace period?')) return;
    const r = await api('/api/billing/run', 'POST', {}); toast(`${r.invoices_created} invoices created, ${r.suspended.length} suspended`); reload();
  },
  async 'inv-void'(d) { if (confirmAct('Void this invoice?')) { await api(`/api/invoices/${d.id}/void`, 'POST'); reload(); } },
  async 'nas-add'() {
    const devs = await options('devices');
    modal('<h2>Add NAS (RADIUS client)</h2>' + form('nas', fields([['nasname', 'Router IP (RADIUS source)', 'text', {required: true}], ['shortname', 'Short name', 'text', {required: true}],
      ['secret', 'Shared secret (12+ chars)', 'password', {required: true}], ['device_id', 'Device', 'select', {options: none('—').concat(devs)}], ['description', 'Notes', 'text']]), 'Save'));
  },
  async 'nas-del'(d) { if (confirmAct('Remove this NAS? Its PPPoE logins will fail.')) { await api(`/api/radius/nas/${d.id}`, 'DELETE'); reload(); } },

  async 'device-edit'(d) {
    const [dev, islands, devices] = await Promise.all([d.id ? api(`/api/devices/${d.id}`) : {poll_enabled: true, settings: {}}, options('islands'), options('devices')]);
    modal(`<h2>${d.id ? 'Edit' : 'Add'} device</h2>` + form('device', fields([
      ['name', 'Name', 'text', {required: true}], ['island_id', 'Island', 'select', {options: none('— core / none —').concat(islands)}],
      ['parent_device_id', 'Upstream device', 'select', {options: none('—').concat(devices.filter(x => x[0] !== d.id))}],
      ['vendor', 'Vendor', 'select', {options: [['mikrotik', 'MikroTik'], ['huawei', 'Huawei'], ['ubiquiti', 'Ubiquiti (airFiber)'], ['other', 'Other']]}],
      ['role', 'Role', 'select', {options: [['island_router', 'Island router'], ['core_router', 'Core router'], ['olt', 'OLT'], ['backhaul', 'Backhaul radio'], ['radius', 'RADIUS'], ['other', 'Other']]}],
      ['management_ip', 'Management IP', 'text'], ['mgmt_port', 'Mgmt port (REST 443 / SSH 22)', 'number'], ['model', 'Model', 'text'],
      ['cred_username', 'Login username', 'text', {placeholder: d.id && dev.has_credentials ? 'stored — leave blank to keep' : ''}],
      ['cred_password', 'Login password', 'password', {placeholder: d.id && dev.has_credentials ? 'stored — leave blank to keep' : ''}],
      ['cred_snmp', 'SNMP community (airFiber)', 'password'],
      ['ssh_host_key', 'Pinned SSH host key (OLT)', 'text', {placeholder: 'SHA256:...'}],
      ['poll_enabled', 'Monitor this device', 'check'],
      ['settings', 'Settings JSON — OLT: {"gpon_slots":[1]}', 'json'], ['notes', 'Notes', 'textarea']], dev), 'Save', {id: d.id || ''}));
  },
  async 'device-poll'(d) { toast('Polling…'); const r = await api(`/api/devices/${d.id}/poll`, 'POST'); toast(`Poll done: ${JSON.stringify(r)}`); reload(); },
  async 'device-audit'(d) {
    toast('Reading router…');
    const r = await api(`/api/devices/${d.id}/security-audit`);
    $('#device-extra').innerHTML = panel(`Security audit · ${r.device}`, table(r.findings, [['severity', 'Severity', tag], ['check', 'Check'], ['detail', 'Finding']]),
      btn('Fix with generated firewall', 'go', {href: `#/security?device=${d.id}`}, 'primary'));
  },
  async 'device-del'(d) { if (confirmAct('Delete this device and its history?')) { await api(`/api/devices/${d.id}`, 'DELETE'); location.hash = '#/devices'; } },
  async 'link-add'() {
    const devs = await options('devices');
    modal('<h2>Add backhaul link</h2>' + form('link', fields([['name', 'Name', 'text', {required: true, placeholder: 'Core ⇄ HDH-Kulhudhuffushi'}],
      ['kind', 'Type', 'select', {options: [['fiber', 'Fiber'], ['airfiber', 'airFiber'], ['other', 'Other']]}],
      ['a_device_id', 'Side A device', 'select', {options: none('—').concat(devs)}], ['b_device_id', 'Side B device', 'select', {options: none('—').concat(devs)}],
      ['capacity_mbps', 'Capacity Mbps', 'number']]), 'Save'));
  },
  async 'link-del'(d) { if (confirmAct('Remove link?')) { await api(`/api/links/${d.id}`, 'DELETE'); reload(); } },

  async 'olt-autofind'(d) {
    toast('Asking OLT for unregistered ONTs…');
    const rows = await api(`/api/olt/${d.id}/autofind`);
    modal('<h2>Unregistered ONTs (autofind)</h2>' + table(rows, [['frame', 'F/S/P', (v, r) => esc(`${r.frame}/${r.slot}/${r.port}`)], ['serial', 'Serial'], ['equipment_id', 'Model'], ['found_at', 'Found'],
      ['serial', '', (v, r) => btn('Provision', 'ont-provision', {olt: d.id, serial: r.serial, frame: r.frame, slot: r.slot, port: r.port}, 'primary')]], {empty: 'No new ONTs found'}));
  },
  async 'ont-provision'(d) {
    const devs = (await api('/api/devices')).filter(x => x.vendor === 'huawei' && x.role === 'olt');
    const subs = d.sub ? [await api(`/api/subscribers/${d.sub}`)] : await api('/api/subscribers?limit=1000');
    modal('<h2>Provision ONT</h2><p class="muted">Creates a change request (ONT add + PPPoE on the ONT + service-port) for a second admin to approve. Line/service profiles and VLAN must already exist on the OLT.</p>' +
      form('provision', fields([
        ['olt_id', 'OLT', 'select', {options: devs.map(x => [x.id, x.name]), default: d.olt}],
        ['subscriber_id', 'Subscriber', 'select', {options: subs.map(s => [s.id, `${s.account_number} · ${s.full_name} · ${s.pppoe_username}`]), default: d.sub}],
        ['serial', 'ONT serial (16 hex)', 'text', {required: true, default: d.serial}],
        ['frame', 'Frame', 'number', {default: d.frame ?? 0}], ['slot', 'Slot', 'number', {required: true, default: d.slot}], ['port', 'PON port', 'number', {required: true, default: d.port}],
        ['ont_id', 'ONT ID (blank = next free)', 'number'], ['line_profile_id', 'ont-lineprofile-id', 'number', {required: true}],
        ['service_profile_id', 'ont-srvprofile-id', 'number', {required: true}], ['vlan', 'Service VLAN', 'number', {required: true}], ['gemport', 'GEM port', 'number', {default: 1}]]), 'Create change request'));
  },
  async 'ont-reboot'(d) { if (confirmAct('Request an ONT reboot (needs approval)?')) { const r = await api(`/api/olt/onts/${d.id}/reboot`, 'POST'); location.hash = `#/change/${r.change_id}`; } },

  async 'change-new'() {
    const devs = (await api('/api/devices')).filter(x => ['mikrotik', 'huawei'].includes(x.vendor));
    modal('<h2>Manual change request</h2>' + form('change', fields([['device_id', 'Device', 'select', {options: devs.map(x => [x.id, `${x.name} · ${x.vendor}`])}],
      ['kind', 'Type', 'select', {options: [['mikrotik_script', 'MikroTik script'], ['huawei_cli', 'Huawei CLI lines']]}], ['title', 'Title', 'text', {required: true}],
      ['plan', 'Commands', 'textarea', {required: true}], ['rollback', 'Rollback commands (Huawei)', 'textarea']]), 'Submit for approval'));
  },
  async 'change-approve'(d) { await api(`/api/changes/${d.id}/approve`, 'POST'); reload(); },
  async 'change-reject'(d) { if (confirmAct('Reject this change?')) { await api(`/api/changes/${d.id}/reject`, 'POST'); reload(); } },
  async 'change-apply'(d) {
    if (!confirmAct('Apply this change to the live device now?')) return;
    toast('Applying… this can take a minute');
    const r = await api(`/api/changes/${d.id}/apply`, 'POST'); toast(`Change ${r.status}`, !r.ok); reload();
  },

  async 'user-add'() {
    modal('<h2>Add user</h2>' + form('user', fields([['username', 'Username (lowercase)', 'text', {required: true}], ['full_name', 'Full name', 'text'],
      ['role', 'Role', 'select', {options: [['support', 'Support (read only)'], ['billing', 'Billing'], ['noc', 'NOC'], ['admin', 'Admin']]}],
      ['password', 'Initial password', 'password', {required: true}]]), 'Create'));
  },
  async 'user-pw'(d) { const p = window.prompt('New password (12+ chars, upper/lower/digit):'); if (p) { await api(`/api/users/${d.id}`, 'PATCH', {password: p}); toast('Password reset; user signed out everywhere'); } },
  async 'user-active'(d) { await api(`/api/users/${d.id}`, 'PATCH', {active: !!d.active}); reload(); },
};

const FORMS = {
  async island(data, f) { await api(f.dataset.id ? `/api/islands/${f.dataset.id}` : '/api/islands', f.dataset.id ? 'PUT' : 'POST', data); closeModal(); reload(); },
  async 'sub-filter'(data) { const p = new URLSearchParams(Object.entries(data).filter(([, v]) => v)); location.hash = '#/subscribers' + (p.toString() ? '?' + p : ''); },
  async subscriber(data, f) {
    if (f.dataset.id) { await api(`/api/subscribers/${f.dataset.id}`, 'PUT', data); closeModal(); reload(); return; }
    const r = await api('/api/subscribers', 'POST', data);
    modal(`<h2>Subscriber ${esc(r.account_number)} created</h2><p>PPPoE password (shown once):</p><div class="secret">${esc(r.pppoe_password)}</div>
      <p class="muted">Account is <b>pending</b> until you activate it. Provision the ONT with this username/password.</p>${btn('Open subscriber', 'go', {href: `#/subscriber/${r.id}`}, 'primary')}`);
  },
  async payment(data, f) {
    const r = await api('/api/payments', 'POST', {...data, subscriber_id: f.dataset.sub, amount_mvr: String(data.amount_mvr)});
    closeModal(); toast(`Payment recorded${r.service_resumed ? ' — service restored' : ''}. Unallocated: ${r.unallocated}`); reload();
  },
  async plan(data, f) { data.monthly_price_mvr = String(data.monthly_price_mvr); await api(f.dataset.id ? `/api/plans/${f.dataset.id}` : '/api/plans', f.dataset.id ? 'PUT' : 'POST', data); closeModal(); reload(); },
  async nas(data) { const r = await api('/api/radius/nas', 'POST', data); closeModal(); toast(r.note); reload(); },
  async device(data, f) {
    const {cred_username: u, cred_password: p, cred_snmp: c, ...body} = data;
    if (u || p || c) body.credentials = {username: u, password: p, snmp_community: c};
    await api(f.dataset.id ? `/api/devices/${f.dataset.id}` : '/api/devices', f.dataset.id ? 'PUT' : 'POST', body); closeModal(); reload();
  },
  async link(data) { await api('/api/links', 'POST', data); closeModal(); reload(); },
  async provision(data) {
    const {olt_id, ...body} = data;
    const r = await api(`/api/olt/${olt_id}/provision`, 'POST', body); closeModal(); location.hash = `#/change/${r.change_id}`;
  },
  async change(data) { const r = await api('/api/changes', 'POST', data); closeModal(); location.hash = `#/change/${r.id}`; },
  async firewall(data) {
    const r = await api('/api/security/firewall', 'POST', data);
    $('#fw-out').innerHTML = panel('Generated RouterOS script', `${r.change_id ? `<p>Change request <a href="#/change/${val(r.change_id)}">#${esc(r.change_id)}</a> created — a second admin must approve it.</p>` : '<p class="muted">Review, then paste in a Winbox terminal opened in Safe Mode, or pick a router above to apply via the change workflow.</p>'}<pre id="fw-script">${esc(r.script)}</pre>`, btn('Copy', 'copy', {target: 'fw-script'}));
  },
  async user(data) { await api('/api/users', 'POST', data); closeModal(); reload(); },
  async 'mfa-enable'(data) {
    const r = await api('/api/auth/mfa/enable', 'POST', {code: data.code});
    $('#mfa-setup').innerHTML = `<p class="s-ok">Two-factor is on.</p>${btn('Continue', 'mfa-finish', {}, 'primary')}`;
    showRecoveryCodes(r.recovery_codes, 'mfa-finish');
  },
  async 'mfa-regen'(data) { const r = await api('/api/auth/mfa/recovery-codes', 'POST', {code: data.code}); showRecoveryCodes(r.recovery_codes, 'mfa-finish'); },
  async 'mfa-disable'(data) {
    if (!confirmAct('Turn off two-factor for your account?')) return;
    await api('/api/auth/mfa/disable', 'POST', data); toast('Two-factor turned off'); start();
  },
  async 'my-password'(data) { const r = await api('/api/auth/password', 'POST', data); toast(r.detail); showLogin(); },
};
ACTIONS.copy = async d => { await navigator.clipboard.writeText(document.getElementById(d.target).textContent); toast('Copied'); };

document.addEventListener('click', async e => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  e.preventDefault(); e.stopPropagation();
  try { await ACTIONS[el.dataset.act]({...el.dataset}, el); } catch (err) { toast(err.message, true); }
});
document.addEventListener('change', async e => {
  const el = e.target.closest('[data-act-change="user-role"]');
  if (!el) return;
  try { await api(`/api/users/${el.dataset.id}`, 'PATCH', {role: el.value}); toast('Role updated'); } catch (err) { toast(err.message, true); reload(); }
});
document.addEventListener('submit', async e => {
  const f = e.target.closest('form[data-form]');
  if (!f) return;
  e.preventDefault();
  const b = f.querySelector('button[type=submit]'); if (b) b.disabled = true;
  try { await FORMS[f.dataset.form](formData(f), f); } catch (err) { toast(err.message, true); } finally { if (b) b.disabled = false; }
});

// ---------------------------------------------------------------- shell
function buildNav() {
  let html = '', group = '';
  for (const [key, p] of Object.entries(PAGES)) {
    if (p.hidden || !can(p.perm)) continue;
    if (p.group !== group) { group = p.group; html += `<div class="group">${esc(group)}</div>`; }
    html += `<button data-act="go" data-href="#/${key}" data-page="${key}">${esc(p.nav)}</button>`;
  }
  $('#nav').innerHTML = html;
}

async function route() {
  if (ME.mfa_setup_required) {
    $('#crumb').textContent = 'Security'; $('#title').textContent = 'Two-factor sign-in';
    $('#view').innerHTML = mfaSetupPanel(`Your ${ME.role} account must use two-factor sign-in before you can continue.`);
    $('#connection').textContent = '● API connected';
    return;
  }
  const [path, qs] = (location.hash.slice(2) || 'dashboard').split('?');
  const [key, id] = path.split('/');
  const page = PAGES[key] && can(PAGES[key].perm) ? PAGES[key] : PAGES.dashboard;
  const navKey = {subscriber: 'subscribers', device: 'devices', change: 'changes'}[key] || key;
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === navKey));
  $('#crumb').textContent = page.nav ? page.nav.slice(2) : page.title;
  $('#title').textContent = page.title;
  try {
    $('#view').innerHTML = await page.render(new URLSearchParams(qs || ''), id);
    $('#connection').textContent = '● API connected'; $('#connection').style.color = '';
  } catch (err) {
    $('#view').innerHTML = panel('Could not load', `<p class="error">${esc(err.message)}</p>`);
  }
}

let mfaToken = null;
function showLogin() {
  ME = null; mfaToken = null; $('#app').classList.add('hidden'); $('#login').classList.remove('hidden'); closeModal();
  $('#mfa-form').classList.add('hidden'); $('#login-form').classList.remove('hidden');
}

async function start() {
  try { ME = await api('/api/auth/me'); } catch { showLogin(); return; }
  $('#login').classList.add('hidden'); $('#app').classList.remove('hidden');
  $('#me').textContent = `${ME.username} · ${ME.role}`;
  buildNav(); route();
}

$('#login-form').addEventListener('submit', async e => {
  e.preventDefault();
  $('#login-error').textContent = '';
  const f = new FormData(e.target);
  try {
    const r = await api('/api/auth/login', 'POST', {username: f.get('username'), password: f.get('password')});
    e.target.reset();
    if (r.mfa_required) {
      mfaToken = r.mfa_token;
      $('#login-form').classList.add('hidden'); $('#mfa-form').classList.remove('hidden'); $('#mfa-error').textContent = '';
      $('#mfa-form input[name=code]').focus();
      return;
    }
    start();
  } catch (err) { $('#login-error').textContent = err.message; }
});
$('#mfa-form').addEventListener('submit', async e => {
  e.preventDefault();
  $('#mfa-error').textContent = '';
  const code = new FormData(e.target).get('code');
  try {
    const r = await api('/api/auth/login/mfa', 'POST', {mfa_token: mfaToken, code});
    e.target.reset(); mfaToken = null;
    await start();
    if (r.recovery_codes_left <= 3) toast(`Only ${r.recovery_codes_left} recovery codes left. Generate new ones under My account.`, true);
  } catch (err) {
    e.target.reset();
    $('#mfa-error').textContent = err.message;
    if (/expired/i.test(err.message)) setTimeout(showLogin, 1500);
  }
});
$('#mfa-back').addEventListener('click', showLogin);
$('#logout').addEventListener('click', async () => { try { await api('/api/auth/logout', 'POST'); } finally { showLogin(); } });
$('#modal-close').addEventListener('click', closeModal);
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });
window.addEventListener('hashchange', () => { if (ME) route(); });
setInterval(() => { if (ME && !document.hidden && ['', '#/dashboard', '#/alerts', '#/radius'].includes(location.hash) && $('#modal').classList.contains('hidden')) route(); }, 30000);
start();
