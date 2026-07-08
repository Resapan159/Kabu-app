"""ピック履歴の記録と答え合わせ（シグナル検証）。

構想書 Phase1 の要: ピックした銘柄を自動追跡し、5日後・10日後の騰落率を記録。
効かないシグナルの除外・重み調整の唯一の根拠になるため初日から記録する。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

PICKS_COLS = ["pick_date", "ref_date", "code", "name",
              "ref_close", "score", "num_systems", "systems"]


def _picks_path(cfg: dict) -> Path:
    return Path(cfg["paths"]["history_dir"]) / "picks.csv"


def _results_path(cfg: dict) -> Path:
    return Path(cfg["paths"]["history_dir"]) / "results.csv"


def load_picks(cfg: dict) -> pd.DataFrame:
    p = _picks_path(cfg)
    if p.exists():
        return pd.read_csv(p, dtype={"code": str})
    return pd.DataFrame(columns=PICKS_COLS)


def record_picks(candidates: list, data: dict, cfg: dict, top_n: int = 10) -> int:
    """本日のトップN候補をpicks.csvに追記。同日・同銘柄の重複は記録しない。"""
    picks = load_picks(cfg)
    today = date.today().isoformat()
    existing = set(zip(picks.get("pick_date", []), picks.get("code", [])))

    rows = []
    for c in candidates[:top_n]:
        key = (today, c["code"])
        if key in existing:
            continue
        df = data.get(c["code"])
        ref_date = str(df.index[-1].date()) if df is not None and len(df) else today
        rows.append({
            "pick_date": today,
            "ref_date": ref_date,
            "code": c["code"],
            "name": c["name"],
            "ref_close": c["close"],
            "score": c["score"],
            "num_systems": c["num_systems"],
            "systems": "|".join(c["systems"]),
        })
    if rows:
        new_df = pd.DataFrame(rows)
        out = new_df if len(picks) == 0 else pd.concat([picks, new_df], ignore_index=True)
        out.to_csv(_picks_path(cfg), index=False)
    return len(rows)


def _forward_return(df: pd.DataFrame, ref_date: str, horizon: int) -> float | None:
    """ref_date のバーから horizon 営業日後の終値騰落率(%)。まだ先がなければ None。"""
    if df is None or len(df) == 0:
        return None
    idx = df.index.normalize()
    try:
        pos = idx.get_loc(pd.Timestamp(ref_date).normalize())
    except KeyError:
        # 近い日付を探す
        matches = idx[idx <= pd.Timestamp(ref_date).normalize()]
        if len(matches) == 0:
            return None
        pos = idx.get_loc(matches[-1])
    if isinstance(pos, slice):
        pos = pos.start
    if pos + horizon >= len(df):
        return None
    base = float(df["Close"].iloc[pos])
    fut = float(df["Close"].iloc[pos + horizon])
    return round((fut / base - 1) * 100, 2)


def evaluate_history(data: dict, cfg: dict) -> dict:
    """過去ピックの答え合わせ。results.csvを更新し、系統別集計を返す。"""
    picks = load_picks(cfg)
    horizons = cfg["review"]["horizons_days"]
    if len(picks) == 0:
        return {"summary": [], "recent": [], "by_system": []}

    records = []
    for _, row in picks.iterrows():
        df = data.get(str(row["code"]))
        rec = {
            "pick_date": row["pick_date"], "code": row["code"], "name": row["name"],
            "systems": row["systems"], "score": row["score"],
        }
        for h in horizons:
            rec[f"ret_{h}d"] = _forward_return(df, row["ref_date"], h)
        records.append(rec)

    res = pd.DataFrame(records)
    res.to_csv(_results_path(cfg), index=False)

    # 直近ピックの答え合わせ（表示用）: 最新のpick_dateブロック
    recent = []
    if len(res):
        # ret列があり評価済みのものだけ
        primary_h = horizons[0]
        col = f"ret_{primary_h}d"
        evaluated = res.dropna(subset=[col])
        if len(evaluated):
            latest_date = evaluated["pick_date"].max()
            block = evaluated[evaluated["pick_date"] == latest_date]
            wins = (block[col] > 0).sum()
            recent = {
                "pick_date": latest_date,
                "horizon": primary_h,
                "n": len(block),
                "avg_ret": round(block[col].mean(), 2),
                "win_rate": f"{wins}/{len(block)}",
            }

    # 系統別集計
    by_system = []
    primary_h = horizons[0]
    col = f"ret_{primary_h}d"
    ev = res.dropna(subset=[col])
    sys_stats = {}
    for _, r in ev.iterrows():
        for sysname in str(r["systems"]).split("|"):
            if not sysname:
                continue
            sys_stats.setdefault(sysname, []).append(r[col])
    for sysname, rets in sorted(sys_stats.items()):
        wins = sum(1 for x in rets if x > 0)
        by_system.append({
            "system": sysname,
            "n": len(rets),
            "avg_ret": round(sum(rets) / len(rets), 2),
            "win_rate": round(wins / len(rets) * 100, 0),
        })

    return {"recent": recent, "by_system": by_system, "results_count": len(ev)}
