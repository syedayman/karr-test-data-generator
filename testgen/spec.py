"""The project spec: one JSON document that every output file is built from.

`make_spec` invents a project (numbers by rule, names and prose from the AI
story or fallbacks). `derive` computes what the files and the KARR AI form
need from the floors: travel heights, occupied / boarding counts, rough
population and the machine type. `validate` says what is wrong with an
edited spec before anything is built from it.
"""

from __future__ import annotations

import math
import random
import re
from datetime import date

from . import fallback_story
from .assets import (
    ASSETS,
    CAR_OCCUPANCY,
    ENTRANCE_PEOPLE_PER_CAR,
    ESCALATOR_SPLIT,
    HOTEL_STAR_AWT,
    HOTEL_STARS,
    MRA_SPEEDS,
    MRL_SPEEDS,
    OPERATOR_RATES_APARTMENTS,
    OPERATOR_RATES_HOTEL,
    PENTHOUSE_TYPES,
    TROLLEY_USE_RE,
    VALID_SPEEDS,
    Asset,
    asset_for,
    default_capacities,
    height_category,
    key_occupancy,
    unit_occupancy,
)
from .excel import ground_index
from .floors import build_floors, choose, occupied_limits

SPEC_VERSION = 2
LOCATIONS = ["Dubai", "Abu Dhabi", "Sharjah & N.E."]
PROJECT_TYPES = ["Pre Concept", "Concept", "Schematic", "Detailed"]
PASSENGER_CAPACITIES = [1050, 1125, 1350, 1600, 1800, 2000]
FIRE_CAPACITIES = [1275, 1600, 2000]
SIM_SPEEDS = MRL_SPEEDS + MRA_SPEEDS
# m² per person for Hotel Apartments public areas (optional "Public Area Occupancy" sheet).
PUBLIC_AREA_OCCUPANCY = [{"area": "Meeting rooms", "m2_per_person": 1.4},
                         {"area": "Restaurant", "m2_per_person": 1.5},
                         {"area": "Ball room", "m2_per_person": 1.2}]
# Files and sheets left out unless the tester ticks them (optional KARR AI inputs).
DEFAULT_SKIP = ["Public Area Occupancy"]
GROUPINGS = ["in-line", "facing_each_other"]
LOBBY_DEPTHS_M = [3.0, 3.5, 4.0, 4.5]


# ------------------------------------------------------------------ derived

def _lowest_index(floors: list[dict], pred) -> int | None:
    idx = [i for i, f in enumerate(floors) if pred(f)]
    return max(idx) if idx else None  # list is top to bottom


def _highest_index(floors: list[dict], pred) -> int | None:
    idx = [i for i, f in enumerate(floors) if pred(f)]
    return min(idx) if idx else None


def _travel(floors: list[dict], top: int, bottom: int) -> float:
    """Sum of floor-to-floor heights from `bottom` up to, not including, `top`."""
    return round(sum(float(floors[i].get("height_m") or 0) for i in range(top + 1, bottom + 1)), 2)


def passenger_served(spec: dict) -> tuple[int, int]:
    """(top index, bottom index) of the passenger lift run."""
    floors = spec["floors"]
    bottom = _lowest_index(floors, lambda f: f.get("boarding") or f.get("occupied"))
    if spec["vt_criteria"].get("serves_roof"):
        top = 0
    else:
        top = _highest_index(floors, lambda f: f.get("occupied") or f.get("boarding"))
    return top, bottom


def floor_people(asset: Asset, spec: dict, floor: dict) -> float:
    """People on one floor, counted the way KARR AI counts them where it can."""
    star = spec["project_info"].get("hotel_star_rating") or "4-5"
    has_operator = bool(spec["building"].get("has_operator"))
    if asset.key == "hotel" and floor.get("units"):
        return sum(floor["units"].values()) * key_occupancy(star, has_operator)
    if floor.get("units"):
        rates = unit_occupancy(asset.key, has_operator)
        return sum(rates.get(t, 2.0) * n for t, n in floor["units"].items())
    if asset.key == "office" and floor.get("occupied") and floor.get("area_m2"):
        return floor["area_m2"] * 0.8 / 10
    if asset.key == "retail" and floor.get("area_m2"):
        return floor["area_m2"] / 5
    if asset.key == "car_parking" and floor.get("occupied") and floor.get("cars"):
        rate = CAR_OCCUPANCY.get(spec["project_info"].get("car_parking_facility_type"), 1.5)
        return floor["cars"] * rate
    if floor.get("classrooms"):
        return floor["classrooms"] * floor.get("students_per_classroom", 0) * 0.10 + floor.get("staff", 0)
    return 0.0


def escalator_split(spec: dict, floor: dict) -> tuple[float, float]:
    """(escalator share, lift share) of a floor's people.

    (0, 1) everywhere except car parks with escalators, where DBC Table 2.13
    sends most people on the lower levels by escalator (KARR AI's population split).
    """
    if spec["asset"] != "Car Parking" or not spec["project_info"].get("car_parking_has_escalators"):
        return 0.0, 1.0
    levels = [f["name"] for f in reversed(spec["floors"]) if f.get("occupied")]  # ground up
    if floor["name"] not in levels:
        return 0.0, 1.0
    return ESCALATOR_SPLIT[min(levels.index(floor["name"]) + 1, 5)]


def lift_share(spec: dict, floor: dict) -> float:
    return escalator_split(spec, floor)[1]


def lift_people(spec: dict, floor: dict) -> float:
    """People on a floor who use the lifts (what the simulations are run for)."""
    people = floor_people(asset_for(spec["asset"]), spec, floor)
    escalator, _ = escalator_split(spec, floor)
    if not escalator:
        return people
    total = round(people)  # rounded the way KARR AI's population split rounds
    return total - round(total * escalator)


def derive(spec: dict) -> dict:
    asset = asset_for(spec["asset"])
    floors = spec["floors"]
    top, bottom = passenger_served(spec)
    fire_top, fire_bottom = 0, len(floors) - 1
    pass_travel = _travel(floors, top, bottom)
    fire_travel = _travel(floors, fire_top, fire_bottom)
    population = round(sum(floor_people(asset, spec, f) for f in floors if f.get("occupied")))
    divisor = asset.speed_divisor
    min_speed = pass_travel / divisor if divisor else 1.0
    machine = "mrl" if min_speed <= 1.75 else "mra"
    return {
        "height_category": height_category(asset, spec["model"]),
        "occupied_floors": sum(1 for f in floors if f.get("occupied")),
        "boarding_floors": sum(1 for f in floors if f.get("boarding")),
        "passenger_travel_m": pass_travel,
        "fire_travel_m": fire_travel,
        "passenger_top": floors[top]["name"],
        "passenger_bottom": floors[bottom]["name"],
        "population": population,
        "min_speed_mps": round(min_speed, 2),
        "machine_type": machine,
        "stops": bottom - top + 1,
    }


# --------------------------------------------------------------- simulations

def _speeds(min_speed: float) -> list[float]:
    pool = MRL_SPEEDS if min_speed <= 1.75 else MRA_SPEEDS
    above = [s for s in pool if s >= min_speed - 1e-9]
    return (above or pool[-1:])[:2]


def _capacities(default_kg: int) -> list[int]:
    base = default_kg if default_kg in PASSENGER_CAPACITIES else 1350
    i = PASSENGER_CAPACITIES.index(base)
    return PASSENGER_CAPACITIES[i:i + 2]


_PER_LIFT = {"residential": 300, "office": 200, "hotel": 150, "hotel_apartments": 170,
             "car_parking": 450, "retail": 400, "schools": 150, "universities": 150}


def simulation_rows(rng: random.Random, lifts_target: int, speeds: list[float],
                    capacities: list[int], awt_limit: float, travel_m: float,
                    spread: float = 1.0) -> list[dict]:
    """Rows of a fake results table: target lift count passes, one fewer fails."""
    door = [round(rng.choice([0.0, 0.5]), 2), round(rng.choice([1.8, 2.0, 2.2]), 2),
            round(rng.choice([2.8, 2.9, 3.0]), 2)]
    rows = []
    for n in sorted({max(1, lifts_target - 1), lifts_target, lifts_target + 1}):
        for s_i, speed in enumerate(speeds):
            for cap in capacities:
                awt = awt_limit * 0.80 * spread * (lifts_target / n) ** 1.6 * (0.95 if s_i else 1.0)
                if n == lifts_target:
                    awt = min(awt, awt_limit * 0.93)
                elif n < lifts_target:
                    awt = max(awt, awt_limit * rng.uniform(1.12, 1.3))
                transit = travel_m / speed + 8 + rng.uniform(0, 6)
                rows.append({
                    "lifts": n, "speed": speed, "accel": 0.8 if speed < 2.5 else 1.0,
                    "jerk": 0.9 if speed < 2.5 else 1.2, "capacity": cap, "door": door,
                    "awt": round(awt, 1), "lwt": round(awt * rng.uniform(3.2, 3.8), 1),
                    "att": round(transit, 1), "ltt": round(transit * rng.uniform(2.0, 2.6), 1),
                    "atd": round(awt + transit, 1),
                    "ltd": round((awt + transit) * rng.uniform(2.3, 2.7), 1),
                })
    return rows


def make_simulations(rng: random.Random, spec: dict) -> dict | None:
    asset = asset_for(spec["asset"])
    d = derive(spec)
    building = spec["building"]
    needs_guest = spec["model"] == "DBC-M2"
    needs_op = asset.hotel_like and building.get("has_operator")
    needs_am = asset.hotel_like and building.get("has_amenities")
    if not (needs_guest or needs_op or needs_am):
        return None
    cores = spec["vt_criteria"].get("core_count") or 1
    chosen = spec.get("options") or {}
    lift_users = sum(lift_people(spec, f) for f in spec["floors"] if f.get("occupied"))
    target = int(chosen.get("sim_lifts")
                 or max(2, min(10, math.ceil(lift_users / cores / _PER_LIFT[asset.key]))))
    speeds = sorted(chosen.get("sim_speeds") or _speeds(d["min_speed_mps"]))
    caps = sorted(chosen.get("sim_capacities") or _capacities(spec["space_planning"]["passenger_capacity_kg"]))
    awt = guest_awt(spec)
    sims: dict = {}
    if needs_guest:
        if asset.single_sim:
            sims["guest"] = {"single": simulation_rows(rng, target, speeds, caps, awt, d["passenger_travel_m"])}
        else:
            sims["guest"] = {
                "morning": simulation_rows(rng, target, speeds, caps, awt, d["passenger_travel_m"]),
                "evening": simulation_rows(rng, target, speeds, caps, awt, d["passenger_travel_m"],
                                           spread=rng.uniform(0.9, 1.05)),
            }
    if needs_op:
        op_awt = spec["operator_profile"]["awt_s"]
        sims["operator"] = simulation_rows(rng, target, speeds, caps, op_awt, d["passenger_travel_m"])
    if needs_am:
        am_awt = spec["amenities_profile"]["awt_s"]
        sims["amenities"] = simulation_rows(rng, rng.randint(2, 3), speeds[:1], caps[:1], am_awt,
                                            d["passenger_travel_m"] * 0.4)
    return sims


def guest_awt(spec: dict) -> int:
    asset = asset_for(spec["asset"])
    if asset.key == "hotel":
        return HOTEL_STAR_AWT[spec["project_info"].get("hotel_star_rating") or "4-5"]
    return asset.awt_s


def make_entrance_bias(rng: random.Random, spec: dict) -> list[dict] | None:
    """Entrance Bias rows (boarding floors, percent) for single-simulation M2 assets."""
    asset = asset_for(spec["asset"])
    if spec["model"] != "DBC-M2" or not asset.entrance_bias_sheet:
        return None
    floors = spec["floors"]
    if asset.key == "car_parking":
        parking = [f for f in floors if f.get("occupied") and f.get("cars")]
        weight = {f["name"]: f["cars"] * lift_share(spec, f) for f in parking}
        total = sum(weight.values()) or 1
        rows = [{"floor": f["name"], "parking": f["cars"],
                 "percent": round(100 * weight[f["name"]] / total, 1)} for f in parking]
        ground = next(f for f in floors if f.get("boarding"))
        rows.append({"floor": ground["name"], "parking": ground.get("cars", 0), "percent": 0.0})
        _fix_total(rows)
        return rows
    rows = []
    rooftop = next((f for f in floors if f.get("rooftop")), None)
    if rooftop:
        rows.append({"floor": rooftop["name"], "parking": 0, "percent": 5.0})
    basements = [f for f in floors if f.get("boarding") and f.get("cars")]
    each = rng.choice([0.0, 5.0, 10.0])
    for b in basements:
        rows.append({"floor": b["name"], "parking": b["cars"], "percent": each})
    ground = next(f for f in floors if f.get("boarding") and not f.get("cars") and not f.get("rooftop"))
    rows.insert(1 if rooftop else 0, {"floor": ground["name"], "parking": 0,
                                      "percent": round(100 - sum(r["percent"] for r in rows), 1)})
    return rows


def _fix_total(rows: list[dict]) -> None:
    gap = round(100 - sum(r["percent"] for r in rows), 1)
    biggest = max(rows, key=lambda r: r["percent"])
    biggest["percent"] = round(biggest["percent"] + gap, 1)


# ----------------------------------------------------------------- profiles

def make_operator_profile(rng: random.Random, story: dict, apartments: bool) -> dict:
    return {
        "title": "Design Criteria- Hotel guest pass lifts",
        "design_guide": f"{story['operator_brand']} Operator Guidelines v1.0",
        "occupancy_rates": dict(OPERATOR_RATES_APARTMENTS if apartments else OPERATOR_RATES_HOTEL),
        "building_occupancy": "100% Occupancy",
        "cabin_loading_factor": 0.5,
        "handling_capacity": 0.12,
        "awt_s": rng.choice([24, 30]),
    }


def make_amenities_profile(rng: random.Random, story: dict) -> dict:
    return {
        "title": "Design Criteria- Hotel public pass lifts",
        "design_guide": f"{story['operator_brand']} Guidelines v1.0",
        "occupancy_rates": {"Meeting room": 1.2, "Restaurant": 1.5, "Ballroom": 1.5},
        "building_occupancy": "100% Occupancy",
        "cabin_loading_factor": 0.5,
        "handling_capacity": 0.12,
        "awt_s": rng.choice([30, 40]),
    }


# --------------------------------------------------------------------- make

def check_options(asset: Asset, model: str, opts: dict) -> None:
    """Raise ValueError for an option KARR AI could not take for this method."""
    if model == "DBC-M2" and not asset.supports_m2:
        raise ValueError(f"{asset.classification} has no M2 in KARR AI yet.")
    occ = opts.get("occupied_floors")
    if occ is not None:
        lo, hi = occupied_limits(asset, model)
        if not lo <= int(occ) <= hi:
            raise ValueError(f"{asset.classification} {model[-2:]} needs {lo}-{hi} occupied floors, not {occ}.")
    cores = opts.get("core_count")
    if cores is not None and not 1 <= int(cores) <= 5:
        raise ValueError("KARR AI takes 1-5 cores.")
    lo, hi = opts.get("units_per_floor_min"), opts.get("units_per_floor_max")
    if lo is not None and hi is not None and int(lo) > int(hi):
        raise ValueError(f"Min per floor ({lo}) is above max ({hi}).")


def make_spec(asset_key: str, model: str, seed: int | None = None,
              options: dict | None = None, story: dict | None = None) -> dict:
    """Invent a project. `options` (see floors.py and README) fix any value.

    A setup-page field KARR AI fills in by default (no authority exception, one core,
    no operator / amenities, Independent car park, no escalators, capacities) gets
    that default; the rest is random.
    """
    asset = ASSETS[asset_key]
    opts = {k: v for k, v in (options or {}).items()
            if v is not None and v != "" and (v != [] or k == "skip_outputs")}
    check_options(asset, model, opts)
    seed = seed if seed is not None else random.randrange(1, 10**6)
    rng = random.Random(seed)
    chosen = dict(opts)  # what the tester set, kept in the spec
    story = story or fallback_story.make(rng, asset, opts)

    if asset.key == "hotel":
        opts["hotel_star_rating"] = choose(opts, "hotel_star_rating", rng.choice(HOTEL_STARS))
    if asset.hotel_like:
        opts["has_operator"] = choose(opts, "has_operator", False)
        opts["has_amenities"] = choose(opts, "has_amenities", False)
    if asset.key == "car_parking":
        opts["car_parking_facility_type"] = choose(opts, "car_parking_facility_type", "Independent")
        opts["car_parking_has_escalators"] = choose(opts, "car_parking_has_escalators", False)

    floors, unit_types = build_floors(asset, model, rng, opts)
    today = date.today()
    location = story.get("location") if story.get("location") in LOCATIONS else rng.choice(LOCATIONS)
    project_info = {
        "project_name": opts.get("project_name") or story["project_name"],
        "employer_client_developer": story["client"],
        "architect": story["architect"],
        "lead_consultant": story["lead_consultant"],
        "project_location": choose(opts, "location", location),
        "project_classification": asset.classification,
        "header_text": "TEST PROJECT - FICTIONAL DATA",
        "footer_text": f"{story['lead_consultant']} - generated test data",
        "revision_details": "First draft",
        "project_address": story["address"],
        "project_type": choose(opts, "project_type", rng.choice(PROJECT_TYPES)),
        "reference": f"TEST-{today:%y%m}-{seed:06d}-{asset.key[:3].upper()}-{model[-2:]}",
        "author": story["author"],
        "approved_by": story["approved_by"],
    }
    if asset.key == "hotel":
        project_info["hotel_star_rating"] = opts["hotel_star_rating"]
    if asset.key == "car_parking":
        project_info["car_parking_facility_type"] = opts["car_parking_facility_type"]
        project_info["car_parking_has_escalators"] = bool(opts["car_parking_has_escalators"])

    passenger_kg, fire_kg = default_capacities(asset, opts.get("hotel_star_rating"))
    spec = {
        "spec_version": SPEC_VERSION,
        "seed": seed,
        "asset": asset.classification,
        "model": model,
        "options": chosen,
        "project_info": project_info,
        "building": {"has_authority_exceptions": bool(choose(opts, "authority_exceptions", False))},
        "vt_criteria": {
            "elevator_grouping": choose(opts, "elevator_grouping", rng.choice(GROUPINGS)),
            "lobby_depth_m": float(choose(opts, "lobby_depth_m", rng.choice(LOBBY_DEPTHS_M))),
            "core_count": int(choose(opts, "core_count", 1)),
            "serves_roof": bool(opts.get("serves_roof", False)),
            "multipurpose_elevator": bool(choose(opts, "multipurpose_elevator",
                                                 asset.key == "schools" and model == "DBC-M1")),
            "usable_area_below_pit": False,
        },
        "space_planning": {"passenger_capacity_kg": int(choose(opts, "passenger_capacity_kg", passenger_kg)),
                           "fire_service_capacity_kg": int(choose(opts, "fire_service_capacity_kg", fire_kg))},
        "unit_types": unit_types,
        "floors": floors,
        "operator_profile": None,
        "amenities_profile": None,
        "entrance_bias": None,
        "simulations": None,
        "public_area_occupancy": None,
        "outputs": {"skip": list(opts.get("skip_outputs", DEFAULT_SKIP))},
        "story": story,
    }
    if asset.hotel_like:
        spec["building"]["has_operator"] = bool(opts["has_operator"])
        spec["building"]["has_amenities"] = bool(opts["has_amenities"])
        if opts["has_operator"]:
            spec["operator_profile"] = make_operator_profile(rng, story, asset.key == "hotel_apartments")
        if opts["has_amenities"]:
            spec["amenities_profile"] = make_amenities_profile(rng, story)
            if asset.key == "hotel_apartments":
                spec["public_area_occupancy"] = [dict(r) for r in PUBLIC_AREA_OCCUPANCY]
    if spec["building"]["has_authority_exceptions"]:
        spec["building"]["authority_exceptions"] = [{
            "exception_no": f"EXP-{rng.randint(100, 999)}",
            "exception_date": f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{today:%y}",
            "details": "Authority accepted one fire/service lift serving the podium car park levels "
                       "instead of two (fictional test exception).",
        }]

    return refresh(spec, rng)


def refresh(spec: dict, rng: random.Random | None = None) -> dict:
    """Work out everything that follows from the floors.

    Machine type, the architect's preliminary lift numbers, the entrance bias
    and the simulation results. Run after the floors change (the floor editor).
    """
    rng = rng or random.Random(int(spec.get("seed") or 1))
    asset = asset_for(spec["asset"])
    cores = spec["vt_criteria"].get("core_count") or 1
    d = derive(spec)
    spec["space_planning"]["machine_type"] = d["machine_type"]
    est = max(1, min(10, math.ceil(d["population"] / cores / _PER_LIFT[asset.key])))
    spec["building"]["passenger_lifts_prelim"] = max(1, est * cores + rng.choice([-1, 0, 0, 1]))
    spec["building"]["fire_service_lifts_prelim"] = cores
    spec["entrance_bias"] = make_entrance_bias(rng, spec)
    spec["simulations"] = make_simulations(rng, spec)
    return spec


def with_story(spec: dict, story: dict) -> dict:
    """Swap in a new story (e.g. from the AI) and the project fields it names.

    A project name or location the tester chose wins over the story's.
    """
    info = spec["project_info"]
    chosen = spec.get("options") or {}
    info.update({
        "project_name": chosen.get("project_name") or story["project_name"],
        "employer_client_developer": story["client"],
        "architect": story["architect"],
        "lead_consultant": story["lead_consultant"],
        "project_address": story["address"],
        "author": story["author"],
        "approved_by": story["approved_by"],
        "footer_text": f"{story['lead_consultant']} - generated test data",
    })
    if chosen.get("location") in LOCATIONS:
        info["project_location"] = chosen["location"]
    elif story.get("location") in LOCATIONS:
        info["project_location"] = story["location"]
    for key in ("operator_profile", "amenities_profile"):
        if spec.get(key):
            suffix = " Operator Guidelines v1.0" if key == "operator_profile" else " Guidelines v1.0"
            spec[key]["design_guide"] = f"{story['operator_brand']}{suffix}"
    spec["story"] = story
    return spec


def _span(values: list):
    """One value, or (low, high) when the floors differ; None when there are none."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    lo, hi = min(values), max(values)
    return lo if lo == hi else (lo, hi)


def resolved_options(spec: dict) -> dict:
    """The value of every option as the project actually has it (what Auto picked).

    Keys match `make_spec` options. Floor values that differ between floors come
    back as (low, high).
    """
    asset = asset_for(spec["asset"])
    floors = spec["floors"]
    g = ground_index(floors)
    occupied = [f for f in floors if f.get("occupied")]
    typical = [f for f in occupied if f is not floors[g] and not str(f["name"]).startswith("Roof")]
    info, b, vt, sp = spec["project_info"], spec["building"], spec["vt_criteria"], spec["space_planning"]
    out = {
        "occupied_floors": len(occupied),
        "basements": len(floors) - g - 1,
        "typical_floor_height_m": _span([f.get("height_m") for f in typical]),
        "ground_floor_height_m": floors[g].get("height_m"),
        "project_name": info["project_name"],
        "location": info["project_location"],
        "project_type": info["project_type"],
        "authority_exceptions": bool(b.get("has_authority_exceptions")),
        "core_count": vt.get("core_count") or 1,
        "elevator_grouping": vt.get("elevator_grouping"),
        "lobby_depth_m": vt.get("lobby_depth_m"),
        "serves_roof": bool(vt.get("serves_roof")),
        "multipurpose_elevator": bool(vt.get("multipurpose_elevator")),
        "passenger_capacity_kg": sp.get("passenger_capacity_kg"),
        "fire_service_capacity_kg": sp.get("fire_service_capacity_kg"),
    }
    penthouses = [f for f in occupied if f.get("use") == "Penthouse"]
    if asset.key in ("residential", "hotel_apartments", "hotel"):
        counts = [sum(f["units"].values()) for f in occupied if f not in penthouses]
        out["units_per_floor_min"], out["units_per_floor_max"] = min(counts), max(counts)
    if asset.key in ("residential", "hotel_apartments"):
        out["unit_types"] = [t for t in spec.get("unit_types") or [] if t not in PENTHOUSE_TYPES]
    if asset.key == "residential":
        out["penthouse_floors"] = len(penthouses)
        if penthouses:
            out["penthouse_type"] = next(iter(penthouses[0]["units"]))
    if asset.key != "car_parking" and floors[g + 1:]:
        out["cars_per_basement"] = _span([f.get("cars") for f in floors[g + 1:]])
    if asset.key == "office":
        out["floor_area_m2"] = _span([f.get("area_m2") for f in occupied])
        out["mezzanine"] = any(f["name"] == "M" for f in floors)
    if asset.key == "retail":
        out["floor_area_m2"] = _span([f.get("area_m2") for f in occupied])
        trolley = any(TROLLEY_USE_RE.search(str(f["use"])) for f in floors[:g + 1])
        out["moving_walks"] = trolley and any(f.get("cars") for f in floors[g + 1:])
    if asset.key == "car_parking":
        out["cars_per_floor"] = _span([f.get("cars") for f in occupied])
        out["car_parking_facility_type"] = info.get("car_parking_facility_type")
        out["car_parking_has_escalators"] = bool(info.get("car_parking_has_escalators"))
    if asset.key in ("schools", "universities"):
        out["classrooms_per_floor"] = _span([f.get("classrooms") for f in occupied])
        out["students_per_classroom"] = _span([f.get("students_per_classroom") for f in occupied])
    if asset.key == "hotel":
        out["hotel_star_rating"] = info.get("hotel_star_rating")
    if asset.hotel_like:
        out["has_operator"] = bool(b.get("has_operator"))
        out["has_amenities"] = bool(b.get("has_amenities"))
    tables = [rows for label, rows in simulation_tables(spec) if label != "Amenities simulation"]
    if tables:
        rows = tables[0]
        lifts = sorted({r["lifts"] for r in rows})
        out["sim_lifts"] = lifts[1] if len(lifts) == 3 else lifts[0]
        out["sim_speeds"] = sorted({r["speed"] for r in rows})
        out["sim_capacities"] = sorted({r["capacity"] for r in rows})
    return out


def floors_summary(spec: dict) -> str:
    d = derive(spec)
    uses = sorted({str(f["use"]) for f in spec["floors"]})
    return (f"{len(spec['floors'])} levels ({d['occupied_floors']} occupied), uses: {', '.join(uses)}; "
            f"about {d['population']} occupants.")


# ----------------------------------------------------------------- validate

REQUIRED_TOP = ["spec_version", "asset", "model", "project_info", "building",
                "vt_criteria", "space_planning", "floors", "story"]


def validate(spec: dict) -> list[str]:
    errors = [f"Missing '{k}'." for k in REQUIRED_TOP if k not in spec]
    if errors:
        return errors
    try:
        asset = asset_for(spec["asset"])
    except ValueError as e:
        return [str(e)]
    if spec["model"] not in ("DBC-M1", "DBC-M2"):
        return ["model must be DBC-M1 or DBC-M2."]
    if spec["model"] == "DBC-M2" and not asset.supports_m2:
        errors.append(f"{asset.classification} has no M2 in KARR AI yet.")
    floors = spec["floors"]
    if not floors or not all("name" in f for f in floors):
        return errors + ["Every floor needs a name."]
    names = [str(f["name"]) for f in floors]
    if len(set(names)) != len(names):
        errors.append("Floor names must be unique.")
    occ = sum(1 for f in floors if f.get("occupied"))
    if occ == 0:
        errors.append("At least one floor must be occupied.")
    if not any(f.get("boarding") for f in floors):
        errors.append("At least one floor must be a boarding floor.")
    limit = asset.m1_threshold
    if spec["model"] == "DBC-M1" and occ > limit:
        errors.append(f"M1 {asset.classification} allows at most {limit} occupied floors; this has {occ}.")
    if spec["model"] == "DBC-M2" and occ <= limit:
        errors.append(f"M2 {asset.classification} needs more than {limit} occupied floors; this has {occ}.")
    if not 1 <= int(spec["vt_criteria"].get("core_count") or 1) <= 5:
        errors.append("vt_criteria.core_count must be 1-5.")
    for f in floors:
        if any(not isinstance(n, int) or n < 0 for n in (f.get("units") or {}).values()):
            errors.append(f"Floor {f['name']}: unit counts must be whole numbers, 0 or more.")
        for key in ("height_m", "area_m2", "cars", "classrooms", "students_per_classroom", "staff"):
            value = f.get(key)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                errors.append(f"Floor {f['name']}: {key} must be a number, 0 or more.")
    b = spec["building"]
    if asset.hotel_like:
        if b.get("has_operator") and not spec.get("operator_profile"):
            errors.append("has_operator is on but operator_profile is empty.")
        if b.get("has_amenities") and not spec.get("amenities_profile"):
            errors.append("has_amenities is on but amenities_profile is empty.")
    sims = spec.get("simulations") or {}
    if spec["model"] == "DBC-M2":
        guest = sims.get("guest") or {}
        need = ["single"] if asset.single_sim else ["morning", "evening"]
        for key in need:
            if not guest.get(key):
                errors.append(f"M2 needs simulations.guest.{key} rows.")
        if asset.entrance_bias_sheet and asset.key != "car_parking" and not spec.get("entrance_bias"):
            errors.append("M2 hotels need entrance_bias rows.")
    if asset.hotel_like and b.get("has_operator") and not sims.get("operator"):
        errors.append("Operator on: simulations.operator rows are needed.")
    if asset.hotel_like and b.get("has_amenities") and not sims.get("amenities"):
        errors.append("Amenities on: simulations.amenities rows are needed.")
    for name, rows in simulation_tables(spec):
        if len(rows) > MAX_SIM_ROWS:
            errors.append(f"{name}: at most {MAX_SIM_ROWS} result rows fit on the page.")
        for r in rows:
            if int(r.get("lifts") or 0) < 1 or float(r.get("speed") or 0) <= 0 or int(r.get("capacity") or 0) <= 0:
                errors.append(f"{name}: every row needs lifts, speed and capacity above 0.")
                break
    for r in spec.get("entrance_bias") or []:
        if not str(r.get("floor") or "").strip():
            errors.append("Every entrance bias row needs a floor.")
            break
    return errors


MAX_SIM_ROWS = 60


def car_park_sim_speed(spec: dict) -> float:
    """The one speed KARR AI accepts from a Car Parking M2 simulation (its M1 speed)."""
    raw = derive(spec)["passenger_travel_m"] / asset_for(spec["asset"]).speed_divisor
    return next((s for s in VALID_SPEEDS if s >= raw - 1e-9), VALID_SPEEDS[-1])


def _largest_remainder(percentages: list[float]) -> list[int]:
    """Whole percentages summing to 100, as KARR AI rounds them (negatives count as 0)."""
    cleaned = [max(0.0, p) for p in percentages]
    total = sum(cleaned)
    if total <= 0:
        return [0] * len(cleaned)
    if abs(total - 100.0) > 1e-9:
        cleaned = [p / total * 100.0 for p in cleaned]
    whole = [int(p) for p in cleaned]
    order = sorted(range(len(cleaned)), key=lambda i: cleaned[i] - whole[i], reverse=True)
    for i in order[:100 - sum(whole)]:
        whole[i] += 1
    return whole


def _entrance_population(spec: dict) -> int | None:
    """The population KARR AI divides by in the Entrance Bias table its report prints, else None.

    Residential (M1 and M2): the building population. Office M2: round(GA x 0.08) per office
    floor. Hotels, Hotel Apartments and Car Parking take the uploaded sheet instead; the other
    reports print no Entrance Bias table.
    """
    key = asset_for(spec["asset"]).key
    if key == "residential":
        return derive(spec)["population"]
    if key == "office" and spec["model"] == "DBC-M2":
        return sum(round(f["area_m2"] * 0.08) for f in spec["floors"]
                   if f.get("occupied") and f.get("area_m2") and re.search(r"offic|amenit", str(f["use"]).lower()))
    return None


def karr_entrance_bias(spec: dict) -> list[dict]:
    """KARR AI's own Entrance Bias table where its report prints one (see `_entrance_population`), else [].

    Ground and every parking level, top down. A parking level gets cars x 1.5 people as a
    share of the population; the ground floor takes the rest (negative when the cars bring
    more people than the building holds); the traffic-study column rounds to whole percent.
    """
    population = _entrance_population(spec)
    if population is None:
        return []
    floors = spec["floors"]
    g = ground_index(floors)
    levels = [f for i, f in enumerate(floors)
              if (f.get("cars") or 0) > 0 or i == g or (i > g and "park" in str(f["use"]).lower())]
    rows = []
    for f in levels:
        people = round((f.get("cars") or 0) * ENTRANCE_PEOPLE_PER_CAR)
        rows.append({"floor": f["name"], "cars": f.get("cars") or 0, "people": people, "ground": f is floors[g],
                     "percent": 0.0 if f is floors[g] else (people / population * 100 if population else 0.0)})
    ground_share = 100.0 - sum(r["percent"] for r in rows if not r["ground"])
    for r in rows:
        if r["ground"]:
            r["percent"] = ground_share
    for r, whole in zip(rows, _largest_remainder([r["percent"] for r in rows])):
        r["study"] = whole
    return rows


def entrance_problems(spec: dict) -> list[str]:
    """Why KARR AI's Entrance Bias table would look wrong (empty = fine)."""
    ground = next((r for r in karr_entrance_bias(spec) if r["ground"]), None)
    if ground and ground["percent"] < 0:
        return [f"cars x 1.5 is more people than the building holds, so KARR AI gives the ground floor "
                f"{ground['percent']:.0f}% in Entrance Bias"]
    return []


def simulation_problems(spec: dict) -> list[str]:
    """Reasons KARR AI would find no acceptable simulated option (empty = it will)."""
    sims = spec.get("simulations") or {}
    guest = sims.get("guest") or {}
    limit = guest_awt(spec)
    problems = []

    def passing(rows, awt):
        return {(r["lifts"], r["speed"], r["capacity"]) for r in rows if r["awt"] <= awt}

    if guest.get("morning") and guest.get("evening"):
        if not passing(guest["morning"], limit) & passing(guest["evening"], limit):
            problems.append(f"No option waits {limit} s or less in both peaks")
    elif guest.get("single"):
        ok = passing(guest["single"], limit)
        if not ok:
            problems.append(f"No option waits {limit} s or less")
        elif asset_for(spec["asset"]).key == "car_parking":
            speed = car_park_sim_speed(spec)
            if not any(abs(s - speed) < 1e-6 for _, s, _ in ok):
                problems.append(f"No passing option at {speed:g} m/s, the speed KARR AI takes for this travel")
    for key, label in (("operator", "operator"), ("amenities", "amenities")):
        profile = spec.get(f"{key}_profile")
        if sims.get(key) and profile and not passing(sims[key], profile["awt_s"]):
            problems.append(f"No {label} option waits {profile['awt_s']} s or less")
    return problems


def simulation_tables(spec: dict) -> list[tuple[str, list[dict]]]:
    """(label, rows) for every simulation in the spec, in file order."""
    sims = spec.get("simulations") or {}
    guest = sims.get("guest") or {}
    second = "Breaks peak" if spec["asset"] in ("Schools", "Universities") else "Evening peak"
    out = []
    for key, label in (("morning", "Morning peak"), ("evening", second), ("single", "Guest simulation")):
        if guest.get(key):
            out.append((label, guest[key]))
    for key, label in (("operator", "Operator simulation"), ("amenities", "Amenities simulation")):
        if sims.get(key):
            out.append((label, sims[key]))
    return out
