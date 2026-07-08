"""日足データの取得とキャッシュ。

yfinance で日足を取り、data_dir に銘柄ごとの CSV を保存する。
- キャッシュが新しければ再取得しない（レート制限・IPブロック対策）
- 取得失敗時は前回キャッシュにフォールバックし、失敗した銘柄コードを記録する
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # 検証環境ではyfinance未導入でも他モジュールを読めるように
    yf = None


OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]


def _cache_path(data_dir: str, code: str) -> Path:
    return Path(data_dir) / f"{code}.csv"


def load_cache(data_dir: str, code: str) -> pd.DataFrame | None:
    p = _cache_path(data_dir, code)
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    return df


def _is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < max_age_hours * 3600


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance の戻り（MultiIndex列など）を単純な OHLCV に整える。"""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OHLCV_COLS)
    if isinstance(df.columns, pd.MultiIndex):
        # 単一銘柄をdownloadすると ('Close','7203.T') のような列になる
        df.columns = df.columns.get_level_values(0)
    keep = [c for c in OHLCV_COLS if c in df.columns]
    df = df[keep].copy()
    df = df.dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


def fetch_one(code: str, cfg: dict, force: bool = False) -> tuple[pd.DataFrame | None, str]:
    """1銘柄の日足を取得（またはキャッシュ）。

    戻り値: (DataFrame or None, status)  status は 'fresh'|'cache'|'download'|'fallback'|'fail'
    """
    data_dir = cfg["paths"]["data_dir"]
    max_age = cfg["data"]["cache_max_age_hours"]
    lookback = cfg["data"]["lookback_days"]
    path = _cache_path(data_dir, code)

    if not force and _is_fresh(path, max_age):
        return load_cache(data_dir, code), "fresh"

    if yf is None:
        cached = load_cache(data_dir, code)
        return (cached, "cache") if cached is not None else (None, "fail")

    ticker = f"{code}.T"
    start = (datetime.now() - timedelta(days=int(lookback * 1.6))).strftime("%Y-%m-%d")
    try:
        raw = yf.download(
            ticker, start=start, interval="1d",
            progress=False, auto_adjust=True, threads=False,
        )
        df = _normalize(raw)
        if len(df) == 0:
            raise ValueError("empty")
        df.to_csv(path)
        return df, "download"
    except Exception:
        cached = load_cache(data_dir, code)
        if cached is not None:
            return cached, "fallback"
        return None, "fail"


def fetch_universe(codes: list[str], cfg: dict, force: bool = False):
    """ユニバース全銘柄を取得。戻り値: (dict[code->DataFrame], list[失敗code])。"""
    out: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    sleep = cfg["data"].get("request_sleep_sec", 0.4)
    for code in codes:
        df, status = fetch_one(code, cfg, force=force)
        if df is not None and len(df) > 0:
            out[code] = df
        else:
            failed.append(code)
        if status in ("download", "fallback"):
            time.sleep(sleep)  # ダウンロードした場合のみ待機
    return out, failed


def fetch_index(ticker: str, cfg: dict) -> pd.DataFrame | None:
    """指数・為替の日足（地合いゲート用）。キャッシュはコード名を安全化して保存。"""
    data_dir = cfg["paths"]["data_dir"]
    safe = ticker.replace("^", "_idx_").replace("=", "_")
    path = _cache_path(data_dir, safe)
    max_age = cfg["data"]["cache_max_age_hours"]
    if _is_fresh(path, max_age):
        return load_cache(data_dir, safe)
    if yf is None:
        return load_cache(data_dir, safe)
    try:
        raw = yf.download(ticker, period="1mo", interval="1d",
                          progress=False, auto_adjust=True, threads=False)
        df = _normalize(raw)
        if len(df) == 0:
            raise ValueError("empty")
        df.to_csv(path)
        return df
    except Exception:
        return load_cache(data_dir, safe)


def load_universe_list(cfg: dict) -> list[tuple[str, str]]:
    """universe.csv を読み込み [(code, name), ...] を返す。"""
    df = pd.read_csv(cfg["paths"]["universe"], dtype={"code": str})
    df["code"] = df["code"].str.strip()
    return list(df[["code", "name"]].itertuples(index=False, name=None))
