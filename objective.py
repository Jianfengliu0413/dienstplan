# objective.py
"""soft constraints with penalties"""

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
                # Find duty indices for that day and type
                duty_indices = [i for i, (d, st, abbr) in enumerate(duties) if d == day_idx and abbr == duty_abbr]
                if not duty_indices:
                    continue
                j = doctors.index(doc.name)
                for i in duty_indices:
                    # If priority > 0: we want x=1, else we want x=0
                    if priority > 0:
                        # Penalty if not assigned (1 - x)
                        penalty = model_cp.NewIntVar(0, 1, f'pref_pos_{doc.name}_{i}')
                        model_cp.Add(penalty == 1 - x_vars[(i, j)])
                    else:
                        # Penalty if assigned (x)
                        penalty = model_cp.NewIntVar(0, 1, f'pref_neg_{doc.name}_{i}')
                        model_cp.Add(penalty == x_vars[(i, j)])
                    penalties.append(pref_weight * abs(priority) * penalty)

    # After preference and before other constraints
    day_off_weight = int(penalties_cfg.get('DayOffPenalty', 50))
    if day_off_weight != 0 and hasattr(schedule, 'soft_unavailable'):
        for doc_name, day_idx in schedule.soft_unavailable:
            if doc_name not in doctors:
                continue
            j = doctors.index(doc_name)
            # Find all duties on that day
            duty_indices = [i for i, (d, _, _) in enumerate(duties) if d == day_idx]
            if not duty_indices:
                continue
            # Penalty if assigned any duty that day: sum over duty_indices of x_vars
            # Create a boolean that is 1 if any assigned
            assigned = model_cp.NewIntVar(0, 1, f'dayoff_{doc_name}_{day_idx}')
            # assigned == 1 if sum(x) > 0
            model_cp.Add(assigned <= sum(x_vars[(i, j)] for i in duty_indices))
            # Actually, we want assigned == 1 if sum > 0, but we can use a linear constraint with a big M? Simpler: use a penalty per duty assigned.
            # We can just add penalty for each duty assignment:
            for i in duty_indices:
                penalties.append(day_off_weight * x_vars[(i, j)])

    # # 2. Workload balance (based on FTE)
    # balance_weight = int(penalties_cfg.get('WorkloadBalance', 20))
    # if balance_weight != 0:
    #     total_duties = num_duties
    #     total_fte = sum(doc.fte for doc in schedule.doctors.values())
    #     for j, doc_name in enumerate(doctors):
    #         doc = schedule.doctors[doc_name]
    #         target = (doc.fte / 100) * (total_duties / total_fte) if total_fte > 0 else 0
    #         assigned = model_cp.NewIntVar(0, total_duties, f'assigned_{j}')
    #         model_cp.Add(assigned == sum(x_vars[(i, j)] for i in range(num_duties)))
    #         pos_dev = model_cp.NewIntVar(0, total_duties, f'pos_{j}')
    #         neg_dev = model_cp.NewIntVar(0, total_duties, f'neg_{j}')
    #         model_cp.Add(assigned - int(target) == pos_dev - neg_dev)
    #         penalties.append(balance_weight * pos_dev)
    #         penalties.append(balance_weight * neg_dev)

    # 2. Workload balance based on HOURS (respects FTE and initial hours)
    balance_weight = int(penalties_cfg.get('WorkloadBalance', 100))
    if balance_weight != 0:
        total_initial_hours = sum(initial_hours.values())
        total_month_hours = sum(duty_hours)
        total_fte = sum(doc.fte for doc in schedule.doctors.values()) / 100.0

        # For each doctor, compute target this-month hours
        for j, doc_name in enumerate(doctors):
            doc = schedule.doctors[doc_name]
            # target final hours = (total_initial + total_month) * (FTE/100) / total_FTE
            target_final = (total_initial_hours + total_month_hours) * (doc.fte / 100) / total_fte if total_fte > 0 else 0
            target_this_month = target_final - initial_hours.get(doc_name, 0.0)

            # assigned hours = sum over duties of (hours * x)
            assigned_hours = model_cp.NewIntVar(0, int(total_month_hours), f'assigned_hours_{j}')
            # Build linear expression
            expr = 0
            for i in range(num_duties):
                expr += int(duty_hours[i] * 10) * x_vars[(i, j)]  # use integer scaling (e.g., *10 for 0.1h precision)
            # But we need to use integer variables; we can scale hours by 10 to keep integers.
            # However, simpler: round hours to nearest integer? We can treat hours as floats and use integer linear expressions by scaling.
            # Better: define hours as integers (e.g., 8, 9) and use integer multiplication.
            # We'll assume hours are integers (e.g., 8, 8.5? we can keep .5 by scaling by 2)
            # For simplicity, we'll use hours as floats but convert to integer minutes? Let's keep hours as integers (8, 9, etc.) and scale by 2 for half hours.
            # I'll adjust: we'll store hours as float, but in the objective we use a scale factor of 10 to handle one decimal.
            # We'll create an expression: sum of (int(duty_hours[i]*10) * x_vars[(i,j)]) then later divide by 10 in target.
            # But target is also in hours *10.
            # Let's define a scaling factor SCALE = 10.
            SCALE = 10
            target_scaled = int(target_this_month * SCALE)
            # Build expression
            assigned_scaled = model_cp.NewIntVar(0, int(total_month_hours * SCALE), f'assigned_scaled_{j}')
            model_cp.Add(assigned_scaled == sum(int(duty_hours[i] * SCALE) * x_vars[(i, j)] for i in range(num_duties)))
            # Penalize deviation
            pos_dev = model_cp.NewIntVar(0, int(total_month_hours * SCALE), f'hpos_{j}')
            neg_dev = model_cp.NewIntVar(0, int(total_month_hours * SCALE), f'hneg_{j}')
            model_cp.Add(assigned_scaled - target_scaled == pos_dev - neg_dev)
            penalties.append(balance_weight * pos_dev)
            penalties.append(balance_weight * neg_dev)
    
    # 3. Weekend balance
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
    # 4. Penalize doctors who work only one day of a weekend (to encourage pairing)
    pair_weight = int(penalties_cfg.get('WeekendPairing', 10))
    if pair_weight != 0:
        weekend_pairs = {}  # (doctor, station, week_number) -> list of duty indices for Saturday and Sunday
        for i, (day_idx, station, abbr) in enumerate(duties):
            if schedule.days[day_idx].is_weekend:
                week_num = schedule.days[day_idx].date.isocalendar().week
                doc_name = doctors[j]  # we need to loop over doctors? Actually we need to know which doctor is assigned.
                # We'll create a variable for each doctor-weekend-station that indicates if they work Saturday/Sunday.
    # 4. Priority of duty types: try to assign high-priority duties to doctors who prefer them?
    # Already handled via preference, but can add duty priority as a global weight
    # For simplicity, we'll skip.
    
    # 5. Balance KM duties specifically
    km_weight = int(penalties_cfg.get('KMBalance', 30))  # default 30
    if km_weight != 0:
        # find all KM duty indices
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

    # 6. Cross-station penalty for ZD, SD, HD, NAZ (encourage same-station coverage) 
    cross_weight = int(penalties_cfg.get('CrossStation', 30))
    if cross_weight != 0:
        for i, (day_idx, station, abbr) in enumerate(duties):
            if abbr in ['ZD', 'SD', 'HD', 'NAZ'] and station != 'Global':
                for j, doc_name in enumerate(doctors):
                    if schedule.doctors[doc_name].station != station:
                        penalties.append(cross_weight * x_vars[(i, j)])

    return penalties
