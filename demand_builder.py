"""
demand_builder.py
Computes for each station and day which duties are required.
"""

from models import ScheduleModel
from collections import defaultdict
import pandas as pd

NO_SUBSTITUTE_STATIONS = {'Rotation Med I', 'Aufnahme', 'Labor', 'Forschung', 'Elternzeit', 
                          'Balingen','Sprechstunde PP/Oberärzte','Springer/Konsile/Diagnostik',
                          '93 (3 IS)','Amb 1 (Lymphom/allgemein)','Amb 2 (allgemein/Gerinnung)',
                          'Amb 3 (spezialisiert mix)','Amb 4 (Myelom)','KMT 1','KMT 2','Rheuma 1','Rheuma 2','Rheuma 3'
                          }

def build_demand(model: ScheduleModel, config: dict) -> dict:
    demand = defaultdict(lambda: defaultdict(int))

    # 1. Load base demand from Stations
    station_cfg = config.get('Stations', pd.DataFrame())
    for _, row in station_cfg.iterrows():
        name = str(row['Station']).strip()
        if name not in model.stations:
            continue

        weekday_counts = {}
        weekend_counts = {}

        wd_str = str(row.get('WeekdayDutyCounts', ''))
        if wd_str and wd_str.strip() and wd_str.lower() != 'nan':
            for part in wd_str.split(','):
                if '=' in part:
                    abbr, cnt = part.strip().split('=')
                    weekday_counts[abbr.strip()] = int(cnt)

        we_str = str(row.get('WeekendDutyCounts', ''))
        if we_str and we_str.strip() and we_str.lower() != 'nan':
            for part in we_str.split(','):
                if '=' in part:
                    abbr, cnt = part.strip().split('=')
                    weekend_counts[abbr.strip()] = int(cnt)

        if not weekday_counts and not weekend_counts:
            legacy_str = str(row.get('DutyCounts', ''))
            if legacy_str and legacy_str.strip() and legacy_str.lower() != 'nan':
                for part in legacy_str.split(','):
                    if '=' in part:
                        abbr, cnt = part.strip().split('=')
                        weekday_counts[abbr.strip()] = int(cnt)
                        weekend_counts[abbr.strip()] = int(cnt)

        model.stations[name].weekday_demand = weekday_counts
        model.stations[name].weekend_demand = weekend_counts

    # 2. Apply DayDemand overrides
    if 'DayDemand' in config:
        df_day = config['DayDemand']
        if not hasattr(model, '_day_overrides'):
            model._day_overrides = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        for _, row in df_day.iterrows():
            station = str(row['Station']).strip()
            day_name = str(row['DayOfWeek']).strip().lower()
            duty = str(row['DutyType']).strip()
            count = int(row['Count'])
            if station in model.stations:
                model._day_overrides[station][day_name][duty] = count
            else:
                print(f"DayDemand station '{station}' not found – check name.")

    # 3. Build final demand per day
    for day_idx, day in enumerate(model.days):
        day_name = day.date.strftime('%A').lower()
        is_weekend = day.is_weekend

        for station_name, station in model.stations.items():
            if is_weekend:
                counts = station.weekend_demand.copy()
            else:
                counts = station.weekday_demand.copy()

            # Apply DayDemand overrides
            if hasattr(model, '_day_overrides') and station_name in model._day_overrides:
                overrides = model._day_overrides[station_name]
                if day_name in overrides:
                    for duty, cnt in overrides[day_name].items():
                        counts[duty] = cnt

            for duty, cnt in counts.items():
                if cnt > 0:
                    demand[(day_idx, station_name)][duty] += cnt

    # ========== NEW: Add fixed assignments to the demand ==========
    if hasattr(model, 'fixed_assignments'):
        for doc_name, day_idx, station, duty_abbr in model.fixed_assignments:
            # Only add if the duty is known and the station exists
            if duty_abbr in model.duty_types and station in model.stations:
                # Ensure at least one slot for this duty on this day/station
                demand[(day_idx, station)][duty_abbr] = max(demand[(day_idx, station)].get(duty_abbr, 0), 1)
            else:
                print(f"⚠️ Warning: Cannot add fixed assignment for {duty_abbr} at {station} – duty or station unknown.")

    # 4. SUBSTITUTION LOGIC
    demand = add_substitute_demand(model, demand)

    return demand

def add_substitute_demand(model: ScheduleModel, demand: dict) -> dict:
    """
    For each station found in the template, if no doctor from that station is available on a day,
    and the station row does NOT have a '0' on that day, add a SUB duty.
    SUB duties can only be covered by doctors from 65 PP (enforced in constraints).
    """ 
    # Build a set of (day_idx, station) that already have fixed assignments
    fixed_cover = set()
    for doc_name, day_idx, station, abbr in model.fixed_assignments:
        fixed_cover.add((day_idx, station))

    station_doctors = defaultdict(list)
    for doc in model.doctors.values():
        if doc.station:
            station_doctors[doc.station].append(doc.name)

    stations_with_demand = set()
    for (day_idx, station) in demand.keys():
        stations_with_demand.add(station)

    stations_to_check = set(model.found_station_names) | stations_with_demand

    for station in stations_to_check:
        if station in NO_SUBSTITUTE_STATIONS or station == '65 PP':
            continue
        docs = station_doctors.get(station, [])
        if not docs:
            continue
        for day_idx in range(len(model.days)):
            # Skip if already covered by a fixed assignment from another station
            if (day_idx, station) in fixed_cover:
                continue
            zero_days = model.station_zero_days.get(station, set())
            if day_idx in zero_days:
                continue

            # Check if any doctor from this station is available
            available = False
            for doc_name in docs:
                if (doc_name, day_idx) not in model.unavailable:
                    available = True
                    break

            if not available:
                # Check if there is existing demand on this day for this station
                existing_demand = demand.get((day_idx, station), {})
                if not existing_demand:
                    continue
                # Add SUB
                demand[(day_idx, station)]['SUB'] = demand[(day_idx, station)].get('SUB', 0) + 1
                print(f"🔄 SUB needed: {station} on {model.days[day_idx].date} – adding SUB duty.")
    return demand