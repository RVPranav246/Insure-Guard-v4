"""
Data loader — reads Excel sheets into pandas DataFrames.
All sheets loaded once at startup, held in memory.
Provides autofill, search, and lookup functions.
"""
import os
import pandas as pd
from difflib import SequenceMatcher

DATASET_PATH = os.path.join(os.path.dirname(__file__), "..", "motor_fraud_dataset_v2.xlsx")

_claims_df = None
_workshops_df = None
_benchmarks_df = None


def _load():
    global _claims_df, _workshops_df, _benchmarks_df
    if _claims_df is not None:
        return
    path = os.path.abspath(DATASET_PATH)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dataset not found at {path}")
    _claims_df    = pd.read_excel(path, sheet_name="Claims_Data")
    _workshops_df = pd.read_excel(path, sheet_name="Approved_Workshops")
    _benchmarks_df = pd.read_excel(path, sheet_name="Repair_Benchmarks")


def get_claims() -> pd.DataFrame:
    _load(); return _claims_df

def get_workshops() -> pd.DataFrame:
    _load(); return _workshops_df

def get_benchmarks() -> pd.DataFrame:
    _load(); return _benchmarks_df


# ── Policyholder search (for smart dropdown) ─────────────────────────────────

def search_policyholders(query: str, max_results: int = 10) -> list[dict]:
    """
    Return policyholders whose name OR policy number contains the query string.
    Used by the front-end searchable dropdown.
    """
    df = get_claims()
    query_lc = query.strip().lower()
    if not query_lc:
        return []
    mask = (
        df["Claimant Name"].str.lower().str.contains(query_lc, na=False) |
        df["Claim ID"].str.lower().str.contains(query_lc, na=False) |
        df["Policy Number"].str.lower().str.contains(query_lc, na=False)
    )
    results = df[mask].head(max_results)
    return [
        {
            "claim_id":      row["Claim ID"],
            "name":          row["Claimant Name"],
            "policy_number": row["Policy Number"],
            "vehicle":       row["Vehicle"],
            "label":         f"{row['Claimant Name']} — {row['Claim ID']} — {row['Vehicle']}",
        }
        for _, row in results.iterrows()
    ]


def validate_policyholder(name: str) -> bool:
    """Strict check — name must exist exactly (case-insensitive) in database."""
    df = get_claims()
    return name.strip().lower() in df["Claimant Name"].str.lower().values


def autofill_by_claim_id(claim_id: str) -> dict | None:
    """
    Fetch all policy/vehicle/history fields for a given Claim ID.
    Returns a dict ready to populate the form, or None if not found.
    """
    df = get_claims()
    matches = df[df["Claim ID"].str.strip().str.lower() == claim_id.strip().lower()]
    if matches.empty:
        return None
    row = matches.iloc[0]

    def safe(val):
        if pd.isna(val):
            return ""
        if hasattr(val, "strftime"):
            return str(val)[:10]
        return str(val)

    return {
        "claim_id":              safe(row["Claim ID"]),
        "claimant_name":         safe(row["Claimant Name"]),
        "gender":                safe(row["Gender"]),
        "claimant_phone":        safe(row["Claimant Phone"]),
        "claimant_city":         safe(row["City"]),
        "claimant_state":        safe(row["State"]),
        "dl_number":             safe(row["DL Number"]),
        "rc_number":             safe(row["RC Number"]),
        "policy_number":         safe(row["Policy Number"]),
        "policy_start_date":     safe(row["Policy Start"]),
        "vehicle_name":          safe(row["Vehicle"]),
        "vehicle_segment":       safe(row["Segment"]),
        "vehicle_age_years":     safe(row["Vehicle Age (Yrs)"]),
        "original_purchase_price": safe(row["Purchase Price (₹)"]),
        "current_value":         safe(row["Current Value (₹)"]),
        "accident_date":         safe(row["Accident Date"]),
        "report_date":           safe(row["Report Date"]),
        "claim_type":            safe(row["Claim Type"]),
        "claim_amount":          safe(row["Claim Amount (₹)"]),
        "workshop_name":         safe(row["Workshop Name"]),
        "workshop_contact":      safe(row["WS Contact"]),
        "surveyor_contact":      safe(row["Surveyor Contact"]),
        "injury_claimed":        safe(row["Injury"]),
        "fir_number":            safe(row["FIR Number"]),
        "prior_claims_90d":      safe(row["Claims 90d"]),
        "prior_claims_total":    safe(row["Claims Total"]),
        "past_rejected":         safe(row["Rejected"]),
        "police_report_filed":   safe(row["Police Report"]),
        "tax_invoice_amount":    safe(row["Tax Invoice Amount (₹)"]),
    }


# ── Existing lookups ──────────────────────────────────────────────────────────

def find_claimant_history(name: str) -> pd.DataFrame:
    df = get_claims()
    return df[df["Claimant Name"].str.lower() == name.strip().lower()]


def find_workshop(name: str, threshold: float = 0.75) -> dict | None:
    ws_df = get_workshops()
    exact = ws_df[ws_df["Workshop Name"].str.lower() == name.strip().lower()]
    if not exact.empty:
        return {"found": True, "exact": True, "data": exact.iloc[0].to_dict()}
    best_ratio, best_row = 0, None
    for _, row in ws_df.iterrows():
        r = SequenceMatcher(None, name.lower(), str(row["Workshop Name"]).lower()).ratio()
        if r > best_ratio:
            best_ratio, best_row = r, row
    if best_ratio >= threshold and best_row is not None:
        return {"found": True, "exact": False,
                "match_pct": round(best_ratio * 100, 1), "data": best_row.to_dict()}
    return {"found": False, "exact": False, "data": None}


def get_benchmark(claim_type: str) -> dict | None:
    df = get_benchmarks()
    m = df[df["Claim Type"].str.lower() == claim_type.strip().lower()]
    return m.iloc[0].to_dict() if not m.empty else None


def find_workshop_surveyor_combos(workshop_name: str, surveyor_contact: str) -> int:
    df = get_claims()
    return len(df[
        (df["Workshop Name"].str.lower() == workshop_name.strip().lower()) &
        (df["Surveyor Contact"].astype(str) == str(surveyor_contact))
    ])


def get_tax_invoice_for_claim(claim_id: str) -> float | None:
    df = get_claims()
    m = df[df["Claim ID"].str.strip().str.lower() == claim_id.strip().lower()]
    if m.empty:
        return None
    val = m.iloc[0].get("Tax Invoice Amount (₹)")
    return float(val) if pd.notna(val) else None


def claim_id_exists(claim_id: str) -> bool:
    df = get_claims()
    return claim_id.strip().upper() in df["Claim ID"].str.strip().str.upper().values
