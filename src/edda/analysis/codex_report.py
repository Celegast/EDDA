"""
Odyssey Codex (exobiology) gap-analysis report.

Reads the community game-codex TSVs under game_codex/ (relative to the
current working directory — same convention as other report outputs) and
builds a self-contained HTML report of regional and galactic first-discovery
opportunities.

Method
------
* Canonn ("Canonn - Surface Biology - Odyssey Codex.tsv") = the definitive list of
  colour variants that EXIST galaxy-wide, one per (species, star type).
* CodexEntries.tsv tells us which of those have been logged in each region.
* A variant NOT logged in region R  ->  a regional first available in R.
* "Missing Colours.tsv" marks cells "Has Gap" / "Gap 1 of N?" where a variant is
  believed to exist but has NEVER been logged anywhere  ->  a galactic first.

The report DB (the commander(s) selected when the report is run) supplies the
star-population sample used to judge whether a region realistically carries a
given star type, plus which (species, star type) variants the commander has
personally logged, shown as a distinct highlight.
"""
from __future__ import annotations

import base64
import collections
import csv
import html
import io
import json
import math
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Source TSVs live under game_codex/ at the project root — data, not package
# code — the same way other reports' default output paths are relative to cwd.
GAME_CODEX_DIR = Path.cwd() / "game_codex"
CANONN = GAME_CODEX_DIR / "Canonn - Surface Biology - Odyssey Codex.tsv"
CE_TSV = GAME_CODEX_DIR / "Elite Dangerous in Game Codex - CodexEntries.tsv"
MC_TSV = GAME_CODEX_DIR / "Elite Dangerous in Game Codex - Missing Colours.tsv"
ME_TSV = GAME_CODEX_DIR / "Elite Dangerous, Undiscovered Odyssey Biology Count - Missing Entries.tsv"

REQUIRED_SOURCES = (CANONN, CE_TSV, MC_TSV)

# (local file, Google Sheet ID, tab name) for `refresh_sources()`
SOURCES = [
    (CANONN, "15lqZtqJk7B2qUV5Jb4tlnst6i1B7pXlAUzQnacX64Kc", "Odyssey Codex"),
    (CE_TSV, "1uOYgECrwpIeYsapUxfOuULCeLAwIv_3ZqtNIvNDHsFA", "CodexEntries"),
    (MC_TSV, "1uOYgECrwpIeYsapUxfOuULCeLAwIv_3ZqtNIvNDHsFA", "Missing Colours"),
    (ME_TSV, "1TpPZUFd61KUQWy1sV8VhScZiVbRWJ435wTN8xjN0Qv0", "Missing Entries"),
]

CODEX_REGION = {
    1: "Galactic Centre", 2: "Empyrean Straits", 3: "Ryker's Hope", 4: "Odin's Hold",
    5: "Norma Arm", 6: "Arcadian Stream", 7: "Izanami", 8: "Inner Orion-Perseus Conflux",
    9: "Inner Scutum-Centaurus Arm", 10: "Norma Expanse", 11: "Trojan Belt", 12: "The Veils",
    13: "Newton's Vault", 14: "The Conduit", 15: "Outer Orion-Perseus Conflux",
    16: "Orion-Cygnus Arm", 17: "Temple", 18: "Inner Orion Spur", 19: "Hawking's Gap",
    20: "Dryman's Point", 21: "Sagittarius-Carina Arm", 22: "Mare Somnia", 23: "Acheron",
    24: "Formorian Frontier", 25: "Hieronymus Delta", 26: "Outer Scutum-Centaurus Arm",
    27: "Outer Arm", 28: "Aquila's Halo", 29: "Errant Marches", 30: "Perseus Arm",
    31: "Formidine Rift", 32: "Vulcan Gate", 33: "Elysian Shore", 34: "Sanguineous Rim",
    35: "Outer Orion Spur", 36: "Achilles's Altar", 37: "Xibalba", 38: "Lyra's Song",
    39: "Tenebrae", 40: "The Abyss", 41: "Kepler's Crest", 42: "The Void",
}

# star-type columns for the matrix (Missing Colours grid order)
STARS = ["O", "B", "A", "F", "G", "K", "M", "L", "T", "TTS", "AeBe", "Y", "W", "D", "N"]
STAR_LABEL = {"O": "O", "B": "B", "A": "A", "F": "F", "G": "G", "K": "K", "M": "M",
              "L": "L", "T": "T", "TTS": "TTS", "AeBe": "AeBe", "Y": "Y", "W": "WR",
              "D": "WD", "N": "NS"}
STAR_FULL = {"O": "O", "B": "B", "A": "A", "F": "F", "G": "G", "K": "K", "M": "M",
             "L": "L Dwarf", "T": "T Dwarf", "TTS": "T Tauri", "AeBe": "Herbig Ae/Be",
             "Y": "Y Brown Dwarf", "W": "Wolf-Rayet", "D": "White Dwarf", "N": "Neutron Star"}
EXOTIC = {"O", "W", "AeBe"}   # bio around these is near-nonexistent galaxy-wide
EASY = {"F", "G", "K", "M", "A", "Y"}

# material-related species key off a surface trace element instead of a star.
# Every material-related species in Canonn uses exactly one of these two
# 6-element sets — one combined column list covers both (each species leaves
# the other 6 columns blank, same convention as STARS does for missing variants).
MATERIALS = ["Mercury", "Niobium", "Tin", "Tungsten", "Molybdenum", "Cadmium",
             "Technetium", "Tellurium", "Polonium", "Ruthenium", "Antimony", "Yttrium"]
# genera that only appear material-related (not in the star-grid GEN_ORDER list)
MAT_GEN_ORDER = ["Bacterium", "Concha", "Electricae", "Fumerola", "Fungoida", "Osseus", "Recepta"]
STAR_TIP = {
    "Y": "brown dwarfs are everywhere",
    "L": "L dwarfs common in the disc", "T": "T dwarfs common",
    "TTS": "T Tauri: star-forming regions (arms, nebulae)",
    "B": "B stars: spiral-arm regions", "N": "neutron: core-adjacent regions",
    "D": "white dwarf: hard, densest near the core",
    "AeBe": "Herbig: ~29 candidate planets in the whole galaxy — near-impossible",
    "W": "Wolf-Rayet: ~5 candidate planets in the whole galaxy — near-impossible",
    "O": "O type: ~11 candidate planets in the whole galaxy — near-impossible",
}

# codex colour -> hex (for the little chips)
COLOUR_HEX = {
    "Green": "#3fae52", "Teal": "#2bb6a8", "Emerald": "#1f8a4c", "Lime": "#8dcf3f",
    "Yellow": "#e8c53a", "Turquoise": "#40c8c0", "Mauve": "#b57bd0", "Amethyst": "#9b6cd6",
    "Grey": "#9aa3b0", "Sage": "#a7c08a", "Indigo": "#5566cc", "Ocher": "#c08a3a",
    "Red": "#d0524a", "Maroon": "#9a3b3b", "Orange": "#e08a3a", "Gold": "#d8b23a",
    "White": "#dfe3ea", "Peach": "#e8b89a", "Blue": "#3a6fd0", "Cyan": "#3ac0d0",
    "Cobalt": "#3550c0", "Aquamarine": "#4fd0b0", "Magenta": "#d04fb0", "Mulberry": "#a04070",
}
NULL_CELLS = {"NoGap", "NoSpaceinEntryID", "NoBasedOnType", "Missing", ""}


# ── refresh from Google Sheets ──────────────────────────────────────────────
def _fetch_sheet_csv(sheet_id, sheet_name, timeout=20):
    url = ("https://docs.google.com/spreadsheets/d/" + sheet_id + "/gviz/tq?"
           + urllib.parse.urlencode({"tqx": "out:csv", "sheet": sheet_name}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def refresh_sources() -> bool:
    """Re-download each tracked Google Sheet tab, trimming the trailing blank
    columns gviz pads exports with, and overwrite the local TSV in place."""
    GAME_CODEX_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for path, sheet_id, sheet_name in SOURCES:
        try:
            csv_text = _fetch_sheet_csv(sheet_id, sheet_name)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  ! {path.name}: fetch failed ({e}) — keeping existing copy")
            ok = False
            continue
        rows = list(csv.reader(io.StringIO(csv_text)))
        for row in rows:
            while row and row[-1] == "":
                row.pop()
        # re-pad to a uniform width (gviz exports pad much further than the sheet's
        # real content) so the diff against the previous copy stays minimal
        width = max((len(r) for r in rows), default=0)
        for row in rows:
            row.extend([""] * (width - len(row)))
        # plain tab-join, not csv.writer: quotes in the data (player names like
        # `JESSICA "..." I`) are literal here and shouldn't get CSV-escaped
        text = "\n".join("\t".join(row) for row in rows) + "\n"
        path.write_text(text, encoding="utf-8")
        print(f"  {path.name}: {len(rows)} rows")
    return ok


def missing_sources() -> list[str]:
    """Names of required source TSVs not present on disk."""
    return [f.name for f in REQUIRED_SOURCES if not f.exists()]


# ── loaders ─────────────────────────────────────────────────────────────────
def load_canonn():
    """species -> {star: colour}  and  species -> {material: colour}."""
    star_map: dict[str, dict[str, str]] = {}
    mat_map: dict[str, dict[str, str]] = {}
    for row in csv.reader(CANONN.open(encoding="utf-8"), delimiter="\t"):
        if not row or row[0].strip() in ("", "Species"):
            continue
        sp = row[0].strip()
        for cell in row[4:]:
            cell = cell.strip()
            if " - " not in cell:
                continue
            col, key = (x.strip() for x in cell.rsplit(" - ", 1))
            key = "AeBe" if key == "Ae" else key
            (star_map if key in STARS else mat_map).setdefault(sp, {})[key] = col
    return star_map, mat_map


def _in_odyssey_window(date: str) -> bool:
    """True if `date` (DateDiscovered, YYYY-MM-DD) falls in the Odyssey era, OR
    the date is missing/unparseable — a handful of genuine entries have no
    DateDiscovered recorded, and a missing date shouldn't disqualify an
    otherwise-valid exobiology entry from being counted."""
    return len(date) < 7 or date[:7] >= ODYSSEY_LAUNCH_MONTH


def load_found(commander_names: set[str] = frozenset()):
    """(species,colour) -> regions where Found=1; region list; genus per species;
    sp_regions[species] -> regions where the species has ANY confirmed variant;
    sp_here[region] -> species confirmed present there;
    my_firsts[region][species] -> colours YOU (commander_names) discovered there,
    per the CodexEntries 'DiscoveredBy' column — an actual regional first you logged;
    my_first_list -> the same, as a flat list of (region, species, colour, system, date)
    for a summary table, most recent first;
    discoverer_counts -> every commander's regional-first tally, Odyssey-era
    exobiology entries only — the same rows my_firsts draws from, for anyone,
    not just commander_names, so the Statistics leaderboard can never drift
    out of sync with 'Your regional firsts' above it."""
    found: dict[tuple, set] = collections.defaultdict(set)
    regions: set[str] = set()
    genus: dict[str, str] = {}
    sp_regions: dict[str, set] = collections.defaultdict(set)
    sp_here: dict[str, set] = collections.defaultdict(set)
    my_firsts: dict[str, dict] = collections.defaultdict(lambda: collections.defaultdict(set))
    my_first_list: list[tuple] = []
    discoverer_counts: collections.Counter = collections.Counter()
    for r in csv.DictReader(CE_TSV.open(encoding="utf-8"), delimiter="\t"):
        if r["Category"] != "Bio":
            continue
        sp, _, col = r["EnglishName"].rpartition(" - ")
        if not col:
            continue
        sp, col, reg = sp.strip(), col.strip(), r["RegionName"]
        regions.add(reg)
        genus[sp] = r["GroupName"]
        if r["Found"] == "1":
            found[(sp, col)].add(reg)
            sp_regions[sp].add(reg)
            sp_here[reg].add(sp)
            discoverer = (r.get("DiscoveredBy") or "").strip()
            date = (r.get("DateDiscovered") or "").strip()
            if discoverer and _in_odyssey_window(date):
                discoverer_counts[discoverer] += 1
                if discoverer.upper() in commander_names:
                    my_firsts[reg][sp].add(col)
                    my_first_list.append((reg, sp, col, r.get("System", ""), date))
    my_first_list.sort(key=lambda x: x[4], reverse=True)
    return found, sorted(regions), genus, sp_regions, sp_here, my_firsts, my_first_list, discoverer_counts


def load_gaps():
    """species -> {star: 'gap'|'gap?'}  from the Has-Gap / Gap-1-of-N markers.
    These are believed-valid variants that have never been logged anywhere."""
    out: dict[str, dict[str, str]] = collections.defaultdict(dict)
    rows = list(csv.reader(MC_TSV.open(encoding="utf-8"), delimiter="\t"))
    for r in rows[2:]:
        if len(r) < 17 or not r[1].strip():
            continue
        sp = f"{r[0].strip()} {r[1].strip()}"
        for star, cell in zip(STARS, (c.strip() for c in r[2:17])):
            if cell == "Has Gap":
                out[sp][star] = "gap"
            elif cell.startswith("Gap 1 of"):
                out[sp][star] = "gap?"
    return out


def load_reconciliation_total():
    """Grand-total outstanding-variant count from the community reference sheet
    ('Undiscovered Odyssey Biology Count'), if the file is present."""
    if not ME_TSV.exists():
        return None
    rows = list(csv.reader(ME_TSV.open(encoding="utf-8"), delimiter="\t"))
    if not rows:
        return None
    try:
        col = rows[0].index("Grand Total")
    except ValueError:
        return None
    for row in rows[1:]:
        if row and row[0] == "Grand Total" and len(row) > col:
            try:
                return int(row[col].replace(",", ""))
            except ValueError:
                return None
    return None


ODYSSEY_LAUNCH_MONTH = "3307-05"   # in-universe YYYY-MM Odyssey went live


def load_monthly_series():
    """Regional-first Bio codex entries per month since Odyssey's launch, plus
    a 3-month trailing average. None if the source has no post-launch dates."""
    counts: collections.Counter = collections.Counter()
    for r in csv.DictReader(CE_TSV.open(encoding="utf-8"), delimiter="\t"):
        if r["Category"] != "Bio" or r["Found"] != "1":
            continue
        d = (r.get("DateDiscovered") or "").strip()
        if len(d) >= 7 and d[:7] >= ODYSSEY_LAUNCH_MONTH:
            counts[d[:7]] += 1
    if not counts:
        return None

    months = sorted(counts)
    sy, sm = (int(x) for x in months[0].split("-"))
    ey, em = (int(x) for x in months[-1].split("-"))
    series: list[list] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        key = f"{y:04d}-{m:02d}"
        series.append([key, counts.get(key, 0)])
        m += 1
        if m > 12:
            m, y = 1, y + 1

    # Centered 7-month average, not trailing: a trailing window lags behind
    # sharp moves (e.g. the launch spike), which reads as jagged rather than a
    # smooth trend. Centering removes that lag; edges shrink to what's available.
    trend = []
    for i in range(len(series)):
        lo, hi = max(0, i - 3), min(len(series), i + 4)
        window = series[lo:hi]
        trend.append(round(sum(w[1] for w in window) / len(window), 1))

    peak_month, peak_val = max(counts.items(), key=lambda kv: kv[1])
    return {
        "series": series, "trend": trend, "total": sum(counts.values()),
        "peak_month": peak_month, "peak_val": peak_val,
        "start": series[0][0], "end": series[-1][0],
    }


def build_commander_leaderboard(discoverer_counts: collections.Counter):
    """Turn load_found()'s discoverer_counts into the leaderboard shape. Reuses
    the exact same rows 'Your regional firsts' draws from — same species-validity
    and Odyssey-window rules — so the two can never disagree."""
    if not discoverer_counts:
        return None
    ranked = discoverer_counts.most_common()
    return {
        "leaderboard": [[i, name, n] for i, (name, n) in enumerate(ranked, 1)],
        "total_cmdrs": len(ranked),
        "total_firsts": sum(discoverer_counts.values()),
    }


_SUBTYPE_STAR = {}
for _c, _subs in {
    "O": {"O"}, "B": {"B", "B_BlueWhiteSuperGiant"}, "A": {"A", "A_BlueWhiteSuperGiant"},
    "F": {"F", "F_WhiteSuperGiant"}, "G": {"G", "G_WhiteSuperGiant"},
    "K": {"K", "K_OrangeGiant"}, "M": {"M", "M_RedGiant", "M_RedSuperGiant"},
    "L": {"L"}, "T": {"T"}, "TTS": {"TTS"}, "AeBe": {"AeBe"}, "Y": {"Y"},
    "W": {"W", "WC", "WN", "WO", "WNC"},
    "D": {"D", "DA", "DB", "DC", "DAB", "DAV", "DAZ", "DBV", "DBZ", "DCV", "DQ", "DO", "DOV", "DX"},
    "N": {"N"},
}.items():
    for _s in _subs:
        _SUBTYPE_STAR[_s] = _c


def commander_names(conn: sqlite3.Connection) -> set[str]:
    """Every distinct commander name recorded in the report DB (one, or several
    if multiple commanders were merged), upper-cased for matching against the
    CodexEntries 'DiscoveredBy' column."""
    rows = conn.execute("SELECT DISTINCT name FROM commander_snapshots WHERE name IS NOT NULL").fetchall()
    return {r[0].strip().upper() for r in rows if r[0] and r[0].strip()}


def _guess_material_colour(species_materials: dict, body_materials: list) -> str | None:
    """Best-effort colour for a material-related species on a body, from the
    body's full material list `[(name_lower, percent), ...]` sorted richest
    first. `species_materials` is {MaterialName: colour} for this species (6
    entries — the "Species - Colour" variant_localised string is authoritative
    when we have it; this is only the fallback for scans that predate it).

    Percentage doesn't reliably predict which of several present candidates
    is the real one (verified against known personal finds: the true colour
    has come from both the higher- and the lower-percentage candidate on
    different bodies), so a multi-candidate body is genuinely ambiguous —
    only report a colour when exactly one of the species' candidate
    materials is present at all."""
    candidates = {name.lower(): (name, colour) for name, colour in species_materials.items()}
    present = [name for name, _pct in body_materials if name in candidates]
    if len(present) != 1:
        return None
    return candidates[present[0]][1]


def db_region_data(conn: sqlite3.Connection, star_map: dict, mat_map: dict):
    """From the report DB, per region:
       stars[region][star_code]  = systems with that star type present
       cover[region]             = systems visited (confidence)
       prof[region][star_code]   = your bio scans by parent star ('tried here?')
       region_materials[region][material] = systems with a body carrying that
                                   surface trace element (material-related species)
       personal_region[region][species] = colours you've personally scanned
                                   that species as, IN THIS REGION
       personal_global[species]  = the same, but anywhere (for the whole-galaxy
                                   matrix, which isn't region-scoped).
       Colours come straight from organic_scans.variant_localised (the game's
       own "Species - Colour" string for that scan) when available — not
       inferred from the parent star's type. Elite Dangerous's colour-
       determining star isn't reliably "the nearest star in the orbital
       Parents chain" (confirmed: a body whose immediate parent was a T
       Tauri star still came back with the colour variant belonging to a
       distant, unrelated B star elsewhere in the system), so guessing via
       parent_star_id can silently pick the wrong star.
       `variant_localised` was only added to the ScanOrganic journal event
       partway through Odyssey's life, though — scans from before then have
       no colour recorded at all, so for those (and only those) we fall back
       to a best-effort guess: parent star type for star-gated species (see
       caveat above), or the scanned body's own surface material composition
       for material-related ones (see _guess_material_colour)."""
    stars: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    prof: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    personal_region: dict[str, dict] = collections.defaultdict(lambda: collections.defaultdict(set))
    personal_global: dict[str, set] = collections.defaultdict(set)
    cover: dict[str, int] = {}

    for reg, n in conn.execute("SELECT region, COUNT(*) FROM systems WHERE region>'' GROUP BY region"):
        cover[reg] = n
    for reg, st, n in conn.execute("""
        SELECT s.region, b.subtype, COUNT(DISTINCT s.system_address)
        FROM bodies b JOIN systems s ON s.system_address=b.system_address
        WHERE b.body_type='Star' AND s.region>'' GROUP BY s.region, b.subtype"""):
        c = _SUBTYPE_STAR.get(st)
        if c:
            stars[reg][c] += n
    for reg, st, n in conn.execute("""
        SELECT s.region, ps.subtype, COUNT(*)
        FROM organic_scans o
        JOIN systems s ON s.system_address=o.system_address
        JOIN bodies b  ON b.system_address=o.system_address AND b.body_id=o.body_id
        LEFT JOIN bodies ps ON ps.system_address=o.system_address AND ps.body_id=b.parent_star_id
        WHERE o.scan_state='Analyse' AND s.region>''
        GROUP BY s.region, ps.subtype"""):
        prof[reg][_SUBTYPE_STAR.get(st or "", (st or "?").split("_")[0])] += n
    # Pass 1: the common, correct case — the game's own recorded colour.
    for reg, variant, sp_local in conn.execute("""
        SELECT s.region, o.variant_localised, o.species_localised
        FROM organic_scans o
        JOIN systems s ON s.system_address=o.system_address
        WHERE o.scan_state='Analyse' AND o.species_localised>'' AND o.variant_localised>'' AND s.region>''
        GROUP BY s.region, o.variant_localised, o.species_localised"""):
        sp, _, col = variant.rpartition(" - ")
        sp, col = sp.strip(), col.strip()
        if col:
            personal_region[reg][sp].add(col)
            personal_global[sp].add(col)

    # Pass 2: fallback for scans that predate variant_localised. Star-gated
    # species fall back to the parent star's type; material-related species
    # fall back to the scanned body's own surface material composition.
    for reg, sp_local, sa, bid, st in conn.execute("""
        SELECT s.region, o.species_localised, o.system_address, o.body_id, ps.subtype
        FROM organic_scans o
        JOIN systems s ON s.system_address=o.system_address
        JOIN bodies b  ON b.system_address=o.system_address AND b.body_id=o.body_id
        LEFT JOIN bodies ps ON ps.system_address=o.system_address AND ps.body_id=b.parent_star_id
        WHERE o.scan_state='Analyse' AND o.species_localised>''
          AND (o.variant_localised IS NULL OR o.variant_localised='') AND s.region>''
        GROUP BY s.region, o.species_localised, o.system_address, o.body_id, ps.subtype"""):
        col = None
        if sp_local in star_map:
            star_code = _SUBTYPE_STAR.get(st or "")
            col = star_map.get(sp_local, {}).get(star_code) if star_code else None
        elif sp_local in mat_map:
            body_mats = conn.execute("""
                SELECT LOWER(name), percent FROM body_materials
                WHERE system_address=? AND body_id=? ORDER BY percent DESC""", (sa, bid)).fetchall()
            col = _guess_material_colour(mat_map[sp_local], body_mats)
        if col:
            personal_region[reg][sp_local].add(col)
            personal_global[sp_local].add(col)

    region_materials: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for reg, mat, n in conn.execute("""
        SELECT s.region, LOWER(bm.name), COUNT(DISTINCT s.system_address)
        FROM body_materials bm
        JOIN systems s ON s.system_address=bm.system_address
        WHERE s.region>'' AND bm.percent>0
        GROUP BY s.region, LOWER(bm.name)"""):
        region_materials[reg][mat] += n

    return stars, cover, prof, personal_region, personal_global, region_materials


# ── report ──────────────────────────────────────────────────────────────────
CSS = """
body{background:#0c0e16;color:#c8cdda;font:13px/1.5 'Segoe UI',system-ui,sans-serif;margin:0;padding:30px}
h1{color:#e6ebf5;font-size:1.4rem}
h2{color:#dbe2f0;margin-top:2.2em;border-bottom:1px solid #232838;padding-bottom:.3em}
h3{color:#cdd6ea;margin:.2em 0}
.sub{color:#8892a8;max-width:82ch}
a{color:#6fa8ff;text-decoration:none}
.chip{display:inline-block;width:9px;height:9px;border-radius:2px;vertical-align:0;border:1px solid #0007}
table.sum{border-collapse:collapse;font-size:12px;margin:.6em 0}
table.sum th,table.sum td{padding:4px 9px;border-bottom:1px solid #1c2130;text-align:left}
table.sum td.n{text-align:right;font-variant-numeric:tabular-nums}
table.mx{border-collapse:collapse;font-size:11px;margin:.5em 0 .2em}
table.mx th{color:#e6ebf5;font-weight:600;padding:2px 4px;text-align:center;border-bottom:1px solid #232838}
table.mx th.sp{text-align:left;padding-right:10px;color:#aab3c6}
table.mx td{width:20px;height:18px;text-align:center;border:1px solid #12151f}
table.mx td.sp{width:auto;text-align:left;padding:1px 10px 1px 2px;color:#b9c2d6;white-space:nowrap}
table.mx tr.gsep td{border-top:2px solid #232838}
table.mx tr.mxtot td{border-bottom:2px solid #232838;color:#6f7890;font-variant-numeric:tabular-nums;font-weight:600}
.done{background:#16241c}
.confirmed{background:#0f1620}
.mine{background:#4d5566}
.myfirst{background:#3a0a1c;outline:2px solid #ff4fa0;box-shadow:0 0 8px #ff4fa099,inset 0 0 6px #ff4fa055;font-weight:700}
.rf{background:#2b2410;outline:1px solid #6a5a24}
.rfsoft{background:#1c1e26;outline:1px solid #333a48}
.rfdead{background:#1a1720}
.gf{background:#3a2c0c;outline:1px solid #caa63c;box-shadow:inset 0 0 6px #caa63c66;color:#f0c24a;font-weight:700}
.gfx{background:#241d16;color:#7c6a42}
.na{background:#0e1017}
.region{background:#11141f;border:1px solid #1e2333;border-radius:6px;padding:12px 16px;margin:12px 0}
details>summary{cursor:pointer;color:#cdd6ea;font-size:1.02rem;padding:4px 0}
summary.h2toggle{color:#dbe2f0;font-size:1.5em;font-weight:700;margin-top:2.2em;padding-bottom:.3em;border-bottom:1px solid #232838}
.prof{font:11px/1.5 ui-monospace,monospace;color:#7c8598;margin:.3em 0}
.hint{color:#9aa3b8;margin:.4em 0;max-width:90ch}
.legend span{margin-right:16px}
.warn{background:#2a1a15;border-left:3px solid #c0603a;padding:10px 14px;border-radius:4px;max-width:88ch;margin:1em 0}

/* ---------- statistics section ---------- */
.st-wrap{position:relative;margin-top:.5em}
.st-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:#232838;border:1px solid #232838;border-radius:8px;overflow:hidden;margin:16px 0 20px}
.st-kpi{background:#11141f;padding:16px 18px}
.st-kpi-label{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#6a7488;margin-bottom:8px}
.st-kpi-value{font-family:'Orbitron',sans-serif;font-weight:700;font-size:24px;color:#e6ebf5;font-variant-numeric:tabular-nums}
.st-kpi-value.accent{color:#d97016}
.st-kpi-sub{margin-top:5px;font-size:11.5px;color:#8892a8}
.st-panel{background:#11141f;border:1px solid #1e2333;border-radius:8px;padding:18px 20px 12px;margin:14px 0}
.st-panel-head{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:6px 16px;margin-bottom:4px}
.st-panel-title{font-size:14px;font-weight:600;color:#dbe2f0}
.st-panel-note{font-size:11px;color:#6a7488}
.st-legend{display:flex;gap:18px;margin:2px 0 12px}
.st-legend-item{display:flex;align-items:center;gap:6px;font-size:11px;color:#8892a8}
.st-legend-key{width:14px;height:2px;flex:none}
.st-legend-key.raw{background:#d97016}
.st-legend-key.trend{background-image:linear-gradient(90deg,#e6ebf5 0 2px,transparent 2px 8px);background-size:8px 2px;background-repeat:repeat-x;height:2px}
.st-chart-scroll{overflow-x:auto}
.st-chart-svg{display:block;width:100%;height:auto;min-width:680px}
.st-gridline{stroke:#1c2233;stroke-width:1;shape-rendering:crispEdges}
.st-axis-text{font-size:10.5px;fill:#6a7488}
.st-baseline{stroke:#232838;stroke-width:1}
.st-area-fill{fill:rgba(217,112,22,.16)}
.st-line-path{fill:none;stroke:#d97016;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.st-trend-path{fill:none;stroke:#e6ebf5;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;stroke-dasharray:1 6;opacity:.85}
.st-peak-dot{fill:#ffb35c;stroke:#11141f;stroke-width:2}
.st-peak-label-value{font-family:'Orbitron',sans-serif;font-weight:700;font-size:14px;fill:#ffb35c}
.st-peak-label-sub{font-size:10px;fill:#8892a8}
.st-peak-leader{stroke:#565f78;stroke-width:1;stroke-dasharray:2 3}
.st-hover-line{stroke:#565f78;stroke-width:1;opacity:0;pointer-events:none}
.st-hover-dot{fill:#ffb35c;stroke:#11141f;stroke-width:2;opacity:0;pointer-events:none}
.st-hit-layer{fill:transparent;cursor:crosshair}
.st-tooltip{position:absolute;pointer-events:none;background:#171b28;border:1px solid #232838;border-radius:6px;padding:8px 11px;font-size:12px;line-height:1.5;opacity:0;transform:translate(-50%,calc(-100% - 12px));transition:opacity .08s ease;white-space:nowrap;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.st-tooltip .st-t-date{color:#8892a8;font-size:10.5px}
.st-tooltip .st-t-val{font-family:'Orbitron',sans-serif;font-weight:700;color:#ffb35c;font-size:14px;font-variant-numeric:tabular-nums}
.st-tooltip .st-t-trend{color:#8892a8;font-size:10.5px;margin-top:2px;font-variant-numeric:tabular-nums}
.st-table-toggle{margin-top:20px;background:none;border:1px solid #232838;color:#8892a8;font-size:11.5px;letter-spacing:.03em;padding:7px 14px;border-radius:6px;cursor:pointer}
.st-table-toggle:hover{color:#dbe2f0;border-color:#565f78}
.st-table-toggle:focus-visible{outline:2px solid #d97016;outline-offset:2px}
.st-table-wrap{margin-top:12px;overflow-x:auto;display:none}
.st-table-wrap.open{display:block}
table.st-data{border-collapse:collapse;width:100%;font-size:12.5px}
table.st-data th,table.st-data td{text-align:left;padding:6px 12px;border-bottom:1px solid #1c2130;white-space:nowrap}
table.st-data th{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#6a7488;font-weight:500}
table.st-data td.num{font-variant-numeric:tabular-nums;color:#c8cdda}
table.st-data td.month{color:#8892a8}
table.st-data td.cmdr{color:#c8cdda}
table.st-data tr.you-row td{background:rgba(217,112,22,.30)}
table.st-data tr.you-row td.cmdr{color:#ffb35c;font-weight:600}
.st-lb-note{font-size:12.5px;line-height:1.6;color:#8892a8;max-width:68ch;margin:4px 0 16px}
.st-lb-top{display:flex;flex-direction:column;gap:2px;margin-bottom:16px}
.st-lb-row{display:grid;grid-template-columns:40px 1fr auto;align-items:center;gap:12px;padding:8px 11px;border-radius:6px;background:#171b28}
.st-lb-rank{font-family:'Orbitron',sans-serif;font-weight:700;font-size:13px;color:#6a7488;text-align:center}
.st-lb-row.medal-1 .st-lb-rank{color:#ffd35c}
.st-lb-row.medal-2 .st-lb-rank{color:#d7dce6}
.st-lb-row.medal-3 .st-lb-rank{color:#e0a566}
.st-lb-name{font-size:12.5px;color:#dbe2f0;letter-spacing:.01em;overflow:hidden;text-overflow:ellipsis}
.st-lb-count{font-family:'Orbitron',sans-serif;font-weight:700;font-size:13px;color:#8892a8;font-variant-numeric:tabular-nums}
.st-lb-row.medal-1 .st-lb-count,.st-lb-row.medal-2 .st-lb-count,.st-lb-row.medal-3 .st-lb-count{color:#e6ebf5}
.st-lb-divider{display:flex;align-items:center;gap:10px;padding:3px 11px;font-size:10.5px;color:#6a7488}
.st-lb-divider::before,.st-lb-divider::after{content:"";flex:1;height:1px;background:#232838}
.st-lb-row.you{background:rgba(217,112,22,.30);border:1px solid #d97016}
.st-lb-row.you .st-lb-rank,.st-lb-row.you .st-lb-count{color:#ffb35c}
.st-lb-row.you .st-lb-name{color:#e6ebf5;font-weight:600}
.st-lb-you-tag{font-size:9px;letter-spacing:.08em;color:#0c0e16;background:#d97016;padding:1px 5px;border-radius:3px;margin-left:6px}
.st-lb-jump{background:none;border:none;color:#ffb35c;font-size:11px;cursor:pointer;padding:0;text-decoration:underline;text-underline-offset:2px}
.st-lb-jump:hover{color:#dbe2f0}
"""


def chip(colour):
    return f'<span class="chip" title="{html.escape(colour)}" style="background:{COLOUR_HEX.get(colour,"#778")}"></span>'


def esc(s):
    return html.escape(str(s))


def pie_logo(size=44):
    """A little rainbow pie chart built from the codex colour palette, for the report header."""
    wheel = ["Red", "Orange", "Gold", "Yellow", "Lime", "Green", "Teal", "Cyan",
             "Blue", "Cobalt", "Indigo", "Magenta"]
    r = size / 2 - 1
    cx = cy = size / 2
    step = 360 / len(wheel)
    paths, ang = [], -90.0
    for name in wheel:
        a0, a1 = math.radians(ang), math.radians(ang + step)
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        paths.append(f'<path d="M{cx},{cy} L{x0:.2f},{y0:.2f} A{r},{r} 0 0 1 {x1:.2f},{y1:.2f} Z" '
                     f'fill="{COLOUR_HEX[name]}"/>')
        ang += step
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'style="vertical-align:-12px;margin-right:12px">' + "".join(paths) + '</svg>')


def favicon_data_uri(size=32):
    svg = pie_logo(size).replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


_STATS_FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;700&display=swap" '
    'rel="stylesheet">'
)


def _stats_section_html(monthly: dict | None, leaderboard: dict | None,
                        commander_names_: set[str]) -> str:
    """Community-wide monthly activity (log-scale chart + trend line) and the
    all-time commander leaderboard, both from CodexEntries.tsv. Interactive
    (hover tooltip, collapsible tables) — a client-side JS chart, unlike the
    rest of this server-rendered report."""
    if not monthly and not leaderboard:
        return ""

    P = ["<h2>Statistics</h2>",
         "<p class='sub'>Community-wide activity pulled from the same CodexEntries.tsv this report is "
         "built from — how many exobiology regional firsts get logged galaxy-wide each month, and who's "
         "logged the most all-time.</p>",
         "<div class='st-wrap'>"]

    if monthly:
        n = len(monthly["series"])
        P.append("<div class='st-kpis'>"
                 "<div class='st-kpi'><div class='st-kpi-label'>Regional firsts logged</div>"
                 "<div class='st-kpi-value' id='st-kpi-total'>—</div>"
                 "<div class='st-kpi-sub'>since Odyssey launch</div></div>"
                 "<div class='st-kpi'><div class='st-kpi-label'>Peak month</div>"
                 "<div class='st-kpi-value accent' id='st-kpi-peak'>—</div>"
                 "<div class='st-kpi-sub' id='st-kpi-peak-sub'></div></div>"
                 "<div class='st-kpi'><div class='st-kpi-label'>Months tracked</div>"
                 f"<div class='st-kpi-value'>{n}</div>"
                 "<div class='st-kpi-sub' id='st-kpi-months-sub'></div></div>"
                 "</div>")

        P.append(
            "<div class='st-panel'><div class='st-panel-head'>"
            "<div class='st-panel-title'>Regional firsts per month</div>"
            "<div class='st-panel-note'>hover to inspect &middot; log scale</div></div>"
            "<div class='st-legend'>"
            "<div class='st-legend-item'><span class='st-legend-key raw'></span>Monthly count</div>"
            "<div class='st-legend-item'><span class='st-legend-key trend'></span>Trend</div>"
            "</div>"
            "<div class='st-chart-scroll'><svg class='st-chart-svg' id='st-chart' "
            "viewBox='0 0 1180 460' preserveAspectRatio='xMinYMin meet'></svg></div>"
            "<button class='st-table-toggle' id='st-table-btn' type='button' "
            "aria-expanded='false' aria-controls='st-table-wrap'>View as table &darr;</button>"
            "<div class='st-table-wrap' id='st-table-wrap'>"
            "<table class='st-data'><thead><tr><th>Month</th><th>Regional firsts</th></tr></thead>"
            "<tbody id='st-table-body'></tbody></table></div>"
            "</div>")

    if leaderboard:
        P.append(
            "<div class='st-panel'><div class='st-panel-head'>"
            "<div class='st-panel-title'>Commander leaderboard</div>"
            "<div class='st-panel-note' id='st-lb-panel-note'>—</div></div>"
            "<p class='st-lb-note'>Every commander CodexEntries.tsv credits as the discoverer of an "
            "exobiology regional first, ranked by count — same Odyssey-era window as the chart above.</p>"
            "<div class='st-lb-top' id='st-lb-top'></div>"
            "<div style='display:flex;align-items:center;gap:16px;flex-wrap:wrap'>"
            "<button class='st-table-toggle' id='st-lb-btn' type='button' "
            "aria-expanded='false' aria-controls='st-lb-wrap'>View full leaderboard &darr;</button>"
            "<button class='st-lb-jump' id='st-lb-jump' type='button' style='display:none'>"
            "Jump to my rank &rarr;</button>"
            "</div>"
            "<div class='st-table-wrap' id='st-lb-wrap'>"
            "<table class='st-data'><thead><tr><th>Rank</th><th>Commander</th>"
            "<th>Regional firsts</th></tr></thead><tbody id='st-lb-body'></tbody></table></div>"
            "</div>")

    P.append("<div class='st-tooltip' id='st-tooltip'><div class='st-t-date' id='st-tt-date'></div>"
             "<div class='st-t-val' id='st-tt-val'></div><div class='st-t-trend' id='st-tt-trend'></div></div>")
    P.append("</div>")

    P.append("<script>" + _stats_chart_js(monthly) + "</script>")
    P.append("<script>" + _stats_leaderboard_js(leaderboard, commander_names_) + "</script>")
    return "".join(P)


def _stats_chart_js(monthly: dict | None) -> str:
    if not monthly:
        return ""
    return """
(function () {
  var DATA = """ + json.dumps(monthly) + """;
  var series = DATA.series;

  function monthLabel(key) {
    var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var parts = key.split('-');
    return MONTHS[parseInt(parts[1], 10) - 1] + ' ' + parts[0];
  }

  document.getElementById('st-kpi-total').textContent = DATA.total.toLocaleString('en-US');
  document.getElementById('st-kpi-peak').textContent = DATA.peak_val.toLocaleString('en-US');
  document.getElementById('st-kpi-peak-sub').textContent = monthLabel(DATA.peak_month) + ' — Odyssey launch';
  document.getElementById('st-kpi-months-sub').textContent = monthLabel(DATA.start) + ' → ' + monthLabel(DATA.end);

  var tbody = document.getElementById('st-table-body');
  var rows = series.slice().reverse();
  var frag = document.createDocumentFragment();
  rows.forEach(function (d) {
    var tr = document.createElement('tr');
    var tdMonth = document.createElement('td');
    tdMonth.className = 'month';
    tdMonth.textContent = monthLabel(d[0]);
    var tdVal = document.createElement('td');
    tdVal.className = 'num';
    tdVal.textContent = d[1].toLocaleString('en-US');
    tr.appendChild(tdMonth);
    tr.appendChild(tdVal);
    frag.appendChild(tr);
  });
  tbody.appendChild(frag);

  var tableBtn = document.getElementById('st-table-btn');
  var tableWrap = document.getElementById('st-table-wrap');
  tableBtn.addEventListener('click', function () {
    var open = tableWrap.classList.toggle('open');
    tableBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    tableBtn.textContent = open ? 'Hide table ↑' : 'View as table ↓';
  });

  var svg = document.getElementById('st-chart');
  var W = 1180, H = 460;
  var M = { top: 24, right: 20, bottom: 34, left: 54 };
  var plotW = W - M.left - M.right;
  var plotH = H - M.top - M.bottom;
  var n = series.length;
  var yLogMin = 10, yLogMax = 5000;
  var lDomMin = Math.log10(yLogMin), lDomMax = Math.log10(yLogMax);

  function x(i) { return M.left + (i / (n - 1)) * plotW; }
  function y(v) {
    var lv = Math.log10(Math.max(v, yLogMin));
    return M.top + plotH - ((lv - lDomMin) / (lDomMax - lDomMin)) * plotH;
  }

  var svgNS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs) {
    var e = document.createElementNS(svgNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  var yTicks = [10, 30, 100, 300, 1000, 3000];
  yTicks.forEach(function (v) {
    var gy = y(v);
    svg.appendChild(el('line', { x1: M.left, x2: W - M.right, y1: gy, y2: gy, class: 'st-gridline' }));
    var t = el('text', { x: M.left - 10, y: gy + 4, 'text-anchor': 'end', class: 'st-axis-text' });
    t.textContent = v >= 1000 ? (v / 1000) + 'k' : v;
    svg.appendChild(t);
  });
  svg.appendChild(el('line', { x1: M.left, x2: W - M.right, y1: M.top + plotH, y2: M.top + plotH, class: 'st-baseline' }));

  for (var i = 0; i < n; i++) {
    var mm = series[i][0].split('-')[1];
    var yy = series[i][0].split('-')[0];
    if (mm === '01' || i === 0) {
      var gx = x(i);
      var lbl = el('text', { x: gx, y: M.top + plotH + 20, 'text-anchor': 'middle', class: 'st-axis-text' });
      lbl.textContent = yy;
      svg.appendChild(lbl);
    }
  }

  var areaD = 'M ' + x(0) + ' ' + y(series[0][1]);
  for (i = 1; i < n; i++) areaD += ' L ' + x(i) + ' ' + y(series[i][1]);
  areaD += ' L ' + x(n - 1) + ' ' + (M.top + plotH) + ' L ' + x(0) + ' ' + (M.top + plotH) + ' Z';
  svg.appendChild(el('path', { d: areaD, class: 'st-area-fill' }));

  var lineD = 'M ' + x(0) + ' ' + y(series[0][1]);
  for (i = 1; i < n; i++) lineD += ' L ' + x(i) + ' ' + y(series[i][1]);
  svg.appendChild(el('path', { d: lineD, class: 'st-line-path' }));

  var trend = DATA.trend;
  if (trend && trend.length === n) {
    var trendD = 'M ' + x(0) + ' ' + y(trend[0]);
    for (i = 1; i < n; i++) trendD += ' L ' + x(i) + ' ' + y(trend[i]);
    svg.appendChild(el('path', { d: trendD, class: 'st-trend-path' }));
  }

  var peakIdx = series.findIndex(function (d) { return d[0] === DATA.peak_month; });
  var px = x(peakIdx), py = y(series[peakIdx][1]);
  var peakAnchor = peakIdx < n * 0.15 ? 'start' : peakIdx > n * 0.85 ? 'end' : 'middle';
  var peakLabelX = peakAnchor === 'start' ? px + 8 : peakAnchor === 'end' ? px - 8 : px;
  svg.appendChild(el('line', { x1: px, y1: py - 10, x2: px, y2: M.top + 34, class: 'st-peak-leader' }));
  var peakVal = el('text', { x: peakLabelX, y: M.top + 14, 'text-anchor': peakAnchor, class: 'st-peak-label-value' });
  peakVal.textContent = series[peakIdx][1].toLocaleString('en-US');
  svg.appendChild(peakVal);
  var peakSub = el('text', { x: peakLabelX, y: M.top + 28, 'text-anchor': peakAnchor, class: 'st-peak-label-sub' });
  peakSub.textContent = monthLabel(DATA.peak_month) + ' — Odyssey launch';
  svg.appendChild(peakSub);
  svg.appendChild(el('circle', { cx: px, cy: py, r: 4, class: 'st-peak-dot' }));

  var hoverLine = el('line', { x1: 0, x2: 0, y1: M.top, y2: M.top + plotH, class: 'st-hover-line' });
  var hoverDot = el('circle', { r: 4.5, class: 'st-hover-dot' });
  svg.appendChild(hoverLine);
  svg.appendChild(hoverDot);

  var hit = el('rect', { x: M.left, y: M.top, width: plotW, height: plotH, class: 'st-hit-layer' });
  svg.appendChild(hit);

  var tooltip = document.getElementById('st-tooltip');
  var ttDate = document.getElementById('st-tt-date');
  var ttVal = document.getElementById('st-tt-val');
  var ttTrend = document.getElementById('st-tt-trend');

  function pointerToIndex(clientX) {
    var rect = svg.getBoundingClientRect();
    var svgX = (clientX - rect.left) / rect.width * W;
    var frac = (svgX - M.left) / plotW;
    var idx = Math.round(frac * (n - 1));
    return Math.max(0, Math.min(n - 1, idx));
  }

  function showAt(idx) {
    var gx = x(idx), gy = y(series[idx][1]);
    hoverLine.setAttribute('x1', gx);
    hoverLine.setAttribute('x2', gx);
    hoverLine.style.opacity = 1;
    hoverDot.setAttribute('cx', gx);
    hoverDot.setAttribute('cy', gy);
    hoverDot.style.opacity = 1;

    ttDate.textContent = monthLabel(series[idx][0]);
    ttVal.textContent = series[idx][1].toLocaleString('en-US') + ' regional firsts';
    ttTrend.textContent = trend ? 'trend: ' + Math.round(trend[idx]).toLocaleString('en-US') : '';

    var wrapRect = document.querySelector('.st-wrap').getBoundingClientRect();
    var svgRect = svg.getBoundingClientRect();
    var left = (svgRect.left - wrapRect.left) + (gx / W) * svgRect.width;
    var top = (svgRect.top - wrapRect.top) + (gy / H) * svgRect.height;
    tooltip.style.left = left + 'px';
    tooltip.style.top = top + 'px';
    tooltip.style.opacity = 1;
  }

  function hide() {
    hoverLine.style.opacity = 0;
    hoverDot.style.opacity = 0;
    tooltip.style.opacity = 0;
  }

  hit.addEventListener('pointermove', function (e) { showAt(pointerToIndex(e.clientX)); });
  hit.addEventListener('pointerleave', hide);
})();
"""


def _stats_leaderboard_js(leaderboard: dict | None, commander_names_: set[str]) -> str:
    if not leaderboard:
        return ""
    lb = dict(leaderboard)
    lb["me_names"] = sorted(
        r[1] for r in leaderboard["leaderboard"] if r[1].strip().upper() in commander_names_
    )
    return """
(function () {
  var LB = """ + json.dumps(lb) + """;
  var rows = LB.leaderboard;
  var meNames = LB.me_names || [];
  var meRow = null;
  rows.forEach(function (r) { if (meNames.indexOf(r[1]) !== -1 && (!meRow || r[0] < meRow[0])) meRow = r; });

  document.getElementById('st-lb-panel-note').textContent =
    LB.total_cmdrs.toLocaleString('en-US') + ' commanders · ' +
    LB.total_firsts.toLocaleString('en-US') + ' firsts';

  function medalClass(rank) {
    return rank === 1 ? ' medal-1' : rank === 2 ? ' medal-2' : rank === 3 ? ' medal-3' : '';
  }

  function makeRow(rank, name, count, extraClass, tag) {
    var div = document.createElement('div');
    div.className = 'st-lb-row' + medalClass(rank) + (extraClass ? ' ' + extraClass : '');
    var rankEl = document.createElement('div');
    rankEl.className = 'st-lb-rank';
    rankEl.textContent = '#' + rank;
    var nameEl = document.createElement('div');
    nameEl.className = 'st-lb-name';
    nameEl.textContent = name;
    if (tag) {
      var tagEl = document.createElement('span');
      tagEl.className = 'st-lb-you-tag';
      tagEl.textContent = tag;
      nameEl.appendChild(tagEl);
    }
    var countEl = document.createElement('div');
    countEl.className = 'st-lb-count';
    countEl.textContent = count.toLocaleString('en-US');
    div.appendChild(rankEl);
    div.appendChild(nameEl);
    div.appendChild(countEl);
    return div;
  }

  var lbTop = document.getElementById('st-lb-top');
  rows.slice(0, 10).forEach(function (r) { lbTop.appendChild(makeRow(r[0], r[1], r[2])); });

  if (meRow && meRow[0] > 10) {
    var divider = document.createElement('div');
    divider.className = 'st-lb-divider';
    divider.textContent = (meRow[0] - 11) + ' more';
    lbTop.appendChild(divider);
    lbTop.appendChild(makeRow(meRow[0], meRow[1], meRow[2], 'you', 'YOU'));
  }

  var lbBody = document.getElementById('st-lb-body');
  var frag = document.createDocumentFragment();
  rows.forEach(function (r) {
    var tr = document.createElement('tr');
    var isMe = meNames.indexOf(r[1]) !== -1;
    if (isMe) {
      tr.className = 'you-row';
      if (meRow && r[0] === meRow[0]) tr.id = 'st-lb-you-row';
    }
    var tdRank = document.createElement('td');
    tdRank.className = 'num';
    tdRank.textContent = '#' + r[0];
    var tdName = document.createElement('td');
    tdName.className = 'cmdr';
    tdName.textContent = r[1] + (isMe ? '  (you)' : '');
    var tdCount = document.createElement('td');
    tdCount.className = 'num';
    tdCount.textContent = r[2].toLocaleString('en-US');
    tr.appendChild(tdRank);
    tr.appendChild(tdName);
    tr.appendChild(tdCount);
    frag.appendChild(tr);
  });
  lbBody.appendChild(frag);

  var lbBtn = document.getElementById('st-lb-btn');
  var lbWrap = document.getElementById('st-lb-wrap');
  lbBtn.addEventListener('click', function () {
    var open = lbWrap.classList.toggle('open');
    lbBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    lbBtn.textContent = open ? 'Hide full leaderboard ↑' : 'View full leaderboard ↓';
  });

  if (meRow) {
    var lbJump = document.getElementById('st-lb-jump');
    lbJump.style.display = '';
    lbJump.addEventListener('click', function () {
      if (!lbWrap.classList.contains('open')) {
        lbWrap.classList.add('open');
        lbBtn.setAttribute('aria-expanded', 'true');
        lbBtn.textContent = 'Hide full leaderboard ↑';
      }
      var target = document.getElementById('st-lb-you-row');
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }
})();
"""


def _render(star_map, mat_map, gaps, found, regions, genus, sp_regions, sp_here,
            region_stars, cover, prof, personal_region, personal_global, region_materials,
            my_firsts, my_first_list, reconcile_total, cmdrs,
            monthly, leaderboard, out_path: Path) -> None:
    NR = len(regions)
    COVER_OK = 250      # min systems visited to trust "this region has no such star"
    UNIVERSAL = 38      # confirmed in >= this many regions -> "occurs galaxy-wide"

    def spawns(reg, star):
        """Does region `reg` carry star type `star` in enough numbers to be worth
        hunting (galaxy sample)?  Under-sampled regions get the benefit of doubt."""
        cov = cover.get(reg, 0)
        if cov < COVER_OK:
            return True
        need = max(3, round(cov * 0.004))     # ~0.4% of systems, min 3
        return region_stars.get(reg, {}).get(star, 0) >= need

    def sp_state(reg, sp):
        """'here'    = species confirmed in this region (solid regional firsts)
           'univ'    = not confirmed here but occurs galaxy-wide (likely findable)
           'absent'  = confirmed in few regions, not here -> regionally restricted"""
        if sp in sp_here.get(reg, ()):
            return "here"
        return "univ" if len(sp_regions.get(sp, ())) >= UNIVERSAL else "absent"
    GEN_ORDER = ["Aleoida", "Bacterium", "Cactoida", "Clypeus", "Concha", "Fonticulua",
                 "Frutexa", "Osseus", "Recepta", "Stratum", "Tubus", "Tussock"]
    # species that use the star grid (in Canonn star_map or have gap markers), grouped by genus
    species = sorted(set(star_map) | set(gaps), key=lambda s: (GEN_ORDER.index(s.split()[0])
                     if s.split()[0] in GEN_ORDER else 99, s))
    species = [s for s in species if s.split()[0] in GEN_ORDER]

    # ---- galaxy-wide tallies
    gf_reach, gf_exotic = [], []
    for sp in species:
        for star, kind in gaps.get(sp, {}).items():
            (gf_exotic if star in EXOTIC else gf_reach).append((sp, star, kind))
    rf_raw = rf_exotic = 0
    for sp in species:
        for star, col in star_map.get(sp, {}).items():
            miss = NR - len(found.get((sp, col), ()))
            rf_raw += miss
            if star in EXOTIC:
                rf_exotic += miss
    # filtered: only species confirmed present (or galaxy-wide), non-exotic star,
    # and the star type actually spawns in the region in trustworthy numbers
    rf_real = 0
    for reg in regions:
        for sp in species:
            if sp_state(reg, sp) == "absent":
                continue
            for star, col in star_map.get(sp, {}).items():
                if star not in EXOTIC and reg not in found.get((sp, col), ()) and spawns(reg, star):
                    rf_real += 1

    # ---- material-related species (Bacterium Nebulus, Concha Renibus, …) ----
    # Same regional-first method, but the column axis is a surface trace
    # element instead of a star. No galactic-first tracking is possible for
    # these — Missing Colours.tsv (the "Has Gap" source) is star-columns only,
    # nothing equivalent exists for materials.
    def spawns_mat(reg, material):
        """Does region `reg` carry bodies rich in `material` in enough numbers
        to be worth hunting? Same shape/threshold as spawns(), material axis."""
        cov = cover.get(reg, 0)
        if cov < COVER_OK:
            return True
        need = max(3, round(cov * 0.004))
        return region_materials.get(reg, {}).get(material.lower(), 0) >= need

    species_mat = sorted(mat_map, key=lambda s: (MAT_GEN_ORDER.index(s.split()[0])
                         if s.split()[0] in MAT_GEN_ORDER else 99, s))

    rf_mat_raw = 0
    for sp in species_mat:
        for mat, col in mat_map.get(sp, {}).items():
            rf_mat_raw += NR - len(found.get((sp, col), ()))

    rf_mat_real = 0
    for reg in regions:
        for sp in species_mat:
            if sp_state(reg, sp) == "absent":
                continue
            for mat, col in mat_map.get(sp, {}).items():
                if reg not in found.get((sp, col), ()) and spawns_mat(reg, mat):
                    rf_mat_real += 1

    P = [f"<style>{CSS}</style><h1>{pie_logo()}Odyssey Codex Report</h1>"]
    P.append(
        f"<p class='sub'>A colour variant not yet logged in a region is a <b>regional first</b> there; "
        f"one never logged anywhere is a <b>galactic first</b>. Method: Canonn's variant list minus what "
        f"CodexEntries.tsv shows found per region, keeping only species actually known to occur in the "
        f"region. Your own visits don't affect what's missing.</p>")
    P.append(
        f"<p><b>{rf_real:,}</b> realistic regional firsts (species confirmed present in the region, "
        f"ordinary star types). {rf_raw - rf_exotic:,} more exist on paper but for species that have never "
        f"been seen in that region — likely spiral-arm restricted, so excluded. "
        f"<b>{len(gf_reach) + len(gf_exotic)}</b> galactic firsts believed to exist and never logged — "
        f"<b>{len(gf_reach)}</b> of them around ordinary stars. The galactic firsts are the same in every "
        f"region and have gone unfound across ~280&nbsp;million scanned systems, so the per-region view "
        f"below shows only regional firsts — those you can realistically be first to log. A further "
        f"<b>{rf_mat_real:,}</b> realistic regional firsts come from <b>material-related</b> species — "
        f"colour set by a surface trace element instead of a star — covered separately below since no "
        f"galactic-first data exists for them.</p>")

    # ---- your own regional firsts, as a flat table -------------------------
    if my_first_list:
        LONG_LIST = 10
        n = len(my_first_list)
        intro = (f"<p class='sub'>Every colour variant CodexEntries.tsv credits <b>you</b> as the discoverer "
                 f"of, across all regions — <b>{n}</b> so far. Most recent first.</p>")
        table = ["<table class='sum'><tr><th>Region</th><th>Species</th><th>Colour</th>"
                 "<th>System</th><th>Date</th></tr>"]
        for reg, sp, col, system, date in my_first_list:
            table.append(f"<tr><td>{esc(reg)}</td><td>{esc(sp)}</td><td>{chip(col)} {esc(col)}</td>"
                         f"<td class='sub'>{esc(system)}</td><td class='sub'>{esc(date[:10])}</td></tr>")
        table.append("</table>")
        if n > LONG_LIST:
            P.append(f"<details><summary class='h2toggle'>\U0001f3c6 Your regional firsts "
                     f"({n})</summary>" + intro + "".join(table) + "</details>")
        else:
            P.append(f"<h2>\U0001f3c6 Your regional firsts</h2>" + intro + "".join(table))

    # ---- ONE galactic-firsts matrix (region-independent) ------------------
    P.append("<h2>Galactic firsts — the whole-galaxy picture</h2>")
    P.append("<p class='sub'>Every species &times; star type. <b>★ / ?</b> = a variant believed to exist "
             "that <b>nobody has ever logged</b> (players have scanned ~280&nbsp;million systems and still "
             "not found these). A faint chip = a variant that <i>is</i> confirmed somewhere. Blank = no "
             "such variant. Column = parent star.</p>")
    P.append("<p class='sub legend'>"
             "<span class='gf' style='padding:1px 7px'>★ galactic first (reachable star)</span>"
             "<span class='gfx' style='padding:1px 7px'>★ galactic first (O / WR / Herbig — forget it)</span>"
             "<span class='confirmed' style='padding:1px 7px'>confirmed somewhere</span>"
             "<span class='mine' style='padding:1px 7px'>in your codex</span></p>")
    P.append("<table class='mx'><tr><th class='sp'></th>"
             + "".join(f"<th title='{STAR_FULL[s]}'>{STAR_LABEL[s]}</th>" for s in STARS) + "</tr>")
    last_gen = None
    for sp in species:
        cells = []
        for star in STARS:
            col = star_map.get(sp, {}).get(star)
            gap = gaps.get(sp, {}).get(star)
            if gap:
                mark = "★" if gap == "gap" else "?"
                cls = "gfx" if star in EXOTIC else "gf"
                cells.append(f"<td class='{cls}' title='{esc(sp)} — {STAR_FULL[star]}: galactic first'>{mark}</td>")
            elif col:
                if col in personal_global.get(sp, ()):
                    cells.append(f"<td class='mine' title='{esc(sp)} – {esc(col)} ({STAR_FULL[star]}): "
                                 f"in your codex'>{chip(col)}</td>")
                else:
                    cells.append(f"<td class='confirmed' title='{esc(sp)} – {esc(col)} ({STAR_FULL[star]}): confirmed'>{chip(col)}</td>")
            else:
                cells.append("<td class='na'></td>")
        g = sp.split()[0]
        trclass = " class='gsep'" if last_gen and g != last_gen else ""
        last_gen = g
        P.append(f"<tr{trclass}><td class='sp'>{esc(sp)}</td>" + "".join(cells) + "</tr>")
    P.append("</table>")
    P.append("<p class='sub'>The reachable ones (★ not in an O/WR/Herbig column): "
             + esc(", ".join(f"{sp} – {STAR_FULL[st]}"
                   for sp, st, _ in sorted(gf_reach, key=lambda x: (STARS.index(x[1]), x[0]))))
             + f". {len(gf_exotic)} more sit in O/WR/Herbig columns and are effectively unobtainable.</p>")

    ref_txt = f"{reconcile_total:,}" if reconcile_total else "~4,500"
    P.append('<div class="warn"><b>Reconciliation.</b> The community "Undiscovered Odyssey Biology Count" '
             f"sheet lists {ref_txt} outstanding; after excluding species not known in each region this method "
             f"finds ~{rf_real:,}. The remaining gap is species that occur in a region but have had no "
             "colour logged there yet (shown dimmed) — real, lower-confidence firsts.</div>")

    P.append("<p class='sub legend'>Region-matrix cells: "
             "<span class='done' style='padding:1px 6px'>found here</span>"
             "<span class='mine' style='padding:1px 6px'>in your codex</span>"
             "<span class='myfirst' style='padding:1px 6px'>\U0001f3c6 you discovered this regional first</span>"
             "<span class='rf' style='padding:1px 6px'>regional first (species confirmed here)</span>"
             "<span class='rfsoft' style='padding:1px 6px'>species occurs galaxy-wide, not yet confirmed here</span>"
             "<span class='rfdead' style='padding:1px 6px'>region has ~no such star</span>"
             "<span class='na' style='padding:1px 6px'>n/a</span>. "
             "Galactic firsts are <b>not</b> shown per region.</p>")

    # ---- material-related species — the whole-galaxy picture -----------------
    if species_mat:
        P.append("<h2>Material-related species — the whole-galaxy picture</h2>")
        P.append("<p class='sub'>Same idea as the star matrix above, but the column is a surface trace "
                 "element instead of a star — these species (Bacterium, Concha, Electricae, Fumerola, "
                 "Fungoida, Osseus, Recepta) key their colour off whichever of six named materials the "
                 "body is richest in. No galactic-first tracking exists for these (Missing Colours.tsv is "
                 "star-columns only), so every valid variant just shows confirmed or in-your-codex.</p>")
        P.append("<p class='sub legend'>"
                 "<span class='confirmed' style='padding:1px 7px'>confirmed somewhere</span>"
                 "<span class='mine' style='padding:1px 7px'>in your codex</span></p>")
        P.append("<table class='mx'><tr><th class='sp'></th>"
                 + "".join(f"<th title='{m}'>{m[:3]}</th>" for m in MATERIALS) + "</tr>")
        last_gen = None
        for sp in species_mat:
            cells = []
            for mat in MATERIALS:
                col = mat_map.get(sp, {}).get(mat)
                if col:
                    if col in personal_global.get(sp, ()):
                        cells.append(f"<td class='mine' title='{esc(sp)} – {esc(col)} ({esc(mat)}): "
                                     f"in your codex'>{chip(col)}</td>")
                    else:
                        cells.append(f"<td class='confirmed' title='{esc(sp)} – {esc(col)} ({esc(mat)}): "
                                     f"confirmed'>{chip(col)}</td>")
                else:
                    cells.append("<td class='na'></td>")
            g = sp.split()[0]
            trclass = " class='gsep'" if last_gen and g != last_gen else ""
            last_gen = g
            P.append(f"<tr{trclass}><td class='sp'>{esc(sp)}</td>" + "".join(cells) + "</tr>")
        P.append("</table>")

    # ---- per-region matrices (regional firsts only)
    P.append("<h2>By region — regional firsts</h2><p class='sub'>Only species already <b>confirmed to occur "
             "in the region</b> are in the matrix (their unlogged colours are real firsts). Species never "
             "confirmed there — likely restricted to other spiral arms — are struck through in a footnote "
             "and not counted. Near-universal species not yet confirmed in a region are shown "
             "<span class='rfsoft' style='padding:0 4px'>dimmed</span>. <b>Well-sampled regions first.</b> "
             "A gap counts as <b>viable</b> only if that star type is known to occur in the region.</p>")
    _shown_thin_header = [False]

    def viable_count(reg):
        n = dead = 0
        for sp in species:
            if sp_state(reg, sp) == "absent":
                continue
            for star, col in star_map.get(sp, {}).items():
                if star in EXOTIC or reg in found.get((sp, col), ()):
                    continue
                if spawns(reg, star):
                    n += 1
                else:
                    dead += 1
        return n, dead

    reg_stats = {r: viable_count(r) for r in regions}

    def rank_key(r):
        return (0 if cover.get(r, 0) >= 400 else 1, -reg_stats[r][0])

    for reg in sorted(regions, key=rank_key):
        viable, dead = reg_stats[reg]
        if cover.get(reg, 0) < 400 and not _shown_thin_header[0]:
            _shown_thin_header[0] = True
            P.append("<h3 style='margin-top:1.5em;color:#8892a8'>— under-sampled regions "
                     "(star-population numbers unreliable) —</h3>")

        rows_html, absent_sp = [], []
        star_gap = collections.Counter()
        col_totals = collections.Counter()
        last_gen = None
        for sp in species:
            st_state = sp_state(reg, sp)
            if st_state == "absent":
                absent_sp.append(sp)
                continue
            cells, any_missing = [], False
            for star in STARS:
                col = star_map.get(sp, {}).get(star)
                if not col:
                    cells.append("<td class='na'></td>")
                    continue
                if reg in found.get((sp, col), ()):
                    if col in my_firsts.get(reg, {}).get(sp, ()):
                        cells.append(f"<td class='myfirst' title='{esc(sp)} – {esc(col)}: "
                                     f"you discovered this regional first!'>\U0001f3c6{chip(col)}</td>")
                    elif col in personal_region.get(reg, {}).get(sp, ()):
                        cells.append(f"<td class='mine' title='{esc(sp)} – {esc(col)}: in your codex'>{chip(col)}</td>")
                    else:
                        cells.append(f"<td class='done'>{chip(col)}</td>")
                elif star in EXOTIC or not spawns(reg, star):
                    why = "almost no bio around this star type" if star in EXOTIC else f"no {STAR_FULL[star]} in this region"
                    cells.append(f"<td class='rfdead' title='{esc(sp)} – {esc(col)}: {why}'>{chip(col)}</td>")
                    any_missing = True
                else:
                    cls = "rf" if st_state == "here" else "rfsoft"
                    cells.append(f"<td class='{cls}' title='{esc(sp)} – {esc(col)} ({STAR_FULL[star]})'>{chip(col)}</td>")
                    any_missing = True
                    col_totals[star] += 1
                    if st_state == "here":
                        star_gap[star] += 1
            if not any_missing:
                continue
            g = sp.split()[0]
            trclass = " class='gsep'" if last_gen and g != last_gen else ""
            last_gen = g
            nm = esc(sp) if st_state == "here" else f"<i>{esc(sp)}</i> <span class='sub'>?</span>"
            rows_html.append(f"<tr{trclass}><td class='sp'>{nm}</td>" + "".join(cells) + "</tr>")

        cov = cover.get(reg, 0)
        deadtxt = f", {dead} where the star type is absent here" if dead else ""
        summ = (f"{esc(reg)} &nbsp;—&nbsp; <b>{viable}</b> viable regional firsts{deadtxt} "
                f"<span class='prof'>&nbsp;({cov:,} systems sampled, {len(absent_sp)} species not present)</span>")
        P.append(f"<details><summary>{summ}</summary><div class='region'>")
        P.append("<table class='mx'><tr><th class='sp'></th>"
                 + "".join(f"<th title='{STAR_FULL[s]}'>{STAR_LABEL[s]}</th>" for s in STARS) + "</tr>")
        P.append("<tr class='mxtot' title='viable regional firsts in this column'><td class='sp sub'>&Sigma;</td>"
                 + "".join(f"<td>{col_totals[s] or ''}</td>" for s in STARS) + "</tr>")
        P.append("".join(rows_html) + "</table>")

        top = star_gap.most_common()
        if top:
            parts = [f"<b>{STAR_FULL[st]}</b> ({n})" + (f" — {STAR_TIP[st]}" if st in STAR_TIP else "")
                     for st, n in top[:6]]
            P.append("<p class='hint'><b>Where the firsts are (confirmed species):</b> "
                     + "; ".join(parts) + ".</p>")
        P.append("<p class='hint'>The plant's planet usually orbits a <i>companion</i> star — that "
                 "companion's class sets the colour, so a neutron / white-dwarf / brown-dwarf variant "
                 "means finding one as a secondary with its own close planets. "
                 "<i>Italic ?</i> rows are galaxy-wide species not yet confirmed here — probably present, "
                 "but the first confirmation would itself be the regional first.</p>")
        if absent_sp:
            P.append("<details class='sub'><summary>" + str(len(absent_sp))
                     + " species never confirmed in this region (likely restricted to other spiral arms — "
                     "excluded)</summary><p style='text-decoration:line-through'>"
                     + esc(", ".join(absent_sp)) + "</p></details>")
        pr = prof.get(reg)
        if pr:
            P.append("<p class='prof'>you've scanned bio here around: "
                     + "  ".join(f"{k} {v}" for k, v in pr.most_common(12)) + "</p>")

        # material-related species for this region (same viable/absent logic,
        # material axis instead of star)
        mat_rows_html, absent_sp_mat = [], []
        mat_totals = collections.Counter()
        last_gen = None
        for sp in species_mat:
            st_state = sp_state(reg, sp)
            if st_state == "absent":
                absent_sp_mat.append(sp)
                continue
            cells, any_missing = [], False
            for mat in MATERIALS:
                col = mat_map.get(sp, {}).get(mat)
                if not col:
                    cells.append("<td class='na'></td>")
                    continue
                if reg in found.get((sp, col), ()):
                    if col in my_firsts.get(reg, {}).get(sp, ()):
                        cells.append(f"<td class='myfirst' title='{esc(sp)} – {esc(col)}: "
                                     f"you discovered this regional first!'>\U0001f3c6{chip(col)}</td>")
                    elif col in personal_region.get(reg, {}).get(sp, ()):
                        cells.append(f"<td class='mine' title='{esc(sp)} – {esc(col)}: in your codex'>{chip(col)}</td>")
                    else:
                        cells.append(f"<td class='done'>{chip(col)}</td>")
                elif not spawns_mat(reg, mat):
                    cells.append(f"<td class='rfdead' title='{esc(sp)} – {esc(col)}: "
                                 f"no {esc(mat)}-rich bodies known in this region'>{chip(col)}</td>")
                    any_missing = True
                else:
                    cls = "rf" if st_state == "here" else "rfsoft"
                    cells.append(f"<td class='{cls}' title='{esc(sp)} – {esc(col)} ({esc(mat)})'>{chip(col)}</td>")
                    any_missing = True
                    mat_totals[mat] += 1
            if not any_missing:
                continue
            g = sp.split()[0]
            trclass = " class='gsep'" if last_gen and g != last_gen else ""
            last_gen = g
            nm = esc(sp) if st_state == "here" else f"<i>{esc(sp)}</i> <span class='sub'>?</span>"
            mat_rows_html.append(f"<tr{trclass}><td class='sp'>{nm}</td>" + "".join(cells) + "</tr>")

        if mat_rows_html:
            P.append("<h3 style='margin-top:1.2em'>Material-related species</h3>")
            P.append("<table class='mx'><tr><th class='sp'></th>"
                     + "".join(f"<th title='{m}'>{m[:3]}</th>" for m in MATERIALS) + "</tr>")
            P.append("<tr class='mxtot' title='viable regional firsts in this column'><td class='sp sub'>&Sigma;</td>"
                     + "".join(f"<td>{mat_totals[m] or ''}</td>" for m in MATERIALS) + "</tr>")
            P.append("".join(mat_rows_html) + "</table>")
            if absent_sp_mat:
                P.append("<details class='sub'><summary>" + str(len(absent_sp_mat))
                         + " material-related species never confirmed in this region</summary>"
                         "<p style='text-decoration:line-through'>"
                         + esc(", ".join(absent_sp_mat)) + "</p></details>")

        P.append("</div></details>")

    # ---- by star type ------------------------------------------------------
    P.append("<h2>By star type — where to point your ship</h2>")
    P.append("<p class='sub'>Same data, the other way round: pick the star type you're camped on and see which "
             "regions have the most open entries for it (only species already confirmed present in the region "
             "count). Exotic stars (O / Wolf-Rayet / Herbig Ae/Be) are listed last — bio there is almost "
             "nonexistent.</p>")

    def star_viable_regions(sp, col, star):
        return [reg for reg in regions
                if sp_state(reg, sp) != "absent"
                and reg not in found.get((sp, col), ())
                and spawns(reg, star)]

    star_rows: dict[str, list] = {}
    star_totals: dict[str, int] = {}
    for star in STARS:
        rows, total = [], 0
        for sp in species:
            gap = gaps.get(sp, {}).get(star)
            if gap:
                rows.append((sp, None, [], gap))
                continue
            col = star_map.get(sp, {}).get(star)
            if not col:
                continue
            regs = [] if star in EXOTIC else star_viable_regions(sp, col, star)
            if regs:
                rows.append((sp, col, regs, None))
                total += len(regs)
        star_rows[star] = rows
        star_totals[star] = total

    for star in sorted(STARS, key=lambda s: (s in EXOTIC, -star_totals.get(s, 0))):
        rows = star_rows[star]
        if not rows:
            continue
        gal = sorted(sp for sp, col, regs, gap in rows if gap)
        region_counts: collections.Counter = collections.Counter()
        region_species: dict[str, list] = collections.defaultdict(list)
        for sp, col, regs, gap in rows:
            if gap:
                continue
            for reg in regs:
                region_counts[reg] += 1
                region_species[reg].append((sp, col))
        P.append(f"<details><summary><b>{STAR_FULL[star]}</b> ({STAR_LABEL[star]}) &nbsp;—&nbsp; "
                 f"<b>{star_totals[star]}</b> viable regional firsts"
                 + (f", {len(gal)} galactic first(s) unlogged anywhere" if gal else "")
                 + (" — near-impossible, only a handful of candidate planets galaxy-wide"
                    if star in EXOTIC else "")
                 + "</summary><div class='region'>")
        if star in STAR_TIP:
            P.append(f"<p class='hint'>{esc(STAR_TIP[star])}</p>")
        if gal:
            P.append("<p class='hint'><b>Galactic firsts needing this star:</b> " + esc(", ".join(gal)) + "</p>")
        if region_counts:
            P.append("<table class='sum'><tr><th>Region</th><th>Open</th><th>Species</th></tr>")
            ranked = sorted(region_counts, key=lambda r: (0 if cover.get(r, 0) >= 400 else 1, -region_counts[r]))
            thin_shown = False
            for reg in ranked:
                if cover.get(reg, 0) < 400 and not thin_shown:
                    thin_shown = True
                    P.append("<tr><td colspan='3' style='color:#8892a8;padding-top:8px'>"
                              "— under-sampled regions (star-population numbers unreliable) —</td></tr>")
                n = region_counts[reg]
                sp_list = ", ".join(f"{chip(col)} {esc(sp)}" for sp, col in sorted(region_species[reg]))
                P.append(f"<tr><td>{esc(reg)}</td><td class='n'>{n}</td>"
                         f"<td class='sub'>{sp_list}</td></tr>")
            P.append("</table>")
        P.append("</div></details>")

    # ---- by material ---------------------------------------------------------
    if species_mat:
        P.append("<h2>By material — where to land your ship</h2>")
        P.append("<p class='sub'>Same idea as the by-star-type view, but for material-related species: pick "
                 "the trace element you're prospecting for and see which regions have the most open entries "
                 "for it (only species already confirmed present in the region count).</p>")

        def mat_viable_regions(sp, col, mat):
            return [reg for reg in regions
                    if sp_state(reg, sp) != "absent"
                    and reg not in found.get((sp, col), ())
                    and spawns_mat(reg, mat)]

        mat_rows_by_col: dict[str, list] = {}
        mat_totals_by_col: dict[str, int] = {}
        for mat in MATERIALS:
            rows, total = [], 0
            for sp in species_mat:
                col = mat_map.get(sp, {}).get(mat)
                if not col:
                    continue
                regs = mat_viable_regions(sp, col, mat)
                if regs:
                    rows.append((sp, col, regs))
                    total += len(regs)
            mat_rows_by_col[mat] = rows
            mat_totals_by_col[mat] = total

        for mat in sorted(MATERIALS, key=lambda m: -mat_totals_by_col.get(m, 0)):
            rows = mat_rows_by_col[mat]
            if not rows:
                continue
            region_counts: collections.Counter = collections.Counter()
            region_species: dict[str, list] = collections.defaultdict(list)
            for sp, col, regs in rows:
                for reg in regs:
                    region_counts[reg] += 1
                    region_species[reg].append((sp, col))
            P.append(f"<details><summary><b>{esc(mat)}</b> &nbsp;—&nbsp; "
                     f"<b>{mat_totals_by_col[mat]}</b> viable regional firsts</summary><div class='region'>")
            if region_counts:
                P.append("<table class='sum'><tr><th>Region</th><th>Open</th><th>Species</th></tr>")
                ranked = sorted(region_counts, key=lambda r: (0 if cover.get(r, 0) >= 400 else 1, -region_counts[r]))
                thin_shown = False
                for reg in ranked:
                    if cover.get(reg, 0) < 400 and not thin_shown:
                        thin_shown = True
                        P.append("<tr><td colspan='3' style='color:#8892a8;padding-top:8px'>"
                                  "— under-sampled regions (star-population numbers unreliable) —</td></tr>")
                    n = region_counts[reg]
                    sp_list = ", ".join(f"{chip(col)} {esc(sp)}" for sp, col in sorted(region_species[reg]))
                    P.append(f"<tr><td>{esc(reg)}</td><td class='n'>{n}</td>"
                             f"<td class='sub'>{sp_list}</td></tr>")
                P.append("</table>")
            P.append("</div></details>")

    # ---- statistics (community-wide monthly activity + commander leaderboard)
    stats_html = _stats_section_html(monthly, leaderboard, cmdrs)
    P.append(stats_html)

    font_link = _STATS_FONT_LINK if stats_html else ""
    out_path.write_text("<!doctype html><meta charset=utf-8><title>Odyssey Codex Report</title>"
                        f'<link rel="icon" href="{favicon_data_uri()}">{font_link}' + "".join(P),
                        encoding="utf-8")
    print(f"  wrote {out_path}")
    print(f"  realistic regional firsts: {rf_real:,}   (raw incl. absent species: {rf_raw - rf_exotic:,})")
    print(f"  galactic firsts: {len(gf_reach)} reachable + {len(gf_exotic)} exotic")
    print(f"  material-related regional firsts: {rf_mat_real:,}   (raw incl. absent species: {rf_mat_raw:,})")


def build_codex_report(conn: sqlite3.Connection, out_path: Path) -> None:
    """Build and write the self-contained Odyssey Codex gap-analysis report."""
    star_map, mat_map = load_canonn()
    cmdrs = commander_names(conn)
    found, regions, genus, sp_regions, sp_here, my_firsts, my_first_list, discoverer_counts = load_found(cmdrs)
    gaps = load_gaps()
    region_stars, cover, prof, personal_region, personal_global, region_materials = \
        db_region_data(conn, star_map, mat_map)
    reconcile_total = load_reconciliation_total()
    monthly = load_monthly_series()
    leaderboard = build_commander_leaderboard(discoverer_counts)
    _render(star_map, mat_map, gaps, found, regions, genus, sp_regions, sp_here,
            region_stars, cover, prof, personal_region, personal_global, region_materials,
            my_firsts, my_first_list, reconcile_total, cmdrs,
            monthly, leaderboard, out_path)
