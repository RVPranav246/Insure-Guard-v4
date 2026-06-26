"""
Agent 1 — History Lookup
Searches Excel for claimant's prior claim history.
"""
from core.data_loader import find_claimant_history
from datetime import datetime, timedelta


def run(claim: dict) -> dict:
    name = claim.get("claimant_name", "")
    accident_date_str = claim.get("accident_date", "")

    result = {"agent": "History Lookup", "points": 0, "flags": [],
              "details": {}, "summary": ""}

    history = find_claimant_history(name)

    if history.empty:
        result["details"] = {"prior_claims_90d": 0, "prior_claims_total": 0,
                              "past_rejected": 0, "status": "New claimant"}
        result["summary"] = f"No prior records found for '{name}'. First-time claimant."
        return result

    total_claims = len(history)

    # Count claims in last 90 days
    claims_90d = 0
    if accident_date_str:
        try:
            acc_date = datetime.strptime(accident_date_str, "%Y-%m-%d")
            cutoff = acc_date - timedelta(days=90)
            date_col = "Accident Date" if "Accident Date" in history.columns else "accident_date"
            for _, row in history.iterrows():
                row_date = row.get(date_col)
                if row_date and str(row_date) != "nan":
                    try:
                        rd = datetime.strptime(str(row_date)[:10], "%Y-%m-%d")
                        if cutoff <= rd <= acc_date:
                            claims_90d += 1
                    except (ValueError, TypeError):
                        pass
        except (ValueError, TypeError):
            pass

    # Past rejections
    rej_col = "Past Rejected Claims" if "Past Rejected Claims" in history.columns else "past_rejected_claims"
    past_rejected = 0
    if rej_col in history.columns:
        past_rejected = int(history[rej_col].max()) if not history[rej_col].isna().all() else 0

    # Scoring
    pts = 0
    flags = []

    if claims_90d >= 3:
        pts += 35
        flags.append(f"CRITICAL: {claims_90d} claims in last 90 days (Rule 3 — auto-flag)")
    elif claims_90d >= 2:
        pts += 25
        flags.append(f"HIGH: {claims_90d} claims in last 90 days (Rule 3 — auto-flag)")
    elif claims_90d == 1:
        pts += 10
        flags.append(f"ELEVATED: 1 prior claim in last 90 days")

    rej_pts = min(past_rejected * 5, 15)
    if rej_pts > 0:
        pts += rej_pts
        flags.append(f"{past_rejected} past rejected claim(s) — +{rej_pts} pts")

    result["points"] = pts
    result["flags"] = flags
    result["details"] = {
        "prior_claims_90d": claims_90d,
        "prior_claims_total": total_claims,
        "past_rejected": past_rejected,
        "status": "Existing claimant",
    }
    result["summary"] = (
        f"Found {total_claims} prior claim(s) for '{name}'. "
        f"{claims_90d} in last 90 days. {past_rejected} past rejection(s). "
        f"Score: +{pts} pts."
    )
    result["override_review"] = claims_90d >= 2
    return result
