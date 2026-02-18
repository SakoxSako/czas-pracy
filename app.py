import streamlit as st
import pandas as pd
from datetime import datetime
import hashlib
import gspread
from google.oauth2.service_account import Credentials
from zoneinfo import ZoneInfo
import time

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

# ---  ZAPIS DO INDYWIDUALNEGO ARKUSZA ---
def save_to_personal_sheet(username, action, row_data=None, end_time_str=None, duration=None):
    """
    Zapisuje dane do arkusza o nazwie użytkownika (tworzy go, jeśli nie istnieje).
    """
    try:
        # 1. Próba otwarcia arkusza użytkownika
        try:
            ws_user = sh.worksheet(username)
        except gspread.WorksheetNotFound:
            # Jeśli nie istnieje, tworzymy go i dodajemy nagłówki
            ws_user = sh.add_worksheet(title=username, rows=1000, cols=6)
            ws_user.append_row(["Użytkownik", "Data", "Wejście", "Wyjście", "Status", "Godziny"])
        
        # 2. Obsługa akcji
        if action == "start":
            ws_user.append_row(row_data)
            
        elif action == "stop":
            # Musimy znaleźć ostatni wiersz "W Pracy" w arkuszu użytkownika
            # Ponieważ to arkusz tylko jednego usera, szukamy po prostu ostatniego "W Pracy" w kolumnie E (5)
            statuses = ws_user.col_values(5) # Kolumna Status
            
            found_idx = -1
            for i in range(len(statuses) - 1, -1, -1):
                if statuses[i] == "W Pracy":
                    found_idx = i + 1
                    break
            
            if found_idx != -1:
                ws_user.update_cell(found_idx, 4, end_time_str) # Wyjście
                ws_user.update_cell(found_idx, 5, "Zakończono") # Status
                ws_user.update_cell(found_idx, 6, duration)     # Godziny
                
    except Exception as e:
        st.error(f"Błąd zapisu w arkuszu osobistym: {e}")

# --- INICJALIZACJA UI ---
st.set_page_config(page_title="Rejestrator Czasu", page_icon="🇵🇱")

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ''
if 'user_token' not in st.session_state:
    st.session_state['user_token'] = ''

# --- LOGIKA AUTO-LOGOWANIA PRZEZ URL (QR KODY) ---
query_params = st.query_params
qr_user = query_params.get("user", None)
qr_token = query_params.get("token", None)
qr_action = query_params.get("akcja", None)

if qr_user and qr_token and not st.session_state['logged_in']:
    # Próba automatycznego logowania
    df_users = get_users_df()
    found = df_users[df_users['username'] == qr_user]
    
    if not found.empty:
        # W tokenie w QR kodzie przesyłamy HASH hasła, więc porównujemy hash z hashem w bazie
        stored_hash = found.iloc[0]['password']
        if qr_token == stored_hash:
            st.session_state['logged_in'] = True
            st.session_state['username'] = qr_user
            st.session_state['user_token'] = stored_hash
            st.toast(f"🔑 Zalogowano automatycznie z QR: {qr_user}")
        else:
            st.error("Nieprawidłowy token QR.")
    else:
        st.error("Użytkownik z QR nie istnieje.")

# --- FUNKCJA GŁÓWNA ---
def main_app():
    username = st.session_state['username']
    
    # Obsługa akcji z QR kodu (jeśli jesteśmy zalogowani i jest akcja w URL)
    if qr_action:
        now = datetime.now(ZoneInfo("Europe/Warsaw"))
        
        # Pobieramy stan, żeby wiedzieć czy można wykonać akcję
        df_temp = get_logs_df()
        is_working_qr = False
        if not df_temp.empty:
            u_df = df_temp[df_temp["Użytkownik"] == username]
            if not u_df.empty:
                is_working_qr = u_df.iloc[-1]["Status"] == "W Pracy"

        if qr_action == "start":
            if not is_working_qr:
                row = [username, now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S"), "", "W Pracy", 0.0]
                worksheet_logs.append_row(row)
                save_to_personal_sheet(username, "start", row_data=row)
                st.toast(f"✅ QR START: {now.strftime('%H:%M')}")
            else:
                st.toast("⚠️ Już pracujesz!", icon="Info")
                
        elif qr_action == "stop":
            if is_working_qr:
                # Logika STOP dla QR
                end_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
                
                # Szukamy wiersza w GŁÓWNYM arkuszu
                all_users = worksheet_logs.col_values(1)
                all_statuses = worksheet_logs.col_values(5)
                found_row_index = -1
                for i in range(len(all_users) - 1, -1, -1):
                    if all_users[i] == username and all_statuses[i] == "W Pracy":
                        found_row_index = i + 1
                        break
                
                if found_row_index != -1:
                    # Pobieramy czas wejścia, żeby policzyć różnicę
                    start_time_str = df_temp[df_temp["Użytkownik"] == username].iloc[-1]['Wejście']
                    duration = calculate_duration(start_time_str, end_time_str)

                    worksheet_logs.update_cell(found_row_index, 4, end_time_str)
                    worksheet_logs.update_cell(found_row_index, 5, "Zakończono")
                    worksheet_logs.update_cell(found_row_index, 6, duration)
                    
                    # Aktualizacja w arkuszu OSOBISTYM
                    save_to_personal_sheet(username, "stop", end_time_str=end_time_str, duration=duration)
                    
                    st.toast(f"🛑 QR STOP. Czas: {duration}h")
                else:
                    st.error("Błąd synchronizacji QR.")
            else:
                st.toast("⚠️ Nie pracujesz, więc nie możesz skończyć.", icon="Info")

        # Czyścimy URL po wykonaniu akcji (żeby odświeżenie strony nie dublowało)
        st.query_params.clear()
        time.sleep(2) # Krótka pauza żeby toast był widoczny
        st.rerun()


    # --- STANDARDOWY INTERFEJS ---
    st.sidebar.success(f"Zalogowany: {username}")
    
    # GENERATOR KODÓW QR DLA UŻYTKOWNIKA
    with st.sidebar.expander("📱 Twoje Kody QR (Start/Stop)"):
        st.write("Wydrukuj te linki lub wygeneruj z nich kody QR.")
        
        # Pobieramy hash hasła (token) z sesji lub z bazy jeśli brak w sesji
        token = st.session_state.get('user_token', '')
        if not token:
             # Fallback jeśli token zginął z sesji
             users = get_users_df()
             token = users[users['username']==username].iloc[0]['password']

        base_url = "https://twoja-aplikacja.streamlit.app" # <--- ZMIENI SIĘ SAMO NA PASKU ADRESU, ALE TU MOŻESZ WPISAĆ NA SZTYWNO
        # Streamlit cloud URL detection workaround:
        # Lepiej, żeby użytkownik skopiował base url z paska przeglądarki.
        
        link_start = f"?user={username}&token={token}&akcja=start"
        link_stop = f"?user={username}&token={token}&akcja=stop"
        
        st.text_input("Link START (do QR kodu)", value=link_start)
        st.text_input("Link STOP (do QR kodu)", value=link_stop)
        st.caption("Skopiuj pełny adres strony + ten tekst powyżej do generatora QR.")

    if st.sidebar.button("Wyloguj"):
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''
        st.session_state['user_token'] = ''
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

    # --- BUTTONY RĘCZNE ---
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        if not is_working:
            st.info("Status: POZA PRACĄ")
            if st.button("🟢 ZACZNIJ PRACĘ", use_container_width=True):
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
                save_to_personal_sheet(username, "start", row_data=row)
                st.toast(f"Zalogowano: {now.strftime('%H:%M')}")
                st.rerun()
        else:
            start_time_str = user_df.iloc[-1]['Wejście']
            st.success(f"Pracujesz od: {start_time_str[11:16]}")
            
            if st.button("🔴 KOŃCZĘ PRACĘ", use_container_width=True):
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
                    
                    # ZAPIS DO OSOBISTEGO
                    save_to_personal_sheet(username, "stop", end_time_str=end_time_str, duration=duration)
                    
                    st.toast(f"Koniec pracy. Czas: {duration}h")
                    st.rerun()
                else:
                    st.error("Błąd synchronizacji.")

    st.divider()
    st.subheader("Historia")
    if not user_df.empty:
        history = user_df[user_df["Status"] == "Zakończono"]
        if not history.empty:
            st.dataframe(history[["Data", "Wejście", "Wyjście", "Godziny"]].sort_index(ascending=False), use_container_width=True)

            csv_data = history[["Data", "Wejście", "Wyjście", "Godziny"]].to_csv(sep=';', decimal=',', index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 Pobierz Excel (CSV)",
                data=csv_data,
                file_name=f'godziny_{username}.csv',
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
                        st.session_state['user_token'] = stored_hash # Zapisujemy token do sesji dla generatora QR
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
