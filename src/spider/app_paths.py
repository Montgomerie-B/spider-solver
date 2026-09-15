"""Windows-local application data paths. Do not require write access to the install dir."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def local_app_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "SpiderSolver"
    return Path.home() / ".spider-solver"


def default_campaigns_dir() -> Path:
    p = local_app_root() / "Campaigns"
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_folder() -> Path:
    p = local_app_root()
    p.mkdir(parents=True, exist_ok=True)
    return p


def repo_root() -> Path:
    """Source checkout, or PyInstaller _MEIPASS when frozen."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def research_json(name: str) -> Path:
    return repo_root() / "docs" / "research" / name
