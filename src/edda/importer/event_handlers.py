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
    conn.execute("""
        INSERT INTO systems (system_address, name, x, y, z, star_class, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address) DO UPDATE SET
            name       = excluded.name,
            x          = excluded.x,
            y          = excluded.y,
            z          = excluded.z,
            star_class = COALESCE(excluded.star_class, systems.star_class)
    """, (
        sa,
        event.get("StarSystem", ""),
        event.get("StarPos", [None, None, None])[0],
        event.get("StarPos", [None, None, None])[1],
        event.get("StarPos", [None, None, None])[2],
        None,  # star_class populated later from Scan events
        event.get("timestamp"),
    ))
    conn.execute("""
        INSERT INTO jumps (system_address, timestamp, jump_dist, fuel_used, fuel_remaining)
        VALUES (?, ?, ?, ?, ?)
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
    conn.execute("""
        INSERT INTO systems (system_address, name, x, y, z, star_class, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address) DO NOTHING
    """, (
        sa,
        event.get("StarSystem", ""),
        star_pos[0], star_pos[1], star_pos[2],
        event.get("StarClass"),
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

    # Update system's primary star class from the main-star scan
    if body_type == "Star" and event.get("DistanceFromArrivalLS", 999) < 1:
        conn.execute("""
            UPDATE systems SET star_class = ?
            WHERE system_address = ? AND star_class IS NULL
        """, (subtype, sa))

    row: dict[str, Any] = {
        "system_address":    sa,
        "body_id":           body_id,
        "name":              body_name,
        "body_type":         body_type,
        "subtype":           subtype,
        "distance_ls":       event.get("DistanceFromArrivalLS"),
        "radius_km":         event.get("Radius", 0) / 1000.0 if event.get("Radius") else None,
        "mass_em":           event.get("StellarMass") if body_type == "Star" else event.get("MassEM"),
        "age_my":            event.get("Age_MY") if body_type == "Star" else None,
        "surface_gravity_g": event.get("SurfaceGravity", 0) / 9.80665 if event.get("SurfaceGravity") else None,
        "surface_temp_k":    event.get("SurfaceTemperature"),
        "surface_pressure":  event.get("SurfacePressure"),
        "atmosphere_type":    atmo_type,
        "atmosphere_density": _atmosphere_density(atmo_type),
        "atmosphere_he_pct":  he_pct,
        "volcanism":         event.get("Volcanism"),
        "is_landable":       int(bool(event.get("Landable"))),
        "terraform_state":   event.get("TerraformState"),
        "bio_signals":       0,
        "geo_signals":       0,
        "was_mapped":        0,
        "first_discovered":  int(not event.get("WasDiscovered", True)),
        "first_mapped":      int(not event.get("WasMapped", True)),
        "scanned_at":        event.get("timestamp"),
    }

    conn.execute("""
        INSERT INTO bodies (
            system_address, body_id, name, body_type, subtype,
            distance_ls, radius_km, mass_em, age_my, surface_gravity_g,
            surface_temp_k, surface_pressure, atmosphere_type,
            atmosphere_density, atmosphere_he_pct, volcanism, is_landable,
            terraform_state, bio_signals, geo_signals,
            was_mapped, first_discovered, first_mapped, scanned_at
        ) VALUES (
            :system_address, :body_id, :name, :body_type, :subtype,
            :distance_ls, :radius_km, :mass_em, :age_my, :surface_gravity_g,
            :surface_temp_k, :surface_pressure, :atmosphere_type,
            :atmosphere_density, :atmosphere_he_pct, :volcanism, :is_landable,
            :terraform_state, :bio_signals, :geo_signals,
            :was_mapped, :first_discovered, :first_mapped, :scanned_at
        )
        ON CONFLICT(system_address, body_id) DO UPDATE SET
            subtype            = COALESCE(excluded.subtype, bodies.subtype),
            distance_ls        = COALESCE(excluded.distance_ls, bodies.distance_ls),
            radius_km          = COALESCE(excluded.radius_km, bodies.radius_km),
            mass_em            = COALESCE(excluded.mass_em, bodies.mass_em),
            age_my             = COALESCE(excluded.age_my, bodies.age_my),
            surface_gravity_g  = COALESCE(excluded.surface_gravity_g, bodies.surface_gravity_g),
            surface_temp_k     = COALESCE(excluded.surface_temp_k, bodies.surface_temp_k),
            surface_pressure   = COALESCE(excluded.surface_pressure, bodies.surface_pressure),
            atmosphere_type    = COALESCE(excluded.atmosphere_type, bodies.atmosphere_type),
            atmosphere_density = COALESCE(excluded.atmosphere_density, bodies.atmosphere_density),
            atmosphere_he_pct  = COALESCE(excluded.atmosphere_he_pct, bodies.atmosphere_he_pct),
            volcanism          = COALESCE(excluded.volcanism, bodies.volcanism),
            is_landable        = COALESCE(excluded.is_landable, bodies.is_landable),
            terraform_state    = COALESCE(excluded.terraform_state, bodies.terraform_state),
            first_discovered   = MAX(excluded.first_discovered, bodies.first_discovered),
            first_mapped       = MAX(excluded.first_mapped, bodies.first_mapped),
            scanned_at         = COALESCE(bodies.scanned_at, excluded.scanned_at)
    """, row)


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

    if bio_total > 0 or geo_total > 0:
        conn.execute("""
            UPDATE bodies SET
                bio_signals = MAX(bio_signals, ?),
                geo_signals = MAX(geo_signals, ?)
            WHERE system_address = ? AND body_id = ?
        """, (bio_total, geo_total, sa, body_id))


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

    if bio_total > 0 or geo_total > 0:
        conn.execute("""
            UPDATE bodies SET
                bio_signals = MAX(bio_signals, ?),
                geo_signals = MAX(geo_signals, ?)
            WHERE system_address = ? AND body_id = ?
        """, (bio_total, geo_total, sa, body_id))


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
        INSERT INTO organic_scans
            (system_address, body_id, timestamp, scan_state,
             genus, genus_localised, species, species_localised,
             variant, variant_localised)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sa, body_id,
        event.get("timestamp"),
        event.get("ScanType"),
        event.get("Genus"),
        event.get("Genus_Localised"),
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
# Exploration sales
# ---------------------------------------------------------------------------

def handle_multi_sell_exploration_data(event: dict, conn: sqlite3.Connection) -> None:
    base = event.get("BaseValue", 0)
    bonus = event.get("Bonus", 0)
    conn.execute("""
        INSERT INTO exploration_sales (timestamp, base_value, bonus, total_earnings, event_type)
        VALUES (?, ?, ?, ?, 'MultiSellExplorationData')
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
# Dispatch table
# ---------------------------------------------------------------------------

HANDLERS: dict[str, Any] = {
    "FSDJump":                   handle_fsd_jump,
    "Location":                  handle_location,
    "Scan":                      handle_scan,
    "FSSBodySignals":            handle_fss_body_signals,
    "SAASignalsFound":           handle_saa_signals_found,
    "SAAScanComplete":           handle_saa_scan_complete,
    "ScanOrganic":               handle_scan_organic,
    "SellOrganicData":           handle_sell_organic_data,
    "CodexEntry":                handle_codex_entry,
    "MultiSellExplorationData":  handle_multi_sell_exploration_data,
    "Rank":                      handle_rank,
    "LoadGame":                  handle_load_game,
}
