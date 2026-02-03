import streamlit as st
import pandas as pd
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import gspread
import io
import json
import pypdf
import time

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="NBFC Competitive Intelligence", layout="wide")

# --- 2. PASSWORD PROTECTION ---
def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == st.secrets["passwords"]["ceo"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Enter Access Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Enter Access Password", type="password", on_change=password_entered, key="password")
        st.error("❌ Incorrect Password")
        return False
    else:
        return True

if check_password():
    
    # --- CONSTANTS ---
    TRACKED_QUARTERS = ["Q3FY26", "Q2FY26", "Q1FY26", "Q4FY25", "Q3FY25", "Q2FY25", "Q1FY25", "FY24"]
    PILLAR_MAP = {
        "Financial Health": ["NIM_Spreads", "Fee_Income_Ratio", "Cost_to_Income", "RoA", "RoE", "Credit_Cost"],
        "Asset Quality": ["GNPA", "NNPA", "Stage_2_Assets", "Stage_3_Assets", "Collection_Efficiency", "Concentration_Risk"],
        "Growth Engine": ["AUM_Growth", "Disbursement_Velocity", "Co_Lending_Share", "Product_Strategy"],
        "Funding & Liquidity": ["Cost_of_Funds", "Liability_Mix", "ALM_Gap", "Direct_Assignment"],
        "Digital & Tech": ["Digital_Sourcing_Percent", "Productivity_Metrics", "Tech_Stack_AI", "Customer_Friction_TAT"],
        "Soft Power": ["Capital_Adequacy_CRAR", "Regulatory_Standing", "Leadership_Depth", "ESG_Score"]
    }

    # --- HELPERS ---
    def get_gspread_client():
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        return gspread.authorize(creds)

    def get_drive_service():
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=creds)

    def get_tab_if_exists(sheet, tab_name):
        try:
            return sheet.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            return None 

    def get_existing_data(worksheet, quarter):
        try:
            all_records = worksheet.get_all_records()
            df = pd.DataFrame(all_records)
            if df.empty: return None
            # Check if Quarter column exists and has data
            if "Quarter" not in df.columns: return None
            row = df[df["Quarter"] == quarter]
            if not row.empty:
                return row.iloc[0].to_dict()
            return None
        except Exception as e:
            st.error(f"DB Read Error: {e}")
            return None

    def save_to_sheet(worksheet, data, quarter):
        # Maps JSON keys to the specific Sheet Column Order
        row = [
            quarter,
            data.get("NIM_Spreads", "-"), data.get("Fee_Income_Ratio", "-"), data.get("Cost_to_Income", "-"), data.get("RoA", "-"), data.get("RoE", "-"), data.get("Credit_Cost", "-"),
            data.get("GNPA", "-"), data.get("NNPA", "-"), data.get("Stage_2_Assets", "-"), data.get("Stage_3_Assets", "-"), data.get("Collection_Efficiency", "-"), data.get("Concentration_Risk", "-"),
            data.get("AUM_Growth", "-"), data.get("Disbursement_Velocity", "-"), data.get("Co_Lending_Share", "-"), data.get("Product_Strategy", "-"),
            data.get("Cost_of_Funds", "-"), data.get("Liability_Mix", "-"), data.get("ALM_Gap", "-"), data.get("Direct_Assignment", "-"),
            data.get("Digital_Sourcing_Percent", "-"), data.get("Productivity_Metrics", "-"), data.get("Tech_Stack_AI", "-"), data.get("Customer_Friction_TAT", "-"),
            data.get("Capital_Adequacy_CRAR", "-"), data.get("Regulatory_Standing", "-"), data.get("Leadership_Depth", "-"), data.get("ESG_Score", "-")
        ]
        worksheet.append_row(row)

    def analyze_content(combined_text, competitor):
        genai.configure(api_key=st.secrets["gemini_api_key"])
        try:
            model = genai.GenerativeModel("gemini-1.5-flash") # Safe default
            
            prompt = f"""
            You are a Strategic Analyst analyzing {competitor}. 
            Source Material: **Investor Presentation / Earnings Call Transcript**.
            
            **OUTPUT RULES:**
            1. **FINANCIALS:** BE CONCISE. Numbers only. Format: "2.5% (down 10bps)". Normalize to INR Cr.
            2. **STRATEGY:** Provide 2-3 sentences of context/commentary from management.

            EXTRACT DATA STRICTLY INTO JSON:
            {{
                "NIM_Spreads": "...", "Fee_Income_Ratio": "...", "Cost_to_Income": "...", "RoA": "...", "RoE": "...", "Credit_Cost": "...",
                "GNPA": "...", "NNPA": "...", "Stage_2_Assets": "...", "Stage_3_Assets": "...", "Collection_Efficiency": "...", "Concentration_Risk": "...",
                "AUM_Growth": "...", "Disbursement_Velocity": "...", "Co_Lending_Share": "...", "Product_Strategy": "...",
                "Cost_of_Funds": "...", "Liability_Mix": "...", "ALM_Gap": "...", "Direct_Assignment": "...",
                "Digital_Sourcing_Percent": "...", "Productivity_Metrics": "...", "Tech_Stack_AI": "...", "Customer_Friction_TAT": "...",
                "Capital_Adequacy_CRAR": "...", "Regulatory_Standing": "...", "Leadership_Depth": "...", "ESG_Score": "..."
            }}
            """
            response = model.generate_content([prompt, combined_text])
            raw_text = response.text
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0]
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1]
            return json.loads(raw_text)
        except Exception as e:
            st.error(f"AI Error: {e}")
            return None

    def find_and_extract_all_docs(comp, qtr):
        service = get_drive_service()
        # Loose match search
        query = f"name contains '{comp}' and name contains '{qtr}' and mimeType = 'application/pdf' and trashed = false"
        
        try:
            results = service.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])
            
            if not files: 
                return None, f"No files found for {comp} {qtr}"
            
            full_text = ""
            file_names = []
            for file in files:
                file_names.append(file['name'])
                request = service.files().get_media(fileId=file['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done: _, done = downloader.next_chunk()
                
                try:
                    pdf = pypdf.PdfReader(fh)
                    for page in pdf.pages:
                        if page.extract_text(): full_text += page.extract_text() + "\n"
                except: pass
            
            return full_text, file_names
        except Exception as e:
            return None, str(e)

    # --- UI ---
    st.title("🏦 NBFC Competitive Intelligence")
    st.markdown("---")

    with st.container():
        col1, col2 = st.columns([1, 2])
        with col1:
            analysis_mode = st.radio("Select View:", ["Financial Analysis", "Strategic Analysis"])
            selected_competitors = st.multiselect("Competitors", ["SBFC","Poonawala","FedFina","Tata Capital", "HDB"], default=["SBFC"])
        with col2:
            if "Financial" in analysis_mode:
                selected_quarters = st.multiselect("Quarters", TRACKED_QUARTERS, default=[TRACKED_QUARTERS[0]])
                selected_pillars = ["Financial Health", "Funding & Liquidity", "Asset Quality"]
            else:
                selected_pillars = st.multiselect("Pillars", list(PILLAR_MAP.keys()), default=["Asset Quality", "Growth Engine"])
                selected_quarters = st.multiselect("Quarters", TRACKED_QUARTERS, default=[TRACKED_QUARTERS[0]])

    st.markdown("###")
    if st.button("🚀 Generate Report", type="primary"):
        if not selected_competitors:
            st.error("Select at least one competitor.")
            st.stop()

        gc = get_gspread_client()
        sh = gc.open_by_key(st.secrets["sheet_id"])
        final_results = {}
        
        # STATUS CONTAINER
        status_box = st.status("Processing Data...", expanded=True)

        for comp in selected_competitors:
            status_box.write(f"**Checking {comp}...**")
            
            # 1. CHECK TAB
            ws = get_tab_if_exists(sh, comp)
            if not ws:
                status_box.warning(f"⚠️ Tab '{comp}' NOT found in Sheet. Skipping.")
                continue # Skip to next competitor
            
            comp_data = []
            for qtr in selected_quarters:
                # 2. CHECK EXISTING DATA
                db_data = get_existing_data(ws, qtr)
                if db_data:
                    status_box.success(f"✅ Found Data for {comp} | {qtr}")
                    comp_data.append(db_data)
                else:
                    # 3. FETCH FROM DRIVE
                    status_box.write(f"🔍 Searching Drive for {comp} {qtr}...")
                    text, info = find_and_extract_all_docs(comp, qtr)
                    
                    if text:
                        status_box.info(f"📄 Found: {info}. Analyzing with AI...")
                        ai_data = analyze_content(text, comp)
                        if ai_data:
                            save_to_sheet(ws, ai_data, qtr)
                            ai_data["Quarter"] = qtr
                            comp_data.append(ai_data)
                            status_box.success(f"💾 Saved New Data for {comp} {qtr}")
                    else:
                        status_box.error(f"❌ {info} (No PDF in Drive)")
            
            if comp_data:
                final_results[comp] = pd.DataFrame(comp_data)

        status_box.update(label="Processing Complete!", state="complete", expanded=False)
        st.divider()

        # --- MATRIX GENERATOR ---
        def render_matrix(quarter, pillars):
            st.subheader(f"🗓️ Period: {quarter}")
            matrix_rows = []
            
            for pillar in pillars:
                metrics = PILLAR_MAP.get(pillar, [])
                for metric in metrics:
                    row = {"Category": pillar, "Metric": metric}
                    for comp in selected_competitors:
                        df = final_results.get(comp)
                        val = "No Data"
                        if df is not None and not df.empty:
                            match = df[df["Quarter"] == quarter]
                            if not match.empty:
                                val = match.iloc[0].get(metric, "-")
                        row[comp] = val
                    matrix_rows.append(row)
            
            if matrix_rows:
                df_view = pd.DataFrame(matrix_rows)
                
                # STYLING
                styled = df_view.style.set_properties(**{
                    'white-space': 'normal', 'height': 'auto', 'border': '1px solid #e6e9ef', 'color': 'black'
                }).set_table_styles([
                    {'selector': 'th', 'props': [('background-color', '#2b2b2b'), ('color', 'white'), ('font-weight', 'bold')]},
                    {'selector': 'td:nth-child(1)', 'props': [('font-weight', 'bold'), ('background-color', '#f0f2f6')]},
                    {'selector': 'td:nth-child(2)', 'props': [('font-weight', 'bold'), ('background-color', '#f0f2f6')]}
                ])
                
                cols_config = {
                    "Category": st.column_config.TextColumn("Category", width="small"),
                    "Metric": st.column_config.TextColumn("Metric", width="medium")
                }
                for comp in selected_competitors:
                    cols_config[comp] = st.column_config.TextColumn(comp, width="large")

                st.dataframe(styled, use_container_width=True, column_config=cols_config, hide_index=True)
            else:
                st.info(f"No Data Available for {quarter}")

        if not final_results:
            st.warning("No data found for any selected competitor.")
        else:
            for qtr in selected_quarters:
                render_matrix(qtr, selected_pillars)
