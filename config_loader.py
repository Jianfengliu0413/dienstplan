# config_loader.py

import pandas as pd
from typing import Dict, Any, List

def load_config(config_path: str) -> Dict[str, pd.DataFrame]:
    """Load all sheets from Rules.xlsx into a dict of DataFrames."""
    xl = pd.ExcelFile(config_path)
    return {sheet: pd.read_excel(xl, sheet_name=sheet, header=0) for sheet in xl.sheet_names}

def load_working_hours(config_path: str, doctors: List[str]) -> Dict[str, float]:
    try:
        df = pd.read_excel(config_path, sheet_name='WorkingHours', index_col=0)
        hours = {}
        for doc in doctors:
            hours[doc] = df.loc[doc, 'Hours'] if doc in df.index else 0.0
        return hours
    except:
        # Sheet doesn't exist or empty
        return {doc: 0.0 for doc in doctors}