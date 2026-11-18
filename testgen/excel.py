"""Combined unit-mix workbook (KARR AI document type `unit_mix_excel`).

Sheet order matters: KARR AI finds sheets by keyword in order, so the
schedule comes first, then `Lifts Stacking Mix`, then the optional
`Amenities Stacking Mix`, `Entrance Bias`, `Operator Profile` and
`Amenities Profile` (and the optional Hotel Apartments `Public Area Occupancy`).
Layouts copy the sample workbooks KARR AI was built on.
"""

from __future__ import annotations

import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .assets import asset_for

_THIN = Side(style="thin", color="999999")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEAD_FILL = PatternFill("solid", fgColor="DDE6F0")
_TITLE_FONT = Font(bold=True, size=12)
_BOLD = Font(bold=True)
_GROUND_RE = re.compile(r"^(gf|g|ground|ground floor|level g)$", re.IGNORECASE)


def ground_index(floors: list[dict]) -> int:
    for i, f in enumerate(floors):
        if _GROUND_RE.match(str(f["name"]).strip()):
            return i
    return next(i for i, f in enumerate(floors) if f.get("boarding"))


def floor_levels(floors: list[dict]) -> list[float]:
    """Finished floor level (m) of each floor, ground = 0."""
    g = ground_index(floors)
    levels = [0.0] * len(floors)
    for i in range(g - 1, -1, -1):
        levels[i] = levels[i + 1] + float(floors[i + 1].get("height_m") or 0)
    for i in range(g + 1, len(floors)):
        levels[i] = levels[i - 1] - float(floors[i].get("height_m") or 0)
    return [round(v, 2) for v in levels]


def _write_table(ws, title: str, headers: list[str], rows: list[list], total: list | None = None) -> None:
    ws.append([title])
    ws["A1"].font = _TITLE_FONT
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=2, column=c)
        cell.font = _BOLD
        cell.fill = _HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    for r in rows:
        ws.append(r)
    if total:
        ws.append(total)
        for c in range(1, len(headers) + 1):
            ws.cell(row=ws.max_row, column=c).font = _BOLD
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
        for cell in row:
            cell.border = _BORDER
    for c, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(r[c - 1])) for r in rows if c - 1 < len(r) and r[c - 1] is not None])
        ws.column_dimensions[get_column_letter(c)].width = min(max(10, width + 2), 48)
    ws.row_dimensions[2].height = 32


def _yn(flag) -> str:
    return "Y" if flag else "N"


# ----------------------------------------------------------------- schedules

def _residential(ws, spec):
    types = spec["unit_types"]
    floors = spec["floors"]
    ffl = floor_levels(floors)
    headers = ["Level", "Floor to Floor Height (m)", "FFL (m)", "Car parking qty",
               "Description", *types, "Total number of units"]
    rows = []
    for f, lvl in zip(floors, ffl):
        units = [f.get("units", {}).get(t, 0) for t in types]
        rows.append([f["name"], f.get("height_m"), lvl, f.get("cars") or None, f["use"], *units, sum(units)])
    totals = [sum(r[5 + i] for r in rows) for i in range(len(types))]
    total = ["Total", None, None, sum(f.get("cars") or 0 for f in floors), None, *totals, sum(totals)]
    _write_table(ws, f"Unit Mix - {spec['project_info']['project_name']}", headers, rows, total)


def _office(ws, spec):
    floors = spec["floors"]
    headers = ["Floor Reference", "Floor Height (m)", "Utility", "Parking", "GA (sq. m)"]
    rows = [[f["name"], f.get("height_m"), f["use"], f.get("cars") or None,
             f.get("area_m2") if f.get("occupied") else None] for f in floors]
    total = ["Total", None, None, sum(f.get("cars") or 0 for f in floors),
             sum(f.get("area_m2") or 0 for f in floors if f.get("occupied"))]
    _write_table(ws, f"Building Overview - {spec['project_info']['project_name']}", headers, rows, total)


def _hotel(ws, spec):
    # Room-type columns only: a "Keys pop (x1.8)" column (as in some old samples)
    # is read by KARR AI as another room column and doubles the population.
    types = spec["unit_types"]
    floors = spec["floors"]
    ffl = floor_levels(floors)
    headers = ["Floor Reference", "Floor Height (m)", "Floor Level (m)", "Utility", *types, "Area"]
    rows = []
    for f, lvl in zip(floors, ffl):
        if f.get("area_m2"):
            vals = ["Area"] * len(types) + [f["area_m2"]]
        elif f.get("cars"):
            vals = ["Valet parking only"] * len(types) + [None]
        elif f.get("boarding") and not f.get("rooftop"):
            vals = ["Main lobby"] * len(types) + [None]
        else:
            vals = [f.get("units", {}).get(t, 0) for t in types] + [None]
        rows.append([f["name"], f.get("height_m"), lvl, f["use"], *vals])
    totals = [sum(f.get("units", {}).get(t, 0) for f in floors) for t in types]
    _write_table(ws, f"HOTEL - Room schedule - {spec['project_info']['project_name']}", headers, rows,
                 ["Total", None, None, None, *totals, None])


def _hotel_apartments(ws, spec):
    types = spec["unit_types"]
    floors = spec["floors"]
    ffl = floor_levels(floors)
    headers = ["Floor Reference", "Floor Height (m)", "Floor Level (m)", "Utility", *types, "Area"]
    rows = []
    for f, lvl in zip(floors, ffl):
        if f.get("area_m2"):
            vals = ["Area"] * len(types) + [f["area_m2"]]
        elif f.get("boarding") and not f.get("cars") and not f.get("rooftop"):
            vals = ["Main lobby"] * len(types) + [None]
        else:
            vals = [f.get("units", {}).get(t, 0) for t in types] + [None]
        rows.append([f["name"], f.get("height_m"), lvl, f["use"], *vals])
    totals = [sum(f.get("units", {}).get(t, 0) for f in floors) for t in types]
    _write_table(ws, f"HOTEL Apts - Unit mix - {spec['project_info']['project_name']}", headers, rows,
                 ["Total", None, None, None, *totals, None])


def _car_parking(ws, spec):
    floors = spec["floors"]
    headers = ["Level", "Floor height in mm", "Car Parking"]
    rows = [[f["name"], int(round(f["height_m"] * 1000)) if f.get("height_m") else None, f.get("cars", 0)]
            for f in floors]
    _write_table(ws, "Car Parking Mix", headers, rows, ["Total", None, sum(f.get("cars", 0) for f in floors)])


def _retail(ws, spec):
    floors = spec["floors"]
    headers = ["Level", "Utility", "Area in sqm.", "No of Parking", "Floor height (m)"]
    rows = [[f["name"], f["use"], f.get("area_m2"), f.get("cars"),
             f.get("height_m")] for f in floors]
    total = ["Total", None, sum(f.get("area_m2") or 0 for f in floors), sum(f.get("cars") or 0 for f in floors), None]
    _write_table(ws, "Retail Mix", headers, rows, total)


def _education(ws, spec):
    floors = spec["floors"]
    has_parking = any(f.get("cars") for f in floors)
    headers = ["Level", "Floor height", "Details", "Qty of class rooms", "Students per class room",
               "Staff", "Total Occupancy students +Staff"] + (["No of Parking"] if has_parking else [])
    rows = []
    for f in floors:
        if f.get("classrooms"):
            occ = f["classrooms"] * f["students_per_classroom"] + f.get("staff", 0)
            row = [f["name"], f["height_m"], f["use"], f["classrooms"], f["students_per_classroom"],
                   f.get("staff", 0), occ]
        else:
            row = [f["name"], f["height_m"], f["use"], None, None, None, 0]
        if has_parking:
            row.append(f.get("cars"))
        rows.append(row)
    total = ["Total", None, None, None, None, None, sum(r[6] for r in rows)]
    if has_parking:
        total.append(sum(f.get("cars") or 0 for f in floors))
    _write_table(ws, f"{spec['project_info']['project_name']} - Bldg details / Area Schedule / Occupancy",
                 headers, rows, total)


_SCHEDULES = {
    "residential": (_residential, "Unit Mix"),
    "office": (_office, "Unit Mix"),
    "hotel": (_hotel, "Room Schedule"),
    "hotel_apartments": (_hotel_apartments, "Room Schedule"),
    "car_parking": (_car_parking, "Parking Mix"),
    "retail": (_retail, "Unit Mix"),
    "schools": (_education, "Unit Mix"),
    "universities": (_education, "Unit Mix"),
}

_OCCUPIED_WORD = {"residential": "Occupied", "hotel": "Occupied", "hotel_apartments": "Occupied"}


# -------------------------------------------------------------- other sheets

def _stacking(ws, spec):
    word = _OCCUPIED_WORD.get(asset_for(spec["asset"]).key, "Serving")
    ws.append(["Lifts Stacking Mix Guest Passenger lifts"])
    ws["A1"].font = _TITLE_FONT
    ws.append(["Building", "Usage", None])
    ws.append(["Floor", f"{word} floor", "Boarding floor"])
    for c in range(1, 4):
        ws.cell(row=3, column=c).font = _BOLD
        ws.cell(row=3, column=c).fill = _HEAD_FILL
    for f in spec["floors"]:
        ws.append([f["name"], _yn(f.get("occupied")), _yn(f.get("boarding"))])
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16


def _amenities_stacking(ws, spec):
    floors = spec["floors"]
    first = next(i for i, f in enumerate(floors) if f.get("amenity"))
    ws.append(["Lifts Stacking Mix Public amenities Passenger lifts"])
    ws["A1"].font = _TITLE_FONT
    ws.append(["Building", "Usage", None])
    ws.append(["Floor", "Occupied floor", "Boarding floor"])
    for f in floors[first:]:
        board = f.get("boarding") and not f.get("rooftop")
        ws.append([f["name"], _yn(f.get("amenity")), _yn(board)])
    ws.column_dimensions["A"].width = 18


def _entrance_bias(ws, spec, population):
    rows = spec["entrance_bias"]
    ws.append(["Entrance bias"])
    ws["A1"].font = _TITLE_FONT
    ws.append(["Parking or Amenity Levels", "Number of Parking",
               "Population entering through Boarding floors ", "Entrance bias %",
               "Entrance bias % (with ground floor)", "Entrance bias % for traffic study"])
    for c in range(1, 7):
        ws.cell(row=2, column=c).font = _BOLD
        ws.cell(row=2, column=c).fill = _HEAD_FILL
        ws.cell(row=2, column=c).alignment = Alignment(wrap_text=True)
    ground = _GROUND_RE
    for r in rows:
        frac = r["percent"] / 100
        is_ground = bool(ground.match(str(r["floor"]).strip()))
        ws.append([r["floor"], r.get("parking", 0), round(population * frac, 1),
                   None if is_ground else frac, frac, frac])
    no_ground = sum(r["percent"] for r in rows if not ground.match(str(r["floor"]).strip())) / 100
    ws.append(["Total", sum(r.get("parking", 0) for r in rows), round(population, 1),
               round(no_ground, 4), 1, 1])
    for row in ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=4, max_col=6):
        for cell in row:
            cell.number_format = "0.0%"
    ws.column_dimensions["A"].width = 26
    for col in "BCDEF":
        ws.column_dimensions[col].width = 18
    ws.row_dimensions[2].height = 45


def _profile(ws, profile: dict):
    rates = "\n".join(f"{k} - {v:g}" for k, v in profile["occupancy_rates"].items())
    ws.append([profile["title"], None])
    ws["A1"].font = _TITLE_FONT
    ws.append(["Design Guide ", profile["design_guide"]])
    ws.append(["Occupancy rate ", rates])
    ws.append(["Occupancy of the Building", profile["building_occupancy"]])
    ws.append(["Cabin Loading Factor", profile["cabin_loading_factor"]])
    ws.append(["Handling Capacity", profile["handling_capacity"]])
    ws.append(["Average Waiting Time  ", f"≤ {profile['awt_s']} sec"])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 44
    for r in range(2, 8):
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")


def _public_area_occupancy(ws, spec):
    """Optional Hotel Apartments sheet: m² per person for each public area (KARR AI overrides)."""
    _write_table(ws, "Public area occupancy", ["Area", "Occupancy (m² per person)"],
                 [[r["area"], r["m2_per_person"]] for r in spec["public_area_occupancy"]])


def workbook_sheets(spec: dict) -> list[str]:
    """Sheets this project's workbook can carry, in the order KARR AI searches them."""
    asset = asset_for(spec["asset"])
    b = spec["building"]
    names = [_SCHEDULES[asset.key][1], "Lifts Stacking Mix"]
    if asset.hotel_like and b.get("has_amenities") and any(f.get("amenity") for f in spec["floors"]):
        names.append("Amenities Stacking Mix")
    if spec.get("entrance_bias"):
        names.append("Entrance Bias")
    if asset.hotel_like and b.get("has_operator") and spec.get("operator_profile"):
        names.append("Operator Profile")
    if asset.hotel_like and b.get("has_amenities") and spec.get("amenities_profile"):
        names.append("Amenities Profile")
    if asset.key == "hotel_apartments" and spec.get("public_area_occupancy"):
        names.append("Public Area Occupancy")
    return names


def build_workbook(spec: dict, population: float, skip: set[str] | frozenset = frozenset()) -> bytes:
    """The combined workbook; sheets named in `skip` are left out."""
    asset = asset_for(spec["asset"])
    schedule_writer, schedule = _SCHEDULES[asset.key]
    writers = {
        schedule: lambda ws: schedule_writer(ws, spec),
        "Lifts Stacking Mix": lambda ws: _stacking(ws, spec),
        "Amenities Stacking Mix": lambda ws: _amenities_stacking(ws, spec),
        "Entrance Bias": lambda ws: _entrance_bias(ws, spec, population),
        "Operator Profile": lambda ws: _profile(ws, spec["operator_profile"]),
        "Amenities Profile": lambda ws: _profile(ws, spec["amenities_profile"]),
        "Public Area Occupancy": lambda ws: _public_area_occupancy(ws, spec),
    }
    wb = Workbook()
    first = True
    for name in workbook_sheets(spec):
        if name in skip:
            continue
        ws = wb.active if first else wb.create_sheet()
        ws.title = name
        writers[name](ws)
        first = False
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
