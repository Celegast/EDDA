"""
Handlers for individual Elite Dangerous journal event types.

Each handler receives the raw parsed event dict and an open sqlite3.Connection.
Return value is ignored; handlers commit nothing — the reader batches commits.
"""

import sqlite3
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Region bitmap constants — same coordinate system as analysis/maps.py
_REG_X0    = -49985.0
_REG_Z0    = -24105.0
_REG_PX_SZ = 4096.0 / 83

_region_rle_cache:   list | None = None
_region_names_cache: list | None = None


def _region_for_coords(x: float, z: float) -> str | None:
    global _region_rle_cache, _region_names_cache
    if _region_rle_cache is None:
        from ..analysis._region_map_data import regionmap, regions
        _region_rle_cache   = regionmap
        _region_names_cache = regions
    px = int((x - _REG_X0) / _REG_PX_SZ)
    pz = int((z - _REG_Z0) / _REG_PX_SZ)
    if not (0 <= px < 2048 and 0 <= pz < 2048):
        return None
    col = 0
    for length, rid in _region_rle_cache[pz]:
        col += length
        if col > px:
            names = _region_names_cache
            return names[rid] if rid and rid < len(names) else None
    return None


def backfill_regions(conn: sqlite3.Connection, verbose: bool = True) -> int:
    """Fill systems.region for rows where coordinates are known but region is NULL."""
    rows = conn.execute(
        "SELECT system_address, x, z FROM systems"
        " WHERE region IS NULL AND x IS NOT NULL AND z IS NOT NULL"
    ).fetchall()
    if not rows:
        return 0
    if verbose:
        print(f"Backfilling region for {len(rows):,} systems...")
    updated = 0
    conn.execute("BEGIN")
    for row in rows:
        region = _region_for_coords(row["x"], row["z"])
        if region:
            conn.execute(
                "UPDATE systems SET region = ? WHERE system_address = ?",
                (region, row["system_address"]),
            )
            updated += 1
    conn.execute("COMMIT")
    if verbose:
        print(f"  {updated:,} systems assigned a region.")
    return updated


# The game journal writes a species-variant name into genus_localised for these genera.
GENUS_LOCALISED_CORRECTIONS: dict[str, str] = {
    "$Codex_Ent_Sphere_Name;": "Anemone",
    "$Codex_Ent_Tube_Name;":   "Sinuous Tubers",
    "$Codex_Ent_Cone_Name;":   "Bark Mounds",
}


def _atmosphere_density(atmosphere_type: str) -> str:
    """Extract a normalised density label from a raw atmosphere type string."""
    lower = (atmosphere_type or "").lower()
    if "thin" in lower:
        return "thin"
    if "thick" in lower:
        return "thick"
    if "no atmosphere" in lower or lower == "none" or lower == "":
        return "none"
    return "standard"


# ---------------------------------------------------------------------------
# System / navigation events
# ---------------------------------------------------------------------------

def handle_fsd_jump(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    if not sa:
        return
    star_pos = event.get("StarPos", [None, None, None])
    x, y, z = star_pos[0], star_pos[1], star_pos[2]
    region = _region_for_coords(x, z) if x is not None and z is not None else None
    conn.execute("""
        INSERT INTO systems (system_address, name, x, y, z, star_class, region, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address) DO UPDATE SET
            name       = excluded.name,
            x          = excluded.x,
            y          = excluded.y,
            z          = excluded.z,
            star_class = COALESCE(excluded.star_class, systems.star_class),
            region     = COALESCE(excluded.region, systems.region)
    """, (
        sa,
        event.get("StarSystem", ""),
        x, y, z,
        None,  # star_class populated later from Scan events
        region,
        event.get("timestamp"),
    ))
    conn.execute("""
        INSERT INTO jumps (system_address, timestamp, jump_dist, fuel_used, fuel_remaining)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(system_address, timestamp) DO NOTHING
    """, (
        sa,
        event.get("timestamp"),
        event.get("JumpDist"),
        event.get("FuelUsed"),
        event.get("FuelLevel"),
    ))


def handle_location(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    if not sa:
        return
    star_pos = event.get("StarPos", [None, None, None])
    x, y, z = star_pos[0], star_pos[1], star_pos[2]
    region = _region_for_coords(x, z) if x is not None and z is not None else None
    conn.execute("""
        INSERT INTO systems (system_address, name, x, y, z, star_class, region, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address) DO NOTHING
    """, (
        sa,
        event.get("StarSystem", ""),
        x, y, z,
        event.get("StarClass"),
        region,
        event.get("timestamp"),
    ))


# ---------------------------------------------------------------------------
# Body scan events
# ---------------------------------------------------------------------------

def _ensure_system(sa: int, event: dict, conn: sqlite3.Connection) -> None:
    """Insert a minimal system row if it doesn't exist yet."""
    conn.execute("""
        INSERT OR IGNORE INTO systems (system_address, name, first_seen_at)
        VALUES (?, ?, ?)
    """, (sa, event.get("StarSystem", event.get("BodyName", "")), event.get("timestamp")))


def handle_scan(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    body_id = event.get("BodyID")
    if sa is None or body_id is None:
        return
    _ensure_system(sa, event, conn)

    scan_type = event.get("ScanType", "")
    body_name = event.get("BodyName", "")

    # Distinguish stars from planets/moons
    if "StarType" in event:
        body_type = "Star"
        subtype = event.get("StarType")
    elif "PlanetClass" in event:
        body_type = "Planet"
        subtype = event.get("PlanetClass")
    else:
        body_type = "Other"
        subtype = None

    atmo_type = event.get("AtmosphereType", "")

    he_pct = None
    for comp in event.get("AtmosphereComposition", []):
        if (comp.get("Name") or "").lower() == "helium":
            he_pct = comp.get("Percent")
            break

    # Update system's primary star class from the arrival-star scan.
    # Always overwrite — the Scan StarType is more specific than the StarClass
    # field in FSDJump/Location (e.g. Location may report 'O' for a WO star).
    if body_type == "Star" and subtype and event.get("DistanceFromArrivalLS", 999) < 1:
        conn.execute("""
            UPDATE systems SET star_class = ?
            WHERE system_address = ?
        """, (subtype, sa))

    comp = event.get("Composition") or {}
    parent_star_id = None
    for parent in event.get("Parents", []):
        if "Star" in parent:
            parent_star_id = parent["Star"]
            break

    orbital_parent_id = None
    parents = event.get("Parents") or []
    if parents:
        for key, val in parents[0].items():
            if key != "Null":
                orbital_parent_id = val
                break

    row: dict[str, Any] = {
        "system_address":     sa,
        "body_id":            body_id,
        "name":               body_name,
        "body_type":          body_type,
        "subtype":            subtype,
        "subclass":           event.get("Subclass") if body_type == "Star" else None,
        "distance_ls":        event.get("DistanceFromArrivalLS"),
        "radius_km":          event.get("Radius", 0) / 1000.0 if event.get("Radius") else None,
        "mass_em":            event.get("StellarMass") if body_type == "Star" else event.get("MassEM"),
        "age_my":             event.get("Age_MY") if body_type == "Star" else None,
        "surface_gravity_g":  event.get("SurfaceGravity", 0) / 9.80665 if event.get("SurfaceGravity") else None,
        "surface_temp_k":     event.get("SurfaceTemperature"),
        "surface_pressure":   event.get("SurfacePressure"),
        "atmosphere_type":    atmo_type,
        "atmosphere_density": _atmosphere_density(atmo_type),
        "atmosphere_he_pct":  he_pct,
        "volcanism":          event.get("Volcanism"),
        "is_landable":        int(bool(event.get("Landable"))),
        "terraform_state":    event.get("TerraformState"),
        "bio_signals":        0,
        "geo_signals":        0,
        "was_mapped":         0,
        "first_discovered":   int(not event.get("WasDiscovered", True)),
        "first_mapped":       int(not event.get("WasMapped", True)),
        "scanned_at":         event.get("timestamp"),
        "luminosity":         event.get("Luminosity") if body_type == "Star" else None,
        "absolute_magnitude": event.get("AbsoluteMagnitude") if body_type == "Star" else None,
        "orbital_period":     event.get("OrbitalPeriod"),
        "semi_major_axis":    event.get("SemiMajorAxis"),
        "eccentricity":       event.get("Eccentricity"),
        "orbital_inclination":event.get("OrbitalInclination"),
        "periapsis":          event.get("Periapsis"),
        "ascending_node":     event.get("AscendingNode"),
        "mean_anomaly":       event.get("MeanAnomaly"),
        "rotation_period":    event.get("RotationPeriod"),
        "axial_tilt":         event.get("AxialTilt"),
        "composition_ice":    comp.get("Ice"),
        "composition_rock":   comp.get("Rock"),
        "composition_metal":  comp.get("Metal"),
        "reserve_level":      event.get("ReserveLevel"),
        "parent_star_id":     parent_star_id,
        "orbital_parent_id":  orbital_parent_id,
    }

    conn.execute("""
        INSERT INTO bodies (
            system_address, body_id, name, body_type, subtype, subclass,
            distance_ls, radius_km, mass_em, age_my, surface_gravity_g,
            surface_temp_k, surface_pressure, atmosphere_type,
            atmosphere_density, atmosphere_he_pct, volcanism, is_landable,
            terraform_state, bio_signals, geo_signals,
            was_mapped, first_discovered, first_mapped, scanned_at,
            luminosity, absolute_magnitude,
            orbital_period, semi_major_axis, eccentricity,
            orbital_inclination, periapsis, ascending_node, mean_anomaly,
            rotation_period, axial_tilt,
            composition_ice, composition_rock, composition_metal,
            reserve_level, parent_star_id, orbital_parent_id
        ) VALUES (
            :system_address, :body_id, :name, :body_type, :subtype, :subclass,
            :distance_ls, :radius_km, :mass_em, :age_my, :surface_gravity_g,
            :surface_temp_k, :surface_pressure, :atmosphere_type,
            :atmosphere_density, :atmosphere_he_pct, :volcanism, :is_landable,
            :terraform_state, :bio_signals, :geo_signals,
            :was_mapped, :first_discovered, :first_mapped, :scanned_at,
            :luminosity, :absolute_magnitude,
            :orbital_period, :semi_major_axis, :eccentricity,
            :orbital_inclination, :periapsis, :ascending_node, :mean_anomaly,
            :rotation_period, :axial_tilt,
            :composition_ice, :composition_rock, :composition_metal,
            :reserve_level, :parent_star_id, :orbital_parent_id
        )
        ON CONFLICT(system_address, body_id) DO UPDATE SET
            subtype             = COALESCE(excluded.subtype,             bodies.subtype),
            subclass            = COALESCE(excluded.subclass,            bodies.subclass),
            distance_ls         = COALESCE(excluded.distance_ls,         bodies.distance_ls),
            radius_km           = COALESCE(excluded.radius_km,           bodies.radius_km),
            mass_em             = COALESCE(excluded.mass_em,             bodies.mass_em),
            age_my              = COALESCE(excluded.age_my,              bodies.age_my),
            surface_gravity_g   = COALESCE(excluded.surface_gravity_g,   bodies.surface_gravity_g),
            surface_temp_k      = COALESCE(excluded.surface_temp_k,      bodies.surface_temp_k),
            surface_pressure    = COALESCE(excluded.surface_pressure,    bodies.surface_pressure),
            atmosphere_type     = COALESCE(excluded.atmosphere_type,     bodies.atmosphere_type),
            atmosphere_density  = COALESCE(excluded.atmosphere_density,  bodies.atmosphere_density),
            atmosphere_he_pct   = COALESCE(excluded.atmosphere_he_pct,   bodies.atmosphere_he_pct),
            volcanism           = COALESCE(excluded.volcanism,           bodies.volcanism),
            is_landable         = COALESCE(excluded.is_landable,         bodies.is_landable),
            terraform_state     = COALESCE(excluded.terraform_state,     bodies.terraform_state),
            first_discovered    = MAX(excluded.first_discovered,         bodies.first_discovered),
            first_mapped        = MAX(excluded.first_mapped,             bodies.first_mapped),
            scanned_at          = COALESCE(bodies.scanned_at,            excluded.scanned_at),
            luminosity          = COALESCE(excluded.luminosity,          bodies.luminosity),
            absolute_magnitude  = COALESCE(excluded.absolute_magnitude,  bodies.absolute_magnitude),
            orbital_period      = COALESCE(excluded.orbital_period,      bodies.orbital_period),
            semi_major_axis     = COALESCE(excluded.semi_major_axis,     bodies.semi_major_axis),
            eccentricity        = COALESCE(excluded.eccentricity,        bodies.eccentricity),
            orbital_inclination = COALESCE(excluded.orbital_inclination, bodies.orbital_inclination),
            periapsis           = COALESCE(excluded.periapsis,           bodies.periapsis),
            ascending_node      = COALESCE(excluded.ascending_node,      bodies.ascending_node),
            mean_anomaly        = COALESCE(excluded.mean_anomaly,        bodies.mean_anomaly),
            rotation_period     = COALESCE(excluded.rotation_period,     bodies.rotation_period),
            axial_tilt          = COALESCE(excluded.axial_tilt,          bodies.axial_tilt),
            composition_ice     = COALESCE(excluded.composition_ice,     bodies.composition_ice),
            composition_rock    = COALESCE(excluded.composition_rock,    bodies.composition_rock),
            composition_metal   = COALESCE(excluded.composition_metal,   bodies.composition_metal),
            reserve_level       = COALESCE(excluded.reserve_level,       bodies.reserve_level),
            parent_star_id      = COALESCE(excluded.parent_star_id,      bodies.parent_star_id),
            orbital_parent_id   = COALESCE(excluded.orbital_parent_id,   bodies.orbital_parent_id)
    """, row)

    for mat in event.get("Materials", []):
        conn.execute("""
            INSERT INTO body_materials (system_address, body_id, name, percent)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(system_address, body_id, name) DO UPDATE SET
                percent = excluded.percent
        """, (sa, body_id, mat.get("Name"), mat.get("Percent")))

    for ring in event.get("Rings", []):
        conn.execute("""
            INSERT INTO rings (system_address, body_id, name, ring_class, mass_mt, inner_rad, outer_rad)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id, name) DO UPDATE SET
                ring_class = excluded.ring_class,
                mass_mt    = excluded.mass_mt,
                inner_rad  = excluded.inner_rad,
                outer_rad  = excluded.outer_rad
        """, (sa, body_id, ring.get("Name"), ring.get("RingClass"),
              ring.get("MassMT"), ring.get("InnerRad"), ring.get("OuterRad")))


def _record_body_signals(conn: sqlite3.Connection, sa: int, body_id: int,
                         body_name: str, bio_total: int, geo_total: int) -> None:
    """
    Upsert bio/geo signal counts onto a body.

    FSSBodySignals fires right after the discovery honk — before the body's Scan
    row exists — so a bare UPDATE matches nothing and the count is silently lost
    (only DSS-mapped bodies, whose SAASignalsFound arrives after Scan, kept one).
    Insert a stub row instead; handle_scan fills in the rest later and leaves
    bio_signals/geo_signals untouched.
    """
    if bio_total <= 0 and geo_total <= 0:
        return
    if body_name:
        conn.execute("""
            INSERT INTO bodies (system_address, body_id, name, body_type,
                                bio_signals, geo_signals)
            VALUES (?, ?, ?, 'Planet', ?, ?)
            ON CONFLICT(system_address, body_id) DO UPDATE SET
                bio_signals = MAX(bodies.bio_signals, excluded.bio_signals),
                geo_signals = MAX(bodies.geo_signals, excluded.geo_signals)
        """, (sa, body_id, body_name, bio_total, geo_total))
    else:
        conn.execute("""
            UPDATE bodies SET
                bio_signals = MAX(bio_signals, ?),
                geo_signals = MAX(geo_signals, ?)
            WHERE system_address = ? AND body_id = ?
        """, (bio_total, geo_total, sa, body_id))


def handle_saa_signals_found(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    body_id = event.get("BodyID")
    if sa is None or body_id is None:
        return
    _ensure_system(sa, event, conn)

    bio_total = 0
    geo_total = 0

    for sig in event.get("Signals", []):
        sig_type = sig.get("Type", "")
        count = sig.get("Count", 0)
        if "$SAA_SignalType_Biological;" in sig_type:
            bio_total += count
        elif "$SAA_SignalType_Geological;" in sig_type:
            geo_total += count

    for genus_entry in event.get("Genuses", []):
        genus = genus_entry.get("Genus", "")
        localised = genus_entry.get("Genus_Localised", genus)
        conn.execute("""
            INSERT INTO bio_signals (system_address, body_id, genus, genus_localised, count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(system_address, body_id, genus) DO NOTHING
        """, (sa, body_id, genus, localised))

    _record_body_signals(conn, sa, body_id, event.get("BodyName", ""),
                         bio_total, geo_total)


def handle_fss_body_signals(event: dict, conn: sqlite3.Connection) -> None:
    """FSSBodySignals — bio/geo signal counts from the FSS scanner."""
    sa = event.get("SystemAddress")
    body_id = event.get("BodyID")
    if sa is None or body_id is None:
        return
    _ensure_system(sa, event, conn)

    bio_total = 0
    geo_total = 0
    for sig in event.get("Signals", []):
        sig_type = sig.get("Type", "")
        count = sig.get("Count", 0)
        if "$SAA_SignalType_Biological;" in sig_type:
            bio_total += count
        elif "$SAA_SignalType_Geological;" in sig_type:
            geo_total += count

    _record_body_signals(conn, sa, body_id, event.get("BodyName", ""),
                         bio_total, geo_total)


def handle_saa_scan_complete(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    body_id = event.get("BodyID")
    if sa is None or body_id is None:
        return
    conn.execute("""
        UPDATE bodies SET was_mapped = 1
        WHERE system_address = ? AND body_id = ?
    """, (sa, body_id))
    # Mapping payout recorded separately via SAAScanComplete — not a direct sale event,
    # but we can track it if ProbeRadius/ProbesUsed are present (informational only).


# ---------------------------------------------------------------------------
# Biology scan events
# ---------------------------------------------------------------------------

def handle_scan_organic(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    body_id = event.get("Body")
    if sa is None or body_id is None:
        return
    _ensure_system(sa, event, conn)
    conn.execute("""
        INSERT OR IGNORE INTO organic_scans
            (system_address, body_id, timestamp, scan_state,
             genus, genus_localised, species, species_localised,
             variant, variant_localised)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sa, body_id,
        event.get("timestamp"),
        event.get("ScanType"),
        event.get("Genus"),
        GENUS_LOCALISED_CORRECTIONS.get(event.get("Genus", ""), event.get("Genus_Localised")),
        event.get("Species"),
        event.get("Species_Localised"),
        event.get("Variant"),
        event.get("Variant_Localised"),
    ))


def handle_sell_organic_data(event: dict, conn: sqlite3.Connection) -> None:
    ts = event.get("timestamp")
    for item in event.get("BioData", []):
        value = item.get("Value", 0)
        bonus = item.get("Bonus", 0)
        conn.execute("""
            INSERT INTO organic_sales
                (timestamp, species, species_localised, bonus, value, total)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ts,
            item.get("Species", ""),
            item.get("Species_Localised"),
            bonus, value, value + bonus,
        ))


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------

def handle_codex_entry(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    if sa is None:
        return
    _ensure_system(sa, event, conn)
    region = event.get("Region", "")
    entry_id = event.get("EntryID")
    if entry_id is None:
        return
    conn.execute("""
        INSERT INTO codex_entries
            (system_address, timestamp, entry_id, name, name_localised,
             sub_category, category, region, is_new_entry)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entry_id, region) DO NOTHING
    """, (
        sa,
        event.get("timestamp"),
        entry_id,
        event.get("Name"),
        event.get("Name_Localised"),
        event.get("SubCategory"),
        event.get("Category"),
        region,
        int(bool(event.get("IsNewEntry"))),
    ))


# ---------------------------------------------------------------------------
# FSS / Discovery events
# ---------------------------------------------------------------------------

def handle_discovery_scan(event: dict, conn: sqlite3.Connection) -> None:
    """DiscoveryScan — fired when the player honks, gives total body count."""
    sa = event.get("SystemAddress")
    if sa is None:
        return
    _ensure_system(sa, event, conn)
    bodies = event.get("Bodies")
    if bodies is not None:
        conn.execute("""
            UPDATE systems SET total_bodies = ?
            WHERE system_address = ? AND (total_bodies IS NULL OR total_bodies < ?)
        """, (bodies, sa, bodies))


def handle_fss_all_bodies_found(event: dict, conn: sqlite3.Connection) -> None:
    """FSSAllBodiesFound — fired when FSS scan is complete for a system."""
    sa = event.get("SystemAddress")
    if sa is None:
        return
    _ensure_system(sa, event, conn)
    bodies = event.get("Count")
    if bodies is not None:
        conn.execute("""
            UPDATE systems SET fss_complete = 1,
                total_bodies = COALESCE(total_bodies, ?)
            WHERE system_address = ?
        """, (bodies, sa))
    else:
        conn.execute(
            "UPDATE systems SET fss_complete = 1 WHERE system_address = ?", (sa,)
        )


# ---------------------------------------------------------------------------
# Statistics snapshot
# ---------------------------------------------------------------------------

def handle_statistics(event: dict, conn: sqlite3.Connection) -> None:
    """Statistics — periodic comprehensive stats dump."""
    expl = event.get("Exploration") or {}
    exobio = event.get("Exobiology") or {}
    conn.execute("""
        INSERT INTO statistics_snapshots (
            timestamp,
            systems_visited, exploration_profits,
            planets_scanned_to_level1, planets_scanned_to_level2,
            efficient_scans, highest_payout,
            total_hyperspace_dist, total_hyperspace_jumps,
            greatest_dist_from_start, time_played,
            organic_genus_encountered, organic_species_encountered,
            organic_species_analysed, exobiology_profits
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event.get("timestamp"),
        expl.get("Systems_Visited"),
        expl.get("Exploration_Profits"),
        expl.get("Planets_Scanned_To_Level_1"),
        expl.get("Planets_Scanned_To_Level_2"),
        expl.get("Efficient_Scans"),
        expl.get("Highest_Payout"),
        expl.get("Total_Hyperspace_Distance"),
        expl.get("Total_Hyperspace_Jumps"),
        expl.get("Greatest_Distance_From_Start"),
        event.get("TotalPlayTime"),
        exobio.get("Organic_Genus_Encountered"),
        exobio.get("Organic_Species_Encountered"),
        exobio.get("Organic_Species_Analysed"),
        exobio.get("Exobiology_Profits"),
    ))


# ---------------------------------------------------------------------------
# Rank promotion
# ---------------------------------------------------------------------------

def handle_promotion(event: dict, conn: sqlite3.Connection) -> None:
    """Promotion — fires when any rank is promoted."""
    conn.execute("""
        INSERT INTO commander_snapshots
            (timestamp, rank_combat, rank_trade, rank_explore,
             rank_exobiology, rank_empire, rank_federation)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        event.get("timestamp"),
        event.get("Combat"),
        event.get("Trade"),
        event.get("Explore"),
        event.get("Exobiologist"),
        event.get("Empire"),
        event.get("Federation"),
    ))


# ---------------------------------------------------------------------------
# Exploration sales
# ---------------------------------------------------------------------------

def handle_multi_sell_exploration_data(event: dict, conn: sqlite3.Connection) -> None:
    base = event.get("BaseValue", 0)
    bonus = event.get("Bonus", 0)
    conn.execute("""
        INSERT INTO exploration_sales (timestamp, base_value, bonus, total_earnings, event_type)
        VALUES (?, ?, ?, ?, 'MultiSellExplorationData')
    """, (event.get("timestamp"), base, bonus, base + bonus))


def handle_sell_exploration_data(event: dict, conn: sqlite3.Connection) -> None:
    base = event.get("BaseValue", 0)
    bonus = event.get("Bonus", 0)
    conn.execute("""
        INSERT INTO exploration_sales (timestamp, base_value, bonus, total_earnings, event_type)
        VALUES (?, ?, ?, ?, 'SellExplorationData')
    """, (event.get("timestamp"), base, bonus, base + bonus))


# ---------------------------------------------------------------------------
# Commander snapshot (Rank + LoadGame for credits)
# ---------------------------------------------------------------------------

def handle_rank(event: dict, conn: sqlite3.Connection) -> None:
    conn.execute("""
        INSERT INTO commander_snapshots
            (timestamp, rank_combat, rank_trade, rank_explore,
             rank_exobiology, rank_empire, rank_federation)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        event.get("timestamp"),
        event.get("Combat"),
        event.get("Trade"),
        event.get("Explore"),
        event.get("Exobiologist"),
        event.get("Empire"),
        event.get("Federation"),
    ))


def handle_load_game(event: dict, conn: sqlite3.Connection) -> None:
    conn.execute("""
        INSERT INTO commander_snapshots (timestamp, name, credits)
        VALUES (?, ?, ?)
    """, (
        event.get("timestamp"),
        event.get("Commander"),
        event.get("Credits"),
    ))


# ---------------------------------------------------------------------------
# FSS / barycentre / missions / powerplay
# ---------------------------------------------------------------------------

def handle_fss_signal_discovered(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    if not sa:
        return
    _ensure_system(sa, event, conn)
    conn.execute("""
        INSERT OR IGNORE INTO fss_signals
            (system_address, timestamp, signal_name, signal_name_localised, is_station)
        VALUES (?, ?, ?, ?, ?)
    """, (
        sa,
        event.get("timestamp"),
        event.get("SignalName", ""),
        event.get("SignalName_Localised"),
        int(bool(event.get("IsStation", False))),
    ))


def handle_scan_barycentre(event: dict, conn: sqlite3.Connection) -> None:
    sa = event.get("SystemAddress")
    body_id = event.get("BodyID")
    if sa is None or body_id is None:
        return
    _ensure_system(sa, event, conn)
    conn.execute("""
        INSERT OR IGNORE INTO barycentres
            (system_address, body_id, timestamp, semi_major_axis, eccentricity,
             orbital_inclination, periapsis, orbital_period, ascending_node, mean_anomaly)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sa,
        body_id,
        event.get("timestamp"),
        event.get("SemiMajorAxis"),
        event.get("Eccentricity"),
        event.get("OrbitalInclination"),
        event.get("Periapsis"),
        event.get("OrbitalPeriod"),
        event.get("AscendingNode"),
        event.get("MeanAnomaly"),
    ))


def handle_mission_completed(event: dict, conn: sqlite3.Connection) -> None:
    mission_id = event.get("MissionID")
    if mission_id is None:
        return
    station = event.get("DestinationStation") or event.get("DestinationSettlement")
    conn.execute("""
        INSERT OR IGNORE INTO missions
            (mission_id, timestamp, faction, name,
             destination_system, destination_station, reward)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        mission_id,
        event.get("timestamp"),
        event.get("Faction"),
        event.get("Name"),
        event.get("DestinationSystem"),
        station,
        event.get("Reward", 0),
    ))


def handle_powerplay_merits(event: dict, conn: sqlite3.Connection) -> None:
    conn.execute("""
        INSERT INTO powerplay_merits (timestamp, power, merits_gained, total_merits)
        VALUES (?, ?, ?, ?)
    """, (
        event.get("timestamp"),
        event.get("Power", ""),
        event.get("MeritsGained", 0),
        event.get("TotalMerits", 0),
    ))


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

HANDLERS: dict[str, Any] = {
    "FSDJump":                   handle_fsd_jump,
    "Location":                  handle_location,
    "Scan":                      handle_scan,
    "FSSBodySignals":            handle_fss_body_signals,
    "FSSAllBodiesFound":         handle_fss_all_bodies_found,
    "SAASignalsFound":           handle_saa_signals_found,
    "SAAScanComplete":           handle_saa_scan_complete,
    "ScanOrganic":               handle_scan_organic,
    "SellOrganicData":           handle_sell_organic_data,
    "CodexEntry":                handle_codex_entry,
    "DiscoveryScan":             handle_discovery_scan,
    "Statistics":                handle_statistics,
    "MultiSellExplorationData":  handle_multi_sell_exploration_data,
    "SellExplorationData":       handle_sell_exploration_data,
    "Rank":                      handle_rank,
    "Promotion":                 handle_promotion,
    "LoadGame":                  handle_load_game,
    "FSSSignalDiscovered":       handle_fss_signal_discovered,
    "ScanBaryCentre":            handle_scan_barycentre,
    "MissionCompleted":          handle_mission_completed,
    "PowerplayMerits":           handle_powerplay_merits,
}

# Event types we have consciously decided not to handle.
# Any event type found in journals that is in neither HANDLERS nor this set
# is considered unknown and reported at the end of an import run.
KNOWN_IGNORED_EVENTS: frozenset[str] = frozenset({
    # Inventory / loadout snapshots
    "ShipLocker", "Loadout", "StoredModules", "Materials", "SuitLoadout",
    "EngineerProgress", "Backpack", "Cargo", "StoredShips", "BackpackChange",
    "CollectItems", "MaterialCollected",
    # UI / ambient noise
    "Music", "ReceiveText", "SendText", "FSDTarget", "StartJump",
    "ReservoirReplenished", "NavRoute", "NavRouteClear", "DockingRequested",
    "Friends", "UnderAttack",
    # Movement / status
    "Disembark", "Embark", "Touchdown", "Liftoff",
    "SupercruiseEntry", "SupercruiseExit", "SupercruiseDestinationDrop",
    "FuelScoop", "ApproachBody", "LeaveBody", "ApproachSettlement",
    "LaunchSRV", "DockSRV", "SRVDestroyed", "VehicleSwitch",
    # Ship / station interactions
    "Docked", "Undocked", "DockingGranted", "DockingDenied",
    "DockingCancelled", "DockingTimeout",
    "ShieldState", "HullDamage", "HeatWarning", "HeatDamage",
    "JetConeDamage", "JetConeBoost", "CockpitBreached",
    "RefuelAll", "RefuelPartial", "RepairAll", "Repair", "AfmuRepairs", "RebootRepair",
    "BuyAmmo", "BuyDrones", "SellDrones", "Synthesis",
    "LaunchDrone", "RepairDrone", "RestockVehicle",
    "EjectCargo", "CollectCargo", "CargoTransfer",
    # Modules / outfitting
    "ModuleBuy", "ModuleSell", "ModuleStore", "ModuleRetrieve", "ModuleSwap",
    "ModuleSellRemote", "FetchRemoteModule", "ModuleInfo", "MassModuleStore",
    "Outfitting", "Shipyard", "ShipyardBuy", "ShipyardNew", "ShipyardSwap",
    "ShipyardTransfer", "ShipyardRedeem", "ShipRedeemed", "ShipyardSell", "ShipyardBankDeposit",
    # Suits / on-foot
    "SwitchSuitLoadout", "CreateSuitLoadout", "DeleteSuitLoadout",
    "RenameSuitLoadout", "LoadoutEquipModule",
    "BuySuit", "SellSuit", "UpgradeSuit",
    "BuyWeapon", "SellWeapon", "UpgradeWeapon",
    "BookDropship", "DropshipDeploy", "BookTaxi",
    "UseConsumable", "DropItems",
    "TradeMicroResources", "BuyMicroResources", "SellMicroResources",
    # Combat
    "ShipTargeted", "FactionKillBond", "Bounty",
    "Interdicted", "Interdiction", "EscapeInterdiction",
    "PVPKill", "Died", "Resurrect", "SelfDestruct", "SystemsShutdown",
    "Scanned", "DataScanned", "DatalinkScan", "DatalinkVoucher",
    "NavBeaconScan", "USSDrop",
    "CommitCrime", "CrimeVictim", "PayFines", "PayBounties", "RedeemVoucher",
    # Mining
    "MiningRefined", "ProspectedAsteroid", "AsteroidCracked",
    # Trading
    "MarketBuy", "MarketSell", "Market", "CargoDepot", "SearchAndRescue",
    # Materials / engineering / research
    "MaterialTrade", "MaterialDiscovered", "TechnologyBroker",
    "EngineerCraft", "EngineerContribution", "ScientificResearch",
    # Missions
    "MissionAccepted", "MissionAbandoned", "MissionFailed", "MissionRedirected",
    "CommunityGoal", "CommunityGoalJoin", "CommunityGoalReward", "CommunityGoalDiscard",
    # Fleet carriers
    "CarrierJump", "CarrierJumpRequest", "CarrierJumpCancelled", "CarrierStats", "CarrierLocation",
    "CarrierTradeOrder", "CarrierDepositFuel", "CarrierFinance",
    "CarrierBankTransfer", "CarrierCrewServices", "CarrierDockingPermission",
    "CarrierModulePack", "CarrierNameChange", "CarrierShipPack",
    "FCMaterials",
    # Powerplay
    "Powerplay", "PowerplayRank", "PowerplaySalary", "PowerplayCollect",
    "PowerplayDeliver", "PowerplayFastTrack", "PowerplayJoin", "PowerplayLeave",
    # Social / crew / squadrons / wings
    "WingAdd", "WingJoin", "WingLeave", "WingInvite",
    "SquadronStartup", "SquadronPromotion", "JoinedSquadron", "InvitedToSquadron",
    "SharedBookmarkToSquadron",
    "ChangeCrewRole", "CrewMemberJoins", "CrewMemberQuits", "CrewMemberRoleChange",
    "EndCrewSession", "JoinACrew", "KickCrewMember", "QuitACrew",
    # Colonisation
    "ColonisationConstructionDepot", "ColonisationContribution",
    "ColonisationBeaconDeployed", "ColonisationSystemClaim",
    "DeliverPowerMicroResources",
    # FSS progress (body count already captured via DiscoveryScan / FSSAllBodiesFound)
    "FSSDiscoveryScan",
    # Session bookkeeping / misc
    "Fileheader", "Commander", "Shutdown", "Progress", "Reputation",
    "Missions", "Passengers", "SetUserShipName", "Screenshot",
    "BuyExplorationData", "Resupply",
})
