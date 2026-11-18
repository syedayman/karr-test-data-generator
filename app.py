"""KARR AI Test Data Generator - Streamlit app.

Makes fictional projects for testing KARR AI: the combined unit-mix workbook,
a fake architect's design report, a render, logos, plan/section figures,
traffic-simulation PDFs for M2 and hotel sidecars, and the values to type
into KARR AI's setup form. Empty inputs are picked at random; the preview
shows the building before anything is generated; the floors and the project
JSON can be edited and rebuilt afterwards.
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from typing import Any

import streamlit as st

import json_format
import views
from testgen import ai, charts, floor_table
from testgen.assets import (
    ASSETS,
    HOTEL_APARTMENT_UNIT_TYPES,
    HOTEL_STARS,
    PENTHOUSE_TYPES,
    RESIDENTIAL_UNIT_TYPES,
    asset_for,
)
from testgen.bundle import IMAGES, RENDER, build_files, file_names, zip_files, zip_name
from testgen.excel import workbook_sheets
from testgen.floors import SIZING, occupied_limits
from testgen.spec import (
    DEFAULT_SKIP,
    FIRE_CAPACITIES,
    GROUPINGS,
    LOCATIONS,
    PASSENGER_CAPACITIES,
    PROJECT_TYPES,
    SIM_SPEEDS,
    derive,
    floors_summary,
    make_spec,
    refresh,
    resolved_options,
    entrance_problems,
    simulation_problems,
    validate,
    with_story,
)
from views import section

st.set_page_config(page_title="KARR AI Test Data", layout="wide")

st.html("""
<style>
[data-testid="stMainBlockContainer"] {padding-top: 4rem; max-width: 1280px;}
[data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] {display: none;}
.st-key-view [data-testid="stButtonGroup"] > div {flex-wrap: wrap; overflow: visible; row-gap: 8px;}
h3 {font-weight: 600; letter-spacing: -0.01em;}
.tg-sec {font-size: .74rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
  color: #6B7280; margin: 6px 0 -4px;}
.tg-meta {color: #6B7280; font-size: .9rem; margin-top: -6px;}
.tg-facts {display: grid;
  border: 1px solid #DADDE2; border-radius: 4px;}
.tg-facts div {padding: 8px 12px; border-left: 1px solid #DADDE2;}
.tg-facts div:first-child {border-left: 0;}
.tg-facts span {display: block; font-size: .75rem; color: #6B7280;}
.tg-facts b {font-size: 1.05rem; font-weight: 600; font-variant-numeric: tabular-nums;}
.tg-status {font-size: .86rem; margin: 8px 0 2px; color: #374151;}
.tg-status.ok::before, .tg-status.bad::before, .tg-status.sim::before {content: ""; display: inline-block;
  width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; vertical-align: 1px;}
.tg-status.ok::before {background: #2E7D4F;} .tg-status.bad::before {background: #B42318;}
.tg-status.sim::before {background: #1F4E79;}
.tg-status.bad {color: #B42318;}
.tg-stack {border: 1px solid #DADDE2; border-radius: 4px; overflow: hidden; margin-top: 10px;}
.tg-floor {display: grid; grid-template-columns: 70px 1fr 56px; gap: 10px; align-items: center;
  padding: 5px 12px; font-size: .82rem; border-top: 1px solid #E8EAED;}
.tg-floor:first-child {border-top: 0;}
.tg-occupied {background: #EEF3F8;} .tg-boarding {background: #F8F4EC;} .tg-other {background: #FFFFFF;}
.tg-floor b {font-weight: 600;}
.tg-floor small {display: block; color: #6B7280; font-size: .76rem;}
.tg-floor i {font-style: normal; color: #6B7280; text-align: right; font-variant-numeric: tabular-nums;}
</style>
""")


def secret(name: str, default: str | None = None) -> str | None:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # noqa: BLE001 - no secrets file locally
        pass
    return os.environ.get(name, default)


# ------------------------------------------------------------------ gate

password = secret("APP_PASSWORD")
if password and not st.session_state.get("authed"):
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        st.markdown("### KARR AI Test Data")
        with st.form("gate", border=False):
            entered = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Enter", type="primary", width="stretch")
        if submitted and entered == password:
            st.session_state.authed = True
            st.rerun()
        elif submitted:
            st.error("Wrong password")
    st.stop()

API_KEY = secret("OPENAI_API_KEY")
TEXT_MODEL = secret("TEXT_MODEL", "gpt-5.4-mini")
IMAGE_MODEL = secret("IMAGE_MODEL", "gpt-image-2.6-flare")


def openai_client():
    if not API_KEY:
        return None
    from openai import OpenAI

    return OpenAI(api_key=API_KEY)


# ------------------------------------------------------------ vocabulary

TYPES = {
    "residential": "Residential", "office": "Office", "hotel": "Hotel", "hotel_apartments": "Hotel Apartments",
    "car_parking": "Car Parking", "retail": "Retail", "schools": "School", "universities": "University",
}
FLOOR_LABEL = {
    "residential": "Apartment floors", "office": "Office floors", "hotel": "Room floors",
    "hotel_apartments": "Apartment floors", "car_parking": "Parking levels", "retail": "Occupied floors",
    "schools": "Teaching floors", "universities": "Teaching floors",
}


def enabled_types() -> list[str]:
    """Building types the app offers: the BUILDING_TYPES secret (comma-separated keys), else all."""
    raw = secret("BUILDING_TYPES")
    if not raw:
        return list(TYPES)
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    unknown = [k for k in keys if k not in TYPES]
    if unknown or not keys:
        st.error(f"BUILDING_TYPES: unknown {', '.join(unknown) or '(empty)'}. Use any of {', '.join(TYPES)}.")
        st.stop()
    return [k for k in TYPES if k in keys]


ENABLED = enabled_types()
GROUPING_LABEL = {"in-line": "In-line", "facing_each_other": "Facing each other"}
YES_NO = {"Yes": True, "No": False}
PASSENGER_KG = tuple(sorted({*PASSENGER_CAPACITIES, *(a.passenger_kg for a in ASSETS.values())}))
FIRE_KG = tuple(sorted({*FIRE_CAPACITIES, *(a.fire_kg for a in ASSETS.values())}))


@dataclass(frozen=True)
class Field:
    """One optional input: left empty, the generator picks and its pick shows in grey."""

    name: str  # make_spec option
    label: str
    kind: str  # int | float | choice | yesno | multi | text
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    choices: tuple = ()
    fmt: Callable[[Any], str] = str
    span: int = 1  # columns it takes


def size_fields(asset, model: str) -> list[list[Field]]:
    lo, hi = occupied_limits(asset, model)
    first = [Field("occupied_floors", FLOOR_LABEL[asset.key], "int", lo, hi)]
    if SIZING[asset.key]["basements"] is not None:
        first.append(Field("basements", "Basements", "int", 0, 5))
    first += [Field("typical_floor_height_m", "Typical floor height (m)", "float", 2.5, 9.0, 0.05),
              Field("ground_floor_height_m", "Ground floor height (m)", "float", 2.5, 10.0, 0.05)]
    unit_types = Field("unit_types", "Unit types", "multi", span=2, choices=tuple(
        RESIDENTIAL_UNIT_TYPES if asset.key == "residential" else HOTEL_APARTMENT_UNIT_TYPES))
    units = [Field("units_per_floor_min", "Min units per floor", "int", 1, 80),
             Field("units_per_floor_max", "Max units per floor", "int", 1, 80)]
    rooms = "Lecture rooms" if asset.key == "universities" else "Classrooms"
    education = [Field("classrooms_per_floor", f"{rooms} per floor", "int", 1, 60),
                 Field("students_per_classroom", "Students per room", "int", 1, 200)]
    second = {
        "residential": [unit_types, *units],
        "hotel_apartments": [unit_types, *units],
        "hotel": [Field("units_per_floor_min", "Min keys per floor", "int", 1, 120),
                  Field("units_per_floor_max", "Max keys per floor", "int", 1, 120)],
        "office": [Field("floor_area_m2", "Area per floor (m²)", "int", 50, 20000, 50),
                   Field("mezzanine", "Mezzanine", "yesno")],
        "car_parking": [Field("cars_per_floor", "Cars per level", "int", 1, 2000, 5)],
        "retail": [Field("floor_area_m2", "Area per level (m²)", "int", 100, 60000, 100)],
        "schools": education,
        "universities": education,
    }
    third = [[Field("cars_per_basement", "Cars per basement", "int", 0, 2000, 5)]] \
        if SIZING[asset.key]["basements"] is not None else []
    return [first, second[asset.key], *third]


def option_fields(asset, model: str) -> list[list[Field]]:
    row = []
    if asset.key == "residential":
        row += [Field("penthouse_floors", "Penthouse floors", "int", 0, 4),
                Field("penthouse_type", "Penthouse type", "choice", choices=tuple(PENTHOUSE_TYPES))]
    if asset.key == "hotel":
        row.append(Field("hotel_star_rating", "Stars", "choice", choices=tuple(HOTEL_STARS)))
    if asset.hotel_like:
        row += [Field("has_operator", "Operator", "yesno"), Field("has_amenities", "Public amenities", "yesno")]
    if asset.key == "retail":
        row.append(Field("moving_walks", "Moving walks", "yesno"))
    if asset.key == "car_parking":
        row.append(Field("car_parking_facility_type", "Facility", "choice",
                         choices=("Independent", "Retail/Mall Attached"), span=2))
        if model == "DBC-M2":
            row.append(Field("car_parking_has_escalators", "Escalators", "yesno"))
    return [row] if row else []


def project_fields() -> list[list[Field]]:
    return [
        [Field("project_name", "Project name", "text"),
         Field("location", "Location", "choice", choices=tuple(LOCATIONS)),
         Field("project_type", "Stage", "choice", choices=tuple(PROJECT_TYPES))],
        [Field("core_count", "Cores", "int", 1, 5),
         Field("elevator_grouping", "Lift grouping", "choice", choices=tuple(GROUPINGS), fmt=GROUPING_LABEL.get),
         Field("lobby_depth_m", "Lobby depth (m)", "float", 1.5, 8.0, 0.5)],
        [Field("passenger_capacity_kg", "Passenger lift (kg)", "choice", choices=PASSENGER_KG),
         Field("fire_service_capacity_kg", "Fire/service lift (kg)", "choice", choices=FIRE_KG),
         Field("multipurpose_elevator", "Multipurpose lift", "yesno")],
        [Field("authority_exceptions", "Authority exception", "yesno"),
         Field("serves_roof", "Lifts serve roof", "yesno")],
    ]


def simulation_fields() -> list[list[Field]]:
    return [[Field("sim_lifts", "Lifts needed", "int", 1, 12),
             Field("sim_speeds", "Speeds (m/s)", "multi", choices=tuple(SIM_SPEEDS), fmt=lambda v: f"{v:g}", span=2),
             Field("sim_capacities", "Capacities (kg)", "multi", choices=tuple(PASSENGER_KG), span=2)]]


def read(field: Field, key: str):
    value = st.session_state.get(key)
    if field.kind == "yesno":
        return YES_NO.get(value)
    if field.kind == "multi":
        return list(value or []) or None
    if field.kind == "text":
        return (value or "").strip() or None
    return value


def shown(field: Field, value) -> str:
    """The generator's pick as grey placeholder text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, tuple):
        return "–".join(shown(field, v) for v in value)
    if isinstance(value, list):
        return ", ".join(field.fmt(v) for v in value)
    if field.kind == "float":
        return f"{value:.2f}"
    return field.fmt(value)


def render(col, field: Field, key: str, placeholder: str) -> None:
    if field.kind == "int":
        col.number_input(field.label, min_value=int(field.lo), max_value=int(field.hi), value=None,
                         step=int(field.step or 1), placeholder=placeholder, key=key)
    elif field.kind == "float":
        col.number_input(field.label, min_value=field.lo, max_value=field.hi, value=None, step=field.step,
                         format="%.2f", placeholder=placeholder, key=key)
    elif field.kind == "choice":
        col.selectbox(field.label, field.choices, index=None, placeholder=placeholder, format_func=field.fmt,
                      key=key)
    elif field.kind == "yesno":
        col.selectbox(field.label, tuple(YES_NO), index=None, placeholder=placeholder, key=key)
    elif field.kind == "multi":
        col.multiselect(field.label, field.choices, placeholder=placeholder, format_func=field.fmt, key=key)
    else:
        col.text_input(field.label, placeholder=placeholder, key=key)


def render_rows(rows: list[list[Field]], keys: dict[str, str], picked: dict, width: int,
                placeholders: dict[str, str]) -> None:
    for row in rows:
        spans = [f.span for f in row]
        cols = st.columns(spans + [1] * (width - sum(spans)))
        for col, field in zip(cols, row):
            text = placeholders.get(field.name, shown(field, picked.get(field.name)))
            render(col, field, keys[field.name], text)


def keep_enabled() -> None:
    if st.session_state.asset not in ENABLED:
        st.session_state.asset = st.session_state.get("asset-last", ENABLED[0])


def building_choice() -> tuple[str, str]:
    keys = list(TYPES)
    off = [i for i, k in enumerate(keys) if k not in ENABLED]
    if off:  # the dropdown list carries the label; grey the types this deploy doesn't offer
        items = ", ".join(f'[role="listbox"][aria-label="Building type"] [data-key="{i}"]' for i in off)
        st.html(f"<style>{items} {{opacity: .4; pointer-events: none;}}</style>")
    c1, _ = st.columns([2, 3])
    asset_key = c1.selectbox("Building type", keys, index=keys.index(ENABLED[0]), format_func=TYPES.get,
                             key="asset", on_change=keep_enabled)
    st.session_state["asset-last"] = asset_key
    asset = ASSETS[asset_key]
    methods = ["DBC-M1", "DBC-M2"] if asset.supports_m2 else ["DBC-M1"]
    model = st.segmented_control("Method", methods, default="DBC-M1", required=True, key=f"model-{asset_key}",
                                 format_func=lambda m: m[-2:])
    return asset_key, model


def project_form(asset, model: str, ai_text: bool):
    """Render the inputs with the generator's picks in grey.

    Returns (options, skipped files and sheets, preview or error).
    """
    size, extra, sims, project = (size_fields(asset, model), option_fields(asset, model), simulation_fields(),
                                  project_fields())
    keys = {f.name: f"{f.name}-{asset.key}-{model}" for row in size + extra + sims for f in row}
    keys |= {f.name: f"p-{f.name}" for row in project for f in row}
    every = [f for rows in (size, extra, sims, project) for row in rows for f in row]
    options = {f.name: read(f, keys[f.name]) for f in every}
    options = {k: v for k, v in options.items() if v is not None}
    try:
        result = preview(asset.key, model, int(st.session_state.seed), json.dumps(options, sort_keys=True))
        picked = resolved_options(result[0])
    except ValueError as e:
        result, picked = str(e), {}
    placeholders = {"project_name": "From the AI"} if ai_text else {}

    section("Size")
    render_rows(size, keys, picked, 4, placeholders)
    if extra:
        section("Options")
        render_rows(extra, keys, picked, 3, placeholders)
    if "sim_lifts" in picked:
        section("Simulations")
        render_rows(sims, keys, picked, 5, placeholders)
    with st.expander("Project details"):
        render_rows(project, keys, picked, 3, placeholders)
    skip = output_checkboxes(result[0]) if not isinstance(result, str) else []
    return options, skip, result


def output_checkboxes(spec: dict) -> list[str]:
    """Ticks for every file and workbook sheet; returns the unticked names."""
    files = file_names(spec)
    sheets = workbook_sheets(spec)
    skip = []
    with st.expander("Files"):
        left, right = st.columns(2)
        with left:
            section("Files")
            for name in files:
                if not st.checkbox(name, value=name not in DEFAULT_SKIP, key=f"out-{name}"):
                    skip.append(name)
        with right:
            section("Workbook sheets")
            for name in sheets:
                if not st.checkbox(name, value=name not in DEFAULT_SKIP, key=f"out-{name}"):
                    skip.append(name)
    return skip


def shuffle() -> None:
    st.session_state.seed = random.randrange(1, 10**6)


# --------------------------------------------------------------- display

@st.cache_data(max_entries=64, show_spinner=False)
def preview(asset_key: str, model: str, seed: int, opts_json: str):
    spec = make_spec(asset_key, model, seed=seed, options=json.loads(opts_json))
    return spec, derive(spec), charts.check(spec)


def facts(spec: dict, d: dict, more: bool = False) -> None:
    if asset_for(spec["asset"]).key == "office":
        size = ("Office area", f"{charts.chart_value(spec)[0]:,.0f} m²")
    else:
        size = ("People", f"{d['population']:,}")
    items = [("Levels", len(spec["floors"])), ("Occupied", d["occupied_floors"]), size,
             ("Lift travel", f"{d['passenger_travel_m']:.1f} m")]
    if more:
        b = spec["building"]
        items += [("Fire lift travel", f"{d['fire_travel_m']:.1f} m"),
                  ("Prelim lifts", f"{b['passenger_lifts_prelim']} + {b['fire_service_lifts_prelim']}")]
    cells = "".join(f"<div><span>{escape(k)}</span><b>{escape(str(v))}</b></div>" for k, v in items)
    st.html(f'<div class="tg-facts" style="grid-template-columns: repeat({len(items)}, 1fr)">{cells}</div>')


def status(spec: dict, problems: list[str]) -> None:
    if spec["model"] == "DBC-M2":
        line = '<div class="tg-status sim">Lifts from the simulation PDFs</div>'
    elif not charts.has_chart(asset_for(spec["asset"]).key):
        line = '<div class="tg-status ok">Lifts by DBC formula</div>'
    elif problems:
        line = "".join(f'<div class="tg-status bad">Not computable: {escape(p)}</div>' for p in problems)
    else:
        value, unit = charts.chart_value(spec)
        line = f'<div class="tg-status ok">Inside the M1 chart ({value:,.0f} {escape(unit)})</div>'
    if spec["model"] == "DBC-M2" and simulation_problems(spec):
        line = ""
    line += "".join(f'<div class="tg-status bad">No acceptable simulation: {escape(p)}</div>'
                    for p in simulation_problems(spec))
    line += "".join(f'<div class="tg-status bad">Entrance bias: {escape(p)}</div>' for p in entrance_problems(spec))
    st.html(line)


def span_label(bottom: str, top: str) -> str:
    """'Level 6' and 'Level 7' read as 'Level 6–7'."""
    head, _, low = bottom.rpartition(" ")
    if head and top.startswith(head + " "):
        return f"{head} {low}–{top[len(head) + 1:]}"
    return f"{bottom}–{top}"


def stack(spec: dict) -> None:
    rows = []
    for g in floor_table.floor_groups(spec):
        label = g["top"] if g["count"] == 1 else span_label(str(g["bottom"]), str(g["top"]))
        many = f" ×{g['count']}" if g["count"] > 1 else ""
        extra = f"<small>{escape(g['contents'])}</small>" if g["contents"] else ""
        height = f"{g['height_m']:.2f}" if g["height_m"] else ""
        rows.append(f'<div class="tg-floor tg-{g["kind"]}"><b>{escape(str(label))}</b>'
                    f'<span>{escape(str(g["use"]))}{many}{extra}</span><i>{height}</i></div>')
    st.html(f'<div class="tg-stack">{"".join(rows)}</div>')


# ------------------------------------------------------------ generating

def finish(spec: dict, render: bytes | None, source: str, notes: list[str]) -> None:
    """Build every file and make it the current project. source: drawn, AI or uploaded render."""
    files = build_files(spec, render if source != "drawn" else None)
    drawn = files.get(RENDER) or render
    if drawn is None:
        from testgen.images import fallback_render

        drawn = fallback_render(spec, int(spec.get("seed") or 1))
    st.session_state.build_no = st.session_state.get("build_no", 0) + 1
    st.session_state.current = {"spec": spec, "files": files, "render": drawn, "render_source": source,
                                "notes": notes}


def create_project(asset_key: str, model: str, opts: dict, seed: int,
                   use_ai_text: bool, use_ai_image: bool, hint: str) -> tuple[dict, bytes | None, str, list[str]]:
    spec = make_spec(asset_key, model, seed=seed, options=opts)
    client = openai_client()
    notes = []
    if use_ai_text and client:
        location = spec["project_info"]["project_location"]  # keep the previewed location
        try:
            story = ai.generate_story(client, TEXT_MODEL, ASSETS[asset_key], model, {**opts, "location": location},
                                      floors_summary(spec), hint)
            with_story(spec, story)
            spec["project_info"]["project_location"] = location
        except Exception as e:  # noqa: BLE001
            notes.append(f"AI text failed, built-in names used ({e.__class__.__name__}: {e})")
    render = None
    if use_ai_image and client and IMAGES not in (opts.get("skip_outputs") or []):
        try:
            render = ai.generate_render(client, IMAGE_MODEL, spec["story"]["render_prompt"])
        except Exception as e:  # noqa: BLE001
            notes.append(f"AI render failed, drawn render used ({e.__class__.__name__}: {e})")
    return spec, render, "AI" if render is not None else "drawn", notes


def show_errors(errors: list[str]) -> None:
    st.error("\n".join(f"- {e}" for e in errors))


def spec_errors(spec: dict) -> list[str]:
    errors = validate(spec)
    if not errors and asset_for(spec["asset"]).key not in ENABLED:
        errors = [f"{spec['asset']} isn't available here yet."]
    return errors


def projects_from_files(uploads) -> tuple[list[dict], list[str]]:
    """Every project in the uploaded files (each holds one project or a list of them), and any errors."""
    specs, errors = [], []
    for up in uploads:
        try:
            data = json.loads(up.getvalue().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            errors.append(f"{up.name}: invalid JSON ({e})")
            continue
        items = data if isinstance(data, list) else [data]
        for n, spec in enumerate(items, start=1):
            where = up.name if len(items) == 1 else f"{up.name} #{n}"
            problems = spec_errors(spec) if isinstance(spec, dict) else ["not a project object"]
            errors += [f"{where}: {p}" for p in problems]
            if not problems:
                specs.append(spec)
    return specs, errors


def add_to_bundle(bundle: dict[str, bytes], i: int, spec: dict, render: bytes | None, source: str) -> None:
    files = build_files(spec, render if source != "drawn" else None)
    folder = f"{i:02d} {zip_name(spec)[:-4]}"
    for name, data in files.items():
        bundle[f"{folder}/{name}"] = data


def build_from_json_text(text: str, cur: dict | None = None, ai_render: bool = False) -> None:
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as e:
        st.error(f"Invalid JSON: {e}")
        return
    errors = spec_errors(spec) if isinstance(spec, dict) else ["One project per file here; Batch takes lists."]
    if errors:
        show_errors(errors)
        return
    render, source = (cur["render"], cur["render_source"]) if cur else (None, "drawn")
    if ai_render and openai_client():
        with st.spinner("Rendering"):
            try:
                render, source = ai.generate_render(openai_client(), IMAGE_MODEL, spec["story"]["render_prompt"]), "AI"
            except Exception as e:  # noqa: BLE001
                st.warning(f"AI render failed, drawn render used ({e})")
    finish(spec, render, source, [])
    st.rerun()


def apply_edit(spec: dict, recompute: bool) -> None:
    """An editor's changes: check, work out what follows from the floors if asked, rebuild."""
    errors = validate(spec)
    if errors:
        show_errors(errors)
        return
    if recompute:
        refresh(spec)
    cur = st.session_state.current
    finish(spec, cur["render"], cur["render_source"], [])
    st.rerun()


def replace_render(png: bytes) -> None:
    cur = st.session_state.current
    finish(cur["spec"], png, "uploaded", [])
    st.rerun()


def show_result(cur: dict) -> None:
    spec, files = cur["spec"], cur["files"]
    token = st.session_state.get("build_no", 0)
    d = derive(spec)
    source = spec["story"].get("source", "?")
    meta = [TYPES[asset_for(spec["asset"]).key], spec["model"], f"seed {spec.get('seed')}",
            "built-in names" if source == "fallback" else f"text by {source}", f"{cur['render_source']} render"]

    st.divider()
    head, downloads = st.columns([3, 2], vertical_alignment="bottom")
    with head:
        st.markdown(f"### {spec['project_info']['project_name']}")
        st.html(f'<div class="tg-meta">{escape(" · ".join(meta))}</div>')
    with downloads:
        st.download_button("Download .zip", zip_files(files), file_name=zip_name(spec), mime="application/zip",
                           type="primary", width="stretch")
    for note in cur.get("notes", []):
        st.warning(note)
    facts(spec, d, more=True)
    status(spec, charts.check(spec))

    names = views.view_names(spec, files)
    view = st.pills("View", names, default=names[0], required=True, key="view", label_visibility="collapsed")
    if view not in names:
        view = names[0]
    views.show_view(view, cur, token, apply_edit, lambda text: build_from_json_text(text, cur), replace_render)


# -------------------------------------------------------------------- page

st.markdown("### KARR AI Test Data")
st.session_state.setdefault("seed", random.randrange(1, 10**6))

tab_new, tab_json, tab_batch = st.tabs(["New project", "From JSON", "Batch"])

with tab_new:
    form_col, preview_col = st.columns([3, 2], gap="large")
    with form_col:
        asset_key, model = building_choice()
        asset = ASSETS[asset_key]
        ai_on = bool(API_KEY) and st.session_state.get("ai-text", True)
        options, skip, result = project_form(asset, model, ai_on)

        use_text = use_image = False
        hint = ""
        if API_KEY:
            c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="bottom")
            use_text = c1.toggle("AI text", value=True, key="ai-text")
            use_image = c2.toggle("AI render", value=True, key="ai-img")
            if use_text:
                hint = c3.text_input("Direction for the AI", key="ai-hint")

        c1, c2, c3 = st.columns([2, 1, 3], vertical_alignment="bottom")
        c1.number_input("Seed", min_value=1, max_value=999999, step=1, key="seed")
        c2.button("Shuffle", on_click=shuffle, width="stretch")
        generate = c3.button("Generate", type="primary", width="stretch")
        if generate:
            with st.spinner("Generating"):
                try:
                    finish(*create_project(asset_key, model, {**options, "skip_outputs": skip},
                                           int(st.session_state.seed), use_text, use_image, hint))
                except ValueError as e:
                    st.error(str(e))
        if st.session_state.get("current"):
            cur = st.session_state.current
            a, b = st.columns([3, 2], vertical_alignment="center")
            a.markdown(f"**{cur['spec']['project_info']['project_name']}** is ready.")
            b.download_button("Download .zip", zip_files(cur["files"]), file_name=zip_name(cur["spec"]),
                              mime="application/zip", width="stretch", key="dl-top")

    with preview_col:
        section("Preview")
        if isinstance(result, str):
            st.error(result)
        else:
            spec, d, problems = result
            facts(spec, d)
            status(spec, problems)
            stack(spec)

with tab_json:
    json_format.show(ENABLED, TYPES)
    upload = st.file_uploader("project.json", type=["json"])
    new_render = st.toggle("New AI render", value=False) if API_KEY else False
    if st.button("Build", type="primary", disabled=upload is None):
        build_from_json_text(upload.getvalue().decode("utf-8"), ai_render=new_render)

with tab_batch:
    batch_source = st.segmented_control("Projects", ["Random", "JSON files"], default="Random", required=True,
                                        key="b-source")
    if batch_source == "Random":
        combos = [(k, m) for k, a in ASSETS.items() if k in ENABLED
                  for m in (["DBC-M1", "DBC-M2"] if a.supports_m2 else ["DBC-M1"])]
        c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="bottom")
        per_combo = c1.number_input("Per type and method", min_value=1, max_value=5, value=1, step=1)
        batch_text = batch_image = False
        if API_KEY:
            batch_text = c2.toggle("AI text", value=True, key="b-text")
            batch_image = c3.toggle("AI renders", value=False, key="b-img")
        total = len(combos) * per_combo
        batch_inputs = ("Random",)
        if st.button(f"Generate {total} projects", type="primary"):
            bundle: dict[str, bytes] = {}
            jobs = [c for c in combos for _ in range(per_combo)]
            bar = st.progress(0.0)
            for i, (k, m) in enumerate(jobs, start=1):
                bar.progress(i / len(jobs), text=f"{TYPES[k]} {m[-2:]} ({i}/{len(jobs)})")
                spec, render, source, _ = create_project(k, m, {}, random.randrange(1, 10**6),
                                                         batch_text, batch_image, "")
                add_to_bundle(bundle, i, spec, render, source)
            st.session_state.batch = (batch_inputs, zip_files(bundle))
    else:
        json_format.show(ENABLED, TYPES, prefix="b", many=True)
        uploads = st.file_uploader("project.json files", type=["json"], accept_multiple_files=True)
        specs, errors = projects_from_files(uploads or [])
        batch_inputs = ("JSON", *((u.name, u.size) for u in uploads or []))
        if errors:
            show_errors(errors)
        json_image = st.toggle("AI renders", value=False, key="b-json-img") if API_KEY else False
        if st.button(f"Build {len(specs)} projects", type="primary", disabled=bool(errors) or not specs):
            bundle = {}
            bar = st.progress(0.0)
            for i, spec in enumerate(specs, start=1):
                bar.progress(i / len(specs), text=f"{spec['project_info']['project_name']} ({i}/{len(specs)})")
                render, source = None, "drawn"
                if json_image:
                    try:
                        render, source = ai.generate_render(openai_client(), IMAGE_MODEL,
                                                            spec["story"]["render_prompt"]), "AI"
                    except Exception as e:  # noqa: BLE001
                        st.warning(f"{spec['project_info']['project_name']}: AI render failed, drawn render used "
                                   f"({e})")
                add_to_bundle(bundle, i, spec, render, source)
            st.session_state.batch = (batch_inputs, zip_files(bundle))
    built = st.session_state.get("batch")
    if built and built[0] == batch_inputs:
        st.download_button("Download .zip", built[1], file_name="KARR AI test projects.zip",
                           mime="application/zip", type="primary")

if st.session_state.get("current"):
    show_result(st.session_state.current)
