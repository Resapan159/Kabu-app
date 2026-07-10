"""スマホ対応HTMLレポート生成（モバイルファースト・ダークモード）。

構想書のUI方針: 単一HTML、銘柄カードをタップで根拠を展開、ダークモード対応。
総資金・購入記録はスマホ側localStorageのみに保存（公開ページに個人情報を載せない）。
チャートは prices.json（公開データ: ユニバースの日足）をJSで描画する。
"""
from __future__ import annotations

import html
import json
from pathlib import Path


def _esc(s) -> str:
    return html.escape(str(s))


def _gate_banner(gate: dict) -> str:
    status = gate["status"]
    color = {"OK": "#1f9d55", "WARN": "#c98a00", "NG": "#c0392b"}[status]
    icon = {"OK": "✅", "WARN": "⚠️", "NG": "⛔"}[status]
    m = gate["metrics"]
    metric_txt = " / ".join(filter(None, [
        f"先物 {m['futures_pct']:+.1f}%" if m.get("futures_pct") is not None else None,
        f"日経 {m['nikkei_pct']:+.1f}%" if m.get("nikkei_pct") is not None else None,
        f"SOX {m['sox_pct']:+.1f}%" if m.get("sox_pct") is not None else None,
        f"ダウ {m['dow_pct']:+.1f}%" if m.get("dow_pct") is not None else None,
        f"為替 {m['usdjpy']:.1f}円" if m.get("usdjpy") is not None else None,
    ]))
    reasons = "　".join(_esc(r) for r in gate["reasons"])
    return f"""
    <div class="banner" style="background:{color}">
      <div class="banner-top">{icon} 地合い: {status}</div>
      <div class="banner-metrics">{_esc(metric_txt)}</div>
      <div class="banner-reasons">{reasons}</div>
    </div>"""


def _candidate_card(c: dict, rank: int) -> str:
    gated = c.get("gated_out")
    hit_rows = "".join(
        f'<li><b>{_esc(h["label"])}</b>'
        + (f' — {_esc(h["detail"])}' if h.get("detail") else "")
        + "</li>"
        for h in c["hits"]
    )
    sys_tags = "".join(
        f'<span class="tag">{_esc(lbl)}</span>' for lbl in c["system_labels"]
    )
    pos = c["position"]
    shares_line = (
        f'{pos["shares"]}株（コスト約{pos["cost_yen"]:,}円）'
        if pos["shares"] > 0 else f'—（{_esc(pos["note"])}）'
    )
    gated_note = '<div class="gated">⛔ 地合いNGのため本日は見送り推奨</div>' if gated else ""
    code = _esc(c["code"])
    name = _esc(c["name"])
    return f"""
    <details class="card{' gated-card' if gated else ''}" data-code="{code}"
             data-in="{c['in_price']}" data-stop="{c['stop']}">
      <summary>
        <div class="card-head">
          <span class="rank">{rank}</span>
          <span class="code">{code}</span>
          <span class="name">{name}</span>
          <span class="score">{c['score']}</span>
        </div>
        <div class="card-sub">
          {sys_tags}
          <span class="muted">出来高{c['volume_ratio']}倍 / 代金{c['turnover_oku']}億</span>
        </div>
      </summary>
      <div class="card-body">
        {gated_note}
        <ul class="hits">{hit_rows}</ul>
        <div class="levels">
          <div><span class="k">IN目安</span><span class="v">{c['in_price']:,}円</span></div>
          <div><span class="k">損切り</span><span class="v">{c['stop']:,}円 ({c['stop_pct']}%)</span></div>
          <div><span class="k">目標</span><span class="v">{c['target']:,}円 (+{c['target_pct']}%)</span></div>
          <div><span class="k">株数目安</span><span class="v shares" data-code="{code}">{shares_line}</span></div>
        </div>
        <div class="btnrow">
          <button class="btn chartbtn" data-code="{code}" data-name="{name}">📈 チャート</button>
          <button class="btn buy buybtn" data-code="{code}" data-name="{name}"
                  data-in="{c['in_price']}">🛒 購入登録</button>
        </div>
      </div>
    </details>"""


def _holdings_section(holdings: list) -> str:
    if not holdings:
        return ""
    rows = ""
    color = {"継続": "#1f9d55", "利確検討": "#2d7dd2",
             "撤退（損切り）": "#c0392b", "撤退（時間切れ）": "#c98a00"}
    for h in holdings:
        col = color.get(h["judgment"], "#888")
        detail = _esc(h.get("detail", ""))
        pnl = f'{h.get("pnl_pct", 0):+.1f}%' if "pnl_pct" in h else ""
        rows += f"""
        <div class="hold">
          <div class="hold-head">
            <span class="code">{_esc(h['code'])}</span>
            <span class="name">{_esc(h['name'])}</span>
            <span class="pnl">{pnl}</span>
            <span class="judge" style="background:{col}">{_esc(h['judgment'])}</span>
          </div>
          <div class="hold-detail muted">{detail}</div>
        </div>"""
    return f'<h2>■ 保有銘柄チェック（holdings.csv）</h2><div class="holds">{rows}</div>'


def _review_section(review: dict) -> str:
    recent = review.get("recent")
    by_system = review.get("by_system", [])
    if not recent and not by_system:
        return '<h2>■ 答え合わせ</h2><p class="muted">まだ評価対象のピックがありません（記録開始直後）。</p>'
    parts = ['<h2>■ 答え合わせ（シグナル検証）</h2>']
    if recent:
        parts.append(
            f'<p>{_esc(recent["pick_date"])}ピック {recent["n"]}銘柄: '
            f'{recent["horizon"]}日後平均 <b>{recent["avg_ret"]:+.1f}%</b>'
            f'（勝率 {_esc(recent["win_rate"])}）</p>'
        )
    if by_system:
        srows = "".join(
            f'<tr><td>{_esc(s["system"])}</td><td>{s["n"]}</td>'
            f'<td>{s["avg_ret"]:+.1f}%</td><td>{s["win_rate"]:.0f}%</td></tr>'
            for s in by_system
        )
        parts.append(
            '<table class="rev"><thead><tr><th>系統</th><th>件数</th>'
            f'<th>平均</th><th>勝率</th></tr></thead><tbody>{srows}</tbody></table>'
        )
    return "".join(parts)


# ---------------------------------------------------------------- CSS / JS
CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;
  background:#0d1117; color:#e6edf3; line-height:1.6; padding-bottom:40px; }
.wrap { max-width:560px; margin:0 auto; padding:12px; }
h1 { font-size:1.15rem; margin:8px 0; }
h2 { font-size:1rem; margin:22px 0 8px; border-left:4px solid #2d7dd2; padding-left:8px; }
.muted { color:#8b949e; font-size:.85rem; }
.banner { border-radius:12px; padding:12px 14px; color:#fff; margin:10px 0; }
.banner-top { font-weight:700; font-size:1.05rem; }
.banner-metrics { font-size:.9rem; opacity:.95; margin-top:2px; }
.banner-reasons { font-size:.8rem; opacity:.9; margin-top:4px; }
.errbar { background:#5a3a00; color:#ffd479; border-radius:8px; padding:8px 10px;
  font-size:.8rem; margin:8px 0; }
.seemikakuri { background:#3a1414; color:#ffb3b3; border-radius:8px; padding:10px;
  font-size:.9rem; margin:8px 0; }
.capbox { background:#161b22; border:1px solid #30363d; border-radius:10px;
  padding:10px 12px; margin:10px 0; font-size:.85rem; }
.capbox input { width:120px; background:#0d1117; color:#e6edf3; border:1px solid #30363d;
  border-radius:6px; padding:4px 8px; font-size:.9rem; }
.card { background:#161b22; border:1px solid #30363d; border-radius:12px;
  margin:10px 0; overflow:hidden; }
.card[open] { border-color:#2d7dd2; }
.gated-card { opacity:.7; }
summary { list-style:none; cursor:pointer; padding:12px; }
summary::-webkit-details-marker { display:none; }
.card-head { display:flex; align-items:center; gap:8px; }
.rank { background:#2d7dd2; color:#fff; border-radius:50%; width:22px; height:22px;
  display:flex; align-items:center; justify-content:center; font-size:.8rem; font-weight:700; }
.code { font-family:monospace; color:#8b949e; }
.name { font-weight:700; flex:1; }
.score { background:#233; color:#7ee787; font-weight:700; padding:2px 8px;
  border-radius:6px; font-size:.9rem; }
.card-sub { margin-top:6px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
.tag { background:#1f2d3d; color:#79c0ff; border-radius:5px; padding:1px 7px; font-size:.72rem; }
.card-body { padding:0 12px 12px; border-top:1px solid #30363d; }
.gated { color:#ffb3b3; font-size:.85rem; margin:8px 0; }
.hits { margin:10px 0; padding-left:18px; font-size:.85rem; }
.hits li { margin:3px 0; }
.levels { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:8px; }
.levels > div { background:#0d1117; border-radius:8px; padding:6px 8px; }
.levels .k { display:block; color:#8b949e; font-size:.72rem; }
.levels .v { font-weight:700; }
.btnrow { display:flex; gap:8px; margin-top:10px; }
.btn { flex:1; background:#21262d; color:#e6edf3; border:1px solid #30363d;
  border-radius:8px; padding:8px; font-size:.85rem; cursor:pointer; }
.btn.buy { background:#1f3d2b; border-color:#2ea043; color:#7ee787; }
.btn.danger { background:#3a1414; border-color:#c0392b; color:#ffb3b3; }
.btn.small { flex:none; padding:5px 10px; font-size:.78rem; }
.holds .hold { background:#161b22; border:1px solid #30363d; border-radius:10px;
  padding:10px; margin:8px 0; }
.hold-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.hold .pnl { font-weight:700; }
.judge { color:#fff; border-radius:6px; padding:2px 8px; font-size:.78rem; }
.hold-detail { margin-top:4px; }
table.rev { width:100%; border-collapse:collapse; font-size:.82rem; margin-top:6px; }
table.rev th, table.rev td { border-bottom:1px solid #30363d; padding:5px; text-align:center; }
table.rev th { color:#8b949e; }
footer { margin-top:26px; font-size:.72rem; color:#8b949e; }
/* 購入一覧 */
.psum { background:#161b22; border:1px solid #30363d; border-radius:10px;
  padding:10px 12px; margin:8px 0; font-size:.95rem; }
.pos { color:#7ee787; } .neg { color:#ff7b72; }
.pcard { background:#161b22; border:1px solid #30363d; border-radius:10px;
  padding:10px; margin:8px 0; }
.pcard.sold { opacity:.75; }
.pcard-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.pcard-head .pnl { font-weight:700; margin-left:auto; }
.pcard-detail { font-size:.82rem; color:#8b949e; margin-top:3px; }
.pcard .btnrow { margin-top:8px; }
/* チャートモーダル */
#chart-overlay { position:fixed; inset:0; background:rgba(0,0,0,.85); z-index:50;
  display:none; align-items:center; justify-content:center; flex-direction:column; }
#chart-overlay.show { display:flex; }
#chart-box { background:#161b22; border:1px solid #30363d; border-radius:14px;
  padding:12px; width:min(96vw, 640px); }
#chart-title { font-weight:700; margin-bottom:6px; display:flex; align-items:center; }
#chart-close { margin-left:auto; background:none; border:none; color:#8b949e;
  font-size:1.4rem; cursor:pointer; padding:0 4px; }
#chart-canvas { width:100%; height:340px; display:block; }
#chart-note { font-size:.72rem; color:#8b949e; margin-top:4px; }
/* タブ */
.tabs { position:sticky; top:0; z-index:10; display:flex; gap:6px; background:#0d1117;
  padding:8px 0; }
.tabbtn { flex:1; background:#161b22; color:#8b949e; border:1px solid #30363d;
  border-radius:10px; padding:9px 0; font-size:.9rem; cursor:pointer; }
.tabbtn.active { background:#1f2d3d; color:#79c0ff; border-color:#2d7dd2; font-weight:700; }
.tabpanel { display:none; }
.tabpanel.active { display:block; }
/* 購入ダイアログ */
#buy-overlay { position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:60;
  display:none; align-items:center; justify-content:center; }
#buy-overlay.show { display:flex; }
#buy-box { background:#161b22; border:1px solid #2ea043; border-radius:14px;
  padding:16px; width:min(92vw, 380px); }
#buy-box h3 { margin:0 0 10px; font-size:1rem; }
#buy-box label { display:block; font-size:.8rem; color:#8b949e; margin-top:10px; }
#buy-box input { width:100%; background:#0d1117; color:#e6edf3; border:1px solid #30363d;
  border-radius:8px; padding:8px; font-size:1rem; margin-top:3px; }
#buy-box .btnrow { margin-top:14px; }
"""

SCRIPT = r"""
<script>
const RISK_PCT = __RISK__;
const CANDS = __CANDS__;
const IS_ARCHIVE = location.pathname.includes('/reports/');
const PRICES_URL = (IS_ARCHIVE ? '../' : '') + 'prices.json';
let PRICES = null;

function fmt(n) { return Math.round(n).toLocaleString('ja-JP'); }
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

/* ---------- 総資金→株数再計算 ---------- */
const capEl = document.getElementById('capital');
function recalc() {
  const cap = parseFloat(capEl.value);
  CANDS.forEach(c => {
    const el = document.querySelector('.shares[data-code="' + c.code + '"]');
    if (!el || !cap || cap <= 0) return;
    const risk = cap * RISK_PCT / 100;
    const per = Math.max(c.in - c.stop, 0.01);
    const shares = Math.floor((risk / per) / 100) * 100;
    el.textContent = shares > 0
      ? shares + '株（コスト約' + fmt(shares * c.in) + '円）'
      : '—（値幅が大きく単元に満たない）';
  });
}
try { const s = localStorage.getItem('kabu_capital'); if (s) { capEl.value = s; recalc(); } } catch (e) {}
capEl.addEventListener('input', () => {
  try { localStorage.setItem('kabu_capital', capEl.value); } catch (e) {}
  recalc();
});

/* ---------- 購入記録（localStorage） ---------- */
function loadPurchases() {
  try { return JSON.parse(localStorage.getItem('kabu_purchases') || '[]'); }
  catch (e) { return []; }
}
function savePurchases(a) { localStorage.setItem('kabu_purchases', JSON.stringify(a)); }
function lastClose(code) {
  const p = PRICES && PRICES[code];
  return (p && p.c.length) ? p.c[p.c.length - 1] : null;
}
function stockName(code) {
  const p = PRICES && PRICES[code];
  return p ? p.name : '';
}

function renderPurchases() {
  const box = document.getElementById('purchase-list');
  const items = loadPurchases();
  if (!items.length) {
    box.innerHTML = '<p class="muted">まだ購入記録がありません。候補カードの「🛒 購入登録」から追加できます。</p>';
    return;
  }
  let totalPnl = 0, totalCost = 0, html = '';
  const holding = items.filter(p => p.status !== 'sold');
  const sold = items.filter(p => p.status === 'sold');

  holding.forEach(p => {
    const shares = p.units * 100;
    const cur = lastClose(p.code);
    let pnlHtml = '<span class="muted">現在値不明</span>', detail;
    if (cur !== null) {
      const pnl = (cur - p.price) * shares;
      const pct = (cur / p.price - 1) * 100;
      totalPnl += pnl; totalCost += p.price * shares;
      const cls = pnl >= 0 ? 'pos' : 'neg';
      pnlHtml = '<span class="pnl ' + cls + '">' + (pnl >= 0 ? '+' : '') + fmt(pnl) + '円 (' +
        (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%)</span>';
      detail = '購入 ' + esc(p.date) + ' @' + fmt(p.price) + ' × ' + p.units + '単元(' + shares +
        '株) → 現在 ' + fmt(cur) + '円';
    } else {
      detail = '購入 ' + esc(p.date) + ' @' + fmt(p.price) + ' × ' + p.units + '単元(' + shares + '株)';
    }
    html += '<div class="pcard">' +
      '<div class="pcard-head"><span class="code">' + esc(p.code) + '</span>' +
      '<span class="name">' + esc(p.name || stockName(p.code)) + '</span>' + pnlHtml + '</div>' +
      '<div class="pcard-detail">' + detail + '</div>' +
      '<div class="btnrow">' +
      '<button class="btn small chartbtn" data-code="' + esc(p.code) + '" data-name="' +
        esc(p.name || '') + '" data-line="' + p.price + '">📈 チャート</button>' +
      '<button class="btn small" onclick="sellPurchase(\'' + p.id + '\')">💰 売却登録</button>' +
      '<button class="btn small danger" onclick="deletePurchase(\'' + p.id + '\')">🗑 削除</button>' +
      '</div></div>';
  });

  let sum = '';
  if (totalCost > 0) {
    const cls = totalPnl >= 0 ? 'pos' : 'neg';
    sum = '<div class="psum">保有中の評価損益: <b class="' + cls + '">' +
      (totalPnl >= 0 ? '+' : '') + fmt(totalPnl) + '円 (' +
      (totalPnl / totalCost * 100).toFixed(1) + '%)</b>' +
      ' <span class="muted">/ 投下資金 ' + fmt(totalCost) + '円</span></div>';
  }

  if (sold.length) {
    html += '<h3 style="font-size:.9rem;color:#8b949e;margin:14px 0 4px">売却済み（確定）</h3>';
    sold.forEach(p => {
      const shares = p.units * 100;
      const pnl = (p.sellPrice - p.price) * shares;
      const pct = (p.sellPrice / p.price - 1) * 100;
      const cls = pnl >= 0 ? 'pos' : 'neg';
      html += '<div class="pcard sold">' +
        '<div class="pcard-head"><span class="code">' + esc(p.code) + '</span>' +
        '<span class="name">' + esc(p.name || '') + '</span>' +
        '<span class="pnl ' + cls + '">' + (pnl >= 0 ? '+' : '') + fmt(pnl) + '円 (' +
        (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%)</span></div>' +
        '<div class="pcard-detail">購入 ' + esc(p.date) + ' @' + fmt(p.price) +
        ' → 売却 ' + esc(p.sellDate || '') + ' @' + fmt(p.sellPrice) + ' × ' + p.units + '単元</div>' +
        '<div class="btnrow"><button class="btn small danger" onclick="deletePurchase(\'' +
        p.id + '\')">🗑 削除</button></div></div>';
    });
  }
  box.innerHTML = sum + html;
}

function sellPurchase(id) {
  const items = loadPurchases();
  const p = items.find(x => x.id === id);
  if (!p) return;
  const cur = lastClose(p.code);
  const v = prompt('売却価格（円）を入力', cur !== null ? String(cur) : '');
  if (v === null) return;
  const price = parseFloat(v);
  if (!price || price <= 0) { alert('価格が不正です'); return; }
  p.status = 'sold';
  p.sellPrice = price;
  p.sellDate = new Date().toISOString().slice(0, 10);
  savePurchases(items);
  renderPurchases();
}
function deletePurchase(id) {
  if (!confirm('この記録を削除しますか？')) return;
  savePurchases(loadPurchases().filter(x => x.id !== id));
  renderPurchases();
}

/* ---------- 購入登録ダイアログ ---------- */
function openBuy(code, name, defPrice) {
  document.getElementById('buy-code').value = code || '';
  document.getElementById('buy-code').readOnly = !!code;
  document.getElementById('buy-name').textContent = name ? code + ' ' + name : '銘柄コードを入力';
  document.getElementById('buy-price').value = defPrice || '';
  document.getElementById('buy-units').value = 1;
  document.getElementById('buy-date').value = new Date().toISOString().slice(0, 10);
  document.getElementById('buy-overlay').classList.add('show');
}
function closeBuy() { document.getElementById('buy-overlay').classList.remove('show'); }
function submitBuy() {
  const code = document.getElementById('buy-code').value.trim();
  const price = parseFloat(document.getElementById('buy-price').value);
  const units = parseInt(document.getElementById('buy-units').value, 10);
  const date = document.getElementById('buy-date').value;
  if (!code) { alert('銘柄コードを入力してください'); return; }
  if (!price || price <= 0) { alert('購入価格を入力してください'); return; }
  if (!units || units <= 0) { alert('単元数を入力してください'); return; }
  const items = loadPurchases();
  items.push({
    id: String(Date.now()), code: code,
    name: stockName(code) || '',
    price: price, units: units, date: date, status: 'holding'
  });
  savePurchases(items);
  closeBuy();
  renderPurchases();
  const tb = document.querySelector('.tabbtn[data-tab="buy"]');
  if (tb) tb.click();
}

/* ---------- チャート描画（ローソク足＋MA5/25＋出来高） ---------- */
function openChart(code, line) {
  const p = PRICES && PRICES[code];
  const overlay = document.getElementById('chart-overlay');
  document.getElementById('chart-title-text').textContent =
    code + ' ' + (p ? p.name : '') + (line ? '（橙線=購入価格）' : '');
  overlay.classList.add('show');
  const canvas = document.getElementById('chart-canvas');
  const note = document.getElementById('chart-note');
  if (!p) {
    const g = canvas.getContext('2d');
    g.clearRect(0, 0, canvas.width, canvas.height);
    note.textContent = 'この銘柄の株価データがありません（ユニバース外、またはprices.json未読込）。';
    return;
  }
  note.textContent = '直近' + p.c.length + '営業日 / 青線=MA25 黄線=MA5 / 最終日: ' + p.d[p.d.length - 1];
  drawChart(canvas, p, line);
}
function closeChart() { document.getElementById('chart-overlay').classList.remove('show'); }

function sma(arr, n) {
  const out = new Array(arr.length).fill(null);
  let sum = 0;
  for (let i = 0; i < arr.length; i++) {
    sum += arr[i];
    if (i >= n) sum -= arr[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

function drawChart(canvas, p, line) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const g = canvas.getContext('2d');
  g.scale(dpr, dpr);
  g.clearRect(0, 0, W, H);

  const n = p.c.length;
  const padL = 46, padR = 8, padT = 8;
  const volH = H * 0.16, gap = 6;
  const priceH = H - volH - gap - padT - 16;
  const plotW = W - padL - padR;

  let lo = Math.min.apply(null, p.l), hi = Math.max.apply(null, p.h);
  if (line) { lo = Math.min(lo, line); hi = Math.max(hi, line); }
  const range = (hi - lo) || 1;
  lo -= range * 0.04; hi += range * 0.04;
  const y = v => padT + (hi - v) / (hi - lo) * priceH;
  const x = i => padL + (i + 0.5) / n * plotW;
  const cw = Math.max(1.5, plotW / n * 0.62);

  g.strokeStyle = '#21262d'; g.fillStyle = '#8b949e';
  g.font = '10px sans-serif'; g.textAlign = 'right';
  for (let k = 0; k <= 4; k++) {
    const v = lo + (hi - lo) * k / 4, yy = y(v);
    g.beginPath(); g.moveTo(padL, yy); g.lineTo(W - padR, yy); g.stroke();
    g.fillText(Math.round(v).toLocaleString(), padL - 4, yy + 3);
  }
  g.textAlign = 'center';
  const step = Math.max(1, Math.floor(n / 5));
  for (let i = 0; i < n; i += step) g.fillText(p.d[i], x(i), H - 4);

  const vmax = Math.max.apply(null, p.v) || 1;
  const vy0 = padT + priceH + gap;
  for (let i = 0; i < n; i++) {
    g.fillStyle = p.c[i] >= p.o[i] ? 'rgba(38,166,154,.45)' : 'rgba(239,83,80,.45)';
    const vh = p.v[i] / vmax * volH;
    g.fillRect(x(i) - cw / 2, vy0 + volH - vh, cw, vh);
  }

  for (let i = 0; i < n; i++) {
    const up = p.c[i] >= p.o[i];
    g.strokeStyle = g.fillStyle = up ? '#26a69a' : '#ef5350';
    g.beginPath(); g.moveTo(x(i), y(p.h[i])); g.lineTo(x(i), y(p.l[i])); g.stroke();
    const top = y(Math.max(p.o[i], p.c[i])), bot = y(Math.min(p.o[i], p.c[i]));
    g.fillRect(x(i) - cw / 2, top, cw, Math.max(1, bot - top));
  }

  [[sma(p.c, 5), '#e3b341'], [sma(p.c, 25), '#58a6ff']].forEach(pair => {
    const ma = pair[0], col = pair[1];
    g.strokeStyle = col; g.lineWidth = 1.4; g.beginPath();
    let started = false;
    for (let i = 0; i < n; i++) {
      if (ma[i] === null) continue;
      if (!started) { g.moveTo(x(i), y(ma[i])); started = true; }
      else g.lineTo(x(i), y(ma[i]));
    }
    g.stroke(); g.lineWidth = 1;
  });

  if (line) {
    g.strokeStyle = '#f0883e'; g.setLineDash([5, 4]); g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(padL, y(line)); g.lineTo(W - padR, y(line)); g.stroke();
    g.setLineDash([]); g.lineWidth = 1;
    g.fillStyle = '#f0883e'; g.textAlign = 'left';
    g.fillText('買 ' + Math.round(line).toLocaleString(), padL + 2, y(line) - 4);
  }
}

/* ---------- イベント委譲 ---------- */
document.addEventListener('click', e => {
  const cb = e.target.closest('.chartbtn');
  if (cb) { openChart(cb.dataset.code, parseFloat(cb.dataset.line || '') || null); return; }
  const bb = e.target.closest('.buybtn');
  if (bb) { openBuy(bb.dataset.code, bb.dataset.name, parseFloat(bb.dataset.in || '') || ''); return; }
});
document.getElementById('chart-overlay').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeChart();
});
document.getElementById('buy-overlay').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeBuy();
});

/* ---------- タブ切替 ---------- */
document.querySelectorAll('.tabbtn').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.tabbtn').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.tabpanel').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  document.getElementById('tab-' + b.dataset.tab).classList.add('active');
  try { localStorage.setItem('kabu_tab', b.dataset.tab); } catch (e) {}
}));
try {
  const t = localStorage.getItem('kabu_tab');
  if (t && t !== 'cand') {
    const b = document.querySelector('.tabbtn[data-tab="' + t + '"]');
    if (b) b.click();
  }
} catch (e) {}

/* ---------- 株価データ読込 ---------- */
fetch(PRICES_URL)
  .then(r => r.json())
  .then(p => { PRICES = p; renderPurchases(); })
  .catch(() => {
    renderPurchases();
    const el = document.getElementById('prices-warn');
    el.textContent = '⚠ 株価データ(prices.json)を読み込めませんでした。チャート・現在値は表示されません（ローカルで開いている場合は python -m http.server 経由で開いてください）。';
    el.style.display = 'block';
  });
</script>
"""


def build_html(ctx: dict) -> str:
    today = ctx["date"]
    gen_time = ctx.get("generated_at", "")
    gate = ctx["gate"]
    candidates = ctx["candidates"]
    holdings = ctx["holdings"]
    review = ctx["review"]
    errors = ctx.get("errors", [])
    risk_pct = ctx.get("risk_per_trade_pct", 1.0)
    max_pos = ctx.get("max_positions", 5)

    error_banner = ""
    if errors:
        error_banner = (
            f'<div class="errbar">⚠ データ取得失敗 {len(errors)}銘柄 '
            f'（前日キャッシュで代替の可能性）: {_esc(", ".join(errors[:15]))}'
            f'{"…" if len(errors) > 15 else ""}</div>'
        )

    if gate["status"] == "NG":
        cards_html = ('<div class="seemikakuri">⛔ 本日は地合いNGのため「見送り」推奨。'
                      '以下は参考候補（IN非推奨）。</div>')
    else:
        cards_html = ""
    if candidates:
        cards_html += "".join(_candidate_card(c, i + 1)
                              for i, c in enumerate(candidates[:10]))
    else:
        cards_html += '<p class="muted">本日の条件を満たす新規候補はありません。</p>'

    js_data = json.dumps([
        {"code": c["code"], "in": c["in_price"], "stop": c["stop"]}
        for c in candidates[:10]
    ], ensure_ascii=False)

    script = SCRIPT.replace("__RISK__", str(risk_pct)).replace("__CANDS__", js_data)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="manifest.json">
<link rel="apple-touch-icon" href="icons/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>株レポ {today} {gen_time}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>■ {today} レポート <span class="muted" style="font-size:.78rem">更新 {gen_time}</span></h1>
  {error_banner}
  <div class="errbar" id="prices-warn" style="display:none"></div>
  {_gate_banner(gate)}

  <div class="capbox">
    総資金（この端末だけに保存）:
    <input id="capital" type="number" inputmode="numeric" placeholder="例 3000000"> 円
    <span class="muted">→ 許容損失 {risk_pct}% / 同時保有上限 {max_pos}銘柄で株数を再計算</span>
  </div>

  <nav class="tabs">
    <button class="tabbtn active" data-tab="cand">📋 候補</button>
    <button class="tabbtn" data-tab="buy">🛒 購入一覧</button>
    <button class="tabbtn" data-tab="etc">📊 保有・検証</button>
  </nav>

  <section class="tabpanel active" id="tab-cand">
    <h2>■ 新規候補</h2>
    {cards_html}
  </section>

  <section class="tabpanel" id="tab-buy">
    <h2 id="purchases-h2">■ 購入一覧（この端末だけに保存）</h2>
    <div id="purchase-list"></div>
    <div class="btnrow">
      <button class="btn buybtn" data-code="" data-name="" data-in="">＋ 候補以外の銘柄を手動で購入登録</button>
    </div>
  </section>

  <section class="tabpanel" id="tab-etc">
    {_holdings_section(holdings)}
    {_review_section(review)}
  </section>

  <footer>
    ※本ツールは候補提示であり投資助言ではありません。最終判断は自分で行い、
    実発注前に証券会社アプリで現値を確認してください。無料データは遅延・欠損があり得ます。<br>
    購入記録・総資金はこの端末のブラウザ内(localStorage)にのみ保存され、公開されません。<br>
    生成: {today}
  </footer>
</div>

<div id="chart-overlay">
  <div id="chart-box">
    <div id="chart-title"><span id="chart-title-text"></span>
      <button id="chart-close" onclick="closeChart()">✕</button></div>
    <canvas id="chart-canvas"></canvas>
    <div id="chart-note"></div>
  </div>
</div>

<div id="buy-overlay">
  <div id="buy-box">
    <h3>🛒 購入登録 <span class="muted" id="buy-name"></span></h3>
    <label>銘柄コード</label><input id="buy-code" inputmode="numeric" placeholder="例 7203">
    <label>購入価格（円）</label><input id="buy-price" type="number" inputmode="decimal">
    <label>単元数（1単元=100株）</label><input id="buy-units" type="number" inputmode="numeric" value="1" min="1">
    <label>購入日</label><input id="buy-date" type="date">
    <div class="btnrow">
      <button class="btn" onclick="closeBuy()">キャンセル</button>
      <button class="btn buy" onclick="submitBuy()">登録する</button>
    </div>
  </div>
</div>
{script}
</body>
</html>"""


def save_prices_json(data: dict, universe: list, cfg: dict, days: int = 75) -> str:
    """チャート・現在値用の公開株価データ（日足）をプロジェクト直下に保存。

    公開されるのは株価という公開情報のみ（個人の購入記録は含まない＝秘匿方針）。
    """
    from . import config as configmod
    name_map = dict(universe)
    out = {}
    for code, df in data.items():
        if df is None or df.empty:
            continue
        d = df.tail(days)
        out[str(code)] = {
            "name": name_map.get(code, ""),
            "d": [idx.strftime("%m/%d") for idx in d.index],
            "o": [round(float(v), 1) for v in d["Open"]],
            "h": [round(float(v), 1) for v in d["High"]],
            "l": [round(float(v), 1) for v in d["Low"]],
            "c": [round(float(v), 1) for v in d["Close"]],
            "v": [int(v) for v in d["Volume"]],
        }
    path = configmod.ROOT / "prices.json"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    return str(path)


def save_report(ctx: dict, cfg: dict) -> tuple[str, str]:
    """レポートHTMLを reports/YYYY-MM-DD.html と index.html に保存。"""
    html_str = build_html(ctx)
    reports_dir = Path(cfg["paths"]["reports_dir"])
    dated = reports_dir / f"{ctx['date']}.html"
    dated.write_text(html_str, encoding="utf-8")
    # index.html はプロジェクト直下（PWAの起点）
    from . import config as configmod
    index = configmod.ROOT / "index.html"
    index.write_text(html_str, encoding="utf-8")
    return str(dated), str(index)
