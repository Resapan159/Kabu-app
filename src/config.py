"""設定ファイル(config.yaml)の読み込みとパス解決。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# プロジェクトルート = このファイルの1つ上（src の親）
ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | os.PathLike | None = None) -> dict:
    """config.yaml を読み込んで dict で返す。相対パスはプロジェクトルート基準に解決する。"""
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # パス系をルート基準の絶対パスに解決
    paths = cfg.setdefault("paths", {})
    for key in ("universe", "data_dir", "reports_dir", "history_dir"):
        if key in paths:
            p = Path(paths[key])
            paths[key] = str(p if p.is_absolute() else ROOT / p)

    # 出力ディレクトリを用意
    for key in ("data_dir", "reports_dir", "history_dir"):
        if key in paths:
            Path(paths[key]).mkdir(parents=True, exist_ok=True)

    return cfg
