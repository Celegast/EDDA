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


def load_found():
    """(species,colour) -> regions where Found=1; region list; genus per species;
    sp_regions[species] -> regions where the species has ANY confirmed variant;
    sp_here[region] -> species confirmed present there."""
    found: dict[tuple, set] = collections.defaultdict(set)
    regions: set[str] = set()
    genus: dict[str, str] = {}
    sp_regions: dict[str, set] = collections.defaultdict(set)
    sp_here: dict[str, set] = collections.defaultdict(set)
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
    return found, sorted(regions), genus, sp_regions, sp_here


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


def db_region_data(conn: sqlite3.Connection):
    """From the report DB, per region:
       stars[region][star_code]  = systems with that star type present
       cover[region]             = systems visited (confidence)
       prof[region][star_code]   = your bio scans by parent star ('tried here?')
       personal_region[region][species] = star codes you've personally scanned
                                   that species around, IN THIS REGION
       personal_global[species]  = the same, but anywhere (for the whole-galaxy
                                   matrix, which isn't region-scoped)."""
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
    for reg, sp, st in conn.execute("""
        SELECT s.region, o.species_localised, ps.subtype
        FROM organic_scans o
        JOIN systems s ON s.system_address=o.system_address
        JOIN bodies b  ON b.system_address=o.system_address AND b.body_id=o.body_id
        LEFT JOIN bodies ps ON ps.system_address=o.system_address AND ps.body_id=b.parent_star_id
        WHERE o.scan_state='Analyse' AND o.species_localised>'' AND s.region>''
        GROUP BY s.region, o.species_localised, ps.subtype"""):
        c = _SUBTYPE_STAR.get(st or "")
        if c:
            personal_region[reg][sp].add(c)
            personal_global[sp].add(c)

    return stars, cover, prof, personal_region, personal_global


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
.rf{background:#2b2410;outline:1px solid #6a5a24}
.rfsoft{background:#1c1e26;outline:1px solid #333a48}
.rfdead{background:#1a1720}
.gf{background:#3a2c0c;outline:1px solid #caa63c;box-shadow:inset 0 0 6px #caa63c66;color:#f0c24a;font-weight:700}
.gfx{background:#241d16;color:#7c6a42}
.na{background:#0e1017}
.region{background:#11141f;border:1px solid #1e2333;border-radius:6px;padding:12px 16px;margin:12px 0}
details>summary{cursor:pointer;color:#cdd6ea;font-size:1.02rem;padding:4px 0}
.prof{font:11px/1.5 ui-monospace,monospace;color:#7c8598;margin:.3em 0}
.hint{color:#9aa3b8;margin:.4em 0;max-width:90ch}
.legend span{margin-right:16px}
.warn{background:#2a1a15;border-left:3px solid #c0603a;padding:10px 14px;border-radius:4px;max-width:88ch;margin:1em 0}
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


def _render(star_map, mat_map, gaps, found, regions, genus, sp_regions, sp_here,
            region_stars, cover, prof, personal_region, personal_global,
            reconcile_total, out_path: Path) -> None:
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

    P = [f"<style>{CSS}</style><h1>{pie_logo()}Odyssey Codex (report)</h1>"]
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
        f"below shows only regional firsts — those you can realistically be first to log.</p>")
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
                if star in personal_global.get(sp, ()):
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
             "<span class='rf' style='padding:1px 6px'>regional first (species confirmed here)</span>"
             "<span class='rfsoft' style='padding:1px 6px'>species occurs galaxy-wide, not yet confirmed here</span>"
             "<span class='rfdead' style='padding:1px 6px'>region has ~no such star</span>"
             "<span class='na' style='padding:1px 6px'>n/a</span>. "
             "Galactic firsts are <b>not</b> shown per region.</p>")

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
                    if star in personal_region.get(reg, {}).get(sp, ()):
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

    # ---- materials appendix
    if mat_map:
        P.append("<h2>Material-gated species (Bacterium / Concha / Osseus / Recepta …)</h2>"
                 "<p class='sub'>These variants key off a rare <i>surface material</i>, not the star. "
                 "Colour follows the material. Region tracking for these is spotty in the source data, so "
                 "this is just the variant list — hunt planets rich in the named element.</p>")
        P.append("<table class='sum'><tr><th>Species</th><th>Variants (colour – material)</th></tr>")
        for sp in sorted(mat_map):
            vs = ", ".join(f"{chip(c)} {esc(c)}–{esc(m)}" for m, c in mat_map[sp].items())
            P.append(f"<tr><td>{esc(sp)}</td><td class='sub'>{vs}</td></tr>")
        P.append("</table>")

    out_path.write_text("<!doctype html><meta charset=utf-8><title>Odyssey Codex (report)</title>"
                        f'<link rel="icon" href="{favicon_data_uri()}">' + "".join(P),
                        encoding="utf-8")
    print(f"  wrote {out_path}")
    print(f"  realistic regional firsts: {rf_real:,}   (raw incl. absent species: {rf_raw - rf_exotic:,})")
    print(f"  galactic firsts: {len(gf_reach)} reachable + {len(gf_exotic)} exotic")


def build_codex_report(conn: sqlite3.Connection, out_path: Path) -> None:
    """Build and write the self-contained Odyssey Codex gap-analysis report."""
    star_map, mat_map = load_canonn()
    found, regions, genus, sp_regions, sp_here = load_found()
    gaps = load_gaps()
    region_stars, cover, prof, personal_region, personal_global = db_region_data(conn)
    reconcile_total = load_reconciliation_total()
    _render(star_map, mat_map, gaps, found, regions, genus, sp_regions, sp_here,
            region_stars, cover, prof, personal_region, personal_global,
            reconcile_total, out_path)
