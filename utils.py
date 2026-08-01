# utils.py
from datetime import datetime

def parse_date_from_excel(val):
    if isinstance(val, datetime):
        return val
    # additional parsing if needed
    return None