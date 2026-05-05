"""Database connection management and helpers."""

import sqlite3
from pathlib import Path
from typing import Optional

from .schema import SCHEMA_SQL


_DEFAULT_DB = Path(".edda") / "ed.db"


def get_db_path(override: Optional[Path] = None) -> Path:
    path = Path(override) if override else _DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def open_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = get_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    for sql in (
        "ALTER TABLE journal_files ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE journal_files ADD COLUMN lines_processed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE bodies ADD COLUMN age_my REAL",
        "ALTER TABLE systems ADD COLUMN total_bodies INTEGER",
        "ALTER TABLE systems ADD COLUMN fss_complete INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(sql)
        except Exception:
            pass
    conn.commit()
    return conn


def upsert_system(conn: sqlite3.Connection, system_address: int, name: str,
                  x: float, y: float, z: float, star_class: Optional[str],
                  timestamp: str) -> None:
    conn.execute("""
        INSERT INTO systems (system_address, name, x, y, z, star_class, first_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address) DO UPDATE SET
            name       = excluded.name,
            x          = excluded.x,
            y          = excluded.y,
            z          = excluded.z,
            star_class = COALESCE(excluded.star_class, systems.star_class)
    """, (system_address, name, x, y, z, star_class, timestamp))


def upsert_body(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute("""
        INSERT INTO bodies (
            system_address, body_id, name, body_type, subtype,
            distance_ls, radius_km, mass_em, surface_gravity_g,
            surface_temp_k, surface_pressure, atmosphere_type,
            atmosphere_density, volcanism, is_landable,
            terraform_state, bio_signals, geo_signals,
            was_mapped, first_discovered, first_mapped, scanned_at
        ) VALUES (
            :system_address, :body_id, :name, :body_type, :subtype,
            :distance_ls, :radius_km, :mass_em, :surface_gravity_g,
            :surface_temp_k, :surface_pressure, :atmosphere_type,
            :atmosphere_density, :volcanism, :is_landable,
            :terraform_state, :bio_signals, :geo_signals,
            :was_mapped, :first_discovered, :first_mapped, :scanned_at
        )
        ON CONFLICT(system_address, body_id) DO UPDATE SET
            subtype            = COALESCE(excluded.subtype, bodies.subtype),
            distance_ls        = COALESCE(excluded.distance_ls, bodies.distance_ls),
            radius_km          = COALESCE(excluded.radius_km, bodies.radius_km),
            mass_em            = COALESCE(excluded.mass_em, bodies.mass_em),
            surface_gravity_g  = COALESCE(excluded.surface_gravity_g, bodies.surface_gravity_g),
            surface_temp_k     = COALESCE(excluded.surface_temp_k, bodies.surface_temp_k),
            surface_pressure   = COALESCE(excluded.surface_pressure, bodies.surface_pressure),
            atmosphere_type    = COALESCE(excluded.atmosphere_type, bodies.atmosphere_type),
            atmosphere_density = COALESCE(excluded.atmosphere_density, bodies.atmosphere_density),
            volcanism          = COALESCE(excluded.volcanism, bodies.volcanism),
            is_landable        = COALESCE(excluded.is_landable, bodies.is_landable),
            terraform_state    = COALESCE(excluded.terraform_state, bodies.terraform_state),
            bio_signals        = MAX(excluded.bio_signals, bodies.bio_signals),
            geo_signals        = MAX(excluded.geo_signals, bodies.geo_signals),
            was_mapped         = MAX(excluded.was_mapped, bodies.was_mapped),
            first_discovered   = MAX(excluded.first_discovered, bodies.first_discovered),
            first_mapped       = MAX(excluded.first_mapped, bodies.first_mapped),
            scanned_at         = COALESCE(bodies.scanned_at, excluded.scanned_at)
    """, row)
