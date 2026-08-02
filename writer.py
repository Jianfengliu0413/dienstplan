# # writer.py 
import openpyxl
from openpyxl.utils import get_column_letter
from models import ScheduleModel
import pandas as pd
from statistics import generate_statistics
from report import generate_conflict_report, generate_explanation
from typing import Dict, List, Tuple
from datetime import datetime
def write_output(
    template_path: str,
    output_path: str,
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    config: dict,
    solver,
    suggestions_df: pd.DataFrame = None
) -> None:
    wb = openpyxl.load_workbook(template_path)
    sheet_name = getattr(schedule, 'sheet_name', None)
    if not sheet_name or sheet_name not in wb.sheetnames:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]

    # --- Build reverse mapping: day_idx -> column ---
    col_for_day = {day_idx: col for col, day_idx in schedule.day_col.items()}

    # Determine the column range for date headers (row 1)
    date_header_row = 1
    start_col = 2
    end_col = ws.max_column

    # 1. CLEAR ALL WEEKEND CELLS for every doctor row (using header scan)
    for doc_name, row in schedule.doctor_row.items():
        for col in range(start_col, end_col + 1):
            header_cell = ws.cell(row=date_header_row, column=col)
            if isinstance(header_cell.value, datetime) and header_cell.value.weekday() >= 5:
                target_cell = ws.cell(row=row, column=col)
                # Handle merged cells
                if target_cell.coordinate in ws.merged_cells:
                    for merged_range in ws.merged_cells.ranges:
                        if target_cell.coordinate in merged_range:
                            top_left = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
                            try:
                                top_left.value = None
                            except Exception:
                                pass
                            break
                else:
                    try:
                        target_cell.value = None
                    except Exception:
                        pass

    # 2. Clear editable cells (weekdays)
    for row, col in schedule.editable_cells:
        try:
            ws.cell(row=row, column=col).value = None
        except Exception:
            pass

    # 3. Write main assignments (skip weekends, use col_for_day)
    # Load station code mapping (reverse: full name -> code)
    station_code_map_rev = {}
    if 'StationCodeMap' in config:
        df_map = config['StationCodeMap']
        for _, row in df_map.iterrows():
            code = str(row['Code']).strip().lower()
            station = str(row['Station']).strip()
            station_code_map_rev[station] = code

    # 3. Write main assignments (use col_for_day) 
    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        if doc_name in schedule.doctor_row:
            row = schedule.doctor_row[doc_name]
            col = col_for_day.get(day_idx)
            if col is not None and (row, col) in schedule.editable_cells:
                try:
                    doc_station = schedule.doctors[doc_name].station
                    if schedule.days[day_idx].is_weekend:
                        # Weekends: write full station name
                        ws.cell(row=row, column=col).value = station
                    else:
                        # Weekdays: if the duty station differs from doctor's station,
                        # write the station code of the target station, otherwise write abbreviation.
                        if doc_station != station and abbr in ['ZD', 'SD', 'HD', 'NAZ']:
                            code = station_code_map_rev.get(station, station)
                            ws.cell(row=row, column=col).value = code
                        else:
                            ws.cell(row=row, column=col).value = abbr
                except Exception:
                    pass

    # # 4. Compensatory SD (skip weekends, use col_for_day)
    # add_compensatory_sd(ws, schedule, assignment, duties, doctors, col_for_day)
    # Write fixed assignments (from wishes file)
    for doc_name, day_idx, station, abbr in schedule.fixed_assignments:
        if doc_name in schedule.doctor_row:
            row = schedule.doctor_row[doc_name]
            col = col_for_day.get(day_idx)
            if col is not None:
                try:
                    if abbr == 'PR':
                        # PR on weekend → show station; on weekdays → show "PR"
                        if schedule.days[day_idx].is_weekend:
                            ws.cell(row=row, column=col).value = station
                        else:
                            ws.cell(row=row, column=col).value = abbr
                    else:
                        # For any other duty (NAZ, HD, SD, ZD, KM, SUB, etc.) write the abbreviation
                        ws.cell(row=row, column=col).value = abbr
                except Exception:
                    pass

    # 5. Add statistics, conflict report, explanation
    if 'Statistics' in wb.sheetnames:
        wb.remove(wb['Statistics'])
    stats_df = generate_statistics(schedule, assignment, duties, doctors)
    with pd.ExcelWriter(output_path, engine='openpyxl', mode='a' if 'Statistics' in wb.sheetnames else 'w') as writer:
        stats_df.to_excel(writer, sheet_name='Statistics', index=False)

    if 'ConflictReport' in wb.sheetnames:
        wb.remove(wb['ConflictReport'])
    conflict_df = generate_conflict_report(schedule, assignment, duties, doctors, solver)
    with pd.ExcelWriter(output_path, engine='openpyxl', mode='a') as writer:
        conflict_df.to_excel(writer, sheet_name='ConflictReport', index=False)

    if 'Explanation' in wb.sheetnames:
        wb.remove(wb['Explanation'])
    explain_df = generate_explanation(schedule, assignment, duties, doctors)
    with pd.ExcelWriter(output_path, engine='openpyxl', mode='a') as writer:
        explain_df.to_excel(writer, sheet_name='Explanation', index=False)

    wb.save(output_path)

    if suggestions_df is not None and not suggestions_df.empty:
        with pd.ExcelWriter(output_path, engine='openpyxl', mode='a') as writer:
            suggestions_df.to_excel(writer, sheet_name='DayOffSuggestions', index=False)


def add_compensatory_sd(
    ws,
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    
    col_for_day: Dict[int, int] 
) -> None:
    """
    Post‑process: for each doctor, count weekend duties and assign the same
    number of SD duties on weekdays where the cell is empty.
    """
    # Build reverse lookup
    assigned = {}
    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        assigned[(doc_name, day_idx)] = abbr

    # Count weekend duties per doctor
    weekend_count = {}
    for doc_name in doctors:
        weekend_count[doc_name] = 0

    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        if schedule.days[day_idx].is_weekend:
            weekend_count[doc_name] += 1

    # Assign SD on weekdays
    for doc_name in doctors:
        num_sd_needed = weekend_count.get(doc_name, 0)
        if num_sd_needed <= 0:
            continue
        if schedule.doctors[doc_name].fte < 100:
            continue

        weekday_indices = [idx for idx, day in enumerate(schedule.days) if not day.is_weekend]
        assigned_sd = 0
        for day_idx in weekday_indices:
            if assigned_sd >= num_sd_needed:
                break
            if (doc_name, day_idx) in assigned:
                continue
            if (doc_name, day_idx) in schedule.unavailable:
                continue 
            row = schedule.doctor_row.get(doc_name)
            col = col_for_day.get(day_idx)
            if row is None or col is None:
                continue
            if (row, col) not in schedule.editable_cells:
                continue
            if (row, col) in schedule.fixed_cells:
                continue
            cell = ws.cell(row=row, column=col)
            if isinstance(cell, openpyxl.cell.cell.MergedCell):
                continue
            ws.cell(row=row, column=col).value = 'SD'
            assigned_sd += 1
            assigned[(doc_name, day_idx)] = 'SD'

        if assigned_sd < num_sd_needed:
            print(f"Warning: Could not assign all {num_sd_needed} SD duties for {doc_name} (only {assigned_sd} assigned).")

