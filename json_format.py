"""The project.json format, shown on the From JSON tab for the building types on offer."""

from __future__ import annotations

import json

import streamlit as st

from testgen.assets import ASSETS
from testgen.spec import SPEC_VERSION, make_spec

HOTELS = {"hotel", "hotel_apartments"}
HOUSING = {"residential"} | HOTELS
EDUCATION = {"schools", "universities"}
TWO_PEAKS = {k for k, a in ASSETS.items() if a.supports_m2 and not a.single_sim}
ONE_PEAK = {k for k, a in ASSETS.items() if a.supports_m2 and a.single_sim}

# (key, building types it applies to or None for all, contents)
TOP = [
    ("spec_version", None, str(SPEC_VERSION)),
    ("asset", None, "building type (Types table)"),
    ("model", None, "`DBC-M1` or `DBC-M2`"),
    ("project_info", None, "project_classification (same as asset), project_name, employer_client_developer, "
                           "architect, lead_consultant, project_location, "
                           "project_address, project_type, reference, author, approved_by, revision_details, "
                           "header_text, footer_text"),
    ("project_info.hotel_star_rating", {"hotel"}, "`1-2`, `3` or `4-5`"),
    ("project_info.car_parking_facility_type", {"car_parking"}, "`Independent` or `Retail/Mall Attached`"),
    ("project_info.car_parking_has_escalators", {"car_parking"}, "true / false (M2)"),
    ("building", None, "has_authority_exceptions, authority_exceptions (exception_no, exception_date, details), "
                       "passenger_lifts_prelim, fire_service_lifts_prelim"),
    ("building.has_operator, has_amenities", HOTELS, "true / false"),
    ("vt_criteria", None, "core_count (1–5), elevator_grouping (`in-line` / `facing_each_other`), lobby_depth_m, "
                          "serves_roof, multipurpose_elevator"),
    ("space_planning", None, "passenger_capacity_kg, fire_service_capacity_kg, machine_type (`mra` / `mrl`)"),
    ("unit_types", HOUSING, "unit or room type names, in schedule order"),
    ("floors", None, "every floor, top first (Floors table)"),
    ("operator_profile", HOTELS, "when has_operator: title, design_guide, occupancy_rates {type: people}, "
                                 "building_occupancy, cabin_loading_factor, handling_capacity, awt_s"),
    ("amenities_profile", HOTELS, "when has_amenities: same fields as operator_profile"),
    ("entrance_bias", HOTELS | {"car_parking"}, "M2: rows of floor, parking, percent"),
    ("simulations.guest.morning, evening", TWO_PEAKS, "M2: result rows per peak"),
    ("simulations.guest.evening", EDUCATION, "schools and universities: the breaks peak"),
    ("simulations.guest.single", ONE_PEAK, "M2: result rows"),
    ("simulations.operator, amenities", HOTELS, "result rows, when has_operator / has_amenities"),
    ("public_area_occupancy", {"hotel_apartments"}, "optional rows of area, m2_per_person"),
    ("outputs.skip", None, "optional: file and sheet names to leave out"),
    ("story", None, "project_name, client, architect, lead_consultant, location, address, author, approved_by, "
                    "operator_brand, and the architect report text: vision, site, massing, facade, amenities, "
                    "sustainability, render_prompt"),
]
FLOOR = [
    ("name", None, "unique"),
    ("height_m", None, "floor-to-floor height (m)"),
    ("use", None, "text"),
    ("occupied", None, "true where people are counted"),
    ("boarding", None, "true for entrance and parking floors"),
    ("units", HOUSING, '{"type": count}'),
    ("area_m2", {"office", "retail"} | HOTELS, "floor area (m²); hotels: public area floors"),
    ("cars", set(ASSETS) - {"schools"}, "parking spaces"),
    ("classrooms, students_per_classroom, staff", EDUCATION, "whole numbers"),
    ("amenity, rooftop", HOTELS, "true on amenity floors"),
]
SIM_ROW = ("lifts, speed, accel, jerk, capacity, door [pre-open, open, close], "
           "awt, lwt, att, ltt, atd, ltd (wait / transit / to destination: average and longest, s)")


def _table(head: tuple[str, str], rows: list[tuple]) -> str:
    lines = [f"| {head[0]} | {head[1]} |", "|---|---|"]
    lines += [f"| `{k}` | {text} |" for k, text in rows]
    return "\n".join(lines)


def _for(rows: list[tuple], enabled: list[str]) -> list[tuple[str, str]]:
    return [(k, text) for k, types, text in rows if types is None or types & set(enabled)]


def show(enabled: list[str], labels: dict[str, str], prefix: str = "j", many: bool = False) -> None:
    """many: files may hold a list of projects (Batch); the example is then a list of every type and method."""
    with st.expander("Format"):
        c1, c2, c3 = st.columns([2, 1, 2], vertical_alignment="bottom")
        key = c1.selectbox("Example", enabled, format_func=labels.get, key=f"{prefix}-fmt-type")
        models = ["DBC-M1", "DBC-M2"] if ASSETS[key].supports_m2 else ["DBC-M1"]
        model = c2.selectbox("Method", models, format_func=lambda m: m[-2:], key=f"{prefix}-fmt-model-{key}")
        example = json.dumps(make_spec(key, model, seed=1), indent=2)
        c3.download_button("Download example", example, file_name=f"project {labels[key]} {model[-2:]}.json",
                           mime="application/json", width="stretch", key=f"{prefix}-fmt-one")
        if many:
            every = [make_spec(k, m, seed=1) for k in enabled
                     for m in (["DBC-M1", "DBC-M2"] if ASSETS[k].supports_m2 else ["DBC-M1"])]
            st.markdown("A file holds one project `{...}` or a list of projects `[{...}, {...}]`.")
            st.download_button("Download example list", json.dumps(every, indent=2), file_name="projects.json",
                               mime="application/json", key=f"{prefix}-fmt-list")

        types = [(f"`{ASSETS[k].classification}`",
                  f"M1 up to {ASSETS[k].m1_threshold} occupied floors"
                  + (f", M2 above {ASSETS[k].m1_threshold}" if ASSETS[k].supports_m2 else ""))
                 for k in enabled]
        st.markdown("\n".join(["| Type (`asset`) | Floors |", "|---|---|"] + [f"| {a} | {b} |" for a, b in types]))
        st.markdown(_table(("Key", "Contents"), _for(TOP, enabled)))
        st.markdown(_table(("Floor field", "Contents"), _for(FLOOR, enabled)))
        st.markdown(f"Simulation rows: {SIM_ROW}. Travel heights, population and form values are worked out "
                    "from the floors.")
