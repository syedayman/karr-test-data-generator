# KARR AI Test Data Generator

A small standalone web app that makes **fictional projects** for testing KARR AI.
For each project it produces every file a tester uploads, plus the values to type
into KARR AI's setup form:

| File | Goes to (KARR AI setup page) |
|---|---|
| `01 Architect design report.pdf` | Documents > Architect's design report |
| `02 Unit mix workbook.xlsx` | Documents > Unit mix / schedule Excel (with `Lifts Stacking Mix`, and `Entrance Bias`, `Operator Profile`, `Amenities Profile`, `Amenities Stacking Mix` when needed) |
| `03 Images/` | Report images > Project render (AI image, or a drawn one without a key), Architect plan / section figure |
| `04 Logos/` | Report images > Client / Architect / Lead consultant logo |
| `05`-`08` simulation PDFs | Building data > simulation uploads (M2 guest sims; hotel operator / amenities sims) |
| `00 KARR AI form values.txt` | Every setup-form value, section by section |
| `project.json` | The project itself: edit and upload it again to rebuild the files |

Covers all eight KARR AI building types (Residential, Office, Hotels, Hotel Apartments,
Car Parking, Retail, Schools, Universities) on DBC M1 and M2 (Retail is M1 only, as in
KARR AI).

## Choosing what you get

Every input starts empty and shows, in grey, the value the generator picked for the building in the
preview. Type or choose a value to fix it (black); clear it to hand it back to the generator.
A field KARR AI's setup page fills in by default starts on that default (no authority exception,
one core, lifts don't serve the roof, no multipurpose lift except Schools M1, no operator / amenities,
Independent car park, no escalators, KARR AI's capacities, hotels by star tier); the rest is random.

| Group | Options |
|---|---|
| Building | type, method (M1 / M2) |
| Size | occupied floors (bounded by the M1 limit), basements, cars per basement, typical and ground floor heights, and per type: apartment types (Studio to 6BR, + Maid, Duplex) + min / max apartments per floor, penthouse floors + type, min / max keys per floor, office / retail area per floor, cars per level, classrooms + students per room, mezzanine |
| Options | hotel stars, operator, public amenities; car park facility type, escalators (M2); retail moving walks |

Where KARR AI works out the Entrance Bias table itself from the parking column (Residential, Office M2), the simulation PDFs use that same split, and the preview warns when cars x 1.5 would outnumber the people in the building.

Residential people per unit follow DBC Table D.5 as KARR AI reads the column names: 4BR 5, then +1 per bedroom (5BR 6, 6BR 7), a penthouse with no bedroom count 5, duplex and maid's room +1 each.

Apartment and hotel floors come in runs (more units low down), each run with its own count. With a
min and max set, the lowest run gets the max, the highest the min, and the runs between fall inside.
| Project details | name, location, stage, cores, lift grouping, lobby depth, lift capacities, multipurpose lift, authority exception, lifts serve roof |
| Seed | same seed + same inputs = same project; one input changed leaves the rest as it was |

**Simulations** (M2, and hotel operator / amenities): lifts needed, speeds and capacities.
**Files**: tick the files and workbook sheets to include (the optional Hotel Apartments
`Public Area Occupancy` sheet is off by default).

After generating, every workbook sheet (unit mix / room schedule / parking mix, stacking mix,
amenities stacking, entrance bias, operator and amenities profiles, occupancy), the architect report
and each simulation PDF has its own view: **Edit** changes it cell by cell, **File** shows the file as
built. Floor edits rework travel, preliminary lifts and simulations; the render can be replaced with
an upload; **JSON** edits anything else.

**From JSON** rebuilds one project from a `project.json`. **Batch** makes random projects for every
type and method, or builds every project in several uploaded JSON files (each holds one project or a
list of them) into one zip. Both pages have a **Format** section: the keys, the floor fields, and
example files to download.

The preview says whether KARR AI's M1 chart will give a lift count. The chart limits in
`testgen/charts.py` were read off KARR AI's chart tables; auto-sized M1 buildings always stay inside.

## How it works

- **Numbers are made by rule** (`testgen/floors.py`, `testgen/spec.py`): floors, unit mix,
  heights, parking, classrooms and simulation results. People are counted the way KARR AI counts
  them. M2 projects get simulations with at least one acceptable and one failing lift option.
- **Names and report text come from the AI** (`testgen/ai.py`) when an OpenAI key is set,
  otherwise from a built-in list (`testgen/fallback_story.py`). All names are invented.
- **Travel heights and form values are worked out from the floors**, so editing floors or the JSON
  keeps everything consistent.
- Per-asset facts (M1 limits, waiting times, capacities, occupancy rates) live in `testgen/assets.py`
  and the M1 chart limits in `testgen/charts.py`. Keep both in step with
  `apps/api/worker/building_types/` in KARR AI.

## Run it locally

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

Optional `.streamlit/secrets.toml` (see `secrets.toml.example`): `OPENAI_API_KEY`,
`APP_PASSWORD`, `BUILDING_TYPES`, `TEXT_MODEL` (default `gpt-5.4-mini`), `IMAGE_MODEL`
(default `gpt-image-2.6-flare`, falls back to other GPT Image models).

`BUILDING_TYPES` picks the building types the app offers, comma-separated
(`residential, office, hotel, hotel_apartments, car_parking, retail, schools, universities`).
The others show greyed out in the dropdown, and From JSON / Batch refuse them. Leave it out for all types.

## Put it online (Streamlit Community Cloud, free)

1. Push this folder to a GitHub repository (private is fine).
2. Go to share.streamlit.io, sign in with GitHub, **Create app**, pick the repo, branch
   `main`, file `app.py`.
3. In **Advanced settings > Secrets** paste `OPENAI_API_KEY`, `APP_PASSWORD` and, to offer
   only some types, `BUILDING_TYPES` (e.g. `"residential"`).
4. Deploy and share the link and password.

To offer more types later, edit `BUILDING_TYPES` in the app's **Settings > Secrets** (or delete it
for all types); the app restarts with them.

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```
