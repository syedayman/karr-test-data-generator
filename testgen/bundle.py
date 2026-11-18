"""Turn a spec into the files a tester uploads to KARR AI, plus a form-values sheet."""

from __future__ import annotations

import io
import json
import re
import zipfile

from . import images
from .architect_pdf import build_architect_pdf
from .assets import asset_for
from .excel import build_workbook
from .simulation_pdf import build_simulation_pdf
from .spec import derive, karr_entrance_bias, lift_people, passenger_served, simulation_tables


def _yes(v) -> str:
    return "Yes" if v else "No"


def form_values(spec: dict, d: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    """KARR AI setup form, section by section, as (label, value) pairs."""
    asset = asset_for(spec["asset"])
    info, b, vt, sp = spec["project_info"], spec["building"], spec["vt_criteria"], spec["space_planning"]
    model_txt = "DBC Method 1 (M1)" if spec["model"] == "DBC-M1" else "DBC Method 2 (M2)"
    pi = [
        ("Model (New project screen)", model_txt),
        ("Project name", info["project_name"]),
        ("Employer/Client/Developer", info["employer_client_developer"]),
        ("Architect", info["architect"]),
        ("Lead consultant", info["lead_consultant"]),
        ("Project location", info["project_location"]),
        ("Project classification", info["project_classification"]),
    ]
    if asset.key == "hotel":
        pi.append(("Hotel star rating", f"{info['hotel_star_rating']} Star"))
    if asset.key == "car_parking":
        pi.append(("Car parking facility type", info["car_parking_facility_type"]))
        if spec["model"] == "DBC-M2":
            pi.append(("Escalators present", _yes(info.get("car_parking_has_escalators"))))
    pi += [
        ("Header text", info["header_text"]),
        ("Footer text", info["footer_text"]),
        ("Revision details", info["revision_details"]),
        ("Project address", info["project_address"]),
        ("Project type", info["project_type"]),
        ("Reference", info["reference"]),
        ("Author", info["author"]),
        ("Approved by", info["approved_by"]),
    ]
    bd = [
        ("No. of passenger lifts in architect's preliminary design", str(b.get("passenger_lifts_prelim"))),
        ("No. of fire/service lifts in architect's preliminary design", str(b.get("fire_service_lifts_prelim"))),
        ("Height category (auto)", d["height_category"]),
        ("Authority exceptions", _yes(b.get("has_authority_exceptions"))),
    ]
    for i, ex in enumerate(b.get("authority_exceptions") or [], start=1):
        bd += [(f"Exception {i} no.", ex["exception_no"]), (f"Exception {i} date", ex["exception_date"]),
               (f"Exception {i} details", ex["details"])]
    if asset.hotel_like:
        bd += [("Operator present", _yes(b.get("has_operator"))), ("Amenities present", _yes(b.get("has_amenities")))]
    vtc = [
        ("Passenger lift travel height (m)", f"{d['passenger_travel_m']}"),
        ("Fire/service lift travel height (m)", f"{d['fire_travel_m']}"),
        ("Elevator grouping", "In-line" if vt.get("elevator_grouping") == "in-line" else "Facing each other"),
        ("Lobby depth (mm)", str(int(round((vt.get("lobby_depth_m") or 0) * 1000)))),
        ("Number of cores / lobbies", str(vt.get("core_count") or 1)),
        ("Serves roof", _yes(vt.get("serves_roof"))),
        ("Multipurpose elevator", _yes(vt.get("multipurpose_elevator"))),
        ("Usable area below pit", _yes(vt.get("usable_area_below_pit"))),
    ]
    spc = [
        ("Machine type", "MRL (machine room-less)" if sp["machine_type"] == "mrl" else "MRA (machine room)"),
        ("Passenger capacity (kg)", f"{sp['passenger_capacity_kg']} (auto-fills)"),
        ("Fire/service capacity (kg)", f"{sp['fire_service_capacity_kg']} (auto-fills)"),
        ("Lift dimensions", "Leave the auto-filled values"),
    ]
    facts = [
        ("Occupied floors", str(d["occupied_floors"])),
        ("Boarding floors", str(d["boarding_floors"])),
        ("Passenger lifts serve", f"{d['passenger_bottom']} to {d['passenger_top']} ({d['stops']} stops)"),
        ("Rough occupied population", str(d["population"])),
        ("Minimum passenger speed (travel / divisor)", f"{d['min_speed_mps']} m/s"),
    ]
    return [("Project information", pi), ("Building data", bd), ("VT criteria", vtc),
            ("Space planning", spc), ("Building facts (for checking the report)", facts)]


def _served_for_sim(spec: dict, asset, entrance_names: set[str]) -> list[dict]:
    floors = spec["floors"]
    top, bottom = passenger_served(spec)
    out = []
    for f in reversed(floors[top:bottom + 1]):
        out.append({"name": f["name"], "height_m": f.get("height_m"),
                    "people": lift_people(spec, f) if f.get("occupied") else 0,
                    "entrance": f["name"] in entrance_names})
    return out


def _entrance(spec: dict) -> list[tuple[str, float]]:
    if spec.get("entrance_bias"):
        return [(r["floor"], r["percent"]) for r in spec["entrance_bias"] if r["percent"] > 0]
    karr = karr_entrance_bias(spec)  # the split KARR AI's Entrance Bias table prints
    if karr:
        return [(r["floor"], float(r["study"])) for r in karr if r["study"] > 0]
    boarding = [f for f in spec["floors"] if f.get("boarding")]
    cars = [f.get("cars") or 0 for f in boarding]
    if not sum(cars):
        share = round(100 / len(boarding), 2)
        return [(f["name"], share) for f in boarding]
    total = sum(cars)
    rows = [(f["name"], round(60 * c / total, 2)) for f, c in zip(boarding, cars) if c]
    ground = next((f["name"] for f in boarding if not f.get("cars")), boarding[0]["name"])
    rows.insert(0, (ground, round(100 - sum(p for _, p in rows), 2)))
    return rows


ARCHITECT = "01 Architect design report.pdf"
WORKBOOK = "02 Unit mix workbook.xlsx"
IMAGES = "03 Images"
LOGOS = "04 Logos"
RENDER = f"{IMAGES}/Project render.png"
PLAN = f"{IMAGES}/Architect plan figure.png"
SECTION = f"{IMAGES}/Architect section figure.png"
CLIENT_LOGO = f"{LOGOS}/Client logo.png"
ARCHITECT_LOGO = f"{LOGOS}/Architect logo.png"
CONSULTANT_LOGO = f"{LOGOS}/Lead consultant logo.png"
FORM_VALUES = "00 KARR AI form values.txt"
PROJECT_JSON = "project.json"

_SIM_FILES = {
    "Morning peak": ("05 Morning peak simulation.pdf", "AM", "Morning up-peak"),
    "Evening peak": ("06 Evening peak simulation.pdf", "EVENING", "Evening peak"),
    "Breaks peak": ("06 Breaks peak simulation.pdf", "BREAKS", "Breaks peak"),
    "Guest simulation": ("05 Guest simulation.pdf", "GUEST", "Two-way"),
    "Operator simulation": ("07 Operator simulation.pdf", "OP", "Two-way (operator criteria)"),
    "Amenities simulation": ("08 Amenities simulation.pdf", "AMEN", "Two-way (public amenities)"),
}


def simulation_file_name(spec: dict, label: str) -> str:
    if label == "Guest simulation" and asset_for(spec["asset"]).key == "car_parking":
        return "05 Simulation.pdf"
    return _SIM_FILES[label][0]


def top(name: str) -> str:
    """The file, or the folder it sits in (what the tester ticks and downloads)."""
    return name.split("/")[0]


def simulation_pdf(spec: dict, label: str, rows: list[dict]) -> bytes:
    """One simulation PDF; `label` as in spec.simulation_tables."""
    asset = asset_for(spec["asset"])
    entrance = _entrance(spec)
    served = _served_for_sim(spec, asset, {n for n, _ in entrance})
    if label == "Amenities simulation":
        amenity = {f["name"] for f in spec["floors"] if f.get("amenity")}
        served = [f for f in served if f["entrance"] or f["name"] in amenity] or served
    btype = {"office": "Office", "hotel": "Hotel", "hotel_apartments": "Hotel",
             "residential": "Residential"}.get(asset.key, "Unspecified")
    _, job_suffix, peak = _SIM_FILES[label]
    job = f"{spec['project_info']['project_name']} {job_suffix}"
    return build_simulation_pdf(job, served, entrance, rows, peak, btype)


def file_names(spec: dict) -> list[str]:
    """Every file and folder this project can have, in upload order."""
    sims = [simulation_file_name(spec, label) for label, _ in simulation_tables(spec)]
    return [ARCHITECT, WORKBOOK, IMAGES, LOGOS, *sims, FORM_VALUES, PROJECT_JSON]


def skipped(spec: dict) -> set[str]:
    """File and sheet names the tester left out."""
    return set((spec.get("outputs") or {}).get("skip") or [])


def build_files(spec: dict, render_png: bytes | None = None) -> dict[str, bytes]:
    """Every file the tester kept (see `skipped`)."""
    d = derive(spec)
    seed = int(spec.get("seed") or 1)
    info = spec["project_info"]
    skip = skipped(spec)
    render = render_png or images.fallback_render(spec, seed)
    section = images.section_figure(spec, d)
    plan = images.plan_figure(spec)
    makers = {
        ARCHITECT: lambda: build_architect_pdf(spec, d, render, section, plan),
        WORKBOOK: lambda: build_workbook(spec, d["population"], skip),
        RENDER: lambda: render,
        PLAN: lambda: plan,
        SECTION: lambda: section,
        CLIENT_LOGO: lambda: images.logo(info["employer_client_developer"], seed + 1),
        ARCHITECT_LOGO: lambda: images.logo(info["architect"], seed + 2),
        CONSULTANT_LOGO: lambda: images.logo(info["lead_consultant"], seed + 3),
    }
    for label, rows in simulation_tables(spec):
        makers[simulation_file_name(spec, label)] = lambda label=label, rows=rows: simulation_pdf(spec, label, rows)
    files = {name: make() for name, make in makers.items() if top(name) not in skip}
    if FORM_VALUES not in skip:
        files[FORM_VALUES] = form_values_text(spec, d, files).encode("utf-8")
    if PROJECT_JSON not in skip:
        files[PROJECT_JSON] = json.dumps(spec, indent=2, ensure_ascii=False).encode("utf-8")
    return files


def folder_zip(files: dict[str, bytes], folder: str) -> bytes:
    """One folder's files as a zip of that folder."""
    return zip_files({name: data for name, data in files.items() if top(name) == folder})


_UPLOAD_TARGET = {
    ARCHITECT: "Documents > Architect's design report",
    WORKBOOK: "Documents > Unit mix / schedule Excel",
    RENDER: "Project information > Report images > Project render",
    PLAN: "Project information > Report images > Architect plan figure",
    SECTION: "Project information > Report images > Architect section figure",
    CLIENT_LOGO: "Project information > Report images > Client logo",
    ARCHITECT_LOGO: "Project information > Report images > Architect logo",
    CONSULTANT_LOGO: "Project information > Report images > Lead consultant logo",
}
_SIM_TARGET = {
    "05": "Building data > Traffic analysis simulation documents",
    "06": "Building data > Traffic analysis simulation documents",
    "07": "Building data > Operator simulation PDF",
    "08": "Building data > Amenities simulation PDF",
}


def upload_plan(files: dict[str, bytes]) -> list[tuple[str, str]]:
    plan = []
    for name in sorted(files):
        target = _UPLOAD_TARGET.get(name) or (_SIM_TARGET.get(name[:2]) if name.endswith(".pdf") else None)
        if target:
            plan.append((name, target))
    return plan


def form_values_text(spec: dict, d: dict, files: dict[str, bytes]) -> str:
    lines = [f"KARR AI test project: {spec['project_info']['project_name']}",
             f"{spec['asset']} - {spec['model']} - seed {spec.get('seed')}",
             "Fictional test data. Fill the KARR AI setup form with these values.", ""]
    lines.append("UPLOADS")
    for name, target in upload_plan(files):
        lines.append(f"  {name}  ->  {target}")
    for section, pairs in form_values(spec, d):
        lines += ["", section.upper()]
        width = max(len(k) for k, _ in pairs)
        lines += [f"  {k.ljust(width)}  {v}" for k, v in pairs]
    return "\n".join(lines) + "\n"


def zip_name(spec: dict) -> str:
    safe = re.sub(r"[^A-Za-z0-9 ._-]+", "", spec["project_info"]["project_name"]).strip()
    asset = asset_for(spec["asset"]).key.replace("_", " ")
    return f"{safe} - {asset} {spec['model'][-2:]}.zip"


def zip_files(files: dict[str, bytes], folder: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(f"{folder}/{name}" if folder else name, data)
    return buf.getvalue()
