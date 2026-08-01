# report.py
import pandas as pd
from models import ScheduleModel
from statistics import generate_statistics 
from typing import Dict, List, Tuple

def generate_conflict_report(
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    solver
) -> pd.DataFrame:
    rows = []
    # Unsatisfied preferences
    for doc in schedule.doctors.values():
        for (day_idx, duty_abbr, priority) in doc.preferences:
            assigned = False
            for i, assigned_doc in assignment.items():
                if assigned_doc == doc.name and duties[i][0] == day_idx and duties[i][2] == duty_abbr:
                    assigned = True
                    break
            if priority > 0 and not assigned:
                rows.append(['Unsatisfied Preference', f"{doc.name} preferred {duty_abbr} on {schedule.days[day_idx].date} but not assigned"])
            elif priority < 0 and assigned:
                rows.append(['Unsatisfied Preference', f"{doc.name} wanted to avoid {duty_abbr} on {schedule.days[day_idx].date} but assigned"])

    # Imbalance warnings (diff > 1.5)
    stats = generate_statistics(schedule, assignment, duties, doctors)
    for _, row in stats.iterrows():
        if row['Doctor'] != 'TOTAL':
            if abs(row['Diff']) > 1.5:
                rows.append(['Workload Imbalance', f"{row['Doctor']} has {row['Total']} duties, expected {row['Expected']}"])

    # Explanation: for each assignment, give reason
    # We'll generate a separate explanation sheet in writer

    df = pd.DataFrame(rows, columns=['Type', 'Description'])
    return df

def generate_explanation(
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str]
) -> pd.DataFrame:
    rows = []
    for i, (day_idx, station, abbr) in enumerate(duties):
        doc_name = assignment.get(i, 'UNASSIGNED')
        day = schedule.days[day_idx]
        rows.append([
            day.date.strftime('%Y-%m-%d'),
            station,
            abbr,
            doc_name,
            f"Doctor {doc_name} has skill {abbr}, belongs to {station} (or global), not on vacation."
        ])
    df = pd.DataFrame(rows, columns=['Date', 'Station', 'Duty', 'Doctor', 'Reason'])
    return df