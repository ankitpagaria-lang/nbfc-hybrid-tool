import streamlit as st
import pandas as pd
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import gspread
import io
import json
import pypdf
import time

# --- CONFIG ---
st.set_page_config(page_title="NBFC Master Vault", layout="wide")

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

def check_data_exists(worksheet, quarter):
    """Returns True if data for this Quarter already exists in the tab."""
    try:
        # Column 1 is always Quarter
        existing_quarters = worksheet.col_values(1)
        if quarter in existing_quarters:
            return True
        return False
    except:
        return False

def get_existing_data(worksheet, quarter):
    """Fetches the row for the existing quarter."""
    try:
        all_records = worksheet.get_all_records()
        df = pd.DataFrame(all_records)
        return df[df["Quarter"] == quarter].iloc[0].to_dict()
    except:
        return None

# --- NEW BULLETPROOF AI ENGINE ---
def get_best_model():
    """
    Dynamically finds the best available model for your API key.
    Prioritizes Gemini 3 -> 2.5 -> 1.5 -> Legacy.
    """
    try:
        # 1. Ask Google what models are available to THIS key
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 2. Define our Dream Team (Best to Worst)
        # Note: We use partial string matching to catch versions like 'gemini-1.5-flash-001'
        priority_list = [
            "gemini-3",          # Future proofing
            "gemini-2.5",        # High end 2026 model
            "gemini-2.0-flash",  # Fast 2.0
            "gemini-1.5-pro",    # Reliable workhorse
            "gemini-1.5-flash",  # Fast reliable
            "gemini-pro"         # Legacy fallback
        ]
        
        # 3. Find the first match
        for priority in priority_list:
            for real_model in available_models:
                if priority in real_model:
                    return real_model # Return the exact system name (e.g. models/gemini-1.5-flash-001)
        
        # 4. If no priority match, just take the first one that works
        if available_models:
            return available_models[0]
            
    except Exception as e:
        print(f"Model listing failed: {e}")
    
    # Absolute fallback if list_models fails (Manual Guess)
    return "models/gemini-1.5-flash"

def analyze_pdf(pdf_bytes, competitor):
    genai.configure(api_key=st.secrets["gemini_api_key"])
    
    # 1. Extract text (Most reliable method, bypasses file-size limits)
    try:
        pdf_file = io.BytesIO(pdf_bytes)
        reader = pypdf.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            if page.extract_text():
                text += page.extract_text() + "\n"
    except Exception as e:
        st.error(f"PDF Reading Error: {e}")
        return None
            
    # 2. Auto-Select the Best Available Model
    model_name = get_best_model()
    # st.write(f"DEBUG: Using AI Brain: {model_name}") # Uncomment to see which model is picked
    
    # 6-PILLAR PROMPT
    prompt = f"""
    You are a Senior Banking Analyst analyzing {competitor}. Extract data strictly into JSON.
    
    PILLAR 1: FINANCIAL HEALTH
    - NIM_Spreads: Net Interest Margin & Spreads (Yield - CoF). Breakdown by product if avail.
    - Fee_Income_Ratio: Non-interest income as % of total.
    - Cost_to_Income: Opex / Total Income.
    - RoA: Return on Assets %.
    - RoE: Return on Equity %.
    - Credit_Cost: Provisions/Write-offs as % of AUM.

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
    - Product_Strategy: New launches vs Old products.

    PILLAR 4: FUNDING
    - Cost_of_Funds: Weighted avg borrowing cost.
    - Liability_Mix: Bank vs NCD vs CP mix.
    - ALM_Gap: Asset Liability positive/negative mismatch.
    - Direct_Assignment: Securitization/Book selldown volume.

    PILLAR 5: DIGITAL
    - Digital_Sourcing_Percent: % loans via STP/App.
    - Productivity_Metrics: AUM per employee or Branch profit.
    - Tech_Stack_AI: AI/Cloud investments mentioned.
    - Customer_Friction_TAT: Turnaround time metrics.

    PILLAR 6: SOFT POWER
    - Capital_Adequacy_CRAR: Tier 1 + Tier 2.
    - Regulatory_Standing: Compliance/Penalties.
    - Leadership_Depth: Management changes/stability.
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
    If data is missing, put "Not Disclosed". Keep text concise (max 2 sentences per field).
    """

    # 3. Execute with Retry Logic (Handles Glitches/Timeouts)
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content([prompt, text])
        
        # Clean JSON
        raw_text = response.text
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0]
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            
        return json.loads(raw_text)
        
    except Exception as e:
        # Emergency Fallback: If the "Best" model crashed, try the "Safest" one (1.5 Flash)
        if "404" in str(e) or "not found" in str(e).lower():
            try:
                # st.warning("Primary model failed. Switching to Safety Net (Gemini 1.5 Flash)...")
                model = genai.GenerativeModel("models/gemini-1.5-flash") # Hardcoded safety net
                response = model.generate_content([prompt, text])
                
                raw_text = response.text
                if "```json" in raw_text:
                    raw_text = raw_text.split("```json")[1].split("```")[0]
                elif "```" in raw_text:
                    raw_text = raw_text.split("```")[1]
                return json.loads(raw_text)
            except Exception as e2:
                st.error(f"AI Analysis Failed on both primary and backup models: {e2}")
                return None
        else:
            st.error(f"AI Analysis Failed: {e}")
            return None

# --- SAVING TO SHEET ---
def save_to_sheet(worksheet, data, quarter):
    # Prepare row in exact order of headers
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

# --- DRIVE SEARCH ---
def find_file(comp, qtr):
    service = get_drive_service()
    query = f"name contains '{comp}' and name contains '{qtr}' and mimeType = 'application/pdf'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files: return None
    request = service.files().get_media(fileId=files[0]['id'])
    fh = io.BytesIO()
    downloader = build('drive', 'v3', credentials=service._http.credentials).files().get_media(fileId=files[0]['id'])
    # Simple download
    return request.execute()

# --- UI & LOGIC ---
st.title("🏦 NBFC Strategy Command Center")

# 1. SIDEBAR CONTROLS
mode = st.sidebar.radio("Analysis Mode", ["Financial Analysis (Tables)", "Strategic Analysis (Insights)"])

# Competitor Selection (Multi-Select)
competitors = st.sidebar.multiselect("Select Competitors", ["SBFC","Poonawala","FedFina","Bajaj Finance", "SK Finance", "Shriram", "Kogta", "Tata Capital", "Muthoot"], default=["Bajaj Finance"])
quarters = st.sidebar.multiselect("Select Quarters", ["Q3FY25", "Q2FY25","Q1FY25","Q4FY25","Q1FY26","Q2FY26","Q3FY26","Q4FY26"], default=["Q3FY26"])

if st.sidebar.button("Run Analysis"):
    gc = get_gspread_client()
    sh = gc.open_by_key(st.secrets["sheet_id"])
    
    st.write("---")
    
    # Loop through every requested Competitor & Quarter
    for comp in competitors:
        # Get specific tab for this competitor
        ws = get_or_create_tab(sh, comp)
        
        for qtr in quarters:
            with st.status(f"Processing {comp} - {qtr}...", expanded=True) as status:
                
                # STEP 1: CHECK IF DATA EXISTS
                st.write("🔍 Checking Master Database...")
                if check_data_exists(ws, qtr):
                    st.success(f"✅ Data found for {comp} {qtr}. Skipping AI Analysis.")
                    data = get_existing_data(ws, qtr)
                else:
                    # STEP 2: IF NOT, RUN AI
                    st.write("📂 Data missing. Searching Drive for PDF...")
                    pdf_bytes = find_file(comp, qtr)
                    
                    if pdf_bytes:
                        st.write("🧠 Analyzing 6 Strategic Pillars...")
                        data = analyze_pdf(pdf_bytes, comp)
                        
                        if data:
                            st.write("💾 Saving to Master Database...")
                            save_to_sheet(ws, data, qtr)
                            st.success("Analysis Complete & Saved.")
                        else:
                            st.error("AI Analysis Failed.")
                            data = None
                    else:
                        st.error(f"PDF not found for {comp} {qtr}")
                        data = None
                
                status.update(label="Done", state="complete")

# --- OUTPUT DISPLAY MODES ---
if mode == "Financial Analysis (Tables)":
    st.subheader("📊 Financial Performance Matrix")
    # Fetch all data for selected competitors
    if st.button("Refresh View"):
        gc = get_gspread_client()
        sh = gc.open_by_key(st.secrets["sheet_id"])
        
        for comp in competitors:
            try:
                ws = sh.worksheet(comp)
                df = pd.DataFrame(ws.get_all_records())
                st.write(f"### {comp}")
                st.dataframe(df)
            except:
                st.warning(f"No data yet for {comp}")

elif mode == "Strategic Analysis (Insights)":
    st.subheader("🧠 Strategic Deep Dive")
    selected_pillar = st.selectbox("Select Strategic Pillar", [
        "Financial Health", "Asset Quality", "Growth Engine", "Funding & Liquidity", "Digital & Tech", "Soft Power"
    ])
    
    # Mapping Dropdown to Keys
    pillar_map = {
        "Financial Health": ["NIM_Spreads", "Cost_to_Income", "RoA"],
        "Asset Quality": ["GNPA", "Collection_Efficiency", "Stage_2_Assets"],
        "Growth Engine": ["AUM_Growth", "Co_Lending_Share", "Product_Strategy"],
        "Funding & Liquidity": ["Cost_of_Funds", "Liability_Mix", "ALM_Gap"],
        "Digital & Tech": ["Digital_Sourcing_Percent", "Tech_Stack_AI", "Customer_Friction_TAT"],
        "Soft Power": ["Leadership_Depth", "ESG_Score", "Regulatory_Standing"]
    }
    
    if st.button("Generate Insight Report"):
        gc = get_gspread_client()
        sh = gc.open_by_key(st.secrets["sheet_id"])
        
        # Create a comparison view
        cols = st.columns(len(competitors))
        
        for idx, comp in enumerate(competitors):
            with cols[idx]:
                st.markdown(f"### {comp}")
                try:
                    ws = sh.worksheet(comp)
                    df = pd.DataFrame(ws.get_all_records())
                    
                    # Filter for selected quarters if available
                    df_filtered = df[df["Quarter"].isin(quarters)]
                    
                    if not df_filtered.empty:
                        for _, row in df_filtered.iterrows():
                            st.markdown(f"**{row['Quarter']}**")
                            for metric in pillar_map[selected_pillar]:
                                st.markdown(f"**{metric}:** {row.get(metric, '-')}")
                            st.divider()
                    else:
                        st.write("No data for selected quarters.")
                except:
                    st.write("No data available.")
