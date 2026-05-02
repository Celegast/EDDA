"""
Journal file reader — incremental, batch-committing.

Scans the Elite Dangerous saved-games folder for Journal.*.log files,
skips any already recorded in journal_files, and processes new ones in
chronological order.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .event_handlers import HANDLERS


ED_JOURNAL_DIR = (
    Path.home()
    / "Saved Games"
    / "Frontier Developments"
    / "Elite Dangerous"
)

COMMIT_EVERY = 500   # events between transaction commits


def iter_journal_files(journal_dir: Path) -> list[Path]:
    """Return all Journal.*.log files sorted chronologically by filename."""
    return sorted(journal_dir.glob("Journal.*.log"))


def already_processed(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT filename FROM journal_files").fetchall()
    return {r["filename"] for r in rows}


def iter_events(path: Path) -> Iterator[dict]:
    """Yield parsed JSON objects from a journal file, skipping bad lines."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def process_file(path: Path, conn: sqlite3.Connection) -> int:
    """Process one journal file. Returns number of handled events."""
    event_count = 0
    pending = 0

    conn.execute("BEGIN")
    for event in iter_events(path):
        event_type = event.get("event")
        handler = HANDLERS.get(event_type)
        if handler:
            handler(event, conn)
            event_count += 1

        pending += 1
        if pending >= COMMIT_EVERY:
            conn.execute("COMMIT")
            conn.execute("BEGIN")
            pending = 0

    conn.execute("COMMIT")

    conn.execute("""
        INSERT INTO journal_files (filename, processed_at, event_count)
        VALUES (?, ?, ?)
    """, (
        path.name,
        datetime.now(timezone.utc).isoformat(),
        event_count,
    ))
    conn.commit()
    return event_count


def run_import(conn: sqlite3.Connection,
               journal_dir: Path | None = None,
               force: bool = False,
               verbose: bool = True) -> dict:
    """
    Main import entry point.

    Parameters
    ----------
    conn        : open sqlite3.Connection
    journal_dir : override for the default ED journal directory
    force       : re-process files even if already recorded
    verbose     : print progress to stdout

    Returns
    -------
    dict with keys: files_processed, files_skipped, events_handled
    """
    jdir = journal_dir or ED_JOURNAL_DIR
    if not jdir.exists():
        raise FileNotFoundError(f"Journal directory not found: {jdir}")

    all_files = iter_journal_files(jdir)
    done = set() if force else already_processed(conn)

    files_processed = 0
    files_skipped = 0
    events_handled = 0

    total = len(all_files)
    for i, path in enumerate(all_files, 1):
        if path.name in done:
            files_skipped += 1
            continue

        if verbose:
            print(f"[{i}/{total}] {path.name} ... ", end="", flush=True)

        count = process_file(path, conn)
        events_handled += count
        files_processed += 1

        if verbose:
            print(f"{count} events")

    if verbose:
        print(
            f"\nDone. Processed {files_processed} files "
            f"({files_skipped} skipped), "
            f"{events_handled} events handled."
        )

    return {
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "events_handled": events_handled,
    }
