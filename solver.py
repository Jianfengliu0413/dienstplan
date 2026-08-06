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
import copy

from demand_builder import GLOBAL_STATION, MAIN_STATIONS 


def solve_schedule(
    schedule: ScheduleModel,
    config: dict,
    config_path: str, 
    repair_mode: bool = True,
    auto_relax: bool = True
) -> Tuple[Dict[int, str], cp_model.CpSolver, List[Tuple[int, str, str]], List[str]]:
    """
    Solve the schedule. If repair_mode is True, it will relax skill constraints if needed.
    If auto_relax is True, it will also progressively increase caps and disable constraints
    if the repair fails.
    """
    demand = build_demand(schedule, config)
    duties = []
    duty_hours = []
    for (day_idx, station), counts in demand.items():
        for abbr, cnt in counts.items():
            hours = schedule.duty_types[abbr].hours
            for _ in range(cnt):
                duties.append((day_idx, station, abbr))
                duty_hours.append(hours)
    doctors = list(schedule.doctors.keys())
    initial_hours = {doc: 0.0 for doc in doctors}

    # Try normal solve with optional repair
    try:
        return _solve_internal(schedule, config, duties, doctors, demand, duty_hours, initial_hours, repair_mode)
    except RuntimeError as e:
        if not auto_relax:
            raise
        print("Normal solve (even with repair) failed. Starting automatic parameter relaxation...")
        return auto_relax_and_solve(schedule, config, duties, doctors, demand, duty_hours, initial_hours)


def _solve_internal(schedule, config, duties, doctors, demand, duty_hours, initial_hours, repair_mode):
    """
    Core solve routine. Builds model, adds constraints, solves.
    If repair_mode is True and a hard constraint error or infeasibility occurs,
    it calls repair_schedule.
    """
    num_duties = len(duties)
    num_doctors = len(doctors)
    model_cp = cp_model.CpModel()
    x = {}
    for i in range(num_duties):
        for j in range(num_doctors):
            x[(i, j)] = model_cp.NewBoolVar(f'x_{i}_{j}')

    # Fixed assignments
    duty_map = {}
    for i, (day_idx, station, abbr) in enumerate(duties):
        duty_map[(day_idx, station, abbr)] = i

    for doc_name, day_idx, station, duty_abbr in schedule.fixed_assignments:
        if (day_idx, station, duty_abbr) in duty_map:
            duty_i = duty_map[(day_idx, station, duty_abbr)]
            doctor_j = doctors.index(doc_name)
            model_cp.Add(x[(duty_i, doctor_j)] == 1)
            print(f"[FIXED]: {doc_name} want {duty_abbr} at {station} on day {day_idx}")
        else:
            print(f"[Warning]: Fixed assignment for {doc_name} on {day_idx} {station} {duty_abbr} not found in duties.")

    try:
        add_hard_constraints(model_cp, schedule, config, x, duties, doctors, demand)
    except ValueError as e:
        if repair_mode:
            print(f"Hard constraint error: {e}. Attempting repair by relaxing constraints...")
            return repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours)
        else:
            raise

    # Soft constraints
    penalties = add_soft_constraints(model_cp, schedule, config, x, duties, doctors, demand, duty_hours, initial_hours)
    model_cp.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    status = solver.Solve(model_cp)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if repair_mode:
            print("No feasible solution found. Running repair...")
            return repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours)
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
    Repair: relax skill constraints only. Keep all other hard constraints.
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

    # --- ENFORCE FIXED ASSIGNMENTS ---
    duty_map = {}
    for i, (day_idx, station, abbr) in enumerate(duties):
        duty_map[(day_idx, station, abbr)] = i
    for doc_name, day_idx, station, duty_abbr in schedule.fixed_assignments:
        if (day_idx, station, duty_abbr) in duty_map:
            duty_i = duty_map[(day_idx, station, duty_abbr)]
            doctor_j = doctors.index(doc_name)
            model_cp.Add(x[(duty_i, doctor_j)] == 1)
            print(f"REPAIR FIXED: {doc_name} want {duty_abbr} at {station} on day {day_idx}")
        else:
            print(f"Warning: Fixed assignment for {doc_name} on {day_idx} {station} {duty_abbr} not found in duties.")

    # 1. Each duty assigned to exactly one doctor
    for i in range(num_duties):
        model_cp.Add(sum(x[(i, j)] for j in range(num_doctors)) == 1)

    # 2. Each doctor at most one duty per day
    duties_by_day = defaultdict(list)
    for i, (day_idx, _, _) in enumerate(duties):
        duties_by_day[day_idx].append(i)
    for day_idx, duty_list in duties_by_day.items():
        for j in range(num_doctors):
            model_cp.Add(sum(x[(i, j)] for i in duty_list) <= 1)

    # 3. Station match (including weekend PR logic)
    for i, (day_idx, station, abbr) in enumerate(duties):
        if station == GLOBAL_STATION:
            if abbr == 'SD':
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
                    allowed = [j for j, doc_name in enumerate(doctors)
                               if schedule.doctors[doc_name].station == station]
                else:
                    home_doctors = [j for j, doc_name in enumerate(doctors)
                                    if schedule.doctors[doc_name].station == station]
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
                        fallback = [j for j, doc_name in enumerate(doctors)
                                    if (doc_name, day_idx) not in schedule.unavailable
                                    and not any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name)]
                        if fallback:
                            allowed = fallback
                        else:
                            allowed = list(range(num_doctors))
                            print(f"ZD on day {day_idx}, station {station}: no eligible doctors – allowing all")
        if not allowed:
            raise ValueError(f"No allowed doctors for duty {i}: day={day_idx}, station='{station}', abbr='{abbr}'")
        model_cp.Add(sum(x[(i, j)] for j in allowed) == 1)

    # 4. KM pairing
    km_duties_by_week = defaultdict(list)
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'KM':
            week_num = schedule.days[day_idx].date.isocalendar().week
            km_duties_by_week[week_num].append(i)
    for week_num, duty_indices in km_duties_by_week.items():
        if len(duty_indices) == 2:
            for j in range(num_doctors):
                model_cp.Add(x[(duty_indices[0], j)] == x[(duty_indices[1], j)])

    # 5. Vacation / unavailable
    for i, (day_idx, station, abbr) in enumerate(duties):
        for j, doc_name in enumerate(doctors):
            if (doc_name, day_idx) in schedule.unavailable:
                model_cp.Add(x[(i, j)] == 0)

    # 6. Weekend restrictions
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

    # 7. Max total weekend duties per doctor
    max_weekend_per_doctor = int(general.get('MaxWeekendPerDoctor', 1))
    if constraints_cfg.get('MaxOneWeekendPerDoctor', 'Yes') == 'Yes':
        for j in range(num_doctors):
            weekend_indices = [i for i, (day_idx, _, _) in enumerate(duties) if schedule.days[day_idx].is_weekend]
            if weekend_indices:
                model_cp.Add(sum(x[(i, j)] for i in weekend_indices) <= max_weekend_per_doctor)

    # 8. Max SD per doctor
    max_sd_per_doctor = int(general.get('MaxSDPerDoctor', 4))
    if constraints_cfg.get('MaxSD', 'Yes') == 'Yes':
        for j in range(num_doctors):
            sd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'SD']
            if sd_indices:
                model_cp.Add(sum(x[(i, j)] for i in sd_indices) <= max_sd_per_doctor)

    # 9. Max NAZ per doctor
    max_naz = int(general.get('MaxNAZPerDoctor', 2))
    if constraints_cfg.get('MaxNAZ', 'Yes') == 'Yes':
        for j in range(num_doctors):
            naz_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'NAZ']
            if naz_indices:
                model_cp.Add(sum(x[(i, j)] for i in naz_indices) <= max_naz)

    # 10. Max PR on weekends per doctor
    max_pr_weekend = int(general.get('MaxWeekendPRPerDoctor', 1))
    if constraints_cfg.get('MaxWeekendPR', 'Yes') == 'Yes':
        for j in range(num_doctors):
            pr_weekend_indices = [
                i for i, (day_idx, station, abbr) in enumerate(duties)
                if abbr == 'PR' and schedule.days[day_idx].is_weekend
            ]
            if pr_weekend_indices:
                model_cp.Add(sum(x[(i, j)] for i in pr_weekend_indices) <= max_pr_weekend)

    # 11. Max house shifts (HD) per doctor
    max_hd_per_doctor = int(general.get('MaxHouseShifts', 2))
    if constraints_cfg.get('MaxHouseShifts', 'Yes') == 'Yes':
        for j in range(num_doctors):
            hd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'HD']
            if hd_indices:
                model_cp.Add(sum(x[(i, j)] for i in hd_indices) <= max_hd_per_doctor)

    # 12. 92 KMT weekend PR restriction
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

    # 13. NAZ restriction (only allowed doctors)
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

    # 14. Max consecutive days
    if constraints_cfg.get('MaxConsecutive', 'Yes') == 'Yes':
        max_consec = int(general.get('MaxConsecutiveWorkDays', 6))
        if max_consec > 0:
            work = {}
            for j in range(num_doctors):
                for day_idx in range(len(schedule.days)):
                    duties_this_day = [i for i, (d, _, _) in enumerate(duties) if d == day_idx]
                    if duties_this_day:
                        work[(j, day_idx)] = model_cp.NewBoolVar(f'work_{j}_{day_idx}')
                        model_cp.Add(work[(j, day_idx)] == sum(x[(i, j)] for i in duties_this_day))
                    else:
                        work[(j, day_idx)] = model_cp.NewConstant(0)
            for j in range(num_doctors):
                for start in range(len(schedule.days) - max_consec):
                    window = [work[(j, day)] for day in range(start, start + max_consec + 1)]
                    model_cp.Add(sum(window) <= max_consec)

    # 15. Max duties per week
    if constraints_cfg.get('MaxPerWeek', 'Yes') == 'Yes':
        max_week = int(general.get('MaxDutiesPerWeek', 5))
        if max_week > 0:
            week_days = defaultdict(list)
            for day_idx, day in enumerate(schedule.days):
                week_days[day.date.isocalendar().week].append(day_idx)
            for week, day_indices in week_days.items():
                for j in range(num_doctors):
                    duty_indices_in_week = [i for i, (d, _, _) in enumerate(duties) if d in day_indices]
                    if duty_indices_in_week:
                        model_cp.Add(sum(x[(i, j)] for i in duty_indices_in_week) <= max_week)

    # Add soft constraints (objective)
    penalties = add_soft_constraints(model_cp, schedule, config, x, duties, doctors, demand, duty_hours, initial_hours)
    model_cp.Minimize(sum(penalties))

    # Diagnostics (as before)
    print("\n=== REPAIR DIAGNOSTICS ===")
    # ... keep the existing diagnostics code ...
    # (We'll include the diagnostics code from the original repair_schedule)
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
            eligible = 0
            for doc_name in doctors:
                doc = schedule.doctors[doc_name]
                if (doc_name, day_idx) in schedule.unavailable:
                    continue
                if doc.fte < 100 or not doc.weekend_available:
                    continue
                if station == '92 KMT' and not doc.allow_92_kmt:
                    continue
                if doc.station != station and station != 'Global':
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
def auto_relax_and_solve(schedule, config, duties, doctors, demand, duty_hours, initial_hours):
    """
    Attempt to solve by progressively relaxing parameters in multiple stages.
    Returns (assignment, solver, duties, doctors, duty_hours, initial_hours) on success.
    Raises RuntimeError if all relaxation stages fail.
    """
    # Define relaxation stages (each stage is a dict of adjustments)
    # Stage 1: moderate increases
    stage1 = {
        'caps': {
            'MaxWeekendPerDoctor': 6,
            'MaxWeekendPRPerDoctor': 2,
            'MaxConsecutiveWorkDays': 8,
            'MaxDutiesPerWeek': 7
        },
        'disable': []  # no constraints disabled
    }
    # Stage 2: further increases and disable MaxOneWeekendPerDoctor
    stage2 = {
        'caps': {
            'MaxWeekendPerDoctor': 8,
            'MaxWeekendPRPerDoctor': 4,
            'MaxConsecutiveWorkDays': 9,
            'MaxDutiesPerWeek': 8
        },
        'disable': ['MaxOneWeekendPerDoctor']
    }
    # Stage 3: very high caps, disable MaxWeekendPR, and remove PR demand
    stage3 = {
        'caps': {
            'MaxWeekendPerDoctor': 10,
            'MaxWeekendPRPerDoctor': 10,
            'MaxConsecutiveWorkDays': 10,
            'MaxDutiesPerWeek': 10
        },
        'disable': ['MaxOneWeekendPerDoctor', 'MaxWeekendPR'],
        'remove_pr': True   # remove PR from weekend demand for main stations
    }

    stages = [stage1, stage2, stage3]
    all_adjustments = []
    relaxed_config = copy.deepcopy(config)   # start with original config

    for stage_idx, stage in enumerate(stages, start=1):
        print(f"\n--- Auto‑relaxation Stage {stage_idx} ---")
        # Apply caps
        general = relaxed_config.get('GeneralRules', pd.DataFrame())
        if not general.empty and 'RuleName' in general.columns:
            if general['Value'].dtype != object:
                general['Value'] = general['Value'].astype(object)
        else:
            general = pd.DataFrame(columns=['RuleName', 'Value'])

        for rule, new_val in stage['caps'].items():
            if rule in general['RuleName'].values:
                idx = general[general['RuleName'] == rule].index[0]
                old = general.loc[idx, 'Value']
                try:
                    old_int = int(old)
                except (ValueError, TypeError):
                    old_int = 0
                if old_int < new_val:
                    general.at[idx, 'Value'] = str(new_val)
                    all_adjustments.append(f"Stage {stage_idx}: Increased {rule} from {old} to {new_val}")
            else:
                new_row = pd.DataFrame({'RuleName': [rule], 'Value': [str(new_val)]})
                general = pd.concat([general, new_row], ignore_index=True)
                all_adjustments.append(f"Stage {stage_idx}: Added {rule} = {new_val}")
        relaxed_config['GeneralRules'] = general

        # Disable constraints
        constraints = relaxed_config.get('Constraints', pd.DataFrame())
        if not constraints.empty and 'Constraint' in constraints.columns:
            if constraints['Enabled'].dtype != object:
                constraints['Enabled'] = constraints['Enabled'].astype(object)
        else:
            constraints = pd.DataFrame(columns=['Constraint', 'Enabled'])

        for cons in stage.get('disable', []):
            if cons in constraints['Constraint'].values:
                idx = constraints[constraints['Constraint'] == cons].index[0]
                if constraints.loc[idx, 'Enabled'] == 'Yes':
                    constraints.at[idx, 'Enabled'] = 'No'
                    all_adjustments.append(f"Stage {stage_idx}: Disabled constraint {cons}")
            else:
                new_row = pd.DataFrame({'Constraint': [cons], 'Enabled': ['No']})
                constraints = pd.concat([constraints, new_row], ignore_index=True)
                all_adjustments.append(f"Stage {stage_idx}: Added constraint {cons} = No")
        relaxed_config['Constraints'] = constraints

        # Remove PR demand (last resort, only in stage 3)
        if stage.get('remove_pr', False):
            stations = relaxed_config.get('Stations', pd.DataFrame())
            if not stations.empty and 'Station' in stations.columns:
                for idx, row in stations.iterrows():
                    station = row['Station']
                    if station in MAIN_STATIONS:
                        weekend_counts = row.get('WeekendDutyCounts', '')
                        if pd.isna(weekend_counts):
                            weekend_counts = ''
                        if 'PR=' in weekend_counts:
                            parts = [p.strip() for p in weekend_counts.split(',') if p.strip()]
                            new_parts = [p for p in parts if not p.startswith('PR=')]
                            if not new_parts:
                                new_val = ''
                            else:
                                new_val = ', '.join(new_parts)
                            if new_val != weekend_counts:
                                stations.at[idx, 'WeekendDutyCounts'] = new_val
                                all_adjustments.append(f"Stage {stage_idx}: Removed PR from {station} weekend demand")
                relaxed_config['Stations'] = stations

        print("Attempting solve with current relaxations...")
        try:
            # Try to solve with this stage's relaxed config
            result = _solve_internal(schedule, relaxed_config, duties, doctors, demand, duty_hours, initial_hours, repair_mode=True)
            print(f"Stage {stage_idx} succeeded!")
            print("Relaxations applied:")
            for adj in all_adjustments:
                print(f"  - {adj}")
            return result
        except RuntimeError:
            print(f"Stage {stage_idx} failed. Continuing to next stage...")
            continue

    # All stages failed
    raise RuntimeError(
        "Auto-relaxation could not find a feasible solution after all stages.\n"
        "Adjustments made:\n" + "\n".join(all_adjustments) +
        "\nConsider reducing demand (e.g., lower PR counts) or adding more doctors."
    )
 

# # solver.py
# from ortools.sat.python import cp_model
# from models import ScheduleModel
# from demand_builder import build_demand
# from constraints import add_hard_constraints
# from objective import add_soft_constraints
# from config_loader import load_working_hours 
# import pandas as pd
# from collections import defaultdict
# from typing import Tuple, List, Dict

# from demand_builder import GLOBAL_STATION, MAIN_STATIONS 


# def solve_schedule(
#     schedule: ScheduleModel,
#     config: dict,
#     config_path: str, 
#     repair_mode: bool = True
# ) -> Tuple[Dict[int, str], cp_model.CpSolver, List[Tuple[int, str, str]], List[str]]:
#     demand = build_demand(schedule, config)
#     duties = []  # list of (day_idx, station, duty_abbr)
#     duty_hours = []   # list of hours per duty
#     for (day_idx, station), counts in demand.items():
#         for abbr, cnt in counts.items():
#             hours = schedule.duty_types[abbr].hours
#             for _ in range(cnt):
#                 duties.append((day_idx, station, abbr))
#                 duty_hours.append(hours)
#     doctors = list(schedule.doctors.keys())
#     num_duties = len(duties)
#     num_doctors = len(doctors)

#     # Load initial working hours
#     # try:
#     #     initial_hours = load_working_hours(config_path, doctors)
#     # except Exception as e:
#     #     print(f"failed to get the initial_hours from 'Rules file: {e}'")
#     initial_hours = {doc: 0.0 for doc in doctors}
#     # Create CP model
#     model_cp = cp_model.CpModel()
#     x = {}
#     for i in range(num_duties):
#         for j in range(num_doctors):
#             x[(i, j)] = model_cp.NewBoolVar(f'x_{i}_{j}')
 
    
#     # --- ENFORCE FIXED ASSIGNMENTS (hard constraints) ---
#     duty_map = {}
#     for i, (day_idx, station, abbr) in enumerate(duties):
#         duty_map[(day_idx, station, abbr)] = i

#     for doc_name, day_idx, station, duty_abbr in schedule.fixed_assignments:
#         if (day_idx, station, duty_abbr) in duty_map:
#             duty_i = duty_map[(day_idx, station, duty_abbr)]
#             doctor_j = doctors.index(doc_name)
#             model_cp.Add(x[(duty_i, doctor_j)] == 1)
#             print(f"[FIXED]: {doc_name} want {duty_abbr} at {station} on day {day_idx}")
#         else:
#             print(f"[Warning]: Fixed assignment for {doc_name} on {day_idx} {station} {duty_abbr} not found in duties.")

#     # Build hard constraints (now including the fixed assignments)
#     try:
#         add_hard_constraints(model_cp, schedule, config, x, duties, doctors, demand)
#     except ValueError as e:
#         if repair_mode:
#             print(f"Hard constraint error: {e}. Attempting repair by relaxing constraints...")
#             return repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours)# repair_schedule(schedule, config, duties, doctors, demand)
#         else:
#             raise
    
#     # Build soft constraints (objective)
#     penalties = add_soft_constraints(model_cp, schedule, config, x, duties, doctors, demand, duty_hours, initial_hours)
#     model_cp.Minimize(sum(penalties))

#     solver = cp_model.CpSolver()
#     status = solver.Solve(model_cp)

#     if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
#         if repair_mode:
#             print("No feasible solution found. Running repair...")
#             return repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours) #repair_schedule(schedule, config, duties, doctors, demand)
#         else:
#             raise RuntimeError("No feasible solution.")

#     assignment = {}
#     for i in range(num_duties):
#         for j in range(num_doctors):
#             if solver.Value(x[(i, j)]) == 1:
#                 assignment[i] = doctors[j]
#                 break

#     return assignment, solver, duties, doctors, duty_hours, initial_hours

# # def repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours):
# #     """
# #     Repair: relax skill constraints only. Keep station match, vacation, and weekend rules.
# #     If still infeasible, raise error (user must reduce demand).
# #     """

# #     general_df = config.get('GeneralRules', pd.DataFrame())
# #     if not general_df.empty and 'RuleName' in general_df.columns:
# #         general = general_df.set_index('RuleName')['Value'].to_dict()
# #     else:
# #         general = {}

# #     constraints_cfg = config.get('Constraints', pd.DataFrame())
# #     if not constraints_cfg.empty and 'Constraint' in constraints_cfg.columns:
# #         constraints_cfg = constraints_cfg.set_index('Constraint')['Enabled'].to_dict()
# #     else:
# #         constraints_cfg = {}

# #     print("Repair: relaxing skill constraints (keeping station match, vacation, and weekend rules)...")
# #     model_cp = cp_model.CpModel()
# #     num_duties = len(duties)
# #     num_doctors = len(doctors)
# #     x = {}
# #     for i in range(num_duties):
# #         for j in range(num_doctors):
# #             x[(i, j)] = model_cp.NewBoolVar(f'x_{i}_{j}')

# #     # --- ENFORCE FIXED ASSIGNMENTS (hard constraints) ---
# #     duty_map = {}
# #     for i, (day_idx, station, abbr) in enumerate(duties):
# #         duty_map[(day_idx, station, abbr)] = i

# #     for doc_name, day_idx, station, duty_abbr in schedule.fixed_assignments:
# #         if (day_idx, station, duty_abbr) in duty_map:
# #             duty_i = duty_map[(day_idx, station, duty_abbr)]
# #             doctor_j = doctors.index(doc_name)
# #             model_cp.Add(x[(duty_i, doctor_j)] == 1)
# #             print(f"REPAIR FIXED: {doc_name} want {duty_abbr} at {station} on day {day_idx}")
# #         else:
# #             print(f"Warning: Fixed assignment for {doc_name} on {day_idx} {station} {duty_abbr} not found in duties.")

# #     # Essential constraints
# #     for i in range(num_duties):
# #         model_cp.Add(sum(x[(i, j)] for j in range(num_doctors)) == 1)
# #     duties_by_day = defaultdict(list)
# #     for i, (day_idx, _, _) in enumerate(duties):
# #         duties_by_day[day_idx].append(i)
# #     for day_idx, duty_list in duties_by_day.items():
# #         for j in range(num_doctors):
# #             model_cp.Add(sum(x[(i, j)] for i in duty_list) <= 1)


# #     # 3. Station match
# #     for i, (day_idx, station, abbr) in enumerate(duties):
# #         if station == GLOBAL_STATION:
# #             if abbr == 'SD':
# #                 # Prefer main‑station doctors, but fallback to all if none available
# #                 main_allowed = [j for j, doc_name in enumerate(doctors)
# #                                 if schedule.doctors[doc_name].station in MAIN_STATIONS]
# #                 if main_allowed:
# #                     allowed = main_allowed
# #                 else:
# #                     allowed = list(range(num_doctors))
# #                     print(f"Global SD on day {day_idx}: no main‑station doctors – allowing all")
# #             else:
# #                 allowed = list(range(num_doctors))
# #         else:
# #             if abbr == 'SUB':
# #                 allowed = [j for j, doc_name in enumerate(doctors) 
# #                         if schedule.doctors[doc_name].station == '65 PP']
# #             elif schedule.days[day_idx].is_weekend and abbr == 'PR':
# #                 allowed = list(range(num_doctors))
# #             else:
# #                 if abbr == 'SD':
# #                     # Station‑specific SD: only doctors from the same station
# #                     allowed = [j for j, doc_name in enumerate(doctors)
# #                             if schedule.doctors[doc_name].station == station]
# #                 else:
# #                     # ZD and other weekdays: prefer same station, else any doctor
# #                     home_doctors = [j for j, doc_name in enumerate(doctors)
# #                                     if schedule.doctors[doc_name].station == station]
# #                     # Filter out unavailable and those already fixed to another duty that day
# #                     available_home = []
# #                     for j in home_doctors:
# #                         doc_name = doctors[j]
# #                         if (doc_name, day_idx) in schedule.unavailable:
# #                             continue
# #                         if any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name):
# #                             continue
# #                         available_home.append(j)
# #                     if available_home:
# #                         allowed = available_home
# #                     else:
# #                         # Fallback: any doctor not unavailable and not fixed that day
# #                         fallback = [j for j, doc_name in enumerate(doctors)
# #                                     if (doc_name, day_idx) not in schedule.unavailable
# #                                     and not any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name)]
# #                         if fallback:
# #                             allowed = fallback
# #                         else:
# #                             # Ultimate fallback: all doctors (vacation/fixed constraints will block)
# #                             allowed = list(range(num_doctors))
# #                             print(f"ZD on day {day_idx}, station {station}: no eligible doctors – allowing all")
# #         # Ensure allowed is never empty
# #         if not allowed:
# #             raise ValueError(f"No allowed doctors for duty {i}: day={day_idx}, station='{station}', abbr='{abbr}'")
# #         model_cp.Add(sum(x[(i, j)] for j in allowed) == 1)

# #     # KEEP KM pairing
# #     km_duties_by_week = defaultdict(list)
# #     for i, (day_idx, station, abbr) in enumerate(duties):
# #         if abbr == 'KM':
# #             week_num = schedule.days[day_idx].date.isocalendar().week
# #             km_duties_by_week[week_num].append(i)
# #     for week_num, duty_indices in km_duties_by_week.items():
# #         if len(duty_indices) == 2:
# #             for j in range(num_doctors):
# #                 model_cp.Add(x[(duty_indices[0], j)] == x[(duty_indices[1], j)])

# #     # KEEP vacation constraint
# #     for i, (day_idx, station, abbr) in enumerate(duties):
# #         for j, doc_name in enumerate(doctors):
# #             if (doc_name, day_idx) in schedule.unavailable:
# #                 model_cp.Add(x[(i, j)] == 0)

# #     # KEEP weekend constraints
# #     if constraints_cfg.get('WeekendOnlyFullTime', 'Yes') == 'Yes':
# #         for i, (day_idx, station, abbr) in enumerate(duties):
# #             if schedule.days[day_idx].is_weekend:
# #                 for j, doc_name in enumerate(doctors):
# #                     if schedule.doctors[doc_name].fte < 100:
# #                         model_cp.Add(x[(i, j)] == 0)

# #     if constraints_cfg.get('WeekendAvailability', 'Yes') == 'Yes':
# #         for i, (day_idx, station, abbr) in enumerate(duties):
# #             if schedule.days[day_idx].is_weekend:
# #                 for j, doc_name in enumerate(doctors):
# #                     if not schedule.doctors[doc_name].weekend_available:
# #                         model_cp.Add(x[(i, j)] == 0)

# #     if constraints_cfg.get('WeekendOnlyForSkilled', 'Yes') == 'Yes':
# #         for i, (day_idx, station, abbr) in enumerate(duties):
# #             if schedule.days[day_idx].is_weekend:
# #                 for j, doc_name in enumerate(doctors):
# #                     if 'Weekend' not in schedule.doctors[doc_name].skills:
# #                         model_cp.Add(x[(i, j)] == 0)

# #     # Max weekend duties per doctor
# #     max_weekend_per_doctor = int(general.get('MaxWeekendPerDoctor', 1))
# #     if constraints_cfg.get('MaxOneWeekendPerDoctor', 'Yes') == 'Yes':
# #         for j in range(num_doctors):
# #             weekend_duties_for_doctor = []
# #             for i, (day_idx, station, abbr) in enumerate(duties):
# #                 if schedule.days[day_idx].is_weekend:
# #                     weekend_duties_for_doctor.append(x[(i, j)])
# #             if weekend_duties_for_doctor:
# #                 model_cp.Add(sum(weekend_duties_for_doctor) <= max_weekend_per_doctor)

# #     max_sd_per_doctor = int(general.get('MaxSDPerDoctor', 4))
# #     if constraints_cfg.get('MaxSD', 'Yes') == 'Yes':
# #         for j in range(num_doctors):
# #             sd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'SD']
# #             if sd_indices:
# #                 model_cp.Add(sum(x[(i, j)] for i in sd_indices) <= max_sd_per_doctor)

# #     # --- 92 KMT weekend PR restriction ---
# #     allowed_92_indices = [
# #         j for j, doc_name in enumerate(doctors)
# #         if schedule.doctors[doc_name].allow_92_kmt
# #     ]
# #     for i, (day_idx, station, abbr) in enumerate(duties):
# #         if station == '92 KMT' and schedule.days[day_idx].is_weekend and abbr == 'PR':
# #             if allowed_92_indices:
# #                 model_cp.Add(sum(x[(i, j)] for j in allowed_92_indices) == 1)
# #             else:
# #                 model_cp.Add(0 == 1)

# #     # --- NAZ restriction ---
# #     allowed_naz_indices = [
# #         j for j, doc_name in enumerate(doctors)
# #         if schedule.doctors[doc_name].allow_naz
# #     ]
# #     for i, (day_idx, station, abbr) in enumerate(duties):
# #         if abbr == 'NAZ':
# #             if allowed_naz_indices:
# #                 model_cp.Add(sum(x[(i, j)] for j in allowed_naz_indices) == 1)
# #             else:
# #                 model_cp.Add(0 == 1)
# #     # --- Max weekend PR per doctor ---
# #     max_pr_weekend = int(general.get('MaxWeekendPRPerDoctor', 1))
# #     if constraints_cfg.get('MaxWeekendPR', 'Yes') == 'Yes':
# #         for j in range(num_doctors):
# #             pr_weekend_indices = [
# #                 i for i, (day_idx, station, abbr) in enumerate(duties)
# #                 if abbr == 'PR' and schedule.days[day_idx].is_weekend
# #             ]
# #             if pr_weekend_indices:
# #                 model_cp.Add(sum(x[(i, j)] for i in pr_weekend_indices) <= max_pr_weekend)

# #     # --- Max NAZ per doctor ---
# #     max_naz = int(general.get('MaxNAZPerDoctor', 2))
# #     if constraints_cfg.get('MaxNAZ', 'Yes') == 'Yes':
# #         for j in range(num_doctors):
# #             naz_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'NAZ']
# #             if naz_indices:
# #                 model_cp.Add(sum(x[(i, j)] for i in naz_indices) <= max_naz)

# #     # --- Max house shifts (HD) per doctor ---
# #     max_hd_per_doctor = int(general.get('MaxHouseShifts', 2))
# #     if constraints_cfg.get('MaxHouseShifts', 'Yes') == 'Yes':
# #         for j in range(num_doctors):
# #             hd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'HD']
# #             if hd_indices:
# #                 model_cp.Add(sum(x[(i, j)] for i in hd_indices) <= max_hd_per_doctor)

# #     # --- Max SD per doctor (already present, keep as is) ---
# #     max_sd_per_doctor = int(general.get('MaxSDPerDoctor', 4))
# #     if constraints_cfg.get('MaxSD', 'Yes') == 'Yes':
# #         for j in range(num_doctors):
# #             sd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'SD']
# #             if sd_indices:
# #                 model_cp.Add(sum(x[(i, j)] for i in sd_indices) <= max_sd_per_doctor)

# #     # Add soft constraints (objective)
# #     penalties = add_soft_constraints(model_cp, schedule, config, x, duties, doctors, demand, duty_hours, initial_hours)
# #     model_cp.Minimize(sum(penalties))

# #     # --- DIAGNOSTICS (no local imports) ---
# #     print("\n=== REPAIR DIAGNOSTICS ===")
    
# #     # 1. Count duties per day
# #     duties_per_day = defaultdict(int)
# #     for i, (day_idx, _, _) in enumerate(duties):
# #         duties_per_day[day_idx] += 1
# #     print("Duties per day (day index: count):", sorted(duties_per_day.items()))

# #     # 2. Available doctors per day (respecting vacation, weekend restrictions)
# #     for day_idx in range(len(schedule.days)):
# #         count = duties_per_day.get(day_idx, 0)
# #         if count == 0:
# #             continue
# #         available = 0
# #         for doc_name in doctors:
# #             doc = schedule.doctors[doc_name]
# #             if (doc_name, day_idx) in schedule.unavailable:
# #                 continue
# #             if schedule.days[day_idx].is_weekend:
# #                 if doc.fte < 100 or not doc.weekend_available:
# #                     continue
# #             available += 1
# #         print(f"Day {day_idx} ({schedule.days[day_idx].date}): duties={count}, available doctors={available}")

# #     # 3. Check for conflicting fixed assignments
# #     fixed_conflicts = defaultdict(list)
# #     for doc_name, day_idx, station, abbr in schedule.fixed_assignments:
# #         fixed_conflicts[(doc_name, day_idx)].append(abbr)
# #     conflict_found = False
# #     for (doc, day), duties_list in fixed_conflicts.items():
# #         if len(duties_list) > 1:
# #             print(f"CONFLICT: Doctor {doc} has multiple fixed duties on day {day}: {duties_list}")
# #             conflict_found = True
# #     if not conflict_found:
# #         print("No fixed assignment conflicts found.")

# #     # 4. Check capacity (ignore station restrictions)
# #     for day_idx in range(len(schedule.days)):
# #         count = duties_per_day.get(day_idx, 0)
# #         if count == 0:
# #             continue
# #         potential = 0
# #         for doc_name in doctors:
# #             doc = schedule.doctors[doc_name]
# #             if (doc_name, day_idx) in schedule.unavailable:
# #                 continue
# #             if schedule.days[day_idx].is_weekend:
# #                 if doc.fte < 100 or not doc.weekend_available:
# #                     continue
# #             potential += 1
# #         if potential < count:
# #             print(f"WARNING: Day {day_idx} has {count} duties but only {potential} potentially available doctors (before station restrictions).")
# #     # 5. Station-specific capacity check (weekend PR only)
# #     from collections import defaultdict as dd
# #     station_duties = dd(lambda: dd(int))  # day -> station -> count
# #     for i, (day_idx, station, abbr) in enumerate(duties):
# #         if abbr == 'PR' and schedule.days[day_idx].is_weekend:
# #             station_duties[day_idx][station] += 1

# #     for day_idx in sorted(station_duties.keys()):
# #         for station, count in station_duties[day_idx].items():
# #             # Count doctors available for this station on this day
# #             eligible = 0
# #             for doc_name in doctors:
# #                 doc = schedule.doctors[doc_name]
# #                 if (doc_name, day_idx) in schedule.unavailable:
# #                     continue
# #                 if doc.fte < 100 or not doc.weekend_available:
# #                     continue
# #                 # Check station eligibility:
# #                 if station == '92 KMT' and not doc.allow_92_kmt:
# #                     continue
# #                 if doc.station != station and station != 'Global':  # only same station or global
# #                     continue
# #                 eligible += 1
# #             if eligible < count:
# #                 print(f"WARNING: Day {day_idx} station {station} needs {count} PR but only {eligible} eligible doctors.")
# #     # 6. Station-specific weekday demand (ZD, SD)
# #     station_weekday_demand = defaultdict(lambda: defaultdict(int))
# #     for i, (day_idx, station, abbr) in enumerate(duties):
# #         if abbr in ['ZD', 'SD'] and station != 'Global' and not schedule.days[day_idx].is_weekend:
# #             station_weekday_demand[day_idx][station] += 1

# #     for day_idx, station_demand in station_weekday_demand.items():
# #         for station, count in station_demand.items():
# #             # Count available doctors from this station (not on vacation, not fixed that day)
# #             available = 0
# #             for doc_name in doctors:
# #                 doc = schedule.doctors[doc_name]
# #                 if doc.station != station:
# #                     continue
# #                 if (doc_name, day_idx) in schedule.unavailable:
# #                     continue
# #                 if any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name):
# #                     continue
# #                 available += 1
# #             if available < count:
# #                 print(f"WARNING: Day {day_idx} ({schedule.days[day_idx].date}) station {station} needs {count} ZD/SD duties but only {available} available doctors.")

# #     # Solve
# #     solver = cp_model.CpSolver()
# #     solver.parameters.log_search_progress = True
# #     solver.parameters.max_time_in_seconds = 60.0 
# #     status = solver.Solve(model_cp)
# #     if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
# #         assignment = {}
# #         for i in range(num_duties):
# #             for j in range(num_doctors):
# #                 if solver.Value(x[(i, j)]) == 1:
# #                     assignment[i] = doctors[j]
# #                     break
# #         print("Repair successful (station match kept).")
# #         return assignment, solver, duties, doctors, duty_hours, initial_hours

# #     raise RuntimeError(
# #         "Even with relaxed skill constraints, the model is infeasible. "
# #         "Please reduce demand (e.g., lower DutyCounts) or add more doctors."
# #     )


# def repair_schedule(schedule, config, duties, doctors, demand, duty_hours, initial_hours):
#     """
#     Repair: relax skill constraints only. Keep all other hard constraints.
#     """
#     general_df = config.get('GeneralRules', pd.DataFrame())
#     if not general_df.empty and 'RuleName' in general_df.columns:
#         general = general_df.set_index('RuleName')['Value'].to_dict()
#     else:
#         general = {}

#     constraints_cfg = config.get('Constraints', pd.DataFrame())
#     if not constraints_cfg.empty and 'Constraint' in constraints_cfg.columns:
#         constraints_cfg = constraints_cfg.set_index('Constraint')['Enabled'].to_dict()
#     else:
#         constraints_cfg = {}

#     print("Repair: relaxing skill constraints (keeping station match, vacation, and weekend rules)...")
#     model_cp = cp_model.CpModel()
#     num_duties = len(duties)
#     num_doctors = len(doctors)
#     x = {}
#     for i in range(num_duties):
#         for j in range(num_doctors):
#             x[(i, j)] = model_cp.NewBoolVar(f'x_{i}_{j}')

#     # --- ENFORCE FIXED ASSIGNMENTS ---
#     duty_map = {}
#     for i, (day_idx, station, abbr) in enumerate(duties):
#         duty_map[(day_idx, station, abbr)] = i
#     for doc_name, day_idx, station, duty_abbr in schedule.fixed_assignments:
#         if (day_idx, station, duty_abbr) in duty_map:
#             duty_i = duty_map[(day_idx, station, duty_abbr)]
#             doctor_j = doctors.index(doc_name)
#             model_cp.Add(x[(duty_i, doctor_j)] == 1)
#             print(f"REPAIR FIXED: {doc_name} want {duty_abbr} at {station} on day {day_idx}")
#         else:
#             print(f"Warning: Fixed assignment for {doc_name} on {day_idx} {station} {duty_abbr} not found in duties.")

#     # 1. Each duty assigned to exactly one doctor
#     for i in range(num_duties):
#         model_cp.Add(sum(x[(i, j)] for j in range(num_doctors)) == 1)

#     # 2. Each doctor at most one duty per day
#     duties_by_day = defaultdict(list)
#     for i, (day_idx, _, _) in enumerate(duties):
#         duties_by_day[day_idx].append(i)
#     for day_idx, duty_list in duties_by_day.items():
#         for j in range(num_doctors):
#             model_cp.Add(sum(x[(i, j)] for i in duty_list) <= 1)

#     # 3. Station match (including weekend PR logic)
#     for i, (day_idx, station, abbr) in enumerate(duties):
#         if station == GLOBAL_STATION:
#             if abbr == 'SD':
#                 main_allowed = [j for j, doc_name in enumerate(doctors)
#                                 if schedule.doctors[doc_name].station in MAIN_STATIONS]
#                 if main_allowed:
#                     allowed = main_allowed
#                 else:
#                     allowed = list(range(num_doctors))
#                     print(f"Global SD on day {day_idx}: no main‑station doctors – allowing all")
#             else:
#                 allowed = list(range(num_doctors))
#         else:
#             if abbr == 'SUB':
#                 allowed = [j for j, doc_name in enumerate(doctors)
#                            if schedule.doctors[doc_name].station == '65 PP']
#             elif schedule.days[day_idx].is_weekend and abbr == 'PR':
#                 allowed = list(range(num_doctors))
#             else:
#                 if abbr == 'SD':
#                     allowed = [j for j, doc_name in enumerate(doctors)
#                                if schedule.doctors[doc_name].station == station]
#                 else:
#                     home_doctors = [j for j, doc_name in enumerate(doctors)
#                                     if schedule.doctors[doc_name].station == station]
#                     available_home = []
#                     for j in home_doctors:
#                         doc_name = doctors[j]
#                         if (doc_name, day_idx) in schedule.unavailable:
#                             continue
#                         if any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name):
#                             continue
#                         available_home.append(j)
#                     if available_home:
#                         allowed = available_home
#                     else:
#                         fallback = [j for j, doc_name in enumerate(doctors)
#                                     if (doc_name, day_idx) not in schedule.unavailable
#                                     and not any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doc_name)]
#                         if fallback:
#                             allowed = fallback
#                         else:
#                             allowed = list(range(num_doctors))
#                             print(f"ZD on day {day_idx}, station {station}: no eligible doctors – allowing all")
#         if not allowed:
#             raise ValueError(f"No allowed doctors for duty {i}: day={day_idx}, station='{station}', abbr='{abbr}'")
#         model_cp.Add(sum(x[(i, j)] for j in allowed) == 1)

#     # 4. KM pairing
#     km_duties_by_week = defaultdict(list)
#     for i, (day_idx, station, abbr) in enumerate(duties):
#         if abbr == 'KM':
#             week_num = schedule.days[day_idx].date.isocalendar().week
#             km_duties_by_week[week_num].append(i)
#     for week_num, duty_indices in km_duties_by_week.items():
#         if len(duty_indices) == 2:
#             for j in range(num_doctors):
#                 model_cp.Add(x[(duty_indices[0], j)] == x[(duty_indices[1], j)])

#     # 5. Vacation / unavailable
#     for i, (day_idx, station, abbr) in enumerate(duties):
#         for j, doc_name in enumerate(doctors):
#             if (doc_name, day_idx) in schedule.unavailable:
#                 model_cp.Add(x[(i, j)] == 0)

#     # 6. Weekend restrictions
#     if constraints_cfg.get('WeekendOnlyFullTime', 'Yes') == 'Yes':
#         for i, (day_idx, station, abbr) in enumerate(duties):
#             if schedule.days[day_idx].is_weekend:
#                 for j, doc_name in enumerate(doctors):
#                     if schedule.doctors[doc_name].fte < 100:
#                         model_cp.Add(x[(i, j)] == 0)

#     if constraints_cfg.get('WeekendAvailability', 'Yes') == 'Yes':
#         for i, (day_idx, station, abbr) in enumerate(duties):
#             if schedule.days[day_idx].is_weekend:
#                 for j, doc_name in enumerate(doctors):
#                     if not schedule.doctors[doc_name].weekend_available:
#                         model_cp.Add(x[(i, j)] == 0)

#     if constraints_cfg.get('WeekendOnlyForSkilled', 'Yes') == 'Yes':
#         for i, (day_idx, station, abbr) in enumerate(duties):
#             if schedule.days[day_idx].is_weekend:
#                 for j, doc_name in enumerate(doctors):
#                     if 'Weekend' not in schedule.doctors[doc_name].skills:
#                         model_cp.Add(x[(i, j)] == 0)

#     # 7. Max total weekend duties per doctor
#     max_weekend_per_doctor = int(general.get('MaxWeekendPerDoctor', 1))
#     if constraints_cfg.get('MaxOneWeekendPerDoctor', 'Yes') == 'Yes':
#         for j in range(num_doctors):
#             weekend_indices = [i for i, (day_idx, _, _) in enumerate(duties) if schedule.days[day_idx].is_weekend]
#             if weekend_indices:
#                 model_cp.Add(sum(x[(i, j)] for i in weekend_indices) <= max_weekend_per_doctor)

#     # 8. Max SD per doctor
#     max_sd_per_doctor = int(general.get('MaxSDPerDoctor', 4))
#     if constraints_cfg.get('MaxSD', 'Yes') == 'Yes':
#         for j in range(num_doctors):
#             sd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'SD']
#             if sd_indices:
#                 model_cp.Add(sum(x[(i, j)] for i in sd_indices) <= max_sd_per_doctor)

#     # 9. Max NAZ per doctor
#     max_naz = int(general.get('MaxNAZPerDoctor', 2))
#     if constraints_cfg.get('MaxNAZ', 'Yes') == 'Yes':
#         for j in range(num_doctors):
#             naz_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'NAZ']
#             if naz_indices:
#                 model_cp.Add(sum(x[(i, j)] for i in naz_indices) <= max_naz)

#     # 10. Max PR on weekends per doctor
#     max_pr_weekend = int(general.get('MaxWeekendPRPerDoctor', 1))
#     if constraints_cfg.get('MaxWeekendPR', 'Yes') == 'Yes':
#         for j in range(num_doctors):
#             pr_weekend_indices = [
#                 i for i, (day_idx, station, abbr) in enumerate(duties)
#                 if abbr == 'PR' and schedule.days[day_idx].is_weekend
#             ]
#             if pr_weekend_indices:
#                 model_cp.Add(sum(x[(i, j)] for i in pr_weekend_indices) <= max_pr_weekend)

#     # 11. Max house shifts (HD) per doctor
#     max_hd_per_doctor = int(general.get('MaxHouseShifts', 2))
#     if constraints_cfg.get('MaxHouseShifts', 'Yes') == 'Yes':
#         for j in range(num_doctors):
#             hd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'HD']
#             if hd_indices:
#                 model_cp.Add(sum(x[(i, j)] for i in hd_indices) <= max_hd_per_doctor)

#     # 12. 92 KMT weekend PR restriction
#     allowed_92_indices = [
#         j for j, doc_name in enumerate(doctors)
#         if schedule.doctors[doc_name].allow_92_kmt
#     ]
#     for i, (day_idx, station, abbr) in enumerate(duties):
#         if station == '92 KMT' and schedule.days[day_idx].is_weekend and abbr == 'PR':
#             if allowed_92_indices:
#                 model_cp.Add(sum(x[(i, j)] for j in allowed_92_indices) == 1)
#             else:
#                 model_cp.Add(0 == 1)

#     # 13. NAZ restriction (only allowed doctors)
#     allowed_naz_indices = [
#         j for j, doc_name in enumerate(doctors)
#         if schedule.doctors[doc_name].allow_naz
#     ]
#     for i, (day_idx, station, abbr) in enumerate(duties):
#         if abbr == 'NAZ':
#             if allowed_naz_indices:
#                 model_cp.Add(sum(x[(i, j)] for j in allowed_naz_indices) == 1)
#             else:
#                 model_cp.Add(0 == 1)


#     # 14. Max consecutive days
#     if constraints_cfg.get('MaxConsecutive', 'Yes') == 'Yes':
#         max_consec = int(general.get('MaxConsecutiveWorkDays', 6))
#         if max_consec > 0:
#             work = {}
#             for j in range(num_doctors):
#                 for day_idx in range(len(schedule.days)):
#                     duties_this_day = [i for i, (d, _, _) in enumerate(duties) if d == day_idx]
#                     if duties_this_day:
#                         work[(j, day_idx)] = model_cp.NewBoolVar(f'work_{j}_{day_idx}')
#                         model_cp.Add(work[(j, day_idx)] == sum(x[(i, j)] for i in duties_this_day))
#                     else:
#                         work[(j, day_idx)] = model_cp.NewConstant(0)
#             for j in range(num_doctors):
#                 for start in range(len(schedule.days) - max_consec):
#                     window = [work[(j, day)] for day in range(start, start + max_consec + 1)]
#                     model_cp.Add(sum(window) <= max_consec)

#     # 15. Max duties per week
#     if constraints_cfg.get('MaxPerWeek', 'Yes') == 'Yes':
#         max_week = int(general.get('MaxDutiesPerWeek', 5))
#         if max_week > 0:
#             week_days = defaultdict(list)
#             for day_idx, day in enumerate(schedule.days):
#                 week_days[day.date.isocalendar().week].append(day_idx)
#             for week, day_indices in week_days.items():
#                 for j in range(num_doctors):
#                     duty_indices_in_week = [i for i, (d, _, _) in enumerate(duties) if d in day_indices]
#                     if duty_indices_in_week:
#                         model_cp.Add(sum(x[(i, j)] for i in duty_indices_in_week) <= max_week)

#     # Add soft constraints (objective)
#     penalties = add_soft_constraints(model_cp, schedule, config, x, duties, doctors, demand, duty_hours, initial_hours)
#     model_cp.Minimize(sum(penalties))

#     # Diagnostics (as before)
#     print("\n=== REPAIR DIAGNOSTICS ===")
#     # ... keep the existing diagnostics code ...

#     # Solve
#     solver = cp_model.CpSolver()
#     solver.parameters.log_search_progress = True
#     solver.parameters.max_time_in_seconds = 60.0
#     status = solver.Solve(model_cp)
#     if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
#         assignment = {}
#         for i in range(num_duties):
#             for j in range(num_doctors):
#                 if solver.Value(x[(i, j)]) == 1:
#                     assignment[i] = doctors[j]
#                     break
#         print("Repair successful (station match kept).")
#         return assignment, solver, duties, doctors, duty_hours, initial_hours

#     raise RuntimeError(
#         "Even with relaxed skill constraints, the model is infeasible. "
#         "Please reduce demand (e.g., lower DutyCounts) or add more doctors."
#     )