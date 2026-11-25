"""Per-asset rules mirrored from KARR AI (apps/api/worker/building_types).

Only the facts the generator needs to produce valid inputs live here: the
classification string, the M1 height threshold, the acceptable waiting time
for simulations, default capacities, the speed divisor and which extra
documents each asset needs. Keep these in step with KARR AI when it changes.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    key: str                     # short id used in file names
    classification: str          # KARR AI project_classification (exact)
    m1_threshold: int            # max occupied floors on M1
    awt_s: int                   # acceptable average waiting time (s)
    passenger_kg: int
    fire_kg: int
    speed_divisor: float         # passenger travel (m) / divisor = min speed
    supports_m2: bool = True
    single_sim: bool = False     # one guest simulation PDF instead of morning + evening
    entrance_bias_sheet: bool = False  # M2 workbook carries an Entrance Bias sheet
    hotel_like: bool = False     # operator / amenities toggles exist
    # A simulation covers one core and KARR AI multiplies its lifts by the core
    # count (BuildingTypeConfig.apply_core_multiplier); otherwise it covers the
    # whole building and KARR AI shares its lifts out over the cores
    sim_per_core: bool = False


ASSETS: dict[str, Asset] = {
    a.key: a
    for a in [
        Asset("residential", "Residential Apartments", 35, 40, 1350, 1600, 40),
        Asset("office", "Office Buildings", 20, 35, 1600, 1600, 30),
        Asset("hotel", "Hotels", 30, 30, 1600, 2000, 20,
              single_sim=True, entrance_bias_sheet=True, hotel_like=True),
        Asset("hotel_apartments", "Hotel Apartments", 30, 35, 1350, 1600, 25,
              single_sim=True, entrance_bias_sheet=True, hotel_like=True),
        Asset("car_parking", "Car Parking", 9, 40, 1600, 1600, 30,
              single_sim=True, entrance_bias_sheet=True, sim_per_core=True),
        Asset("retail", "Retail/Shopping Centres and Malls", 10, 40, 2000, 2000, 25,
              supports_m2=False),
        Asset("schools", "Schools", 5, 40, 1275, 1275, 25, sim_per_core=True),
        Asset("universities", "Universities", 5, 40, 1600, 2000, 25, sim_per_core=True),
    ]
}

BY_CLASSIFICATION = {a.classification: a for a in ASSETS.values()}

# Hotel star tiers change the acceptable waiting time, room occupancy and the
# passenger speed divisor (KARR AI hotel.py PASSENGER_SPEED_DIVISORS).
HOTEL_STAR_AWT = {"1-2": 40, "3": 35, "4-5": 30}
HOTEL_STAR_SPEED_DIVISOR = {"1-2": 35, "3": 25, "4-5": 20}
HOTEL_STARS = ["1-2", "3", "4-5"]


def speed_divisor(asset: Asset, stars: str | None = None) -> float:
    """Passenger travel (m) / this = the minimum speed; hotels go by star tier."""
    if asset.key == "hotel" and stars in HOTEL_STAR_SPEED_DIVISOR:
        return HOTEL_STAR_SPEED_DIVISOR[stars]
    return asset.speed_divisor


def default_capacities(asset: Asset, stars: str | None = None) -> tuple[int, int]:
    """(passenger, fire/service) kg the KARR AI setup page fills in; hotels go by star tier."""
    if asset.key == "hotel":
        return (1350 if stars == "1-2" else 1600), (2000 if stars == "4-5" else 1600)
    return asset.passenger_kg, asset.fire_kg

# Speeds KARR AI's lift configuration chart covers, by machine type.
MRL_SPEEDS = [1.0, 1.75]
MRA_SPEEDS = [2.5, 3.0, 3.5, 4.0, 5.0, 6.0]
# Speeds KARR AI snaps a calculated speed to (BuildingTypeConfig.get_valid_speeds).
VALID_SPEEDS = [1.0, 1.75, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]

# People per unit / key / car, as KARR AI counts them:
# residential = legacy_worker `_header_to_base_factor`, hotel apartments =
# HotelApartmentsConfig.get_occupancy_factor (DBC D.18), hotels = per key by
# star (DBC D.12), parking = per car (DBC D.27).
HOTEL_APARTMENT_UNIT_TYPES = ["Studio", "1BR", "2BR", "3BR", "4BR"]
RESIDENTIAL_UNIT_TYPES = ["Studio", "1BR", "2BR", "3BR", "4BR", "5BR", "6BR",
                          "3BR + Maid", "4BR + Maid", "4BR Duplex", "5BR Duplex"]


def residential_unit_occupancy(name: str) -> float:
    """People per unit, read off the column name the way KARR AI's Residential reader does.

    DBC Table D.5: studio 1.5, 1BR 1.8, 2BR 3, 3BR 4, 4BR 5, then 1 more per bedroom; a
    duplex / triplex or maid's room adds 1.
    """
    s = name.lower()
    bedrooms = re.search(r"(\d+)\s*br\b", s)
    if "studio" in s:
        base = 1.5
    elif bedrooms:
        n = int(bedrooms.group(1))
        base = n + 1.0 if n >= 4 else {1: 1.8, 2: 3.0, 3: 4.0}[n]
    else:
        raise ValueError(f"No occupancy rate for {name!r}")
    duplex = bool(re.search(r"\bduplex\b|\btriplex\b", s))
    maid = bool(re.search(r"\+\s*m\b|\bmaid\b|\bhk\b|\bhousekeeper\b", s))
    return base + duplex + maid


RESIDENTIAL_UNIT_OCCUPANCY = {t: residential_unit_occupancy(t) for t in RESIDENTIAL_UNIT_TYPES}
HOTEL_APARTMENT_UNIT_OCCUPANCY = {"Studio": 1.0, "1BR": 1.5, "2BR": 2.5, "3BR": 3.5, "4BR": 4.5}
HOTEL_KEY_OCCUPANCY = {"1-2": 1.5, "3": 1.5, "4-5": 1.8}
# Schools and universities count a parking basement's cars x 1.5 as people
# (KARR AI universities.py BASEMENT_OCCUPANCY_PER_CAR; schools the same)
SCHOOL_PARKING_PER_CAR = 1.5
# Retail: basement cars x 3 (KARR AI retail.py BASEMENT_OCCUPANCY_PER_CAR)
RETAIL_PARKING_PER_CAR = 3.0
CAR_OCCUPANCY = {"Independent": 1.5, "Retail/Mall Attached": 3.0}
# People per parked car in KARR AI's Entrance Bias sheet (unitmix_processor_v2.write_entrance_bias_sheet_web).
ENTRANCE_PEOPLE_PER_CAR = 1.5

# Occupancy rates written into the Operator Profile sheet. KARR AI rejects a
# profile without a "Default Occupancy" line.
OPERATOR_RATES_HOTEL = {"Default Occupancy": 1.75, "1BR": 1.75, "2BR": 2.5, "3BR": 3.5, "Penthouse": 5}
OPERATOR_RATES_APARTMENTS = {"Default Occupancy": 1.75, "Studio": 1.0, "1BR": 1.75, "2BR": 2.5, "3BR": 3.5}


# Car parks with escalators: (escalator share, lift share) of each level's people,
# by floors travelled above ground (DBC Table 2.13, worker/escalators/constants.py).
ESCALATOR_SPLIT = {1: (0.90, 0.10), 2: (0.75, 0.25), 3: (0.50, 0.50), 4: (0.25, 0.75), 5: (0.10, 0.90)}

# Retail moving walks: a trolley-heavy use on an above-ground floor, with
# basements below it (worker/building_types/retail.py `_MW_TRIGGER_RE`).
TROLLEY_USE_RE = re.compile(
    r"super\s*market|hyper\s*market|department\s*store|big[\s\-]?box|warehouse\s*club|"
    r"cash[\s\-]?and[\s\-]?carry|home\s*cent(?:re|er)|home\s*depot|furniture\s*(?:store|mart|gallery)?|"
    r"diy|grocer(?:y|ies)|food\s*hall",
    re.IGNORECASE,
)


def unit_occupancy(asset_key: str, has_operator: bool = False) -> dict[str, float]:
    """People per unit type. With an operator the higher of DBC and operator rates is used."""
    if asset_key != "hotel_apartments":
        return dict(RESIDENTIAL_UNIT_OCCUPANCY)
    rates = dict(HOTEL_APARTMENT_UNIT_OCCUPANCY)
    if has_operator:
        for t in rates:
            rates[t] = max(rates[t], OPERATOR_RATES_APARTMENTS.get(t, 0))
    return rates


def key_occupancy(star: str, has_operator: bool = False) -> float:
    """People per hotel key; an operator's default (1.75) can raise it."""
    rate = HOTEL_KEY_OCCUPANCY[star]
    return max(rate, OPERATOR_RATES_HOTEL["Default Occupancy"]) if has_operator else rate


def asset_for(classification: str) -> Asset:
    try:
        return BY_CLASSIFICATION[classification]
    except KeyError:
        raise ValueError(f"Unknown classification: {classification!r}") from None


def height_category(asset: Asset, model: str) -> str:
    return f"<{asset.m1_threshold}" if model == "DBC-M1" else f">{asset.m1_threshold}"
