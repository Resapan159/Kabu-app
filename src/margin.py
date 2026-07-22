"""信用需給（④）: JPX公表の銘柄別信用取引週末残高から信用倍率を算出。

JPXは毎週第3営業日頃に「銘柄別信用取引週末残高」を公開する。
このモジュールは公開ページから最新のExcel/CSVリンクを探してダウンロードし、
{code: {"ratio": 信用倍率(買残/売残), "buy": 買残, "sell": 売残}} を返す。
結果は data/margin_cache.json に保存し、3日間はキャッシュを使う。
※サイト構造変更で取れなくなる可能性あり。失敗時は空dictで継続（実験的機能）。
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

LIST_URL = "https://www.jpx.co.jp/markets/statistics-equities/margin/05.html"
BASE = "https://www.jpx.co.jp"
UA = {"User-Agent": "kabu-app/1.0 (personal use)"}
CACHE_MAX_AGE_SEC = 3 * 24 * 3600


def _cache_path(cfg: dict) -> Path:
    return Path(cfg["paths"]["data_dir"]) / "margin_cache.json"


def _fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(20_000_000)


def _find_latest_file_url(html: str) -> str | None:
    # ページ内の .xls/.xlsx/.csv リンク（週末残高ファイル）を上から順に探す
    for m in re.finditer(r'href="([^"]+\.(?:xlsx?|csv))"', html):
        url = m.group(1)
        return url if url.startswith("http") else BASE + url
    return None


def _parse_table(data: bytes, url: str) -> dict:
    """Excel/CSVから コード・売残・買残 を推定して抽出する。"""
    import io
    import pandas as pd
    frames = []
    try:
        if url.endswith(".csv"):
            for enc in ("shift_jis", "utf-8"):
                try:
                    frames = [pd.read_csv(io.BytesIO(data), encoding=enc,
                                          header=None, dtype=str)]
                    break
                except Exception:
                    continue
        else:
            xls = pd.read_excel(io.BytesIO(data), sheet_name=None,
                                header=None, dtype=str)
            frames = list(xls.values())
    except Exception:
        return {}

    out = {}
    code_re = re.compile(r"^[0-9]{4}$")
    for df in frames:
        if df is None or df.empty:
            continue
        arr = df.fillna("").astype(str).values
        for row in arr:
            cells = [c.strip().replace(",", "") for c in row]
            # 4桁コードのセルを探す
            code = None
            idx = None
            for i, c in enumerate(cells[:6]):
                if code_re.match(c):
                    code = c
                    idx = i
                    break
            if code is None:
                continue
            # コード以降の数値セルを収集（売残・買残の候補）
            nums = []
            for c in cells[idx + 1:]:
                if re.match(r"^-?[0-9]+(?:\.[0-9]+)?$", c):
                    nums.append(float(c))
            # 一般的な列順: …売残, 前週比, 買残, 前週比（大きな2値を売残/買残とみなす）
            big = [x for x in nums if x >= 0]
            if len(big) < 2:
                continue
            # ヒューリスティック: 数値のうち最大2つを残高とみなす（前週比は小さい）
            top2 = sorted(big, reverse=True)[:2]
            sell, buy = None, None
            # 順序保持: bigの中で top2 に含まれる最初の2つ
            picked = [x for x in big if x in top2][:2]
            if len(picked) == 2:
                sell, buy = picked[0], picked[1]
            if not sell or buy is None:
                continue
            ratio = round(buy / sell, 2) if sell > 0 else None
            out[code] = {"ratio": ratio, "sell": sell, "buy": buy}
    return out


def fetch(cfg: dict) -> dict:
    """信用倍率マップを返す（キャッシュ優先）。失敗時は {}。"""
    cache = _cache_path(cfg)
    try:
        if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_MAX_AGE_SEC:
            return json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        html = _fetch(LIST_URL).decode("utf-8", errors="ignore")
        file_url = _find_latest_file_url(html)
        if not file_url:
            return {}
        table = _parse_table(_fetch(file_url), file_url)
        if table:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(table, ensure_ascii=False),
                             encoding="utf-8")
        return table
    except Exception:
        return {}
