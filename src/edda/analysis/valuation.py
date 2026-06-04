"""
Credit value estimates for exploration data and exobiology scans.

Body formula (Odyssey era, community-verified):
    scan_value = k * (1 + 3 * mass_em^0.199977 / 5.3)
    + terraforming bonus applied to k before the mass term
    × first-discovered multiplier (2.0)
    × mapping multiplier (3.3 if first-mapped, 1.5 if mapped-not-first)

Exobiology:
    payout = base_species_value × (5 if first_log else 1) × antal_bonus
    where antal_bonus = 1.3 at base pledge rank (only when selling in Antal systems)

All values are estimates — the game applies rounding and minor undocumented
corrections that can cause a few percent deviation from calculated figures.
"""

import math
import re

# ---------------------------------------------------------------------------
# Body value constants
# ---------------------------------------------------------------------------

# Base k values per planet class (Odyssey era).
# These determine how much raw mass scaling matters for each body type.
# All keys are lowercase — matched via planet_class.lower() at lookup time.
BODY_BASE_K: dict[str, float] = {
    "metal rich body":                    52_292,
    "high metal content body":            23_168,
    "rocky body":                            720,
    "rocky ice body":                        720,
    "icy body":                              720,
    "water world":                       155_581,
    "ammonia world":                     232_619,
    "earthlike body":                    155_581,
    "water giant":                         3_974,
    "gas giant with water based life":     3_974,
    "gas giant with ammonia based life":  23_168,
    "class i gas giant":                   3_974,
    "class ii gas giant":                 23_168,
    "class iii gas giant":                 3_974,
    "class iv gas giant":                  3_974,
    "class v gas giant":                   3_974,
    "helium rich gas giant":               3_974,
    "helium gas giant":                    3_974,
}

TERRA_BONUS_K: dict[str, float] = {
    "high metal content body":  241_607,
    "water world":              279_088,
    "earthlike body":           279_088,
    "rocky body":               223_971,
    "rocky ice body":           223_971,
}

# ELW always includes the terraforming bonus regardless of terraform_state —
# the game treats all ELW as intrinsically habitable.  WW can be either
# terraformable or not, so it uses the terraform_state field normally.
_ALWAYS_TERRA = {"earthlike body"}

# ---------------------------------------------------------------------------
# Star value constants
# ---------------------------------------------------------------------------

# Base k values per star type (Odyssey era, community-derived).
# Lookup order: "{star_type}_{luminosity}".lower() first, then star_type.lower() fallback.
# Formula:
#   primary   star: k × (1 + mass^0.5) × (6.0 if FD else 1.0)
#   companion star: k × 0.01 × (1 + mass^0.5) × (2.0 if FD else 1.0)
# Calibrated against in-game sell screens (no-FD primary unless noted):
#   A Vb = 76,868 (Pria Free HL-P d5-7, A Vb, mass=1.660, no FD)
#   F Vb = 79,773 (Aucopp LN-A d1-2, F4 Vb, mass=1.277, no FD)
#   F Vb = 78,990 (Huemo FN-R d5-7, mass=1.227, FD÷6 — matches Aucopp within 1%)
#   F VI = 19,271 (Truechiae FS-B d13-2, F0 VI, mass=1.617, FD÷6)
#   G Va = 44,514 (mean of SYNUEFAI WA-F C27-3 + PO-I C25-3, G Vab, no FD)
#   K Vab = 81,019 (Pro Auwsy FQ-G d10-5, K Vab, mass=0.934, no FD)
#   DC   = 14,718 (confirmed community value)
STAR_BASE_K: dict[str, float] = {
    # Main sequence (generic fallback — use luminosity-specific keys below when known)
    "o":     3_933,
    "b":     3_184,
    "a":     1_445,   # fallback — see "a_vb" for main-sequence calibration
    "f":    79_773,   # calibrated: F4 Vb Aucopp LN-A d1-2 (no FD)
    "g":    44_514,   # calibrated: mean of G Vab SYNUEFAI WA-F C27-3 + PO-I C25-3 (no FD)
    "k":     1_100,   # fallback — see "k_va"/"k_vab" for main-sequence calibration
    "m":     1_100,   # uncalibrated
    # Luminosity-class-specific entries (compound key: "{type}_{lum}")
    "a_v":   40_582,   # A main seq    — HIP 12164            A V    (no FD, single point)
    "a_vb":  76_868,   # A main seq    — Pria Free HL-P d5-7  A Vb   (no FD)
    "f_vi":  19_271,   # F subdwarf    — Truechiae FS-B d13-2 F0 VI  (FD, star_FD_mult=6)
    "f_vb":  79_773,   # F main seq    — Aucopp LN-A d1-2    F4 Vb  (no FD)
    "g_va":  44_514,   # G main seq    — mean of SYNUEFAI WA-F C27-3 + PO-I C25-3 (no FD)
    "g_vab": 44_514,   # G main seq    — same calibration, Va ≈ Vab
    "k_va":   9_325,   # K main seq    — SWOILZ KZ-D C3             K Va   (no FD, single point)
    "k_vab": 81_019,   # K main seq    — Pro Auwsy FQ-G d10-5       K Vab  (no FD)
    # Brown dwarfs
    "l":     1_100,
    "t":     1_100,
    "y":     1_100,
    # Pre-main-sequence / peculiar
    "tts":   1_100,   # T Tauri
    "aebe":  2_111,   # Herbig Ae/Be
    # Carbon / S-type
    "c":     2_111,  "cs":  2_111,  "cn":  2_111,
    "cj":    2_111,  "ch":  2_111,  "chd": 2_111,
    "ms":    2_111,  "s":   2_111,
    # Giant branches
    "a_bluewhitesupergiant": 2_111,
    "f_whitesupergiant":     2_111,
    "m_redsupergiant":       2_111,
    "m_redgiant":            2_111,
    "k_orangegiant":         2_111,
    # Wolf-Rayet
    "w":    22_628,  "wn":  22_628,  "wnc": 22_628,
    "wc":   22_628,  "wo":  22_628,
    # White dwarfs
    "d":    14_718,  "da":  14_718,  "dab": 14_718,
    "dah":  14_718,  "daz": 14_718,  "db":  14_718,
    "dbz":  14_718,  "dbv": 14_718,  "do":  14_718,
    "dov":  14_718,  "dq":  14_718,  "dc":  14_718,
    "dcv":  14_718,  "dx":  14_718,
    # Compact objects
    "n":    22_628,   # neutron star
    "h":    22_628,   # black hole
    "supermassiveblackhole": 22_628,
    "x":    22_628,
}

# ---------------------------------------------------------------------------
# Multipliers
# ---------------------------------------------------------------------------
_FIRST_DISCOVERED_MULT      = 2.0
_STAR_FIRST_DISCOVERED_MULT = 6.0   # fallback FD multiplier for uncalibrated star types
_COMPANION_K_FRACTION       = 0.01  # companion stars worth ~1% of primary k (ratio ~1:100)

# Per-type FD multipliers for primary stars (compound key "{type}_{lum}" or bare type).
# Where absent, falls back to _STAR_FIRST_DISCOVERED_MULT (6.0).
# Derived from in-game sell screens for FD=1 systems with known k:
#   A Vb  3.5 — mean of GREAE HYPAI (3.705), PRIA FREE (3.295), HYPIO PRI (3.552)
#   A Vab 3.4 — BLEAE AUWSY (3.356, single point)
#   F Vb  3.0 — median of 13 FD systems (range 2.4–4.7; F VI k calibrated at 6.0 so excluded)
#   K Va  2.0 — EACTAILD VR-I C23-3 (1.94); PREAE CHROA AS-P C7-3 gives 2.99 (scatter: 2–3×)
#   K Vab 2.0 — BLEAE BRIAE MM-C C13-3 (1.97)
STAR_FD_MULT: dict[str, float] = {
    "a_vb":  3.5,
    "a_vab": 3.4,
    "f_vb":  3.0,
    "k_va":  2.0,   # EACTAILD VR-I C23-3 K Va FD: 31,735 / (9,325 × 1.753) = 1.94; PREAE gives 2.99 (higher outlier)
    "k_vab": 2.0,   # BLEAE BRIAE MM-C C13-3 K Vab FD: 294,070 / (81,019 × 1.846) = 1.97
}
_FIRST_MAPPED_MULT          = 3.3   # replaces the not-first mapping multiplier
_MAPPED_MULT                = 1.5   # mapped but not first-mapped
_MASS_EXP                   = 0.199977
_MASS_SCALE                 = 3 / 5.3   # ≈ 0.5660


def body_scan_value(
    planet_class: str | None,
    mass_em: float | None,
    terraform_state: str | None,
    first_discovered: bool,
    was_mapped: bool,
    first_mapped: bool,
) -> int:
    """
    Estimate the credit value of one body's exploration data.

    Returns 0 for bodies with no planet class or mass (e.g. pure star records).
    """
    if not planet_class or mass_em is None or mass_em <= 0:
        return 0

    key = planet_class.lower()
    key = re.sub(r"^sudarsky\s+", "", key)   # DB stores "Sudarsky class I gas giant"; key is "class i gas giant"
    k = BODY_BASE_K.get(key, 720)

    is_terraformable = (key in _ALWAYS_TERRA) or bool(
        terraform_state and terraform_state.lower() not in ("", "not terraformable")
    )
    if is_terraformable:
        k += TERRA_BONUS_K.get(key, 0)

    scan_value = k * (1 + _MASS_SCALE * (mass_em ** _MASS_EXP))

    if was_mapped:
        if first_discovered:
            scan_value *= _FIRST_DISCOVERED_MULT
        if first_mapped:
            scan_value *= _FIRST_MAPPED_MULT
        else:
            scan_value *= _MAPPED_MULT

    return max(500, round(scan_value))


def star_scan_value(
    star_type: str | None,
    stellar_mass: float | None,
    first_discovered: bool,
    luminosity: str | None = None,
    is_primary: bool = True,
) -> int:
    """
    Estimate the credit value of one star's exploration data.

    star_type      — spectral class from the journal StarType field (e.g. "DC", "M", "N")
    stellar_mass   — stellar mass in solar masses (journal StellarMass field)
    first_discovered — True if this was the first discovery of this body
    luminosity     — luminosity class from the journal Luminosity field (e.g. "Vb", "VI")
    is_primary     — True for the main star of a system (body_id=1); False for companions

    Formula (Odyssey era, calibrated against in-game sell values):
        primary:   k × (1 + stellar_mass^0.5) × (fd_mult if FD else 1.0)
        companion: k × 0.01 × (1 + stellar_mass^0.5) × (2.0 if FD else 1.0)
    k lookup: tries "{star_type}_{luminosity}" first, falls back to star_type alone.
    fd_mult lookup (primaries): STAR_FD_MULT[compound_key] → STAR_FD_MULT[type] → 6.0.
    """
    if not star_type or stellar_mass is None or stellar_mass <= 0:
        return 0

    base_key = star_type.lower()
    lum_norm = re.sub(r"[\s\-]", "", luminosity).lower() if luminosity else None
    key = f"{base_key}_{lum_norm}" if lum_norm and f"{base_key}_{lum_norm}" in STAR_BASE_K else base_key
    k = STAR_BASE_K.get(key, 1_100)

    if not is_primary:
        k *= _COMPANION_K_FRACTION

    scan_value = k * (1 + stellar_mass ** 0.5)

    if is_primary:
        fd_mult = STAR_FD_MULT.get(key, STAR_FD_MULT.get(base_key, _STAR_FIRST_DISCOVERED_MULT))
    else:
        fd_mult = _FIRST_DISCOVERED_MULT
    if first_discovered:
        scan_value *= fd_mult

    return max(500, round(scan_value))


# ---------------------------------------------------------------------------
# Exobiology species values
# ---------------------------------------------------------------------------

# Base credit value per species (before first-log or Antal bonuses).
# Source: Vista Genomics database / ED community wiki, current as of 2025.
SPECIES_VALUES: dict[str, int] = {
    "Aleoida Arcus":          7_252_500,
    "Aleoida Coronamus":      6_284_600,
    "Aleoida Gravis":        12_934_900,
    "Aleoida Laminiae":       3_385_200,
    "Aleoida Spica":          3_385_200,
    "Amphora Plant":          1_628_800,
    "Anemone":                1_499_900,
    "Bacterium Acies":        1_000_000,
    "Bacterium Alcyoneum":    1_658_500,
    "Bacterium Aurasus":      1_000_000,
    "Bacterium Bullaris":     1_152_500,
    "Bacterium Cerbrus":      1_689_800,
    "Bacterium Informem":     8_418_000,
    "Bacterium Nebulus":      5_289_900,
    "Bacterium Omentum":      4_638_900,
    "Bacterium Scopulum":     4_934_500,
    "Bacterium Tela":         1_949_000,
    "Bacterium Verrata":      3_897_000,
    "Bacterium Vesicula":     1_000_000,
    "Bacterium Volu":         7_774_700,
    "Bark Mounds":            1_471_900,
    "Brain Tree":             1_593_700,
    "Cactoida Cortexum":      3_667_600,
    "Cactoida Lapis":         2_483_600,
    "Cactoida Peperatis":     2_483_600,
    "Cactoida Pullulanta":    3_667_600,
    "Cactoida Vermis":       16_202_800,
    "Clypeus Lacrimam":       8_418_000,
    "Clypeus Margaritus":    11_873_200,
    "Clypeus Speculumi":     16_202_800,
    "Concha Aureolas":        7_774_700,
    "Concha Biconcavis":     19_010_800,
    "Concha Labiata":         2_352_400,
    "Concha Renibus":         4_572_400,
    "Coral Root":             1_924_600,
    "Coral Tree":             1_896_800,
    "Crystalline Shards":     1_628_800,
    "Electricae Pluma":       6_284_600,
    "Electricae Radialem":    6_284_600,
    "Fonticulua Campestris":  1_000_000,
    "Fonticulua Digitos":     1_804_100,
    "Fonticulua Fluctus":    20_000_000,
    "Fonticulua Lapida":      3_111_000,
    "Fonticulua Segmentatus":19_010_800,
    "Fonticulua Upupam":      5_727_600,
    "Frutexa Acus":           7_774_700,
    "Frutexa Collum":         1_639_800,
    "Frutexa Fera":           1_632_500,
    "Frutexa Flabellum":      1_808_900,
    "Frutexa Flammasis":     10_326_000,
    "Frutexa Metallicum":     1_632_500,
    "Frutexa Sponsae":        5_988_000,
    "Fumerola Aquatis":       6_284_600,
    "Fumerola Carbosis":      6_284_600,
    "Fumerola Extremus":     16_202_800,
    "Fumerola Nitris":        7_500_900,
    "Fungoida Bullarum":      3_703_200,
    "Fungoida Gelata":        3_330_300,
    "Fungoida Setisis":       1_670_100,
    "Fungoida Stabitis":      2_680_300,
    "Osseus Cornibus":        1_483_000,
    "Osseus Discus":         12_934_900,
    "Osseus Fractus":         4_027_800,
    "Osseus Pellebantus":     9_739_000,
    "Osseus Pumice":          3_156_300,
    "Osseus Spiralis":        2_404_700,
    "Recepta Conditivus":    14_313_700,
    "Recepta Deltahedronix": 16_202_800,
    "Radicoida Unica":          119_037,
    "Recepta Umbrux":        12_934_900,
    "Sinuous Tubers":         1_514_500,
    "Thargoid Barnacle Matrix":   2_313_500,
    "Thargoid Mega Barnacles":    2_313_500,
    "Minor Thargoid Spire":       2_247_100,
    "Major Thargoid Spire":       2_247_100,
    "Primary Thargoid Spire":     2_247_100,
    "Thargoid Spire":             2_247_100,
    "Thargoid Spires":            2_247_100,
    "Stratum Araneamus":      2_448_900,
    "Stratum Cucumisis":     16_202_800,
    "Stratum Excutitus":      2_448_900,
    "Stratum Frigus":         2_637_500,
    "Stratum Laminamus":      2_788_300,
    "Stratum Limaxus":        1_362_000,
    "Stratum Paleas":         1_362_000,
    "Stratum Tectonicas":    19_010_800,
    "Tubus Cavas":           11_873_200,
    "Tubus Compagibus":       7_774_700,
    "Tubus Conifer":          2_415_500,
    "Tubus Rosarium":         2_637_500,
    "Tubus Sororibus":        5_727_600,
    "Tussock Albata":         3_252_500,
    "Tussock Capillum":       7_025_800,
    "Tussock Caputus":        3_472_400,
    "Tussock Catena":         1_766_600,
    "Tussock Cultro":         1_766_600,
    "Tussock Divisa":         1_766_600,
    "Tussock Ignis":          1_849_000,
    "Tussock Pennata":        5_853_800,
    "Tussock Pennatis":       1_000_000,
    "Tussock Propagito":      1_000_000,
    "Tussock Serrati":        4_447_100,
    "Tussock Stigmasis":     19_010_800,
    "Tussock Triticum":       7_774_700,
    "Tussock Ventusa":        3_227_700,
    "Tussock Virgam":        14_313_700,
}

# Pranav Antal maximum exobiology bonus (rank 94+).  Kept for legacy reference.
ANTAL_EXOBIO_BONUS = 0.30

# ---------------------------------------------------------------------------
# Powerplay 2.0 merit-rank bonus tables
# ---------------------------------------------------------------------------

# Merit totals required to reach each rank.
# Rank 1-4 have irregular thresholds; rank 5+ follow 15000 + (rank-5)*8000.
def merit_rank(total_merits: int) -> int:
    """Convert total accumulated merits to Powerplay 2.0 rank (1-100)."""
    if total_merits < 2_000:  return 1
    if total_merits < 5_000:  return 2
    if total_merits < 9_000:  return 3
    if total_merits < 15_000: return 4
    return min(100, (total_merits + 25_000) // 8_000)


# (min_rank, bonus_fraction) — checked highest-first
_ANTAL_EXOBIO_STEPS: list[tuple[int, float]] = [
    (94, 0.30), (78, 0.25), (52, 0.20), (42, 0.15), (24, 0.10),
]

_LYR_EXPL_STEPS: list[tuple[int, float]] = [
    (86, 1.00), (73, 0.90), (67, 0.80), (55, 0.70), (48, 0.60),
    (32, 0.50), (22, 0.40), (14, 0.30), (5, 0.20),
]


def antal_exobio_bonus(total_merits: int) -> float:
    """Exobiology sell-bonus fraction for Pranav Antal at the given merit total."""
    rank = merit_rank(total_merits)
    for threshold, bonus in _ANTAL_EXOBIO_STEPS:
        if rank >= threshold:
            return bonus
    return 0.0


def lyr_expl_bonus(total_merits: int) -> float:
    """Cartographic/exploration sell-bonus fraction for Li Yong-Rui at the given merit total."""
    rank = merit_rank(total_merits)
    for threshold, bonus in _LYR_EXPL_STEPS:
        if rank >= threshold:
            return bonus
    return 0.0


def organic_value(
    species_localised: str | None,
    is_first_log: bool = False,
    antal_bonus: bool = False,
) -> int:
    """
    Estimate credit value for one completed organic scan.

    species_localised  — human-readable species name, e.g. "Stratum Tectonicas"
    is_first_log       — True if this was the first scan of this species on this body
    antal_bonus        — True if sold in Antal-controlled space
    """
    if not species_localised:
        return 0

    base = SPECIES_VALUES.get(species_localised.strip(), 0)
    if base == 0:
        lower = species_localised.strip().lower()
        for k, v in SPECIES_VALUES.items():
            if k.lower() == lower:
                base = v
                break
    if base == 0:
        # Suffix fallback: "Viride Brain Tree" → "Brain Tree", "Roseum Bioluminescent Anemone" → "Anemone", etc.
        lower = species_localised.strip().lower()
        for k, v in SPECIES_VALUES.items():
            if lower.endswith(k.lower()):
                base = v
                break

    if base == 0:
        return 0

    total = base * (5 if is_first_log else 1)
    if antal_bonus:
        total = round(total * (1 + ANTAL_EXOBIO_BONUS))
    return total
