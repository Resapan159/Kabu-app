"""PTS夜間価格の取得（構想書: 開示への夜間反応で翌朝の寄付を先読み）。

株探(kabutan)の銘柄ページからPTS価格をベストエフォートで抽出する。
※非公式スクレイピングのためサイト構造変更で取れなくなる可能性あり。
  失敗しても空を返しレポート生成は継続する（実験的機能）。
"""
from __future__ import annotations

import re
import time
import urllib.request

UA = {"User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                     "AppleWebKit/605.1.15 kabu-app/1.0 personal-use")}


def _fetch_html(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(1_500_000).decode("utf-8", errors="ignore")


def _parse_pts(html: str) -> float | None:
    """ページ中のPTS価格らしき数値を抽出する。"""
    # 「PTS」の近傍にある価格（カンマ区切り数値）を探す
    for m in re.finditer(r"PTS([\s\S]{0,300})", html):
        seg = m.group(1)
        for num in re.findall(r"[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?", seg):
            try:
                v = float(num.replace(",", ""))
            except ValueError:
                continue
            if v >= 10:  # 株価らしい値のみ（タグ内の小さな数字は除外）
                return v
    return None


def fetch_for(codes: list[str], closes: dict, max_codes: int = 10,
              sleep_sec: float = 1.0) -> dict:
    """開示があった銘柄のPTS価格を取得し {code: {price, gap_pct}} を返す。

    closes: {code: 直近終値} — 夜間ギャップ率の計算に使用。
    """
    out = {}
    for code in codes[:max_codes]:
        try:
            html = _fetch_html(f"https://kabutan.jp/stock/?code={code}")
            price = _parse_pts(html)
            if price is None:
                continue
            base = closes.get(code)
            gap = round((price / base - 1) * 100, 2) if base else None
            # 終値からの乖離が非現実的（±30%超）なら誤抽出とみなし捨てる
            if gap is not None and abs(gap) > 30:
                continue
            out[code] = {"price": price, "gap_pct": gap}
        except Exception:
            continue
        time.sleep(sleep_sec)
    return out
