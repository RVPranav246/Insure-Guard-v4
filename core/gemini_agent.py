"""
Gemini AI Agent — InsureGuard v4
Uses the modern google-genai SDK (compatible with AQ. keys).
Web research removed.
Retry logic: 2.5-flash → 2.0-flash → 1.5-flash with quota-aware delays.
"""

import os
import json
import base64
import time
import re
from typing import Optional
from dotenv import load_dotenv
from google import genai

load_dotenv(override=True)

# ── Client & Model Config ────────────────────────────────────────────────────

MODEL_PRIMARY  = "gemini-2.5-flash"
MODEL_FALLBACK = "gemini-2.0-flash"
MODEL_LAST     = "gemini-1.5-flash"


def _get_client() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if not key:
        raise ValueError("GEMINI_API_KEY not set in your .env file.")
    return genai.Client(api_key=key)


def _parse_retry_delay(err_str: str) -> float:
    """Extract retry delay in seconds from Google's 429 error message."""
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
    return float(m.group(1)) if m else 20.0


def _generate_with_retry(contents, max_retries: int = 3) -> str:
    """
    Tries MODEL_PRIMARY first with retries.
    On quota exhaustion (429) or unavailability (503), moves to next model.
    Falls through: gemini-2.5-flash → gemini-2.0-flash → gemini-1.5-flash.
    Respects Google's retry delay from the error message on 429s.
    """
    client = _get_client()
    models = [MODEL_PRIMARY, MODEL_FALLBACK, MODEL_LAST]

    for model in models:
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents
                )
                return response.text
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    delay = _parse_retry_delay(err)
                    print(f"[InsureGuard] 429 on {model} attempt {attempt + 1}, waiting {delay:.0f}s...")
                    time.sleep(delay)
                elif "503" in err or "UNAVAILABLE" in err:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    print(f"[InsureGuard] 503 on {model} attempt {attempt + 1}, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    # Non-transient error — skip retries, try next model
                    print(f"[InsureGuard] Non-transient error on {model}: {err[:80]}")
                    break

        print(f"[InsureGuard] {model} exhausted, trying next model...")

    raise RuntimeError(
        "All models exhausted. Check your quota at https://ai.dev/rate-limit"
    )


# ── Job 1: Document Vision Analysis ─────────────────────────────────────────

def analyze_document(file_path: str, doc_type: str, claim_context: Optional[dict] = None) -> dict:
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}

    mime_type = "application/pdf"
    if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        ext = os.path.splitext(file_path.lower())[1]
        mime_type = f"image/{ext[1:]}" if ext != ".jpg" else "image/jpeg"

    b64_data = base64.b64encode(file_bytes).decode("utf-8")

    context_hint = ""
    if claim_context:
        context_hint = f"\n\nCLAIM CONTEXT FOR CROSS-CHECKING:\n{json.dumps(claim_context, indent=2)}"

    if doc_type.lower() == "fir":
        prompt = (
            "You are an expert insurance document analyzer. Extract from this FIR:\n"
            "1. FIR Number  2. Date of Accident  3. Vehicle Number  4. Narrative.\n"
            "Respond ONLY in raw JSON:\n"
            '{"fir_number":"string","accident_date":"YYYY-MM-DD",'
            '"vehicle_number":"string","narrative":"string"}'
            + context_hint
        )
    else:
        prompt = (
            "You are an expert invoice examiner. Extract from this Tax Invoice:\n"
            "1. Invoice Number  2. Invoice Date  3. Total Amount  4. Parts replaced.\n"
            "Respond ONLY in raw JSON:\n"
            '{"invoice_number":"string","invoice_date":"YYYY-MM-DD",'
            '"total_amount":0.0,"parts_replaced":["string"]}'
            + context_hint
        )

    try:
        raw = _generate_with_retry([
            {
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": b64_data}},
                    {"text": prompt}
                ]
            }
        ]).strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "JSON parse failed", "raw": raw}
    except Exception as e:
        return {"error": f"Document analysis failed: {str(e)}"}


# ── Job 2: Cross-Reference Check ─────────────────────────────────────────────

def cross_reference_check(
    claim_narrative: str,
    doc_extractions: dict,
    agent_scores: Optional[dict] = None,
    historical_data: Optional[dict] = None
) -> str:
    prompt = f"""
You are an expert insurance fraud investigator.
Compare the policyholder's statement against the official document records and flag any conflict.

POLICYHOLDER STATEMENT:
{claim_narrative}

EXTRACTED DOCUMENT RECORDS:
{json.dumps(doc_extractions, indent=2)}

DETERMINISTIC AGENT SCORES:
{json.dumps(agent_scores or {}, indent=2)}

HISTORICAL DATA:
{json.dumps(historical_data or {}, indent=2)}

Respond in clear bullet points covering:
1. Vehicle number or date mismatches
2. Damage description conflicts
3. Any inconsistency between scores and narrative
4. What checks out correctly
Be objective and concise.
"""
    try:
        return _generate_with_retry(prompt)
    except Exception as e:
        return f"Cross-Reference check failed: {str(e)}"


# ── Job 3: AI Summary Report ─────────────────────────────────────────────────

def generate_ai_summary(
    claim_data: dict,
    total_score: int,
    verdict: str,
    agent_results: list,
    cross_ref: str,
    web_research: str,
    doc_extractions: dict
) -> dict:
    prompt = f"""
You are the head AI fraud analyst for InsureGuard AI.
Generate a structured executive fraud assessment.

CLAIM DETAILS:
{json.dumps(claim_data, indent=2)}

DETERMINISTIC AGENT SCORES:
{json.dumps(agent_results, indent=2)}

TOTAL FRAUD SUSPICION SCORE: {total_score} / 100
PRELIMINARY VERDICT: {verdict}

CROSS-REFERENCE AUDIT:
{cross_ref}

DOCUMENT VERIFICATION:
{json.dumps(doc_extractions, indent=2)}

Respond using EXACTLY these section headers:

SUMMARY BULLETS:
- [3-4 high-impact findings about risk or legitimacy]

OVERALL ASSESSMENT:
[2-3 sentences explaining why this claim received its score]

RECOMMENDED ACTION:
[Explicit next steps for the claims adjuster]

CONFIDENCE LEVEL:
[High / Medium / Low]
"""
    try:
        raw = _generate_with_retry(prompt)

        def extract(pattern, text):
            m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return m.group(1).strip() if m else ""

        def parse_bullets(text: str) -> list:
            if not text:
                return []
            lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
            return [re.sub(r"^[\-\*\•\d\.\)]\s*", "", l).strip() for l in lines if l]

        bullets_raw = extract(r"SUMMARY BULLETS:(.*?)(?:OVERALL ASSESSMENT:|$)", raw)
        assess_raw  = extract(r"OVERALL ASSESSMENT:(.*?)(?:RECOMMENDED ACTION:|$)", raw)
        action_raw  = extract(r"RECOMMENDED ACTION:(.*?)(?:CONFIDENCE LEVEL:|$)", raw)
        conf_match  = re.search(r"CONFIDENCE LEVEL:\s*(High|Medium|Low)", raw, re.IGNORECASE)

        return {
            "summary_bullets":    parse_bullets(bullets_raw) or parse_bullets(raw),
            "overall_assessment": assess_raw,
            "recommended_action": action_raw,
            "confidence":         conf_match.group(1).capitalize() if conf_match else "Medium",
            "raw_report":         raw,
            "error":              None,
        }

    except Exception as e:
        return {
            "summary_bullets":    [f"AI Summary failed: {str(e)}"],
            "overall_assessment": "",
            "recommended_action": "",
            "confidence":         "Medium",
            "raw_report":         "",
            "error":              str(e),
        }
