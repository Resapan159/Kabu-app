#!/usr/bin/env python3
"""朝の銘柄ピックアップ・メイン処理（Phase 1）。

使い方:
    python run.py            # 通常実行（キャッシュ活用）
    python run.py --force     # キャッシュ無視で再取得
    python run.py --no-net    # ネット取得せずキャッシュのみ（オフライン確認用）

処理の流れ（構想書コア機能1）:
  [0] 地合いゲート判定 → [1] データ収集 → [2] シグナル検出 → [3] スコアリング
  → [4] 保有銘柄チェック → [5] レポート生成 → ピック履歴記録・答え合わせ
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime

from src import config as configmod
from src import data as datamod
from src import market_gate
from src import screener
from src import portfolio
from src import history
from src import report
from src import disclosures as discmod
from src import backtest as btmod
from src import pts as ptsmod
from src import margin as marginmod


def is_holiday_weekend() -> bool:
    return datetime.now().weekday() >= 5


def is_market_closed() -> bool:
    """東証休場判定（土日・日本の祝日・年末年始）。"""
    today = date.today()
    if is_holiday_weekend():
        return True
    try:
        import jpholiday
        if jpholiday.is_holiday(today):
            return True
    except ImportError:
        pass
    if (today.month == 12 and today.day == 31) or \
            (today.month == 1 and today.day <= 3):
        return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="キャッシュ無視で再取得")
    parser.add_argument("--no-net", action="store_true", help="ネット取得せずキャッシュのみ")
    parser.add_argument("--config", default=None, help="config.yamlのパス")
    args = parser.parse_args(argv)

    cfg = configmod.load_config(args.config)
    today = date.today().isoformat()

    # 休場日はスキップ（自動実行時のみ。手動実行は通常どおり動く）
    if is_market_closed() and os.environ.get("GITHUB_ACTIONS") \
            and os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        print(f"本日({today})は休場のためスキップします。")
        return 0

    if args.no_net:
        # yfinance呼び出しを抑止（キャッシュのみ使用）
        datamod.yf = None

    print(f"[0] 地合いゲート判定 ...")
    gate = market_gate.evaluate(cfg)
    print(f"    → {gate['status']}: {'; '.join(gate['reasons'])}")

    print("[1] データ収集（ユニバース日足）...")
    universe = datamod.load_universe_list(cfg)
    data, failed = datamod.fetch_universe(
        [c for c, _ in universe], cfg, force=args.force)
    print(f"    → 取得 {len(data)}銘柄 / 失敗 {len(failed)}銘柄")

    print("[1b] 適時開示の取得（TDnet）...")
    disc = {} if args.no_net else discmod.fetch([c for c, _ in universe], cfg)
    n_disc = sum(len(v) for v in disc.values())
    print(f"    → ユニバース関連 {n_disc}件")
    if disc:
        n_rev = discmod.enrich_revisions(disc)
        print(f"    → 修正幅PDF解析 {n_rev}件")

    print("[1c] PTS夜間価格（開示銘柄のみ・実験的）...")
    pts_map = {}
    if disc and not args.no_net:
        closes = {c: float(df["Close"].iloc[-1])
                  for c, df in data.items() if df is not None and len(df)}
        pts_map = ptsmod.fetch_for(list(disc.keys()), closes)
    print(f"    → 取得 {len(pts_map)}銘柄")

    print("[1d] 信用需給（JPX週末信用残・実験的）...")
    margin_map = {} if args.no_net else marginmod.fetch(cfg)
    print(f"    → {len(margin_map)}銘柄分")

    print("[2-3] シグナル検出＆スコアリング ...")
    gate_ok = gate["status"] != "NG"
    candidates = screener.screen(data, universe, cfg, gate_ok=gate_ok,
                                 disclosures=disc, margin_map=margin_map,
                                 pts_map=pts_map)
    print(f"    → 候補 {len(candidates)}銘柄")

    print("[検証] バックテスト（過去データ）...")
    bt = btmod.run(data, cfg)
    print(f"    → {bt['from']}〜{bt['to']} / 系統 {len(bt['rows'])}件")

    print("[2b] 予備軍（もうすぐ候補）...")
    watch = screener.watchlist(data, universe, cfg,
                               exclude_codes={c["code"] for c in candidates},
                               bt=bt)
    print(f"    → 予備軍 {len(watch)}銘柄")

    print("[4] 保有銘柄チェック ...")
    holdings = portfolio.check(data, cfg)
    print(f"    → 保有 {len(holdings)}銘柄")

    print("[答え合わせ] 過去ピックの追跡 ...")
    # 地合いNGでも候補は記録（答え合わせの母数確保）。実INは別管理。
    n_new = history.record_picks(candidates, data, cfg, top_n=10)
    review = history.evaluate_history(data, cfg)
    print(f"    → 新規記録 {n_new}件 / 評価済 {review.get('results_count', 0)}件")

    print("[5] レポート生成 ...")
    ctx = {
        "date": today,
        "generated_at": datetime.now().strftime("%H:%M"),
        "gate": gate,
        "candidates": candidates,
        "holdings": holdings,
        "review": review,
        "errors": failed,
        "risk_per_trade_pct": cfg["money"]["risk_per_trade_pct"],
        "max_positions": cfg["money"]["max_positions"],
        "watchlist": watch,
        "disclosures": disc,
        "backtest": bt,
        "pts": pts_map,
    }
    dated, index = report.save_report(ctx, cfg)
    print(f"    → {index}")
    print(f"    → {dated}")
    prices_path = report.save_prices_json(data, universe, cfg)
    print(f"    → {prices_path}（チャート用データ）")
    archive_path = report.save_archive(cfg)
    print(f"    → {archive_path}（過去レポート一覧）")

    if is_holiday_weekend():
        print("（注: 本日は土日。休場の可能性があります）")
    print("完了。index.html をブラウザ/スマホで開いてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
