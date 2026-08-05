# models.py
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set, Tuple
from datetime import datetime

@dataclass
class Doctor:
    name: str
    fte: int = 100                     # 0‑100
    station: Optional[str] = None
    skills: Set[str] = field(default_factory=set)   # duty abbreviations they can do
    preferences: List[tuple] = field(default_factory=list)  # (day_idx, duty_abbr, priority)
    weekend_available: bool = True
    allow_92_kmt: bool = False
    allow_naz: bool = False
    

@dataclass
class DutyType:
    abbr: str
    fullname: str
    requires_senior: bool = False
    weekend_only: bool = False
    priority: int = 1                  # higher = more important to satisfy
    hours: float = 8.5

@dataclass
class Station:
    name: str
    requires_senior: bool = False      # all duties at this station require senior?
    demand: Dict[str, int] = field(default_factory=dict)       # fallback (if no weekday/weekend)
    weekday_demand: Dict[str, int] = field(default_factory=dict)
    weekend_demand: Dict[str, int] = field(default_factory=dict)

@dataclass
class Day:
    date: datetime
    weekday: str
    is_weekend: bool = False

@dataclass
class ScheduleModel:
    doctors: Dict[str, Doctor] = field(default_factory=dict)
    duty_types: Dict[str, DutyType] = field(default_factory=dict)
    stations: Dict[str, Station] = field(default_factory=dict)
    days: List[Day] = field(default_factory=list)
    # mapping from doctor name to row index in template
    doctor_row: Dict[str, int] = field(default_factory=dict)
    # mapping from day index to column index
    day_col: Dict[int, int] = field(default_factory=dict)
    fixed_cells: Set[tuple] = field(default_factory=set)  # (row, col) not to touch
    editable_cells: Set[tuple] = field(default_factory=set) # (row, col) we can fill
    # vacation / unavailable: (doctor_name, day_idx)
    unavailable: Set[tuple] = field(default_factory=set)
    sheet_name: str = ""   # <--- ADD THIS LINE
    found_station_names: Set[str] = field(default_factory=set)   # for writing config
    fixed_assignments: List[Tuple[str, int, str, str]] = field(default_factory=list)  # (doctor, day_idx, station, duty_abbr)
    # In models.py, add to ScheduleModel
    station_zero_days: Dict[str, Set[int]] = field(default_factory=dict)  # station -> set of day_idx where row has '0'
    ima_sd_days: Set[int] = field(default_factory=set)  # days where IMA covers SD