"""What the app shows about a project: the facts strip, the status lines, the
floor stack and the details line under the project name."""

from __future__ import annotations

from . import charts, floor_table
from .assets import asset_for
from .fields import TYPES
from .spec import entrance_problems, simulation_problems


def facts(spec: dict, d: dict, more: bool = False) -> list[tuple[str, str]]:
    """(label, value) pairs; `more` adds the fire lift travel and the preliminary lifts."""
    if asset_for(spec["asset"]).key == "office":
        size = ("Office area", f"{charts.chart_value(spec)[0]:,.0f} m²")
    else:
        size = ("People", f"{d['population']:,}")
    items = [("Levels", str(len(spec["floors"]))), ("Occupied", str(d["occupied_floors"])), size,
             ("Lift travel", f"{d['passenger_travel_m']:.1f} m")]
    if more:
        b = spec["building"]
        items += [("Fire lift travel", f"{d['fire_travel_m']:.1f} m"),
                  ("Prelim lifts", f"{b['passenger_lifts_prelim']} + {b['fire_service_lifts_prelim']}")]
    return items


def status(spec: dict, problems: list[str]) -> list[tuple[str, str]]:
    """(tone, text) lines: how KARR AI will find the lifts, and what will go wrong.

    tone is ok, bad or sim (lifts from the simulations). `problems` is `charts.check(spec)`.
    """
    if spec["model"] == "DBC-M2":
        lines = [("sim", "Lifts from the simulation PDFs")]
    elif not charts.has_chart(asset_for(spec["asset"]).key):
        lines = [("ok", "Lifts by DBC formula")]
    elif problems:
        lines = [("bad", f"Not computable: {p}") for p in problems]
    else:
        value, unit = charts.chart_value(spec)
        lines = [("ok", f"Inside the M1 chart ({value:,.0f} {unit})")]
    if spec["model"] == "DBC-M2" and simulation_problems(spec):
        lines = []
    lines += [("bad", f"No acceptable simulation: {p}") for p in simulation_problems(spec)]
    lines += [("bad", f"Entrance bias: {p}") for p in entrance_problems(spec)]
    return lines


def span_label(bottom: str, top: str) -> str:
    """'Level 6' and 'Level 7' read as 'Level 6–7'."""
    head, _, low = bottom.rpartition(" ")
    if head and top.startswith(head + " "):
        return f"{head} {low}–{top[len(head) + 1:]}"
    return f"{bottom}–{top}"


def stack(spec: dict) -> list[dict]:
    """The building top to bottom, identical floors run together.

    Each row: label, use (with ×count for a run), contents, height (m, as text) and
    kind (occupied, boarding or other).
    """
    rows = []
    for g in floor_table.floor_groups(spec):
        label = g["top"] if g["count"] == 1 else span_label(str(g["bottom"]), str(g["top"]))
        many = f" ×{g['count']}" if g["count"] > 1 else ""
        rows.append({"label": str(label), "use": f"{g['use']}{many}", "contents": g["contents"],
                     "height": f"{g['height_m']:.2f}" if g["height_m"] else "", "kind": g["kind"]})
    return rows


def details(spec: dict, render_source: str) -> str:
    """The line under a generated project's name. render_source: drawn, AI or uploaded."""
    source = spec["story"].get("source", "?")
    meta = [TYPES[asset_for(spec["asset"]).key], spec["model"], f"seed {spec.get('seed')}",
            "built-in names" if source == "fallback" else f"text by {source}", f"{render_source} render"]
    return " · ".join(meta)
