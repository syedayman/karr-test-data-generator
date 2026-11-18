"""Tester-chosen options: they are honoured, stay valid for KARR AI, and the floor editor round-trips."""

import copy

import pytest

from testgen import charts, floor_table
from testgen.assets import ASSETS
from testgen.floors import occupied_limits
from testgen.spec import (
    derive,
    entrance_problems,
    karr_entrance_bias,
    make_spec,
    refresh,
    resolved_options,
    validate,
    with_story,
)

COMBOS = [(k, m) for k, a in ASSETS.items() for m in (["DBC-M1", "DBC-M2"] if a.supports_m2 else ["DBC-M1"])]


def _occupied(spec):
    return [f for f in spec["floors"] if f.get("occupied")]


@pytest.mark.parametrize("asset_key,model", COMBOS)
def test_the_chosen_floor_count_is_built_at_both_limits(asset_key, model):
    lo, hi = occupied_limits(ASSETS[asset_key], model)
    for n in (lo, hi):
        spec = make_spec(asset_key, model, seed=4, options={"occupied_floors": n})
        assert derive(spec)["occupied_floors"] == n
        assert validate(spec) == []


@pytest.mark.parametrize("asset_key", [k for k in ASSETS if charts.has_chart(k)])
def test_auto_sized_m1_buildings_get_a_chart_answer_for_every_floor_count(asset_key):
    lo, hi = occupied_limits(ASSETS[asset_key], "DBC-M1")
    for n in range(lo, hi + 1):
        for seed in (1, 2):
            spec = make_spec(asset_key, "DBC-M1", seed=seed, options={"occupied_floors": n})
            assert charts.check(spec) == [], (n, seed)


@pytest.mark.parametrize("asset_key,model,n", [
    ("residential", "DBC-M1", 36), ("residential", "DBC-M2", 35), ("hotel", "DBC-M1", 31),
    ("car_parking", "DBC-M2", 9), ("retail", "DBC-M1", 11), ("schools", "DBC-M1", 6),
])
def test_a_floor_count_on_the_wrong_side_of_the_m1_limit_is_refused(asset_key, model, n):
    with pytest.raises(ValueError, match="occupied floors"):
        make_spec(asset_key, model, seed=1, options={"occupied_floors": n})


def test_size_options_are_honoured():
    spec = make_spec("residential", "DBC-M1", seed=3, options={
        "occupied_floors": 12, "basements": 2, "typical_floor_height_m": 3.25, "ground_floor_height_m": 5.5,
        "unit_types": ["Studio", "2BR"], "units_per_floor_min": 9, "units_per_floor_max": 9})
    assert spec["unit_types"] == ["Studio", "2BR"]
    assert all(sum(f["units"].values()) == 9 and f["height_m"] == 3.25 for f in _occupied(spec))
    assert [f["name"] for f in spec["floors"] if f.get("cars")] == ["B1", "B2"]
    assert next(f for f in spec["floors"] if f["name"] == "GF")["height_m"] == 5.5
    assert not any("amenities" in f["use"].lower() for f in spec["floors"])


@pytest.mark.parametrize("asset_key,options,check", [
    ("hotel", {"units_per_floor_min": 18, "units_per_floor_max": 18}, lambda f: sum(f["units"].values()) == 18),
    ("hotel_apartments", {"units_per_floor_min": 7, "units_per_floor_max": 7}, lambda f: sum(f["units"].values()) == 7),
    ("office", {"floor_area_m2": 950}, lambda f: f["area_m2"] == 950),
    ("car_parking", {"cars_per_floor": 120}, lambda f: f["cars"] == 120),
    ("retail", {"floor_area_m2": 6000}, lambda f: f["name"] == "Roof" or f["area_m2"] == 6000),
    ("schools", {"classrooms_per_floor": 9, "students_per_classroom": 22},
     lambda f: f["classrooms"] == 9 and f["students_per_classroom"] == 22),
])
def test_contents_per_floor_are_honoured(asset_key, options, check):
    spec = make_spec(asset_key, "DBC-M1", seed=5, options=options)
    assert all(check(f) for f in _occupied(spec))


@pytest.mark.parametrize("asset_key", ["residential", "hotel", "hotel_apartments"])
def test_units_per_floor_vary_inside_the_chosen_range(asset_key):
    counts = {sum(f["units"].values()) for f in _occupied(make_spec(
        asset_key, "DBC-M2", seed=4, options={"units_per_floor_min": 8, "units_per_floor_max": 14}))
        if f["use"] != "Penthouse"}
    assert len(counts) > 1 and min(counts) >= 8 and max(counts) <= 14
    with pytest.raises(ValueError, match="above max"):
        make_spec(asset_key, "DBC-M1", seed=1, options={"units_per_floor_min": 9, "units_per_floor_max": 8})


@pytest.mark.parametrize("asset_key,model", COMBOS)
def test_setup_fields_get_karr_ai_defaults(asset_key, model):
    """What KARR AI's setup page fills in before the tester touches it."""
    spec = make_spec(asset_key, model, seed=2)
    assert spec["building"]["has_authority_exceptions"] is False
    assert spec["vt_criteria"]["core_count"] == 1
    assert spec["vt_criteria"]["serves_roof"] is False
    assert spec["vt_criteria"]["multipurpose_elevator"] is (asset_key == "schools" and model == "DBC-M1")
    assert spec["project_info"]["revision_details"] == "First draft"
    if ASSETS[asset_key].hotel_like:
        assert not spec["building"]["has_operator"] and not spec["building"]["has_amenities"]
    if asset_key == "car_parking":
        assert spec["project_info"]["car_parking_facility_type"] == "Independent"
        assert spec["project_info"]["car_parking_has_escalators"] is False


@pytest.mark.parametrize("stars,kg", [("1-2", (1350, 1600)), ("3", (1600, 1600)), ("4-5", (1600, 2000))])
def test_hotel_capacities_follow_the_star_tier(stars, kg):
    sp = make_spec("hotel", "DBC-M1", seed=1, options={"hotel_star_rating": stars})["space_planning"]
    assert (sp["passenger_capacity_kg"], sp["fire_service_capacity_kg"]) == kg


def test_office_without_mezzanine():
    spec = make_spec("office", "DBC-M1", seed=2, options={"mezzanine": False})
    assert "M" not in [f["name"] for f in spec["floors"]]


def test_project_settings_do_not_reshuffle_the_building():
    plain = make_spec("residential", "DBC-M1", seed=9)
    tuned = make_spec("residential", "DBC-M1", seed=9, options={
        "location": "Abu Dhabi", "project_type": "Detailed", "core_count": 3, "elevator_grouping": "in-line",
        "lobby_depth_m": 5.0, "authority_exceptions": False, "passenger_capacity_kg": 1600})
    assert tuned["floors"] == plain["floors"]
    assert tuned["project_info"]["project_location"] == "Abu Dhabi"
    assert tuned["project_info"]["project_type"] == "Detailed"
    assert tuned["vt_criteria"]["core_count"] == 3
    assert tuned["space_planning"]["passenger_capacity_kg"] == 1600
    assert tuned["options"]["location"] == "Abu Dhabi"


def test_a_chosen_name_and_location_survive_the_ai_story():
    spec = make_spec("office", "DBC-M1", seed=1, options={"project_name": "Test Tower", "location": "Sharjah & N.E."})
    story = dict(spec["story"], project_name="AI Name", location="Dubai")
    with_story(spec, story)
    assert spec["project_info"]["project_name"] == "Test Tower"
    assert spec["project_info"]["project_location"] == "Sharjah & N.E."


def test_the_chart_check_flags_buildings_outside_the_m1_chart():
    crowded = make_spec("residential", "DBC-M1", seed=1, options={"occupied_floors": 30, "units_per_floor_min": 60})
    assert any("the M1 chart covers" in p for p in charts.check(crowded))
    deep = make_spec("residential", "DBC-M1", seed=1, options={"occupied_floors": 3, "basements": 5})
    assert any("boarding floors" in p for p in charts.check(deep))
    assert charts.check(make_spec("residential", "DBC-M2", seed=1)) == []  # M2 has no chart


VIEWS = [floor_table.schedule_columns, floor_table.stacking_columns, floor_table.amenity_columns]


@pytest.mark.parametrize("asset_key,model", COMBOS)
@pytest.mark.parametrize("view", VIEWS)
def test_an_unchanged_sheet_editor_gives_back_the_same_floors(asset_key, model, view):
    spec = make_spec(asset_key, model, seed=7)
    columns = view(spec)
    assert floor_table.from_rows(spec, floor_table.to_rows(spec, columns), columns) == spec["floors"]


def test_editing_the_stacking_mix_keeps_the_schedule():
    spec = make_spec("hotel", "DBC-M1", seed=3, options={"has_amenities": True})
    columns = floor_table.stacking_columns(spec)
    rows = floor_table.to_rows(spec, columns)
    basement = next(r for r in rows if str(r["Floor"]).startswith("B"))
    basement["Boarding"] = False
    floors = floor_table.from_rows(spec, rows, columns)
    changed = [(a, b) for a, b in zip(spec["floors"], floors) if a != b]
    assert len(changed) == 1
    before, after = changed[0]
    assert after == dict(before, boarding=False)  # units, cars, rooftop and amenity flags untouched


def test_edited_floors_rebuild_with_fresh_simulations():
    spec = make_spec("residential", "DBC-M2", seed=12)
    columns = floor_table.schedule_columns(spec)
    rows = floor_table.to_rows(spec, columns)
    first_res = next(r for r in rows if spec["floors"][r[floor_table.ROW_ID]].get("occupied"))
    rows.insert(rows.index(first_res), dict(first_res, Floor="99"))  # one more apartment floor on top
    edited = copy.deepcopy(spec)
    edited["floors"] = floor_table.from_rows(spec, rows, columns)
    refresh(edited)
    assert validate(edited) == []
    assert derive(edited)["occupied_floors"] == derive(spec)["occupied_floors"] + 1
    assert derive(edited)["passenger_travel_m"] > derive(spec)["passenger_travel_m"]


def test_a_new_row_starts_as_an_empty_floor():
    spec = make_spec("office", "DBC-M1", seed=1)
    columns = floor_table.schedule_columns(spec)
    rows = floor_table.to_rows(spec, columns)
    rows.insert(1, {"Floor": "X", "Height (m)": 4.0, "Use": "Plant"})
    floors = floor_table.from_rows(spec, rows, columns)
    assert floors[1] == {"name": "X", "height_m": 4.0, "use": "Plant", "occupied": False, "boarding": False}


def test_a_floor_row_without_a_name_is_reported():
    spec = make_spec("office", "DBC-M1", seed=1)
    columns = floor_table.schedule_columns(spec)
    rows = floor_table.to_rows(spec, columns)
    rows[1]["Floor"] = None
    edited = dict(spec, floors=floor_table.from_rows(spec, rows, columns))
    assert any("name" in e for e in validate(edited))


def test_floor_groups_merge_identical_floors():
    spec = make_spec("office", "DBC-M1", seed=1, options={"occupied_floors": 10})
    groups = floor_table.floor_groups(spec)
    offices = [g for g in groups if g["kind"] == "occupied"]
    assert len(offices) == 1 and offices[0]["count"] == 10
    assert sum(g["count"] for g in groups) == len(spec["floors"])


@pytest.mark.parametrize("asset_key,model", COMBOS)
@pytest.mark.parametrize("seed", [8, 21])
def test_the_values_shown_as_picked_are_the_ones_the_project_uses(asset_key, model, seed):
    """Typing each shown pick back in as a fixed value changes nothing."""
    spec = make_spec(asset_key, model, seed=seed)
    picked = resolved_options(spec)
    assert picked["occupied_floors"] == derive(spec)["occupied_floors"]
    fixed = {k: v for k, v in picked.items() if not isinstance(v, tuple)}
    again = make_spec(asset_key, model, seed=seed, options=fixed)
    assert resolved_options(again) == picked
    assert again["floors"] == spec["floors"]


def test_residential_parking_drives_karr_entrance_bias():
    spec = make_spec("residential", "DBC-M2", seed=1, options={"basements": 2, "cars_per_basement": 100})
    rows = karr_entrance_bias(spec)
    assert [(r["floor"], r["cars"]) for r in rows] == [("GF", 0), ("B1", 100), ("B2", 100)]
    share = 150 / derive(spec)["population"] * 100  # 100 cars x 1.5 people
    assert rows[1]["percent"] == pytest.approx(share)
    assert rows[0]["percent"] == pytest.approx(100 - 2 * share)
    assert sum(r["study"] for r in rows) == 100 and not entrance_problems(spec)
    crowded = make_spec("residential", "DBC-M1", seed=1, options={"basements": 3, "cars_per_basement": 900})
    assert entrance_problems(crowded)


@pytest.mark.parametrize("asset_key,model,printed", [
    ("office", "DBC-M2", True), ("office", "DBC-M1", False), ("hotel", "DBC-M2", False),
    ("retail", "DBC-M1", False), ("universities", "DBC-M2", False),
])
def test_cars_per_basement_and_where_karr_prints_entrance_bias(asset_key, model, printed):
    spec = make_spec(asset_key, model, seed=2, options={"basements": 1, "cars_per_basement": 80})
    assert [f.get("cars") for f in spec["floors"] if f.get("boarding") and f.get("use") != "Main lobby"][-1] == 80
    assert bool(karr_entrance_bias(spec)) == printed
