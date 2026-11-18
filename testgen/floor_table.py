"""Floors as flat tables (one row per floor) for the app's sheet editors.

Three views of the same floors: the schedule sheet (unit mix / room schedule /
parking mix), the Lifts Stacking Mix (occupied / boarding) and the Amenities
Stacking Mix. `to_rows` flattens a view (unit counts become one column per unit
type) and carries each floor's index in `ROW_ID`; `from_rows` writes edited
rows back, keeping every field the view does not show.
"""

from __future__ import annotations

import math

from .assets import asset_for

ROW_ID = "_floor"
_SCHEDULE_EXTRA = {
    "residential": [("cars", "Cars")],
    "office": [("area_m2", "Area (m²)"), ("cars", "Cars")],
    "hotel": [("area_m2", "Public area (m²)"), ("cars", "Cars")],
    "hotel_apartments": [("area_m2", "Public area (m²)"), ("cars", "Cars")],
    "car_parking": [("cars", "Cars")],
    "retail": [("area_m2", "Area (m²)"), ("cars", "Cars")],
    "schools": [("classrooms", "Classrooms"), ("students_per_classroom", "Students / room"),
                ("staff", "Staff"), ("cars", "Cars")],
    "universities": [("classrooms", "Lecture rooms"), ("students_per_classroom", "Students / room"),
                     ("staff", "Staff"), ("cars", "Cars")],
}
FLAGS = {"occupied", "boarding", "amenity", "rooftop"}
WHOLE = {"cars", "classrooms", "students_per_classroom", "staff"}


def schedule_columns(spec: dict) -> list[tuple[str, str]]:
    """(field, label) pairs of the schedule sheet; unit types appear as (type, type)."""
    units = [(t, t) for t in spec.get("unit_types") or []]
    return [("name", "Floor"), ("height_m", "Height (m)"), ("use", "Use"), *units,
            *_SCHEDULE_EXTRA[asset_for(spec["asset"]).key]]


def stacking_columns(spec: dict) -> list[tuple[str, str]]:
    return [("name", "Floor"), ("occupied", "Occupied"), ("boarding", "Boarding")]


def amenity_columns(spec: dict) -> list[tuple[str, str]]:
    return [("name", "Floor"), ("amenity", "Amenity floor")]


def to_rows(spec: dict, columns: list[tuple[str, str]]) -> list[dict]:
    types = set(spec.get("unit_types") or [])
    rows = []
    for i, f in enumerate(spec["floors"]):
        row = {ROW_ID: i}
        for field, label in columns:
            if field in types:
                row[label] = (f.get("units") or {}).get(field, 0)
            elif field in FLAGS:
                row[label] = bool(f.get(field))
            else:
                row[label] = f.get(field)
        rows.append(row)
    return rows


def _blank(value) -> bool:
    """Empty cell: None, '', NaN, or pandas' NA / NaT."""
    if value is None or type(value).__name__ in ("NAType", "NaTType"):
        return True
    return (isinstance(value, float) and math.isnan(value)) or (isinstance(value, str) and not value.strip())


def _cell(field: str, value):
    """An edited cell as the floor stores it (None = leave the field out)."""
    if field in FLAGS:
        return False if _blank(value) else bool(value)
    if _blank(value):
        return "" if field == "use" else None
    if field in ("name", "use"):
        return str(value).strip()
    if field in WHOLE:
        return int(value)
    number = float(value)
    return int(number) if number.is_integer() and field != "height_m" else round(number, 3)


def from_rows(spec: dict, rows: list[dict], columns: list[tuple[str, str]]) -> list[dict]:
    """Edited rows back to floors.

    A row keeps the floor it came from (by `ROW_ID`) and changes only the shown
    fields; a new row starts as an empty floor; a deleted row drops its floor.
    """
    types = list(spec.get("unit_types") or [])
    floors = []
    for row in rows:
        shown = [row.get(label) for _, label in columns]
        if all(_blank(v) or v is False for v in shown):
            continue  # an empty row the editor added
        source = row.get(ROW_ID)
        floor = dict(spec["floors"][int(source)]) if not _blank(source) else {"occupied": False, "boarding": False}
        units = dict(floor.get("units") or {t: 0 for t in types})
        for field, label in columns:
            value = row.get(label)
            if field in types:
                units[field] = 0 if _blank(value) else int(value)
                continue
            new = _cell(field, value)
            if new is False and field not in floor:
                continue  # an unticked flag the floor never had
            if new is None and field != "height_m":
                floor.pop(field, None)  # a blank name stays missing so validation asks for one
            else:
                floor[field] = new
        if types:
            floor["units"] = units
        floors.append(floor)
    return floors


def _contents(asset_key: str, f: dict) -> str:
    units = sum((f.get("units") or {}).values())
    parts = []
    if units:
        parts.append(f"{units} {'keys' if asset_key == 'hotel' else 'apartments'}")
    if f.get("classrooms"):
        parts.append(f"{f['classrooms']} rooms × {f.get('students_per_classroom', 0)}")
    if f.get("area_m2"):
        parts.append(f"{f['area_m2']:,.0f} m²")
    if f.get("cars"):
        parts.append(f"{f['cars']} cars")
    return " · ".join(parts)


def floor_groups(spec: dict) -> list[dict]:
    """Runs of identical floors (top to bottom) for a compact building stack.

    Each group: top / bottom floor names, count, use, kind (occupied, boarding
    or other), height_m and a short contents line.
    """
    asset = asset_for(spec["asset"])
    groups: list[dict] = []
    for f in spec["floors"]:
        kind = "occupied" if f.get("occupied") else "boarding" if f.get("boarding") else "other"
        contents = _contents(asset.key, f)
        same = (f["use"], kind, f.get("height_m"), contents)
        if groups and groups[-1]["_same"] == same:
            groups[-1]["bottom"] = f["name"]
            groups[-1]["count"] += 1
            continue
        groups.append({"_same": same, "top": f["name"], "bottom": f["name"], "count": 1, "use": f["use"],
                       "kind": kind, "height_m": f.get("height_m"), "contents": contents})
    for g in groups:
        del g["_same"]
    return groups
