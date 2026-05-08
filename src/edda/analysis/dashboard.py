"""
Single-page HTML dashboard — all analytics in one self-contained file.

Layout:
  - Each section uses a tab bar so only one chart is visible at a time.
  - Catalogue sections (Species, Bodies, Stars) use a scrollable item-list on
    the left and a detail panel on the right; clicking an item shows its stats.

Plotly.js is embedded inline (matching the installed Python version) so
binary-encoded customdata and hover templates resolve correctly offline.
"""

import base64
import math
import sqlite3
from importlib.metadata import version as _pkg_version
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from . import stats as st
from . import charts as ch
from . import maps as mp


# ---------------------------------------------------------------------------
# Favicon — ED-style targeting diamond with crosshairs, embedded as SVG
# ---------------------------------------------------------------------------

_FAVICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <!-- Outer diamond: stroke only, transparent interior -->
  <polygon points="16,1.5 30.5,16 16,30.5 1.5,16"
           fill="none" stroke="#ff8833" stroke-width="1.2"/>
  <!-- 4 corner sub-diamonds (self-similar, each with a transparent hole at its outer tip) -->
  <path fill="#ff8833" fill-rule="evenodd"
        d="M 16,1.5 L 21,6.5 L 16,11.5 L 11,6.5 Z
           M 16,1.5 L 18,3.5 L 16,5.5 L 14,3.5 Z"/>
  <path fill="#ff8833" fill-rule="evenodd"
        d="M 30.5,16 L 25.5,11 L 20.5,16 L 25.5,21 Z
           M 30.5,16 L 28.5,14 L 26.5,16 L 28.5,18 Z"/>
  <path fill="#ff8833" fill-rule="evenodd"
        d="M 16,30.5 L 21,25.5 L 16,20.5 L 11,25.5 Z
           M 16,30.5 L 18,28.5 L 16,26.5 L 14,28.5 Z"/>
  <path fill="#ff8833" fill-rule="evenodd"
        d="M 1.5,16 L 6.5,11 L 11.5,16 L 6.5,21 Z
           M 1.5,16 L 3.5,14 L 5.5,16 L 3.5,18 Z"/>
  <!-- Crosshair connectors from inner sub-tips toward centre -->
  <line x1="16"   y1="11.5" x2="16"   y2="14"   stroke="#ff8833" stroke-width="1"/>
  <line x1="16"   y1="18"   x2="16"   y2="20.5" stroke="#ff8833" stroke-width="1"/>
  <line x1="11.5" y1="16"   x2="14"   y2="16"   stroke="#ff8833" stroke-width="1"/>
  <line x1="18"   y1="16"   x2="20.5" y2="16"   stroke="#ff8833" stroke-width="1"/>
  <!-- Centre dot -->
  <circle cx="16" cy="16" r="1.8" fill="#ff8833"/>
</svg>"""

_FAVICON_HREF = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(_FAVICON_SVG.encode()).decode()
)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #0a0a1a;
    color: #e0e0e0;
    display: flex;
    min-height: 100vh;
}

/* ---- Sidebar ---- */
#sidebar {
    position: fixed;
    left: 0; top: 0; bottom: 0;
    width: 210px;
    background: #0d0d22;
    border-right: 1px solid #1e1e44;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    z-index: 100;
}

.sidebar-logo {
    padding: 18px 16px 14px;
    font-size: 1em;
    font-weight: bold;
    color: #88aaff;
    border-bottom: 1px solid #1e1e44;
    line-height: 1.4;
}

.sidebar-logo-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}
.sidebar-logo .version {
    font-size: 0.65em;
    color: #6677aa;
    font-weight: normal;
}
.sidebar-logo span {
    display: block;
    font-size: 0.72em;
    color: #6677aa;
    font-weight: normal;
    margin-top: 3px;
}

#sidebar a {
    display: block;
    padding: 10px 16px;
    color: #99aacc;
    text-decoration: none;
    font-size: 0.88em;
    border-left: 3px solid transparent;
    transition: background 0.12s, color 0.12s;
}

#sidebar a:hover { background: #14143a; color: #ddeeff; }
#sidebar a.active { background: #14143a; color: #88ccff; border-left-color: #4488ff; }

/* ---- Main ---- */
main {
    margin-left: 210px;
    padding: 28px 36px 60px;
    flex: 1;
    min-width: 0;
}

section {
    margin-bottom: 70px;
    scroll-margin-top: 24px;
}

section h2 {
    font-size: 1.5em;
    color: #88aaff;
    border-bottom: 1px solid #1e1e44;
    padding-bottom: 10px;
    margin-bottom: 20px;
}

/* ---- Overview two-column ---- */
.two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 32px;
    align-items: start;
}
@media (max-width: 1100px) { .two-col { grid-template-columns: 1fr; } }

.col-head { font-size: 1em; color: #aabbdd; margin-bottom: 10px; }
.hints-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; max-height: 500px; overflow-y: auto; padding-right: 4px; }
.hint-card { background: #0e0e22; border: 1px solid #2a2a50; border-left: 3px solid #ff8833; border-radius: 4px; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.hint-card.tectonicas { border-left-color: #44cc88; }
.hint-card.highvalue { border-left-color: #44aaff; }
.hint-body { flex: 1; min-width: 0; }
.hint-card .hint-type { font-size: 0.85em; color: #ff8833; font-weight: bold; letter-spacing: 0.03em; }
.hint-card.tectonicas .hint-type { color: #44cc88; }
.hint-card.highvalue .hint-type { color: #44aaff; }
.hint-card .hint-coords { font-size: 0.78em; color: #8899cc; margin-top: 3px; font-family: monospace; }
.hint-card .hint-dist { font-size: 0.9em; color: #ccddff; font-weight: bold; flex-shrink: 0; text-align: right; white-space: nowrap; }
.hint-card .hint-detail { font-size: 0.78em; color: #7788aa; margin-top: 3px; }
.hints-empty { font-size: 0.85em; color: #445566; font-style: italic; }

/* ---- Summary tables ---- */
.summary-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9em;
}
.summary-table tr:nth-child(even) td { background: #0d0d22; }
.summary-table td, .summary-table th {
    padding: 7px 10px;
    border-bottom: 1px solid #1a1a33;
    vertical-align: top;
}
.summary-table th {
    color: #88aaff;
    font-weight: 600;
    background: #0d0d22;
}
.summary-table .val {
    text-align: right;
    font-family: 'Consolas', monospace;
    color: #88ddff;
    white-space: nowrap;
}

/* ---- Tab groups (charts sections) ---- */
.tab-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-bottom: 16px;
}

.tab-btn {
    background: #0d0d22;
    border: 1px solid #1e1e44;
    color: #99aacc;
    padding: 7px 15px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.84em;
    font-family: inherit;
    transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.tab-btn:hover { background: #14143a; color: #ddeeff; }
.tab-btn.active { background: #1a2a4a; color: #88ccff; border-color: #4488ff; }

.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* ---- Chart containers ---- */
.static-chart {
    max-width: 100%;
    border-radius: 6px;
    border: 1px solid #1e1e44;
    display: block;
}
.plotly-wrap {
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #1e1e44;
}
.empty-note { color: #445566; font-style: italic; padding: 20px 0; }

/* ---- Detail layout (catalogues) ---- */
.detail-layout {
    display: grid;
    grid-template-columns: 230px 1fr;
    gap: 20px;
    align-items: start;
}

.detail-list {
    border: 1px solid #1e1e44;
    border-radius: 6px;
    overflow-y: auto;
    max-height: 72vh;
    background: #0d0d22;
    position: sticky;
    top: 20px;
}

.detail-list input[type=search] {
    display: block;
    width: 100%;
    background: #0a0a1a;
    border: none;
    border-bottom: 1px solid #1e1e44;
    color: #cce;
    padding: 8px 12px;
    font-size: 0.82em;
    font-family: inherit;
    outline: none;
}
.detail-list input[type=search]::placeholder { color: #334; }

.detail-btn {
    display: block;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    border-bottom: 1px solid #1a1a33;
    padding: 8px 12px;
    color: #99aacc;
    cursor: pointer;
    font-size: 0.82em;
    font-family: inherit;
    transition: background 0.1s;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.detail-btn:hover { background: #14143a; color: #ddeeff; }
.detail-btn.active { background: #1a2a4a; color: #88ccff; }
.detail-btn.hidden { display: none; }

/* ---- Genus groups (species catalogue) ---- */
.genus-header { font-weight: 600; color: #aabbee; }
.genus-header::before { content: '▸ '; font-size: 0.75em; opacity: 0.7; }
.genus-header.open::before { content: '▾ '; }
.genus-items { display: none; }
.genus-items.open { display: block; }
.species-btn { padding-left: 26px !important; font-size: 0.80em; }
.legacy-tag { font-size: 0.62em; background: rgba(100,70,10,0.4); color: #bbaa55; border: 1px solid #8a7030; border-radius: 3px; padding: 0 3px; margin-left: 5px; vertical-align: middle; letter-spacing: 0.03em; }

.detail-content { min-width: 0; }
.detail-panel { display: none; }
.detail-panel.active { display: block; }

/* ---- Stats card ---- */
.stats-card {
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    background: #0d0d22;
    border: 1px solid #1e1e44;
    border-radius: 6px;
    padding: 16px 24px;
    margin-bottom: 20px;
}
.stat-item { text-align: center; min-width: 90px; }
.stat-val {
    display: block;
    font-size: 1.35em;
    font-family: 'Consolas', monospace;
    color: #88ddff;
    font-weight: bold;
}
.stat-label { display: block; font-size: 0.72em; color: #6677aa; margin-top: 3px; }

/* ---- Detail tables ---- */
.table-wrap {
    max-height: 420px;
    overflow-y: auto;
    border: 1px solid #1e1e44;
    border-radius: 4px;
    margin-bottom: 20px;
}
.detail-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.84em;
}
.detail-table th {
    text-align: left;
    padding: 7px 10px;
    background: #0d0d22;
    color: #88aaff;
    border-bottom: 2px solid #1e1e44;
    position: sticky;
    top: 0;
    z-index: 1;
}
.detail-table.sortable th { cursor: pointer; user-select: none; }
.detail-table.sortable th:hover { color: #aaccff; }
.detail-table.sortable th .sort-arr { float: right; opacity: 0.35; font-size: 0.8em; margin-left: 4px; }
.detail-table.sortable th.sort-asc .sort-arr,
.detail-table.sortable th.sort-desc .sort-arr { opacity: 1; color: #ff8833; }
.detail-table td {
    padding: 5px 10px;
    border-bottom: 1px solid #131328;
    vertical-align: top;
}
.detail-table tr:hover td { background: #0f0f28; }
.detail-table .num {
    text-align: right;
    font-family: 'Consolas', monospace;
    color: #88ddff;
}
.check { color: #44cc88; }

.sub-head { color: #aabbdd; font-size: 0.95em; margin: 18px 0 8px; }
.body-hint { display: block; font-size: 0.75em; color: #ffffff; font-weight: normal; margin-top: 2px; }
.detail-table .hint-col     { color: #ccddee; vertical-align: middle; }
.detail-table .hint-col-min { color: #ccddee; vertical-align: middle; text-align: right; }
.detail-table .num-center   { text-align: center; }

/* ---- Overview button in detail lists ---- */
.detail-overview-btn {
    font-weight: 600;
    color: #88aaff;
    border-bottom: 2px solid #1e1e44;
    letter-spacing: 0.03em;
}
.detail-overview-btn.active { color: #88ccff; }
"""


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

_JS = """
(function () {

    // ---- Tab switching ----
    document.querySelectorAll('.tab-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var bar = btn.closest('.tab-bar');
            var section = btn.closest('section');
            bar.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
            section.querySelectorAll(':scope > .tab-panel, .tab-group > .tab-panel').forEach(function (p) {
                p.classList.remove('active');
            });
            btn.classList.add('active');
            var panel = document.getElementById(btn.dataset.tab);
            if (!panel) return;
            panel.classList.add('active');
            panel.querySelectorAll('.plotly-graph-div').forEach(function (div) {
                if (window.Plotly) { try { Plotly.relayout(div, { autosize: true }); } catch (e) {} }
            });
        });
    });

    window.addEventListener('load', function () {
        document.querySelectorAll('.tab-panel.active .plotly-graph-div').forEach(function (div) {
            if (window.Plotly) { try { Plotly.relayout(div, { autosize: true }); } catch (e) {} }
        });
    });

    // ---- Detail-panel selector ----
    document.querySelectorAll('.detail-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var layout = btn.closest('.detail-layout');
            layout.querySelectorAll('.detail-btn').forEach(function (b) { b.classList.remove('active'); });
            layout.querySelectorAll('.detail-panel').forEach(function (p) { p.classList.remove('active'); });
            btn.classList.add('active');
            var panel = document.getElementById(btn.dataset.panel);
            if (panel) panel.classList.add('active');
        });
    });

    // ---- Genus expand/collapse ----
    document.querySelectorAll('.genus-header').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var items = btn.nextElementSibling;
            var open = items.classList.toggle('open');
            btn.classList.toggle('open', open);
        });
    });

    // ---- Search filter for detail lists ----
    document.querySelectorAll('.detail-list input[type=search]').forEach(function (inp) {
        inp.addEventListener('input', function () {
            var q = inp.value.trim().toLowerCase();
            var list = inp.closest('.detail-list');

            // Genus-grouped items (species catalogue)
            list.querySelectorAll('.genus-group').forEach(function (group) {
                var header = group.querySelector('.genus-header');
                var items  = group.querySelector('.genus-items');
                var btns   = group.querySelectorAll('.species-btn');
                if (!q) {
                    header.classList.remove('hidden');
                    btns.forEach(function (b) { b.classList.remove('hidden'); });
                    return;
                }
                var genusMatch = header.dataset.label.toLowerCase().includes(q);
                var anyMatch   = false;
                btns.forEach(function (b) {
                    var m = genusMatch || b.dataset.label.toLowerCase().includes(q);
                    b.classList.toggle('hidden', !m);
                    if (m) anyMatch = true;
                });
                var show = genusMatch || anyMatch;
                header.classList.toggle('hidden', !show);
                if (show) { items.classList.add('open'); header.classList.add('open'); }
            });

            // Flat items (body/star catalogues)
            list.querySelectorAll('.detail-btn:not(.detail-overview-btn):not(.genus-header):not(.species-btn)').forEach(function (btn) {
                btn.classList.toggle('hidden', !btn.dataset.label.toLowerCase().includes(q));
            });
        });
    });

    // ---- Sidebar scroll tracking ----
    var links = {};
    document.querySelectorAll('#sidebar a[href^="#"]').forEach(function (a) {
        links[a.getAttribute('href').slice(1)] = a;
    });
    function setSidebarActive(id) {
        Object.values(links).forEach(function (a) { a.classList.remove('active'); });
        if (links[id]) links[id].classList.add('active');
    }
    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { if (e.isIntersecting) setSidebarActive(e.target.id); });
    }, { threshold: 0.15 });
    document.querySelectorAll('section[id]').forEach(function (s) { observer.observe(s); });

    document.querySelectorAll('#sidebar a[href^="#"]').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            var t = document.querySelector(a.getAttribute('href'));
            if (t) t.scrollIntoView({ behavior: 'smooth' });
        });
    });

    // ---- Sortable tables ----
    document.querySelectorAll('table.sortable thead th').forEach(function (th) {
        th.innerHTML += '<span class="sort-arr">⇅</span>';
        th.addEventListener('click', function () {
            var table = th.closest('table');
            var col = Array.from(th.parentElement.children).indexOf(th);
            var asc = th.dataset.dir !== 'asc';
            table.querySelectorAll('thead th').forEach(function (h) {
                h.dataset.dir = '';
                h.classList.remove('sort-asc', 'sort-desc');
                var a = h.querySelector('.sort-arr');
                if (a) a.textContent = '⇅';
            });
            th.dataset.dir = asc ? 'asc' : 'desc';
            th.classList.add(asc ? 'sort-asc' : 'sort-desc');
            var arr = th.querySelector('.sort-arr');
            if (arr) arr.textContent = asc ? '▲' : '▼';
            var tbody = table.querySelector('tbody');
            var rows = Array.from(tbody.querySelectorAll('tr'));
            rows.sort(function (a, b) {
                var ac = a.children[col], bc = b.children[col];
                if (ac.dataset.sort !== undefined && bc.dataset.sort !== undefined) {
                    var d = parseFloat(ac.dataset.sort) - parseFloat(bc.dataset.sort);
                    return asc ? d : -d;
                }
                var as = ac.textContent.trim(), bs = bc.textContent.trim();
                return asc ? as.localeCompare(bs) : bs.localeCompare(as);
            });
            rows.forEach(function (r) { tbody.appendChild(r); });
        });
    });

}());
"""


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="icon" type="image/svg+xml" href="{favicon_href}">
  <script type="text/javascript">{plotly_js}</script>
  <style>
{css}
  </style>
</head>
<body>
  <nav id="sidebar">
    <div class="sidebar-logo">
      <div class="sidebar-logo-row">EDDA<span class="version">v{version}</span></div>
      <span>Elite Dangerous Data Analyser</span>
    </div>
{nav}
  </nav>
  <main>
{sections}
  </main>
  <script>
{js}
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

def _tab_group(section_id: str, tabs: list[tuple[str, str]]) -> str:
    buttons, panels = [], []
    for i, (label, content) in enumerate(tabs):
        tid = f"{section_id}-tab{i}"
        active = " active" if i == 0 else ""
        buttons.append(f'<button class="tab-btn{active}" data-tab="{tid}">{label}</button>')
        panels.append(f'<div class="tab-panel{active}" id="{tid}">{content}</div>')
    return (
        '<div class="tab-group">'
        f'<div class="tab-bar">{"".join(buttons)}</div>'
        + "".join(panels)
        + "</div>"
    )


def _section(section_id: str, title: str, content: str) -> str:
    return (
        f'<section id="{section_id}">\n'
        f'<h2>{title}</h2>\n'
        f'{content}\n'
        f'</section>'
    )


def _img(b64: str | None) -> str:
    if not b64:
        return '<p class="empty-note">No data available.</p>'
    return f'<img class="static-chart" src="data:image/png;base64,{b64}">'


def _plotly(fig: go.Figure | None) -> str:
    if fig is None:
        return '<p class="empty-note">No data available.</p>'
    return f'<div class="plotly-wrap">{fig.to_html(full_html=False, include_plotlyjs=False)}</div>'


def _summary_table_html(data: dict) -> str:
    labels = {
        "journal_files":       "Journal files processed",
        "systems_visited":     "Systems visited",
        "jumps":               "FSD jumps",
        "ly_travelled":        "Light-years travelled",
        "bodies_scanned":      "Bodies scanned",
        "planets_landable":    "Landable planets",
        "first_discoveries":   "First discoveries",
        "first_mapped":        "First mapped",
        "bio_signals_bodies":  "Bodies with bio signals",
        "organic_scans_done":  "Organic scans completed",
        "species_unique":      "Unique species",
        "organic_credits":     "Exobiology credits earned",
        "exploration_credits": "Exploration credits earned",
        "codex_new_entries":   "New codex entries",
    }
    _credit_keys = {"organic_credits", "exploration_credits"}
    rows = []
    for key, label in labels.items():
        val = data.get(key, 0)
        if key in _credit_keys:
            fmt = _fmt_cr(val)
        elif isinstance(val, float):
            fmt = f"{val:,.1f}"
        else:
            fmt = f"{val:,}"
        rows.append(f'<tr><td>{label}</td><td class="val">{fmt}</td></tr>')
    return '<table class="summary-table">' + "".join(rows) + "</table>"


def _records_table_html(df: pd.DataFrame) -> str:
    if df.empty:
        return '<p class="empty-note">No records yet.</p>'
    def _fmt(r) -> str:
        val = float(r["Value"])
        val_str = f"{val:,.3f}" if val < 1_000_000 else f"{val:,.0f}"
        unit = str(r.get("Unit", "")).strip()
        return f"{val_str} {unit}".strip()
    rows = [
        f'<tr><td>{r["Record"]}</td><td>{r["Body / System"]}</td>'
        f'<td class="val">{_fmt(r)}</td></tr>'
        for _, r in df.iterrows()
    ]
    hdr = "<tr><th>Record</th><th>Body / System</th><th>Value</th></tr>"
    return '<table class="summary-table">' + hdr + "".join(rows) + "</table>"


# ---------------------------------------------------------------------------
# Catalogue helpers
# ---------------------------------------------------------------------------

def _fmt_cr(n) -> str:
    n = float(n) if n else 0.0
    if n >= 1e9:
        return f'<span style="color:#ffcc44">{n/1e9:.1f} BCr</span>'
    if n >= 1e6:
        return f'<span style="color:#ff9944">{n/1e6:.1f} MCr</span>'
    if n >= 1e3:
        return f"{n/1e3:.0f} KCr"
    return f"{int(n)} Cr"


def _dist_ly(pos: dict | None, x, y, z) -> float | None:
    if pos is None or None in (x, y, z):
        return None
    try:
        return math.sqrt(
            (float(x) - pos["x"]) ** 2 +
            (float(y) - pos["y"]) ** 2 +
            (float(z) - pos["z"]) ** 2
        )
    except (TypeError, ValueError):
        return None


def _fmt_dist(d: float | None) -> str:
    return f"{d:,.0f} ly" if d is not None else "—"


def _dist_td(d: float | None) -> str:
    if d is None:
        return '<td class="num">—</td>'
    return f'<td class="num" data-sort="{d:.0f}">{_fmt_dist(d)}</td>'


def _vicinity_hints_html(helium_boxels: pd.DataFrame,
                         tectonicas_boxels: pd.DataFrame,
                         high_value_boxels: pd.DataFrame) -> str:
    entries: list[tuple[float, str]] = []

    for _, r in helium_boxels.iterrows():
        he_range = (f"{r['he_min']:.1f}–{r['he_max']:.1f}%"
                    if abs(r["he_max"] - r["he_min"]) > 0.1
                    else f"{r['he_mean']:.1f}%")
        entries.append((float(r["dist"]),
            '<li><div class="hint-card">'
            '<div class="hint-body">'
            '<span class="hint-type">Potential helium-rich boxel</span>'
            f'<div class="hint-coords">{r["nearest_system"]}</div>'
            f'<div class="hint-detail">Boxel: {r["boxel"]} &nbsp;·&nbsp; '
            f'He%: {he_range} &nbsp;·&nbsp; '
            f'{int(r["gg_count"])} gas giants scanned</div>'
            '</div>'
            f'<span class="hint-dist">{r["dist"]:,.0f} ly</span>'
            '</div></li>'
        ))

    for _, r in tectonicas_boxels.iterrows():
        entries.append((float(r["dist"]),
            '<li><div class="hint-card tectonicas">'
            '<div class="hint-body">'
            '<span class="hint-type">Potential Stratum Tectonicas boxel</span>'
            f'<div class="hint-coords">{r["nearest_system"]}</div>'
            f'<div class="hint-detail">Boxel: {r["boxel"]} &nbsp;·&nbsp; '
            f'He%: {r["he_mean"]:.1f}% &nbsp;·&nbsp; '
            f'{int(r["gg_count"])} gas giants scanned</div>'
            '</div>'
            f'<span class="hint-dist">{r["dist"]:,.0f} ly</span>'
            '</div></li>'
        ))

    for _, r in high_value_boxels.iterrows():
        entries.append((float(r["dist"]),
            '<li><div class="hint-card highvalue">'
            '<div class="hint-body">'
            '<span class="hint-type">Potential high exploration value boxel (&gt;3.5 MCr avg)</span>'
            f'<div class="hint-coords">{r["nearest_system"]}</div>'
            f'<div class="hint-detail">Boxel: {r["boxel"]} &nbsp;·&nbsp; '
            f'He%: {r["he_mean"]:.1f}% &nbsp;·&nbsp; '
            f'{int(r["gg_count"])} gas giants scanned</div>'
            '</div>'
            f'<span class="hint-dist">{r["dist"]:,.0f} ly</span>'
            '</div></li>'
        ))

    if not entries:
        return '<p class="hints-empty">No hints within 5,000 ly based on current scan data.</p>'

    entries.sort(key=lambda t: t[0])
    return f'<ul class="hints-list">{"".join(html for _, html in entries)}</ul>'


def _top_bodies_table_html(df: pd.DataFrame, cur_pos: dict | None) -> str:
    if df.empty:
        return '<p class="empty-note">No data.</p>'
    dist_th = "<th>Distance</th>" if cur_pos else ""
    rows = []
    for _, r in df.iterrows():
        d = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
        rows.append(
            f"<tr><td>{r['name']}</td>"
            f'<td class="num" data-sort="{int(r["body_count"])}">{int(r["body_count"]):,}</td>'
            f'<td class="num" data-sort="{int(r["bio_signals"])}">{int(r["bio_signals"]):,}</td>'
            f'<td class="num" data-sort="{int(r["first_disc"])}">{int(r["first_disc"]):,}</td>'
            + (f'<td class="num" data-sort="{d:.0f}">{_fmt_dist(d)}</td>' if cur_pos else "")
            + "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="detail-table sortable"><thead>'
        f"<tr><th>System</th><th>Bodies</th><th>Bio signals</th><th>1st disc.</th>{dist_th}</tr>"
        f'</thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _top_bio_table_html(df: pd.DataFrame, cur_pos: dict | None) -> str:
    if df.empty:
        return '<p class="empty-note">No data.</p>'
    dist_th = "<th>Distance</th>" if cur_pos else ""
    rows = []
    for _, r in df.iterrows():
        d = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
        rows.append(
            f"<tr><td>{r['name']}</td>"
            f'<td class="num" data-sort="{int(r["bio_signals"])}">{int(r["bio_signals"]):,}</td>'
            f'<td class="num" data-sort="{int(r["body_count"])}">{int(r["body_count"]):,}</td>'
            f'<td class="num" data-sort="{int(r["first_disc"])}">{int(r["first_disc"]):,}</td>'
            + (f'<td class="num" data-sort="{d:.0f}">{_fmt_dist(d)}</td>' if cur_pos else "")
            + "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="detail-table sortable"><thead>'
        f"<tr><th>System</th><th>Bio signals</th><th>Bodies</th><th>1st disc.</th>{dist_th}</tr>"
        f'</thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _top_stars_table_html(df: pd.DataFrame, cur_pos: dict | None) -> str:
    if df.empty:
        return '<p class="empty-note">No data.</p>'
    dist_th = "<th>Distance</th>" if cur_pos else ""
    rows = []
    for _, r in df.iterrows():
        d = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
        rows.append(
            f"<tr><td>{r['name']}</td>"
            f'<td class="num" data-sort="{int(r["star_count"])}">{int(r["star_count"]):,}</td>'
            f'<td class="num" data-sort="{int(r["star_classes"])}">{int(r["star_classes"]):,}</td>'
            f'<td class="num" data-sort="{int(r["first_disc"])}">{int(r["first_disc"]):,}</td>'
            + (_dist_td(d) if cur_pos else "")
            + "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="detail-table sortable"><thead>'
        f"<tr><th>System</th><th>Stars</th><th>Classes</th><th>1st disc.</th>{dist_th}</tr>"
        f'</thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _top_exobio_table_html(df: pd.DataFrame, cur_pos: dict | None) -> str:
    if df.empty:
        return '<p class="empty-note">No organic scan data.</p>'
    dist_th = "<th>Distance</th>" if cur_pos else ""
    rows = []
    for _, r in df.iterrows():
        d = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
        rows.append(
            f"<tr><td>{r['name']}</td>"
            f'<td class="num" data-sort="{int(r["species_count"])}">{int(r["species_count"]):,}</td>'
            f'<td class="num" data-sort="{float(r["total_value"]):.0f}">{_fmt_cr(r["total_value"])}</td>'
            + (f'<td class="num" data-sort="{d:.0f}">{_fmt_dist(d)}</td>' if cur_pos else "")
            + "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="detail-table sortable"><thead>'
        f"<tr><th>System</th><th>Species</th><th>Est. value</th>{dist_th}</tr>"
        f'</thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _top_explor_table_html(df: pd.DataFrame, cur_pos: dict | None) -> str:
    if df.empty:
        return '<p class="empty-note">No body scan data.</p>'
    dist_th = "<th>Distance</th>" if cur_pos else ""
    rows = []
    for _, r in df.iterrows():
        d = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
        rows.append(
            f"<tr><td>{r['name']}</td>"
            f'<td class="num" data-sort="{int(r["body_count"])}">{int(r["body_count"]):,}</td>'
            f'<td class="num" data-sort="{float(r["total_value"]):.0f}">{_fmt_cr(r["total_value"])}</td>'
            + (f'<td class="num" data-sort="{d:.0f}">{_fmt_dist(d)}</td>' if cur_pos else "")
            + "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="detail-table sortable"><thead>'
        f"<tr><th>System</th><th>Bodies</th><th>Est. value</th>{dist_th}</tr>"
        f'</thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _stats_card(items: list[tuple[str, str]]) -> str:
    inner = "".join(
        f'<div class="stat-item">'
        f'<span class="stat-val">{val}</span>'
        f'<span class="stat-label">{lbl}</span>'
        f'</div>'
        for lbl, val in items
    )
    return f'<div class="stats-card">{inner}</div>'


def _detail_layout(prefix_id: str, list_items: list[tuple[str, str]],
                   panel_html_fn, overview_html: str | None = None) -> str:
    """
    Build a detail-selector layout.

    list_items    — (label, panel_id) for each button.
    panel_html_fn(item_label, panel_id, is_first) → panel HTML string.
    overview_html — if provided, shown as the initial active panel with an
                    "Overview" button pinned above the search box.
    """
    has_overview = overview_html is not None
    overview_panel_id = f"{prefix_id}-overview"

    btn_html, panel_html = [], []

    if has_overview:
        panel_html.append(
            f'<div class="detail-panel active" id="{overview_panel_id}">'
            f'{overview_html}</div>'
        )

    for i, (label, panel_id) in enumerate(list_items):
        # No item is active when an overview exists
        active = "" if has_overview else (" active" if i == 0 else "")
        btn_html.append(
            f'<button class="detail-btn{active}" data-panel="{panel_id}" '
            f'data-label="{label}">{label}</button>'
        )
        panel_html.append(panel_html_fn(label, panel_id, i == 0 and not has_overview))

    overview_btn = ""
    if has_overview:
        overview_btn = (
            f'<button class="detail-btn detail-overview-btn active" '
            f'data-panel="{overview_panel_id}">Overview</button>'
        )

    list_block = (
        f'<div class="detail-list">'
        + overview_btn
        + '<input type="search" placeholder="Search…">'
        + "".join(btn_html)
        + "</div>"
    )
    content_block = '<div class="detail-content">' + "".join(panel_html) + "</div>"
    return f'<div class="detail-layout">{list_block}{content_block}</div>'


# ---------------------------------------------------------------------------
# Catalogue overview builders
# ---------------------------------------------------------------------------

def _species_overview(oval_df: pd.DataFrame) -> str:
    n_species  = oval_df["species"].nunique()
    total      = len(oval_df)
    n_first    = int(oval_df["is_first_log"].sum())
    est_total  = oval_df["estimated_payout"].sum()
    actual     = float(oval_df.drop_duplicates("species")["actual_total_sold"].dropna().sum())

    card = _stats_card([
        ("Species found",   f"{n_species:,}"),
        ("Total scans",     f"{total:,}"),
        ("First logs",      f"{n_first:,}"),
        ("Est. total value",_fmt_cr(est_total)),
        ("Actual sold",     _fmt_cr(actual) if actual > 0 else "—"),
    ])

    grp = (
        oval_df.groupby("species", sort=False)
        .agg(genus=("genus", "first"),
             scans=("species", "count"),
             first_logs=("is_first_log", "sum"),
             est_total=("estimated_payout", "sum"))
        .reset_index()
        .sort_values("scans", ascending=False)
    )
    rows = []
    for _, r in grp.iterrows():
        rows.append(
            f"<tr><td>{r['species']}</td><td>{r['genus'] or '—'}</td>"
            f'<td class="num" data-sort="{int(r["scans"])}">{int(r["scans"]):,}</td>'
            f'<td class="num" data-sort="{int(r["first_logs"])}">{int(r["first_logs"]):,}</td>'
            f'<td class="num" data-sort="{float(r["est_total"]):.0f}">{_fmt_cr(r["est_total"])}</td></tr>'
        )
    table = (
        '<div class="table-wrap"><table class="detail-table sortable"><thead><tr>'
        "<th>Species</th><th>Genus</th><th>Scans</th><th>First logs</th><th>Est. total</th>"
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    return card + table


def _body_overview(bval_df: pd.DataFrame) -> str:
    total    = len(bval_df)
    n_first  = int(bval_df["first_discovered"].sum())
    n_mapped = int(bval_df["was_mapped"].sum())
    n_fm     = int(bval_df["first_mapped"].sum())
    tot_val  = bval_df["estimated_value"].sum()

    card = _stats_card([
        ("Planets",          f"{total:,}"),
        ("First disc.",      f"{n_first:,}"),
        ("Mapped",           f"{n_mapped:,}"),
        ("First mapped",     f"{n_fm:,}"),
        ("Total est. value", _fmt_cr(tot_val)),
    ])

    grp = (
        bval_df.groupby("planet_class", sort=False)
        .agg(count=("name", "count"),
             first_disc=("first_discovered", "sum"),
             mapped=("was_mapped", "sum"),
             total_val=("estimated_value", "sum"),
             avg_val=("estimated_value", "mean"))
        .reset_index()
        .sort_values("count", ascending=False)
    )
    rows = []
    for _, r in grp.iterrows():
        rows.append(
            f"<tr><td>{r['planet_class']}</td>"
            f'<td class="num" data-sort="{int(r["count"])}">{int(r["count"]):,}</td>'
            f'<td class="num" data-sort="{int(r["first_disc"])}">{int(r["first_disc"]):,}</td>'
            f'<td class="num" data-sort="{int(r["mapped"])}">{int(r["mapped"]):,}</td>'
            f'<td class="num" data-sort="{float(r["total_val"]):.0f}">{_fmt_cr(r["total_val"])}</td>'
            f'<td class="num" data-sort="{float(r["avg_val"]):.2f}">{_fmt_cr(r["avg_val"])}</td></tr>'
        )
    table = (
        '<div class="table-wrap"><table class="detail-table sortable"><thead><tr>'
        "<th>Planet type</th><th>Bodies</th><th>1st disc.</th><th>Mapped</th>"
        "<th>Total value</th><th>Avg value</th>"
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    return card + table


def _star_overview(star_df: pd.DataFrame) -> str:
    n_systems  = len(star_df)
    n_classes  = star_df["star_class"].nunique()
    tot_bodies = int(star_df["body_count"].sum())
    bio_sys    = int((star_df["bodies_with_bio"] > 0).sum())
    first_disc = int(star_df["has_first_disc"].sum())

    card = _stats_card([
        ("Systems",          f"{n_systems:,}"),
        ("Star classes",     f"{n_classes:,}"),
        ("Total bodies",     f"{tot_bodies:,}"),
        ("Bio systems",      f"{bio_sys:,}"),
        ("1st disc. systems",f"{first_disc:,}"),
    ])

    grp = (
        star_df.groupby("star_class", sort=False)
        .agg(systems=("system_name", "count"),
             tot_bodies=("body_count", "sum"),
             avg_bodies=("body_count", "mean"),
             bio_systems=("bodies_with_bio", lambda x: (x > 0).sum()),
             first_disc=("has_first_disc", "sum"))
        .reset_index()
        .sort_values("systems", ascending=False)
    )
    rows = []
    for _, r in grp.iterrows():
        rows.append(
            f"<tr><td>{r['star_class']}</td>"
            f'<td class="num" data-sort="{int(r["systems"])}">{int(r["systems"]):,}</td>'
            f'<td class="num" data-sort="{int(r["tot_bodies"])}">{int(r["tot_bodies"]):,}</td>'
            f'<td class="num" data-sort="{r["avg_bodies"]:.4f}">{r["avg_bodies"]:.1f}</td>'
            f'<td class="num" data-sort="{int(r["bio_systems"])}">{int(r["bio_systems"]):,}</td>'
            f'<td class="num" data-sort="{int(r["first_disc"])}">{int(r["first_disc"]):,}</td></tr>'
        )
    table = (
        '<div class="table-wrap"><table class="detail-table sortable"><thead><tr>'
        "<th>Star class</th><th>Systems</th><th>Bodies</th><th>Avg bodies</th>"
        "<th>Bio systems</th><th>1st disc.</th>"
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    return card + table


# ---------------------------------------------------------------------------
# Species catalogue
# ---------------------------------------------------------------------------

def _species_panel_html(species: str, grp: pd.DataFrame,
                        genus: str, species_values: dict) -> str:
    n_scans    = len(grp)
    n_first    = int(grp["is_first_log"].sum())
    base_val   = species_values.get(species, int(grp["base_value"].iloc[0]))
    est_total  = grp["estimated_payout"].sum()
    actual_raw = grp["actual_total_sold"].dropna()
    actual     = float(actual_raw.iloc[0]) if not actual_raw.empty else 0.0

    card = _stats_card([
        ("Scans",       f"{n_scans:,}"),
        ("First logs",  f"{n_first:,}"),
        ("Base value",  _fmt_cr(base_val)),
        ("Est. total",  _fmt_cr(est_total)),
        ("Actual sold", _fmt_cr(actual) if actual > 0 else "—"),
    ])

    rows = []
    for _, r in grp.sort_values("timestamp").iterrows():
        ts  = str(r.get("timestamp", ""))[:10]
        sys = r.get("system_name")  or "—"
        bod = r.get("body_name")    or "—"
        pc  = r.get("planet_class") or "—"
        fl  = '<span class="check">✓</span>' if r.get("is_first_log") else ""
        ep  = _fmt_cr(r.get("estimated_payout", 0))
        rows.append(
            f"<tr><td>{ts}</td><td>{sys}</td><td>{bod}</td>"
            f"<td>{pc}</td>"
            f'<td style="text-align:center">{fl}</td>'
            f'<td class="num">{ep}</td></tr>'
        )
    table = (
        '<div class="table-wrap"><table class="detail-table"><thead><tr>'
        "<th>Date</th><th>System</th><th>Body</th><th>Planet type</th>"
        "<th>1st log</th><th>Est. value</th>"
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    return (
        f'<p style="color:#6677aa;font-size:0.82em;margin-bottom:12px">{genus}</p>'
        + card + table
    )


def _genus_panel_html(genus: str, genus_df: pd.DataFrame,
                      species_values: dict) -> str:
    n_species = genus_df["species"].nunique()
    n_scans   = len(genus_df)
    n_first   = int(genus_df["is_first_log"].sum())
    est_total = genus_df["estimated_payout"].sum()

    card = _stats_card([
        ("Species",        f"{n_species:,}"),
        ("Total scans",    f"{n_scans:,}"),
        ("First logs",     f"{n_first:,}"),
        ("Est. total",     _fmt_cr(est_total)),
    ])

    grp = (
        genus_df.groupby("species", sort=False)
        .agg(scans=("species", "count"),
             first_logs=("is_first_log", "sum"),
             est_total=("estimated_payout", "sum"),
             planet_types=("planet_class",
                           lambda x: ", ".join(sorted(x.dropna().unique()))))
        .reset_index()
        .sort_values("scans", ascending=False)
    )
    rows = []
    for _, r in grp.iterrows():
        base = species_values.get(r["species"], 0)
        rows.append(
            f"<tr><td>{r['species']}</td>"
            f'<td class="num">{int(r["scans"]):,}</td>'
            f'<td class="num">{int(r["first_logs"]):,}</td>'
            f'<td class="num">{_fmt_cr(base)}</td>'
            f'<td class="num">{_fmt_cr(r["est_total"])}</td>'
            f"<td>{r['planet_types'] or '—'}</td></tr>"
        )
    table = (
        '<div class="table-wrap"><table class="detail-table sortable"><thead><tr>'
        "<th>Species</th><th>Scans</th><th>First logs</th>"
        "<th>Base value</th><th>Est. total</th><th>Planet types</th>"
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    return card + table


_HORIZONS_GENERA = frozenset({
    "Amphora Plant", "Anemone", "Bark Mounds",
    "Brain Trees", "Crystalline Shards", "Sinuous Tubers",
})


def _build_species_section(oval_df: pd.DataFrame) -> str:
    if oval_df.empty:
        return '<p class="empty-note">No organic scan data.</p>'

    from .valuation import SPECIES_VALUES

    overview_panel_id = "sp-overview"
    panels: dict[str, str] = {overview_panel_id: _species_overview(oval_df)}

    genus_groups: list[tuple[str, str, list[tuple[str, str]]]] = []
    sp_idx = 0
    for g_idx, (genus, genus_df) in enumerate(
            oval_df.groupby("genus", sort=True)):
        genus_label    = genus or "Unknown"
        genus_panel_id = f"sp-genus-{g_idx}"
        species_items: list[tuple[str, str]] = []

        for species, sp_grp in genus_df.groupby("species", sort=True):
            if not species:
                continue
            sp_id = f"sp-{sp_idx}"
            sp_idx += 1
            species_items.append((species, sp_id))
            panels[sp_id] = _species_panel_html(
                species, sp_grp, genus_label, SPECIES_VALUES)

        panels[genus_panel_id] = _genus_panel_html(
            genus_label, genus_df, SPECIES_VALUES)
        genus_groups.append((genus_label, genus_panel_id, species_items))

    # Non-legacy genera first (alphabetical), then Horizons legacy genera (alphabetical)
    genus_groups.sort(key=lambda g: (g[0] in _HORIZONS_GENERA, g[0]))

    # Build list block with grouped structure
    btns = [
        f'<button class="detail-btn detail-overview-btn active" '
        f'data-panel="{overview_panel_id}">Overview</button>',
        '<input type="search" placeholder="Search…">',
    ]
    for genus_label, genus_panel_id, species_items in genus_groups:
        sp_btns = "".join(
            f'<button class="detail-btn species-btn" data-panel="{sp_id}" '
            f'data-label="{sp}">{sp}</button>'
            for sp, sp_id in species_items
        )
        legacy_tag = ' <span class="legacy-tag">Horizons</span>' if genus_label in _HORIZONS_GENERA else ""
        btns.append(
            f'<div class="genus-group">'
            f'<button class="detail-btn genus-header" data-panel="{genus_panel_id}" '
            f'data-label="{genus_label}">{genus_label}{legacy_tag}</button>'
            f'<div class="genus-items">{sp_btns}</div>'
            f'</div>'
        )

    list_block = f'<div class="detail-list">{"".join(btns)}</div>'

    # Build content block
    panel_html = [
        f'<div class="detail-panel active" id="{overview_panel_id}">'
        f'{panels[overview_panel_id]}</div>'
    ]
    for genus_label, genus_panel_id, species_items in genus_groups:
        panel_html.append(
            f'<div class="detail-panel" id="{genus_panel_id}">'
            f'{panels[genus_panel_id]}</div>'
        )
        for sp, sp_id in species_items:
            panel_html.append(
                f'<div class="detail-panel" id="{sp_id}">'
                f'{panels[sp_id]}</div>'
            )

    content_block = f'<div class="detail-content">{"".join(panel_html)}</div>'
    return f'<div class="detail-layout">{list_block}{content_block}</div>'


# ---------------------------------------------------------------------------
# Body-type catalogue
# ---------------------------------------------------------------------------

def _build_body_section(bval_df: pd.DataFrame, cur_pos: dict | None = None) -> str:
    if bval_df.empty:
        return '<p class="empty-note">No body data available.</p>'

    list_items = []
    panels: dict[str, str] = {}

    for planet_class, grp in bval_df.groupby("planet_class", sort=True):
        panel_id = f"bt-{len(list_items)}"
        n_bodies     = len(grp)
        n_first      = int(grp["first_discovered"].sum())
        n_mapped     = int(grp["was_mapped"].sum())
        n_fm         = int(grp["first_mapped"].sum())
        total_val    = grp["estimated_value"].sum()
        avg_val      = grp["estimated_value"].mean()

        label = f"{planet_class} ({n_bodies:,})"
        list_items.append((label, panel_id))

        card = _stats_card([
            ("Bodies",          f"{n_bodies:,}"),
            ("First disc.",     f"{n_first:,}"),
            ("Mapped",          f"{n_mapped:,}"),
            ("First mapped",    f"{n_fm:,}"),
            ("Total est. value",_fmt_cr(total_val)),
            ("Avg est. value",  _fmt_cr(avg_val)),
        ])

        # Property ranges with min/max body names
        grp = grp.copy()
        grp["surface_pressure_atm"] = grp["surface_pressure"] / 101325.0

        prop_rows = []
        for col, lbl, fmt in [
            ("surface_gravity_g",   "Gravity (g)",              "{:.3f}"),
            ("surface_temp_k",      "Surface temperature (K)",  "{:.0f}"),
            ("radius_km",           "Radius (km)",              "{:,.0f}"),
            ("mass_em",             "Earth masses",             "{:.4f}"),
            ("surface_pressure_atm","Surface pressure (atm)",   "{:.4f}"),
        ]:
            if col not in grp.columns:
                continue
            valid = grp[[col, "name"]].dropna(subset=[col])
            valid = valid[valid[col] > 0]
            if len(valid) < 2:
                continue
            idx_min = valid[col].idxmin()
            idx_max = valid[col].idxmax()
            prop_rows.append(
                f"<tr><td>{lbl}</td>"
                f'<td class="hint-col-min">{valid.loc[idx_min, "name"]}</td>'
                f'<td class="num num-center">{fmt.format(valid.loc[idx_min, col])}</td>'
                f'<td class="num num-center">{fmt.format(valid[col].mean())}</td>'
                f'<td class="num num-center">{fmt.format(valid.loc[idx_max, col])}</td>'
                f'<td class="hint-col">{valid.loc[idx_max, "name"]}</td></tr>'
            )

        sys_counts = grp.groupby("system_name").size()
        top_sys = sys_counts.idxmax()
        prop_rows.append(
            f"<tr><td>Most in system</td>"
            f'<td class="hint-col-min"></td><td class="num num-center"></td><td class="num num-center"></td>'
            f'<td class="num">{int(sys_counts.max())}</td>'
            f'<td class="hint-col">{top_sys}</td></tr>'
        )

        _vw = "width:90px;text-align:center"
        prop_block = (
            '<p class="sub-head">Property Ranges</p>'
            '<div class="table-wrap">'
            '<table class="detail-table"><thead>'
            f'<tr><th>Property</th><th></th>'
            f'<th style="{_vw}">Min</th><th style="{_vw}">Avg</th><th style="{_vw}">Max</th>'
            f'<th></th></tr>'
            f'</thead><tbody>{"".join(prop_rows)}</tbody></table></div>'
        )

        # Top 25 bodies by estimated value
        top = grp.nlargest(25, "estimated_value")
        dist_th = "<th>Distance</th>" if cur_pos else ""
        top_rows = []
        for _, r in top.iterrows():
            fd = '<span class="check">✓</span>' if r.get("first_discovered") else ""
            fm = '<span class="check">✓</span>' if r.get("first_mapped") else ""
            tf = r.get("terraform_state") or ""
            tf_note = " ✦" if tf and tf.lower() not in ("", "not terraformable") else ""
            d = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
            top_rows.append(
                f"<tr>"
                f"<td>{r.get('name', '')}{tf_note}</td>"
                f"<td>{r.get('system_name', '')}</td>"
                f'<td class="num" data-sort="{1 if r.get("first_discovered") else 0}" style="text-align:center">{fd}</td>'
                f'<td class="num" data-sort="{1 if r.get("first_mapped") else 0}" style="text-align:center">{fm}</td>'
                f'<td class="num" data-sort="{float(r.get("estimated_value", 0)):.0f}">{_fmt_cr(r.get("estimated_value", 0))}</td>'
                + (f'<td class="num" data-sort="{d:.0f}">{_fmt_dist(d)}</td>' if cur_pos else "")
                + "</tr>"
            )

        top_block = (
            '<p class="sub-head">Top Bodies by Estimated Value</p>'
            '<div class="table-wrap">'
            '<table class="detail-table sortable"><thead>'
            f"<tr><th>Body</th><th>System</th><th>1st disc.</th><th>1st mapped</th><th>Est. value</th>{dist_th}</tr>"
            f'</thead><tbody>{"".join(top_rows)}</tbody></table></div>'
        )

        panels[panel_id] = card + prop_block + top_block

    def _panel(label, panel_id, is_first):
        active = " active" if is_first else ""
        return f'<div class="detail-panel{active}" id="{panel_id}">{panels[panel_id]}</div>'

    return _detail_layout("bt", list_items, _panel, overview_html=_body_overview(bval_df))


# ---------------------------------------------------------------------------
# Star-class catalogue
# ---------------------------------------------------------------------------

def _build_star_section(star_df: pd.DataFrame, cur_pos: dict | None = None,
                        star_body_df: pd.DataFrame | None = None) -> str:
    if star_df.empty:
        return '<p class="empty-note">No star data available.</p>'

    body_by_class: dict = {}
    if star_body_df is not None and not star_body_df.empty:
        for sc, grp in star_body_df.groupby("star_class", sort=False):
            body_by_class[sc] = grp

    list_items = []
    panels: dict[str, str] = {}

    for star_class, grp in star_df.groupby("star_class", sort=True):
        panel_id        = f"sc-{len(list_items)}"
        n_systems       = len(grp)
        total_bodies    = int(grp["body_count"].sum())
        bio_systems     = int((grp["bodies_with_bio"] > 0).sum())
        first_disc_sys  = int(grp["has_first_disc"].sum())
        avg_bodies      = grp["body_count"].mean()

        label = f"{star_class} ({n_systems:,})"
        list_items.append((label, panel_id))

        card = _stats_card([
            ("Systems",            f"{n_systems:,}"),
            ("Total bodies",       f"{total_bodies:,}"),
            ("Avg bodies/system",  f"{avg_bodies:.1f}"),
            ("Bio systems",        f"{bio_systems:,}"),
            ("With 1st discovery", f"{first_disc_sys:,}"),
        ])

        top = grp.nlargest(25, "body_count")
        dist_th = "<th>Distance</th>" if cur_pos else ""
        top_rows = []
        for _, r in top.iterrows():
            fd  = '<span class="check">✓</span>' if r.get("has_first_disc") else ""
            bio = str(int(r["bodies_with_bio"])) if r.get("bodies_with_bio", 0) > 0 else "—"
            d = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
            top_rows.append(
                f"<tr>"
                f"<td>{r.get('system_name', '')}</td>"
                f'<td class="num" data-sort="{int(r["body_count"])}">{int(r["body_count"])}</td>'
                f'<td class="num" data-sort="{int(r.get("bodies_with_bio", 0))}">{bio}</td>'
                f'<td class="num" data-sort="{int(r.get("has_first_disc", 0))}" style="text-align:center">{fd}</td>'
                + (f'<td class="num" data-sort="{d:.0f}">{_fmt_dist(d)}</td>' if cur_pos else "")
                + "</tr>"
            )

        top_block = (
            '<p class="sub-head">Top Systems by Body Count</p>'
            '<div class="table-wrap">'
            '<table class="detail-table sortable"><thead>'
            f"<tr><th>System</th><th>Bodies</th><th>Bio bodies</th><th>1st disc.</th>{dist_th}</tr>"
            f'</thead><tbody>{"".join(top_rows)}</tbody></table></div>'
        )

        star_prop_block = ""
        if star_class in body_by_class:
            _SOL_R = 695_700.0
            sbg = body_by_class[star_class].copy()
            if "radius_km" in sbg.columns:
                sbg["radius_sr"] = sbg["radius_km"] / _SOL_R
            star_prop_rows = []
            for col, lbl, fmt in [
                ("surface_temp_k", "Surface temperature (K)", "{:.0f}"),
                ("radius_sr",      "Solar radius",            "{:.4f}"),
                ("mass_em",        "Solar masses",            "{:.4f}"),
                ("age_my",         "Age (million years)",     "{:,.0f}"),
            ]:
                if col not in sbg.columns:
                    continue
                valid = sbg[[col, "name"]].dropna(subset=[col])
                valid = valid[valid[col] > 0]
                if len(valid) < 2:
                    continue
                idx_min = valid[col].idxmin()
                idx_max = valid[col].idxmax()
                star_prop_rows.append(
                    f"<tr><td>{lbl}</td>"
                    f'<td class="hint-col-min">{valid.loc[idx_min, "name"]}</td>'
                    f'<td class="num num-center">{fmt.format(valid.loc[idx_min, col])}</td>'
                    f'<td class="num num-center">{fmt.format(valid[col].mean())}</td>'
                    f'<td class="num num-center">{fmt.format(valid.loc[idx_max, col])}</td>'
                    f'<td class="hint-col">{valid.loc[idx_max, "name"]}</td></tr>'
                )
            sys_counts = sbg.groupby("system_name").size()
            top_sys = sys_counts.idxmax()
            star_prop_rows.append(
                f"<tr><td>Most in system</td>"
                f'<td class="hint-col-min"></td><td class="num num-center"></td><td class="num num-center"></td>'
                f'<td class="num">{int(sys_counts.max())}</td>'
                f'<td class="hint-col">{top_sys}</td></tr>'
            )
            _vw = "width:90px;text-align:center"
            star_prop_block = (
                '<p class="sub-head">Property Ranges</p>'
                '<div class="table-wrap">'
                '<table class="detail-table"><thead>'
                f'<tr><th>Property</th><th></th>'
                f'<th style="{_vw}">Min</th><th style="{_vw}">Avg</th><th style="{_vw}">Max</th>'
                f'<th></th></tr>'
                f'</thead><tbody>{"".join(star_prop_rows)}</tbody></table></div>'
            )

        panels[panel_id] = card + star_prop_block + top_block

    def _panel(label, panel_id, is_first):
        active = " active" if is_first else ""
        return f'<div class="detail-panel{active}" id="{panel_id}">{panels[panel_id]}</div>'

    return _detail_layout("sc", list_items, _panel, overview_html=_star_overview(star_df))


# ---------------------------------------------------------------------------
# Dashboard builder
# ---------------------------------------------------------------------------

def build_dashboard(conn: sqlite3.Connection, out_path: Path) -> None:
    sections = []
    cur_pos = st.current_location(conn)

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    print("  Overview...")
    summ               = st.summary(conn)
    helium_boxels      = st.nearby_helium_boxels(conn, cur_pos)
    tectonicas_boxels  = st.nearby_tectonicas_boxels(conn, cur_pos)
    high_value_boxels  = st.nearby_high_value_boxels(conn, cur_pos)
    sections.append(_section("overview", "Overview",
        '<div class="two-col">'
        f'<div><p class="col-head">Summary</p>{_summary_table_html(summ)}</div>'
        f'<div><p class="col-head">Vicinity Hints '
        f'<small style="color:#6677aa;font-size:0.8em;">within 5,000 ly</small></p>'
        f'{_vicinity_hints_html(helium_boxels, tectonicas_boxels, high_value_boxels)}</div>'
        '</div>'
    ))

    # ------------------------------------------------------------------
    # Personal Records
    # ------------------------------------------------------------------
    print("  Personal records...")
    records       = st.personal_records(conn)
    df_top_bodies = st.top_systems_by_bodies(conn)
    df_top_bio    = st.top_systems_by_bio(conn)
    df_top_exobio = st.top_systems_by_exobio_value(conn)
    df_top_explor = st.top_systems_by_exploration_value(conn)
    df_top_stars  = st.top_systems_by_stars(conn)
    sections.append(_section("records", "Personal Records",
        _tab_group("records", [
            ("Miscellaneous",    _records_table_html(records)),
            ("Most Bodies",      _top_bodies_table_html(df_top_bodies, cur_pos)),
            ("Most Stars",       _top_stars_table_html(df_top_stars, cur_pos)),
            ("Most Bio Signals", _top_bio_table_html(df_top_bio, cur_pos)),
            ("Top Exobiology",   _top_exobio_table_html(df_top_exobio, cur_pos)),
            ("Top Exploration",  _top_explor_table_html(df_top_explor, cur_pos)),
        ])
    ))

    # ------------------------------------------------------------------
    # Galaxy Maps
    # ------------------------------------------------------------------
    print("  Galaxy maps...")
    df_sys = st.systems_for_map(conn)
    sections.append(_section("galaxy-map", "Galaxy Maps",
        _tab_group("galaxy-map", [
            ("First Discoveries", _img(mp.plot_galaxy_map_static(df_sys, None, colour_by="first_discovery", current_pos=cur_pos))),
            ("Side View",         _img(mp.plot_galaxy_side_view_static(df_sys, None, current_pos=cur_pos))),
            ("Interactive",       _plotly(mp.plot_galaxy_map_interactive(df_sys, None, colour_by="bodies_scanned", current_pos=cur_pos))),
            ("Bio Heatmap",       _plotly(mp.plot_bio_heatmap_interactive(df_sys, None, current_pos=cur_pos))),
        ])
    ))

    # ------------------------------------------------------------------
    # Sector Map 3D
    # ------------------------------------------------------------------
    print("  Sector map 3D...")
    df_sec = st.sector_map_data(conn)
    sections.append(_section("sector-map", "Sector Map 3D",
        _tab_group("sector-map", [
            ("Interactive 3D", _plotly(mp.plot_sector_map_interactive(df_sec, None, current_pos=cur_pos))),
        ])
    ))

    # ------------------------------------------------------------------
    # Valuable Regions
    # ------------------------------------------------------------------
    print("  Valuable regions...")
    df_svd  = st.sector_valuable_data(conn)
    df_rz   = st.body_rate_vs_z(conn)
    df_rsc  = st.body_rate_vs_star_class(conn)

    # Top-sectors table (≥5 systems, sorted by terra_rate)
    top_sec = df_svd[df_svd["system_count"] >= 5].head(30)
    top_sec_rows = "".join(
        f"<tr>"
        f"<td>{r['sector']}</td>"
        f"<td>{int(r['system_count'])}</td>"
        f"<td>{r['terra_rate']:.3f}</td>"
        f"<td>{int(r['terra_count'])}</td>"
        f"<td>{r['elw_rate']:.3f}</td>"
        f"<td>{int(r['elw_count'])}</td>"
        f"<td>{r['ww_rate']:.3f}</td>"
        f"<td>{int(r['ww_count'])}</td>"
        f"<td>{r['bio_rate']:.3f}</td>"
        f"</tr>"
        for _, r in top_sec.iterrows()
    )
    top_sec_html = (
        '<p class="col-head">Top Sectors by Terraformable Rate '
        '(≥ 5 systems visited, rates are per visited system)</p>'
        '<div class="table-wrap"><table class="stats-table">'
        "<thead><tr><th>Sector</th><th>Systems</th>"
        "<th>Terra rate</th><th>Terra #</th>"
        "<th>ELW rate</th><th>ELW #</th>"
        "<th>WW rate</th><th>WW #</th>"
        "<th>Bio rate</th></tr></thead>"
        f"<tbody>{top_sec_rows}</tbody></table></div>"
    )

    sections.append(_section("valuable-regions", "Valuable Regions",
        _tab_group("valuable-regions", [
            ("Terra Sector Map",   _plotly(mp.plot_sector_valuable_map_interactive(df_svd, None, "terra_rate",   current_pos=cur_pos))),
            ("ELW Sector Map",     _plotly(mp.plot_sector_valuable_map_interactive(df_svd, None, "elw_rate",    current_pos=cur_pos))),
            ("Bio Sector Map",     _plotly(mp.plot_sector_valuable_map_interactive(df_svd, None, "bio_rate",    current_pos=cur_pos))),
            ("Rate vs Galactic Y", _plotly(ch.plot_body_rate_vs_z_interactive(df_rz, None))),
            ("Rate vs Star Class", _plotly(ch.plot_body_rate_vs_star_class_interactive(df_rsc, None))),
            ("Top Sectors Table",  top_sec_html),
        ])
    ))

    # ------------------------------------------------------------------
    # Bodies — charts + catalogue
    # ------------------------------------------------------------------
    print("  Bodies...")
    df_bodies      = st.body_type_counts(conn)
    df_stars       = st.star_class_counts(conn)
    df_bval        = st.body_values_table(conn)
    df_boxel_val   = st.boxel_he_vs_value(conn)
    _fig_boxel_val = ch.plot_boxel_he_vs_value(df_boxel_val, None)

    bodies_tabs = [
        ("Planet Types",       _plotly(ch.plot_body_types_interactive(df_bodies, None))),
        ("Star Classes",       _img(ch.plot_star_classes_static(df_stars, None))),
        ("Value by Type",      _plotly(ch.plot_body_values_by_type_interactive(df_bval, None))),
        ("Value Detail",       _img(ch.plot_body_values_by_type_static(df_bval, None))),
        ("Value Distribution", _img(ch.plot_body_value_histogram_static(df_bval, None))),
    ]
    if _fig_boxel_val is not None:
        bodies_tabs.append(("He% vs System Value", _plotly(_fig_boxel_val)))

    sections.append(_section("bodies", "Bodies",
        _tab_group("bodies", bodies_tabs)
    ))

    # ------------------------------------------------------------------
    # Exobiology — charts + catalogue
    # ------------------------------------------------------------------
    print("  Exobiology...")
    df_oval    = st.organic_values_table(conn)
    df_species = st.top_species(conn)
    df_sxp     = st.species_by_planet_type(conn)
    df_he_tec  = st.boxel_he_vs_tectonicas(conn)

    # Build bubble maps for a curated list of notable species
    _BUBBLE_SPECIES = [
        "Stratum Tectonicas",
        "Stratum Cucumisis",
        "Fonticulua Fluctus",
        "Fonticulua Segmentatus",
        "Concha Biconcavis",
        "Tussock Stigmasis",
    ]
    bubble_tabs = []
    for sp in _BUBBLE_SPECIES:
        df_sp = st.species_system_locations(conn, sp)
        if not df_sp.empty:
            fig = mp.plot_species_bubble_3d(df_sp, sp, None, current_pos=cur_pos)
            bubble_tabs.append((sp, _plotly(fig)))

    _fig_tec_he = ch.plot_tectonicas_he_distribution(df_he_tec, None)
    exobio_tabs = [
        ("Top Organisms",       _img(ch.plot_top_species_static(df_species, None))),
        ("Income by Species",   _plotly(ch.plot_organic_value_by_species_interactive(df_oval, None))),
        ("Genus × Planet Type", _plotly(ch.plot_species_planet_heatmap_interactive(df_sxp, None))),
        ("By Planet (static)",  _img(ch.plot_organic_value_by_planet_type_static(df_oval, None))),
    ] + bubble_tabs
    if _fig_tec_he is not None:
        exobio_tabs.append(("He% vs Tectonicas", _plotly(_fig_tec_he)))

    sections.append(_section("exobiology", "Exobiology",
        _tab_group("exobiology", exobio_tabs)
    ))

    # ------------------------------------------------------------------
    # Income & Travel
    # ------------------------------------------------------------------
    print("  Income & Travel...")
    df_expl     = st.exploration_income_over_time(conn)
    df_org      = st.organic_income_over_time(conn)
    jump_series = st.jump_distance_histogram_data(conn)

    sections.append(_section("income", "Income & Travel",
        _tab_group("income", [
            ("Exploration Income",   _plotly(ch.plot_exploration_income_interactive(df_expl, None))),
            ("Exploration (static)", _img(ch.plot_exploration_income_static(df_expl, None))),
            ("Exobiology Income",    _img(ch.plot_organic_income_static(df_org, None))),
            ("Jump Histogram",       _img(ch.plot_jump_histogram_static(jump_series, None))),
        ])
    ))

    # ------------------------------------------------------------------
    # Species Catalogue
    # ------------------------------------------------------------------
    print("  Species catalogue...")
    sections.append(_section("species-cat", "Species Catalogue",
        _build_species_section(df_oval)
    ))

    # ------------------------------------------------------------------
    # Body-type Catalogue
    # ------------------------------------------------------------------
    print("  Body-type catalogue...")
    sections.append(_section("body-cat", "Body-type Catalogue",
        _build_body_section(df_bval, cur_pos)
    ))

    # ------------------------------------------------------------------
    # Star-class Catalogue
    # ------------------------------------------------------------------
    print("  Star-class catalogue...")
    df_star      = st.star_class_system_details(conn)
    df_star_body = st.star_body_details(conn)
    sections.append(_section("star-cat", "Star-class Catalogue",
        _build_star_section(df_star, cur_pos, df_star_body)
    ))

    # ------------------------------------------------------------------
    # Assemble
    # ------------------------------------------------------------------
    print("  Assembling HTML...")

    nav_items = [
        ("overview",          "Overview"),
        ("records",           "Personal Records"),
        ("galaxy-map",        "Galaxy Maps"),
        ("sector-map",        "Sector Map 3D"),
        ("valuable-regions",  "Valuable Regions"),
        ("bodies",            "Bodies"),
        ("exobiology",  "Exobiology"),
        ("income",      "Income & Travel"),
        ("species-cat", "Species Catalogue"),
        ("body-cat",    "Body-type Catalogue"),
        ("star-cat",    "Star-class Catalogue"),
    ]
    nav_html = "\n".join(
        f'    <a href="#{sid}">{label}</a>' for sid, label in nav_items
    )

    try:
        _version = _pkg_version("edda")
    except Exception:
        _version = "dev"

    html = _HTML_TEMPLATE.format(
        title="EDDA — Elite Dangerous Data Analyser",
        favicon_href=_FAVICON_HREF,
        plotly_js=get_plotlyjs(),
        css=_CSS,
        nav=nav_html,
        sections="\n\n".join(sections),
        js=_JS,
        version=_version,
    )

    out_path.write_text(html, encoding="utf-8")
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"\nDashboard saved: {out_path}  ({size_mb:.1f} MB)")
