"""
Agent 6 — Fraud & Discrepancy Detection
Compares the user-input Estimation Bill against the Tax Invoice from Excel.
If estimation is abnormally higher than tax invoice → halt and flag.
"""
from core.data_loader import get_tax_invoice_for_claim


def run(claim: dict) -> dict:
    claim_id = claim.get("claim_id", "")
    estimation_bill = float(claim.get("estimation_bill", 0))

    result = {"agent": "Bill Discrepancy", "points": 0, "flags": [],
              "details": {}, "summary": "", "halt": False}

    if estimation_bill <= 0:
        result["details"] = {"status": "No estimation bill provided"}
        result["summary"] = "No estimation bill amount provided. Skipped."
        return result

    # Get tax invoice from Excel
    tax_invoice = get_tax_invoice_for_claim(claim_id)

    if tax_invoice is None:
        result["details"] = {
            "status": "No matching tax invoice in records",
            "estimation_bill": estimation_bill,
        }
        result["points"] = 5
        result["flags"] = [f"No tax invoice found for {claim_id} — cannot cross-verify"]
        result["summary"] = f"No tax invoice in records for '{claim_id}'. +5 pts."
        return result

    if tax_invoice <= 0:
        result["points"] = 5
        result["flags"] = ["Tax invoice is ₹0 — data anomaly"]
        result["summary"] = "Tax invoice is zero. Cannot compute variance. +5 pts."
        return result

    # Calculate variance
    variance = estimation_bill - tax_invoice
    variance_pct = (variance / tax_invoice) * 100

    pts = 0
    flags = []
    halt = False

    if variance_pct > 50:
        # Estimation is >50% higher than tax invoice — HALT
        pts += 40
        halt = True
        flags.append(
            f"HALT — Estimation ₹{estimation_bill:,.0f} is {variance_pct:.1f}% ABOVE "
            f"tax invoice ₹{tax_invoice:,.0f}. Variance: ₹{variance:,.0f}. "
            f"Claim processing HALTED — Held for Review."
        )
    elif variance_pct > 30:
        pts += 25
        flags.append(
            f"HIGH: Estimation {variance_pct:.1f}% above tax invoice. "
            f"Variance: ₹{variance:,.0f}"
        )
    elif variance_pct > 15:
        pts += 10
        flags.append(
            f"ELEVATED: Estimation {variance_pct:.1f}% above tax invoice. "
            f"Variance: ₹{variance:,.0f}"
        )
    elif variance_pct > 5:
        pts += 3
        flags.append(f"Minor variance: {variance_pct:.1f}% above tax invoice")
    elif variance_pct < -10:
        # Estimation LOWER than invoice — unusual but not fraud
        flags.append(
            f"NOTE: Estimation is {abs(variance_pct):.1f}% BELOW tax invoice "
            f"(unusual — workshop underquoted?)"
        )

    result["points"] = pts
    result["flags"] = flags
    result["halt"] = halt
    result["details"] = {
        "estimation_bill": estimation_bill,
        "tax_invoice": tax_invoice,
        "variance_amount": round(variance),
        "variance_pct": round(variance_pct, 1),
        "status": "HALTED — Held for Review" if halt else "Processed",
    }
    result["summary"] = (
        f"Estimation: ₹{estimation_bill:,.0f} vs Tax Invoice: ₹{tax_invoice:,.0f}. "
        f"Variance: {variance_pct:+.1f}% (₹{variance:,.0f}). "
        + ("CLAIM HALTED. " if halt else "")
        + f"Score: +{pts} pts."
    )
    return result
