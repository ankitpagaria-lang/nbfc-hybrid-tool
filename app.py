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
st.set_page_config(page_title="NBFC Master Vault", layout="wide")

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

# --- SMART DATABASE MANAGER ---
def get_or_create_tab(sheet, tab_name):
    """Checks if a tab exists for the NBFC. If not, creates it with 6-Pillar Headers."""
    try:
        worksheet = sheet.worksheet(tab_name)
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
        # Create new tab
        worksheet = sheet.add_worksheet(title=tab_name, rows=100, cols=50)
        
        # DEFINING THE MASTER HEADERS (Financials + 6 Pillars)
        headers = [
            "Quarter", 
            # Pillar 1: Financial Health
            "NIM_Spreads", "Fee_Income_Ratio", "Cost_to_Income", "RoA", "RoE", "Credit_Cost",
            # Pillar 2: Asset Quality
            "GNPA", "NNPA", "Stage_2_Assets", "Stage_3_Assets", "Collection_Efficiency", "Concentration_Risk",
            # Pillar 3: Growth
            "AUM_Growth", "Disbursement_Velocity", "Co_Lending_Share", "Product_Strategy",
            # Pillar 4: Funding
            "Cost_of_Funds", "Liability_Mix", "ALM_Gap", "Direct_Assignment",
            # Pillar 5: Digital
            "Digital_Sourcing_Percent", "Productivity_Metrics", "Tech_Stack_AI", "Customer_Friction_TAT",
            # Pillar 6: Soft Power
            "Capital_Adequacy_CRAR", "Regulatory_Standing", "Leadership_Depth", "ESG_Score"
        ]
        worksheet.append_row(headers)
        return worksheet

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

    # 6-PILLAR PROMPT - REFINED FOR TRANSCRIPTS
    prompt = f"""
    You are a Senior Banking Analyst analyzing {competitor}. 
    I have provided text from the **Investor Presentation AND/OR Earnings Call Transcript**.
    
    Synthesize information from both sources. 
    - Use the Transcript to find "Management Commentary" regarding Strategy, Future Guidance, and nuances.
    - Use the Presentation for hard numbers (NIM, GNPA, AUM).

    EXTRACT DATA STRICTLY INTO JSON.

    PILLAR 1: FINANCIAL HEALTH
    - NIM_Spreads: Net Interest Margin & Spreads. (Look for specific product spreads in transcript).
    - Fee_Income_Ratio: Non-interest income %.
    - Cost_to_Income: Opex / Total Income.
    - RoA: Return on Assets %.
    - RoE: Return on Equity %.
    - Credit_Cost: Provisions %.

    PILLAR 2: ASSET QUALITY
    - GNPA: Gross NPA %.
    - NNPA: Net NPA %.
    - Stage_2_Assets: Loans overdue 60+ days.
    - Stage_3_Assets: Loans overdue 90+ days.
    - Collection_Efficiency: Collection Demand vs Collection.
    - Concentration_Risk: Geo or Borrower concentration.

    PILLAR 3: GROWTH
    - AUM_Growth: YoY AUM Growth %.
    - Disbursement_Velocity: New loans disbursed.
    - Co_Lending_Share: % sourced via partners.
    - Product_Strategy: New launches vs Old products (Look for "Blue Ocean" commentary).

    PILLAR 4: FUNDING
    - Cost_of_Funds: Weighted avg borrowing cost.
    - Liability_Mix: Bank vs NCD vs CP mix.
    - ALM_Gap: Asset Liability positive/negative mismatch.
    - Direct_Assignment: Securitization volume.

    PILLAR 5: DIGITAL
    - Digital_Sourcing_Percent: % loans via STP/App.
    - Productivity_Metrics: AUM per employee or Branch profit.
    - Tech_Stack_AI: AI/Cloud investments.
    - Customer_Friction_TAT: Turnaround time metrics.

    PILLAR 6: SOFT POWER
    - Capital_Adequacy_CRAR: Tier 1 + Tier 2.
    - Regulatory_Standing: Compliance/Penalties.
    - Leadership_Depth: Management changes (Mention specific names if transcript mentions exits).
    - ESG_Score: Green financing/Social impact.

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
    If data is missing, put "Not Disclosed". Keep text concise (max 2-3 sentences per field).
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
        
        # print(f"DEBUG: Found {len(files)} files: {files_found}")
        return full_combined_text

    except Exception as e:
        st.error(f"Drive Error: {e}")
        return None

# --- MAIN UI ---
st.title("🏦 Executive NBFC Vault")
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
            ["SBFC","Poonawala","FedFina","Bajaj Finance", "SK Finance", "Shriram", "Kogta", "Tata Capital", "Muthoot"],
            default=["Bajaj Finance", "Shriram"]
        )

    with col2:
        st.subheader("Parameters")
        if "Financial" in analysis_mode:
            # Financial Mode: Needs Specific Quarters
            selected_quarters = st.multiselect(
                "Select Quarters", 
                TRACKED_QUARTERS,
                default=["Q3FY25"]
            )
            selected_pillars = None # Not used
            
        else:
            # Strategic Mode: MULTI-SELECT for Pillars and Quarters
            selected_pillars = st.multiselect(
                "Select Strategic Pillars",
                list(PILLAR_MAP.keys()),
                default=["Financial Health", "Asset Quality"]
            )
            selected_quarters = st.multiselect(
                "Select Periods for Comparison", 
                TRACKED_QUARTERS,
                default=["Q3FY25"]
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
        ws = get_or_create_tab(sh, comp)
        comp_data = [] # List to hold data for this competitor
        
        for qtr in selected_quarters:
            step_count += 1
            my_bar.progress(step_count / total_steps, text=f"Processing {comp} | {qtr}...")
            
            # STEP 1: CHECK DB
            db_data = get_existing_data(ws, qtr)
            
            if db_data:
                # Data Exists -> Use it
                comp_data.append(db_data)
            else:
                # STEP 2: IF MISSING -> FIND ALL PDFS (Pres + Transcript) & ANALYZE
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
    
    if "Financial" in analysis_mode:
        st.header("📊 Financial Performance Matrix")
        
        if not final_results:
            st.warning("No data found for the selected criteria.")
        
        for comp, df in final_results.items():
            with st.expander(f"📘 {comp} - Financial Overview", expanded=True):
                if not df.empty and "Quarter" in df.columns:
                    # Clean display: Quarters as Columns
                    df = df.set_index("Quarter")
                    st.dataframe(df.T, use_container_width=True)
                else:
                    st.warning("Data structure invalid.")

    elif "Strategic" in analysis_mode:
        st.markdown("## 🧠 Strategic Executive Briefing")
        
        if not final_results:
            st.warning("No data available to generate strategic insights.")
        else:
            # EXECUTIVE COMPARISON VIEW
            for qtr in selected_quarters:
                st.markdown(f"### 🗓️ Period: {qtr}")
                
                # 1. Prepare Data for Matrix
                matrix_rows = []
                
                for pillar in selected_pillars:
                    metrics = PILLAR_MAP.get(pillar, [])
                    
                    for metric in metrics:
                        # Start a new row for this metric
                        row_data = {"Category": pillar, "Metric": metric}
                        
                        # Fill in data for each competitor
                        for comp in selected_competitors:
                            df = final_results.get(comp)
                            val = "-" # Default
                            
                            if df is not None and not df.empty and "Quarter" in df.columns:
                                # Find row for this quarter
                                match = df[df["Quarter"] == qtr]
                                if not match.empty:
                                    val = match.iloc[0].get(metric, "-")
                            
                            row_data[comp] = val
                        
                        matrix_rows.append(row_data)

                # 2. Display as a Clean Table with WRAPPED TEXT
                if matrix_rows:
                    df_view = pd.DataFrame(matrix_rows)
                    # Set Index for Grouped Look (Category | Metric)
                    df_view = df_view.set_index(["Category", "Metric"])
                    
                    # DYNAMIC COLUMN CONFIGURATION FOR TEXT WRAPPING
                    # We create a config dict that applies "width=medium" to ALL columns found
                    column_config_dict = {}
                    for col_name in df_view.columns:
                        # This Forces wrapping ("medium" or "large" usually triggers wrap)
                        column_config_dict[col_name] = st.column_config.TextColumn(
                            col_name,
                            width="large" 
                        )

                    # Display with Streamlit
                    st.dataframe(
                        df_view,
                        use_container_width=True,
                        column_config=column_config_dict # <--- THIS ENABLES WRAPPING
                    )
                else:
                    st.info(f"No matching data found for {qtr}")
                
                st.divider()
