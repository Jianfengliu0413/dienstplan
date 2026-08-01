


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
# --- Hide Streamlit branding ---
hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none !important;}
    .stAppDeployButton {display: none !important;}
    .stApp [data-testid="stToolbar"] {display: none;}
    .stApp [data-testid="stHeader"] {display: none;}
    .stApp [data-testid="stHeaderManageApp"] {display: none !important;}
    .stApp [data-testid="stHeaderAppMenu"] {display: none !important;}
    /* Hide the "Manage app" dropdown and button */
    .st-emotion-cache-1v0mbdj {display: none !important;}
    .st-emotion-cache-1r6slb0 {display: none !important;}
    </style>
"""

st.markdown(hide_streamlit_style, unsafe_allow_html=True)
# --- Custom CSS for modern look ---
st.markdown("""
<style>
    /* Main background */
    .stApp {
        background-color: #f8f9fa;
    }
    /* Card style for containers */
    .custom-card {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 1.5rem;
        border: 1px solid #e9ecef;
    }
    /* Sidebar styling */
    .css-1d391kg {
        background-color: #ffffff;
        border-right: 1px solid #dee2e6;
    }
    /* Headers */
    h1, h2, h3 {
        color: #1a1a2e;
        font-weight: 600;
    }
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #6c757d;
        margin-bottom: 1.5rem;
    }
    /* Buttons */
    .stButton button {
        background-color: #2E86C1;
        color: white;
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
    /* File uploader */
    .stFileUploader {
        border: 2px dashed #dee2e6;
        border-radius: 8px;
        padding: 0.5rem;
        background: #fafafa;
    }
    /* Data editor */
    .stDataFrame {
        border-radius: 8px;
        border: 1px solid #e9ecef;
        overflow: hidden;
    }
    /* Footer */
    footer {visibility: hidden;}
    .stDeployButton {display: none !important;}
</style>
""", unsafe_allow_html=True)

# --- Session state initialization ---
if 'initialized' not in st.session_state:
    st.session_state.clear()
    st.session_state['initialized'] = True
    st.session_state['rules_file_path'] = None
    st.session_state['template_path'] = None
    st.session_state['wishes_path'] = None
    st.session_state['config_loaded'] = False
    st.session_state['output_file'] = None

# --- Sidebar ---
with st.sidebar:
    st.markdown("### **Files**")
    
    rules_file = st.file_uploader("Rules.xlsx", type=["xlsx"])
    if rules_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(rules_file.getvalue())
            st.session_state['rules_file_path'] = tmp.name
            st.session_state['config_loaded'] = True
    
    template_file = st.file_uploader("Template (Stationsplan)", type=["xlsx"])
    if template_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(template_file.getvalue())
            st.session_state['template_path'] = tmp.name
    
    wishes_file = st.file_uploader("Wishes (optional)", type=["xlsx"])
    if wishes_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(wishes_file.getvalue())
            st.session_state['wishes_path'] = tmp.name
    
    st.markdown("---")
    # Status indicators
    st.markdown("### Status")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Rules**")
        st.markdown("Loaded" if st.session_state['config_loaded'] else "Not loaded")
    with col2:
        st.markdown("**Template**")
        st.markdown("Loaded" if st.session_state['template_path'] else "Not loaded")
    
    if st.button("Reset All", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- Main content --- 
if not st.session_state['config_loaded']:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    
    # Header
    st.markdown("""
    <div style="text-align: center; margin-bottom: 2rem;">
        <h1 style="color: #1a1a2e; font-weight: 700;">UKT IM2 Dienstplan</h1>
        <p style="color: #6c757d; font-size: 1.1rem;">Enterprise‑Grade Duty Scheduling System</p>
        <hr style="width: 80px; border: 2px solid #2E86C1; margin: 0 auto;">
    </div>
    """, unsafe_allow_html=True)
    
    # Confidentiality notice
    st.warning("""
    **⚠️ Confidential – Internal Use Only**  
    This system is for authorised personnel of the UKT IM2 department only.  
    All data processed through this application is sensitive and must be handled in compliance with applicable data protection regulations.
    """)
    
    st.markdown("""
    ### Getting Started
    
    This tool generates **optimized duty schedules** for your department using advanced constraint‑based optimisation.
    
    **To begin, please follow these steps:**
    
    1.  **Upload your configuration** – Provide your `Rules.xlsx` file in the sidebar. This file contains all department rules, doctor lists, stations, duty types, and constraints.
    2.  **Upload the monthly template** – The `Stationsplan` Excel file for the target month (e.g., `Stationsplan November 26.xlsx`).
    3.  **(Optional) Upload wishes** – If you have a `Wishes.xlsx` file with doctor preferences, upload it as well.
    4.  **Review and adjust parameters** – Use the **Edit** tab to fine‑tune settings, duty counts, penalties, and constraints.
    5.  **Run the scheduler** – Click **Generate Schedule** and wait for the optimised plan.
    6.  **Download the results** – Obtain the generated schedule and the updated `Rules.xlsx` from the **Downloads** tab.
    
    ---
    
    ### Data Privacy & Security
    
    - All file uploads are processed **locally** in your browser and **not stored** on any external server.
    - Temporary files are automatically **deleted** after your session ends.
    - This application is **not** connected to any external databases or cloud storage.
    
    *For any technical issues, please contact the IT support team.*
    """)
    
    # Footer
    st.markdown("""
    <div style="margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #dee2e6; text-align: center; color: #6c757d; font-size: 0.85rem;">
        UKT IM2 – Internal Use Only
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.info("Once you upload a valid `Rules.xlsx` file, this page will be replaced with the full featured interface.")
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
    
    # Show current configuration summary
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
                # Determine template path
                template_path = st.session_state['template_path']
                if template_path is None:
                    settings_df = config.get("Settings", pd.DataFrame())
                    if not settings_df.empty:
                        template_path = settings_df[settings_df["Setting"] == "TemplateFile"]["Value"].values[0]
                    else:
                        st.error("Template file not found. Please upload one.")
                        st.stop()
                
                # Prepare temporary rules with updated settings
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
                
                # Copy to current directory
                shutil.copy(updated_rules, "Rules.xlsx")
                wishes = st.session_state.get('wishes_path')
                if wishes:
                    shutil.copy(wishes, "wishes.xlsx")
                
                # Run scheduler
                result = run_scheduler(template_path, output_file, "Rules.xlsx", wishes)
                if result:
                    st.success("Schedule generated successfully!")
                    st.session_state['output_file'] = output_file
                    st.balloons()
                else:
                    st.error("Scheduler failed. Please check logs.")
                
                # Cleanup
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
            st.info(f"Sheet '{sheet_name}' not found – it will be created when you save.")
    
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
            st.success("Changes saved successfully!")
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
    st.markdown('</div>', unsafe_allow_html=True)
##############################
########## 260801: v001 ######
# import streamlit as st
# import pandas as pd
# import os
# import tempfile
# import shutil
# from io import BytesIO
# from scheduler import run_scheduler
# from config_loader import load_config
# import openpyxl
# import traceback

# st.set_page_config(page_title="Duty Scheduler", layout="wide")

# # --- Reset session state on page load to avoid stale data ---
# if 'initialized' not in st.session_state:
#     # Clear all keys except a few we want to keep (e.g., file paths)
#     for key in list(st.session_state.keys()):
#         del st.session_state[key]
#     st.session_state['initialized'] = True
#     # We will also reset the editor keys by not setting them yet
#     st.rerun()
# if st.sidebar.button("Clear All Data"):
#     # Delete temporary files
#     if st.session_state.get('rules_file_path') and os.path.exists(st.session_state['rules_file_path']):
#         os.unlink(st.session_state['rules_file_path'])
#     # Clear session state
#     for key in list(st.session_state.keys()):
#         del st.session_state[key]
#     st.rerun()
# # --- Hide Streamlit branding ---
# hide_streamlit_style = """
#     <style>
#     #MainMenu {visibility: hidden;}
#     footer {visibility: hidden;}
#     .stDeployButton {display: none !important;}
#     .stAppDeployButton {display: none !important;}
#     .stApp [data-testid="stToolbar"] {display: none;}
#     .stApp [data-testid="stHeader"] {display: none;}
#     .stApp [data-testid="stHeaderManageApp"] {display: none !important;}
#     .stApp [data-testid="stHeaderAppMenu"] {display: none !important;}
#     /* Hide the "Manage app" dropdown and button */
#     .st-emotion-cache-1v0mbdj {display: none !important;}
#     .st-emotion-cache-1r6slb0 {display: none !important;}
#     </style>
# """

# st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# st.title("UKT IM2")

# # --- Sidebar: File upload ---
# st.sidebar.header("Upload Files") 
# # At the top, after session reset
# if 'config_loaded' not in st.session_state:
#     st.session_state['config_loaded'] = False
#     st.session_state['rules_file_path'] = None
#     st.session_state['uploaded_rules'] = None

# # In the file uploader section:
# rules_file = st.sidebar.file_uploader("Upload Rules.xlsx", type=["xlsx"])
# if rules_file is not None:
#     # Save to temporary file and set session state
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_rules:
#         tmp_rules.write(rules_file.getvalue())
#         rules_path = tmp_rules.name
#     st.session_state['rules_file_path'] = rules_path
#     st.session_state['config_loaded'] = True
#     st.session_state['uploaded_rules'] = rules_file.getvalue()  # store for later
# else:
#     # If no file uploaded, check if we have a stored one
#     if st.session_state.get('rules_file_path') and os.path.exists(st.session_state['rules_file_path']):
#         rules_path = st.session_state['rules_file_path']
#         st.session_state['config_loaded'] = True
#     else:
#         rules_path = None
#         st.session_state['config_loaded'] = False 
#         st.error("Please upload Rules.xlsx")
#         st.stop()
# # Upload Template (Stationsplan)
# template_file = st.sidebar.file_uploader("Upload Template (Stationsplan)", type=["xlsx"])
# if template_file is not None:
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_template:
#         tmp_template.write(template_file.getvalue())
#         template_path = tmp_template.name
#         st.session_state['template_path'] = template_path
# else:
#     if 'template_path' in st.session_state and os.path.exists(st.session_state['template_path']):
#         template_path = st.session_state['template_path']
#     else:
#         template_path = None

# # Upload Wishes (optional)
# wishes_file = st.sidebar.file_uploader("Upload Wishes (optional)", type=["xlsx"])
# if wishes_file is not None:
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_wishes:
#         tmp_wishes.write(wishes_file.getvalue())
#         wishes_path = tmp_wishes.name
#         st.session_state['wishes_path'] = wishes_path
# else:
#     if 'wishes_path' in st.session_state and os.path.exists(st.session_state['wishes_path']):
#         wishes_path = st.session_state['wishes_path']
#     else:
#         wishes_path = None

# st.sidebar.markdown("---")
# if st.sidebar.button("Reload Files"):
#     # Clear the file paths from session state to force re-upload
#     for key in ['rules_path', 'template_path', 'wishes_path']:
#         if key in st.session_state:
#             del st.session_state[key]
#     # Also clear editor keys to reset data
#     for key in list(st.session_state.keys()):
#         if key.startswith('edit_'):
#             del st.session_state[key]
#     st.rerun()

# # Now load the config (Rules.xlsx)
# try:
#     config = load_config(rules_path)
#     # Store config in session state to avoid reloading on every rerun? But we want fresh data.
#     # We'll just load it each time, it's fast.
# except Exception as e:
#     st.error(f"Failed to load Rules.xlsx: {e}")
#     st.stop()

# # --- Main area: tabs ---
# tab1, tab2, tab3 = st.tabs([ "Run Scheduler", "Downloads","Edit Parameters"])
# # tab1, tab2, tab3 = st.tabs(["Edit Parameters", "Run Scheduler", "Downloads"])

# # --- Tab 1: Run Scheduler ---
# with tab1:
#     st.subheader("Run Scheduler")
#     output_file = st.text_input("Output File Name", "Stationsplan_out.xlsx")

#     if st.button("Generate Schedule"):
#         with st.spinner("Running scheduler..."):
#             try:
#                 # Determine template path
#                 if template_path is None:
#                     settings_df = config.get("Settings", pd.DataFrame())
#                     if not settings_df.empty:
#                         template_path = settings_df[settings_df["Setting"] == "TemplateFile"]["Value"].values[0]
#                     else:
#                         st.error("Template file not specified. Please upload or set in Settings.")
#                         st.stop()

#                 # Ensure output directory exists
#                 output_dir = os.path.dirname(output_file)
#                 if output_dir:
#                     os.makedirs(output_dir, exist_ok=True)

#                 # Create a temporary rules file with updated settings
#                 settings_df = config.get("Settings", pd.DataFrame())
#                 settings_df.loc[settings_df["Setting"] == "TemplateFile", "Value"] = template_path
#                 settings_df.loc[settings_df["Setting"] == "OutputFile", "Value"] = output_file
#                 if wishes_path:
#                     settings_df.loc[settings_df["Setting"] == "WishesFile", "Value"] = wishes_path

#                 with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_rules_updated:
#                     with pd.ExcelWriter(tmp_rules_updated.name, engine='openpyxl') as writer:
#                         for sheet, df in config.items():
#                             if sheet == "Settings":
#                                 settings_df.to_excel(writer, sheet_name=sheet, index=False)
#                             else:
#                                 df.to_excel(writer, sheet_name=sheet, index=False)
#                     updated_rules_path = tmp_rules_updated.name

#                 # Copy updated rules to current directory as Rules.xlsx
#                 shutil.copy(updated_rules_path, "Rules.xlsx")
#                 if wishes_path:
#                     shutil.copy(wishes_path, "wishes.xlsx")

#                 from scheduler import run_scheduler as rs
#                 result = rs(template_path, output_file, "Rules.xlsx", wishes_path)
#                 if result:
#                     st.success("Schedule generated successfully!")
#                     st.session_state['output_file'] = output_file
#                     st.session_state['rules_file'] = "Rules.xlsx"
#                 else:
#                     st.error("Scheduler failed. Check logs.")

#             except Exception as e:
#                 st.error(f"Scheduler failed with error:\n\n```\n{e}\n```")
#                 st.code(traceback.format_exc(), language="python")
#             finally:
#                 if os.path.exists(updated_rules_path):
#                     os.unlink(updated_rules_path)

#     # Display log output if available (we'll capture it later)
#     if 'log_output' in st.session_state:
#         st.text_area("Log Output", st.session_state.log_output, height=300)

# # --- Tab 3: Downloads ---
# with tab2:
#     st.subheader("Download Files")

#     if 'output_file' in st.session_state and st.session_state['output_file']:
#         output_path = st.session_state['output_file']
#         if os.path.exists(output_path):
#             with open(output_path, "rb") as f:
#                 st.download_button(
#                     label="Download Generated Schedule",
#                     data=f,
#                     file_name=os.path.basename(output_path),
#                     mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#                 )
#         else:
#             st.info("No generated schedule found. Please run the scheduler first.")

#     # Download updated Rules.xlsx (always available)
#     if os.path.exists(rules_path):
#         with open(rules_path, "rb") as f:
#             st.download_button(
#                 label="Download Updated Rules.xlsx",
#                 data=f,
#                 file_name="Rules_updated.xlsx",
#                 mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#             )

#     # Download template if available
#     if template_path and os.path.exists(template_path):
#         with open(template_path, "rb") as f:
#             st.download_button(
#                 label="Download Template",
#                 data=f,
#                 file_name=os.path.basename(template_path),
#                 mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#             )

# # --- Tab 1: Edit Parameters ---
# with tab3:
#     st.subheader("Parameters Editor")
#     sheets_to_edit = ["Settings", "Doctors", "Stations", "DutyTypes", "Penalties", "Constraints", "GeneralRules", "StationCodeMap"]

#     # We'll use a unique key for each editor that includes a hash of the file content or a version number.
#     # A simple approach: use the modification time of the file or a counter.
#     # Since we already have a session state 'initialized', we can use that as a version.
#     # But we want to reset editors when a new file is uploaded.
#     # We'll store a file_hash or just use the file path.

#     # We'll use the basename of the rules_path as part of the key to force refresh when file changes.
#     import hashlib
#     # Create a hash of the file content (or just use the path)
#     file_key = hashlib.md5(rules_path.encode()).hexdigest()

#     for sheet_name in sheets_to_edit:
#         if sheet_name in config:
#             st.markdown(f"### {sheet_name}")
#             df = config[sheet_name].copy().fillna("")
#             # Use a key that includes the file hash and sheet name
#             editor_key = f"edit_{sheet_name}_{file_key}"
#             edited_df = st.data_editor(df, key=editor_key, use_container_width=True)
#             # Store edited data back to a temporary config
#             # We'll store in session state for saving later
#             st.session_state[f'edited_{sheet_name}'] = edited_df
#         else:
#             st.info(f"Sheet {sheet_name} not found in Rules.xlsx")

#     if st.button("Save Changes to Rules.xlsx"):
#         # Write back all edited sheets
#         with pd.ExcelWriter(rules_path, engine='openpyxl', mode='w') as writer:
#             for sheet_name in sheets_to_edit:
#                 if sheet_name in config:
#                     df = st.session_state.get(f'edited_{sheet_name}')
#                     if df is not None:
#                         df.to_excel(writer, sheet_name=sheet_name, index=False)
#                     else:
#                         # fallback to original
#                         config[sheet_name].to_excel(writer, sheet_name=sheet_name, index=False)
#         st.success("Rules.xlsx updated successfully!")
#         # Reload config and update session state
#         config = load_config(rules_path)
#         # Also update the file hash to refresh editors
#         st.rerun()
 
 