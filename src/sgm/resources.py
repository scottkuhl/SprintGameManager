from __future__ import annotations

import sys
from pathlib import Path


def _bundle_base_dir() -> Path:
    # PyInstaller: files are unpacked to sys._MEIPASS.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))

    # Source checkout: `src/sgm/resources.py` -> repo root is parents[2].
    return Path(__file__).resolve().parents[2]


def resources_dir() -> Path:
    # Prefer a `resources/` folder next to where the app is being run from.
    cwd = Path.cwd() / "resources"
    if cwd.exists():
        return cwd

    return _bundle_base_dir() / "resources"


def resource_path(*parts: str) -> Path:
    return resources_dir().joinpath(*parts)
