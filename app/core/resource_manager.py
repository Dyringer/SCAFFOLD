import os
import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent / "resources"
    return base / relative


def local_dir() -> Path:
    """Return the per-instance state directory, creating it if needed.

    Override via SCAFFOLD_PROFILE env var (e.g. SCAFFOLD_PROFILE=b ->
    .local-b) when running multiple instances against the same repo
    so they have distinct settings/identity/logs.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent.parent  # repo root
    suffix = os.environ.get("SCAFFOLD_PROFILE", "").strip()
    name = f".local-{suffix}" if suffix else ".local"
    d = base / name
    d.mkdir(exist_ok=True)
    return d
