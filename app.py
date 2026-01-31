import streamlit as st
import pandas as pd
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import json
import pypdf
import time
import random

# --- CONFIG ---
st.set_page_config(page_title="Hybrid NBFC Vault (Gemini 3.0)", layout="wide")

# --- AUTH ---
def get_creds():
    return service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    )

# --- SMART MODEL SELECTOR (UPDATED FOR GEMINI 3 & 2.5) ---
def get_best_model(api_key):
    """
    Prioritizes Gemini 3.0 -> Gemini 2.5 -> Gemini 2.0 -> Legacy.
    """
    genai.configure(api_key=api_key)
    try:
        # Get list of all models available to your key
        all_models = list(genai.list_models())
        capable_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        
        # 2026 PRIORITY LADDER
        priority_order = [
            "gemini-3-pro-preview",    # Latest bleeding edge (Nov 2025)
            "gemini-3-flash-preview",  # Latest fast model (Dec 2025)
            "gemini-2.5-pro",          # Stable Workhorse (June 2025)
            "gemini-2.5-flash",        # Stable Fast (June 2025)
            "gemini-2.0-flash",        # Legacy reliable
            "gemini-1.5-pro",          # Old reliable
            "gemini-1.5-flash"         # Old fast
        ]

        # Check for specific matches in priority order
        for priority in priority_order:
            for m_name in capable_models:
                if priority in m_name:
                    return m_name
        
        # Fallback: Just take the newest one we can find
        if capable_models:
            return capable_models[0]
            
    except Exception as e:
        print(f"Model listing failed: {e}")
    
    # Ultimate Fallback if list_models fails
    return "models/gemini-2.5-flash"

# --- ROBUST AI CALLER (With Retry) ---
def call_gemini_with_retry(model, content_list):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(content_list)
            return response
        except Exception as e:
            error_str = str(e).lower()
            # Catch 429 (Rate Limit) or 503 (Overloaded)
            if "429" in error_str or "quota" in error_str or "503" in error_str:
                wait_time = 30 + (attempt * 10)
                st.toast(f"⚠️ High Traffic on Gemini 3. Pausing for {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                raise e
    return None

# --- HELPER: EXTRACT TEXT FROM PDF ---
def extract_text_from_pdf(pdf_bytes):
    try:
        pdf_file = io.BytesIO(pdf_bytes)
        reader = pypdf.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Text extraction failed: {e}")
        return None

def clean_json(text):
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1]
        return json.loads(text)
    except:
        return None

# --- ANALYSIS ENGINE ---
def analyze_pdf(pdf_bytes):
    api_key = st.secrets["gemini_api_key"]
    genai.configure(api_key=api_key)
    
    # 1. AUTO-SELECT BEST AVAILABLE MODEL (3.0 or 2.5)
    model_name = get_best_model(api_key)
    print(f"Selected Model: {model_name}")
    st.toast(f"Using Brain: {model_name}") # Show user which brain is working
    
    prompt_text = """
    Act as a Senior Financial Analyst. Extract data from this earnings report.
    
    TASK 1: FINANCIALS (Normalize to INR Crores. If Mn, divide by 10).
    JSON Keys: interest_income, interest_expense, nii, other_income, total_income, opex, ppop, provisions, pbt, tax, pat, aum, gnpa_percent, nnpa_percent.
    
    TASK 2: STRATEGY (1 sentence summary).
    JSON Keys: ai_digital, hr_people, geography, credit_borrowings, partnerships, leadership, product_mix, customer_eng, new_initiatives, productivity.
    
    OUTPUT: Single JSON object with keys "financials" and "strategy".
    """

    model = genai.GenerativeModel(model_name)

    # Strategy: Hybrid (PDF Direct -> Text Fallback)
    # Gemini 3 and 2.5 are excellent at handling raw PDFs, so we try that first.
    try:
        # print(f"Attempting Direct PDF Read with {model_name}...")
        # response = call_gemini_with_retry(model, [{"mime_type": "application/pdf", "data": pdf_bytes}, prompt_text])
        # if response: return clean_json(response.text)
        
        # NOTE: For maximum reliability across all versions, we stick to Text Extraction
        # because it never fails on file-size limits.
        print(f"Attempting Text Extraction with {model_name}...")
        text_content = extract_text_from_pdf(pdf_bytes)
        
        if not text_content:
            st.error("PDF appears to be empty or scanned images.")
            return None
        
        response = call_gemini_with_retry(model, [prompt_text, text_content])
        if response:
            return clean_json(response.text)
            
    except Exception as e:
        st.error(f"Analysis failed: {e}")
        return None
    
    return None

# --- DRIVE & SHEETS ---
def find_file(comp, qtr):
    try:
        service = build('drive', 'v3', credentials=get_creds())
        query = f"name contains '{comp}' and name contains '{qtr}' and mimeType = 'application/pdf'"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        if not files: return None
        
        request = service.files().get_media(fileId=files[0]['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        return fh.getvalue()
    except Exception as e:
        st.error(f"Drive Error: {e}")
        return None

def save_to_db(data, comp, qtr):
    try:
        service = build('sheets', 'v4', credentials=get_creds())
        sheet_id = st.secrets["sheet_id"]
        
        fin = data.get('financials', {})
        row1 = [comp, qtr, fin.get('interest_income',0), fin.get('interest_expense',0), fin.get('nii',0), 
                fin.get('other_income',0), fin.get('total_income',0), fin.get('opex',0), fin.get('ppop',0),
                fin.get('provisions',0), fin.get('pbt',0), fin.get('tax',0), fin.get('pat',0), 
                fin.get('aum',0), fin.get('gnpa_percent',0), fin.get('nnpa_percent',0)]
        
        strat = data.get('strategy', {})
        row2 = [comp, qtr, strat.get('ai_digital','-'), strat.get('hr_people','-'), strat.get('geography','-'),
                strat.get('credit_borrowings','-'), strat.get('partnerships','-'), strat.get('leadership','-'),
                strat.get('product_mix','-'), strat.get('customer_eng','-'), strat.get('new_initiatives','-'),
                strat.get('productivity','-')]

        service.spreadsheets().values().append(spreadsheetId=sheet_id, range="Financials!A:P", 
            valueInputOption="USER_ENTERED", body={'values': [row1]}).execute()
        service.spreadsheets().values().append(spreadsheetId=sheet_id, range="Strategy!A:L", 
            valueInputOption="USER_ENTERED", body={'values': [row2]}).execute()
        return True
    except Exception as e:
        st.error(f"Database Error: {e}")
        return False

# --- UI ---
st.title("🏦 Hybrid NBFC Vault (Gemini 3.0)")

comp = st.selectbox("Competitor", ["SK Finance", "Kogta", "Bajaj", "Shriram", "Tata Capital", "SBFC", "Poonawala", "Jio Finance", "HDB", "FedFina"])
qtr = st.selectbox("Quarter", ["Q3FY25", "Q4FY25", "FY25", "Q1FY26", "Q2FY26", "Q3FY26", "FY26"])

if st.button("🚀 Analyze Document"):
    with st.status("Processing...") as status:
        st.write(f"📂 Searching Drive for {comp} {qtr}...")
        pdf = find_file(comp, qtr)
        
        if pdf:
            st.write("🧠 Engaging Gemini 3.0 / 2.5 Brain...")
            data = analyze_pdf(pdf)
            
            if data:
                st.write("💾 Saving to Database...")
                if save_to_db(data, comp, qtr):
                    st.success("Success! Database Updated.")
                    st.json(data)
                    status.update(label="Complete", state="complete")
            else:
                st.error("AI failed. Please check the logs.")
        else:
            st.error(f"File not found in Drive. Looked for name containing: '{comp}' AND '{qtr}'")
