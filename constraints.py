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
    duty_map = { (day_idx, station, abbr): i for i, (day_idx, station, abbr) in enumerate(duties) }
    fixed_duty_indices = set()
    for doc_name, day_idx, station, duty_abbr in schedule.fixed_assignments:
        key = (day_idx, station, duty_abbr)
        if key in duty_map:
            fixed_duty_indices.add(duty_map[key])
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

    # # 3. Station match
    # for i, (day_idx, station, abbr) in enumerate(duties):
    #     if i in fixed_duty_indices: continue
    #     if station == GLOBAL_STATION and abbr == 'SD':
    #         # 收集当天可用的主站医生
    #         main_available = []
    #         for j, doc_name in enumerate(doctors):
    #             if schedule.doctors[doc_name].station in MAIN_STATIONS:
    #                 if (doc_name, day_idx) not in schedule.unavailable:
    #                     # 如果当天已有固定任务，求解器会在后续约束中处理，但这里我们只排除 unavailable
    #                     main_available.append(j)
    #         if main_available:
    #             allowed = main_available
    #         else:
    #             allowed = list(range(num_doctors))
    #             print(f"Global SD on day {day_idx}: no available main‑station doctors – allowing all")
    # 3. Station match
    for i, (day_idx, station, abbr) in enumerate(duties):
        if i in fixed_duty_indices: continue
        if station == GLOBAL_STATION and abbr in ['SD', 'HD', 'NAZ']:
            # 主站优先
            main_candidates = []
            for j, doc_name in enumerate(doctors):
                if schedule.doctors[doc_name].station not in MAIN_STATIONS:
                    continue
                if (doc_name, day_idx) in schedule.unavailable:
                    continue
                if abbr == 'NAZ' and not schedule.doctors[doc_name].allow_naz:
                    continue
                main_candidates.append(j)
            if main_candidates:
                allowed = main_candidates
            else:
                # fallback: 所有符合条件的医生
                fallback = []
                for j, doc_name in enumerate(doctors):
                    if (doc_name, day_idx) in schedule.unavailable:
                        continue
                    if abbr == 'NAZ' and not schedule.doctors[doc_name].allow_naz:
                        continue
                    fallback.append(j)
                if fallback:
                    allowed = fallback
                else:
                    allowed = list(range(num_doctors))
                print(f"Global {abbr} on day {day_idx}: no available main‑station doctors – allowing all")
            model_cp.Add(sum(x_vars[(i, j)] for j in allowed) == 1)
        else:
            if abbr == 'SUB':
                allowed = [j for j, doc_name in enumerate(doctors) 
                        if schedule.doctors[doc_name].station == '65 PP']
            elif schedule.days[day_idx].is_weekend and abbr == 'PR':

                allowed = get_weekend_duty_allowed(day_idx, station, abbr, doctors, schedule, num_doctors)
                model_cp.Add(sum(x_vars[(i, j)] for j in allowed) == 1)
                # # allowed = get_allowed_doctors_for_weekend_pr(day_idx, station, doctors, schedule)
                # # # Ensure allowed is not empty (fallback to all)
                # # if not allowed:
                # #     allowed = list(range(num_doctors))

                # # In constraint building:
                # main_doctors = [j for j in range(num_doctors) if schedule.doctors[doctors[j]].category == 'main'
                #                 and (doctors[j], day_idx) not in schedule.unavailable
                #                 and not any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doctors[j])]
                # if main_doctors:
                #     allowed = main_doctors
                # else:
                #     jumper_doctors = [j for j in range(num_doctors) if schedule.doctors[doctors[j]].category == 'jumper'
                #                     and (doctors[j], day_idx) not in schedule.unavailable
                #                     and not any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doctors[j])]
                #     if jumper_doctors:
                #         allowed = jumper_doctors
                #     else:
                #         # fallback to any doctor
                #         allowed = [j for j in range(num_doctors) if (doctors[j], day_idx) not in schedule.unavailable
                #                 and not any(d == day_idx for _, d, _, _ in schedule.fixed_assignments if _ == doctors[j])]
                #         if not allowed:
                #             allowed = list(range(num_doctors))

                # model_cp.Add(sum(x_vars[(i, j)] for j in allowed) == 1)
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
        if i in fixed_duty_indices: continue
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
        if i in fixed_duty_indices: continue
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
        if i in fixed_duty_indices: continue
        for j, doc_name in enumerate(doctors):
            if abbr not in schedule.doctors[doc_name].skills:
                model_cp.Add(x_vars[(i, j)] == 0)

    # 5. Vacation / unavailable (hard)
    for i, (day_idx, station, abbr) in enumerate(duties):
        if i in fixed_duty_indices: continue
        for j, doc_name in enumerate(doctors):
            if (doc_name, day_idx) in schedule.unavailable:
                model_cp.Add(x_vars[(i, j)] == 0)

    # 6. Senior requirement (duty or station requires senior)
    has_senior = any('Senior' in schedule.doctors[doc_name].skills for doc_name in doctors)
    if has_senior:
        for i, (day_idx, station, abbr) in enumerate(duties):
            if i in fixed_duty_indices: continue
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
            if i in fixed_duty_indices: continue
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
            if i in fixed_duty_indices: continue
            if schedule.days[day_idx].is_weekend:
                for j, doc_name in enumerate(doctors):
                    if schedule.doctors[doc_name].fte < 100:
                        model_cp.Add(x_vars[(i, j)] == 0) 

    # 9. Weekend availability per doctor (from Weekend column)
    if constraints_cfg.get('WeekendAvailability', 'Yes') == 'Yes':
        for i, (day_idx, station, abbr) in enumerate(duties):
            if i in fixed_duty_indices: continue
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
            if i in fixed_duty_indices: continue
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

    # # 13. Special: Weekend PR at 92 KMT only for doctors with allow_92_kmt=True ---
    # allowed_92_indices = [
    #     j for j, doc_name in enumerate(doctors)
    #     if schedule.doctors[doc_name].allow_92_kmt
    # ]
    # for i, (day_idx, station, abbr) in enumerate(duties):
    #     if i in fixed_duty_indices: continue
    #     if station == '92 KMT' and schedule.days[day_idx].is_weekend and abbr == 'PR':
    #         if allowed_92_indices:
    #             model_cp.Add(sum(x_vars[(i, j)] for j in allowed_92_indices) == 1)
    #         else:
    #             # No allowed doctors – force infeasible if such duty exists
    #             model_cp.Add(0 == 1)

    # 14. NAZ shifts: only doctors with allow_naz=True ---
    allowed_naz_indices = [
        j for j, doc_name in enumerate(doctors)
        if schedule.doctors[doc_name].allow_naz
    ]
    for i, (day_idx, station, abbr) in enumerate(duties):
        if i in fixed_duty_indices: continue
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
            if i in fixed_duty_indices: continue
            if not schedule.days[day_idx].is_weekend:
                continue
            weekday = schedule.days[day_idx].date.weekday()
            for j, doc_name in enumerate(doctors):
                if weekday == 5 and (doc_name, day_idx - 1) in schedule.unavailable:
                    model_cp.Add(x_vars[(i, j)] == 0)
                elif weekday == 6 and (doc_name, day_idx + 1) in schedule.unavailable:
                    model_cp.Add(x_vars[(i, j)] == 0)

    # 19. Main station doctors: max weekend duty cap (reads from GeneralRules)
    # Fixed assignments (wishes) are excluded from this cap.
    if constraints_cfg.get('MainDoctorMaxOneWeekend', 'Yes') == 'Yes':
        max_main_weekend = int(general.get('MainDoctorMaxWeekend', 1))
        for j, doc_name in enumerate(doctors):
            if schedule.doctors[doc_name].category == 'main':
                # Only count weekend duties that are NOT fixed assignments
                weekend_indices = [
                    i for i, (day_idx, _, _) in enumerate(duties)
                    if schedule.days[day_idx].is_weekend and i not in fixed_duty_indices
                ]
                if weekend_indices:
                    model_cp.Add(sum(x_vars[(i, j)] for i in weekend_indices) <= max_main_weekend)
    # 20. Limited doctors can only take their fixed duties
    limited_doctors = [j for j, doc_name in enumerate(doctors) if getattr(schedule.doctors[doc_name], '_limited_to_fixed', False)]
    for j in limited_doctors:
        # They can only be assigned to duties that are fixed for them
        # We need to identify which duties are fixed for this doctor
        fixed_duties_for_this_doctor = []
        for doc_name, day_idx, station, abbr in schedule.fixed_assignments:
            if doc_name == doctors[j]:
                # Get the duty index
                key = (day_idx, station, abbr)
                if key in duty_map:
                    fixed_duties_for_this_doctor.append(duty_map[key])
        # Allow only those duties
        for i in range(num_duties):
            if i not in fixed_duties_for_this_doctor:
                model_cp.Add(x_vars[(i, j)] == 0)
def get_allowed_doctors_for_weekend_pr(day_idx, station, doctors, schedule):
    """
    Return list of doctor indices in priority order:
    1. main station doctors (from station itself, and any main station)
    2. jumper doctors
    3. all other doctors (except those unavailable)
    """
    num_doctors = len(doctors)
    # Prepare availability masks
    unavailable = set()
    fixed_today = set()
    for doc_name, d, _, _ in schedule.fixed_assignments:
        if d == day_idx:
            fixed_today.add(doc_name)
    for doc_name, d in schedule.unavailable:
        if d == day_idx:
            unavailable.add(doc_name)

    # 1. Main station doctors (any main station, but prefer same station first)
    main_indices = []
    same_station_main = []
    for j, doc_name in enumerate(doctors):
        if doc_name in unavailable or doc_name in fixed_today:
            continue
        if schedule.doctors[doc_name].category == 'main':
            if schedule.doctors[doc_name].station == station:
                same_station_main.append(j)
            else:
                main_indices.append(j)
    # Put same station first, then other main stations
    main_ordered = same_station_main + [j for j in main_indices if j not in same_station_main]

    # 2. Jumper doctors
    jumper_indices = [j for j, doc_name in enumerate(doctors) if schedule.doctors[doc_name].category == 'jumper'
                      and doc_name not in unavailable and doc_name not in fixed_today]

    # 3. Other doctors (excluding main and jumper)
    other_indices = [j for j, doc_name in enumerate(doctors) if schedule.doctors[doc_name].category not in ('main', 'jumper')
                     and doc_name not in unavailable and doc_name not in fixed_today]

    # Combine
    allowed = main_ordered + jumper_indices + other_indices
    # Additionally, we must ensure that if no main are available, we still allow others.
    # But we also need to enforce that if main exist, we only allow them? That would be too strict.
    # We'll use a soft constraint later, but here we allow all but prioritize.
    # For hard constraint, we only enforce that the doctor must be from one of these.
    # The priority will be handled in the objective.
    # So we return the full list.
    return allowed

# def get_weekend_duty_allowed(day_idx, station, abbr, doctors, schedule, num_doctors):
#     # Build set of unavailable and fixed today
#     unavailable = set()
#     fixed_today = set()
#     for doc_name, d, _, _ in schedule.fixed_assignments:
#         if d == day_idx:
#             fixed_today.add(doc_name)
#     for doc_name, d in schedule.unavailable:
#         if d == day_idx:
#             unavailable.add(doc_name)

#     # Step 1: main doctors from the same station
#     same_main = [j for j, doc_name in enumerate(doctors)
#                  if schedule.doctors[doc_name].category == 'main'
#                  and schedule.doctors[doc_name].station == station
#                  and doc_name not in unavailable
#                  and doc_name not in fixed_today]
#     if same_main:
#         return same_main

#     # Step 2: main doctors from any main station
#     any_main = [j for j, doc_name in enumerate(doctors)
#                 if schedule.doctors[doc_name].category == 'main'
#                 and doc_name not in unavailable
#                 and doc_name not in fixed_today]
#     if any_main:
#         return any_main

#     # Step 3: jumper doctors
#     jumpers = [j for j, doc_name in enumerate(doctors)
#                if schedule.doctors[doc_name].category == 'jumper'
#                and doc_name not in unavailable
#                and doc_name not in fixed_today]
#     if jumpers:
#         return jumpers

#     # Step 4: any other available doctor
#     others = [j for j, doc_name in enumerate(doctors)
#               if doc_name not in unavailable
#               and doc_name not in fixed_today]
#     if others:
#         return others

#     # Ultimate fallback: all (might include unavailable/fixed, but those will be blocked later)
#     return list(range(num_doctors))

def get_weekend_duty_allowed(day_idx, station, abbr, doctors, schedule, num_doctors):
    # Build set of unavailable and fixed today
    unavailable = set()
    fixed_today = set()
    for doc_name, d, _, _ in schedule.fixed_assignments:
        if d == day_idx:
            fixed_today.add(doc_name)
    for doc_name, d in schedule.unavailable:
        if d == day_idx:
            unavailable.add(doc_name)

    # All doctors except unavailable and fixed (they will be blocked later)
    allowed = [j for j, doc_name in enumerate(doctors)
               if doc_name not in unavailable and doc_name not in fixed_today]
    # If none available, allow all (fallback)
    if not allowed:
        allowed = list(range(num_doctors))
    return allowed