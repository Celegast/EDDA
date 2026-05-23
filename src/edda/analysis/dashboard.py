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
import json
import math
import re
import sqlite3
from importlib.metadata import version as _pkg_version
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from . import stats as st
from . import charts as ch
from . import maps as mp
from .valuation import SPECIES_VALUES


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
.map-nav-hint {
    font-size: 0.72rem; color: #3a4a60; margin-top: 6px; padding: 0 2px;
    user-select: none;
}
.map-nav-hint kbd {
    display: inline-block; padding: 0 5px; border: 1px solid #222844;
    border-radius: 3px; font-size: 0.9em; background: #0c0c22; color: #5a6888;
    font-family: inherit;
}

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
.detail-table td.nowrap { white-space: nowrap; }
.detail-table tr:hover td { background: #0f0f28; }
.detail-table .num {
    text-align: right;
    font-family: 'Consolas', monospace;
    color: #88ddff;
}
.check { color: #44cc88; }
.bio-tag {
    display: inline-block; background: #1a3a2a; color: #88ddaa;
    border: 1px solid #2a5a3a; border-radius: 3px;
    padding: 1px 5px; margin: 1px 2px; font-size: 0.78em; white-space: nowrap;
}
.dim { color: #556; }

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

/* ---- System diagram modal ---- */
.sys-modal {
    display: none;
    position: fixed;
    inset: 0;
    z-index: 500;
    align-items: center;
    justify-content: center;
    padding: 20px;
}
.sys-modal.open { display: flex; }
.sys-modal-bg {
    position: absolute;
    inset: 0;
    background: rgba(0,0,0,0.72);
}
.sys-modal-box {
    position: relative;
    background: #0b0b1e;
    border: 1px solid #2a2a55;
    border-radius: 8px;
    width: fit-content;
    max-width: 95vw;
    box-shadow: 0 0 80px rgba(30,30,120,0.5);
    overflow: hidden;
}
.sys-modal-hdr {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    border-bottom: 1px solid #1e1e44;
    background: #0d0d22;
}
.sys-modal-ttl { font-size: 1em; color: #88aaff; font-weight: 600; }
.sys-modal-sc  { font-size: 0.8em; color: #6677aa; }
.sys-modal-ftr {
    border-top: 1px solid #1e1e44;
    background: #0d0d22;
    padding: 6px 12px;
    display: flex;
    align-items: center;
    gap: 10px;
}
#gal-canvas, #sys-legend-canvas {
    display: block;
    border: 1px solid #1e1e44;
    border-radius: 3px;
}
.sys-modal-close {
    margin-left: auto;
    background: none;
    border: none;
    color: #6677aa;
    cursor: pointer;
    font-size: 1.2em;
    line-height: 1;
    padding: 2px 6px;
    border-radius: 3px;
    transition: color 0.1s, background 0.1s;
}
.sys-modal-close:hover { color: #ee8866; background: rgba(255,100,50,0.1); }
#sys-canvas {
    display: block;
    height: auto;
    cursor: crosshair;
}
.sys-tip {
    position: fixed;
    background: rgba(8,8,24,0.96);
    border: 1px solid #2a2a55;
    border-radius: 4px;
    padding: 8px 11px;
    font-size: 0.78em;
    color: #ccd;
    pointer-events: none;
    display: none;
    max-width: 260px;
    line-height: 1.65;
    white-space: nowrap;
    z-index: 600;
}
.sys-tip.visible { display: block; }
.sys-link {
    cursor: pointer;
    color: #88aaff;
    text-decoration: underline;
    text-decoration-style: dotted;
    text-underline-offset: 2px;
}
.sys-link:hover { color: #bbddff; }
/* END_SYS_MODAL_CSS */
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

    // ---- Plotly legend group-title toggle ----
    // After any plot renders, find text elements whose content matches a
    // legendgroup name and make them clickable to toggle all traces in that group.
    function _patchLegendGroupTitles(gd) {
        if (!window.Plotly || !gd.data) return;
        var groups = {};
        gd.data.forEach(function (trace, i) {
            if (trace.legendgroup)
                (groups[trace.legendgroup] = groups[trace.legendgroup] || []).push(i);
        });
        gd.querySelectorAll('g.legend text').forEach(function (el) {
            var name = el.textContent.trim();
            if (!groups[name]) return;
            var idxs = groups[name].slice();
            el.style.cursor = 'pointer';
            var clone = el.cloneNode(true);
            clone.style.cursor = 'pointer';
            clone.style.textDecoration = 'underline';
            el.parentNode.replaceChild(clone, el);
            clone.addEventListener('click', function (e) {
                e.stopPropagation();
                var anyVisible = idxs.some(function (i) {
                    var v = gd.data[i].visible;
                    return v === true || v === undefined || v === null;
                });
                Plotly.restyle(gd, { visible: anyVisible ? 'legendonly' : true }, idxs);
            });
        });
    }

    window.addEventListener('load', function () {
        document.querySelectorAll('.tab-panel.active .plotly-graph-div').forEach(function (div) {
            if (window.Plotly) { try { Plotly.relayout(div, { autosize: true }); } catch (e) {} }
        });

        // Patch legend group titles on all Plotly divs, and re-patch after each re-render.
        document.querySelectorAll('.plotly-graph-div').forEach(function (gd) {
            _patchLegendGroupTitles(gd);
            gd.on('plotly_afterplot', function () { _patchLegendGroupTitles(gd); });
        });

        // ---- Make every plain-text system-name cell clickable ----
        if (typeof SYSTEM_DATA === 'undefined') return;
        var nameSA = {};
        Object.keys(SYSTEM_DATA).forEach(function(sa) {
            nameSA[SYSTEM_DATA[sa].name] = sa;
        });
        document.querySelectorAll('td').forEach(function(td) {
            // Only wrap cells that already contain a sys-link span, or are plain text
            if (td.querySelector('.sys-link')) return;  // already done
            if (td.children.length !== 0) return;       // has other child elements
            var txt = td.textContent.trim();
            var sa  = nameSA[txt];
            if (!sa) return;
            td.innerHTML = '<span class="sys-link" data-sa="' + sa + '">' +
                           td.innerHTML + '</span>';
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

// ---- System Diagram ----

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

// Galaxy top-view minimap
// ED coordinates: Sol at (0,0,0), galactic centre ~(25,-21,25900)
// Top-down view uses X (east-west) and Z (north-south).
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

    // Coordinate mapping: show ±_GAL_R around galactic centre
    function toSX(x) { return (x - _GC_X + _GAL_R) / (_GAL_R * 2) * W; }
    function toSY(z) { return (1 - (z - _GC_Z + _GAL_R) / (_GAL_R * 2)) * H; }

    // Galaxy disc — radial gradient from GC
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

    // Galactic centre (Sag A*)
    ctx.beginPath(); ctx.arc(gcX, gcY, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,220,140,0.9)'; ctx.fill();
    ctx.font = '8px sans-serif'; ctx.fillStyle = 'rgba(255,220,140,0.7)';
    ctx.textAlign = 'center'; ctx.fillText('Sag A*', gcX, gcY - 4);

    // Reference points
    ctx.font = '8px sans-serif';
    _GAL_REFS.forEach(function(ref) {
        var rx = toSX(ref.x), ry = toSY(ref.z);
        ctx.beginPath(); ctx.arc(rx, ry, 2, 0, Math.PI * 2);
        ctx.fillStyle = ref.col; ctx.fill();
        ctx.fillStyle = ref.col; ctx.textAlign = 'center';
        ctx.fillText(ref.lbl, rx, ry - 4);
    });

    // Current system — cyan crosshair so it stands out from the amber GC
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

    var ir = 7;  // icon body radius
    var rx = ir * 1.9, ry = ir * 0.48, rot = Math.PI * 0.2;
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

    // Two columns: items 0-2 left, items 3-4 right
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
    var d = (typeof SYSTEM_DATA !== 'undefined') && SYSTEM_DATA[String(sa)];
    if (!d) {
        var sysName = fallbackName || ('System ' + sa);
        document.getElementById('sys-modal-ttl').textContent = sysName;
        document.getElementById('sys-modal-sc').textContent = 'no scan data';
        document.getElementById('sys-modal').classList.add('open');
        var canvas = document.getElementById('sys-canvas');
        if (canvas) {
            canvas.width = 680; canvas.height = 80;
            var ctx = canvas.getContext('2d');
            ctx.fillStyle = '#040410'; ctx.fillRect(0, 0, 680, 80);
            ctx.fillStyle = '#556688'; ctx.font = '13px monospace';
            ctx.fillText('No detailed body scan data available for this system.', 16, 46);
        }
        return;
    }
    _sysData = d;
    document.getElementById('sys-modal-ttl').textContent = d.name;
    document.getElementById('sys-modal-sc').textContent  = d.sc ? '(' + d.sc + ')' : '';
    document.getElementById('sys-modal').classList.add('open');
    _drawLegend();
    _drawGalMap(d);
    requestAnimationFrame(_drawSys);
}

function closeSysModal() {
    document.getElementById('sys-modal').classList.remove('open');
    _sysData = null; _sysBodies = null;
}

// Radial orrery — kept for reference, not currently active.
// To reactivate: rename to _drawSys and revert tooltip to use p.r / p.x / p.y.
function _drawSysOrrery() {
    var canvas = document.getElementById('sys-canvas');
    if (!canvas || !_sysData) return;
    canvas.width = 700; canvas.height = 460;
    var ctx = canvas.getContext('2d');
    var W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#040410'; ctx.fillRect(0, 0, W, H);

    var rng = 7919;
    function _rn() { rng = (rng * 1664525 + 1013904223) | 0; return (rng >>> 0) / 4294967296; }
    for (var si = 0; si < 140; si++) {
        ctx.beginPath();
        ctx.arc(_rn()*W, _rn()*H, 0.65, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(180,200,255,' + (0.1 + _rn()*0.4).toFixed(2) + ')';
        ctx.fill();
    }

    var all     = _sysData.bodies || [];
    var stars   = all.filter(function(b){ return b.t === 'Star'; });
    var planets = all.filter(function(b){ return b.t !== 'Star' && b.t !== 'Other' && (b.d || 0) > 0; });
    planets.sort(function(a, b){ return (a.d||0) - (b.d||0); });

    var cx = W/2, cy = H/2;
    var maxR = Math.min(W,H)/2 - 38;

    var dists  = planets.map(function(b){ return b.d||0; }).filter(function(d){ return d>0; });
    var logMin = dists.length ? Math.log10(Math.max(Math.min.apply(null,dists), 0.01)) - 0.5 : 0;
    var logMax = dists.length ? Math.log10(Math.max.apply(null,dists)) + 0.3 : 4;
    if (logMax - logMin < 1) logMax = logMin + 1;

    function dToR(d) {
        if (!d || d <= 0) return 0;
        var t = (Math.log10(d) - logMin) / (logMax - logMin);
        return 26 + (maxR - 26) * Math.max(0, Math.min(1, t));
    }

    var ringDone = {};
    planets.forEach(function(b) {
        var rr = Math.round(dToR(b.d) * 4) / 4;
        if (ringDone[rr]) return;
        ringDone[rr] = true;
        ctx.beginPath(); ctx.arc(cx, cy, dToR(b.d), 0, Math.PI*2);
        ctx.strokeStyle = 'rgba(80,100,200,0.09)'; ctx.lineWidth = 0.7; ctx.stroke();
    });

    var placed = [];
    var phi = Math.PI * (3 - Math.sqrt(5));
    planets.forEach(function(b, i) {
        var r = dToR(b.d), angle = i * phi;
        placed.push({ x: cx + r*Math.cos(angle), y: cy + r*Math.sin(angle), b: b, r: _bodyPx(b) });
    });
    stars.forEach(function(s, i) {
        var r = (i > 0 && s.d && s.d > 1) ? dToR(s.d) : 0;
        var angle = (i + 0.5) * 2.1;
        placed.push({ x: cx + r*Math.cos(angle), y: cy + r*Math.sin(angle), b: s, r: _bodyPx(s) });
    });
    _sysBodies = placed;

    placed.forEach(function(p) {
        var b = p.b, bx = p.x, by = p.y, br = p.r;
        var col = (b.t === 'Star') ? _starCol(b.s) : _planetCol(b.s, b.e);
        var isBlackHole = b.t === 'Star' && (b.s === 'H' || b.s === 'SupermassiveBlackHole');
        if (b.t === 'Star' && !isBlackHole) {
            var g = ctx.createRadialGradient(bx, by, 0, bx, by, br*3.5);
            g.addColorStop(0, col); g.addColorStop(0.45, col + '66'); g.addColorStop(1, col + '00');
            ctx.fillStyle = g; ctx.beginPath(); ctx.arc(bx, by, br*3.5, 0, Math.PI*2); ctx.fill();
        }
        if (b.b > 0) {
            ctx.beginPath(); ctx.arc(bx, by, br + 4, 0, Math.PI*2);
            ctx.strokeStyle = 'rgba(50,220,100,0.75)'; ctx.lineWidth = 1.5; ctx.stroke();
        }
        ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI*2);
        if (isBlackHole) {
            ctx.fillStyle = '#050010'; ctx.fill();
            ctx.beginPath(); ctx.arc(bx, by, br + 2, 0, Math.PI*2);
            ctx.strokeStyle = '#cc33ff'; ctx.lineWidth = 1; ctx.stroke();
        } else {
            ctx.fillStyle = col; ctx.fill();
        }
        if (b.f) {
            ctx.fillStyle = '#ffee44'; ctx.font = 'bold 8px sans-serif';
            ctx.textAlign = 'center'; ctx.fillText('★', bx, by - br - 3);
        }
        if (b.w && b.t !== 'Star') {
            ctx.beginPath(); ctx.arc(bx, by, br + 1.5, 0, Math.PI*2);
            ctx.strokeStyle = 'rgba(255,200,80,0.55)'; ctx.lineWidth = 1; ctx.stroke();
        }
    });
    ctx.textAlign = 'left';

    if (dists.length) {
        var steps = [0.1,0.3,1,3,10,30,100,300,1000,3000,10000,30000];
        ctx.font = '9px monospace'; ctx.fillStyle = 'rgba(120,140,200,0.55)';
        steps.forEach(function(ls) {
            var r = dToR(ls);
            if (r >= 28 && r <= maxR + 5) {
                var angle = -Math.PI * 0.28;
                ctx.textAlign = 'left';
                var lbl = ls >= 1 ? Math.round(ls) + ' LS' : ls.toFixed(1) + ' LS';
                ctx.fillText(lbl, cx + r*Math.cos(angle) + 3, cy + r*Math.sin(angle) - 3);
            }
        });
        ctx.textAlign = 'left';
    }

    var lx = W - 14, ly = 14, lh = 14;
    var items = [];
    if (planets.some(function(b){ return b.b > 0; }))
        items.push({col:'rgba(50,220,100,0.75)', lbl:'Bio signals', ring:true});
    if (planets.some(function(b){ return b.f; }))
        items.push({col:'#ffee44', lbl:'First discovery', star:true});
    if (planets.some(function(b){ return b.w; }))
        items.push({col:'rgba(255,200,80,0.55)', lbl:'Mapped', ring:true});
    ctx.font = '9px sans-serif'; ctx.textAlign = 'right';
    items.forEach(function(item) {
        ctx.fillStyle = item.col;
        if (item.star) ctx.fillText('★ ' + item.lbl, lx, ly);
        else           ctx.fillText('● ' + item.lbl, lx, ly);
        ly += lh;
    });
    ctx.textAlign = 'left';

    if (!all.length) {
        ctx.fillStyle = '#446'; ctx.font = '14px sans-serif'; ctx.textAlign = 'center';
        ctx.fillText('No body data available', W/2, H/2);
        ctx.textAlign = 'left';
    }
}

function _buildTree(data) {
    var allBodies = data.bodies || [];
    var bodies = allBodies.filter(function(b) { return b.t === 'Star' || b.t === 'Planet'; });
    var byId = {};
    bodies.forEach(function(b) {
        byId[b.i] = { b: b, children: [], parent: null, sortKey: null,
                      gx: 0, gy: 0, lvl: 0, cols: 1, rows: 1, x: 0, y: 0 };
    });
    // Phase 1: use orbital_parent_id where present
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
    // Phase 2: name-inference fallback for bodies not yet parented
    _inferHierarchy(byId, bodies, data.name);
    // Derive labels / sort-keys for barycentres created in phase 1 (phase 2 already labels its own)
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
    // Reassign orphaned non-star/barycentre nodes to the primary star (or root barycentre) as fallback
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
                // re-attach numbered companion stars with missing orbital_parent_id (e.g. "5","6","7","8")
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
        // primary star's name IS the system name — it has no meaningful suffix
        var suf = (b.n === sysName) ? '' : (b.n.indexOf(pfx) === 0 ? b.n.slice(pfx.length) : b.n);
        byId[b.i]._sfx = suf;
        byId[b.i]._tok = suf.trim() ? suf.trim().split(/\\s+/) : [];
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
            // Barycenter pattern: "BC 3" → parent "BC".  Stars B and C stay as independent roots;
            // the × node only owns the bodies explicitly named after it (BC 1, BC 2 …).
            // sortKey places the × between the referenced stars in the root order.
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

// Direction is determined by the LAST token of the body's name suffix:
//   all-digits  ("1","19")      → planet   → children BELOW   (vertical)
//   all-lowercase ("a","b")     → moon     → children to RIGHT (horizontal)
//   all-uppercase ("A","BCD")   → star/bary → children to RIGHT (horizontal)
// Barycentre nodes (synthetic × markers) are always horizontal regardless.
// Falls back to level-parity for synthetic nodes that carry no _tok.
function _nodeHoriz(node, lvl) {
    if (node.b.t === 'Barycentre') return true;
    if (node._tok && node._tok.length > 0) {
        var last = node._tok[node._tok.length - 1];
        if (/^[0-9]+$/.test(last))  return false; // number → planet/companion-star → children below
        if (/^[a-z]+$/.test(last))  return true; // lowercase → moon → children right
        if (/^[A-Z]+$/.test(last))  return true; // uppercase → star name → children right
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

    var H_STEP = 52, V_STEP = 36, PAD_L = 50, PAD_T = 38, PAD_B = 20;
    var ROOT_GAP = 1;  // extra blank row between root-level stars

    var tree  = _buildTree(_sysData);
    var roots = tree.roots;
    var totalRows = 0, totalCols = 1;
    roots.forEach(function(r) {
        _computeSize(r, 0);
        _placeNode(r, 0, totalRows, 0);
        totalRows += r.rows + ROOT_GAP;
        if (r.cols > totalCols) totalCols = r.cols;
    });
    totalRows = Math.max(1, totalRows - ROOT_GAP);  // remove trailing gap

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

    // Connector lines (behind bodies)
    ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(80,100,160,0.45)';
    placed.forEach(function(node) {
        if (!node.children.length) return;
        var px = nPx(node), py = nPy(node);
        var horiz  = _nodeHoriz(node, node.lvl);
        var last   = node.children[node.children.length - 1];
        if (horiz) {
            ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(nPx(last), py); ctx.stroke();
        } else {
            ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px, nPy(last)); ctx.stroke();
        }
    });

    // Bodies
    placed.forEach(function(node) {
        var b = node.b;
        node.x = nPx(node); node.y = nPy(node);
        var bx = node.x, by = node.y;

        // Barycentre: red × mark
        if (b.t === 'Barycentre') {
            var xs = 5;
            ctx.strokeStyle = '#cc3333'; ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.moveTo(bx-xs, by-xs); ctx.lineTo(bx+xs, by+xs); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(bx+xs, by-xs); ctx.lineTo(bx-xs, by+xs); ctx.stroke();
            if (b.s) {
                ctx.font = '8px sans-serif'; ctx.fillStyle = 'rgba(220,120,120,0.9)';
                ctx.textAlign = 'left'; ctx.fillText(b.s, bx + xs + 2, by + 3);
            }
            node.x = bx; node.y = by;
            return;
        }

        var br  = _bodyPx(b);
        var col = b.t === 'Star' ? _starCol(b.s) : _planetCol(b.s, b.e);
        var isBH = b.t === 'Star' && ((b.s || '').toUpperCase() === 'H' ||
                   (b.s || '').toLowerCase().indexOf('black') >= 0);

        // Star glow (compact — br*2 to avoid overlap with adjacent rows)
        if (b.t === 'Star' && !isBH) {
            var g = ctx.createRadialGradient(bx, by, 0, bx, by, br * 2);
            g.addColorStop(0, col); g.addColorStop(0.5, col + '55'); g.addColorStop(1, col + '00');
            ctx.fillStyle = g; ctx.beginPath(); ctx.arc(bx, by, br * 2, 0, Math.PI * 2); ctx.fill();
        }
        if (b.b > 0) {
            ctx.beginPath(); ctx.arc(bx, by, br + 3, 0, Math.PI * 2);
            ctx.strokeStyle = 'rgba(50,220,100,0.75)'; ctx.lineWidth = 1.5; ctx.stroke();
        }
        // Ring back arc — drawn before body so body fill covers the centre portion
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
        // Ring front arc — drawn after body fill so it appears in front
        if (b.ri > 0) {
            ctx.beginPath();
            ctx.ellipse(bx, by, br * 2.2, br * 0.52, Math.PI * 0.2, Math.PI, Math.PI * 2);
            ctx.strokeStyle = 'rgba(210,210,255,0.9)'; ctx.lineWidth = 1; ctx.stroke();
        }
        if (b.f) {
            ctx.font = 'bold 6px sans-serif';
            ctx.fillStyle = '#ffee44';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'alphabetic';
            ctx.fillText('★', bx, by - br - 3);
        }

        // Index label: strip system prefix, show at upper-right of icon
        var lbl = b.n;
        var lpfx = _sysData.name + ' ';
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

// Modal events and tooltip (script is at end of <body>, DOM is ready)
(function() {
    var canvas = document.getElementById('sys-canvas');
    var tip    = document.getElementById('sys-tip');
    if (!canvas) return;

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
            // Use fixed viewport coords — tooltip never causes scrollbar flicker
            var scale = rect.width / canvas.width;
            var cx = rect.left + best.x * scale;
            var cy = rect.top  + best.y * scale;
            var tw = tip.offsetWidth, th = tip.offsetHeight;
            var tx = cx + 14;
            var ty = cy - 10;
            if (tx + tw + 8 > window.innerWidth)  tx = cx - tw - 14;
            if (ty + th + 8 > window.innerHeight) ty = cy - th - 10;
            if (ty < 4) ty = 4;
            if (tx < 4) tx = 4;
            tip.style.left = tx + 'px'; tip.style.top = ty + 'px';
        } else {
            tip.classList.remove('visible');
        }
    });
    canvas.addEventListener('mouseleave', function() { tip.classList.remove('visible'); });

    var bg    = document.getElementById('sys-modal-bg');
    var close = document.getElementById('sys-modal-close');
    if (bg)    bg.addEventListener('click', closeSysModal);
    if (close) close.addEventListener('click', closeSysModal);
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeSysModal(); });
    document.addEventListener('click', function(e) {
        var link = e.target.closest('.sys-link');
        if (link && link.dataset.sa) openSysModal(link.dataset.sa, link.textContent.trim());
    });
// END_SYS_DIAGRAM
}());
"""


# Extracted sub-sections for reuse in the trip report
_SYS_MODAL_CSS = _CSS[_CSS.index("/* ---- System diagram modal"):
                       _CSS.index("/* END_SYS_MODAL_CSS */")]

_SYS_MODAL_JS = _JS[_JS.index("// ---- System Diagram ----"):
                     _JS.index("// END_SYS_DIAGRAM")]

_SYS_MODAL_HTML = """\
<div id="sys-modal" class="sys-modal">
  <div class="sys-modal-bg" id="sys-modal-bg"></div>
  <div class="sys-modal-box">
    <div class="sys-modal-hdr">
      <span id="sys-modal-ttl" class="sys-modal-ttl">–</span>
      <span id="sys-modal-sc"  class="sys-modal-sc"></span>
      <button class="sys-modal-close" id="sys-modal-close">✕</button>
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
</div>"""


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
<div id="sys-modal" class="sys-modal">
  <div class="sys-modal-bg" id="sys-modal-bg"></div>
  <div class="sys-modal-box">
    <div class="sys-modal-hdr">
      <span id="sys-modal-ttl" class="sys-modal-ttl">–</span>
      <span id="sys-modal-sc"  class="sys-modal-sc"></span>
      <button class="sys-modal-close" id="sys-modal-close">✕</button>
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
  <script>__SYS_DATA_PLACEHOLDER__</script>
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


def _spectral_img(b64: str | None) -> str:
    """Spectral distribution chart rendered at natural resolution."""
    if not b64:
        return ""
    return f'<img class="static-chart" src="data:image/png;base64,{b64}" style="margin-top:8px">'


def _plotly(fig: go.Figure | None) -> str:
    if fig is None:
        return '<p class="empty-note">No data available.</p>'
    return f'<div class="plotly-wrap">{fig.to_html(full_html=False, include_plotlyjs=False)}</div>'


_3D_NAV_HINT = (
    '<p class="map-nav-hint">'
    '<kbd>drag</kbd> rotate &nbsp;·&nbsp;'
    '<kbd>right-drag</kbd> pan &nbsp;·&nbsp;'
    '<kbd>scroll</kbd> zoom &nbsp;·&nbsp;'
    'reset: hover chart → ⌂ in toolbar'
    '</p>'
)


def _plotly_exclusive_legend(
    fig: go.Figure,
    div_id: str,
    n_exclusive: int,
    layer_titles: list[str] | None = None,
) -> str:
    """Plotly figure where the first n_exclusive traces are mutually exclusive in the legend.

    Clicking a data-layer entry: shows that layer, sets others to 'legendonly',
    updates the chart title, and preserves the current visibility of all
    non-data traces (regions, landmarks, etc.).
    """
    html = fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id)
    titles_js = json.dumps(layer_titles or [])
    js = f"""
(function() {{
  function init() {{
    var gd = document.getElementById('{div_id}');
    if (!gd || !gd.on) {{ setTimeout(init, 50); return; }}
    var N = {n_exclusive};
    var titles = {titles_js};
    gd.on('plotly_legendclick', function(evt) {{
      var c = evt.curveNumber;
      if (typeof c !== 'number' || isNaN(c) || c < 0 || c >= N) return true;
      var vis = gd.data.map(function(t, i) {{
        if (i < N) return i === c ? true : 'legendonly';
        return t.visible === undefined ? true : t.visible;
      }});
      Plotly.restyle(gd, 'visible', vis);
      if (titles[c]) Plotly.relayout(gd, {{'title.text': titles[c]}});
      return false;
    }});
    gd.on('plotly_legenddoubleclick', function(evt) {{
      var c = evt.curveNumber;
      if (typeof c !== 'number' || isNaN(c) || c < 0 || c >= N) return true;
      return false;
    }});
  }}
  init();
}})();
"""
    return f'<div class="plotly-wrap">{html}<script>{js}</script></div>'


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
    rows = []
    for _, r in df.iterrows():
        sa = r.get("system_address")
        name = r["Body / System"]
        ref = (f'<span class="sys-link" data-sa="{int(sa)}">{name}</span>'
               if sa and str(sa) not in ("", "nan") else name)
        rows.append(
            f'<tr><td>{r["Record"]}</td><td>{ref}</td>'
            f'<td class="val">{_fmt(r)}</td></tr>'
        )
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

    def _sys_ref(name: str, sa) -> str:
        if sa and str(sa) not in ("", "nan"):
            return f'<span class="sys-link" data-sa="{int(sa)}">{name}</span>'
        return name

    for _, r in helium_boxels.iterrows():
        he_range = (f"{r['he_min']:.1f}–{r['he_max']:.1f}%"
                    if abs(r["he_max"] - r["he_min"]) > 0.1
                    else f"{r['he_mean']:.1f}%")
        entries.append((float(r["dist"]),
            '<li><div class="hint-card">'
            '<div class="hint-body">'
            '<span class="hint-type">Potential helium-rich boxel</span>'
            f'<div class="hint-coords">{_sys_ref(r["nearest_system"], r.get("nearest_system_address"))}</div>'
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
            f'<div class="hint-coords">{_sys_ref(r["nearest_system"], r.get("nearest_system_address"))}</div>'
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
            f'<div class="hint-coords">{_sys_ref(r["nearest_system"], r.get("nearest_system_address"))}</div>'
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
                        genus: str, species_values: dict,
                        spectral_chart: str = "") -> str:
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
        sa  = r.get("system_address", "")
        sys_html = (f'<span class="sys-link" data-sa="{sa}">{sys}</span>'
                    if sa and sys != "—" else sys)
        bod_html = (f'<span class="sys-link" data-sa="{sa}">{bod}</span>'
                    if sa and bod != "—" else bod)
        rows.append(
            f"<tr><td>{ts}</td><td>{sys_html}</td><td>{bod_html}</td>"
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
        + card + table + spectral_chart
    )


def _genus_panel_html(genus: str, genus_df: pd.DataFrame,
                      species_values: dict,
                      spectral_chart: str = "") -> str:
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
    return card + table + spectral_chart


_STAR_CLASS_GROUPS: list[tuple[str, list[str]]] = [
    ("Main Sequence Stars",    ["O", "B", "A", "F", "G", "K", "M"]),
    ("Giants and Supergiants", ["A_BlueWhiteSuperGiant", "B_BlueWhiteSuperGiant",
                                "K_OrangeGiant", "M_RedGiant", "M_RedSuperGiant"]),
    ("Proto Stars",            ["AeBe", "TTS"]),
    ("Carbon Stars",           ["C", "CH", "CHd", "CJ", "CN", "CS", "MS", "S"]),
    ("Wolf-Rayet Stars",       ["W", "WC", "WN", "WNC", "WO"]),
    ("White Dwarfs",           ["D", "DA", "DAB", "DAV", "DAZ", "DB", "DBV",
                                "DC", "DCV", "DO", "DOV", "DQ", "DX"]),
    ("Neutron Stars",          ["N"]),
    ("Black Holes",            ["H", "SupermassiveBlackHole"]),
    ("Brown Dwarfs",           ["L", "T", "Y"]),
]


_HORIZONS_GENERA = frozenset({
    "Amphora Plant", "Anemone", "Bark Mounds",
    "Brain Trees", "Crystalline Shards", "Sinuous Tubers",
})


def _build_species_section(oval_df: pd.DataFrame,
                           sp_charts: dict[str, str] | None = None,
                           genus_charts: dict[str, str] | None = None) -> str:
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
            chart = _spectral_img((sp_charts or {}).get(species)) if sp_charts else ""
            panels[sp_id] = _species_panel_html(
                species, sp_grp, genus_label, SPECIES_VALUES, chart)

        chart = _spectral_img((genus_charts or {}).get(genus_label)) if genus_charts else ""
        panels[genus_panel_id] = _genus_panel_html(
            genus_label, genus_df, SPECIES_VALUES, chart)
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
# Notable Stellar Phenomena
# ---------------------------------------------------------------------------

# Ordered: Seed Pods before Plants so "Gyre Pod" doesn't match "Gyre Tree" rule.
_NSP_TAXONOMY: list[tuple[str, str, str]] = [
    # (keyword_in_display_name,  category,             subcategory)
    ("E-Type",            "Anomalies",          "E-Type Anomalies"),
    ("K-Type",            "Anomalies",          "K-Type Anomalies"),
    ("L-Type",            "Anomalies",          "L-Type Anomalies"),
    ("P-Type",            "Anomalies",          "P-Type Anomalies"),
    ("Q-Type",            "Anomalies",          "Q-Type Anomalies"),
    ("T-Type",            "Anomalies",          "T-Type Anomalies"),
    ("Storm Cloud",       "Lagrange Clouds",    "Storm Clouds"),
    ("Lagrange Cloud",    "Lagrange Clouds",    "Lagrange Clouds"),
    ("Calcite Plate",     "Mineral Formations", "Calcite Plates"),
    ("Ice Crystal",       "Mineral Formations", "Ice Crystals"),
    ("Lattice Mineral",   "Mineral Formations", "Lattice Mineral Spheres"),
    ("Metallic Crystal",  "Mineral Formations", "Metallic Crystals"),
    ("Silicate Crystal",  "Mineral Formations", "Silicate Crystals"),
    ("Solid Mineral",     "Mineral Formations", "Solid Mineral Spheres"),
    ("Aster Pod",         "Seed Pods",          "Aster Pods"),
    ("Chalice Pod",       "Seed Pods",          "Chalice Pods"),
    ("Collared Pod",      "Seed Pods",          "Collared Pods"),
    ("Gyre Pod",          "Seed Pods",          "Gyre Pods"),
    ("Octahedral Pod",    "Seed Pods",          "Octahedral Pods"),
    ("Peduncle Pod",      "Seed Pods",          "Peduncle Pods"),
    ("Quadripartite Pod", "Seed Pods",          "Quadripartite Pods"),
    ("Rhizome Pod",       "Seed Pods",          "Rhizome Pods"),
    ("Stolon Pod",        "Seed Pods",          "Stolon Pods"),
    ("Aster Tree",        "Plants",             "Aster Trees"),
    ("Gyre Tree",         "Plants",             "Gyre Trees"),
    ("Peduncle Tree",     "Plants",             "Peduncle Trees"),
    ("Stolon Tree",       "Plants",             "Stolon Trees"),
    ("Void Heart",        "Plants",             "Void Hearts"),
    ("Bell Mollusc",      "Molluscs",           "Bell Molluscs"),
    ("Bulb Mollusc",      "Molluscs",           "Bulb Molluscs"),
    ("Bullet Mollusc",    "Molluscs",           "Bullet Molluscs"),
    ("Capsule Mollusc",   "Molluscs",           "Capsule Molluscs"),
    ("Globe Mollusc",     "Molluscs",           "Globe Molluscs"),
    ("Gourd Mollusc",     "Molluscs",           "Gourd Molluscs"),
    ("Parasol Mollusc",   "Molluscs",           "Parasol Molluscs"),
    ("Reel Mollusc",      "Molluscs",           "Reel Molluscs"),
    ("Squid Mollusc",     "Molluscs",           "Squid Molluscs"),
    ("Torus Mollusc",     "Molluscs",           "Torus Molluscs"),
    ("Umbrella Mollusc",  "Molluscs",           "Umbrella Molluscs"),
]

_NSP_CATEGORY_ORDER = [
    "Anomalies",
    "Lagrange Clouds",
    "Mineral Formations",
    "Molluscs",
    "Plants",
    "Seed Pods",
]


# Fallback classifier keyed on raw codex name when name_localised is null.
# IMPORTANT: more-specific prefixes MUST come before shorter/broader ones.
# Lagrange Cloud organisms use $Codex_Ent_LagrangeCloud_<type>_ prefix,
# so they must be listed before the bare $Codex_Ent_LagrangeCloud catch-all.
_NSP_CODEX_TAXONOMY: list[tuple[str, str, str]] = [
    # Real in-game codex key prefixes (fires when name_localised is null).
    # Anomalies — particle clouds
    ("$Codex_Ent_L_Phn_Part_",          "Anomalies",          "Anomaly"),
    # Lagrange Clouds (Storm variants have _Storm_ in the name but same prefix)
    ("$Codex_Ent_Gas_Clds_",            "Lagrange Clouds",    "Lagrange Clouds"),
    # Mineral Formations — crystals (specific before generic)
    ("$Codex_Ent_L_Cry_IcCry_",         "Mineral Formations", "Ice Crystals"),
    ("$Codex_Ent_L_Cry_MetCry_",        "Mineral Formations", "Metallic Crystals"),
    ("$Codex_Ent_L_Cry_QtzCry_",        "Mineral Formations", "Silicate Crystals"),
    ("$Codex_Ent_L_Cry_",               "Mineral Formations", "Crystals"),
    # Mineral Formations — other space formations
    ("$Codex_Ent_L_Org_PltFun_",        "Mineral Formations", "Calcite Plates"),
    ("$Codex_Ent_SPOI_Ball_Lattice",    "Mineral Formations", "Lattice Mineral Spheres"),
    ("$Codex_Ent_SPOI_Ball_",           "Mineral Formations", "Solid Mineral Spheres"),
    # Molluscs — large (L_Org_Moll03: V1=Parasol, V2=Bulb, V3=Umbrella, V4=Capsule, V6=Reel)
    ("$Codex_Ent_L_Org_Moll03_V1_",    "Molluscs",           "Parasol Molluscs"),
    ("$Codex_Ent_L_Org_Moll03_V2_",    "Molluscs",           "Bulb Molluscs"),
    ("$Codex_Ent_L_Org_Moll03_V3_",    "Molluscs",           "Umbrella Molluscs"),
    ("$Codex_Ent_L_Org_Moll03_V4_",    "Molluscs",           "Capsule Molluscs"),
    ("$Codex_Ent_L_Org_Moll03_V6_",    "Molluscs",           "Reel Molluscs"),
    ("$Codex_Ent_L_Org_Moll03_",       "Molluscs",           "Mollusc"),
    # Molluscs — small (V1=Gourd, V2=Torus, V3=Squid, V4=Bullet, V5=Globe, V6=Bell)
    ("$Codex_Ent_Small_Org_Moll01_V1_","Molluscs",           "Gourd Molluscs"),
    ("$Codex_Ent_Small_Org_Moll01_V2_","Molluscs",           "Torus Molluscs"),
    ("$Codex_Ent_Small_Org_Moll01_V3_","Molluscs",           "Squid Molluscs"),
    ("$Codex_Ent_Small_Org_Moll01_V4_","Molluscs",           "Bullet Molluscs"),
    ("$Codex_Ent_Small_Org_Moll01_V5_","Molluscs",           "Globe Molluscs"),
    ("$Codex_Ent_Small_Org_Moll01_V6_","Molluscs",           "Bell Molluscs"),
    ("$Codex_Ent_Small_Org_Moll01_",   "Molluscs",           "Mollusc"),
    # Plants
    ("$Codex_Ent_L_Seed_Pln01_",       "Plants",             "Peduncle Trees"),
    ("$Codex_Ent_L_Seed_Pln02_",       "Plants",             "Aster Trees"),
    ("$Codex_Ent_L_Seed_SdRt02_",      "Plants",             "Stolon Trees"),
    ("$Codex_Ent_L_Seed_",             "Plants",             "Plant"),
    ("$Codex_Ent_SPOI_SeedPolyp01_",   "Plants",             "Gyre Trees"),
    ("$Codex_Ent_SPOI_SeedWeed01_",    "Plants",             "Void Hearts"),
    # Seed Pods
    ("$Codex_Ent_S_Seed_SdTp01_",      "Seed Pods",          "Peduncle Pods"),
    ("$Codex_Ent_S_Seed_SdTp02_",      "Seed Pods",          "Aster Pods"),
    ("$Codex_Ent_S_Seed_SdTp03_",      "Seed Pods",          "Octahedral Pods"),
    ("$Codex_Ent_S_Seed_SdTp04_",      "Seed Pods",          "Collared Pods"),
    ("$Codex_Ent_S_Seed_SdTp05_",      "Seed Pods",          "Chalice Pods"),
    ("$Codex_Ent_S_Seed_SdTp06_",      "Seed Pods",          "Gyre Pods"),
    ("$Codex_Ent_S_Seed_SdTp07_",      "Seed Pods",          "Rhizome Pods"),
    ("$Codex_Ent_S_Seed_SdTp08_",      "Seed Pods",          "Quadripartite Pods"),
    ("$Codex_Ent_S_Seed_",             "Seed Pods",          "Seed Pod"),
    ("$Codex_Ent_SPOI_Root_Seeds_",    "Seed Pods",          "Stolon Pods"),
]




_ANOMALY_NUM_RE = re.compile(r'\b([a-z])\d+-type anomaly\b', re.IGNORECASE)
_ANOMALY_LETTER_MAP = {
    'E': 'E-Type Anomalies', 'K': 'K-Type Anomalies',
    'L': 'L-Type Anomalies', 'P': 'P-Type Anomalies',
    'Q': 'Q-Type Anomalies', 'T': 'T-Type Anomalies',
}

_CODEX_REGION_NAMES: dict[int, str] = {
    1: "Galactic Centre", 2: "Empyrean Straits", 3: "Ryker's Hope",
    4: "Odin's Hold", 5: "Norma Arm", 6: "Arcadian Stream",
    7: "Izanami", 8: "Inner Orion-Perseus Conflux",
    9: "Inner Scutum-Centaurus Arm", 10: "Norma Expanse",
    11: "Trojan Belt", 12: "The Veils", 13: "Newton's Vault",
    14: "The Conduit", 15: "Outer Orion-Perseus Conflux",
    16: "Orion-Cygnus Arm", 17: "Temple", 18: "Inner Orion Spur",
    19: "Hawking's Gap", 20: "Dryman's Point",
    21: "Sagittarius-Carina Arm", 22: "Mare Somnia", 23: "Acheron",
    24: "Formorian Frontier", 25: "Hieronymus Delta",
    26: "Outer Scutum-Centaurus Arm", 27: "Outer Arm",
    28: "Aquila's Halo", 29: "Errant Marches", 30: "Perseus Arm",
    31: "Formidine Rift", 32: "Vulcan Gate", 33: "Elysian Shore",
    34: "Sanguineous Rim", 35: "Outer Orion Spur",
    36: "Achilles's Altar", 37: "Xibalba", 38: "Lyra's Song",
    39: "Tenebrae", 40: "The Abyss", 41: "Kepler's Crest",
    42: "The Void",
}
_CODEX_REGION_RE = re.compile(r'\$Codex_RegionName_(\d+)', re.IGNORECASE)


def _decode_region(raw: str | None) -> str:
    if not raw:
        return "—"
    m = _CODEX_REGION_RE.search(raw)
    if m:
        return _CODEX_REGION_NAMES.get(int(m.group(1)), raw)
    return raw


def _classify_nsp(display_name: str,
                  codex_name: str = "",
                  sub_category: str = "") -> tuple[str, str]:
    dn = (display_name or "").lower()

    # Handle numbered anomaly variants: "K01-Type Anomaly", "E04-Type Anomaly" etc.
    m = _ANOMALY_NUM_RE.search(dn)
    if m:
        letter = m.group(1).upper()
        return "Anomalies", _ANOMALY_LETTER_MAP.get(letter, f"{letter}-Type Anomalies")

    # 1. Localised display name keyword match
    for kw, cat, subcat in _NSP_TAXONOMY:
        if kw.lower() in dn:
            return cat, subcat

    # 2. Raw codex key prefix match (fires when name_localised is null)
    cn = codex_name if isinstance(codex_name, str) else ""
    if cn:
        for prefix, cat, subcat in _NSP_CODEX_TAXONOMY:
            if cn.startswith(prefix):
                return cat, subcat

    # 3. Sub-category field fallback (broad but reliable)
    sc = (sub_category or "").lower()
    label = display_name if display_name and not display_name.startswith("$") else "Unknown"
    if "anomal" in sc:
        return "Anomalies", label
    # "lagrange" in sub_category only means "Lagrange Cloud" when no more specific
    # codex prefix matched above — i.e. it really is the cloud entity itself.
    if "lagrange" in sc and not cn:
        return "Lagrange Clouds", label
    if "mollusc" in sc:
        return "Molluscs", label
    if "plant" in sc or "tree" in sc:
        return "Plants", label
    if "pod" in sc:
        return "Seed Pods", label
    if "mineral" in sc or "formation" in sc or "crystal" in sc:
        return "Mineral Formations", label
    if "organic" in sc:
        # Broad organic structures — try to narrow by codex_name fragment
        cn_l = cn.lower()
        for frag, cat, subcat in [
            ("torus",     "Molluscs",  "Torus Molluscs"),
            ("bell",      "Molluscs",  "Bell Molluscs"),
            ("bulb",      "Molluscs",  "Bulb Molluscs"),
            ("bullet",    "Molluscs",  "Bullet Molluscs"),
            ("capsule",   "Molluscs",  "Capsule Molluscs"),
            ("globe",     "Molluscs",  "Globe Molluscs"),
            ("gourd",     "Molluscs",  "Gourd Molluscs"),
            ("parasol",   "Molluscs",  "Parasol Molluscs"),
            ("reel",      "Molluscs",  "Reel Molluscs"),
            ("squid",     "Molluscs",  "Squid Molluscs"),
            ("umbrella",  "Molluscs",  "Umbrella Molluscs"),
            ("gyre",      "Plants",    "Gyre Trees"),
            ("aster",     "Plants",    "Aster Trees"),
            ("peduncle",  "Plants",    "Peduncle Trees"),
            ("stolon",    "Plants",    "Stolon Trees"),
            ("void",      "Plants",    "Void Hearts"),
            ("chalice",   "Seed Pods", "Chalice Pods"),
            ("collar",    "Seed Pods", "Collared Pods"),
            ("octahedral","Seed Pods", "Octahedral Pods"),
            ("quadri",    "Seed Pods", "Quadripartite Pods"),
            ("rhizome",   "Seed Pods", "Rhizome Pods"),
        ]:
            if frag in cn_l or frag in dn:
                return cat, subcat
        return "Molluscs", label  # safest default for organic structures

    return "Other", display_name or "Unknown"


def _nsp_category_panel_html(cat: str, df_cat: pd.DataFrame) -> str:
    n_sys = df_cat["system_name"].nunique()
    n_new = int(df_cat["is_new_entry"].sum())
    n_sub = df_cat["nsp_subcat"].nunique()
    return _stats_card([
        ("Types found",     f"{n_sub:,}"),
        ("Systems scanned", f"{n_sys:,}"),
        ("New codex entries", f"{n_new:,}"),
    ])


def _nsp_subcat_panel_html(df_sub: pd.DataFrame, cur_pos: dict | None) -> str:
    df_sub = df_sub.drop_duplicates(subset=["system_address", "display_name"])
    dist_th = "<th>Distance</th>" if cur_pos else ""
    rows = []
    for _, r in df_sub.iterrows():
        sa  = r.get("system_address")
        sys = r.get("system_name", "—")
        nm  = r.get("display_name") or "—"
        reg = _decode_region(r.get("region"))
        ts  = str(r.get("timestamp", ""))[:10]
        new = '<span class="check">✓</span>' if r.get("is_new_entry") else ""
        d   = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
        sys_html = (f'<span class="sys-link" data-sa="{int(sa)}">{sys}</span>'
                    if sa else sys)
        rows.append(
            f"<tr><td>{nm}</td>"
            f'<td style="text-align:center">{new}</td>'
            f"<td>{reg}</td><td>{ts}</td><td>{sys_html}</td>"
            + (f'<td class="num" data-sort="{d:.0f}">{_fmt_dist(d)}</td>' if cur_pos else "")
            + "</tr>"
        )
    if not rows:
        return '<p class="empty-note">No entries found.</p>'
    return (
        '<div class="table-wrap"><table class="detail-table sortable"><thead>'
        f"<tr><th>Variant</th><th>New codex entry</th><th>Region</th>"
        f"<th>Date</th><th>System</th>{dist_th}</tr>"
        f'</thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _build_nsp_section(df_det: "pd.DataFrame", df_codex: "pd.DataFrame",
                       cur_pos: dict | None = None) -> str:
    # ── Classify codex entries ────────────────────────────────────────────────
    df = df_codex.copy()
    if not df.empty:
        df["nsp_cat"], df["nsp_subcat"] = zip(*df.apply(
            lambda r: _classify_nsp(
                r["display_name"],
                r["codex_name"] if isinstance(r.get("codex_name"), str) else "",
                r["sub_category"] if isinstance(r.get("sub_category"), str) else "",
            ),
            axis=1,
        ))

    # ── Overview panel ────────────────────────────────────────────────────────
    n_det  = len(df_det)
    n_cod  = len(df)
    n_new  = int(df["is_new_entry"].sum()) if not df.empty else 0
    n_sys  = df["system_name"].nunique()   if not df.empty else 0
    n_cats = df["nsp_cat"].nunique()       if not df.empty else 0

    overview_card = _stats_card([
        ("Systems with NSP signals", f"{n_det:,}"),
        ("Codex entries recorded",   f"{n_cod:,}"),
        ("New codex entries",         f"{n_new:,}"),
        ("Unique systems scanned",   f"{n_sys:,}"),
        ("Categories found",         f"{n_cats:,}"),
    ])

    dist_th = "<th>Distance</th>" if cur_pos else ""

    # Build display_name -> hex color matching the 3D map coloring
    nsp_color_lookup: dict[str, str] = {}
    if not df.empty:
        _cat_subcat_order: dict[str, list[str]] = {
            cat: sorted(grp["nsp_subcat"].unique())
            for cat, grp in df.groupby("nsp_cat")
        }
        for dn, cat, subcat in (
            df[["display_name", "nsp_cat", "nsp_subcat"]]
            .drop_duplicates()
            .itertuples(index=False)
        ):
            subcats = _cat_subcat_order.get(cat, [subcat])
            idx = subcats.index(subcat) if subcat in subcats else 0
            nsp_color_lookup[dn] = mp._nsp_color(cat, idx, len(subcats))

    def _nsp_tag(name: str) -> str:
        fg = nsp_color_lookup.get(name, "#88ddaa")
        r, g, b = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
        bg = f"#{r // 5:02x}{g // 5:02x}{b // 5:02x}"
        return (f'<span class="bio-tag" style="color:{fg};border-color:{fg};'
                f'background:{bg}">{name}</span>')

    # Build system_address -> sorted unique NSP display names from codex data
    nsp_by_sys: dict[int, list[str]] = {}
    if not df.empty and "system_address" in df.columns:
        for sa_val, grp in df.groupby("system_address"):
            nsp_by_sys[int(sa_val)] = sorted(grp["display_name"].dropna().unique().tolist())

    # FSS detections table
    det_rows = []
    for _, r in df_det.iterrows():
        sa  = r.get("system_address")
        sys = r.get("system_name", "—")
        sc  = r.get("star_class") or "—"
        ts  = str(r.get("detected_at", ""))[:10]
        d   = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
        sys_html = (f'<span class="sys-link" data-sa="{int(sa)}">{sys}</span>'
                    if sa else sys)
        nsps = nsp_by_sys.get(int(sa), []) if sa else []
        nsp_cell = (
            " ".join(_nsp_tag(n) for n in nsps)
            if nsps else '<span class="dim">not catalogued</span>'
        )
        det_rows.append(
            f'<tr><td class="nowrap">{sys_html}</td>'
            f'<td class="nowrap">{sc}</td>'
            f'<td class="nowrap">{ts}</td>'
            f"<td>{nsp_cell}</td>"
            + (f'<td class="num nowrap" data-sort="{d:.0f}">{_fmt_dist(d)}</td>' if cur_pos else "")
            + "</tr>"
        )
    det_html = (
        '<div class="table-wrap"><table class="detail-table sortable"><thead>'
        f"<tr><th>System</th><th>Star class</th><th>Detected</th><th>NSPs found</th>{dist_th}</tr>"
        f'</thead><tbody>{"".join(det_rows)}</tbody></table></div>'
        if det_rows else
        '<p class="empty-note">No NSP signals recorded — FSS scan data required.</p>'
    )

    # Galaxy map (needs nsp_cat / nsp_subcat columns)
    map_fig = mp.plot_nsp_map_3d(df if not df.empty else df_codex,
                                  current_pos=cur_pos)
    map_html = (_plotly(map_fig) + _3D_NAV_HINT if map_fig is not None
                else '<p class="empty-note">No codex data for map.</p>')

    overview_panel_id = "nsp-overview"
    panels: dict[str, str] = {
        overview_panel_id: (
            overview_card
            + _tab_group("nsp-ov", [
                ("NSP Map",        map_html),
                ("FSS Detections", det_html),
            ])
        )
    }

    # ── Category groups (mirrors _build_species_section pattern) ─────────────
    cat_groups: list[tuple[str, str, list[tuple[str, str]]]] = []
    cat_idx = sc_idx = 0

    ordered_cats = _NSP_CATEGORY_ORDER + (
        ["Other"] if not df.empty and "Other" in df["nsp_cat"].values else []
    )
    for cat in ordered_cats:
        if df.empty:
            continue
        df_cat = df[df["nsp_cat"] == cat]
        if df_cat.empty:
            continue

        cat_panel_id = f"nsp-cat-{cat_idx}"
        cat_idx += 1
        panels[cat_panel_id] = _nsp_category_panel_html(cat, df_cat)

        subcat_items: list[tuple[str, str]] = []
        for subcat, df_sub in df_cat.groupby("nsp_subcat", sort=True):
            sc_id = f"nsp-sc-{sc_idx}"
            sc_idx += 1
            n = df_sub["system_name"].nunique()
            subcat_items.append((f"{subcat} ({n:,})", sc_id))
            panels[sc_id] = _nsp_subcat_panel_html(df_sub, cur_pos)

        cat_groups.append((cat, cat_panel_id, subcat_items))

    # ── List block ────────────────────────────────────────────────────────────
    btns = [
        f'<button class="detail-btn detail-overview-btn active" '
        f'data-panel="{overview_panel_id}">Overview</button>',
        '<input type="search" placeholder="Search…">',
    ]
    for cat_label, cat_panel_id, subcat_items in cat_groups:
        sc_btns = "".join(
            f'<button class="detail-btn species-btn" data-panel="{sc_id}" '
            f'data-label="{label}">{label}</button>'
            for label, sc_id in subcat_items
        )
        btns.append(
            f'<div class="genus-group">'
            f'<button class="detail-btn genus-header" data-panel="{cat_panel_id}" '
            f'data-label="{cat_label}">{cat_label}</button>'
            f'<div class="genus-items">{sc_btns}</div>'
            f'</div>'
        )
    list_block = f'<div class="detail-list">{"".join(btns)}</div>'

    # ── Content block ─────────────────────────────────────────────────────────
    panel_html = [
        f'<div class="detail-panel active" id="{overview_panel_id}">'
        f'{panels[overview_panel_id]}</div>'
    ]
    for cat_label, cat_panel_id, subcat_items in cat_groups:
        panel_html.append(
            f'<div class="detail-panel" id="{cat_panel_id}">'
            f'{panels[cat_panel_id]}</div>'
        )
        for label, sc_id in subcat_items:
            panel_html.append(
                f'<div class="detail-panel" id="{sc_id}">'
                f'{panels[sc_id]}</div>'
            )

    content_block = f'<div class="detail-content">{"".join(panel_html)}</div>'
    return f'<div class="detail-layout">{list_block}{content_block}</div>'


# ---------------------------------------------------------------------------
# Body-type catalogue
# ---------------------------------------------------------------------------

def _build_body_section(bval_df: pd.DataFrame, cur_pos: dict | None = None,
                        bt_charts: dict[str, str] | None = None) -> str:
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
            ("ring_outer_max_km",   "Ring outer radius (km)",   "{:,.0f}"),
        ]:
            if col not in grp.columns:
                continue
            valid = grp[[col, "name", "system_address"]].dropna(subset=[col])
            valid = valid[valid[col] > 0]
            if len(valid) < 2:
                continue
            idx_min = valid[col].idxmin()
            idx_max = valid[col].idxmax()
            min_name = valid.loc[idx_min, "name"]
            min_sa   = int(valid.loc[idx_min, "system_address"])
            max_name = valid.loc[idx_max, "name"]
            max_sa   = int(valid.loc[idx_max, "system_address"])
            prop_rows.append(
                f"<tr><td>{lbl}</td>"
                f'<td class="hint-col-min"><span class="sys-link" data-sa="{min_sa}">{min_name}</span></td>'
                f'<td class="num num-center">{fmt.format(valid.loc[idx_min, col])}</td>'
                f'<td class="num num-center">{fmt.format(valid[col].mean())}</td>'
                f'<td class="num num-center">{fmt.format(valid.loc[idx_max, col])}</td>'
                f'<td class="hint-col"><span class="sys-link" data-sa="{max_sa}">{max_name}</span></td></tr>'
            )

        sys_counts = grp.groupby("system_name").size()
        top_sys = sys_counts.idxmax()
        top_sa = int(grp.loc[grp["system_name"] == top_sys, "system_address"].iloc[0])
        prop_rows.append(
            f"<tr><td>Most in system</td>"
            f'<td class="hint-col-min"></td><td class="num num-center"></td><td class="num num-center"></td>'
            f'<td class="num">{int(sys_counts.max())}</td>'
            f'<td class="hint-col"><span class="sys-link" data-sa="{top_sa}">{top_sys}</span></td></tr>'
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
            d  = _dist_ly(cur_pos, r.get("x"), r.get("y"), r.get("z"))
            sa = int(r["system_address"]) if r.get("system_address") else None
            body_name = r.get("name", "")
            sys_name  = r.get("system_name", "")
            body_cell = (f'<span class="sys-link" data-sa="{sa}">{body_name}</span>'
                         if sa else body_name)
            sys_cell  = (f'<span class="sys-link" data-sa="{sa}">{sys_name}</span>'
                         if sa and sys_name else sys_name)
            top_rows.append(
                f"<tr>"
                f"<td>{body_cell}</td>"
                f"<td>{sys_cell}</td>"
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

        chart = _spectral_img((bt_charts or {}).get(planet_class)) if bt_charts else ""
        panels[panel_id] = card + prop_block + top_block + chart

    def _panel(label, panel_id, is_first):
        active = " active" if is_first else ""
        return f'<div class="detail-panel{active}" id="{panel_id}">{panels[panel_id]}</div>'

    return _detail_layout("bt", list_items, _panel, overview_html=_body_overview(bval_df))


# ---------------------------------------------------------------------------
# Star-class catalogue
# ---------------------------------------------------------------------------



def _star_group_panel_html(group_name: str, group_df: pd.DataFrame) -> str:
    n_classes  = group_df["star_class"].nunique()
    n_systems  = len(group_df)
    tot_bodies = int(group_df["body_count"].sum())
    avg_bodies = group_df["body_count"].mean() if n_systems > 0 else 0.0

    card = _stats_card([
        ("Star classes",      f"{n_classes:,}"),
        ("Systems",           f"{n_systems:,}"),
        ("Total bodies",      f"{tot_bodies:,}"),
        ("Avg bodies/system", f"{avg_bodies:.1f}"),
    ])

    by_class = (
        group_df.groupby("star_class")
        .agg(systems=("star_class", "count"),
             bodies=("body_count", "sum"),
             avg_bodies=("body_count", "mean"))
        .reset_index()
        .sort_values("systems", ascending=False)
    )
    rows = "".join(
        f"<tr><td>{r['star_class']}</td>"
        f'<td class="num">{int(r["systems"]):,}</td>'
        f'<td class="num">{int(r["bodies"]):,}</td>'
        f'<td class="num">{r["avg_bodies"]:.1f}</td></tr>'
        for _, r in by_class.iterrows()
    )
    table = (
        '<div class="table-wrap"><table class="detail-table"><thead>'
        "<tr><th>Class</th><th>Systems</th><th>Bodies</th><th>Avg bodies</th></tr>"
        f'</thead><tbody>{rows}</tbody></table></div>'
    )
    return card + table


def _build_star_section(star_df: pd.DataFrame, cur_pos: dict | None = None,
                        star_body_df: pd.DataFrame | None = None) -> str:
    if star_df.empty:
        return '<p class="empty-note">No star data available.</p>'

    body_by_class: dict = {}
    if star_body_df is not None and not star_body_df.empty:
        for sc, grp in star_body_df.groupby("star_class", sort=False):
            body_by_class[sc] = grp

    # Build per-class panels
    sc_idx = 0
    panels: dict[str, str] = {}
    sc_panel_ids: dict[str, str] = {}

    for star_class, grp in star_df.groupby("star_class", sort=True):
        panel_id       = f"sc-{sc_idx}"
        sc_idx        += 1
        n_systems      = len(grp)
        total_bodies   = int(grp["body_count"].sum())
        bio_systems    = int((grp["bodies_with_bio"] > 0).sum())
        first_disc_sys = int(grp["has_first_disc"].sum())
        avg_bodies     = grp["body_count"].mean()

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
                ("surface_temp_k",     "Surface temperature (K)", "{:.0f}"),
                ("radius_sr",          "Solar radius",            "{:.4f}"),
                ("mass_em",            "Solar masses",            "{:.4f}"),
                ("age_my",             "Age (million years)",     "{:,.0f}"),
                ("ring_outer_max_km",  "Ring outer radius (km)",  "{:,.0f}"),
            ]:
                if col not in sbg.columns:
                    continue
                valid = sbg[[col, "name", "system_address"]].dropna(subset=[col])
                valid = valid[valid[col] > 0]
                if len(valid) < 2:
                    continue
                idx_min = valid[col].idxmin()
                idx_max = valid[col].idxmax()
                min_name = valid.loc[idx_min, "name"]
                min_sa   = int(valid.loc[idx_min, "system_address"])
                max_name = valid.loc[idx_max, "name"]
                max_sa   = int(valid.loc[idx_max, "system_address"])
                star_prop_rows.append(
                    f"<tr><td>{lbl}</td>"
                    f'<td class="hint-col-min"><span class="sys-link" data-sa="{min_sa}">{min_name}</span></td>'
                    f'<td class="num num-center">{fmt.format(valid.loc[idx_min, col])}</td>'
                    f'<td class="num num-center">{fmt.format(valid[col].mean())}</td>'
                    f'<td class="num num-center">{fmt.format(valid.loc[idx_max, col])}</td>'
                    f'<td class="hint-col"><span class="sys-link" data-sa="{max_sa}">{max_name}</span></td></tr>'
                )
            sys_counts = sbg.groupby("system_name").size()
            top_sys = sys_counts.idxmax()
            top_sa = int(sbg.loc[sbg["system_name"] == top_sys, "system_address"].iloc[0])
            star_prop_rows.append(
                f"<tr><td>Most in system</td>"
                f'<td class="hint-col-min"></td><td class="num num-center"></td><td class="num num-center"></td>'
                f'<td class="num">{int(sys_counts.max())}</td>'
                f'<td class="hint-col"><span class="sys-link" data-sa="{top_sa}">{top_sys}</span></td></tr>'
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
        sc_panel_ids[star_class] = panel_id

    # Build group structure — known groups in defined order, then any unrecognised classes
    classes_in_db = set(star_df["star_class"].unique())
    assigned: set[str] = set()
    star_groups: list[tuple[str, str, list[tuple[str, str]]]] = []
    g_idx = sc_idx

    for group_name, members in _STAR_CLASS_GROUPS:
        present = [c for c in members if c in classes_in_db]
        if not present:
            continue
        group_panel_id = f"sc-{g_idx}"
        g_idx += 1
        group_df = star_df[star_df["star_class"].isin(present)]
        panels[group_panel_id] = _star_group_panel_html(group_name, group_df)
        class_items = [
            (f"{c} ({len(star_df[star_df['star_class'] == c]):,})", sc_panel_ids[c])
            for c in members if c in classes_in_db
        ]
        star_groups.append((group_name, group_panel_id, class_items))
        assigned.update(present)

    leftover = classes_in_db - assigned
    if leftover:
        group_panel_id = f"sc-{g_idx}"
        group_df = star_df[star_df["star_class"].isin(leftover)]
        panels[group_panel_id] = _star_group_panel_html("Other", group_df)
        class_items = [
            (f"{c} ({len(star_df[star_df['star_class'] == c]):,})", sc_panel_ids[c])
            for c in sorted(leftover)
        ]
        star_groups.append(("Other", group_panel_id, class_items))

    overview_panel_id = "sc-overview"
    panels[overview_panel_id] = _star_overview(star_df)

    # Build list block
    btns = [
        f'<button class="detail-btn detail-overview-btn active" '
        f'data-panel="{overview_panel_id}">Overview</button>',
        '<input type="search" placeholder="Search…">',
    ]
    for group_name, group_panel_id, class_items in star_groups:
        sc_btns = "".join(
            f'<button class="detail-btn species-btn" data-panel="{sc_pid}" '
            f'data-label="{sc_label}">{sc_label}</button>'
            for sc_label, sc_pid in class_items
        )
        btns.append(
            f'<div class="genus-group">'
            f'<button class="detail-btn genus-header" data-panel="{group_panel_id}" '
            f'data-label="{group_name}">{group_name}</button>'
            f'<div class="genus-items">{sc_btns}</div>'
            f'</div>'
        )

    list_block = f'<div class="detail-list">{"".join(btns)}</div>'

    # Build content block
    panel_html = [
        f'<div class="detail-panel active" id="{overview_panel_id}">'
        f'{panels[overview_panel_id]}</div>'
    ]
    for group_name, group_panel_id, class_items in star_groups:
        panel_html.append(
            f'<div class="detail-panel" id="{group_panel_id}">'
            f'{panels[group_panel_id]}</div>'
        )
        for sc_label, sc_pid in class_items:
            panel_html.append(
                f'<div class="detail-panel" id="{sc_pid}">'
                f'{panels[sc_pid]}</div>'
            )

    content_block = f'<div class="detail-content">{"".join(panel_html)}</div>'
    return f'<div class="detail-layout">{list_block}{content_block}</div>'


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
    sections.append(_section("galaxy-map", "2D Galaxy Maps",
        _tab_group("galaxy-map", [
            ("First Discoveries", _img(mp.plot_galaxy_map_static(df_sys, None, colour_by="first_discovery", current_pos=cur_pos))),
            ("Side View",         _img(mp.plot_galaxy_side_view_static(df_sys, None, current_pos=cur_pos))),
            ("Interactive",       _plotly(mp.plot_galaxy_map_interactive(df_sys, None, colour_by="bodies_scanned", current_pos=cur_pos))),
            ("Bio Heatmap",       _plotly(mp.plot_bio_heatmap_interactive(df_sys, None, current_pos=cur_pos))),
        ])
    ))

    # ------------------------------------------------------------------
    # 3D Galaxy Maps — tab 0: sector heat map; tab 1: high-value exobiology
    # ------------------------------------------------------------------
    print("  Sector map 3D...")
    df_sec = st.sector_map_data(conn)
    df_svd = st.sector_valuable_data(conn)
    _combined = mp.plot_sector_combined_3d(df_sec, df_svd, None, current_pos=cur_pos)
    if _combined is not None:
        _fig_combined, _n_layers, _layer_titles = _combined
        _sector_html = _plotly_exclusive_legend(
            _fig_combined, "edda-sector-3d", _n_layers, _layer_titles
        )
    else:
        _sector_html = '<p class="empty-note">No data available.</p>'

    print("  Exobiology 3D map...")
    _high_value_species = sorted(
        [(sp, v) for sp, v in SPECIES_VALUES.items() if v > 8_000_000],
        key=lambda x: x[1], reverse=True,
    )
    _exobio_3d_data = [
        (sp, st.species_system_locations(conn, sp))
        for sp, _ in _high_value_species
    ]
    _fig_exobio_3d = mp.plot_exobio_combined_3d(_exobio_3d_data, None, current_pos=cur_pos)

    _3d_tabs = [("Sector Heat Map", _sector_html)]
    if _fig_exobio_3d is not None:
        _3d_tabs.append(("Exobiology", _plotly(_fig_exobio_3d)))
    sections.append(_section("sector-map", "3D Galaxy Maps",
        _tab_group("sector-map", _3d_tabs) + _3D_NAV_HINT
    ))

    # ------------------------------------------------------------------
    # Bodies — charts + catalogue
    # ------------------------------------------------------------------
    print("  Bodies...")
    df_rz          = st.body_rate_vs_z(conn)
    df_rsc         = st.body_rate_vs_star_class(conn)
    df_bodies      = st.body_type_counts(conn)
    df_stars       = st.star_class_counts(conn)
    df_bval        = st.body_values_table(conn)
    df_boxel_val   = st.boxel_he_vs_value(conn)
    _fig_boxel_val = ch.plot_boxel_he_vs_value(df_boxel_val, None)

    # Top-sectors table (≥5 systems, sorted by terra_rate)
    top_sec = df_svd[df_svd["system_count"] >= 5].head(30)
    dist_th = "<th>Distance</th>" if cur_pos else ""

    # Per-column max for relative heat colouring (rgb matches the 3D map colorscales)
    _rate_rgb = {
        "terra_rate": (220,  90,  20),
        "elw_rate":   (210,  40,  40),
        "ww_rate":    ( 40, 100, 210),
        "bio_rate":   ( 60, 180,  60),
    }
    _rate_max = {col: top_sec[col].max() for col in _rate_rgb}

    def _rate_td(v: float, col: str) -> str:
        col_max = _rate_max[col]
        style = ""
        if col_max > 0:
            ri, gi, bi = _rate_rgb[col]
            alpha = 0.65 * (v / col_max)
            style = f' style="background-color:rgba({ri},{gi},{bi},{alpha:.2f})"'
        return f'<td class="num" data-sort="{v:.4f}"{style}>{v:.3f}</td>'

    top_sec_rows = []
    for _, r in top_sec.iterrows():
        d = _dist_ly(cur_pos, r["grid_cx"], r["grid_cy"], r["grid_cz"])
        top_sec_rows.append(
            f"<tr>"
            f"<td>{r['sector']}</td>"
            f'<td class="num" data-sort="{int(r["system_count"])}">{int(r["system_count"])}</td>'
            + _rate_td(r["terra_rate"], "terra_rate")
            + f'<td class="num" data-sort="{int(r["terra_count"])}">{int(r["terra_count"])}</td>'
            + _rate_td(r["elw_rate"], "elw_rate")
            + f'<td class="num" data-sort="{int(r["elw_count"])}">{int(r["elw_count"])}</td>'
            + _rate_td(r["ww_rate"], "ww_rate")
            + f'<td class="num" data-sort="{int(r["ww_count"])}">{int(r["ww_count"])}</td>'
            + _rate_td(r["bio_rate"], "bio_rate")
            + (_dist_td(d) if cur_pos else "")
            + "</tr>"
        )
    top_sec_html = (
        '<p class="sub-head">Top Sectors by Terraformable Rate '
        '(≥ 5 systems visited, rates are per visited system)</p>'
        '<div class="table-wrap">'
        '<table class="detail-table sortable"><thead>'
        f"<tr><th>Sector</th><th>Systems</th>"
        "<th>Terra rate</th><th>Terra #</th>"
        "<th>ELW rate</th><th>ELW #</th>"
        "<th>WW rate</th><th>WW #</th>"
        f"<th>Bio rate</th>{dist_th}</tr></thead>"
        f'<tbody>{"".join(top_sec_rows)}</tbody></table></div>'
    )

    bodies_tabs = [
        ("Planet Types",       _plotly(ch.plot_body_types_interactive(df_bodies, None))),
        ("Star Classes",       _img(ch.plot_star_classes_static(df_stars, None))),
        ("Value by Type",      _plotly(ch.plot_body_values_by_type_interactive(df_bval, None))),
        ("Value Detail",       _img(ch.plot_body_values_by_type_static(df_bval, None))),
        ("Value Distribution", _img(ch.plot_body_value_histogram_static(df_bval, None))),
        ("Rate vs Galactic Y", _plotly(ch.plot_body_rate_vs_z_interactive(df_rz, None))),
        ("Rate vs Star Class", _plotly(ch.plot_body_rate_vs_star_class_interactive(df_rsc, None))),
        ("Top Sectors Table",  top_sec_html),
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

    _fig_tec_he = ch.plot_tectonicas_he_distribution(df_he_tec, None)
    exobio_tabs = [
        ("Top Organisms",       _img(ch.plot_top_species_static(df_species, None))),
        ("Income by Species",   _plotly(ch.plot_organic_value_by_species_interactive(df_oval, None))),
        ("Genus × Planet Type", _plotly(ch.plot_species_planet_heatmap_interactive(df_sxp, None))),
        ("By Planet (static)",  _img(ch.plot_organic_value_by_planet_type_static(df_oval, None))),
    ]
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
    # Spectral distribution charts (species + body-type catalogues)
    # ------------------------------------------------------------------
    print("  Spectral distribution charts...")
    df_sp_spec  = st.species_spectral_distribution(conn)
    df_bt_spec  = st.body_type_spectral_distribution(conn)
    sc_totals   = st.planet_counts_by_spectral_class(conn)

    sp_charts: dict[str, str] = {}
    for sp, grp in df_sp_spec.groupby("species"):
        b64 = ch.plot_spectral_distribution(
            grp.set_index("spectral_class")["count"],
            title=str(sp), totals=sc_totals)
        if b64:
            sp_charts[sp] = b64

    genus_charts: dict[str, str] = {}
    if not df_sp_spec.empty and not df_oval.empty:
        for genus_label, genus_oval in df_oval.groupby("genus"):
            genus_label = genus_label or "Unknown"
            sp_in_genus = genus_oval["species"].dropna().unique()
            grp = (df_sp_spec[df_sp_spec["species"].isin(sp_in_genus)]
                   .groupby("spectral_class")["count"].sum())
            b64 = ch.plot_spectral_distribution(
                grp, title=str(genus_label), totals=sc_totals)
            if b64:
                genus_charts[genus_label] = b64

    bt_charts: dict[str, str] = {}
    for bt, grp in df_bt_spec.groupby("planet_class"):
        b64 = ch.plot_spectral_distribution(
            grp.set_index("spectral_class")["count"],
            title=str(bt), totals=sc_totals)
        if b64:
            bt_charts[bt] = b64

    # ------------------------------------------------------------------
    # System diagram data (embedded JSON for canvas renderer)
    # ------------------------------------------------------------------
    print("  System diagram data...")
    diagram_data = st.system_diagram_data(conn)

    # ------------------------------------------------------------------
    # Species Catalogue
    # ------------------------------------------------------------------
    print("  Species catalogue...")
    sections.append(_section("species-cat", "Species Catalogue",
        _build_species_section(df_oval, sp_charts, genus_charts)
    ))

    # ------------------------------------------------------------------
    # Body-type Catalogue
    # ------------------------------------------------------------------
    print("  Body-type catalogue...")
    sections.append(_section("body-cat", "Body-type Catalogue",
        _build_body_section(df_bval, cur_pos, bt_charts)
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
    # Notable Stellar Phenomena
    # ------------------------------------------------------------------
    print("  Notable Stellar Phenomena...")
    df_nsp_det    = st.nsp_detections(conn, cur_pos)
    df_nsp_codex  = st.nsp_codex_entries(conn)
    sections.append(_section("nsp", "Notable Stellar Phenomena",
        _build_nsp_section(df_nsp_det, df_nsp_codex, cur_pos)
    ))

    # ------------------------------------------------------------------
    # Assemble
    # ------------------------------------------------------------------
    print("  Assembling HTML...")

    nav_items = [
        ("overview",          "Overview"),
        ("records",           "Personal Records"),
        ("galaxy-map",        "2D Galaxy Maps"),
        ("sector-map",        "3D Galaxy Maps"),
        ("bodies",            "Bodies"),
        ("exobiology",  "Exobiology"),
        ("income",      "Income & Travel"),
        ("species-cat", "Species Catalogue"),
        ("body-cat",    "Body-type Catalogue"),
        ("star-cat",    "Star-class Catalogue"),
        ("nsp",         "Notable Stellar Phenomena"),
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

    sys_data_js = "var SYSTEM_DATA = " + json.dumps(diagram_data, separators=(",", ":")) + ";"
    html = html.replace("__SYS_DATA_PLACEHOLDER__", sys_data_js)

    out_path.write_text(html, encoding="utf-8")
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"\nDashboard saved: {out_path}  ({size_mb:.1f} MB)")
