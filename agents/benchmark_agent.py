"""
Agent 3 — Amount Benchmark
Compares claim amount against industry repair benchmark.
Also checks report delay + police report rule.
"""
from core.data_loader import get_benchmark
from datetime import datetime


def _depreciated_value(purchase_price: float, age_years: int) -> float:
    return purchase_price * (0.95 ** age_years)


def run(claim: dict) -> dict:
    claim_amount = float(claim.get("claim_amount", 0))
    claim_type = claim.get("claim_type", "")
    purchase_price = float(claim.get("original_purchase_price", 0))
    vehicle_age = int(claim.get("vehicle_age_years", 0))
    accident_date_str = claim.get("accident_date", "")
    report_date_str = claim.get("report_date", "")
    police_report = str(claim.get("police_report_filed", "N/A")).lower()

    result = {"agent": "Amount Benchmark", "points": 0, "flags": [],
              "details": {}, "summary": ""}

    # Current vehicle value
    current_value = _depreciated_value(purchase_price, vehicle_age) if purchase_price > 0 else 0

    # Get benchmark
    bm_data = get_benchmark(claim_type)
    if bm_data is None:
        result["points"] = 5
        result["flags"] = [f"Unknown claim type: '{claim_type}'"]
        result["details"] = {"claim_type_found": False}
        result["summary"] = f"Claim type '{claim_type}' not in benchmark table. +5 pts."
        return result

    benchmark = float(bm_data.get("Benchmark Value (₹)", bm_data.get("benchmark", 0)))

    # For theft/total loss, benchmark = current vehicle value
    if claim_type.lower() in ["theft/total loss", "theft / total loss"]:
        benchmark = current_value if current_value > 0 else benchmark

    if benchmark <= 0:
        result["points"] = 5
        result["flags"] = ["Benchmark is zero — cannot calculate ratio"]
        result["summary"] = "Benchmark value is zero. Cannot perform comparison. +5 pts."
        return result

    claim_pct = (claim_amount / benchmark) * 100
    pts = 0
    flags = []
    override_reject = False

    # Rule 1: >140% = auto-reject
    if claim_pct > 140:
        pts += 30
        override_reject = True
        flags.append(
            f"CRITICAL: Claim is {claim_pct:.1f}% of benchmark "
            f"(₹{claim_amount:,.0f} vs ₹{benchmark:,.0f}) — Rule 1 AUTO-REJECT"
        )
    # Rule 2: 90–140% = flag
    elif claim_pct > 90:
        pts += 15
        flags.append(
            f"ELEVATED: Claim is {claim_pct:.1f}% of benchmark "
            f"(₹{claim_amount:,.0f} vs ₹{benchmark:,.0f}) — Rule 2 FLAG"
        )
    elif claim_pct > 60:
        pts += 5
        flags.append(f"Claim is {claim_pct:.1f}% of benchmark — within expected range")

    # Rule 7: report delay >30 days + no police report
    report_delay = 0
    if accident_date_str and report_date_str:
        try:
            acc = datetime.strptime(accident_date_str, "%Y-%m-%d")
            rep = datetime.strptime(report_date_str, "%Y-%m-%d")
            report_delay = (rep - acc).days
        except (ValueError, TypeError):
            pass

    if report_delay > 30 and police_report not in ["yes", "y", "true", "1"]:
        pts += 20
        flags.append(
            f"Report delay {report_delay} days + no police report — Rule 7 (+20 pts)"
        )

    result["points"] = pts
    result["flags"] = flags
    result["override_reject"] = override_reject
    result["details"] = {
        "claim_amount": claim_amount,
        "benchmark_value": benchmark,
        "claim_to_benchmark_pct": round(claim_pct, 1),
        "current_vehicle_value": round(current_value),
        "depreciation_formula": f"₹{purchase_price:,.0f} × 0.95^{vehicle_age}",
        "report_delay_days": report_delay,
        "police_report": police_report,
    }
    result["summary"] = (
        f"Claim ₹{claim_amount:,.0f} is {claim_pct:.1f}% of benchmark ₹{benchmark:,.0f}. "
        f"Vehicle value: ₹{current_value:,.0f} (₹{purchase_price:,.0f} × 0.95^{vehicle_age}). "
        f"Report delay: {report_delay} days. Score: +{pts} pts."
    )
    return result
