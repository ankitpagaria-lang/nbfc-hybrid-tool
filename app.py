import streamlit as st
import pandas as pd
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import json
import pypdf

# --- CONFIG ---
st.set_page_config(page_title="Hybrid NBFC Vault", layout="wide")

# --- AUTH ---
def get_creds():
    return service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    )

# --- SMART MODEL SELECTOR ---
def get_best_model(api_key):
    """Asks Google which models are available and picks the best one."""
    genai.configure(api_key=api_key)
    try:
        # Get list of all models available to your key
        all_models = list(genai.list_models())
        
        # Filter for models that can generate content
        capable_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        
        # Priority Logic: Try to find 1.5 Pro -> 1.5 Flash -> Pro -> Any
        for priority in ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-pro']:
            for m_name in capable_models:
                if priority in m_name:
                    return m_name
        
        # If no preferred model found, take the first valid one
        if capable_models:
            return capable_models[0]
            
    except Exception as e:
        print(f"Model listing failed: {e}")
    
    # Ultimate Fallback (Legacy name)
    return "models/gemini-pro"

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

# --- ANALYSIS ENGINE ---
def analyze_pdf(pdf_bytes):
    api_key = st.secrets["gemini_api_key"]
    genai.configure(api_key=api_key)
    
    # 1. AUTO-DETECT BEST MODEL
    model_name = get_best_model(api_key)
    print(f"Selected Model: {model_name}")
    
    prompt_text = """
    Act as a Senior Financial Analyst. Extract data from this earnings report.
    
    TASK 1: FINANCIALS (Normalize to INR Crores. If Mn, divide by 10).
    JSON Keys: interest_income, interest_expense, nii, other_income, total_income, opex, ppop, provisions, pbt, tax, pat, aum, gnpa_percent, nnpa_percent.
    
    TASK 2: STRATEGY (1 sentence summary).
    JSON Keys: ai_digital, hr_people, geography, credit_borrowings, partnerships, leadership, product_mix, customer_eng, new_initiatives, productivity.
    
    OUTPUT: Single JSON object with keys "financials" and "strategy".
    """

    # 2. DECIDE STRATEGY
    # Strategy 1 (Direct PDF) only works on 1.5 models.
    # Strategy 2 (Text Only) works on ALL models.
    
    if "1.5" in model_name:
        try:
            print(f"Attempting Strategy 1 (Direct PDF) with {model_name}...")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([
                {"mime_type": "application/pdf", "data": pdf_bytes}, 
                prompt_text
            ])
            return clean_json(response.text)
        except Exception as e:
            print(f"Strategy 1 Failed: {e}. Switching to Strategy 2...")
            # Fallthrough to Strategy 2

    # Strategy 2: Text Extraction (The "Tank" - works on everything)
    try:
        print(f"Attempting Strategy 2 (Text Extraction) with {model_name}...")
        text_content = extract_text_from_pdf(pdf_bytes)
        
        if not text_content:
            st.error("PDF appears to be empty or scanned images. OCR required.")
            return None

        model = genai.GenerativeModel(model_name)
        response = model.generate_content([prompt_text, text_content])
        return clean_json(response.text)
        
    except Exception as e2:
        st.error(f"Analysis failed. Error: {e2}")
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
st.title("🏦 Hybrid NBFC Vault")

comp = st.selectbox("Competitor", ["SK Finance", "Kogta", "Bajaj", "Shriram", "Tata Capital", "SBFC", "Poonawala", "Jio Finance", "HDB", "FedFina"])
qtr = st.selectbox("Quarter", ["Q3FY25", "Q4FY25", "FY25", "Q1FY26", "Q2FY26", "Q3FY26", "FY26"])

if st.button("🚀 Analyze Document"):
    with st.status("Processing...") as status:
        st.write(f"📂 Searching Drive for {comp} {qtr}...")
        pdf = find_file(comp, qtr)
        
        if pdf:
            st.write("🧠 Auto-Detecting Best AI Model...")
            # analyze_pdf will print the selected model in the logs
            data = analyze_pdf(pdf)
            
            if data:
                st.write("💾 Saving to Database...")
                if save_to_db(data, comp, qtr):
                    st.success("Success! Database Updated.")
                    st.json(data)
                    status.update(label="Complete", state="complete")
            else:
                st.error("AI failed to extract data. Check if PDF is readable.")
        else:
            st.error(f"File not found in Drive. Looked for name containing: '{comp}' AND '{qtr}'")
