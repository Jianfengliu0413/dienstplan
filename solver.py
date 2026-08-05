# solver.py
from ortools.sat.python import cp_model
from models import ScheduleModel
from demand_builder import build_demand
from constraints import add_hard_constraints
from objective import add_soft_constraints
from config_loader import load_working_hours 
import pandas as pd
from collections import defaultdict
from typing import Tuple, List, Dict

from demand_builder import GLOBAL_STATION, MAIN_STATIONS 


def solve_schedule(
    schedule: ScheduleModel,
    config: dict,
    config_path: str, 
    repair_mode: bool = True
) -> Tuple[Dict[int, str], cp_model.CpSolver, List[Tuple[int, str, str]], List[str]]:
    demand = build_demand(schedule, config)
    duties = []  # list of (day_idx, station, duty_abbr)
    duty_hours = []   # list of hours per duty
    for (day_idx, station), counts in demand.items():
        for abbr, cnt in counts.items():
            hours = schedule.duty_types[abbr].hours
            for _ in range(cnt):
                duties.append((day_idx, station, abbr))
                duty_hours.append(hours)
    doctors = list(schedule.doctors.keys())
    num_duties = len(duties)
    num_doctors = len(doctors)

    # Load initial working hours
    # try:
    #     initial_hours = load_working_hours(config_path, doctors)
    # except Exception as e:
    #     print(f"failed to get the initial_hours from 'Rules file: {e}'")
    initial_hours = {doc: 0.0 for doc in doctors}
    # Create CP model
    model_cp = cp_model.CpModel()
    x = {}
    for i in range(num_duties):
        for j in range(num_doctors):
            x[(i, j)] = model_cp.NewBoolVar(f'x_{i}_{j}')
 
    
    # --- ENFORCE FIXED ASSIGNMENTS (hard constraints) ---
    duty_map = {}
    for i, (day_idx, station, abbr) in enumerate(duties):
        duty_map[(day_idx, station, abbr)] = i

    for doc_name, day_idx, station, duty_abbr in schedule.fixed_assignments:
        if (day_idx, station, duty_abbr) in duty_map:
            duty_i = duty_map[(day_idx, station, duty_abbr)]
            doctor_j = doctors.index(doc_name)
            model_cp.Add(x[(duty_i, doctor_j)] == 1)
            print(f"[FIXED]: {doc_name} must do {duty_abbr} at {station} on day {day_idx}")
        else:
            print(f"[Warning]: Fixed assignment for {doc_name} on {day_idx} {station} {duty_abbr} not found in duties.")

    # Build hard constraints (now including the fixed assignments)
    try:
        add_hard_constraints(model_cp, schedule, config, x, duties, doctors, demand)
    except ValueError as e:
        if repair_mode:
            print(f"Hard constraint error: {e}. Attempting repair by relaxing constraints...")
            return repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours)# repair_schedule(schedule, config, duties, doctors, demand)
        else:
            raise
    
    # Build soft constraints (objective)
    penalties = add_soft_constraints(model_cp, schedule, config, x, duties, doctors, demand, duty_hours, initial_hours)
    model_cp.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    status = solver.Solve(model_cp)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if repair_mode:
            print("No feasible solution found. Running repair...")
            return repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours) #repair_schedule(schedule, config, duties, doctors, demand)
        else:
            raise RuntimeError("No feasible solution.")

    assignment = {}
    for i in range(num_duties):
        for j in range(num_doctors):
            if solver.Value(x[(i, j)]) == 1:
                assignment[i] = doctors[j]
                break

    return assignment, solver, duties, doctors, duty_hours, initial_hours

def repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours):
    """
    Repair: relax skill constraints only. Keep station match, vacation, and weekend rules.
    If still infeasible, raise error (user must reduce demand).
    """

    general_df = config.get('GeneralRules', pd.DataFrame())
    if not general_df.empty and 'RuleName' in general_df.columns:
        general = general_df.set_index('RuleName')['Value'].to_dict()
    else:
        general = {}

    constraints_cfg = config.get('Constraints', pd.DataFrame())
    if not constraints_cfg.empty and 'Constraint' in constraints_cfg.columns:
        constraints_cfg = constraints_cfg.set_index('Constraint')['Enabled'].to_dict()
    else:
        constraints_cfg = {}

    print("Repair: relaxing skill constraints (keeping station match, vacation, and weekend rules)...")
    model_cp = cp_model.CpModel()
    num_duties = len(duties)
    num_doctors = len(doctors)
    x = {}
    for i in range(num_duties):
        for j in range(num_doctors):
            x[(i, j)] = model_cp.NewBoolVar(f'x_{i}_{j}')

    # --- ENFORCE FIXED ASSIGNMENTS (hard constraints) ---
    duty_map = {}
    for i, (day_idx, station, abbr) in enumerate(duties):
        duty_map[(day_idx, station, abbr)] = i

    for doc_name, day_idx, station, duty_abbr in schedule.fixed_assignments:
        if (day_idx, station, duty_abbr) in duty_map:
            duty_i = duty_map[(day_idx, station, duty_abbr)]
            doctor_j = doctors.index(doc_name)
            model_cp.Add(x[(duty_i, doctor_j)] == 1)
            print(f"REPAIR FIXED: {doc_name} must do {duty_abbr} at {station} on day {day_idx}")
        else:
            print(f"Warning: Fixed assignment for {doc_name} on {day_idx} {station} {duty_abbr} not found in duties.")

    # Essential constraints
    for i in range(num_duties):
        model_cp.Add(sum(x[(i, j)] for j in range(num_doctors)) == 1)
    duties_by_day = defaultdict(list)
    for i, (day_idx, _, _) in enumerate(duties):
        duties_by_day[day_idx].append(i)
    for day_idx, duty_list in duties_by_day.items():
        for j in range(num_doctors):
            model_cp.Add(sum(x[(i, j)] for i in duty_list) <= 1)


    # 3. Station match
    for i, (day_idx, station, abbr) in enumerate(duties):
        if station == GLOBAL_STATION:
            if abbr == 'SD':
                # Prefer main‑station doctors, but fallback to all if none available
                main_allowed = [j for j, doc_name in enumerate(doctors)
                                if schedule.doctors[doc_name].station in MAIN_STATIONS]
                if main_allowed:
                    allowed = main_allowed
                else:
                    allowed = list(range(num_doctors))
                    print(f"Global SD on day {day_idx}: no main‑station doctors – allowing all")
            else:
                allowed = list(range(num_doctors))
        else:
            if abbr == 'SUB':
                allowed = [j for j, doc_name in enumerate(doctors) 
                        if schedule.doctors[doc_name].station == '65 PP']
            elif schedule.days[day_idx].is_weekend and abbr == 'PR':
                allowed = list(range(num_doctors))
            else:
                if abbr == 'SD':
                    # Station‑specific SD: only doctors from the same station
                    allowed = [j for j, doc_name in enumerate(doctors)
                            if schedule.doctors[doc_name].station == station]
                else:
                    # ZD and other weekdays: prefer same station, else any doctor
                    home_doctors = [j for j, doc_name in enumerate(doctors)
                                    if schedule.doctors[doc_name].station == station]
                    # Filter out unavailable and those already fixed to another duty that day
                    available_home = []
                    for j in home_doctors:
                        doc_name = doctors[j]
                        if (doc_name, day_idx) in schedule.unavailable:
                            continue
                        if any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name):
                            continue
                        available_home.append(j)
                    if available_home:
                        allowed = available_home
                    else:
                        # Fallback: any doctor not unavailable and not fixed that day
                        fallback = [j for j, doc_name in enumerate(doctors)
                                    if (doc_name, day_idx) not in schedule.unavailable
                                    and not any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name)]
                        if fallback:
                            allowed = fallback
                        else:
                            # Ultimate fallback: all doctors (vacation/fixed constraints will block)
                            allowed = list(range(num_doctors))
                            print(f"ZD on day {day_idx}, station {station}: no eligible doctors – allowing all")
        # Ensure allowed is never empty
        if not allowed:
            raise ValueError(f"No allowed doctors for duty {i}: day={day_idx}, station='{station}', abbr='{abbr}'")
        model_cp.Add(sum(x[(i, j)] for j in allowed) == 1)

    # KEEP KM pairing
    km_duties_by_week = defaultdict(list)
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'KM':
            week_num = schedule.days[day_idx].date.isocalendar().week
            km_duties_by_week[week_num].append(i)
    for week_num, duty_indices in km_duties_by_week.items():
        if len(duty_indices) == 2:
            for j in range(num_doctors):
                model_cp.Add(x[(duty_indices[0], j)] == x[(duty_indices[1], j)])

    # KEEP vacation constraint
    for i, (day_idx, station, abbr) in enumerate(duties):
        for j, doc_name in enumerate(doctors):
            if (doc_name, day_idx) in schedule.unavailable:
                model_cp.Add(x[(i, j)] == 0)

    # KEEP weekend constraints
    if constraints_cfg.get('WeekendOnlyFullTime', 'Yes') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if schedule.days[day_idx].is_weekend:
                for j, doc_name in enumerate(doctors):
                    if schedule.doctors[doc_name].fte < 100:
                        model_cp.Add(x[(i, j)] == 0)

    if constraints_cfg.get('WeekendAvailability', 'Yes') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if schedule.days[day_idx].is_weekend:
                for j, doc_name in enumerate(doctors):
                    if not schedule.doctors[doc_name].weekend_available:
                        model_cp.Add(x[(i, j)] == 0)

    if constraints_cfg.get('WeekendOnlyForSkilled', 'Yes') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if schedule.days[day_idx].is_weekend:
                for j, doc_name in enumerate(doctors):
                    if 'Weekend' not in schedule.doctors[doc_name].skills:
                        model_cp.Add(x[(i, j)] == 0)

    # Max weekend duties per doctor
    max_weekend_per_doctor = int(general.get('MaxWeekendPerDoctor', 1))
    if constraints_cfg.get('MaxOneWeekendPerDoctor', 'Yes') == 'Yes':
        for j in range(num_doctors):
            weekend_duties_for_doctor = []
            for i, (day_idx, station, abbr) in enumerate(duties):
                if schedule.days[day_idx].is_weekend:
                    weekend_duties_for_doctor.append(x[(i, j)])
            if weekend_duties_for_doctor:
                model_cp.Add(sum(weekend_duties_for_doctor) <= max_weekend_per_doctor)

    max_sd_per_doctor = int(general.get('MaxSDPerDoctor', 4))
    if constraints_cfg.get('MaxSD', 'Yes') == 'Yes':
        for j in range(num_doctors):
            sd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'SD']
            if sd_indices:
                model_cp.Add(sum(x[(i, j)] for i in sd_indices) <= max_sd_per_doctor)

    # --- 92 KMT weekend PR restriction ---
    allowed_92_indices = [
        j for j, doc_name in enumerate(doctors)
        if schedule.doctors[doc_name].allow_92_kmt
    ]
    for i, (day_idx, station, abbr) in enumerate(duties):
        if station == '92 KMT' and schedule.days[day_idx].is_weekend and abbr == 'PR':
            if allowed_92_indices:
                model_cp.Add(sum(x[(i, j)] for j in allowed_92_indices) == 1)
            else:
                model_cp.Add(0 == 1)

    # --- NAZ restriction ---
    allowed_naz_indices = [
        j for j, doc_name in enumerate(doctors)
        if schedule.doctors[doc_name].allow_naz
    ]
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'NAZ':
            if allowed_naz_indices:
                model_cp.Add(sum(x[(i, j)] for j in allowed_naz_indices) == 1)
            else:
                model_cp.Add(0 == 1)

    # Add soft constraints (objective)
    penalties = add_soft_constraints(model_cp, schedule, config, x, duties, doctors, demand, duty_hours, initial_hours)
    model_cp.Minimize(sum(penalties))

    # --- DIAGNOSTICS (no local imports) ---
    print("\n=== REPAIR DIAGNOSTICS ===")
    
    # 1. Count duties per day
    duties_per_day = defaultdict(int)
    for i, (day_idx, _, _) in enumerate(duties):
        duties_per_day[day_idx] += 1
    print("Duties per day (day index: count):", sorted(duties_per_day.items()))

    # 2. Available doctors per day (respecting vacation, weekend restrictions)
    for day_idx in range(len(schedule.days)):
        count = duties_per_day.get(day_idx, 0)
        if count == 0:
            continue
        available = 0
        for doc_name in doctors:
            doc = schedule.doctors[doc_name]
            if (doc_name, day_idx) in schedule.unavailable:
                continue
            if schedule.days[day_idx].is_weekend:
                if doc.fte < 100 or not doc.weekend_available:
                    continue
            available += 1
        print(f"Day {day_idx} ({schedule.days[day_idx].date}): duties={count}, available doctors={available}")

    # 3. Check for conflicting fixed assignments
    fixed_conflicts = defaultdict(list)
    for doc_name, day_idx, station, abbr in schedule.fixed_assignments:
        fixed_conflicts[(doc_name, day_idx)].append(abbr)
    conflict_found = False
    for (doc, day), duties_list in fixed_conflicts.items():
        if len(duties_list) > 1:
            print(f"CONFLICT: Doctor {doc} has multiple fixed duties on day {day}: {duties_list}")
            conflict_found = True
    if not conflict_found:
        print("No fixed assignment conflicts found.")

    # 4. Check capacity (ignore station restrictions)
    for day_idx in range(len(schedule.days)):
        count = duties_per_day.get(day_idx, 0)
        if count == 0:
            continue
        potential = 0
        for doc_name in doctors:
            doc = schedule.doctors[doc_name]
            if (doc_name, day_idx) in schedule.unavailable:
                continue
            if schedule.days[day_idx].is_weekend:
                if doc.fte < 100 or not doc.weekend_available:
                    continue
            potential += 1
        if potential < count:
            print(f"WARNING: Day {day_idx} has {count} duties but only {potential} potentially available doctors (before station restrictions).")
    # 5. Station-specific capacity check (weekend PR only)
    from collections import defaultdict as dd
    station_duties = dd(lambda: dd(int))  # day -> station -> count
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'PR' and schedule.days[day_idx].is_weekend:
            station_duties[day_idx][station] += 1

    for day_idx in sorted(station_duties.keys()):
        for station, count in station_duties[day_idx].items():
            # Count doctors available for this station on this day
            eligible = 0
            for doc_name in doctors:
                doc = schedule.doctors[doc_name]
                if (doc_name, day_idx) in schedule.unavailable:
                    continue
                if doc.fte < 100 or not doc.weekend_available:
                    continue
                # Check station eligibility:
                if station == '92 KMT' and not doc.allow_92_kmt:
                    continue
                if doc.station != station and station != 'Global':  # only same station or global
                    continue
                eligible += 1
            if eligible < count:
                print(f"WARNING: Day {day_idx} station {station} needs {count} PR but only {eligible} eligible doctors.")
    # 6. Station-specific weekday demand (ZD, SD)
    station_weekday_demand = defaultdict(lambda: defaultdict(int))
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr in ['ZD', 'SD'] and station != 'Global' and not schedule.days[day_idx].is_weekend:
            station_weekday_demand[day_idx][station] += 1

    for day_idx, station_demand in station_weekday_demand.items():
        for station, count in station_demand.items():
            # Count available doctors from this station (not on vacation, not fixed that day)
            available = 0
            for doc_name in doctors:
                doc = schedule.doctors[doc_name]
                if doc.station != station:
                    continue
                if (doc_name, day_idx) in schedule.unavailable:
                    continue
                if any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name):
                    continue
                available += 1
            if available < count:
                print(f"WARNING: Day {day_idx} ({schedule.days[day_idx].date}) station {station} needs {count} ZD/SD duties but only {available} available doctors.")

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.log_search_progress = True
    solver.parameters.max_time_in_seconds = 60.0 
    status = solver.Solve(model_cp)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignment = {}
        for i in range(num_duties):
            for j in range(num_doctors):
                if solver.Value(x[(i, j)]) == 1:
                    assignment[i] = doctors[j]
                    break
        print("Repair successful (station match kept).")
        return assignment, solver, duties, doctors, duty_hours, initial_hours

    raise RuntimeError(
        "Even with relaxed skill constraints, the model is infeasible. "
        "Please reduce demand (e.g., lower DutyCounts) or add more doctors."
    )
