from __future__ import annotations
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from typing import List, Any

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource(show_spinner=False)
def _client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def _open_workbook():
    client = _client()
    wb_name = st.secrets["gsheets"]["workbook_name"]
    return client.open(wb_name)

def _open_ws(name: str):
    wb = _open_workbook()
    try:
        return wb.worksheet(name)
    except Exception:
        wb.add_worksheet(title=name, rows=1000, cols=50)
        return wb.worksheet(name)

def append_row(ws_name: str, row: List[Any]):
    ws = _open_ws(ws_name)
    ws.append_row(row, value_input_option="USER_ENTERED")

def append_rows(ws_name: str, rows: List[List[Any]]):
    ws = _open_ws(ws_name)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")

def read_sheet(ws_name: str) -> pd.DataFrame:
    ws = _open_ws(ws_name)
    data = ws.get_all_records()
    return pd.DataFrame(data)

def ensure_headers(ws_name: str, headers: List[str]):
    ws = _open_ws(ws_name)
    vals = ws.get_all_values()
    if not vals:
        ws.append_row(headers, value_input_option="USER_ENTERED")
