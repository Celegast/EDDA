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
from typing import Optional

from .event_handlers import HANDLERS, KNOWN_IGNORED_EVENTS, backfill_regions


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


def peek_commander(path: Path) -> Optional[str]:
    """Return the Commander name from the first LoadGame event in the file, or None."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for _, raw in zip(range(50), fh):
                try:
                    event = json.loads(raw.strip())
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "LoadGame":
                    return event.get("Commander")
    except Exception:
        pass
    return None


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
               verbose: bool = True,
               files: list[Path] | None = None) -> dict:
    """
    Main import entry point.

    Parameters
    ----------
    conn        : open sqlite3.Connection
    journal_dir : override for the default ED journal directory
    force       : re-process files from scratch even if already recorded
    verbose     : print progress to stdout
    files       : explicit list of files to import (skips directory scan when set)

    Returns
    -------
    dict with keys: files_processed, files_skipped, events_handled
    """
    jdir = journal_dir or ED_JOURNAL_DIR
    if files is None and not jdir.exists():
        raise FileNotFoundError(f"Journal directory not found: {jdir}")

    all_files = files if files is not None else iter_journal_files(jdir)
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

    backfill_regions(conn, verbose=verbose)

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


def run_import_all_commanders(
    journal_dir: Path | None = None,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, dict]:
    """
    Scan the journal directory, group files by commander, and import each
    commander's files into a separate .edda/<name>.db database.

    Auto-sets the active commander in config if exactly one is found and none
    is currently active.
    """
    from ..config import (
        get_commander_db_path, get_active_commander,
        set_active_commander, register_commander,
    )
    from ..db.connection import open_db

    jdir = journal_dir or ED_JOURNAL_DIR
    if not jdir.exists():
        raise FileNotFoundError(f"Journal directory not found: {jdir}")

    all_files = iter_journal_files(jdir)
    if not all_files:
        if verbose:
            print("No journal files found.")
        return {}

    # Group files by commander name.
    # Files with no LoadGame inherit the last known commander (mid-session
    # crashes etc.).  Files that appear before any LoadGame is seen are kept
    # in a temporary "__unknown__" bucket and attributed to the first
    # commander found further on in the file list.
    files_by_cmdr: dict[str, list[Path]] = {}
    first_cmdr: Optional[str] = None
    last_cmdr: Optional[str] = None
    no_loadgame: int = 0
    for path in all_files:
        name = peek_commander(path)
        if name is not None:
            if first_cmdr is None:
                first_cmdr = name
            last_cmdr = name
        elif last_cmdr is not None:
            name = last_cmdr
            no_loadgame += 1
        else:
            name = "__unknown__"
        files_by_cmdr.setdefault(name, []).append(path)

    # Attribute any pre-history files to the first commander found.
    if "__unknown__" in files_by_cmdr and first_cmdr is not None:
        pre = files_by_cmdr.pop("__unknown__")
        no_loadgame += len(pre)
        # Prepend so chronological order is preserved within the list.
        files_by_cmdr[first_cmdr] = pre + files_by_cmdr.get(first_cmdr, [])
        if verbose:
            print(
                f"  {len(pre)} file(s) before first LoadGame attributed to "
                f"{first_cmdr} (first known commander)."
            )

    real_cmdrs = [c for c in files_by_cmdr if c != "__unknown__"]

    if verbose:
        print(
            f"Found {len(real_cmdrs)} commander(s) across {len(all_files)} "
            f"journal file(s)"
            + (f" ({no_loadgame} carried forward from previous session)." if no_loadgame else ".")
        )

    results: dict[str, dict] = {}
    for cmdr_name in sorted(real_cmdrs):
        db_path = get_commander_db_path(cmdr_name)
        register_commander(cmdr_name)
        files = files_by_cmdr[cmdr_name]

        if verbose:
            print(f"\n=== Commander: {cmdr_name} ({len(files)} file(s)) ===")

        conn = open_db(db_path)
        try:
            result = run_import(
                conn,
                journal_dir=jdir,
                force=force,
                verbose=verbose,
                files=files,
            )
            results[cmdr_name] = result
        finally:
            conn.close()

    unknown_count = len(files_by_cmdr.get("__unknown__", []))
    if verbose and unknown_count:
        print(
            f"\n[?] {unknown_count} file(s) appeared before any LoadGame event "
            f"and could not be attributed to a commander — skipped."
        )

    # Auto-set active commander if none is configured yet
    active = get_active_commander()
    if active is None:
        if len(real_cmdrs) == 1:
            set_active_commander(real_cmdrs[0])
            if verbose:
                print(f"\nActive commander set to: {real_cmdrs[0]}")
        elif len(real_cmdrs) > 1:
            if verbose:
                print(
                    f"\nMultiple commanders found: {', '.join(sorted(real_cmdrs))}. "
                    "Select the active one via the GUI or re-run with --db."
                )

    return results
