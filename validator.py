"""
validator.py
Checks data integrity before solving.
"""

from models import ScheduleModel, Station
from demand_builder import build_demand
import pandas as pd

def validate(model: ScheduleModel, config: dict) -> list:
    errors = []
    
    # --- Ensure all stations from doctors exist in model.stations ---
    # If not, add them with empty demand to avoid errors
    for doc in model.doctors.values():
        if doc.station and doc.station not in model.stations:
            # Add station with no demand (assume it's a valid station)
            model.stations[doc.station] = Station(name=doc.station, requires_senior=False)
    
    # Check each doctor has at least one skill
    for doc in model.doctors.values():
        if not doc.skills:
            errors.append(f"Doctor {doc.name} has no skills defined.")
        # Now station existence is guaranteed
        if doc.station and doc.station not in model.stations:
            # This shouldn't happen now, but keep for safety
            errors.append(f"Doctor {doc.name} assigned to unknown station {doc.station}.")
    
    # Check duty types referenced in demand exist
    demand = build_demand(model, config)
    for (_, st_name), duties in demand.items():
        for abbr in duties:
            if abbr not in model.duty_types:
                errors.append(f"Duty {abbr} used in demand for station {st_name} but not defined.")
    
    # Check that every station with demand has at least one doctor
    stations_with_demand = set([st for (_, st) in demand.keys()])
    for st_name in stations_with_demand:
        if st_name != 'Global':
            doctors_in_station = [doc for doc in model.doctors.values() if doc.station == st_name]
            if not doctors_in_station:
                errors.append(f"Station '{st_name}' has duty demand but no doctors are assigned to it.")
    
    # Check preferences reference valid duties and days
    for doc in model.doctors.values():
        for day_idx, abbr, _ in doc.preferences:
            if day_idx >= len(model.days):
                errors.append(f"Doctor {doc.name} preference day index {day_idx} out of range.")
            if abbr not in model.duty_types:
                errors.append(f"Doctor {doc.name} preference uses unknown duty {abbr}.")
        if doc.station and doc.station in stations_with_demand:
            if not doc.skills:
                errors.append(f"Doctor {doc.name} is assigned to station '{doc.station}' which has duty demand, but has no skills defined.")
        # If station is not in demand, we don't care about skills.
    
    # Check no duplicate doctor names
    names = [d.name for d in model.doctors.values()]
    if len(set(names)) != len(names):
        errors.append("Duplicate doctor names found.")
    
    return errors 