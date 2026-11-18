"""Choosing files and sheets, simulation settings and edits, the optional occupancy sheet."""

import io

import openpyxl
import pdfplumber
import pytest

from testgen import sim_table
from testgen.bundle import build_files, file_names, top
from testgen.excel import workbook_sheets
from testgen.spec import guest_awt, make_spec, simulation_tables, validate


def _sheets(files):
    return openpyxl.load_workbook(io.BytesIO(files["02 Unit mix workbook.xlsx"])).sheetnames


def _text(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(page.extract_text() for page in doc.pages)


def test_every_planned_file_is_built_unless_left_out():
    spec = make_spec("hotel", "DBC-M2", seed=4, options={"has_operator": True, "has_amenities": True})
    assert {top(n) for n in build_files(spec)} == set(file_names(spec))
    assert {n for n in build_files(spec) if top(n) == "04 Logos"} == {
        "04 Logos/Client logo.png", "04 Logos/Architect logo.png", "04 Logos/Lead consultant logo.png"}
    left_out = ["03 Images", "07 Operator simulation.pdf", "Entrance Bias", "Operator Profile"]
    spec = make_spec("hotel", "DBC-M2", seed=4, options={"has_operator": True, "has_amenities": True,
                                                         "skip_outputs": left_out})
    files = build_files(spec)
    assert {top(n) for n in files} == set(file_names(spec)) - set(left_out)
    assert _sheets(files) == [s for s in workbook_sheets(spec) if s not in left_out]
    assert "07 Operator simulation.pdf" not in files["00 KARR AI form values.txt"].decode()


def test_the_schedule_and_stacking_stay_first_in_the_workbook():
    spec = make_spec("hotel_apartments", "DBC-M2", seed=2,
                     options={"has_operator": True, "has_amenities": True, "skip_outputs": []})
    names = _sheets(build_files(spec))
    assert names[:2] == ["Room Schedule", "Lifts Stacking Mix"]
    assert names[-1] == "Public Area Occupancy"


def test_the_occupancy_sheet_is_off_unless_ticked():
    spec = make_spec("hotel_apartments", "DBC-M1", seed=2, options={"has_amenities": True})
    assert "Public Area Occupancy" in workbook_sheets(spec)
    assert "Public Area Occupancy" not in _sheets(build_files(spec))


def test_the_occupancy_sheet_has_the_headers_karr_ai_looks_for():
    spec = make_spec("hotel_apartments", "DBC-M1", seed=2, options={"has_amenities": True, "skip_outputs": []})
    ws = openpyxl.load_workbook(io.BytesIO(build_files(spec)["02 Unit mix workbook.xlsx"]))["Public Area Occupancy"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[1] == ("Area", "Occupancy (m² per person)")
    assert {r[0] for r in rows[2:]} == {r["area"] for r in spec["public_area_occupancy"]}


@pytest.mark.parametrize("asset_key", ["residential", "office", "hotel", "car_parking", "schools"])
def test_simulation_settings_are_honoured(asset_key):
    opts = {"sim_lifts": 4, "sim_speeds": [2.5, 3.5], "sim_capacities": [1600]}
    spec = make_spec(asset_key, "DBC-M2", seed=3, options=opts)
    label, rows = simulation_tables(spec)[0]
    assert sorted({r["lifts"] for r in rows}) == [3, 4, 5]
    assert sorted({r["speed"] for r in rows}) == [2.5, 3.5]
    assert {r["capacity"] for r in rows} == {1600}
    limit = guest_awt(spec)
    assert all(r["awt"] > limit for r in rows if r["lifts"] == 3)
    assert all(r["awt"] <= limit for r in rows if r["lifts"] >= 4)


@pytest.mark.parametrize("asset_key,model,opts", [
    ("residential", "DBC-M2", {}), ("hotel", "DBC-M1", {"has_operator": True, "has_amenities": True}),
    ("car_parking", "DBC-M2", {}),
])
def test_an_unchanged_simulation_table_gives_back_the_same_rows(asset_key, model, opts):
    spec = make_spec(asset_key, model, seed=5, options=opts)
    for label, rows in simulation_tables(spec):
        assert sim_table.from_table(sim_table.to_table(rows)) == rows


def test_edited_simulation_rows_reach_the_pdf():
    spec = make_spec("hotel", "DBC-M2", seed=6)
    label, rows = simulation_tables(spec)[0]
    table = sim_table.to_table(rows)
    table[0]["Avg wait (s)"] = 99.9
    table.append(dict(table[-1], Lifts=9))
    sim_table.set_rows(spec, label, sim_table.from_table(table))
    assert validate(spec) == []
    new_rows = dict(simulation_tables(spec))[label]
    assert new_rows[0]["awt"] == 99.9 and new_rows[-1]["lifts"] == 9
    text = _text(build_files(spec)["05 Guest simulation.pdf"])
    assert "99.9" in text


def test_too_many_simulation_rows_are_reported():
    spec = make_spec("residential", "DBC-M2", seed=3)
    label, rows = simulation_tables(spec)[0]
    sim_table.set_rows(spec, label, rows * 10)
    assert any("at most" in e for e in validate(spec))
