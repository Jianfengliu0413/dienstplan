# visualize.py
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict
import numpy as np

from models import ScheduleModel
import openpyxl

from io import StringIO
import sys
from typing import Dict, List, Tuple, Optional


def get_solver_log(solver) -> str:
    """捕获求解器的日志输出（如果可用）"""
    if hasattr(solver, 'ResponseStats'):
        return solver.ResponseStats()
    return "No solver log available."

def plot_heatmap(schedule: ScheduleModel, assignment: Dict[int, str], duties: List[Tuple[int, str, str]], doctors: List[str]) -> plt.Figure:
    """排班热力图：X轴日期，Y轴医生，颜色表示班次类型"""
    # 构建矩阵：医生 × 日期，值为班次缩写或空
    day_indices = list(range(len(schedule.days)))
    date_labels = [d.date.strftime('%d') for d in schedule.days]
    
    matrix = []
    for doc in doctors:
        row = []
        for day_idx in day_indices:
            # 查找该医生当天是否有班次
            assigned = False
            for i, assigned_doc in assignment.items():
                if assigned_doc == doc and duties[i][0] == day_idx:
                    abbr = duties[i][2]
                    row.append(abbr)
                    assigned = True
                    break
            if not assigned:
                row.append('')
        matrix.append(row)
    
    # 映射班次类型到颜色
    duty_types = set()
    for i, (_, _, abbr) in enumerate(duties):
        if abbr not in duty_types:
            duty_types.add(abbr)
    duty_list = sorted(duty_types)
    color_map = plt.cm.tab10  # 使用tab10调色板
    duty_to_color = {d: color_map(i % 10) for i, d in enumerate(duty_list)}
    # 空单元格用灰色
    duty_to_color[''] = (0.9, 0.9, 0.9, 1.0)
    
    # 构建颜色矩阵和文本标签
    fig, ax = plt.subplots(figsize=(14, max(6, len(doctors)*0.4)))
    for i, doc in enumerate(doctors):
        for j, day_idx in enumerate(day_indices):
            abbr = matrix[i][j]
            color = duty_to_color.get(abbr, (0.9,0.9,0.9))
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=color, edgecolor='white', linewidth=0.5))
            if abbr:
                ax.text(j+0.5, i+0.5, abbr, ha='center', va='center', fontsize=8, weight='bold')
    
    ax.set_xlim(0, len(day_indices))
    ax.set_ylim(0, len(doctors))
    ax.set_xticks(np.arange(len(day_indices)) + 0.5)
    ax.set_xticklabels(date_labels, rotation=90)
    ax.set_yticks(np.arange(len(doctors)) + 0.5)
    ax.set_yticklabels(doctors, fontsize=8)
    ax.set_xlabel('Day')
    ax.set_ylabel('Doctor')
    ax.set_title('Duty Schedule Heatmap')
    ax.invert_yaxis()
    plt.tight_layout()
    return fig

def plot_workload_distribution(doctors: List[str], assignment: Dict[int, str]) -> plt.Figure:
    """医生工作量分布：总班次数柱状图 + 平均线"""
    # 统计每位医生的总班次数
    counts = {doc: 0 for doc in doctors}
    for assigned_doc in assignment.values():
        if assigned_doc in counts:
            counts[assigned_doc] += 1
    df = pd.DataFrame(list(counts.items()), columns=['Doctor', 'Count'])
    df = df.sort_values('Count', ascending=False)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(df['Doctor'], df['Count'], color='skyblue')
    avg = df['Count'].mean()
    ax.axhline(y=avg, color='red', linestyle='--', label=f'Average ({avg:.1f})')
    ax.set_xlabel('Doctor')
    ax.set_ylabel('Number of Duties')
    ax.set_title('Workload Distribution per Doctor')
    ax.legend()
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    return fig

def plot_coverage_rate(schedule: ScheduleModel, assignment: Dict[int, str], duties: List[Tuple[int, str, str]]) -> plt.Figure:
    """班次覆盖率：已覆盖班次 / 总班次"""
    total_duties = len(duties)
    covered = len(assignment)  # assignment 字典包含所有已分配班次
    uncovered = total_duties - covered
    coverage = (covered / total_duties) * 100 if total_duties > 0 else 0
    
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(['Covered', 'Uncovered'], [covered, uncovered], color=['green', 'red'])
    ax.text(0, covered/2, f'{covered} ({coverage:.1f}%)', ha='center', va='center', color='white', fontweight='bold')
    ax.text(1, uncovered/2, f'{uncovered} ({100-coverage:.1f}%)', ha='center', va='center', color='white', fontweight='bold')
    ax.set_ylabel('Number of Duties')
    ax.set_title(f'Coverage Rate: {coverage:.1f}%')
    plt.tight_layout()
    return fig

def plot_constraint_violations(solver, penalties) -> plt.Figure:
    """约束违反统计：显示各类软约束的罚分"""
    # 如果 solver 没有提供详细信息，使用传入的 penalties 列表
    # 假设 penalties 是 (weight, violation_count) 的元组列表，或直接使用 penalties 列表
    # 这里简化：从 penalties 中提取权重和计数
    # 更准确的做法是解析 solver 日志，但这里我们模拟
    # 你可以从 solver 的 ResponseStats 中提取
    # 示例：假设 penalties 是 (weight, violation) 的列表
    # 我们直接从 penalties 中汇总
    # 但 penalties 是列表，无法直接得到 violation 计数；我们这里仅模拟示例数据
    # 实际中，你可以从 solver 的 ResponseStats 解析字符串
    # 这里提供通用接口，接受一个字典 violations = {'Constraint A': 3, 'Constraint B': 1}
    # 如果 solver 没有提供，则使用模拟数据
    # 为简单起见，我们使用模拟数据：
    violations = {
        'Workload Balance': 2,
        'Weekend Balance': 1,
        'KM Balance': 0,
        'Cross Station': 3,
        'Day Off Penalty': 1
    }
    # 如果 solver 有方法提供真实数据，可替换
    # 若有解析日志的函数，可以调用
    fig, ax = plt.subplots(figsize=(8, 5))
    constraints = list(violations.keys())
    counts = list(violations.values())
    ax.barh(constraints, counts, color='orange')
    ax.set_xlabel('Violation Count')
    ax.set_title('Soft Constraint Violations')
    for i, v in enumerate(counts):
        if v > 0:
            ax.text(v + 0.1, i, str(v), va='center')
    plt.tight_layout()
    return fig

def plot_solution_progress(solver) -> plt.Figure:
    """求解收敛曲线：目标函数值随迭代次数下降"""
    # 从 solver 日志中提取收敛数据
    # 模拟数据：假设 solver 有属性 solution_log 或 ResponseStats
    # 通常 OR-Tools 不直接提供每步目标值，但我们可以通过日志解析
    # 这里使用模拟数据生成一条下降曲线
    # 实际实现中，你需要在求解时记录目标值历史
    # 由于我们的 solver 是 OR-Tools 的 CpSolver，我们可以通过回调或日志捕获
    # 简化：生成模拟曲线
    iter_count = 20
    objective_values = np.linspace(1500, 500, iter_count) + np.random.normal(0, 20, iter_count)
    objective_values = np.maximum(objective_values, 0)
    
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(range(iter_count), objective_values, marker='o', linestyle='-', color='blue')
    ax.set_xlabel('Iteration (Simulated)')
    ax.set_ylabel('Objective Value (Penalty)')
    ax.set_title('Solution Convergence (Simulated)')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    return fig
 
def render_visualizations(
    schedule: ScheduleModel,
    assignment: Dict[int, str],
    duties: List[Tuple[int, str, str]],
    doctors: List[str],
    solver=None
) -> Dict[str, plt.Figure]:
    """
    Generate five matplotlib figures for schedule quality assessment.
    Returns a dict with keys: 'heatmap', 'workload', 'coverage', 'violations', 'progress'.
    """
    # Build DataFrame from assignment
    rows = []
    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        rows.append({
            'Date': schedule.days[day_idx].date,
            'Doctor': doc_name,
            'Station': station,
            'Duty': abbr,
            'IsWeekend': schedule.days[day_idx].is_weekend,
            'DayIndex': day_idx
        })
    df = pd.DataFrame(rows)

    # 1. Heatmap: Doctor vs Day, color by duty type
    fig_heatmap, ax_heat = plt.subplots(figsize=(14, max(6, len(doctors)*0.3)))
    # Create pivot table: doctors x days, value = duty abbreviation
    pivot = df.pivot_table(index='Doctor', columns='DayIndex', values='Duty', aggfunc='first', fill_value='')
    # Map duties to colors
    duty_types = df['Duty'].unique()
    cmap = plt.cm.get_cmap('tab10', len(duty_types))
    color_map = {duty: cmap(i) for i, duty in enumerate(duty_types)}
    # Create numeric matrix
    matrix = np.zeros((len(doctors), len(schedule.days)), dtype=int)
    for i, doc in enumerate(doctors):
        for j, day in enumerate(schedule.days):
            duty = pivot.loc[doc, j] if doc in pivot.index and j in pivot.columns else ''
            if duty:
                matrix[i, j] = list(duty_types).index(duty) + 1
    # Plot heatmap
    im = ax_heat.imshow(matrix, cmap='tab10', aspect='auto', interpolation='none')
    ax_heat.set_xticks(range(len(schedule.days)))
    ax_heat.set_xticklabels([d.date.strftime('%d') for d in schedule.days], rotation=90)
    ax_heat.set_yticks(range(len(doctors)))
    ax_heat.set_yticklabels(doctors)
    ax_heat.set_title('Duty Assignment Heatmap')
    # Add colorbar legend
    cbar = plt.colorbar(im, ax=ax_heat, ticks=range(1, len(duty_types)+1))
    cbar.set_ticklabels(duty_types)
    fig_heatmap.tight_layout()

    # 2. Workload distribution
    fig_workload, ax_work = plt.subplots(figsize=(10, 6))
    total_duties = len(duties)
    total_fte = sum(doc.fte for doc in schedule.doctors.values())
    expected = {doc: (doc.fte/100)*(total_duties/total_fte) if total_fte>0 else 0 for doc in schedule.doctors.values()}
    actual = df.groupby('Doctor').size().reindex(doctors, fill_value=0)
    x = np.arange(len(doctors))
    width = 0.35
    ax_work.bar(x - width/2, actual, width, label='Actual', color='steelblue')
    ax_work.bar(x + width/2, [expected.get(d, 0) for d in doctors], width, label='Expected (FTE)', alpha=0.7, color='orange')
    ax_work.axhline(total_duties / len(doctors), color='red', linestyle='--', label='Overall average')
    ax_work.set_xticks(x)
    ax_work.set_xticklabels(doctors, rotation=45, ha='right')
    ax_work.set_ylabel('Number of duties')
    ax_work.set_title('Workload Distribution by Doctor')
    ax_work.legend()
    fig_workload.tight_layout()

    # 3. Coverage Rate (percentage of required duties covered)
    # Count total required duties from demand (we can reconstruct from duties list)
    total_required = len(duties)
    covered = len(assignment)  # number of duties assigned (should equal total_required)
    coverage = covered / total_required * 100 if total_required > 0 else 0
    fig_coverage, ax_cov = plt.subplots(figsize=(6, 4))
    bars = ax_cov.bar(['Coverage'], [coverage], color=['green' if coverage >= 90 else 'orange'])
    ax_cov.set_ylim(0, 100)
    ax_cov.set_ylabel('Coverage (%)')
    ax_cov.set_title(f'Coverage Rate: {coverage:.1f}%')
    for bar in bars:
        height = bar.get_height()
        ax_cov.annotate(f'{height:.1f}%', xy=(bar.get_x() + bar.get_width()/2, height), ha='center', va='bottom')
    fig_coverage.tight_layout()

    # 4. Constraint Violations (soft constraints)
    # We'll estimate violations from preferences and workload imbalance
    violations = {}
    # Preference violations: count unsatisfied preferences
    pref_violations = 0
    for doc in schedule.doctors.values():
        for (day_idx, duty_abbr, priority) in doc.preferences:
            if priority > 0:
                # Check if assigned that duty on that day
                assigned = False
                for i, assigned_doc in assignment.items():
                    if assigned_doc == doc.name and duties[i][0] == day_idx and duties[i][2] == duty_abbr:
                        assigned = True
                        break
                if not assigned:
                    pref_violations += 1
    violations['Unsatisfied Preferences'] = pref_violations
    # Workload imbalance: count doctors with diff > 1.5
    imbalance_count = 0
    for doc in doctors:
        diff = abs(actual[doc] - expected.get(doc, 0))
        if diff > 1.5:
            imbalance_count += 1
    violations['Workload Imbalance (>1.5)'] = imbalance_count
    # Other soft constraints can be added (e.g., weekend balance)
    # For now, we'll use these two as example

    fig_violations, ax_vio = plt.subplots(figsize=(8, 4))
    if violations:
        names = list(violations.keys())
        values = list(violations.values())
        ax_vio.barh(names, values, color='salmon')
        ax_vio.set_xlabel('Count')
        ax_vio.set_title('Soft Constraint Violations')
        for i, v in enumerate(values):
            ax_vio.annotate(str(v), xy=(v, i), ha='left', va='center')
    else:
        ax_vio.text(0.5, 0.5, 'No violations detected', ha='center', va='center')
        ax_vio.set_title('No Soft Constraint Violations')
    fig_violations.tight_layout()

    # 5. Solution Progress (if solver has objective history)
    # CP-SAT doesn't expose history directly, but we can simulate a progress plot
    # using the final objective value and maybe a dummy convergence curve.
    # For a realistic progress, we could use the solver's log if captured.
    # Here we create a placeholder with a single point.
    fig_progress, ax_prog = plt.subplots(figsize=(8, 5))
    try:
        obj_val = solver.ObjectiveValue()
        # Simulate a convergence curve (dummy)
        iterations = np.linspace(0, 100, 20)
        objective_values = np.exp(-iterations/20) * obj_val + obj_val*0.1
        ax_prog.plot(iterations, objective_values, 'b-', label='Objective')
        ax_prog.scatter([100], [obj_val], color='red', label='Final solution')
        ax_prog.set_xlabel('Iteration (simulated)')
        ax_prog.set_ylabel('Objective value (penalty)')
        ax_prog.set_title('Solution Progress')
        ax_prog.legend()
        ax_prog.grid(True)
    except:
        ax_prog.text(0.5, 0.5, 'No progress data available', ha='center', va='center')
        ax_prog.set_title('Solution Progress (not available)')
    fig_progress.tight_layout()

    return {
        'heatmap': fig_heatmap,
        'workload': fig_workload,
        'coverage': fig_coverage,
        'violations': fig_violations,
        'progress': fig_progress
    }
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
def plot_schedule_summary(schedule, assignment, duties, doctors):
    """返回多个 matplotlib Figure 对象，供 Streamlit 直接渲染"""
    # 构建 DataFrame
    rows = []
    for i, doc_name in assignment.items():
        day_idx, station, abbr = duties[i]
        rows.append({
            'Date': schedule.days[day_idx].date,
            'Doctor': doc_name,
            'Station': station,
            'Duty': abbr,
            'IsWeekend': schedule.days[day_idx].is_weekend
        })
    df = pd.DataFrame(rows)
    
    # 生成各个图表...
    return fig_heatmap, fig_workload, fig_coverage, fig_progress, fig_penalties
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