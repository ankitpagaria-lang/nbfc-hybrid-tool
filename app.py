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

# --- GEMINI ENGINE (ENTERPRISE) ---
def analyze_pdf(pdf_bytes):
    # Uses Enterprise Key
    genai.configure(api_key=st.secrets["gemini_api_key"])
    model = genai.GenerativeModel("gemini-1.5-pro")
    
    prompt = """
    Act as a Senior Analyst. Extract data from this report.
    
    TASK 1: FINANCIALS (Normalize to INR Crores. If Mn, divide by 10).
    JSON Keys: interest_income, interest_expense, nii, other_income, total_income, opex, ppop, provisions, pbt, tax, pat, aum, gnpa_percent, nnpa_percent.
    
    TASK 2: STRATEGY (1 sentence summary).
    JSON Keys: ai_digital, hr_people, geography, credit_borrowings, partnerships, leadership, product_mix, customer_eng, new_initiatives, productivity.
    
    OUTPUT: Single JSON object with keys "financials" and "strategy".
    """
    
    try:
        response = model.generate_content([{"mime_type": "application/pdf", "data": pdf_bytes}, prompt])
        return json.loads(response.text.replace("```json", "").replace("```", ""))
    except Exception as e:
        st.error(f"AI Error: {e}")
        return None

# --- DRIVE & SHEETS ---
def find_file(comp, qtr):
    service = build('drive', 'v3', credentials=get_creds())
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
comp = st.selectbox("Competitor", ["SK Finance", "Kogta", "Bajaj", "Shriram"])
qtr = st.selectbox("Quarter", ["Q3FY25", "Q2FY25", "FY24"])

if st.button("🚀 Analyze Document"):
    with st.status("Processing..."):
        st.write("📂 Personal Robot: Searching Corporate Vault...")
        pdf = find_file(comp, qtr)
        if pdf:
            st.write("🧠 Enterprise Brain: Analyzing...")
            data = analyze_pdf(pdf)
            if data:
                save_to_db(data, comp, qtr)
                st.success("Done! Database Updated.")
        else:
            st.error("File not found.")
