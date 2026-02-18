import streamlit as st
import pandas as pd
from datetime import datetime
import hashlib
import gspread
from google.oauth2.service_account import Credentials
from zoneinfo import ZoneInfo  

# --- KONFIGURACJA ---
try:
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    gc = gspread.authorize(credentials)
    
    sh = gc.open_by_url(st.secrets["spreadsheet_url"])
    worksheet_logs = sh.worksheet("logs")
    worksheet_users = sh.worksheet("users")
    
except Exception as e:
    st.error(f"Błąd połączenia z bazą danych: {e}")
    st.stop()

# --- FUNKCJE POMOCNICZE ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    return make_hashes(password) == hashed_text

def calculate_duration(start_str, end_str):
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        t1 = datetime.strptime(start_str, fmt)
        t2 = datetime.strptime(end_str, fmt)
        hours = (t2 - t1).total_seconds() / 3600
        return round(hours * 4) / 4
    except:
        return 0.0

def get_logs_df():
    # PANCERNA METODA POBIERANIA DANYCH
    all_values = worksheet_logs.get_all_values()
    if not all_values:
        return pd.DataFrame(columns=["Użytkownik", "Data", "Wejście", "Wyjście", "Status", "Godziny"])
    
    headers = all_values.pop(0)
    clean_headers = [h.strip() for h in headers]
    df = pd.DataFrame(all_values, columns=clean_headers)
    return df

def get_users_df():
    all_values = worksheet_users.get_all_values()
    if not all_values:
         return pd.DataFrame(columns=["username", "password"])
    headers = all_values.pop(0)
    clean_headers = [h.strip() for h in headers]
    return pd.DataFrame(all_values, columns=clean_headers)

# --- INICJALIZACJA UI ---
st.set_page_config(page_title="Rejestrator Czasu", page_icon="🇵🇱")

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ''

# --- FUNKCJA GŁÓWNA ---
def main_app():
    username = st.session_state['username']
    st.sidebar.success(f"Zalogowany: {username}")
    
    if st.sidebar.button("Wyloguj"):
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''
        st.rerun()

    st.title(f"Cześć, {username}! 👋")

    df = get_logs_df()
    
    is_working = False
    user_df = pd.DataFrame()

    if not df.empty:
        user_df = df[df["Użytkownik"] == username]
        if not user_df.empty:
            last_entry = user_df.iloc[-1]
            is_working = last_entry["Status"] == "W Pracy"

    # --- LOGIKA START / STOP ---
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        if not is_working:
            st.info("Status: POZA PRACĄ")
            if st.button("🟢 ZACZNIJ PRACĘ", use_container_width=True):
                #  CZAS POLSKI
                now = datetime.now(ZoneInfo("Europe/Warsaw"))
                
                row = [
                    username,
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    "",
                    "W Pracy",
                    0.0
                ]
                worksheet_logs.append_row(row)
                st.toast(f"Zalogowano wejście: {now.strftime('%H:%M')}")
                st.rerun()
        else:
            start_time_str = user_df.iloc[-1]['Wejście']
            st.success(f"Pracujesz od: {start_time_str[11:16]}")
            
            if st.button("🔴 KOŃCZĘ PRACĘ", use_container_width=True):
                #  CZAS POLSKI
                now = datetime.now(ZoneInfo("Europe/Warsaw"))
                end_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
                
                all_users = worksheet_logs.col_values(1)
                all_statuses = worksheet_logs.col_values(5)
                
                found_row_index = -1
                for i in range(len(all_users) - 1, -1, -1):
                    if all_users[i] == username and all_statuses[i] == "W Pracy":
                        found_row_index = i + 1
                        break
                
                if found_row_index != -1:
                    duration = calculate_duration(user_df.iloc[-1]['Wejście'], end_time_str)
                    
                    worksheet_logs.update_cell(found_row_index, 4, end_time_str)
                    worksheet_logs.update_cell(found_row_index, 5, "Zakończono")
                    worksheet_logs.update_cell(found_row_index, 6, duration)
                    
                    st.toast(f"Koniec pracy. Czas: {duration}h")
                    st.rerun()
                else:
                    st.error("Błąd synchronizacji.")

    # --- AUTOMATYZACJA (QR) ---
    query_params = st.query_params
    auto_action = query_params.get("akcja", None)
    
    if auto_action:
        #  CZAS POLSKI DLA QR KODÓW 
        now = datetime.now(ZoneInfo("Europe/Warsaw"))
        
        if auto_action == "start" and not is_working:
             row = [username, now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S"), "", "W Pracy", 0.0]
             worksheet_logs.append_row(row)
             st.query_params.clear()
             st.rerun()
        # (Tu można dodać logikę STOP dla QR jeśli potrzebna w przyszłości)

    st.divider()
    st.subheader("Historia")
    if not user_df.empty:
        # Filtrujemy, żeby pokazać tylko zakończone i posortowane
        history = user_df[user_df["Status"] == "Zakończono"]
        if not history.empty:
            st.dataframe(history[["Data", "Wejście", "Wyjście", "Godziny"]].sort_index(ascending=False), use_container_width=True)

            
            
            csv_data = history[["Data", "Wejście", "Wyjście", "Godziny"]].to_csv(sep=';', decimal=',', index=False).encode('utf-8-sig')
            
            st.download_button(
                label="📥 Pobierz poprawny plik Excel (CSV)",
                data=csv_data,
                file_name=f'godziny_pracy_{username}.csv',
                mime='text/csv'
            )

# --- LOGOWANIE ---
def login_page():
    st.title("🔐 Panel Logowania")
    menu = ["Logowanie", "Rejestracja"]
    choice = st.selectbox("Wybierz opcję", menu)

    if choice == "Logowanie":
        user = st.text_input("Login")
        passwd = st.text_input("Hasło", type='password')
        if st.button("Zaloguj"):
            df_users = get_users_df()
            if not df_users.empty:
                found = df_users[df_users['username'] == user]
                if not found.empty:
                    stored_hash = found.iloc[0]['password']
                    if check_hashes(passwd, stored_hash):
                        st.session_state['logged_in'] = True
                        st.session_state['username'] = user
                        st.rerun()
                    else:
                        st.error("Błędne hasło")
                else:
                    st.error("Brak użytkownika")
            else:
                st.error("Baza pusta")

    elif choice == "Rejestracja":
        new_user = st.text_input("Nowy Login")
        new_pass = st.text_input("Nowe Hasło", type='password')
        if st.button("Utwórz konto"):
            df_users = get_users_df()
            if not df_users.empty and new_user in df_users['username'].values:
                st.warning("Użytkownik już istnieje")
            elif new_user and new_pass:
                worksheet_users.append_row([new_user, make_hashes(new_pass)])
                st.success("Konto utworzone! Przejdź do logowania.")

if st.session_state['logged_in']:
    main_app()
else:
    login_page()
