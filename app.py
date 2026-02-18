import streamlit as st
import pandas as pd
from datetime import datetime
import os

# --- KONFIGURACJA ---
FILE_NAME = 'rejestr_godzin.csv'

# Funkcja do zaokrąglania czasu do 15 minut
def round_time_to_15min(dt):
    # Zaokrąglamy tylko do celów obliczeniowych, 
    # ale w bazie zapisujemy dokładny czas wejścia/wyjścia.
    minutes = dt.minute
    rounded_min = round(minutes / 15) * 15
    
    if rounded_min == 60:
        rounded_min = 0
        # Tu uproszczenie: w pełnej wersji należałoby dodać godzinę,
        # ale dla celów obliczeniowych minuty wystarczą.
    
    return f"{dt.hour:02d}:{rounded_min:02d}"

# Funkcja obliczająca czas pracy
def calculate_duration(start_str, end_str):
    fmt = "%Y-%m-%d %H:%M:%S"
    t1 = datetime.strptime(start_str, fmt)
    t2 = datetime.strptime(end_str, fmt)
    delta = t2 - t1
    hours = delta.total_seconds() / 3600
    # Zaokrąglenie wyniku do 0.25h (15 min)
    return round(hours * 4) / 4

# --- INTERFEJS UŻYTKOWNIKA ---
st.set_page_config(page_title="Rejestrator Czasu", page_icon="⏰")
st.title("⏰ Rejestracja Czasu Pracy")

# 1. Ładowanie lub tworzenie bazy danych
if not os.path.exists(FILE_NAME):
    df = pd.DataFrame(columns=["Data", "Wejście", "Wyjście", "Status", "Godziny (ok. 15min)"])
    df.to_csv(FILE_NAME, index=False)
else:
    df = pd.read_csv(FILE_NAME)

# 2. Sprawdzenie ostatniego statusu
if not df.empty:
    last_entry = df.iloc[-1]
    is_working = last_entry["Status"] == "W Pracy"
else:
    is_working = False

# 3. Główny Przycisk (Logika Wejścia/Wyjścia)
col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    if not is_working:
        # Przycisk WEJŚCIE
        if st.button("🟢 ZACZNIJ PRACĘ", use_container_width=True):
            now = datetime.now()
            new_row = {
                "Data": now.strftime("%Y-%m-%d"),
                "Wejście": now.strftime("%Y-%m-%d %H:%M:%S"),
                "Wyjście": None,
                "Status": "W Pracy",
                "Godziny (ok. 15min)": 0.0
            }
            # Dodanie nowego wiersza metodą concat (pandas 2.0+)
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            df.to_csv(FILE_NAME, index=False)
            st.success(f"Zalogowano wejście o: {now.strftime('%H:%M')}")
            st.rerun()
            
    else:
        # Przycisk WYJŚCIE
        st.info(f"Pracujesz od: {df.iloc[-1]['Wejście'][11:16]}")
        if st.button("🔴 KOŃCZĘ PRACĘ", use_container_width=True):
            now = datetime.now()
            idx = df.index[-1]
            
            # Aktualizacja rekordu
            df.at[idx, "Wyjście"] = now.strftime("%Y-%m-%d %H:%M:%S")
            df.at[idx, "Status"] = "Zakończono"
            
            # Obliczenie czasu z zaokrągleniem
            start_time = df.at[idx, "Wejście"]
            end_time = now.strftime("%Y-%m-%d %H:%M:%S")
            duration = calculate_duration(start_time, end_time)
            df.at[idx, "Godziny (ok. 15min)"] = duration
            
            df.to_csv(FILE_NAME, index=False)
            st.warning(f"Zalogowano wyjście o: {now.strftime('%H:%M')}. Przepracowano: {duration}h")
            st.rerun()

st.divider()

# 4. Wyświetlanie tabeli i Eksport do Excela
st.subheader("Historia Twojej pracy")

# Pokazujemy tylko zakończone sesje w tabeli podglądowej (bez technicznych kolumn)
display_df = df[df["Status"] == "Zakończono"][["Data", "Wejście", "Wyjście", "Godziny (ok. 15min)"]]

st.dataframe(display_df.sort_index(ascending=False), use_container_width=True)

# Konwersja do Excela
def convert_df_to_excel(df):
    from io import BytesIO
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Godziny Pracy')
    return output.getvalue()

if not df.empty:
    excel_data = convert_df_to_excel(df)
    st.download_button(
        label="📥 Pobierz Raport Excel",
        data=excel_data,
        file_name='moje_godziny_pracy.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )