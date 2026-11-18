"""Names and prose for a project when no AI key is set (or the AI call fails).

All names are invented. The text is written so KARR AI's report prompts have
a design-intent paragraph, a site description and a building description to
summarise.
"""

from __future__ import annotations

import random

from .assets import Asset

_FIRST = ["Azure", "Palm", "Coral", "Silver", "Falcon", "Oasis", "Pearl", "Dune", "Cedar",
          "Harbour", "Saffron", "Crescent", "Mirage", "Amber", "Lotus", "Horizon"]
_SECOND = {
    "residential": ["Residences", "Heights", "Tower", "Gardens", "Living"],
    "office": ["Business Tower", "Office Park", "Commerce Centre", "Exchange"],
    "hotel": ["Grand Hotel", "Resort & Spa", "Hotel", "Suites Hotel"],
    "hotel_apartments": ["Hotel Apartments", "Serviced Residences", "Suites"],
    "car_parking": ["Car Park", "Parking Hub", "Mobility Hub"],
    "retail": ["Mall", "Shopping Centre", "Galleria", "Souk"],
    "schools": ["International School", "Academy", "Primary School"],
    "universities": ["University Campus", "Institute of Technology", "College"],
}
_DISTRICTS = {
    "Dubai": ["Dubai Marina", "Business Bay", "Jumeirah Village Circle", "Dubai Hills", "Al Furjan"],
    "Abu Dhabi": ["Al Reem Island", "Saadiyat Island", "Yas Island", "Al Raha Beach"],
    "Sharjah & N.E.": ["Aljada", "Al Majaz", "Muwaileh", "Al Khan"],
}
_CLIENTS = ["Dune Ridge Developments","Sandstone Properties", "Blue Lagoon Holdings",
            "Meridian Gulf Real Estate", "Arcadia Development Co.", "Safa Crest Investments"]
_ARCHITECTS = ["Studio Qamar Architects", "Linea Design Partners", "Northlight Architecture",
               "Mosaic Atelier", "Vantage Form Architects", "Atrium & Co. Architects"]
_CONSULTANTS = ["Orbit Engineering Consultants", "Keystone MEP Consultants",
                "Summit Building Services", "Parallax Engineering"]
_PEOPLE = ["A. Rahman", "S. Menon", "L. Haddad", "R. Iyer", "M. Costa", "J. Okafor", "N. Farouk"]
_BRANDS = ["Lumen", "Sahra", "Marlowe", "Veranda", "Corniche", "Atlas"]

_VISION = {
    "residential": "a calm vertical neighbourhood where every home opens to light and views",
    "office": "a flexible workplace that puts people, daylight and collaboration first",
    "hotel": "a destination hotel that blends local hospitality with a contemporary skyline presence",
    "hotel_apartments": "a serviced-living address combining hotel services with the comfort of home",
    "car_parking": "an efficient, legible parking structure that is easy and safe to move through",
    "retail": "a lively community retail destination organised around shaded courts",
    "schools": "a nurturing learning environment with daylit classrooms and generous shared spaces",
    "universities": "an open academic hub that encourages research, exchange and campus life",
}


def make(rng: random.Random, asset: Asset, opts: dict) -> dict:
    # Draw first, then apply the tester's choice, so a chosen name or location
    # does not change the random numbers that follow.
    location = rng.choice(list(_DISTRICTS))
    location = opts.get("location") if opts.get("location") in _DISTRICTS else location
    district = rng.choice(_DISTRICTS[location])
    name = f"{rng.choice(_FIRST)} {rng.choice(_SECOND[asset.key])}"
    name = opts.get("project_name") or name
    architect = rng.choice(_ARCHITECTS)
    author, approver = rng.sample(_PEOPLE, 2)
    vision = _VISION[asset.key]
    return {
        "source": "fallback",
        "project_name": name,
        "client": rng.choice(_CLIENTS),
        "architect": architect,
        "lead_consultant": rng.choice(_CONSULTANTS),
        "location": location,
        "address": f"Plot {rng.randint(100, 999)}-{rng.randint(10, 99)}, {district}, {location}, UAE",
        "author": author,
        "approved_by": approver,
        "operator_brand": rng.choice(_BRANDS),
        "vision": (
            f"{name} is conceived as {vision}. The design intent is to create a clear, "
            f"memorable massing that responds to its setting in {district}, with a strong "
            "ground-floor presence, a sheltered arrival experience and a simple, efficient "
            "core. Planning keeps vertical circulation central so every level is reached "
            "quickly, while the facade balances solar shading with open views."
        ),
        "site": (
            f"The site sits in {district}, {location}, with frontage onto a primary road and a "
            "secondary service street. Vehicle drop-off and basement ramps are taken from the "
            "service side to keep the main frontage pedestrian-friendly."
        ),
        "massing": (
            "The building rises from a podium base to a slender upper volume. Floors are stacked "
            "around a single central core containing passenger lifts, the fire-fighting lift, "
            "stairs and risers."
        ),
        "facade": (
            "A unitised glazed facade with vertical fins and horizontal shading bands reduces "
            "solar gain on the south and west elevations."
        ),
        "amenities": "Shared amenities include a landscaped arrival court, fitness facilities and a rooftop terrace.",
        "sustainability": (
            "The project targets Al Sa'fat Silver / Estidama-equivalent performance with efficient "
            "glazing, LED lighting and water-saving fittings."
        ),
        "render_prompt": (
            f"Architectural exterior render of {name}, a {asset.classification.lower()} building in "
            f"{district}, {location}, UAE, modern facade, daytime, blue sky, photorealistic"
        ),
    }
