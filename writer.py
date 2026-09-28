# # writer.py 
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill
from models import ScheduleModel
import pandas as pd
from statistics import generate_statistics
from report import generate_conflict_report, generate_explanation
from typing import Dict, List, Tuple
from datetime import datetime
from collections import defaultdict
from demand_builder import GLOBAL_STATION

RED_FILL = PatternFill(start_color='EA3323', end_color='EA3323', fill_type='solid')
ORANGE_FILL = PatternFill(start_color='F5C242', end_color='F5C242', fill_type='solid')
BLUE_FILL = PatternFill(start_color='B7C5E4', end_color='B7C5E4', fill_type='solid')
LIGHT_GREEN_FILL = PatternFill(start_color='9FCE63', end_color='9FCE63', fill_type='solid')

# calculate working hours
def write_working_hours_sheet(
    output_path: str,
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    config: dict,
) -> pd.DataFrame:
    """
    Compute per-doctor working hours and write to a 'WorkingHours' sheet
    inside the output workbook.

    Columns:
      Doctor, FTE %, Station, Category,
      <DutyType> Hours  (SD/ZD/KM/HD/NAZ/PR/SUB/...),
      Duty Hours, Weekend Hours,
      Normal Days, Normal Hours,
      Grand Total, Target Hours, Diff
    """
    import openpyxl

    # ---- 0. Duty hours lookup from config ----
    duty_hours_map = {}
    duty_cfg = config.get('DutyTypes', pd.DataFrame())
    if not duty_cfg.empty and 'Abbr' in duty_cfg.columns:
        for _, row in duty_cfg.iterrows():
            abbr = str(row['Abbr']).strip()
            hours_val = row.get('Hours', 8.5)
            if pd.isna(hours_val):
                hours_val = 8.5
            duty_hours_map[abbr] = float(hours_val)

    # ---- 1. Per-doctor duty-hour breakdown ----
    hours_by_type = {doc: defaultdict(float) for doc in doctors}
    weekend_hours = {doc: 0.0 for doc in doctors}
    duty_hours_total = {doc: 0.0 for doc in doctors}

    for i, doc_name in assignment.items():
        if doc_name not in hours_by_type:
            continue
        day_idx, station, abbr = duties[i]
        h = duty_hours_map.get(abbr, 8.5)

        hours_by_type[doc_name][abbr] += h
        duty_hours_total[doc_name] += h
        if schedule.days[day_idx].is_weekend:
            weekend_hours[doc_name] += h

    # ---- 2. Normal weekdays (no duty, not unavailable) ----
    weekday_indices = [idx for idx, day in enumerate(schedule.days) if not day.is_weekend]
    normal_hours_per_day = 8.5
    normal_days = {doc: 0 for doc in doctors}

    assigned_days = {doc: set() for doc in doctors}
    for i, doc_name in assignment.items():
        if doc_name in assigned_days:
            assigned_days[doc_name].add(duties[i][0])

    for doc in doctors:
        for day_idx in weekday_indices:
            if (doc, day_idx) in schedule.unavailable:
                continue
            if day_idx in assigned_days[doc]:
                continue
            normal_days[doc] += 1

    # ---- 3. Target hours based on FTE ----
    total_weekdays = len(weekday_indices)
    target_hours = {
        doc: (schedule.doctors[doc].fte / 100.0) * total_weekdays * normal_hours_per_day
        for doc in doctors
    }

    # ---- 4. Build DataFrame ----
    duty_types_in_model = sorted({abbr for _, _, abbr in duties})
    preferred_order = ['SD', 'ZD', 'KM', 'HD', 'NAZ', 'PR', 'SUB']
    ordered_types = [t for t in preferred_order if t in duty_types_in_model]
    ordered_types += [t for t in duty_types_in_model if t not in ordered_types]

    rows = []
    for doc in doctors:
        d = schedule.doctors[doc]
        row = {
            'Doctor': doc,
            'FTE %': d.fte,
            'Station': d.station or '',
            'Category': d.category,
        }
        for t in ordered_types:
            row[f'{t} Hours'] = round(hours_by_type[doc].get(t, 0.0), 2)

        duty_total = round(duty_hours_total[doc], 2)
        norm_h = round(normal_days[doc] * normal_hours_per_day, 2)
        grand_total = round(duty_total + norm_h, 2)
        target = round(target_hours[doc], 2)
        diff = round(grand_total - target, 2)

        row.update({
            'Duty Hours': duty_total,
            'Weekend Hours': round(weekend_hours[doc], 2),
            'Normal Days': normal_days[doc],
            'Normal Hours': norm_h,
            'Grand Total': grand_total,
            'Target Hours': target,
            'Diff': diff,
        })
        rows.append(row)

    df = pd.DataFrame(rows)

    # ---- 5. Add TOTAL row ----
    numeric_cols = [c for c in df.columns if c not in (
        'Doctor', 'FTE %', 'Station', 'Category'
    )]
    total_row = {c: df[c].sum() for c in numeric_cols}
    total_row['Doctor'] = 'TOTAL'
    df = pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

    # ---- 6. Write to Excel sheet 'WorkingHours' (replace if exists) ----
    try:
        wb = openpyxl.load_workbook(output_path)
        if 'WorkingHours' in wb.sheetnames:
            del wb['WorkingHours']
        wb.save(output_path)
    except Exception:
        pass

    with pd.ExcelWriter(output_path, engine='openpyxl', mode='a') as writer:
        df.to_excel(writer, sheet_name='WorkingHours', index=False)

    print(f"[WorkingHours] wrote sheet with {len(rows)} doctors")
    return df
    
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
 
    # 构建固定任务集合
    # fixed_set = set()
    # for doc_name, day_idx, station, abbr in schedule.fixed_assignments:
    #     fixed_set.add((day_idx, station, abbr))
    fixed_set = set()
    for doc_name, day_idx, station, abbr in schedule.fixed_assignments:
        fixed_set.add((doc_name, day_idx, station, abbr))
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

    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        if doc_name in schedule.doctor_row:
            row = schedule.doctor_row[doc_name]
            col = col_for_day.get(day_idx)
            if col is None:
                print(f"Warning: day {day_idx} not in col_for_day")
                continue 
            if schedule.days[day_idx].is_weekend and abbr == 'PR':
                code = station_code_map_rev.get(station, station).upper()
                ws.cell(row=row, column=col).value = code
                # Non-requested assignment → red fill
                if (doc_name, day_idx, station, abbr) not in fixed_set:
                    ws.cell(row=row, column=col).fill = RED_FILL
                # 若该单元格不在 editable_cells，打印一次警告（可选）
                # if (row, col) not in schedule.editable_cells:
                #     print(f"Warning: forced write to non-editable weekend cell ({row},{col})")
                continue
            # 其他任务需要 editable
            if (row, col) in schedule.editable_cells:
                try:
                    # 原有写入逻辑（保持不变）
                    if station == GLOBAL_STATION:
                        ws.cell(row=row, column=col).value = abbr
                    else:
                        doc_station = schedule.doctors[doc_name].station
                        if schedule.days[day_idx].is_weekend:
                            code = station_code_map_rev.get(station, station).upper()
                            ws.cell(row=row, column=col).value = code 
                        else:
                            if doc_station != station and abbr in ['ZD', 'SD', 'HD', 'NAZ']:
                                code = station_code_map_rev.get(station, station).upper()
                                ws.cell(row=row, column=col).value = code
                            else:
                                ws.cell(row=row, column=col).value = abbr

                    # --- Color coding ---
                    # HD / NAZ at GLOBAL_STATION: red if NOT a fixed (requested) assignment 
                    if abbr in ('HD', 'NAZ') and station == GLOBAL_STATION:
                        if (doc_name, day_idx, station, abbr) not in fixed_set:
                            ws.cell(row=row, column=col).fill = RED_FILL
                    elif abbr == 'ZD':
                        ws.cell(row=row, column=col).fill = BLUE_FILL
                    elif abbr == 'SD':
                        ws.cell(row=row, column=col).fill = ORANGE_FILL

                except Exception:
                    pass

    # # 4. Compensatory SD (skip weekends, use col_for_day)
    # add_compensatory_sd(ws, schedule, assignment, duties, doctors, col_for_day)
    # Write fixed assignments (from wishes file) 
    for doc_name, day_idx, station, abbr in schedule.fixed_assignments:
        if doc_name not in schedule.doctor_row:
            continue
        row = schedule.doctor_row[doc_name]
        col = col_for_day.get(day_idx)
        if col is None:
            continue
        cell = ws.cell(row=row, column=col)
        # Only write if the main loop didn't already fill this exact cell
        # for the same doctor. This protects against a mismatch where the
        # solver placed a different doctor on the same duty slot.
        if cell.value is not None:
            continue
        try:
            if abbr == 'PR':
                if schedule.days[day_idx].is_weekend:
                    code = station_code_map_rev.get(station, station).upper()
                    cell.value = code
                else:
                    cell.value = abbr
            else:
                cell.value = abbr
        except Exception:
            pass
    # ========== 补偿休息日标记（浅绿色） ==========
    mark_compensatory_days(ws, schedule, assignment, duties, doctors, col_for_day, station_code_map_rev)

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
    
    # write: working hours sheet
    try:
        write_working_hours_sheet(
            output_path=output_path,
            schedule=schedule,
            assignment=assignment,
            duties=duties,
            doctors=doctors,
            config=config,
        )
    except Exception as e:
        print(f"[WorkingHours] failed: {e}")

    wb.save(output_path)

    if suggestions_df is not None and not suggestions_df.empty:
        with pd.ExcelWriter(output_path, engine='openpyxl', mode='a') as writer:
            suggestions_df.to_excel(writer, sheet_name='DayOffSuggestions', index=False)

def mark_compensatory_days(
    ws,
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    col_for_day: Dict[int, int],
    station_code_map_rev: Dict[str, str]
):
    """
    After all assignments are written, mark compensatory days (light green)
    for doctors based on weekend PR (2 PR = 1 day), HD (1 day each), NAZ (1 day each).

    Rules:
At most 1 doctor from the same station can take comp on the same day.
Prefer days where the station has good coverage (many available doctors).
Prefer days that are far from other already-assigned comp days
        (temporal spread across the month).
Never overwrite a fixed (wish) assignment or a non-empty cell.
    """
    from openpyxl.styles import PatternFill
    from collections import defaultdict

    # ------------------------------------------------------------------
    # 1. Count weekend PR / HD / NAZ per doctor
    # ------------------------------------------------------------------
    counts = {doc: {'PR': 0, 'HD': 0, 'NAZ': 0} for doc in doctors}
    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        if schedule.days[day_idx].is_weekend:
            if abbr == 'PR':
                counts[doc_name]['PR'] += 1
            elif abbr == 'HD':
                counts[doc_name]['HD'] += 1
            elif abbr == 'NAZ':
                counts[doc_name]['NAZ'] += 1

    # Cells already used by a fixed (wish) assignment — must not be tinted
    fixed_assignment_cells = set()
    for dn, di, _, _ in schedule.fixed_assignments:
        r = schedule.doctor_row.get(dn)
        c = col_for_day.get(di)
        if r is not None and c is not None:
            fixed_assignment_cells.add((r, c))

    # ------------------------------------------------------------------
    # 2. Compute comp days needed per doctor
    #    (round up for odd PR: 3 PR -> 2 days, 5 PR -> 3 days, ...)
    # ------------------------------------------------------------------
    comp_needed = {}
    for doc in doctors:
        pr = counts[doc]['PR']
        hd = counts[doc]['HD']
        naz = counts[doc]['NAZ']
        base = pr // 2 + hd + naz
        if pr % 2 == 1 and base > 0:
            comp = base + 1
        else:
            comp = base
        comp_needed[doc] = comp

    # ------------------------------------------------------------------
    # 3. Busy days per doctor (already has a duty)
    # ------------------------------------------------------------------
    busy_on_day = defaultdict(set)
    for i, doc_name in assignment.items():
        day_idx, _, _ = duties[i]
        busy_on_day[day_idx].add(doc_name)

    # ------------------------------------------------------------------
    # 4. Available weekdays per doctor
    # ------------------------------------------------------------------
    available = {doc: [] for doc in doctors}
    for day_idx, day in enumerate(schedule.days):
        if day.is_weekend:
            continue
        for doc in doctors:
            if doc in busy_on_day[day_idx]:
                continue
            if (doc, day_idx) in schedule.unavailable:
                continue
            available[doc].append(day_idx)

    # ------------------------------------------------------------------
    # 5. Group doctors by station
    # ------------------------------------------------------------------
    station_doctors = defaultdict(list)
    for doc in doctors:
        station = schedule.doctors[doc].station
        if station is not None:
            station_doctors[station].append(doc)

    # ------------------------------------------------------------------
    # 6. Per-station per-day comp counter (max 1 per station per day)
    #    and global per-day comp counter (for temporal spread)
    # ------------------------------------------------------------------
    station_comp_count = defaultdict(lambda: defaultdict(int))
    global_comp_count = defaultdict(int)

    # ------------------------------------------------------------------
    # 7. Helper: pick the best day for `doc` from `avail_days`, then assign
    # ------------------------------------------------------------------
    def assign_one_comp(doc, avail_days, station, doc_list):
        """Pick one day for `doc` and tint it. Returns the chosen day_idx or None."""
        if not avail_days:
            return None
    
        scored_days = []
        for day_idx in avail_days:
            # (a) Station coverage
            station_available = 0
            for other_doc in doc_list:
                if other_doc == doc:
                    continue
                if other_doc in busy_on_day[day_idx]:
                    continue
                if (other_doc, day_idx) in schedule.unavailable:
                    continue
                station_available += 1
    
            # (b) Already-assigned comp at this station/day
            existing_station_comp = station_comp_count[station][day_idx]
    
            # (c) Already-assigned comp globally (use .get to avoid defaultdict side effect)
            existing_global_comp = global_comp_count.get(day_idx, 0)
    
            # (d) Distance to nearest *actually-used* comp day
            existing_days = [d for d, c in global_comp_count.items() if c > 0]
            if existing_days:
                min_dist = min(abs(day_idx - d) for d in existing_days)
            else:
                min_dist = 999
    
            score = (
                    station_available * 1
                    - existing_station_comp * 10
                    - existing_global_comp * 5.
                    + min_dist * 2
                )
            scored_days.append((day_idx, score))
    
        # Tie-break: larger day_idx on equal score (counters early-month bias)
        scored_days.sort(key=lambda x: (-x[1], -x[0]))
        chosen_day = scored_days[0][0]
    
        # Write the tint
        row = schedule.doctor_row.get(doc)
        col = col_for_day.get(chosen_day)
        if row is None or col is None:
            return None
    
        cell = ws.cell(row=row, column=col)
        if (
            cell.value is None
            and (row, col) not in schedule.fixed_cells
            and (row, col) not in fixed_assignment_cells
        ):
            cell.fill = LIGHT_GREEN_FILL
            station_comp_count[station][chosen_day] += 1
            global_comp_count[chosen_day] += 1
            return chosen_day
        else:
            return None

    # ------------------------------------------------------------------
    # 8. Assign comp days for doctors WITH a station
    # ------------------------------------------------------------------
    for station, doc_list in station_doctors.items():
        docs_needing = [doc for doc in doc_list if comp_needed.get(doc, 0) > 0]
        # More needy first (stable order)
        docs_needing.sort(key=lambda d: comp_needed[d], reverse=True)

        for doc in docs_needing:
            needed = comp_needed[doc]
            avail_days = list(available.get(doc, []))
            if not avail_days:
                continue

            assigned = 0
            # Try until we assign `needed` days or run out of candidates
            attempts = 0
            max_attempts = needed * 3  # allow a few retries on non-writable cells
            while assigned < needed and avail_days and attempts < max_attempts:
                attempts += 1
                chosen = assign_one_comp(doc, avail_days, station, doc_list)
                if chosen is None:
                    # The best day was not writable — remove it and retry
                    # Find the day with the best score to drop it
                    # (we simply drop the first day that got the top score)
                    # To keep it simple, we pop the day the previous call would
                    # have picked.
                    # Fallback: drop the first available day.
                    avail_days.pop(0)
                    continue
                avail_days.remove(chosen)
                assigned += 1

            if assigned < needed:
                print(
                    f"[comp] {doc}: could only assign {assigned}/{needed} "
                    f"compensatory days (station={station})"
                )

    # ------------------------------------------------------------------
    # 9. Doctors WITHOUT a station (fallback): spread by distance too
    # ------------------------------------------------------------------
    for doc in doctors:
        if schedule.doctors[doc].station is not None:
            continue
        needed = comp_needed.get(doc, 0)
        if needed <= 0:
            continue
        avail_days = list(available.get(doc, []))
        if not avail_days:
            continue

        assigned = 0
        attempts = 0
        max_attempts = needed * 3
        while assigned < needed and avail_days and attempts < max_attempts:
            attempts += 1

            if global_comp_count:
                chosen_day = max(
                    avail_days,
                    key=lambda d: min(
                        abs(d - cd)
                        for cd, c in global_comp_count.items()
                        if c > 0
                    ),
                )
            else:
                # No anchors yet → start from the middle of the month
                chosen_day = avail_days[len(avail_days) // 2]

            row = schedule.doctor_row.get(doc)
            col = col_for_day.get(chosen_day)
            if row is None or col is None:
                avail_days.remove(chosen_day)
                continue

            cell = ws.cell(row=row, column=col)
            if (
                cell.value is None
                and (row, col) not in schedule.fixed_cells
                and (row, col) not in fixed_assignment_cells
            ):
                cell.fill = LIGHT_GREEN_FILL
                global_comp_count[chosen_day] += 1
                assigned += 1
            avail_days.remove(chosen_day)

    # ------------------------------------------------------------------
    # 10. Debug: print comp day distribution across the month
    # ------------------------------------------------------------------
    if global_comp_count:
        total_days = len(schedule.days)
        half = total_days // 2
        first_half = sum(c for d, c in global_comp_count.items() if d < half)
        second_half = sum(c for d, c in global_comp_count.items() if d >= half)
        print("\n=== Compensatory days distribution ===")
        print(f"  Total comp days: {sum(global_comp_count.values())}")
        print(f"  First half of month: {first_half}")
        print(f"  Second half of month: {second_half}")
        # Optional detailed dump (commented out to keep logs short):
        # for d in sorted(global_comp_count):
        #     day = schedule.days[d]
        #     print(f"    {day.date.strftime('%Y-%m-%d (%a)')}: {global_comp_count[d]}")

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

