"""
Command-line entry points (run via pdm).

  pdm run import     — parse journal files into the database
  pdm run stats      — print summary statistics
  pdm run trip       — print statistics for a specific date range
  pdm run map        — render galaxy maps
  pdm run charts     — render all charts
  pdm run dashboard  — build the single-page HTML dashboard
"""

import argparse
import sys
from pathlib import Path

from .db.connection import open_db, get_db_path
from .importer.journal_reader import run_import, run_import_all_commanders, ED_JOURNAL_DIR
from .analysis import stats as st
from .analysis import maps as mp
from .analysis import charts as ch
from .analysis import dashboard as db
from .analysis import trip_report as tr
from .analysis import stratum_report as sr


# ---------------------------------------------------------------------------
# Shared argument helpers
# ---------------------------------------------------------------------------

def _db_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db", type=Path, action="append", default=None,
        metavar="PATH",
        help="Path to SQLite database (default: active commander's DB). "
             "Repeat to merge data from multiple commanders.",
    )


def _open_report_db(db_paths: list[Path] | None):
    """Open the DB for a reporting command, merging sources when needed."""
    if not db_paths:
        return open_db(None)
    if len(db_paths) == 1:
        return open_db(db_paths[0])
    from .db.merge import merge_databases
    return open_db(merge_databases(db_paths))


def _out_arg(parser: argparse.ArgumentParser, default: str = "output") -> None:
    parser.add_argument(
        "--out", type=Path, default=Path(default),
        metavar="DIR",
        help="Output directory for generated files (default: ./output)",
    )


# ---------------------------------------------------------------------------
# edjdb-import
# ---------------------------------------------------------------------------

def cmd_import(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pdm run import",
        description="Import Elite Dangerous journal files into the database.",
    )
    _db_arg(parser)
    parser.add_argument(
        "--journal-dir", type=Path, default=None,
        metavar="DIR",
        help=f"Journal directory (default: {ED_JOURNAL_DIR})",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-process files that were already imported.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-file output.",
    )
    args = parser.parse_args(argv)

    if args.db is None:
        # Multi-commander mode: auto-detect commanders from journal files and
        # create one .edda/<name>.db per commander.
        run_import_all_commanders(
            journal_dir=args.journal_dir,
            force=args.force,
            verbose=not args.quiet,
        )
    else:
        conn = open_db(args.db[0] if args.db else None)
        try:
            run_import(conn,
                       journal_dir=args.journal_dir,
                       force=args.force,
                       verbose=not args.quiet)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# edjdb-stats
# ---------------------------------------------------------------------------

def cmd_stats(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pdm run stats",
        description="Print exploration statistics from the database.",
    )
    _db_arg(parser)
    args = parser.parse_args(argv)

    conn = _open_report_db(args.db)
    try:
        data = st.summary(conn)
        print("\n=== Elite Dangerous — Exploration Summary ===\n")
        labels = {
            "journal_files":        "Journal files processed",
            "systems_visited":      "Systems visited",
            "jumps":                "FSD jumps",
            "ly_travelled":         "Light-years travelled",
            "bodies_scanned":       "Bodies scanned (FSS)",
            "bodies_mapped":        "  Bodies mapped (DSS)",
            "planets_landable":     "  Landable planets",
            "first_discoveries":    "  First discoveries",
            "first_mapped":         "  First mapped (DSS, new)",
            "bio_signals_detected": "Bio signals detected (FSS)",
            "bio_signals_bodies":   "  Bodies with bio signals",
            "bio_bodies_sampled":   "  Bodies sampled (analysed)",
            "organic_scans_done":   "Organic scans completed",
            "species_unique":       "  Unique species",
            "organic_credits":      "Exobiology credits earned",
            "exploration_credits":  "Exploration credits earned",
            "codex_new_entries":    "New codex entries",
        }
        for key, label in labels.items():
            val = data.get(key, 0)
            if "credits" in key or key == "ly_travelled":
                print(f"  {label:<35} {val:>15,.0f}")
            else:
                print(f"  {label:<35} {val:>15,}")

        print("\n--- Personal Records ---\n")
        records = st.personal_records(conn)
        if not records.empty:
            print(f"  {'Record':<22} {'Body / System':<40} {'Value':>20}")
            print(f"  {'-'*22} {'-'*40} {'-'*20}")
            for _, r in records.iterrows():
                val = float(r["Value"])
                unit = str(r["Unit"])
                val_str = f"{val:,.3f}" if val < 1_000_000 else f"{val:,.0f}"
                val_with_unit = f"{val_str} {unit}".strip()
                print(f"  {str(r['Record']):<22} {str(r['Body / System']):<40} {val_with_unit:>20}")

        print()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# edda trip
# ---------------------------------------------------------------------------

def cmd_trip(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pdm run trip",
        description=(
            "Print exploration statistics for a specific date range.\n"
            "Useful for comparing a single expedition against other tools."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _db_arg(parser)
    parser.add_argument(
        "--from", dest="date_from", required=True, metavar="YYYY-MM-DD[THH:MM]",
        help="Start of range, inclusive. Date only or with time, e.g. '2026-01-18 14:30'.",
    )
    parser.add_argument(
        "--to", dest="date_to", required=True, metavar="YYYY-MM-DD[THH:MM]",
        help="End of range, inclusive. Date only or with time, e.g. '2026-05-02 22:00'.",
    )
    parser.add_argument(
        "--systems", action="store_true",
        help="Print the full chronological list of systems visited.",
    )
    parser.add_argument(
        "--html", dest="html_out", metavar="PATH", type=Path, default=None,
        help="Write a self-contained HTML report to PATH instead of (or in addition to) the terminal output.",
    )
    args = parser.parse_args(argv)

    conn = _open_report_db(args.db)
    try:
        data = st.trip_summary(conn, args.date_from, args.date_to)

        lo_disp = data["date_from"][:19].replace("T", " ")
        hi_disp = data["date_to"][:19].replace("T", " ")
        print(f"\n=== EDDA -- Trip Statistics  [{lo_disp} to {hi_disp}] ===\n")

        summary_labels = {
            "systems_visited":    "Systems visited",
            "jumps":              "FSD jumps",
            "ly_travelled":       "Light-years travelled",
            "bodies_scanned":     "Bodies scanned (FSS)",
            "bodies_mapped":      "  Bodies mapped (DSS)",
            "planets_landable":   "  Landable planets",
            "first_discoveries":  "  First discoveries",
            "first_mapped":       "  First mapped (DSS, new)",
            "bio_signals_detected": "Bio signals detected (FSS)",
            "bio_signals_bodies": "  Bodies with bio signals",
            "bio_bodies_sampled": "  Bodies sampled (analysed)",
            "organic_scans_done": "Organic scans completed",
            "species_unique":     "  Unique species",
            "organic_credits":    "Exobiology credits earned",
            "exploration_credits":"Exploration credits earned",
        }
        for key, label in summary_labels.items():
            val = data.get(key, 0)
            if "credits" in key or key == "ly_travelled":
                print(f"  {label:<35} {val:>15,.0f}")
            else:
                print(f"  {label:<35} {val:>15,}")

        # --- Estimated values (computed once, used in two sections) ---
        est = st.trip_estimated_values(conn, args.date_from, args.date_to)

        print("\n--- Exobiology Samples ---\n")
        df_org = est["organic_species"]
        if not df_org.empty:
            print(f"  {'Qty':>5}   {'Species':<45} {'Base value':>18}")
            print(f"  {'---':>5}   {'-'*45} {'----------':>18}")
            for _, r in df_org.iterrows():
                print(f"  {int(r['qty']):>5}x  {str(r['species']):<45} "
                      f"{int(r['base_total']):>18,}")
            print()
            print(f"  {'Total base value of exobiology data:':<50} {est['organic_base']:>18,}")
            print(f"  {'With first logged (x5) up to:':<50} {est['organic_first_log']:>18,}")
            print(f"  {'With first logged + Antal bonus up to:':<50} {est['organic_antal']:>18,}")
        else:
            print("  (no organic scans in this range)")

        print("\n--- Planet Types Scanned ---\n")
        bodies = st.trip_body_breakdown_grouped(conn, args.date_from, args.date_to)
        if not bodies.empty:
            print(f"  {'Planet type':<42} {'Scanned':>8}  {'1st disc':>8}  {'Mapped':>7}  {'1st map':>7}")
            print(f"  {'-'*42} {'-------':>8}  {'--------':>8}  {'------':>7}  {'-------':>7}")
            for _, r in bodies.iterrows():
                print(f"  {str(r['planet_group']):<42} {int(r['count']):>8,}  "
                      f"{int(r['first_disc']):>8,}  {int(r['mapped']):>7,}  {int(r['first_mapped']):>7,}")
        else:
            print("  (no planet scans in this range)")

        print(f"\n  {'Estimated value of exploration data:':<50} {est['exploration_estimate']:>18,}")
        print(f"  {'Estimated value of star data (approx):':<50} {est['star_estimate']:>18,}")

        print("\n--- Personal Bests (trip) ---\n")
        records = st.trip_personal_records(conn, args.date_from, args.date_to)
        if not records.empty:
            print(f"  {'Record':<22} {'Body / System':<40} {'Value':>20}")
            print(f"  {'-'*22} {'-'*40} {'-'*20}")
            for _, r in records.iterrows():
                val = float(r["Value"])
                unit = str(r["Unit"])
                val_str = f"{val:,.3f}" if val < 1_000_000 else f"{val:,.0f}"
                val_with_unit = f"{val_str} {unit}".strip()
                print(f"  {str(r['Record']):<22} {str(r['Body / System']):<40} {val_with_unit:>20}")
        else:
            print("  (no body scan data in this range)")

        if args.systems:
            print("\n--- Systems Visited (chronological) ---\n")
            sys_df = st.trip_systems_visited(conn, args.date_from, args.date_to)
            if not sys_df.empty:
                print(f"  {'Timestamp':<22} {'System':<35} {'Cl':>3} {'Dist':>7} "
                      f"{'Bodies':>6} {'1stD':>4} {'BioB':>4} {'BioSig':>6} {'Smp':>3}")
                print(f"  {'-'*22} {'-'*35} {'--':>3} {'-------':>7} "
                      f"{'------':>6} {'----':>4} {'----':>4} {'------':>6} {'---':>3}")
                for _, r in sys_df.iterrows():
                    ts   = str(r["timestamp"])[:19].replace("T", " ")
                    name = str(r["name"])[:35]
                    sc   = str(r["star_class"] or "?")[:3]
                    dist = r["jump_dist"] or 0.0
                    b    = int(r["bodies_scanned"])
                    fd   = int(r["first_disc"])
                    bio  = int(r["bio_bodies"])
                    sig  = int(r["bio_signals"])
                    smp  = int(r["bio_sampled"])
                    print(f"  {ts:<22} {name:<35} {sc:>3} {dist:>7.2f} "
                          f"{b:>6} {fd:>4} {bio:>4} {sig:>6} {smp:>3}")
            else:
                print("  (no jumps in this range)")

        if args.html_out:
            print(f"\nBuilding HTML report...")
            tr.build_trip_report(conn, args.date_from, args.date_to, args.html_out)

        print()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# edjdb-map
# ---------------------------------------------------------------------------

def cmd_map(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pdm run map",
        description="Render galaxy maps from the database.",
    )
    _db_arg(parser)
    _out_arg(parser)
    parser.add_argument(
        "--static-only", action="store_true",
        help="Skip interactive HTML output.",
    )
    parser.add_argument(
        "--interactive-only", action="store_true",
        help="Skip static PNG output.",
    )
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    conn = _open_report_db(args.db)
    try:
        print("Loading system data...")
        df = st.systems_for_map(conn)
        print(f"  {len(df):,} systems with coordinates.")

        if not args.interactive_only:
            mp.plot_galaxy_map_static(
                df, args.out / "galaxy_density.png", colour_by="density")
            mp.plot_galaxy_map_static(
                df, args.out / "galaxy_bio.png", colour_by="bio")
            mp.plot_galaxy_map_static(
                df, args.out / "galaxy_first_discoveries.png",
                colour_by="first_discovery")
            mp.plot_galaxy_side_view_static(
                df, args.out / "galaxy_side.png")

        if not args.static_only:
            mp.plot_galaxy_map_interactive(
                df, args.out / "galaxy_interactive.html",
                colour_by="bodies_scanned")
            mp.plot_bio_heatmap_interactive(
                df, args.out / "galaxy_bio_interactive.html")

        print("Loading sector data...")
        df_sec = st.sector_map_data(conn)
        print(f"  {len(df_sec):,} sectors.")

        if not args.interactive_only:
            mp.plot_sector_map_static(
                df_sec, args.out / "sector_heatmap.png")
        if not args.static_only:
            mp.plot_sector_map_interactive(
                df_sec, args.out / "sector_heatmap.html")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# edjdb-charts
# ---------------------------------------------------------------------------

def cmd_charts(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pdm run charts",
        description="Render exploration charts from the database.",
    )
    _db_arg(parser)
    _out_arg(parser)
    parser.add_argument(
        "--static-only", action="store_true",
        help="Skip interactive HTML output.",
    )
    parser.add_argument(
        "--interactive-only", action="store_true",
        help="Skip static PNG output.",
    )
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    conn = _open_report_db(args.db)

    try:
        static = not args.interactive_only
        interactive = not args.static_only

        print("Body type distribution...")
        df_bodies = st.body_type_counts(conn)
        if static:
            ch.plot_body_types_static(df_bodies, args.out / "body_types.png")
        if interactive:
            ch.plot_body_types_interactive(
                df_bodies, args.out / "body_types.html")

        print("Star classes...")
        df_stars = st.star_class_counts(conn)
        if static:
            ch.plot_star_classes_static(df_stars, args.out / "star_classes.png")

        print("Exploration income...")
        df_expl = st.exploration_income_over_time(conn)
        if static:
            ch.plot_exploration_income_static(
                df_expl, args.out / "exploration_income.png")
        if interactive:
            ch.plot_exploration_income_interactive(
                df_expl, args.out / "exploration_income.html")

        print("Exobiology income...")
        df_org = st.organic_income_over_time(conn)
        if static:
            ch.plot_organic_income_static(
                df_org, args.out / "organic_income.png")

        print("Jump histogram...")
        jump_series = st.jump_distance_histogram_data(conn)
        if static:
            ch.plot_jump_histogram_static(
                jump_series, args.out / "jump_histogram.png")

        print("Top species...")
        df_species = st.top_species(conn)
        if static:
            ch.plot_top_species_static(
                df_species, args.out / "top_species.png")

        print("Species × planet type heatmap...")
        df_sxp = st.species_by_planet_type(conn)
        if static:
            ch.plot_species_planet_heatmap_static(
                df_sxp, args.out / "species_planet_heatmap.png")
        if interactive:
            ch.plot_species_planet_heatmap_interactive(
                df_sxp, args.out / "species_planet_heatmap.html")

        print("Body value breakdown...")
        df_bval = st.body_values_table(conn)
        if static:
            ch.plot_body_values_by_type_static(
                df_bval, args.out / "body_values_by_type.png")
            ch.plot_body_value_histogram_static(
                df_bval, args.out / "body_value_histogram.png")
        if interactive:
            ch.plot_body_values_by_type_interactive(
                df_bval, args.out / "body_values_by_type.html")

        print("Organic value breakdown...")
        df_oval = st.organic_values_table(conn, antal_bonus=False)
        if static:
            ch.plot_organic_value_by_species_static(
                df_oval, args.out / "organic_value_by_species.png")
            ch.plot_organic_value_by_planet_type_static(
                df_oval, args.out / "organic_value_by_planet_type.png")
        if interactive:
            ch.plot_organic_value_by_species_interactive(
                df_oval, args.out / "organic_value_by_species.html")

        print("Valuable regions...")
        df_svd = st.sector_valuable_data(conn)
        df_rz  = st.body_rate_vs_z(conn)
        df_rsc = st.body_rate_vs_star_class(conn)
        if static:
            ch.plot_body_rate_vs_z_static(
                df_rz,  args.out / "body_rate_vs_z.png")
            ch.plot_body_rate_vs_star_class_static(
                df_rsc, args.out / "body_rate_vs_star_class.png")
        if interactive:
            ch.plot_body_rate_vs_z_interactive(
                df_rz,  args.out / "body_rate_vs_z.html")
            ch.plot_body_rate_vs_star_class_interactive(
                df_rsc, args.out / "body_rate_vs_star_class.html")
            mp.plot_sector_valuable_map_interactive(
                df_svd, args.out / "sector_terra_rate.html",
                metric="terra_rate")
            mp.plot_sector_valuable_map_interactive(
                df_svd, args.out / "sector_elw_rate.html",
                metric="elw_rate")

        print(f"\nAll charts written to {args.out}/")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# edjdb-dashboard
# ---------------------------------------------------------------------------

def cmd_dashboard(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pdm run dashboard",
        description="Build a single-page HTML dashboard with all analytics.",
    )
    _db_arg(parser)
    parser.add_argument(
        "--out", type=Path, default=Path("dashboard.html"),
        metavar="FILE",
        help="Output HTML file (default: ./dashboard.html)",
    )
    args = parser.parse_args(argv)

    conn = _open_report_db(args.db)
    try:
        db.build_dashboard(conn, args.out)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# stratum — Stratum Tectonicas research report
# ---------------------------------------------------------------------------

def cmd_stratum(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pdm run stratum",
        description=(
            "Build a Stratum Tectonicas research report.\n\n"
            "Normal mode (requires --db):\n"
            "  pdm run stratum [--min-temp K] [--max-temp K] [--out FILE]\n"
            "  pdm run stratum --export FILE [--min-temp K] [--max-temp K]\n\n"
            "Aggregated mode (no DB needed):\n"
            "  pdm run stratum --from-files FILE1 [FILE2 ...] [--out FILE]"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _db_arg(parser)
    parser.add_argument(
        "--out", type=Path, default=Path("stratum_report.html"),
        metavar="FILE",
        help="Output HTML file (default: ./stratum_report.html)",
    )
    parser.add_argument(
        "--min-temp", type=float, default=165.0, metavar="K",
        help="Minimum surface temperature in K (default: 165)",
    )
    parser.add_argument(
        "--max-temp", type=float, default=None, metavar="K",
        help="Maximum surface temperature in K (default: no limit)",
    )
    parser.add_argument(
        "--export", type=Path, default=None, metavar="FILE",
        help="Export candidates to a JSONL file instead of building the report",
    )
    parser.add_argument(
        "--from-files", nargs="+", type=str, metavar="PATTERN",
        help=(
            "Build an aggregated report from JSONL exports — accepts glob patterns, "
            "e.g. --from-files stratum_candidates*.jsonl"
        ),
    )
    args = parser.parse_args(argv)

    if args.from_files:
        import glob as _glob
        paths: list[Path] = []
        for pattern in args.from_files:
            matched = sorted(_glob.glob(pattern))
            if not matched:
                print(f"  Warning: no files matched '{pattern}'")
            paths.extend(Path(p) for p in matched)
        if not paths:
            print("Error: no files found matching the given pattern(s).")
            return
        print(f"Building aggregated Stratum report from {len(paths)} file(s)...")
        sr.build_stratum_report_from_files(paths, args.out)
        return

    conn = _open_report_db(args.db)
    try:
        if args.export:
            print("Exporting Stratum candidates...")
            sr.export_candidates(conn, args.export,
                                 min_temp=args.min_temp, max_temp=args.max_temp)
        else:
            print("Building Stratum Tectonicas report...")
            sr.build_stratum_report(conn, args.out,
                                    min_temp=args.min_temp, max_temp=args.max_temp)
    finally:
        conn.close()
