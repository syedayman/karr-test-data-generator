"""Result views for the app: one per sheet or file, with an editor and the file as built.

Each editor changes the project spec and hands it to `apply(spec, recompute)`;
the app checks it, rebuilds every file and reruns. `recompute` regenerates what
follows from the floors (travel, preliminary lifts, entrance bias, simulations).
"""

from __future__ import annotations

import copy
import io
from collections.abc import Callable
from html import escape

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from testgen import floor_table, sim_table
from testgen.bundle import (
    ARCHITECT,
    IMAGES,
    LOGOS,
    WORKBOOK,
    folder_zip,
    form_values,
    simulation_file_name,
    skipped,
    top,
    upload_plan,
)
from testgen.excel import workbook_sheets
from testgen.spec import derive, simulation_tables

STORY_TEXT = [("vision", "Design intent"), ("site", "Site and context"), ("massing", "Massing and core"),
              ("facade", "Facade"), ("amenities", "Amenities"), ("sustainability", "Sustainability")]
Apply = Callable[[dict, bool], None]


def section(title: str) -> None:
    st.html(f'<div class="tg-sec">{escape(title)}</div>')


def table_height(rows: int, extra_row: bool = False) -> int:
    """Pixels to show every row (plus the add-row line) up to a cap."""
    return min(35 * (rows + 1 + extra_row) + 2, 735)


def full_table(df: pd.DataFrame) -> None:
    st.dataframe(df, hide_index=True, width="stretch", height=table_height(len(df)))


# ------------------------------------------------------------ file previews

@st.cache_data(max_entries=32, show_spinner=False)
def pdf_pages(data: bytes) -> list[bytes]:
    import pypdfium2 as pdfium

    pages = []
    for page in pdfium.PdfDocument(data):
        buf = io.BytesIO()
        page.render(scale=1.5).to_pil().save(buf, format="PNG")
        pages.append(buf.getvalue())
    return pages


def show_pdf(data: bytes) -> None:
    for png in pdf_pages(data):
        st.image(png, width=760)


@st.cache_data(max_entries=32, show_spinner=False)
def sheet_grid(data: bytes, sheet: str) -> pd.DataFrame:
    ws = load_workbook(io.BytesIO(data), data_only=True)[sheet]
    rows = [["" if v is None else str(v) for v in row] for row in ws.iter_rows(values_only=True)]
    width = max((len(r) for r in rows), default=0)
    return pd.DataFrame(rows, columns=[get_column_letter(i + 1) for i in range(width)],
                        index=range(1, len(rows) + 1))


def show_sheet(data: bytes, sheet: str) -> None:
    grid = sheet_grid(data, sheet)
    st.dataframe(grid, width="stretch", height=table_height(len(grid)))


# ------------------------------------------------------------------ editors

def _number_config(label: str, whole: bool):
    return st.column_config.NumberColumn(label, min_value=0, step=1 if whole else 0.01,
                                         format="%d" if whole else "%.2f")


def _floor_editor(cur: dict, key: str, columns_of, apply: Apply, add_rows: bool) -> None:
    spec = cur["spec"]
    columns = columns_of(spec)
    config: dict = {floor_table.ROW_ID: None}
    for field, label in columns:
        if field in floor_table.FLAGS:
            config[label] = st.column_config.CheckboxColumn(label, default=False)
        elif field == "name":
            config[label] = st.column_config.TextColumn(label, required=True, width="small")
        elif field == "use":
            config[label] = st.column_config.TextColumn(label, width="large")
        elif field == "height_m":
            config[label] = st.column_config.NumberColumn(label, min_value=0.0, max_value=20.0, step=0.05,
                                                          format="%.2f")
        else:
            config[label] = _number_config(label, True)
    edited = st.data_editor(pd.DataFrame(floor_table.to_rows(spec, columns)), hide_index=True,
                            num_rows="dynamic" if add_rows else "fixed", column_config=config, key=key,
                            disabled=[] if add_rows else ["Floor"], width="stretch",
                            height=table_height(len(spec["floors"]), add_rows))
    if st.button("Apply", type="primary", key=f"{key}-go"):
        new = copy.deepcopy(spec)
        new["floors"] = floor_table.from_rows(spec, edited.to_dict("records"), columns)
        apply(new, True)


def _entrance_editor(cur: dict, key: str, apply: Apply) -> None:
    spec = cur["spec"]
    df = pd.DataFrame([{"Floor": r["floor"], "Parking": r.get("parking", 0), "Entrance bias (%)": r["percent"]}
                       for r in spec["entrance_bias"]])
    edited = st.data_editor(df, hide_index=True, num_rows="dynamic", key=key, width="stretch", column_config={
        "Floor": st.column_config.TextColumn("Floor", required=True),
        "Parking": _number_config("Parking", True),
        "Entrance bias (%)": _number_config("Entrance bias (%)", False)})
    st.html(f'<div class="tg-status">Total {edited["Entrance bias (%)"].fillna(0).sum():.1f}%</div>')
    if st.button("Apply", type="primary", key=f"{key}-go"):
        new = copy.deepcopy(spec)
        new["entrance_bias"] = [
            {"floor": str(r["Floor"]).strip(), "parking": int(r["Parking"] or 0),
             "percent": round(float(r["Entrance bias (%)"] or 0), 2)}
            for r in edited.fillna({"Parking": 0, "Entrance bias (%)": 0}).to_dict("records")
            if str(r["Floor"] or "").strip() and str(r["Floor"]) != "nan"]
        apply(new, False)


def _profile_editor(cur: dict, key: str, field: str, apply: Apply) -> None:
    spec = cur["spec"]
    p = spec[field]
    c1, c2 = st.columns(2)
    title = c1.text_input("Title", p["title"], key=f"{key}-title")
    guide = c2.text_input("Design guide", p["design_guide"], key=f"{key}-guide")
    c1, c2, c3, c4 = st.columns(4)
    occupancy = c1.text_input("Building occupancy", p["building_occupancy"], key=f"{key}-occ")
    loading = c2.number_input("Cabin loading factor", 0.0, 1.0, float(p["cabin_loading_factor"]), 0.05,
                              key=f"{key}-load")
    handling = c3.number_input("Handling capacity", 0.0, 1.0, float(p["handling_capacity"]), 0.01,
                               key=f"{key}-hc")
    awt = c4.number_input("Waiting time (s)", 1, 300, int(p["awt_s"]), 1, key=f"{key}-awt")
    rates = st.data_editor(pd.DataFrame([{"Type": k, "Occupancy rate": v} for k, v in p["occupancy_rates"].items()]),
                           hide_index=True, num_rows="dynamic", key=f"{key}-rates", width="stretch",
                           column_config={"Occupancy rate": _number_config("Occupancy rate", False)})
    if st.button("Apply", type="primary", key=f"{key}-go"):
        new = copy.deepcopy(spec)
        new[field] = dict(p, title=title, design_guide=guide, building_occupancy=occupancy,
                          cabin_loading_factor=loading, handling_capacity=handling, awt_s=int(awt),
                          occupancy_rates={str(r["Type"]).strip(): float(r["Occupancy rate"] or 0)
                                           for r in rates.to_dict("records")
                                           if str(r["Type"] or "").strip() and str(r["Type"]) != "nan"})
        apply(new, False)


def _occupancy_editor(cur: dict, key: str, apply: Apply) -> None:
    spec = cur["spec"]
    df = pd.DataFrame([{"Area": r["area"], "m² per person": r["m2_per_person"]}
                       for r in spec["public_area_occupancy"]])
    edited = st.data_editor(df, hide_index=True, num_rows="dynamic", key=key, width="stretch",
                            column_config={"m² per person": _number_config("m² per person", False)})
    if st.button("Apply", type="primary", key=f"{key}-go"):
        new = copy.deepcopy(spec)
        new["public_area_occupancy"] = [
            {"area": str(r["Area"]).strip(), "m2_per_person": float(r["m² per person"] or 0)}
            for r in edited.to_dict("records") if str(r["Area"] or "").strip() and str(r["Area"]) != "nan"]
        apply(new, False)


def _story_editor(cur: dict, key: str, apply: Apply) -> None:
    spec = cur["spec"]
    texts = {}
    for field, label in STORY_TEXT:
        texts[field] = st.text_area(label, spec["story"].get(field, ""), height=110, key=f"{key}-{field}")
    if st.button("Apply", type="primary", key=f"{key}-go"):
        new = copy.deepcopy(spec)
        new["story"].update(texts)
        apply(new, False)


def _simulation_editor(cur: dict, key: str, label: str, rows: list[dict], apply: Apply) -> None:
    spec = cur["spec"]
    config = {lab: _number_config(lab, whole) if k in sim_table.REPORTED else None
              for k, lab, whole in sim_table.COLUMNS}
    edited = st.data_editor(pd.DataFrame(sim_table.to_table(rows)), hide_index=True, num_rows="dynamic",
                            column_config=config, key=f"{key}-rows", width="stretch",
                            height=table_height(len(rows), True))
    if st.button("Apply", type="primary", key=f"{key}-go"):
        new = copy.deepcopy(spec)
        sim_table.set_rows(new, label, sim_table.from_table(edited.to_dict("records")))
        apply(new, False)


# -------------------------------------------------------------------- views

def view_names(spec: dict, files: dict[str, bytes]) -> list[str]:
    names = []
    if WORKBOOK in files:
        names += [s for s in workbook_sheets(spec) if s not in skipped(spec)]
    if ARCHITECT in files:
        names.append("Architect report")
    names += [label for label, _ in simulation_tables(spec) if simulation_file_name(spec, label) in files]
    folders = ["Logos"] if any(top(n) == LOGOS for n in files) else []
    return ["Files", *names, "Images", *folders, "Form values", "JSON"]


def _edit_and_file(edit, file) -> None:
    edit_tab, file_tab = st.tabs(["Edit", "File"])
    with edit_tab:
        edit()
    with file_tab:
        file()


def show_view(name: str, cur: dict, token: int, apply: Apply, rebuild_json: Callable[[str], None],
              replace_render: Callable[[bytes], None]) -> None:
    spec, files = cur["spec"], cur["files"]
    key = f"{name}-{token}"
    sims = dict(simulation_tables(spec))
    sheets = workbook_sheets(spec)

    if name in sheets:
        book = files[WORKBOOK]
        editors = {
            sheets[0]: lambda: _floor_editor(cur, key, floor_table.schedule_columns, apply, True),
            "Lifts Stacking Mix": lambda: _floor_editor(cur, key, floor_table.stacking_columns, apply, False),
            "Amenities Stacking Mix": lambda: _floor_editor(cur, key, floor_table.amenity_columns, apply, False),
            "Entrance Bias": lambda: _entrance_editor(cur, key, apply),
            "Operator Profile": lambda: _profile_editor(cur, key, "operator_profile", apply),
            "Amenities Profile": lambda: _profile_editor(cur, key, "amenities_profile", apply),
            "Public Area Occupancy": lambda: _occupancy_editor(cur, key, apply),
        }
        _edit_and_file(editors[name], lambda: show_sheet(book, name))
    elif name == "Architect report":
        _edit_and_file(lambda: _story_editor(cur, key, apply), lambda: show_pdf(files[ARCHITECT]))
    elif name in sims:
        pdf = files[simulation_file_name(spec, name)]
        _edit_and_file(lambda: _simulation_editor(cur, key, name, sims[name], apply), lambda: show_pdf(pdf))
    elif name == "Files":
        full_table(pd.DataFrame(upload_plan(files), columns=["File", "Upload to"]))
        with st.expander("Single files"):
            for item in sorted({top(n) for n in files}):
                data, file_name = (files[item], item) if item in files else (folder_zip(files, item), f"{item}.zip")
                st.download_button(file_name, data, file_name=file_name, key=f"dl-{token}-{item}", type="tertiary")
    elif name == "Images":
        _images(cur, token, replace_render)
    elif name == "Logos":
        _gallery(files, LOGOS)
    elif name == "Form values":
        sections = form_values(spec, derive(spec))
        for col, chunk in zip(st.columns(2, gap="medium"), (sections[:2], sections[2:])):
            with col:
                for title, pairs in chunk:
                    section(title)
                    full_table(pd.DataFrame(pairs, columns=["Field", "Value"]))
    else:
        import json

        text = st.text_area("project.json", json.dumps(spec, indent=2, ensure_ascii=False), height=460,
                            key=key, label_visibility="collapsed")
        if st.button("Apply", type="primary", key=f"{key}-go"):
            rebuild_json(text)


def _images(cur: dict, token: int, replace_render: Callable[[bytes], None]) -> None:
    files = cur["files"]
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.image(cur["render"], width="stretch")
    with right:
        upload = st.file_uploader("Replace render", type=["png", "jpg", "jpeg"], key=f"render-{token}")
        if upload is not None and st.button("Use this render", key=f"render-go-{token}"):
            replace_render(upload.getvalue())
    _gallery({n: d for n, d in files.items() if not n.endswith("render.png")}, IMAGES)


def _gallery(files: dict[str, bytes], folder: str) -> None:
    """The folder's pictures side by side, captioned with their file names."""
    shown = [n for n in files if top(n) == folder]
    for col, name in zip(st.columns(max(len(shown), 3)), shown):
        col.image(files[name], caption=name.split("/")[-1][:-4], width="stretch")
