# constraints.py
from ortools.sat.python import cp_model
from models import ScheduleModel
from demand_builder import build_demand, GLOBAL_STATION, MAIN_STATIONS
from collections import defaultdict
import pandas as pd
from typing import List, Dict, Tuple

def add_hard_constraints(
    model_cp: cp_model.CpModel,
    schedule: ScheduleModel,
    config: dict,
    x_vars: Dict[tuple, cp_model.IntVar],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    demand: dict
) -> None:
    constraints_cfg = config.get('Constraints', pd.DataFrame())
    if not constraints_cfg.empty and 'Constraint' in constraints_cfg.columns:
        constraints_cfg = constraints_cfg.set_index('Constraint')['Enabled'].to_dict()
    else:
        constraints_cfg = {}

    # Read GeneralRules with fallback
    general_df = config.get('GeneralRules', pd.DataFrame())
    if not general_df.empty and 'RuleName' in general_df.columns:
        general = general_df.set_index('RuleName')['Value'].to_dict()
    else:
        general = {}

    num_duties = len(duties)
    num_doctors = len(doctors)

    # 1. Each duty assigned to exactly one doctor
    for i in range(num_duties):
        model_cp.Add(sum(x_vars[(i, j)] for j in range(num_doctors)) == 1)

    # 2. Each doctor at most one duty per day
    duties_by_day = defaultdict(list)
    for i, (day_idx, _, _) in enumerate(duties):
        duties_by_day[day_idx].append(i)
    for day_idx, duty_list in duties_by_day.items():
        for j in range(num_doctors):
            model_cp.Add(sum(x_vars[(i, j)] for i in duty_list) <= 1)

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
        model_cp.Add(sum(x_vars[(i, j)] for j in allowed) == 1)

    # 3.2 Special rule for SUB duties: only doctors from 65 PP can cover
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'SUB':
            allowed = [j for j, doc_name in enumerate(doctors)
                       if schedule.doctors[doc_name].station == '65 PP']
            if not allowed:
                raise ValueError(f"No doctors from 65 PP available for SUB duty at {station} on day {day_idx}")
            model_cp.Add(sum(x_vars[(i, j)] for j in allowed) == 1)

    # 3.1 Special rule for KM duties: same doctor for Monday and Tuesday of the same week
    # Identify KM duties and group by week and station (though station is always 92 KMT)
    km_duties_by_week = defaultdict(list)
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'KM':
            week_num = schedule.days[day_idx].date.isocalendar().week
            km_duties_by_week[week_num].append(i)
    for week_num, duty_indices in km_duties_by_week.items():
        if len(duty_indices) == 2:  # Monday and Tuesday
            # They must have the same doctor
            # We can't directly enforce equality, but we can use a boolean variable per doctor
            # For each doctor j, require that both duties are assigned to the same doctor (or neither)
            # Actually, we can use a linear constraint: for each doctor, x_i_j == x_k_j
            for j in range(num_doctors):
                model_cp.Add(x_vars[(duty_indices[0], j)] == x_vars[(duty_indices[1], j)])

    # 4. Skills: doctor must have the duty in their skills
    for i, (day_idx, station, abbr) in enumerate(duties):
        for j, doc_name in enumerate(doctors):
            if abbr not in schedule.doctors[doc_name].skills:
                model_cp.Add(x_vars[(i, j)] == 0)

    # 5. Vacation / unavailable (hard)
    for i, (day_idx, station, abbr) in enumerate(duties):
        for j, doc_name in enumerate(doctors):
            if (doc_name, day_idx) in schedule.unavailable:
                model_cp.Add(x_vars[(i, j)] == 0)

    # 6. Senior requirement (duty or station requires senior)
    has_senior = any('Senior' in schedule.doctors[doc_name].skills for doc_name in doctors)
    if has_senior:
        for i, (day_idx, station, abbr) in enumerate(duties):
            duty = schedule.duty_types[abbr]
            station_obj = schedule.stations.get(station)
            requires_senior = duty.requires_senior or (station_obj and station_obj.requires_senior)
            if requires_senior:
                senior_doctors = [j for j, doc_name in enumerate(doctors) 
                                  if 'Senior' in schedule.doctors[doc_name].skills]
                if not senior_doctors:
                    raise ValueError(f"No senior doctors for duty {abbr} at {station}")
                model_cp.Add(sum(x_vars[(i, j)] for j in senior_doctors) == 1)

    # 7. Weekend only duties: only on weekends
    if constraints_cfg.get('WeekendOnly', 'Yes') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if schedule.duty_types[abbr].weekend_only and not schedule.days[day_idx].is_weekend:
                for j in range(num_doctors):
                    model_cp.Add(x_vars[(i, j)] == 0)
    # 7.5 Max weekend duties per doctor (hard constraint) 
    max_weekend_per_doctor = int(general.get('MaxWeekendPerDoctor', 1)) # in 'GeneralRules' sheet of Rules.xlsx
    if constraints_cfg.get('MaxOneWeekendPerDoctor', 'Yes') == 'Yes':
        for j in range(num_doctors):
            weekend_duties_for_doctor = []
            for i, (day_idx, station, abbr) in enumerate(duties):
                if schedule.days[day_idx].is_weekend:
                    weekend_duties_for_doctor.append(x_vars[(i, j)])
            if weekend_duties_for_doctor:
                model_cp.Add(sum(weekend_duties_for_doctor) <= max_weekend_per_doctor)

    # 8. Weekend shifts only for 100% FTE doctors
    if constraints_cfg.get('WeekendOnlyFullTime', 'Yes') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if schedule.days[day_idx].is_weekend:
                for j, doc_name in enumerate(doctors):
                    if schedule.doctors[doc_name].fte < 100:
                        model_cp.Add(x_vars[(i, j)] == 0) 

    # 9. Weekend availability per doctor (from Weekend column)
    if constraints_cfg.get('WeekendAvailability', 'Yes') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if schedule.days[day_idx].is_weekend:
                for j, doc_name in enumerate(doctors):
                    if not schedule.doctors[doc_name].weekend_available:
                        model_cp.Add(x_vars[(i, j)] == 0)

    # # 10. Only doctors with 'Weekend' skill can work on weekends
    # if constraints_cfg.get('WeekendOnlyForSkilled', 'Yes') == 'Yes':
    #     for i, (day_idx, station, abbr) in enumerate(duties):
    #         if schedule.days[day_idx].is_weekend:
    #             for j, doc_name in enumerate(doctors):
    #                 if 'Weekend' not in schedule.doctors[doc_name].skills:
    #                     model_cp.Add(x_vars[(i, j)] == 0)

    # 10. Only doctors who are available on weekends (Weekend column = Yes) can work on weekends
    if constraints_cfg.get('WeekendOnlyForSkilled', 'Yes') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if schedule.days[day_idx].is_weekend:
                for j, doc_name in enumerate(doctors):
                    if not schedule.doctors[doc_name].weekend_available:
                        model_cp.Add(x_vars[(i, j)] == 0)

    # 11. Max consecutive days
    if constraints_cfg.get('MaxConsecutive', 'Yes') == 'Yes':
        max_consec = int(general.get('MaxConsecutiveWorkDays', 6))
        if max_consec > 0:
            work = {}
            for j in range(num_doctors):
                for day_idx in range(len(schedule.days)):
                    duties_this_day = [i for i, (d, _, _) in enumerate(duties) if d == day_idx]
                    if duties_this_day:
                        work[(j, day_idx)] = model_cp.NewBoolVar(f'work_{j}_{day_idx}')
                        model_cp.Add(work[(j, day_idx)] == sum(x_vars[(i, j)] for i in duties_this_day))
                    else:
                        work[(j, day_idx)] = model_cp.NewConstant(0)
            for j in range(num_doctors):
                for start in range(len(schedule.days) - max_consec):
                    window = [work[(j, day)] for day in range(start, start + max_consec + 1)]
                    model_cp.Add(sum(window) <= max_consec)

    # 12. Max duties per week
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
                        model_cp.Add(sum(x_vars[(i, j)] for i in duty_indices_in_week) <= max_week)

    # 13. Special: Weekend PR at 92 KMT only for doctors with allow_92_kmt=True ---
    allowed_92_indices = [
        j for j, doc_name in enumerate(doctors)
        if schedule.doctors[doc_name].allow_92_kmt
    ]
    for i, (day_idx, station, abbr) in enumerate(duties):
        if station == '92 KMT' and schedule.days[day_idx].is_weekend and abbr == 'PR':
            if allowed_92_indices:
                model_cp.Add(sum(x_vars[(i, j)] for j in allowed_92_indices) == 1)
            else:
                # No allowed doctors – force infeasible if such duty exists
                model_cp.Add(0 == 1)

    # 14. NAZ shifts: only doctors with allow_naz=True ---
    allowed_naz_indices = [
        j for j, doc_name in enumerate(doctors)
        if schedule.doctors[doc_name].allow_naz
    ]
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'NAZ':
            if allowed_naz_indices:
                model_cp.Add(sum(x_vars[(i, j)] for j in allowed_naz_indices) == 1)
            else:
                model_cp.Add(0 == 1)
    # --- 15. Max house shifts (HD) per doctor ---
    max_pr_weekend = int(general.get('MaxWeekendPRPerDoctor', 1))
    max_naz = int(general.get('MaxNAZPerDoctor', 2))

    # For PR on weekends:
    if constraints_cfg.get('MaxWeekendPR', 'Yes') == 'Yes':
        for j in range(num_doctors):
            pr_weekend_indices = [
                i for i, (day_idx, station, abbr) in enumerate(duties)
                if abbr == 'PR' and schedule.days[day_idx].is_weekend
            ]
            if pr_weekend_indices:
                model_cp.Add(sum(x_vars[(i, j)] for i in pr_weekend_indices) <= max_pr_weekend)

    # For NAZ:
    if constraints_cfg.get('MaxNAZ', 'Yes') == 'Yes':
        for j in range(num_doctors):
            naz_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'NAZ']
            if naz_indices:
                model_cp.Add(sum(x_vars[(i, j)] for i in naz_indices) <= max_naz)


    # --- 16. Max house shifts (HD) per doctor ---
    max_hd_per_doctor = int(general.get('MaxHouseShifts', 2))
    if constraints_cfg.get('MaxHouseShifts', 'Yes') == 'Yes':
        for j in range(num_doctors):
            hd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'HD']
            if hd_indices:
                model_cp.Add(sum(x_vars[(i, j)] for i in hd_indices) <= max_hd_per_doctor)

    # --- 17. Max SD per doctor (to avoid concentration) ---
    max_sd_per_doctor = int(general.get('MaxSDPerDoctor', 4))   # default 4
    if constraints_cfg.get('MaxSD', 'Yes') == 'Yes':
        for j in range(num_doctors):
            sd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'SD']
            if sd_indices:
                model_cp.Add(sum(x_vars[(i, j)] for i in sd_indices) <= max_sd_per_doctor)
    # 18. No weekend duty if bridge day
    if constraints_cfg.get('BridgeDay', 'No') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if not schedule.days[day_idx].is_weekend:
                continue
            weekday = schedule.days[day_idx].date.weekday()
            for j, doc_name in enumerate(doctors):
                if weekday == 5 and (doc_name, day_idx - 1) in schedule.unavailable:
                    model_cp.Add(x_vars[(i, j)] == 0)
                elif weekday == 6 and (doc_name, day_idx + 1) in schedule.unavailable:
                    model_cp.Add(x_vars[(i, j)] == 0)