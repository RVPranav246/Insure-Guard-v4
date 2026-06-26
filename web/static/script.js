/* InsureGuard AI v4.0 — Agentic Frontend */

// ── State ──────────────────────────────────────────────────────────────
let uploadedFiles = { fir_document: null, workshop_invoice: null };
let isThirdParty = false;
let dropdownData = [];
let dropdownOpen = false;

// ── Init ───────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadClaimTypes();
    setupDropdown();
    setupFileUploads();
    document.getElementById("claim_type").addEventListener("change", onClaimTypeChange);
});

// ── Claim type change ──────────────────────────────────────────────────
function loadClaimTypes() {
    fetch("/api/claim-types").then(r => r.json()).then(types => {
        const sel = document.getElementById("claim_type");
        sel.innerHTML = '<option value="">Select type</option>';
        types.forEach(t => {
            const o = document.createElement("option");
            o.value = t; o.textContent = t;
            sel.appendChild(o);
        });
    }).catch(() => {});
}

function onClaimTypeChange() {
    const val = document.getElementById("claim_type").value;
    isThirdParty = val.toLowerCase().includes("third party");
    const firSection = document.getElementById("fir-section");
    if (firSection) {
        firSection.style.display = isThirdParty ? "block" : "none";
        if (isThirdParty) {
            document.getElementById("fir-upload-zone").classList.add("required-missing");
        }
    }
}

// ── Smart Searchable Dropdown ──────────────────────────────────────────
function setupDropdown() {
    const input = document.getElementById("policyholder_search");
    const dropdown = document.getElementById("policyholder_dropdown");
    if (!input || !dropdown) return;

    let debounce;
    input.addEventListener("input", () => {
        clearTimeout(debounce);
        const q = input.value.trim();
        if (q.length < 2) { closeDropdown(); return; }
        debounce = setTimeout(() => fetchSuggestions(q), 250);
    });

    input.addEventListener("blur", () => setTimeout(closeDropdown, 200));
    input.addEventListener("focus", () => {
        if (dropdownData.length) openDropdown();
    });
}

function fetchSuggestions(q) {
    fetch(`/api/search-policyholders?q=${encodeURIComponent(q)}`)
        .then(r => r.json())
        .then(results => {
            dropdownData = results;
            renderDropdown(results);
        }).catch(() => {});
}

function renderDropdown(results) {
    const dd = document.getElementById("policyholder_dropdown");
    if (!results.length) {
        dd.innerHTML = `<div class="dropdown-empty">No policyholders found matching your search.</div>`;
        openDropdown();
        return;
    }
    dd.innerHTML = results.map((r, i) => `
        <div class="dropdown-item" onclick="selectPolicyholder(${i})">
            <span class="item-name">${esc(r.name)}</span>
            <span class="item-meta">${esc(r.claim_id)} &nbsp;·&nbsp; ${esc(r.vehicle)}</span>
        </div>`).join("");
    openDropdown();
}

function openDropdown()  { document.getElementById("policyholder_dropdown").classList.add("open"); dropdownOpen = true; }
function closeDropdown() { document.getElementById("policyholder_dropdown").classList.remove("open"); dropdownOpen = false; }

function selectPolicyholder(idx) {
    const item = dropdownData[idx];
    if (!item) return;
    document.getElementById("policyholder_search").value = item.name;
    closeDropdown();
    const msg = document.getElementById("validation-msg");
    msg.className = "validation-msg success";
    msg.textContent = `✓ Policyholder found — ${item.claim_id} — ${item.vehicle}`;

    // Autofill
    fetch(`/api/autofill/${encodeURIComponent(item.claim_id)}`)
        .then(r => r.json())
        .then(data => {
            if (data.error) { showValidationError(data.error); return; }
            autofillForm(data);
        }).catch(() => {});
}

function autofillForm(data) {
    const fieldMap = {
        "claim_id":               "claim_id",
        "claimant_name":          "claimant_name_hidden",
        "claimant_phone":         "claimant_phone",
        "claimant_city":          "claimant_city",
        "vehicle_name":           "vehicle_name",
        "vehicle_age_years":      "vehicle_age_years",
        "original_purchase_price":"original_purchase_price",
        "policy_number":          "policy_number",
        "accident_date":          "accident_date",
        "report_date":            "report_date",
        "workshop_name":          "workshop_name",
        "workshop_contact":       "workshop_contact",
        "surveyor_contact":       "surveyor_contact",
        "prior_claims_90d":       "prior_claims_90d",
        "prior_claims_total":     "prior_claims_total",
        "past_rejected":          "past_rejected",
        "tax_invoice_amount":     "tax_invoice_hidden",
    };

    for (const [dataKey, fieldId] of Object.entries(fieldMap)) {
        const el = document.getElementById(fieldId);
        if (!el || !data[dataKey] && data[dataKey] !== 0) continue;
        el.value = data[dataKey];
        if (el.classList.contains("form-input")) el.classList.add("autofilled");
    }

    // Claim type dropdown
    if (data.claim_type) {
        const sel = document.getElementById("claim_type");
        for (const opt of sel.options) {
            if (opt.value.toLowerCase() === data.claim_type.toLowerCase()) {
                sel.value = opt.value;
                onClaimTypeChange();
                break;
            }
        }
    }

    // Claim amount
    if (data.claim_amount) {
        const el = document.getElementById("claim_amount");
        if (el) { el.value = data.claim_amount; el.classList.add("autofilled"); }
    }

    // Show tax invoice box
    if (data.tax_invoice_amount) {
        const box = document.getElementById("invoice-box");
        if (box) {
            box.innerHTML = `
                <div class="invoice-box-label">Tax Invoice on Record</div>
                <div class="invoice-row">
                    <span class="key">Tax Invoice Amount</span>
                    <span class="val">${fmtCur(data.tax_invoice_amount)}</span>
                </div>`;
            box.style.display = "block";
        }
    }
}

function showValidationError(msg) {
    const el = document.getElementById("validation-msg");
    el.className = "validation-msg error";
    el.textContent = "✗ " + msg;
}

// ── File Uploads ───────────────────────────────────────────────────────
function setupFileUploads() {
    setupZone("fir-upload-zone", "fir_file_input", "fir_document");
    setupZone("invoice-upload-zone", "invoice_file_input", "workshop_invoice");
}

function setupZone(zoneId, inputId, docType) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    if (!zone || !input) return;

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover", e => { e.preventDefault(); zone.style.borderColor = "var(--gold)"; });
    zone.addEventListener("dragleave", () => zone.style.borderColor = "");
    zone.addEventListener("drop", e => {
        e.preventDefault();
        zone.style.borderColor = "";
        const file = e.dataTransfer.files[0];
        if (file) uploadFile(file, docType, zoneId);
    });
    input.addEventListener("change", () => {
        if (input.files[0]) uploadFile(input.files[0], docType, zoneId);
    });
}

function uploadFile(file, docType, zoneId) {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("doc_type", docType);

    const zone = document.getElementById(zoneId);
    if (zone) {
        zone.querySelector(".upload-label").innerHTML = `<strong>Uploading...</strong>`;
    }

    fetch("/api/upload-document", { method: "POST", body: formData })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                if (zone) zone.querySelector(".upload-label").innerHTML =
                    `<strong>Error:</strong> ${esc(data.error)}`;
                return;
            }
            uploadedFiles[docType] = data.path;
            if (zone) {
                zone.classList.remove("required-missing");
                zone.classList.add("has-file");
                zone.querySelector(".upload-label").innerHTML =
                    `<strong>${esc(data.filename)}</strong> — uploaded successfully`;
            }
        }).catch(e => {
            if (zone) zone.querySelector(".upload-label").innerHTML =
                `<strong>Upload failed:</strong> ${esc(e.message)}`;
        });
}

// ── Run Analysis ───────────────────────────────────────────────────────
function runAnalysis() {
    // Validate policyholder
    const name = document.getElementById("policyholder_search")?.value.trim();
    if (!name) { showTopError("Please enter a policyholder name."); return; }

    const fields = [
        "claim_id", "claimant_phone", "accident_date", "report_date",
        "claim_type", "claim_amount", "original_purchase_price", "vehicle_age_years",
        "vehicle_name", "workshop_name", "workshop_contact", "surveyor_contact",
        "police_report_filed", "estimation_bill",
        "prior_claims_90d", "prior_claims_total", "past_rejected",
    ];
    const data = { claimant_name: name };
    for (const f of fields) {
        const el = document.getElementById(f);
        if (el) data[f] = el.value.trim();
    }

    // Narrative
    const narr = document.getElementById("accident_narrative");
    if (narr) data.accident_narrative = narr.value.trim();
    const city = document.getElementById("claimant_city");
    if (city) data.accident_location = city.value.trim();

    // Uploaded files
    data.fir_document_path      = uploadedFiles.fir_document || "";
    data.workshop_invoice_path  = uploadedFiles.workshop_invoice || "";

    // Validate required
    const required = ["claim_id", "claim_amount", "claim_type", "accident_date", "workshop_name"];
    for (const f of required) {
        if (!data[f]) { showTopError(`Required field missing: ${f.replace(/_/g," ")}`); return; }
    }
    if (parseFloat(data.claim_amount) <= 0) { showTopError("Claim amount must be greater than zero."); return; }

    // FIR check
    if (isThirdParty && !uploadedFiles.fir_document) {
        showTopError("FIR document is compulsory for Third Party Liability claims. Please upload the FIR.");
        return;
    }

    // Reset UI
    document.getElementById("btn-run").style.display = "none";
    document.getElementById("btn-clear").style.display = "none";
    document.getElementById("progress-wrap").classList.add("active");

    const res = document.getElementById("results-section");
    res.classList.add("active");
    document.getElementById("agent-grid").innerHTML = "";
    document.getElementById("ai-task-list").innerHTML = "";
    document.getElementById("halt-banner").classList.remove("active");
    document.getElementById("verdict-wrap").innerHTML = "";
    document.getElementById("ai-summary-wrap").innerHTML = "";
    document.getElementById("score-number").textContent = "0";
    document.getElementById("score-number").className = "score-number";
    document.getElementById("score-meter-fill").style.width = "0%";
    document.getElementById("score-meter-fill").className = "score-meter-fill";
    resetBandPips();

    // SSE stream
    fetch("/api/assess", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data),
    }).then(resp => {
        if (!resp.ok) return resp.json().then(e => { throw new Error(e.error || "Server error"); });
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        function pump() {
            reader.read().then(({done, value}) => {
                if (done) { finishRun(); return; }
                buf += dec.decode(value, {stream: true});
                const lines = buf.split("\n"); buf = lines.pop();
                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        try { handle(JSON.parse(line.slice(6))); } catch(e) {}
                    }
                }
                pump();
            }).catch(e => { showTopError("Stream error: " + e.message); finishRun(); });
        }
        pump();
    }).catch(e => { showTopError(e.message); finishRun(); });
}

// ── Event handlers ─────────────────────────────────────────────────────
function handle(p) {
    if (p.type === "agent_result") renderAgent(p);
    else if (p.type === "ai_task") renderAiTask(p);
    else if (p.type === "verdict") renderVerdict(p);
}

function renderAgent(d) {
    const pct = ((d.agent_index + 1) / d.agent_count) * 100;
    document.getElementById("progress-fill").style.width = pct + "%";
    document.getElementById("progress-text").textContent =
        `Agent ${d.agent_index + 1}/${d.agent_count}: ${d.agent_name}`;

    const total = Math.min(d.running_total, 100);
    animateNum(document.getElementById("score-number"), total);
    const bc = bandClass(total);
    document.getElementById("score-number").className = "score-number " + bc;
    const fill = document.getElementById("score-meter-fill");
    fill.style.width = total + "%";
    fill.className = "score-meter-fill " + bc;
    highlightBandPip(bc);

    let flagsHtml = "";
    if (d.flags?.length) {
        flagsHtml = `<ul class="agent-flags">${d.flags.map(f=>`<li>${esc(f)}</li>`).join("")}</ul>`;
    }
    const card = document.createElement("div");
    card.className = "agent-card " + borderClass(d.points);
    card.innerHTML = `
        <div class="agent-header">
            <span class="agent-name">${esc(d.agent_name)}</span>
            <span class="agent-tag ${tagClass(d.points)}">+${d.points} pts</span>
        </div>
        <p class="agent-summary">${esc(d.summary)}</p>${flagsHtml}`;
    document.getElementById("agent-grid").appendChild(card);
    requestAnimationFrame(() => requestAnimationFrame(() => card.classList.add("visible")));
    if (d.halted) document.getElementById("halt-banner").classList.add("active");
}

function renderAiTask(d) {
    document.getElementById("progress-text").textContent = `AI: ${d.task}`;
    const list = document.getElementById("ai-task-list");
    const row = document.createElement("div");
    const dotClass = { running: "dot-running", complete: "dot-complete",
                       error: "dot-error", warning: "dot-warning" }[d.status] || "dot-running";
    row.className = "ai-task-row";
    row.id = `task-${d.task.replace(/\s+/g,"-")}`;
    row.innerHTML = `
        <div class="ai-task-dot ${dotClass}"></div>
        <span class="ai-task-name">${esc(d.task)}</span>
        <span class="ai-task-msg">${esc(d.message)}</span>`;
    list.appendChild(row);
    requestAnimationFrame(() => requestAnimationFrame(() => row.classList.add("visible")));

    // AI Summary data arrived — render the box
    if (d.task === "AI Summary Report" && d.status === "complete" && d.data) {
        renderAiSummary(d.data);
    }

    // Cross-ref findings
    if (d.task === "Cross-Reference Check" && d.status === "complete" && d.data) {
        renderCrossRef(d.data);
    }
}

function renderAiSummary(data) {
    const wrap = document.getElementById("ai-summary-wrap");
    const bullets = (data.summary_bullets || []).map((b, i) => `
        <li>
            <div class="ai-bullet-marker">${i+1}</div>
            <span>${esc(b)}</span>
        </li>`).join("");

    const confClass = { High: "conf-high", Medium: "conf-medium", Low: "conf-low" }[data.confidence] || "conf-medium";

    wrap.innerHTML = `
        <div class="ai-summary-card" id="ai-summary-card">
            <div class="ai-summary-eyebrow">AI Summary Report</div>
            <div class="ai-summary-title serif">Agent Analysis &amp; Findings</div>
            ${bullets ? `<ul class="ai-bullets">${bullets}</ul>` : ""}
            ${data.overall_assessment ? `
            <div class="ai-assess-box">
                <div class="ai-assess-label">Overall Assessment</div>
                <div class="ai-assess-text">${esc(data.overall_assessment)}</div>
            </div>` : ""}
            <div class="ai-action-row">
                <span class="ai-recommended">
                    <strong>Recommended Action:</strong> ${esc(data.recommended_action || "—")}
                </span>
                <span class="ai-confidence ${confClass}">
                    ${esc(data.confidence || "Medium")} Confidence
                </span>
            </div>
        </div>`;

    requestAnimationFrame(() => requestAnimationFrame(() => {
        document.getElementById("ai-summary-card")?.classList.add("visible");
    }));
}

function renderCrossRef(data) {
    const inc = data.inconsistencies || [];
    const con = data.consistent_points || [];
    if (!inc.length && !con.length) return;

    const wrap = document.getElementById("crossref-wrap");
    if (!wrap) return;
    wrap.innerHTML = `
        <div class="findings-grid">
            <div class="finding-box inconsistencies">
                <div class="finding-label bad">Inconsistencies Found (${inc.length})</div>
                <ul class="finding-list">
                    ${inc.length ? inc.map(i=>`<li>${esc(i)}</li>`).join("") : "<li>None detected</li>"}
                </ul>
            </div>
            <div class="finding-box consistent">
                <div class="finding-label good">Consistent Points (${con.length})</div>
                <ul class="finding-list">
                    ${con.length ? con.map(c=>`<li>${esc(c)}</li>`).join("") : "<li>None noted</li>"}
                </ul>
            </div>
        </div>`;
}

function renderVerdict(d) {
    const bc = d.verdict.toLowerCase().replace(/\s+/g,"-");
    document.getElementById("verdict-wrap").innerHTML = `
        <div class="verdict-card verdict-${bc}" id="v-card">
            <div class="verdict-eyebrow">Final Verdict — Score ${d.total_score}/100</div>
            <div class="verdict-heading">${esc(d.verdict)}</div>
            <div class="verdict-level">${esc(d.level)}</div>
            <div class="verdict-action">${esc(d.action)}</div>
        </div>`;
    if (d.halted) document.getElementById("input-card").classList.add("halted");
    requestAnimationFrame(() => requestAnimationFrame(() => {
        document.getElementById("v-card")?.classList.add("visible");
    }));
}

// ── Utilities ──────────────────────────────────────────────────────────
function animateNum(el, target) {
    const cur = parseInt(el.textContent) || 0;
    if (cur === target) return;
    const step = target > cur ? 1 : -1; let v = cur;
    const iv = setInterval(() => { v += step; el.textContent = v; if (v === target) clearInterval(iv); }, 25);
}

function bandClass(s) {
    if (s >= 86) return "reject";
    if (s >= 66) return "investigate";
    if (s >= 41) return "review";
    return "approve";
}
function tagClass(p) {
    if (p === 0) return "tag-0"; if (p <= 10) return "tag-low";
    if (p <= 29) return "tag-high"; return "tag-crit";
}
function borderClass(p) {
    if (p === 0) return "clean"; if (p <= 10) return "warn"; return "flagged";
}

const pipIds = {approve:"pip-approve",review:"pip-review",investigate:"pip-investigate",reject:"pip-reject"};
function resetBandPips() {
    ["approve","review","investigate","reject"].forEach(b => {
        document.getElementById(`pip-${b}`).className = `score-band-pip pip-${b}`;
    });
}
function highlightBandPip(band) {
    resetBandPips();
    const id = pipIds[band];
    if (id) document.getElementById(id).className = `score-band-pip active-${band}`;
}

function finishRun() {
    document.getElementById("progress-wrap").classList.remove("active");
    document.getElementById("btn-run").style.display = "inline-block";
    document.getElementById("btn-clear").style.display = "inline-block";
}

function clearForm() {
    document.querySelectorAll(".form-input,.form-select,.form-textarea")
        .forEach(el => el.tagName === "SELECT" ? el.selectedIndex = 0 : el.value = "");
    document.querySelectorAll(".autofilled").forEach(e => e.classList.remove("autofilled"));
    const ps = document.getElementById("policyholder_search");
    if (ps) ps.value = "";
    const vm = document.getElementById("validation-msg");
    if (vm) { vm.className = "validation-msg"; vm.textContent = ""; }
    uploadedFiles = { fir_document: null, workshop_invoice: null };
    ["fir-upload-zone","invoice-upload-zone"].forEach(id => {
        const z = document.getElementById(id);
        if (z) { z.classList.remove("has-file","required-missing");
                 const lbl = z.querySelector(".upload-label");
                 if (lbl) lbl.innerHTML = `Click or drag to upload`; }
    });
    document.getElementById("results-section").classList.remove("active");
    document.getElementById("agent-grid").innerHTML = "";
    document.getElementById("ai-task-list").innerHTML = "";
    document.getElementById("halt-banner").classList.remove("active");
    document.getElementById("verdict-wrap").innerHTML = "";
    document.getElementById("ai-summary-wrap").innerHTML = "";
    const crossref = document.getElementById("crossref-wrap");
    if (crossref) crossref.innerHTML = "";
    document.getElementById("invoice-box").style.display = "none";
    document.getElementById("progress-wrap").classList.remove("active");
    document.getElementById("input-card").classList.remove("halted");
    document.getElementById("score-number").textContent = "0";
    document.getElementById("score-number").className = "score-number";
    document.getElementById("score-meter-fill").style.width = "0%";
    resetBandPips();
    isThirdParty = false;
    const firs = document.getElementById("fir-section");
    if (firs) firs.style.display = "none";
}

function showTopError(msg) {
    document.getElementById("results-section").classList.add("active");
    const grid = document.getElementById("agent-grid");
    const card = document.createElement("div");
    card.className = "agent-card flagged visible";
    card.innerHTML = `<div class="agent-header"><span class="agent-name">Error</span></div>
        <p class="agent-summary" style="color:var(--investigate)">${esc(msg)}</p>`;
    grid.prepend(card);
    finishRun();
}

function fmtCur(n) { return "₹" + Number(n).toLocaleString("en-IN"); }
function esc(s) {
    return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;")
        .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
