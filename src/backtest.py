"""過去データによるシグナル検証（バックテスト）。

実運用の答え合わせ(history)が貯まるまでの間も、過去数年の日足で
「各シグナル系統が発生した後のリターン」を集計して重み調整の参考にする。

注意:
- 現在のユニバース構成での検証のため生存者バイアスあり（あくまで目安）
- カタリスト系（適時開示）は過去データが無料入手できないため対象外
- 「基準（全営業日）」行と比べて優位性があるかを見る
"""
from __future__ import annotations

import pandas as pd

from . import indicators as ind


def _masks(df: pd.DataFrame, cfg: dict) -> dict:
    """ライブ版 signals.analyze と同等の条件をベクトル化して全日分の発生マスクを作る。"""
    s = cfg["signals"]
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    volr = vol / vol.rolling(20).mean()
    m = {}

    # ②出来高・需給
    vmask = volr >= s["volume_surge_ratio"]
    brk = close >= high.rolling(s["breakout_lookback"]).max().shift(1)
    m["volume"] = (vmask | brk)

    # ③テクニカル
    rsi = ind.rsi(close, s["rsi_period"])
    rsi_up30 = (rsi.shift(1) < s["rsi_oversold"]) & (rsi >= s["rsi_oversold"])
    rsi_up50 = (rsi.shift(1) < s["rsi_trend"]) & (rsi >= s["rsi_trend"])
    macd_line, sig_line, _ = ind.macd(
        close, s["macd_fast"], s["macd_slow"], s["macd_signal"])
    macd_gc = (macd_line.shift(1) <= sig_line.shift(1)) & (macd_line > sig_line)
    ma_s = ind.sma(close, s["ma_short"])
    ma_m = ind.sma(close, s["ma_mid"])
    ma_l = ind.sma(close, s["ma_long"])
    ma_gc = (ma_s.shift(1) <= ma_m.shift(1)) & (ma_s > ma_m)
    upper, mid, lower, width = ind.bollinger(close, s["bb_period"], s["bb_std"])
    squeeze = (width <= width.rolling(s["bb_period"]).mean() * s["bb_squeeze_pct"]) \
        & (close > mid)
    po = (ma_s > ma_m) & (ma_m > ma_l) & (ma_s > ma_s.shift(5))
    m["tech"] = (rsi_up30 | rsi_up50 | macd_gc | ma_gc | squeeze | po)

    # ⑦アノマリー（52週高値圏）
    m["anomaly"] = close >= close.rolling(240).max() * 0.995

    # アルゴ痕跡（蓄積検知）
    rng = (high - low) / close * 100
    quiet = (rng <= s["accumulation_range_pct"]) & \
            (volr >= s["accumulation_vol_ratio"])
    ad = s["accumulation_days"]
    m["algo"] = (quiet.rolling(ad).sum() >= max(3, ad - 1)) & \
                (close >= close.shift(ad))
    return m


def _agg(name: str, series_list: list) -> dict | None:
    allr = pd.concat(series_list) if series_list else pd.Series(dtype=float)
    allr = allr.dropna()
    if len(allr) == 0:
        return None
    return {"system": name, "n": int(len(allr)),
            "avg_ret": round(float(allr.mean()) * 100, 2),
            "win_rate": round(float((allr > 0).mean()) * 100, 0)}


def run(data: dict, cfg: dict, warmup: int = 220) -> dict:
    """全ユニバースでバックテストを実行し、系統別の統計を返す。"""
    horizons = cfg["review"]["horizons_days"]
    h0 = horizons[0]
    stats: dict = {}
    base = []
    span = [None, None]

    for code, df in data.items():
        if df is None or len(df) < warmup + 30:
            continue
        close = df["Close"]
        fwd = close.shift(-h0) / close - 1
        masks = _masks(df, cfg)
        valid = df.index[warmup:len(df) - h0]
        if len(valid) == 0:
            continue
        span[0] = valid[0] if span[0] is None else min(span[0], valid[0])
        span[1] = valid[-1] if span[1] is None else max(span[1], valid[-1])
        fv = fwd.loc[valid]
        base.append(fv)
        count = None
        for sysname, mask in masks.items():
            mv = mask.loc[valid].fillna(False).astype(bool)
            stats.setdefault(sysname, []).append(fv[mv])
            count = mv.astype(int) if count is None else count + mv.astype(int)
        if count is not None:
            stats.setdefault("combo2", []).append(fv[count >= 2])

    rows = []
    for sysname in ["combo2", "volume", "tech", "anomaly", "algo"]:
        r = _agg(sysname, stats.get(sysname, []))
        if r:
            rows.append(r)
    return {
        "horizon": h0,
        "rows": rows,
        "baseline": _agg("baseline", base),
        "from": str(span[0].date()) if span[0] is not None else "",
        "to": str(span[1].date()) if span[1] is not None else "",
    }
