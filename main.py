import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parent
    src = root / "src"
    if not src.exists():
        return
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_ensure_src_on_path()

from sgm.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
