"""The inputs of a new project as plain data: labels, kinds, ranges and choices.

Every field is one optional `make_spec` option. Left empty, the generator picks
a value and its pick shows in grey (`shown`). The Streamlit app and KARR AI's
Archies Architect page both draw their forms from `form`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .assets import ASSETS, HOTEL_APARTMENT_UNIT_TYPES, HOTEL_STARS, RESIDENTIAL_UNIT_TYPES
from .floors import SIZING, occupied_limits
from .spec import FIRE_CAPACITIES, GROUPINGS, LOCATIONS, PASSENGER_CAPACITIES, PROJECT_TYPES, SIM_SPEEDS

TYPES = {
    "residential": "Residential", "office": "Office", "hotel": "Hotel", "hotel_apartments": "Hotel Apartments",
    "car_parking": "Car Parking", "retail": "Retail", "schools": "School", "universities": "University",
}
FLOOR_LABEL = {
    "residential": "Apartment floors", "office": "Office floors", "hotel": "Room floors",
    "hotel_apartments": "Apartment floors", "car_parking": "Parking levels", "retail": "Occupied floors",
    "schools": "Teaching floors", "universities": "Teaching floors",
}
GROUPING_LABEL = {"in-line": "In-line", "facing_each_other": "Facing each other"}
PASSENGER_KG = tuple(sorted({*PASSENGER_CAPACITIES, *(a.passenger_kg for a in ASSETS.values())}))
FIRE_KG = tuple(sorted({*FIRE_CAPACITIES, *(a.fire_kg for a in ASSETS.values())}))
# Form sections the app shows only sometimes
SIMULATIONS = "Simulations"  # when the project has simulations (`"sim_lifts" in resolved_options`)
PROJECT_DETAILS = "Project details"  # folded away


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
    labels: tuple[tuple[Any, str], ...] = ()  # (choice, how it reads) where it reads differently
    span: int = 1  # columns it takes
    blank: str = ""  # what the generator does when it picks no value

    def text(self, value) -> str:
        """How one choice reads."""
        named = dict(self.labels).get(value)
        if named is not None:
            return named
        return f"{value:g}" if isinstance(value, float) and self.choices else str(value)


def methods(asset_key: str) -> list[str]:
    return ["DBC-M1", "DBC-M2"] if ASSETS[asset_key].supports_m2 else ["DBC-M1"]


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
         Field("elevator_grouping", "Lift grouping", "choice", choices=tuple(GROUPINGS),
               labels=tuple(GROUPING_LABEL.items())),
         Field("lobby_depth_m", "Lobby depth (m)", "float", 1.5, 8.0, 0.5)],
        # Lifts facing each other: how many stand in the first row (empty: half,
        # the bigger half first). KARR AI's lift drawings only.
        [Field("front_row_lifts", "Lifts in row 1", "int", 1, 4, blank="Half")],
        [Field("passenger_capacity_kg", "Passenger lift (kg)", "choice", choices=PASSENGER_KG),
         Field("fire_service_capacity_kg", "Fire/service lift (kg)", "choice", choices=FIRE_KG),
         Field("multipurpose_elevator", "Multipurpose lift", "yesno")],
        [Field("authority_exceptions", "Authority exception", "yesno"),
         Field("serves_roof", "Lifts serve roof", "yesno")],
    ]


def simulation_fields() -> list[list[Field]]:
    return [[Field("sim_lifts", "Lifts needed", "int", 1, 12),
             Field("sim_speeds", "Speeds (m/s)", "multi", choices=tuple(SIM_SPEEDS), span=2),
             Field("sim_capacities", "Capacities (kg)", "multi", choices=tuple(PASSENGER_KG), span=2)]]


def form(asset_key: str, model: str) -> list[tuple[str, int, list[list[Field]]]]:
    """The form's sections in order: (title, columns per row, rows of fields)."""
    asset = ASSETS[asset_key]
    sections = [("Size", 4, size_fields(asset, model))]
    extra = option_fields(asset, model)
    if extra:
        sections.append(("Options", 3, extra))
    sections += [(SIMULATIONS, 5, simulation_fields()), (PROJECT_DETAILS, 3, project_fields())]
    return sections


def shown(field: Field, value) -> str:
    """The generator's pick as grey placeholder text."""
    if value is None:
        return field.blank
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, tuple):
        return "–".join(shown(field, v) for v in value)
    if isinstance(value, list):
        return ", ".join(field.text(v) for v in value)
    if field.kind == "float":
        return f"{value:.2f}"
    return field.text(value)
