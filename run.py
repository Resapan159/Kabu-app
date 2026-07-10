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
import sys
from datetime import date, datetime

from src import config as configmod
from src import data as datamod
from src import market_gate
from src import screener
from src import portfolio
from src import history
from src import report


def is_holiday_weekend() -> bool:
    # 土日判定（祝日カレンダーはPhase2で追加）
    return datetime.now().weekday() >= 5


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="キャッシュ無視で再取得")
    parser.add_argument("--no-net", action="store_true", help="ネット取得せずキャッシュのみ")
    parser.add_argument("--config", default=None, help="config.yamlのパス")
    args = parser.parse_args(argv)

    cfg = configmod.load_config(args.config)
    today = date.today().isoformat()

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

    print("[2-3] シグナル検出＆スコアリング ...")
    gate_ok = gate["status"] != "NG"
    candidates = screener.screen(data, universe, cfg, gate_ok=gate_ok)
    print(f"    → 候補 {len(candidates)}銘柄")

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
    }
    dated, index = report.save_report(ctx, cfg)
    print(f"    → {index}")
    print(f"    → {dated}")
    prices_path = report.save_prices_json(data, universe, cfg)
    print(f"    → {prices_path}（チャート用データ）")

    if is_holiday_weekend():
        print("（注: 本日は土日。休場の可能性があります）")
    print("完了。index.html をブラウザ/スマホで開いてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
