"""
Gemini AI Agent
Handles all LLM-powered tasks via the Gemini 1.5 Flash REST API.

Four jobs:
1. Document Vision Analysis  — extract facts from FIR / invoice PDFs or images
2. Cross-Reference Check     — compare document facts vs claim narrative + history
3. Web Research              — search DuckDuckGo for accident news at the location/date
4. AI Summary Report         — ingest all scores + findings and write plain-English bullet points

All scoring stays in the deterministic Python agents (0-100 scale).
The LLM never outputs a number that feeds the score. It only reasons and writes.
"""

import os
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
import re
import html
from typing import Optional


# ─── Gemini API helpers ───────────────────────────────────────────────────────

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-1.5-flash"


def _get_api_key() -> str:
    key = os.getenv("GOOGLE_API_KEY", "")
    if not key:
        raise ValueError(
            "GOOGLE_API_KEY not set. "
            "Get a free key at https://aistudio.google.com/apikey "
            "and add it to your .env file."
        )
    return key


def _gemini_post(payload: dict) -> dict:
    """POST to Gemini generateContent endpoint and return parsed JSON."""
    api_key = _get_api_key()
    url = f"{GEMINI_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API error {e.code}: {detail[:400]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error reaching Gemini API: {e.reason}") from e


def _extract_text(response: dict) -> str:
    """Pull plain text from Gemini response."""
    try:
        parts = response["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        return ""


def _file_to_base64(path: str) -> tuple[str, str]:
    """Return (base64_data, mime_type) for a file path."""
    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    mime = mime_map.get(ext, "application/octet-stream")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8"), mime


# ─── DuckDuckGo web search (stdlib only) ─────────────────────────────────────

def _duckduckgo_search(query: str, max_results: int = 5) -> list[str]:
    """
    Lightweight DuckDuckGo HTML search via urllib.
    Returns a list of plain-text snippet strings.
    Falls back gracefully if network is blocked.
    """
    try:
        encoded = urllib.parse.urlencode({"q": query, "kl": "in-en"})
        url = f"https://html.duckduckgo.com/html/?{encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")

        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL
        )
        clean = []
        for s in snippets[:max_results]:
            s = re.sub(r"<[^>]+>", "", s)
            s = html.unescape(s).strip()
            if s:
                clean.append(s)
        return clean if clean else ["No results found."]
    except Exception as e:
        return [f"Web search unavailable: {str(e)[:80]}"]


# ─── Task 1: Document Vision Analysis ────────────────────────────────────────

def analyze_document(file_path: str, doc_type: str, claim_context: str) -> dict:
    """
    Send a document (PDF or image) to Gemini Vision for fact extraction.

    doc_type: "FIR" | "Workshop Invoice" | "Survey Report"
    claim_context: brief string describing the claim for context

    Returns:
      {
        "extracted_facts": str,   # bullet-point facts extracted by the LLM
        "raw_text": str,          # full LLM response
        "error": str | None
      }
    """
    if not file_path or not os.path.exists(file_path):
        return {
            "extracted_facts": "",
            "raw_text": "",
            "error": f"File not found: {file_path}",
        }

    try:
        b64_data, mime_type = _file_to_base64(file_path)
    except Exception as e:
        return {"extracted_facts": "", "raw_text": "", "error": str(e)}

    type_instructions = {
        "FIR": (
            "This is a First Information Report (FIR) filed with the police in India. "
            "Extract: (1) Date and time of incident, (2) Location, (3) Parties involved "
            "(names, vehicle numbers), (4) Nature of accident/offence, (5) Injuries reported "
            "(yes/no and severity), (6) Property damage description, (7) FIR number, "
            "(8) Reporting officer name and station, (9) Any witness names mentioned. "
            "If any field is absent in the document, state 'Not mentioned'."
        ),
        "Workshop Invoice": (
            "This is a workshop repair invoice for a motor vehicle claim. "
            "Extract: (1) Workshop name and registration number, (2) Invoice number and date, "
            "(3) Vehicle registration number, (4) Complete parts list with quantity and unit price, "
            "(5) Labour charges, (6) GST/Tax breakdown, (7) Total invoice amount, "
            "(8) Payment status. List every line item separately."
        ),
        "Survey Report": (
            "This is a motor vehicle survey/damage assessment report. "
            "Extract: (1) Surveyor name and license number, (2) Survey date, "
            "(3) Vehicle details (make, model, registration), (4) Damage description "
            "per area (front, rear, sides, engine, interior), (5) Estimated repair cost, "
            "(6) Surveyor's recommendation, (7) Any pre-existing damage noted."
        ),
    }

    instruction = type_instructions.get(
        doc_type,
        "Extract all key facts, figures, dates, and names from this insurance document.",
    )

    prompt = (
        f"You are an insurance forensic analyst examining a {doc_type}.\n"
        f"Claim context: {claim_context}\n\n"
        f"Task: {instruction}\n\n"
        "Format your response as clear numbered bullet points. "
        "Be precise — exact numbers, dates, and names matter for fraud detection."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_data,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1500},
    }

    try:
        resp = _gemini_post(payload)
        raw = _extract_text(resp)
        return {"extracted_facts": raw, "raw_text": raw, "error": None}
    except Exception as e:
        return {"extracted_facts": "", "raw_text": "", "error": str(e)}


# ─── Task 2: Cross-Reference Check ───────────────────────────────────────────

def cross_reference_check(
    claim_narrative: dict,
    document_extractions: dict,
    agent_scores: dict,
    historical_data: dict,
) -> dict:
    """
    LLM acts as an investigator comparing:
    - What the claimant described (narrative)
    - What documents actually say (extractions)
    - What history shows (prior claims, rejections)
    - What deterministic agents flagged (scores)

    Returns:
      {
        "inconsistencies": list[str],
        "consistent_points": list[str],
        "investigator_notes": str,
        "error": str | None
      }
    """
    narrative_str = json.dumps(claim_narrative, indent=2, default=str)
    extractions_str = (
        json.dumps(document_extractions, indent=2, default=str)
        if document_extractions
        else "No documents uploaded."
    )
    scores_str = json.dumps(agent_scores, indent=2, default=str)
    history_str = json.dumps(historical_data, indent=2, default=str)

    prompt = f"""You are a senior motor insurance investigator. Your job is to find logical 
inconsistencies and verify consistency across multiple sources of evidence.

CLAIM NARRATIVE (what the claimant says):
{narrative_str}

EXTRACTED DOCUMENT FACTS (what documents show):
{extractions_str}

HISTORICAL DATA (prior claims, rejections, patterns):
{history_str}

DETERMINISTIC AGENT FLAGS (rule-based checks already run):
{scores_str}

INSTRUCTIONS:
1. Compare the accident description against FIR facts — do they match in date, location, 
   severity, and parties involved?
2. Compare claimed repair amount against workshop invoice line items — is the amount justified?
3. Check if injury claimed matches FIR injury status.
4. Identify any temporal inconsistencies (report dates, accident dates, document dates).
5. Note if the workshop's charges are consistent with the damage described.
6. Flag anything that doesn't add up logically.

Respond with exactly two sections:
INCONSISTENCIES: (numbered list — if none, write "None detected")
CONSISTENT POINTS: (numbered list — things that check out)
INVESTIGATOR NOTES: (2-3 sentences of overall assessment)"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.15, "maxOutputTokens": 1200},
    }

    try:
        resp = _gemini_post(payload)
        raw = _extract_text(resp)

        # Parse sections
        inc_match = re.search(
            r"INCONSISTENCIES:(.*?)(?:CONSISTENT POINTS:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        con_match = re.search(
            r"CONSISTENT POINTS:(.*?)(?:INVESTIGATOR NOTES:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        note_match = re.search(
            r"INVESTIGATOR NOTES:(.*?)$", raw, re.DOTALL | re.IGNORECASE
        )

        def parse_numbered(text: str) -> list[str]:
            if not text:
                return []
            items = re.findall(r"\d+\.\s*(.+?)(?=\d+\.|$)", text.strip(), re.DOTALL)
            clean = [i.strip() for i in items if i.strip() and i.strip().lower() != "none detected"]
            return clean if clean else ["None detected"]

        return {
            "inconsistencies": parse_numbered(inc_match.group(1) if inc_match else ""),
            "consistent_points": parse_numbered(con_match.group(1) if con_match else ""),
            "investigator_notes": note_match.group(1).strip() if note_match else raw[:500],
            "raw_response": raw,
            "error": None,
        }
    except Exception as e:
        return {
            "inconsistencies": [],
            "consistent_points": [],
            "investigator_notes": "",
            "raw_response": "",
            "error": str(e),
        }


# ─── Task 3: Web Research Agent ──────────────────────────────────────────────

def web_research_agent(
    accident_location: str,
    accident_date: str,
    claim_type: str,
    vehicle: str,
) -> dict:
    """
    Search DuckDuckGo for news or traffic reports corroborating the accident.
    Then ask Gemini to assess whether results support or contradict the claim.

    Returns:
      {
        "search_queries": list[str],
        "search_results": list[str],
        "gemini_assessment": str,
        "corroboration_level": "High" | "Medium" | "Low" | "None",
        "error": str | None
      }
    """
    # Build targeted search queries
    queries = [
        f"accident {accident_location} {accident_date} motor vehicle",
        f"road accident news {accident_location} {accident_date}",
        f"{claim_type} accident {accident_location} India {accident_date[:4]}",
    ]

    all_snippets = []
    for q in queries:
        results = _duckduckgo_search(q, max_results=3)
        all_snippets.extend(results)

    snippets_text = "\n".join(f"- {s}" for s in all_snippets[:9]) if all_snippets else "No results."

    prompt = f"""You are a motor insurance investigator using web search results to verify a claim.

CLAIM DETAILS:
- Location: {accident_location}
- Date: {accident_date}
- Claim Type: {claim_type}
- Vehicle: {vehicle}

WEB SEARCH RESULTS:
{snippets_text}

ASSESSMENT TASK:
1. Do any search results mention an accident at this location and approximate date?
2. Does the severity reported online match the claim type?
3. Is there any news suggesting a pattern of fraud or staged accidents in this area?
4. What is your corroboration level? Choose: High (strong match found), Medium (partial match), 
   Low (tangentially related results), None (no relevant results found)

Respond in this format:
CORROBORATION LEVEL: [High/Medium/Low/None]
ASSESSMENT: [3-5 sentences of analysis]"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 600},
    }

    try:
        resp = _gemini_post(payload)
        assessment = _extract_text(resp)

        level_match = re.search(
            r"CORROBORATION LEVEL:\s*(High|Medium|Low|None)", assessment, re.IGNORECASE
        )
        corroboration = level_match.group(1).capitalize() if level_match else "None"

        return {
            "search_queries": queries,
            "search_results": all_snippets[:9],
            "gemini_assessment": assessment,
            "corroboration_level": corroboration,
            "error": None,
        }
    except Exception as e:
        return {
            "search_queries": queries,
            "search_results": all_snippets,
            "gemini_assessment": "",
            "corroboration_level": "None",
            "error": str(e),
        }


# ─── Task 4: AI Summary Report ───────────────────────────────────────────────

def generate_ai_summary(
    claim_data: dict,
    total_score: int,
    verdict: str,
    agent_results: list[dict],
    cross_ref: dict,
    web_research: dict,
    doc_extractions: dict,
) -> dict:
    """
    Ingest all evidence and produce a plain-English AI Summary Report.

    Returns:
      {
        "summary_bullets": list[str],
        "overall_assessment": str,
        "recommended_action": str,
        "confidence": str,   # "High" | "Medium" | "Low"
        "raw_report": str,
        "error": str | None
      }
    """
    # Build comprehensive context for the LLM
    flags_by_agent = []
    for r in agent_results:
        if r.get("flags"):
            for f in r["flags"]:
                agent = r.get("agent_name", "Unknown agent")
                flags_by_agent.append(f"[{agent}] {f}")

    inconsistencies = cross_ref.get("inconsistencies", []) if cross_ref else []
    consistent_pts = cross_ref.get("consistent_points", []) if cross_ref else []
    inv_notes = cross_ref.get("investigator_notes", "") if cross_ref else ""
    web_level = web_research.get("corroboration_level", "None") if web_research else "Not run"
    web_assess = web_research.get("gemini_assessment", "") if web_research else ""

    doc_facts = ""
    if doc_extractions:
        for dtype, facts in doc_extractions.items():
            if facts.get("extracted_facts"):
                doc_facts += f"\n{dtype}: {facts['extracted_facts'][:400]}"

    prompt = f"""You are a senior claims analyst writing an AI Summary Report for a motor insurance claim.
Your report will be read by a claims officer who will make the final decision.

CLAIM REFERENCE: {claim_data.get('claim_id', 'Unknown')}
CLAIMANT: {claim_data.get('claimant_name', 'Unknown')}
CLAIM TYPE: {claim_data.get('claim_type', 'Unknown')}
CLAIM AMOUNT: ₹{claim_data.get('claim_amount', 0):,.0f}

DETERMINISTIC FRAUD SCORE: {total_score}/100 → {verdict}
Score bands: 0-40 Approve | 41-65 Review | 66-85 Investigate | 86-100 Reject

FLAGS RAISED BY DETECTION AGENTS:
{chr(10).join(flags_by_agent) if flags_by_agent else "No flags raised."}

DOCUMENT ANALYSIS RESULTS:
{doc_facts if doc_facts else "No documents uploaded."}

CROSS-REFERENCE FINDINGS:
Inconsistencies: {chr(10).join(inconsistencies) if inconsistencies else "None detected"}
Consistent points: {chr(10).join(consistent_pts) if consistent_pts else "None noted"}
Investigator notes: {inv_notes}

WEB RESEARCH CORROBORATION:
Level: {web_level}
{web_assess[:400] if web_assess else "Not run."}

INSTRUCTIONS:
Write a professional AI Summary Report with these exact sections:

SUMMARY BULLETS:
(Write 4-8 plain-English bullet points. Each bullet should explain ONE finding in simple language 
that a non-technical claims officer can understand. Be specific — cite amounts, dates, percentages.)

OVERALL ASSESSMENT:
(2-3 sentences. State clearly whether this claim appears legitimate, suspicious, or fraudulent, 
and what the primary driver of that conclusion is.)

RECOMMENDED ACTION:
(One clear sentence: what the claims officer should do next.)

CONFIDENCE LEVEL: [High/Medium/Low]
(One sentence explaining why.)"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1800},
    }

    try:
        resp = _gemini_post(payload)
        raw = _extract_text(resp)

        # Parse sections
        bullets_match = re.search(
            r"SUMMARY BULLETS:(.*?)(?:OVERALL ASSESSMENT:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        assess_match = re.search(
            r"OVERALL ASSESSMENT:(.*?)(?:RECOMMENDED ACTION:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        action_match = re.search(
            r"RECOMMENDED ACTION:(.*?)(?:CONFIDENCE LEVEL:|$)", raw, re.DOTALL | re.IGNORECASE
        )
        conf_match = re.search(
            r"CONFIDENCE LEVEL:\s*(High|Medium|Low)", raw, re.IGNORECASE
        )

        def parse_bullets(text: str) -> list[str]:
            if not text:
                return []
            lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
            bullets = []
            for line in lines:
                line = re.sub(r"^[\-\*\•\d\.\)]\s*", "", line).strip()
                if line:
                    bullets.append(line)
            return bullets

        return {
            "summary_bullets": parse_bullets(bullets_match.group(1) if bullets_match else raw),
            "overall_assessment": assess_match.group(1).strip() if assess_match else "",
            "recommended_action": action_match.group(1).strip() if action_match else "",
            "confidence": conf_match.group(1).capitalize() if conf_match else "Medium",
            "raw_report": raw,
            "error": None,
        }
    except Exception as e:
        return {
            "summary_bullets": [f"AI Summary unavailable: {str(e)[:120]}"],
            "overall_assessment": "",
            "recommended_action": "",
            "confidence": "Low",
            "raw_report": "",
            "error": str(e),
        }
