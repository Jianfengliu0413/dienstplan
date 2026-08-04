
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
from datetime import datetime

# --- Page config ---
st.set_page_config(
    page_title=f"IM2 Dienstplan",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)


# --- Fixed Rules file path ---
RULES_FILE = "Rules_edit.xlsx"
INACTIVITY_TIMEOUT_SECONDS = 30 # in seconds

# --- add a timer --- 
if 'last_activity' in st.session_state:
    elapsed= (datetime.now()-st.session_state['last_activity']).total_seconds()
    if elapsed > INACTIVITY_TIMEOUT_SECONDS: # in seonds
        if os.path.exists(RULES_FILE):
            try:
                os.unlink(RULES_FILE)
            except:
                pass
        for path_key in ['template_path', 'wishes_path']:
            if st.session_state.get(path_key) and os.path.exists(st.session_state[path_key]):
                try:
                    os.unlink(st.session_state[path_key])
                except:
                    pass 
        st.session_state.clear()
        st.rerun()
st.session_state['last_activity']= datetime.now()
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
    /* Reduce header height */
    header {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        min-height: 0rem !important;
    }
    /* If there's a specific header class */
    .stApp header {
        padding: 0.2rem 0rem !important;
        height: auto !important;
    }
    /* Also reduce the top margin of the main content to compensate */
    .main > div {
        padding-top: 0.1rem !important;
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
    st.session_state['rules_file_path'] = RULES_FILE
    st.session_state['template_path'] = None
    st.session_state['wishes_path'] = None
    st.session_state['config_loaded'] = False
    st.session_state['output_file'] = None
    st.session_state['file_hashes'] = {}

# --- Sidebar ---
with st.sidebar:
    st.markdown("### Upload Files (click or drag files)")
    
    rules_file = st.file_uploader("Rules.xlsx", type=["xlsx"])
    if rules_file is not None:
        with open(RULES_FILE, "wb") as f:
            f.write(rules_file.getvalue())
        st.session_state['rules_file_path'] = RULES_FILE
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
    
    st.markdown("---")
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
    
    st.markdown("---")
    
    if st.button("Reset All", use_container_width=True):
        if os.path.exists(RULES_FILE):
            try:
                os.unlink(RULES_FILE)
            except:
                pass
        for path_key in ['template_path', 'wishes_path']:
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
    # If Rules_edit.xlsx exists but session says not loaded, load it
    if os.path.exists(RULES_FILE):
        try:
            config = load_config(RULES_FILE)
            st.session_state['config'] = config
            st.session_state['config_loaded'] = True
            st.session_state['rules_file_path'] = RULES_FILE
            st.rerun()
        except:
            pass

if not st.session_state['config_loaded']:
    # Welcome page
    st.markdown("""
    <div style="text-align: center; margin-bottom: 1rem;">
        <h3 style="color: #1a1a2e; font-weight: 700; font-size: 1.8rem; margin: 0.2rem 0;">IM2 Dienstplan</h3>
        <hr style="width: 200px; border: 1px solid #2E86C1; margin: 0rem auto;">hospital shift schu(beta version)</hr>
    </div>
    """, unsafe_allow_html=True)
    
    st.error("""
    ### Data Privacy and Security
    Once you upload a valid Rules file (in sidbar), this page will be replaced with the full featured interface.

    """)
    st.info("""
    **Confidential - Internal Use Only**  
    This system is for authorised personnel only. All data processed through this application is sensitive and must be handled in compliance with applicable data protection regulations.
    - All file uploads are not stored on any external server (is not connected to any external databases or cloud storage.).
    - Temporary files are automatically deleted after your session ends.
    - For any technical issues, please contact JF (TEL: xxxxx61369).""")
    
    st.markdown("""
    ### Getting Started
    To begin, please follow these steps:
    1.  Upload your configuration –- Rules.xlsx file in the sidebar. This file contains all rules, doctors, stations, duties ...
    2.  Upload the monthly template –- The Stationsplan Excel file for the target month (e.g., xxxstationsplanxxx.xlsx).
    3.  Upload doctor's wishes – (optional).
    4.  Run the scheduler – Click Generate Schedule and wait for the optimised plan.
    5.  Download the results – Obtain the generated schedule and the updated Rules.xlsx from the Downloads tab.
    """)
    
    st.markdown(""" 
    <div class="footer">
    IM2 – Internal Use Only<br>
    This application uses the <a href="https://developers.google.com/optimization?hl=de" target="_blank" rel="noopener noreferrer">Google OR-Tools</a> open‑source optimisation library.
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# --- Load config from the fixed file ---
try:
    config = load_config(RULES_FILE)
    st.session_state['config'] = config
    st.session_state['rules_file_path'] = RULES_FILE
except Exception as e:
    st.error(f"Error loading Rules.xlsx: {e}")
    st.stop()

# --- Tabs ---
# tab1, tab2, tab3 = st.tabs(["Run", "Edit", "Downloads"])
tab1,tab3  = st.tabs(["Run",'Downloads'])

# -------- TAB 1: RUN --------
with tab1:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.markdown("### Generate Schedule")
    
    # Use the latest config from session state
    current_config = st.session_state.get('config', config)
    
    # --- DEBUG: Show all sheets in the current config ---
    with st.expander("Show all sheets in current_config", expanded=False):
        st.write("**Sheet names and first rows:**")
        for sheet_name in sorted(current_config.keys()):
            st.write(f"**{sheet_name}**")
            df = current_config[sheet_name]
            st.dataframe(df)
     
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Doctors", len(current_config.get("Doctors", pd.DataFrame())))
    with col2:
        stations = current_config.get("Stations", pd.DataFrame())
        st.metric("Stations", len(stations))
    with col3:
        duties = current_config.get("DutyTypes", pd.DataFrame())
        st.metric("Duty Types", len(duties))
    
    output_file = st.text_input("Output filename", "Stationsplan_out.xlsx")

    if st.button("Generate Schedule", use_container_width=True):
        with st.spinner("Generating schedule..."):
            try:
                template_path = st.session_state.get('template_path')
                if template_path is None or not os.path.exists(template_path):
                    st.error("Please upload a valid Template file (Stationsplan) in the sidebar.")
                    st.stop()
                
                rules_file_path = RULES_FILE
                st.info(f"Reading your local Rules file...")

                settings_df = current_config.get("Settings", pd.DataFrame()).copy()
                settings_df.loc[settings_df["Setting"] == "TemplateFile", "Value"] = template_path
                settings_df.loc[settings_df["Setting"] == "OutputFile", "Value"] = output_file
                if st.session_state.get('wishes_path'):
                    settings_df.loc[settings_df["Setting"] == "WishesFile", "Value"] = st.session_state['wishes_path']
                
                with pd.ExcelWriter(rules_file_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                    settings_df.to_excel(writer, sheet_name="Settings", index=False)
                # # After writing Settings sheet, but before run_scheduler:
                # if os.path.exists(rules_file_path):
                #     # Print the content of the Stations sheet for verification
                #     try:
                #         debug_config = load_config(rules_file_path)
                #         stations_df = debug_config.get('Stations', pd.DataFrame())
                #         # st.write("Stations sheet in the file being used:")
                #         # st.dataframe(stations_df)
                #     except Exception as e:
                #         st.warning(f"Could not read Stations sheet for debug: {e}")


                # st.subheader("Debug: Stations sheet in current_config")
                # st.dataframe(current_config.get('Stations', pd.DataFrame()))
                wishes = st.session_state.get('wishes_path')

                # Use the current_config dict directly to avoid file I/O issues
                success, log_output = run_scheduler(template_path, output_file, None, wishes, config_dict=current_config)
                if success:
                    st.success("Schedule generated successfully!")
                    st.session_state['output_file'] = output_file
                    st.session_state['log_output'] = log_output
                else:
                    st.error(f"Scheduler failed. Log:\n{log_output}")
                
            except Exception as e:
                st.error(f"Error: {e}")
                st.code(traceback.format_exc(), language="python")
    st.markdown('</div>', unsafe_allow_html=True)

# # -------- TAB 2: EDIT --------
# with tab2:
#     st.markdown('<div class="custom-card">', unsafe_allow_html=True)
#     st.markdown("### Parameters Editor")
#     st.caption("Edit your configuration tables. Changes are saved to the Rules.xlsx file.")

#     all_sheets = list(current_config.keys())
#     if not all_sheets:
#         st.error("No sheets found in the configuration file. Please upload a valid Rules.xlsx.")
#         st.stop()

#     version_key = hashlib.md5(RULES_FILE.encode()).hexdigest()
#     if 'edit_version' not in st.session_state:
#         st.session_state['edit_version'] = version_key
#     elif st.session_state['edit_version'] != version_key:
#         for key in list(st.session_state.keys()):
#             if key.startswith('editor_'):
#                 del st.session_state[key]
#         st.session_state['edit_version'] = version_key

#     for sheet_name in all_sheets:
#         expanded = sheet_name in ["Settings", "Doctors", "Stations", "DutyTypes"]
#         with st.expander(f"{sheet_name}", expanded=expanded):
#             editor_key = f"editor_{sheet_name}"
#             initial_df = current_config[sheet_name].copy().fillna("")
#             # Ensure we have a DataFrame (convert if needed)
#             existing = st.session_state.get(editor_key)
#             if existing is not None and not isinstance(existing, pd.DataFrame):
#                 # If it's a dict or something else, convert to DataFrame
#                 try:
#                     existing = pd.DataFrame(existing)
#                 except:
#                     existing = initial_df
#             else:
#                 existing = initial_df
#             edited_df = st.data_editor(
#                 existing,
#                 key=editor_key,
#                 use_container_width=True,
#                 num_rows="dynamic"
#             )
#             # The widget updates st.session_state[editor_key] automatically

#     if st.button("Save All Changes", use_container_width=True):
#         try:
#             file_path = RULES_FILE
#             st.info(f"Saving to: {file_path}")

#             from openpyxl import Workbook
#             from openpyxl.utils.dataframe import dataframe_to_rows

#             wb = Workbook()
#             wb.remove(wb.active)

#             for sheet_name in all_sheets:
#                 editor_key = f"editor_{sheet_name}"
#                 df = st.session_state.get(editor_key)
#                 if df is None or not isinstance(df, pd.DataFrame):
#                     df = current_config[sheet_name].copy().fillna("")
#                 if not isinstance(df, pd.DataFrame):
#                     df = pd.DataFrame(df)
#                 ws = wb.create_sheet(title=sheet_name)
#                 for r in dataframe_to_rows(df, index=False, header=True):
#                     ws.append(r)

#             wb.save(file_path)


#             # --- DEBUG: Show all sheets in the saved file ---
#             debug_config = load_config(file_path)
#             st.success(f"File saved successfully!")
#             with st.expander("🔍 Debug: Saved file content", expanded=True):
#                 st.write(f"**File path:** {file_path}")
#                 for sheet_name in sorted(debug_config.keys()):
#                     st.write(f"**{sheet_name}**")
#                     df = debug_config[sheet_name]
#                     st.dataframe(df.head(3))


#             st.success("Changes saved successfully!")

#             st.session_state['config'] = load_config(file_path)
#             for sheet_name in all_sheets:
#                 editor_key = f"editor_{sheet_name}"
#                 if editor_key in st.session_state:
#                     del st.session_state[editor_key]
#             st.rerun()
#         except Exception as e:
#             st.error(f"Save failed: {e}")

#     st.markdown('</div>', unsafe_allow_html=True)

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
        if os.path.exists(RULES_FILE):
            with open(RULES_FILE, "rb") as f:
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
        IM2 - Internal Use Only
    </div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
