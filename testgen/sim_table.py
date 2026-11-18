"""Simulation result rows as a flat table for the app's simulation editor.

A spec row keeps the three door times as one list; the table gives each its
own column. `set_rows` writes edited rows back to the right simulation.
"""

from __future__ import annotations

import math

# (row key, column label, whole number?)
COLUMNS = [
    ("lifts", "Lifts", True), ("speed", "Speed (m/s)", False), ("accel", "Accel (m/s²)", False),
    ("jerk", "Jerk (m/s³)", False), ("capacity", "Capacity (kg)", True),
    ("door0", "Door pre-open (s)", False), ("door1", "Door open (s)", False), ("door2", "Door close (s)", False),
    ("awt", "Avg wait (s)", False), ("lwt", "Longest wait (s)", False),
    ("att", "Avg transit (s)", False), ("ltt", "Longest transit (s)", False),
    ("atd", "Avg to dest (s)", False), ("ltd", "Longest to dest (s)", False),
]
# Columns KARR AI's report takes from the winning row; the rest stay in the PDF for its reader.
REPORTED = {"lifts", "speed", "accel", "jerk", "capacity", "door1", "door2", "awt", "atd"}
_PATHS = {"Morning peak": ("guest", "morning"), "Evening peak": ("guest", "evening"),
          "Breaks peak": ("guest", "evening"), "Guest simulation": ("guest", "single"),
          "Operator simulation": ("operator",), "Amenities simulation": ("amenities",)}


def to_table(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        flat = {k: r[k] for k, _, _ in COLUMNS if not k.startswith("door")}
        flat.update({f"door{i}": r["door"][i] for i in range(3)})
        out.append({label: flat[k] for k, label, _ in COLUMNS})
    return out


def _blank(value) -> bool:
    return value is None or type(value).__name__ == "NAType" or (isinstance(value, float) and math.isnan(value))


def from_table(records: list[dict]) -> list[dict]:
    """Edited table rows back to simulation rows (rows left fully empty are dropped)."""
    rows = []
    for rec in records:
        values = {k: rec.get(label) for k, label, _ in COLUMNS}
        if all(_blank(v) for v in values.values()):
            continue
        clean = {k: (0 if _blank(v) else (int(v) if whole else round(float(v), 2)))
                 for (k, _, whole), v in zip(COLUMNS, values.values())}
        row = {k: v for k, v in clean.items() if not k.startswith("door")}
        row["door"] = [clean["door0"], clean["door1"], clean["door2"]]
        rows.append(row)
    return rows


def set_rows(spec: dict, label: str, rows: list[dict]) -> None:
    """Put `rows` in the simulation that `spec.simulation_tables` calls `label`."""
    node = spec["simulations"]
    *parents, key = _PATHS[label]
    for p in parents:
        node = node[p]
    node[key] = rows
