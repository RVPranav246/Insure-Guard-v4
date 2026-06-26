"""
Agent 2 — Workshop Validator
Checks if the workshop is on the insurer's approved list.
"""
from core.data_loader import find_workshop


def run(claim: dict) -> dict:
    ws_name = claim.get("workshop_name", "")

    result = {"agent": "Workshop Validator", "points": 0, "flags": [],
              "details": {}, "summary": ""}

    if not ws_name:
        result["points"] = 10
        result["flags"] = ["No workshop name provided"]
        result["summary"] = "Workshop name missing from claim. +10 pts."
        return result

    lookup = find_workshop(ws_name)

    if lookup["found"]:
        data = lookup["data"]
        fraud_rate = float(data.get("Fraud Rate (%)", data.get("fraud_rate_pct", 0)))
        approved = str(data.get("Insurer Approved", data.get("insurer_approved", "No")))
        matched_name = data.get("Workshop Name", data.get("workshop_name", ws_name))

        pts = 0
        flags = []

        if approved.lower() != "yes":
            pts += 25
            flags.append(f"Workshop '{matched_name}' NOT on approved list (Rule 5 — +25 pts)")
        elif fraud_rate > 15:
            pts += 10
            flags.append(f"Approved but high fraud rate: {fraud_rate}%")
        elif fraud_rate > 8:
            pts += 5
            flags.append(f"Approved with elevated fraud rate: {fraud_rate}%")

        match_note = ""
        if not lookup["exact"]:
            match_note = f" (fuzzy match {lookup['match_pct']}% to '{matched_name}')"

        result["points"] = pts
        result["flags"] = flags
        result["details"] = {
            "workshop_found": True,
            "matched_name": matched_name,
            "exact_match": lookup["exact"],
            "insurer_approved": approved,
            "fraud_rate_pct": fraud_rate,
            "registration": data.get("Registration Status", data.get("registration", "Unknown")),
        }
        result["summary"] = (
            f"Workshop '{ws_name}'{match_note}: "
            f"Approved={approved}, Fraud rate={fraud_rate}%. "
            f"Score: +{pts} pts."
        )
    else:
        result["points"] = 25
        result["flags"] = [f"Workshop '{ws_name}' NOT found in approved list (Rule 5 — +25 pts)"]
        result["details"] = {
            "workshop_found": False,
            "matched_name": None,
            "insurer_approved": "No",
        }
        result["summary"] = f"Workshop '{ws_name}' not found in approved list. +25 pts."

    return result
