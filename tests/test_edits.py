"""The result views' editors: applied unchanged they give back the same project, and
their changes land in the spec."""

import pytest

from testgen import edits
from testgen.assets import ASSETS
from testgen.bundle import build_files
from testgen.spec import make_spec, validate

COMBOS = [(k, m) for k, a in ASSETS.items() for m in (["DBC-M1", "DBC-M2"] if a.supports_m2 else ["DBC-M1"])]


def _values(shape):
    fields = {f["name"]: f["value"] for row in shape["fields"] for f in row}
    rows = [dict(r) for r in shape["table"]["rows"]] if shape["table"] else []
    return fields, rows


@pytest.mark.parametrize("asset_key,model", COMBOS)
def test_every_editor_applied_unchanged_gives_back_the_same_project(asset_key, model):
    hotel = ASSETS[asset_key].hotel_like
    spec = make_spec(asset_key, model, seed=3, options={"has_operator": True, "has_amenities": True} if hotel else {})
    views = [v for v in edits.view_names(spec, build_files(spec)) if edits.editor(spec, v)]

    assert len(views) >= 3  # schedule, stacking, architect report at least
    for view in views:
        new, recompute = edits.change(spec, view, *_values(edits.editor(spec, view)))
        assert new == spec, view
        assert recompute == (view in (edits.workbook_sheets(spec)[0], "Lifts Stacking Mix", "Amenities Stacking Mix"))


def test_edits_land_in_the_spec():
    spec = make_spec("hotel", "DBC-M2", seed=4, options={"has_operator": True})
    fields, rows = _values(edits.editor(spec, "Operator Profile"))
    fields["Waiting time (s)"] = 45
    rows.append({"Type": "4BR", "Occupancy rate": 4.5})
    new, _ = edits.change(spec, "Operator Profile", fields, rows)
    assert new["operator_profile"]["awt_s"] == 45 and new["operator_profile"]["occupancy_rates"]["4BR"] == 4.5

    fields, rows = _values(edits.editor(spec, "Lifts Stacking Mix"))
    for row in rows:
        row["Boarding"] = False
    new, recompute = edits.change(spec, "Lifts Stacking Mix", fields, rows)
    assert recompute and "At least one floor must be a boarding floor." in validate(new)

    fields, rows = _values(edits.editor(spec, "Guest simulation"))
    new, _ = edits.change(spec, "Guest simulation", fields, rows[:1])
    assert len(new["simulations"]["guest"]["single"]) == 1
