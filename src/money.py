"""資金管理。許容損失から購入株数の目安を計算する。

総資金の実額はここに保存しない（構想書: スマホ側localStorageのみ）。
config の reference_capital_yen はレポート表示用のプレースホルダ。
"""
from __future__ import annotations

import math


def position_size(in_price: float, stop: float, cfg: dict,
                  capital_yen: float | None = None) -> dict:
    """株数目安を計算。日本株は単元(100株)前提で丸める。"""
    m = cfg["money"]
    capital = capital_yen if capital_yen is not None else m["reference_capital_yen"]
    risk_yen = capital * m["risk_per_trade_pct"] / 100.0
    per_share_risk = max(in_price - stop, 0.01)
    raw_shares = risk_yen / per_share_risk
    # 単元100株に丸める
    units = math.floor(raw_shares / 100)
    shares = units * 100
    cost = shares * in_price
    return {
        "risk_yen": round(risk_yen),
        "per_share_risk": round(per_share_risk, 1),
        "shares": shares,
        "cost_yen": round(cost),
        "note": "" if shares > 0 else "許容損失に対し値幅が大きく、単元(100株)に満たない",
    }
