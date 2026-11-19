/* ═══ GOLD TERMINAL — app logic ═══
   Two refresh cadences, deliberately separate:
   • Live ticker   : gold-api.com every 15 s (CORS-open, no key)
   • Engine data   : data.json rebuilt by GitHub Actions cron (Mon–Fri, every 30m)
   If data.json fails to load, the last good render stays on screen.          */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmt$ = n => n == null || isNaN(n) ? '—' : '$' + Number(n).toLocaleString('en-US', {maximumFractionDigits: 2, minimumFractionDigits: 2});
const fmtN = (n, d = 1) => n == null || isNaN(n) ? '—' : Number(n).toLocaleString('en-US', {maximumFractionDigits: d, minimumFractionDigits: d});
const sign = (n, d = 2) => (n >= 0 ? '+' : '') + Number(n).toFixed(d);

let DATA = null;

/* ─────────────────────────────────────────── fetch engine snapshot */
async function fetchData(initial = false) {
  try {
    const res = await fetch('data.json?t=' + Date.now(), {cache: 'no-store'});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const d = await res.json();
    const changed = !DATA || DATA.generated_at !== d.generated_at;
    DATA = d;
    if (changed) {
      renderAll(d);
      if (!initial) flash('✓ New market data published — view refreshed');
    }
  } catch (e) {
    console.warn('data.json fetch failed:', e);
    $('#refreshAge').textContent = 'stale — retry pending';
    if (initial) $('#callHeadline').textContent = 'Engine data unavailable — check your connection or redeploy.';
  }
}

/* ─────────────────────────────────────────── live spot ticker (gold-api) */
let settleRef = null;
async function tickLive() {
  try {
    const res = await fetch('https://api.gold-api.com/price/XAU', {cache: 'no-store'});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const j = await res.json();
    const px = Number(j.price);
    if (!isFinite(px)) return;
    $('#livePrice').textContent = fmt$(px);
    if (settleRef) {
      const chg = (px / settleRef - 1) * 100;
      const el = $('#liveChg');
      el.textContent = sign(chg, 2) + '% vs settle';
      el.className = 't-chg ' + (chg >= 0 ? 'up' : 'dn');
    }
  } catch (e) {
    // gold-api unreachable — keep last print; engine snapshot still renders
  }
}

/* ─────────────────────────────────────────── renderers */
function renderAll(d) {
  settleRef = d.futures?.prev_close ?? null;
  renderHero(d); renderChips(d); renderCall(d); renderLevels(d);
  renderModel(d); renderDrivers(d); renderScenarios(d); renderCalendar(d); renderCharts(d);
  tickLive();
}

function renderHero(d) {
  $('#genAt').textContent = 'engine run ' + d.generated_at.replace('T', ' ').replace('Z', ' UTC');
  const bias = $('#biasPill');
  bias.textContent = d.call.bias;
  bias.className = 'bias-pill ' + (d.call.pill || 'blue');
  $('#callHeadline').textContent = d.call.headline;
  $('#callTiming').textContent = d.call.timing;
  $('#bandValue').textContent = `$${fmtN(d.expected_band[0], 0)} – $${fmtN(d.expected_band[1], 0)}`;
  $('#bandSub').textContent = `ATR(14) $${fmtN(d.tech.atr14, 1)} (${d.tech.atr_pct}% of price) · spot ref $${fmtN(d.ref_price, 0)}`;
  const p = d.model.p_up.ensemble;
  $('#pUpVal').textContent = (p * 100).toFixed(0) + '%';
  $('#pUpFill').style.width = Math.round(p * 100) + '%';
  $('#refreshAge').textContent = ageString(d.generated_at);
}

function chip(k, v, sub) {
  return `<div class="chip"><div class="k">${esc(k)}</div><div class="v">${v}${sub ? ` <small>${esc(sub)}</small>` : ''}</div></div>`;
}
function pctCls(n) { return n >= 0 ? 'up' : 'dn'; }

function renderChips(d) {
  const f = d.futures, t = d.tech, ctx = d.context, r = d.returns;
  const px = d.spot.xau ?? f.price;
  const html = [
    chip('Spot XAU', fmt$(px)),
    chip('GC=F Futures', `$${fmtN(f.price, 2)}`, `${sign(f.change_pct)}%`),
    chip('Day range', `${fmtN(f.day_low, 0)}–${fmtN(f.day_high, 0)}`),
    chip('52W low', `$${fmtN(f.fiftyTwoWeekLow, 0)}`, 'tagged today?'),
    chip('52W high', `$${fmtN(f.fiftyTwoWeekHigh, 0)}`),
    chip('RSI(14)', fmtN(t.rsi14, 1), t.rsi14 < 30 ? 'oversold' : ''),
    chip('vs 200-DMA', `${sign(t.dist_sma200, 1)}%`, ''),
    chip('DXY', fmtN(ctx.dxy, 2), `${sign(ctx.dxy_20d, 1)}% 20d`),
    chip('US 10Y', fmtN(ctx.tnx, 2) + '%', `${sign(ctx.tnx_60d, 2)}pt 60d`),
    chip('Silver', fmt$(ctx.silver), `${sign(ctx.silver_60d, 1)}% 60d`),
    chip('WTI', fmt$(ctx.oil), `${sign(ctx.oil_20d, 1)}% 20d`),
    chip('Gold/Silver', fmtN(t.gs_ratio, 1), 'ratio'),
    chip('SPX', fmtN(ctx.spx, 0), `${sign(ctx.spx_20d, 1)}% 20d`),
    chip('5d return', `${sign(r.d5, 2)}%`, ''),
    chip('60d return', `${sign(r.d60, 2)}%`, ''),
    chip('Realized vol', fmtN(t.vol20, 1) + '%', '20d ann.'),
  ].join('');
  $('#chips').innerHTML = html;
}

function renderCall(d) {
  $('#aggDir').textContent = d.call.direction === 'up' ? 'ENTRY (LONG)' : 'ENTRY (SHORT)';
  $('#entryAgg').textContent = d.call.entry_aggressive;
  $('#entryCons').textContent = d.call.entry_conservative;
  $('#invalidation').textContent = d.call.invalidation;
  $('#targetChain').innerHTML = d.call.targets.map(esc).join('<br>');
  $('#expectedEnd').textContent = d.call.expected_end;
}

function renderLevels(d) {
  const ref = d.ref_price;
  $('#pvH').textContent = fmtN(d.pivots.prevH, 1);
  $('#pvL').textContent = fmtN(d.pivots.prevL, 1);
  $('#pvC').textContent = fmtN(d.pivots.prevC, 1);
  const rows = d.levels.map(l => {
    const dist = (l.price / ref - 1) * 100;
    const cls = l.kind === 'R' ? 'lvlR' : l.kind === 'S' ? 'lvlS' : l.kind === 'P' ? 'lvlP' : 'lvlN';
    const here = Math.abs(dist) < 0.35;
    return `<tr class="${cls}${here ? ' here' : ''}"><td>${fmtN(l.price, 1)}</td><td style="white-space:normal">${esc(l.label)}${here ? ' ← spot' : ''}</td><td class="num ${dist >= 0 ? 'up' : 'dn'}">${sign(dist, 2)}%</td></tr>`;
  }).join('');
  $('#levelRows').innerHTML = rows;
}

function renderModel(d) {
  const m = d.model, o = m.oos;
  $('#oosKpis').innerHTML = [
    ['GB hit rate', (o.gb_acc * 100).toFixed(1) + '%', o.gb_acc >= 0.5 ? 'up' : 'dn'],
    ['LR hit rate', (o.lr_acc * 100).toFixed(1) + '%', o.lr_acc >= 0.5 ? 'up' : 'dn'],
    ['Ens. last-30', (o.ens_recent30 * 100).toFixed(1) + '%', o.ens_recent30 >= 0.5 ? 'up' : 'dn'],
    ['Always-long', (o.baseline_long * 100).toFixed(1) + '%', 'dim'],
  ].map(([d_, n_, c_]) => `<div class="kpi"><div class="n ${c_}">${n_}</div><div class="d">${d_}<br>(${o.n} OOS)</div></div>`).join('');

  const gauge = (label, val, color) => `
    <div class="gauge"><div class="g-label">${esc(label)}</div>
      <div class="g-track"><div class="g-fill" style="width:${(val * 100).toFixed(0)}%;background:${color}"></div></div>
      <div class="g-val">${(val * 100).toFixed(0)}%</div></div>`;
  $('#gauges').innerHTML =
    gauge('Gradient Boost', m.p_up.gb, 'var(--red)') +
    gauge('Logistic Reg', m.p_up.lr, 'var(--blue)') +
    gauge('Ensemble (0.6/0.4)', m.p_up.ensemble, 'var(--gold)');

  const maxImp = Math.max(...m.importances.map(([, v]) => v), 1);
  $('#importances').innerHTML = m.importances.map(([k, v]) => `
    <div class="imp"><div>${esc(k)}</div>
      <div class="i-bar"><div class="i-fill" style="width:${(v / maxImp * 100).toFixed(1)}%"></div></div>
      <div class="i-val">${v}%</div></div>`).join('');

  $('#wfRows').innerHTML = m.walk_forward.slice().reverse().map(r => `
    <tr><td>${esc(r.date)}</td><td>${(r.p_ens * 100).toFixed(0)}%</td>
        <td>${r.actual ? '▲ up' : '▼ down'}</td>
        <td class="${r.fwd_ret >= 0 ? 'up' : 'dn'}">${sign(r.fwd_ret, 2)}%</td></tr>`).join('');
}

function renderDrivers(d) {
  $('#driverList').innerHTML = d.drivers.map(x => `<li>${esc(x)}</li>`).join('');
  const c = d.corr;
  $('#corrStrip').innerHTML = [
    ['corr(gold, DXY) 30d', c.dxy], ['corr(gold, 10Y) 30d', c.tnx],
    ['corr(gold, silver) 30d', c.slv], ['corr(gold, WTI) 60d', c.oil_60],
  ].map(([k, v]) => `<span class="corr-pill">${esc(k)}: <b>${v >= 0 ? '+' : ''}${v}</b></span>`).join('');
  const note = (d.desk_note || '').trim();
  $('#deskNoteWrap').hidden = !note;
  if (note) $('#deskNote').textContent = note;
}

function renderScenarios(d) {
  $('#scenarioList').innerHTML = d.scenarios.map(s => `
    <div class="scenario">
      <div class="sc-name">${esc(s.name)}<span class="pill ${esc(s.pill)}">${s.prob}%</span></div>
      <div class="sc-prob">${s.prob}%</div>
      <div class="sc-bar"><div class="sc-fill" style="width:${s.prob}%"></div></div>
      <div class="sc-desc">${esc(s.desc)}</div>
    </div>`).join('');
}

function renderCalendar(d) {
  const cal = d.calendar;
  $('#calRows').innerHTML = cal.events.map(e => `
    <tr><td><b>${esc(e.time_utc)}</b></td><td>${esc(e.event)}</td>
        <td class="imp-${esc(e.impact.replace('—', 'LOW'))}">${esc(e.impact)}</td>
        <td>${esc(e.gold_read)}</td></tr>`).join('');
  $('#calNote').textContent = `${cal.weekday} ${cal.as_of} · ${cal.note}`;
}

let CHART_V = '';
function renderCharts(d) {
  CHART_V = encodeURIComponent(d.generated_at);
  const active = $('#chartTabs .tab.active');
  setChart(active ? active.dataset.chart : 'chart_6m');
}
function setChart(name) {
  $$('#chartTabs .tab').forEach(b => b.classList.toggle('active', b.dataset.chart === name));
  $('#chartImg').src = `charts/${name}.png?v=${CHART_V}`;
}
/* tab clicks bound exactly once (event delegation) */
$('#chartTabs').addEventListener('click', e => {
  const btn = e.target.closest('.tab');
  if (btn) setChart(btn.dataset.chart);
});

/* ─────────────────────────────────────────── csv download */
$('#csvBtn').addEventListener('click', () => {
  if (!DATA?.hist?.length) return;
  const csv = 'date,close_gc_f\n' + DATA.hist.map(r => `${r.date},${r.close}`).join('\n');
  const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
  const a = Object.assign(document.createElement('a'), {href: url, download: 'gold_gc_f_daily.csv'});
  a.click(); URL.revokeObjectURL(url);
});

/* ─────────────────────────────────────────── helpers */
function ageString(iso) {
  const ms = Date.now() - Date.parse(iso);
  if (!isFinite(ms)) return '—';
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'updated just now';
  if (m < 60) return `updated ${m}m ago · auto ~30m`;
  const h = Math.floor(m / 60);
  return `updated ${h}h ${m % 60}m ago · auto ~30m`;
}
function flash(msg) {
  const f = $('#flash'); f.textContent = msg; f.classList.add('show');
  setTimeout(() => f.classList.remove('show'), 4000);
}

/* ─────────────────────────────────────────── boot */
fetchData(true).then(() => { tickLive(); });
setInterval(() => fetchData(false), 60_000);
setInterval(tickLive, 15_000);
setInterval(() => { if (DATA) $('#refreshAge').textContent = ageString(DATA.generated_at); }, 30_000);
setInterval(() => { if (DATA) renderCharts(DATA); }, 5 * 60_000); // re-bust chart URLs periodically
