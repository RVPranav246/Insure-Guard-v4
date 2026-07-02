"""
Orchestrator — runs all 6 deterministic agents, then 4 Gemini AI tasks.
Yields SSE events for real-time streaming to the frontend.
"""
from core.ml_model import predict_fraud
import os
from core.scorer import FraudScorer
from agents import (history_agent, workshop_agent, benchmark_agent,
                     document_agent, nexus_agent, discrepancy_agent)
from core.gemini_agent import (
    analyze_document,
    cross_reference_check,
    generate_ai_summary,
)

AGENTS = [
    ("History Lookup",    history_agent),
    ("Workshop Validator", workshop_agent),
    ("Amount Benchmark",   benchmark_agent),
    ("Document Verifier",  document_agent),
    ("Nexus Detector",     nexus_agent),
    ("Bill Discrepancy",   discrepancy_agent),
]


def assess_claim(claim: dict, uploaded_files: dict | None = None):
    """
    Generator that yields dicts for SSE.

    Phase 1: 6 deterministic agents → score
    Phase 2: Gemini document analysis (if files uploaded)
    Phase 3: Gemini cross-reference check
    Phase 4: Gemini web research
    Phase 5: Gemini AI summary report
    """
    scorer = FraudScorer()
    halted = False
    agent_results = []
    uploaded_files = uploaded_files or {}

    # ── Phase 1: Deterministic agents ──────────────────────────────────────
    for i, (name, module) in enumerate(AGENTS):
        result = module.run(claim)
        pts   = result.get("points", 0)
        flags = result.get("flags", [])
        scorer.add(name, pts, flags)

        if result.get("override_reject"):
            scorer.set_override_reject(f"{name}: auto-reject")
        if result.get("override_review"):
            scorer.set_override_review(f"{name}: auto-review")
        if result.get("halt"):
            halted = True

        result["agent_name"] = name
        agent_results.append(result)

        yield {
            "type":          "agent_result",
            "agent_index":   i,
            "agent_name":    name,
            "agent_count":   len(AGENTS),
            "points":        pts,
            "running_total": scorer.total,
            "flags":         flags,
            "details":       result.get("details", {}),
            "summary":       result.get("summary", ""),
            "halted":        halted,
        }

    final_score   = scorer.total
    verdict_data  = scorer.verdict
    agent_summary = scorer.summary()

    # ── Phase 2: Document Analysis ─────────────────────────────────────────
    doc_extractions = {}
    claim_type = claim.get("claim_type", "")
    is_third_party = "third party" in claim_type.lower()

    # FIR — compulsory for Third Party Liability
    fir_path = uploaded_files.get("fir_document", "")
    if is_third_party and not fir_path:
        yield {
            "type":    "ai_task",
            "task":    "Document Analysis",
            "status":  "warning",
            "message": "FIR document is compulsory for Third Party Liability claims but was not uploaded.",
            "data":    {},
        }
    elif fir_path and os.path.exists(fir_path):
        yield {"type": "ai_task", "task": "Document Analysis", "status": "running",
               "message": "Analyzing FIR with Gemini Vision...", "data": {}}
        ctx = f"{claim.get('claimant_name','?')} accident on {claim.get('accident_date','?')} at {claim.get('accident_location', claim.get('claimant_city','?'))}"
        result = analyze_document(fir_path, "FIR", ctx)
        doc_extractions["FIR"] = result
        yield {
            "type":    "ai_task",
            "task":    "Document Analysis — FIR",
            "status":  "error" if result.get("error") else "complete",
            "message": result.get("error") or "FIR analyzed successfully.",
            "data":    {"extracted_facts": result.get("extracted_facts", "")},
        }

    # Workshop invoice — optional
    invoice_path = uploaded_files.get("workshop_invoice", "")
    if invoice_path and os.path.exists(invoice_path):
        yield {"type": "ai_task", "task": "Document Analysis", "status": "running",
               "message": "Analyzing Workshop Invoice with Gemini Vision...", "data": {}}
        ctx = f"Claim amount ₹{claim.get('claim_amount',0):,.0f}, vehicle {claim.get('vehicle_name','?')}"
        result = analyze_document(invoice_path, "Workshop Invoice", ctx)
        doc_extractions["Workshop Invoice"] = result
        yield {
            "type":    "ai_task",
            "task":    "Document Analysis — Invoice",
            "status":  "error" if result.get("error") else "complete",
            "message": result.get("error") or "Invoice analyzed successfully.",
            "data":    {"extracted_facts": result.get("extracted_facts", "")},
        }

    # ── Phase 3: Cross-Reference ────────────────────────────────────────────
    yield {"type": "ai_task", "task": "Cross-Reference Check", "status": "running",
           "message": "Gemini comparing documents vs narrative vs history...", "data": {}}

    history_df  = __import__("core.data_loader", fromlist=["find_claimant_history"]).find_claimant_history(
        claim.get("claimant_name", "")
    )
    historical = {
        "prior_claims_total": int(claim.get("prior_claims_total", 0)),
        "prior_claims_90d":   int(claim.get("prior_claims_90d", 0)),
        "past_rejected":      int(claim.get("past_rejected", 0)),
    }
    cross_ref = cross_reference_check(claim, doc_extractions, agent_summary["agent_scores"], historical)

    # 1. Setup safe defaults
    final_status = "complete"
    final_message = "Cross-reference analysis generated successfully."
    final_inconsistencies = []
    final_consistent = []
    final_notes = ""

        # 2. Bulletproof Type-Checking
    if isinstance(cross_ref, dict):
        if cross_ref.get("error"):
                final_status = "error"
                final_message = cross_ref.get("error")
        else:
                final_inconsistencies = cross_ref.get("inconsistencies", [])
                final_consistent = cross_ref.get("consistent_points", [])
                final_notes = cross_ref.get("investigator_notes", "")
                
    elif isinstance(cross_ref, str):
            # If the AI returns plain text, safely assign it to inconsistencies so the UI can display it
            final_inconsistencies = [cross_ref]
            final_notes = cross_ref
            
    else:
            final_inconsistencies = [str(cross_ref)]

        # 3. Safely yield the exact dictionary structure your app expects
    yield {
            "type":    "ai_task",
            "task":    "Cross-Reference Check",
            "status":  final_status,
            "message": final_message,
            "data":    {
                "inconsistencies":    final_inconsistencies,
                "consistent_points":  final_consistent,
                "investigator_notes": final_notes,
            },
        }

      # ── ML Prediction ──────────────────────────────────────────────────────
    ml_result = predict_fraud(claim)
    yield {
        "type":    "ai_task",
        "task":    "ML Fraud Prediction",
        "status":  "complete",
        "message": f"LightGBM confidence: {ml_result['ml_probability']*100:.1f}%",
        "data":    ml_result,
    }

    
    # ── Phase 5: AI Summary Report ──────────────────────────────────────────
    yield {"type": "ai_task", "task": "AI Summary Report", "status": "running",
           "message": "Generating executive AI summary...", "data": {}}

    summary = generate_ai_summary(
        claim_data=claim,
        total_score=final_score,
        verdict=verdict_data["verdict"],
        agent_results=agent_results,
        cross_ref=cross_ref,
        web_research="Web research module disabled.",   # ← web_res removed
        doc_extractions=doc_extractions,
    )

    # Bulletproof type-check — summary can be dict, str, or anything else
    if isinstance(summary, dict):
        summary_status  = "error" if summary.get("error") else "complete"
        summary_message = summary.get("error") or "AI Summary Report generated successfully."
        summary_payload = summary
    else:
        summary_status  = "complete"
        summary_message = "AI Summary Report generated successfully."
        summary_payload = {
            "summary_bullets":    [str(summary)],
            "overall_assessment": str(summary),
            "recommended_action": "Review full AI output above.",
            "confidence":         "Medium",
            "raw_report":         str(summary),
            "error":              None,
        }

    yield {
        "type":    "ai_task",
        "task":    "AI Summary Report",
        "status":  summary_status,
        "message": summary_message,
        "data":    summary_payload,
    }

    # ── Final verdict ────────────────────────────────────────────────────────
    yield {
        "type":            "verdict",
        "total_score":     final_score,
        "verdict":         verdict_data["verdict"],
        "level":           verdict_data["level"],
        "band_color":      verdict_data["band_color"],
        "action":          verdict_data["action"],
        "flags":           agent_summary["flags"],
        "agent_scores":    agent_summary["agent_scores"],
        "halted":          halted,
        "halt_message":    "Estimation bill halted — Held for Review." if halted else "",
        "ai_summary":      summary_payload,
        "cross_ref":       cross_ref,
        "web_research":    "Web research module disabled.",   # ← web_res removed
        "doc_extractions": doc_extractions,
    }