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

# Multipliers
_FIRST_DISCOVERED_MULT = 2.0
_FIRST_MAPPED_MULT     = 3.3   # replaces the not-first mapping multiplier
_MAPPED_MULT           = 1.5   # mapped but not first-mapped
_MASS_EXP              = 0.199977
_MASS_SCALE            = 3 / 5.3   # ≈ 0.5660


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
    k = BODY_BASE_K.get(key, 720)

    is_terraformable = (key in _ALWAYS_TERRA) or bool(
        terraform_state and terraform_state.lower() not in ("", "not terraformable")
    )
    if is_terraformable:
        k += TERRA_BONUS_K.get(key, 0)

    scan_value = k * (1 + _MASS_SCALE * (mass_em ** _MASS_EXP))

    if first_discovered:
        scan_value *= _FIRST_DISCOVERED_MULT

    if was_mapped:
        if first_mapped:
            scan_value *= _FIRST_MAPPED_MULT
        else:
            scan_value *= _MAPPED_MULT

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

# Pranav Antal power bonus on exobiology sales (applied when selling in Antal space).
# Base pledge rank: +30%.  Note: does NOT apply to cartography data.
ANTAL_EXOBIO_BONUS = 0.30


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
