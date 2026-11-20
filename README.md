# Archies Architect

KARR AI's VT test data generator: a small standalone web app that makes **fictional projects**
for testing KARR AI. For each project it produces every file a tester uploads, the values to type
into KARR AI's setup form, and the project as JSON:

| File | Goes to (KARR AI setup page) |
|---|---|
| `01 Architect design report.pdf` | Documents > Architect's design report |
| `02 Unit mix workbook.xlsx` | Documents > Unit mix / schedule Excel (with `Lifts Stacking Mix`, and `Entrance Bias`, `Operator Profile`, `Amenities Profile`, `Amenities Stacking Mix` when needed) |
| `03 Images/` | Report images > Project render (AI image, or a drawn one without a key), Architect plan / section figure |
| `04 Logos/` | Report images > Client / Architect / Lead consultant logo |
| `05`-`08` simulation PDFs | Building data > simulation uploads (M2 guest sims; hotel operator / amenities sims) |
| `00 KARR AI form values.txt` | Every setup-form value, section by section |
| `project.json` | The whole project as data (format below) |

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
| Size | occupied floors (bounded by the M1 limit), basements, cars per basement, typical and ground floor heights, and per type: apartment types (Studio to 6BR, + Maid, Duplex) + min / max apartments per floor, min / max keys per floor, office / retail area per floor, cars per level, classrooms + students per room, mezzanine |
| Options | hotel stars, operator, public amenities; car park facility type, escalators (M2); retail moving walks |
| Project details | name, location, stage, cores, lift grouping, lobby depth, lift capacities, multipurpose lift, authority exception, lifts serve roof |
| Seed | same seed + same inputs = same project; one input changed leaves the rest as it was |

Where KARR AI works out the Entrance Bias table itself from the parking column (Residential, Office M2), the simulation PDFs use that same split, and the preview warns when cars x 1.5 would outnumber the people in the building.

Residential people per unit follow DBC Table D.5 as KARR AI reads the column names: 4BR 5, then +1 per bedroom (5BR 6, 6BR 7), duplex and maid's room +1 each.

Apartment and hotel floors come in runs (more units low down), each run with its own count. With a
min and max set, the lowest run gets the max, the highest the min, and the runs between fall inside.

**Simulations** (M2, and hotel operator / amenities): lifts needed, speeds and capacities.
**Files**: tick the files and workbook sheets to include (the optional Hotel Apartments
`Public Area Occupancy` sheet is off by default).

After generating, every workbook sheet (unit mix / room schedule / parking mix, stacking mix,
amenities stacking, entrance bias, operator and amenities profiles, occupancy), the architect report
and each simulation PDF has its own view: **Edit** changes it cell by cell, **File** shows the file as
built. Floor edits rework travel, preliminary lifts and simulations; the render can be replaced with
an upload; **JSON** shows the project.json.

**Batch** makes random projects for every type and method into one zip: a folder of files for each
project, and `projects.json` at the top with every project's JSON in one list.

The preview says whether KARR AI's M1 chart will give a lift count. The chart limits in
`testgen/charts.py` were read off KARR AI's chart tables; auto-sized M1 buildings always stay inside.

## project.json

One project per file (`projects.json` holds a list of them). Travel heights, population and form
values are not stored: they are worked out from the floors.

| Key | Contents |
|---|---|
| `spec_version`, `asset`, `model` | format version, building type key, `DBC-M1` / `DBC-M2` |
| `project_info` | the setup page's project fields (classification, name, client, architect, location, revision, header / footer, ...); `hotel_star_rating`, `car_parking_facility_type`, `car_parking_has_escalators` where they apply |
| `building` | authority exceptions, preliminary lift counts; `has_operator`, `has_amenities` for hotels |
| `vt_criteria` | `core_count`, `elevator_grouping`, `lobby_depth_m`, `serves_roof`, `multipurpose_elevator` |
| `space_planning` | `passenger_capacity_kg`, `fire_service_capacity_kg`, `machine_type` |
| `unit_types` | residential / hotel apartments / hotel: unit or room types in schedule order |
| `floors` | every floor, top first: `name`, `height_m`, `use`, `occupied`, `boarding`, and per type `units`, `area_m2`, `cars`, `classrooms`, `students_per_classroom`, `staff`, `amenity`, `rooftop` |
| `operator_profile`, `amenities_profile` | hotels, when switched on |
| `entrance_bias` | hotels, hotel apartments, car parking M2: rows of floor, parking, percent |
| `simulations` | M2 guest peaks and hotel sidecars: result rows (lifts, speed, capacity, door times, waiting / transit times) |
| `public_area_occupancy`, `outputs.skip`, `story` | hotel apartments public areas, files left out, names and architect report text |

## How it works

- **Numbers are made by rule** (`testgen/floors.py`, `testgen/spec.py`): floors, unit mix,
  heights, parking, classrooms and simulation results. People are counted the way KARR AI counts
  them. M2 projects get simulations with at least one acceptable and one failing lift option.
- **Names and report text come from the AI** (`testgen/ai.py`) when an OpenAI key is set,
  otherwise from a built-in list (`testgen/fallback_story.py`). All names are invented.
- **Travel heights and form values are worked out from the floors**, so editing floors keeps
  everything consistent.
- Per-asset facts (M1 limits, waiting times, capacities, occupancy rates) live in `testgen/assets.py`
  and the M1 chart limits in `testgen/charts.py`. Keep both in step with
  `apps/api/worker/building_types/` in KARR AI.
- **What the app shows comes from the package too**: the form (`testgen/fields.py`), the preview's
  facts, status and floor stack (`testgen/summary.py`), the result views and their editors
  (`testgen/edits.py`) and the batch zip (`testgen/bundle.py`). `app.py` and `views.py` only draw them.

## Inside KARR AI

KARR AI runs the same engine for its admin accounts (Archies Architect in its navbar), where it also
makes VT reports straight from these projects. Its `apps/api/worker/archies/` is an exact copy of
`testgen/`: after changing anything in `testgen/`, run the tests here, copy every `testgen/*.py`
there unchanged, and check the copies match. KARR AI's `docs/ARCHIES.md` has the rest.

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
The others show greyed out in the dropdown and Batch leaves them out. Leave it out for all types.

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
