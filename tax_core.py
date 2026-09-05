"""
tax_core.py
------------------------------------------------------------------
Pure calculation logic for the FY 2019-20 (old regime) income tax
calculator. Contains NO input()/print() - it is imported by both the
FastAPI backend (fastapi_app.py) and can be reused by any other
front end (CLI, Streamlit, etc.) so the tax rules live in exactly one
place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

logger = logging.getLogger("TaxCore")


# ---------------------------------------------------------------------------
# Reference data (shared by backend + any frontend that wants the option list)
# ---------------------------------------------------------------------------
EIGHTY_C_OPTIONS: List[str] = [
    "Life Insurance Premium",
    "Equity Linked Savings Scheme (ELSS)",
    "Employee's Provident Fund (EPF)",
    "General Provident Fund (GPF)",
    "Principal Payment on Home Loan",
    "PPF Account",
    "National Saving Certificate (NSC)",
    "National Pension Scheme",
    "Tuition Fee of Two Children",
]
HUNDRED_PCT_80G_FUNDS: List[str] = [
    "Prime Minister's National Relief Fund",
    "Family Welfare Relief Fund",
    "National Security Fund",
    "Prime Minister's Armenia Earthquake Relief Fund",
    "Swachh Bharat Kosh",
    "Clean Ganga Fund",
    "Chief Minister's Relief Fund",
]
FIFTY_PCT_80G_FUNDS: List[str] = [
    "Jawaharlal Nehru Memorial Fund",
    "Prime Minister's Drought Relief Fund",
    "Indira Gandhi Memorial Trust",
]

# Caps / constants
STANDARD_DEDUCTION = 50_000
CAP_80C = 150_000
CAP_80D_NON_SENIOR = 25_000
CAP_80D_SENIOR = 25_000
CAP_SECTION_24 = 200_000
CAP_80TTA = 10_000     # non-senior: savings-account interest only
CAP_80TTB = 50_000     # senior citizens: all deposit interest
REBATE_87A_INCOME_LIMIT = 500_000
REBATE_87A_MAX_AMOUNT = 12_500
CESS_RATE = 0.04


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Taxpayer:
    gross_income: float
    age: int

    def __post_init__(self) -> None:
        if self.gross_income < 0:
            raise ValueError("Gross income cannot be negative.")
        if self.age <= 0 or self.age > 130:
            raise ValueError("Age must be a realistic positive number.")

    @property
    def is_senior_citizen(self) -> bool:
        return self.age >= 60

    @property
    def basic_exemption_limit(self) -> int:
        return 300_000 if self.is_senior_citizen else 250_000


@dataclass
class DeductionResult:
    section: str
    amount_claimed: float
    items: Dict[str, float] = field(default_factory=dict)


@dataclass
class DeductionSummary:
    results: List[DeductionResult] = field(default_factory=list)

    def add(self, result: DeductionResult) -> None:
        self.results.append(result)
        logger.info("%s: deduction claimed Rs %.2f", result.section, result.amount_claimed)

    @property
    def total(self) -> float:
        return sum(r.amount_claimed for r in self.results)


# ---------------------------------------------------------------------------
# Deduction engine - pure computation, takes structured amounts (no prompts)
# ---------------------------------------------------------------------------
class DeductionEngine:
    """Evaluates deduction sections from already-collected amounts.

    This mirrors the interactive DeductionCollector used by the CLI
    version, but instead of asking the user questions it simply takes
    the amounts (e.g. from a JSON request body or Streamlit form) and
    applies the same caps/rules.
    """

    def __init__(self, taxpayer: Taxpayer) -> None:
        self.taxpayer = taxpayer

    @staticmethod
    def _clean_items(items: Dict[str, float]) -> Dict[str, float]:
        """Drop non-positive/invalid entries and coerce to float."""
        cleaned = {}
        for name, amount in (items or {}).items():
            try:
                value = float(amount)
            except (TypeError, ValueError):
                logger.warning("Skipping non-numeric deduction amount for %r: %r", name, amount)
                continue
            if value > 0:
                cleaned[name] = value
        return cleaned

    def evaluate_80c(self, items: Dict[str, float]) -> DeductionResult:
        items = self._clean_items(items)
        total = sum(items.values())
        claimed = min(total, CAP_80C)
        return DeductionResult("Section 80C", claimed, items)

    def evaluate_80d(self, amount: float) -> DeductionResult:
        amount = max(float(amount or 0), 0)
        cap = CAP_80D_SENIOR if self.taxpayer.is_senior_citizen else CAP_80D_NON_SENIOR
        claimed = min(amount, cap)
        items = {"Medical Insurance Premium": amount} if amount > 0 else {}
        return DeductionResult("Section 80D", claimed, items)

    def evaluate_section_24(self, amount: float) -> DeductionResult:
        amount = max(float(amount or 0), 0)
        claimed = min(amount, CAP_SECTION_24)
        items = {"Interest on Home Loan": amount} if amount > 0 else {}
        return DeductionResult("Section 24", claimed, items)

    def evaluate_80e(self, amount: float) -> DeductionResult:
        amount = max(float(amount or 0), 0)
        items = {"Interest on Education Loan": amount} if amount > 0 else {}
        return DeductionResult("Section 80E", amount, items)  # no upper cap

    def evaluate_80g(
        self,
        hundred_percent_items: Dict[str, float],
        fifty_percent_items: Dict[str, float],
    ) -> DeductionResult:
        hundred = self._clean_items(hundred_percent_items)
        fifty = self._clean_items(fifty_percent_items)

        items: Dict[str, float] = dict(hundred)
        total = sum(hundred.values())
        for name, amount in fifty.items():
            eligible = amount * 0.5
            items[name] = eligible
            total += eligible

        return DeductionResult("Section 80G", total, items)

    def evaluate_80tta_ttb(self, amount: float) -> DeductionResult:
        amount = max(float(amount or 0), 0)
        senior = self.taxpayer.is_senior_citizen
        section = "Section 80TTB" if senior else "Section 80TTA"
        cap = CAP_80TTB if senior else CAP_80TTA
        claimed = min(amount, cap)
        items = {"Interest Income": amount} if amount > 0 else {}
        return DeductionResult(section, claimed, items)

    def evaluate_all(self, deductions: "DeductionsInputLike") -> DeductionSummary:
        """`deductions` just needs the attributes used below (duck-typed so
        this works with a plain dict-like object or a Pydantic model)."""
        summary = DeductionSummary()
        summary.add(self.evaluate_80c(deductions.eighty_c))
        summary.add(self.evaluate_80d(deductions.eighty_d))
        summary.add(self.evaluate_section_24(deductions.section_24))
        summary.add(self.evaluate_80e(deductions.eighty_e))
        summary.add(
            self.evaluate_80g(deductions.eighty_g_hundred_percent, deductions.eighty_g_fifty_percent)
        )
        summary.add(self.evaluate_80tta_ttb(deductions.eighty_tta_ttb))
        return summary


# Type alias only used for the docstring/hint above - avoids importing
# Pydantic into this module, keeping it framework-agnostic.
DeductionsInputLike = "DeductionsInputLike"


# ---------------------------------------------------------------------------
# Pure tax computation
# ---------------------------------------------------------------------------
class IncomeTaxCalculator:
    def __init__(self, taxpayer: Taxpayer) -> None:
        self.taxpayer = taxpayer

    def compute_slab_tax(self, taxable_income: float) -> float:
        """Old-regime FY 2019-20 slab tax, before cess/rebate."""
        ti = max(taxable_income, 0.0)
        senior = self.taxpayer.is_senior_citizen

        if senior:
            if ti <= 300_000:
                return 0.0
            if ti <= 500_000:
                return 0.05 * (ti - 300_000)
            if ti <= 1_000_000:
                return 10_000 + 0.20 * (ti - 500_000)
            return 110_000 + 0.30 * (ti - 1_000_000)
        else:
            if ti <= 250_000:
                return 0.0
            if ti <= 500_000:
                return 0.05 * (ti - 250_000)
            if ti <= 1_000_000:
                return 12_500 + 0.20 * (ti - 500_000)
            return 112_500 + 0.30 * (ti - 1_000_000)

    def apply_87a_rebate(self, taxable_income: float, tax: float) -> Tuple[float, float]:
        """Returns (tax_after_rebate, rebate_amount)."""
        if taxable_income <= REBATE_87A_INCOME_LIMIT:
            rebate = min(tax, REBATE_87A_MAX_AMOUNT)
            return max(tax - rebate, 0.0), rebate
        return tax, 0.0

    def compute(self, gross_income: float, total_deductions: float) -> dict:
        income_after_standard_deduction = max(gross_income - STANDARD_DEDUCTION, 0.0)
        taxable_income = max(income_after_standard_deduction - total_deductions, 0.0)

        base_tax = self.compute_slab_tax(taxable_income)
        tax_after_rebate, rebate_amount = self.apply_87a_rebate(taxable_income, base_tax)
        cess = tax_after_rebate * CESS_RATE
        total_tax = round(tax_after_rebate + cess, 2)

        logger.info(
            "gross=%.2f deductions=%.2f taxable=%.2f base_tax=%.2f rebate=%.2f cess=%.2f total_tax=%.2f",
            gross_income, total_deductions, taxable_income, base_tax, rebate_amount, cess, total_tax,
        )

        return {
            "income_after_standard_deduction": round(income_after_standard_deduction, 2),
            "total_deductions": round(total_deductions, 2),
            "taxable_income": round(taxable_income, 2),
            "base_tax": round(base_tax, 2),
            "rebate_87a_applied": round(rebate_amount, 2),
            "tax_after_rebate": round(tax_after_rebate, 2),
            "cess": round(cess, 2),
            "total_tax_payable": total_tax,
            "income_after_tax": round(taxable_income - total_tax, 2),
        }