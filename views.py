"""Result views for the app: one per sheet or file, with an editor and the file as built.

The views and editors are defined in `testgen.edits`. An editor's Apply hands the
changed spec to `apply(spec, recompute)`; the app checks it, rebuilds every file
and reruns. `recompute` regenerates what follows from the floors (travel,
preliminary lifts, entrance bias, simulations).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from html import escape

import pandas as pd
import streamlit as st

from testgen import edits
from testgen.bundle import (
    ARCHITECT,
    IMAGES,
    LOGOS,
    WORKBOOK,
    folder_zip,
    form_values,
    simulation_file_name,
    top,
    upload_plan,
)
from testgen.excel import workbook_sheets
from testgen.spec import derive, simulation_tables

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
    rows = edits.sheet_grid(data, sheet)
    width = max((len(r) for r in rows), default=0)
    return pd.DataFrame(rows, columns=edits.column_letters(width), index=range(1, len(rows) + 1))


def show_sheet(data: bytes, sheet: str) -> None:
    grid = sheet_grid(data, sheet)
    st.dataframe(grid, width="stretch", height=table_height(len(grid)))


# ------------------------------------------------------------------ editors

def _column_config(c: dict):
    """A Streamlit column for one of the editor's columns (None hides it)."""
    if c["hidden"]:
        return None
    if c["kind"] == "tick":
        return st.column_config.CheckboxColumn(c["name"], default=False)
    if c["kind"] == "text":
        width = "small" if c["narrow"] else "large" if c["wide"] else None
        return st.column_config.TextColumn(c["name"], required=c["required"] or None, width=width)
    whole = c["kind"] == "whole"
    return st.column_config.NumberColumn(c["name"], min_value=c["lo"], max_value=c["hi"],
                                         step=c["step"] or (1 if whole else 0.01), format="%d" if whole else "%.2f")


def _field_widget(col, c: dict, key: str):
    name, value = c["name"], c["value"]
    if c["kind"] == "long":
        return col.text_area(name, value, height=110, key=key)
    if c["kind"] == "number":
        return col.number_input(name, c["lo"], c["hi"], float(value), c["step"], key=key)
    if c["kind"] == "whole":
        return col.number_input(name, int(c["lo"]), int(c["hi"]), int(value), int(c["step"]), key=key)
    return col.text_input(name, value, key=key)


def _editor(cur: dict, view: str, key: str, apply: Apply) -> None:
    """The view's fields and table, and Apply."""
    spec = cur["spec"]
    shape = edits.editor(spec, view)
    fields = {}
    for row in shape["fields"]:
        for col, c in zip(st.columns(len(row)), row):
            fields[c["name"]] = _field_widget(col, c, f"{key}-{c['name']}")
    rows = []
    table = shape["table"]
    if table:
        columns = table["columns"]
        edited = st.data_editor(
            pd.DataFrame(table["rows"], columns=[c["name"] for c in columns]), hide_index=True,
            num_rows="dynamic" if table["add_rows"] else "fixed",
            column_config={c["name"]: _column_config(c) for c in columns}, key=f"{key}-rows",
            disabled=[c["name"] for c in columns if c["locked"]], width="stretch",
            height=table_height(len(table["rows"]), table["add_rows"]))
        if table["total_percent"]:
            total = edited[table["total_percent"]].fillna(0).sum()
            st.html(f'<div class="tg-status">Total {total:.1f}%</div>')
        rows = edited.to_dict("records")
    if st.button("Apply", type="primary", key=f"{key}-go"):
        try:
            new, recompute = edits.change(spec, view, fields, rows)
        except (ValueError, TypeError) as e:
            st.error(str(e))
            return
        apply(new, recompute)


# -------------------------------------------------------------------- views

def _edit_and_file(edit, file) -> None:
    edit_tab, file_tab = st.tabs(["Edit", "File"])
    with edit_tab:
        edit()
    with file_tab:
        file()


def show_view(name: str, cur: dict, token: int, apply: Apply, replace_render: Callable[[bytes], None]) -> None:
    spec, files = cur["spec"], cur["files"]
    key = f"{name}-{token}"
    sims = dict(simulation_tables(spec))
    sheets = workbook_sheets(spec)

    def edit():
        _editor(cur, name, key, apply)

    if name in sheets:
        _edit_and_file(edit, lambda: show_sheet(files[WORKBOOK], name))
    elif name == edits.ARCHITECT_REPORT:
        _edit_and_file(edit, lambda: show_pdf(files[ARCHITECT]))
    elif name in sims:
        _edit_and_file(edit, lambda: show_pdf(files[simulation_file_name(spec, name)]))
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

        st.code(json.dumps(spec, indent=2, ensure_ascii=False), language="json", height=460)


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
