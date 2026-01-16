import re
from pathlib import Path

import pandas as pd
import streamlit as st

# For local testing, point to a folder of excel files.
# On Streamlit Cloud later, you’ll likely use a repo folder like Path("data")
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

    # numeric coercion; '000010' -> 10, '40' -> 40
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

    # CLEANING RULE:
    # delete row if Shipped Qty OR Ship Date is blank
    df = df[~df["Shipped Qty"].apply(is_blank) & ~df["Ship Date"].apply(is_blank)].copy()

    # Normalize ROMP to 01-12 style
    df["ROMP"] = df["ROMP"].apply(normalize_romp)

    # Normalize SAP to an int so lookup is consistent across files
    df["SAP"] = df["SAP"].apply(normalize_sap_to_int).astype("Int64")

    # Optional: drop rows that became invalid after normalization
    df = df.dropna(subset=["ROMP", "SAP"])

    return df[required]

@st.cache_data(show_spinner=False)
def build_database(data_dir: Path) -> pd.DataFrame:
    files = sorted(data_dir.glob("*.xlsx"))
    if not files:
        return pd.DataFrame(columns=["SAP", "ROMP", "Catalog", "Shipped Qty", "Ship Date", "Carrier"])

    frames = [clean_one_file(p) for p in files]
    return pd.concat(frames, ignore_index=True)

def render_card(row: pd.Series):
    # Mobile-friendly vertical card display
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

st.set_page_config(page_title="ROMP Shipment Lookup", layout="centered")
st.title("ROMP Shipment Lookup")

db = build_database(DATA_DIR)

with st.expander("Database status"):
    st.write(f"Files found: **{len(list(DATA_DIR.glob('*.xlsx')))}**")
    st.write(f"Rows in database (after cleaning): **{len(db)}**")

romp = st.selectbox("Select ROMP", ROMP_OPTIONS)
sap_text = st.text_input("Enter SAP (number)", placeholder="e.g., 10 or 170")

sap_val = None
if sap_text.strip():
    try:
        sap_val = int(sap_text.strip())
    except ValueError:
        st.error("SAP must be a number.")

if sap_val is not None:
    matches = db[(db["ROMP"] == romp) & (db["SAP"] == sap_val)]

    st.subheader("Results")
    if matches.empty:
        st.info(f"No matches for ROMP {romp} + SAP {sap_val}.")
    else:
        for _, r in matches.iterrows():
            render_card(r)

        with st.expander("Table view"):
            st.dataframe(matches, use_container_width=True, hide_index=True)
