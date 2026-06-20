"""Flask-based web UI — control panel + query builder (pdm run serve)."""

from __future__ import annotations

import argparse
import json
import queue
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from edda import __version__ as _VERSION

from flask import Flask, Response, jsonify, render_template_string, request, stream_with_context

from .analysis._region_map_data import regions as _REGION_NAMES
from .analysis.valuation import SPECIES_VALUES as _SV
from .config import (
    list_commanders, get_active_commander, set_active_commander,
    get_ui_state, set_ui_state,
)
from .db.connection import open_db

# ── Shared choice lists ───────────────────────────────────────────────────────

_STAR_CLASS_CHOICES: list[str] = [
    "O", "B", "A", "F", "G", "K", "M", "L", "T", "Y",
    "TTS", "AeBe",
    "M_RedGiant", "M_RedSuperGiant", "K_OrangeGiant",
    "B_BlueWhiteSuperGiant", "A_BlueWhiteSuperGiant",
    "F_WhiteSuperGiant", "G_WhiteSuperGiant",
    "W", "WN", "WNC", "WC", "WO",
    "C", "CN", "CJ", "CS", "MS", "S",
    "D", "DA", "DAB", "DAV", "DAZ", "DB", "DBV", "DBZ", "DC", "DCV", "DQ",
    "N", "H",
]

_PLANET_SUBTYPE_CHOICES: list[str] = [
    "Rocky body", "Rocky ice body", "Icy body",
    "Metal rich body", "High metal content body",
    "Earthlike body", "Water world", "Ammonia world",
    "Water giant", "Water giant with life",
    "Gas giant with water based life", "Gas giant with ammonia based life",
    "Sudarsky class I gas giant", "Sudarsky class II gas giant",
    "Sudarsky class III gas giant", "Sudarsky class IV gas giant",
    "Sudarsky class V gas giant",
    "Helium rich gas giant", "Helium gas giant",
]

_GENUS_CHOICES: list[str] = [
    "Aleoida", "Bacterium", "Cactoida", "Clypeus", "Concha",
    "Electricae", "Fonticulua", "Frutexa", "Fumerola", "Fungoida",
    "Osseus", "Radicoida", "Recepta", "Stratum", "Tubus", "Tussock",
    "Amphora Plant", "Anemone", "Bark Mounds", "Brain Tree",
    "Coral Root", "Coral Tree", "Crystalline Shards", "Sinuous Tubers",
    "Thargoid Barnacle Matrix", "Thargoid Mega Barnacles", "Thargoid Spire",
]

_SPECIES_CHOICES: list[str] = sorted(_SV)

_REGION_CHOICES: list[str] = [r for r in _REGION_NAMES if r is not None]

# ── Correlated subqueries ─────────────────────────────────────────────────────

_SQ_BODY_VOLCANISM = (
    "SELECT 1 WHERE b.volcanism IS NOT NULL"
    " AND b.volcanism != ''"
    " AND b.volcanism NOT LIKE 'No volcanism%'"
)

_SQ_BODY_RINGS = (
    "SELECT 1 FROM rings r2"
    " WHERE r2.system_address = b.system_address"
    " AND r2.body_id = b.body_id"
    " AND r2.name NOT LIKE '% Belt'"
)
_SQ_BODY_ORGANIC = (
    "SELECT 1 FROM organic_scans os2"
    " WHERE os2.system_address = b.system_address"
    " AND os2.body_id = b.body_id"
    " AND os2.scan_state = 'Analyse'"
)
_SQ_ORGANIC_STAR_RINGS = (
    "SELECT 1 FROM bodies star_b"
    " JOIN rings r ON r.system_address = star_b.system_address"
    "   AND r.body_id = star_b.body_id"
    " WHERE star_b.system_address = s.system_address"
    " AND star_b.body_type = 'Star'"
    " AND star_b.distance_ls < 1"
    " AND r.name NOT LIKE '% Belt'"
)

_SQ_ORGANIC_PARENT_RINGS = (
    "SELECT 1 FROM bodies ps"
    " JOIN rings r ON r.system_address = ps.system_address"
    "   AND r.body_id = ps.body_id"
    " WHERE ps.system_address = b.system_address"
    " AND ps.body_id = b.parent_star_id"
    " AND r.name NOT LIKE '% Belt'"
)

_SQ_SYS_BIO = (
    "SELECT 1 FROM bodies b2"
    " WHERE b2.system_address = s.system_address"
    " AND b2.bio_signals > 0"
)
_SQ_SYS_ELW = (
    "SELECT 1 FROM bodies b2"
    " WHERE b2.system_address = s.system_address"
    " AND b2.subtype = 'Earthlike body'"
)
_SQ_SYS_WW = (
    "SELECT 1 FROM bodies b2"
    " WHERE b2.system_address = s.system_address"
    " AND b2.subtype = 'Water world'"
)
_SQ_SYS_TERRA = (
    "SELECT 1 FROM bodies b2"
    " WHERE b2.system_address = s.system_address"
    " AND b2.terraform_state IS NOT NULL"
    " AND b2.terraform_state != ''"
)

_BOOL_COLS: frozenset[str] = frozenset({
    "b.is_landable", "s.fss_complete", "b.was_mapped",
    "b.first_discovered", "b.first_mapped",
})

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA: dict[str, dict[str, Any]] = {
    "Systems": {
        "from":       "systems s",
        "base_where": None,
        "display": [
            ("s.name",         "Name"),
            ("s.star_class",   "Star class"),
            ("s.region",       "Region"),
            ("s.x",            "X"),
            ("s.y",            "Y"),
            ("s.z",            "Z"),
            ("s.total_bodies", "Total bodies"),
            ("s.fss_complete", "FSS complete"),
        ],
        "fields": {
            "Name":              {"col": "s.name",         "type": "text"},
            "Star class":        {"col": "s.star_class",   "type": "choice",
                                  "choices": _STAR_CLASS_CHOICES},
            "Region":            {"col": "s.region", "type": "choice", "choices": _REGION_CHOICES},
            "X":                 {"col": "s.x",            "type": "number"},
            "Y":                 {"col": "s.y",            "type": "number"},
            "Z":                 {"col": "s.z",            "type": "number"},
            "Total bodies":      {"col": "s.total_bodies", "type": "number"},
            "FSS complete":      {"col": "s.fss_complete", "type": "choice",
                                  "choices": ["Yes", "No"]},
            "First seen":        {"col": "s.first_seen_at", "type": "datetime"},
            "Has bio signals":   {"type": "exists", "subquery": _SQ_SYS_BIO},
            "Has ELW":           {"type": "exists", "subquery": _SQ_SYS_ELW},
            "Has water world":   {"type": "exists", "subquery": _SQ_SYS_WW},
            "Has terraformable": {"type": "exists", "subquery": _SQ_SYS_TERRA},
        },
    },
    "Planets": {
        "from": (
            "bodies b "
            "JOIN systems s ON s.system_address = b.system_address"
        ),
        "base_where": "b.body_type = 'Planet'",
        "display": [
            ("b.name",              "Body"),
            ("s.name",              "System"),
            ("b.subtype",           "Type"),
            ("b.distance_ls",       "Dist (ls)"),
            ("b.radius_km",         "Radius (km)"),
            ("b.mass_em",           "Mass (EM)"),
            ("b.surface_gravity_g", "Gravity (g)"),
            ("b.surface_temp_k",    "Temp (K)"),
            ("b.atmosphere_type",   "Atmosphere"),
            ("b.terraform_state",   "Terraform"),
            ("b.bio_signals",       "Bio signals"),
            ("b.geo_signals",       "Geo signals"),
            ("b.is_landable",       "Landable"),
            ("b.was_mapped",        "Mapped"),
            ("b.first_discovered",  "1st disc"),
            ("s.region",            "Region"),
        ],
        "fields": {
            "Name":             {"col": "b.name",              "type": "text"},
            "System name":      {"col": "s.name",              "type": "text"},
            "Subtype":          {"col": "b.subtype",           "type": "choice",
                                 "choices": _PLANET_SUBTYPE_CHOICES},
            "Distance (ls)":    {"col": "b.distance_ls",       "type": "number"},
            "Radius (km)":      {"col": "b.radius_km",         "type": "number"},
            "Mass (EM)":        {"col": "b.mass_em",           "type": "number"},
            "Gravity (g)":      {"col": "b.surface_gravity_g", "type": "number"},
            "Temperature (K)":  {"col": "b.surface_temp_k",    "type": "number"},
            "Surface pressure": {"col": "b.surface_pressure",  "type": "number"},
            "Atmosphere":       {"col": "b.atmosphere_type",   "type": "choice",
                                 "choices": [
                                     ["None",              "None"],
                                     ["EarthLike",         "Earth-Like"],
                                     ["Ammonia",           "Ammonia"],
                                     ["AmmoniaRich",       "Ammonia-Rich"],
                                     ["AmmoniaOxygen",     "Ammonia-Oxygen"],
                                     ["Water",             "Water"],
                                     ["WaterRich",         "Water-Rich"],
                                     ["CarbonDioxide",     "Carbon Dioxide"],
                                     ["CarbonDioxideRich", "Carbon Dioxide-Rich"],
                                     ["SulphurDioxide",    "Sulphur Dioxide"],
                                     ["Nitrogen",          "Nitrogen"],
                                     ["Methane",           "Methane"],
                                     ["MethaneRich",       "Methane-Rich"],
                                     ["Helium",            "Helium"],
                                     ["Neon",              "Neon"],
                                     ["NeonRich",          "Neon-Rich"],
                                     ["Argon",             "Argon"],
                                     ["ArgonRich",         "Argon-Rich"],
                                     ["Oxygen",            "Oxygen"],
                                     ["SilicateVapour",    "Silicate Vapour"],
                                     ["MetallicVapour",    "Metallic Vapour"],
                                 ]},
            "Has volcanism":    {"type": "exists", "subquery": _SQ_BODY_VOLCANISM},
            "Is landable":      {"col": "b.is_landable",       "type": "choice",
                                 "choices": ["Yes", "No"]},
            "Terraform state":  {"col": "b.terraform_state",   "type": "choice",
                                 "choices": ["Terraformable", "Terraformed", "Terraforming"]},
            "Bio signals":      {"col": "b.bio_signals",       "type": "number"},
            "Geo signals":      {"col": "b.geo_signals",       "type": "number"},
            "Was mapped":       {"col": "b.was_mapped",        "type": "choice",
                                 "choices": ["Yes", "No"]},
            "First discovered": {"col": "b.first_discovered",  "type": "choice",
                                 "choices": ["Yes", "No"]},
            "First mapped":     {"col": "b.first_mapped",      "type": "choice",
                                 "choices": ["Yes", "No"]},
            "He atmosphere %":  {"col": "b.atmosphere_he_pct", "type": "number"},
            "Star class":       {"col": "s.star_class",        "type": "choice",
                                 "choices": _STAR_CLASS_CHOICES},
            "Region":           {"col": "s.region", "type": "choice", "choices": _REGION_CHOICES},
            "Scanned at":       {"col": "b.scanned_at", "type": "datetime"},
            "Has rings":        {"type": "exists", "subquery": _SQ_BODY_RINGS},
            "Has organic scans":{"type": "exists", "subquery": _SQ_BODY_ORGANIC},
        },
    },
    "Stars": {
        "from": (
            "bodies b "
            "JOIN systems s ON s.system_address = b.system_address"
        ),
        "base_where": "b.body_type = 'Star'",
        "display": [
            ("b.name",               "Body"),
            ("s.name",               "System"),
            ("b.subtype",            "Star type"),
            ("b.subclass",           "Subclass"),
            ("b.luminosity",         "Luminosity"),
            ("b.age_my",             "Age (My)"),
            ("b.mass_em",            "Mass (SM)"),
            ("b.surface_temp_k",     "Temp (K)"),
            ("b.absolute_magnitude", "Abs mag"),
            ("b.distance_ls",        "Dist (ls)"),
            ("s.region",             "Region"),
        ],
        "fields": {
            "Name":            {"col": "b.name",               "type": "text"},
            "System name":     {"col": "s.name",               "type": "text"},
            "Star type":       {"col": "b.subtype",            "type": "choice",
                                "choices": _STAR_CLASS_CHOICES},
            "Subclass":        {"col": "b.subclass",           "type": "number"},
            "Luminosity":      {"col": "b.luminosity",         "type": "choice",
                                "choices": [
                                    "O",
                                    "Ia0", "Ia", "Iab", "Ib", "I",
                                    "IIa", "IIab", "IIb", "II",
                                    "IIIa", "IIIab", "IIIb", "III",
                                    "IVa", "IVab", "IVb", "IV",
                                    "V", "Va", "Vab", "Vb", "Vz",
                                    "VI", "VII",
                                ]},
            "Age (My)":        {"col": "b.age_my",             "type": "number"},
            "Mass (SM)":       {"col": "b.mass_em",            "type": "number"},
            "Temperature (K)": {"col": "b.surface_temp_k",    "type": "number"},
            "Abs magnitude":   {"col": "b.absolute_magnitude", "type": "number"},
            "Distance (ls)":   {"col": "b.distance_ls",        "type": "number"},
            "Scanned at":      {"col": "b.scanned_at", "type": "datetime"},
            "Region":          {"col": "s.region", "type": "choice", "choices": _REGION_CHOICES},
            "Has rings":       {"type": "exists", "subquery": _SQ_BODY_RINGS},
        },
    },
    "Organic Scans": {
        "from": (
            "organic_scans os "
            "JOIN systems s ON s.system_address = os.system_address "
            "LEFT JOIN bodies b ON b.system_address = os.system_address "
            "  AND b.body_id = os.body_id"
        ),
        "base_where": "os.scan_state = 'Analyse'",
        "display": [
            ("os.genus_localised",   "Genus"),
            ("os.species_localised", "Species"),
            ("s.name",               "System"),
            ("b.name",               "Body"),
            ("b.subtype",            "Planet type"),
            ("s.star_class",         "Star class"),
            ("s.region",             "Region"),
            ("os.timestamp",         "Timestamp"),
        ],
        "fields": {
            "Genus":       {"col": "os.genus_localised",   "type": "choice",
                            "choices": _GENUS_CHOICES},
            "Species":     {"col": "os.species_localised", "type": "choice",
                            "choices": _SPECIES_CHOICES},
            "System name": {"col": "s.name",               "type": "text"},
            "Body name":   {"col": "b.name",               "type": "text"},
            "Planet type": {"col": "b.subtype",            "type": "choice",
                            "choices": _PLANET_SUBTYPE_CHOICES},
            "Star class":  {"col": "s.star_class",         "type": "choice",
                            "choices": _STAR_CLASS_CHOICES},
            "Primary star has rings": {"type": "exists",
                                       "subquery": _SQ_ORGANIC_STAR_RINGS},
            "Parent star type": {"type": "parent_subtype",
                                 "choices": _STAR_CLASS_CHOICES},
            "Parent star has rings": {"type": "exists",
                                      "subquery": _SQ_ORGANIC_PARENT_RINGS},
            "Timestamp":   {"col": "os.timestamp", "type": "datetime"},
            "Region":      {"col": "s.region", "type": "choice", "choices": _REGION_CHOICES},
        },
    },
    "Rings": {
        "from": (
            "rings r "
            "JOIN bodies b ON b.system_address = r.system_address "
            "  AND b.body_id = r.body_id "
            "JOIN systems s ON s.system_address = r.system_address"
        ),
        "base_where": "r.name NOT LIKE '% Belt'",
        "display": [
            ("r.name",               "Ring"),
            ("b.name",               "Body"),
            ("s.name",               "System"),
            ("r.ring_class",         "Class"),
            ("r.inner_rad / 1000.0", "Inner (km)"),
            ("r.outer_rad / 1000.0", "Outer (km)"),
            ("r.mass_mt",            "Mass (MT)"),
            ("s.region",             "Region"),
        ],
        "fields": {
            "Ring name":         {"col": "r.name",               "type": "text"},
            "Body name":         {"col": "b.name",               "type": "text"},
            "System name":       {"col": "s.name",               "type": "text"},
            "Ring class":        {"col": "r.ring_class",         "type": "choice",
                                  "choices": [
                                      ["eRingClass_Rocky",    "Rocky"],
                                      ["eRingClass_MetalRich","Metal Rich"],
                                      ["eRingClass_Icy",      "Icy"],
                                      ["eRingClass_Metalic",  "Metallic"],
                                  ]},
            "Inner radius (km)": {"col": "r.inner_rad / 1000.0", "type": "number"},
            "Outer radius (km)": {"col": "r.outer_rad / 1000.0", "type": "number"},
            "Mass (MT)":         {"col": "r.mass_mt",            "type": "number"},
            "Region":            {"col": "s.region", "type": "choice", "choices": _REGION_CHOICES},
        },
    },
}

_LIMIT = 500

# ── Flask app ─────────────────────────────────────────────────────────────────


app = Flask(__name__)
_db_path: Path | None = None

_output_queue: queue.Queue = queue.Queue()
_task_running = threading.Event()


def _conn() -> sqlite3.Connection:
    return open_db(_db_path)


def _like_escape(val: str) -> str:
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _label_to_alias(label: str) -> str:
    alias = (
        label.lower()
        .replace(" ", "_")
        .replace("(", "").replace(")", "")
        .replace("/", "").replace("%", "pct")
        .replace(".", "_").replace("-", "_")
    )
    if alias and alias[0].isdigit():
        alias = "c_" + alias
    return alias


def _condition_sql(fdef: dict, op: str, val: str, val2: str
                   ) -> tuple[str, list[Any]] | None:
    """Return (sql_fragment, params) for one condition, or None to skip."""
    ftype = fdef["type"]

    if ftype == "exists":
        subq = fdef["subquery"]
        want = (op == "is" and val == "Yes") or (op == "is_not" and val == "No")
        prefix = "" if want else "NOT "
        return f"{prefix}EXISTS ({subq})", []

    if ftype == "parent_subtype":
        sym = "=" if op == "is" else "!="
        return (
            "EXISTS (SELECT 1 FROM bodies ps"
            " WHERE ps.system_address = b.system_address"
            f" AND ps.body_id = b.parent_star_id AND ps.subtype {sym} ?)"
        ), [val]

    if ftype == "datetime":
        col = fdef["col"]
        if not val:
            return None
        if op == "between":
            if not val2:
                return None
            return f"(date({col}) BETWEEN ? AND ?)", [val, val2]
        if op == "on":
            return f"date({col}) = ?", [val]
        sym = {"after": ">", "from": ">=", "before": "<", "until": "<="}.get(op, ">=")
        return f"{col} {sym} ?", [val]

    col = fdef["col"]
    if ftype == "choice":
        is_bool = col in _BOOL_COLS
        mapped: Any = (1 if val == "Yes" else 0) if is_bool else val
        sym = "=" if op == "is" else "!="
        return f"{col} {sym} ?", [mapped]
    if ftype == "number":
        try:
            v = float(val)
        except (ValueError, TypeError):
            return None
        if op == "between":
            try:
                v2 = float(val2)
            except (ValueError, TypeError):
                return None
            return f"({col} BETWEEN ? AND ?)", [v, v2]
        sym = {"=": "=", "!=": "!=", ">": ">", ">=": ">=",
               "<": "<", "<=": "<="}.get(op, "=")
        return f"{col} {sym} ?", [v]
    # text
    if op == "contains":
        return f"{col} LIKE ? ESCAPE '\\'", [f"%{_like_escape(val)}%"]
    if op == "starts_with":
        return f"{col} LIKE ? ESCAPE '\\'", [f"{_like_escape(val)}%"]
    if op == "ends_with":
        return f"{col} LIKE ? ESCAPE '\\'", [f"%{_like_escape(val)}"]
    if op == "!=":
        return f"{col} != ?", [val]
    return f"{col} = ?", [val]


def _build_combined_query(conditions: list[dict], logic: str
                          ) -> tuple[str, list[Any]]:
    entity_counts: dict[str, int] = {}
    for c in conditions:
        e = c.get("entity", "")
        f = c.get("field", "")
        v = str(c.get("value", "")).strip()
        if e in _SCHEMA and f in _SCHEMA[e].get("fields", {}) and v:
            entity_counts[e] = entity_counts.get(e, 0) + 1

    active: set[str] = set(entity_counts)
    if not active:
        mentioned = [c.get("entity", "") for c in conditions if c.get("entity", "") in _SCHEMA]
        primary = mentioned[0] if mentioned else "Systems"
        active = {primary}
    else:
        primary = max(entity_counts, key=entity_counts.__getitem__)

    has_planets = "Planets" in active
    has_stars   = "Stars"   in active
    has_bodies  = has_planets or has_stars
    has_organic = "Organic Scans" in active
    has_rings   = "Rings"   in active

    base_parts: list[str] = []

    if has_organic:
        from_clause = (
            "organic_scans os "
            "JOIN systems s ON s.system_address = os.system_address "
            "LEFT JOIN bodies b ON b.system_address = os.system_address "
            "  AND b.body_id = os.body_id"
        )
        if has_rings:
            from_clause += (
                " LEFT JOIN rings r ON r.system_address = b.system_address"
                " AND r.body_id = b.body_id"
            )
        base_parts.append("os.scan_state = 'Analyse'")
        if has_rings:
            base_parts.append("r.name NOT LIKE '% Belt'")

    elif has_rings and not has_bodies:
        from_clause = (
            "rings r "
            "JOIN bodies b ON b.system_address = r.system_address "
            "  AND b.body_id = r.body_id "
            "JOIN systems s ON s.system_address = r.system_address"
        )
        base_parts.append("r.name NOT LIKE '% Belt'")

    elif has_bodies:
        from_clause = (
            "bodies b "
            "JOIN systems s ON s.system_address = b.system_address"
        )
        if has_planets and not has_stars:
            base_parts.append("b.body_type = 'Planet'")
        elif has_stars and not has_planets:
            base_parts.append("b.body_type = 'Star'")
        else:
            base_parts.append("(b.body_type IN ('Planet', 'Star'))")
        if has_rings:
            from_clause += (
                " LEFT JOIN rings r ON r.system_address = b.system_address"
                " AND r.body_id = b.body_id"
            )
            base_parts.append("r.name NOT LIKE '% Belt'")

    else:
        from_clause = "systems s"

    user_parts: list[tuple[str, str]] = []  # (per-condition logic, sql fragment)
    user_params: list[Any] = []

    for c in conditions:
        e    = c.get("entity", "")
        f    = c.get("field", "")
        op   = c.get("op", "")
        val  = str(c.get("value",  "")).strip()
        val2 = str(c.get("value2", "")).strip()
        cond_logic = str(c.get("logic", logic)).upper()
        if cond_logic not in ("AND", "OR"):
            cond_logic = logic
        if e not in _SCHEMA or f not in _SCHEMA[e].get("fields", {}) or not val:
            continue
        result = _condition_sql(_SCHEMA[e]["fields"][f], op, val, val2)
        if result:
            user_parts.append((cond_logic, result[0]))
            user_params.extend(result[1])

    def _join_user(parts: list[tuple[str, str]]) -> str:
        tokens = [parts[0][1]]
        for op_str, frag in parts[1:]:
            tokens.extend([op_str, frag])
        return " ".join(tokens)

    if base_parts and user_parts:
        where = f" WHERE {' AND '.join(base_parts)} AND ({_join_user(user_parts)})"
    elif base_parts:
        where = f" WHERE {' AND '.join(base_parts)}"
    elif user_parts:
        where = f" WHERE {_join_user(user_parts)}"
    else:
        where = ""

    selects: list[str] = []
    seen_aliases: set[str] = set()

    for c in conditions:
        e = c.get("entity", "")
        f = c.get("field", "")
        if e not in _SCHEMA or f not in _SCHEMA[e].get("fields", {}):
            continue
        fdef  = _SCHEMA[e]["fields"][f]
        alias = _label_to_alias(f)
        if alias not in seen_aliases:
            if fdef["type"] == "exists":
                selects.append(f"EXISTS ({fdef['subquery']}) AS {alias}")
            elif fdef["type"] == "parent_subtype":
                selects.append(
                    "(SELECT ps.subtype FROM bodies ps"
                    " WHERE ps.system_address = b.system_address"
                    f" AND ps.body_id = b.parent_star_id) AS {alias}"
                )
            else:
                selects.append(f"{fdef['col']} AS {alias}")
            seen_aliases.add(alias)

    for expr, label in _SCHEMA[primary]["display"]:
        alias = _label_to_alias(label)
        if alias not in seen_aliases:
            selects.append(f"{expr} AS {alias}")
            seen_aliases.add(alias)

    if "_sa" not in seen_aliases:
        selects.append("s.system_address AS _sa")
        seen_aliases.add("_sa")

    sql = (
        f"SELECT {', '.join(selects)}"
        f" FROM {from_clause}"
        f"{where}"
        f" LIMIT {_LIMIT}"
    )
    return sql, user_params


def _inline_sql(sql: str, params: list[Any]) -> str:
    """Return the SQL string with ? placeholders replaced by their literal values."""
    parts: list[str] = []
    idx = 0
    for ch in sql:
        if ch == "?" and idx < len(params):
            v = params[idx]
            if v is None:
                parts.append("NULL")
            elif isinstance(v, str):
                parts.append("'" + v.replace("'", "''") + "'")
            else:
                parts.append(str(v))
            idx += 1
        else:
            parts.append(ch)
    return "".join(parts)


def _js_schema() -> str:
    out: dict[str, Any] = {}
    for entity, edef in _SCHEMA.items():
        out[entity] = {}
        for fname, fdef in edef["fields"].items():
            if fdef["type"] in ("exists",):
                out[entity][fname] = {"type": "choice", "choices": ["Yes", "No"]}
            elif fdef["type"] == "parent_subtype":
                out[entity][fname] = {"type": "choice", "choices": fdef["choices"]}
            elif fdef["type"] == "datetime":
                out[entity][fname] = {"type": "datetime"}
            else:
                out[entity][fname] = {k: v for k, v in fdef.items()
                                      if k in ("type", "choices")}
    return json.dumps(out)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.after_request
def _no_cache(response):
    if "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index() -> str:
    return render_template_string(_CONTROL_TEMPLATE, version=_VERSION)


@app.get("/query-builder")
def query_builder() -> str:
    return render_template_string(
        _TEMPLATE,
        schema_json=_js_schema(),
        entity_names=json.dumps(list(_SCHEMA.keys())),
        limit=_LIMIT,
        version=_VERSION,
    )


@app.post("/query")
def run_query():
    data = request.get_json(force=True) or {}
    conditions = data.get("conditions", [])
    logic = data.get("logic", "AND")
    if logic not in ("AND", "OR"):
        logic = "AND"

    try:
        sql, params = _build_combined_query(conditions, logic)
        conn = _conn()
        try:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            columns = [d[0] for d in (cursor.description or [])]
            return jsonify({
                "count":   len(rows),
                "columns": columns,
                "rows":    [list(r) for r in rows],
                "sql":     _inline_sql(sql, params),
            })
        finally:
            conn.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/query_raw")
def run_query_raw():
    data = request.get_json(force=True) or {}
    sql = (data.get("sql") or "").strip()
    if not sql:
        return jsonify({"error": "No SQL provided."}), 400
    first_word = sql.split()[0].upper() if sql.split() else ""
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        return jsonify({"error": "Only SELECT / WITH / EXPLAIN queries are allowed."}), 400
    try:
        conn = _conn()
        try:
            cursor = conn.execute(sql)
            rows = cursor.fetchmany(_LIMIT)
            columns = [d[0] for d in (cursor.description or [])]
            return jsonify({
                "count":   len(rows),
                "columns": columns,
                "rows":    [list(r) for r in rows],
                "sql":     sql,
            })
        finally:
            conn.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/system_data")
def get_system_data():
    sa_str = request.args.get("sa", "").strip()
    try:
        sa_int = int(sa_str)
    except (ValueError, TypeError):
        return jsonify(None)
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT system_address, name, star_class, x, z, first_seen_at"
            " FROM systems WHERE system_address = ?", (sa_int,)
        ).fetchone()
        if not row:
            return jsonify(None)
        fv = row[5][:10] if row[5] else None
        result: dict[str, Any] = {
            "name": row[1], "sc": row[2] or "", "x": row[3], "z": row[4],
            "fv": fv, "bodies": []
        }
        for r in conn.execute("""
            SELECT b.body_id, b.name, b.body_type, b.subtype,
                   b.distance_ls, b.bio_signals, b.geo_signals,
                   b.was_mapped, b.first_discovered, b.radius_km,
                   b.surface_temp_k, b.is_landable, b.terraform_state,
                   b.orbital_parent_id, b.parent_star_id,
                   (SELECT COUNT(*) FROM rings r
                    WHERE r.system_address = b.system_address
                      AND r.body_id = b.body_id
                      AND r.name NOT LIKE '% Belt') AS ring_count
            FROM bodies b
            WHERE b.system_address = ?
            ORDER BY COALESCE(b.distance_ls, 99999)
        """, (sa_int,)).fetchall():
            tf = (r[12] or "").strip().lower()
            result["bodies"].append({
                "i": r[0], "n": r[1], "t": r[2], "s": r[3] or "",
                "d": round(r[4], 2) if r[4] is not None else None,
                "b": r[5] or 0, "g": r[6] or 0,
                "w": r[7] or 0, "f": r[8] or 0,
                "r": round(r[9]) if r[9] else None,
                "k": round(r[10]) if r[10] else None,
                "l": r[11] or 0,
                "e": 1 if tf and tf not in ("", "not terraformable") else 0,
                "p": r[13], "q": r[14], "ri": r[15] or 0,
            })
        sp_map: dict[int, list] = {}
        for r in conn.execute(
            "SELECT body_id, species_localised FROM organic_scans"
            " WHERE system_address = ? AND scan_state = 'Analyse'"
            "   AND species_localised IS NOT NULL"
            " ORDER BY body_id, species_localised", (sa_int,)
        ).fetchall():
            sp_map.setdefault(r[0], [])
            if r[1] not in sp_map[r[0]]:
                sp_map[r[0]].append(r[1])
        for body in result["bodies"]:
            sp = sp_map.get(body["i"])
            if sp:
                body["sp"] = sp
        return jsonify(result)
    finally:
        conn.close()


# ── Commander API ─────────────────────────────────────────────────────────────

@app.get("/api/commanders")
def api_commanders():
    commanders = list_commanders()
    active = get_active_commander()
    return jsonify({"commanders": commanders, "active": active})


@app.get("/api/ui-state")
def api_get_ui_state():
    return jsonify(get_ui_state())


@app.post("/api/ui-state")
def api_set_ui_state():
    data = request.get_json(force=True) or {}
    if data:
        set_ui_state(data)
    return jsonify({"ok": True})


@app.post("/api/commanders/active")
def api_set_active():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    set_active_commander(name)
    return jsonify({"ok": True, "active": name})


# ── Task runner (subprocess → SSE) ────────────────────────────────────────────

_TASK_FUNCS = {
    "import":    "cmd_import",
    "dashboard": "cmd_dashboard",
    "stratum":   "cmd_stratum",
    "charts":    "cmd_charts",
    "trip":      "cmd_trip",
}


@app.post("/api/tasks/run")
def api_run_task():
    if _task_running.is_set():
        return jsonify({"error": "A task is already running"}), 409

    data = request.get_json(force=True) or {}
    task = data.get("task", "")
    task_args: list[str] = data.get("args", [])

    if task not in _TASK_FUNCS:
        return jsonify({"error": f"Unknown task: {task!r}"}), 400

    func_name = _TASK_FUNCS[task]

    def _run() -> None:
        _task_running.set()
        while not _output_queue.empty():
            try:
                _output_queue.get_nowait()
            except queue.Empty:
                break
        code = (
            f"from edda.cli import {func_name}; "
            f"{func_name}({task_args!r})"
        )
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", code],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(Path.cwd()),
            )
            for line in proc.stdout:
                _output_queue.put(line.rstrip("\n"))
            proc.wait()
        except Exception as exc:
            _output_queue.put(f"ERROR: {exc}")
        finally:
            _output_queue.put("__DONE__")
            _task_running.clear()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/tasks/stream")
def api_task_stream():
    @stream_with_context
    def _generate():
        while True:
            try:
                msg = _output_queue.get(timeout=25)
                if msg == "__DONE__":
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    return
                yield f"data: {json.dumps({'line': msg})}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'ping': True})}\n\n"

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Control panel template ────────────────────────────────────────────────────

_CONTROL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EDDA Control Panel</title>
<style>
:root{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--green:#3fb950;--orange:#f0883e;--red:#f85149}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;min-height:100vh}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;justify-content:space-between}
.logo{font-size:17px;font-weight:700;letter-spacing:.5px;color:var(--accent)}
.logo span{color:var(--muted);font-weight:400;font-size:12px;margin-left:8px}
nav a{color:var(--muted);text-decoration:none;margin-left:18px;font-size:13px}
nav a:hover{color:var(--accent)}
.container{max-width:860px;margin:24px auto;padding:0 20px;display:grid;gap:18px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px}
.card h2{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.9px;color:var(--muted);margin-bottom:14px}
.cmdr-row{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:6px}
.cmdr-row:hover{background:rgba(88,166,255,.06)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--border);flex-shrink:0}
.dot.on{background:var(--green)}
.cmdr-name{flex:1}
.cmdr-name.on{color:var(--green);font-weight:600}
.badge{font-size:11px;color:var(--muted)}
.no-cmdrs{color:var(--muted);font-style:italic;font-size:13px;padding:4px 10px}
.tasks-row{display:flex;flex-wrap:wrap;gap:10px}
.tbtn{background:#21262d;border:1px solid var(--border);color:var(--text);padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;transition:border-color .15s,background .15s}
.tbtn:hover{border-color:var(--accent);background:rgba(88,166,255,.09);color:var(--accent)}
.tbtn.active{border-color:var(--accent);color:var(--accent)}
.tbtn:disabled{opacity:.4;cursor:not-allowed}
.opts{display:none;margin-top:16px;border-top:1px solid var(--border);padding-top:16px}
.opts.open{display:block}
.opts-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px;margin-bottom:14px}
.fg{display:flex;flex-direction:column;gap:5px}
.fg label{font-size:12px;color:var(--muted)}
.fg input[type=text]{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px 9px;border-radius:4px;font-size:13px;width:100%}
.fg input[type=text]:focus{outline:none;border-color:var(--accent)}
.ck{display:flex;align-items:center;gap:7px;margin-top:2px}
.ck input{accent-color:var(--accent)}
.run-btn{background:var(--accent);border:none;color:#0d1117;padding:7px 22px;border-radius:6px;cursor:pointer;font-weight:600;font-size:13px}
.run-btn:hover{opacity:.85}
.con-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.con-hdr h2{margin-bottom:0}
.clr-btn{background:none;border:1px solid var(--border);color:var(--muted);padding:3px 10px;border-radius:4px;cursor:pointer;font-size:12px}
.clr-btn:hover{border-color:var(--red);color:var(--red)}
#con{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:12px;height:300px;overflow-y:auto;font-family:'Cascadia Code','Consolas',monospace;font-size:12px;line-height:1.6}
.ln{white-space:pre-wrap;word-break:break-all}
.ln.e{color:var(--red)}
.ln.ok{color:var(--green)}
#sdot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--muted);margin-right:6px;vertical-align:middle}
#sdot.run{background:var(--orange);animation:pulse 1s infinite}
#sdot.done{background:var(--green)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.sw-btn{background:none;border:1px solid var(--border);color:var(--muted);padding:3px 11px;border-radius:4px;cursor:pointer;font-size:12px}
.sw-btn:hover{border-color:var(--accent);color:var(--accent)}
</style>
</head>
<body>
<header>
  <div class="logo">EDDA <span>v{{ version }}</span></div>
  <nav>
    <a href="/query-builder">Query Builder &rarr;</a>
  </nav>
</header>
<div class="container">

  <div class="card">
    <h2>Commander</h2>
    <div id="cmdr-list"><span class="no-cmdrs">Loading&hellip;</span></div>
  </div>

  <div class="card">
    <h2>Tasks</h2>
    <div class="tasks-row">
      <button class="tbtn" id="tbtn-import"    onclick="toggleOpts('import')">&#128190; Import Journals</button>
      <button class="tbtn" id="tbtn-dashboard" onclick="toggleOpts('dashboard')">&#128202; Build Dashboard</button>
      <button class="tbtn" id="tbtn-stratum"   onclick="toggleOpts('stratum')">&#127758; Stratum Report</button>
      <button class="tbtn" id="tbtn-charts"    onclick="toggleOpts('charts')">&#128200; Build Charts</button>
      <button class="tbtn" id="tbtn-trip"      onclick="toggleOpts('trip')">&#128345; Trip Report</button>
    </div>

    <div id="opts-import" class="opts">
      <div class="opts-grid">
        <div class="fg"><label>Journal directory</label><input type="text" id="i-jdir" placeholder="(default: ED saved games)"></div>
        <div class="fg"><div class="ck"><input type="checkbox" id="i-force"><label for="i-force">Force re-import all files</label></div></div>
      </div>
      <button class="run-btn" onclick="runTask('import')">Run Import</button>
    </div>

    <div id="opts-dashboard" class="opts">
      <div class="opts-grid">
        <div class="fg"><label>Output file</label><input type="text" id="d-out" value="dashboard.html"></div>
      </div>
      <button class="run-btn" onclick="runTask('dashboard')">Build Dashboard</button>
    </div>

    <div id="opts-stratum" class="opts">
      <div class="opts-grid">
        <div class="fg"><label>Min temperature (K)</label><input type="text" id="s-min" value="165"></div>
        <div class="fg"><label>Max temperature (K)</label><input type="text" id="s-max" placeholder="(no limit)"></div>
        <div class="fg"><label>Output file</label><input type="text" id="s-out" value="stratum_report.html"></div>
      </div>
      <button class="run-btn" onclick="runTask('stratum')">Build Report</button>
    </div>

    <div id="opts-charts" class="opts">
      <div class="opts-grid">
        <div class="fg"><label>Output directory</label><input type="text" id="c-out" value="output"></div>
      </div>
      <button class="run-btn" onclick="runTask('charts')">Build Charts</button>
    </div>

    <div id="opts-trip" class="opts">
      <div class="opts-grid">
        <div class="fg"><label>From (YYYY-MM-DD or YYYY-MM-DD HH:MM)</label><input type="text" id="t-from" placeholder="e.g. 2026-01-01"></div>
        <div class="fg"><label>To (YYYY-MM-DD or YYYY-MM-DD HH:MM)</label><input type="text" id="t-to" placeholder="e.g. 2026-06-08"></div>
        <div class="fg"><label>HTML output file (optional)</label><input type="text" id="t-out" placeholder="trip_report.html"></div>
        <div class="fg"><div class="ck"><input type="checkbox" id="t-systems"><label for="t-systems">List all systems visited</label></div></div>
      </div>
      <button class="run-btn" onclick="runTask('trip')">Build Trip Report</button>
    </div>
  </div>

  <div class="card">
    <div class="con-hdr">
      <h2><span id="sdot"></span>Output</h2>
      <button class="clr-btn" onclick="clearCon()">Clear</button>
    </div>
    <div id="con"></div>
  </div>

</div>
<script>
var _es=null, _openTask=null;

function toggleOpts(t){
  ['import','dashboard','stratum','charts','trip'].forEach(function(n){
    var el=document.getElementById('opts-'+n);
    var btn=document.getElementById('tbtn-'+n);
    if(n===t){
      var open=el.classList.toggle('open');
      btn.classList.toggle('active',open);
      _openTask=open?t:null;
    } else {
      el.classList.remove('open');
      btn.classList.remove('active');
    }
  });
}

function buildArgs(t){
  var a=[];
  if(t==='import'){
    var jd=document.getElementById('i-jdir').value.trim();
    if(jd){a.push('--journal-dir');a.push(jd);}
    if(document.getElementById('i-force').checked)a.push('--force');
  } else if(t==='dashboard'){
    var o=document.getElementById('d-out').value.trim();
    if(o){a.push('--out');a.push(o);}
  } else if(t==='stratum'){
    var mn=document.getElementById('s-min').value.trim();
    var mx=document.getElementById('s-max').value.trim();
    var o=document.getElementById('s-out').value.trim();
    if(mn){a.push('--min-temp');a.push(mn);}
    if(mx){a.push('--max-temp');a.push(mx);}
    if(o){a.push('--out');a.push(o);}
  } else if(t==='charts'){
    var o=document.getElementById('c-out').value.trim();
    if(o){a.push('--out');a.push(o);}
  } else if(t==='trip'){
    var fr=document.getElementById('t-from').value.trim();
    var to=document.getElementById('t-to').value.trim();
    var o=document.getElementById('t-out').value.trim();
    if(!fr||!to){alert('Trip report requires both From and To dates.');return null;}
    a.push('--from');a.push(fr);
    a.push('--to');a.push(to);
    if(o){a.push('--html');a.push(o);}
    if(document.getElementById('t-systems').checked)a.push('--systems');
  }
  return a;
}

function addLine(txt,cls){
  var c=document.getElementById('con');
  var d=document.createElement('div');
  d.className='ln'+(cls?' '+cls:'');
  d.textContent=txt;
  c.appendChild(d);
  c.scrollTop=c.scrollHeight;
}

function clearCon(){
  document.getElementById('con').innerHTML='';
  document.getElementById('sdot').className='';
}

function setBusy(busy){
  document.querySelectorAll('.tbtn,.run-btn').forEach(function(b){b.disabled=busy;});
}

function runTask(t){
  if(_es){_es.close();_es=null;}
  var args=buildArgs(t);
  if(args===null)return;
  setBusy(true);
  document.getElementById('sdot').className='run';
  addLine('> '+t+(args.length?' '+args.join(' '):''));

  _es=new EventSource('/api/tasks/stream');
  _es.onmessage=function(e){
    var d=JSON.parse(e.data);
    if(d.done){
      addLine('> Done.','ok');
      document.getElementById('sdot').className='done';
      setBusy(false);
      _es.close();_es=null;
    } else if(d.line!==undefined){
      var c=(/^(ERROR|Traceback|Warning)/.test(d.line))?'e':'';
      addLine(d.line,c);
    }
  };
  _es.onerror=function(){
    addLine('> Connection lost.','e');
    document.getElementById('sdot').className='';
    setBusy(false);
    if(_es){_es.close();_es=null;}
  };

  fetch('/api/tasks/run',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({task:t,args:args})
  }).then(function(r){return r.json();}).then(function(d){
    if(d.error){addLine('> Error: '+d.error,'e');setBusy(false);if(_es){_es.close();_es=null;}}
  });
}

function loadCmdrs(){
  fetch('/api/commanders').then(function(r){return r.json();}).then(function(d){
    var el=document.getElementById('cmdr-list');
    if(!d.commanders||!d.commanders.length){
      el.innerHTML='<span class="no-cmdrs">No commanders found — run Import to auto-detect from journal files.</span>';
      return;
    }
    el.innerHTML=d.commanders.map(function(n){
      var on=n===d.active;
      return '<div class="cmdr-row">'
        +'<div class="dot'+(on?' on':'')+'"></div>'
        +'<div class="cmdr-name'+(on?' on':'')+'">'+esc(n)
        +(on?' <span class="badge">(active)</span>':'')+'</div>'
        +(on?'':'<button class="sw-btn" data-n="'+esc(n)+'" onclick="switchCmdr(this)">Switch</button>')
        +'</div>';
    }).join('');
  });
}

function switchCmdr(btn){
  var n=btn.dataset.n;
  fetch('/api/commanders/active',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:n})
  }).then(function(){loadCmdrs();});
}

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

loadCmdrs();

// Persist trip dates in .edda/config.json via the server.
(function(){
  var fields=['t-from','t-to'];
  fetch('/api/ui-state').then(function(r){return r.json();}).then(function(d){
    if(d['trip-from'])document.getElementById('t-from').value=d['trip-from'];
    if(d['trip-to'])  document.getElementById('t-to').value=d['trip-to'];
  });
  fields.forEach(function(id){
    document.getElementById(id).addEventListener('change',function(){
      var update={};
      update['trip-from']=document.getElementById('t-from').value;
      update['trip-to']=document.getElementById('t-to').value;
      fetch('/api/ui-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(update)});
    });
  });
}());
</script>
</body>
</html>"""


# ── Query-builder template ─────────────────────────────────────────────────────

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>EDDA Query Builder</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d0f;color:#c8c8c8;font-family:"Consolas","Courier New",monospace;font-size:13px;min-height:100vh}
header{background:#1a1a20;border-bottom:1px solid #2e2e3a;padding:10px 18px;display:flex;align-items:center;gap:12px}
header h1{font-size:14px;color:#e07820;letter-spacing:2px;text-transform:uppercase}
header .sub{color:#555;font-size:11px;margin-left:auto}
.builder{padding:16px 18px;max-width:1280px}
.mode-tabs{display:flex;gap:0;margin-bottom:14px;border-bottom:1px solid #2e2e3a}
.mode-tab{background:none;border:none;border-bottom:2px solid transparent;color:#666;padding:7px 16px;cursor:pointer;font-family:inherit;font-size:12px;letter-spacing:.5px;margin-bottom:-1px;transition:color .15s,border-color .15s}
.mode-tab.active{color:#e07820;border-bottom-color:#e07820}
.mode-tab:hover:not(.active){color:#aaa}
.entity-row{display:flex;align-items:center;gap:8px;margin-bottom:14px;flex-wrap:wrap}
.entity-row label{color:#666;font-size:11px;text-transform:uppercase;letter-spacing:1px}
.entity-btn{background:#1c1c24;border:1px solid #2e2e3a;color:#999;padding:5px 14px;cursor:pointer;border-radius:2px;font-family:inherit;font-size:12px;transition:border-color .15s,color .15s}
.entity-btn:hover{border-color:#e07820;color:#e07820}
.entity-btn.active{background:#2a1e10;border-color:#e07820;color:#e07820}
.conditions-wrap{background:#111118;border:1px solid #242430;border-radius:3px;padding:12px 14px;margin-bottom:12px}
.conditions-hdr{color:#555;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
.condition-row{display:flex;align-items:center;gap:6px;margin-bottom:4px;flex-wrap:wrap}
.logic-pill{background:#1a1a24;border:1px solid #333;color:#777;font-size:10px;padding:2px 9px;border-radius:10px;letter-spacing:1px;cursor:pointer;user-select:none;margin:3px 2px;transition:background .15s,border-color .15s,color .15s}
.logic-pill:hover,.logic-pill.active{background:#1a2a1a;border-color:#4c8;color:#4c8}
.logic-pill.or,.logic-pill.or:hover{background:#2a1a10;border-color:#e07820;color:#e07820}
select,input[type=text],input[type=number]{background:#181820;border:1px solid #2e2e3a;color:#ccc;padding:4px 8px;border-radius:2px;font-family:inherit;font-size:12px;outline:none;transition:border-color .15s}
select:focus,input:focus{border-color:#e07820}
.ent-sel{min-width:110px}
.field-sel{min-width:155px}
.op-sel{min-width:100px}
.val1,.val2{width:128px}
.between-sep{color:#555;padding:0 2px}
.rm-btn{background:none;border:1px solid #2e2e3a;color:#555;cursor:pointer;padding:3px 9px;border-radius:2px;font-size:13px;line-height:1;transition:border-color .15s,color .15s}
.rm-btn:hover{border-color:#b44;color:#c55}
.action-row{display:flex;align-items:center;gap:8px;margin-top:10px;flex-wrap:wrap}
.btn{background:#1c1c24;border:1px solid #333;color:#aaa;padding:5px 14px;cursor:pointer;border-radius:2px;font-family:inherit;font-size:12px;transition:border-color .15s,color .15s}
.btn:hover{border-color:#888;color:#fff}
.btn-run{background:#2a1e10;border-color:#c06010;color:#e07820;font-weight:bold;letter-spacing:.5px}
.btn-run:hover{background:#3a2818;border-color:#e07820}
.logic-toggle{display:flex;border:1px solid #2e2e3a;border-radius:2px;overflow:hidden}
.logic-toggle button{background:#181820;border:none;color:#666;padding:5px 11px;cursor:pointer;font-family:inherit;font-size:11px;letter-spacing:1px;transition:background .15s,color .15s}
.logic-toggle button.active{background:#1a2a1a;color:#4c8}
.logic-toggle button:hover{color:#ccc}
.raw-panel{background:#111118;border:1px solid #242430;border-radius:3px;padding:12px 14px;margin-bottom:12px}
#raw-input{width:100%;height:110px;background:#181820;border:1px solid #2e2e3a;color:#ccc;padding:8px 10px;border-radius:2px;font-family:"Consolas","Courier New",monospace;font-size:12px;resize:vertical;outline:none;line-height:1.5;transition:border-color .15s}
#raw-input:focus{border-color:#e07820}
.hist-wrap{margin-bottom:12px}
.hist-hdr{display:flex;align-items:center;gap:7px;padding:5px 2px;cursor:pointer;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:1px;user-select:none;border-bottom:1px solid #1e1e28}
.hist-hdr:hover{color:#888}
.hist-badge{background:#1e1820;border:1px solid #2e2030;border-radius:10px;color:#806050;font-size:10px;padding:0 6px;min-width:18px;text-align:center}
.hist-chevron{margin-left:auto;color:#3a3a50;transition:transform .2s}
.hist-hdr.open .hist-chevron{transform:rotate(180deg)}
.hist-clear-btn{background:none;border:none;color:#3a3040;cursor:pointer;font-family:inherit;font-size:10px;padding:0;letter-spacing:.5px;margin-right:4px}
.hist-clear-btn:hover{color:#a44}
.hist-body{display:none;padding-top:4px}
.hist-body.open{display:block}
.hist-entry{display:flex;align-items:center;gap:5px;padding:3px 2px;border-bottom:1px solid #131318}
.hist-entry:hover{background:#0e0e16}
.hist-time{color:#383848;font-size:10px;white-space:nowrap;min-width:58px}
.hist-sql{flex:1;color:#484860;font-size:11px;font-family:"Consolas","Courier New",monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:default}
.hist-btn{background:none;border:1px solid #222230;color:#3a4a3a;cursor:pointer;padding:1px 7px;border-radius:2px;font-size:11px;font-family:inherit;transition:border-color .15s,color .15s}
.hist-btn:hover{border-color:#4a8;color:#6ca}
.hist-btn-edit{color:#3a3a50}
.hist-btn-edit:hover{border-color:#668;color:#99b}
.hist-del{background:none;border:1px solid #222230;color:#302838;cursor:pointer;padding:1px 7px;border-radius:2px;font-size:12px;line-height:1;transition:border-color .15s,color .15s}
.hist-del:hover{border-color:#844;color:#a55}
.results-section{margin-top:16px}
.results-meta{font-size:11px;color:#666;margin-bottom:6px;display:flex;align-items:center;gap:10px}
.results-meta .count{color:#e07820;font-weight:bold}
.results-meta .limit-note{color:#888}
.btn-copy{background:none;border:1px solid #2e2e3a;color:#555;padding:2px 8px;cursor:pointer;border-radius:2px;font-family:inherit;font-size:11px;margin-left:auto}
.btn-copy:hover{border-color:#888;color:#aaa}
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#181820;color:#c07030;text-align:left;padding:5px 10px;border-bottom:1px solid #242430;cursor:pointer;white-space:nowrap;user-select:none;position:sticky;top:0}
th:hover{background:#1e1e2a}
th .arr{color:#444;margin-left:3px;font-size:10px}
th.asc .arr::after{content:"▲";color:#e07820}
th.desc .arr::after{content:"▼";color:#e07820}
th:not(.asc):not(.desc) .arr::after{content:"⇅"}
td{padding:4px 10px;border-bottom:1px solid #191920;white-space:nowrap;max-width:300px;overflow:hidden;text-overflow:ellipsis}
tr:hover td{background:#141420}
.num{text-align:right;font-variant-numeric:tabular-nums}
.nil{color:#333}
.sql-box{margin-top:8px;font-size:10px;color:#3a3a50;word-break:break-all;padding:4px 0}
.err{color:#c55;padding:8px 10px;background:#180e0e;border:1px solid #422;border-radius:2px}
.empty{color:#555;padding:16px;text-align:center}
.sys-modal{display:none;position:fixed;inset:0;z-index:500;align-items:center;justify-content:center;padding:20px}
.sys-modal.open{display:flex}
.sys-modal-bg{position:absolute;inset:0;background:rgba(0,0,0,0.72)}
.sys-modal-box{position:relative;background:#0b0b1e;border:1px solid #2a2a55;border-radius:8px;width:fit-content;max-width:95vw;box-shadow:0 0 80px rgba(30,30,120,0.5);overflow:hidden}
.sys-modal-hdr{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #1e1e44;background:#0d0d22}
.sys-modal-ttl{font-size:1em;color:#88aaff;font-weight:600}
.sys-modal-sc{font-size:0.8em;color:#6677aa}
.sys-modal-ftr{border-top:1px solid #1e1e44;background:#0d0d22;padding:6px 12px;display:flex;align-items:center;gap:10px}
#gal-canvas,#sys-legend-canvas{display:block;border:1px solid #1e1e44;border-radius:3px}
.sys-modal-close{margin-left:auto;background:none;border:none;color:#6677aa;cursor:pointer;font-size:1.2em;line-height:1;padding:2px 6px;border-radius:3px;transition:color .1s,background .1s}
.sys-modal-close:hover{color:#ee8866;background:rgba(255,100,50,0.1)}
#sys-canvas{display:block;height:auto;cursor:crosshair}
.sys-tip{position:fixed;background:rgba(8,8,24,0.96);border:1px solid #2a2a55;border-radius:4px;padding:8px 11px;font-size:0.78em;color:#ccd;pointer-events:none;display:none;max-width:260px;line-height:1.65;white-space:nowrap;z-index:600}
.sys-tip.visible{display:block}
.sys-link{cursor:pointer;color:#88aaff;text-decoration:underline;text-decoration-style:dotted;text-underline-offset:2px}
.sys-link:hover{color:#bbddff}
</style>
</head>
<body>
<header>
  <h1>EDDA &middot; Query Builder</h1>
  <span class="sub">Elite Dangerous Data Analyser</span>
  <span class="sub" style="margin-left:0">v""" + "{{ version }}" + r"""</span>
</header>
<div class="builder">

  <div class="mode-tabs">
    <button class="mode-tab active" data-mode="builder" onclick="setMode('builder')">Builder</button>
    <button class="mode-tab" data-mode="raw" onclick="setMode('raw')">Raw SQL</button>
  </div>

  <!-- ── Builder panel ── -->
  <div id="panel-builder">
    <div class="entity-row">
      <label>Default entity:</label>
      <div id="ent-btns"></div>
    </div>
    <div class="conditions-wrap">
      <div class="conditions-hdr">Conditions</div>
      <div id="cond-list"></div>
      <div class="action-row">
        <button class="btn" onclick="addRow()">+ Add condition</button>
        <div class="logic-toggle" title="Logical operator between conditions">
          <button id="btn-and" class="active" onclick="setLogic('AND')">AND</button>
          <button id="btn-or"  onclick="setLogic('OR')">OR</button>
        </div>
        <button class="btn btn-run" onclick="runQuery()">&#9654;&nbsp;Run</button>
      </div>
    </div>
  </div>

  <!-- ── Raw SQL panel ── -->
  <div id="panel-raw" style="display:none">
    <div class="raw-panel">
      <textarea id="raw-input" spellcheck="false"
        placeholder="SELECT s.name, s.star_class, s.x, s.y, s.z&#10;FROM systems s&#10;WHERE s.star_class = &#39;G&#39;&#10;LIMIT 100"></textarea>
      <div class="action-row" style="margin-top:8px">
        <button class="btn btn-run" onclick="runRaw()">&#9654;&nbsp;Run SQL</button>
        <button class="btn" onclick="document.getElementById('raw-input').value=''">Clear</button>
      </div>
    </div>
  </div>

  <!-- ── History ── -->
  <div class="hist-wrap">
    <div class="hist-hdr" id="hist-hdr" onclick="toggleHistory()">
      History
      <span class="hist-badge" id="hist-count">0</span>
      <button class="hist-clear-btn" onclick="event.stopPropagation();clearHistory()" title="Remove all history entries">clear all</button>
      <span class="hist-chevron">&#9660;</span>
    </div>
    <div class="hist-body" id="hist-body">
      <div style="color:#333;padding:6px 2px;font-size:11px">No history yet.</div>
    </div>
  </div>

  <!-- ── Results ── -->
  <div id="results" style="display:none" class="results-section">
    <div class="results-meta" id="rmeta"></div>
    <div class="tbl-wrap" id="rtbl"></div>
    <div class="sql-box" id="rsql"></div>
  </div>

</div>

<div id="sys-modal" class="sys-modal">
  <div class="sys-modal-bg" id="sys-modal-bg"></div>
  <div class="sys-modal-box">
    <div class="sys-modal-hdr">
      <span id="sys-modal-ttl" class="sys-modal-ttl">&#8211;</span>
      <span id="sys-modal-sc"  class="sys-modal-sc"></span>
      <button class="sys-modal-close" id="sys-modal-close">&#x2715;</button>
    </div>
    <div id="sys-canvas-wrap" style="position:relative;overflow-y:auto;max-height:calc(92vh - 160px);overflow-x:auto">
      <canvas id="sys-canvas" width="700" height="460"></canvas>
      <div id="sys-tip" class="sys-tip"></div>
    </div>
    <div class="sys-modal-ftr">
      <canvas id="sys-legend-canvas" width="224" height="130"></canvas>
      <canvas id="gal-canvas" width="280" height="130"></canvas>
    </div>
  </div>
</div>

<script>
const SCHEMA =""" + "{{ schema_json | safe }}" + r""";
const ENAMES = """ + "{{ entity_names | safe }}" + r""";
const LIMIT  = """ + "{{ limit }}" + r""";

const OPS_NUM    = [{v:"=",l:"="},{v:"!=",l:"≠"},{v:">",l:">"},{v:">=",l:"≥"},{v:"<",l:"<"},{v:"<=",l:"≤"},{v:"between",l:"between"}];
const OPS_TEXT   = [{v:"=",l:"="},{v:"!=",l:"≠"},{v:"contains",l:"contains"},{v:"starts_with",l:"starts with"},{v:"ends_with",l:"ends with"}];
const OPS_CHOICE = [{v:"is",l:"is"},{v:"is_not",l:"is not"}];
const OPS_DATE   = [{v:"on",l:"on"},{v:"from",l:"from (≥)"},{v:"until",l:"until (≤)"},{v:"after",l:"after (>)"},{v:"before",l:"before (<)"},{v:"between",l:"between"}];

let curEntity = ENAMES[0];
let logic = "AND";
let seq = 0;
let lastResults = null;

// ── Mode switching ────────────────────────────────────────────────────────────
function setMode(m) {
  document.querySelectorAll(".mode-tab").forEach(t =>
    t.classList.toggle("active", t.dataset.mode === m));
  document.getElementById("panel-builder").style.display = m === "builder" ? "" : "none";
  document.getElementById("panel-raw").style.display     = m === "raw"     ? "" : "none";
}

// ── History (localStorage) ────────────────────────────────────────────────────
const H_KEY = "edda_qb_history";
const H_MAX = 50;

function hLoad() {
  try { return JSON.parse(localStorage.getItem(H_KEY) || "[]"); } catch { return []; }
}
function hSave(arr) { localStorage.setItem(H_KEY, JSON.stringify(arr.slice(0, H_MAX))); }

function hAdd(sql) {
  let h = hLoad();
  h = h.filter(e => e.sql !== sql);
  h.unshift({ ts: Date.now(), sql });
  hSave(h);
  renderHistory();
}

function clearHistory() {
  hSave([]);
  renderHistory();
}

function hDel(i) {
  const h = hLoad(); h.splice(i, 1); hSave(h); renderHistory();
}

function hRun(i) {
  const h = hLoad();
  if (h[i]) execRaw(h[i].sql);
}

function hEdit(i) {
  const h = hLoad();
  if (!h[i]) return;
  document.getElementById("raw-input").value = h[i].sql;
  setMode("raw");
}

function toggleHistory() {
  const hdr  = document.getElementById("hist-hdr");
  const body = document.getElementById("hist-body");
  const open = hdr.classList.toggle("open");
  body.classList.toggle("open", open);
}

function esc(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function renderHistory() {
  const h = hLoad();
  document.getElementById("hist-count").textContent = h.length;
  const body = document.getElementById("hist-body");
  if (h.length === 0) {
    body.innerHTML = '<div style="color:#333;padding:6px 2px;font-size:11px">No history yet.</div>';
    return;
  }
  const now = new Date();
  body.innerHTML = h.map((e, i) => {
    const d = new Date(e.ts);
    const sameDay = d.toDateString() === now.toDateString();
    const ts = sameDay
      ? d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})
      : d.toLocaleDateString([], {day:"2-digit", month:"2-digit"}) + " "
        + d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
    const preview = esc(e.sql.replace(/\s+/g, " ").slice(0, 100));
    return '<div class="hist-entry">'
      + '<span class="hist-time">' + ts + '</span>'
      + '<span class="hist-sql" title="' + esc(e.sql) + '">' + preview + '</span>'
      + '<button class="hist-btn" onclick="hRun(' + i + ')" title="Run this query">&#9654;</button>'
      + '<button class="hist-btn hist-btn-edit" onclick="hEdit(' + i + ')" title="Load into Raw SQL editor">Edit</button>'
      + '<button class="hist-del" onclick="hDel(' + i + ')" title="Remove">&times;</button>'
      + '</div>';
  }).join("");
}

// ── Entity / condition builder ────────────────────────────────────────────────
function buildEntBtns() {
  const wrap = document.getElementById("ent-btns");
  wrap.innerHTML = "";
  for (const e of ENAMES) {
    const b = document.createElement("button");
    b.className = "entity-btn" + (e === curEntity ? " active" : "");
    b.textContent = e;
    b.onclick = () => selectEntity(e);
    wrap.appendChild(b);
  }
}

function selectEntity(name) {
  curEntity = name;
  document.querySelectorAll(".entity-btn").forEach(b =>
    b.classList.toggle("active", b.textContent === name));
}

function setLogic(l) {
  logic = l;
  document.getElementById("btn-and").classList.toggle("active", l === "AND");
  document.getElementById("btn-or").classList.toggle("active",  l === "OR");
}

function addRow() {
  const list = document.getElementById("cond-list");
  const existing = list.querySelectorAll(".condition-row");

  if (existing.length > 0) {
    const pill = document.createElement("div");
    pill.className = "logic-pill active" + (logic === "OR" ? " or" : "");
    pill.textContent = logic;
    pill.onclick = () => {
      const toOr = pill.textContent === "AND";
      pill.textContent = toOr ? "OR" : "AND";
      pill.classList.toggle("or", toOr);
    };
    list.appendChild(pill);
  }

  const row = document.createElement("div");
  row.className = "condition-row";
  row.dataset.id = seq++;

  const es = document.createElement("select"); es.className = "ent-sel";
  for (const e of ENAMES) {
    const o = document.createElement("option");
    o.value = o.textContent = e;
    if (e === curEntity) o.selected = true;
    es.appendChild(o);
  }
  es.onchange = () => { fillFieldSel(fs, es.value); onFieldChange(row); };

  const fs = document.createElement("select"); fs.className = "field-sel";
  fillFieldSel(fs, curEntity); fs.onchange = () => onFieldChange(row);

  const os = document.createElement("select"); os.className = "op-sel";
  os.onchange = () => onOpChange(row);

  const va = document.createElement("span"); va.className = "val-area";

  const rm = document.createElement("button"); rm.className = "rm-btn";
  rm.innerHTML = "&times;"; rm.onclick = () => removeRow(row);

  row.append(es, fs, os, va, rm);
  list.appendChild(row);
  onFieldChange(row);
}

function removeRow(row) {
  const prev = row.previousElementSibling;
  if (prev && prev.classList.contains("logic-pill")) {
    prev.remove();
  } else {
    const next = row.nextElementSibling;
    if (next && next.classList.contains("logic-pill")) next.remove();
  }
  row.remove();
}

function fillFieldSel(sel, entity) {
  const fields = Object.keys(SCHEMA[entity] || SCHEMA[curEntity]);
  const prev = sel.value;
  sel.innerHTML = fields.map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join("");
  if (fields.includes(prev)) sel.value = prev;
}

function rowEntity(row) {
  return row.querySelector(".ent-sel")?.value || curEntity;
}

function getOps(type) {
  if (type === "number")   return OPS_NUM;
  if (type === "choice")   return OPS_CHOICE;
  if (type === "datetime") return OPS_DATE;
  return OPS_TEXT;
}

function onFieldChange(row) {
  const fs = row.querySelector(".field-sel");
  const os = row.querySelector(".op-sel");
  const va = row.querySelector(".val-area");
  const fd = SCHEMA[rowEntity(row)][fs.value] || {type:"text"};
  const ops = getOps(fd.type);
  os.innerHTML = ops.map(o => `<option value="${o.v}">${o.l}</option>`).join("");
  rebuildVal(va, fd, os.value);
}

function onOpChange(row) {
  const fs = row.querySelector(".field-sel");
  const os = row.querySelector(".op-sel");
  const va = row.querySelector(".val-area");
  const fd = SCHEMA[rowEntity(row)][fs.value] || {type:"text"};
  rebuildVal(va, fd, os.value);
}

function rebuildVal(va, fd, op) {
  if (fd.type === "choice") {
    const choices = fd.choices || [];
    va.innerHTML = `<select class="val1">${choices.map(c => {
      const v = Array.isArray(c) ? c[0] : c;
      const l = Array.isArray(c) ? c[1] : c;
      return `<option value="${esc(String(v))}">${esc(String(l))}</option>`;
    }).join("")}</select>`;
  } else if (fd.type === "datetime") {
    if (op === "between") {
      va.innerHTML = `<input class="val1" type="date"><span class="between-sep"> – </span><input class="val2" type="date">`;
    } else {
      va.innerHTML = `<input class="val1" type="date">`;
    }
  } else if (op === "between") {
    va.innerHTML = `<input class="val1" type="number" placeholder="min"><span class="between-sep"> – </span><input class="val2" type="number" placeholder="max">`;
  } else if (fd.type === "number") {
    va.innerHTML = `<input class="val1" type="number" placeholder="value">`;
  } else {
    va.innerHTML = `<input class="val1" type="text" placeholder="value">`;
  }
}

function collectConds() {
  return [...document.querySelectorAll(".condition-row")].map((row, i) => {
    let rowLogic = "AND";
    if (i > 0) {
      const prev = row.previousElementSibling;
      if (prev && prev.classList.contains("logic-pill")) rowLogic = prev.textContent;
    }
    return {
      entity: rowEntity(row),
      field:  row.querySelector(".field-sel").value,
      op:     row.querySelector(".op-sel").value,
      value:  (row.querySelector(".val1")?.value ?? ""),
      value2: (row.querySelector(".val2")?.value ?? ""),
      logic:  rowLogic,
    };
  });
}

// ── Shared result display ─────────────────────────────────────────────────────
function showRunning() {
  const sec = document.getElementById("results");
  sec.style.display = "block";
  document.getElementById("rmeta").innerHTML = "<span style='color:#555'>Running…</span>";
  document.getElementById("rtbl").innerHTML  = "";
  document.getElementById("rsql").textContent = "";
}

function showError(msg) {
  document.getElementById("rmeta").innerHTML = `<span class="err">${esc(msg)}</span>`;
}

function showResults(data) {
  lastResults = data;
  const limitNote = data.count >= LIMIT
    ? ` <span class="limit-note">(capped at ${LIMIT})</span>` : "";
  document.getElementById("rmeta").innerHTML =
    `<span class="count">${data.count.toLocaleString()}</span> rows${limitNote}`
    + ` <button class="btn-copy" onclick="copySQL()">Copy SQL</button>`
    + ` <button class="btn-copy" onclick="copyTable('tsv')" title="Paste into Excel / Sheets">Copy TSV</button>`
    + ` <button class="btn-copy" onclick="copyTable('csv')">Copy CSV</button>`;
  document.getElementById("rsql").textContent = data.sql;
  const tbl = document.getElementById("rtbl");
  if (data.count === 0) { tbl.innerHTML = `<div class="empty">No results.</div>`; return; }
  renderTable(tbl, data.columns, data.rows);
}

function copySQL() {
  navigator.clipboard?.writeText(document.getElementById("rsql").textContent);
}

function copyTable(fmt) {
  if (!lastResults) return;
  let saIdx = lastResults.columns.indexOf("_sa");
  if (saIdx < 0) saIdx = lastResults.columns.indexOf("system_address");
  const sep = fmt === "csv" ? "," : "\t";
  function cell(v) {
    const s = (v === null || v === undefined) ? "" : String(v);
    if (fmt === "csv" && (s.includes(",") || s.includes('"') || s.includes("\n")))
      return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }
  const visCols = lastResults.columns.filter((_, i) => i !== saIdx);
  const lines = [
    visCols.map(cell).join(sep),
    ...lastResults.rows.map(r => r.filter((_, i) => i !== saIdx).map(cell).join(sep)),
  ];
  navigator.clipboard?.writeText(lines.join("\n"));
}

// ── Builder run ───────────────────────────────────────────────────────────────
async function runQuery() {
  showRunning();
  let data;
  try {
    const resp = await fetch("/query", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({conditions: collectConds(), logic}),
    });
    data = await resp.json();
    if (!resp.ok) { showError(data.error || "Error"); return; }
  } catch(e) { showError("Request failed: " + e); return; }
  hAdd(data.sql);
  document.getElementById("raw-input").value = data.sql;
  showResults(data);
}

// ── Raw SQL run ───────────────────────────────────────────────────────────────
async function runRaw() {
  const sql = document.getElementById("raw-input").value.trim();
  if (!sql) return;
  await execRaw(sql);
}

async function execRaw(sql) {
  showRunning();
  let data;
  try {
    const resp = await fetch("/query_raw", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({sql}),
    });
    data = await resp.json();
    if (!resp.ok) { showError(data.error || "Error"); return; }
  } catch(e) { showError("Request failed: " + e); return; }
  hAdd(sql);
  document.getElementById("raw-input").value = sql;
  showResults(data);
}

// ── Table renderer ────────────────────────────────────────────────────────────
// Column names (lowercase) whose cells are rendered as clickable system-map links
// when a system address is available in the result set.
const _LINK_COL_NAMES = new Set([
  "system", "system_name", "name", "body", "body_name", "body / system"
]);

function renderTable(wrap, cols, rows) {
  // SA source: _sa (injected by builder) or system_address (present in raw SQL).
  // Either way the column is hidden from the visible table — it's an internal key.
  let saIdx = cols.indexOf("_sa");
  if (saIdx < 0) saIdx = cols.indexOf("system_address");

  const visCols = cols.filter((_, i) => i !== saIdx);
  const origIdx = visCols.map(c => cols.indexOf(c));

  const isNum = visCols.map((_, ci) =>
    rows.every(r => {
      const v = r[origIdx[ci]];
      return v === null || v === "" || (v !== "" && !isNaN(parseFloat(v)));
    }));

  let sortCol = -1, sortDir = 1;

  function build() {
    const t = document.createElement("table");
    const hr = t.createTHead().insertRow();
    visCols.forEach((c, ci) => {
      const th = document.createElement("th");
      th.innerHTML = `${esc(c.replace(/_/g," "))}<span class="arr"></span>`;
      if (ci === sortCol) th.classList.add(sortDir === 1 ? "asc" : "desc");
      th.onclick = () => {
        sortCol === ci ? (sortDir = -sortDir) : (sortCol = ci, sortDir = 1);
        rebuild();
      };
      hr.appendChild(th);
    });
    const sorted = [...rows].sort((a, b) => {
      if (sortCol < 0) return 0;
      const oi = origIdx[sortCol];
      const va = a[oi], vb = b[oi];
      if (va === null && vb === null) return 0;
      if (va === null) return sortDir; if (vb === null) return -sortDir;
      const na = parseFloat(va), nb = parseFloat(vb);
      if (!isNaN(na) && !isNaN(nb)) return (na - nb) * sortDir;
      return String(va).localeCompare(String(vb)) * sortDir;
    });
    const tb = t.createTBody();
    for (const row of sorted) {
      const tr = tb.insertRow();
      visCols.forEach((_, ci) => {
        const v = row[origIdx[ci]];
        const td = tr.insertCell();
        if (isNum[ci]) td.className = "num";
        if (v === null || v === "") {
          td.innerHTML = `<span class="nil">&#8212;</span>`;
        } else if (_LINK_COL_NAMES.has(visCols[ci].toLowerCase()) && saIdx >= 0 && row[saIdx] != null) {
          td.innerHTML = `<span class="sys-link" data-sa="${esc(String(row[saIdx]))}">${esc(String(v))}</span>`;
        } else if (isNum[ci] && typeof v === "number") {
          td.textContent = v.toLocaleString(undefined, {maximumFractionDigits:3});
        } else {
          td.textContent = v;
        }
      });
    }
    return t;
  }

  function rebuild() { wrap.innerHTML = ""; wrap.appendChild(build()); }
  rebuild();
}

// ── System diagram ────────────────────────────────────────────────────────────
var _sysData = null, _sysBodies = null;

var _starCols = [
    ['SupermassiveBlackHole','#150020'],['AeBe','#ffffe0'],['TTS','#ffa030'],
    ['WNC','#dd44ff'],['WC','#dd44ff'],['WN','#dd44ff'],['WO','#dd44ff'],['W','#dd44ff'],
    ['DAB','#d0e8ff'],['DAV','#d0e8ff'],['DAZ','#d0e8ff'],['DBV','#d0e8ff'],['DCV','#d0e8ff'],['DOV','#d0e8ff'],
    ['DA','#d0e8ff'],['DB','#d0e8ff'],['DC','#d0e8ff'],['DO','#d0e8ff'],['DQ','#d0e8ff'],['DX','#d0e8ff'],['D','#d0e8ff'],
    ['CHd','#e07030'],['CJ','#e07030'],['CN','#e07030'],['CH','#e07030'],['CS','#e08040'],['MS','#e09050'],
    ['C','#e06020'],['S','#e08040'],
    ['N','#00e8e8'],['H','#110018'],
    ['O','#9ac8ff'],['B','#c4e4ff'],['A','#eef4ff'],['F','#fff8e0'],
    ['G','#ffe870'],['K','#ffb840'],['M','#ff6820'],
    ['L','#bb2800'],['T','#801800'],['Y','#401000']
];
function _starCol(sub) {
    if (!sub) return '#aaaaaa';
    for (var i = 0; i < _starCols.length; i++) {
        if (sub.startsWith(_starCols[i][0])) return _starCols[i][1];
    }
    return '#cccccc';
}
function _planetCol(sub, terra) {
    if (!sub) return '#778899';
    var s = sub.toLowerCase();
    if (s === 'earthlike body')           return terra ? '#5aaa70' : '#3a8a5a';
    if (s === 'water world')              return terra ? '#5588cc' : '#3a5aaa';
    if (s === 'ammonia world')            return '#aa7730';
    if (s.includes('metal rich'))         return '#aaaaaa';
    if (s.includes('high metal content')) return '#887766';
    if (s.includes('rocky ice'))          return '#667aaa';
    if (s === 'rocky body')               return terra ? '#aa8844' : '#554433';
    if (s.includes('icy body'))           return '#99bbcc';
    if (s.includes('class i gas')    && !s.includes('ii'))  return '#ccaa44';
    if (s.includes('class ii gas')   && !s.includes('iii')) return '#ee9933';
    if (s.includes('class iii gas')  && !s.includes('iv'))  return '#cc6622';
    if (s.includes('class iv gas')   && !s.includes('v'))   return '#cc4422';
    if (s.includes('class v gas'))        return '#aa2222';
    if (s.includes('helium rich gas'))    return '#6688aa';
    if (s.includes('helium gas giant'))   return '#7799bb';
    if (s.includes('water giant'))        return '#4466aa';
    if (s.includes('gas giant') || s.includes('sudarsky')) return '#cc9944';
    return '#778899';
}
function _bodyPx(b) {
    if (b.t === 'Star') {
        var s = (b.s || '').toLowerCase();
        if (s.includes('supergiant')) return 24;
        if (s.includes('giant'))      return 19;
        if (s === 'n')                return 7;
        if (s.length <= 3 && s.startsWith('d')) return 7;
        if (s === 'h' || s === 'supermassiveblackhole') return 12;
        return 15;
    }
    var s = (b.s || '').toLowerCase();
    if (s.includes('gas giant') || s.includes('water giant') || s.includes('sudarsky')) return 12;
    return 9;
}

var _GC_X = 25, _GC_Z = 25900, _GAL_R = 52000;
var _GAL_REFS = [
    { x: 0,       z: 0,        col: 'rgba(200,200,255,0.75)', r: 1.5, lbl: 'Sol' },
    { x: -9530.5, z: 19808.1,  col: 'rgba(180,140,255,0.80)', r: 1.5, lbl: 'Colonia' },
    { x: 1111.6,  z: 65269.8,  col: 'rgba(140,200,255,0.80)', r: 1.5, lbl: 'Beagle Pt' },
];
function _drawGalMap(data) {
    var canvas = document.getElementById('gal-canvas');
    if (!canvas) return;
    var W = canvas.width, H = canvas.height;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#04040f'; ctx.fillRect(0, 0, W, H);
    function toSX(x) { return (x - _GC_X + _GAL_R) / (_GAL_R * 2) * W; }
    function toSY(z) { return (1 - (z - _GC_Z + _GAL_R) / (_GAL_R * 2)) * H; }
    var gcX = toSX(_GC_X), gcY = toSY(_GC_Z);
    var gRad = Math.min(W, H) * 0.48;
    var gal = ctx.createRadialGradient(gcX, gcY, 0, gcX, gcY, gRad);
    gal.addColorStop(0,    'rgba(255,230,180,0.55)');
    gal.addColorStop(0.08, 'rgba(200,160,100,0.35)');
    gal.addColorStop(0.25, 'rgba(120,100,180,0.20)');
    gal.addColorStop(0.55, 'rgba(60,60,130,0.10)');
    gal.addColorStop(1,    'rgba(0,0,0,0)');
    ctx.fillStyle = gal;
    ctx.beginPath(); ctx.ellipse(gcX, gcY, gRad, gRad * 0.55, -0.35, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(gcX, gcY, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,220,140,0.9)'; ctx.fill();
    ctx.font = '8px sans-serif'; ctx.fillStyle = 'rgba(255,220,140,0.7)';
    ctx.textAlign = 'center'; ctx.fillText('Sag A*', gcX, gcY - 4);
    ctx.font = '8px sans-serif';
    _GAL_REFS.forEach(function(ref) {
        var rx = toSX(ref.x), ry = toSY(ref.z);
        ctx.beginPath(); ctx.arc(rx, ry, 2, 0, Math.PI * 2);
        ctx.fillStyle = ref.col; ctx.fill();
        ctx.fillStyle = ref.col; ctx.textAlign = 'center';
        ctx.fillText(ref.lbl, rx, ry - 4);
    });
    if (data.x != null && data.z != null) {
        var sx = toSX(data.x), sy = toSY(data.z);
        ctx.strokeStyle = 'rgba(60,220,255,0.8)'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(sx - 6, sy); ctx.lineTo(sx + 6, sy); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(sx, sy - 6); ctx.lineTo(sx, sy + 6); ctx.stroke();
        ctx.beginPath(); ctx.arc(sx, sy, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = '#44ddff'; ctx.fill();
    }
    ctx.textAlign = 'left';
}
function _drawLegend() {
    var canvas = document.getElementById('sys-legend-canvas');
    if (!canvas) return;
    var W = canvas.width, H = canvas.height;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0d0d22'; ctx.fillRect(0, 0, W, H);
    var ir = 7, rx = ir * 1.9, ry = ir * 0.48, rot = Math.PI * 0.2;
    var items = [
        { lbl: 'Bio signals', col: 'rgba(160,170,200,0.9)',
          draw: function(x,y) {
            ctx.beginPath(); ctx.arc(x,y,ir,0,Math.PI*2); ctx.fillStyle='rgba(120,140,200,0.9)'; ctx.fill();
            ctx.beginPath(); ctx.arc(x,y,ir+2,0,Math.PI*2); ctx.strokeStyle='rgba(50,220,100,0.75)'; ctx.lineWidth=1.5; ctx.stroke();
          }},
        { lbl: 'Mapped', col: 'rgba(160,170,200,0.9)',
          draw: function(x,y) {
            ctx.beginPath(); ctx.arc(x,y,ir,0,Math.PI*2); ctx.fillStyle='rgba(120,140,200,0.9)'; ctx.fill();
            ctx.beginPath(); ctx.arc(x,y,ir+2,0,Math.PI*2); ctx.strokeStyle='rgba(255,200,80,0.55)'; ctx.lineWidth=1.5; ctx.stroke();
          }},
        { lbl: 'Has rings', col: 'rgba(160,170,200,0.9)',
          draw: function(x,y) {
            ctx.beginPath(); ctx.ellipse(x,y,rx,ry,rot,0,Math.PI); ctx.strokeStyle='rgba(210,210,255,0.7)'; ctx.lineWidth=1; ctx.stroke();
            ctx.beginPath(); ctx.arc(x,y,ir,0,Math.PI*2); ctx.fillStyle='rgba(120,140,200,0.9)'; ctx.fill();
            ctx.beginPath(); ctx.ellipse(x,y,rx,ry,rot,Math.PI,Math.PI*2); ctx.strokeStyle='rgba(210,210,255,0.9)'; ctx.lineWidth=1; ctx.stroke();
          }},
        { lbl: 'First discovered', col: 'rgba(160,170,200,0.9)',
          draw: function(x,y) {
            ctx.beginPath(); ctx.arc(x,y,ir,0,Math.PI*2); ctx.fillStyle='rgba(120,140,200,0.9)'; ctx.fill();
            ctx.font='bold 8px sans-serif'; ctx.fillStyle='#ffee44'; ctx.textAlign='center'; ctx.textBaseline='alphabetic';
            ctx.fillText('★',x,y-ir-2); ctx.font='11px sans-serif'; ctx.textBaseline='alphabetic'; ctx.textAlign='left';
          }},
        { lbl: 'Terraformable', col: '#66ffaa',
          draw: function(x,y) {
            ctx.beginPath(); ctx.arc(x,y,ir,0,Math.PI*2); ctx.fillStyle='rgba(120,140,200,0.9)'; ctx.fill();
          }},
    ];
    var col1x = 16, col2x = W / 2, rowH = 30, startY = 22;
    items.forEach(function(item, i) {
        var lx = i < 3 ? col1x : col2x;
        var ly = startY + (i < 3 ? i : i - 3) * rowH;
        item.draw(lx + ir, ly);
        ctx.font = '11px sans-serif';
        ctx.fillStyle = item.col; ctx.textAlign = 'left';
        ctx.fillText(item.lbl, lx + ir * 2 + 6, ly + 4);
    });
}

function openSysModal(sa, fallbackName) {
    var sysName = fallbackName || ('System ' + sa);
    document.getElementById('sys-modal-ttl').textContent = sysName;
    document.getElementById('sys-modal-sc').textContent = '…';
    document.getElementById('sys-modal').classList.add('open');
    fetch('/system_data?sa=' + encodeURIComponent(sa))
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (!d || !d.bodies) {
                document.getElementById('sys-modal-sc').textContent = 'no scan data';
                var cv = document.getElementById('sys-canvas');
                if (cv) {
                    cv.width = 680; cv.height = 80;
                    var ctx = cv.getContext('2d');
                    ctx.fillStyle = '#040410'; ctx.fillRect(0, 0, 680, 80);
                    ctx.fillStyle = '#556688'; ctx.font = '13px monospace';
                    ctx.fillText('No body scan data for this system.', 16, 46);
                }
                return;
            }
            _sysData = d;
            document.getElementById('sys-modal-ttl').textContent = d.name;
            var scParts = [];
            if (d.sc) scParts.push('(' + d.sc + ')');
            if (d.fv) scParts.push('[' + d.fv + ']');
            document.getElementById('sys-modal-sc').textContent = scParts.join('  ');
            _drawLegend();
            _drawGalMap(d);
            requestAnimationFrame(_drawSys);
        })
        .catch(function() {
            document.getElementById('sys-modal-sc').textContent = 'error';
        });
}
function closeSysModal() {
    document.getElementById('sys-modal').classList.remove('open');
    _sysData = null; _sysBodies = null;
}

function _buildTree(data) {
    var allBodies = data.bodies || [];
    var bodies = allBodies.filter(function(b) { return b.t === 'Star' || b.t === 'Planet'; });
    var byId = {};
    bodies.forEach(function(b) {
        byId[b.i] = { b: b, children: [], parent: null, sortKey: null,
                      gx: 0, gy: 0, lvl: 0, cols: 1, rows: 1, x: 0, y: 0 };
    });
    bodies.forEach(function(b) {
        if (b.p == null) return;
        if (!byId[b.p]) {
            byId[b.p] = { b: { i: b.p, n: '', t: 'Barycentre', s: '' },
                           children: [], parent: null, sortKey: null,
                           gx: 0, gy: 0, lvl: 0, cols: 1, rows: 1, x: 0, y: 0 };
        }
        byId[b.i].parent = b.p;
        byId[b.p].children.push(byId[b.i]);
    });
    _inferHierarchy(byId, bodies, data.name);
    var pfx = data.name + ' ';
    Object.keys(byId).forEach(function(id) {
        var node = byId[id];
        if (node.b.t !== 'Barycentre' || node.b.s) return;
        var stars = node.children.filter(function(c) { return c.b.t === 'Star'; });
        var ref   = stars.length ? stars : node.children;
        node.b.s = stars.map(function(c) {
            var s = c.b.n; return s.indexOf(pfx) === 0 ? s.slice(pfx.length) : s;
        }).join('');
        node.sortKey = ref.reduce(function(s, c) { return s + c.b.i; }, 0) / Math.max(ref.length, 1);
    });
    var primaryStar = null;
    Object.keys(byId).forEach(function(id) {
        var n = byId[id];
        if (n.parent != null) return;
        if (n.b.t === 'Star') {
            if (!primaryStar || primaryStar.b.t !== 'Star' || n.b.i < primaryStar.b.i) primaryStar = n;
        } else if (n.b.t === 'Barycentre' && (!primaryStar || primaryStar.b.t !== 'Star')) {
            if (!primaryStar) primaryStar = n;
        }
    });
    if (primaryStar) {
        Object.keys(byId).forEach(function(id) {
            var n = byId[id];
            if (n.parent != null) return;
            if (n.b.t === 'Barycentre') return;
            if (n.b.t === 'Star') {
                if (n._tok && n._tok.length === 1 && /^[0-9]+$/.test(n._tok[0]) && n !== primaryStar) {
                    n.parent = primaryStar.b.i;
                    primaryStar.children.push(n);
                }
                return;
            }
            n.parent = primaryStar.b.i;
            primaryStar.children.push(n);
        });
    }
    var roots = [];
    Object.keys(byId).forEach(function(id) {
        var n = byId[id]; if (n && n.parent == null) roots.push(n);
    });
    roots.sort(function(a, c) {
        var ak = a.sortKey != null ? a.sortKey : (a.b.i >= 0 ? a.b.i : 9999);
        var ck = c.sortKey != null ? c.sortKey : (c.b.i >= 0 ? c.b.i : 9999);
        if (ak !== ck) return ak - ck;
        if (a.b.t === 'Star' && c.b.t !== 'Star') return -1;
        if (a.b.t !== 'Star' && c.b.t === 'Star') return 1;
        return 0;
    });
    function sortKids(n) {
        n.children.sort(function(a, c) { return a.b.i - c.b.i; });
        n.children.forEach(sortKids);
    }
    roots.forEach(sortKids);
    return { roots: roots, byId: byId };
}
function _inferHierarchy(byId, bodies, sysName) {
    var pfx = sysName + ' ';
    var bySuffix = {};
    var nextSynId = -1;
    bodies.forEach(function(b) {
        var suf = (b.n === sysName) ? '' : (b.n.indexOf(pfx) === 0 ? b.n.slice(pfx.length) : b.n);
        byId[b.i]._sfx = suf;
        byId[b.i]._tok = suf.trim() ? suf.trim().split(/\s+/) : [];
        if (suf) bySuffix[suf] = b.i;
    });
    var sorted = bodies.slice().sort(function(a, c) {
        return byId[a.i]._tok.length - byId[c.i]._tok.length;
    });
    sorted.forEach(function(b) {
        var node = byId[b.i];
        if (node._tok.length <= 1 || node.parent != null) return;
        var pSuf = node._tok.slice(0, -1).join(' ');
        var pId  = bySuffix[pSuf];
        if (pId != null && byId[pId]) {
            node.parent = pId;
            byId[pId].children.push(node);
        } else if (/^[A-Z]{2,}$/.test(pSuf)) {
            if (bySuffix[pSuf] == null) {
                var sid = nextSynId--;
                var letters = pSuf.split('');
                var refIds  = letters.map(function(l) { return bySuffix[l]; }).filter(function(x) { return x != null; });
                var sk = refIds.length ? refIds.reduce(function(s, i) { return s + i; }, 0) / refIds.length : 9999;
                byId[sid] = { b: { i: sid, n: sysName + ' ' + pSuf, t: 'Barycentre', s: pSuf },
                               children: [], parent: null, sortKey: sk,
                               gx: 0, gy: 0, lvl: 0, cols: 1, rows: 1, x: 0, y: 0 };
                bySuffix[pSuf] = sid;
            }
            var baryNode = byId[bySuffix[pSuf]];
            node.parent = baryNode.b.i;
            baryNode.children.push(node);
        }
    });
}
function _nodeHoriz(node, lvl) {
    if (node.b.t === 'Barycentre') return true;
    if (node._tok && node._tok.length > 0) {
        var last = node._tok[node._tok.length - 1];
        if (/^[0-9]+$/.test(last)) return false;
        if (/^[a-z]+$/.test(last)) return true;
        if (/^[A-Z]+$/.test(last)) return true;
    }
    return lvl % 2 === 0;
}
function _computeSize(node, lvl) {
    if (!node.children.length) { node.cols = 1; node.rows = 1; return; }
    var isStar = node.b.t === 'Star' || node.b.t === 'Barycentre';
    var childLvl = isStar ? 1 : lvl + 1;
    node.children.forEach(function(c) { _computeSize(c, childLvl); });
    if (_nodeHoriz(node, lvl)) {
        node.cols = 1 + node.children.reduce(function(s, c) { return s + c.cols; }, 0);
        node.rows = node.children.reduce(function(mx, c) { return Math.max(mx, c.rows); }, 1);
    } else {
        node.cols = node.children.reduce(function(mx, c) { return Math.max(mx, c.cols); }, 1);
        node.rows = 1 + node.children.reduce(function(s, c) { return s + c.rows; }, 0);
    }
}
function _placeNode(node, gx, gy, lvl) {
    node.gx = gx; node.gy = gy; node.lvl = lvl;
    var isStar = node.b.t === 'Star' || node.b.t === 'Barycentre';
    var childLvl = isStar ? 1 : lvl + 1;
    var horiz = _nodeHoriz(node, lvl);
    var off = 1;
    if (horiz) {
        node.children.forEach(function(c) { _placeNode(c, gx + off, gy, childLvl); off += c.cols; });
    } else {
        node.children.forEach(function(c) { _placeNode(c, gx, gy + off, childLvl); off += c.rows; });
    }
}
function _drawSys() {
    var canvas = document.getElementById('sys-canvas');
    if (!canvas || !_sysData) return;
    var H_STEP = 52, V_STEP = 36, PAD_L = 50, PAD_T = 38, PAD_B = 20, ROOT_GAP = 1;
    var tree  = _buildTree(_sysData);
    var roots = tree.roots;
    var totalRows = 0, totalCols = 1;
    roots.forEach(function(r) {
        _computeSize(r, 0);
        _placeNode(r, 0, totalRows, 0);
        totalRows += r.rows + ROOT_GAP;
        if (r.cols > totalCols) totalCols = r.cols;
    });
    totalRows = Math.max(1, totalRows - ROOT_GAP);
    canvas.width  = Math.max(600, PAD_L + totalCols * H_STEP + 30);
    canvas.height = Math.max(320, totalRows * V_STEP + PAD_T + PAD_B);
    var W = canvas.width, H = canvas.height;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#040410'; ctx.fillRect(0, 0, W, H);
    var rng = 7919;
    function _rn() { rng = (rng * 1664525 + 1013904223) | 0; return (rng >>> 0) / 4294967296; }
    for (var si = 0; si < 160; si++) {
        ctx.beginPath(); ctx.arc(_rn()*W, _rn()*H, 0.65, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(180,200,255,' + (0.1 + _rn()*0.4).toFixed(2) + ')';
        ctx.fill();
    }
    function nPx(n) { return PAD_L + n.gx * H_STEP; }
    function nPy(n) { return PAD_T + n.gy * V_STEP; }
    var placed = [];
    (function collect(nodes) {
        nodes.forEach(function(n) { placed.push(n); collect(n.children); });
    }(roots));
    _sysBodies = placed;
    ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(80,100,160,0.45)';
    placed.forEach(function(node) {
        if (!node.children.length) return;
        var px = nPx(node), py = nPy(node);
        var horiz = _nodeHoriz(node, node.lvl);
        var last  = node.children[node.children.length - 1];
        if (horiz) {
            ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(nPx(last), py); ctx.stroke();
        } else {
            ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px, nPy(last)); ctx.stroke();
        }
    });
    placed.forEach(function(node) {
        var b = node.b;
        node.x = nPx(node); node.y = nPy(node);
        var bx = node.x, by = node.y;
        if (b.t === 'Barycentre') {
            var xs = 5;
            ctx.strokeStyle = '#cc3333'; ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.moveTo(bx-xs, by-xs); ctx.lineTo(bx+xs, by+xs); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(bx+xs, by-xs); ctx.lineTo(bx-xs, by+xs); ctx.stroke();
            if (b.s) {
                ctx.font = '8px sans-serif'; ctx.fillStyle = 'rgba(220,120,120,0.9)';
                ctx.textAlign = 'left'; ctx.fillText(b.s, bx + xs + 2, by + 3);
            }
            return;
        }
        var br  = _bodyPx(b);
        var col = b.t === 'Star' ? _starCol(b.s) : _planetCol(b.s, b.e);
        var isBH = b.t === 'Star' && ((b.s || '').toUpperCase() === 'H' ||
                   (b.s || '').toLowerCase().indexOf('black') >= 0);
        if (b.t === 'Star' && !isBH) {
            var g = ctx.createRadialGradient(bx, by, 0, bx, by, br * 2);
            g.addColorStop(0, col); g.addColorStop(0.5, col + '55'); g.addColorStop(1, col + '00');
            ctx.fillStyle = g; ctx.beginPath(); ctx.arc(bx, by, br * 2, 0, Math.PI * 2); ctx.fill();
        }
        if (b.b > 0) {
            ctx.beginPath(); ctx.arc(bx, by, br + 3, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(50,220,100,0.75)'; ctx.lineWidth = 1.5; ctx.stroke();
        }
        if (b.ri > 0) {
            ctx.beginPath();
            ctx.ellipse(bx, by, br * 2.2, br * 0.52, Math.PI * 0.2, 0, Math.PI);
            ctx.strokeStyle = 'rgba(210,210,255,0.7)'; ctx.lineWidth = 1; ctx.stroke();
        }
        ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2);
        if (isBH) {
            ctx.fillStyle = '#050010'; ctx.fill();
            ctx.beginPath(); ctx.arc(bx, by, br + 2, 0, Math.PI * 2);
            ctx.strokeStyle = '#cc33ff'; ctx.lineWidth = 1; ctx.stroke();
        } else {
            ctx.fillStyle = col; ctx.fill();
        }
        if (b.w && b.t !== 'Star') {
            ctx.beginPath(); ctx.arc(bx, by, br + 1.5, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(255,200,80,0.55)'; ctx.lineWidth = 1; ctx.stroke();
        }
        if (b.ri > 0) {
            ctx.beginPath();
            ctx.ellipse(bx, by, br * 2.2, br * 0.52, Math.PI * 0.2, Math.PI, Math.PI * 2);
            ctx.strokeStyle = 'rgba(210,210,255,0.9)'; ctx.lineWidth = 1; ctx.stroke();
        }
        if (b.f) {
            ctx.font = 'bold 6px sans-serif'; ctx.fillStyle = '#ffee44';
            ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
            ctx.fillText('★', bx, by - br - 3);
        }
        var lbl = b.n, lpfx = _sysData.name + ' ';
        if (lbl.indexOf(lpfx) === 0) lbl = lbl.slice(lpfx.length);
        if (lbl === _sysData.name) lbl = '';
        if (lbl) {
            ctx.font = '8px sans-serif';
            ctx.fillStyle = b.e ? '#66ffaa' : '#ffee44';
            ctx.textAlign = 'left';
            ctx.fillText(lbl, bx + br * 0.55, by - br - 1);
        }
    });
    ctx.textAlign = 'left';
    if (!placed.length) {
        ctx.fillStyle = '#446'; ctx.font = '14px sans-serif'; ctx.textAlign = 'center';
        ctx.fillText('No body data available', W / 2, H / 2); ctx.textAlign = 'left';
    }
}

// ── Init ──────────────────────────────────────────────────────────────────────
buildEntBtns();
addRow();
renderHistory();
(function() {
  var canvas = document.getElementById('sys-canvas');
  var tip    = document.getElementById('sys-tip');
  if (canvas) {
    canvas.addEventListener('mousemove', function(e) {
      if (!_sysBodies || !_sysBodies.length) { tip.classList.remove('visible'); return; }
      var rect = canvas.getBoundingClientRect();
      var sx = canvas.width / rect.width, sy = canvas.height / rect.height;
      var mx = (e.clientX - rect.left) * sx, my = (e.clientY - rect.top) * sy;
      var best = null, bd = 9999;
      _sysBodies.forEach(function(node) {
        var br = _bodyPx(node.b);
        var dx = node.x - mx, dy = node.y - my, d = Math.sqrt(dx*dx + dy*dy);
        if (d < br + 12 && d < bd) { bd = d; best = node; }
      });
      if (best) {
        var b = best.b;
        var lines = ['<b>' + (b.n || '?') + '</b>'];
        if (b.s) lines.push(b.s);
        if (b.t !== 'Star') {
          if (b.d) lines.push(b.d.toFixed(1) + ' LS from arrival');
          if (b.b > 0) lines.push('<span style="color:#44ee88">' + b.b + ' bio signal' + (b.b>1?'s':'') + '</span>');
          if (b.g > 0) lines.push('<span style="color:#ee8844">' + b.g + ' geo signal' + (b.g>1?'s':'') + '</span>');
          if (b.ri > 0) lines.push(b.ri + ' ring' + (b.ri>1?'s':''));
          if (b.l)     lines.push('<span style="color:#66cc88">Landable</span>');
          if (b.e)     lines.push('<span style="color:#66ffaa">Terraformable</span>');
          if (b.w)     lines.push('<span style="color:#ffcc44">Mapped</span>');
          if (b.f)     lines.push('<span style="color:#ffee44">★ First discovery</span>');
          if (b.r)     lines.push(b.r.toLocaleString() + ' km radius');
          if (b.k)     lines.push(Math.round(b.k) + ' K');
          if (b.sp && b.sp.length) {
            lines.push('<span style="color:#88ddaa">Species:</span>');
            b.sp.forEach(function(s) { lines.push('&nbsp;&middot; ' + s); });
          }
        } else {
          if (b.d && b.d > 1) lines.push(b.d.toFixed(1) + ' LS from arrival');
          if (b.r) lines.push((b.r / 695700).toFixed(2) + ' R☉');
          if (b.ri > 0) lines.push(b.ri + ' ring' + (b.ri>1?'s':''));
          if (b.f) lines.push('<span style="color:#ffee44">★ First discovery</span>');
        }
        tip.innerHTML = lines.join('<br>');
        tip.classList.add('visible');
        var scale = rect.width / canvas.width;
        var cx = rect.left + best.x * scale;
        var cy = rect.top  + best.y * scale;
        var tw = tip.offsetWidth, th = tip.offsetHeight;
        var tx = cx + 14, ty = cy - 10;
        if (tx + tw + 8 > window.innerWidth)  tx = cx - tw - 14;
        if (ty + th + 8 > window.innerHeight) ty = cy - th - 10;
        if (ty < 4) ty = 4; if (tx < 4) tx = 4;
        tip.style.left = tx + 'px'; tip.style.top = ty + 'px';
      } else {
        tip.classList.remove('visible');
      }
    });
    canvas.addEventListener('mouseleave', function() { tip.classList.remove('visible'); });
  }
  var bg    = document.getElementById('sys-modal-bg');
  var close = document.getElementById('sys-modal-close');
  if (bg)    bg.addEventListener('click', closeSysModal);
  if (close) close.addEventListener('click', closeSysModal);
  document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeSysModal(); });
  document.addEventListener('click', function(e) {
    var link = e.target.closest('.sys-link');
    if (link && link.dataset.sa) openSysModal(link.dataset.sa, link.textContent.trim());
  });
}());
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pdm run serve",
        description="Start the EDDA query builder web UI at http://localhost:5000",
    )
    parser.add_argument(
        "--db", type=Path, default=None, metavar="PATH",
        help="Path to SQLite database (default: .edda/ed.db)",
    )
    parser.add_argument(
        "--port", type=int, default=5000, metavar="PORT",
        help="Port to listen on (default: 5000)",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Do not auto-open the browser on startup",
    )
    args = parser.parse_args(argv)

    global _db_path
    _db_path = args.db

    url = f"http://localhost:{args.port}/"
    print(f"EDDA Control Panel -> {url}  (Ctrl-C to stop)")
    if not args.no_browser and sys.stdout and sys.stdout.isatty():
        threading.Timer(0.8, webbrowser.open, args=[url]).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
