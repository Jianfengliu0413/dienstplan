

# UKT IM2 Duty Scheduler

## Overview

This system automatically generates monthly duty schedules. It uses Google OR-Tools to solve a constraint‑based optimisation problem, balancing workloads, respecting doctor qualifications, and handling substitutions when needed.

The core is a Python backend that reads Excel templates, runs the solver, and writes back the optimised schedule. A Streamlit web interface makes it easy for non‑technical users to upload files, adjust parameters, and download results.

------

## Architecture

### Modules

| Module            | Responsibility                                               |
| :---------------- | :----------------------------------------------------------- |
| parser.py         | Reads the monthly template Excel and builds a ScheduleModel (doctors, stations, days, duties, availability). |
| demand_builder.py | Computes the required number of duties per station/day based on WeekdayDutyCounts, WeekendDutyCounts, and DayDemand overrides. Adds SUB duties when a station lacks its own available doctors. |
| constraints.py    | Defines hard constraints for the solver (e.g., each duty assigned to exactly one doctor, max duties per week, station match, skill requirements). |
| objective.py      | Defines soft constraints (penalties) to guide the solver towards a balanced, high‑quality schedule. |
| solver.py         | Uses OR-Tools CP-SAT to solve the model. Falls back to a repair mode if the initial model is infeasible. |
| writer.py         | Writes the final schedule back to the Excel template, adding statistics, conflict reports, and explanations. |
| visualize.py      | Generates plots (workload, weekend duties, KM rotation, heatmap) for quick validation. |
| app.py            | Streamlit user interface for uploading, editing, running, and downloading. |
| config_loader.py  | Loads all sheets from Rules.xlsx into pandas DataFrames.     |
| scheduler.py      | Orchestrates the entire pipeline: parse -> validate -> solve -> write -> visualise. |

### Data Flow

text

```
Template (.xlsx)  +  Rules.xlsx  +  Wishes.xlsx (optional)
        |                    |                    |
        +--------------------+--------------------+
                             |
                             v
                     parse_template
                     (build model)
                             |
                             v
                     build_demand
                             |
                             v
                     solver (CP-SAT)
                             |
                             v
                     write_output
                             |
                             v
                     Output schedule (.xlsx)
                     + updated Rules.xlsx
                     + WorkingHours.xlsx
```

------

## Installation and Setup

### 1. Clone the repository

```
git clone https://github.com/your-org/dienstplan.git
cd dienstplan
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3. Run the Streamlit app (optional)

```
streamlit run app.py
```

### 4. Run the scheduler from the command line

```
python scheduler.py
```

------

## Configuration – Rules.xlsx

All configuration is stored in a single Excel file Rules.xlsx. Each sheet is described below.

### Settings

| Setting             | Description                                                  |
| :------------------ | :----------------------------------------------------------- |
| TemplateFile        | Path to the monthly Stationsplan file.                       |
| OutputFile          | Path where the generated schedule will be saved.             |
| ScheduleSheet       | Sheet name in the template containing the schedule data.     |
| DoctorNameColumn    | Column (e.g., "A") where doctor names are found.             |
| StationColumn       | Column (e.g., "B") containing station codes/names.           |
| FixedValues         | Values that mark a cell as fixed/unavailable (e.g., x, U, NAZ). |
| EditablePlaceholder | Value indicating an empty cell (default 0).                  |
| VacationColor       | Hex color code for vacation (light green).                   |
| UnavailableColor    | Hex color code for dark-green unavailable cells.             |
| WishesFile          | Optional path to a wishes file.                              |

### StationCodeMap

Maps station codes (numbers or strings) used in the template to full station names.

| Code | Station |
| :--- | :------ |
| 1    | 65 PP   |
| 2    | 65 LAF  |
| ...  | ...     |

### Doctors

| Column  | Description                                                 |
| :------ | :---------------------------------------------------------- |
| Name    | Doctor’s full name.                                         |
| FTE (%) | Percentage full-time equivalent (e.g., 100, 50, 20).        |
| Station | Home station (must match a station name in StationCodeMap). |
| Active  | Yes/No – inactive doctors are excluded from scheduling.     |
| Weekend | Yes/No – whether the doctor can work on weekends.           |

### Stations

| Column            | Description                                                  |
| :---------------- | :----------------------------------------------------------- |
| Station           | Station name (must match a station in StationCodeMap).       |
| RequiresSenior    | Yes/No – whether all duties at this station require a senior doctor. |
| WeekdayDutyCounts | Comma-separated list, e.g., ZD=1, SD=1 (one ZD and one SD on each weekday). |
| WeekendDutyCounts | Same format, for weekends (e.g., PR=1).                      |

Note: If WeekdayDutyCounts is empty, no duties are generated for weekdays. DayDemand can override specific days.

### DutyTypes

| Abbr | FullName            | RequiresSenior | WeekendOnly | Priority | Hours |
| :--- | :------------------ | :------------- | :---------- | :------- | :---- |
| ZD   | Zwischendienst      | No             | No          | 1        | 8.5   |
| SD   | Spätdienst          | No             | No          | 1        | 8.5   |
| KM   | Knochenmarkentnahme | Yes            | No          | 2        | 3.0   |
| PR   | Präsenz             | No             | No          | 1        | 8.5   |
| SUB  | Substitution        | No             | No          | 1        | 8.5   |
| ...  | ...                 | ...            | ...         | ...      | ...   |

- Hours is used for workload balancing (total working hours per doctor).
- RequiresSenior forces the duty to be assigned only to doctors with the Senior skill.
- WeekendOnly ensures the duty is only placed on weekends.

### Penalties

Soft constraint weights – higher values make the constraint more important.

| Penalty         | Description                                           | Recommended Weight |
| :-------------- | :---------------------------------------------------- | :----------------- |
| Preference      | Satisfy doctor preferences (wishes)                   | 10                 |
| WorkloadBalance | Balance total hours according to FTE                  | 100                |
| WeekendBalance  | Distribute weekend duties evenly                      | 15                 |
| KMBalance       | Distribute KM duties evenly                           | 30                 |
| CrossStation    | Penalise assigning a doctor to a station != their own | 30                 |
| DayOffPenalty   | Avoid assigning duties on light-green (day-off) cells | 50                 |

### Constraints

Hard constraints that cannot be violated (Enabled = Yes).

| Constraint             | Description                                              |
| :--------------------- | :------------------------------------------------------- |
| MaxConsecutive         | Limit consecutive working days (set in GeneralRules).    |
| MaxPerWeek             | Max duties per week (set in GeneralRules).               |
| WeekendOnly            | Enforce that WeekendOnly duties only appear on weekends. |
| SeniorRequired         | Enforce seniority requirements.                          |
| WeekendAvailability    | Only doctors with Weekend=Yes can take weekend duties.   |
| WeekendOnlyFullTime    | Weekend shifts only for 100% FTE doctors.                |
| WeekendOnlyForSkilled  | Only doctors with the Weekend skill can work weekends.   |
| MaxOneWeekendPerDoctor | At most one weekend assignment per doctor per month.     |

### GeneralRules

| RuleName               | Value |
| :--------------------- | :---- |
| MaxConsecutiveWorkDays | 6     |
| MaxDutiesPerWeek       | 6     |
| MaxWeekendPerDoctor    | 3     |

### DayDemand

Overrides the default station demand for specific days.

| Station | DayOfWeek | DutyType | Count |
| :------ | :-------- | :------- | :---- |
| 92 KMT  | Monday    | KM       | 1     |
| 92 KMT  | Tuesday   | KM       | 1     |

### Skills

Each doctor can have multiple skills (duty abbreviations or special flags like Senior, Weekend).

| Doctor | DutyType |
| :----- | :------- |
| J*     | ZD       |
| J*     | SD       |
| J*     | Senior   |

If a doctor lacks a skill for a duty, they cannot be assigned to that duty (unless in repair mode).

### HolidayRules (optional)

Manually add unavailable days.

| Doctor | Day  | Type     |
| :----- | :--- | :------- |
| J*     | 15   | Vacation |

### Preferences (optional)

Doctor preferences (positive = wants, negative = avoids).

| Doctor | Day  | DutyType | Priority |
| :----- | :--- | :------- | :------- |
| J*     | 10   | ZD       | 10       |

### WorkingHours (auto-generated)

This sheet is overwritten after each run. It contains the cumulative working hours for each doctor, used in the workload balance objective.

------

## Input Files

### Template (Stationsplan)

- Must have the month in cell A1 (e.g., 01.11.2026 or November 2026).
- Row 1: date headers (day numbers).
- Column A: doctor names.
- Column B: station codes (matching StationCodeMap).
- Doctors are listed under their station headers.
- Cells marked with x, U, or any value in FixedValues are considered fixed/unavailable.
- Dark-green fill -> hard unavailable.
- Light-green fill -> day-off preference (soft).

### Wishes File (optional)

- Same structure as the template, but only contains the rows for doctors who have wishes.
- Values can be:
  - Station codes (e.g., 92) -> creates a preference for that station.
  - Duty abbreviations (e.g., NAZ, HD) -> creates a fixed assignment at the doctor's own station.
  - Fixed values (e.g., x, U) -> marks the day as unavailable.
- Weekend codes like 65P will create a fixed PR duty at that station.

------

## How the Solver Works

1. Build demand – For each station and day, calculate how many of each duty type are required (from Stations + DayDemand).
2. Add substitution duties – If a station has demand but no available doctor from that station (due to vacations, etc.), add a SUB duty. Only doctors from 65 PP can cover SUB.
3. Hard constraints – Enforce station match (except PR on weekends and SUB), skills, vacations, max consecutive days, max per week.
4. Soft constraints – Minimise penalties for workload imbalance, cross-station, unsatisfied preferences, etc.
5. Repair mode – If the model is infeasible, the solver relaxes skill constraints and tries again.

------

## Output Files

The scheduler generates:

- Schedule – the original template with duties filled in (same sheet name).
- Statistics – summary of duties per doctor (total, SD, ZD, KM, weekend, expected).
- ConflictReport – unsat preferences and workload imbalances.
- Explanation – detailed list of each assignment.
- DayOffSuggestions – recommended days off for part-time doctors (if hours exceed FTE target).
- WorkingHours – updated cumulative hours for each doctor (also written to Rules.xlsx).

------

## Customising for Your Department

### Add a new station

1. Add the station code and name to StationCodeMap.
2. Add the station to the Stations sheet with desired duty counts.
3. Ensure the template uses the new station code.

### Add a new doctor

1. Add the doctor to the Doctors sheet (with FTE, station, Active, Weekend).
2. Add the required skills in the Skills sheet.
3. The parser will automatically detect the doctor in the template.

### Adjust workload balance

- Increase WorkloadBalance penalty weight to enforce stricter FTE-based distribution.
- If part-time doctors are overloaded, also increase KMBalance and CrossStation weights.

### Enable substitution

- Ensure SUB is defined in DutyTypes.
- Set WeekdayDutyCounts for stations that need coverage.
- Doctors from 65 PP must have the SUB skill (auto-added by the parser).

------

## Troubleshooting

| Issue                             | Likely Cause                                                 | Solution                                                     |
| :-------------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------- |
| Total duties = 0                  | Station names don't match between template and StationCodeMap. | Check station codes in column B of the template. Ensure StationCodeMap has the same codes. |
| Infeasible model                  | Demand > capacity, or too many fixed assignments.            | Reduce demand (e.g., lower WeekdayDutyCounts), add more doctors, or relax hard constraints (e.g., increase MaxConsecutiveWorkDays). |
| Part-time doctor overloaded       | WorkloadBalance weight too low.                              | Increase WorkloadBalance to 100+ in Penalties.               |
| Dark-green cells not recognised   | The UnavailableColor is set incorrectly or the fill is conditional. | Set UnavailableColor to the exact hex value of the static fill (e.g., #008000). Avoid conditional formatting. |
| Session state errors in Streamlit | Keys not initialised.                                        | Use st.session_state.get('key') instead of direct access.    |

------

## License

This project uses the Google OR-Tools open-source library (Apache License 2.0).
The scheduler code is proprietary to UKT IM2.

------

## Support

For technical issues, please contact JF(61369).



# Rules

> The scheduler generates a **monthly duty roster** for the **UKT IM2 department** (Med. Klinik – Innere Medizin II).
> It assigns doctors to **duties (ZD, SD, KM, PR, etc.)** across multiple stations while respecting:
>
> - Individual availability (vacations, days off)
> - Qualifications (skills, seniority)
> - Fair workload distribution (based on FTE)
> - Hard constraints (max consecutive days, max duties per week, etc.)
> - Soft preferences (wishes, station preferences, day-off requests)
>
> The output is a fully filled Excel template that can be directly used as the department's official schedule.
>
> ------
>
> ## 2. Input Files
>
> | File                        | Purpose                                                      |
> | :-------------------------- | :----------------------------------------------------------- |
> | **Rules.xlsx**              | Central configuration file (all sheets described below).     |
> | **Template (Stationsplan)** | Monthly empty schedule template with station headers and doctor rows. |
> | **Wishes.xlsx** (optional)  | Doctor preferences and fixed assignments for a specific month. |
>
> ------
>
> ## 3. Station Demand Rules (What Duties Go Where)
>
> Duties are generated per **station** and per **day** based on the `WeekdayDutyCounts` and `WeekendDutyCounts` columns in the **Stations** sheet.
> `DayDemand` sheet can override specific days.
>
> ### Weekday Demand (Monday – Friday)
>
> | Station                                      | WeekdayDutyCounts | Notes                                          |
> | :------------------------------------------- | :---------------- | :--------------------------------------------- |
> | 65 PP                                        | `ZD=1, SD=1`      | Two shifts: mid-day and late                   |
> | 65 LAF                                       | `ZD=1, SD=1`      | Two shifts                                     |
> | 85 Häm/Onk/Rheu                              | `ZD=1, SD=1`      | Two shifts                                     |
> | 92 KMT                                       | `ZD=1, SD=1`      | Two shifts; plus KM on Mon/Tue (via DayDemand) |
> | Amb 1–4, KMT 1/2, Rheuma 1–3                 | `ZD=1` (or empty) | Usually one shift or covered by substitution   |
> | Other stations (Sonographie, Aufnahme, etc.) | Empty             | Covered by substitution only when needed       |
>
> ### Weekend Demand (Saturday & Sunday)
>
> | Station                   | WeekendDutyCounts |
> | :------------------------ | :---------------- |
> | 65 PP, 65 LAF, 85, 92 KMT | `PR=1`            |
> | All other stations        | Empty             |
>
> ### KM Duties
>
> - Only at **92 KMT**.
> - Only on **Mondays and Tuesdays** (via `DayDemand` sheet: `KM=1` on each Monday and Tuesday).
> - Must be assigned to doctors with the `KM` skill.
> - The same doctor covers both Monday and Tuesday of the same week (hard constraint).
>
> ------
>
> ## 4. Duty Types
>
> | Abbr    | Full Name            | Typical Hours                 | When Used                             |
> | :------ | :------------------- | :---------------------------- | :------------------------------------ |
> | **ZD**  | Zwischendienst       | 9:30 – 18:00 (8.5 hrs)        | Weekdays, mid-day coverage            |
> | **SD**  | Spätdienst           | 13:30 – 22:00 (8.5 hrs)       | Weekdays, evening coverage            |
> | **KM**  | Knochenmarkentnahme  | ~3 hours                      | Monday & Tuesday at 92 KMT            |
> | **PR**  | Präsenz              | Normal working time (8.5 hrs) | Weekends (shown as station name)      |
> | **NAZ** | Nacht-/Notarztdienst | 8.5 hrs                       | Fixed shifts (from wishes)            |
> | **HD**  | Halbtagdienst        | 4.0 hrs                       | Fixed half‑day shifts (from wishes)   |
> | **SUB** | Substitution         | 8.5 hrs                       | When a station needs cover from 65 PP |
>
> ------
>
> ## 5. Substitution Rules
>
> - When a station has demand (e.g., `ZD=1`) but **no doctor from that station** is available (due to vacation, day‑off, etc.), a **SUB** duty is automatically added.
> - **Only doctors from 65 PP** can cover `SUB` duties (hard constraint).
> - Substitution is **not** added if:
>   - The station row has a **`0`** indicator (means “no substitution needed”).
>   - The station is in the `NO_SUBSTITUTE_STATIONS` list (e.g., Sonographie, Aufnahme, Forschung, Balingen, etc.).
> - The output shows the **station code** (e.g., `12` for KMT1) in the substituting doctor's cell.
>
> ------
>
> ## 6. Unavailability & Day‑Off Handling
>
> | Marker                                 | Meaning                                       | Handling                                     |
> | :------------------------------------- | :-------------------------------------------- | :------------------------------------------- |
> | **Dark‑green** fill                    | Hard unavailable (vacation, sick leave, etc.) | Doctor cannot be assigned any duty that day. |
> | **Light‑green** fill                   | “Day‑off due to overload” – soft request      | Avoid assigning if possible (soft penalty).  |
> | **`x`, `U`, `NAZ`** (in `FixedValues`) | Hard unavailable                              | Doctor cannot be assigned any duty that day. |
> | **`0`** on station row                 | No substitution needed                        | Substitution skipped for that station/day.   |
> | **`F?`**                               | Unknown                                       | Ignored (treated as blank).                  |
>
> ------
>
> ## 7. Weekend Assignment Rules
>
> - **Only doctors with `Weekend = Yes`** in the `Doctors` sheet can work weekends (hard constraint).
> - **Only 100% FTE doctors** can work weekends (`WeekendOnlyFullTime = Yes`).
> - **Maximum weekend duties per doctor** = 3 (from `GeneralRules`, `MaxWeekendPerDoctor`).
> - Weekend output shows the **full station name** (e.g., `65 PP`), not the duty abbreviation.
>
> ------
>
> ## 8. Workload & FTE (Hours‑Based Balancing)
>
> - **Workload balance** is based on **total hours** (duties + normal working days), not just duty count.
> - **Normal working day** = 8.5 hours (08:00‑16:30).
> - **Target hours** for each doctor = `(FTE/100) × total_available_month_hours` (where total available = 22 weekdays × 8.5h = 187h for a full month).
> - **Part‑time doctors** (FTE < 100%) are expected to work proportionally fewer hours.
> - The `WorkloadBalance` penalty weight (e.g., 100) strongly enforces this target.
>
> ------
>
> ## 9. Hard Constraints (Always Enforced)
>
> | Constraint                                        | Value | Notes                                                        |
> | :------------------------------------------------ | :---- | :----------------------------------------------------------- |
> | Each duty assigned to exactly one doctor          | –     | –                                                            |
> | At most one duty per doctor per day               | –     | No double‑booking                                            |
> | Station match (doctor must belong to the station) | Yes   | Exception: `SUB` duties (from 65 PP) and `PR` on weekends (any doctor) |
> | Skills required                                   | Yes   | Doctor must have the duty abbreviation in their `Skills` sheet |
> | Unavailability                                    | Yes   | No duties on dark‑green or `x` / `U` days                    |
> | Senior requirement                                | Yes   | Duty or station with `RequiresSenior = Yes`only for doctors with `Senior` skill |
> | Max consecutive work days                         | 6     | From `GeneralRules`                                          |
> | Max duties per week                               | 6     | From `GeneralRules`                                          |
> | Max weekend duties per doctor                     | 3     | From `GeneralRules`                                          |
> | Weekend only for 100% FTE                         | Yes   | `WeekendOnlyFullTime`                                        |
> | Weekend availability                              | Yes   | Only doctors with `Weekend = Yes`                            |
>
> ------
>
> ## 10. Soft Constraints (Penalties)
>
> | Penalty           | Weight | Purpose                                       |
> | :---------------- | :----- | :-------------------------------------------- |
> | `WorkloadBalance` | 100    | Balance total hours by FTE (strong)           |
> | `Preference`      | 10     | Satisfy doctor wishes (from Wishes file)      |
> | `WeekendBalance`  | 15     | Distribute weekend duties evenly              |
> | `KMBalance`       | 30     | Distribute KM duties evenly                   |
> | `CrossStation`    | 30     | Prefer assigning doctors to their own station |
> | `DayOffPenalty`   | 50     | Avoid light‑green (day‑off request) days      |
>
> ------
>
> ## 11. Fixed Assignments (Wishes)
>
> - From the optional **Wishes.xlsx** file.
> - **Duty abbreviations** (e.g., `NAZ`, `HD`) → create a **fixed assignment**at the doctor's own station (hard constraint).
> - **Station codes** (e.g., `92`, `85`, `65P`) → create a **preference**(priority 50) on weekdays, or a **fixed assignment** on weekends (if station is one of the four main stations).
> - **Fixed assignments** are hard constraints – the solver must respect them.
>
> ------
>
> ## 12. Output Format
>
> - **Weekdays:**
>   - Same‑station duty → show duty abbreviation (`ZD`, `SD`, `KM`, etc.)
>   - Cross‑station duty (including `SUB`) → show **station code** (e.g., `12`, `92`, `65p`)
> - **Weekends:**
>   - Always show **full station name** (e.g., `65 PP`, `92 KMT`)
>
> ------
>
> ## 13. Additional Output Sheets
>
> | Sheet               | Content                                                      |
> | :------------------ | :----------------------------------------------------------- |
> | `Statistics`        | Duties per doctor (Total, SD, ZD, KM, Weekend, Expected, Diff) |
> | `ConflictReport`    | Unsatisfied preferences + workload imbalances                |
> | `Explanation`       | Each assignment with reasoning                               |
> | `DayOffSuggestions` | Recommended days off for part‑time doctors (excess hours > target) |
> | `WorkingHours`      | Updated cumulative hours (also written to `Rules.xlsx`)      |
>
> ------
>
> ## 14. Summary of Key Configuration Values
>
> | Setting                              | Value                            | Location           |
> | :----------------------------------- | :------------------------------- | :----------------- |
> | `MaxConsecutiveWorkDays`             | 6                                | `GeneralRules`     |
> | `MaxDutiesPerWeek`                   | 6                                | `GeneralRules`     |
> | `MaxWeekendPerDoctor`                | 3                                | `GeneralRules`     |
> | `WeekdayDutyCounts`for main stations | `ZD=1, SD=1`                     | `Stations` sheet   |
> | `WeekendDutyCounts`for main stations | `PR=1`                           | `Stations` sheet   |
> | `DayDemand`                          | KM on Monday & Tuesday at 92 KMT | `DayDemand` sheet  |
> | `WorkloadBalance`weight              | 100                              | `Penalties` sheet  |
> | `CrossStation` weight                | 30                               | `Penalties` sheet  |
> | `DayOffPenalty`weight                | 50                               | `Penalties` sheet  |
> | `WeekendOnlyFullTime`                | Yes                              | `Constraints`sheet |
> | `WeekendAvailability`                | Yes                              | `Constraints`sheet |
> | `MaxOneWeekendPerDoctor`             | Yes                              | `Constraints`sheet |
> | `SeniorRequired`                     | Yes                              | `Constraints`sheet |
> | `MaxConsecutive`                     | Yes                              | `Constraints`sheet |
> | `MaxPerWeek`                         | Yes                              | `Constraints`sheet |
>
> ------
>
> ## 15. Notes on Customisation
>
> - **To add a new station**: update `StationCodeMap`, add station to `Stations` with demand counts.
> - **To add a new duty type**: add to `DutyTypes` sheet, then add to `Skills` for relevant doctors.
> - **To change substitution rules**: edit `NO_SUBSTITUTE_STATIONS` in `demand_builder.py`.
> - **To adjust penalty weights**: modify the `Penalties` sheet – higher weights make the constraint stricter.
>
> ------
>
> ## 16. Support
>
> For technical issues, contact JF, 61369).
> 