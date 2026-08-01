# statistics.py
import pandas as pd
from models import ScheduleModel
from typing import Dict, List, Tuple
import pandas as pd
from collections import defaultdict
from typing import Tuple, List, Dict

def generate_statistics(
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str]
) -> pd.DataFrame:
    data = []
    total_duties = len(duties)
    total_fte = sum(doc.fte for doc in schedule.doctors.values())
    for doc_name in doctors:
        doc = schedule.doctors[doc_name]
        total = 0
        sd = zd = km = 0
        weekend = 0
        for i, assigned_doc in assignment.items():
            if assigned_doc == doc_name:
                total += 1
                abbr = duties[i][2]
                if abbr == 'SD': sd += 1
                elif abbr == 'ZD': zd += 1
                elif abbr == 'KM': km += 1
                if schedule.days[duties[i][0]].is_weekend:
                    weekend += 1
        expected = (doc.fte / 100) * (total_duties / total_fte) if total_fte > 0 else 0
        data.append([doc_name, doc.fte, total, sd, zd, km, weekend, round(expected, 1), round(total - expected, 1)])
    df = pd.DataFrame(data, columns=['Doctor', 'FTE %', 'Total', 'SD', 'ZD', 'KM', 'Weekend', 'Expected', 'Diff'])
    # Add total row
    total_row = ['TOTAL', '', df['Total'].sum(), df['SD'].sum(), df['ZD'].sum(), df['KM'].sum(), df['Weekend'].sum(), '', '']
    df.loc[len(df)] = total_row
    return df