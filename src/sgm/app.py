from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from sgm.config import AppConfig
from sgm.resources import resource_path
from sgm.ui.main_window import MainWindow
from sgm.version import APP_NAME


def main() -> int:
    if os.name == "nt" and not os.environ.get("QT_QPA_FONTDIR"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        fonts_dir = windir / "Fonts"
        if fonts_dir.exists():
            os.environ["QT_QPA_FONTDIR"] = str(fonts_dir)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    icon_path = resource_path("icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config_path = Path.cwd() / "sgm.ini"
    config = AppConfig.load_or_create(config_path)

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
