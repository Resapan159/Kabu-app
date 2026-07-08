"""スマホ対応HTMLレポート生成（モバイルファースト・ダークモード）。

構想書のUI方針: 単一HTML、銘柄カードをタップで根拠を展開、ダークモード対応。
総資金はスマホ側localStorageのみに保存し、株数をクライアント側で再計算する。
"""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path


def _esc(s) -> str:
    return html.escape(str(s))


def _gate_banner(gate: dict) -> str:
    status = gate["status"]
    color = {"OK": "#1f9d55", "WARN": "#c98a00", "NG": "#c0392b"}[status]
    icon = {"OK": "✅", "WARN": "⚠️", "NG": "⛔"}[status]
    m = gate["metrics"]
    metric_txt = " / ".join(filter(None, [
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
    return f"""
    <details class="card{' gated-card' if gated else ''}" data-code="{_esc(c['code'])}"
             data-in="{c['in_price']}" data-stop="{c['stop']}">
      <summary>
        <div class="card-head">
          <span class="rank">{rank}</span>
          <span class="code">{_esc(c['code'])}</span>
          <span class="name">{_esc(c['name'])}</span>
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
          <div><span class="k">株数目安</span><span class="v shares" data-code="{_esc(c['code'])}">{shares_line}</span></div>
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
    return f'<h2>■ 保有銘柄チェック</h2><div class="holds">{rows}</div>'


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


def build_html(ctx: dict) -> str:
    today = ctx["date"]
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

    # クライアント側の株数再計算用データ
    js_data = json.dumps([
        {"code": c["code"], "in": c["in_price"], "stop": c["stop"]}
        for c in candidates[:10]
    ], ensure_ascii=False)

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
<title>朝のピックアップ {today}</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family:-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;
  background:#0d1117; color:#e6edf3; line-height:1.6; padding-bottom:40px; }}
.wrap {{ max-width:560px; margin:0 auto; padding:12px; }}
h1 {{ font-size:1.15rem; margin:8px 0; }}
h2 {{ font-size:1rem; margin:22px 0 8px; border-left:4px solid #2d7dd2; padding-left:8px; }}
.muted {{ color:#8b949e; font-size:.85rem; }}
.banner {{ border-radius:12px; padding:12px 14px; color:#fff; margin:10px 0; }}
.banner-top {{ font-weight:700; font-size:1.05rem; }}
.banner-metrics {{ font-size:.9rem; opacity:.95; margin-top:2px; }}
.banner-reasons {{ font-size:.8rem; opacity:.9; margin-top:4px; }}
.errbar {{ background:#5a3a00; color:#ffd479; border-radius:8px; padding:8px 10px;
  font-size:.8rem; margin:8px 0; }}
.seemikakuri {{ background:#3a1414; color:#ffb3b3; border-radius:8px; padding:10px;
  font-size:.9rem; margin:8px 0; }}
.capbox {{ background:#161b22; border:1px solid #30363d; border-radius:10px;
  padding:10px 12px; margin:10px 0; font-size:.85rem; }}
.capbox input {{ width:120px; background:#0d1117; color:#e6edf3; border:1px solid #30363d;
  border-radius:6px; padding:4px 8px; font-size:.9rem; }}
.card {{ background:#161b22; border:1px solid #30363d; border-radius:12px;
  margin:10px 0; overflow:hidden; }}
.card[open] {{ border-color:#2d7dd2; }}
.gated-card {{ opacity:.7; }}
summary {{ list-style:none; cursor:pointer; padding:12px; }}
summary::-webkit-details-marker {{ display:none; }}
.card-head {{ display:flex; align-items:center; gap:8px; }}
.rank {{ background:#2d7dd2; color:#fff; border-radius:50%; width:22px; height:22px;
  display:flex; align-items:center; justify-content:center; font-size:.8rem; font-weight:700; }}
.code {{ font-family:monospace; color:#8b949e; }}
.name {{ font-weight:700; flex:1; }}
.score {{ background:#233; color:#7ee787; font-weight:700; padding:2px 8px;
  border-radius:6px; font-size:.9rem; }}
.card-sub {{ margin-top:6px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
.tag {{ background:#1f2d3d; color:#79c0ff; border-radius:5px; padding:1px 7px; font-size:.72rem; }}
.card-body {{ padding:0 12px 12px; border-top:1px solid #30363d; }}
.gated {{ color:#ffb3b3; font-size:.85rem; margin:8px 0; }}
.hits {{ margin:10px 0; padding-left:18px; font-size:.85rem; }}
.hits li {{ margin:3px 0; }}
.levels {{ display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:8px; }}
.levels > div {{ background:#0d1117; border-radius:8px; padding:6px 8px; }}
.levels .k {{ display:block; color:#8b949e; font-size:.72rem; }}
.levels .v {{ font-weight:700; }}
.holds .hold {{ background:#161b22; border:1px solid #30363d; border-radius:10px;
  padding:10px; margin:8px 0; }}
.hold-head {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
.hold .pnl {{ font-weight:700; }}
.judge {{ color:#fff; border-radius:6px; padding:2px 8px; font-size:.78rem; }}
.hold-detail {{ margin-top:4px; }}
table.rev {{ width:100%; border-collapse:collapse; font-size:.82rem; margin-top:6px; }}
table.rev th, table.rev td {{ border-bottom:1px solid #30363d; padding:5px; text-align:center; }}
table.rev th {{ color:#8b949e; }}
footer {{ margin-top:26px; font-size:.72rem; color:#8b949e; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>■ {today} 朝のピックアップ</h1>
  {error_banner}
  {_gate_banner(gate)}

  <div class="capbox">
    総資金（この端末だけに保存）:
    <input id="capital" type="number" inputmode="numeric" placeholder="例 3000000"> 円
    <span class="muted">→ 許容損失 {risk_pct}% / 同時保有上限 {max_pos}銘柄で株数を再計算</span>
  </div>

  <h2>■ 新規候補</h2>
  {cards_html}

  {_holdings_section(holdings)}

  {_review_section(review)}

  <footer>
    ※本ツールは候補提示であり投資助言ではありません。最終判断は自分で行い、
    実発注前に証券会社アプリで現値を確認してください。無料データは遅延・欠損があり得ます。<br>
    生成: {today}
  </footer>
</div>
<script>
const RISK_PCT = {risk_pct};
const CANDS = {js_data};
const capEl = document.getElementById('capital');
function fmt(n) {{ return n.toLocaleString('ja-JP'); }}
function recalc() {{
  const cap = parseFloat(capEl.value);
  CANDS.forEach(c => {{
    const el = document.querySelector('.shares[data-code="'+c.code+'"]');
    if (!el) return;
    if (!cap || cap <= 0) return;
    const risk = cap * RISK_PCT / 100;
    const per = Math.max(c.in - c.stop, 0.01);
    const shares = Math.floor((risk / per) / 100) * 100;
    if (shares > 0) el.textContent = shares + '株（コスト約' + fmt(Math.round(shares*c.in)) + '円）';
    else el.textContent = '—（値幅が大きく単元に満たない）';
  }});
}}
try {{
  const saved = localStorage.getItem('kabu_capital');
  if (saved) {{ capEl.value = saved; recalc(); }}
}} catch(e) {{}}
capEl.addEventListener('input', () => {{
  try {{ localStorage.setItem('kabu_capital', capEl.value); }} catch(e) {{}}
  recalc();
}});
</script>
</body>
</html>"""


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
