# objective.py

from ortools.sat.python import cp_model
from models import ScheduleModel
import pandas as pd
from collections import defaultdict

from typing import List, Tuple, Dict

def add_soft_constraints(
    model_cp: cp_model.CpModel,
    schedule: ScheduleModel,
    config: dict,
    x_vars: Dict[tuple, cp_model.IntVar],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    demand: dict,
    duty_hours: List[float], 
    initial_hours: Dict[str, float] 
) -> List[cp_model.IntVar]:
    penalties = []
    penalties_cfg = config.get('Penalties', pd.DataFrame()).set_index('Penalty')['Weight'].to_dict()
    num_duties = len(duties)
    num_doctors = len(doctors)

    # 1. Preference satisfaction
    pref_weight = int(penalties_cfg.get('Preference', 10))
    if pref_weight != 0:
        for doc in schedule.doctors.values():
            for (day_idx, duty_abbr, priority) in doc.preferences:
                duty_indices = [i for i, (d, st, abbr) in enumerate(duties) if d == day_idx and abbr == duty_abbr]
                if not duty_indices:
                    continue
                j = doctors.index(doc.name)
                for i in duty_indices:
                    if priority > 0:
                        penalty = model_cp.NewIntVar(0, 1, f'pref_pos_{doc.name}_{i}')
                        model_cp.Add(penalty == 1 - x_vars[(i, j)])
                    else:
                        penalty = model_cp.NewIntVar(0, 1, f'pref_neg_{doc.name}_{i}')
                        model_cp.Add(penalty == x_vars[(i, j)])
                    penalties.append(pref_weight * abs(priority) * penalty)

    # 2. Day‑off soft penalty
    day_off_weight = int(penalties_cfg.get('DayOffPenalty', 50))
    if day_off_weight != 0 and hasattr(schedule, 'soft_unavailable'):
        for doc_name, day_idx in schedule.soft_unavailable:
            if doc_name not in doctors:
                continue
            j = doctors.index(doc_name)
            duty_indices = [i for i, (d, _, _) in enumerate(duties) if d == day_idx]
            if not duty_indices:
                continue
            for i in duty_indices:
                penalties.append(day_off_weight * x_vars[(i, j)])

    # 3. Workload balance (hours‑based)
    balance_weight = int(penalties_cfg.get('WorkloadBalance', 100))
    if balance_weight != 0:
        total_initial_hours = sum(initial_hours.values())
        total_month_hours = sum(duty_hours)
        total_fte = sum(doc.fte for doc in schedule.doctors.values()) / 100.0
        SCALE = 10
        for j, doc_name in enumerate(doctors):
            doc = schedule.doctors[doc_name]
            target_final = (total_initial_hours + total_month_hours) * (doc.fte / 100) / total_fte if total_fte > 0 else 0
            target_this_month = target_final - initial_hours.get(doc_name, 0.0)
            target_scaled = int(target_this_month * SCALE)
            assigned_scaled = model_cp.NewIntVar(0, int(total_month_hours * SCALE), f'assigned_scaled_{j}')
            model_cp.Add(assigned_scaled == sum(int(duty_hours[i] * SCALE) * x_vars[(i, j)] for i in range(num_duties)))
            pos_dev = model_cp.NewIntVar(0, int(total_month_hours * SCALE), f'hpos_{j}')
            neg_dev = model_cp.NewIntVar(0, int(total_month_hours * SCALE), f'hneg_{j}')
            model_cp.Add(assigned_scaled - target_scaled == pos_dev - neg_dev)
            penalties.append(balance_weight * pos_dev)
            penalties.append(balance_weight * neg_dev)
    
    # 4. Weekend balance (equal distribution)
    weekend_weight = int(penalties_cfg.get('WeekendBalance', 15))
    if weekend_weight != 0:
        weekend_days = [idx for idx, day in enumerate(schedule.days) if day.is_weekend]
        weekend_duty_indices = [i for i, (d, _, _) in enumerate(duties) if d in weekend_days]
        if weekend_duty_indices:
            avg_weekend = len(weekend_duty_indices) / num_doctors if num_doctors > 0 else 0
            for j in range(num_doctors):
                weekend_assigned = model_cp.NewIntVar(0, len(weekend_duty_indices), f'weekend_{j}')
                model_cp.Add(weekend_assigned == sum(x_vars[(i, j)] for i in weekend_duty_indices))
                pos_dev = model_cp.NewIntVar(0, len(weekend_duty_indices), f'wpos_{j}')
                neg_dev = model_cp.NewIntVar(0, len(weekend_duty_indices), f'wneg_{j}')
                model_cp.Add(weekend_assigned - int(avg_weekend) == pos_dev - neg_dev)
                penalties.append(weekend_weight * pos_dev)
                penalties.append(weekend_weight * neg_dev)

    # 5. Weekend pairing and home‑station bonus for PR
    weekend_pairing_reward = int(penalties_cfg.get('WeekendPairingReward', 30))
    weekend_single_penalty = int(penalties_cfg.get('WeekendSinglePenalty', 20))
    weekend_home_bonus = int(penalties_cfg.get('WeekendHomeStationBonus', 10))

    weekend_pr_groups = defaultdict(list)
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'PR' and schedule.days[day_idx].is_weekend:
            week_num = schedule.days[day_idx].date.isocalendar().week
            weekend_pr_groups[(week_num, station)].append(i)

    for (week_num, station), duty_indices in weekend_pr_groups.items():
        if len(duty_indices) >= 2:
            duty_indices_sorted = sorted(duty_indices, key=lambda i: duties[i][0])
            sat_idx = duty_indices_sorted[0]
            sun_idx = duty_indices_sorted[1] if len(duty_indices_sorted) > 1 else None
            if sun_idx is None:
                continue
            for j in range(num_doctors):
                both = model_cp.NewBoolVar(f'both_{week_num}_{station}_{j}')
                model_cp.Add(both <= x_vars[(sat_idx, j)])
                model_cp.Add(both <= x_vars[(sun_idx, j)])
                model_cp.Add(both >= x_vars[(sat_idx, j)] + x_vars[(sun_idx, j)] - 1)

                single = model_cp.NewBoolVar(f'single_{week_num}_{station}_{j}')
                model_cp.Add(single <= x_vars[(sat_idx, j)] + x_vars[(sun_idx, j)])
                model_cp.Add(single >= x_vars[(sat_idx, j)] - x_vars[(sun_idx, j)])
                model_cp.Add(single >= x_vars[(sun_idx, j)] - x_vars[(sat_idx, j)])

                penalties.append(-weekend_pairing_reward * both)
                penalties.append(weekend_single_penalty * single)

                doc = schedule.doctors[doctors[j]]
                if doc.station == station:
                    penalties.append(-weekend_home_bonus * x_vars[(sat_idx, j)])
                    penalties.append(-weekend_home_bonus * x_vars[(sun_idx, j)])

    # 6. Balance KM duties
    km_weight = int(penalties_cfg.get('KMBalance', 30))
    if km_weight != 0:
        km_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'KM']
        if km_indices:
            avg_km = len(km_indices) / num_doctors if num_doctors > 0 else 0
            for j in range(num_doctors):
                km_assigned = model_cp.NewIntVar(0, len(km_indices), f'km_{j}')
                model_cp.Add(km_assigned == sum(x_vars[(i, j)] for i in km_indices))
                pos_dev = model_cp.NewIntVar(0, len(km_indices), f'km_pos_{j}')
                neg_dev = model_cp.NewIntVar(0, len(km_indices), f'km_neg_{j}')
                model_cp.Add(km_assigned - int(avg_km) == pos_dev - neg_dev)
                penalties.append(km_weight * pos_dev)
                penalties.append(km_weight * neg_dev)

    # 7. Cross‑station penalty for ZD/SD/HD/NAZ (encourage same‑station coverage)
    cross_weight = int(penalties_cfg.get('CrossStation', 30))
    if cross_weight != 0:
        for i, (day_idx, station, abbr) in enumerate(duties):
            if abbr in ['ZD', 'SD', 'HD', 'NAZ'] and station != 'Global':
                for j, doc_name in enumerate(doctors):
                    if schedule.doctors[doc_name].station != station:
                        penalties.append(cross_weight * x_vars[(i, j)])

    # 8. SD balance
    sd_weight = int(penalties_cfg.get('SDBalance', 20))
    if sd_weight != 0:
        sd_indices = [i for i, (_, _, abbr) in enumerate(duties) if abbr == 'SD']
        if sd_indices:
            avg_sd = len(sd_indices) / num_doctors if num_doctors > 0 else 0
            for j in range(num_doctors):
                sd_assigned = model_cp.NewIntVar(0, len(sd_indices), f'sd_{j}')
                model_cp.Add(sd_assigned == sum(x_vars[(i, j)] for i in sd_indices))
                pos_dev = model_cp.NewIntVar(0, len(sd_indices), f'sd_pos_{j}')
                neg_dev = model_cp.NewIntVar(0, len(sd_indices), f'sd_neg_{j}')
                model_cp.Add(sd_assigned - int(avg_sd) == pos_dev - neg_dev)
                penalties.append(sd_weight * pos_dev)
                penalties.append(sd_weight * neg_dev)

    # 9. Consecutive ZD reward
    zd_consecutive_reward = int(penalties_cfg.get('ZDConsecutiveReward', 50))
    zd_duty_map = {}
    for i, (day_idx, station, abbr) in enumerate(duties):
        if abbr == 'ZD':
            zd_duty_map[(day_idx, station)] = i

    for (day_idx, station), i in zd_duty_map.items():
        if day_idx > 0:
            prev_i = zd_duty_map.get((day_idx-1, station))
            if prev_i is not None:
                for j in range(num_doctors):
                    consecutive = model_cp.NewBoolVar(f'consec_zd_{i}_{j}')
                    model_cp.Add(consecutive <= x_vars[(i, j)])
                    model_cp.Add(consecutive <= x_vars[(prev_i, j)])
                    model_cp.Add(consecutive >= x_vars[(i, j)] + x_vars[(prev_i, j)] - 1)
                    penalties.append(-zd_consecutive_reward * consecutive)

    # 10. Penalize weekend duties if doctor is on vacation on adjacent Friday or Monday
    adjacent_weekend_weight = int(penalties_cfg.get('BridgeDay', 0))
    if adjacent_weekend_weight != 0:
        for i, (day_idx, station, abbr) in enumerate(duties):
            if not schedule.days[day_idx].is_weekend:
                continue
            weekday = schedule.days[day_idx].date.weekday()  # Monday=0, Sunday=6
            for j, doc_name in enumerate(doctors):
                # Check if doctor has vacation on adjacent day
                vacation_adjacent = False
                if weekday == 5:  # Saturday -> check Friday (day_idx-1)
                    if day_idx > 0 and (doc_name, day_idx - 1) in schedule.unavailable:
                        vacation_adjacent = True
                elif weekday == 6:  # Sunday -> check Monday (day_idx+1)
                    if day_idx < len(schedule.days) - 1 and (doc_name, day_idx + 1) in schedule.unavailable:
                        vacation_adjacent = True
                if vacation_adjacent:
                    penalties.append(adjacent_weekend_weight * x_vars[(i, j)])

    return penalties