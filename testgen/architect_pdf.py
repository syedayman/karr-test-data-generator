"""Fake architect's design report (KARR AI document type `pdf`).

KARR AI embeds this PDF for its report text (design intent summary) and for
Ask Medha questions, so it carries the usual chapters: vision, site, massing,
facade, amenities, area schedule, vertical transportation and sustainability.
"""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .assets import asset_for
from .spec import counts_people, floor_people

_STYLES = getSampleStyleSheet()
_BODY = ParagraphStyle("body", parent=_STYLES["BodyText"], fontSize=10, leading=14, spaceAfter=6)
_H1 = ParagraphStyle("h1", parent=_STYLES["Heading1"], fontSize=16, spaceBefore=8, spaceAfter=8)
_H2 = ParagraphStyle("h2", parent=_STYLES["Heading2"], fontSize=12, spaceBefore=6, spaceAfter=4)
_SMALL = ParagraphStyle("small", parent=_BODY, fontSize=8, leading=10)
_TITLE = ParagraphStyle("title", parent=_STYLES["Title"], fontSize=24, leading=30)


def _img(png: bytes, max_w: float, max_h: float) -> Image:
    from PIL import Image as PILImage

    w, h = PILImage.open(io.BytesIO(png)).size
    scale = min(max_w / w, max_h / h)
    return Image(io.BytesIO(png), width=w * scale, height=h * scale)


def _table(rows: list[list], col_widths=None, font=8) -> Table:
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", font),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", font),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE6F0")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _schedule_rows(spec: dict) -> tuple[list[list], list[float] | None]:
    asset = asset_for(spec["asset"])
    floors = spec["floors"]
    if asset.key in ("residential", "hotel", "hotel_apartments"):
        types = spec["unit_types"]
        area = asset.hotel_like
        rows = [["Level", "Use", *types, "Total"] + (["Area (m²)"] if area else [])]
        for f in floors:
            u = [f.get("units", {}).get(t, 0) for t in types]
            row = [f["name"], Paragraph(str(f["use"]), _SMALL), *u, sum(u)]
            rows.append(row + ([f.get("area_m2") or "-"] if area else []))
        return rows, None
    if asset.key in ("schools", "universities"):
        rows = [["Level", "Use", "Rooms", "Students / room", "Staff"]]
        for f in floors:
            rows.append([f["name"], Paragraph(str(f["use"]), _SMALL), f.get("classrooms") or "-",
                         f.get("students_per_classroom") or "-", f.get("staff") or "-"])
        return rows, [70, 220, 50, 80, 50]
    rows = [["Level", "Use", "GFA (m²)", "Parking bays"]]
    for f in floors:
        rows.append([f["name"], Paragraph(str(f["use"]), _SMALL), f.get("area_m2") or "-", f.get("cars") or "-"])
    return rows, [70, 260, 70, 70]


def build_architect_pdf(spec: dict, derived: dict, render_png: bytes,
                        section_png: bytes, plan_png: bytes) -> bytes:
    asset = asset_for(spec["asset"])
    info = spec["project_info"]
    story = spec["story"]
    b = spec["building"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"{info['project_name']} - Architectural Design Report",
                            author=info["architect"])

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 10 * mm, f"{info['architect']} | {info['project_name']} | Design Report")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    s: list = [
        Spacer(1, 20 * mm),
        Paragraph(info["project_name"], _TITLE),
        Paragraph(f"Architectural Design Report - {info.get('project_type') or 'Concept'} Stage", _H2),
        Spacer(1, 6 * mm),
        _img(render_png, 170 * mm, 110 * mm),
        Spacer(1, 6 * mm),
        _table([
            ["Client / Developer", info["employer_client_developer"]],
            ["Architect", info["architect"]],
            ["Lead consultant", info["lead_consultant"]],
            ["Location", info["project_address"]],
            ["Building type", asset.classification],
            ["Document reference", info["reference"]],
            ["Date", f"{date.today():%d %B %Y}"],
        ], col_widths=[50 * mm, 110 * mm], font=9),
        Spacer(1, 4 * mm),
        Paragraph("Fictional project created as test data. Names, places and figures are invented.", _SMALL),
        PageBreak(),
        Paragraph("1. Introduction and Design Vision", _H1),
        Paragraph(story["vision"], _BODY),
        Paragraph("2. Site and Context", _H1),
        Paragraph(story["site"], _BODY),
        Paragraph("3. Massing, Planning and Core", _H1),
        Paragraph(story["massing"], _BODY),
        Paragraph("4. Facade and Materials", _H1),
        Paragraph(story["facade"], _BODY),
        Paragraph("5. Amenities", _H1),
        Paragraph(story["amenities"], _BODY),
        PageBreak(),
        Paragraph("6. Area and Floor Schedule", _H1),
    ]
    rows, widths = _schedule_rows(spec)
    s.append(_table(rows, col_widths=widths))
    s.append(Spacer(1, 4 * mm))
    occupied = derived["occupied_floors"]
    people = round(sum(floor_people(asset, spec, f) for f in spec["floors"]
                       if counts_people(asset, f)))
    s += [
        Paragraph(
            f"The building has {len(spec['floors'])} levels in total, of which {occupied} are occupied "
            f"floors. The architect's estimate of the occupied population is about {people} people.", _BODY),
        PageBreak(),
        Paragraph("7. Vertical Transportation (Preliminary)", _H1),
        Paragraph(
            f"The preliminary design provides {b.get('passenger_lifts_prelim')} passenger lift(s) and "
            f"{b.get('fire_service_lifts_prelim')} fire-fighting / service lift(s) in "
            f"{spec['vt_criteria'].get('core_count') or 1} core(s). Passenger lifts serve "
            f"{derived['passenger_bottom']} to {derived['passenger_top']} "
            f"({derived['stops']} stops, travel about {derived['passenger_travel_m']} m). The fire-fighting "
            f"lift serves every level, travel about {derived['fire_travel_m']} m. Lift numbers, sizes and "
            "speeds are to be confirmed by the VT consultant's traffic analysis.", _BODY),
        Paragraph(
            f"Lifts are arranged {spec['vt_criteria'].get('elevator_grouping', 'in-line').replace('_', ' ')} "
            f"with a lift lobby depth of about {spec['vt_criteria'].get('lobby_depth_m')} m.", _BODY),
        _img(plan_png, 170 * mm, 100 * mm),
        Paragraph("Figure 1 - Typical floor plan (schematic)", _SMALL),
        PageBreak(),
        _img(section_png, 170 * mm, 230 * mm),
        Paragraph("Figure 2 - Building section (schematic)", _SMALL),
        PageBreak(),
        Paragraph("8. Sustainability", _H1),
        Paragraph(story["sustainability"], _BODY),
    ]
    doc.build(s, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
