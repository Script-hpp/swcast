from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]


def load_config(path: str | Path = _REPO_ROOT / "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = Path(os.path.expandvars(cfg["data_dir"])).expanduser()
    return cfg
