"""
Flask backend — InsureGuard AI v4.0
Adds: policyholder search/autofill, document upload, AI summary report streaming.
"""
import os, sys, json
from flask import (Flask, render_template, request, jsonify,
                   Response, stream_with_context)
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from core.orchestrator import assess_claim
from core.data_loader import (
    search_policyholders, validate_policyholder,
    autofill_by_claim_id, get_benchmarks, claim_id_exists,
    get_tax_invoice_for_claim,
)

app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(__file__), "templates"),
            static_folder=os.path.join(os.path.dirname(__file__), "static"))
app.config["SECRET_KEY"] = "insure-guard-2026"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


def allowed_file(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in ALLOWED_EXT


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search-policyholders")
def search_policyholders_route():
    """Typeahead search for policyholder name/ID. Returns list for dropdown."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    results = search_policyholders(q, max_results=8)
    return jsonify(results)


@app.route("/api/autofill/<claim_id>")
def autofill(claim_id: str):
    """Return all fields for a claim ID to autofill the form."""
    data = autofill_by_claim_id(claim_id)
    if data is None:
        return jsonify({"error": "Claim ID not found"}), 404
    return jsonify(data)


@app.route("/api/claim-types")
def claim_types():
    try:
        df = get_benchmarks()
        return jsonify(df["Claim Type"].tolist())
    except Exception:
        return jsonify(["Minor Scratch/Dent", "Moderate Collision", "Major Accident",
                        "Windshield/Glass", "Theft/Total Loss", "Natural Disaster",
                        "Third Party Liability", "Fire Damage"])


@app.route("/api/check-claim-id")
def check_claim_id():
    cid = request.args.get("id", "")
    exists = claim_id_exists(cid)
    tax_inv = get_tax_invoice_for_claim(cid) if exists else None
    return jsonify({"exists": exists, "tax_invoice": tax_inv})


@app.route("/api/upload-document", methods=["POST"])
def upload_document():
    """Upload FIR or workshop invoice. Returns saved file path."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    doc_type = request.form.get("doc_type", "document")  # "fir_document" | "workshop_invoice"
    if not f.filename:
        return jsonify({"error": "No filename"}), 400
    if not allowed_file(f.filename):
        return jsonify({"error": f"File type not allowed. Use: {', '.join(ALLOWED_EXT)}"}), 400

    import uuid
    ext = os.path.splitext(f.filename)[1].lower()
    safe_name = f"{doc_type}_{uuid.uuid4().hex[:8]}{ext}"
    save_path = os.path.join(UPLOAD_FOLDER, safe_name)
    f.save(save_path)
    return jsonify({"path": save_path, "filename": f.filename, "doc_type": doc_type})


@app.route("/api/assess", methods=["POST"])
def assess():
    try:
        data = request.json or {}

        # ── Strict policyholder validation ────────────────────────────────
        name = data.get("claimant_name", "").strip()
        if not name:
            return jsonify({"error": "Claimant name is required."}), 400
        if not validate_policyholder(name):
            return jsonify({
                "error": f"Invalid Policyholder: '{name}' was not found in the database. "
                         f"Please select a valid name from the dropdown suggestions."
            }), 422

        # ── Required fields ───────────────────────────────────────────────
        required = ["claim_id", "claimant_name", "claim_amount",
                    "claim_type", "accident_date", "workshop_name"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

        # FIR compulsory check for Third Party Liability
        claim_type = str(data.get("claim_type", ""))
        if "third party" in claim_type.lower():
            fir_path = data.get("fir_document_path", "")
            if not fir_path or not os.path.exists(fir_path):
                return jsonify({
                    "error": "FIR document is compulsory for Third Party Liability claims. "
                             "Please upload the FIR before submitting."
                }), 422

        if float(data.get("claim_amount", 0)) <= 0:
            return jsonify({"error": "Claim amount must be greater than zero."}), 400

        # Build claim dict
        claim = {
            "claim_id":               str(data.get("claim_id", "")).strip(),
            "claimant_name":          str(data.get("claimant_name", "")).strip(),
            "claimant_phone":         str(data.get("claimant_phone", "")).strip(),
            "accident_date":          str(data.get("accident_date", "")).strip(),
            "accident_location":      str(data.get("accident_location",
                                          data.get("claimant_city", ""))).strip(),
            "report_date":            str(data.get("report_date", "")).strip(),
            "claim_type":             claim_type.strip(),
            "claim_amount":           float(data.get("claim_amount", 0)),
            "original_purchase_price":float(data.get("original_purchase_price", 0)),
            "vehicle_age_years":      int(data.get("vehicle_age_years", 0)),
            "vehicle_name":           str(data.get("vehicle_name", data.get("vehicle", ""))).strip(),
            "vehicle":                str(data.get("vehicle_name", data.get("vehicle", ""))).strip(),
            "workshop_name":          str(data.get("workshop_name", "")).strip(),
            "workshop_contact":       str(data.get("workshop_contact", "")).strip(),
            "surveyor_contact":       str(data.get("surveyor_contact", "")).strip(),
            "police_report_filed":    str(data.get("police_report_filed", "N/A")).strip(),
            "estimation_bill":        float(data.get("estimation_bill", 0)),
            "prior_claims_90d":       int(data.get("prior_claims_90d", 0)),
            "prior_claims_total":     int(data.get("prior_claims_total", 0)),
            "past_rejected":          int(data.get("past_rejected", 0)),
            "claimant_city":          str(data.get("claimant_city", "")).strip(),
            "documents_uploaded":     data.get("documents_uploaded", []),
            "accident_narrative":     str(data.get("accident_narrative", "")).strip(),
        }

        uploaded_files = {
            "fir_document":    data.get("fir_document_path", ""),
            "workshop_invoice": data.get("workshop_invoice_path", ""),
        }

        def generate():
            for result in assess_claim(claim, uploaded_files):
                yield f"data: {json.dumps(result, default=str)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large. Maximum size is 16 MB."}), 413


if __name__ == "__main__":
    gemini_key = os.getenv("GOOGLE_API_KEY", "")
    print("\n" + "=" * 62)
    print("  InsureGuard AI v4.0 — Motor Insurance Fraud Detection")
    print(f"  Gemini API: {'✓ Key loaded' if gemini_key else '✗ MISSING — add GOOGLE_API_KEY to .env'}")
    print("  http://localhost:5000")
    print("=" * 62 + "\n")
    app.run(debug=True, host="localhost", port=5000, use_reloader=False)
