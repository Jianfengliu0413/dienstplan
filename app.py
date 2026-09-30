"""
260801: v001
"""

import hashlib
import os
import tempfile
import traceback
from datetime import datetime
import shutil
from pathlib import Path
import pandas as pd
import streamlit as st

from scheduler import run_scheduler, write_missing_config_sheets, RULES_FILE
from config_loader import load_config


# ------------------------------------------------------------------
# Page config
# ------------------------------------------------------------------
st.set_page_config(
    page_title="IM2 Dienstplan",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------
# RULES_FILE = "Rules_updated.xlsx"
INACTIVITY_TIMEOUT_SECONDS = 300
PROJECT_ROOT = Path(__file__).resolve().parent

# ------------------------------------------------------------------
# Custom CSS
# ------------------------------------------------------------------
st.markdown(
    """
<style>
    .stApp { background-color: #f4f6f9; }

    .custom-card {
        background: white;
        padding: 1.8rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.06);
        margin-bottom: 1.5rem;
        border: 1px solid #e9ecef;
    }

    header {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        min-height: 0rem !important;
    }
    .stApp header { padding: 0.2rem 0rem !important; height: auto !important; }
    .main > div { padding-top: 0.1rem !important; }

    .css-1d391kg, .stSidebar, [data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1px solid #dee2e6 !important;
        color: #1a1a2e !important;
    }

    h1, h2, h3 { color: #1a1a2e; font-weight: 400; }

    .stButton button {
        background-color: #2E86C1;
        color: white !important;
        font-weight: 500;
        border-radius: 6px;
        border: none;
        padding: 0.5rem 1.5rem;
        transition: all 0.2s;
    }
    .stButton button:hover {
        background-color: #1a5276;
        box-shadow: 0 2px 8px rgba(46,134,193,0.3);
        transform: translateY(-1px);
    }

    .status-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #1a1a2e !important;
    }
    .status-loaded  { background: #d4edda !important; color: #155724 !important; }
    .status-missing { background: #f8d7da !important; color: #721c24 !important; }

    .stAlert .stMarkdown,
    .stAlert .stMarkdown strong { color: #1a1a2e !important; }
    .stAlert { padding: 0.5rem 1rem !important; }

    .footer {
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 1px solid #dee2e6;
        text-align: center;
        color: #6c757d;
        font-size: 0.8rem;
    }
    .footer a { color: #2E86C1 !important; }

    #MainMenu, footer { visibility: hidden; }
    .stDeployButton,
    .stAppDeployButton,
    .stApp [data-testid="stToolbar"],
    .stApp [data-testid="stHeaderManageApp"],
    .stApp [data-testid="stHeaderAppMenu"],
    .stApp [data-testid="stHeaderGitHub"],
    .stApp [data-testid="stHeaderFork"] { display: none !important; }
    .stApp header a[href*="github"] { display: none !important; }

    .stSidebar .stMarkdown,
    .stSidebar .stText,
    .stSidebar label { color: #1a1a2e !important; }

    .stMarkdown, .stText, .stCaption,
    .stInfo, .stWarning, .stError, .stSuccess { color: #1a1a2e !important; }

    [data-testid="stMetricValue"] { color: #1a1a2e !important; }
    [data-testid="stMetricLabel"] { color: #6c757d !important; }

    .stTabs [data-baseweb="tab-list"],
    .stTabs [data-baseweb="tab"] { color: #1a1a2e !important; }
    .streamlit-expanderHeader { color: #1a1a2e !important; }
    .stFileUploader label { color: #1a1a2e !important; }

    .st-emotion-cache-1v0mbdj { display: none !important; }
    .st-emotion-cache-1r6slb0 { display: none !important; }
</style>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _safe_unlink(path: str) -> None:
    """Delete a file, ignoring errors."""
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _cleanup_session() -> None:
    """Delete every temp file this session created, then clear state."""
    _safe_unlink(RULES_FILE)
    for key in ("template_path", "wishes_path"):
        _safe_unlink(st.session_state.get(key))
    st.session_state.clear()

# ------------------------------------------------------------------
# Cache cleanup
# ------------------------------------------------------------------

def _purge_pycache(root: Path = PROJECT_ROOT) -> int:
    """
    Recursively delete every __pycache__ directory under `root`.
    Returns the number of directories removed.

    Equivalent to:
        find . -type d -name __pycache__ -exec rm -rf {} +
    """
    removed = 0
    for pycache in root.rglob("__pycache__"):
        if not pycache.is_dir():
            continue
        try:
            shutil.rmtree(pycache, ignore_errors=True)
            removed += 1
        except Exception:
            pass
    return removed

def _ensure_clean_startup() -> None:
    """
    On the very first run of a new session:
      - delete any leftover Rules_edit.xlsx on disk
      - sweep orphan temp files created by *previous* sessions
      - initialise session_state
    """
    if "initialized" in st.session_state:
        return

    # purge Python bytecode caches once per session
    n = _purge_pycache()
    if n:
        print(f"[startup] removed {n} __pycache__ dir(s)")

    _safe_unlink(RULES_FILE)

    # Sweep orphan temp xlsx files created by previous crashed sessions
    tmp_dir = tempfile.gettempdir()
    try:
        for name in os.listdir(tmp_dir):
            if name.startswith("tmp") and name.endswith(".xlsx"):
                # Only delete files older than 1 hour to avoid touching active sessions
                fpath = os.path.join(tmp_dir, name)
                try:
                    if os.path.getmtime(fpath) < (datetime.now().timestamp() - 3600):
                        os.unlink(fpath)
                except OSError:
                    pass
    except OSError:
        pass

    st.session_state["initialized"] = True
    st.session_state["rules_file_path"] = RULES_FILE
    st.session_state["template_path"] = None
    st.session_state["template_name"] = None
    st.session_state["wishes_path"] = None
    st.session_state["config_loaded"] = False
    st.session_state["output_file"] = None
    st.session_state["file_hashes"] = {}
    st.session_state["log_output"] = None
    st.session_state["last_activity"] = datetime.now()


def _touch_activity() -> bool:
    """
    Update last_activity. Return True if the session has expired.
    """
    last = st.session_state.get("last_activity")
    now = datetime.now()
    if last is not None:
        if (now - last).total_seconds() > INACTIVITY_TIMEOUT_SECONDS:
            _cleanup_session()
            return True
    st.session_state["last_activity"] = now
    return False


def _load_config_cached(path: str, file_hash: str):
    """Load config only when the file's hash changes."""
    return _cached_load_config(path, file_hash)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_load_config(path: str, file_hash: str):
    """Cache config per (path, hash). Returns a copy each call."""
    return load_config(path)


def _build_default_output_name() -> str:
    """Template base name + today's YYYYMMDD suffix."""
    template_name = st.session_state.get("template_name")
    base = os.path.splitext(template_name)[0] if template_name else "Stationsplan"
    return f"{base}_{datetime.now().strftime('%Y%m%d')}.xlsx"


# ------------------------------------------------------------------
# Session init (also cleans stale files)
# ------------------------------------------------------------------
_ensure_clean_startup()

if _touch_activity():
    st.rerun()


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Upload Files (click or drag files)")

    # ---------- Rules ----------
    rules_file = st.file_uploader("Rules.xlsx", type=["xlsx"])
    if rules_file is not None:
        with open(RULES_FILE, "wb") as f:
            f.write(rules_file.getvalue())
        st.session_state["rules_file_path"] = RULES_FILE
        st.session_state["config_loaded"] = True
        st.session_state["file_hashes"]["rules"] = hashlib.md5(
            rules_file.getvalue()
        ).hexdigest()

    # ---------- Template ----------
    template_file = st.file_uploader(
        "Stationsplan (.xlsx)",
        type=["xlsx"],
        help="Monthly station plan template for the target month.",
    )
    if template_file is not None:
        # Delete the previous temp file to avoid accumulating garbage
        _safe_unlink(st.session_state.get("template_path"))

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(template_file.getvalue())
            st.session_state["template_path"] = tmp.name
            st.session_state["template_name"] = template_file.name
            st.session_state["file_hashes"]["template"] = hashlib.md5(
                template_file.getvalue()
            ).hexdigest()

    # ---------- Wishes ----------
    wishes_file = st.file_uploader("Wishes (optional)", type=["xlsx"])
    if wishes_file is not None:
        _safe_unlink(st.session_state.get("wishes_path"))

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(wishes_file.getvalue())
            st.session_state["wishes_path"] = tmp.name
            st.session_state["file_hashes"]["wishes"] = hashlib.md5(
                wishes_file.getvalue()
            ).hexdigest()

    # ---------- Status ----------
    st.markdown("---")
    st.markdown("### Status")

    def _badge(label: str, ok: bool, loaded_text="Loaded", missing_text="Not loaded"):
        cls = "status-loaded" if ok else "status-missing"
        text = loaded_text if ok else missing_text
        st.markdown(
            f"**{label}** <span class='status-badge {cls}'>{text}</span>",
            unsafe_allow_html=True,
        )

    _badge("Rules", st.session_state["config_loaded"])
    _badge("Template", bool(st.session_state["template_path"]))
    _badge("Wishes", bool(st.session_state["wishes_path"]),
           loaded_text="Loaded", missing_text="Not set")

    st.markdown("---")

    if st.button("Reset All", use_container_width=True):
        _cleanup_session()
        st.rerun()


# ------------------------------------------------------------------
# Welcome page (no Rules uploaded yet)
# ------------------------------------------------------------------
if not st.session_state["config_loaded"]:
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 1rem;">
            <h3 style="color: #1a1a2e; font-weight: 700; font-size: 1.8rem; margin: 0.2rem 0;">IM2 Dienstplan</h3>
            <hr style="width: 200px; border: 1px solid #2E86C1; margin: 0rem auto;">hospital shift schu(beta version)</hr>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.error(
        """
        ### Data Privacy and Security
        Once you upload a valid Rules file (in sidebar), this page will be replaced
        with the full featured interface.
        """
    )
    st.info(
        """
        **Confidential - Internal Use Only**
        This system is for authorised personnel only. All data processed through this
        application is sensitive and must be handled in compliance with applicable
        data protection regulations.
        - All file uploads are not stored on any external server (not connected to any
          external databases or cloud storage).
        - Temporary files are automatically deleted after your session ends.
        - For any technical issues, please contact JF (TEL: xxxxx61369).
        """
    )

    st.markdown(
        """
        ### Getting Started
        To begin, please follow these steps:
        1.  Upload your configuration - Rules.xlsx file in the sidebar. This file
            contains all rules, doctors, stations, duties ...
        2.  Upload the monthly template - The Stationsplan Excel file for the target
            month (e.g., xxxstationsplanxxx.xlsx).
        3.  Upload doctor's wishes - (optional).
        4.  Run the scheduler - Click Generate Schedule and wait for the optimised plan.
        5.  Download the results - Obtain the generated schedule and the updated
            Rules.xlsx from the Downloads tab.
        """
    )

    st.markdown(
        """
        <div class="footer">
        IM2 – Internal Use Only<br>
        This application uses the
        <a href="https://developers.google.com/optimization?hl=de"
           target="_blank" rel="noopener noreferrer">Google OR-Tools</a>
        open-source optimisation library.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


# ------------------------------------------------------------------
# Load config (cached, hash-aware)
# ------------------------------------------------------------------
rules_hash = st.session_state["file_hashes"].get("rules", "")
try:
    config = _load_config_cached(RULES_FILE, rules_hash)
    st.session_state["config"] = config
    st.session_state["rules_file_path"] = RULES_FILE
except Exception as e:
    st.error(f"Error loading Rules.xlsx: {e}")
    st.stop()


# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------
tab1, tab3 = st.tabs(["Run", "Downloads"])


# ==================================================================
# TAB 1 — RUN
# ==================================================================
with tab1:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.markdown("### Generate Schedule")

    current_config = st.session_state.get("config", config)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Doctors", len(current_config.get("Doctors", pd.DataFrame())))
    with col2:
        st.metric("Stations", len(current_config.get("Stations", pd.DataFrame())))
    with col3:
        st.metric("Duty Types", len(current_config.get("DutyTypes", pd.DataFrame())))

    # ---- Output filename: auto from template + today's date ----
    template_hash = st.session_state["file_hashes"].get("template")
    if st.session_state.get("_output_default_hash") != template_hash:
        st.session_state["_output_default_hash"] = template_hash
        st.session_state["output_file_input"] = _build_default_output_name()

    output_file = st.text_input(
        "Output filename",
        key="output_file_input",
        help="Auto-generated from the template name + today's date. You can edit it.",
    )

    if st.button("Generate Schedule", use_container_width=True):
        with st.spinner("Generating schedule..."):
            try:
                template_path = st.session_state.get("template_path")
                if not template_path or not os.path.exists(template_path):
                    st.error(
                        "Please upload a valid Template file (Stationsplan) "
                        "in the sidebar."
                    )
                    st.stop()

                # Persist Settings into Rules_edit.xlsx before solving
                settings_df = current_config.get("Settings", pd.DataFrame()).copy()
                if not settings_df.empty:
                    settings_df.loc[
                        settings_df["Setting"] == "TemplateFile", "Value"
                    ] = template_path
                    settings_df.loc[
                        settings_df["Setting"] == "OutputFile", "Value"
                    ] = output_file
                    if st.session_state.get("wishes_path"):
                        settings_df.loc[
                            settings_df["Setting"] == "WishesFile", "Value"
                        ] = st.session_state["wishes_path"]

                    with pd.ExcelWriter(
                        RULES_FILE,
                        engine="openpyxl",
                        mode="a",
                        if_sheet_exists="replace",
                    ) as writer:
                        settings_df.to_excel(
                            writer, sheet_name="Settings", index=False
                        )

                # Normalise dates in SpecialWeekendDays
                if "SpecialWeekendDays" in current_config:
                    df = current_config["SpecialWeekendDays"].copy()
                    if "Date" in df.columns:
                        df["Date"] = (
                            pd.to_datetime(df["Date"]).dt.date.astype(str)
                        )
                    current_config["SpecialWeekendDays"] = df

                wishes = st.session_state.get("wishes_path")
                success, log_output, schedule = run_scheduler(
                    template_path,
                    output_file,
                    None,
                    wishes,
                    config_dict=current_config,
                )
                st.session_state["log_output"] = log_output
                if success and schedule is not None:
                    try:
                        write_missing_config_sheets(schedule, RULES_FILE)
                    except Exception as e:
                        st.warning(f"could not write Auto sheets: {e}")
                if success and os.path.exists(output_file):
                    st.success(
                        f"Schedule generated successfully → `{output_file}`"
                    )
                    st.session_state["output_file"] = output_file
                else:
                    st.error(
                        "Scheduler failed. See the log below for details."
                    )

            except Exception as e:
                st.error(f"Error: {e}")
                st.code(traceback.format_exc(), language="python")

    st.markdown("</div>", unsafe_allow_html=True)




# ==================================================================
# TAB 3 — DOWNLOADS
# ==================================================================
with tab3:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.markdown("### Download Files")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Generated Schedule")
        out = st.session_state.get("output_file")
        if out and os.path.exists(out):
            with open(out, "rb") as f:
                st.download_button(
                    "Download Schedule",
                    data=f,
                    file_name=os.path.basename(out),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
        else:
            st.info("No schedule generated yet. Run the scheduler first.")

    with col2:
        st.markdown("#### Rules.xlsx")
        if os.path.exists(RULES_FILE):
            with open(RULES_FILE, "rb") as f:
                st.download_button(
                    "Download Updated Rules",
                    data=f,
                    file_name=RULES_FILE,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
        else:
            st.info("No Rules.xlsx available.")

    st.markdown("---")
    st.markdown("#### Template File")
    tmpl = st.session_state.get("template_path")
    if tmpl and os.path.exists(tmpl):
        with open(tmpl, "rb") as f:
            st.download_button(
                "Download Template",
                data=f,
                file_name=os.path.basename(tmpl),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    else:
        st.info("No template file uploaded.")

    st.markdown(
        """
        <div class="footer">
            IM2 - Internal Use Only
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


# ---- Log (inside Run tab) ----
if st.session_state.get("log_output"):
    with st.expander("Scheduler Log", expanded=False):
        st.code(st.session_state["log_output"], language="text")
    st.download_button(
        "Download log",
        data=st.session_state["log_output"].encode("utf-8"),
        file_name="scheduler_log.txt",
        mime="text/plain",
        use_container_width=True,
    )

out_path = st.session_state.get("output_file")
if out_path and os.path.exists(out_path):
    try:
        with pd.ExcelFile(out_path) as xl:
            if "WorkingHours" in xl.sheet_names:
                st.markdown("### Working Hours Summary")
                df_wh = pd.read_excel(xl, sheet_name="WorkingHours")
                st.dataframe(df_wh, use_container_width=True)
            else:
                st.info(
                    "WorkingHours sheet not yet available. "
                    f"Sheets in file: {', '.join(xl.sheet_names)}"
                )
    except Exception as e:
        st.warning(f"Could not read output file: {e}")
