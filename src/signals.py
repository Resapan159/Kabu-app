"""シグナル検出。1銘柄の日足からシグナルを検出し、根拠系統ごとに分類する。

根拠系統（構想書 ①〜⑦ に対応。Phase1は日足＋出来高で可能なものを実装）:
  volume  = ②需給・出来高系
  tech    = ③テクニカル系
  anomaly = ⑦統計・アノマリー系（52週高値モメンタム等）
  algo    = アルゴ痕跡（蓄積検知）… 構想書コア機能2の日足で可能な部分
（①カタリスト/④信用需給/⑥業績はPhase2で追加）
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class Analysis:
    code: str
    name: str
    close: float
    volume_ratio: float          # 当日出来高 ÷ 20日平均
    turnover_yen: float          # 20日平均売買代金
    atr: float
    hits: list[dict] = field(default_factory=list)   # {system, label, detail}
    systems: set = field(default_factory=set)
    # 出口の目安
    in_price: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    liquid: bool = False
    excluded_reason: str = ""


def _add(a: Analysis, system: str, label: str, detail: str = ""):
    a.hits.append({"system": system, "label": label, "detail": detail})
    a.systems.add(system)


def analyze(df: pd.DataFrame, code: str, name: str, cfg: dict) -> Analysis | None:
    """1銘柄を分析。データ不足なら None。"""
    s = cfg["signals"]
    if df is None or len(df) < max(s["ma_mid"], s["breakout_lookback"], 60) + 5:
        return None

    close = df["Close"]
    vol = df["Volume"]
    last = df.iloc[-1]
    last_close = float(close.iloc[-1])

    vol_ma20 = vol.rolling(20).mean().iloc[-1]
    vol_ratio = float(vol.iloc[-1] / vol_ma20) if vol_ma20 and vol_ma20 > 0 else 0.0
    turnover = float((close * vol).rolling(20).mean().iloc[-1])
    atr_series = ind.atr(df, s["atr_period"])
    atr_val = float(atr_series.iloc[-1])

    a = Analysis(
        code=code, name=name, close=last_close,
        volume_ratio=round(vol_ratio, 2),
        turnover_yen=turnover, atr=atr_val,
    )

    # ---- 流動性・リスクフィルタ（除外条件） ----
    liq = cfg["liquidity"]
    if turnover < liq["hard_exclude_below_yen"]:
        a.excluded_reason = "流動性不足(売買代金<1億円/日)"
        return a
    a.liquid = turnover >= liq["min_turnover_yen"]
    if not a.liquid:
        a.excluded_reason = f"売買代金不足(<{liq['min_turnover_yen']/1e8:.0f}億円/日)"

    # ===== ②需給・出来高系 =====
    if vol_ratio >= s["volume_surge_ratio"]:
        strong = vol_ratio >= s["strong_volume_ratio"]
        _add(a, "volume", "出来高急増",
             f"出来高が20日平均比 {vol_ratio:.1f}倍" + ("（大商い）" if strong else ""))
    # 価格を伴う出来高増（上昇＋大商い）
    up_day = last_close > float(close.iloc[-2])
    if up_day and vol_ratio >= s["volume_surge_ratio"]:
        _add(a, "volume", "価格を伴う出来高増",
             "陽線＋大商い（本物のブレイク候補）")
    # ボックス上限ブレイク（直近N日高値更新）
    lookback = s["breakout_lookback"]
    prior_high = df["High"].iloc[-(lookback + 1):-1].max()
    if last_close >= prior_high:
        _add(a, "volume", f"{lookback}日高値ブレイク",
             f"直近{lookback}日高値({prior_high:.0f})を上抜け")

    # ===== ③テクニカル系 =====
    rsi = ind.rsi(close, s["rsi_period"])
    rsi_now = float(rsi.iloc[-1])
    rsi_prev = float(rsi.iloc[-2])
    if rsi_prev < s["rsi_oversold"] <= rsi_now:
        _add(a, "tech", "RSI売られすぎ反転",
             f"RSI {rsi_prev:.0f}→{rsi_now:.0f}（{s['rsi_oversold']}割れから反発）")
    elif rsi_prev < s["rsi_trend"] <= rsi_now:
        _add(a, "tech", "RSI 50超え",
             f"RSI {rsi_now:.0f}（トレンド転換の目安）")

    macd_line, sig_line, hist = ind.macd(
        close, s["macd_fast"], s["macd_slow"], s["macd_signal"])
    gc_macd = ind.cross_up(macd_line, sig_line)
    if ind.recent_true(gc_macd, s["golden_cross_within_days"]):
        near_zero = abs(float(macd_line.iloc[-1])) < atr_val  # 0ライン付近=信頼度高
        _add(a, "tech", "MACDゴールデンクロス",
             "直近でGC" + ("（0ライン付近・信頼度高）" if near_zero else ""))

    ma_s = ind.sma(close, s["ma_short"])
    ma_m = ind.sma(close, s["ma_mid"])
    gc_ma = ind.cross_up(ma_s, ma_m)
    if ind.recent_true(gc_ma, s["golden_cross_within_days"]):
        _add(a, "tech", f"{s['ma_short']}/{s['ma_mid']}日ゴールデンクロス",
             "中期トレンド転換シグナル")

    upper, mid, lower, width = ind.bollinger(close, s["bb_period"], s["bb_std"])
    width_ma = width.rolling(s["bb_period"]).mean().iloc[-1]
    if pd.notna(width_ma) and width.iloc[-1] <= width_ma * s["bb_squeeze_pct"] \
            and last_close > float(mid.iloc[-1]):
        _add(a, "tech", "BBスクイーズ",
             "バンド幅縮小→エクスパンション初動の可能性")

    # パーフェクトオーダー（短期>中期>長期 かつ 右肩上がり）
    ma_l = ind.sma(close, s["ma_long"])
    if pd.notna(ma_l.iloc[-1]):
        if ma_s.iloc[-1] > ma_m.iloc[-1] > ma_l.iloc[-1] and \
                ma_s.iloc[-1] > ma_s.iloc[-5]:
            _add(a, "tech", "パーフェクトオーダー",
                 f"{s['ma_short']}>{s['ma_mid']}>{s['ma_long']}日線の上昇配列")

    # ===== ⑦統計・アノマリー系（52週高値モメンタム） =====
    if len(close) >= 240:
        high_52w = close.iloc[-240:].max()
        if last_close >= high_52w * 0.995:
            _add(a, "anomaly", "52週高値圏",
                 "モメンタム継続の統計的優位（52週高値更新圏）")

    # ===== アルゴ痕跡: 蓄積検知（執行アルゴの買い集め疑い） =====
    ad = s["accumulation_days"]
    recent = df.iloc[-ad:]
    day_range_pct = (recent["High"] - recent["Low"]) / recent["Close"] * 100
    vol_ratio_series = (vol / vol.rolling(20).mean()).iloc[-ad:]
    quiet_but_heavy = (day_range_pct <= s["accumulation_range_pct"]) & \
                      (vol_ratio_series >= s["accumulation_vol_ratio"])
    if quiet_but_heavy.sum() >= max(3, ad - 1) and last_close >= float(close.iloc[-ad]):
        _add(a, "algo", "蓄積検知",
             "出来高増なのに値動き小＝VWAP執行による買い集め疑い")

    # ---- 出口の目安（ATRベース） ----
    ex = cfg["exit"]
    a.in_price = round(last_close, 1)
    a.stop = round(last_close - atr_val * ex["stop_atr_mult"], 1)
    a.target = round(last_close + atr_val * ex["target_atr_mult"], 1)
    return a
