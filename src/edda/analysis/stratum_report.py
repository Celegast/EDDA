"""
Stratum Tectonicas research report.

Queries the EDDA database for High Metal Content bodies with exactly one
biological signal, thin atmosphere, and surface temperature >= 165 K
(the canonical filter for Stratum Tectonicas candidates).

Generates a self-contained dark-theme HTML report comparing confirmed
Stratum bodies against those where another genus was confirmed, to help
identify predictive physical indicators.
"""

from __future__ import annotations

import json
import re as _re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .dashboard import _SYS_MODAL_CSS, _SYS_MODAL_JS, _SYS_MODAL_HTML


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

_COL_STRATUM = "#55cc66"      # soft green    — confirmed Stratum
_COL_OTHER   = "#f08080"      # lightcoral    — confirmed non-Stratum (Bacterium)
_COL_UNKNOWN = "#888899"      # muted grey    — unconfirmed
_COL_RATE    = "#ffffff"      # white         — Stratum rate % overlay
_BG_PAPER    = "#0a0a1a"
_BG_PLOT     = "#0f0f2a"
_GRID        = "#222244"

_LAYOUT_BASE = dict(
    paper_bgcolor=_BG_PAPER,
    plot_bgcolor=_BG_PLOT,
    font_color="white",
    legend=dict(bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
    margin=dict(l=60, r=40, t=50, b=50),
)


# ---------------------------------------------------------------------------
# CSS / HTML helpers  (shared with trip_report style)
# ---------------------------------------------------------------------------

_FAVICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <circle cx="16" cy="16" r="15" fill="#0a0a2a" stroke="#1a2a1a" stroke-width="0.8"/>
  <!-- Concentric flat discs: Stratum Tectonicas silhouette -->
  <ellipse cx="16" cy="20" rx="12" ry="4.2" fill="none" stroke="#55cc66" stroke-width="1.5" opacity="0.55"/>
  <ellipse cx="16" cy="20" rx="7.5" ry="2.6" fill="none" stroke="#55cc66" stroke-width="1.4" opacity="0.8"/>
  <ellipse cx="16" cy="20" rx="3.2" ry="1.2" fill="#55cc66"/>
  <!-- Stem -->
  <line x1="16" y1="18.8" x2="16" y2="11.5" stroke="#44aa55" stroke-width="1.2" stroke-linecap="round"/>
  <!-- Spore cap -->
  <circle cx="16" cy="9.8" r="2.2" fill="#55cc66"/>
</svg>"""

import base64 as _b64
_FAVICON_HREF = (
    "data:image/svg+xml;base64,"
    + _b64.b64encode(_FAVICON_SVG.encode()).decode()
)

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #07071a; color: #ccd0e0; font-family: 'Segoe UI', system-ui, sans-serif;
       font-size: 14px; line-height: 1.5; }
header { background: #0a0a22; border-bottom: 1px solid #1a1a44;
         padding: 18px 28px 14px; }
header h1 { font-size: 1.55rem; font-weight: 700; color: #aabbee; letter-spacing: 0.04em; }
.subtitle { font-size: 0.82rem; color: #556688; margin-top: 3px; }
.temp-badge { background: #2a1800; border: 1px solid #cc7700; border-radius: 3px;
              color: #ffaa33; font-size: 0.80rem; padding: 1px 6px; margin-left: 4px;
              font-weight: 600; letter-spacing: 0.02em; }
.content { max-width: 1280px; margin: 0 auto; padding: 18px 24px 40px; }
section { margin-bottom: 28px; }
h2 { font-size: 1.05rem; font-weight: 600; color: #7788bb;
     text-transform: uppercase; letter-spacing: 0.07em;
     border-bottom: 1px solid #1a1a33; padding-bottom: 6px; margin-bottom: 12px; }

/* stat cards */
.stat-row { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 4px; }
.stat-card { background: #0d0d28; border: 1px solid #1a1a44; border-radius: 6px;
             padding: 10px 16px; min-width: 120px; }
.stat-val  { font-size: 1.3rem; font-weight: 700; color: #aabbee; }
.stat-val.green  { color: #4de86a; }
.stat-val.orange { color: #e87a4d; }
.stat-val.blue   { color: #6688aa; }
.stat-label { font-size: 0.72rem; color: #556688; margin-top: 2px; text-transform: uppercase; }

/* tables */
.table-wrap { overflow-x: auto; }
.table-scroll { max-height: 60vh; overflow-y: auto; }
.table-scroll thead th { position: sticky; top: 0; z-index: 2; background: #111133; }
table { border-collapse: collapse; width: 100%; font-size: 0.82rem; }
thead tr { background: #111133; }
th { padding: 7px 10px; text-align: left; color: #8899bb;
     font-weight: 600; border-bottom: 1px solid #222244; }
th.sortable-col { cursor: pointer; user-select: none; }
th.sortable-col:hover { color: #aaccff; }
th.sort-asc::after  { content: " ▲"; font-size: 0.65em; }
th.sort-desc::after { content: " ▼"; font-size: 0.65em; }
td { padding: 5px 10px; border-bottom: 1px solid #161630; }
tr:hover td { background: #111133; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.stratum  { color: #4de86a; font-weight: 600; }
td.other    { color: #e87a4d; }
td.unknown  { color: #556688; font-style: italic; }

/* chart containers */
.chart-wrap { background: #0a0a1a; border-radius: 6px;
              border: 1px solid #1a1a33; overflow: hidden; }
"""

_SORT_JS = """
<script>
(function() {
  document.querySelectorAll('table.sortable thead th').forEach(function(th) {
    th.classList.add('sortable-col');
    th.addEventListener('click', function() {
      var table = th.closest('table');
      var tbody = table.querySelector('tbody');
      var idx   = Array.from(th.parentElement.children).indexOf(th);
      var wasSortAsc  = th.classList.contains('sort-asc');
      var wasSortDesc = th.classList.contains('sort-desc');
      var asc;
      if (!wasSortAsc && !wasSortDesc) {
        var sampleCell = tbody.querySelector('tr td:nth-child(' + (idx + 1) + ')');
        var sampleVal  = sampleCell ? parseSortVal(sampleCell.textContent.trim()) : NaN;
        asc = isNaN(sampleVal);
      } else {
        asc = wasSortDesc;
      }
      table.querySelectorAll('thead th').forEach(function(h) {
        h.classList.remove('sort-asc', 'sort-desc');
      });
      th.classList.add(asc ? 'sort-asc' : 'sort-desc');
      var rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort(function(a, b) {
        var av = parseSortVal(a.cells[idx] ? a.cells[idx].textContent.trim() : '');
        var bv = parseSortVal(b.cells[idx] ? b.cells[idx].textContent.trim() : '');
        if (isNaN(av) && isNaN(bv)) return asc ? av > bv ? 1 : -1 : av < bv ? 1 : -1;
        if (isNaN(av)) return 1;
        if (isNaN(bv)) return -1;
        return asc ? av - bv : bv - av;
      });
      rows.forEach(function(r) { tbody.appendChild(r); });
    });
  });
  function parseSortVal(text) {
    var t = text.replace(/,/g, '').trim();
    var n = parseFloat(t);
    return isNaN(n) ? t : n;
  }
}());
</script>
"""


def _html_doc(title: str, body: str, extra_js: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="icon" type="image/svg+xml" href="{_FAVICON_HREF}">
<style>{_CSS}{_SYS_MODAL_CSS}</style>
</head>
<body>
{body}
{extra_js}
</body>
</html>"""


def _section(heading: str, content: str) -> str:
    return f'<section><h2>{heading}</h2>{content}</section>'


def _plotly_div(fig: go.Figure, first: bool = False) -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if first else False,
        config={"responsive": True},
    )


def _chart(fig: go.Figure | None, first: bool = False) -> str:
    if fig is None:
        return ""
    return f'<div class="chart-wrap">{_plotly_div(fig, first=first)}</div>'


def _esc(s: str) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _fmt(val, decimals: int = 2) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return "—"
    return f"{val:,.{decimals}f}"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_CANDIDATE_SQL = """
SELECT
    b.system_address,
    b.body_id,
    b.name                  AS body_name,
    s.name                  AS system_name,
    b.surface_temp_k        AS temp_k,
    b.surface_gravity_g     AS gravity_g,
    b.mass_em,
    b.radius_km,
    b.atmosphere_type,
    b.surface_pressure,
    b.composition_ice,
    b.composition_rock,
    b.composition_metal,
    b.distance_ls,
    b.semi_major_axis,
    b.parent_star_id,
    b.terraform_state,
    b.was_mapped,
    -- parent star info
    ps.subtype              AS star_type,
    ps.age_my               AS star_age_my,
    ps.mass_em              AS star_mass_sol,
    ps.absolute_magnitude   AS star_abs_mag,
    -- genus from DSS mapping (SAASignalsFound) — available for all mapped bodies
    bs.genus_localised      AS confirmed_genus,
    -- species name from completed organic scan (more specific, optional)
    os.species_localised    AS confirmed_species,
    -- species from any scan stage (for oddity detection when scan is incomplete)
    os_any.species_localised AS any_scan_species,
    -- avg He% of gas giants in same system (regional metallicity proxy)
    (SELECT AVG(b_gg.atmosphere_he_pct)
     FROM bodies b_gg
     WHERE b_gg.system_address = b.system_address
       AND b_gg.body_type = 'Planet'
       AND LOWER(b_gg.subtype) LIKE '%gas giant%'
       AND b_gg.atmosphere_he_pct > 0
    ) AS system_he_pct,
    -- system primary star (lowest body_id star) for binary/companion context
    (SELECT b2.mass_em FROM bodies b2
     WHERE b2.system_address = b.system_address AND b2.body_type = 'Star'
     ORDER BY b2.body_id ASC LIMIT 1) AS system_primary_mass_sol
FROM bodies b
JOIN systems s ON s.system_address = b.system_address
LEFT JOIN bodies ps
    ON ps.system_address = b.system_address
   AND ps.body_id        = b.parent_star_id
   AND ps.body_type      = 'Star'
LEFT JOIN (
    SELECT system_address, body_id, MAX(genus_localised) AS genus_localised
    FROM bio_signals
    GROUP BY system_address, body_id
) bs ON bs.system_address = b.system_address AND bs.body_id = b.body_id
LEFT JOIN (
    SELECT system_address, body_id, MAX(species_localised) AS species_localised
    FROM organic_scans
    WHERE scan_state = 'Analyse'
    GROUP BY system_address, body_id
) os ON os.system_address = b.system_address AND os.body_id = b.body_id
LEFT JOIN (
    SELECT system_address, body_id, MAX(species_localised) AS species_localised
    FROM organic_scans
    WHERE species_localised IS NOT NULL
    GROUP BY system_address, body_id
) os_any ON os_any.system_address = b.system_address AND os_any.body_id = b.body_id
WHERE b.subtype          = 'High metal content body'
  AND b.bio_signals      = 1
  AND b.surface_temp_k   >= ?
  AND b.surface_temp_k   <= ?
  AND (b.surface_pressure IS NULL OR b.surface_pressure < 10000)
ORDER BY b.system_address, b.body_id
"""

_MATERIALS_SQL = """
SELECT bm.system_address, bm.body_id, bm.name AS material, bm.percent
FROM body_materials bm
JOIN bodies b ON b.system_address = bm.system_address AND b.body_id = bm.body_id
WHERE b.subtype = 'High metal content body'
  AND b.bio_signals = 1
  AND b.surface_temp_k >= ?
  AND b.surface_temp_k <= ?
  AND (b.surface_pressure IS NULL OR b.surface_pressure < 10000)
"""


# Biological genera introduced in Horizons (pre-Odyssey phenomena visible from
# the ship — not scanned with the biological scanner on foot).  Bodies whose
# only bio signal is one of these are irrelevant to Stratum research.
_HORIZONS_GENERA = {
    "anemone", "sinuous tubers", "bark mounds", "brain trees",
    "crystalline shards", "amphora plant", "lasso",
}

# Star spectral classes where Stratum Tectonicas has never been confirmed.
# Exclusion uses prefix matching so variants (A_SuperGiant, G_SubGiant, etc.)
# are also covered.  AeBe (Herbig Ae/Be) is exempt from the A-prefix rule —
# it IS a confirmed Stratum host.
_EXCLUDED_STAR_PREFIXES = ("A", "G", "B", "O", "N")


def _is_excluded_star(star_type: str | None) -> bool:
    if not star_type:
        return False  # unidentified parent — keep in unconfirmed pool
    if star_type.startswith("AeBe"):
        return False  # Herbig Ae/Be: Stratum confirmed
    for prefix in _EXCLUDED_STAR_PREFIXES:
        if star_type == prefix or star_type.startswith(prefix + "_"):
            return True
    return False


def _is_horizons(genus: str | None) -> bool:
    if not genus:
        return False
    g = genus.lower()
    return any(h in g for h in _HORIZONS_GENERA)


_TEMP_NO_MAX = 99_999.0   # sentinel: no upper bound on surface temperature


def _temp_range_label(min_temp: float, max_temp: float | None) -> str:
    if max_temp is None:
        return f"surface temp ≥ {min_temp:.0f} K"
    return (
        f"surface temp "
        f'<span class="temp-badge">{min_temp:.0f}–{max_temp:.0f} K</span>'
    )


def _load_data(
    conn: sqlite3.Connection,
    min_temp: float = 165.0,
    max_temp: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (candidates_df, materials_df), Horizons-only bodies excluded."""
    t_params = (min_temp, max_temp if max_temp is not None else _TEMP_NO_MAX)
    df = pd.read_sql_query(_CANDIDATE_SQL, conn, params=t_params)

    # Drop bodies whose confirmed genus is a Horizons-era phenomenon
    df = df[~df["confirmed_genus"].fillna("").apply(_is_horizons)].copy()

    # Drop bodies whose parent star type is known to never host Stratum
    df = df[~df["star_type"].fillna("").apply(_is_excluded_star)].copy()

    # Classify each body
    genus_lower = df["confirmed_genus"].fillna("").str.lower()
    df["status"] = "unconfirmed"
    df.loc[genus_lower.str.contains("stratum"), "status"] = "stratum"
    df.loc[(genus_lower != "") & ~genus_lower.str.contains("stratum"), "status"] = "other"

    # Flag bodies that are confirmed oddities — kept in tables, excluded from charts.
    # Case 1: DSS genus is confirmed as non-Stratum, non-Bacterium.
    # Case 2: no DSS genus but any organic scan stage (incl. partial Log/Sample)
    #         reveals a non-Stratum/Bacterium species.
    any_species_lower = df["any_scan_species"].fillna("").str.lower()
    df["is_oddity"] = (
        (df["status"] == "other") & ~genus_lower.str.contains("bacterium")
    ) | (
        (df["status"] == "unconfirmed") &
        (any_species_lower != "") &
        ~any_species_lower.str.contains("stratum") &
        ~any_species_lower.str.contains("bacterium")
    )

    mat = pd.read_sql_query(_MATERIALS_SQL, conn, params=t_params)
    # Also drop materials for excluded bodies (re-filter by surviving keys)
    surviving = set(zip(df["system_address"], df["body_id"]))
    mat = mat[mat.apply(
        lambda r: (r["system_address"], r["body_id"]) in surviving, axis=1
    )].copy()

    return df, mat


def _system_diagram_data(conn: sqlite3.Connection, system_addresses: list) -> dict:
    """System diagram data for given system addresses (same format as dashboard)."""
    if not system_addresses:
        return {}

    ph = ",".join("?" * len(system_addresses))
    sys_rows = conn.execute(
        f"SELECT system_address, name, star_class, x, z, first_seen_at "
        f"FROM systems WHERE system_address IN ({ph})",
        system_addresses,
    ).fetchall()
    result = {
        str(r[0]): {
            "name": r[1], "sc": r[2] or "",
            "x": r[3], "z": r[4],
            "fv": r[5][:10] if r[5] else None,
            "bodies": [],
        }
        for r in sys_rows
    }
    sa_list = list(result.keys())
    if not sa_list:
        return result

    ph2 = ",".join("?" * len(sa_list))
    bodies_sql = f"""
        SELECT b.system_address, b.body_id, b.name, b.body_type, b.subtype,
               b.distance_ls, b.bio_signals, b.geo_signals,
               b.was_mapped, b.first_discovered, b.radius_km,
               b.surface_temp_k, b.is_landable, b.terraform_state,
               b.orbital_parent_id, b.parent_star_id,
               (SELECT COUNT(*) FROM rings r
                WHERE r.system_address = b.system_address AND r.body_id = b.body_id
                  AND r.name NOT LIKE '% Belt') AS ring_count
        FROM bodies b
        WHERE b.system_address IN ({ph2})
        ORDER BY b.system_address, COALESCE(b.distance_ls, 99999)
    """
    for r in conn.execute(bodies_sql, sa_list).fetchall():
        sa_str = str(r[0])
        if sa_str not in result:
            continue
        tf = (r[13] or "").strip().lower()
        result[sa_str]["bodies"].append({
            "i": r[1], "n": r[2], "t": r[3], "s": r[4] or "",
            "d": round(r[5], 2) if r[5] is not None else None,
            "b": r[6] or 0, "g": r[7] or 0,
            "w": r[8] or 0, "f": r[9] or 0,
            "r": round(r[10]) if r[10] else None,
            "k": round(r[11]) if r[11] else None,
            "l": r[12] or 0,
            "e": 1 if tf and tf not in ("", "not terraformable") else 0,
            "p": r[14], "q": r[15], "ri": r[16] or 0,
        })

    ph3 = ",".join("?" * len(sa_list))
    species_sql = f"""
        SELECT system_address, body_id, species_localised
        FROM organic_scans
        WHERE scan_state = 'Analyse' AND species_localised IS NOT NULL
          AND system_address IN ({ph3})
        ORDER BY system_address, body_id, species_localised
    """
    species_map: dict = {}
    for r in conn.execute(species_sql, sa_list).fetchall():
        key = (str(r[0]), r[1])
        species_map.setdefault(key, []).append(r[2])
    for body_data in (b for sys in result.values() for b in sys["bodies"]):
        key = (str(body_data.get("sa", "")), body_data["i"])
        # find the right system
    for sa_str, sys in result.items():
        for body_data in sys["bodies"]:
            key = (sa_str, body_data["i"])
            if key in species_map:
                body_data["sp"] = species_map[key]

    return result


# ---------------------------------------------------------------------------
# Summary cards
# ---------------------------------------------------------------------------

def _summary_cards(df: pd.DataFrame) -> str:
    total      = len(df)
    n_stratum  = (df["status"] == "stratum").sum()
    n_other    = (df["status"] == "other").sum()
    n_unknown  = (df["status"] == "unconfirmed").sum()
    n_scanned  = n_stratum + n_other
    rate_str   = f"{n_stratum / n_scanned * 100:.1f}%" if n_scanned else "n/a"

    def card(val: str, label: str, cls: str = "") -> str:
        cls_attr = f' class="{cls}"' if cls else ''
        return (
            f'<div class="stat-card">'
            f'<div class="stat-val{cls_attr}">{val}</div>'
            f'<div class="stat-label">{label}</div>'
            f'</div>'
        )

    return (
        f'<div class="stat-row">'
        + card(f"{total:,}",        "Total candidates")
        + card(f"{n_stratum:,}",    "Confirmed Stratum", " green")
        + card(f"{n_other:,}",      "Confirmed other",   " orange")
        + card(f"{n_unknown:,}",    "Unconfirmed",       " blue")
        + card(rate_str,            "Stratum rate (scanned)")
        + f'</div>'
    )


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _atm_type_chart(df: pd.DataFrame) -> go.Figure | None:
    """Bar chart: Stratum rate by atmosphere type."""
    grp = (
        df.groupby("atmosphere_type")["status"]
        .value_counts()
        .unstack(fill_value=0)
    )
    for col in ("stratum", "other", "unconfirmed"):
        if col not in grp.columns:
            grp[col] = 0

    grp["scanned"] = grp["stratum"] + grp["other"]
    grp["rate"] = grp.apply(
        lambda r: r["stratum"] / r["scanned"] if r["scanned"] > 0 else None, axis=1
    )
    grp = grp.sort_values("scanned", ascending=False).head(20)

    if grp.empty:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["stratum"],
        name="Stratum", marker_color=_COL_STRATUM, opacity=0.85,
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["other"],
        name="Other genus", marker_color=_COL_OTHER, opacity=0.85,
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["unconfirmed"],
        name="Unconfirmed", marker_color=_COL_UNKNOWN, opacity=0.6,
    ), secondary_y=False)
    _rate_vals = grp["rate"] * 100
    fig.add_trace(go.Scatter(
        x=grp.index,
        y=_rate_vals,
        name="Stratum rate %", mode="markers+text+lines",
        marker=dict(color=_COL_RATE, size=8),
        line=dict(color="rgba(255,255,255,0.2)", width=1.5, dash="dot"),
        text=[f"{v:.1f}%" if v is not None else "" for v in _rate_vals],
        textposition="top center",
        textfont=dict(color=_COL_RATE, size=9),
        hovertemplate="%{y:.1f}%<extra>Stratum rate</extra>",
    ), secondary_y=True)
    fig.update_layout(
        title="Atmosphere Type vs Stratum Confirmation",
        barmode="stack",
        xaxis_tickangle=-35,
        yaxis_title="Body count",
        height=400,
        **_LAYOUT_BASE,
    )
    fig.update_yaxes(title_text="Stratum rate (%)", secondary_y=True, range=[0, 115],
                     gridcolor="rgba(255,255,255,0.06)")
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, secondary_y=False)
    return fig


def _physical_scatter(df: pd.DataFrame) -> go.Figure | None:
    """Gravity vs Temperature scatter, coloured by status."""
    d = df.dropna(subset=["temp_k", "gravity_g"])
    if d.empty:
        return None

    fig = go.Figure()
    for status, col, name in [
        ("other",       _COL_OTHER,    "Other genus"),
        ("unconfirmed", _COL_UNKNOWN,  "Unconfirmed"),
        ("stratum",     _COL_STRATUM,  "Stratum"),
    ]:
        sub = d[d["status"] == status]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["temp_k"],
            y=sub["gravity_g"],
            mode="markers",
            name=name,
            marker=dict(color=col, size=5, opacity=0.7),
            text=sub["body_name"],
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Temp: %{x:.0f} K<br>"
                "Gravity: %{y:.3f} g<extra></extra>"
            ),
        ))
    fig.update_layout(
        title="Surface Gravity vs Temperature",
        xaxis_title="Surface Temperature (K)",
        yaxis_title="Surface Gravity (g)",
        height=420,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    return fig


def _mass_gravity_chart(df: pd.DataFrame) -> go.Figure | None:
    """Side-by-side box plots: mass and gravity for Stratum vs other."""
    scanned = df[df["status"] != "unconfirmed"]
    if scanned.empty:
        return None

    s = scanned[scanned["status"] == "stratum"]
    o = scanned[scanned["status"] == "other"]

    fig = make_subplots(rows=1, cols=2, subplot_titles=["Mass (Earth masses)", "Gravity (g)"])

    for col_name, row_col, title in [("mass_em", 1, ""), ("gravity_g", 2, "")]:
        for sub, name, col in [(s, "Stratum", _COL_STRATUM), (o, "Other", _COL_OTHER)]:
            vals = sub[col_name].dropna()
            if vals.empty:
                continue
            fig.add_trace(go.Box(
                y=vals, name=name, marker_color=col, showlegend=(col_name == "mass_em"),
                boxmean=True,
            ), row=1, col=row_col)

    fig.update_layout(
        title="Physical Properties: Stratum vs Other (scanned only)",
        height=380,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    return fig


def _star_type_chart(df: pd.DataFrame) -> go.Figure | None:
    """Stratum rate by parent star type (top types only)."""
    d = df.dropna(subset=["star_type"])
    if d.empty:
        return None

    grp = (
        d.groupby("star_type")["status"]
        .value_counts()
        .unstack(fill_value=0)
    )
    for col in ("stratum", "other", "unconfirmed"):
        if col not in grp.columns:
            grp[col] = 0

    grp["total"] = grp["stratum"] + grp["other"] + grp["unconfirmed"]
    grp = grp[grp["total"] >= 3].sort_values("total", ascending=False).head(15)
    if grp.empty:
        return None

    grp["scanned"] = grp["stratum"] + grp["other"]
    grp["rate"] = grp.apply(
        lambda r: r["stratum"] / r["scanned"] * 100 if r["scanned"] > 0 else None, axis=1
    )

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["stratum"],
        name="Stratum", marker_color=_COL_STRATUM, opacity=0.85,
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["other"],
        name="Other genus", marker_color=_COL_OTHER, opacity=0.85,
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["unconfirmed"],
        name="Unconfirmed", marker_color=_COL_UNKNOWN, opacity=0.6,
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=grp.index, y=grp["rate"],
        name="Stratum rate %", mode="markers+text+lines",
        marker=dict(color=_COL_RATE, size=8),
        line=dict(color="rgba(255,255,255,0.2)", width=1.5, dash="dot"),
        text=[f"{v:.1f}%" if v is not None else "" for v in grp["rate"]],
        textposition="top center",
        textfont=dict(color=_COL_RATE, size=9),
        hovertemplate="%{y:.1f}%<extra>Stratum rate</extra>",
    ), secondary_y=True)
    fig.update_layout(
        title="Parent Star Type vs Stratum Confirmation",
        barmode="stack",
        xaxis_title="Star type",
        yaxis_title="Body count",
        height=400,
        **_LAYOUT_BASE,
    )
    fig.update_yaxes(title_text="Stratum rate (%)", secondary_y=True, range=[0, 115],
                     gridcolor="rgba(255,255,255,0.06)")
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, secondary_y=False)
    return fig


def _star_age_chart(df: pd.DataFrame) -> go.Figure | None:
    """Age histogram (500 MY bins): Stratum vs other."""
    scanned = df[df["status"] != "unconfirmed"].dropna(subset=["star_age_my"])
    if scanned.empty:
        return None

    s_ages = scanned[scanned["status"] == "stratum"]["star_age_my"]
    o_ages = scanned[scanned["status"] == "other"]["star_age_my"]
    bins = dict(start=0, end=scanned["star_age_my"].max() + 500, size=500)

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=o_ages, xbins=bins, name="Other genus",
        marker_color=_COL_OTHER, opacity=0.75,
    ))
    fig.add_trace(go.Histogram(
        x=s_ages, xbins=bins, name="Stratum",
        marker_color=_COL_STRATUM, opacity=0.75,
    ))
    fig.update_layout(
        title="Parent Star Age Distribution (500 MY bins)",
        barmode="overlay",
        xaxis_title="Star Age (MY)",
        yaxis_title="Count",
        height=360,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    return fig


def _materials_chart(df: pd.DataFrame, mat: pd.DataFrame) -> go.Figure | None:
    """Mean material % comparison: Stratum vs other."""
    if mat.empty or df.empty:
        return None

    merged = mat.merge(
        df[["system_address", "body_id", "status"]],
        on=["system_address", "body_id"], how="left"
    )
    scanned = merged[merged["status"].isin(["stratum", "other"])]
    if scanned.empty:
        return None

    grp = (
        scanned.groupby(["material", "status"])["percent"]
        .mean()
        .unstack(fill_value=0)
    )
    for col in ("stratum", "other"):
        if col not in grp.columns:
            grp[col] = 0.0

    grp["diff"] = grp["stratum"] - grp["other"]
    grp = grp.reindex(grp["diff"].abs().sort_values(ascending=False).index)
    grp = grp.head(20)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=grp.index,
        y=grp["stratum"],
        name="Stratum (mean %)", marker_color=_COL_STRATUM, opacity=0.85,
    ))
    fig.add_trace(go.Bar(
        x=grp.index,
        y=grp["other"],
        name="Other genus (mean %)", marker_color=_COL_OTHER, opacity=0.85,
    ))
    fig.update_layout(
        title="Surface Materials: Stratum vs Other (mean %, top 20 by difference)",
        barmode="group",
        xaxis_tickangle=-40,
        yaxis_title="Mean % on body surface",
        height=400,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    return fig


# ---------------------------------------------------------------------------
# Distribution plots (histogram + Stratum ratio overlay per property)
# ---------------------------------------------------------------------------

_DIST_FEATURES = [
    ("temp_k",           "Surface Temperature (K)",   None),
    ("gravity_g",        "Surface Gravity (g)",        None),
    ("mass_em",          "Mass (Earth masses)",        None),
    ("radius_km",        "Radius (km)",                None),
    ("surface_pressure", "Surface Pressure (Pa)",      None),
]


def _distribution_plots(df: pd.DataFrame) -> go.Figure | None:
    """One subplot per physical property: Stratum vs Other histogram + ratio curve."""
    import numpy as np

    scanned = df[df["status"].isin(["stratum", "other"])]
    if scanned.empty:
        return None

    n = len(_DIST_FEATURES)
    fig = make_subplots(
        rows=n, cols=1,
        subplot_titles=[f[1] for f in _DIST_FEATURES],
        specs=[[{"secondary_y": True}]] * n,
        vertical_spacing=0.07,
    )

    for row_idx, (col, label, _) in enumerate(_DIST_FEATURES, start=1):
        data = scanned.dropna(subset=[col])
        if data.empty:
            continue
        s_vals = data[data["status"] == "stratum"][col].to_numpy(dtype=float, na_value=float("nan"))
        o_vals = data[data["status"] == "other"][col].to_numpy(dtype=float, na_value=float("nan"))
        all_vals = np.concatenate([s_vals, o_vals])
        lo, hi = all_vals.min(), all_vals.max()
        if lo >= hi:
            continue

        bins = np.linspace(lo, hi, 31)
        centers = (bins[:-1] + bins[1:]) / 2

        s_counts, _ = np.histogram(s_vals, bins=bins)
        o_counts, _ = np.histogram(o_vals, bins=bins)
        total = s_counts + o_counts
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = np.where(total > 0, s_counts / total * 100, np.nan)

        fig.add_trace(go.Bar(
            x=centers, y=o_counts, name="Other" if row_idx == 1 else None,
            marker_color=_COL_OTHER, opacity=0.75,
            showlegend=(row_idx == 1),
            hovertemplate=f"{label}: %{{x:.2f}}<br>Other: %{{y}}<extra></extra>",
        ), row=row_idx, col=1, secondary_y=False)
        fig.add_trace(go.Bar(
            x=centers, y=s_counts, name="Stratum" if row_idx == 1 else None,
            marker_color=_COL_STRATUM, opacity=0.75,
            showlegend=(row_idx == 1),
            hovertemplate=f"{label}: %{{x:.2f}}<br>Stratum: %{{y}}<extra></extra>",
        ), row=row_idx, col=1, secondary_y=False)

        mask = total > 0
        xm, ym = centers[mask], ratio[mask]
        # Raw rate dots with percentage labels
        fig.add_trace(go.Scatter(
            x=xm, y=ym,
            name="Stratum rate" if row_idx == 1 else None,
            mode="markers+text", marker=dict(color=_COL_RATE, size=6),
            text=[f"{v:.1f}" for v in ym],
            textposition="top center",
            textfont=dict(color=_COL_RATE, size=8),
            showlegend=(row_idx == 1),
            hovertemplate="Stratum rate: %{y:.1f}%<extra></extra>",
        ), row=row_idx, col=1, secondary_y=True)
        # Gaussian-smoothed trend line
        if len(xm) >= 4:
            xs = np.linspace(xm.min(), xm.max(), 200)
            sigma = (xm.max() - xm.min()) * 0.08
            ys = np.array([
                np.average(ym, weights=np.exp(-0.5 * ((xm - xi) / sigma) ** 2))
                for xi in xs
            ])
            fig.add_trace(go.Scatter(
                x=xs, y=np.clip(ys, 0, 100),
                name=None, showlegend=False,
                mode="lines",
                line=dict(color="rgba(255,255,255,0.55)", width=1.5, dash="dot"),
                hoverinfo="skip",
            ), row=row_idx, col=1, secondary_y=True)

        fig.update_yaxes(title_text=label, row=row_idx, col=1,
                         secondary_y=False, gridcolor=_GRID)
        fig.update_yaxes(title_text="Stratum %", row=row_idx, col=1,
                         secondary_y=True, range=[0, 115],
                         gridcolor="rgba(255,255,255,0.06)",
                         tickfont=dict(color="rgba(255,255,255,0.4)"))
        fig.update_xaxes(gridcolor=_GRID, row=row_idx, col=1)

    fig.update_layout(
        title="Physical Property Distributions: Stratum vs Other",
        barmode="overlay",
        height=280 * n,
        **_LAYOUT_BASE,
    )
    return fig


# ---------------------------------------------------------------------------
# 2D scatter plots for key property pairs
# ---------------------------------------------------------------------------

_SCATTER_PAIRS = [
    ("temp_k",    "mass_em",    "Temperature (K)",   "Mass (EM)"),
    ("temp_k",    "radius_km",  "Temperature (K)",   "Radius (km)"),
    ("temp_k",    "surface_pressure", "Temperature (K)", "Pressure (Pa)"),
    ("gravity_g", "mass_em",    "Gravity (g)",       "Mass (EM)"),
    ("gravity_g", "radius_km",  "Gravity (g)",       "Radius (km)"),
    ("mass_em",   "radius_km",  "Mass (EM)",         "Radius (km)"),
]


def _scatter_matrix(df: pd.DataFrame) -> go.Figure | None:
    """3x2 grid of key 2D scatter plots, coloured by status."""
    if df.empty:
        return None

    rows, cols = 3, 2
    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=[f"{xl} vs {yl}" for _, _, xl, yl in _SCATTER_PAIRS],
        vertical_spacing=0.10,
        horizontal_spacing=0.10,
    )

    for idx, (cx, cy, xl, yl) in enumerate(_SCATTER_PAIRS):
        r, c = divmod(idx, cols)
        r, c = r + 1, c + 1
        for status, col, name in [
            ("other",       _COL_OTHER,    "Other"),
            ("unconfirmed", _COL_UNKNOWN,  "Unconfirmed"),
            ("stratum",     _COL_STRATUM,  "Stratum"),
        ]:
            sub = df[df["status"] == status].dropna(subset=[cx, cy])
            if sub.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sub[cx], y=sub[cy], mode="markers",
                name=name, showlegend=(idx == 0),
                marker=dict(color=col, size=4, opacity=0.55),
                text=sub["body_name"],
                hovertemplate=(
                    f"<b>%{{text}}</b><br>"
                    f"{xl}: %{{x:.2f}}<br>{yl}: %{{y:.2f}}<extra>{name}</extra>"
                ),
            ), row=r, col=c)
        fig.update_xaxes(title_text=xl, gridcolor=_GRID, row=r, col=c)
        fig.update_yaxes(title_text=yl, gridcolor=_GRID, row=r, col=c)

    fig.update_layout(
        title="Physical Property Scatter Plots",
        height=900,
        **_LAYOUT_BASE,
    )
    return fig


# ---------------------------------------------------------------------------
# Binding energy proxy: G*M²/R vs surface temperature
# ---------------------------------------------------------------------------

_G  = 6.674e-11      # m³ kg⁻¹ s⁻²
_ME = 5.972e24       # kg (Earth mass)
_KM = 1_000.0        # m per km


def _binding_energy_chart(df: pd.DataFrame) -> go.Figure | None:
    """Scatter: gravitational binding energy proxy (G*M²/R) vs surface temperature."""
    import numpy as np

    d = df.dropna(subset=["mass_em", "radius_km", "temp_k"])
    d = d[d["radius_km"] > 0].copy()
    if d.empty:
        return None

    mass_kg = d["mass_em"] * _ME
    radius_m = d["radius_km"] * _KM
    d = d.copy()
    d["gm2r"] = _G * mass_kg ** 2 / radius_m

    fig = go.Figure()
    for status, col, name in [
        ("other",       _COL_OTHER,    "Other"),
        ("unconfirmed", _COL_UNKNOWN,  "Unconfirmed"),
        ("stratum",     _COL_STRATUM,  "Stratum"),
    ]:
        sub = d[d["status"] == status]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["temp_k"], y=sub["gm2r"],
            mode="markers", name=name,
            marker=dict(color=col, size=5, opacity=0.6),
            text=sub["body_name"],
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Temp: %{x:.0f} K<br>"
                "G·M²/R: %{y:.3e}<extra></extra>"
            ),
        ))

    fig.update_layout(
        title="Gravitational Binding Energy Proxy (G·M²/R) vs Surface Temperature",
        xaxis_title="Surface Temperature (K)",
        yaxis_title="G·M²/R  (J)",
        height=440,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, tickformat=".2e")
    return fig


# ---------------------------------------------------------------------------
# Star mass distribution
# ---------------------------------------------------------------------------

def _star_mass_chart(df: pd.DataFrame) -> go.Figure | None:
    """Histogram of parent star mass (solar masses) by status."""
    import numpy as np

    d = df.dropna(subset=["star_mass_sol"])
    if d.empty:
        return None

    # Bin width 0.2 solar masses, cap at 2.5
    d = d[d["star_mass_sol"] <= 2.5].copy()
    if d.empty:
        return None

    bins = np.arange(0, 2.7, 0.2)
    centers = (bins[:-1] + bins[1:]) / 2

    fig = go.Figure()
    for status, col, name in [
        ("other",   _COL_OTHER,   "Other"),
        ("stratum", _COL_STRATUM, "Stratum"),
    ]:
        sub = d[d["status"] == status]["star_mass_sol"].values
        if len(sub) == 0:
            continue
        counts, _ = np.histogram(sub, bins=bins)
        fig.add_trace(go.Bar(
            x=centers, y=counts, name=name,
            marker_color=col, opacity=0.78,
            width=0.17,
        ))

    fig.update_layout(
        title="Parent Star Mass Distribution (solar masses, 0.2 M☉ bins)",
        barmode="overlay",
        xaxis_title="Stellar Mass (M☉)",
        yaxis_title="Count",
        height=360,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    return fig


# ---------------------------------------------------------------------------
# Atmospheric He% distribution
# ---------------------------------------------------------------------------

def _he_distribution_chart(df: pd.DataFrame) -> go.Figure | None:
    """Histogram of system gas-giant He% (metallicity proxy, 0.1% bins) + Stratum rate overlay."""
    import numpy as np

    d = df[df["status"].isin(["stratum", "other"])].dropna(subset=["system_he_pct"])
    d = d[d["system_he_pct"] > 0]
    if d.empty:
        return None

    s_vals = d[d["status"] == "stratum"]["system_he_pct"].to_numpy(dtype=float)
    o_vals = d[d["status"] == "other"]["system_he_pct"].to_numpy(dtype=float)
    all_vals = np.concatenate([s_vals, o_vals])

    lo = max(0.0, all_vals.min() - 0.2)
    hi = all_vals.max() + 0.2
    bins = np.arange(lo, hi + 0.1, 0.1)
    centers = (bins[:-1] + bins[1:]) / 2

    s_counts, _ = np.histogram(s_vals, bins=bins)
    o_counts, _ = np.histogram(o_vals, bins=bins)
    total = s_counts + o_counts
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(total > 0, s_counts / total * 100, np.nan)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=centers, y=o_counts, name="Other genus",
        marker_color=_COL_OTHER, opacity=0.75, width=0.09,
        hovertemplate="He%%: %{x:.1f}<br>Other: %{y}<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=centers, y=s_counts, name="Stratum",
        marker_color=_COL_STRATUM, opacity=0.75, width=0.09,
        hovertemplate="He%%: %{x:.1f}<br>Stratum: %{y}<extra></extra>",
    ), secondary_y=False)

    mask = total > 0
    xm, ym = centers[mask], ratio[mask]
    fig.add_trace(go.Scatter(
        x=xm, y=ym, name="Stratum rate %",
        mode="markers", marker=dict(color=_COL_RATE, size=6),
        hovertemplate="Stratum rate: %{y:.1f}%<extra></extra>",
    ), secondary_y=True)
    if len(xm) >= 4:
        xs = np.linspace(xm.min(), xm.max(), 400)
        sigma = (xm.max() - xm.min()) * 0.08
        ys = np.array([
            np.average(ym, weights=np.exp(-0.5 * ((xm - xi) / sigma) ** 2))
            for xi in xs
        ])
        fig.add_trace(go.Scatter(
            x=xs, y=np.clip(ys, 0, 100), mode="lines", showlegend=False,
            line=dict(color="rgba(255,255,255,0.55)", width=1.5, dash="dot"),
            hoverinfo="skip",
        ), secondary_y=True)

    fig.update_layout(
        title="System Gas-Giant He% Distribution — metallicity proxy (scanned bodies, 0.1% bins)",
        barmode="overlay",
        xaxis_title="Avg He % of gas giants in system",
        yaxis_title="Count",
        xaxis=dict(range=[lo, hi]),
        height=420,
        **_LAYOUT_BASE,
    )
    fig.update_yaxes(title_text="Stratum rate (%)", secondary_y=True, range=[0, 115],
                     gridcolor="rgba(255,255,255,0.06)")
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, secondary_y=False)
    return fig


# ---------------------------------------------------------------------------
# Habitable zone context by star type
# ---------------------------------------------------------------------------

def _habitable_zone_chart(df: pd.DataFrame) -> go.Figure | None:
    """Box plot: orbital distance relative to HZ center, grouped by star type."""
    import numpy as np

    d = df.dropna(subset=["star_abs_mag", "semi_major_axis", "star_type"]).copy()
    d = d[d["semi_major_axis"] > 0].copy()
    if d.empty:
        return None

    # Luminosity from absolute magnitude → simplified HZ center (AU)
    # L/L_sun = 10^((M_sun_abs - M_abs) / 2.5),  M_sun_abs ≈ 4.83
    # HZ_center_AU ≈ sqrt(L/L_sun)
    d["_hz_au"] = np.sqrt(10.0 ** ((4.83 - d["star_abs_mag"]) / 2.5))
    d["hz_ratio"] = d["semi_major_axis"] / d["_hz_au"]

    scanned = d[d["status"].isin(["stratum", "other"])]
    if scanned.empty:
        return None

    top_types = (
        scanned.groupby("star_type").size()
        .sort_values(ascending=False).head(12).index.tolist()
    )
    scanned = scanned[scanned["star_type"].isin(top_types)].copy()
    # Order x-axis by descending count
    scanned["star_type"] = pd.Categorical(scanned["star_type"], categories=top_types, ordered=True)
    scanned = scanned.sort_values("star_type")

    fig = go.Figure()
    for status, col, name in [
        ("other",   _COL_OTHER,   "Other genus"),
        ("stratum", _COL_STRATUM, "Stratum"),
    ]:
        sub = scanned[scanned["status"] == status]
        if sub.empty:
            continue
        fig.add_trace(go.Box(
            x=sub["star_type"], y=sub["hz_ratio"],
            name=name, marker_color=col,
            boxpoints="outliers", opacity=0.85,
        ))

    fig.add_hline(
        y=1.0,
        line_dash="dot", line_color="rgba(255,255,255,0.25)",
        annotation_text="HZ centre", annotation_font_color="rgba(255,255,255,0.35)",
    )
    fig.update_layout(
        title="Orbital Distance / HZ Centre by Star Type (top 12 types, scanned bodies)",
        boxmode="group",
        xaxis_title="Star type",
        yaxis_title="Distance ÷ HZ centre (AU/AU)",
        height=460,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    return fig


# ---------------------------------------------------------------------------
# Primary vs companion star mass
# ---------------------------------------------------------------------------

def _star_mass_companion_chart(df: pd.DataFrame) -> go.Figure | None:
    """Scatter: system primary star mass vs body's parent star mass."""
    d = df.dropna(subset=["system_primary_mass_sol", "star_mass_sol"]).copy()
    if d.empty:
        return None

    fig = go.Figure()
    for status, col, name in [
        ("other",       _COL_OTHER,   "Other genus"),
        ("unconfirmed", _COL_UNKNOWN, "Unconfirmed"),
        ("stratum",     _COL_STRATUM, "Stratum"),
    ]:
        sub = d[d["status"] == status]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["system_primary_mass_sol"], y=sub["star_mass_sol"],
            mode="markers", name=name,
            marker=dict(color=col, size=5, opacity=0.65),
            text=sub["body_name"],
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Primary: %{x:.2f} M☉<br>"
                "Parent: %{y:.2f} M☉<extra></extra>"
            ),
        ))

    # Diagonal: body orbits the primary directly
    m = max(d["system_primary_mass_sol"].max(), d["star_mass_sol"].max()) * 1.05
    fig.add_trace(go.Scatter(
        x=[0, m], y=[0, m], mode="lines",
        line=dict(color="rgba(255,255,255,0.18)", dash="dot"),
        showlegend=False, hoverinfo="skip",
    ))
    fig.update_layout(
        title="System Primary Star Mass vs Parent Star Mass",
        xaxis_title="System primary star mass (M☉)",
        yaxis_title="Body's parent star mass (M☉)",
        height=460,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    return fig


# ---------------------------------------------------------------------------
# Terraform state chart
# ---------------------------------------------------------------------------

def _terraform_chart(df: pd.DataFrame) -> go.Figure | None:
    """Stratum rate by terraform state (terraformable vs not)."""
    def _tf_label(val) -> str:
        v = (val or "").strip().lower()
        if not v or v == "not terraformable":
            return "Not terraformable"
        if v == "terraformable":
            return "Terraformable"
        return val.strip()

    d = df.copy()
    d["tf_label"] = d["terraform_state"].apply(_tf_label)
    grp = (
        d.groupby("tf_label")["status"]
        .value_counts()
        .unstack(fill_value=0)
    )
    for col in ("stratum", "other", "unconfirmed"):
        if col not in grp.columns:
            grp[col] = 0

    grp["scanned"] = grp["stratum"] + grp["other"]
    grp["rate"] = grp.apply(
        lambda r: r["stratum"] / r["scanned"] * 100 if r["scanned"] > 0 else None, axis=1
    )
    grp = grp.sort_values("scanned", ascending=False)
    if grp.empty:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["stratum"],
        name="Stratum", marker_color=_COL_STRATUM, opacity=0.85,
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["other"],
        name="Other genus", marker_color=_COL_OTHER, opacity=0.85,
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=grp.index, y=grp["unconfirmed"],
        name="Unconfirmed", marker_color=_COL_UNKNOWN, opacity=0.6,
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=grp.index, y=grp["rate"],
        name="Stratum rate %", mode="markers+text+lines",
        marker=dict(color=_COL_RATE, size=8),
        line=dict(color="rgba(255,255,255,0.2)", width=1.5, dash="dot"),
        text=[f"{v:.1f}%" if v is not None else "" for v in grp["rate"]],
        textposition="top center",
        textfont=dict(color=_COL_RATE, size=9),
        hovertemplate="%{y:.1f}%<extra>Stratum rate</extra>",
    ), secondary_y=True)
    fig.update_layout(
        title="Terraform State vs Stratum Confirmation",
        barmode="stack",
        yaxis_title="Body count",
        height=360,
        **_LAYOUT_BASE,
    )
    fig.update_yaxes(title_text="Stratum rate (%)", secondary_y=True, range=[0, 115],
                     gridcolor="rgba(255,255,255,0.06)")
    fig.update_xaxes(gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, secondary_y=False)
    return fig


# ---------------------------------------------------------------------------
# Correlation matrices
# ---------------------------------------------------------------------------

_CORR_COLS = [
    ("temp_k",          "Temp (K)"),
    ("gravity_g",       "Gravity (g)"),
    ("mass_em",         "Mass (EM)"),
    ("radius_km",       "Radius (km)"),
    ("surface_pressure","Pressure (Pa)"),
    ("star_mass_sol",   "Star mass (M☉)"),
    ("star_age_my",     "Star age (MY)"),
    ("semi_major_axis", "Semi-major axis"),
]


def _correlation_matrix(df: pd.DataFrame) -> go.Figure | None:
    """Three Pearson correlation heatmaps: Other, Stratum, and Stratum−Other diff."""
    import numpy as np

    cols   = [c for c, _ in _CORR_COLS]
    labels = [l for _, l in _CORR_COLS]

    s_df = df[df["status"] == "stratum"][cols].dropna(how="all")
    o_df = df[df["status"] == "other"][cols].dropna(how="all")
    if s_df.empty or o_df.empty:
        return None

    s_corr = s_df.corr().values
    o_corr = o_df.corr().values
    d_corr = s_corr - o_corr

    colorscale = [
        [0.0,  "#c0392b"],
        [0.25, "#e07060"],
        [0.5,  "#0f0f2a"],
        [0.75, "#6090c0"],
        [1.0,  "#2255cc"],
    ]

    # Layout: 2 rows × 2 columns.
    # Row 1: Other | Stratum  (each half-width — same as before)
    # Row 2: Diff spanning both columns (full-width, visually centred)
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=["Other genus", "Stratum", "Stratum − Other"],
        specs=[
            [{}, {}],
            [{"colspan": 2}, None],
        ],
        vertical_spacing=0.14,
        horizontal_spacing=0.12,
    )

    for (corr, title, zmin, zmax, tmpl, row, col) in [
        (o_corr, "Other genus",     -1.0, 1.0,  "%{text:.2f}",  1, 1),
        (s_corr, "Stratum",         -1.0, 1.0,  "%{text:.2f}",  1, 2),
        (d_corr, "Stratum − Other", -0.5, 0.5,  "%{text:+.2f}", 2, 1),
    ]:
        is_diff = row == 2
        fig.add_trace(go.Heatmap(
            z=corr,
            x=labels, y=labels,
            colorscale=colorscale,
            zmid=0, zmin=zmin, zmax=zmax,
            text=np.round(corr, 2),
            texttemplate=tmpl,
            textfont=dict(size=9),
            showscale=is_diff,
            colorbar=dict(x=1.02, thickness=14, len=0.45, y=0.22, title="Δr") if is_diff else None,
            hovertemplate="%{y} × %{x}: %{z:.3f}<extra>" + title + "</extra>",
        ), row=row, col=col)

    fig.update_layout(
        title="Property Correlation Matrices (Pearson r) — diff colour scale ±0.5",
        height=900,
        **_LAYOUT_BASE,
    )
    fig.update_xaxes(tickangle=-40, gridcolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID)
    return fig


# ---------------------------------------------------------------------------
# Candidate table
# ---------------------------------------------------------------------------

def _candidates_table(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.iterrows():
        status = r["status"]
        if status == "stratum":
            cls = "stratum"
            status_txt = r["confirmed_genus"] or "Stratum"
        elif status == "other":
            if r.get("is_oddity"):
                cls = "unknown"
                status_txt = (r["confirmed_genus"] or "Other") + " ⚠"
            else:
                cls = "other"
                status_txt = r["confirmed_genus"] or "Other"
        else:
            cls = "unknown"
            status_txt = "—"

        sa  = r["system_address"]
        tf  = (r.get("terraform_state") or "").strip().lower()
        tf_txt = "✓" if tf and tf not in ("", "not terraformable") else "—"
        mapped_txt = "✓" if r.get("was_mapped") else "—"
        rows.append(
            f'<tr>'
            f'<td><span class="sys-link" data-sa="{sa}">{_esc(r["system_name"])}</span></td>'
            f'<td><span class="sys-link" data-sa="{sa}">{_esc(r["body_name"])}</span></td>'
            f'<td class="num">{_fmt(r["temp_k"], 0)}</td>'
            f'<td class="num">{_fmt(r["gravity_g"], 3)}</td>'
            f'<td class="num">{_fmt(r["mass_em"], 3)}</td>'
            f'<td class="num">{_fmt(r["radius_km"], 0)}</td>'
            f'<td>{_esc(r["atmosphere_type"] or "—")}</td>'
            f'<td>{_esc("Barycentre" if pd.isna(r["star_type"]) else r["star_type"] or "—")}</td>'
            f'<td class="num">{tf_txt}</td>'
            f'<td class="num">{mapped_txt}</td>'
            f'<td class="{cls}">{_esc(status_txt)}</td>'
            f'</tr>'
        )

    return (
        '<div class="table-wrap"><div class="table-scroll">'
        '<table class="sortable">'
        '<thead><tr>'
        '<th>System</th><th>Body</th>'
        '<th>Temp (K)</th><th>Gravity (g)</th>'
        '<th>Mass (EM)</th><th>Radius (km)</th>'
        '<th>Atmosphere</th><th>Star type</th>'
        '<th>Terraform</th><th>Mapped</th>'
        '<th>Status</th>'
        '</tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody>'
        '</table></div></div>'
    )


# ---------------------------------------------------------------------------
# Species breakdown table (confirmed scans only)
# ---------------------------------------------------------------------------

def _species_table(df: pd.DataFrame) -> str:
    scanned = df[df["status"] != "unconfirmed"].dropna(subset=["confirmed_genus"])
    if scanned.empty:
        return "<p style='color:#445566;font-style:italic'>No completed scans in database.</p>"

    counts = (
        scanned.groupby("confirmed_genus")
        .agg(count=("confirmed_genus", "size"), is_oddity=("is_oddity", "any"))
        .reset_index()
        .sort_values("count", ascending=False)
    )

    rows = []
    for _, r in counts.iterrows():
        g = str(r["confirmed_genus"])
        if "stratum" in g.lower():
            cls, suffix = "stratum", ""
        elif r["is_oddity"]:
            cls, suffix = "unknown", " <em style='font-size:0.8em;color:#667788'>(oddity)</em>"
        else:
            cls, suffix = "other", ""
        rows.append(
            f'<tr>'
            f'<td class="{cls}">{_esc(g)}{suffix}</td>'
            f'<td class="num">{r["count"]}</td>'
            f'</tr>'
        )

    return (
        '<table>'
        '<thead><tr><th>Genus</th><th>Count</th></tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody>'
        '</table>'
    )


# ---------------------------------------------------------------------------
# Oddities table
# ---------------------------------------------------------------------------

def _oddities_table(df: pd.DataFrame) -> str:
    odd = df[df["is_oddity"]].copy()
    if odd.empty:
        return "<p style='color:#445566;font-style:italic'>No oddities found.</p>"

    rows = []
    for _, r in odd.iterrows():
        sa  = r["system_address"]
        tf  = (r.get("terraform_state") or "").strip().lower()
        tf_txt = "✓" if tf and tf not in ("", "not terraformable") else "—"
        rows.append(
            f'<tr>'
            f'<td><span class="sys-link" data-sa="{sa}">{_esc(r["system_name"])}</span></td>'
            f'<td><span class="sys-link" data-sa="{sa}">{_esc(r["body_name"])}</span></td>'
            f'<td class="unknown">{_esc(r["confirmed_genus"] or r["confirmed_species"] or r["any_scan_species"] or "—")}</td>'
            f'<td class="num">{_fmt(r["temp_k"], 0)}</td>'
            f'<td class="num">{_fmt(r["gravity_g"], 3)}</td>'
            f'<td class="num">{_fmt(r["mass_em"], 3)}</td>'
            f'<td>{_esc(r["atmosphere_type"] or "—")}</td>'
            f'<td>{_esc("Barycentre" if pd.isna(r["star_type"]) else r["star_type"] or "—")}</td>'
            f'<td class="num">{tf_txt}</td>'
            f'</tr>'
        )

    return (
        '<div class="table-wrap">'
        '<table class="sortable">'
        '<thead><tr>'
        '<th>System</th><th>Body</th><th>Confirmed genus</th>'
        '<th>Temp (K)</th><th>Gravity (g)</th><th>Mass (EM)</th>'
        '<th>Atmosphere</th><th>Star type</th><th>Terraform</th>'
        '</tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody>'
        '</table></div>'
    )


# ---------------------------------------------------------------------------
# Export / aggregation helpers
# ---------------------------------------------------------------------------

def _get_commander_name(conn: sqlite3.Connection) -> str | None:
    """Return the most recently recorded commander name, or None."""
    row = conn.execute(
        "SELECT name FROM commander_snapshots "
        "WHERE name IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _safe_filename(name: str) -> str:
    """Strip characters that are invalid in filenames."""
    return _re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def export_candidates(
    conn: sqlite3.Connection,
    out_path: Path,
    min_temp: float = 165.0,
    max_temp: float | None = None,
) -> None:
    """Export filtered candidates to a JSONL file for cross-commander aggregation."""
    df, _ = _load_data(conn, min_temp=min_temp, max_temp=max_temp)
    out_path.write_text(df.to_json(orient="records", lines=True), encoding="utf-8")
    print(f"  Exported {len(df):,} candidates to {out_path}")


def _load_from_jsonl(paths: list[Path]) -> pd.DataFrame:
    """Load and deduplicate candidates from one or more JSONL export files."""
    frames = [pd.read_json(p, lines=True) for p in paths]
    df = pd.concat(frames, ignore_index=True)

    # Prefer confirmed over unconfirmed when deduplicating
    priority = {"stratum": 0, "other": 1, "unconfirmed": 2}
    df["_prio"] = df["status"].map(priority).fillna(3)
    df = (
        df.sort_values("_prio")
          .drop_duplicates(subset=["system_address", "body_id"])
          .drop(columns=["_prio"])
          .reset_index(drop=True)
    )
    return df


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_stratum_report(
    conn: sqlite3.Connection,
    out_path: Path,
    min_temp: float = 165.0,
    max_temp: float | None = None,
) -> None:
    """Build and write a self-contained HTML Stratum research report."""

    print("  Loading candidates...")
    df, mat = _load_data(conn, min_temp=min_temp, max_temp=max_temp)
    print(f"  {len(df):,} candidates found.")

    n_stratum = (df["status"] == "stratum").sum()
    n_other   = (df["status"] == "other").sum()
    print(f"  {n_stratum} confirmed Stratum, {n_other} confirmed other genus.")

    if df.empty:
        print("  No data — report will be empty.")

    # Auto-export JSONL for cross-commander aggregation
    cmdr = _get_commander_name(conn)
    cmdr_slug = _safe_filename(cmdr) if cmdr else "unknown"
    jsonl_path = out_path.parent / f"stratum_candidates_{cmdr_slug}.jsonl"
    df.to_json(jsonl_path, orient="records", lines=True)
    print(f"  Candidates exported to {jsonl_path.name}")

    print("  Loading system diagram data...")
    sys_addrs = df["system_address"].dropna().astype(int).unique().tolist()
    diagram_data = _system_diagram_data(conn, sys_addrs)
    sys_data_js = "var SYSTEM_DATA = " + json.dumps(diagram_data, separators=(",", ":")) + ";"

    subtitle = (
        f"HMC bodies · 1 bio signal · surface pressure &lt; 10 kPa · "
        f"{_temp_range_label(min_temp, max_temp)}"
    )
    _build_report(df, mat, out_path, subtitle,
                  modal_js_prefix=f'<script>{sys_data_js}</script>')


def build_stratum_report_from_files(
    jsonl_paths: list[Path],
    out_path: Path,
) -> None:
    """Build a Stratum report from one or more JSONL candidate exports (no DB needed)."""
    print(f"  Loading {len(jsonl_paths)} export file(s)...")
    df = _load_from_jsonl(jsonl_paths)
    mat = pd.DataFrame()   # materials not exported — chart will be skipped

    n_stratum = (df["status"] == "stratum").sum()
    n_other   = (df["status"] == "other").sum()
    print(f"  {len(df):,} candidates after deduplication "
          f"({n_stratum} Stratum, {n_other} other).")

    subtitle = (
        f"Aggregated from {len(jsonl_paths)} commander export(s) · "
        f"HMC bodies · 1 bio signal · surface pressure &lt; 10 kPa"
    )
    _build_report(df, mat, out_path, subtitle,
                  modal_js_prefix='<script>var SYSTEM_DATA = {};</script>')


def _build_report(
    df: pd.DataFrame,
    mat: pd.DataFrame,
    out_path: Path,
    subtitle: str,
    modal_js_prefix: str,
) -> None:
    """Shared report-building logic used by both DB and file-based entry points."""
    print("  Building charts...")
    first = True

    def c(fig: go.Figure | None) -> str:
        nonlocal first
        if fig is None:
            return ""
        html = _chart(fig, first=first)
        first = False
        return html

    chart_df = df[~df["is_oddity"]].copy()

    fig_atm      = _atm_type_chart(chart_df)
    fig_scatter  = _physical_scatter(chart_df)
    fig_boxes    = _mass_gravity_chart(chart_df)
    fig_dists    = _distribution_plots(chart_df)
    fig_corr     = _correlation_matrix(chart_df)
    fig_scatmat  = _scatter_matrix(chart_df)
    fig_gm2r     = _binding_energy_chart(chart_df)
    fig_star     = _star_type_chart(chart_df)
    fig_age      = _star_age_chart(chart_df)
    fig_starmass = _star_mass_chart(chart_df)
    fig_he       = _he_distribution_chart(chart_df)
    fig_hz       = _habitable_zone_chart(chart_df)
    fig_companion = _star_mass_companion_chart(chart_df)
    fig_terraform = _terraform_chart(chart_df)
    fig_mat      = _materials_chart(chart_df, mat)

    sections = [
        _section("Summary", _summary_cards(df)),
        _section("Confirmed Genera", _species_table(df)),
        _section("Atmosphere Type", c(fig_atm)),
        _section("Atmospheric Helium %", c(fig_he)),
        _section("Property Distributions", c(fig_dists)),
        _section("Correlation Matrices", c(fig_corr)),
        _section("Gravity vs Temperature", c(fig_scatter)),
        _section("Property Scatter Plots", c(fig_scatmat)),
        _section("Binding Energy Proxy", c(fig_gm2r)),
        _section("Physical Properties (box)", c(fig_boxes)),
        _section("Parent Star Type", c(fig_star)),
        _section("Parent Star Age", c(fig_age)),
        _section("Parent Star Mass", c(fig_starmass)),
        _section("Habitable Zone Context", c(fig_hz)),
        _section("Primary vs Companion Star Mass", c(fig_companion)),
        _section("Terraform State", c(fig_terraform)),
        _section("Surface Materials", c(fig_mat)),
        _section("All Candidates", _candidates_table(df)),
        _section("Oddities (excluded from charts)", _oddities_table(df)),
    ]

    modal_js = (
        modal_js_prefix
        + f'\n<script>{_SYS_MODAL_JS}\n}}());</script>'
    )

    body = (
        _SYS_MODAL_HTML + "\n"
        + '<header>'
        '<h1>Stratum Tectonicas Research Report</h1>'
        f'<div class="subtitle">{subtitle}</div>'
        '</header>'
        f'<div class="content">{"".join(sections)}</div>'
    )

    html = _html_doc("Stratum Report", body, extra_js=modal_js + "\n" + _SORT_JS)
    out_path.write_text(html, encoding="utf-8")
    print(f"  Saved: {out_path}")
