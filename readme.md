# Income Tax Calculator (FY 2019-20, Old Regime)

Three files, three responsibilities:

| File               | Role                                                                 |
|---------------------|-----------------------------------------------------------------------|
| `tax_core.py`       | Pure calculation logic (no I/O). Single source of truth for tax rules.|
| `fastapi_app.py`    | REST API wrapping `tax_core.py`.                                      |
| `streamlit_app.py`  | Web UI that calls the API over HTTP.                                  |

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 2. Start the API (terminal 1)

```bash
uvicorn fastapi_app:app --reload --port 8000
```

- Swagger docs: http://localhost:8000/docs
- Health check: http://localhost:8000/

## 3. Start the frontend (terminal 2, while the API is still running)

```bash
streamlit run streamlit_app.py
```

- Opens at: http://localhost:8501

## API reference

### `GET /api/deduction-options`
Returns the 80C investment list, 80G fund lists, and current caps - used by
the frontend to render the form, but you can also call it directly.

### `POST /api/calculate-tax`
Request body:

```json
{
  "gross_income": 800000,
  "age": 45,
  "deductions": {
    "eighty_c": {"PPF Account": 100000, "Life Insurance Premium": 60000},
    "eighty_d": 20000,
    "section_24": 250000,
    "eighty_e": 30000,
    "eighty_g_hundred_percent": {"Clean Ganga Fund": 5000},
    "eighty_g_fifty_percent": {"Indira Gandhi Memorial Trust": 4000},
    "eighty_tta_ttb": 12000
  }
}
```

Response includes `taxable_income`, `total_tax_payable`, `income_after_tax`,
a per-section `deduction_breakdown`, and the Section 87A rebate applied (if
taxable income ≤ Rs 5,00,000).

## Notes

- CORS on the API is restricted to `localhost:8501` / `127.0.0.1:8501`
  (Streamlit's default port). Update `fastapi_app.py`'s `CORSMiddleware`
  origins if you serve the frontend elsewhere.
- Both apps log to console and to a local file (`tax_api.log` /
  console-only for the Streamlit app).
- All tax rules (slabs, caps, the Section 87A rebate) live only in
  `tax_core.py` - the API and UI never duplicate that logic.