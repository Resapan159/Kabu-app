"""スクリーニング統合。全銘柄を分析→必須条件で絞り込み→系統数でスコアリング・順位付け。

スコアリング方針（構想書 v3・簡素化）:
  1. 必須条件: 地合いゲートOK ＋ リスクフィルタ通過 ＋ 流動性確保
  2. 順位付け: 満たした根拠の「系統数」で並べ、同数なら出来高倍率
  3. 重み付けは答え合わせデータが貯まってから（Phase3）
表示スコアは系統数と出来高から算出する 0〜100 の目安値（順位の可視化用）。
"""
from __future__ import annotations

from . import signals as sig
from . import money as moneymod

SYSTEM_LABELS = {
    "catalyst": "①カタリスト（開示）",
    "volume": "②出来高・需給",
    "margin": "④信用需給",
    "tech": "③テクニカル",
    "anomaly": "⑦統計・アノマリー",
    "algo": "アルゴ痕跡",
}


def _display_score(num_systems: int, vol_ratio: float, num_hits: int) -> int:
    """順位可視化用スコア（0-100目安）。系統数を主、出来高とヒット数を従に。"""
    base = num_systems * 22           # 系統数(最大4) → 最大88
    vol_bonus = min(vol_ratio, 5) * 2  # 出来高倍率 → 最大10
    hit_bonus = min(num_hits, 6)       # ヒット数 → 最大6
    return int(min(base + vol_bonus + hit_bonus, 100))


def screen(data: dict, universe: list, cfg: dict, gate_ok: bool,
           disclosures: dict | None = None,
           margin_map: dict | None = None,
           pts_map: dict | None = None) -> list:
    """スクリーニングを実行し、候補リスト（スコア降順）を返す。"""
    name_map = {code: name for code, name in universe}
    candidates = []

    for code, df in data.items():
        name = name_map.get(code, code)
        a = sig.analyze(df, code, name, cfg,
                        disclosures=(disclosures or {}).get(code),
                        margin=(margin_map or {}).get(code))
        if a is None:
            continue
        # 必須条件: リスクフィルタ（除外理由なし）＋ 流動性 ＋ 何らかのシグナル
        if a.excluded_reason and not a.liquid:
            continue
        if not a.liquid:
            continue
        if len(a.systems) == 0:
            continue

        pos = moneymod.position_size(a.in_price, a.stop, cfg)
        candidates.append({
            "code": code,
            "name": name,
            "close": a.close,
            "systems": sorted(a.systems),
            "system_labels": [SYSTEM_LABELS.get(s, s) for s in sorted(a.systems)],
            "num_systems": len(a.systems),
            "hits": a.hits,
            "volume_ratio": a.volume_ratio,
            "turnover_oku": round(a.turnover_yen / 1e8, 1),  # 億円
            "atr": round(a.atr, 1),
            "in_price": a.in_price,
            "stop": a.stop,
            "target": a.target,
            "stop_pct": round((a.stop / a.in_price - 1) * 100, 1) if a.in_price else 0,
            "target_pct": round((a.target / a.in_price - 1) * 100, 1) if a.in_price else 0,
            "position": pos,
            "score": _display_score(len(a.systems), a.volume_ratio, len(a.hits)),
            "gated_out": not gate_ok,   # 地合いNGなら見送り扱いで表示
            "pts": (pts_map or {}).get(code),
        })

    # 順位付け: 系統数 → 出来高倍率
    candidates.sort(key=lambda c: (c["num_systems"], c["volume_ratio"]), reverse=True)
    return candidates


def watchlist(data: dict, universe: list, cfg: dict,
              exclude_codes: set, bt: dict | None = None,
              top_n: int = 8) -> list:
    """予備軍（もうすぐ候補）リスト。候補入りしていない銘柄から検出し、
    バックテスト実績から「発火した場合の期待値」を付与する。"""
    name_map = {code: name for code, name in universe}
    bt_map = {r["system"]: r for r in (bt or {}).get("rows", [])}
    out = []
    for code, df in data.items():
        if code in exclude_codes:
            continue
        w = sig.near_miss(df, code, name_map.get(code, code), cfg)
        if not w:
            continue
        syss = sorted({n["sys"] for n in w["notes"]})
        rets = [bt_map[x]["avg_ret"] for x in syss if x in bt_map]
        wins = [bt_map[x]["win_rate"] for x in syss if x in bt_map]
        if rets:
            w["exp_ret"] = round(sum(rets) / len(rets), 2)
            w["exp_win"] = round(sum(wins) / len(wins), 0)
            # 期待度 0-100: 期待リターンと条件数から算出
            w["expect_score"] = int(min(100, max(0,
                50 + w["exp_ret"] * 15 + (w["n"] - 1) * 15)))
        else:
            w["exp_ret"] = None
            w["exp_win"] = None
            w["expect_score"] = None
        out.append(w)
    out.sort(key=lambda w: (w["expect_score"] or 0, w["n"]), reverse=True)
    return out[:top_n]
