"""Commander configuration — persistent state in .edda/config.json."""

import json
from pathlib import Path
from typing import Optional

_EDDA_DIR = Path(".edda")
_CONFIG_FILE = _EDDA_DIR / "config.json"


def _load() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(cfg: dict) -> None:
    _EDDA_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _safe_name(name: str) -> str:
    """Convert a commander name to a safe filename stem."""
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)


def get_commander_db_path(name: str) -> Path:
    """Return the .edda/<safe_name>.db path for a named commander."""
    return _EDDA_DIR / f"{_safe_name(name)}.db"


def list_commanders() -> list[str]:
    """Return display names of all commanders with a .edda/*.db file."""
    cfg = _load()
    known: dict[str, str] = cfg.get("commanders", {})

    names: list[str] = []
    seen: set[str] = set()
    if _EDDA_DIR.exists():
        for db_file in sorted(_EDDA_DIR.glob("*.db")):
            stem = db_file.stem
            display = known.get(stem, stem)
            if display not in seen:
                names.append(display)
                seen.add(display)
    return names


def get_active_commander() -> Optional[str]:
    """Return the active commander display name, or None."""
    return _load().get("active_commander")


def set_active_commander(name: str) -> None:
    """Set the active commander and persist the name→stem mapping."""
    cfg = _load()
    cfg["active_commander"] = name
    cfg.setdefault("commanders", {})[_safe_name(name)] = name
    _save(cfg)


def register_commander(name: str) -> None:
    """Register a commander name without changing the active one."""
    cfg = _load()
    cfg.setdefault("commanders", {})[_safe_name(name)] = name
    _save(cfg)


def get_active_db_path() -> Optional[Path]:
    """Return the DB path for the active commander, or None if none is set."""
    name = get_active_commander()
    return get_commander_db_path(name) if name is not None else None


# ── UI state (persisted per-key under config["ui"]) ───────────────────────────

def get_ui_state() -> dict:
    """Return the entire UI state dict."""
    return _load().get("ui", {})


def set_ui_state(updates: dict) -> None:
    """Merge updates into the UI state dict."""
    cfg = _load()
    cfg.setdefault("ui", {}).update(updates)
    _save(cfg)
