"""
Journal file reader — incremental, batch-committing.

Scans the Elite Dangerous saved-games folder for Journal.*.log files,
skips any already recorded in journal_files, and processes new ones in
chronological order.

Files that were partially imported (e.g. the game was open during the last
import) are resumed from the line where the previous run stopped, so new
events appended since then are picked up without duplicating old ones.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .event_handlers import HANDLERS, KNOWN_IGNORED_EVENTS


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


def already_processed(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """Return {filename: (file_size, lines_processed)} for every recorded file."""
    rows = conn.execute(
        "SELECT filename, file_size, lines_processed FROM journal_files"
    ).fetchall()
    return {r["filename"]: (r["file_size"], r["lines_processed"]) for r in rows}


def process_file(path: Path, conn: sqlite3.Connection,
                 skip_lines: int = 0) -> tuple[int, int, set[str]]:
    """
    Process one journal file starting at line skip_lines.

    Each parsed event is dispatched to its structured handler (if one exists in
    HANDLERS). Event types in neither HANDLERS nor KNOWN_IGNORED_EVENTS are
    collected and returned so the caller can report them.

    Returns (events_counted, total_lines_in_file, unknown_event_types).
    The caller is responsible for updating journal_files.
    """
    event_count = 0
    pending = 0
    total_lines = 0
    unknown: set[str] = set()

    conn.execute("BEGIN")
    with path.open(encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh):
            total_lines = lineno + 1
            if lineno < skip_lines:
                continue
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("event", "")
            handler = HANDLERS.get(event_type)
            if handler:
                handler(event, conn)
            elif event_type and event_type not in KNOWN_IGNORED_EVENTS:
                unknown.add(event_type)

            event_count += 1
            pending += 1
            if pending >= COMMIT_EVERY:
                conn.execute("COMMIT")
                conn.execute("BEGIN")
                pending = 0

    conn.execute("COMMIT")
    return event_count, total_lines, unknown


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
    force       : re-process files from scratch even if already recorded
    verbose     : print progress to stdout

    Returns
    -------
    dict with keys: files_processed, files_skipped, events_handled
    """
    jdir = journal_dir or ED_JOURNAL_DIR
    if not jdir.exists():
        raise FileNotFoundError(f"Journal directory not found: {jdir}")

    all_files = iter_journal_files(jdir)
    done = {} if force else already_processed(conn)

    files_processed = 0
    files_skipped = 0
    events_handled = 0
    unknown_event_types: set[str] = set()

    total = len(all_files)
    for i, path in enumerate(all_files, 1):
        skip_lines = 0

        if not force and path.name in done:
            stored_size, stored_lines = done[path.name]
            current_size = path.stat().st_size

            if stored_size == 0:
                # Legacy record from before resume-tracking was added.
                # Treat as fully processed — stamp the real size and skip.
                conn.execute(
                    "UPDATE journal_files SET file_size = ?, lines_processed = 0"
                    " WHERE filename = ?",
                    (current_size, path.name),
                )
                conn.commit()
                files_skipped += 1
                continue

            if current_size <= stored_size:
                files_skipped += 1
                continue

            # File has grown since last import — resume from where we left off
            skip_lines = stored_lines
            if verbose:
                print(f"[{i}/{total}] {path.name} (resuming from line {skip_lines}) ... ",
                      end="", flush=True)
        else:
            if verbose:
                print(f"[{i}/{total}] {path.name} ... ", end="", flush=True)

        count, total_lines, unknown = process_file(path, conn, skip_lines)
        unknown_event_types |= unknown
        now = datetime.now(timezone.utc).isoformat()
        current_size = path.stat().st_size

        if path.name in done and not force:
            conn.execute("""
                UPDATE journal_files
                SET processed_at = ?, event_count = event_count + ?,
                    file_size = ?, lines_processed = ?
                WHERE filename = ?
            """, (now, count, current_size, total_lines, path.name))
        else:
            conn.execute("""
                INSERT INTO journal_files
                    (filename, processed_at, event_count, file_size, lines_processed)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    processed_at    = excluded.processed_at,
                    event_count     = excluded.event_count,
                    file_size       = excluded.file_size,
                    lines_processed = excluded.lines_processed
            """, (path.name, now, count, current_size, total_lines))
        conn.commit()

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
        if unknown_event_types:
            print("\nWARNING: unknown event types encountered (not handled, not in ignore list):")
            for et in sorted(unknown_event_types):
                print(f"  {et}")
            print("Consider adding handlers or adding them to KNOWN_IGNORED_EVENTS.")

    return {
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "events_handled": events_handled,
        "unknown_event_types": unknown_event_types,
    }
