import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent / "resources"
    return base / relative


def local_dir() -> Path:
    """Return the .local directory next to the repo/executable, creating it if needed."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent.parent  # repo root
    d = base / ".local"
    d.mkdir(exist_ok=True)
    return d
