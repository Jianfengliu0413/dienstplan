"""
demand_builder.py
Computes for each station and day which duties are required.
"""

from models import ScheduleModel
from collections import defaultdict
import pandas as pd 
MAIN_STATIONS = {'65 PP', '65 LAF', '85 Häm/Onk/Rheu', '92 KMT'}
GLOBAL_STATION = 'Global'
GLOBAL_DUTIES = {'HD', 'NAZ', 'SD'}

def build_demand(model: ScheduleModel, config: dict) -> dict:
    demand = defaultdict(lambda: defaultdict(int))

    # --- Read ExcludedStations from Settings ---
    settings_df = config.get('Settings', pd.DataFrame())
    excluded_stations_str = ""
    if not settings_df.empty and 'Setting' in settings_df.columns:
        row = settings_df[settings_df['Setting'] == 'ExcludedStations']
        if not row.empty:
            excluded_stations_str = str(row.iloc[0]['Value'])
    excluded_stations = {s.strip() for s in excluded_stations_str.split(',') if s.strip()}

    # 1. Load base demand from Stations
    station_cfg = config.get('Stations', pd.DataFrame())
    for _, row in station_cfg.iterrows():
        name = str(row['Station']).strip()
        if name not in model.stations:
            continue
        if name in excluded_stations:
            print(f"[Skip] Station '{name}' is excluded – no demand added.")
            continue

        weekday_counts = {}
        weekend_counts = {}

        wd_str = str(row.get('WeekdayDutyCounts', ''))
        if wd_str and wd_str.strip() and wd_str.lower() != 'nan':
            for part in wd_str.split(','):
                if '=' in part:
                    abbr, cnt = part.strip().split('=')
                    # Skip SD for main stations (will be added globally)
                    if abbr == 'SD' and name in MAIN_STATIONS:
                        continue
                    weekday_counts[abbr.strip()] = int(cnt)

        we_str = str(row.get('WeekendDutyCounts', ''))
        if we_str and we_str.strip() and we_str.lower() != 'nan':
            for part in we_str.split(','):
                if '=' in part:
                    abbr, cnt = part.strip().split('=')
                    # Skip HD? We'll let HD be handled by DayDemand or global merging
                    # For now, we don't skip HD; we'll merge later.
                    # But we might also want to skip HD from stations to avoid duplicates.
                    if abbr == 'HD':
                        continue  # skip HD from stations, handled by DayDemand or global
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
            if station in ['GlobalHD', 'GlobalSD']:
                station = GLOBAL_STATION
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
            if station_name in excluded_stations:
                continue
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

    # --- Add global SD duty on weekdays not covered by IMA ---
    for day_idx, day in enumerate(model.days):
        if not day.is_weekend and day_idx not in getattr(model, 'ima_sd_days', set()):
            # Check if there is already a demand for this day? Not needed.
            demand[(day_idx, GLOBAL_STATION)]['SD'] = 1

    # --- Merge HD duties: only one HD per day, set to GlobalHD ---
    # Collect HD demands
    hd_demands = {}
    for (day_idx, station), counts in list(demand.items()):
        if 'HD' in counts:
            hd_demands.setdefault(day_idx, []).append((station, counts['HD']))
            # Remove this HD from demand
            del counts['HD']
            if not counts:
                del demand[(day_idx, station)]
    # Add one HD per day (if there was any demand)
    for day_idx in hd_demands:
        demand[(day_idx, GLOBAL_STATION)]['HD'] = 1  

    # ========== Add fixed assignments to the demand ==========
    if hasattr(model, 'fixed_assignments'):
        for doc_name, day_idx, station, duty_abbr in model.fixed_assignments:
            # Only add if the duty is known and the station exists
            if duty_abbr in model.duty_types and station in model.stations:
                # Ensure at least one slot for this duty on this day/station
                demand[(day_idx, station)][duty_abbr] = max(demand[(day_idx, station)].get(duty_abbr, 0), 1)
            else:
                print(f"[Warning]: Cannot add fixed assignment for {duty_abbr} at {station} – duty or station unknown.")

    # --- Add NAZ demand from wishes file (rows with "NAZ" in column A/B) ---
    if hasattr(model, 'naz_demand_days'):
        for day_idx in model.naz_demand_days:
            # Add one NAZ duty at Global station for that day
            demand[(day_idx, GLOBAL_STATION)]['NAZ'] = max(
                demand[(day_idx, GLOBAL_STATION)].get('NAZ', 0), 1
            )
            print(f"[Demand] Added NAZ on {model.days[day_idx].date} from wishes")

    # 4. SUBSTITUTION LOGIC
    demand = add_substitute_demand(model, demand, excluded_stations)

    return demand

def add_substitute_demand(model: ScheduleModel, demand: dict, excluded_stations: set) -> dict:
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
        if station in excluded_stations:
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
                print(f"SUB needed: {station} on {model.days[day_idx].date} – adding SUB duty.")

    # # --- 强制每个周末每个主站必须有 PR ---
    # for day_idx, day in enumerate(model.days):
    #     if day.is_weekend:
    #         for station_name in MAIN_STATIONS:
    #             # 无论是否存在，强制确保至少一个 PR
    #             demand.setdefault((day_idx, station_name), {})
    #             demand[(day_idx, station_name)]['PR'] = max(
    #                 demand[(day_idx, station_name)].get('PR', 0), 1
    #             )
    #             print(f"[Force PR] {station_name} on {day.date.strftime('%Y-%m-%d')}")
    return demand