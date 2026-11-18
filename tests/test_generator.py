import io
import json
import re

import openpyxl
import pdfplumber
import pytest

from testgen.assets import ASSETS
from testgen.bundle import build_files
from testgen.spec import derive, make_spec, validate

COMBOS = [(k, m) for k, a in ASSETS.items() for m in (["DBC-M1", "DBC-M2"] if a.supports_m2 else ["DBC-M1"])]
ROW_RE = re.compile(r"^(\d+) (\d+\.\d+) (\d+\.\d+) (\d+\.\d+) (\d+) [\d., ]+? (\d+\.\d) ")


@pytest.mark.parametrize("asset_key,model", COMBOS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_combo_is_valid_and_on_the_right_side_of_the_threshold(asset_key, model, seed):
    spec = make_spec(asset_key, model, seed=seed)
    assert validate(spec) == []
    d = derive(spec)
    limit = ASSETS[asset_key].m1_threshold
    assert (d["occupied_floors"] <= limit) == (model == "DBC-M1")
    assert d["passenger_travel_m"] > 0 and d["fire_travel_m"] >= d["passenger_travel_m"] - 0.01


@pytest.mark.parametrize("asset_key,model", COMBOS)
def test_workbook_sheets_come_in_the_order_karr_ai_searches(asset_key, model):
    spec = make_spec(asset_key, model, seed=5,
                     options={"has_operator": True, "has_amenities": True} if ASSETS[asset_key].hotel_like else None)
    wb = openpyxl.load_workbook(io.BytesIO(build_files(spec)["02 Unit mix workbook.xlsx"]))
    names = wb.sheetnames
    assert names[1] == "Lifts Stacking Mix"
    stacking = [n for n in names if "stacking" in n.lower()]
    assert stacking[0] == "Lifts Stacking Mix"
    if ASSETS[asset_key].hotel_like:
        assert {"Operator Profile", "Amenities Profile", "Amenities Stacking Mix"} <= set(names)
    if model == "DBC-M2" and ASSETS[asset_key].entrance_bias_sheet:
        assert "Entrance Bias" in names
    occupied = [r[1] for r in wb["Lifts Stacking Mix"].iter_rows(min_row=4, values_only=True)].count("Y")
    assert occupied == derive(spec)["occupied_floors"]


@pytest.mark.parametrize("asset_key,model", [c for c in COMBOS if c[1] == "DBC-M2"])
def test_simulation_pdf_results_read_back_as_written(asset_key, model):
    spec = make_spec(asset_key, model, seed=9)
    files = build_files(spec)
    guest = spec["simulations"]["guest"]
    rows = guest.get("single") or guest["morning"]
    pdf_name = next(n for n in files if n.startswith("05 "))
    with pdfplumber.open(io.BytesIO(files[pdf_name])) as pdf:
        text = pdf.pages[2].extract_text()
    assert "SIMULATION RESULTS" in text
    got = [(int(m[1]), float(m[2]), int(m[5]), float(m[6]))
           for m in (ROW_RE.match(line) for line in text.splitlines()) if m]
    assert got == [(r["lifts"], r["speed"], r["capacity"], r["awt"]) for r in rows]


@pytest.mark.parametrize("asset_key,model", [c for c in COMBOS if c[1] == "DBC-M2"])
def test_m2_simulations_have_a_passing_and_a_failing_row(asset_key, model):
    from testgen.spec import guest_awt

    spec = make_spec(asset_key, model, seed=11)
    guest = spec["simulations"]["guest"]
    limit = guest_awt(spec)
    for rows in guest.values():
        assert any(r["awt"] <= limit for r in rows)
        assert any(r["awt"] > limit for r in rows)


def test_hotel_schedule_has_room_columns_and_no_population_column():
    # KARR AI reads every room-like header as rooms; a "Keys pop (x1.8)" column doubled the population.
    spec = make_spec("hotel", "DBC-M1", seed=6)
    ws = openpyxl.load_workbook(io.BytesIO(build_files(spec)["02 Unit mix workbook.xlsx"])).worksheets[0]
    header = [c for c in next(ws.iter_rows(min_row=2, max_row=2, values_only=True)) if c]
    assert set(spec["unit_types"]) <= set(header)
    assert not any("pop" in str(h).lower() for h in header)


@pytest.mark.parametrize("seed", range(1, 25))
def test_m1_car_parking_population_fits_figure_d23(seed):
    spec = make_spec("car_parking", "DBC-M1", seed=seed)
    d = derive(spec)
    upper = {3: 500, 4: 600, 5: 700, 6: 1000, 7: 1000}[d["occupied_floors"]]
    assert d["population"] <= upper


@pytest.mark.parametrize("asset_key", ["hotel", "hotel_apartments"])
def test_operator_profile_states_a_default_occupancy(asset_key):
    spec = make_spec(asset_key, "DBC-M1", seed=2, options={"has_operator": True})
    ws = openpyxl.load_workbook(io.BytesIO(build_files(spec)["02 Unit mix workbook.xlsx"]))["Operator Profile"]
    rates = dict(ws.iter_rows(min_row=2, values_only=True))["Occupancy rate "]
    assert rates.splitlines()[0].startswith("Default Occupancy - ")


def test_hotel_sidecars_follow_the_toggles():
    spec = make_spec("hotel", "DBC-M1", seed=4, options={"has_operator": True, "has_amenities": False})
    files = build_files(spec)
    assert "07 Operator simulation.pdf" in files
    assert "08 Amenities simulation.pdf" not in files
    assert not any(n.startswith(("05 ", "06 ")) for n in files)  # M1: no guest simulation


def test_json_round_trip_rebuilds_the_same_workbook():
    spec = make_spec("residential", "DBC-M2", seed=21)
    files = build_files(spec)
    again = build_files(json.loads(files["project.json"]))
    a = openpyxl.load_workbook(io.BytesIO(files["02 Unit mix workbook.xlsx"]))
    b = openpyxl.load_workbook(io.BytesIO(again["02 Unit mix workbook.xlsx"]))
    for name in a.sheetnames:
        assert list(a[name].values) == list(b[name].values)


def test_edited_floors_change_the_travel_height():
    spec = make_spec("office", "DBC-M1", seed=3)
    before = derive(spec)["passenger_travel_m"]
    for f in spec["floors"]:
        if f.get("occupied"):
            f["height_m"] += 1.0
    assert derive(spec)["passenger_travel_m"] > before


@pytest.mark.parametrize("change,message", [
    (lambda s: s.update(model="DBC-M2"), "needs more than"),
    (lambda s: [f.update(occupied=False) for f in s["floors"]], "occupied"),
    (lambda s: s["floors"].append(dict(s["floors"][0])), "unique"),
    (lambda s: s.update(asset="Labour Accommodation"), "Unknown classification"),
])
def test_validate_reports_bad_edits(change, message):
    spec = make_spec("residential", "DBC-M1", seed=8)
    change(spec)
    assert any(message in e for e in validate(spec))


def test_retail_has_no_m2():
    with pytest.raises(ValueError):
        make_spec("retail", "DBC-M2", seed=1)
