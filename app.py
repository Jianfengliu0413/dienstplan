
import streamlit as st
import pandas as pd
import os
import tempfile
import shutil
from io import BytesIO
from scheduler import run_scheduler
from config_loader import load_config
import openpyxl
import traceback

st.set_page_config(page_title="Duty Scheduler", layout="wide")

# --- Reset session state on page load to avoid stale data ---
if 'initialized' not in st.session_state:
    # Clear all keys except a few we want to keep (e.g., file paths)
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state['initialized'] = True
    # We will also reset the editor keys by not setting them yet
    st.rerun()

# --- Hide Streamlit branding ---
hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none !important;}
    .stAppDeployButton {display: none !important;}
    header {visibility: hidden;}
    .stAppHeader {display: none !important;}
    .stApp [data-testid="stToolbar"] {display: none;}
    .stApp [data-testid="stHeader"] {display: none;}
    .stApp [data-testid="stHeaderManageApp"] {display: none !important;}
    .stApp [data-testid="stHeaderAppMenu"] {display: none !important;}
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

st.title("UKT IM2")

# --- Sidebar: File upload ---
st.sidebar.header("Upload Files")

# We'll use a file uploader that triggers a rerun when a new file is uploaded
# We'll store the file paths in session state so they persist across reruns

# Upload Rules.xlsx
rules_file = st.sidebar.file_uploader("Upload Rules.xlsx", type=["xlsx"], key="rules_uploader")
if rules_file is not None:
    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_rules:
        tmp_rules.write(rules_file.getvalue())
        rules_path = tmp_rules.name
        # Store in session state
        st.session_state['rules_path'] = rules_path
else:
    # If no new file uploaded, check if we have a previous path
    if 'rules_path' in st.session_state and os.path.exists(st.session_state['rules_path']):
        rules_path = st.session_state['rules_path']
    else:
        # Fallback to default
        if os.path.exists("Rules.xlsx"):
            rules_path = "Rules.xlsx"
        else:
            st.error("Please upload Rules.xlsx")
            st.stop()

# Upload Template (Stationsplan)
template_file = st.sidebar.file_uploader("Upload Template (Stationsplan)", type=["xlsx"])
if template_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_template:
        tmp_template.write(template_file.getvalue())
        template_path = tmp_template.name
        st.session_state['template_path'] = template_path
else:
    if 'template_path' in st.session_state and os.path.exists(st.session_state['template_path']):
        template_path = st.session_state['template_path']
    else:
        template_path = None

# Upload Wishes (optional)
wishes_file = st.sidebar.file_uploader("Upload Wishes (optional)", type=["xlsx"])
if wishes_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_wishes:
        tmp_wishes.write(wishes_file.getvalue())
        wishes_path = tmp_wishes.name
        st.session_state['wishes_path'] = wishes_path
else:
    if 'wishes_path' in st.session_state and os.path.exists(st.session_state['wishes_path']):
        wishes_path = st.session_state['wishes_path']
    else:
        wishes_path = None

st.sidebar.markdown("---")
if st.sidebar.button("Reload Files"):
    # Clear the file paths from session state to force re-upload
    for key in ['rules_path', 'template_path', 'wishes_path']:
        if key in st.session_state:
            del st.session_state[key]
    # Also clear editor keys to reset data
    for key in list(st.session_state.keys()):
        if key.startswith('edit_'):
            del st.session_state[key]
    st.rerun()

# Now load the config (Rules.xlsx)
try:
    config = load_config(rules_path)
    # Store config in session state to avoid reloading on every rerun? But we want fresh data.
    # We'll just load it each time, it's fast.
except Exception as e:
    st.error(f"Failed to load Rules.xlsx: {e}")
    st.stop()

# --- Main area: tabs ---
tab1, tab2, tab3 = st.tabs([ "Run Scheduler", "Downloads","Edit Parameters"])
# tab1, tab2, tab3 = st.tabs(["Edit Parameters", "Run Scheduler", "Downloads"])

# --- Tab 1: Run Scheduler ---
with tab1:
    st.subheader("Run Scheduler")
    output_file = st.text_input("Output File Name", "Stationsplan_out.xlsx")

    if st.button("Generate Schedule"):
        with st.spinner("Running scheduler..."):
            try:
                # Determine template path
                if template_path is None:
                    settings_df = config.get("Settings", pd.DataFrame())
                    if not settings_df.empty:
                        template_path = settings_df[settings_df["Setting"] == "TemplateFile"]["Value"].values[0]
                    else:
                        st.error("Template file not specified. Please upload or set in Settings.")
                        st.stop()

                # Ensure output directory exists
                output_dir = os.path.dirname(output_file)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                # Create a temporary rules file with updated settings
                settings_df = config.get("Settings", pd.DataFrame())
                settings_df.loc[settings_df["Setting"] == "TemplateFile", "Value"] = template_path
                settings_df.loc[settings_df["Setting"] == "OutputFile", "Value"] = output_file
                if wishes_path:
                    settings_df.loc[settings_df["Setting"] == "WishesFile", "Value"] = wishes_path

                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_rules_updated:
                    with pd.ExcelWriter(tmp_rules_updated.name, engine='openpyxl') as writer:
                        for sheet, df in config.items():
                            if sheet == "Settings":
                                settings_df.to_excel(writer, sheet_name=sheet, index=False)
                            else:
                                df.to_excel(writer, sheet_name=sheet, index=False)
                    updated_rules_path = tmp_rules_updated.name

                # Copy updated rules to current directory as Rules.xlsx
                shutil.copy(updated_rules_path, "Rules.xlsx")
                if wishes_path:
                    shutil.copy(wishes_path, "wishes.xlsx")

                from scheduler import run_scheduler as rs
                result = rs(template_path, output_file, "Rules.xlsx", wishes_path)
                if result:
                    st.success("Schedule generated successfully!")
                    st.session_state['output_file'] = output_file
                    st.session_state['rules_file'] = "Rules.xlsx"
                else:
                    st.error("Scheduler failed. Check logs.")

            except Exception as e:
                st.error(f"Scheduler failed with error:\n\n```\n{e}\n```")
                st.code(traceback.format_exc(), language="python")
            finally:
                if os.path.exists(updated_rules_path):
                    os.unlink(updated_rules_path)

    # Display log output if available (we'll capture it later)
    if 'log_output' in st.session_state:
        st.text_area("Log Output", st.session_state.log_output, height=300)

# --- Tab 3: Downloads ---
with tab2:
    st.subheader("Download Files")

    if 'output_file' in st.session_state and st.session_state['output_file']:
        output_path = st.session_state['output_file']
        if os.path.exists(output_path):
            with open(output_path, "rb") as f:
                st.download_button(
                    label="Download Generated Schedule",
                    data=f,
                    file_name=os.path.basename(output_path),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.info("No generated schedule found. Please run the scheduler first.")

    # Download updated Rules.xlsx (always available)
    if os.path.exists(rules_path):
        with open(rules_path, "rb") as f:
            st.download_button(
                label="Download Updated Rules.xlsx",
                data=f,
                file_name="Rules_updated.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # Download template if available
    if template_path and os.path.exists(template_path):
        with open(template_path, "rb") as f:
            st.download_button(
                label="Download Template",
                data=f,
                file_name=os.path.basename(template_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# --- Tab 1: Edit Parameters ---
with tab3:
    st.subheader("Parameters Editor")
    sheets_to_edit = ["Settings", "Doctors", "Stations", "DutyTypes", "Penalties", "Constraints", "GeneralRules", "StationCodeMap"]

    # We'll use a unique key for each editor that includes a hash of the file content or a version number.
    # A simple approach: use the modification time of the file or a counter.
    # Since we already have a session state 'initialized', we can use that as a version.
    # But we want to reset editors when a new file is uploaded.
    # We'll store a file_hash or just use the file path.

    # We'll use the basename of the rules_path as part of the key to force refresh when file changes.
    import hashlib
    # Create a hash of the file content (or just use the path)
    file_key = hashlib.md5(rules_path.encode()).hexdigest()

    for sheet_name in sheets_to_edit:
        if sheet_name in config:
            st.markdown(f"### {sheet_name}")
            df = config[sheet_name].copy().fillna("")
            # Use a key that includes the file hash and sheet name
            editor_key = f"edit_{sheet_name}_{file_key}"
            edited_df = st.data_editor(df, key=editor_key, use_container_width=True)
            # Store edited data back to a temporary config
            # We'll store in session state for saving later
            st.session_state[f'edited_{sheet_name}'] = edited_df
        else:
            st.info(f"Sheet {sheet_name} not found in Rules.xlsx")

    if st.button("Save Changes to Rules.xlsx"):
        # Write back all edited sheets
        with pd.ExcelWriter(rules_path, engine='openpyxl', mode='w') as writer:
            for sheet_name in sheets_to_edit:
                if sheet_name in config:
                    df = st.session_state.get(f'edited_{sheet_name}')
                    if df is not None:
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
                    else:
                        # fallback to original
                        config[sheet_name].to_excel(writer, sheet_name=sheet_name, index=False)
        st.success("Rules.xlsx updated successfully!")
        # Reload config and update session state
        config = load_config(rules_path)
        # Also update the file hash to refresh editors
        st.rerun()
 

# # app.py

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
# # Reset session state on page load (clears previous data)
# if 'initialized' not in st.session_state:
#     for key in list(st.session_state.keys()):
#         del st.session_state[key]
#     st.session_state['initialized'] = True
#     st.rerun()

# # Hide Streamlit branding 
# hide_streamlit_style = """
#     <style>
#     /* Hide main menu */
#     #MainMenu {visibility: hidden;}
    
#     /* Hide footer */
#     footer {visibility: hidden;}
    
#     /* Hide deploy button / Hosted with Streamlit */
#     .stDeployButton {display: none !important;}
#     .stAppDeployButton {display: none !important;}
    
#     /* Hide the entire header (including "Manage app") */
#     header {visibility: hidden;}
#     .stAppHeader {display: none !important;}
    
#     /* Hide toolbar and GitHub icons */
#     .stApp [data-testid="stToolbar"] {display: none;}
#     .stApp [data-testid="stHeader"] {display: none;}
    
#     /* Hide the "Manage app" button specifically */
#     .stApp [data-testid="stHeaderManageApp"] {display: none !important;}
#     .stApp [data-testid="stHeaderAppMenu"] {display: none !important;}
#     </style>
# """
# st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# st.title("UKT IM2")

# # Clear session button
# if st.sidebar.button("Clear Session"):
#     st.session_state.clear()
#     st.session_state["initialized"] = True
#     # st.rerun()

# if st.sidebar.button("Clear All Data"):
#     for key in list(st.session_state.keys()):
#         del st.session_state[key]
#     st.rerun()
# # --- Sidebar: File upload and session controls ---
# st.sidebar.header("Upload Files")


# # Upload Rules.xlsx
# rules_file = st.sidebar.file_uploader("Upload Rules.xlsx", type=["xlsx"])
# if rules_file is not None:
#     # Reset output file if new rules uploaded
#     if 'output_file' in st.session_state:
#         st.session_state['output_file'] = None
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_rules:
#         tmp_rules.write(rules_file.getvalue())
#         rules_path = tmp_rules.name
# else:
#     # Use default if exists
#     if os.path.exists("Rules.xlsx"):
#         rules_path = "Rules.xlsx"
#     else:
#         st.error("Please upload Rules.xlsx")
#         st.stop()

# # Upload Template (Stationsplan)
# template_file = st.sidebar.file_uploader("Upload Template (Stationsplan)", type=["xlsx"])
# if template_file is not None:
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_template:
#         tmp_template.write(template_file.getvalue())
#         template_path = tmp_template.name
# else:
#     template_path = None  # will be read from Settings

# # Upload Wishes (optional)
# wishes_file = st.sidebar.file_uploader("Upload Wishes (optional)", type=["xlsx"])
# if wishes_file is not None:
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_wishes:
#         tmp_wishes.write(wishes_file.getvalue())
#         wishes_path = tmp_wishes.name
# else:
#     wishes_path = None

# st.sidebar.markdown("---")
# if st.sidebar.button("Reload Files"):
#     st.rerun()

# # --- Main area: tabs ---
# tab1, tab2, tab3 = st.tabs([ "Run Scheduler", "Downloads","Edit Parameters"])

# # Load the config (Rules.xlsx)
# try:
#     config = load_config(rules_path)
# except Exception as e:
#     st.error(f"Failed to load Rules.xlsx: {e}")
#     st.stop()


# # --- Tab 3: Edit Parameters ---
# with tab3:
#     st.subheader("Parameters Editor")
#     # Display editable sheets
#     sheets_to_edit = ["Settings", "Doctors", "Stations", "DutyTypes", "Penalties", "Constraints", "GeneralRules", "StationCodeMap"]

#     edited_config = {}
#     for sheet_name in sheets_to_edit:
#         if sheet_name in config:
#             st.markdown(f"### {sheet_name}")
#             df = config[sheet_name].copy()
#             df = df.fillna("")
#             edited_df = st.data_editor(df, key=f"edit_{sheet_name}", use_container_width=True)
#             edited_config[sheet_name] = edited_df
#         else:
#             st.info(f"Sheet {sheet_name} not found in Rules.xlsx")

#     if st.button("Save Changes to Rules.xlsx"):
#         with pd.ExcelWriter(rules_path, engine='openpyxl', mode='w') as writer:
#             for sheet, df in edited_config.items():
#                 df.to_excel(writer, sheet_name=sheet, index=False)
#         config = load_config(rules_path)
#         st.success("Rules.xlsx updated successfully!")
