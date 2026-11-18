"""Build a fake floor stack for each asset.

Every builder returns floors ordered top to bottom (the order KARR AI's
sample workbooks use). A floor is a plain dict:

    name, height_m, use, occupied, boarding      always
    units {type: count}                           residential, hotel apartments, hotels (King/Twin/Suite)
    area_m2                                       office, retail, hotel public floors
    cars                                          parking floors
    classrooms, students_per_classroom, staff     schools / universities
    amenity                                       hotel amenities stacking (Y/N)

Options (all optional; a missing option is picked at random from `SIZING`):

    occupied_floors          floors KARR AI counts as occupied (Y in Lifts Stacking Mix)
    basements                parking basements below ground
    typical_floor_height_m, ground_floor_height_m
    unit_types               residential / hotel apartments, e.g. ["Studio", "1BR"]
    units_per_floor          residential / hotel apartment units, hotel keys
    floor_area_m2            office / retail area per floor
    cars_per_floor           car parking spaces per level
    classrooms_per_floor, students_per_classroom   schools / universities
    amenity_floor            residential: a residents' amenities level
    mezzanine                office: a mezzanine above ground
    moving_walks             retail: a trolley use (hypermarket) on the ground floor, or none

An auto-sized M1 building is kept inside KARR AI's M1 chart for its floor
count (charts.py), so it always gets a lift count; M2 goes above the M1 limit.
The auto value is always drawn, then replaced by the option (`choose`), so setting one
option leaves the rest of the project as it was.
"""

from __future__ import annotations

import random

from .assets import CAR_OCCUPANCY, TROLLEY_USE_RE, UNIT_TYPES, Asset, key_occupancy, unit_occupancy
from .charts import PUBLIC_AREA_M2_PER_PERSON, chart_range, max_boarding

# Auto ranges per asset. occupied_m1 / occupied_m2 are picked when no floor
# count is given; occupied_min / occupied_max bound what a tester may choose.
SIZING: dict[str, dict] = {
    "residential": dict(occupied_m1=(11, 28), occupied_m2=(37, 50), occupied_min=1, occupied_max=90,
                        typical_h=(3.3, 3.6), ground_h=(4.5, 6.0), basements=(1, 3),
                        people_per_floor_m1=(22, 45), people_per_floor_m2=(35, 55)),
    "office": dict(occupied_m1=(6, 17), occupied_m2=(22, 38), occupied_min=1, occupied_max=70,
                   typical_h=(3.9, 4.3), ground_h=(4.5, 6.0), basements=(1, 3),
                   area_m1=(700, 1300), area_m2=(1100, 1800)),
    "hotel": dict(occupied_m1=(11, 15), occupied_m2=(32, 42), occupied_min=1, occupied_max=70,
                  typical_h=(3.6, 3.9), ground_h=(4.5, 6.0), basements=(1, 2),
                  people_per_floor_m1=(18, 30), people_per_floor_m2=(20, 30)),
    "hotel_apartments": dict(occupied_m1=(11, 15), occupied_m2=(32, 42), occupied_min=1, occupied_max=70,
                             typical_h=(3.6, 3.9), ground_h=(4.5, 6.0), basements=(1, 2),
                             people_per_floor_m1=(18, 30), people_per_floor_m2=(18, 28)),
    "car_parking": dict(occupied_m1=(3, 7), occupied_m2=(10, 13), occupied_min=1, occupied_max=20,
                        typical_h=(3.2, 3.6), ground_h=(4.5, 5.0), basements=None,
                        cars_m1=(60, 160), cars_m2=(120, 220)),
    "retail": dict(occupied_m1=(3, 5), occupied_m2=None, occupied_min=2, occupied_max=10,
                   typical_h=(5.0, 6.0), ground_h=(5.5, 6.5), basements=(1, 2),
                   area_m1=(4000, 9000)),
    "schools": dict(occupied_m1=(2, 4), occupied_m2=(6, 8), occupied_min=1, occupied_max=12,
                    typical_h=(4.2, 4.6), ground_h=(4.8, 5.5), basements=(0, 0),
                    classrooms=(8, 14), students=(20, 28)),
    "universities": dict(occupied_m1=(2, 4), occupied_m2=(6, 8), occupied_min=1, occupied_max=12,
                         typical_h=(4.2, 4.6), ground_h=(4.8, 5.5), basements=(0, 1),
                         classrooms=(8, 14), students=(30, 45)),
}


def occupied_limits(asset: Asset, model: str) -> tuple[int, int]:
    """Smallest and largest occupied-floor count a tester may pick for this method."""
    s = SIZING[asset.key]
    if model == "DBC-M1":
        return s["occupied_min"], asset.m1_threshold
    return asset.m1_threshold + 1, s["occupied_max"]


def _round_h(value: float) -> float:
    return round(value * 20) / 20  # 0.05 m steps


def choose(opts: dict, key: str, auto):
    """The tester's value for `key`, else the auto value (already drawn)."""
    value = opts.get(key)
    return auto if value is None else value


def _occupied(rng: random.Random, asset: Asset, model: str, opts: dict) -> int:
    s = SIZING[asset.key]
    lo, hi = s["occupied_m1"] if model == "DBC-M1" else s["occupied_m2"]
    return int(choose(opts, "occupied_floors", rng.randint(lo, hi)))


def _typical_h(rng: random.Random, asset: Asset, opts: dict) -> float:
    return float(choose(opts, "typical_floor_height_m", _round_h(rng.uniform(*SIZING[asset.key]["typical_h"]))))


def _ground(rng: random.Random, asset: Asset, opts: dict, use: str, name: str = "GF") -> dict:
    h = float(choose(opts, "ground_floor_height_m", _round_h(rng.uniform(*SIZING[asset.key]["ground_h"]))))
    return {"name": name, "height_m": h, "use": use, "occupied": False, "boarding": True}


def _basements(rng: random.Random, asset: Asset, opts: dict, cars_range: tuple[int, int],
               name=lambda i: f"B{i}", use: str = "Parking", most: int | None = None) -> list[dict]:
    """Parking basements; an auto count stays at or under `most` (the chart's boarding limit)."""
    lo, hi = SIZING[asset.key]["basements"]
    auto = rng.randint(lo, hi)
    count = int(choose(opts, "basements", auto if most is None else max(0, min(auto, most))))
    return [{"name": name(i), "height_m": _round_h(rng.uniform(3.0, 3.6)), "use": use,
             "cars": rng.randint(*cars_range), "occupied": False, "boarding": True}
            for i in range(1, count + 1)]


def _roof(rng: random.Random, name: str = "Roof") -> dict:
    return {"name": name, "height_m": _round_h(rng.uniform(3.5, 4.5)),
            "use": "Roof / MEP plant", "occupied": False, "boarding": False}


def _basement_room(asset: Asset, model: str, occ: int, other_boarding: int) -> int | None:
    """Most basements an M1 chart with a boarding-floor column still covers."""
    most = max_boarding(asset.key, occ) if model == "DBC-M1" else None
    return None if most is None else most - other_boarding


def _fit(want: float, band: tuple[int, int] | None, reserve: float = 0.0) -> float:
    """Keep an auto-sized total inside an M1 chart band, with a margin for rounding."""
    if band is None:
        return want
    lo, hi = band
    low_ok = (lo * 1.1 + 10 if lo else 0) - reserve
    high_ok = hi * 0.88 - reserve
    if low_ok > high_ok:
        return (lo + hi) / 2 - reserve
    return min(max(want, low_ok), high_ok)


def _people_target(rng: random.Random, asset: Asset, model: str, occ: int,
                   band: tuple[int, int] | None, reserve: float = 0.0) -> float:
    s = SIZING[asset.key]
    per_floor = s["people_per_floor_m1"] if model == "DBC-M1" else s["people_per_floor_m2"]
    want = occ * rng.uniform(*per_floor)
    return _fit(want, band if model == "DBC-M1" else None, reserve)


# ---------------------------------------------------------------- residential

_RESI_MIXES = [
    ["Studio", "1BR", "2BR"],
    ["1BR", "2BR", "3BR"],
    ["Studio", "1BR", "2BR", "3BR"],
    ["1BR", "2BR", "3BR", "4BR"],
]


def _split(rng: random.Random, types: list[str], total: int) -> dict[str, int]:
    """Spread `total` units over the types with random weights (largest remainder)."""
    weights = [rng.uniform(0.5, 1.5) for _ in types]
    raw = [total * w / sum(weights) for w in weights]
    counts = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True):
        if sum(counts) >= total:
            break
        counts[i] += 1
    return dict(zip(types, counts))


def _unit_plan(rng: random.Random, types: list[str], rates: dict[str, float],
               people_per_floor: float, units: int | None = None) -> dict[str, int]:
    """A per-floor unit mix: `units` units, or as many as house about `people_per_floor`."""
    if units is None:
        avg = sum(rates.get(t, 2.0) for t in types) / len(types)
        units = max(2, round(people_per_floor / avg))
    return _split(rng, types, int(units))


def _unit_types(rng: random.Random, opts: dict, choices: list[list[str]]) -> list[str]:
    auto = rng.choice(choices)
    picked = [t for t in UNIT_TYPES if t in (opts.get("unit_types") or [])]
    return picked or auto


def residential(rng: random.Random, asset: Asset, model: str, opts: dict) -> tuple[list[dict], list[str]]:
    occ = _occupied(rng, asset, model, opts)
    types = _unit_types(rng, opts, _RESI_MIXES)
    rates = unit_occupancy(asset.key)
    typical_h = _typical_h(rng, asset, opts)
    want_amenity = bool(choose(opts, "amenity_floor", rng.random() < 0.6))
    amenity_level = rng.randint(1, max(1, occ - 1)) if want_amenity and occ >= 2 else None

    target = _people_target(rng, asset, model, occ, chart_range(asset.key, occ))
    per_floor_units = opts.get("units_per_floor")
    lower = _unit_plan(rng, types, rates, target / occ * 1.03, per_floor_units)
    upper = _unit_plan(rng, types, rates, target / occ * 0.97, per_floor_units)

    # Levels bottom to top; an optional amenities level sits among them.
    kinds = ["res"] * occ
    if amenity_level:
        kinds.insert(amenity_level, "amenity")
    floors: list[dict] = [_roof(rng)]
    for idx in range(len(kinds) - 1, -1, -1):
        name = str(idx + 1)
        if kinds[idx] == "amenity":
            floors.append({"name": name, "height_m": _round_h(typical_h + 1.0),
                           "use": "Residents' amenities (gym, pool deck)",
                           "occupied": False, "boarding": False})
        else:
            plan = upper if idx > len(kinds) / 2 else lower
            floors.append({"name": name, "height_m": typical_h, "use": "Residential",
                           "units": dict(plan), "occupied": True, "boarding": False})

    floors.append(_ground(rng, asset, opts, "Main entrance lobby, retail"))
    floors += _basements(rng, asset, opts, (60, 160), most=_basement_room(asset, model, occ, 1))
    for f in floors:
        f.setdefault("units", {t: 0 for t in types})
    return floors, types


# --------------------------------------------------------------------- office

def office(rng: random.Random, asset: Asset, model: str, opts: dict) -> tuple[list[dict], list[str]]:
    occ = _occupied(rng, asset, model, opts)
    s = SIZING[asset.key]
    lo, hi = s["area_m1"] if model == "DBC-M1" else s["area_m2"]
    if model == "DBC-M1":  # keep the total office area inside the chart band
        band = chart_range(asset.key, occ)
        if band:
            lo = max(lo, int(band[0] * 1.05 / occ) + 1)
            hi = min(hi, int(band[1] * 0.95 / occ))
            lo = min(lo, hi)
    area = int(choose(opts, "floor_area_m2", rng.randint(lo, hi)))
    typical_h = _typical_h(rng, asset, opts)
    has_mezzanine = bool(choose(opts, "mezzanine", True))

    floors: list[dict] = [_roof(rng)]
    for level in range(occ, 0, -1):
        floors.append({"name": str(level), "height_m": typical_h, "use": "Offices",
                       "area_m2": area, "occupied": True, "boarding": False})
    mezz_h = _round_h(rng.uniform(4.0, 4.5))
    if has_mezzanine:
        floors.append({"name": "M", "height_m": mezz_h,
                       "use": "Mezzanine - MEP, amenities", "occupied": False, "boarding": False})
    floors.append(_ground(rng, asset, opts, "Main lobby, MEP services, retail", name="Ground"))
    floors += _basements(rng, asset, opts, (90, 220), name=lambda i: f"Basement {i}",
                         most=_basement_room(asset, model, occ, 1))
    return floors, []


# ---------------------------------------------------------------------- hotel

# Public areas stay small: KARR AI adds their people (area / 1.2-1.5) to the
# guest population for the M1 chart, which tops out at 700-1,000 people.
_PUBLIC_USES = [
    ("Public Meeting rooms", 90, 150),
    ("Public Restaurant", 110, 170),
    ("Public Ball room", 120, 180),
]
HOTEL_ROOM_TYPES = ["King", "Twin", "Suite"]


def _hotel_common(rng: random.Random, asset: Asset, model: str, opts: dict, rooms_for_floor) -> list[dict]:
    occ = _occupied(rng, asset, model, opts)
    has_amenities = bool(opts.get("has_amenities"))
    public = rng.sample(_PUBLIC_USES, k=2) if has_amenities else []
    areas = [rng.randint(lo, hi) for _, lo, hi in public]
    reserve = sum(areas) / PUBLIC_AREA_M2_PER_PERSON
    band = chart_range(asset.key, occ, opts.get("hotel_star_rating"))
    target = _people_target(rng, asset, model, occ, band, reserve=reserve if asset.key == "hotel" else 0.0)
    typical_h = _typical_h(rng, asset, opts)

    total_levels = occ + len(public)
    public_levels = set(rng.sample(range(1, min(8, total_levels)), k=len(public))) if public else set()
    floors: list[dict] = [{
        "name": str(total_levels + 1), "height_m": _round_h(rng.uniform(4.0, 4.5)),
        "use": "Guest Amenities (rooftop restaurant, pool, gym, spa)",
        "occupied": False, "boarding": True, "amenity": False, "rooftop": True,
    }]
    public_iter = iter(zip(public, areas))
    for level in range(total_levels, 0, -1):
        if level in public_levels:
            (use, _, _), area = next(public_iter)
            floors.append({"name": str(level), "height_m": typical_h, "use": use,
                           "area_m2": area, "occupied": False, "boarding": False, "amenity": True})
        else:
            floors.append({"name": str(level), "height_m": typical_h, "use": "Guest rooms",
                           "occupied": True, "boarding": False, "amenity": False,
                           **rooms_for_floor(target / occ)})
    floors.append(dict(_ground(rng, asset, opts, "Main lobby"), amenity=False))
    for b in _basements(rng, asset, opts, (40, 90), use="Valet parking",
                        most=_basement_room(asset, model, occ, 2)):  # ground + rooftop board too
        b["amenity"] = False
        floors.append(b)
    return floors


def _hotel_rooms(rng: random.Random, keys: int) -> dict[str, int]:
    suites = max(1, round(keys * rng.uniform(0.08, 0.15))) if keys > 1 else 0
    king = round((keys - suites) * rng.uniform(0.5, 0.7))
    return {"King": king, "Twin": keys - suites - king, "Suite": suites}


def hotel(rng: random.Random, asset: Asset, model: str, opts: dict) -> tuple[list[dict], list[str]]:
    rate = key_occupancy(opts.get("hotel_star_rating") or "4-5", bool(opts.get("has_operator")))
    keys = opts.get("units_per_floor")
    floors = _hotel_common(
        rng, asset, model, opts,
        rooms_for_floor=lambda people: {"units": _hotel_rooms(
            rng, int(keys) if keys is not None else max(6, round(people / rate)))},
    )
    for f in floors:
        f.setdefault("units", {t: 0 for t in HOTEL_ROOM_TYPES})
    return floors, list(HOTEL_ROOM_TYPES)


def hotel_apartments(rng: random.Random, asset: Asset, model: str, opts: dict) -> tuple[list[dict], list[str]]:
    types = _unit_types(rng, opts, [["Studio", "1BR", "2BR"], ["Studio", "1BR", "2BR", "3BR"]])
    rates = unit_occupancy(asset.key, bool(opts.get("has_operator")))
    units = opts.get("units_per_floor")
    floors = _hotel_common(
        rng, asset, model, opts,
        rooms_for_floor=lambda people: {"units": _unit_plan(rng, types, rates, people, units)},
    )
    for f in floors:
        f.setdefault("units", {t: 0 for t in types})
    return floors, types


# ---------------------------------------------------------------- car parking

def car_parking(rng: random.Random, asset: Asset, model: str, opts: dict) -> tuple[list[dict], list[str]]:
    levels = _occupied(rng, asset, model, opts)
    per_car = CAR_OCCUPANCY.get(opts.get("car_parking_facility_type"), 1.5)
    s = SIZING[asset.key]
    want = levels * per_car * rng.uniform(*(s["cars_m1"] if model == "DBC-M1" else s["cars_m2"]))
    # M1 population (cars x people per car, ground excluded) stays inside DBC Figure D.23.
    population = _fit(want, chart_range(asset.key, levels) if model == "DBC-M1" else None)
    per_floor = int(choose(opts, "cars_per_floor", max(10, int(population / per_car / levels))))
    exact = opts.get("cars_per_floor") is not None
    jitter = (lambda lo, hi: per_floor) if exact else (lambda lo, hi: int(per_floor * rng.uniform(lo, hi)))
    floors: list[dict] = [{"name": "Level R", "height_m": None, "use": "Roof parking",
                           "cars": jitter(0.9, 1.0), "occupied": True, "boarding": False}]
    typical_h = _typical_h(rng, asset, opts)
    for level in range(levels - 1, 0, -1):
        floors.append({"name": f"Level {level}", "height_m": typical_h, "use": "Parking",
                       "cars": jitter(0.95, 1.0), "occupied": True, "boarding": False})
    ground = _ground(rng, asset, opts, "Ground - entry / exit, lobby", name="Level G")
    ground["cars"] = int(per_floor * rng.uniform(0.6, 0.9))
    floors.append(ground)
    return floors, []


# --------------------------------------------------------------------- retail

_RETAIL_TENANTS = [
    "Retail", "F&B", "Anchor store", "Cinema", "Family entertainment centre",
    "Gym", "Food court", "Fashion retail", "Electronics retail", "Nursery",
]


def retail(rng: random.Random, asset: Asset, model: str, opts: dict) -> tuple[list[dict], list[str]]:
    # Occupied floors = roof + upper levels + ground, as in KARR AI's retail samples.
    upper = _occupied(rng, asset, model, opts) - 2
    area = opts.get("floor_area_m2")
    floors: list[dict] = [{"name": "Roof", "height_m": _round_h(rng.uniform(4.5, 5.5)),
                           "use": "Roof / MEP plant", "occupied": True, "boarding": False}]
    for level in range(upper, 0, -1):
        uses = ", ".join(rng.sample(_RETAIL_TENANTS, k=rng.randint(3, 5)))
        floors.append({"name": f"Level {level}", "height_m": _typical_h(rng, asset, opts),
                       "use": uses, "area_m2": int(choose(opts, "floor_area_m2", rng.randint(4000, 9000))),
                       "occupied": True, "boarding": False})
    anchors = rng.sample(["Super Market", "Hypermarket", "Pharmacy", "Nursery"], k=2)
    moving_walks = opts.get("moving_walks")
    if moving_walks is True and not any(TROLLEY_USE_RE.search(a) for a in anchors):
        anchors[-1] = "Hypermarket"  # a trolley use: KARR AI adds moving walks down to the basements
    elif moving_walks is False:
        anchors = [a if not TROLLEY_USE_RE.search(a) else "Clinic" for a in anchors]
    ground = _ground(rng, asset, opts, ", ".join(["Retail", "F&B", *anchors]), name="Ground floor")
    ground.update(area_m2=int(area) if area is not None else rng.randint(5000, 9000),
                  occupied=True, boarding=False)
    floors.append(ground)
    floors += _basements(rng, asset, opts, (250, 500),
                         name=lambda i: "Basement" if i == 1 else f"Basement {i}")
    return floors, []


# ---------------------------------------------------- schools / universities

def _education(rng: random.Random, asset: Asset, model: str, opts: dict, uni: bool) -> tuple[list[dict], list[str]]:
    levels = _occupied(rng, asset, model, opts)
    typical_h = _typical_h(rng, asset, opts)
    room_word = "Lecture rooms" if uni else "Class rooms"
    s = SIZING[asset.key]
    staff_level = rng.randint(1, levels)
    floors: list[dict] = []
    for level in range(levels, 0, -1):
        is_staff = level == staff_level
        rooms = rng.randint(4, 7) if is_staff else rng.randint(*s["classrooms"])
        floors.append({
            "name": f"Level {level}", "height_m": typical_h,
            "use": f"{room_word} + Staff room" if is_staff else room_word,
            "classrooms": int(choose(opts, "classrooms_per_floor", rooms)),
            "students_per_classroom": int(choose(opts, "students_per_classroom", rng.randint(*s["students"]))),
            "staff": rng.randint(40, 120) if is_staff else 0,
            "occupied": True, "boarding": False,
        })
    floors.append(_ground(rng, asset, opts, f"{room_word}, Admin & Principal's office" if not uni
                          else "Lobby, library, admin offices", name="Ground floor"))
    floors += _basements(rng, asset, opts, (80, 200),
                         name=lambda i: "Basement" if i == 1 else f"Basement {i}")
    return floors, []


def schools(rng, asset, model, opts):
    return _education(rng, asset, model, opts, uni=False)


def universities(rng, asset, model, opts):
    return _education(rng, asset, model, opts, uni=True)


BUILDERS = {
    "residential": residential,
    "office": office,
    "hotel": hotel,
    "hotel_apartments": hotel_apartments,
    "car_parking": car_parking,
    "retail": retail,
    "schools": schools,
    "universities": universities,
}


def build_floors(asset: Asset, model: str, rng: random.Random, opts: dict) -> tuple[list[dict], list[str]]:
    return BUILDERS[asset.key](rng, asset, model, opts)
