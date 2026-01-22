import re
from pathlib import Path
from datetime import date

import pandas as pd
import streamlit as st

DATA_DIR = Path("data")
ROMP_OPTIONS = [f"{i:02d}" for i in range(1, 13)]

def is_blank(x) -> bool:
    if pd.isna(x):
        return True
    return str(x).strip() == ""

def normalize_romp(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    m = re.search(r"(\d+)", s)  # ROMP03 -> 03
    return m.group(1).zfill(2) if m else None

def normalize_sap_to_int(val):
    """Return a nullable integer (Int64) value or <NA> if not parseable."""
    if pd.isna(val):
        return pd.NA
    s = str(val).strip()

    # handle Excel reading '40.0' sometimes
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]

    num = pd.to_numeric(s, errors="coerce")
    if pd.isna(num):
        return pd.NA
    return int(num)

def clean_one_file(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=0)

    required = ["SAP", "ROMP", "Catalog", "Shipped Qty", "Ship Date", "Carrier"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")

    # delete row if Shipped Qty OR Ship Date is blank
    df = df[~df["Shipped Qty"].apply(is_blank) & ~df["Ship Date"].apply(is_blank)].copy()

    # Normalize ROMP
    df["ROMP"] = df["ROMP"].apply(normalize_romp)

    # Normalize SAP
    df["SAP"] = df["SAP"].apply(normalize_sap_to_int).astype("Int64")

    # Normalize Ship Date to a date (so searching works reliably)
    df["Ship Date"] = pd.to_datetime(df["Ship Date"], errors="coerce").dt.date

    # Drop rows missing key fields after normalization
    df = df.dropna(subset=["ROMP", "SAP", "Ship Date"])

    # remove fully duplicated rows (within file)
    df = df.drop_duplicates()

    return df[required]

@st.cache_data(show_spinner=False)
def build_database(data_dir: Path) -> pd.DataFrame:
    files = sorted(data_dir.glob("*.xlsx"))
    if not files:
        return pd.DataFrame(columns=["SAP", "ROMP", "Catalog", "Shipped Qty", "Ship Date", "Carrier"])

    frames = [clean_one_file(p) for p in files]
    db = pd.concat(frames, ignore_index=True)

    # remove fully duplicated rows across ALL files
    db = db.drop_duplicates().reset_index(drop=True)

    return db

def render_card(row: pd.Series):
    st.markdown(
        f"""
        <div style="padding: 12px; border: 1px solid rgba(0,0,0,0.15); border-radius: 12px; margin-bottom: 10px;">
          <div style="font-size: 16px; font-weight: 700; margin-bottom: 6px;">
            ROMP {row['ROMP']} • SAP {int(row['SAP'])}
          </div>
          <div><b>Catalog:</b> {row.get('Catalog','') or ''}</div>
          <div><b>Shipped Qty:</b> {row.get('Shipped Qty','') or ''}</div>
          <div><b>Ship Date:</b> {row.get('Ship Date','') or ''}</div>
          <div><b>Carrier:</b> {row.get('Carrier','') or ''}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def show_results(matches: pd.DataFrame, label: str):
    st.subheader("Results")
    if matches.empty:
        st.info(f"No matches for {label}.")
    else:
        for _, r in matches.iterrows():
            render_card(r)

st.set_page_config(page_title="CMH116 BusDuct Lookup", layout="centered")
st.title("CMH116 BusDuct Lookup")

db = build_database(DATA_DIR)

# --- Search mode selector (tabs) ---
tab_sap, tab_carrier, tab_date, tab_romp = st.tabs(
    ["Search by SAP", "Search by Carrier", "Search by Ship Date", "Entire ROMP"]
)

with tab_sap:
    romp = st.selectbox("Select ROMP", ROMP_OPTIONS, key="romp_sap")
    sap_text = st.text_input("Enter SAP", placeholder="e.g., 10 or 170", key="sap_input")
    search_clicked = st.button("Search", type="primary", key="btn_sap")

    if search_clicked:
        try:
            sap_val = int(sap_text.strip())
        except ValueError:
            st.error("SAP must be a number.")
            st.stop()

        matches = db[(db["ROMP"] == romp) & (db["SAP"] == sap_val)]
        show_results(matches, f"ROMP {romp} + SAP {sap_val}")

with tab_carrier:
    romp = st.selectbox("Select ROMP", ROMP_OPTIONS, key="romp_carrier")

    carriers = (
        db.loc[db["ROMP"] == romp, "Carrier"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
    )
    carriers = sorted([c for c in carriers if c])

    carrier = st.selectbox("Select Carrier", ["(Select)"] + carriers, key="carrier_select")
    search_clicked = st.button("Search", type="primary", key="btn_carrier")

    if search_clicked:
        if carrier == "(Select)":
            st.error("Please select a carrier.")
            st.stop()

        carrier_norm = carrier.strip()
        matches = db[(db["ROMP"] == romp) & (db["Carrier"].astype(str).str.strip() == carrier_norm)]
        show_results(matches, f"ROMP {romp} + Carrier {carrier_norm}")

with tab_date:
    romp = st.selectbox("Select ROMP", ROMP_OPTIONS, key="romp_date")

    dates = db.loc[db["ROMP"] == romp, "Ship Date"].dropna()
    if dates.empty:
        st.info("No ship dates available for this ROMP.")
    else:
        min_d = dates.min()
        max_d = dates.max()

        ship_date = st.date_input(
            "Select Ship Date",
            value=max_d,
            min_value=min_d,
            max_value=max_d,
            key="ship_date",
        )
        search_clicked = st.button("Search", type="primary", key="btn_date")

        if search_clicked:
            matches = db[(db["ROMP"] == romp) & (db["Ship Date"] == ship_date)]
            show_results(matches, f"ROMP {romp} + Ship Date {ship_date}")

with tab_romp:
    romp = st.selectbox("Select ROMP", ROMP_OPTIONS, key="romp_all")
    search_clicked = st.button("Search", type="primary", key="btn_romp_all")

    if search_clicked:
        matches = db[db["ROMP"] == romp]

        # Optional: sort by Ship Date (nice when showing all)
        matches = matches.sort_values(["Ship Date", "SAP", "Catalog"], na_position="last")

        show_results(matches, f"ROMP {romp} (all shipped rows)")
