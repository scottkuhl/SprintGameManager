from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from sgm.config import AppConfig
from sgm.resources import resource_path
from sgm.ui.main_window import MainWindow
from sgm.version import APP_NAME


def _pick_icon_path() -> Path:
    # Prefer the native icon format per-platform, with fallbacks.
    if sys.platform == "darwin":
        names = ["icon.icns", "icon.png", "icon.ico"]
    else:
        names = ["icon.ico", "icon.png", "icon.icns"]

    for name in names:
        p = resource_path(name)
        if p.exists():
            return p
    return resource_path(names[0])


def _app_config_path() -> Path:
    cfg_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    return cfg_dir / "sgm.ini"


def _load_config() -> tuple[AppConfig, Path]:
    local_cfg = Path.cwd() / "sgm.ini"
    app_cfg = _app_config_path()

    # Prefer existing local config to preserve current Windows behavior.
    if local_cfg.exists():
        return (AppConfig.load_or_create(local_cfg), local_cfg)

    # Next prefer existing per-user app config (useful for macOS .app launches).
    if app_cfg.exists():
        return (AppConfig.load_or_create(app_cfg), app_cfg)

    # Neither exists: attempt to create/populate local first.
    try:
        return (AppConfig.load_or_create(local_cfg), local_cfg)
    except Exception:
        pass

    # Fallback: ensure AppConfigLocation exists, then create/populate there.
    app_cfg.parent.mkdir(parents=True, exist_ok=True)
    return (AppConfig.load_or_create(app_cfg), app_cfg)


def main() -> int:
    if os.name == "nt" and not os.environ.get("QT_QPA_FONTDIR"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        fonts_dir = windir / "Fonts"
        if fonts_dir.exists():
            os.environ["QT_QPA_FONTDIR"] = str(fonts_dir)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    icon_path = _pick_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config, config_path = _load_config()

    window = MainWindow(config=config, config_path=config_path)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    # Auto-load last folder if present.
    if config.last_game_folder and config.last_game_folder.lower() != "none":
        last = Path(config.last_game_folder)
        if last.exists() and last.is_dir():
            window.load_folder(last)

    return app.exec()
