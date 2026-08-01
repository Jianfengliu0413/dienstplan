# visualize.py
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict
import numpy as np
from typing import Dict, List, Tuple
from models import ScheduleModel
import openpyxl

def visualize_schedule(
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    output_path: str = None
):
    """
    Generate visualizations and save them as PNG files.
    If output_path is given, saves plots there; otherwise shows them.
    """
    # Build a DataFrame from the assignment
    rows = []
    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        date = schedule.days[day_idx].date
        rows.append({
            'Date': date,
            'Doctor': doc_name,
            'Station': station,
            'Duty': abbr,
            'Weekday': date.strftime('%A'),
            'IsWeekend': schedule.days[day_idx].is_weekend
        })
    df = pd.DataFrame(rows)

    # 1. Workload balance: total duties per doctor vs expected
    total_duties = len(duties)
    total_fte = sum(doc.fte for doc in schedule.doctors.values())
    expected = {}
    for doc in schedule.doctors.values():
        expected[doc.name] = (doc.fte / 100) * (total_duties / total_fte) if total_fte > 0 else 0

    actual = df.groupby('Doctor').size().reindex(doctors, fill_value=0)

    # Bar chart
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(doctors))
    width = 0.35
    ax.bar(x - width/2, actual, width, label='Actual')
    ax.bar(x + width/2, [expected.get(d, 0) for d in doctors], width, label='Expected (FTE-based)', alpha=0.7)
    ax.set_xlabel('Doctor')
    ax.set_ylabel('Number of duties')
    ax.set_title('Workload Balance (Total Duties)')
    ax.set_xticks(x)
    ax.set_xticklabels(doctors, rotation=45, ha='right')
    ax.legend()
    plt.tight_layout()
    if output_path:
        plt.savefig(f'{output_path}_workload.png', dpi=150, bbox_inches='tight')
    else:
        plt.show()
    plt.close()

    # 2. Duty type distribution (stacked bar per doctor)
    duty_pivot = df.pivot_table(index='Doctor', columns='Duty', aggfunc='size', fill_value=0).reindex(doctors, fill_value=0)
    if not duty_pivot.empty:
        fig, ax = plt.subplots(figsize=(12, 6))
        duty_pivot.plot(kind='bar', stacked=True, ax=ax)
        ax.set_title('Duty Type Distribution per Doctor')
        ax.set_xlabel('Doctor')
        ax.set_ylabel('Count')
        ax.legend(title='Duty')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        if output_path:
            plt.savefig(f'{output_path}_duty_types.png', dpi=150, bbox_inches='tight')
        else:
            plt.show()
        plt.close()

    # 3. Weekend duties per doctor
    weekend_df = df[df['IsWeekend']]
    weekend_counts = weekend_df.groupby('Doctor').size().reindex(doctors, fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 5))
    weekend_counts.plot(kind='bar', ax=ax, color='orange')
    ax.set_title('Weekend Duties per Doctor')
    ax.set_xlabel('Doctor')
    ax.set_ylabel('Number of weekend duties')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    if output_path:
        plt.savefig(f'{output_path}_weekend.png', dpi=150, bbox_inches='tight')
    else:
        plt.show()
    plt.close()

    # 4. KM rotation: number of KM duties per doctor
    km_df = df[df['Duty'] == 'KM']
    km_counts = km_df.groupby('Doctor').size().reindex(doctors, fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 5))
    km_counts.plot(kind='bar', ax=ax, color='green')
    ax.set_title('KM Duties per Doctor (should be balanced)')
    ax.set_xlabel('Doctor')
    ax.set_ylabel('Number of KM duties')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    if output_path:
        plt.savefig(f'{output_path}_km.png', dpi=150, bbox_inches='tight')
    else:
        plt.show()
    plt.close()

    # 5. KM timeline: which doctor on which Monday/Tuesday
    if not km_df.empty:
        km_timeline = km_df.pivot_table(index='Date', columns='Doctor', aggfunc='size', fill_value=0)
        fig, ax = plt.subplots(figsize=(12, 4))
        km_timeline.plot(kind='bar', stacked=True, ax=ax, legend=False)
        ax.set_title('KM Duties Timeline (weekly rotation)')
        ax.set_xlabel('Date')
        ax.set_ylabel('KM count')
        plt.xticks(rotation=45)
        # Add legend manually
        handles = [mpatches.Patch(color=plt.cm.tab10(i), label=d) for i, d in enumerate(km_timeline.columns)]
        ax.legend(handles=handles, bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.tight_layout()
        if output_path:
            plt.savefig(f'{output_path}_km_timeline.png', dpi=150, bbox_inches='tight')
        else:
            plt.show()
        plt.close()

    # 6. Calendar heatmap (optional)
    # Create a matrix: doctors vs days, values = duty code (or just 1 for any duty)
    day_list = sorted(schedule.day_col.keys(), key=lambda col: schedule.day_col[col])
    # We'll use the day index as column
    heatmap_data = pd.DataFrame(0, index=doctors, columns=range(len(schedule.days)))
    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        heatmap_data.loc[doc_name, day_idx] = 1  # or encode duty type?
    # Plot as heatmap
    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.imshow(heatmap_data.values, cmap='Blues', aspect='auto')
    ax.set_xticks(range(len(schedule.days)))
    ax.set_xticklabels([d.date.strftime('%d') for d in schedule.days], rotation=90)
    ax.set_yticks(range(len(doctors)))
    ax.set_yticklabels(doctors)
    ax.set_title('Duty Assignment Heatmap (grey = no duty)')
    plt.tight_layout()
    if output_path:
        plt.savefig(f'{output_path}_heatmap.png', dpi=150, bbox_inches='tight')
    else:
        plt.show()
    plt.close()

    print(f"Visualizations saved to {output_path}_*.png" if output_path else "Visualizations displayed.")

if __name__ == "__main__":
    # Example usage: run this script standalone by loading the output Excel
    # (This is optional; you can also call it from scheduler.py)
    import sys
    if len(sys.argv) < 2:
        print("Usage: python visualize.py <output_excel_path>")
        sys.exit(1)
    # We need to re-parse the model; but for simplicity, we assume the scheduler passes the data.
    # To keep it simple, we recommend calling this from scheduler.py after generating the schedule.
    print("Please call this function from within scheduler.py after generating the schedule.")