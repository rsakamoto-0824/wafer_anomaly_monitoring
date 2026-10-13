"""テスト共通の小さな設定（default.yaml を土台に、件数だけ減らす）。"""
from __future__ import annotations

import pytest

from src.config import load_config
from src.experiments.common import build_context


@pytest.fixture(scope="session")
def config():
    return load_config("configs/default.yaml")


@pytest.fixture(scope="session")
def ctx(config, tmp_path_factory):
    cfg = dict(config)
    out = tmp_path_factory.mktemp("results")
    cfg["output_dir"] = str(out)
    cfg["cache_dir"] = str(out / "cache")
    return build_context(cfg)
