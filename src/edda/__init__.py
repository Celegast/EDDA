"""Elite Dangerous Data Analyser — journal parser, database, and analytics dashboard."""

from pathlib import Path
import tomllib


def _read_version() -> str:
    """Read version from pyproject.toml — always current, no reinstall needed."""
    try:
        p = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        with open(p, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        try:
            from importlib.metadata import version
            return version("edda")
        except Exception:
            return "dev"


__version__ = _read_version()
