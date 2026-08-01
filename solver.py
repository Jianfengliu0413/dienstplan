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
    try:
        initial_hours = load_working_hours(config_path, doctors)
    except Exception as e:
        print(f"failed to get the initial_hours from 'Rules file: {e}'")
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
            return repair_schedule(schedule, config, duties, doctors, demand)
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
            return repair_schedule(schedule, config, duties, doctors, demand)
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
            print(f"🔒 REPAIR FIXED: {doc_name} must do {duty_abbr} at {station} on day {day_idx}")
        else:
            print(f"⚠️ Warning: Fixed assignment for {doc_name} on {day_idx} {station} {duty_abbr} not found in duties.")

    # Essential constraints
    for i in range(num_duties):
        model_cp.Add(sum(x[(i, j)] for j in range(num_doctors)) == 1)
    duties_by_day = defaultdict(list)
    for i, (day_idx, _, _) in enumerate(duties):
        duties_by_day[day_idx].append(i)
    for day_idx, duty_list in duties_by_day.items():
        for j in range(num_doctors):
            model_cp.Add(sum(x[(i, j)] for i in duty_list) <= 1)

    # KEEP station match (but relax for weekend PR duties – allow cross‑station) 
    for i, (day_idx, station, abbr) in enumerate(duties):
        # Special rules:
        if abbr == 'SUB':
            allowed = [j for j, doc_name in enumerate(doctors) 
                    if schedule.doctors[doc_name].station == '65 PP']
        # elif abbr in ['ZD', 'SD', 'HD', 'NAZ']:  # <-- add this line
        #     allowed = list(range(num_doctors))   # any doctor can cover these shifts
        elif schedule.days[day_idx].is_weekend and abbr == 'PR':
            allowed = list(range(num_doctors))
        else:
            allowed = [j for j, doc_name in enumerate(doctors) 
                    if schedule.doctors[doc_name].station == station or station == 'Global']
        model_cp.Add(sum(x[(i, j)] for j in allowed) == 1)

    # KEEP KM pairing (same doctor for Mon & Tue of same week)
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

    # KEEP weekend constraints (full‑time, availability, skill)
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

    # Max one weekend per doctor
    if constraints_cfg.get('MaxOneWeekendPerDoctor', 'Yes') == 'Yes':
        for j in range(num_doctors):
            weekend_duties_for_doctor = []
            for i, (day_idx, station, abbr) in enumerate(duties):
                if schedule.days[day_idx].is_weekend:
                    weekend_duties_for_doctor.append(x[(i, j)])
            if weekend_duties_for_doctor:
                model_cp.Add(sum(weekend_duties_for_doctor) <= 1)

    # Add soft constraints (including KMBalance and preferences)
    penalties = add_soft_constraints(model_cp, schedule, config, x, duties, doctors, demand, duty_hours, initial_hours)
    model_cp.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
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

    # If still infeasible, raise error
    raise RuntimeError(
        "Even with relaxed skill constraints, the model is infeasible. "
        "Please reduce demand (e.g., lower DutyCounts) or add more doctors."
    )
