# EDDA — Elite Dangerous Data Analyser

A personal exploration analytics tool for Elite Dangerous. Parses your journal files into a local SQLite database and produces statistics, charts, galaxy maps, and a self-contained HTML dashboard.

## Features

- **Journal importer** — incrementally processes Elite Dangerous journal files; resumes partially-imported files (e.g. when the game was open during import) without duplicating data; idempotent re-runs skip already-imported files
- **Exploration statistics** — system counts, jump distance, first discoveries, mapping stats
- **Trip report** — scoped statistics for a date range, useful for comparing expedition results against tools like Elite Observatory
- **Galaxy maps** — interactive 3D Plotly maps oriented with Sol in front and Colonia to the left, scaled to true in-game galaxy dimensions; static PNG variants for density, bio signals, and first discoveries
- **Sector heat maps** — 1200 ly cube grid coloured by system density, with an interactive 3D version
- **Valuable regions** — rate-normalised sector maps showing ELW, Water World, terraformable, and bio-signal density per visited system; galactic-height (Y) correlation charts; star-class correlation charts
- **Exobiology charts** — species distribution, value breakdown by planet type, 3D species bubble maps, and a He% vs Stratum Tectonicas probability chart (mirrors the community "Boxel Helium vs Tectonicas" chart)
- **Boxel analytics** — He% vs average system exploration value chart; identifies He% ranges associated with high-value boxels (>3.5 MCr average)
- **Body value catalogue** — per-body estimated exploration credit value using the Odyssey credit formula, with correct terraforming bonus handling for Earthlike bodies and Water Worlds; property ranges (min/avg/max with body names) and most-of-type-in-system records per planet type
- **Star-class catalogue** — per-star-class system and body statistics; property ranges (surface temperature, solar radius, solar mass, age) with min/avg/max and body names; most-of-class-in-system records
- **Personal Records** — top-10 lists for most bodies, most stars, most bio signals, top exobiology value, and top exploration value per system; all tables show distance to current commander position
- **Vicinity Hints** — automatically surfaces interesting boxels within 5,000 ly of the commander's current position:
  - *Potential helium-rich boxel* — mean He% above 28.5% with ≥3 gas giants
  - *Potential Stratum Tectonicas boxel* — He% in community-identified sweet spots (24.2–24.5% or 25.9–26.5%)
  - *Potential high exploration value boxel* — He% in ranges correlated with >3.5 MCr average system value (24.7–25.4%, 26.2–26.4%, 30.05–30.15%)
- **Income charts** — exploration and exobiology credits earned over time (cumulative)
- **Dashboard** — all of the above assembled into a single self-contained HTML file with a tabbed navigation sidebar, showing the current package version

## Requirements

- Python 3.12 or newer
- Elite Dangerous installed (journal files must be accessible)

## Installation

**Windows (double-click or run in any terminal):**
```bat
setup.bat
```

**Windows (PowerShell — requires execution policy to be set):**
```powershell
.\setup.ps1
```
> If you see a script execution error, run it without changing system policy:
> `powershell.exe -ExecutionPolicy Bypass -File .\setup.ps1`

**Linux / macOS:**
```bash
chmod +x setup.sh
./setup.sh
```

This creates a `.venv` virtual environment and installs all dependencies into it.
On Windows, the `edda-*` commands live inside `.venv\Scripts\`; on Linux/macOS they are in `.venv/bin/`.

## Updating

Run this once to pull the latest code, sync dependencies, re-import journals, and rebuild everything:

**Windows (double-click or run in any terminal):**
```bat
update.bat
```

**Windows (PowerShell — requires execution policy to be set):**
```powershell
.\update.ps1
```
> If you see a script execution error, run it without changing system policy:
> `powershell.exe -ExecutionPolicy Bypass -File .\update.ps1`

**Linux / macOS:**
```bash
./update.sh
```

If `git` is not installed (e.g. you downloaded a ZIP from the repository), the pull step is skipped automatically — update the files manually and the rest of the script still runs.

Then open `dashboard.html` in a browser.

## Quick start

**Windows:**
```powershell
# Activate the environment (once per terminal session):
.\.venv\Scripts\Activate.ps1

edda-import       # import journal files
edda-stats        # print summary to terminal
edda-dashboard    # build dashboard.html
```

Or without activating: `.\.venv\Scripts\edda-import` etc.

**Linux / macOS:**
```bash
source .venv/bin/activate

edda-import
edda-stats
edda-dashboard
```

Or without activating: `.venv/bin/edda-import` etc.

Open `dashboard.html` in any browser — no server required.

## Browser compatibility

The dashboard is a fully self-contained HTML file (no server, no external requests). It works in all modern browsers on all platforms:

| Browser | Notes |
|---|---|
| Chrome / Chromium | Full support, recommended |
| Firefox | Full support |
| Edge | Full support |
| Safari | Full support |

The interactive 3D galaxy maps use WebGL via Plotly.js. This is supported by all modern browsers. On Linux without a dedicated GPU, software rendering (Mesa/llvmpipe) works but may be slower on older hardware.

The dashboard file is several MB in size due to embedded Plotly.js and base64-encoded chart images. It loads from the local filesystem (`file://`) without any issues.

## Commands

### `edda-import`

Parses journal files and writes data into `.edda/ed.db`.

```
edda-import [--journal-dir DIR] [--db PATH] [--force] [--quiet]
```

| Flag | Description |
|---|---|
| `--journal-dir DIR` | Override the journal directory (default: standard ED path for the OS) |
| `--db PATH` | Use a different database file |
| `--force` | Re-process files that were already imported |
| `--quiet` | Suppress per-file progress output |

Handled journal events: `FSDJump`, `Location`, `Scan`, `FSSBodySignals`, `SAASignalsFound`, `SAAScanComplete`, `ScanOrganic`, `SellOrganicData`, `CodexEntry`, `MultiSellExplorationData`, `Rank`, `LoadGame`.

### `edda-stats`

Prints a lifetime summary to the terminal, including personal records (highest gravity, hottest surface, longest jump, etc.).

```
edda-stats [--db PATH]
```

### `edda-trip`

Prints statistics scoped to a date range — useful for expedition reports.

```
edda-trip --from YYYY-MM-DD --to YYYY-MM-DD [--systems] [--db PATH]
```

Outputs:
- Jump and system counts, light-years travelled
- Exobiology samples with base / first-log / Antal-bonus value estimates
- Planet-type breakdown with first-discovery and first-mapped counts
- Estimated exploration credit value for the period
- Personal bests within the range
- `--systems`: full chronological list of every system visited

### `edda-map`

Renders galaxy maps and sector heat maps.

```
edda-map [--out DIR] [--static-only] [--interactive-only] [--db PATH]
```

Outputs (in `output/` by default):

| File | Description |
|---|---|
| `galaxy_density.png` | Top-down dot map coloured by visit density |
| `galaxy_bio.png` | Top-down map coloured by bio-signal count |
| `galaxy_first_discoveries.png` | Top-down map coloured by first discovery flag |
| `galaxy_side.png` | Side-view (X / Y) scatter |
| `galaxy_interactive.html` | Interactive 3D Plotly map |
| `galaxy_bio_interactive.html` | Interactive bio-signal 3D map |
| `sector_heatmap.png` | Sector grid heat map (PNG) |
| `sector_heatmap.html` | Interactive 3D sector cube map |

All 3D maps use fixed in-game galaxy axis ranges (X: ±50,000 ly, Y: −16,000 / +9,000 ly, Z: −24,000 / +76,000 ly) so sparse data does not distort the proportions.

### `edda-charts`

Renders all analytics charts.

```
edda-charts [--out DIR] [--static-only] [--interactive-only] [--db PATH]
```

Outputs include body type counts, star class counts, exploration and exobiology income over time, jump distance histogram, top species, species × planet type heat map, body value breakdowns, the valuable-regions charts (`body_rate_vs_z`, `body_rate_vs_star_class`, `sector_terra_rate`, `sector_elw_rate`), and the He% correlation charts.

### `edda-dashboard`

Builds a single self-contained HTML file with all analytics.

```
edda-dashboard [--out FILE] [--db PATH]
```

The dashboard sections:

| Section | Contents |
|---|---|
| Overview | Key lifetime counts and Vicinity Hints (helium-rich, Tectonicas, and high-value boxels within 5,000 ly) |
| Personal Records | Top-10 tables for most bodies, most stars, most bio signals, top exobiology value, top exploration value; Miscellaneous personal bests |
| Galaxy Maps | Interactive 3D views (all systems, bio signals, first discoveries) and static PNG maps |
| Sector Map | Interactive 3D sector cube density map |
| Valuable Regions | Rate-normalised sector maps; body rates vs galactic height and star class; top sectors table |
| Bodies | Planet-type and star-class charts; body value breakdown; He% vs average system value line chart |
| Exobiology | Species scan log, value breakdown by species and planet type, interactive genus × planet-type heatmap with row/column totals, 3D species bubble maps, He% vs Stratum Tectonicas probability chart |
| Income & Travel | Cumulative exploration and exobiology credits; jump distance histogram |
| Species Catalogue | Per-species scan counts, first-log tracking, estimated and actual sale values, with planet-type breakdown |
| Body-type Catalogue | Per-type totals with first-discovery and mapping stats; property ranges (gravity, temperature, radius, Earth masses, surface pressure) with min/avg/max and body names; most bodies of that type in one system; sortable detail table with distance to commander |
| Star-class Catalogue | Per-star-class system and body statistics; property ranges (surface temperature, solar radius, solar mass, age) with min/avg/max and star names; most stars of that class in one system; sortable detail table with distance to commander |

## Vicinity Hints

The Overview section surfaces up to 10 hints per category, distance-sorted, within 5,000 ly of the commander's last known position. Hints require He% data in the database — populated from `AtmosphereComposition` in `Scan` journal events. Three hint types are shown:

| Colour | Type | Condition |
|---|---|---|
| Orange | Helium-rich boxel | Mean boxel He% > 28.5%, ≥3 gas giants scanned |
| Green | Stratum Tectonicas boxel | He% in 24.2–24.5% or 25.9–26.5% (community chart: probability > 5%) |
| Blue | High exploration value boxel | He% in 24.7–25.4%, 26.2–26.4%, or 30.05–30.15% (avg system value > 3.5 MCr) |

When actual He% data is not yet available (e.g. before a full reimport), Helium Rich Gas Giants are used as a proxy (He% assumed 35%).

A *boxel* is the system-name prefix after stripping the trailing index number — e.g. `Prooe Drye ZQ-K d9` for systems named `Prooe Drye ZQ-K d9-N`. All systems in a boxel share the same stellar forge properties.

## Database

The SQLite database lives at `.edda/ed.db` (created automatically on first import). Key tables:

| Table | Contents |
|---|---|
| `systems` | Every visited star system with galactic coordinates and primary star class |
| `jumps` | Every FSD jump in chronological order with distance and fuel data |
| `bodies` | All scanned bodies with physical properties (including `age_my` and `mass_em` in solar units for stars), first-discovery/mapping flags, and helium percentage (`atmosphere_he_pct`) for gas giants |
| `bio_signals` | Biological signal genus entries per body from DSS probing |
| `organic_scans` | Individual organism scan events (Log / Sample / Analyse states) |
| `organic_sales` | Vista Genomics sale records with first-log bonus tracking |
| `exploration_sales` | Cartography data sale records |
| `codex_entries` | Codex discoveries, flagged if first in region |
| `commander_snapshots` | Credit and rank snapshots per session start |

## Credit value formula

Exploration scan values are estimated using the community-verified Odyssey formula:

```
k_total = k_base + k_terra  (if terraformable)
scan_value = k_total × (1 + 0.566 × mass_em^0.199977)
           × first_discovered_mult  (if first discovered)
           × mapping_mult           (3.3 if first-mapped, 1.5 if mapped)
```

Earthlike bodies always receive the terraforming bonus regardless of the `terraform_state` field, matching the game's intrinsic valuation. Water Worlds use `terraform_state` normally — non-terraformable Water Worlds are worth less.

Exobiology values use the Vista Genomics price table with optional first-log (×5) and Pranav Antal pledge bonuses.

## Project layout

```
src/edda/
├── cli.py                  entry points for all edda-* commands
├── db/
│   ├── schema.py           SQLite schema definition
│   └── connection.py       open_db(), upsert helpers
├── importer/
│   ├── journal_reader.py   journal file discovery and dispatch
│   └── event_handlers.py   per-event-type parsing logic (incl. He% extraction)
└── analysis/
    ├── valuation.py        credit value formula (body + exobiology)
    ├── stats.py            SQL queries and DataFrame transformations
    ├── charts.py           matplotlib and Plotly chart functions
    ├── maps.py             galaxy and sector map functions
    └── dashboard.py        HTML dashboard assembler
```
