# parser.py

import openpyxl
from openpyxl.utils import column_index_from_string
from openpyxl.styles import PatternFill
from openpyxl.styles.proxy import StyleProxy
from datetime import datetime
import re
import os
import pandas as pd
from models import ScheduleModel, Doctor, Day, DutyType, Station
 
def is_dark_green(rgb_hex: str, tolerance: int = 10) -> bool:
    """Dark green: G > R and G > B with low brightness."""
    if len(rgb_hex) == 8:
        rgb_hex = rgb_hex[2:]
    if len(rgb_hex) != 6:
        return False
    try:
        r = int(rgb_hex[0:2], 16)
        g = int(rgb_hex[2:4], 16)
        b = int(rgb_hex[4:6], 16)
        # Dark green: G is highest, R and B are low, and overall brightness is low
        return (g > r + tolerance and g > b + tolerance and 
                r < 100 and b < 100 and (r + g + b) < 350)
    except:
        return False

def is_light_green(rgb_hex: str, tolerance: int = 10) -> bool:
    """Light green: G > R and G > B with higher brightness."""
    if len(rgb_hex) == 8:
        rgb_hex = rgb_hex[2:]
    if len(rgb_hex) != 6:
        return False
    try:
        r = int(rgb_hex[0:2], 16)
        g = int(rgb_hex[2:4], 16)
        b = int(rgb_hex[4:6], 16)
        return (g > r + tolerance and g > b + tolerance and 
                (r + g + b) >= 350)
    except:
        return False
def parse_template(template_path: str, config: dict, wishes_path: str = None) -> ScheduleModel:
    """
    Reads the Excel template and builds the ScheduleModel.
    """
    wb = openpyxl.load_workbook(template_path, data_only=True)
    settings = config['Settings'].set_index('Setting')['Value'].to_dict()
    for k, v in settings.items():
        if pd.isna(v):
            settings[k] = ''
        else:
            settings[k] = str(v)

    vacation_color = settings.get('VacationColor', '#00B050')
    # Add unavailable color (default dark green)
    unavailable_color = settings.get('UnavailableColor', '#00B050')
    if len(vacation_color) == 6:
        vacation_color = 'FF' + vacation_color
    if len(unavailable_color) == 6:
        unavailable_color = 'FF' + unavailable_color
    # Normalise unavailable_color to 6-digit hex for exact comparison
    if len(unavailable_color) == 8:
        unavailable_6 = unavailable_color[2:]
    else:
        unavailable_6 = unavailable_color
    sheet_name = settings.get('ScheduleSheet', '')
    if not sheet_name or sheet_name not in wb.sheetnames:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]

    # --- 1. Parse month and dates ---
    month_cell = ws.cell(row=1, column=1)
    month_val = month_cell.value
    if isinstance(month_val, datetime):
        base_year = month_val.year
        base_month = month_val.month
    elif month_val:
        month_str = str(month_val)
        month_map = {
            'Januar': 1, 'Jan': 1, 'January': 1,
            'Februar': 2, 'Feb': 2, 'February': 2,
            'März': 3, 'Marz': 3, 'March': 3, 'Mar': 3,
            'April': 4, 'Apr': 4,
            'Mai': 5, 'May': 5,
            'Juni': 6, 'June': 6, 'Jun': 6,
            'Juli': 7, 'July': 7, 'Jul': 7,
            'August': 8, 'Aug': 8,
            'September': 9, 'Sep': 9,
            'Oktober': 10, 'October': 10, 'Oct': 10,
            'November': 11, 'Nov': 11,
            'Dezember': 12, 'Dec': 12, 'Dez': 12
        }
        base_month = 10
        base_year = 2026
        for m_name, m_num in month_map.items():
            if m_name.lower() in month_str.lower():
                base_month = m_num
                break
        match = re.search(r'\d{4}', month_str)
        if match:
            base_year = int(match.group())
    else:
        base_month = 10
        base_year = 2026
    print(f"Using base month={base_month}, year={base_year}")

    # Parse date headers
    days = []
    day_cols = {}
    start_col = 2
    found_any = False
    for col in range(start_col, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        if val and isinstance(val, str):
            match = re.search(r'(\d{1,2})', val)
            if match:
                day_num = int(match.group(1))
                try:
                    date = datetime(base_year, base_month, day_num)
                    days.append(Day(date=date, weekday=date.strftime('%a'), is_weekend=date.weekday() >= 5))
                    day_cols[col] = len(days) - 1
                    found_any = True
                except ValueError:
                    continue
        elif isinstance(val, datetime):
            day_num = val.day
            try:
                date = datetime(base_year, base_month, day_num)
                days.append(Day(date=date, weekday=date.strftime('%a'), is_weekend=date.weekday() >= 5))
                day_cols[col] = len(days) - 1
                found_any = True
            except ValueError:
                continue

    if not found_any:
        start_col = 3
        for col in range(start_col, ws.max_column + 1):
            val = ws.cell(row=1, column=col).value
            if val and isinstance(val, str):
                match = re.search(r'(\d{1,2})', val)
                if match:
                    day_num = int(match.group(1))
                    try:
                        date = datetime(base_year, base_month, day_num)
                        days.append(Day(date=date, weekday=date.strftime('%a'), is_weekend=date.weekday() >= 5))
                        day_cols[col] = len(days) - 1
                        found_any = True
                    except ValueError:
                        continue

    if not days:
        raise ValueError("No valid date headers found in row 1.")

    print(f"Parsed {len(days)} days, first date: {days[0].date.strftime('%Y-%m-%d')}")

    # --- 2. Create the model and set basic attributes ---
    model = ScheduleModel()
    model.days = days
    model.day_col = day_cols
    model.sheet_name = sheet_name

    # --- 3. Build duty types from config (or fallback) ---
    duty_cfg = config.get('DutyTypes', pd.DataFrame())
    if not duty_cfg.empty:
        for _, row in duty_cfg.iterrows():
            abbr = str(row['Abbr']).strip()
            fullname = str(row.get('FullName', abbr)).strip()
            requires_senior = str(row.get('RequiresSenior', 'No')).strip().upper() == 'YES'
            weekend_only = str(row.get('WeekendOnly', 'No')).strip().upper() == 'YES'
            priority_val = row.get('Priority', 1)
            if pd.isna(priority_val):
                priority_val = 1
            else:
                priority_val = int(priority_val)

            # Read hours from config
            hours_val = row.get('Hours', 8.5)
            if pd.isna(hours_val):
                hours = 8.5
            else:
                hours = float(hours_val)

            dt = DutyType(
                abbr=abbr,
                fullname=fullname,
                requires_senior=requires_senior,
                weekend_only=weekend_only,
                priority=priority_val,
                hours=hours
            )
            model.duty_types[dt.abbr] = dt
    else:
        model.duty_types = {
            'SD': DutyType('SD', 'Spätdienst', False, False, 1),
            'ZD': DutyType('ZD', 'Zwischendienst', False, False, 1),
            'KM': DutyType('KM', 'Knochenmarkentnahme', True, False, 2),
        }
    # Always ensure KM is present
    if 'KM' not in model.duty_types:
        model.duty_types['KM'] = DutyType('KM', 'Knochenmarkentnahme', True, False, 2)

    # --- 4. Load station code mapping ---
    station_code_map = {}
    station_names_set = set()
    if 'StationCodeMap' in config:
        df_map = config['StationCodeMap']
        for _, row in df_map.iterrows():
            code = str(row['Code']).strip().lower()
            station = str(row['Station']).strip()
            station_code_map[code] = station
            station_names_set.add(station)

    # --- 5. Define legend keywords ---
    legend_keywords = {
        'ferien', 'spätdienst ima', 'sd', 'zd', 'km', 'hd', 'naz', 'pr', 'sub',
        'spätdienst', 'zwischendienst', 'knochenmarkentnahme','ambulanzen','Elternzeit'
    }

    # --- 6. Scan rows to identify stations and doctors ---
    station_rows = []      # (row, station_name)
    doctor_rows = []       # (row, name, fte, station_name)
    current_station = None
    found_station_names = set()

    for row in range(2, ws.max_row + 1):
        cell_a = ws.cell(row=row, column=1)
        cell_b = ws.cell(row=row, column=2)
        val_a = cell_a.value
        val_b = cell_b.value

        if not val_a and not val_b:
            continue

        name_a = str(val_a).strip() if val_a else ''
        name_b = str(val_b).strip() if val_b else ''

        # Skip legend rows
        if name_a.lower() in legend_keywords or name_b.lower() in legend_keywords:
            continue

        # Check if it's a station header
        is_station = False
        station_name = None

        if name_b and name_b.lower() in station_code_map:
            station_name = station_code_map[name_b.lower()]
            is_station = True
        elif name_a in station_names_set:
            station_name = name_a
            is_station = True

        if is_station:
            current_station = station_name
            found_station_names.add(station_name)
            station_rows.append((row, current_station))
            print(f"\n[Station]: {current_station} ----------- (row {row})")
            continue
        
        # If column A is a known station name, skip (it's a station header, not a doctor)
        if name_a in station_names_set:
            continue

        # Check if it's a doctor row
        if name_a and re.search(r'[a-zA-Z]', name_a):
            if name_a.upper() in model.duty_types:
                continue
            if re.match(r'^\d+(\.\d+)?$', name_a):
                continue

            doctor_name = name_a
            fte = 100

            # Extract FTE from name
            pct_match = re.search(r'(\d{1,3})\s*%', doctor_name)
            if pct_match:
                fte = int(pct_match.group(1))
                doctor_name = re.sub(r'\s*\d{1,3}\s*%', '', doctor_name).strip()
            # Or from column B (e.g., "0.5")
            if name_b:
                try:
                    fte_float = float(name_b)
                    if 0 < fte_float <= 1:
                        fte = int(fte_float * 100)
                    elif 0 < fte_float <= 100:
                        fte = int(fte_float)
                except ValueError:
                    pass
            doctor_name = doctor_name.rstrip('*').strip()

            station = current_station
            if station:
                doctor_rows.append((row, doctor_name, fte, station))
                print(f"[Doctor]: {doctor_name}")
            else:
                doctor_rows.append((row, doctor_name, fte, None))
                print(f"*******[Warning]: Doctor {doctor_name} has no station (row {row})*******")
        else:
            # ignore
            pass

    # --- 7. Add stations to the model ---
    model.found_station_names = found_station_names

    # Create stations from config (if any)
    station_cfg = config.get('Stations', pd.DataFrame())
    for _, row in station_cfg.iterrows():
        name = str(row['Station']).strip()
        req_senior = str(row.get('RequiresSenior', 'No')).strip().upper() == 'YES'
        st = Station(name=name, requires_senior=req_senior)

        weekday_counts_str = str(row.get('WeekdayDutyCounts', ''))
        if weekday_counts_str and weekday_counts_str.strip() and weekday_counts_str.lower() != 'nan':
            for part in weekday_counts_str.split(','):
                if '=' in part:
                    abbr, cnt = part.strip().split('=')
                    st.weekday_demand[abbr.strip()] = int(cnt)

        weekend_counts_str = str(row.get('WeekendDutyCounts', ''))
        if weekend_counts_str and weekend_counts_str.strip() and weekend_counts_str.lower() != 'nan':
            for part in weekend_counts_str.split(','):
                if '=' in part:
                    abbr, cnt = part.strip().split('=')
                    st.weekend_demand[abbr.strip()] = int(cnt)

        st.demand = st.weekday_demand.copy()
        model.stations[name] = st

    # Add stations found in template (if not already in model.stations)
    for station_name in found_station_names:
        if station_name not in model.stations:
            model.stations[station_name] = Station(name=station_name, requires_senior=False)

    # Detect '0' on station rows (no substitution needed)
    for row, station_name in station_rows:
        zero_days = set()
        for col, day_idx in day_cols.items():
            cell = ws.cell(row=row, column=col)
            if cell.value is not None and str(cell.value).strip() == '0':
                zero_days.add(day_idx)
        if station_name in model.stations:
            model.station_zero_days[station_name] = zero_days

    # --- 8. Define default Active/Weekend based on station ---
    station_defaults = {
        'Sprechstunde PP/Oberärzte': ('No', 'No'),
        'Springer/Konsile/Diagnostik': ('No', 'Yes'),
        '93 (3 IS)': ('No', 'Yes'),
        'Rotation Med I': ('No', 'Yes'),
        'Rotation': ('No', 'Yes'),
        'Aufnahme': ('No', 'No'),
        'Forschung': ('No', 'Yes'),
        'Balingen': ('No', 'Yes'),
        'Elternzeit': ('No', 'No'),
        "Ambulanzen": ('No', 'No'),
    }
    # Special doctor override
    special_doctor_defaults = {
        'Schwartz': ('No', 'No'),
    }

    # --- 9. Add doctors, handling duplicates (keep first occurrence) ---
    seen_doctors = set()
    # We'll attach overrides as attributes of the model
    model._active_override = {}
    model._weekend_override = {}
    model._inactive_doctors = {}   # store inactive doctors separately

    for row, name, fte, station in doctor_rows:
        if name in seen_doctors:
            continue
        seen_doctors.add(name)

        # Determine Active and Weekend
        active_default = 'Yes'
        weekend_default = 'Yes'

        if name in special_doctor_defaults:
            active_default, weekend_default = special_doctor_defaults[name]
        elif station in station_defaults:
            active_default, weekend_default = station_defaults[station]

        # Store overrides for all doctors (for writing the sheet)
        model._active_override[name] = active_default
        model._weekend_override[name] = weekend_default

        # Only add ACTIVE doctors to the model (they will be used by the solver)
        if active_default == 'Yes':
            doc = Doctor(
                name=name,
                fte=fte,
                station=station,
                weekend_available=(weekend_default == 'Yes')
            )
            model.doctors[name] = doc
            model.doctor_row[name] = row
        else:
            # Store inactive for later writing (but not in model.doctors)
            model._inactive_doctors[name] = {
                'row': row,
                'fte': fte,
                'station': station,
                'active': active_default,
                'weekend': weekend_default
            }
            print(f"[Skipping inactive doctor]: {name} @ {station}") 

    # --- 10. Skills ---
    skills_cfg = config.get('Skills', pd.DataFrame())
    for _, row in skills_cfg.iterrows():
        doc_name = row['Doctor']
        duty = row['DutyType']
        if doc_name in model.doctors:
            model.doctors[doc_name].skills.add(duty)

    # Auto-add PR if Weekend=Yes and PR exists
    if 'PR' in model.duty_types:
        for doc in model.doctors.values():
            if doc.weekend_available:
                doc.skills.add('PR')

    # Add SUB for 65 PP doctors
    if 'SUB' not in model.duty_types:
        model.duty_types['SUB'] = DutyType('SUB', 'Substitution', False, False, 1)
    for doc in model.doctors.values():
        if doc.station == '65 PP':
            doc.skills.add('SUB')

    # --- 11. Editable/fixed cells ---
    fixed_vals = set(settings.get('FixedValues', 'x, F, X').split(','))
    fixed_vals = {v.strip() for v in fixed_vals if v.strip()}
    placeholder = settings.get('EditablePlaceholder', '0')
    duty_abbrs = set(model.duty_types.keys())

    for row, name, fte, station in doctor_rows:
        if name not in model.doctors:
            continue 
        for col, day_idx in day_cols.items():
            cell = ws.cell(row=row, column=col)
            val = cell.value
            is_fixed = False
            is_unavailable = False

            if val is not None and str(val).strip() in fixed_vals:
                is_fixed = True
                if str(val).strip() not in duty_abbrs:
                    is_unavailable = True

            # --- Check fill colors ---
            if cell.fill:
                rgb_str = None
                is_dark = False
                is_light = False
                try:
                    if hasattr(cell.fill, 'fgColor'):
                        color = cell.fill.fgColor
                    elif hasattr(cell.fill, 'start_color'):
                        color = cell.fill.start_color
                    else:
                        color = None
                    
                    if color:
                        if color.type == 'theme':
                            theme_idx = color.theme
                            tint = color.tint if color.tint is not None else 0.0
                            # print(f"Cell ({row}, {col}) theme: {theme_idx}, tint: {tint}") # debug
                            # Heuristic: theme 6 is often green (Accent 6)
                            if theme_idx == 6:
                                if tint < -0.1:  # dark green
                                    is_dark = True
                                else:
                                    is_light = True
                        elif color.type == 'rgb' and color.rgb:
                            rgb_str = color.rgb
                            if len(rgb_str) == 8:
                                rgb_str = rgb_str[2:]
                            # print(f"Cell ({row}, {col}) RGB: {rgb_str}") # debug
                            if is_dark_green(rgb_str):
                                is_dark = True
                            elif is_light_green(rgb_str):
                                is_light = True
                except (AttributeError, TypeError):
                    pass

                if is_dark or (rgb_str and is_dark_green(rgb_str)):
                    # print("  -> DARK GREEN detected") # debug
                    is_fixed = True
                    is_unavailable = True
                elif is_light or (rgb_str and is_light_green(rgb_str)):
                    if not hasattr(model, 'soft_unavailable'):
                        model.soft_unavailable = set()
                    model.soft_unavailable.add((name, day_idx))
                        
            if is_fixed:
                model.fixed_cells.add((row, col))
                if is_unavailable:
                    model.unavailable.add((name, day_idx))
            else:
                if val is None or str(val) == placeholder:
                    model.editable_cells.add((row, col))
                else:
                    model.fixed_cells.add((row, col))

    # --- 12. Apply wishes file ---
    if wishes_path and os.path.exists(wishes_path):
        apply_wishes_from_file(model, wishes_path, config, fixed_vals, vacation_color)

    print(f"[DONE!!!]: Parsing complete: found {len(model.doctors)} doctors and {len(model.stations)} stations.")
    return model
 
def apply_wishes_from_file(model: ScheduleModel, wishes_path: str, config: dict, fixed_vals: set, vacation_color: str):
    """
    Reads wishes file:
      - Duty abbreviations (SD, ZD, KM, HD, NAZ, etc.) → **fixed assignment** at the doctor's station.
      - Station codes (e.g., "92", "85", "65P") → high‑priority preference (priority=50),
        and if on a weekend and station is one of the four main ones, becomes a fixed assignment.
      - Fixed values (x, U, dgho, etc.) + green fill → unavailable (vacation/absence).
    """
    wb = openpyxl.load_workbook(wishes_path, data_only=True)
    settings = config['Settings'].set_index('Setting')['Value'].to_dict()
    sheet_name = settings.get('ScheduleSheet', '')
    if not sheet_name or sheet_name not in wb.sheetnames:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]

    # Load station code mapping
    station_code_map = {}
    if 'StationCodeMap' in config:
        df_map = config['StationCodeMap']
        for _, row in df_map.iterrows():
            code = str(row['Code']).strip().lower()
            station = str(row['Station']).strip()
            station_code_map[code] = station

    # Build set of duty abbreviations
    duty_abbrs = set(model.duty_types.keys())

    doctor_name_col = settings.get('DoctorNameColumn', 'A')
    doctor_name_col_idx = column_index_from_string(doctor_name_col)

    # Map wish‑file doctor names (clean)
    wish_rows = {}
    for row in range(1, ws.max_row + 1):
        cell = ws.cell(row=row, column=doctor_name_col_idx)
        if cell.value and isinstance(cell.value, str):
            name = cell.value.strip().replace('*', '').strip()
            if name in model.doctors:
                wish_rows[name] = row

    # Parse date columns
    date_row = 1
    day_cols_wish = {}
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=date_row, column=col).value
        if val and isinstance(val, str):
            match = re.search(r'(\d{1,2})', val)
            if match:
                day_num = int(match.group(1))
                for idx, d in enumerate(model.days):
                    if d.date.day == day_num and d.date.month == model.days[0].date.month:
                        day_cols_wish[col] = idx
                        break
        elif isinstance(val, (int, float)):
            day_num = int(val)
            for idx, d in enumerate(model.days):
                if d.date.day == day_num and d.date.month == model.days[0].date.month:
                    day_cols_wish[col] = idx
                    break
        elif isinstance(val, datetime):
            for idx, d in enumerate(model.days):
                if d.date == val:
                    day_cols_wish[col] = idx
                    break

    if not day_cols_wish:
        for col in range(doctor_name_col_idx + 1, ws.max_column + 1):
            day_idx = len(day_cols_wish)
            if day_idx >= len(model.days):
                break
            day_cols_wish[col] = day_idx

    for doc_name, row in wish_rows.items():
        for col, day_idx in day_cols_wish.items():
            cell = ws.cell(row=row, column=col)
            val = cell.value
            if val is None:
                continue
            val_str = str(val).strip()
            if not val_str:
                continue

            # Normalise: remove spaces, strip trailing .0, convert numeric codes
            norm_str = val_str.replace(' ', '')
            if norm_str.endswith('.0'):
                norm_str = norm_str[:-2]
            try:
                numeric_val = float(norm_str)
                if numeric_val.is_integer():
                    norm_str = str(int(numeric_val))
            except ValueError:
                pass
            norm_upper = norm_str.upper()

            # ---------- 1. Check if it's a duty abbreviation ----------
            if norm_upper in duty_abbrs:
                duty_abbr = norm_upper
                # Add as a preference (high priority)
                model.doctors[doc_name].preferences.append((day_idx, duty_abbr, 100))
                print(f"[WISH] (duty): {doc_name} wants {duty_abbr} on {model.days[day_idx].date} (priority 100)")

                # --- Make it a FIXED assignment at the doctor's own station ---
                doc_station = model.doctors[doc_name].station
                if doc_station:
                    model.fixed_assignments.append((doc_name, day_idx, doc_station, duty_abbr))
                    print(f"[FIXED] (duty): {doc_name} must work {duty_abbr} at {doc_station} on {model.days[day_idx].date}")
                    # Auto‑add the skill if missing (so solver doesn't reject it)
                    if duty_abbr not in model.doctors[doc_name].skills:
                        model.doctors[doc_name].skills.add(duty_abbr)
                        print(f"   ➕ Auto‑added skill {duty_abbr} to {doc_name}")
                else:
                    print(f"Could not add fixed assignment: {doc_name} has no station.")
                continue  # skip further checks

            # ---------- 2. Check fixed values → unavailable ----------
            is_fixed = False
            if val_str in fixed_vals:
                is_fixed = True
            # Check green fill
            if cell.fill and isinstance(cell.fill, PatternFill):
                color = cell.fill.start_color
                if color and color.rgb:
                    rgb = color.rgb
                    if len(rgb) == 8 and rgb.upper().endswith(vacation_color[-6:].upper()):
                        is_fixed = True
                    elif len(rgb) == 6 and rgb.upper() == vacation_color[-6:].upper():
                        is_fixed = True

            if is_fixed:
                model.unavailable.add((doc_name, day_idx))
                print(f"[UNAVAILABLE]: {doc_name} on {model.days[day_idx].date} (fixed value)")
                continue

            # ---------- 3. Check station code ----------
            norm_lower = norm_str.lower()
            if norm_lower in station_code_map:
                station = station_code_map[norm_lower]
                if model.days[day_idx].is_weekend:
                    duty_abbr = 'PR'
                    if station in ['65 PP', '85 Häm/Onk/Rheu', '92 KMT', '65 LAF']:
                        model.fixed_assignments.append((doc_name, day_idx, station, duty_abbr))
                        print(f"[FIXED] (station): {doc_name} must work {duty_abbr} at {station} on {model.days[day_idx].date}")
                        model.doctors[doc_name].preferences.append((day_idx, duty_abbr, 100))
                        continue
                else:
                    duty_abbr = 'ZD'
                model.doctors[doc_name].preferences.append((day_idx, duty_abbr, 50))
                print(f"[WISH] (station): {doc_name} wants {duty_abbr} at {station} on {model.days[day_idx].date} (priority 50)")
            else:
                # Ignore anything else
                print(f"[Ignored]: {doc_name} on {model.days[day_idx].date} has value '{val_str}'")