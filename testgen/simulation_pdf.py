"""Fake traffic-simulation PDFs laid out like the reports KARR AI reads.

KARR AI looks for a `SIMULATION RESULTS` table (lifts, speed, accel, jerk,
capacity, door times, waiting / transit / destination times) and a
`BUILDING DATA` floor list. The pages copy that layout; the header marks the
file as generated test data.
"""

from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

_W, _H = A4
_LEFT = 40


class _Page:
    def __init__(self, c: canvas.Canvas, page: int, pages: int, job: str):
        self.c = c
        self.y = _H - 40
        c.setFont("Helvetica", 8)
        c.drawString(_LEFT, self.y, f"Page: {page} of {pages}")
        for line in [f"Job: {job}", "Job No:", "Calculation Title: FICTIONAL TEST DATA",
                     "Made By: KARR test data generator",
                     f"File/Date: {job} {datetime.now():%d %b %Y %H:%M:%S}"]:
            self.y -= 11
            c.drawString(_LEFT, self.y, line)
        self.y -= 18

    def heading(self, text: str):
        self.c.setFont("Helvetica-Bold", 10)
        self.c.drawString(_LEFT, self.y, text)
        self.y -= 14
        self.c.setFont("Helvetica", 8)

    def row(self, cells: list[tuple[float, str]], step: float = 11):
        for x, text in cells:
            self.c.drawString(_LEFT + x, self.y, text)
        self.y -= step

    def kv(self, key: str, value: str):
        self.row([(0, key), (230, value)])


_RESULT_COLS = [0, 38, 74, 108, 142, 186, 268, 312, 356, 400, 444, 488]
_RESULT_HEAD = [
    ["No. of", "Speed", "Acceln", "Jerk", "Elevator", "Door Times", "Average", "Longest", "Average",
     "Longest", "Average", "Longest"],
    ["Elevators", "(m/s)", "(m/s²)", "(m/s³)", "Capacity", "Pre-Open,Open,", "Waiting", "Waiting",
     "Transit", "Transit", "Time to", "Time to"],
    ["", "", "", "", "(kg)", "Close (s)", "Time (s)", "Time (s)", "Time (s)", "Time (s)", "Dest (s)",
     "Dest (s)"],
]


def build_simulation_pdf(job: str, served: list[dict], entrance: list[tuple[str, float]],
                         rows: list[dict], peak_label: str, building_type: str) -> bytes:
    """served: floors bottom to top with name, height_m, people, entrance (bool)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"{job} - simulation (test data)")

    # Page 1: analysis, building and elevator data
    p = _Page(c, 1, 3, job)
    p.heading("ANALYSIS DATA")
    for k, v in [("Analysis Type", "Simulation"), ("Measurement system", "Metric"),
                 ("Dispatcher Algorithm", "Group Collective Traffic mode: Normal"),
                 ("No of simulations to run for each configuration", "5")]:
        p.kv(k, v)
    p.y -= 6
    p.heading("BUILDING DATA")
    # KARR AI's table reader splits columns at the edges of the height values,
    # so the "Height" title must be narrower than a value ("4.450") to stay whole.
    cols = [0, 100, 170, 240, 300, 370]
    p.row([(x, t) for x, t in zip(cols, ["Floor Name", "", "No of people", "Area (m²)",
                                         "Area/person", "Entrance Floor"]) if t], step=0)
    c.setFont("Helvetica", 6.5)
    c.drawString(_LEFT + cols[1], p.y, "Height")
    c.setFont("Helvetica", 8)
    p.y -= 11
    for i, f in enumerate(served):
        top = i == len(served) - 1
        height = "" if top else f"{float(f.get('height_m') or 0):.3f}"
        cells = [f["name"], height, str(int(round(f.get("people", 0)))), "-", "-",
                 "Yes" if f.get("entrance") else "No"]
        p.row([(x, t) for x, t in zip(cols, cells) if t != ""])
    p.kv("Absenteeism (%)", "0.00")
    p.kv("Building Type", building_type)
    p.y -= 6
    p.heading("ELEVATOR DATA")
    lifts = sorted({r["lifts"] for r in rows})
    caps = sorted({r["capacity"] for r in rows})
    speeds = sorted({r["speed"] for r in rows})
    door = rows[0]["door"]
    for k, v in [("No of Elevators", f"SELECT Min: {lifts[0]} Max: {lifts[-1]}"),
                 ("Type", "Single Deck"),
                 ("Capacity (kg)", f"SELECT Min: {caps[0]} Max: {caps[-1]}"),
                 ("Door Pre-opening Time (s)", f"SPECIFIED {door[0]:.2f}"),
                 ("Door Open Time (s)", f"SPECIFIED {door[1]:.2f}"),
                 ("Door Close Time (s)", f"SPECIFIED {door[2]:.2f}"),
                 ("Speed (m/s)", f"SELECT Min: {speeds[0]:.2f} Max: {speeds[-1]:.2f}"),
                 ("Acceleration (m/s²)", f"SPECIFIED {rows[0]['accel']:.2f}"),
                 ("Jerk (m/s³)", f"SPECIFIED {rows[0]['jerk']:.2f}"),
                 ("Home Floor", served[0]["name"] if served else "")]:
        p.kv(k, v)
    c.showPage()

    # Page 2: passenger data and entrance bias
    p = _Page(c, 2, 3, job)
    p.heading("PASSENGER DATA")
    for k, v in [("Peak", peak_label), ("Arrangement", "Conventional for Single Deck elevators"),
                 ("Template", "Constant traffic (% building pop per 5 mins)"),
                 ("Demand (% pop per 5 mins)", "12.00"), ("Passenger Mass (kg)", "75"),
                 ("Capacity Factor by Mass (%)", "80.00")]:
        p.kv(k, v)
    p.y -= 6
    p.row([(0, "Floor Name"), (120, "Entrance Bias")])
    for name, pct in entrance:
        p.row([(0, name), (120, f"{pct:.2f}")])
    c.showPage()

    # Page 3: results
    p = _Page(c, 3, 3, job)
    # KARR AI's bounding-box reader starts 40 pt below the heading. The column
    # titles sit above that line so that reader sees only data rows and the
    # line-by-line reader (the one real reports go through) takes the table.
    c.setFont("Helvetica-Bold", 10)
    c.drawString(_LEFT, p.y, "SIMULATION RESULTS")
    c.setFont("Helvetica", 7)
    for i, head in enumerate(_RESULT_HEAD):
        for x, t in zip(_RESULT_COLS, head):
            if t:
                c.drawString(_LEFT + x, p.y - 10 - 7 * i, t)
    c.setFont("Helvetica", 8)
    p.y -= 46
    for r in rows:
        door_txt = ", ".join(f"{d:.2f}" for d in r["door"])
        cells = [str(r["lifts"]), f"{r['speed']:.2f}", f"{r['accel']:.2f}", f"{r['jerk']:.2f}",
                 str(r["capacity"]), door_txt, f"{r['awt']:.1f}", f"{r['lwt']:.1f}",
                 f"{r['att']:.1f}", f"{r['ltt']:.1f}", f"{r['atd']:.1f}", f"{r['ltd']:.1f}"]
        p.row(list(zip(_RESULT_COLS, cells)))
    c.showPage()
    c.save()
    return buf.getvalue()
