from __future__ import annotations

import os
import unicodedata
from pathlib import Path


def sprint_name_key(value: str | None) -> str:
    """Return a normalized, case-insensitive comparison key.

    Sprint is assumed case-insensitive, so we always casefold regardless of OS.
    """

    s = "" if value is None else str(value)
    # Normalize Unicode so visually-identical strings compare equal.
    s = unicodedata.normalize("NFC", s)
    return s.casefold()


def sprint_path_key(path: Path | str | None) -> str:
    """Return a normalized, case-insensitive path comparison key.

    This is used to enforce Sprint-like case-insensitive semantics on any OS.
    """

    if path is None:
        return ""

    p = Path(path)
    # Avoid strict resolve: the path may not exist yet.
    try:
        p = p.resolve(strict=False)
    except Exception:
        try:
            p = p.absolute()
        except Exception:
            p = Path(str(path))

    s = os.path.abspath(str(p))
    # Normalize separators to make keys stable.
    s = s.replace("\\", "/")
    s = unicodedata.normalize("NFC", s)
    return s.casefold()
