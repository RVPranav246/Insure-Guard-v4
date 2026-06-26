"""
Agent 5 — Nexus Detector
Detects shared contact details between claimant, workshop, and surveyor.
Also checks historical workshop-surveyor combos.
"""
from core.data_loader import find_workshop_surveyor_combos


def run(claim: dict) -> dict:
    claimant_phone = str(claim.get("claimant_phone", "")).strip()
    workshop_contact = str(claim.get("workshop_contact", "")).strip()
    surveyor_contact = str(claim.get("surveyor_contact", "")).strip()
    workshop_name = claim.get("workshop_name", "")

    result = {"agent": "Nexus Detector", "points": 0, "flags": [],
              "details": {}, "summary": ""}

    pts = 0
    flags = []
    overlaps = []

    # Rule 6: any two share contact
    contacts = {
        "claimant": claimant_phone,
        "workshop": workshop_contact,
        "surveyor": surveyor_contact,
    }

    checked_pairs = []
    for role_a, phone_a in contacts.items():
        for role_b, phone_b in contacts.items():
            if role_a >= role_b:
                continue
            pair = f"{role_a}-{role_b}"
            if phone_a and phone_b and phone_a == phone_b:
                pts += 50
                overlaps.append(pair)
                flags.append(
                    f"CRITICAL: {role_a} and {role_b} share phone {phone_a} "
                    f"(Rule 6 — +50 pts)"
                )
            checked_pairs.append({"pair": pair, "match": phone_a == phone_b if phone_a and phone_b else False})

    # Historical combo check
    combo_count = 0
    if workshop_name and surveyor_contact:
        combo_count = find_workshop_surveyor_combos(workshop_name, surveyor_contact)
        if combo_count >= 3:
            pts += 15
            flags.append(
                f"Workshop-surveyor combo seen in {combo_count} past claims (+15 pts)"
            )

    result["points"] = min(pts, 65)
    result["flags"] = flags
    result["details"] = {
        "contacts_compared": contacts,
        "overlaps_found": overlaps,
        "pairs_checked": checked_pairs,
        "workshop_surveyor_combo_count": combo_count,
    }
    result["summary"] = (
        f"Contact check: {len(overlaps)} overlap(s) detected. "
        f"Historical combo: {combo_count} past matches. "
        f"Score: +{min(pts, 65)} pts."
    )
    return result
