"""
HTML trip report builder.

Produces a self-contained dark-theme HTML file summarising an expedition:
  - Key stats overview
  - Interactive 3D route map
  - Earnings timeline (daily bar + cumulative line)
  - Exobiology breakdown
  - Planet types breakdown
  - Personal bests
  - Full system list (scrollable, sortable, with system diagram modal)
"""

from __future__ import annotations

import base64
import json
import re as _re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import stats as st
from . import maps as mp
from .dashboard import _SYS_MODAL_CSS, _SYS_MODAL_JS, _SYS_MODAL_HTML


# ---------------------------------------------------------------------------
# Powerplay conversion rates (credits → merits / control points)
# Derived from in-game research; applied to estimated credit values.
# ---------------------------------------------------------------------------

_PP_EXOBIO_MERIT_RATE = 107_000   # Cr per merit from exobiology
_PP_EXOBIO_CP_RATE    = 222_000   # Cr per control point from exobiology
_PP_EXPL_MERIT_RATE   =   8_200   # Cr per merit from exploration
_PP_EXPL_CP_RATE      =  17_000   # Cr per control point from exploration


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _cr(n) -> str:
    n = float(n) if n else 0.0
    if n >= 1e9:
        return f'<span class="val-bcr">{n/1e9:.2f} BCr</span>'
    if n >= 1e6:
        return f'<span class="val-mcr">{n/1e6:.2f} MCr</span>'
    if n >= 1e3:
        return f'<span class="val-kcr">{n/1e3:.0f} KCr</span>'
    return f"{int(n):,}"


def _n(n) -> str:
    return f"{int(n):,}"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _overview_cards(data: dict) -> str:
    items = [
        ("Systems",        _n(data["systems_visited"])),
        ("Jumps",          _n(data["jumps"])),
        ("Ly travelled",   f'{data["ly_travelled"]:,.0f}'),
        ("Bodies scanned", _n(data["bodies_scanned"])),
        ("Bodies mapped",  _n(data["bodies_mapped"])),
        ("First disc.",    _n(data["first_discoveries"])),
        ("Bio bodies",     _n(data["bio_signals_bodies"])),
        ("Exobio scans",   _n(data["organic_scans_done"])),
        ("Species",        _n(data["species_unique"])),
    ]
    cards = "".join(
        f'<div class="stat-card">'
        f'<div class="stat-val">{val}</div>'
        f'<div class="stat-label">{lbl}</div>'
        f'</div>'
        for lbl, val in items
    )
    return f'<div class="stat-row">{cards}</div>'


def _plotly_div(fig: go.Figure, first: bool = False) -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if first else False,
        config={"responsive": True},
    )


def _earnings_timeline_fig(df: pd.DataFrame,
                           exobio_bonus: float = 0.0,
                           expl_bonus: float = 0.0) -> go.Figure | None:
    if df.empty:
        return None

    fig = make_subplots(
        rows=2, cols=1,
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
        row_heights=[0.62, 0.38],
        shared_xaxes=True,
        vertical_spacing=0.10,
    )

    # --- Row 1: absolute earnings ---
    fig.add_trace(go.Bar(
        x=df["day"], y=df["exploration"],
        name="Exploration", marker_color="#4488cc", opacity=0.85,
        hovertemplate="Exploration: %{y:,.0f} Cr<extra></extra>",
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Bar(
        x=df["day"], y=df["exobiology"],
        name="Exobiology", marker_color="#44cc88", opacity=0.85,
        hovertemplate="Exobiology: %{y:,.0f} Cr<extra></extra>",
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df["day"], y=df["cumulative"],
        name="Cumulative", mode="lines",
        line=dict(color="#ffcc44", width=2, dash="dot"),
        hovertemplate="Cumulative: %{y:,.0f} Cr<extra></extra>",
    ), row=1, col=1, secondary_y=True)

    # --- Row 2: Cr/hour (session-normalised) ---
    hover_hr = df["session_hours"].apply(
        lambda h: f"{h:.1f}h" if h >= 1 else f"{h*60:.0f}min"
    )
    fig.add_trace(go.Bar(
        x=df["day"],
        y=df["cr_per_hour"],
        name="Cr / hour",
        marker_color="#cc88ff", opacity=0.85,
        customdata=hover_hr,
        hovertemplate="Cr/h: %{y:,.0f}  (session: %{customdata})<extra></extra>",
    ), row=2, col=1)

    roll_mean = df["cr_per_hour"].rolling(window=3, center=True, min_periods=1).mean()
    fig.add_trace(go.Scatter(
        x=df["day"], y=roll_mean,
        name="3-day avg", mode="lines",
        line=dict(color="#ffcc44", width=2),
        hovertemplate="3-day avg: %{y:,.0f} Cr/h<extra></extra>",
    ), row=2, col=1)

    overall_avg = df["total"].sum() / max(df["session_hours"].sum(), 1 / 60)
    fig.add_hline(
        y=overall_avg, row=2, col=1,
        line=dict(color="#ffffff", width=1, dash="dot"),
        annotation_text=f"avg {_re.sub(r'<[^>]+>', '', _cr(overall_avg))}/h",
        annotation_position="top right",
        annotation_font=dict(color="#aaaaaa", size=11),
    )

    total = int(df["total"].sum())
    total_str = _re.sub(r"<[^>]+>", "", _cr(total))
    notes = ["exploration + exobio", "exobio: first-log ×5"]
    if exobio_bonus:
        notes.append(f"+{exobio_bonus*100:.0f}% Antal")
    if expl_bonus:
        notes.append(f"+{expl_bonus*100:.0f}% LYR expl.")

    fig.update_layout(
        title=dict(
            text=f"Estimated Earnings — {total_str} total ({', '.join(notes)})",
            font=dict(color="white"),
        ),
        barmode="stack",
        paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a", font_color="white",
        legend=dict(bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
        hovermode="x unified",
        margin=dict(l=60, r=60, t=50, b=40),
        height=520,
    )
    fig.update_xaxes(gridcolor="#222244")
    fig.update_yaxes(gridcolor="#222244")
    fig.update_yaxes(title_text="Cr / day",        row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Cumulative Cr",    row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Cr / active hour", row=2, col=1)
    fig.update_xaxes(title_text="Date",             row=2, col=1)
    return fig


def _powerplay_fig(df: pd.DataFrame) -> go.Figure | None:
    """
    Two-row chart:
      Row 1 — daily merits stacked bars (exploration + exobiology) with
              cumulative merits AND cumulative CPs on the secondary y-axis.
      Row 2 — merits per active hour bars with 3-day rolling average line
              and overall-average hline.
    """
    if df.empty:
        return None

    df = df.copy()
    df["merit_expl"]   = df["exploration"] / _PP_EXPL_MERIT_RATE
    df["merit_exobio"] = df["exobiology"]  / _PP_EXOBIO_MERIT_RATE
    df["merit_total"]  = df["merit_expl"] + df["merit_exobio"]
    df["merit_cum"]    = df["merit_total"].cumsum()

    df["cp_total"] = (
        df["exploration"] / _PP_EXPL_CP_RATE
        + df["exobiology"] / _PP_EXOBIO_CP_RATE
    )
    df["cp_cum"] = df["cp_total"].cumsum()

    active_hours = df["session_hours"].replace(0, float("nan"))
    df["merit_per_hour"] = df["merit_total"] / active_hours
    df["cp_per_hour"]    = df["cp_total"]    / active_hours

    total_merits = df["merit_total"].sum()
    total_cps    = df["cp_total"].sum()
    total_hours  = max(df["session_hours"].sum(), 1 / 60)
    merits_per_h = total_merits / total_hours
    cps_per_h    = total_cps    / total_hours

    rolling_avg     = df["merit_per_hour"].rolling(3, min_periods=1).mean()
    overall_avg     = df["merit_per_hour"].mean()
    overall_avg_cp  = df["cp_per_hour"].mean()

    fig = make_subplots(
        rows=2, cols=1,
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
        row_heights=[0.62, 0.38],
        shared_xaxes=True,
        vertical_spacing=0.12,
    )

    # ── Row 1: Merits / day ───────────────────────────────────────────────────
    fig.add_trace(go.Bar(
        x=df["day"], y=df["merit_expl"],
        name="Merits (exploration)", marker_color="#4488cc", opacity=0.85,
        hovertemplate="Expl merits: %{y:,.0f}<extra></extra>",
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Bar(
        x=df["day"], y=df["merit_exobio"],
        name="Merits (exobiology)", marker_color="#44cc88", opacity=0.85,
        hovertemplate="Exobio merits: %{y:,.0f}<extra></extra>",
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df["day"], y=df["merit_cum"],
        name="Cumulative merits", mode="lines",
        line=dict(color="#ffcc44", width=2, dash="dot"),
        hovertemplate="Cumulative merits: %{y:,.0f}<extra></extra>",
    ), row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(
        x=df["day"], y=df["cp_cum"],
        name="Cumulative CPs", mode="lines",
        line=dict(color="#ff88aa", width=2, dash="dot"),
        hovertemplate="Cumulative CPs: %{y:,.0f}<extra></extra>",
    ), row=1, col=1, secondary_y=True)

    # ── Row 2: Merits / active hour ───────────────────────────────────────────
    fig.add_trace(go.Bar(
        x=df["day"], y=df["merit_per_hour"],
        name="Merits / hour", marker_color="#6688bb", opacity=0.75,
        showlegend=True,
        hovertemplate="Merits/h: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=df["day"], y=rolling_avg,
        name="3-day avg (merits/h)", mode="lines",
        line=dict(color="#ffcc44", width=2),
        hovertemplate="3-day avg: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    fig.add_hline(
        y=overall_avg, row=2, col=1,
        line=dict(color="#ffcc44", width=1, dash="dash"),
        annotation_text=f"avg {overall_avg:,.0f} merits/h",
        annotation_position="top right",
        annotation_font_color="#ffcc44",
    )
    fig.add_hline(
        y=overall_avg_cp, row=2, col=1,
        line=dict(color="#ff8844", width=1, dash="dash"),
        annotation_text=f"avg {overall_avg_cp:,.0f} CPs/h",
        annotation_position="bottom right",
        annotation_font_color="#ff8844",
    )

    fig.update_layout(
        title=dict(
            text=(
                f"Powerplay — "
                f"{total_merits:,.0f} merits ({merits_per_h:,.0f}/h)"
                f"  ·  "
                f"{total_cps:,.0f} control points ({cps_per_h:,.0f}/h)"
            ),
            font=dict(color="white"),
        ),
        barmode="stack",
        paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a", font_color="white",
        legend=dict(bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
        hovermode="x unified",
        margin=dict(l=60, r=80, t=50, b=40),
        height=480,
    )
    fig.update_xaxes(gridcolor="#222244")
    fig.update_yaxes(gridcolor="#222244")
    fig.update_yaxes(title_text="Merits / day",      row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Cumulative",         row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Merits / active hour", row=2, col=1)
    fig.update_xaxes(title_text="Date", row=2, col=1)
    return fig


def _exobio_table(est: dict, exobio_bonus: float = 0.0) -> str:
    df = est["organic_species"]
    if df.empty:
        return '<p class="empty">No organic scans.</p>'

    show_bonus = exobio_bonus > 0
    total_qty = total_base = total_fl = total_bonus = 0
    rows = []
    for _, r in df.iterrows():
        qty      = int(r["qty"])
        base_val = float(r["base_total"])          # qty × base_per
        fl_val   = base_val * 5                    # × first-log
        bon_val  = fl_val * (1 + exobio_bonus)
        total_qty   += qty
        total_base  += base_val
        total_fl    += fl_val
        total_bonus += bon_val
        cells = (
            f'<td class="num">{qty:,}</td>'
            f"<td>{r['species']}</td>"
            f'<td class="num">{_cr(base_val)}</td>'
            f'<td class="num">{_cr(fl_val)}</td>'
        )
        if show_bonus:
            cells += f'<td class="num">{_cr(bon_val)}</td>'
        rows.append(f"<tr>{cells}</tr>")

    foot_cells = (
        f'<td class="num">{total_qty:,}</td>'
        f'<td></td>'
        f'<td class="num">{_cr(total_base)}</td>'
        f'<td class="num">{_cr(total_fl)}</td>'
    )
    if show_bonus:
        foot_cells += f'<td class="num">{_cr(total_bonus)}</td>'
    tfoot = f'<tfoot><tr class="total-row">{foot_cells}</tr></tfoot>'

    bonus_pct = f"+{exobio_bonus*100:.0f}% Antal" if show_bonus else ""
    bonus_hdr = f"<th>Total (incl. {bonus_pct})</th>" if show_bonus else ""
    return (
        '<div class="table-wrap"><table class="sortable">'
        "<thead><tr>"
        f"<th>Qty</th><th>Species</th><th>Base Value</th><th>With first-log (×5)</th>{bonus_hdr}"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"{tfoot}"
        "</table></div>"
        "<p style='margin-top:6px;font-size:0.78rem;color:#556677'>"
        "×5 assumes first discovery — may not apply to all samples.</p>"
    )


def _planet_table(bodies: pd.DataFrame) -> str:
    if bodies.empty:
        return '<p class="empty">No planet scans.</p>'
    rows = "".join(
        f"<tr>"
        f"<td>{r['planet_group']}</td>"
        f'<td class="num">{int(r["count"]):,}</td>'
        f'<td class="num">{int(r["first_disc"]):,}</td>'
        f'<td class="num">{int(r["mapped"]):,}</td>'
        f'<td class="num">{int(r["first_mapped"]):,}</td>'
        f"</tr>"
        for _, r in bodies.iterrows()
    )
    return (
        '<div class="table-wrap"><table class="sortable">'
        "<thead><tr><th>Planet type</th><th>Scanned</th>"
        "<th>1st disc.</th><th>Mapped</th><th>1st map</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _records_table(records: pd.DataFrame) -> str:
    if records.empty:
        return '<p class="empty">No body scan data in this range.</p>'
    rows = "".join(
        f"<tr><td>{r['Record']}</td>"
        f"<td><span class='sys-link' data-sa='{r['system_address']}'>{r['Body / System']}</span></td>"
        f'<td class="num">{r["Value"]:,.3f} {r["Unit"]}</td></tr>'
        for _, r in records.iterrows()
    )
    return (
        '<div class="table-wrap"><table class="sortable">'
        "<thead><tr><th>Record</th><th>Body / System</th><th>Value</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _systems_table(sys_df: pd.DataFrame) -> str:
    if sys_df.empty:
        return '<p class="empty">No jump data.</p>'
    rows = "".join(
        f"<tr>"
        f"<td>{str(r['timestamp'])[:19].replace('T',' ')}</td>"
        f"<td><span class='sys-link' data-sa='{r['system_address']}'>{r['name']}</span></td>"
        f"<td>{r['star_class'] or '?'}</td>"
        f'<td class="num">{(r["jump_dist"] or 0):.2f}</td>'
        f'<td class="num">{int(r["bodies_scanned"])}</td>'
        f'<td class="num">{int(r["first_disc"])}</td>'
        f'<td class="num">{int(r["bio_bodies"])}</td>'
        f'<td class="num">{int(r["bio_signals"])}</td>'
        f"</tr>"
        for _, r in sys_df.iterrows()
    )
    return (
        '<div class="table-wrap table-scroll"><table class="sortable">'
        "<thead><tr><th>Timestamp</th><th>System</th><th>Star class</th>"
        "<th>Dist (ly)</th><th>Bodies</th><th>1st disc</th>"
        "<th>Bio bodies</th><th>Bio signals</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


# ---------------------------------------------------------------------------
# Favicon — route-themed SVG, embedded as a data URI
# ---------------------------------------------------------------------------

_FAVICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <polyline points="4,28 10,16 16,22 22,8 28,14"
    fill="none" stroke="#4488cc" stroke-width="2.2"
    stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="4"  cy="28" r="2.4" fill="#44cc88"/>
  <circle cx="10" cy="16" r="1.8" fill="#88aaff"/>
  <circle cx="16" cy="22" r="1.8" fill="#88aaff"/>
  <circle cx="22" cy="8"  r="1.8" fill="#88aaff"/>
  <circle cx="28" cy="14" r="2.8" fill="#ffcc44"/>
  <circle cx="28" cy="14" r="4.5" fill="none" stroke="#ffcc44" stroke-width="0.8" opacity="0.5"/>
</svg>"""

_FAVICON_HREF = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(_FAVICON_SVG.encode()).decode()
)


# ---------------------------------------------------------------------------
# CSS / HTML frame
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0a0a1a; color: #ccccdd;
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 14px; line-height: 1.5;
}
h1 { font-size: 1.5rem; color: #aabbee; margin-bottom: 4px; }
h2 { font-size: 1.05rem; color: #8899bb; margin-bottom: 12px;
     border-bottom: 1px solid #222244; padding-bottom: 6px; }
.subtitle { color: #667788; font-size: 0.85rem; margin-bottom: 24px; }
header { padding: 24px 32px 16px; border-bottom: 1px solid #1a1a33; }
.content { padding: 24px 32px; max-width: 1400px; }
section { margin-bottom: 36px; }

/* stat cards */
.stat-row { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; }
.stat-card {
  background: #0f0f2a; border: 1px solid #222244;
  border-radius: 6px; padding: 12px 18px; min-width: 110px; text-align: center;
}
.stat-val { font-size: 1.25rem; font-weight: 600; color: #aaccff; }
.stat-label { font-size: 0.72rem; color: #667799; margin-top: 2px; }

/* tables */
.table-wrap { overflow-x: auto; }
.table-scroll { max-height: 60vh; overflow-y: auto; }
.table-scroll thead th {
  position: sticky; top: 0; z-index: 2;
  background: #111133;
}
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
tr.total-row td { background: #111133; font-weight: 600; color: #aabbee;
                  border-top: 1px solid #333366; }

/* credit value spans */
.val-bcr { color: #ffcc44; }
.val-mcr { color: #ff9944; }
.val-kcr { color: #88ddff; }

.empty { color: #445566; font-style: italic; padding: 8px 0; }
.pp-badge { display: inline-block; margin-top: 6px; padding: 3px 10px;
            background: #0f0f2a; border: 1px solid #2a2a55;
            border-radius: 4px; font-size: 0.78rem; color: #8899cc; }

/* plotly chart containers */
.chart-wrap { background: #0a0a1a; border-radius: 6px;
              border: 1px solid #1a1a33; overflow: hidden; }
.map-nav-hint {
  font-size: 0.72rem; color: #3a4a60; margin-top: 6px; padding: 0 2px;
  user-select: none;
}
.map-nav-hint kbd {
  display: inline-block; padding: 0 5px; border: 1px solid #1a2040;
  border-radius: 3px; font-size: 0.9em; background: #0c0c22; color: #5a6888;
  font-family: inherit;
}
"""


def _html_doc(title: str, body: str, extra_css: str = "", extra_js: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="icon" type="image/svg+xml" href="{_FAVICON_HREF}">
<style>{_CSS}{extra_css}</style>
</head>
<body>
{body}
{extra_js}
</body>
</html>"""


def _section(heading: str, content: str) -> str:
    return f'<section><h2>{heading}</h2>{content}</section>'


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

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
        var sampleCell = tbody.querySelector('tr:not(.total-row) td:nth-child(' + (idx + 1) + ')');
        var sampleVal  = sampleCell ? parseSortVal(sampleCell.textContent.trim()) : NaN;
        asc = isNaN(sampleVal);
      } else {
        asc = wasSortDesc;
      }
      table.querySelectorAll('thead th').forEach(function(h) {
        h.classList.remove('sort-asc', 'sort-desc');
      });
      th.classList.add(asc ? 'sort-asc' : 'sort-desc');
      var totals = Array.from(tbody.querySelectorAll('tr.total-row'));
      var rows = Array.from(tbody.querySelectorAll('tr:not(.total-row)'));
      function parseSortVal(text) {
        var t = text.trim();
        var m = t.match(/^([\\d,.]+)\\s*(BCr|MCr|KCr)/);
        if (m) {
          var n = parseFloat(m[1].replace(/,/g, ''));
          if (m[2] === 'BCr') return n * 1e9;
          if (m[2] === 'MCr') return n * 1e6;
          if (m[2] === 'KCr') return n * 1e3;
        }
        var c = t.replace(/,/g, '');
        return /^-?[\\d.]+$/.test(c) ? parseFloat(c) : NaN;
      }
      rows.sort(function(a, b) {
        var av = a.cells[idx] ? a.cells[idx].textContent.trim() : '';
        var bv = b.cells[idx] ? b.cells[idx].textContent.trim() : '';
        var an = parseSortVal(av), bn = parseSortVal(bv);
        var cmp = (!isNaN(an) && !isNaN(bn)) ? (an - bn) : av.localeCompare(bv);
        return asc ? cmp : -cmp;
      });
      rows.forEach(function(r) { tbody.appendChild(r); });
      totals.forEach(function(r) { tbody.appendChild(r); });
    });
  });
}());
</script>
"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_trip_report(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
    out_path: Path,
) -> None:
    """Build and write a self-contained HTML trip report to out_path."""

    print("  Powerplay bonuses...")
    pp = st.infer_powerplay_bonuses(conn)
    exobio_bonus = pp["exobio_bonus"]
    expl_bonus   = pp["expl_bonus"]
    if pp["power"]:
        print(f"    {pp['power']}  rank {pp['rank']}  "
              f"(exobio +{exobio_bonus*100:.0f}%  expl +{expl_bonus*100:.0f}%)")

    print("  Trip summary...")
    data     = st.trip_summary(conn, date_from, date_to)
    lo_disp  = data["date_from"][:19].replace("T", " ")
    hi_disp  = data["date_to"][:19].replace("T", " ")

    print("  Estimated values...")
    est      = st.trip_estimated_values(conn, date_from, date_to)

    print("  Planet breakdown...")
    bodies   = st.trip_body_breakdown_grouped(conn, date_from, date_to)

    print("  Personal records...")
    records  = st.trip_personal_records(conn, date_from, date_to)

    print("  Systems visited...")
    sys_df   = st.trip_systems_visited(conn, date_from, date_to)

    print("  Route map...")
    df_route      = st.trip_route_points(conn, date_from, date_to)
    df_systems    = st.trip_system_data(conn, date_from, date_to,
                                         exobio_bonus=exobio_bonus, expl_bonus=expl_bonus)
    fig_route     = mp.plot_trip_route_3d(df_route, df_systems)
    fig_route_zoom = mp.plot_trip_route_3d_focused(df_route, df_systems)

    print("  Earnings timeline...")
    df_tl    = st.trip_value_timeline(conn, date_from, date_to,
                                       exobio_bonus=exobio_bonus, expl_bonus=expl_bonus)
    fig_tl   = _earnings_timeline_fig(df_tl, exobio_bonus=exobio_bonus, expl_bonus=expl_bonus)
    fig_pp   = _powerplay_fig(df_tl)

    print("  System diagram data...")
    diagram_data = st.trip_system_diagram_data(conn, date_from, date_to)
    sys_data_js  = "var SYSTEM_DATA = " + json.dumps(diagram_data, separators=(",", ":")) + ";"

    # --- assemble HTML ---
    plotly_first = True

    def _chart(fig: go.Figure | None) -> str:
        nonlocal plotly_first
        if fig is None:
            return ""
        html = f'<div class="chart-wrap">{_plotly_div(fig, first=plotly_first)}</div>'
        plotly_first = False
        return html

    pp_badge = ""
    if pp["power"]:
        bonus_parts = []
        if exobio_bonus:
            bonus_parts.append(f"exobio +{exobio_bonus*100:.0f}%")
        if expl_bonus:
            bonus_parts.append(f"expl +{expl_bonus*100:.0f}%")
        bonus_str = f"  ({', '.join(bonus_parts)})" if bonus_parts else ""
        pp_badge = (
            f'<div class="pp-badge">'
            f'{pp["power"]}  ·  rank {pp["rank"]}{bonus_str}'
            f'</div>'
        )

    header = (
        f'<header>'
        f'<h1>Expedition Report</h1>'
        f'<div class="subtitle">{lo_disp} — {hi_disp}</div>'
        f'{pp_badge}'
        f'</header>'
    )

    expl_est  = est["exploration_estimate"] * (1 + expl_bonus)
    star_est  = est["star_estimate"] * (1 + expl_bonus)
    org_est   = est["organic_first_log"] * (1 + exobio_bonus)
    expl_lbl  = f"Est. exploration value" + (f" (+{expl_bonus*100:.0f}% LYR)" if expl_bonus else "")
    star_lbl  = f"Est. star values (approx)" + (f" (+{expl_bonus*100:.0f}% LYR)" if expl_bonus else "")
    org_lbl   = f"Est. exobiology value"  + (f" (+{exobio_bonus*100:.0f}% Antal)" if exobio_bonus else "")
    value_summary = (
        f'<div class="stat-row" style="margin-top:10px">'
        f'<div class="stat-card"><div class="stat-val">{_cr(expl_est)}</div>'
        f'<div class="stat-label">{expl_lbl}</div></div>'
        f'<div class="stat-card"><div class="stat-val">{_cr(star_est)}</div>'
        f'<div class="stat-label">{star_lbl}</div></div>'
        f'<div class="stat-card"><div class="stat-val">{_cr(org_est)}</div>'
        f'<div class="stat-label">{org_lbl}</div></div>'
        f'<div class="stat-card"><div class="stat-val">{_cr(data["organic_credits"])}</div>'
        f'<div class="stat-label">Exobio credits sold</div></div>'
        f'<div class="stat-card"><div class="stat-val">{_cr(data["exploration_credits"])}</div>'
        f'<div class="stat-label">Exploration credits sold</div></div>'
        f'</div>'
    )

    # Powerplay summary cards (only when timeline has data)
    pp_summary = ""
    if not df_tl.empty:
        _tl_expl   = df_tl["exploration"].sum()
        _tl_exobio = df_tl["exobiology"].sum()
        _pp_merits  = _tl_expl / _PP_EXPL_MERIT_RATE + _tl_exobio / _PP_EXOBIO_MERIT_RATE
        _pp_cps     = _tl_expl / _PP_EXPL_CP_RATE    + _tl_exobio / _PP_EXOBIO_CP_RATE
        _pp_hours   = max(df_tl["session_hours"].sum(), 1 / 60)
        pp_summary = (
            f'<div class="stat-row" style="margin-top:6px">'
            f'<div class="stat-card"><div class="stat-val">{_pp_merits:,.0f}</div>'
            f'<div class="stat-label">Est. PP merits</div></div>'
            f'<div class="stat-card"><div class="stat-val">{_pp_merits/_pp_hours:,.0f}</div>'
            f'<div class="stat-label">Merits / active hour</div></div>'
            f'<div class="stat-card"><div class="stat-val">{_pp_cps:,.0f}</div>'
            f'<div class="stat-label">Est. control points</div></div>'
            f'<div class="stat-card"><div class="stat-val">{_pp_cps/_pp_hours:,.0f}</div>'
            f'<div class="stat-label">Control pts / active hour</div></div>'
            f'</div>'
        )

    _3d_nav_hint = (
        '<p class="map-nav-hint">'
        '<kbd>drag</kbd> rotate &nbsp;·&nbsp;'
        '<kbd>right-drag</kbd> pan &nbsp;·&nbsp;'
        '<kbd>scroll</kbd> zoom &nbsp;·&nbsp;'
        'reset: hover chart → ⌂ in toolbar'
        '</p>'
    )

    sections = [
        _section("Overview", _overview_cards(data) + value_summary + pp_summary),
        _section("3D Route", _chart(fig_route) + (_3d_nav_hint if fig_route else "")),
        _section("3D Route (Close-up)", _chart(fig_route_zoom) + (_3d_nav_hint if fig_route_zoom else "")),
        _section("Earnings per Day", _chart(fig_tl)),
        _section("Powerplay Estimates", _chart(fig_pp)) if fig_pp else "",
        _section("Exobiology Samples", _exobio_table(est, exobio_bonus=exobio_bonus)),
        _section("Planet Types", _planet_table(bodies)),
        _section("Personal Bests", _records_table(records)),
        _section("Systems Visited", _systems_table(sys_df)),
    ]

    modal_html = _SYS_MODAL_HTML
    modal_js = (
        f'<script>{sys_data_js}</script>'
        f'<script>{_SYS_MODAL_JS}\n}}());</script>'
    )

    body = (
        modal_html + "\n"
        + header
        + f'<div class="content">{"".join(sections)}</div>'
    )

    html = _html_doc(
        f"Trip Report — {lo_disp}",
        body,
        extra_css="\n" + _SYS_MODAL_CSS,
        extra_js=modal_js + "\n" + _SORT_JS,
    )
    out_path.write_text(html, encoding="utf-8")
    print(f"Saved: {out_path}")
