"""TDnet適時開示の取得と分類（①カタリスト系・構想書Phase2）。

無料の非公式WEB-API（やのしん東証TDnet WEB-API）を利用。
失敗しても空dictを返し、レポート生成は止めない設計。
"""
from __future__ import annotations

import datetime
import json
import urllib.request

API = "https://webapi.yanoshin.jp/webapi/tdnet/list/{span}.json?limit=300"

POS_STRONG = ["上方修正", "増配", "自己株式取得", "自己株式の取得", "自社株買い",
              "株式分割", "業績予想の修正（増額）"]
POS = ["業務提携", "資本提携", "共同開発", "受注", "新製品", "特別利益", "復配"]
NEG = ["下方修正", "減配", "特別損失", "監理銘柄", "整理銘柄", "無配"]
EARN = ["決算短信", "決算説明"]


def classify(title: str) -> tuple[str, str]:
    for k in NEG:
        if k in title:
            return "neg", k
    for k in POS_STRONG:
        if k in title:
            return "pos_strong", k
    for k in POS:
        if k in title:
            return "pos", k
    for k in EARN:
        if k in title:
            return "earnings", k
    return "other", ""


def fetch(universe_codes: list[str], cfg: dict, days: int = 2,
          timeout: int = 20) -> dict:
    """直近days日の開示を取得し {4桁コード: [{'title','cls','kw','time','url'}]} を返す。

    取得失敗時は {}（レポートは開示なしとして生成継続）。
    """
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days)
    span = f"{start:%Y%m%d}-{today:%Y%m%d}"
    try:
        req = urllib.request.Request(
            API.format(span=span),
            headers={"User-Agent": "kabu-app/1.0 (personal use)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}

    uni = set(str(c) for c in universe_codes)
    out: dict = {}
    items = data.get("items", data if isinstance(data, list) else [])
    for item in items:
        td = item.get("Tdnet", item) if isinstance(item, dict) else {}
        code = str(td.get("company_code", ""))[:4]
        if code not in uni:
            continue
        title = str(td.get("title", ""))
        cls, kw = classify(title)
        out.setdefault(code, []).append({
            "title": title, "cls": cls, "kw": kw,
            "time": str(td.get("pubdate", ""))[:16],
            "url": str(td.get("document_url", "")),
        })
    return out
