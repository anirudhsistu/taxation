"""
streamlit_app.py
------------------------------------------------------------------
Streamlit frontend for the Income Tax Calculator. Talks to the FastAPI
backend (fastapi_app.py) over HTTP - it does not contain any tax logic
itself, so the rules always stay in one place (tax_core.py).

Run locally (in a separate terminal from the FastAPI backend):
    streamlit run streamlit_app.py

Make sure the backend is already running first:
    uvicorn fastapi_app:app --reload --port 8000
"""

from __future__ import annotations

import logging

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Config / logging
# ---------------------------------------------------------------------------
API_BASE_URL = "http://localhost:8000"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("TaxFrontend")

st.set_page_config(page_title="Income Tax Calculator (FY 2019-20)", page_icon="🧾", layout="centered")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300)
def fetch_deduction_options() -> dict | None:
    """Pull option lists + caps from the backend so the form matches the rules."""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/deduction-options", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        logger.error("Failed to fetch deduction options: %s", exc)
        return None


def checkbox_amount_group(section_title: str, cap_note: str, options: list[str], key_prefix: str) -> dict:
    """Renders a checkbox + amount input per option; returns {option: amount} for checked items."""
    st.subheader(section_title)
    if cap_note:
        st.caption(cap_note)
    values = {}
    for option in options:
        col1, col2 = st.columns([2, 1])
        checked = col1.checkbox(option, key=f"{key_prefix}_chk_{option}")
        if checked:
            amount = col2.number_input(
                "Amount (Rs)", min_value=0, step=1000, key=f"{key_prefix}_amt_{option}", label_visibility="collapsed"
            )
            values[option] = amount
    return values


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("🧾 Income Tax Calculator")
st.caption("Old tax regime · Financial Year 2019-20 (Assessment Year 2020-21)")

options = fetch_deduction_options()
if options is None:
    st.error(
        "Could not reach the tax calculation API at "
        f"`{API_BASE_URL}`. Make sure it's running:\n\n"
        "`uvicorn fastapi_app:app --reload --port 8000`"
    )
    st.stop()

st.header("1. Basic details")
col1, col2 = st.columns(2)
gross_income = col1.number_input("Gross annual income (Rs)", min_value=0, step=10000, value=800000)
age = col2.number_input("Age", min_value=1, max_value=130, value=30)

is_senior = age >= 60
exemption_limit = 300000 if is_senior else 250000
st.caption(
    f"{'Senior citizen' if is_senior else 'Regular taxpayer'} · "
    f"Basic exemption limit: Rs {exemption_limit:,} · "
    f"Standard deduction: Rs {options['standard_deduction']:,.0f}"
)

st.header("2. Deductions")

eighty_c_items = checkbox_amount_group(
    "Section 80C", f"Combined cap: Rs {options['caps']['eighty_c']:,.0f}",
    options["eighty_c_options"], "eighty_c",
)

st.subheader("Section 80D - Medical Insurance Premium")
cap_80d = options["caps"]["eighty_d_senior"] if is_senior else options["caps"]["eighty_d_non_senior"]
st.caption(f"Cap: Rs {cap_80d:,.0f}")
eighty_d_amount = st.number_input("Premium paid (Rs)", min_value=0, step=1000, key="eighty_d")

st.subheader("Section 24 - Home Loan Interest")
st.caption(f"Cap: Rs {options['caps']['section_24']:,.0f}")
section_24_amount = st.number_input("Interest paid (Rs)", min_value=0, step=1000, key="section_24")

st.subheader("Section 80E - Education Loan Interest")
st.caption("No upper cap")
eighty_e_amount = st.number_input("Interest paid (Rs)", min_value=0, step=1000, key="eighty_e")

eighty_g_hundred = checkbox_amount_group(
    "Section 80G - Funds eligible for 100% deduction", "", options["eighty_g_hundred_percent_funds"], "g100",
)
eighty_g_fifty = checkbox_amount_group(
    "Section 80G - Funds eligible for 50% deduction", "", options["eighty_g_fifty_percent_funds"], "g50",
)

section_label = "80TTB (all deposit interest)" if is_senior else "80TTA (savings account interest)"
cap_tta = options["caps"]["eighty_ttb"] if is_senior else options["caps"]["eighty_tta"]
st.subheader(f"Section {section_label}")
st.caption(f"Cap: Rs {cap_tta:,.0f}")
eighty_tta_amount = st.number_input("Interest earned (Rs)", min_value=0, step=500, key="eighty_tta")

st.divider()

if st.button("Calculate Tax", type="primary", use_container_width=True):
    payload = {
        "gross_income": gross_income,
        "age": age,
        "deductions": {
            "eighty_c": eighty_c_items,
            "eighty_d": eighty_d_amount,
            "section_24": section_24_amount,
            "eighty_e": eighty_e_amount,
            "eighty_g_hundred_percent": eighty_g_hundred,
            "eighty_g_fifty_percent": eighty_g_fifty,
            "eighty_tta_ttb": eighty_tta_amount,
        },
    }

    try:
        response = requests.post(f"{API_BASE_URL}/api/calculate-tax", json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.ConnectionError:
        st.error("Could not connect to the API. Is the FastAPI backend running on localhost:8000?")
        logger.error("Connection error calling calculate-tax endpoint.")
        st.stop()
    except requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = response.json().get("detail", "")
        except Exception:
            pass
        st.error(f"The API rejected the request: {detail or exc}")
        logger.error("HTTP error from calculate-tax endpoint: %s", exc)
        st.stop()
    except requests.exceptions.RequestException as exc:
        st.error(f"Unexpected error contacting the API: {exc}")
        logger.exception("Unexpected error calling calculate-tax endpoint.")
        st.stop()

    st.header("3. Results")

    m1, m2, m3 = st.columns(3)
    m1.metric("Taxable Income", f"Rs {result['taxable_income']:,.0f}")
    m2.metric("Total Tax Payable", f"Rs {result['total_tax_payable']:,.0f}")
    m3.metric("Income After Tax", f"Rs {result['income_after_tax']:,.0f}")

    with st.expander("Deduction breakdown", expanded=True):
        for section in result["deduction_breakdown"]:
            st.write(f"**{section['section']}**: Rs {section['amount_claimed']:,.2f}")
            if section["items"]:
                st.table(
                    {"Item": list(section["items"].keys()), "Amount (Rs)": list(section["items"].values())}
                )
        st.write(f"**Total deductions claimed**: Rs {result['total_deductions']:,.2f}")

    with st.expander("Tax computation details", expanded=True):
        st.write(f"Income after standard deduction: Rs {result['income_after_standard_deduction']:,.2f}")
        st.write(f"Taxable income: Rs {result['taxable_income']:,.2f}")
        st.write(f"Tax before rebate: Rs {result['base_tax']:,.2f}")
        if result["rebate_87a_applied"]:
            st.write(f"Section 87A rebate applied: Rs {result['rebate_87a_applied']:,.2f}")
        st.write(f"Health & Education Cess (4%): Rs {result['health_and_education_cess']:,.2f}")
        st.write(f"**Total tax payable: Rs {result['total_tax_payable']:,.2f}**")