import streamlit as st
import pandas as pd
from datetime import datetime
import hashlib
import gspread
from google.oauth2.service_account import Credentials
from zoneinfo import ZoneInfo
import time
import qrcode
from io import BytesIO

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

# --- FUNKCJA GENERUJĄCA OBRAZEK QR ---
def generate_qr_image(url):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()

# --- ZAPIS DO INDYWIDUALNEGO ARKUSZA ---
def save_to_personal_sheet(username, action, row_data=None, end_time_str=None, duration=None):
    try:
        try:
            ws_user = sh.worksheet(username)
        except gspread.WorksheetNotFound:
            ws_user = sh.add_worksheet(title=username, rows=1000, cols=6)
            ws_user.append_row(["Użytkownik", "Data", "Wejście", "Wyjście", "Status", "Godziny"])
        
        if action == "start":
            ws_user.append_row(row_data)
        elif action == "stop":
            statuses = ws_user.col_values(5)
            found_idx = -1
            for i in range(len(statuses) - 1, -1, -1):
                if statuses[i] == "W Pracy":
                    found_idx = i + 1
                    break
            if found_idx != -1:
                ws_user.update_cell(found_idx, 4, end_time_str)
                ws_user.update_cell(found_idx, 5, "Zakończono")
                ws_user.update_cell(found_idx, 6, duration)
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

# --- LOGIKA AUTO-LOGOWANIA (QR) ---
query_params = st.query_params
qr_user = query_params.get("user", None)
qr_token = query_params.get("token", None)
qr_action = query_params.get("akcja", None)

if qr_user and qr_token and not st.session_state['logged_in']:
    df_users = get_users_df()
    found = df_users[df_users['username'] == qr_user]
    
    if not found.empty:
        stored_hash = found.iloc[0]['password']
        if qr_token == stored_hash:
            st.session_state['logged_in'] = True
            st.session_state['username'] = qr_user
            st.session_state['user_token'] = stored_hash
            st.toast(f"🔑 Zalogowano automatycznie: {qr_user}")
        else:
            st.error("Nieprawidłowy token QR.")
    else:
        st.error("Użytkownik z QR nie istnieje.")

# --- FUNKCJA GŁÓWNA ---
def main_app():
    username = st.session_state['username']
    
    # Obsługa akcji QR
    if qr_action:
        now = datetime.now(ZoneInfo("Europe/Warsaw"))
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
                # POPRAWKA 1: Zamiana icon="Info" na icon="⚠️"
                st.toast("⚠️ Już pracujesz!", icon="⚠️")
                
        elif qr_action == "stop":
            if is_working_qr:
                end_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
                all_users = worksheet_logs.col_values(1)
                all_statuses = worksheet_logs.col_values(5)
                found_row_index = -1
                for i in range(len(all_users) - 1, -1, -1):
                    if all_users[i] == username and all_statuses[i] == "W Pracy":
                        found_row_index = i + 1
                        break
                
                if found_row_index != -1:
                    start_time_str = df_temp[df_temp["Użytkownik"] == username].iloc[-1]['Wejście']
                    duration = calculate_duration(start_time_str, end_time_str)

                    worksheet_logs.update_cell(found_row_index, 4, end_time_str)
                    worksheet_logs.update_cell(found_row_index, 5, "Zakończono")
                    worksheet_logs.update_cell(found_row_index, 6, duration)
                    save_to_personal_sheet(username, "stop", end_time_str=end_time_str, duration=duration)
                    st.toast(f"🛑 QR STOP. Czas: {duration}h")
                else:
                    st.error("Błąd synchronizacji QR.")
            else:
                # POPRAWKA 2: Zamiana icon="Info" na icon="🚫"
                st.toast("⚠️ Nie pracujesz, więc nie możesz skończyć.", icon="🚫")

        st.query_params.clear()
        time.sleep(2)
        st.rerun()

    # --- PASEK BOCZNY Z KODAMI QR ---
    st.sidebar.success(f"Zalogowany: {username}")
    
    with st.sidebar.expander("📱 Twoje Kody QR (Pobierz)"):
        st.write("Zeskanuj telefonem, aby zalogować czas:")
        
        token = st.session_state.get('user_token', '')
        if not token:
             users = get_users_df()
             token = users[users['username']==username].iloc[0]['password']

        # !!! WAŻNE !!! UPEWNIJ SIĘ ŻE TEN ADRES JEST POPRAWNY (skopiuj go z przeglądarki)
        base_url = "https://twoja-aplikacja.streamlit.app" 
        
        url_start = f"{base_url}/?user={username}&token={token}&akcja=start"
        url_stop = f"{base_url}/?user={username}&token={token}&akcja=stop"
        
        st.subheader("🟢 START PRACY")
        img_start = generate_qr_image(url_start)
        st.image(img_start, caption=f"QR Start dla {username}")
        
        st.divider()
        
        st.subheader("🔴 KONIEC PRACY")
        img_stop = generate_qr_image(url_stop)
        st.image(img_stop, caption=f"QR Stop dla {username}")

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

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if not is_working:
            st.info("Status: POZA PRACĄ")
            if st.button("🟢 ZACZNIJ PRACĘ", use_container_width=True):
                now = datetime.now(ZoneInfo("Europe/Warsaw"))
                row = [username, now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S"), "", "W Pracy", 0.0]
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
            st.download_button(label="📥 Pobierz Excel (CSV)", data=csv_data, file_name=f'godziny_{username}.csv', mime='text/csv')

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
                        st.session_state['user_token'] = stored_hash
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
