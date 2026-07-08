"""保有銘柄チェック（出口判定）。holdings.csv があれば毎朝の判定を出す。

holdings.csv 列: code,name,in_price,shares,in_date,stop,in_reason
  stop は空欄可（空ならATRから自動算出）。in_date は YYYY-MM-DD。
※このファイルはローカル専用。公開ページには載せない（構想書の秘匿方針）。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from . import indicators as ind
from . import config as configmod


def _holdings_path() -> Path:
    return configmod.ROOT / "holdings.csv"


def check(data: dict, cfg: dict) -> list:
    """保有銘柄ごとに 継続/利確/撤退 を判定して返す。"""
    p = _holdings_path()
    if not p.exists():
        return []
    hold = pd.read_csv(p, dtype={"code": str})
    ex = cfg["exit"]
    out = []
    for _, row in hold.iterrows():
        code = str(row["code"]).strip()
        df = data.get(code)
        if df is None or len(df) == 0:
            out.append({"code": code, "name": row.get("name", code),
                        "judgment": "データなし", "detail": "日足取得失敗"})
            continue
        close = float(df["Close"].iloc[-1])
        in_price = float(row["in_price"])
        atr_val = float(ind.atr(df, cfg["signals"]["atr_period"]).iloc[-1])
        stop = row.get("stop")
        if pd.isna(stop) or stop == "" or stop is None:
            stop = in_price - atr_val * ex["stop_atr_mult"]
        else:
            stop = float(stop)
        target = in_price + atr_val * ex["target_atr_mult"]
        pnl_pct = (close / in_price - 1) * 100

        # 保有営業日数
        held_days = None
        try:
            in_dt = pd.Timestamp(row["in_date"]).normalize()
            held_days = int((df.index.normalize() >= in_dt).sum())
        except Exception:
            held_days = None

        # 判定
        if close <= stop:
            judgment, detail = "撤退（損切り）", f"終値{close:.0f}が損切りライン{stop:.0f}以下"
        elif close >= target:
            judgment, detail = "利確検討", f"目標{target:.0f}到達（半分利確＋残りトレール）"
        elif held_days is not None and held_days >= ex["time_stop_days"] and abs(pnl_pct) < 3:
            judgment, detail = "撤退（時間切れ）", f"横ばい{held_days}営業日（資金効率）"
        else:
            judgment, detail = "継続", f"損切りまで余裕（{(close-stop)/close*100:.1f}%）"

        out.append({
            "code": code, "name": row.get("name", code),
            "close": round(close, 1), "in_price": round(in_price, 1),
            "pnl_pct": round(pnl_pct, 1), "stop": round(stop, 1),
            "target": round(target, 1), "held_days": held_days,
            "judgment": judgment, "detail": detail,
        })
    return out
