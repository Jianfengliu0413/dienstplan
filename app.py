


"""
260801: v001
"""


import streamlit as st
import pandas as pd
import os
import tempfile
import shutil
import hashlib
import traceback
from scheduler import run_scheduler
from config_loader import load_config

# --- Page config ---
st.set_page_config(
    page_title="UKT IM2 Duty Scheduler",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS ---
st.markdown("""

<style>
    /* Main background */
    .stApp {
        background-color: #f4f6f9;
    }
    /* Card style */
    .custom-card {
        background: white;
        padding: 1.8rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.06);
        margin-bottom: 1.5rem;
        border: 1px solid #e9ecef;
    }
    /* Sidebar */
    .css-1d391kg, .stSidebar, [data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1px solid #dee2e6 !important;
        color: #1a1a2e !important;
    }
    .sidebar-logo {
        text-align: center;
        margin-bottom: 0.5rem;
        padding-top: 0.2rem;
    }
    .sidebar-logo h2 {
        color: #1a1a2e;
        font-weight: 700;
        font-size: 1.2rem;
        margin: 0;
        line-height:1.2;
    }
    .sidebar-logo p {
        color: #6c757d;
        font-size: 0.8rem;
        margin: 0;
    }
    /* Headers */
    h1, h2, h3 {
        color: #1a1a2e;
        font-weight: 400;
    }

    /* Buttons */
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
    /* Status indicators */
    .status-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #1a1a2e !important;
    }
    .status-loaded {
        background: #d4edda !important;
        color: #155724 !important;
    }
    .status-missing {
        background: #f8d7da !important;
        color: #721c24 !important;
    }
    /* Force dark text in warning boxes (mobile fix) */
    .stAlert .stMarkdown {
        color: #1a1a2e !important;
    }
    .stAlert .stMarkdown strong {
        color: #1a1a2e !important;
    }
    /* Reduce warning box padding for mobile */
    .stAlert {
        padding: 0.5rem 1rem !important;
    }
    /* Footer */
    .footer {
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 1px solid #dee2e6;
        text-align: center;
        color: #6c757d;
        font-size: 0.8rem;
    }
    .footer a {
        color: #2E86C1 !important;
    }
    /* Hide Streamlit branding – keep header visible for sidebar toggle */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none !important;}
    .stAppDeployButton {display: none !important;}
    .stApp [data-testid="stToolbar"] {display: none;}
    /* Hide the "Manage app" button if it appears */
    .stApp [data-testid="stHeaderManageApp"] {display: none !important;}
    .stApp [data-testid="stHeaderAppMenu"] {display: none !important;}
    
    /* --- Mobile friendly font colors --- */
    /* Ensure sidebar text is dark */
    .stSidebar .stMarkdown, .stSidebar .stText, .stSidebar label {
        color: #1a1a2e !important;
    }
    /* Ensure all text in the main area is dark */
    .stMarkdown, .stText, .stCaption, .stInfo, .stWarning, .stError, .stSuccess {
        color: #1a1a2e !important;
    }
    /* Metrics */
    [data-testid="stMetricValue"] {
        color: #1a1a2e !important;
    }
    [data-testid="stMetricLabel"] {
        color: #6c757d !important;
    }
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        color: #1a1a2e !important;
    }
    .stTabs [data-baseweb="tab"] {
        color: #1a1a2e !important;
    }
    /* Expanders */
    .streamlit-expanderHeader {
        color: #1a1a2e !important;
    }
    /* File uploader text */
    .stFileUploader label {
        color: #1a1a2e !important;
    }

    /* Hide Streamlit branding - keep header visible */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none !important;}
    .stAppDeployButton {display: none !important;}
    .stApp [data-testid="stToolbar"] {display: none;}
    /* Hide GitHub/Fork and Manage app only */
    .stApp [data-testid="stHeaderGitHub"] {display: none !important;}
    .stApp [data-testid="stHeaderFork"] {display: none !important;}
    .stApp [data-testid="stHeaderManageApp"] {display: none !important;}
    .stApp [data-testid="stHeaderAppMenu"] {display: none !important;}
    /* Also hide any link containing "github" in header */
    .stApp header a[href*="github"] {display: none !important;}
    /* Hide the "Manage app" dropdown and button */
    .st-emotion-cache-1v0mbdj {display: none !important;}
    .st-emotion-cache-1r6slb0 {display: none !important;}

</style>
""", unsafe_allow_html=True) 

# --- Session state ---
if 'initialized' not in st.session_state:
    st.session_state.clear()
    st.session_state['initialized'] = True
    st.session_state['rules_file_path'] = None
    st.session_state['template_path'] = None
    st.session_state['wishes_path'] = None
    st.session_state['config_loaded'] = False
    st.session_state['output_file'] = None
    st.session_state['file_hashes'] = {}

# --- Sidebar ---
with st.sidebar:
    # st.markdown("""
    # <div class="sidebar-logo">
    #     <h4>UKT IM2</h4>
    # </div>
    # """, unsafe_allow_html=True)
    
    # st.markdown("---")
    
    st.markdown("### Upload Files")
    
    rules_file = st.file_uploader("Rules.xlsx", type=["xlsx"])
    if rules_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(rules_file.getvalue())
            st.session_state['rules_file_path'] = tmp.name
            st.session_state['config_loaded'] = True
            st.session_state['file_hashes']['rules'] = hashlib.md5(rules_file.getvalue()).hexdigest()
    
    template_file = st.file_uploader("Template (Stationsplan)", type=["xlsx"])
    if template_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(template_file.getvalue())
            st.session_state['template_path'] = tmp.name
            st.session_state['file_hashes']['template'] = hashlib.md5(template_file.getvalue()).hexdigest()
    
    wishes_file = st.file_uploader("Wishes (optional)", type=["xlsx"])
    if wishes_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(wishes_file.getvalue())
            st.session_state['wishes_path'] = tmp.name
            st.session_state['file_hashes']['wishes'] = hashlib.md5(wishes_file.getvalue()).hexdigest()
    
    # st.markdown("---")
    
    st.markdown("### Status")
    
    rules_status = "Loaded" if st.session_state['config_loaded'] else "Not loaded"
    rules_class = "status-loaded" if st.session_state['config_loaded'] else "status-missing"
    st.markdown(f"**Rules** <span class='status-badge {rules_class}'>{rules_status}</span>", unsafe_allow_html=True)
    
    template_status = "Loaded" if st.session_state['template_path'] else "Not loaded"
    template_class = "status-loaded" if st.session_state['template_path'] else "status-missing"
    st.markdown(f"**Template** <span class='status-badge {template_class}'>{template_status}</span>", unsafe_allow_html=True)
    
    wishes_status = "Loaded" if st.session_state['wishes_path'] else "Not set"
    wishes_class = "status-loaded" if st.session_state['wishes_path'] else "status-missing"
    st.markdown(f"**Wishes** <span class='status-badge {wishes_class}'>{wishes_status}</span>", unsafe_allow_html=True)
    
    # st.markdown("---")
    
    if st.button("Reset All", use_container_width=True):
        for path_key in ['rules_file_path', 'template_path', 'wishes_path']:
            if st.session_state.get(path_key) and os.path.exists(st.session_state[path_key]):
                try:
                    os.unlink(st.session_state[path_key])
                except:
                    pass
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- Main content ---
if not st.session_state['config_loaded']:
    # st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.markdown("""
    <div style="text-align: center; margin-bottom: 1rem;">
        <h3 style="color: #1a1a2e; font-weight: 700; font-size: 1.8rem; margin: 0.2rem 0;">UKT IM2 Dienstplan</h3>
        <hr style="width: 60px; border: 2px solid #2E86C1; margin: 0rem auto;">
    </div>
    """, unsafe_allow_html=True)
    
    st.warning("""
    **Confidential - Internal Use Only**  This system is for authorised personnel only. All data processed through this application is sensitive and must be handled in compliance with applicable data protection regulations.
    """)
    
    st.info("Once you upload a valid Rules.xlsx file, this page will be replaced with the full featured interface.")
    
    st.markdown("""
    ### Data Privacy and Security
    - All file uploads are processed locally in your browser and not stored on any external server.
    - Temporary files are automatically deleted after your session ends.
    - This application is not connected to any external databases or cloud storage.
    For any technical issues, please contact JF (TEL: xxxxx61369).
    ### Getting Started
    This tool uses the Google OR-Tools open‑source library. https://developers.google.com/optimization?hl=de
    To begin, please follow these steps:
    1.  Upload your configuration – Provide your Rules.xlsx file in the sidebar. This file contains all department rules, doctor lists, stations, duty types, and constraints.
    2.  Upload the monthly template – The Stationsplan Excel file for the target month (e.g., xxxstationsplanxxx.xlsx).
    3.  Upload wishes – If you have a Wishes.xlsx file with doctor preferences, upload it as well.
    4.  Review and adjust parameters – Use the Edit tab to fine-tune settings, duty counts, penalties, and constraints.
    5.  Run the scheduler – Click Generate Schedule and wait for the optimised plan.
    6.  Download the results – Obtain the generated schedule and the updated Rules.xlsx from the Downloads tab.
    """)
    
    st.markdown(""" 
    <div class="footer">
    UKT IM2 – Internal Use Only<br>
    This application uses the <a href="https://developers.google.com/optimization?hl=de" target="_blank" rel="noopener noreferrer">Google OR-Tools</a> open‑source optimisation library.
    </div>
    """, unsafe_allow_html=True)
    
    # st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# Load config
try:
    config = load_config(st.session_state['rules_file_path'])
except Exception as e:
    st.error(f"Error loading Rules.xlsx: {e}")
    st.stop()

# --- Tabs ---
tab1, tab2, tab3 = st.tabs(["Run", "Edit", "Downloads"])

# -------- TAB 1: RUN --------
with tab1:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.markdown("### Generate Schedule")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Doctors", len(config.get("Doctors", pd.DataFrame())))
    with col2:
        stations = config.get("Stations", pd.DataFrame())
        st.metric("Stations", len(stations))
    with col3:
        duties = config.get("DutyTypes", pd.DataFrame())
        st.metric("Duty Types", len(duties))
    
    output_file = st.text_input("Output filename", "Stationsplan_out.xlsx")
    
    if st.button("Generate Schedule", use_container_width=True):
        with st.spinner("Generating schedule..."):
            try:
                template_path = st.session_state['template_path']
                if template_path is None:
                    settings_df = config.get("Settings", pd.DataFrame())
                    if not settings_df.empty:
                        template_path = settings_df[settings_df["Setting"] == "TemplateFile"]["Value"].values[0]
                    else:
                        st.error("Template file not found. Please upload one.")
                        st.stop()
                
                settings_df = config.get("Settings", pd.DataFrame()).copy()
                settings_df.loc[settings_df["Setting"] == "TemplateFile", "Value"] = template_path
                settings_df.loc[settings_df["Setting"] == "OutputFile", "Value"] = output_file
                if st.session_state.get('wishes_path'):
                    settings_df.loc[settings_df["Setting"] == "WishesFile", "Value"] = st.session_state['wishes_path']
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                        for sheet, df in config.items():
                            if sheet == "Settings":
                                settings_df.to_excel(writer, sheet_name=sheet, index=False)
                            else:
                                df.to_excel(writer, sheet_name=sheet, index=False)
                    updated_rules = tmp.name
                
                shutil.copy(updated_rules, "Rules.xlsx")
                wishes = st.session_state.get('wishes_path')
                if wishes:
                    shutil.copy(wishes, "wishes.xlsx")
                
                result = run_scheduler(template_path, output_file, "Rules.xlsx", wishes)
                if result:
                    st.success("Schedule generated successfully")
                    st.session_state['output_file'] = output_file
                else:
                    st.error("Scheduler failed. Please check logs.")
                
                os.unlink(updated_rules)
                
            except Exception as e:
                st.error(f"Error: {e}")
                st.code(traceback.format_exc(), language="python")
    st.markdown('</div>', unsafe_allow_html=True)

# -------- TAB 2: EDIT --------
with tab2:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.markdown("### Parameters Editor")
    st.caption("Edit your configuration tables. Changes are saved to the Rules.xlsx file.")
    
    sheets_to_edit = ["Settings", "Doctors", "Stations", "DutyTypes", "Penalties", "Constraints", "GeneralRules", "StationCodeMap"]
    file_hash = hashlib.md5(st.session_state['rules_file_path'].encode()).hexdigest()
    
    for sheet_name in sheets_to_edit:
        if sheet_name in config:
            with st.expander(f"{sheet_name}", expanded=(sheet_name=="Doctors" or sheet_name=="Settings")):
                df = config[sheet_name].copy().fillna("")
                editor_key = f"edit_{sheet_name}_{file_hash}"
                edited_df = st.data_editor(df, key=editor_key, use_container_width=True, num_rows="dynamic")
                st.session_state[f'edited_{sheet_name}'] = edited_df
        else:
            st.info(f"Sheet '{sheet_name}' not found - it will be created when you save.")
    
    if st.button("Save All Changes", use_container_width=True):
        try:
            with pd.ExcelWriter(st.session_state['rules_file_path'], engine='openpyxl', mode='w') as writer:
                for sheet_name in sheets_to_edit:
                    if sheet_name in config:
                        df = st.session_state.get(f'edited_{sheet_name}')
                        if df is not None:
                            df.to_excel(writer, sheet_name=sheet_name, index=False)
                        else:
                            config[sheet_name].to_excel(writer, sheet_name=sheet_name, index=False)
            st.success("Changes saved successfully")
            st.rerun()
        except Exception as e:
            st.error(f"Save failed: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

# -------- TAB 3: DOWNLOADS --------
with tab3:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.markdown("### Download Files")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Generated Schedule")
        if st.session_state.get('output_file') and os.path.exists(st.session_state['output_file']):
            with open(st.session_state['output_file'], "rb") as f:
                st.download_button(
                    label="Download Schedule",
                    data=f,
                    file_name=os.path.basename(st.session_state['output_file']),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        else:
            st.info("No schedule generated yet. Run the scheduler first.")
    
    with col2:
        st.markdown("#### Rules.xlsx")
        if st.session_state.get('rules_file_path') and os.path.exists(st.session_state['rules_file_path']):
            with open(st.session_state['rules_file_path'], "rb") as f:
                st.download_button(
                    label="Download Updated Rules",
                    data=f,
                    file_name="Rules_updated.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        else:
            st.info("No Rules.xlsx available.")
    
    st.markdown("---")
    st.markdown("#### Template File")
    if st.session_state.get('template_path') and os.path.exists(st.session_state['template_path']):
        with open(st.session_state['template_path'], "rb") as f:
            st.download_button(
                label="Download Template",
                data=f,
                file_name=os.path.basename(st.session_state['template_path']),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    else:
        st.info("No template file uploaded.")
    
    st.markdown("""
    <div class="footer">
        UKT IM2 - Internal Use Only
    </div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

