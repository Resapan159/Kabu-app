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


def analyze(df: pd.DataFrame, code: str, name: str, cfg: dict,
            disclosures: list | None = None,
            margin: dict | None = None) -> Analysis | None:
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

    # ===== ①カタリスト系（適時開示） =====
    for d in (disclosures or []):
        rev = d.get("rev_pct")
        rev_txt = f"（利益修正率 {rev:+.1f}%）" if rev is not None else ""
        if d["cls"] == "pos_strong":
            label = f"好材料開示: {d['kw']}{rev_txt}"
            if rev is not None and abs(rev) < 5:
                label = f"材料開示: {d['kw']}{rev_txt}※小幅"
            _add(a, "catalyst", label, f"{d['time']} {d['title'][:48]}")
        elif d["cls"] == "pos":
            _add(a, "catalyst", f"材料開示: {d['kw']}{rev_txt}",
                 f"{d['time']} {d['title'][:48]}")
        elif d["cls"] == "neg":
            a.hits.append({"system": "warn", "label": f"⚠悪材料開示{rev_txt}",
                           "detail": f"{d['time']} {d['title'][:48]}"})
        elif d["cls"] == "earnings":
            a.hits.append({"system": "warn", "label": "決算発表あり",
                           "detail": "決算直後は値動きが荒れやすい（要注意）"})

    # ===== ④信用需給系（週次・JPX信用残） =====
    if margin and margin.get("ratio") is not None:
        ratio = margin["ratio"]
        if ratio < 1.0:
            _add(a, "margin", "信用売り長（踏み上げ候補）",
                 f"信用倍率 {ratio:.2f}倍（売残>買残、ショートカバー圧力）")
        elif ratio < 2.0:
            a.hits.append({"system": "note", "label": "信用倍率 良好",
                           "detail": f"{ratio:.2f}倍（買い残の重さは限定的）"})

    # ---- 出口の目安（ATRベース） ----
    ex = cfg["exit"]
    a.in_price = round(last_close, 1)
    a.stop = round(last_close - atr_val * ex["stop_atr_mult"], 1)
    a.target = round(last_close + atr_val * ex["target_atr_mult"], 1)

    # ---- ヒゲ分析: ストップ狩り帯を避けて損切りを置く（構想書コア機能2） ----
    # 直近10日の安値（下ヒゲの先）がATR損切りラインの少し下にある場合、
    # 逆指値が並ぶその価格帯を「一瞬割ってすぐ戻す」動きに狩られやすい。
    # → ヒゲ安値のさらに下（0.3ATR分）まで損切りを下げて狩り帯を回避する。
    wick_low = float(df["Low"].iloc[-10:].min())
    if a.stop >= wick_low > a.stop - atr_val:
        old_stop = a.stop
        a.stop = round(wick_low - atr_val * 0.3, 1)
        a.hits.append({"system": "note", "label": "ヒゲ分析で損切り調整",
                       "detail": f"直近ヒゲ安値{wick_low:.0f}円の狩り帯を回避 "
                                 f"{old_stop:.0f}→{a.stop:.0f}円"})
    return a


def near_miss(df: pd.DataFrame, code: str, name: str, cfg: dict) -> dict | None:
    """予備軍（もうすぐ候補）判定。条件まであと一歩の銘柄を検出する。"""
    s = cfg["signals"]
    if df is None or len(df) < s["ma_mid"] + 5:
        return None
    close = df["Close"]
    vol = df["Volume"]
    last_close = float(close.iloc[-1])
    turnover = float((close * vol).rolling(20).mean().iloc[-1])
    if turnover < cfg["liquidity"]["min_turnover_yen"]:
        return None

    notes = []
    # ブレイク目前（60日高値まで3%以内）→ 発火すれば②出来高・需給系
    lookback = s["breakout_lookback"]
    prior_high = float(df["High"].iloc[-(lookback + 1):-1].max())
    gap_pct = (prior_high / last_close - 1) * 100
    if 0 < gap_pct <= 3.0:
        notes.append({"text": f"{lookback}日高値まであと{gap_pct:.1f}%（ブレイク目前）",
                      "sys": "volume"})
    # スクイーズ形成中（エネルギー充填）→ 発火すれば③テクニカル系
    upper, mid, lower, width = ind.bollinger(close, s["bb_period"], s["bb_std"])
    width_ma = width.rolling(s["bb_period"]).mean().iloc[-1]
    if pd.notna(width_ma) and float(width.iloc[-1]) <= float(width_ma) * s["bb_squeeze_pct"]:
        notes.append({"text": "BBスクイーズ形成中（ブレイク待ち）", "sys": "tech"})
    # ゴールデンクロス接近 → ③テクニカル系
    ma_s = ind.sma(close, s["ma_short"])
    ma_m = ind.sma(close, s["ma_mid"])
    if pd.notna(ma_s.iloc[-1]) and pd.notna(ma_m.iloc[-1]):
        diff_pct = (float(ma_m.iloc[-1]) / float(ma_s.iloc[-1]) - 1) * 100
        rising = float(ma_s.iloc[-1]) > float(ma_s.iloc[-3])
        if 0 < diff_pct <= 1.5 and rising:
            notes.append({"text": f"GC接近（{s['ma_short']}日線が{s['ma_mid']}日線まで{diff_pct:.1f}%）",
                          "sys": "tech"})
    # 出来高じわ増（急増未満）→ ②出来高・需給系
    vol_ma20 = vol.rolling(20).mean().iloc[-1]
    if vol_ma20 and vol_ma20 > 0:
        vr5 = float(vol.iloc[-5:].mean() / vol_ma20)
        if 1.3 <= vr5 < s["volume_surge_ratio"]:
            notes.append({"text": f"出来高じわ増（5日平均が20日平均比{vr5:.1f}倍）",
                          "sys": "volume"})

    if not notes:
        return None
    return {"code": code, "name": name, "close": last_close,
            "notes": notes, "n": len(notes)}
