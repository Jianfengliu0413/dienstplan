# rotation_planner.py
"""
Standalone N-month rotation planner — stability-first.

DESIGN PHILOSOPHY
-----------------
The planner treats "Konstanz pro Einsatzort" as the PRIMARY goal:
  - Doctors stay at their home station by default.
  - Changing station is allowed but penalized.
  - Any change must be justified by a real need:
      * The station they'd stay at is overstaffed.
      * They cannot work at their home station in some months
        (e.g. their AllowedStations list excludes it).
      * A RotationRules entry forces them somewhere.
      * A required headcount forces redistribution.

WHAT IT DOES
------------
  1. Assigns each doctor to a station per month, keeping them stable
     whenever possible.
  2. Distributes vacation days across the N months.
  3. Optionally writes one monthly template file per month.

WHAT IT DOES NOT DO
-------------------
  - It does NOT assign daily duties (SD, ZD, KM, ...).
  - It does NOT touch the Rules_updated.xlsx used by your app.
    All planner output goes to RotationPlan.xlsx.

CONFIGURATION (optional sheets in Rules.xlsx)
---------------------------------------------
  RotationConfig:
      | Key                    | Value                          |
      | PlanStartMonth         | 2026-10                        |
      | PlanMonths             | 12                             |
      | VacationDaysPerDoctor  | 30                             |
      | GenerateTemplateFiles  | Yes / No                       |
      | TemplatePath           | /path/to/templates             |
      | TemplatePattern        | Stationsplan {month_name} {yy}.xlsx |

  AllowedStations (optional):
      | Doctor | AllowedStations               |
      | Jann   | 65 PP;65 LAF;85 Häm/Onk/Rheu  |
    If a doctor is not listed, ALL stations are allowed for them.

  RotationRules (optional, HARD constraint):
      | Doctor | Month   | Station  |
      | Jann   | 2026-11 | 65 LAF   |
      | Jenter | 2027-02 | 65 PP    |
    These entries are enforced exactly. The planner fills the rest.

  ResearchFree (optional):
      | Doctor | Month   | Capacity |
      | Jann   | 2026-12 | 50       |

  VacationRules (optional):
      | Doctor | PreferredMonths |
      | Jann   | 2026-11;2027-02 |

USAGE
-----
  CLI:
      python rotation_planner.py --rules Rules.xlsx --out RotationPlan.xlsx
      python rotation_planner.py --rules Rules.xlsx --start 2026-10 --months 12
      python rotation_planner.py --rules Rules.xlsx --generate-templates

  Python:
      from rotation_planner import plan_rotation
      plan_rotation("Rules.xlsx", "RotationPlan.xlsx", start_month="2026-10")
"""

from __future__ import annotations

import argparse
import os
import re
from calendar import monthrange
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
from ortools.sat.python import cp_model


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
ROTATION_SHEET = "RotationPlan"
VACATION_SHEET = "VacationPlan"
RESEARCH_FREE_SHEET = "ResearchFreePlan"

DEFAULT_CONFIG = {
    "PlanStartMonth": None,
    "PlanMonths": 6,
    "VacationDaysPerDoctor": 30,
    "GenerateTemplateFiles": "No",
    "TemplatePath": "",
    "TemplatePattern": "Stationsplan {month_name} {yy}.xlsx",
}

# Objective weights (soft). Tuned so that stability dominates.
W_HOME_REWARD = 20       # reward for being at home station
W_STAY_REWARD = 30       # reward for staying at same station as last month
W_CHANGE_PENALTY = 40    # penalty for changing station (per change)
W_FTE_DEVIATION = 2      # penalty for total month-assignments deviating from target

GERMAN_MONTHS = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April",
    5: "Mai", 6: "Juni", 7: "Juli", 8: "August",
    9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}


# ----------------------------------------------------------------------
# Sheet loaders
# ----------------------------------------------------------------------
def _read_sheet(path: str, sheet: str) -> Optional[pd.DataFrame]:
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except Exception:
        return None


def _load_config(rules_path: str) -> Dict[str, object]:
    cfg = dict(DEFAULT_CONFIG)
    df = _read_sheet(rules_path, "RotationConfig")
    if df is None or df.empty:
        return cfg
    df = df.dropna(subset=["Key"])
    for _, row in df.iterrows():
        key = str(row["Key"]).strip()
        val = row["Value"]
        if key in cfg and not pd.isna(val):
            cfg[key] = val
    return cfg


def _load_doctors(rules_path: str) -> pd.DataFrame:
    df = _read_sheet(rules_path, "Doctors")
    if df is None or df.empty:
        raise ValueError("Rules file has no Doctors sheet.")
    df = df.copy()
    df["Name"] = df["Name"].astype(str).str.strip()
    df = df[df["Name"] != ""]
    if "FTE (%)" not in df.columns and "FTE" in df.columns:
        df["FTE (%)"] = df["FTE"]
    df["FTE (%)"] = pd.to_numeric(df["FTE (%)"], errors="coerce").fillna(100)
    df["Station"] = df["Station"].astype(str).str.strip()
    if "Active" not in df.columns:
        df["Active"] = "Yes"
    return df


def _load_stations(rules_path: str) -> pd.DataFrame:
    df = _read_sheet(rules_path, "Stations")
    if df is None or df.empty:
        raise ValueError("Rules file has no Stations sheet.")
    df = df.copy()
    df["Station"] = df["Station"].astype(str).str.strip()
    return df


def _load_allowed_stations(rules_path: str) -> pd.DataFrame:
    df = _read_sheet(rules_path, "AllowedStations")
    if df is None:
        return pd.DataFrame(columns=["Doctor", "AllowedStations"])
    df = df.copy()
    df["Doctor"] = df["Doctor"].astype(str).str.strip()
    df["AllowedStations"] = df.get("AllowedStations", "").astype(str)
    return df


def _load_rotation_rules(rules_path: str) -> pd.DataFrame:
    """
    Optional hard-constraint sheet:
        | Doctor | Month   | Station  |
        | Jann   | 2026-11 | 65 LAF   |
    """
    df = _read_sheet(rules_path, "RotationRules")
    if df is None:
        return pd.DataFrame(columns=["Doctor", "Month", "Station"])
    df = df.copy()
    df["Doctor"] = df["Doctor"].astype(str).str.strip()
    df["Month"] = df["Month"].astype(str).str.strip()
    df["Station"] = df["Station"].astype(str).str.strip()
    df = df[(df["Doctor"] != "") & (df["Month"] != "") & (df["Station"] != "")]
    return df


def _load_research_free(rules_path: str) -> pd.DataFrame:
    df = _read_sheet(rules_path, "ResearchFree")
    if df is None:
        return pd.DataFrame(columns=["Doctor", "Month", "Capacity"])
    df = df.copy()
    df["Doctor"] = df["Doctor"].astype(str).str.strip()
    df["Month"] = df["Month"].astype(str).str.strip()
    df["Capacity"] = pd.to_numeric(df["Capacity"], errors="coerce").fillna(0)
    return df


def _load_vacation_rules(rules_path: str) -> pd.DataFrame:
    df = _read_sheet(rules_path, "VacationRules")
    if df is None:
        return pd.DataFrame(columns=["Doctor", "PreferredMonths"])
    df = df.copy()
    df["Doctor"] = df["Doctor"].astype(str).str.strip()
    df["PreferredMonths"] = df.get("PreferredMonths", "").astype(str)
    return df


# ----------------------------------------------------------------------
# Month utilities
# ----------------------------------------------------------------------
def _month_range(start: datetime, n: int) -> List[str]:
    out = []
    y, m = start.year, start.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _month_days(month_str: str) -> int:
    y, m = map(int, month_str.split("-"))
    return monthrange(y, m)[1]


def _month_label(month_str: str) -> Tuple[str, str]:
    y, m = month_str.split("-")
    return GERMAN_MONTHS[int(m)], y[2:]


# ----------------------------------------------------------------------
# Rotation solver (CP-SAT) — stability-first
# ----------------------------------------------------------------------
def _build_allowed_station_map(
    doctors: List[str],
    stations: List[str],
    allowed_df: pd.DataFrame,
) -> Tuple[Dict[str, List[str]], List[str]]:
    """
    Return:
        allowed_map: doctor -> list of allowed stations
        warnings:    list of non-fatal warnings
    """
    warnings: List[str] = []
    allowed_map: Dict[str, List[str]] = {}

    allowed_lookup: Dict[str, List[str]] = {}
    for _, row in allowed_df.iterrows():
        doc = str(row["Doctor"]).strip()
        raw = str(row["AllowedStations"]).strip()
        if not doc or raw.lower() == "nan" or not raw:
            continue
        allowed_lookup[doc] = [s.strip() for s in raw.split(";") if s.strip()]

    for d in doctors:
        if d in allowed_lookup:
            allowed = [s for s in allowed_lookup[d] if s in stations]
            if not allowed:
                warnings.append(
                    f"Doctor '{d}' has AllowedStations but none of the listed "
                    f"stations exist in Stations sheet. Defaulting to all stations."
                )
                allowed = list(stations)
        else:
            allowed = list(stations)
        allowed_map[d] = allowed

    return allowed_map, warnings


def _solve_rotation(
    doctors: List[str],
    stations: List[str],
    months: List[str],
    doctors_df: pd.DataFrame,
    stations_df: pd.DataFrame,
    allowed_map: Dict[str, List[str]],
    rotation_rules_df: pd.DataFrame,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Decide x[doctor, station, month] ∈ {0,1}.

    Hard constraints:
      - Each doctor: exactly one station per month (within allowed_map).
      - Each station: exactly RequiredDoctors doctors per month.
      - RotationRules entries: enforced exactly.

    Soft objective (stability-first):
      - Strong reward for staying at home station.
      - Strong reward for staying at the same station as the previous month.
      - Penalty for changing station.
    """
    model = cp_model.CpModel()

    # ---- Vars ----
    x: Dict[Tuple[str, str, str], cp_model.IntVar] = {}
    for d in doctors:
        for s in allowed_map[d]:
            for m in months:
                x[(d, s, m)] = model.NewBoolVar(f"x_{d}_{s}_{m}")

    # ---- 1. Each doctor one station per month ----
    for d in doctors:
        for m in months:
            model.Add(sum(x[(d, s, m)] for s in allowed_map[d]) == 1)

    # ---- 2. Station headcount per month ----
    station_required: Dict[str, int] = {}
    has_required = "RequiredDoctors" in stations_df.columns
    for _, row in stations_df.iterrows():
        s = str(row["Station"]).strip()
        if has_required:
            try:
                station_required[s] = int(row["RequiredDoctors"])
            except Exception:
                station_required[s] = 0
        else:
            station_required[s] = int((doctors_df["Station"] == s).sum())

    for s in stations:
        req = station_required.get(s, 0)
        for m in months:
            if req == 0:
                for d in doctors:
                    if s in allowed_map[d]:
                        model.Add(x[(d, s, m)] == 0)
            else:
                terms = [x[(d, s, m)] for d in doctors if s in allowed_map[d]]
                if terms:
                    model.Add(sum(terms) == req)
                elif req > 0:
                    model.Add(0 == 1)  # infeasible; will be diagnosed

    # ---- 3. RotationRules: HARD constraints ----
    for _, row in rotation_rules_df.iterrows():
        d = row["Doctor"]
        m = row["Month"]
        s = row["Station"]
        if d not in doctors or m not in months or s not in stations:
            continue
        if s not in allowed_map[d]:
            raise ValueError(
                f"RotationRules conflict: doctor '{d}' is forced to station "
                f"'{s}' in month '{m}', but this station is not in their "
                f"AllowedStations list {allowed_map[d]}."
            )
        # Force this doctor into that station that month
        model.Add(x[(d, s, m)] == 1)

    # ---- 4. Soft objective: stability-first ----
    objective = []

    home = {row["Name"]: str(row.get("Station", "")).strip()
            for _, row in doctors_df.iterrows()}

    # 4a. Home-station reward (strong)
    for d in doctors:
        home_s = home.get(d, "")
        if home_s and home_s in allowed_map[d]:
            for m in months:
                objective.append(-W_HOME_REWARD * x[(d, home_s, m)])

    # 4b. Stay reward: same station as previous month
    for d in doctors:
        for s in allowed_map[d]:
            for i in range(1, len(months)):
                m0, m1 = months[i - 1], months[i]
                stay = model.NewBoolVar(f"stay_{d}_{s}_{i}")
                model.Add(stay <= x[(d, s, m0)])
                model.Add(stay <= x[(d, s, m1)])
                model.Add(stay >= x[(d, s, m0)] + x[(d, s, m1)] - 1)
                objective.append(-W_STAY_REWARD * stay)

    # 4c. Change penalty (redundant with 4b but makes the intent explicit)
    for d in doctors:
        for i in range(1, len(months)):
            m0, m1 = months[i - 1], months[i]
            # changed = 1 - sum_s (same_s)
            same_vars = []
            for s in allowed_map[d]:
                same = model.NewBoolVar(f"same_{d}_{s}_{i}")
                model.Add(same <= x[(d, s, m0)])
                model.Add(same <= x[(d, s, m1)])
                model.Add(same >= x[(d, s, m0)] + x[(d, s, m1)] - 1)
                same_vars.append(same)
            changed = model.NewBoolVar(f"changed_{d}_{i}")
            model.Add(changed + sum(same_vars) == 1)
            objective.append(W_CHANGE_PENALTY * changed)

    model.Minimize(sum(objective))

    # ---- Solve ----
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 120.0
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        diag = [
            "Rotation planner is INFEASIBLE.",
            "",
            "Common causes:",
            "  - RequiredDoctors sums do not match the number of doctors.",
            "    Each station must be staffed exactly as RequiredDoctors says.",
            "  - AllowedStations (if provided) restrict doctors too much.",
            "  - RotationRules (if provided) force doctors into incompatible months.",
            "",
            "Doctors and their allowed stations:",
        ]
        for d in doctors[:20]:
            diag.append(f"  {d}: {allowed_map[d]}")
        if len(doctors) > 20:
            diag.append(f"  ... and {len(doctors) - 20} more.")
        raise RuntimeError("\n".join(diag))

    # ---- Extract ----
    rows = []
    for d in doctors:
        row = {"Doctor": d}
        for m in months:
            for s in allowed_map[d]:
                if solver.Value(x[(d, s, m)]) == 1:
                    row[m] = s
                    break
            else:
                row[m] = ""
        rows.append(row)

    result = pd.DataFrame(rows, columns=["Doctor"] + months)

    if verbose:
        n_changes_total = 0
        for _, row in result.iterrows():
            vals = [row[m] for m in months]
            changes = sum(1 for i in range(1, len(vals)) if vals[i] != vals[i - 1] and vals[i] and vals[i - 1])
            n_changes_total += changes
        print(
            f"[rotation] solved {len(doctors)} doctors × {len(months)} months; "
            f"total station changes across all doctors: {n_changes_total}"
        )

    return result


# ----------------------------------------------------------------------
# Vacation assignment (CP-SAT)
# ----------------------------------------------------------------------
def _solve_vacation(
    doctors: List[str],
    months: List[str],
    total_days: int,
    preferred: Dict[str, List[str]],
    verbose: bool = True,
) -> pd.DataFrame:
    model = cp_model.CpModel()
    max_per_month = {m: int(_month_days(m) * 0.4) for m in months}

    v: Dict[Tuple[str, str], cp_model.IntVar] = {}
    for d in doctors:
        for m in months:
            v[(d, m)] = model.NewIntVar(0, max_per_month[m], f"v_{d}_{m}")

    for d in doctors:
        model.Add(sum(v[(d, m)] for m in months) == total_days)

    objective = []
    for d in doctors:
        for m in preferred.get(d, []):
            if m in months:
                objective.append(-v[(d, m)])

    avg = total_days / len(months)
    avg_int = int(round(avg))
    for d in doctors:
        for m in months:
            pos = model.NewIntVar(0, max_per_month[m], f"pos_{d}_{m}")
            neg = model.NewIntVar(0, max_per_month[m], f"neg_{d}_{m}")
            model.Add(v[(d, m)] - avg_int == pos - neg)
            objective.append(2 * (pos + neg))

    model.Minimize(sum(objective))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"Vacation planner infeasible. Status: {status}")

    rows = []
    for d in doctors:
        row = {"Doctor": d}
        for m in months:
            row[m] = solver.Value(v[(d, m)])
        rows.append(row)

    if verbose:
        print(f"[vacation] distributed {total_days} days per doctor")

    return pd.DataFrame(rows, columns=["Doctor"] + months)


# ----------------------------------------------------------------------
# Template generation
# ----------------------------------------------------------------------
def _pattern_to_regex(pattern: str) -> str:
    regex = re.escape(pattern)
    regex = regex.replace(re.escape("{month_name}"), r"(?P<month_name>[A-Za-zÄÖÜäöüß]+)")
    regex = regex.replace(re.escape("{yy}"), r"(?P<yy>\d{2})")
    regex = regex.replace(re.escape("{yyyy}"), r"(?P<yyyy>\d{4})")
    regex = regex.replace(re.escape("{mm}"), r"(?P<mm>\d{2})")
    return regex


def _find_template_for_month(
    template_dir: str,
    pattern: str,
    month_str: str,
) -> Optional[str]:
    if not template_dir or not os.path.isdir(template_dir):
        return None
    month_name, yy = _month_label(month_str)
    regex = _pattern_to_regex(pattern)
    compiled = re.compile(regex, re.IGNORECASE)
    for fname in os.listdir(template_dir):
        m = compiled.match(fname)
        if not m:
            continue
        try:
            if m.groupdict().get("month_name", "").lower() == month_name.lower() \
               and m.groupdict().get("yy", "") == yy:
                return os.path.join(template_dir, fname)
        except IndexError:
            continue
    return None


def _rearrange_template(
    template_path: str,
    rotation_df: pd.DataFrame,
    month_str: str,
    doctors_df: pd.DataFrame,
    stations_df: pd.DataFrame,
    output_path: str,
) -> Optional[str]:
    import openpyxl

    if rotation_df is None or rotation_df.empty:
        return None
    if month_str not in rotation_df.columns:
        print(f"[template] no rotation info for {month_str}, skipping")
        return None

    desired: Dict[str, List[str]] = {s: [] for s in stations_df["Station"].tolist()}
    for _, row in rotation_df.iterrows():
        doc = str(row["Doctor"]).strip()
        st = str(row.get(month_str, "")).strip()
        if doc and st and st in desired:
            desired[st].append(doc)

    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    doctor_name_col = 1
    doctor_rows: Dict[str, Tuple[int, Dict[int, object]]] = {}
    for r in range(2, ws.max_row + 1):
        name_cell = ws.cell(row=r, column=doctor_name_col).value
        if not name_cell or not isinstance(name_cell, str):
            continue
        name = name_cell.strip().rstrip("*").strip()
        if name in doctors_df["Name"].tolist():
            values = {c: ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)}
            doctor_rows[name] = (r, values)

    station_names = set(stations_df["Station"].tolist())
    station_positions: Dict[str, int] = {}
    for r in range(2, ws.max_row + 1):
        name_cell = ws.cell(row=r, column=doctor_name_col).value
        if not name_cell or not isinstance(name_cell, str):
            continue
        name = name_cell.strip()
        if name in station_names:
            station_positions[name] = r

    ordered_stations = sorted(station_positions.items(), key=lambda x: x[1])

    for idx, (station, row) in enumerate(ordered_stations):
        next_station_row = (
            ordered_stations[idx + 1][1] if idx + 1 < len(ordered_stations) else ws.max_row + 1
        )
        block_rows = list(range(row + 1, next_station_row))
        doctor_block_rows = [
            r for r in block_rows
            if ws.cell(row=r, column=doctor_name_col).value
            and isinstance(ws.cell(row=r, column=doctor_name_col).value, str)
            and ws.cell(row=r, column=doctor_name_col).value.strip().rstrip("*").strip()
            in doctors_df["Name"].tolist()
        ]

        assigned = desired.get(station, [])
        for i, r in enumerate(doctor_block_rows):
            new_name = assigned[i] if i < len(assigned) else ""
            if new_name:
                ws.cell(row=r, column=doctor_name_col).value = new_name
            else:
                ws.cell(row=r, column=doctor_name_col).value = None

    wb.save(output_path)
    return output_path


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
def plan_rotation(
    rules_path: str = "Rules.xlsx",
    output_path: str = "RotationPlan.xlsx",
    start_month: Optional[str] = None,
    n_months: Optional[int] = None,
    generate_templates: Optional[bool] = None,
    verbose: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Run the full planner.

    Returns a dict with keys: 'rotation', 'vacation', 'research_free'.
    """
    cfg = _load_config(rules_path)

    if start_month is None:
        start_month = cfg.get("PlanStartMonth")
    if n_months is None:
        n_months = int(cfg.get("PlanMonths", 6))
    if generate_templates is None:
        generate_templates = str(cfg.get("GenerateTemplateFiles", "No")).lower() == "yes"

    if start_month is None:
        today = datetime.today()
        y, m = today.year, today.month + 1
        if m > 12:
            m = 1
            y += 1
        start_month = f"{y:04d}-{m:02d}"

    months = _month_range(datetime.strptime(start_month + "-01", "%Y-%m-%d"), n_months)

    if verbose:
        print(f"[planner] planning {n_months} months: {months[0]} → {months[-1]}")
        print(f"[planner] stability-first: minimize station changes")

    doctors_df = _load_doctors(rules_path)
    stations_df = _load_stations(rules_path)
    allowed_df = _load_allowed_stations(rules_path)
    rotation_rules_df = _load_rotation_rules(rules_path)
    research_free_df = _load_research_free(rules_path)
    vacation_rules_df = _load_vacation_rules(rules_path)

    doctors = [str(d).strip() for d in doctors_df["Name"].tolist()
               if str(d).strip() and str(d).strip() != "nan"]
    stations = [str(s).strip() for s in stations_df["Station"].tolist()
                if str(s).strip() and str(s).strip() != "nan"]

    allowed_map, warnings = _build_allowed_station_map(doctors, stations, allowed_df)
    for w in warnings:
        print(f"[warning] {w}")

    # ----- 1. Rotation -----
    rotation_df = _solve_rotation(
        doctors, stations, months, doctors_df, stations_df,
        allowed_map, rotation_rules_df, verbose,
    )

    # ----- 2. Vacation -----
    preferred: Dict[str, List[str]] = {}
    for _, row in vacation_rules_df.iterrows():
        doc = str(row["Doctor"]).strip()
        months_str = str(row.get("PreferredMonths", "")).strip()
        if doc and months_str and months_str.lower() != "nan":
            preferred[doc] = [m.strip() for m in months_str.split(";") if m.strip()]

    total_vac_days = int(cfg.get("VacationDaysPerDoctor", 30))
    vacation_df = _solve_vacation(doctors, months, total_vac_days, preferred, verbose)

    # ----- 3. Research-free -----
    research_free_plan_rows = []
    for _, row in research_free_df.iterrows():
        doc = str(row["Doctor"]).strip()
        month = str(row["Month"]).strip()
        capacity = float(row["Capacity"])
        if doc in doctors and month in months:
            research_free_plan_rows.append({
                "Doctor": doc,
                "Month": month,
                "Capacity": capacity,
            })
    research_free_plan_df = pd.DataFrame(
        research_free_plan_rows,
        columns=["Doctor", "Month", "Capacity"],
    )

    # ----- 4. Write output -----
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        rotation_df.to_excel(writer, sheet_name=ROTATION_SHEET, index=False)
        vacation_df.to_excel(writer, sheet_name=VACATION_SHEET, index=False)
        research_free_plan_df.to_excel(writer, sheet_name=RESEARCH_FREE_SHEET, index=False)

    if verbose:
        print(f"[planner] wrote {output_path}")
        print(rotation_df.to_string(index=False))

    # ----- 5. Templates -----
    if generate_templates:
        template_dir = str(cfg.get("TemplatePath", "")).strip()
        template_pattern = str(cfg.get("TemplatePattern", "")).strip()
        for month_str in months:
            template_path = _find_template_for_month(template_dir, template_pattern, month_str)
            if template_path is None:
                print(f"[template] no template found for {month_str}")
                continue
            month_name, yy = _month_label(month_str)
            out_name = f"Stationsplan_{month_name}_{yy}_generated.xlsx"
            out_path = os.path.join(template_dir, out_name)
            _rearrange_template(
                template_path, rotation_df, month_str,
                doctors_df, stations_df, out_path,
            )
            if verbose:
                print(f"[template] generated {out_path}")

    return {
        "rotation": rotation_df,
        "vacation": vacation_df,
        "research_free": research_free_plan_df,
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone stability-first rotation planner")
    parser.add_argument("--rules", default="Rules.xlsx")
    parser.add_argument("--out", default="RotationPlan.xlsx")
    parser.add_argument("--start", default=None, help="Start month YYYY-MM")
    parser.add_argument("--months", type=int, default=None)
    parser.add_argument("--generate-templates", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    plan_rotation(
        rules_path=args.rules,
        output_path=args.out,
        start_month=args.start,
        n_months=args.months,
        generate_templates=args.generate_templates if args.generate_templates else None,
        verbose=not args.quiet,
    )