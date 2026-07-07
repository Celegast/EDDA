"""Merge multiple EDDA SQLite databases into a temporary combined database."""

import atexit
import sqlite3
import tempfile
from pathlib import Path

# All analytics tables; journal_files is omitted (it tracks import state, not data).
_COPY_TABLES = [
    "systems", "bodies", "body_materials", "rings", "bio_signals",
    "organic_scans", "organic_sales", "codex_entries", "exploration_sales",
    "commander_snapshots", "statistics_snapshots", "fss_signals",
    "barycentres", "missions", "powerplay_merits", "jumps",
]

_temps: list[Path] = []


def _cleanup() -> None:
    for p in _temps:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


atexit.register(_cleanup)


def merge_databases(paths: list[Path]) -> Path:
    """Return a path to a merged SQLite DB combining all sources.

    If exactly one path is supplied it is returned as-is (no copy).
    Otherwise a temporary file is created and registered for cleanup on exit.

    Deduplication strategy:
    - Tables with UNIQUE constraints (systems, bodies, rings, …): INSERT OR IGNORE
      naturally deduplicates by natural key.
    - organic_scans: the unique index created by open_db() on
      (system_address, body_id, timestamp, scan_state, COALESCE(species,''))
      handles dedup.
    - Tables without unique constraints (jumps, organic_sales, …): all rows
      from every source are included (different commanders' histories merged).
    """
    if len(paths) == 1:
        return paths[0]

    from .connection import open_db

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    dest = Path(tmp.name)
    _temps.append(dest)

    # Bootstrap schema + unique indexes in destination (open_db does this).
    seed = open_db(dest)
    seed.close()

    dst = sqlite3.connect(str(dest))
    try:
        for src_path in paths:
            dst.execute("ATTACH DATABASE ? AS _src", [str(src_path)])
            try:
                for table in _COPY_TABLES:
                    try:
                        # Exclude the auto-increment 'id' so the destination
                        # assigns fresh ids and the ON CONFLICT checks operate
                        # only on the natural-key columns.
                        cols = [
                            row[1]
                            for row in dst.execute(f"PRAGMA table_info({table})")
                            if row[1] != "id"
                        ]
                        if not cols:
                            continue
                        col_list = ", ".join(cols)
                        dst.execute(f"""
                            INSERT OR IGNORE INTO {table} ({col_list})
                            SELECT {col_list} FROM _src.{table}
                        """)
                    except sqlite3.OperationalError:
                        pass  # table absent in older DB — skip silently
                dst.commit()
            finally:
                try:
                    dst.execute("DETACH DATABASE _src")
                except Exception:
                    pass
    finally:
        dst.close()

    return dest
