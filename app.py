import streamlit as st
import pandas as pd
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import json
import plotly.graph_objects as go

# --- CONFIG ---
st.set_page_config(page_title="Hybrid NBFC Vault", layout="wide")

# --- AUTH ---
def get_creds():
    # Uses the Personal Robot Credentials to access Work Drive
    return service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    )

# --- GEMINI ENGINE (ROBUST FALLBACK) ---
def analyze_pdf(pdf_bytes):
    # Uses Enterprise Key
    genai.configure(api_key=st.secrets["gemini_api_key"])
    
    # Priority List: Latest Powerful -> Fast Fallback -> Legacy Stable
    # "Gemini 3" doesn't exist yet. 1.5 Pro is the current state-of-the-art.
    models_to_try = [
        "gemini-1.5-pro-latest",  # Try the absolute latest version
        "gemini-1.5-pro",         # Standard stable version
        "gemini-1.5-flash",       # High speed fallback
        "gemini-pro"              # Legacy fallback
    ]
    
    prompt = """
    Act as a Senior Analyst. Extract data from this report.
    
    TASK 1: FINANCIALS (Normalize to INR Crores. If Mn, divide by 10).
    JSON Keys: interest_income, interest_expense, nii, other_income, total_income, opex, ppop, provisions, pbt, tax, pat, aum, gnpa_percent, nnpa_percent.
    
    TASK 2: STRATEGY (1 sentence summary).
    JSON Keys: ai_digital, hr_people, geography, credit_borrowings, partnerships, leadership, product_mix, customer_eng, new_initiatives, productivity.
    
    OUTPUT: Single JSON object with keys "financials" and "strategy".
    """
    
    for model_name in models_to_try:
        try:
            # Silent attempt
            print(f"Attempting with model: {model_name}...") 
            model = genai.GenerativeModel(model_name)
            
            response = model.generate_content([
                {"mime_type": "application/pdf", "data": pdf_bytes}, 
                prompt
            ])
            
            # Clean response
            text = response.text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1]
                
            return json.loads(text)
            
        except Exception as e:
            # If fail, print to console logs (user won't see ugly error) and try next model
            print(f"Model {model_name} failed: {e}")
            continue

    # If all fail, show error to user
    st.error("All AI models failed to process this document. Please check the PDF.")
    return None

# --- DRIVE & SHEETS ---
def find_file(comp, qtr):
    service = build('drive', 'v3', credentials=get_creds())
    # Smart Query: Case insensitive search logic isn't native, so we rely on loose matching
    query = f"name contains '{comp}' and name contains '{qtr}' and mimeType = 'application/pdf'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files: return None
    
    # Download
    request = service.files().get_media(fileId=files[0]['id'])
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    return fh.getvalue()

def save_to_db(data, comp, qtr):
    service = build('sheets', 'v4', credentials=get_creds())
    sheet_id = st.secrets["sheet_id"]
    
    # Financial Row
    fin = data['financials']
    row1 = [comp, qtr, fin.get('interest_income',0), fin.get('interest_expense',0), fin.get('nii',0), 
            fin.get('other_income',0), fin.get('total_income',0), fin.get('opex',0), fin.get('ppop',0),
            fin.get('provisions',0), fin.get('pbt',0), fin.get('tax',0), fin.get('pat',0), 
            fin.get('aum',0), fin.get('gnpa_percent',0), fin.get('nnpa_percent',0)]
    
    # Strategy Row
    strat = data['strategy']
    row2 = [comp, qtr, strat.get('ai_digital','-'), strat.get('hr_people','-'), strat.get('geography','-'),
            strat.get('credit_borrowings','-'), strat.get('partnerships','-'), strat.get('leadership','-'),
            strat.get('product_mix','-'), strat.get('customer_eng','-'), strat.get('new_initiatives','-'),
            strat.get('productivity','-')]

    # Append
    service.spreadsheets().values().append(spreadsheetId=sheet_id, range="Financials!A:P", 
        valueInputOption="USER_ENTERED", body={'values': [row1]}).execute()
    service.spreadsheets().values().append(spreadsheetId=sheet_id, range="Strategy!A:L", 
        valueInputOption="USER_ENTERED", body={'values': [row2]}).execute()

# --- UI ---
st.title("🏦 Hybrid NBFC Vault")

# Updated List with your requested competitors
comp = st.selectbox("Competitor", ["SK Finance", "Kogta", "Bajaj", "Shriram", "Tata Capital", "SBFC", "Poonawala", "Jio Finance", "HDB", "FedFina"])
qtr = st.selectbox("Quarter", ["Q3FY25", "Q4FY25", "FY25", "Q1FY26", "Q2FY26", "Q3FY26", "FY26"])

if st.button("🚀 Analyze Document"):
    with st.status("Processing..."):
        st.write(f"📂 Personal Robot: Searching Corporate Vault for {comp} {qtr}...")
        pdf = find_file(comp, qtr)
        
        if pdf:
            st.write("🧠 Enterprise Brain: Analyzing (Auto-switching to best model)...")
            data = analyze_pdf(pdf)
            
            if data:
                st.write("💾 Saving to Database...")
                save_to_db(data, comp, qtr)
                st.success("Done! Database Updated.")
                st.json(data) # Show preview of data
            else:
                st.error("AI could not extract JSON data.")
        else:
            st.error(f"File not found in Drive. Looked for name containing: '{comp}' AND '{qtr}'")
