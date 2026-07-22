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


# ================= 修正幅の定量抽出（構想書: カタリストの強弱判定） =================

REVISION_KWS = ("上方修正", "下方修正", "業績予想の修正")


def _extract_revision_pct(pdf_bytes: bytes) -> float | None:
    """業績予想修正PDFから営業利益の増減率(%)を抽出する（ベストエフォート）。

    TDnetの修正開示は「前回予想/今回修正予想/増減額/増減率」の定型表を持つ。
    pdfminerでテキスト化し、増減率らしき%数値を探す。営業利益列を特定できない
    場合は、見つかった増減率のうち絶対値が最大のものを代表値とする。
    """
    try:
        from io import BytesIO
        from pdfminer.high_level import extract_text
        text = extract_text(BytesIO(pdf_bytes), maxpages=3)
    except Exception:
        return None
    if not text:
        return None
    import re
    # 全角記号を正規化
    t = text.replace("△", "-").replace("▲", "-").replace("−", "-") \
            .replace("，", ",").replace("％", "%")
    # 「増減率」行の近くの %値 を収集
    vals = []
    for m in re.finditer(r"増\s*減\s*率[\s\S]{0,130}", t):
        seg = m.group(0)
        for v in re.findall(r"(-?\d{1,3}(?:\.\d+)?)\s*%", seg):
            try:
                f = float(v)
                if 0.1 <= abs(f) <= 500:
                    vals.append(f)
            except ValueError:
                pass
    if not vals:
        # フォールバック: 文中の「○%増（減）」表現
        for v, updown in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%\s*(増|減)", t):
            try:
                f = float(v)
                if 0.1 <= f <= 500:
                    vals.append(f if updown == "増" else -f)
            except ValueError:
                pass
    if not vals:
        return None
    # 絶対値最大を代表値に（利益系の修正率は売上より大きく出るため）
    return max(vals, key=abs)


def enrich_revisions(disc: dict, max_pdfs: int = 4, timeout: int = 25) -> int:
    """修正系開示のPDFをダウンロードして rev_pct を付与。処理した件数を返す。"""
    n = 0
    for code, ds in disc.items():
        for d in ds:
            if n >= max_pdfs:
                return n
            title = d.get("title", "")
            if not any(k in title for k in REVISION_KWS):
                continue
            url = d.get("url", "")
            if not url or not url.lower().endswith(".pdf"):
                continue
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "kabu-app/1.0 (personal use)"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    pdf = r.read(3_000_000)
                pct = _extract_revision_pct(pdf)
                if pct is not None:
                    d["rev_pct"] = round(pct, 1)
                n += 1
            except Exception:
                n += 1
                continue
    return n
