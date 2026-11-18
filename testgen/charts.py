"""Which buildings KARR AI's DBC Method 1 charts have a lift count for.

KARR AI looks M1 passenger lifts up in charts (apps/api/worker/building_types).
A building outside every chart cell gets "not computable" in its report. The
ranges below were read off those tables by sweeping every floor count and
population through each config's `compute_lift_count` (2026-11-17); keep them
in step if KARR AI's charts change. Retail, Schools and Universities use
formulas with no upper limit, so they always get an answer.
"""

from __future__ import annotations

from .assets import CAR_OCCUPANCY, asset_for, key_occupancy, unit_occupancy

# (first occupied floor, last occupied floor, lowest, highest) population.
_RESIDENTIAL = [(1, 5, 0, 500), (6, 10, 0, 800), (11, 30, 0, 1200), (31, 35, 201, 1200)]
_HOTEL_APARTMENTS = [(1, 10, 0, 700), (11, 15, 0, 1000), (16, 25, 201, 1000), (26, 30, 301, 1000)]
_HOTEL = {
    "1-2": [(1, 5, 0, 400), (6, 10, 0, 900), (11, 15, 201, 900), (16, 25, 301, 1000), (26, 30, 501, 1000)],
    "3": [(1, 5, 0, 400), (6, 10, 0, 800), (11, 15, 201, 800), (16, 20, 301, 1000), (21, 30, 401, 1000)],
    "4-5": [(1, 5, 0, 400), (6, 10, 0, 900), (11, 15, 201, 900), (16, 25, 401, 900), (26, 30, 501, 900)],
}
_CAR_PARKING = [(1, 1, 0, 300), (2, 2, 0, 400), (3, 3, 0, 500), (4, 4, 0, 600), (5, 5, 0, 700),
                (6, 6, 201, 1000), (7, 7, 301, 1000), (8, 9, 401, 1000)]
# Office looks up the total office floor area (m2), not people.
_OFFICE = [(1, 2, 0, 5000), (3, 4, 0, 10000), (5, 6, 0, 15000), (7, 8, 2501, 20000),
           (9, 10, 2501, 25000), (11, 12, 5001, 25000), (13, 20, 7501, 25000)]
# Most boarding floors each chart has a column for, by occupied floors.
_MAX_BOARDING = {
    "residential": [(1, 5, 3), (6, 10, 4), (11, 35, 6)],
    "hotel_apartments": [(1, 30, 5)],
    "office": [(1, 4, 4), (5, 20, 8)],
}
# KARR AI splits the population across cores (x 0.6 per core) for these.
_PER_CORE_SPLIT = {"residential", "car_parking"}
MULTI_CORE_FACTOR = 0.6
# People per m2 KARR AI gives hotel public floors (meeting rooms are the densest).
PUBLIC_AREA_M2_PER_PERSON = 1.2


def _band(table, floors: int):
    return next((row[2:] for row in table if row[0] <= floors <= row[1]), None)


def chart_range(asset_key: str, occupied: int, star: str | None = None) -> tuple[int, int] | None:
    """(low, high) the M1 chart covers for this many occupied floors.

    None when the chart has no row for that floor count, or the asset has no chart.
    """
    table = {"residential": _RESIDENTIAL, "hotel_apartments": _HOTEL_APARTMENTS,
             "car_parking": _CAR_PARKING, "office": _OFFICE}.get(asset_key)
    if asset_key == "hotel":
        table = _HOTEL[star or "4-5"]
    if table is None:
        return None
    return _band(table, occupied)


def has_chart(asset_key: str) -> bool:
    return asset_key in ("residential", "hotel_apartments", "hotel", "car_parking", "office")


def max_boarding(asset_key: str, occupied: int) -> int | None:
    table = _MAX_BOARDING.get(asset_key)
    return _band(table, occupied)[0] if table and _band(table, occupied) else None


def chart_value(spec: dict) -> tuple[float, str]:
    """What KARR AI looks up in the M1 chart for this spec, and its unit."""
    asset = asset_for(spec["asset"])
    floors = [f for f in spec["floors"] if f.get("occupied")]
    b = spec["building"]
    if asset.key == "office":
        return float(sum(f.get("area_m2") or 0 for f in floors)), "m² office area"
    if asset.key == "car_parking":
        rate = CAR_OCCUPANCY.get(spec["project_info"].get("car_parking_facility_type"), 1.5)
        value = sum(f.get("cars") or 0 for f in floors) * rate
    elif asset.key == "hotel":
        rate = key_occupancy(spec["project_info"].get("hotel_star_rating") or "4-5", b.get("has_operator"))
        keys = sum(sum((f.get("units") or {}).values()) for f in floors)
        public = sum((f.get("area_m2") or 0) for f in spec["floors"] if f.get("amenity"))
        value = keys * rate + public / PUBLIC_AREA_M2_PER_PERSON
    else:
        rates = unit_occupancy(asset.key, b.get("has_operator"))
        value = sum(rates.get(t, 2.0) * n for f in floors for t, n in (f.get("units") or {}).items())
    if asset.key in _PER_CORE_SPLIT and (spec["vt_criteria"].get("core_count") or 1) > 1:
        return round(value * MULTI_CORE_FACTOR), "people per core"
    return round(value), "people"


def check(spec: dict) -> list[str]:
    """Reasons KARR AI's M1 chart would give no lift count (empty = it will)."""
    asset = asset_for(spec["asset"])
    if spec["model"] != "DBC-M1" or not has_chart(asset.key):
        return []
    occupied = sum(1 for f in spec["floors"] if f.get("occupied"))
    star = spec["project_info"].get("hotel_star_rating")
    value, unit = chart_value(spec)
    problems = []
    band = chart_range(asset.key, occupied, star)
    if band is None:
        problems.append(f"No M1 chart row for {occupied} occupied floors")
    elif not band[0] <= value <= band[1]:
        problems.append(f"{value:,.0f} {unit}; the M1 chart covers {band[0]:,}–{band[1]:,} at {occupied} floors")
    boarding = sum(1 for f in spec["floors"] if f.get("boarding"))
    most = max_boarding(asset.key, occupied)
    if most is not None and boarding > most:
        problems.append(f"{boarding} boarding floors; the M1 chart allows {most} at {occupied} floors")
    return problems
