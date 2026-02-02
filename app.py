import streamlit as st

def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["passwords"]["ceo"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "Please enter the access password", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password incorrect, show input + error.
        st.text_input(
            "Please enter the access password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True

if check_password():
    # --- PASTE YOUR ENTIRE EXISTING APP CODE HERE ---
    st.title("🏦 NBFC Competitive Intelligence")
    # ... rest of your code ...


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

# --- CONFIGURATION ---
st.set_page_config(page_title="NBFC Competitive Intelligence", layout="wide")

# Fixed Lists for "All Periods" Logic
TRACKED_QUARTERS = [
    "Q3FY26", "Q2FY26", "Q1FY26", 
    "Q4FY25", "Q3FY25", "Q2FY25", "Q1FY25",
    "FY24"
]

# --- STRATEGIC PILLAR MAPPING ---
PILLAR_MAP = {
    "Financial Health": ["NIM_Spreads", "Fee_Income_Ratio", "Cost_to_Income", "RoA", "RoE", "Credit_Cost"],
    "Asset Quality": ["GNPA", "NNPA", "Stage_2_Assets", "Stage_3_Assets", "Collection_Efficiency", "Concentration_Risk"],
    "Growth Engine": ["AUM_Growth", "Disbursement_Velocity", "Co_Lending_Share", "Product_Strategy"],
    "Funding & Liquidity": ["Cost_of_Funds", "Liability_Mix", "ALM_Gap", "Direct_Assignment"],
    "Digital & Tech": ["Digital_Sourcing_Percent", "Productivity_Metrics", "Tech_Stack_AI", "Customer_Friction_TAT"],
    "Soft Power": ["Capital_Adequacy_CRAR", "Regulatory_Standing", "Leadership_Depth", "ESG_Score"]
}

# --- AUTHENTICATION ---
def get_gspread_client():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    return gspread.authorize(creds)

def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)

# --- STRICT DATABASE MANAGER ---
def get_tab_if_exists(sheet, tab_name):
    """
    STRICT CHECK: Returns the worksheet if it exists. 
    Returns None if it does not exist (DOES NOT CREATE).
    """
    try:
        worksheet = sheet.worksheet(tab_name)
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
        return None 

def get_existing_data(worksheet, quarter):
    """Fetches the row for the existing quarter."""
    try:
        all_records = worksheet.get_all_records()
        df = pd.DataFrame(all_records)
        if df.empty: return None
        row = df[df["Quarter"] == quarter]
        if not row.empty:
            return row.iloc[0].to_dict()
        return None
    except:
        return None

def save_to_sheet(worksheet, data, quarter):
    """Saves the AI extracted data into the sheet."""
    row = [
        quarter,
        data.get("NIM_Spreads"), data.get("Fee_Income_Ratio"), data.get("Cost_to_Income"), data.get("RoA"), data.get("RoE"), data.get("Credit_Cost"),
        data.get("GNPA"), data.get("NNPA"), data.get("Stage_2_Assets"), data.get("Stage_3_Assets"), data.get("Collection_Efficiency"), data.get("Concentration_Risk"),
        data.get("AUM_Growth"), data.get("Disbursement_Velocity"), data.get("Co_Lending_Share"), data.get("Product_Strategy"),
        data.get("Cost_of_Funds"), data.get("Liability_Mix"), data.get("ALM_Gap"), data.get("Direct_Assignment"),
        data.get("Digital_Sourcing_Percent"), data.get("Productivity_Metrics"), data.get("Tech_Stack_AI"), data.get("Customer_Friction_TAT"),
        data.get("Capital_Adequacy_CRAR"), data.get("Regulatory_Standing"), data.get("Leadership_Depth"), data.get("ESG_Score")
    ]
    worksheet.append_row(row)

# --- BULLETPROOF AI ENGINE (INVENTORY BASED) ---
def analyze_content(combined_text, competitor):
    """
    Analyzes text from BOTH Presentation and Transcript.
    """
    genai.configure(api_key=st.secrets["gemini_api_key"])
            
    # 1. GET VALID MODELS FROM GOOGLE (NO GUESSING)
    try:
        all_models = list(genai.list_models())
        valid_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        
        # Priority: Flash (Large Context Window) -> Pro -> Others
        def model_priority(name):
            if "1.5-flash" in name: return 0  # Best for large transcripts
            if "1.5-pro" in name: return 1
            if "gemini-pro" in name: return 2
            return 3
            
        valid_models.sort(key=model_priority)
        
        if not valid_models:
             st.error("Your API Key has no access to any generative models.")
             return None
             
    except Exception as e:
        st.error(f"Failed to fetch model list: {e}")
        return None

    # 6-PILLAR PROMPT - HYBRID CONCISENESS RULE
    prompt = f"""
    You are a BCG Partner analyzing {competitor}. 
    I have provided text from the **Investor Presentation AND/OR Earnings Call Transcript**.
    
    Synthesize information from both sources. 
    - Use the Transcript to find "Management Commentary" regarding Strategy, Future Guidance, and nuances.
    - Use the Presentation for hard numbers (NIM, GNPA, AUM).

    **CRITICAL OUTPUT RULES:**
    1. **FINANCIAL METRICS (NIM, GNPA, RoA, Cost of Funds, etc.):** - BE EXTREMELY CONCISE. Max 10-15 words.
       - Format: "Value (YoY/QoQ change)".
       - Example: "2.5% (down 10bps QoQ)" 

    2. **STRATEGIC/NON-FINANCIAL METRICS (Growth, Digital, Soft Power, etc.):**
       - **PROVIDE COMMENTARY.** Use 2-3 sentences.
       - Explain the "Why" and "How" based on the transcript.
       - Example: "Launched 'Udaan' app for rural market to reduce acquisition costs by 15%. CEO emphasized focus on Tier-3 cities due to saturation in metros."

    EXTRACT DATA STRICTLY INTO JSON.

    PILLAR 1: FINANCIAL HEALTH (Concise)
    - NIM_Spreads
    - Fee_Income_Ratio
    - Cost_to_Income
    - RoA
    - RoE
    - Credit_Cost

    PILLAR 2: ASSET QUALITY (Concise)
    - GNPA
    - NNPA
    - Stage_2_Assets
    - Stage_3_Assets
    - Collection_Efficiency
    - Concentration_Risk

    PILLAR 3: GROWTH (Descriptive - 2/3 sentences)
    - AUM_Growth
    - Disbursement_Velocity
    - Co_Lending_Share
    - Product_Strategy

    PILLAR 4: FUNDING (Concise)
    - Cost_of_Funds
    - Liability_Mix
    - ALM_Gap
    - Direct_Assignment

    PILLAR 5: DIGITAL (Descriptive - 2/3 sentences)
    - Digital_Sourcing_Percent
    - Productivity_Metrics
    - Tech_Stack_AI
    - Customer_Friction_TAT

    PILLAR 6: SOFT POWER (Descriptive - 2/3 sentences)
    - Capital_Adequacy_CRAR
    - Regulatory_Standing
    - Leadership_Depth
    - ESG_Score

    OUTPUT FORMAT:
    Single JSON object matching exactly these keys:
    {{
        "NIM_Spreads": "...", "Fee_Income_Ratio": "...", "Cost_to_Income": "...", "RoA": "...", "RoE": "...", "Credit_Cost": "...",
        "GNPA": "...", "NNPA": "...", "Stage_2_Assets": "...", "Stage_3_Assets": "...", "Collection_Efficiency": "...", "Concentration_Risk": "...",
        "AUM_Growth": "...", "Disbursement_Velocity": "...", "Co_Lending_Share": "...", "Product_Strategy": "...",
        "Cost_of_Funds": "...", "Liability_Mix": "...", "ALM_Gap": "...", "Direct_Assignment": "...",
        "Digital_Sourcing_Percent": "...", "Productivity_Metrics": "...", "Tech_Stack_AI": "...", "Customer_Friction_TAT": "...",
        "Capital_Adequacy_CRAR": "...", "Regulatory_Standing": "...", "Leadership_Depth": "...", "ESG_Score": "..."
    }}
    If data is missing, put "Not Disclosed". 
    """

    # 3. SURVIVOR LOOP
    last_error = None
    
    for model_name in valid_models:
        try:
            model = genai.GenerativeModel(model_name)
            # Send the MASSIVE combined text
            response = model.generate_content([prompt, combined_text])
            
            # Clean JSON
            raw_text = response.text
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0]
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1]
            
            return json.loads(raw_text) 
            
        except Exception as e:
            last_error = e
            continue 

    st.error(f"Analysis Failed. Last Error: {last_error}")
    return None

# --- DRIVE SEARCH & EXTRACT (UPDATED FOR MULTI-FILE) ---
def find_and_extract_all_docs(comp, qtr):
    """
    Searches for ALL matching PDFs (Presentations AND Transcripts).
    Returns combined text from all of them.
    """
    service = get_drive_service()
    # Loose match search: Finds "Bajaj Q3 Presentation" AND "Bajaj Q3 Transcript"
    query = f"name contains '{comp}' and name contains '{qtr}' and mimeType = 'application/pdf' and trashed = false"
    
    try:
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if not files: return None
        
        full_combined_text = ""
        files_found = []
        
        for file in files:
            files_found.append(file['name'])
            # Download
            request = service.files().get_media(fileId=file['id'])
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            
            # Extract Text
            try:
                pdf_reader = pypdf.PdfReader(fh)
                for page in pdf_reader.pages:
                    if page.extract_text():
                        full_combined_text += page.extract_text() + "\n"
            except:
                pass # Skip unreadable files
        
        return full_combined_text

    except Exception as e:
        st.error(f"Drive Error: {e}")
        return None

# --- MAIN UI ---
st.title("🏦 NBFC Competitive Intelligence")
st.markdown("---")

# 1. INPUT SECTION
with st.container():
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Configuration")
        analysis_mode = st.radio("Select Analysis Type:", ["Financial Analysis (Spreadsheet)", "Strategic Analysis (Executive Matrix)"])
        
        # SHARED INPUT: Competitors
        selected_competitors = st.multiselect(
            "Select Competitors", 
            ["SBFC","Poonawala","FedFina","Tata Capital", "HDB"],
            default=["SBFC",]
        )

    with col2:
        st.subheader("Parameters")
        if "Financial" in analysis_mode:
            # Financial Mode: NEEDS SIDE-BY-SIDE MATRIX NOW
            # Allowing Multi-Select Quarters for flexible comparison
            selected_quarters = st.multiselect(
                "Select Periods for Comparison", 
                TRACKED_QUARTERS,
                default=[TRACKED_QUARTERS[0]]
            )
            # Default Financial Pillars
            selected_pillars = ["Financial Health", "Funding & Liquidity", "Asset Quality"] 
            
        else:
            # Strategic Mode: MULTI-SELECT for Pillars and Quarters
            selected_pillars = st.multiselect(
                "Select Strategic Pillars",
                list(PILLAR_MAP.keys()),
                default=["Asset Quality", "Growth Engine"]
            )
            selected_quarters = st.multiselect(
                "Select Periods for Comparison", 
                TRACKED_QUARTERS,
                default=[TRACKED_QUARTERS[0]]
            )

    # THE TRIGGER
    st.markdown("###")
    start_btn = st.button("🚀 Generate Analysis Report", type="primary")

# --- EXECUTION LOGIC ---
if start_btn:
    if not selected_competitors:
        st.error("Please select at least one competitor.")
        st.stop()

    gc = get_gspread_client()
    sh = gc.open_by_key(st.secrets["sheet_id"])
    
    # Store results for display
    final_results = {}

    # PROGRESS BAR
    progress_text = "Initializing..."
    my_bar = st.progress(0, text=progress_text)
    total_steps = len(selected_competitors) * len(selected_quarters)
    step_count = 0

    for comp in selected_competitors:
        # STRICT CHECK: Only proceed if TAB EXISTS
        ws = get_tab_if_exists(sh, comp)
        
        comp_data = [] # List to hold data for this competitor
        
        if not ws:
            # Tab doesn't exist -> SKIP
            st.toast(f"⚠️ No database record found for {comp}. Skipping.")
            # We do NOT search PDFs or create tabs. We just skip.
        else:
            # Tab Exists -> Proceed to check for Quarter Data
            for qtr in selected_quarters:
                step_count += 1
                my_bar.progress(step_count / total_steps, text=f"Processing {comp} | {qtr}...")
                
                # STEP 1: CHECK IF DATA EXISTS IN SHEET
                db_data = get_existing_data(ws, qtr)
                
                if db_data:
                    # Data Exists -> Use it
                    comp_data.append(db_data)
                else:
                    # STEP 2: DATA MISSING -> FIND ALL PDFS & ANALYZE
                    # (Only search PDF if Tab exists but Row is missing)
                    combined_text = find_and_extract_all_docs(comp, qtr)
                    
                    if combined_text:
                        ai_data = analyze_content(combined_text, comp)
                        if ai_data:
                            # Add Quarter to data before saving
                            save_to_sheet(ws, ai_data, qtr)
                            # Add Quarter to dict for display
                            ai_data["Quarter"] = qtr 
                            comp_data.append(ai_data) # Add to current list
                    else:
                        pass # PDF Missing
        
        # Store all data found/created for this competitor
        if comp_data:
            final_results[comp] = pd.DataFrame(comp_data)

    my_bar.empty()
    st.success("Analysis Complete!")
    st.markdown("---")

    # --- OUTPUT GENERATION (MD/CEO VIEW) ---
    
    # REUSABLE MATRIX GENERATOR FUNCTION
    def generate_comparison_matrix(quarter, pillars):
        st.markdown(f"### 🗓️ Period: {quarter}")
        matrix_rows = []
        
        for pillar in pillars:
            metrics = PILLAR_MAP.get(pillar, [])
            for metric in metrics:
                row_data = {"Category": pillar, "Metric": metric}
                for comp in selected_competitors:
                    df = final_results.get(comp)
                    val = "-" 
                    if df is not None and not df.empty and "Quarter" in df.columns:
                        match = df[df["Quarter"] == quarter]
                        if not match.empty:
                            val = match.iloc[0].get(metric, "-")
                    row_data[comp] = val
                matrix_rows.append(row_data)
        
        if matrix_rows:
            df_view = pd.DataFrame(matrix_rows)
            # RESET INDEX so "Category" and "Metric" become regular columns
            # This allows us to apply st.column_config to them for Wrapping!
            
            # --- STYLING LOGIC ---
            
            # 1. Apply Colors via Pandas Styler
            styled_df = df_view.style.set_properties(**{
                'white-space': 'normal', 
                'height': 'auto',
                'border': '1px solid #e6e9ef'
            }).set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#2b2b2b'), ('color', 'white'), ('font-weight', 'bold')]},
            ])

            # 2. Configure Columns for Streamlit (Force Wrap on ALL columns)
            column_config_dict = {}
            
            # Apply wrapping to Category & Metric (now regular columns)
            column_config_dict["Category"] = st.column_config.TextColumn("Category", width="small")
            column_config_dict["Metric"] = st.column_config.TextColumn("Metric", width="medium")
            
            # Apply wrapping to Competitor columns
            for comp in selected_competitors:
                column_config_dict[comp] = st.column_config.TextColumn(comp, width="large")

            # 3. Render
            st.dataframe(
                styled_df, 
                use_container_width=True,
                column_config=column_config_dict,
                hide_index=True # Hide the numeric index (0, 1, 2...)
            )
        else:
            st.info(f"No matching data found for {quarter}")
        st.divider()

    # --- DISPLAY LOGIC ---
    if "Financial" in analysis_mode:
        st.header("📊 Financial Performance Matrix")
        if not final_results:
            st.warning("No data found (Ensure Tabs exist in Google Sheet).")
        else:
            for qtr in selected_quarters:
                generate_comparison_matrix(qtr, selected_pillars)

    elif "Strategic" in analysis_mode:
        st.header("🧠 Strategic Executive Briefing")
        if not final_results:
            st.warning("No data found (Ensure Tabs exist in Google Sheet).")
        else:
            for qtr in selected_quarters:
                generate_comparison_matrix(qtr, selected_pillars)
