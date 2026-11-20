"""Archies Architect - KARR AI's VT test data generator (Streamlit app).

Makes fictional projects for testing KARR AI: the combined unit-mix workbook,
a fake architect's design report, a render, logos, plan/section figures,
traffic-simulation PDFs for M2 and hotel sidecars, and the values to type
into KARR AI's setup form, plus the project as JSON (project.json, and
projects.json for a batch). Empty inputs are picked at random; the preview
shows the building before anything is generated; the floors can be edited and
rebuilt afterwards.
"""

from __future__ import annotations

import base64
import json
import os
import random
from html import escape
from pathlib import Path

import streamlit as st

import views
from testgen import ai, charts, edits, summary
from testgen.assets import ASSETS
from testgen.bundle import IMAGES, RENDER, batch_zip, build_files, file_names, zip_files, zip_name
from testgen.excel import workbook_sheets
from testgen.fields import PROJECT_DETAILS, SIMULATIONS, TYPES, Field, form, methods, shown
from testgen.spec import (
    DEFAULT_SKIP,
    derive,
    floors_summary,
    make_spec,
    refresh,
    resolved_options,
    validate,
    with_story,
)
from views import section


def data_uri(name: str) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(__file__).with_name(name).read_bytes()).decode("ascii")


ICON = Path(__file__).with_name("archies-icon.png")
st.set_page_config(page_title="Archies Architect", page_icon=str(ICON), layout="wide")

st.html("""
<style>
[data-testid="stMainBlockContainer"] {padding-top: 4rem; max-width: 1280px;}
[data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] {display: none;}
.st-key-view [data-testid="stButtonGroup"] > div {flex-wrap: wrap; overflow: visible; row-gap: 8px;}
h3 {font-weight: 600; letter-spacing: -0.01em;}
.tg-brand {display: flex; align-items: center; gap: 14px; margin-bottom: 4px;}
.tg-brand img {width: 64px; height: 64px;}
.tg-brand b {display: block; font-size: 1.6rem; font-weight: 700; letter-spacing: -0.01em; color: #0F2557;}
.tg-brand span {display: block; font-size: .85rem; color: #6B7280;}
.tg-gate img {display: block; width: min(420px, 100%, 52vh); margin: 0 auto 12px;}
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
.tg-status.sim::before {background: #1F6FE0;}
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
        st.html(f'<div class="tg-gate"><img src="{data_uri("archies-architect.png")}" alt="Archies Architect"></div>')
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
YES_NO = {"Yes": True, "No": False}


def read(field: Field, key: str):
    value = st.session_state.get(key)
    if field.kind == "yesno":
        return YES_NO.get(value)
    if field.kind == "multi":
        return list(value or []) or None
    if field.kind == "text":
        return (value or "").strip() or None
    return value


def render(col, field: Field, key: str, placeholder: str) -> None:
    if field.kind == "int":
        col.number_input(field.label, min_value=int(field.lo), max_value=int(field.hi), value=None,
                         step=int(field.step or 1), placeholder=placeholder, key=key)
    elif field.kind == "float":
        col.number_input(field.label, min_value=field.lo, max_value=field.hi, value=None, step=field.step,
                         format="%.2f", placeholder=placeholder, key=key)
    elif field.kind == "choice":
        col.selectbox(field.label, field.choices, index=None, placeholder=placeholder, format_func=field.text,
                      key=key)
    elif field.kind == "yesno":
        col.selectbox(field.label, tuple(YES_NO), index=None, placeholder=placeholder, key=key)
    elif field.kind == "multi":
        col.multiselect(field.label, field.choices, placeholder=placeholder, format_func=field.text, key=key)
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
    model = st.segmented_control("Method", methods(asset_key), default="DBC-M1", required=True, key=f"model-{asset_key}",
                                 format_func=lambda m: m[-2:])
    return asset_key, model


def project_form(asset, model: str, ai_text: bool):
    """Render the inputs with the generator's picks in grey.

    Returns (options, skipped files and sheets, preview or error).
    """
    sections = form(asset.key, model)
    keys = {f.name: f"p-{f.name}" if title == PROJECT_DETAILS else f"{f.name}-{asset.key}-{model}"
            for title, _, rows in sections for row in rows for f in row}
    every = [f for _, _, rows in sections for row in rows for f in row]
    options = {f.name: read(f, keys[f.name]) for f in every}
    options = {k: v for k, v in options.items() if v is not None}
    try:
        result = preview(asset.key, model, int(st.session_state.seed), json.dumps(options, sort_keys=True))
        picked = resolved_options(result[0])
    except ValueError as e:
        result, picked = str(e), {}
    placeholders = {"project_name": "From the AI"} if ai_text else {}

    for title, width, rows in sections:
        if title == SIMULATIONS and "sim_lifts" not in picked:
            continue
        if title == PROJECT_DETAILS:
            with st.expander(title):
                render_rows(rows, keys, picked, width, placeholders)
        else:
            section(title)
            render_rows(rows, keys, picked, width, placeholders)
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
    items = summary.facts(spec, d, more)
    cells = "".join(f"<div><span>{escape(k)}</span><b>{escape(v)}</b></div>" for k, v in items)
    st.html(f'<div class="tg-facts" style="grid-template-columns: repeat({len(items)}, 1fr)">{cells}</div>')


def status(spec: dict, problems: list[str]) -> None:
    st.html("".join(f'<div class="tg-status {tone}">{escape(text)}</div>'
                    for tone, text in summary.status(spec, problems)))


def stack(spec: dict) -> None:
    rows = []
    for g in summary.stack(spec):
        extra = f"<small>{escape(g['contents'])}</small>" if g["contents"] else ""
        rows.append(f'<div class="tg-floor tg-{g["kind"]}"><b>{escape(g["label"])}</b>'
                    f'<span>{escape(g["use"])}{extra}</span><i>{g["height"]}</i></div>')
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

    st.divider()
    head, downloads = st.columns([3, 2], vertical_alignment="bottom")
    with head:
        st.markdown(f"### {spec['project_info']['project_name']}")
        st.html(f'<div class="tg-meta">{escape(summary.details(spec, cur["render_source"]))}</div>')
    with downloads:
        st.download_button("Download .zip", zip_files(files), file_name=zip_name(spec), mime="application/zip",
                           type="primary", width="stretch")
    for note in cur.get("notes", []):
        st.warning(note)
    facts(spec, d, more=True)
    status(spec, charts.check(spec))

    names = edits.view_names(spec, files)
    view = st.pills("View", names, default=names[0], required=True, key="view", label_visibility="collapsed")
    if view not in names:
        view = names[0]
    views.show_view(view, cur, token, apply_edit, replace_render)


# -------------------------------------------------------------------- page

st.html(f'<div class="tg-brand"><img src="{data_uri(ICON.name)}" alt=""><div><b>Archies Architect</b>'
        '<span>Powered by Medha 1.0 — KARR AI</span></div></div>')
st.session_state.setdefault("seed", random.randrange(1, 10**6))

tab_new, tab_batch = st.tabs(["New project", "Batch"])

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
            use_text = c1.toggle("AI text", value=False, key="ai-text")
            use_image = c2.toggle("AI render", value=False, key="ai-img")
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

with tab_batch:
    combos = [(k, m) for k in ASSETS if k in ENABLED for m in methods(k)]
    c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="bottom")
    per_combo = c1.number_input("Per type and method", min_value=1, max_value=5, value=1, step=1)
    batch_text = batch_image = False
    if API_KEY:
        batch_text = c2.toggle("AI text", value=False, key="b-text")
        batch_image = c3.toggle("AI renders", value=False, key="b-img")
    total = len(combos) * per_combo
    if st.button(f"Generate {total} projects", type="primary"):
        projects = []
        jobs = [c for c in combos for _ in range(per_combo)]
        bar = st.progress(0.0)
        for i, (k, m) in enumerate(jobs, start=1):
            bar.progress(i / len(jobs), text=f"{TYPES[k]} {m[-2:]} ({i}/{len(jobs)})")
            spec, render, _, _ = create_project(k, m, {}, random.randrange(1, 10**6), batch_text, batch_image, "")
            projects.append((spec, render))
        with st.spinner("Building the zip"):
            st.session_state.batch = batch_zip(projects)
    if st.session_state.get("batch"):
        st.download_button("Download .zip", st.session_state.batch, file_name="KARR AI test projects.zip",
                           mime="application/zip", type="primary")

if st.session_state.get("current"):
    show_result(st.session_state.current)
