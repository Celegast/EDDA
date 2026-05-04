"""
Text-based statistics derived from the database.
Returns structured dicts / DataFrames for use by charts and CLI.
"""

import re
import sqlite3
import numpy as np
import pandas as pd

SECTOR_SIZE = 1200  # ly — ED sector cube side length


# Matches the procedural "XX-X" tag — everything before it is the sector name.
# Examples: "Hypaa Pruae OZ-D d13-76" → "Hypaa Pruae"
#           "Kueme DX-A d1-175"        → "Kueme"
_SECTOR_RE = re.compile(r"^(.*?)\s+[A-Z]{2}-[A-Z]\b")

# Strips trailing system index to get the boxel name.
# Examples: "Prooe Drye ZQ-K d9-5"  → "Prooe Drye ZQ-K d9"
#           "Byua Aim XV-U d3-9"     → "Byua Aim XV-U d3"
#           "Pueloe BZ-A d123"       → "Pueloe BZ-A d"
_BOXEL_RE = re.compile(r"-\d+$|\d+$")

# He% ranges (from community data) where Stratum Tectonicas probability exceeds 5%.
# Source: "Boxel Helium vs Tectonicas" chart — orange line above 5% threshold.
_TECTONICAS_HE_RANGES: list[tuple[float, float]] = [
    (24.2, 24.5),  # sharp spike, peak ~8%
    (25.9, 26.5),  # broad peak, peak ~6%
]

# He% ranges where average system exploration value exceeds 3.5 MCr.
# Source: EDDA "Boxel He% vs Average System Value" chart.
_HIGH_VALUE_HE_RANGES: list[tuple[float, float]] = [
    (24.7, 25.4),
    (26.2, 26.4),
    (30.05, 30.15),
]
_HIGH_VALUE_THRESHOLD_CR = 3_500_000


def extract_sector(name: str) -> str:
    """Return the sector name for a procedurally generated system, else the name itself."""
    m = _SECTOR_RE.match(name)
    return m.group(1) if m else name


def summary(conn: sqlite3.Connection) -> dict:
    """High-level counts for a quick overview."""
    def scalar(sql, *args):
        row = conn.execute(sql, args).fetchone()
        return row[0] if row else 0

    return {
        "systems_visited":      scalar("SELECT COUNT(*) FROM systems"),
        "jumps":                scalar("SELECT COUNT(*) FROM jumps"),
        "ly_travelled":         scalar("SELECT COALESCE(SUM(jump_dist),0) FROM jumps"),
        "bodies_scanned":       scalar("SELECT COUNT(*) FROM bodies"),
        "bodies_mapped":        scalar("SELECT COUNT(*) FROM bodies WHERE was_mapped=1"),
        "planets_landable":     scalar("SELECT COUNT(*) FROM bodies WHERE is_landable=1"),
        "first_discoveries":    scalar("SELECT COUNT(*) FROM bodies WHERE first_discovered=1"),
        "first_mapped":         scalar("SELECT COUNT(*) FROM bodies WHERE was_mapped=1 AND first_mapped=1"),
        "bio_signals_bodies":   scalar("SELECT COUNT(*) FROM bodies WHERE bio_signals>0"),
        "organic_scans_done":   scalar("SELECT COUNT(*) FROM organic_scans WHERE scan_state='Analyse'"),
        "species_unique":       scalar("SELECT COUNT(DISTINCT species) FROM organic_scans WHERE scan_state='Analyse'"),
        "organic_credits":      scalar("SELECT COALESCE(SUM(total),0) FROM organic_sales"),
        "exploration_credits":  scalar("SELECT COALESCE(SUM(total_earnings),0) FROM exploration_sales"),
        "codex_new_entries":    scalar("SELECT COUNT(*) FROM codex_entries WHERE is_new_entry=1"),
        "journal_files":        scalar("SELECT COUNT(*) FROM journal_files"),
    }


def personal_records(conn: sqlite3.Connection) -> pd.DataFrame:
    """Personal bests across all scanned bodies."""
    queries = [
        ("Highest gravity",  "g",
         "SELECT name, system_address, surface_gravity_g AS value FROM bodies WHERE surface_gravity_g IS NOT NULL ORDER BY surface_gravity_g DESC LIMIT 1"),
        ("Lowest gravity",   "g",
         "SELECT name, system_address, surface_gravity_g AS value FROM bodies WHERE surface_gravity_g > 0 ORDER BY surface_gravity_g ASC LIMIT 1"),
        ("Hottest surface",  "K",
         "SELECT name, system_address, surface_temp_k AS value FROM bodies WHERE surface_temp_k IS NOT NULL ORDER BY surface_temp_k DESC LIMIT 1"),
        ("Coldest surface",  "K",
         "SELECT name, system_address, surface_temp_k AS value FROM bodies WHERE surface_temp_k > 0 ORDER BY surface_temp_k ASC LIMIT 1"),
        ("Largest radius",   "km",
         "SELECT name, system_address, radius_km AS value FROM bodies WHERE radius_km IS NOT NULL ORDER BY radius_km DESC LIMIT 1"),
        ("Smallest radius",  "km",
         "SELECT name, system_address, radius_km AS value FROM bodies WHERE radius_km > 0 ORDER BY radius_km ASC LIMIT 1"),
        ("Most bio signals", "",
         "SELECT name, system_address, bio_signals AS value FROM bodies ORDER BY bio_signals DESC LIMIT 1"),
        ("Longest jump",     "ly",
         "SELECT s.name, j.system_address, j.jump_dist AS value FROM jumps j JOIN systems s ON s.system_address=j.system_address ORDER BY jump_dist DESC LIMIT 1"),
    ]
    rows = []
    for label, unit, sql in queries:
        row = conn.execute(sql).fetchone()
        if row:
            rows.append({
                "Record":        label,
                "Body / System": row[0],
                "Value":         round(float(row[2]), 3),
                "Unit":          unit,
            })
    return pd.DataFrame(rows)


def body_type_counts(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
        SELECT subtype, COUNT(*) AS count
        FROM bodies
        WHERE subtype IS NOT NULL AND body_type = 'Planet'
        GROUP BY subtype
        ORDER BY count DESC
    """
    return pd.read_sql_query(sql, conn)


def star_class_counts(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
        SELECT star_class, COUNT(*) AS count
        FROM systems
        WHERE star_class IS NOT NULL
        GROUP BY star_class
        ORDER BY count DESC
    """
    return pd.read_sql_query(sql, conn)


def top_species(conn: sqlite3.Connection, n: int = 20) -> pd.DataFrame:
    sql = """
        SELECT sc.species_localised AS species,
               COUNT(*) AS scans,
               COALESCE(sal.total_credits, 0) AS total_credits
        FROM organic_scans sc
        LEFT JOIN (
            SELECT species, SUM(total) AS total_credits
            FROM organic_sales
            GROUP BY species
        ) sal ON sal.species = sc.species
        WHERE sc.scan_state = 'Analyse'
        GROUP BY sc.species
        ORDER BY scans DESC
        LIMIT ?
    """
    return pd.read_sql_query(sql, conn, params=(n,))


def species_by_planet_type(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
        SELECT b.subtype AS planet_type,
               sc.genus_localised AS genus,
               COUNT(DISTINCT sc.species) AS species_count,
               COUNT(*) AS scan_count
        FROM organic_scans sc
        JOIN bodies b ON b.system_address = sc.system_address AND b.body_id = sc.body_id
        WHERE sc.scan_state = 'Analyse'
        GROUP BY b.subtype, sc.genus_localised
        ORDER BY scan_count DESC
    """
    return pd.read_sql_query(sql, conn)


def exploration_income_over_time(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
        SELECT DATE(timestamp) AS date,
               SUM(total_earnings) AS credits
        FROM exploration_sales
        GROUP BY DATE(timestamp)
        ORDER BY date
    """
    df = pd.read_sql_query(sql, conn)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["cumulative"] = df["credits"].cumsum()
    return df


def organic_income_over_time(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
        SELECT DATE(timestamp) AS date,
               SUM(total) AS credits
        FROM organic_sales
        GROUP BY DATE(timestamp)
        ORDER BY date
    """
    df = pd.read_sql_query(sql, conn)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["cumulative"] = df["credits"].cumsum()
    return df


def jump_distance_histogram_data(conn: sqlite3.Connection) -> pd.Series:
    sql = "SELECT jump_dist FROM jumps WHERE jump_dist IS NOT NULL"
    df = pd.read_sql_query(sql, conn)
    return df["jump_dist"]


def systems_by_region(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
        SELECT region, COUNT(*) AS count
        FROM systems
        WHERE region IS NOT NULL
        GROUP BY region
        ORDER BY count DESC
    """
    return pd.read_sql_query(sql, conn)


def codex_by_category(conn: sqlite3.Connection) -> pd.DataFrame:
    sql = """
        SELECT category, COUNT(*) AS entries, SUM(is_new_entry) AS new_entries
        FROM codex_entries
        GROUP BY category
        ORDER BY entries DESC
    """
    return pd.read_sql_query(sql, conn)


def sector_map_data(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Per-sector aggregate for the sector heat map.

    Returns one row per sector with:
      sector        — sector name (extracted from system name)
      system_count  — number of visited systems in this sector
      grid_cx/y/z   — grid-aligned cube centre (snapped to SECTOR_SIZE grid)

    Grid alignment: all systems sharing a sector name are inside the same
    1200 ly cube by definition.  floor(any_coord / SECTOR_SIZE) recovers the
    grid cell index, and adding 0.5 gives the cube centre.  This guarantees
    neighbouring sectors are exactly edge-to-edge.
    """
    df = pd.read_sql_query(
        "SELECT name, x, y, z FROM systems WHERE x IS NOT NULL", conn
    )
    if df.empty:
        return pd.DataFrame(columns=["sector", "system_count",
                                     "grid_cx", "grid_cy", "grid_cz"])

    df["sector"] = df["name"].apply(extract_sector)

    # Use the mean coordinate to identify the grid cell — robust against
    # sparse sectors where only one corner was visited.
    grp = df.groupby("sector").agg(
        system_count=("name", "count"),
        mean_x=("x", "mean"),
        mean_y=("y", "mean"),
        mean_z=("z", "mean"),
    ).reset_index()

    # Snap to grid: centre = (floor(mean / S) + 0.5) * S
    for ax in ("x", "y", "z"):
        grp[f"grid_c{ax}"] = (
            np.floor(grp[f"mean_{ax}"] / SECTOR_SIZE) + 0.5
        ) * SECTOR_SIZE

    return grp[["sector", "system_count", "grid_cx", "grid_cy", "grid_cz"]]\
        .sort_values("system_count", ascending=False)


def sector_valuable_data(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Per-sector rates for ELW, Water Worlds, terraformable bodies, and bio signals.

    Rates are per-system-visited so that well-explored sectors don't dominate
    over lightly-explored but genuinely rich ones.

    Returns one row per sector with columns:
      sector, system_count, grid_cx/y/z,
      elw_count, ww_count, ammonia_count, terra_count, bio_count,
      elw_rate, ww_rate, ammonia_rate, terra_rate, bio_rate
    """
    # Per-system counts of valuable body types
    sys_sql = """
        SELECT s.system_address, s.name, s.x, s.y, s.z,
               COUNT(DISTINCT CASE WHEN b.subtype = 'Earthlike body' THEN b.id END)
                   AS elw,
               COUNT(DISTINCT CASE WHEN b.subtype = 'Water world' THEN b.id END)
                   AS ww,
               COUNT(DISTINCT CASE WHEN b.subtype = 'Ammonia world' THEN b.id END)
                   AS ammonia,
               COUNT(DISTINCT CASE
                   WHEN b.terraform_state IS NOT NULL
                    AND b.terraform_state NOT IN ('', 'Not terraformable') THEN b.id
               END) AS terra,
               MAX(CASE WHEN b.bio_signals > 0 THEN 1 ELSE 0 END) AS has_bio
        FROM systems s
        LEFT JOIN bodies b ON b.system_address = s.system_address
        WHERE s.x IS NOT NULL
        GROUP BY s.system_address
    """
    df = pd.read_sql_query(sys_sql, conn)
    if df.empty:
        return pd.DataFrame()

    df["sector"] = df["name"].apply(extract_sector)

    grp = df.groupby("sector").agg(
        system_count=("name", "count"),
        mean_x=("x", "mean"),
        mean_y=("y", "mean"),
        mean_z=("z", "mean"),
        elw_count=("elw", "sum"),
        ww_count=("ww", "sum"),
        ammonia_count=("ammonia", "sum"),
        terra_count=("terra", "sum"),
        bio_count=("has_bio", "sum"),
    ).reset_index()

    for ax in ("x", "y", "z"):
        grp[f"grid_c{ax}"] = (
            np.floor(grp[f"mean_{ax}"] / SECTOR_SIZE) + 0.5
        ) * SECTOR_SIZE

    n = grp["system_count"]
    grp["elw_rate"]    = grp["elw_count"]    / n
    grp["ww_rate"]     = grp["ww_count"]     / n
    grp["ammonia_rate"]= grp["ammonia_count"]/ n
    grp["terra_rate"]  = grp["terra_count"]  / n
    grp["bio_rate"]    = grp["bio_count"]    / n

    cols = ["sector", "system_count",
            "grid_cx", "grid_cy", "grid_cz",
            "elw_count", "ww_count", "ammonia_count", "terra_count", "bio_count",
            "elw_rate", "ww_rate", "ammonia_rate", "terra_rate", "bio_rate"]
    return grp[cols].sort_values("terra_rate", ascending=False)


def body_rate_vs_z(conn: sqlite3.Connection,
                   bin_size: float = 500) -> pd.DataFrame:
    """
    Terraformable/ELW/WW/bio rates binned by galactic Y coordinate.

    Y ≈ 0 is the galactic plane (higher metallicity, more heavy-element worlds).
    Returns one row per Y bin with columns:
      y_bin_centre, systems, elw_rate, ww_rate, terra_rate, bio_rate
    Only bins with ≥ 5 systems are included to avoid noise from sparse coverage.
    """
    sys_sql = """
        SELECT s.y,
               COUNT(DISTINCT CASE WHEN b.subtype = 'Earthlike body' THEN b.id END)
                   AS elw,
               COUNT(DISTINCT CASE WHEN b.subtype = 'Water world' THEN b.id END)
                   AS ww,
               COUNT(DISTINCT CASE
                   WHEN b.terraform_state IS NOT NULL
                    AND b.terraform_state NOT IN ('', 'Not terraformable') THEN b.id
               END) AS terra,
               MAX(CASE WHEN b.bio_signals > 0 THEN 1 ELSE 0 END) AS has_bio
        FROM systems s
        LEFT JOIN bodies b ON b.system_address = s.system_address
        WHERE s.y IS NOT NULL
        GROUP BY s.system_address
    """
    df = pd.read_sql_query(sys_sql, conn)
    if df.empty:
        return pd.DataFrame()

    df["y_bin"] = (np.floor(df["y"] / bin_size) * bin_size + bin_size / 2)

    grp = df.groupby("y_bin").agg(
        systems=("y", "count"),
        elw=("elw", "sum"),
        ww=("ww", "sum"),
        terra=("terra", "sum"),
        bio=("has_bio", "sum"),
    ).reset_index()

    grp = grp[grp["systems"] >= 5].copy()

    n = grp["systems"]
    grp["elw_rate"]   = grp["elw"]   / n
    grp["ww_rate"]    = grp["ww"]    / n
    grp["terra_rate"] = grp["terra"] / n
    grp["bio_rate"]   = grp["bio"]   / n

    grp.rename(columns={"y_bin": "y_bin_centre"}, inplace=True)
    return grp.sort_values("y_bin_centre")


def body_rate_vs_star_class(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Terraformable/ELW/WW/bio rates per star class.

    Only star classes where at least 10 systems were visited are included.
    Returns one row per star class with columns:
      star_class, systems, elw_rate, ww_rate, terra_rate, bio_rate
    """
    sys_sql = """
        SELECT s.star_class,
               COUNT(DISTINCT CASE WHEN b.subtype = 'Earthlike body' THEN b.id END)
                   AS elw,
               COUNT(DISTINCT CASE WHEN b.subtype = 'Water world' THEN b.id END)
                   AS ww,
               COUNT(DISTINCT CASE
                   WHEN b.terraform_state IS NOT NULL
                    AND b.terraform_state NOT IN ('', 'Not terraformable') THEN b.id
               END) AS terra,
               MAX(CASE WHEN b.bio_signals > 0 THEN 1 ELSE 0 END) AS has_bio
        FROM systems s
        LEFT JOIN bodies b ON b.system_address = s.system_address
        WHERE s.star_class IS NOT NULL
        GROUP BY s.system_address
    """
    df = pd.read_sql_query(sys_sql, conn)
    if df.empty:
        return pd.DataFrame()

    grp = df.groupby("star_class").agg(
        systems=("star_class", "count"),
        elw=("elw", "sum"),
        ww=("ww", "sum"),
        terra=("terra", "sum"),
        bio=("has_bio", "sum"),
    ).reset_index()

    grp = grp[grp["systems"] >= 10].copy()

    n = grp["systems"]
    grp["elw_rate"]   = grp["elw"]   / n
    grp["ww_rate"]    = grp["ww"]    / n
    grp["terra_rate"] = grp["terra"] / n
    grp["bio_rate"]   = grp["bio"]   / n

    return grp.sort_values("terra_rate", ascending=False)


def body_values_table(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Per-body estimated exploration credit value using the Odyssey formula.

    Returns all scanned bodies that have enough data for the formula
    (planet class + mass), plus bodies that were mapped.
    """
    from .valuation import body_scan_value

    sql = """
        SELECT b.system_address, b.body_id, b.name,
               b.subtype        AS planet_class,
               b.mass_em,
               b.terraform_state,
               b.first_discovered,
               b.was_mapped,
               b.first_mapped,
               b.bio_signals,
               b.geo_signals,
               b.is_landable,
               b.surface_gravity_g,
               b.surface_temp_k,
               b.scanned_at,
               s.name           AS system_name,
               s.x, s.y, s.z
        FROM bodies b
        JOIN systems s ON s.system_address = b.system_address
        WHERE b.body_type = 'Planet'
          AND b.subtype IS NOT NULL
          AND b.mass_em IS NOT NULL
        ORDER BY b.scanned_at
    """
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        return df

    df["estimated_value"] = df.apply(
        lambda r: body_scan_value(
            planet_class=r["planet_class"],
            mass_em=r["mass_em"],
            terraform_state=r["terraform_state"],
            first_discovered=bool(r["first_discovered"]),
            was_mapped=bool(r["was_mapped"]),
            first_mapped=bool(r["first_mapped"]),
        ),
        axis=1,
    )
    return df


def organic_values_table(conn: sqlite3.Connection,
                         antal_bonus: bool = False) -> pd.DataFrame:
    """
    Per completed-scan organic value table.

    Actual sale values are used where available (joined from organic_sales).
    For scans not yet sold, the species lookup table provides the estimate.
    is_first_log is inferred from the Bonus field in organic_sales:
      bonus > 0  →  first-log sale (bonus = 4 × base value).
    """
    from .valuation import organic_value, SPECIES_VALUES

    # Completed scans
    scans_sql = """
        SELECT sc.rowid            AS scan_id,
               sc.system_address,
               sc.body_id,
               sc.timestamp,
               sc.species_localised,
               sc.genus_localised,
               b.name             AS body_name,
               b.subtype          AS planet_class,
               s.name             AS system_name
        FROM organic_scans sc
        LEFT JOIN bodies  b ON b.system_address = sc.system_address
                            AND b.body_id        = sc.body_id
        LEFT JOIN systems s ON s.system_address  = sc.system_address
        WHERE sc.scan_state = 'Analyse'
        ORDER BY sc.timestamp
    """
    df = pd.read_sql_query(scans_sql, conn)
    if df.empty:
        return df

    # Per-species sale summary: base value and whether any first-log bonus was paid.
    # bonus > 0 in organic_sales means that specific sale row was a first-log.
    sales_sql = """
        SELECT species_localised,
               MIN(value)              AS base_value,
               SUM(CASE WHEN bonus > 0 THEN 1 ELSE 0 END) AS first_log_count,
               COUNT(*)                AS sale_count,
               SUM(total)              AS total_earned
        FROM organic_sales
        GROUP BY species_localised
    """
    sales = pd.read_sql_query(sales_sql, conn)
    sales_map = {
        row["species_localised"]: row
        for _, row in sales.iterrows()
        if row["species_localised"]
    }

    rows = []
    # Count how many first-log sales we've "used" per species to match them
    # against scans in chronological order.
    first_log_budget: dict[str, int] = {}

    for _, r in df.iterrows():
        sp = r["species_localised"] or ""
        sale_row = sales_map.get(sp)

        if sale_row is not None:
            base = int(sale_row["base_value"])
            actual_total = int(sale_row["total_earned"])
            # Allocate first-log flags to the first N scans of this species
            budget = first_log_budget.get(sp, 0)
            remaining = int(sale_row["first_log_count"]) - budget
            is_first_log = remaining > 0
            first_log_budget[sp] = budget + (1 if is_first_log else 0)
        else:
            base = SPECIES_VALUES.get(sp, 0)
            actual_total = None
            # Unsold: conservatively assume first-log (likely a new discovery)
            is_first_log = True

        estimated = organic_value(sp, is_first_log=is_first_log,
                                  antal_bonus=antal_bonus)

        rows.append({
            "timestamp":         r["timestamp"],
            "system_name":       r["system_name"],
            "body_name":         r["body_name"],
            "planet_class":      r["planet_class"],
            "genus":             r["genus_localised"],
            "species":           sp,
            "is_first_log":      is_first_log,
            "base_value":        base,
            "estimated_payout":  estimated,
            "actual_total_sold": actual_total,
        })

    return pd.DataFrame(rows)


def species_system_locations(conn: sqlite3.Connection,
                             species: str) -> pd.DataFrame:
    """
    Systems where a given species was found (completed scans only),
    with scan count per system and galactic coordinates.
    """
    sql = """
        SELECT s.name AS system_name, s.x, s.y, s.z,
               COUNT(*) AS scan_count
        FROM organic_scans sc
        JOIN systems s ON s.system_address = sc.system_address
        WHERE sc.scan_state = 'Analyse'
          AND sc.species_localised = ?
          AND s.x IS NOT NULL
        GROUP BY sc.system_address
        ORDER BY scan_count DESC
    """
    return pd.read_sql_query(sql, conn, params=(species,))


def star_class_system_details(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Per-system row for the star-class catalogue.
    Each row is one visited system, grouped later by star_class in Python.
    """
    sql = """
        SELECT s.name AS system_name, s.star_class, s.x, s.y, s.z,
               COUNT(DISTINCT b.body_id)                              AS body_count,
               COALESCE(SUM(CASE WHEN b.bio_signals > 0 THEN 1 ELSE 0 END), 0)
                                                                      AS bodies_with_bio,
               COALESCE(MAX(b.first_discovered), 0)                   AS has_first_disc
        FROM systems s
        LEFT JOIN bodies b ON b.system_address = s.system_address
        WHERE s.star_class IS NOT NULL
        GROUP BY s.system_address, s.name, s.star_class
        ORDER BY s.star_class, body_count DESC
    """
    return pd.read_sql_query(sql, conn)


def top_systems_by_bodies(conn: sqlite3.Connection, n: int = 10) -> pd.DataFrame:
    """Top n systems by total body count (FSS scans)."""
    sql = """
        SELECT s.name, s.x, s.y, s.z,
               COUNT(DISTINCT b.body_id)                              AS body_count,
               COALESCE(SUM(b.bio_signals), 0)                       AS bio_signals,
               SUM(CASE WHEN b.first_discovered=1 THEN 1 ELSE 0 END) AS first_disc
        FROM systems s
        JOIN bodies b ON b.system_address = s.system_address
        WHERE s.x IS NOT NULL
        GROUP BY s.system_address
        ORDER BY body_count DESC
        LIMIT ?
    """
    return pd.read_sql_query(sql, conn, params=(n,))


def top_systems_by_bio(conn: sqlite3.Connection, n: int = 10) -> pd.DataFrame:
    """Top n systems by total bio-signal count."""
    sql = """
        SELECT s.name, s.x, s.y, s.z,
               COUNT(DISTINCT b.body_id)                              AS body_count,
               COALESCE(SUM(b.bio_signals), 0)                       AS bio_signals,
               SUM(CASE WHEN b.first_discovered=1 THEN 1 ELSE 0 END) AS first_disc
        FROM systems s
        JOIN bodies b ON b.system_address = s.system_address
        WHERE s.x IS NOT NULL
        GROUP BY s.system_address
        HAVING SUM(b.bio_signals) > 0
        ORDER BY bio_signals DESC
        LIMIT ?
    """
    return pd.read_sql_query(sql, conn, params=(n,))


def top_systems_by_exobio_value(conn: sqlite3.Connection, n: int = 10) -> pd.DataFrame:
    """Top n systems by estimated exobiology value (completed organic scans)."""
    from .valuation import SPECIES_VALUES
    sql = """
        SELECT s.name, s.x, s.y, s.z, s.system_address,
               sc.species_localised AS species
        FROM organic_scans sc
        JOIN systems s ON s.system_address = sc.system_address
        WHERE sc.scan_state = 'Analyse'
          AND s.x IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        return pd.DataFrame(columns=["name", "x", "y", "z", "species_count", "total_value"])
    df["value"] = df["species"].map(lambda sp: SPECIES_VALUES.get((sp or "").strip(), 0))
    grp = (
        df.groupby(["system_address", "name", "x", "y", "z"], sort=False)
        .agg(species_count=("species", "nunique"), total_value=("value", "sum"))
        .reset_index()
        .sort_values("total_value", ascending=False)
        .head(n)
    )
    return grp[["name", "x", "y", "z", "species_count", "total_value"]]


def top_systems_by_exploration_value(conn: sqlite3.Connection, n: int = 10) -> pd.DataFrame:
    """Top n systems by estimated exploration value (sum of body scan values)."""
    from .valuation import body_scan_value
    sql = """
        SELECT s.name, s.x, s.y, s.z, s.system_address, b.body_id,
               b.subtype AS planet_class, b.mass_em, b.terraform_state,
               b.first_discovered, b.was_mapped, b.first_mapped
        FROM systems s
        JOIN bodies b ON b.system_address = s.system_address
        WHERE b.body_type = 'Planet'
          AND b.subtype IS NOT NULL
          AND b.mass_em IS NOT NULL
          AND s.x IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        return pd.DataFrame(columns=["name", "x", "y", "z", "body_count", "total_value"])
    df["estimated_value"] = df.apply(
        lambda r: body_scan_value(
            planet_class=r["planet_class"],
            mass_em=r["mass_em"],
            terraform_state=r["terraform_state"],
            first_discovered=bool(r["first_discovered"]),
            was_mapped=bool(r["was_mapped"]),
            first_mapped=bool(r["first_mapped"]),
        ),
        axis=1,
    )
    grp = (
        df.groupby(["system_address", "name", "x", "y", "z"], sort=False)
        .agg(body_count=("body_id", "count"), total_value=("estimated_value", "sum"))
        .reset_index()
        .sort_values("total_value", ascending=False)
        .head(n)
    )
    return grp[["name", "x", "y", "z", "body_count", "total_value"]]


def boxel_he_vs_value(
    conn: sqlite3.Connection,
    min_systems: int = 5,
) -> pd.DataFrame:
    """
    One row per boxel with enough scanned systems.
    Columns: boxel, system_count, he_mean, he_systems, avg_system_value.

    Requires atmosphere_he_pct populated (post-reimport).
    Returns empty DataFrame when no He% data exists yet.
    """
    from .valuation import body_scan_value

    planet_sql = """
        SELECT s.system_address, s.name,
               b.body_id, b.subtype AS planet_class, b.mass_em,
               b.terraform_state, b.first_discovered, b.was_mapped, b.first_mapped
        FROM systems s
        JOIN bodies b ON b.system_address = s.system_address
        WHERE b.body_type = 'Planet'
          AND b.subtype IS NOT NULL
          AND b.mass_em IS NOT NULL
    """
    df_p = pd.read_sql_query(planet_sql, conn)
    if df_p.empty:
        return pd.DataFrame()

    df_p["est_value"] = df_p.apply(
        lambda r: body_scan_value(
            planet_class=r["planet_class"],
            mass_em=r["mass_em"],
            terraform_state=r["terraform_state"],
            first_discovered=bool(r["first_discovered"]),
            was_mapped=bool(r["was_mapped"]),
            first_mapped=bool(r["first_mapped"]),
        ),
        axis=1,
    )
    sys_val = (
        df_p.groupby(["system_address", "name"])
        .agg(total_value=("est_value", "sum"))
        .reset_index()
    )
    sys_val["boxel"] = sys_val["name"].apply(lambda n: _BOXEL_RE.sub("", n))

    he_sql = """
        SELECT s.name AS system_name, b.atmosphere_he_pct
        FROM bodies b
        JOIN systems s ON s.system_address = b.system_address
        WHERE LOWER(b.subtype) LIKE '%gas giant%'
          AND b.atmosphere_he_pct IS NOT NULL
    """
    df_he = pd.read_sql_query(he_sql, conn)
    if df_he.empty:
        return pd.DataFrame()

    df_he["boxel"] = df_he["system_name"].apply(lambda n: _BOXEL_RE.sub("", n))
    he_grp = (
        df_he.groupby("boxel")
        .agg(he_mean=("atmosphere_he_pct", "mean"), he_systems=("atmosphere_he_pct", "count"))
        .reset_index()
    )

    val_grp = (
        sys_val.groupby("boxel")
        .agg(system_count=("system_address", "count"), avg_system_value=("total_value", "mean"))
        .reset_index()
    )

    merged = val_grp.merge(he_grp, on="boxel", how="inner")
    return merged[merged["system_count"] >= min_systems].reset_index(drop=True)


def nearby_helium_boxels(
    conn: sqlite3.Connection,
    cur_pos: dict | None,
    max_dist: float = 5000,
    he_threshold: float = 28.5,
    min_ggs: int = 3,
) -> pd.DataFrame:
    """
    Boxels near the commander whose gas giants indicate a helium-rich region.

    A boxel is the system-name prefix after stripping the trailing index number,
    e.g. "Prooe Drye ZQ-K d9" for all "Prooe Drye ZQ-K d9-N" systems.

    He% comes from AtmosphereComposition in Scan events (atmosphere_he_pct).
    Falls back to HRGG subtype classification when He% data is not yet
    available (requires a reimport after the code change that added He% capture).

    Returns up to 10 nearest qualifying boxels sorted by distance.
    """
    if cur_pos is None:
        return pd.DataFrame()
    sql = """
        SELECT s.name AS system_name, s.x, s.y, s.z,
               b.atmosphere_he_pct,
               b.subtype
        FROM bodies b
        JOIN systems s ON s.system_address = b.system_address
        WHERE LOWER(b.subtype) LIKE '%gas giant%'
          AND s.x IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        return pd.DataFrame()

    # Use actual He% if available; fall back to 35.0 proxy for HRGG bodies
    # (HRGG classification implies He% is above the threshold)
    df["he_pct"] = df["atmosphere_he_pct"].where(
        df["atmosphere_he_pct"].notna(),
        other=df["subtype"].apply(
            lambda s: 35.0 if (s or "").lower() == "helium rich gas giant" else float("nan")
        ),
    )

    df = df[df["he_pct"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df["boxel"] = df["system_name"].apply(lambda n: _BOXEL_RE.sub("", n))
    cx, cy, cz = cur_pos["x"], cur_pos["y"], cur_pos["z"]
    df["dist"] = (
        (df["x"] - cx) ** 2 +
        (df["y"] - cy) ** 2 +
        (df["z"] - cz) ** 2
    ).pow(0.5)

    nearest = (
        df.loc[df.groupby("boxel")["dist"].idxmin(), ["boxel", "system_name"]]
        .set_index("boxel")["system_name"]
    )
    grp = (
        df.groupby("boxel")
        .agg(
            gg_count=("he_pct", "count"),
            he_min=("he_pct", "min"),
            he_max=("he_pct", "max"),
            he_mean=("he_pct", "mean"),
            dist=("dist", "min"),
        )
        .reset_index()
    )
    grp["nearest_system"] = grp["boxel"].map(nearest)
    return (
        grp[
            (grp["gg_count"] >= min_ggs) &
            (grp["he_mean"] > he_threshold) &
            (grp["dist"] <= max_dist)
        ]
        .sort_values("dist")
        .head(10)
        .reset_index(drop=True)
    )


def nearby_tectonicas_boxels(
    conn: sqlite3.Connection,
    cur_pos: dict | None,
    max_dist: float = 5000,
    min_ggs: int = 3,
) -> pd.DataFrame:
    """
    Boxels within max_dist ly whose mean He% falls in a known Stratum Tectonicas
    sweet spot (He% ranges where community data shows >5% Tectonicas probability).

    Returns columns: boxel, he_mean, gg_count, dist.
    """
    if cur_pos is None:
        return pd.DataFrame()
    sql = """
        SELECT s.name AS system_name, s.x, s.y, s.z,
               b.atmosphere_he_pct, b.subtype
        FROM bodies b
        JOIN systems s ON s.system_address = b.system_address
        WHERE LOWER(b.subtype) LIKE '%gas giant%'
          AND s.x IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        return pd.DataFrame()

    df["he_pct"] = df["atmosphere_he_pct"].where(
        df["atmosphere_he_pct"].notna(),
        other=df["subtype"].apply(
            lambda s: 35.0 if (s or "").lower() == "helium rich gas giant" else float("nan")
        ),
    )
    df = df[df["he_pct"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df["boxel"] = df["system_name"].apply(lambda n: _BOXEL_RE.sub("", n))
    cx, cy, cz = cur_pos["x"], cur_pos["y"], cur_pos["z"]
    df["dist"] = (
        (df["x"] - cx) ** 2 + (df["y"] - cy) ** 2 + (df["z"] - cz) ** 2
    ).pow(0.5)

    nearest = (
        df.loc[df.groupby("boxel")["dist"].idxmin(), ["boxel", "system_name"]]
        .set_index("boxel")["system_name"]
    )
    grp = (
        df.groupby("boxel")
        .agg(
            gg_count=("he_pct", "count"),
            he_mean=("he_pct", "mean"),
            dist=("dist", "min"),
        )
        .reset_index()
    )
    grp["nearest_system"] = grp["boxel"].map(nearest)

    in_range = grp["he_mean"].apply(
        lambda he: any(lo <= he <= hi for lo, hi in _TECTONICAS_HE_RANGES)
    )
    return (
        grp[in_range & (grp["gg_count"] >= min_ggs) & (grp["dist"] <= max_dist)]
        .sort_values("dist")
        .head(10)
        .reset_index(drop=True)
    )


def nearby_high_value_boxels(
    conn: sqlite3.Connection,
    cur_pos: dict | None,
    max_dist: float = 5000,
    min_ggs: int = 3,
) -> pd.DataFrame:
    """
    Boxels within max_dist ly whose mean He% falls in a range associated with
    average system exploration value > 3.5 MCr (per _HIGH_VALUE_HE_RANGES).

    Returns columns: boxel, he_mean, gg_count, dist.
    """
    if cur_pos is None:
        return pd.DataFrame()
    sql = """
        SELECT s.name AS system_name, s.x, s.y, s.z,
               b.atmosphere_he_pct, b.subtype
        FROM bodies b
        JOIN systems s ON s.system_address = b.system_address
        WHERE LOWER(b.subtype) LIKE '%gas giant%'
          AND s.x IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        return pd.DataFrame()

    df["he_pct"] = df["atmosphere_he_pct"].where(
        df["atmosphere_he_pct"].notna(),
        other=df["subtype"].apply(
            lambda s: 35.0 if (s or "").lower() == "helium rich gas giant" else float("nan")
        ),
    )
    df = df[df["he_pct"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df["boxel"] = df["system_name"].apply(lambda n: _BOXEL_RE.sub("", n))
    cx, cy, cz = cur_pos["x"], cur_pos["y"], cur_pos["z"]
    df["dist"] = (
        (df["x"] - cx) ** 2 + (df["y"] - cy) ** 2 + (df["z"] - cz) ** 2
    ).pow(0.5)

    nearest = (
        df.loc[df.groupby("boxel")["dist"].idxmin(), ["boxel", "system_name"]]
        .set_index("boxel")["system_name"]
    )
    grp = (
        df.groupby("boxel")
        .agg(
            gg_count=("he_pct", "count"),
            he_mean=("he_pct", "mean"),
            dist=("dist", "min"),
        )
        .reset_index()
    )
    grp["nearest_system"] = grp["boxel"].map(nearest)

    in_range = grp["he_mean"].apply(
        lambda he: any(lo <= he <= hi for lo, hi in _HIGH_VALUE_HE_RANGES)
    )
    return (
        grp[in_range & (grp["gg_count"] >= min_ggs) & (grp["dist"] <= max_dist)]
        .sort_values("dist")
        .head(10)
        .reset_index(drop=True)
    )


def boxel_he_vs_tectonicas(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    One row per boxel that has at least one gas giant with known He%.
    Columns: boxel, he_mean, gg_count, has_tectonicas.

    Used to chart He% distribution of Tectonicas-containing boxels vs. all boxels,
    and to identify promising Tectonicas boxels for vicinity hints.
    """
    gg_sql = """
        SELECT s.name AS system_name, b.atmosphere_he_pct
        FROM bodies b
        JOIN systems s ON s.system_address = b.system_address
        WHERE LOWER(b.subtype) LIKE '%gas giant%'
          AND b.atmosphere_he_pct IS NOT NULL
    """
    df_gg = pd.read_sql_query(gg_sql, conn)
    if df_gg.empty:
        return pd.DataFrame(columns=["boxel", "he_mean", "gg_count", "has_tectonicas"])

    tec_sql = """
        SELECT DISTINCT s.name AS system_name
        FROM organic_scans sc
        JOIN systems s ON s.system_address = sc.system_address
        WHERE sc.scan_state = 'Analyse'
          AND (LOWER(sc.species_localised) LIKE '%tectonicas%'
               OR LOWER(sc.species) LIKE '%tectonicas%')
    """
    df_tec = pd.read_sql_query(tec_sql, conn)

    df_gg["boxel"] = df_gg["system_name"].apply(lambda n: _BOXEL_RE.sub("", n))

    tec_boxels: set[str] = set()
    if not df_tec.empty:
        df_tec["boxel"] = df_tec["system_name"].apply(lambda n: _BOXEL_RE.sub("", n))
        tec_boxels = set(df_tec["boxel"])

    grp = (
        df_gg.groupby("boxel")
        .agg(he_mean=("atmosphere_he_pct", "mean"), gg_count=("atmosphere_he_pct", "count"))
        .reset_index()
    )
    grp["has_tectonicas"] = grp["boxel"].isin(tec_boxels)
    return grp


def systems_for_map(conn: sqlite3.Connection) -> pd.DataFrame:
    """All systems with coords — used for galaxy maps."""
    sql = """
        SELECT s.system_address, s.name, s.x, s.y, s.z, s.star_class,
               COUNT(DISTINCT b.body_id) AS bodies_scanned,
               COALESCE(SUM(b.bio_signals), 0) AS total_bio_signals,
               MAX(b.first_discovered) AS any_first_discovery
        FROM systems s
        LEFT JOIN bodies b ON b.system_address = s.system_address
        WHERE s.x IS NOT NULL
        GROUP BY s.system_address
    """
    return pd.read_sql_query(sql, conn)


def current_location(conn: sqlite3.Connection) -> dict | None:
    """Most recently visited system (from the jumps table), with coordinates."""
    sql = """
        SELECT s.name, s.x, s.y, s.z
        FROM jumps j
        JOIN systems s ON s.system_address = j.system_address
        WHERE s.x IS NOT NULL
        ORDER BY j.timestamp DESC
        LIMIT 1
    """
    row = conn.execute(sql).fetchone()
    if row is None:
        return None
    return {"name": row[0], "x": row[1], "y": row[2], "z": row[3]}


# ---------------------------------------------------------------------------
# Trip statistics — all queries accept ISO-8601 date-range strings
# ---------------------------------------------------------------------------

def _ts_bounds(date_from: str, date_to: str) -> tuple[str, str]:
    """Normalise date or datetime strings to full ISO-8601 timestamps.

    Accepts:  YYYY-MM-DD
              YYYY-MM-DD HH:MM
              YYYY-MM-DD HH:MM:SS
              YYYY-MM-DDTHH:MM:SSZ  (passed through unchanged)
    """
    def _norm(s: str, end_of_day: bool) -> str:
        s = s.strip().replace(" ", "T")
        if "T" not in s:
            return s + ("T23:59:59Z" if end_of_day else "T00:00:00Z")
        date_part, time_part = s.split("T", 1)
        time_part = time_part.rstrip("Z")
        parts = time_part.split(":")
        if len(parts) == 1:
            time_part = parts[0].zfill(2) + ":00:00"
        elif len(parts) == 2:
            time_part = parts[0].zfill(2) + ":" + parts[1].zfill(2) + ":00"
        else:
            time_part = ":".join(p.zfill(2) for p in parts[:3])
        return date_part + "T" + time_part + "Z"

    return _norm(date_from, False), _norm(date_to, True)


def trip_summary(conn: sqlite3.Connection,
                 date_from: str, date_to: str) -> dict:
    """High-level counts for a specific date range."""
    lo, hi = _ts_bounds(date_from, date_to)

    def scalar(sql):
        row = conn.execute(sql, (lo, hi)).fetchone()
        return row[0] if row else 0

    return {
        "date_from":          lo,
        "date_to":            hi,
        "systems_visited":    scalar("""
            SELECT COUNT(DISTINCT system_address) FROM jumps
            WHERE timestamp >= ? AND timestamp <= ?"""),
        "jumps":              scalar("""
            SELECT COUNT(*) FROM jumps
            WHERE timestamp >= ? AND timestamp <= ?"""),
        "ly_travelled":       scalar("""
            SELECT COALESCE(SUM(jump_dist),0) FROM jumps
            WHERE timestamp >= ? AND timestamp <= ?"""),
        "bodies_scanned":     scalar("""
            SELECT COUNT(*) FROM bodies
            WHERE scanned_at >= ? AND scanned_at <= ?"""),
        "bodies_mapped":      scalar("""
            SELECT COUNT(*) FROM bodies
            WHERE was_mapped=1 AND scanned_at >= ? AND scanned_at <= ?"""),
        "planets_landable":   scalar("""
            SELECT COUNT(*) FROM bodies
            WHERE is_landable=1 AND scanned_at >= ? AND scanned_at <= ?"""),
        "first_discoveries":  scalar("""
            SELECT COUNT(*) FROM bodies
            WHERE first_discovered=1 AND scanned_at >= ? AND scanned_at <= ?"""),
        "first_mapped":       scalar("""
            SELECT COUNT(*) FROM bodies
            WHERE was_mapped=1 AND first_mapped=1 AND scanned_at >= ? AND scanned_at <= ?"""),
        "bio_signals_bodies": scalar("""
            SELECT COUNT(*) FROM bodies
            WHERE bio_signals>0 AND scanned_at >= ? AND scanned_at <= ?"""),
        "organic_scans_done": scalar("""
            SELECT COUNT(*) FROM organic_scans
            WHERE scan_state='Analyse' AND timestamp >= ? AND timestamp <= ?"""),
        "species_unique":     scalar("""
            SELECT COUNT(DISTINCT species) FROM organic_scans
            WHERE scan_state='Analyse' AND timestamp >= ? AND timestamp <= ?"""),
        "organic_credits":    scalar("""
            SELECT COALESCE(SUM(total),0) FROM organic_sales
            WHERE timestamp >= ? AND timestamp <= ?"""),
        "exploration_credits":scalar("""
            SELECT COALESCE(SUM(total_earnings),0) FROM exploration_sales
            WHERE timestamp >= ? AND timestamp <= ?"""),
    }


def trip_personal_records(conn: sqlite3.Connection,
                           date_from: str, date_to: str) -> pd.DataFrame:
    """Personal bests within the date range (bodies scanned during the trip)."""
    lo, hi = _ts_bounds(date_from, date_to)
    queries = [
        ("Highest gravity",  "g",
         "SELECT name, system_address, surface_gravity_g AS value FROM bodies WHERE surface_gravity_g IS NOT NULL AND scanned_at>=? AND scanned_at<=? ORDER BY surface_gravity_g DESC LIMIT 1"),
        ("Lowest gravity",   "g",
         "SELECT name, system_address, surface_gravity_g AS value FROM bodies WHERE surface_gravity_g>0 AND scanned_at>=? AND scanned_at<=? ORDER BY surface_gravity_g ASC LIMIT 1"),
        ("Hottest surface",  "K",
         "SELECT name, system_address, surface_temp_k AS value FROM bodies WHERE surface_temp_k IS NOT NULL AND scanned_at>=? AND scanned_at<=? ORDER BY surface_temp_k DESC LIMIT 1"),
        ("Coldest surface",  "K",
         "SELECT name, system_address, surface_temp_k AS value FROM bodies WHERE surface_temp_k>0 AND scanned_at>=? AND scanned_at<=? ORDER BY surface_temp_k ASC LIMIT 1"),
        ("Largest radius",   "km",
         "SELECT name, system_address, radius_km AS value FROM bodies WHERE radius_km IS NOT NULL AND scanned_at>=? AND scanned_at<=? ORDER BY radius_km DESC LIMIT 1"),
        ("Most bio signals", "",
         "SELECT name, system_address, bio_signals AS value FROM bodies WHERE scanned_at>=? AND scanned_at<=? ORDER BY bio_signals DESC LIMIT 1"),
        ("Longest jump",     "ly",
         "SELECT s.name, j.system_address, j.jump_dist AS value FROM jumps j JOIN systems s ON s.system_address=j.system_address WHERE j.timestamp>=? AND j.timestamp<=? ORDER BY j.jump_dist DESC LIMIT 1"),
    ]
    rows = []
    for label, unit, sql in queries:
        row = conn.execute(sql, (lo, hi)).fetchone()
        if row and row["value"]:
            rows.append({
                "Record":        label,
                "Body / System": row["name"],
                "Value":         round(float(row["value"]), 3),
                "Unit":          unit,
            })
    return pd.DataFrame(rows)


def trip_body_breakdown(conn: sqlite3.Connection,
                        date_from: str, date_to: str) -> pd.DataFrame:
    """Planet-type counts for bodies scanned during the trip."""
    lo, hi = _ts_bounds(date_from, date_to)
    sql = """
        SELECT subtype                                                     AS planet_type,
               COUNT(*)                                                    AS count,
               SUM(first_discovered)                                       AS first_disc,
               SUM(was_mapped)                                             AS mapped,
               SUM(CASE WHEN was_mapped=1 THEN first_mapped ELSE 0 END)   AS first_mapped
        FROM bodies
        WHERE body_type  = 'Planet'
          AND subtype    IS NOT NULL
          AND scanned_at >= ? AND scanned_at <= ?
        GROUP BY subtype
        ORDER BY count DESC
    """
    return pd.read_sql_query(sql, conn, params=(lo, hi))


def trip_species_breakdown(conn: sqlite3.Connection,
                           date_from: str, date_to: str) -> pd.DataFrame:
    """Organic species scanned (completed) during the trip."""
    lo, hi = _ts_bounds(date_from, date_to)
    sql = """
        SELECT species_localised AS species,
               genus_localised   AS genus,
               COUNT(*)          AS scans
        FROM organic_scans
        WHERE scan_state = 'Analyse'
          AND timestamp >= ? AND timestamp <= ?
        GROUP BY species
        ORDER BY scans DESC
    """
    return pd.read_sql_query(sql, conn, params=(lo, hi))


def trip_estimated_values(conn: sqlite3.Connection,
                          date_from: str, date_to: str) -> dict:
    """
    Estimated credit value of unsold data for the given period.

    Returns a dict with:
      exploration_estimate   — sum of body_scan_value() for all planets scanned
      organic_species        — DataFrame (species, qty, base_per, base_total)
      organic_base           — total base exobiology value (qty × base_value)
      organic_first_log      — base × 5  (upper bound: all samples are first-log)
      organic_antal          — first_log × 1.3  (with Pranav Antal pledge bonus)
    """
    from .valuation import body_scan_value, SPECIES_VALUES, ANTAL_EXOBIO_BONUS

    lo, hi = _ts_bounds(date_from, date_to)

    # --- Exploration data ---
    body_sql = """
        SELECT subtype AS planet_class, mass_em, terraform_state,
               first_discovered, was_mapped, first_mapped
        FROM bodies
        WHERE body_type = 'Planet'
          AND subtype IS NOT NULL
          AND mass_em IS NOT NULL
          AND scanned_at >= ? AND scanned_at <= ?
    """
    df_b = pd.read_sql_query(body_sql, conn, params=(lo, hi))
    if df_b.empty:
        expl = 0
    else:
        expl = int(df_b.apply(
            lambda r: body_scan_value(
                planet_class=r["planet_class"],
                mass_em=r["mass_em"],
                terraform_state=r["terraform_state"],
                first_discovered=bool(r["first_discovered"]),
                was_mapped=bool(r["was_mapped"]),
                first_mapped=bool(r["first_mapped"]),
            ),
            axis=1,
        ).sum())

    # --- Exobiology ---
    org_sql = """
        SELECT species_localised, COUNT(*) AS qty
        FROM organic_scans
        WHERE scan_state = 'Analyse'
          AND timestamp >= ? AND timestamp <= ?
          AND species_localised IS NOT NULL AND species_localised != ''
        GROUP BY species_localised
        ORDER BY qty DESC
    """
    df_o = pd.read_sql_query(org_sql, conn, params=(lo, hi))

    rows = []
    total_base = total_fl = total_antal = 0
    for _, r in df_o.iterrows():
        sp   = r["species_localised"]
        qty  = int(r["qty"])
        base = SPECIES_VALUES.get(sp, 0)
        bt   = base * qty
        fl   = base * 5 * qty
        an   = round(fl * (1 + ANTAL_EXOBIO_BONUS))
        total_base  += bt
        total_fl    += fl
        total_antal += an
        rows.append({"species": sp, "qty": qty, "base_per": base, "base_total": bt})

    return {
        "exploration_estimate": expl,
        "organic_species":      pd.DataFrame(rows),
        "organic_base":         total_base,
        "organic_first_log":    total_fl,
        "organic_antal":        total_antal,
    }


def trip_body_breakdown_grouped(conn: sqlite3.Connection,
                                date_from: str, date_to: str) -> pd.DataFrame:
    """
    Planet-type counts grouped for expedition reports.

    Named rocky/icy types get their own rows; terraformable variants are
    prefixed 'Terraformable'.  Gas giants and anything unrecognised are
    bucketed as 'Other'.

    Sort order: priority list first, then remaining named types by count
    descending, 'Other' last.

    Columns: planet_group, count, first_disc, mapped, first_mapped
    """
    lo, hi = _ts_bounds(date_from, date_to)
    sql = """
        SELECT subtype, terraform_state,
               COUNT(*) AS count,
               SUM(first_discovered) AS first_disc,
               SUM(was_mapped) AS mapped,
               SUM(CASE WHEN was_mapped=1 THEN first_mapped ELSE 0 END) AS first_mapped
        FROM bodies
        WHERE body_type  = 'Planet'
          AND subtype    IS NOT NULL
          AND scanned_at >= ? AND scanned_at <= ?
        GROUP BY subtype, terraform_state
    """
    df = pd.read_sql_query(sql, conn, params=(lo, hi))

    # Gas giants intentionally excluded — they fall through to "Other".
    _NAMED = {
        "earthlike body", "water world", "ammonia world",
        "high metal content body", "metal rich body",
        "rocky body", "rocky ice body", "icy body",
    }
    _NO_TERRA_PREFIX = {"earthlike body"}
    _PRIORITY = [
        "Earthlike body",
        "Terraformable Water world",
        "Ammonia world",
        "Terraformable High metal content body",
        "Terraformable Rocky body",
        "Water world",
    ]
    _prio_index = {k: i for i, k in enumerate(_PRIORITY)}

    # Accumulate [count, first_disc, mapped, first_mapped] per display key
    groups: dict[str, list[int]] = {}
    for _, r in df.iterrows():
        sub  = (r["subtype"] or "").strip()
        ts   = (r["terraform_state"] or "").strip().lower()
        is_t = ts not in ("", "not terraformable")
        low  = sub.lower()

        if low in _NAMED:
            key = f"Terraformable {sub}" if (is_t and low not in _NO_TERRA_PREFIX) else sub
        else:
            key = "Other"

        if key not in groups:
            groups[key] = [0, 0, 0, 0]
        g = groups[key]
        g[0] += int(r["count"])
        g[1] += int(r["first_disc"])
        g[2] += int(r["mapped"])
        g[3] += int(r["first_mapped"])

    named_rows = [(k, *v) for k, v in groups.items() if k != "Other"]

    def _sort_key(row):
        k = row[0]
        if k in _prio_index:
            return (_prio_index[k], 0)
        return (len(_PRIORITY), -row[1])  # rest: by count desc

    named_rows.sort(key=_sort_key)
    if "Other" in groups:
        named_rows.append(("Other", *groups["Other"]))

    return pd.DataFrame(named_rows,
                        columns=["planet_group", "count", "first_disc",
                                 "mapped", "first_mapped"])


def trip_systems_visited(conn: sqlite3.Connection,
                         date_from: str, date_to: str) -> pd.DataFrame:
    """All systems jumped to during the trip, in chronological order."""
    lo, hi = _ts_bounds(date_from, date_to)
    sql = """
        SELECT s.name, s.star_class, j.timestamp, j.jump_dist,
               COUNT(DISTINCT b.body_id)                    AS bodies_scanned,
               COALESCE(SUM(b.first_discovered),0)          AS first_disc,
               COALESCE(SUM(CASE WHEN b.bio_signals>0 THEN 1 ELSE 0 END),0) AS bio_bodies
        FROM jumps j
        JOIN systems s ON s.system_address = j.system_address
        LEFT JOIN bodies b ON b.system_address = j.system_address
                           AND b.scanned_at >= ? AND b.scanned_at <= ?
        WHERE j.timestamp >= ? AND j.timestamp <= ?
        GROUP BY j.id
        ORDER BY j.timestamp
    """
    return pd.read_sql_query(sql, conn, params=(lo, hi, lo, hi))
