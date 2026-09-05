"""
fastapi_app.py
------------------------------------------------------------------
FastAPI backend for the FY 2019-20 (old regime) income tax calculator.

Run locally:
    uvicorn fastapi_app:app --reload --port 8000

Interactive docs (Swagger UI) once running:
    http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from tax_core import (
    CAP_80C,
    CAP_80D_NON_SENIOR,
    CAP_80D_SENIOR,
    CAP_80TTA,
    CAP_80TTB,
    CAP_SECTION_24,
    EIGHTY_C_OPTIONS,
    FIFTY_PCT_80G_FUNDS,
    HUNDRED_PCT_80G_FUNDS,
    STANDARD_DEDUCTION,
    DeductionEngine,
    IncomeTaxCalculator,
    Taxpayer,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("tax_api.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("TaxAPI")


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------
class DeductionsInput(BaseModel):
    eighty_c: Dict[str, float] = Field(default_factory=dict, description="Section 80C items, e.g. {'PPF Account': 50000}")
    eighty_d: float = Field(0, ge=0, description="Medical insurance premium paid")
    section_24: float = Field(0, ge=0, description="Interest paid on home loan")
    eighty_e: float = Field(0, ge=0, description="Interest paid on education loan")
    eighty_g_hundred_percent: Dict[str, float] = Field(default_factory=dict, description="100%-eligible 80G donations")
    eighty_g_fifty_percent: Dict[str, float] = Field(default_factory=dict, description="50%-eligible 80G donations")
    eighty_tta_ttb: float = Field(0, ge=0, description="Interest earned on savings/deposits")


class TaxCalculationRequest(BaseModel):
    gross_income: float = Field(..., ge=0, description="Gross annual income in rupees")
    age: int = Field(..., ge=1, le=130, description="Taxpayer's age in years")
    deductions: DeductionsInput = Field(default_factory=DeductionsInput)

    @field_validator("gross_income")
    @classmethod
    def _validate_income(cls, v: float) -> float:
        if v > 1_000_000_000:
            raise ValueError("Gross income seems unrealistically high.")
        return v


class DeductionBreakdown(BaseModel):
    section: str
    amount_claimed: float
    items: Dict[str, float]


class TaxCalculationResponse(BaseModel):
    gross_income: float
    age: int
    is_senior_citizen: bool
    basic_exemption_limit: float
    standard_deduction: float
    income_after_standard_deduction: float
    deduction_breakdown: List[DeductionBreakdown]
    total_deductions: float
    taxable_income: float
    base_tax: float
    rebate_87a_applied: float
    tax_after_rebate: float
    health_and_education_cess: float
    total_tax_payable: float
    income_after_tax: float


class DeductionOptionsResponse(BaseModel):
    eighty_c_options: List[str]
    eighty_g_hundred_percent_funds: List[str]
    eighty_g_fifty_percent_funds: List[str]
    caps: Dict[str, float]
    standard_deduction: float


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Income Tax Calculator API",
    description="Old tax regime (FY 2019-20 / AY 2020-21) income tax calculator.",
    version="1.0.0",
)

# Allow a local Streamlit frontend (or any local dev frontend) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["health"])
def health_check() -> dict:
    return {"status": "ok", "service": "Income Tax Calculator API"}


@app.get("/api/deduction-options", response_model=DeductionOptionsResponse, tags=["reference"])
def get_deduction_options() -> DeductionOptionsResponse:
    """Reference data a frontend can use to render the deduction form."""
    return DeductionOptionsResponse(
        eighty_c_options=EIGHTY_C_OPTIONS,
        eighty_g_hundred_percent_funds=HUNDRED_PCT_80G_FUNDS,
        eighty_g_fifty_percent_funds=FIFTY_PCT_80G_FUNDS,
        caps={
            "eighty_c": CAP_80C,
            "eighty_d_non_senior": CAP_80D_NON_SENIOR,
            "eighty_d_senior": CAP_80D_SENIOR,
            "section_24": CAP_SECTION_24,
            "eighty_tta": CAP_80TTA,
            "eighty_ttb": CAP_80TTB,
        },
        standard_deduction=STANDARD_DEDUCTION,
    )


@app.post("/api/calculate-tax", response_model=TaxCalculationResponse, tags=["tax"])
def calculate_tax(request: TaxCalculationRequest) -> TaxCalculationResponse:
    logger.info("Received tax calculation request: gross_income=%s age=%s", request.gross_income, request.age)

    try:
        taxpayer = Taxpayer(gross_income=request.gross_income, age=request.age)
    except ValueError as exc:
        logger.warning("Invalid taxpayer input: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        engine = DeductionEngine(taxpayer)
        summary = engine.evaluate_all(request.deductions)

        calculator = IncomeTaxCalculator(taxpayer)
        result = calculator.compute(taxpayer.gross_income, summary.total)
    except Exception as exc:  # noqa: BLE001 - convert any computation error into a clean 500
        logger.exception("Tax calculation failed.")
        raise HTTPException(status_code=500, detail="Internal error while calculating tax.") from exc

    return TaxCalculationResponse(
        gross_income=taxpayer.gross_income,
        age=taxpayer.age,
        is_senior_citizen=taxpayer.is_senior_citizen,
        basic_exemption_limit=taxpayer.basic_exemption_limit,
        standard_deduction=STANDARD_DEDUCTION,
        income_after_standard_deduction=result["income_after_standard_deduction"],
        deduction_breakdown=[
            DeductionBreakdown(section=r.section, amount_claimed=r.amount_claimed, items=r.items)
            for r in summary.results
        ],
        total_deductions=result["total_deductions"],
        taxable_income=result["taxable_income"],
        base_tax=result["base_tax"],
        rebate_87a_applied=result["rebate_87a_applied"],
        tax_after_rebate=result["tax_after_rebate"],
        health_and_education_cess=result["cess"],
        total_tax_payable=result["total_tax_payable"],
        income_after_tax=result["income_after_tax"],
    )