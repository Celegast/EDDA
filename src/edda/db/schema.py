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
    event_count     INTEGER NOT NULL DEFAULT 0
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
    first_seen_at   TEXT                -- timestamp of first FSDJump/Location event
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
    mass_em             REAL,                       -- Earth masses (planets)
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
"""
