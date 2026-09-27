"""
260801: v002 — UX refresh
"""

import streamlit as st
import pandas as pd
import os
import tempfile
import hashlib
import traceback
from datetime import datetime

from scheduler import run_scheduler
from config_loader import load_config

# ------------------------------------------------------------------
# Page config
# ------------------------------------------------------------------
st.set_page_config(
    page_title="IM2 Dienstplan",
    page_icon=" ",
    layout="wide",
    initial_sidebar_state="expanded",
)

RULES_FILE = "Rules_edit.xlsx"
INACTIVITY_TIMEOUT_SECONDS = 300


# ------------------------------------------------------------------
# Custom CSS
# ------------------------------------------------------------------
st.markdown(
    """
<style>
    /* ---------- Global ---------- */
    .stApp { background-color: #f4f6f9; }

    header, .stApp header {
        padding: 0.2rem 0rem !important;
        min-height: 0rem !important;
    }
    .main > div { padding-top: 0.1rem !important; }

    h1, h2, h3 { color: #1a1a2e; font-weight: 500; }

    /* ---------- Cards ---------- */
    .custom-card {
        background: white;
        padding: 1.6rem 1.8rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 1.2rem;
        border: 1px solid #e9ecef;
    }
    .hero-card {
        background: linear-gradient(135deg, #2E86C1 0%, #1a5276 100%);
        color: white !important;
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        text-align: center;
    }
    .hero-card h1 {
        color: white !important;
        font-size: 2rem;
        margin: 0 0 0.4rem 0;
    }
    .hero-card p {
        color: #d6e9f8 !important;
        margin: 0;
        font-size: 0.95rem;
    }

    /* ---------- Metric cards ---------- */
    .metric-card {
        background: white;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        border: 1px solid #e9ecef;
        box-shadow: 0 2px 6px rgba(0,0,0,0.04);
        display: flex;
        align-items: center;
        gap: 0.9rem;
    }
    .metric-icon {
        font-size: 1.6rem;
        line-height: 1;
    }
    .metric-value {
        font-size: 1.4rem;
        font-weight: 700;
        color: #1a1a2e;
        line-height: 1.1;
    }
    .metric-label {
        font-size: 0.8rem;
        color: #6c757d;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    /* ---------- Buttons ---------- */
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
    .stButton button:disabled {
        background-color: #cdd5dd !important;
        color: #7a869a !important;
        box-shadow: none;
        transform: none;
    }

    /* ---------- Status badges ---------- */
    .status-badge {
        display: inline-block;
        padding: 0.15rem 0.55rem;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 600;
    }
    .status-loaded  { background: #d4edda; color: #155724; }
    .status-missing { background: #f8d7da; color: #721c24; }
    .status-optional{ background: #fff3cd; color: #856404; }

    /* ---------- Sidebar ---------- */
    [data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1px solid #dee2e6 !important;
    }
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] .stText,
    [data-testid="stSidebar"] label {
        color: #1a1a2e !important;
    }

    /* ---------- Alerts ---------- */
    .stAlert .stMarkdown,
    .stAlert .stMarkdown strong { color: #1a1a2e !important; }
    .stAlert { padding: 0.6rem 1rem !important; }

    /* ---------- Footer ---------- */
    .footer {
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 1px solid #dee2e6;
        text-align: center;
        color: #6c757d;
        font-size: 0.8rem;
    }
    .footer a { color: #2E86C1 !important; }

    /* ---------- Hide branding ---------- */
    #MainMenu, footer { visibility: hidden; }
    .stDeployButton,
    .stAppDeployButton,
    .stApp [data-testid="stToolbar"],
    .stApp [data-testid="stHeaderManageApp"],
    .stApp [data-testid="stHeaderAppMenu"],
    .stApp [data-testid="stHeaderGitHub"],
    .stApp [data-testid="stHeaderFork"] { display: none !important; }
    .stApp header a[href*="github"] { display: none !important; }
</style>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def cleanup_session_files() -> None:
    """Delete the Rules file and any temp uploads stored in session."""
    if os.path.exists(RULES_FILE):
        try:
            os.unlink(RULES_FILE)
        except OSError:
            pass
    for key in ("template_path", "wishes_path"):
        path = st.session_state.get(key)
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
    st.session_state.clear()


def render_status_badge(label: str, loaded: bool, optional: bool = False) -> None:
    if loaded:
        css, text = "status-loaded", "Loaded"
    elif optional:
        css, text = "status-optional", "Not set"
    else:
        css, text = "status-missing", "Missing"
    st.markdown(
        f"**{label}** <span class='status-badge {css}'>{text}</span>",
        unsafe_allow_html=True,
    )


def render_metric_card(icon: str, value, label: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-icon">{icon}</div>
            <div>
                <div class="metric-value">{value}</div>
                <div class="metric-label">{label}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


# ------------------------------------------------------------------
# Session state
# ------------------------------------------------------------------
st.session_state.setdefault("rules_file_path", RULES_FILE)
st.session_state.setdefault("template_path", None)
st.session_state.setdefault("wishes_path", None)
st.session_state.setdefault("config_loaded", False)
st.session_state.setdefault("output_file", None)
st.session_state.setdefault("file_hashes", {})
st.session_state.setdefault("log_output", None)


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown("## IM2 Dienstplan")
    st.caption("Hospital shift scheduling")
    st.markdown("---")

    # ---- Required uploads ----
    st.markdown("### 1. Configuration")
    rules_file = st.file_uploader(
        "Rules.xlsx",
        type=["xlsx"],
        help="Contains doctors, stations, duties, rules, and penalties.",
    )
    if rules_file is not None:
        with open(RULES_FILE, "wb") as f:
            f.write(rules_file.getvalue())
        st.session_state["rules_file_path"] = RULES_FILE
        st.session_state["config_loaded"] = True
        st.session_state["file_hashes"]["rules"] = hashlib.md5(
            rules_file.getvalue()
        ).hexdigest()

    st.markdown("### 2. Template")
    template_file = st.file_uploader(
        "Stationsplan (.xlsx)",
        type=["xlsx"],
        help="Monthly station plan template for the target month.",
    )
    if template_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(template_file.getvalue())
            st.session_state["template_path"] = tmp.name
            st.session_state["file_hashes"]["template"] = hashlib.md5(
                template_file.getvalue()
            ).hexdigest()

    st.markdown("### 3. Wishes (optional)")
    wishes_file = st.file_uploader(
        "Wishes (.xlsx)",
        type=["xlsx"],
        help="Doctor preferences, vacation, and specific duty requests.",
    )
    if wishes_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(wishes_file.getvalue())
            st.session_state["wishes_path"] = tmp.name
            st.session_state["file_hashes"]["wishes"] = hashlib.md5(
                wishes_file.getvalue()
            ).hexdigest()

    st.markdown("---")
    st.markdown("### Status")
    render_status_badge("Rules", st.session_state["config_loaded"])
    render_status_badge("Template", bool(st.session_state["template_path"]))
    render_status_badge(
        "Wishes", bool(st.session_state["wishes_path"]), optional=True
    )

    st.markdown("---")
    if st.button("Reset All", use_container_width=True):
        cleanup_session_files()
        st.rerun()

    with st.expander("How to use"):
        st.markdown(
            """
            1. **Upload Rules.xlsx** — configures doctors, stations, duties.
            2. **Upload the Stationsplan** for the target month.
            3. *(Optional)* Upload **Wishes** with doctor preferences.
            4. Go to the **Run** tab and click **Generate Schedule**.
            5. Download the result from the **Downloads** tab.
            """
        )


# ------------------------------------------------------------------
# Welcome page (no Rules loaded yet)
# ------------------------------------------------------------------
if not st.session_state["config_loaded"] and os.path.exists(RULES_FILE):
    # Auto-load if file exists on disk
    try:
        st.session_state["config"] = load_config(RULES_FILE)
        st.session_state["config_loaded"] = True
        st.session_state["rules_file_path"] = RULES_FILE
        st.rerun()
    except Exception:
        pass

if not st.session_state["config_loaded"]:
    st.markdown(
        """
        <div class="hero-card">
            <h1>IM2 Dienstplan</h1>
            <p>Intelligent hospital shift scheduling — powered by Google OR‑Tools</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("### Getting Started")
        st.markdown(
            """
            1. **Upload your configuration** — `Rules.xlsx` in the sidebar.
               This file contains doctors, stations, duty types, and all rules.
            2. **Upload the monthly template** — the `Stationsplan` Excel file
               for the target month.
            3. *(Optional)* **Upload doctor wishes** — preferences and
               vacation requests.
            4. **Run the scheduler** — click **Generate Schedule** in the
               *Run* tab and wait for the optimised plan.
            5. **Download the results** — get the generated schedule and the
               updated `Rules.xlsx` from the *Downloads* tab.
            """
        )

    with col_right:
        st.markdown("### Data Privacy")
        st.info(
            """
            **Confidential — Internal Use Only**

            - All file uploads are processed **locally** and never sent to
              an external server or cloud storage.
            - Temporary files are automatically deleted after your session
              ends.
            - For technical issues, contact **JF** (Tel: xxxxx61369).
            """
        )

    st.markdown(
        """
        <div class="footer">
            IM2 — Internal Use Only<br>
            This application uses the
            <a href="https://developers.google.com/optimization?hl=de"
               target="_blank" rel="noopener noreferrer">Google OR‑Tools</a>
            open‑source optimisation library.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


# ------------------------------------------------------------------
# Load config (guaranteed available here)
# ------------------------------------------------------------------
try:
    config = load_config(RULES_FILE)
    st.session_state["config"] = config
    st.session_state["rules_file_path"] = RULES_FILE
except Exception as e:
    st.error(f"Error loading Rules.xlsx: {e}")
    st.stop()


# ------------------------------------------------------------------
# Tabs
# ------------------------------------------------------------------
tab_run, tab_downloads = st.tabs(["Run", "Downloads"])


# ==================================================================
# TAB 1 — RUN
# ==================================================================
with tab_run:
    current_config = st.session_state.get("config", config)

    # ---- Hero header ----
    st.markdown(
        """
        <div class="hero-card" style="padding: 1.2rem;">
            <h1 style="font-size: 1.5rem;">Generate Schedule</h1>
            <p>Review your configuration and run the optimiser</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- Metrics ----
    n_doctors = len(current_config.get("Doctors", pd.DataFrame()))
    n_stations = len(current_config.get("Stations", pd.DataFrame()))
    n_duties = len(current_config.get("DutyTypes", pd.DataFrame()))

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        render_metric_card("", n_doctors, "Doctors")
    with m2:
        render_metric_card("", n_stations, "Stations")
    with m3:
        render_metric_card("", n_duties, "Duty Types")
    with m4:
        template_ready = bool(st.session_state.get("template_path"))
        render_metric_card(
            "", "Ready" if template_ready else "Missing", "Template"
        )

    st.markdown("")

    # ---- Pre-flight checklist ----
    rules_ok = st.session_state["config_loaded"]
    template_ok = bool(st.session_state.get("template_path"))
    wishes_ok = bool(st.session_state.get("wishes_path"))

    with st.expander("Pre-flight checklist", expanded=not (rules_ok and template_ok)):
        st.markdown(
            f"""
            - {'' if rules_ok else ''} **Rules.xlsx** loaded
            - {'' if template_ok else ''} **Stationsplan template** uploaded
            - {'' if wishes_ok else ' '} **Wishes** uploaded *(optional)*
            """
        )

    # ---- Output filename ----
    st.markdown("#### Output")
    output_file = st.text_input(
        "Output filename",
        "Stationsplan_out.xlsx",
        help="Name of the generated Excel file.",
    )

    # ---- Generate button (disabled until ready) ----
    can_generate = rules_ok and template_ok
    generate = st.button(
        "🚀 Generate Schedule",
        use_container_width=True,
        disabled=not can_generate,
        type="primary",
    )

    if not can_generate:
        st.caption("Upload **Rules.xlsx** and a **template** to enable generation.")

    if generate:
        with st.spinner("Generating schedule… this may take a moment."):
            try:
                template_path = st.session_state["template_path"]

                # --- Persist Settings back to Rules file ---
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

                # --- Special weekend days: normalise Date column ---
                if "SpecialWeekendDays" in current_config:
                    df = current_config["SpecialWeekendDays"].copy()
                    if "Date" in df.columns:
                        df["Date"] = (
                            pd.to_datetime(df["Date"]).dt.date.astype(str)
                        )
                    current_config["SpecialWeekendDays"] = df

                # --- Run ---
                wishes = st.session_state.get("wishes_path")
                success, log_output = run_scheduler(
                    template_path,
                    output_file,
                    None,
                    wishes,
                    config_dict=current_config,
                )
                st.session_state["log_output"] = log_output

                if success and os.path.exists(output_file):
                    st.success(f"Schedule generated successfully → `{output_file}`")
                    st.session_state["output_file"] = output_file
                    st.balloons()
                else:
                    st.error(
                        "Scheduler failed. See the log below for details."
                    )

            except Exception as e:
                st.error(f"Unexpected error: {e}")
                with st.expander("Traceback"):
                    st.code(traceback.format_exc(), language="python")

    # ---- Log (inside Run tab, only if it exists) ----
    if st.session_state.get("log_output"):
        with st.expander("Scheduler log", expanded=False):
            st.code(st.session_state["log_output"], language="text")
            st.download_button(
                "Download log",
                data=st.session_state["log_output"].encode("utf-8"),
                file_name="scheduler_log.txt",
                mime="text/plain",
                use_container_width=True,
            )


# ==================================================================
# TAB 3 — DOWNLOADS
# ==================================================================
with tab_downloads:
    st.markdown(
        """
        <div class="hero-card" style="padding: 1.2rem;">
            <h1 style="font-size: 1.5rem;">Downloads</h1>
            <p>Grab your generated files</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Generated Schedule")
        out = st.session_state.get("output_file")
        if out and os.path.exists(out):
            with open(out, "rb") as f:
                st.download_button(
                    "⬇️ Download Schedule",
                    data=f,
                    file_name=os.path.basename(out),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    type="primary",
                )
        else:
            st.info("No schedule generated yet. Run the scheduler first.")

    with col2:
        st.markdown("#### Rules.xlsx")
        if os.path.exists(RULES_FILE):
            with open(RULES_FILE, "rb") as f:
                st.download_button(
                    "⬇Download Updated Rules",
                    data=f,
                    file_name="Rules_updated.xlsx",
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
            IM2 — Internal Use Only
        </div>
        """,
        unsafe_allow_html=True,
    )