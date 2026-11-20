"""The result views as plain data: which views a project has, a sheet as a grid,
and each view's editor with the way its edited values become a new spec.

A view is "Files", a workbook sheet, "Architect report", a simulation (named as
`spec.simulation_tables` names it), "Images", "Logos", "Form values" or "JSON".
An editor is rows of fields above a table; values are keyed by their labels.
The Streamlit app's views.py and KARR AI's Archies Architect page draw them.
"""

from __future__ import annotations

import copy
import io
from dataclasses import asdict, dataclass

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from . import floor_table, sim_table
from .bundle import ARCHITECT, LOGOS, WORKBOOK, simulation_file_name, skipped, top
from .excel import workbook_sheets
from .spec import simulation_tables

ARCHITECT_REPORT = "Architect report"
STORY_TEXT = [("vision", "Design intent"), ("site", "Site and context"), ("massing", "Massing and core"),
              ("facade", "Facade"), ("amenities", "Amenities"), ("sustainability", "Sustainability")]
PROFILES = {"Operator Profile": "operator_profile", "Amenities Profile": "amenities_profile"}


@dataclass(frozen=True)
class Column:
    """One editable value: a table column or a field above the table."""

    name: str  # its label, and its key in a row or in the fields
    kind: str  # text | long (several lines) | number | whole | tick
    required: bool = False
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    narrow: bool = False
    wide: bool = False
    locked: bool = False  # shown, not editable
    hidden: bool = False  # carried in the row, not shown


def view_names(spec: dict, files: dict[str, bytes]) -> list[str]:
    names = []
    if WORKBOOK in files:
        names += [s for s in workbook_sheets(spec) if s not in skipped(spec)]
    if ARCHITECT in files:
        names.append(ARCHITECT_REPORT)
    names += [label for label, _ in simulation_tables(spec) if simulation_file_name(spec, label) in files]
    folders = ["Logos"] if any(top(n) == LOGOS for n in files) else []
    return ["Files", *names, "Images", *folders, "Form values", "JSON"]


def sheet_grid(data: bytes, sheet: str) -> list[list[str]]:
    """A workbook sheet's cells as text, row by row (columns A, B, ... from `column_letters`)."""
    ws = load_workbook(io.BytesIO(data), data_only=True)[sheet]
    return [["" if v is None else str(v) for v in row] for row in ws.iter_rows(values_only=True)]


def column_letters(width: int) -> list[str]:
    return [get_column_letter(i + 1) for i in range(width)]


# ------------------------------------------------------------------ editors

def _floor_view(spec: dict, view: str):
    """(columns of the floor table, whether floors can be added), or None for another view."""
    if view == workbook_sheets(spec)[0]:
        return floor_table.schedule_columns, True
    return {"Lifts Stacking Mix": (floor_table.stacking_columns, False),
            "Amenities Stacking Mix": (floor_table.amenity_columns, False)}.get(view)


def _floor_columns(spec: dict, columns_of, add_rows: bool) -> list[Column]:
    out = [Column(floor_table.ROW_ID, "whole", hidden=True)]
    for field, label in columns_of(spec):
        if field in floor_table.FLAGS:
            out.append(Column(label, "tick"))
        elif field == "name":
            out.append(Column(label, "text", required=True, narrow=True, locked=not add_rows))
        elif field == "use":
            out.append(Column(label, "text", wide=True))
        elif field == "height_m":
            out.append(Column(label, "number", lo=0.0, hi=20.0, step=0.05))
        else:
            out.append(Column(label, "whole", lo=0))
    return out


def _table(columns: list[Column], rows: list[dict], add_rows: bool = False, total_percent: str | None = None) -> dict:
    return {"columns": [asdict(c) for c in columns], "rows": rows, "add_rows": add_rows,
            "total_percent": total_percent}


def _field(column: Column, value) -> dict:
    return {**asdict(column), "value": value}


def editor(spec: dict, view: str) -> dict | None:
    """The view's editor, or None when it has none.

    fields: rows of fields above the table, each a column with its `value`.
    table: columns, rows, whether rows can be added or removed, and a column whose
    total shows under the table as a percent; None when there is no table.
    """
    floors = _floor_view(spec, view)
    if floors:
        columns_of, add_rows = floors
        columns = columns_of(spec)
        return {"fields": [], "table": _table(_floor_columns(spec, columns_of, add_rows),
                                              floor_table.to_rows(spec, columns), add_rows)}
    if view == "Entrance Bias":
        columns = [Column("Floor", "text", required=True), Column("Parking", "whole", lo=0),
                   Column("Entrance bias (%)", "number", lo=0)]
        rows = [{"Floor": r["floor"], "Parking": r.get("parking", 0), "Entrance bias (%)": r["percent"]}
                for r in spec["entrance_bias"]]
        return {"fields": [], "table": _table(columns, rows, True, "Entrance bias (%)")}
    if view in PROFILES:
        p = spec[PROFILES[view]]
        fields = [
            [_field(Column("Title", "text"), p["title"]), _field(Column("Design guide", "text"), p["design_guide"])],
            [_field(Column("Building occupancy", "text"), p["building_occupancy"]),
             _field(Column("Cabin loading factor", "number", lo=0.0, hi=1.0, step=0.05), float(p["cabin_loading_factor"])),
             _field(Column("Handling capacity", "number", lo=0.0, hi=1.0, step=0.01), float(p["handling_capacity"])),
             _field(Column("Waiting time (s)", "whole", lo=1, hi=300, step=1), int(p["awt_s"]))],
        ]
        rows = [{"Type": k, "Occupancy rate": v} for k, v in p["occupancy_rates"].items()]
        columns = [Column("Type", "text"), Column("Occupancy rate", "number", lo=0)]
        return {"fields": fields, "table": _table(columns, rows, True)}
    if view == "Public Area Occupancy":
        rows = [{"Area": r["area"], "m² per person": r["m2_per_person"]} for r in spec["public_area_occupancy"]]
        columns = [Column("Area", "text"), Column("m² per person", "number", lo=0)]
        return {"fields": [], "table": _table(columns, rows, True)}
    if view == ARCHITECT_REPORT:
        return {"fields": [[_field(Column(label, "long"), spec["story"].get(key, ""))] for key, label in STORY_TEXT],
                "table": None}
    sims = dict(simulation_tables(spec))
    if view in sims:
        columns = [Column(label, "whole" if whole else "number", lo=0, hidden=key not in sim_table.REPORTED)
                   for key, label, whole in sim_table.COLUMNS]
        return {"fields": [], "table": _table(columns, sim_table.to_table(sims[view]), True)}
    return None


def _blank(value) -> bool:
    return floor_table._blank(value)


def _text(value) -> str:
    return "" if value is None else str(value)


def _amount(value, whole: bool = False):
    """A table number; a blank cell counts as 0."""
    if _blank(value):
        return 0
    return int(value) if whole else float(value)


def _field_number(fields: dict, name: str, whole: bool = False):
    value = fields.get(name)
    if _blank(value):
        raise ValueError(f"{name} needs a number.")
    return int(value) if whole else float(value)


def change(spec: dict, view: str, fields: dict, rows: list[dict]) -> tuple[dict, bool]:
    """A copy of `spec` with the editor's values in it, and whether its floors changed.

    When they did, `spec.refresh` works out the travel, preliminary lifts, entrance bias
    and simulations again. Rows left empty are dropped. Check the result with `validate`.
    """
    new = copy.deepcopy(spec)
    floors = _floor_view(spec, view)
    if floors:
        new["floors"] = floor_table.from_rows(spec, rows, floors[0](spec))
        return new, True
    if view == "Entrance Bias":
        new["entrance_bias"] = [
            {"floor": str(r["Floor"]).strip(), "parking": _amount(r.get("Parking"), True),
             "percent": round(_amount(r.get("Entrance bias (%)")), 2)}
            for r in rows if not _blank(r.get("Floor"))]
    elif view in PROFILES:
        key = PROFILES[view]
        new[key] = dict(spec[key], title=_text(fields.get("Title")), design_guide=_text(fields.get("Design guide")),
                        building_occupancy=_text(fields.get("Building occupancy")),
                        cabin_loading_factor=_field_number(fields, "Cabin loading factor"),
                        handling_capacity=_field_number(fields, "Handling capacity"),
                        awt_s=_field_number(fields, "Waiting time (s)", True),
                        occupancy_rates={str(r["Type"]).strip(): _amount(r.get("Occupancy rate"))
                                         for r in rows if not _blank(r.get("Type"))})
    elif view == "Public Area Occupancy":
        new["public_area_occupancy"] = [{"area": str(r["Area"]).strip(), "m2_per_person": _amount(r.get("m² per person"))}
                                        for r in rows if not _blank(r.get("Area"))]
    elif view == ARCHITECT_REPORT:
        new["story"].update({key: _text(fields.get(label)) for key, label in STORY_TEXT})
    elif view in dict(simulation_tables(spec)):
        sim_table.set_rows(new, view, sim_table.from_table(rows))
    else:
        raise ValueError(f"{view} has no editor.")
    return new, False
