"""
Database schema definitions and creation.

All tables use INTEGER PRIMARY KEY (rowid alias) for fast inserts.
system_address is the game's 64-bit SystemAddress — unique across the galaxy.
"""

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Tracks which journal files have been fully processed.
CREATE TABLE IF NOT EXISTS journal_files (
    id              INTEGER PRIMARY KEY,
    filename        TEXT    NOT NULL UNIQUE,
    processed_at    TEXT    NOT NULL,   -- ISO-8601
    event_count     INTEGER NOT NULL DEFAULT 0,
    file_size       INTEGER NOT NULL DEFAULT 0,  -- bytes at last import
    lines_processed INTEGER NOT NULL DEFAULT 0   -- total lines read (resume offset)
);

-- One row per unique star system visited.
CREATE TABLE IF NOT EXISTS systems (
    id              INTEGER PRIMARY KEY,
    system_address  INTEGER NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    x               REAL,
    y               REAL,
    z               REAL,
    star_class      TEXT,               -- primary star spectral class
    region          TEXT,               -- CodexEntry region name
    first_seen_at   TEXT,               -- timestamp of first FSDJump/Location event
    total_bodies    INTEGER,            -- body count from DiscoveryScan (honk)
    fss_complete    INTEGER DEFAULT 0   -- 1 when FSSAllBodiesFound fired
);

CREATE INDEX IF NOT EXISTS idx_systems_coords ON systems(x, y, z);
CREATE INDEX IF NOT EXISTS idx_systems_name   ON systems(name);

-- Every FSD jump, in order. Enables route replay and distance stats.
CREATE TABLE IF NOT EXISTS jumps (
    id              INTEGER PRIMARY KEY,
    system_address  INTEGER NOT NULL REFERENCES systems(system_address),
    timestamp       TEXT    NOT NULL,
    jump_dist       REAL,               -- ly from previous system
    fuel_used       REAL,
    fuel_remaining  REAL
);

CREATE INDEX IF NOT EXISTS idx_jumps_ts ON jumps(timestamp);

-- Bodies (planets, moons, stars) discovered via Scan events.
CREATE TABLE IF NOT EXISTS bodies (
    id                  INTEGER PRIMARY KEY,
    system_address      INTEGER NOT NULL REFERENCES systems(system_address),
    body_id             INTEGER NOT NULL,           -- in-game BodyID
    name                TEXT    NOT NULL,
    body_type           TEXT    NOT NULL,           -- 'Planet', 'Star', 'Belt'
    subtype             TEXT,                       -- e.g. 'High metal content body'
    distance_ls         REAL,
    radius_km           REAL,
    mass_em             REAL,                       -- Earth masses (planets) / Solar masses (stars)
    age_my              REAL,                       -- Age in million years (stars only)
    surface_gravity_g   REAL,
    surface_temp_k      REAL,
    surface_pressure    REAL,
    atmosphere_type     TEXT,
    atmosphere_density  TEXT,                       -- 'thin', 'thick', etc. extracted from type
    atmosphere_he_pct   REAL,                       -- He% from AtmosphereComposition (gas giants)
    volcanism           TEXT,
    is_landable         INTEGER,                    -- 0/1
    terraform_state     TEXT,
    bio_signals         INTEGER DEFAULT 0,
    geo_signals         INTEGER DEFAULT 0,
    was_mapped          INTEGER DEFAULT 0,          -- SAAScanComplete
    first_discovered    INTEGER DEFAULT 0,          -- WasDiscovered=false at scan time
    first_mapped        INTEGER DEFAULT 0,          -- WasMapped=false at scan time
    scanned_at          TEXT,
    UNIQUE(system_address, body_id)
);

CREATE INDEX IF NOT EXISTS idx_bodies_system   ON bodies(system_address);
CREATE INDEX IF NOT EXISTS idx_bodies_subtype  ON bodies(subtype);
CREATE INDEX IF NOT EXISTS idx_bodies_landable ON bodies(is_landable);
CREATE INDEX IF NOT EXISTS idx_bodies_bio      ON bodies(bio_signals);

-- Biological signal types found on a body (SAASignalsFound).
CREATE TABLE IF NOT EXISTS bio_signals (
    id              INTEGER PRIMARY KEY,
    system_address  INTEGER NOT NULL REFERENCES systems(system_address),
    body_id         INTEGER NOT NULL,
    genus           TEXT    NOT NULL,   -- e.g. '$Codex_Ent_Stratum_Genus_Name;'
    genus_localised TEXT,
    count           INTEGER NOT NULL DEFAULT 1,
    UNIQUE(system_address, body_id, genus)
);

CREATE INDEX IF NOT EXISTS idx_biosig_body ON bio_signals(system_address, body_id);

-- Individual organism scan events (ScanOrganic).
-- state: 'Log', 'Sample', 'Analyse' — Analyse is the completed scan.
CREATE TABLE IF NOT EXISTS organic_scans (
    id              INTEGER PRIMARY KEY,
    system_address  INTEGER NOT NULL REFERENCES systems(system_address),
    body_id         INTEGER NOT NULL,
    timestamp       TEXT    NOT NULL,
    scan_state      TEXT    NOT NULL,   -- Log / Sample / Analyse
    genus           TEXT,
    genus_localised TEXT,
    species         TEXT,
    species_localised TEXT,
    variant         TEXT,
    variant_localised TEXT
);

CREATE INDEX IF NOT EXISTS idx_orgscans_body  ON organic_scans(system_address, body_id);
CREATE INDEX IF NOT EXISTS idx_orgscans_state ON organic_scans(scan_state);

-- Organisms sold at Vista Genomics (SellOrganicData).
CREATE TABLE IF NOT EXISTS organic_sales (
    id              INTEGER PRIMARY KEY,
    timestamp       TEXT    NOT NULL,
    species         TEXT    NOT NULL,
    species_localised TEXT,
    bonus           INTEGER NOT NULL DEFAULT 0,     -- first-footfall bonus
    value           INTEGER NOT NULL,               -- credits
    total           INTEGER NOT NULL                -- value + bonus
);

CREATE INDEX IF NOT EXISTS idx_orgsales_ts ON organic_sales(timestamp);

-- Codex entries — first-in-region discoveries.
CREATE TABLE IF NOT EXISTS codex_entries (
    id              INTEGER PRIMARY KEY,
    system_address  INTEGER NOT NULL REFERENCES systems(system_address),
    timestamp       TEXT    NOT NULL,
    entry_id        INTEGER NOT NULL,
    name            TEXT,
    name_localised  TEXT,
    sub_category    TEXT,
    category        TEXT,
    region          TEXT,
    is_new_entry    INTEGER DEFAULT 0,
    UNIQUE(entry_id, region)
);

-- Exploration data sold (MultiSellExplorationData / SAAScanComplete sale).
CREATE TABLE IF NOT EXISTS exploration_sales (
    id              INTEGER PRIMARY KEY,
    timestamp       TEXT    NOT NULL,
    system_address  INTEGER,
    base_value      INTEGER NOT NULL DEFAULT 0,
    bonus           INTEGER NOT NULL DEFAULT 0,
    total_earnings  INTEGER NOT NULL DEFAULT 0,
    event_type      TEXT    NOT NULL   -- 'MultiSellExplorationData' or 'SAAScanComplete'
);

CREATE INDEX IF NOT EXISTS idx_expsales_ts ON exploration_sales(timestamp);

-- Commander snapshot per session start (for rank/credits progression).
CREATE TABLE IF NOT EXISTS commander_snapshots (
    id              INTEGER PRIMARY KEY,
    timestamp       TEXT    NOT NULL,
    name            TEXT,
    credits         INTEGER,
    rank_combat     INTEGER,
    rank_trade      INTEGER,
    rank_explore    INTEGER,
    rank_exobiology INTEGER,
    rank_empire     INTEGER,
    rank_federation INTEGER
);

-- Exploration and other commander statistics snapshots (Statistics event).
CREATE TABLE IF NOT EXISTS statistics_snapshots (
    id                      INTEGER PRIMARY KEY,
    timestamp               TEXT    NOT NULL,
    -- Exploration
    systems_visited         INTEGER,
    exploration_profits     INTEGER,
    planets_scanned_to_level1 INTEGER,
    planets_scanned_to_level2 INTEGER,
    efficient_scans         INTEGER,
    highest_payout          INTEGER,
    total_hyperspace_dist   REAL,
    total_hyperspace_jumps  INTEGER,
    greatest_dist_from_start REAL,
    time_played             INTEGER,
    -- Exobiology
    organic_genus_encountered INTEGER,
    organic_species_encountered INTEGER,
    organic_species_analysed  INTEGER,
    exobiology_profits        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_stats_ts ON statistics_snapshots(timestamp);

-- Every signal discovered during FSS scanning (FSSSignalDiscovered).
CREATE TABLE IF NOT EXISTS fss_signals (
    id                    INTEGER PRIMARY KEY,
    system_address        INTEGER NOT NULL REFERENCES systems(system_address),
    timestamp             TEXT    NOT NULL,
    signal_name           TEXT    NOT NULL,
    signal_name_localised TEXT,
    is_station            INTEGER NOT NULL DEFAULT 0,
    UNIQUE(system_address, signal_name)
);

CREATE INDEX IF NOT EXISTS idx_fss_signals_system ON fss_signals(system_address);
CREATE INDEX IF NOT EXISTS idx_fss_signals_name   ON fss_signals(signal_name);

-- Barycentre orbital data (ScanBaryCentre).
CREATE TABLE IF NOT EXISTS barycentres (
    id                  INTEGER PRIMARY KEY,
    system_address      INTEGER NOT NULL REFERENCES systems(system_address),
    body_id             INTEGER NOT NULL,
    timestamp           TEXT    NOT NULL,
    semi_major_axis     REAL,   -- metres
    eccentricity        REAL,
    orbital_inclination REAL,   -- degrees
    periapsis           REAL,   -- degrees
    orbital_period      REAL,   -- seconds
    ascending_node      REAL,   -- degrees
    mean_anomaly        REAL,   -- degrees
    UNIQUE(system_address, body_id)
);

CREATE INDEX IF NOT EXISTS idx_barycentres_system ON barycentres(system_address);

-- Completed missions (MissionCompleted).
CREATE TABLE IF NOT EXISTS missions (
    id                  INTEGER PRIMARY KEY,
    mission_id          INTEGER NOT NULL UNIQUE,
    timestamp           TEXT    NOT NULL,
    faction             TEXT,
    name                TEXT,   -- mission type key, e.g. 'Mission_Courier_Democracy_name'
    destination_system  TEXT,
    destination_station TEXT,   -- station or settlement name
    reward              INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_missions_ts      ON missions(timestamp);
CREATE INDEX IF NOT EXISTS idx_missions_faction ON missions(faction);

-- Powerplay merit events (PowerplayMerits).
CREATE TABLE IF NOT EXISTS powerplay_merits (
    id           INTEGER PRIMARY KEY,
    timestamp    TEXT    NOT NULL,
    power        TEXT    NOT NULL,
    merits_gained INTEGER NOT NULL DEFAULT 0,
    total_merits  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pp_merits_ts    ON powerplay_merits(timestamp);
CREATE INDEX IF NOT EXISTS idx_pp_merits_power ON powerplay_merits(power);
"""
