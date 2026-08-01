# app.py

import streamlit as st
import pandas as pd
import os
import tempfile
import shutil
from io import BytesIO
from scheduler import main as run_scheduler
from config_loader import load_config
import openpyxl

st.set_page_config(page_title="Duty Scheduler", layout="wide")
st.title("UKT IM2")

# --- Sidebar: File upload ---
st.sidebar.header("Upload Files")

# Upload Rules.xlsx
rules_file = st.sidebar.file_uploader("Upload Rules.xlsx", type=["xlsx"])
if rules_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_rules:
        tmp_rules.write(rules_file.getvalue())
        rules_path = tmp_rules.name
else:
    # Use default if exists
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
else:
    template_path = None  # will be read from Settings

# Upload Wishes (optional)
wishes_file = st.sidebar.file_uploader("Upload Wishes (optional)", type=["xlsx"])
if wishes_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_wishes:
        tmp_wishes.write(wishes_file.getvalue())
        wishes_path = tmp_wishes.name
else:
    wishes_path = None

st.sidebar.markdown("---")
if st.sidebar.button("Reload Files"):
    st.rerun()

# --- Main area: tabs ---
tab1, tab2, tab3 = st.tabs(["Edit Parameters", "Run Scheduler", "Downloads"])

# Load the config (Rules.xlsx)
try:
    config = load_config(rules_path)
except Exception as e:
    st.error(f"Failed to load Rules.xlsx: {e}")
    st.stop()

# --- Tab 1: Edit Parameters ---
with tab1:
    st.subheader("Parameters Editor")
    # Display editable sheets
    sheets_to_edit = ["Settings", "Doctors", "Stations", "DutyTypes", "Penalties", "Constraints", "GeneralRules", "StationCodeMap"]

    edited_config = {}
    for sheet_name in sheets_to_edit:
        if sheet_name in config:
            st.markdown(f"### {sheet_name}")
            df = config[sheet_name].copy()
            # Replace NaN with empty string for display
            df = df.fillna("")
            edited_df = st.data_editor(df, key=f"edit_{sheet_name}", use_container_width=True)
            edited_config[sheet_name] = edited_df
        else:
            st.info(f"Sheet {sheet_name} not found in Rules.xlsx")

    if st.button("Save Changes to Rules.xlsx"):
        # Write back all sheets to the Rules file
        with pd.ExcelWriter(rules_path, engine='openpyxl', mode='w') as writer:
            for sheet, df in edited_config.items():
                df.to_excel(writer, sheet_name=sheet, index=False)
        # Reload config
        config = load_config(rules_path)
        st.success("Rules.xlsx updated successfully!")

# --- Tab 2: Run Scheduler ---
with tab2:
    st.subheader("Run Scheduler")
    output_file = st.text_input("Output File Name", "Stationsplan_out.xlsx")

    if st.button("▶Generate Schedule"):
        with st.spinner("Running scheduler..."):
            # Determine template path
            if template_path is None:
                # Read from Settings
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

            # Create a temporary copy of rules with updated settings
            # We'll write the template path and output path into the settings sheet
            settings_df = config.get("Settings", pd.DataFrame())
            # Update TemplateFile and OutputFile
            settings_df.loc[settings_df["Setting"] == "TemplateFile", "Value"] = template_path
            settings_df.loc[settings_df["Setting"] == "OutputFile", "Value"] = output_file
            # Save to a temp rules file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_rules_updated:
                with pd.ExcelWriter(tmp_rules_updated.name, engine='openpyxl') as writer:
                    for sheet, df in config.items():
                        if sheet == "Settings":
                            settings_df.to_excel(writer, sheet_name=sheet, index=False)
                        else:
                            df.to_excel(writer, sheet_name=sheet, index=False)
                updated_rules_path = tmp_rules_updated.name

            # Also set wishes path if provided
            if wishes_path and "Settings" in config:
                settings_df.loc[settings_df["Setting"] == "WishesFile", "Value"] = wishes_path
                # We'll just rely on the existing logic in scheduler

            try:
                # Run scheduler (we need to call main with the updated rules path)
                # We'll temporarily set the current directory to the app's directory
                # But we can just call main with the rules path as a global
                # We'll patch scheduler to use the provided rules path.
                # Since main() reads from 'Rules.xlsx' hardcoded, we'll need to override.
                # Simple: we can set a global variable or use an environment variable.
                # Easiest: we'll modify main() to accept config_path argument.
                # But to avoid changing scheduler.py, we'll use a context manager that changes the working directory? Not ideal.
                # We'll instead copy the updated rules to a file named 'Rules.xlsx' in the current directory.
                # Then call main().
                # We'll copy the updated rules to ./Rules.xlsx (temporary)
                shutil.copy(updated_rules_path, "Rules.xlsx")
                # Also copy wishes if provided
                if wishes_path:
                    shutil.copy(wishes_path, "wishes.xlsx")  # but main expects the path from settings
                # We'll also set the wishes path in settings if not set

                # Now call main() – it will use ./Rules.xlsx and the template file from settings.
                # We'll use sys.argv to pass? Not needed.
                # We'll just call main() directly.
                # However, main() currently doesn't accept arguments.
                # We'll need to modify scheduler.py to accept them.
                # Let's create a wrapper in scheduler.py: run_scheduler(template_path, output_path, config_path, wishes_path)
                # We'll implement that now.

                # For now, we'll call a new function that we'll add to scheduler.py
                # We'll import run_scheduler from scheduler
                from scheduler import run_scheduler as rs
                result = rs(template_path, output_file, rules_path, wishes_path)
                if result:
                    st.success("Schedule generated successfully!")
                    st.session_state['output_file'] = output_file
                    st.session_state['rules_file'] = rules_path
                else:
                    st.error("Scheduler failed. Check logs.")
            except Exception as e:
                st.error(f"Error: {e}")
            finally:
                # Clean up temp files
                if os.path.exists(updated_rules_path):
                    os.unlink(updated_rules_path)

    # Display log output if available
    if 'log_output' in st.session_state:
        st.text_area("Log Output", st.session_state.log_output, height=300)

# --- Tab 3: Downloads ---
with tab3:
    st.subheader("Download Files")

    if 'output_file' in st.session_state and os.path.exists(st.session_state['output_file']):
        with open(st.session_state['output_file'], "rb") as f:
            st.download_button(
                label="📊 Download Generated Schedule",
                data=f,
                file_name=os.path.basename(st.session_state['output_file']),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    if os.path.exists(rules_path):
        with open(rules_path, "rb") as f:
            st.download_button(
                label="Download Updated Rules.xlsx",
                data=f,
                file_name="Rules_updated.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # Also allow download of the original template if uploaded
    if template_path and os.path.exists(template_path):
        with open(template_path, "rb") as f:
            st.download_button(
                label="Download Template",
                data=f,
                file_name=os.path.basename(template_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )