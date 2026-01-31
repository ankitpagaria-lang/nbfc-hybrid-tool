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

# --- CONFIG ---
st.set_page_config(page_title="Hybrid NBFC Vault (Gemini 3.0)", layout="wide")

# --- AUTH ---
def get_creds():
    return service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    )

# --- SMART MODEL ENGINE ---
def get_working_model(api_key):
    """
    Tries to find the best model your account is ALLOWED to use.
    """
    genai.configure(api_key=api_key)
    
    # Priority List (2026 Era): Bleeding Edge -> Stable -> Safe Fallback
    priority_list = [
        "gemini-3-pro-preview",    # Latest & Greatest
        "gemini-3-flash-preview",  # Fast Latest
        "gemini-2.5-pro",          # Standard High-End
        "gemini-2.5-flash",        # Standard Fast
        "gemini-2.0-flash",        # Legacy
        "gemini-1.5-flash"         # THE SAFETY NET (Works for everyone)
    ]
    
    # We will just return the list to let the main loop try them one by one
    return priority_list

# --- ROBUST ANALYSIS ENGINE ---
def analyze_pdf(pdf_bytes):
    api_key = st.secrets["gemini_api_key"]
    genai.configure(api_key=api_key)
    
    models_to_try = get_working_model(api_key)
    
    # Extract Text ONCE (Works for all models)
    text_content = extract_text_from_pdf(pdf_bytes)
    if not text_content:
        st.error("❌ Error: PDF appears to be empty or scanned.")
        return None

    prompt = """
    Act as a Senior Financial Analyst. Extract data from this earnings report.
    
    TASK 1: FINANCIALS (Normalize to INR Crores. If Mn, divide by 10).
    JSON Keys: interest_income, interest_expense, nii, other_income, total_income, opex, ppop, provisions, pbt, tax, pat, aum, gnpa_percent, nnpa_percent.
    
    TASK 2: STRATEGY (1 sentence summary).
    JSON Keys: ai_digital, hr_people, geography, credit_borrowings, partnerships, leadership, product_mix, customer_eng, new_initiatives, productivity.
    
    OUTPUT: Single JSON object with keys "financials" and "strategy".
    """

    # --- THE FALLBACK LOOP ---
    last_error = None
    
    for model_name in models_to_try:
        try:
            # Show the user which brain we are testing
            status_msg = st.empty()
            status_msg.caption(f"🤖 Attempting with brain: **{model_name}**...")
            
            model = genai.GenerativeModel(model_name)
            
            # Send Request
            response = model.generate_content([prompt, text_content])
            
            # If we get here, IT WORKED!
            status_msg.success(f"✅ Success! Used brain: **{model_name}**")
            time.sleep(1) # Let user see the success message
            status_msg.empty() # Clear it
            
            return clean_json(response.text)
            
        except Exception as e:
            # If it fails (Quota, 404, 429), catch it and try the next one
            error_str = str(e).lower()
            if "404" in error_str:
                status_msg.caption(f"⚠️ {model_name} not found. Skipping...")
            elif "quota" in error_str or "429" in error_str:
                status_msg.caption(f"⚠️ {model_name} quota exceeded. Switching to cheaper model...")
            else:
                status_msg.caption(f"⚠️ {model_name} error: {str(e)[:50]}...")
            
            last_error = e
            continue # Loop to next model in list

    # If ALL models fail
    st.error(f"❌ All AI Models Failed. Last Error: {last_error}")
    return None

# --- HELPER: EXTRACT TEXT FROM PDF ---
def extract_text_from_pdf(pdf_bytes):
    try:
        pdf_file = io.BytesIO(pdf_bytes)
        reader = pypdf.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            if page.extract_text():
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
            st.write("🧠 Thinking...")
            data = analyze_pdf(pdf)
            
            if data:
                st.write("💾 Saving to Database...")
                if save_to_db(data, comp, qtr):
                    st.success("Success! Database Updated.")
                    st.json(data)
                    status.update(label="Complete", state="complete")
            else:
                st.warning("Analysis stopped. See error details above.")
        else:
            st.error(f"File not found in Drive. Looked for name containing: '{comp}' AND '{qtr}'")
