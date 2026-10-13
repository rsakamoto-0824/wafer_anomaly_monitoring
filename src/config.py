"""設定ファイル（YAML）の読み込みと、再現できる乱数の作り方。

- 設定ファイルは `extends: 別ファイル.yaml` で土台を指定し、差分だけを書ける。
- 乱数は「seed ＋ 用途を表すキー」から作る。同じキーなら同じ乱数になるので、
  監視手法や異常の大きさを変えても同じ正常Waferを使える（Common Random Numbers）。
"""
from __future__ import annotations

import copy
import hashlib
import json
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | Path) -> dict[str, Any]:
    """YAML を読み、`extends` があれば土台の設定に重ねて返す。"""
    path = Path(path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path) if not path.exists() else path.resolve()
    with open(path, encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    base_name = config.pop("extends", None)
    if base_name:
        config = deep_merge(load_config(path.parent / base_name), config)
    config["_config_path"] = str(path)
    return config


def deep_merge(base: dict, override: dict) -> dict:
    """辞書を再帰的に重ねる（override 側を優先）。リストは丸ごと置き換える。"""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def config_hash(section: Any) -> str:
    """設定の一部から短いハッシュを作る（途中結果の再利用判定に使う）。"""
    text = json.dumps(section, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _key_to_int(key: Any) -> int:
    if isinstance(key, (int, np.integer)):
        return int(key)
    return zlib.crc32(str(key).encode("utf-8"))


def make_rng(seed: int, *keys: Any) -> np.random.Generator:
    """seed と用途キーから独立な乱数生成器を作る。

    例：make_rng(seed, "phase1", "calibration", block) — 同じ引数なら必ず同じ乱数列になる。
    """
    spawn_key = tuple(_key_to_int(key) for key in keys)
    return np.random.default_rng(np.random.SeedSequence(int(seed), spawn_key=spawn_key))


def resolve_path(config: dict, key: str, default: str) -> Path:
    """設定のパス（相対パスはプロジェクトのフォルダが基準）。"""
    path = Path(config.get(key, default))
    return path if path.is_absolute() else PROJECT_ROOT / path


def output_dir(config: dict) -> Path:
    return resolve_path(config, "output_dir", "results")
