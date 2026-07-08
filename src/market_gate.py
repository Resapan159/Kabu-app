"""地合いゲート。日経・為替・SOX・ダウの前日騰落から当日の売買可否を判定する。

構想書の方針: 地合いは「加点」ではなく「ゲート」。悪地合いの日は好材料でもINしない。
判定: OK / WARN / NG（NGなら新規候補は見送り表示）。
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from . import data as datamod


def _pct_change_last(df: pd.DataFrame | None) -> float | None:
    if df is None or len(df) < 2:
        return None
    c = df["Close"]
    return float((c.iloc[-1] / c.iloc[-2] - 1) * 100)


def evaluate(cfg: dict) -> dict:
    """地合いを評価して dict を返す。"""
    mg = cfg["market_gate"]
    result = {"status": "OK", "reasons": [], "metrics": {}}

    nikkei = datamod.fetch_index(mg["nikkei"], cfg)
    usdjpy = datamod.fetch_index(mg["usdjpy"], cfg)
    sox = datamod.fetch_index(mg["sox"], cfg)
    dow = datamod.fetch_index(mg["dow"], cfg)

    nk = _pct_change_last(nikkei)
    sx = _pct_change_last(sox)
    dw = _pct_change_last(dow)
    fx_level = float(usdjpy["Close"].iloc[-1]) if usdjpy is not None and len(usdjpy) else None

    result["metrics"] = {
        "nikkei_pct": None if nk is None else round(nk, 2),
        "sox_pct": None if sx is None else round(sx, 2),
        "dow_pct": None if dw is None else round(dw, 2),
        "usdjpy": None if fx_level is None else round(fx_level, 2),
    }

    # 日経の前日騰落を主判定に使う
    if nk is None:
        result["status"] = "WARN"
        result["reasons"].append("地合いデータ取得失敗（保守的にWARN）")
    elif nk <= mg["ng_threshold_pct"]:
        result["status"] = "NG"
        result["reasons"].append(f"日経 {nk:+.1f}%（大幅安）→ 本日は見送り推奨")
    elif nk <= mg["warn_threshold_pct"]:
        result["status"] = "WARN"
        result["reasons"].append(f"日経 {nk:+.1f}%（軟調）→ 慎重に")
    else:
        result["reasons"].append(f"日経 {nk:+.1f}%")

    # SOX/ダウの大幅安も警告材料
    if sx is not None and sx <= -2.0:
        result["reasons"].append(f"SOX {sx:+.1f}%（半導体軟調）")
        if result["status"] == "OK":
            result["status"] = "WARN"
    if dw is not None and dw <= -2.0:
        result["reasons"].append(f"ダウ {dw:+.1f}%")
        if result["status"] == "OK":
            result["status"] = "WARN"

    # 経済イベント警告
    events = cfg.get("event_dates") or {}
    today = date.today().isoformat()
    if today in events:
        result["reasons"].append(f"⚠本日は {events[today]}（エントリー警告）")
        if result["status"] == "OK":
            result["status"] = "WARN"

    return result
