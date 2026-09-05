const API_BASE = window.LM_API_BASE || "http://localhost:8000";

let AUTH_TOKEN = localStorage.getItem("lm_token") || null;
let CURRENT_USER = JSON.parse(localStorage.getItem("lm_user") || "null");
let stateChart = null, rulesChart = null, leafletMap = null;
let lastScanResult = null;

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------
async function apiFetch(path, options = {}) {
  const headers = options.headers || {};
  if (AUTH_TOKEN) headers["Authorization"] = `Bearer ${AUTH_TOKEN}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    logout();
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
async function performLogin(username, password) {
  const errBox = document.getElementById("login-error");
  const overlay = document.getElementById("login-loading-overlay");
  const statusEl = document.getElementById("ll-status");
  const bar = document.getElementById("ll-progress-bar");

  errBox.style.display = "none";
  overlay.style.display = "flex";
  statusEl.setAttribute("data-i18n", "loading_authenticating");
  statusEl.textContent = t("loading_authenticating");
  bar.style.width = "12%";

  try {
    const fd = new FormData();
    fd.append("username", username);
    fd.append("password", password);

    const [res] = await Promise.all([
      fetch(`${API_BASE}/api/auth/login`, { method: "POST", body: fd }),
      sleep(500),
    ]);
    if (!res.ok) throw new Error("bad creds");
    const data = await res.json();

    bar.style.width = "65%";
    statusEl.setAttribute("data-i18n", "loading_dashboard");
    statusEl.textContent = t("loading_dashboard");

    AUTH_TOKEN = data.access_token;
    CURRENT_USER = data.user;
    localStorage.setItem("lm_token", AUTH_TOKEN);
    localStorage.setItem("lm_user", JSON.stringify(CURRENT_USER));

    await sleep(550);
    bar.style.width = "100%";
    await sleep(200);

    overlay.style.display = "none";
    bar.style.width = "0%";
    showApp();
  } catch (err) {
    overlay.style.display = "none";
    bar.style.width = "0%";
    errBox.style.display = "block";
  }
}

document.getElementById("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  performLogin(username, password);
});

document.querySelectorAll(".quick-login-card").forEach((card) => {
  card.addEventListener("click", () => {
    performLogin(card.dataset.username, card.dataset.password);
  });
});

function logout() {
  AUTH_TOKEN = null;
  CURRENT_USER = null;
  localStorage.removeItem("lm_token");
  localStorage.removeItem("lm_user");
  document.getElementById("app-screen").style.display = "none";
  document.getElementById("login-screen").style.display = "flex";
}
document.getElementById("logout-btn").addEventListener("click", logout);

function showApp() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app-screen").style.display = "block";
  document.getElementById("user-name").textContent = CURRENT_USER.full_name;
  document.getElementById("user-role").textContent = CURRENT_USER.role;
  navigate(location.hash.replace("#", "") || "dashboard");
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------
const ROUTE_TITLES = {
  dashboard: "nav_dashboard", scan: "nav_scan",
  history: "nav_history", rules: "nav_rules",
};

function navigate(route) {
  if (!ROUTE_TITLES[route]) route = "dashboard";
  document.querySelectorAll(".view").forEach((v) => (v.style.display = "none"));
  document.getElementById(`view-${route}`).style.display = "block";
  document.querySelectorAll(".sidebar-nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === route);
  });
  document.getElementById("page-title").setAttribute("data-i18n", ROUTE_TITLES[route]);
  document.getElementById("page-title").textContent = t(ROUTE_TITLES[route]);
  location.hash = route;

  if (route === "dashboard") loadDashboard();
  if (route === "history") loadHistory();
  if (route === "rules") loadRules();
  if (route === "scan") loadSampleGallery();
}

document.querySelectorAll(".sidebar-nav a").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    navigate(a.dataset.route);
  });
});
window.addEventListener("hashchange", () => navigate(location.hash.replace("#", "")));

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadDashboard() {
  try {
    const res = await apiFetch("/api/dashboard/stats");
    const d = await res.json();

    document.getElementById("stat-total").textContent = d.total_scanned;
    document.getElementById("stat-rate").textContent = `${d.compliance_rate}%`;
    document.getElementById("stat-compliant").textContent = d.compliant;
    document.getElementById("stat-noncompliant").textContent = d.non_compliant;

    // Each of these renders an independent widget. They used to share one
    // try/catch with the stat cards above -- if Chart.js or Leaflet failed
    // to load (e.g. the CDN scripts in <head> were blocked by a firewall
    // or ad-blocker, so `Chart`/`L` are undefined), the FIRST render call
    // threw, and every render after it silently never ran -- leaving the
    // stat cards populated but every chart/map/table blank, with no
    // visible error. Isolating each call means one missing library only
    // blanks its own card instead of the whole dashboard, and logs a
    // specific reason to the console instead of failing silently.
    safeRender("chart-state", () => renderStateChart(d.by_state), typeof Chart === "undefined");
    safeRender("chart-rules", () => renderRulesChart(d.violations_by_rule), typeof Chart === "undefined");
    safeRender("offenders-table", () => renderOffenders(d.top_offenders));
    safeRender("map", () => renderMap(d.heatmap_points), typeof L === "undefined");
  } catch (err) {
    console.error(err);
  }
}

function safeRender(elId, renderFn, libMissing) {
  const el = document.getElementById(elId);
  try {
    if (libMissing) throw new Error("Charting/map library not loaded (blocked script or offline CDN?)");
    renderFn();
  } catch (err) {
    console.error(`Dashboard widget "${elId}" failed to render:`, err);
    if (el && el.tagName !== "CANVAS") {
      el.innerHTML = `<div class="empty-state" style="padding:20px 0;">Couldn't load this widget. Check your internet connection or browser console for details.</div>`;
    } else if (el) {
      const msg = document.createElement("div");
      msg.className = "empty-state";
      msg.style.padding = "20px 0";
      msg.textContent = "Couldn't load this chart. Check your internet connection or browser console for details.";
      el.replaceWith(msg);
    }
  }
}

function renderStateChart(byState) {
  const ctx = document.getElementById("chart-state");
  if (stateChart) stateChart.destroy();
  stateChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: byState.map((r) => r.state),
      datasets: [{
        label: "Inspections",
        data: byState.map((r) => r.count),
        backgroundColor: "#0B3D91",
        borderRadius: 4,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

function renderRulesChart(byRule) {
  const ctx = document.getElementById("chart-rules");
  if (rulesChart) rulesChart.destroy();
  const palette = ["#C62828", "#FF9933", "#B8860B", "#0B3D91", "#138808", "#5B6472", "#8E24AA"];
  rulesChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: byRule.map((r) => r.rule),
      datasets: [{ data: byRule.map((r) => r.count), backgroundColor: palette }],
    },
    options: { plugins: { legend: { position: "right", labels: { boxWidth: 10, font: { size: 10 } } } } },
  });
}

function renderOffenders(offenders) {
  const tbody = document.getElementById("offenders-table");
  tbody.innerHTML = offenders.map((o) => `
    <tr><td>${escapeHtml(o.manufacturer)}</td><td style="text-align:right; font-weight:700; color:var(--danger)">${o.violations}</td></tr>
  `).join("") || `<tr><td class="empty-state">No data</td></tr>`;
}

function renderMap(points) {
  if (!leafletMap) {
    leafletMap = L.map("map").setView([22.9734, 78.6569], 4.6);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(leafletMap);
    window._lm_markers = [];
  }
  window._lm_markers.forEach((m) => leafletMap.removeLayer(m));
  window._lm_markers = [];
  points.forEach((p) => {
    const color = p.status === "COMPLIANT" ? "#1B873F" : "#C62828";
    const marker = L.circleMarker([p.lat, p.lng], {
      radius: 6, color, fillColor: color, fillOpacity: 0.7, weight: 1,
    }).bindPopup(`<b>${escapeHtml(p.product)}</b><br>${escapeHtml(p.state)}<br>${p.status}`);
    marker.addTo(leafletMap);
    window._lm_markers.push(marker);
  });
}

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
let selectedFile = null;

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", (e) => {
  if (e.target.files.length) handleFile(e.target.files[0]);
});

function handleFile(file, sampleId) {
  selectedFile = file;
  const reader = new FileReader();
  reader.onload = (e) => {
    document.getElementById("preview-img").src = e.target.result;
    document.getElementById("preview-wrap").style.display = "block";
    document.getElementById("preview-wrap").scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  reader.readAsDataURL(file);
  document.getElementById("scan-run-btn").disabled = false;

  document.querySelectorAll(".sample-card").forEach((c) => {
    c.classList.toggle("selected", sampleId && c.dataset.id === sampleId);
  });
}

// ---------------------------------------------------------------------------
// Sample product gallery (bundled demo labels for quick, reliable demos)
// ---------------------------------------------------------------------------
// Two sources are merged into one gallery:
//   1. assets/samples/manifest.json    -- synthetic labels with a KNOWN,
//      auto-computed compliant/non-compliant outcome (generated by
//      dataset/generate_dataset.py, which overwrites this file completely
//      every time it runs).
//   2. assets/real_samples/manifest.json -- real product photos added by
//      hand. There's no automatic ground truth for these (nobody has
//      graded them against the Legal Metrology rules), so they're shown
//      with a neutral "Real Product" badge instead of a COMPLIANT /
//      NON_COMPLIANT claim, and they live in a folder generate_dataset.py
//      never touches, so regenerating the synthetic set can't delete them.
let SAMPLE_MANIFEST = [];
let REAL_MANIFEST = [];

async function loadSampleGallery() {
  const gallery = document.getElementById("sample-gallery");
  if (!gallery) return;
  try {
    if (!SAMPLE_MANIFEST.length) {
      const res = await fetch("assets/samples/manifest.json");
      SAMPLE_MANIFEST = (await res.json()).map((s) => ({ ...s, _base: "assets/samples", _real: false }));
    }
    if (!REAL_MANIFEST.length) {
      try {
        const res2 = await fetch("assets/real_samples/manifest.json");
        REAL_MANIFEST = (await res2.json()).map((s) => ({ ...s, _base: "assets/real_samples", _real: true }));
      } catch (e) {
        REAL_MANIFEST = []; // fine if the file/folder doesn't exist yet
      }
    }

    const combined = [...REAL_MANIFEST, ...SAMPLE_MANIFEST];

    gallery.innerHTML = combined.map((s) => `
      <div class="sample-card" data-id="${s.id}" data-file="${s.file}" data-base="${s._base}">
        <span class="sc-badge ${s._real ? "REAL" : s.expected}">${
          s._real ? t("sample_real_badge") : (s.expected === "COMPLIANT" ? t("status_compliant") : t("status_non_compliant"))
        }</span>
        <img src="${s._base}/${s.file}" alt="${escapeHtml(s.title)}" loading="lazy">
        <div class="sc-title">${escapeHtml(s.title)}</div>
        <div class="sc-hint">${escapeHtml(s.hint)}</div>
      </div>
    `).join("");

    gallery.querySelectorAll(".sample-card").forEach((card) => {
      card.addEventListener("click", async () => {
        const file = card.dataset.file;
        const id = card.dataset.id;
        const base = card.dataset.base;
        const resp = await fetch(`${base}/${file}`);
        const blob = await resp.blob();
        const asFile = new File([blob], file, { type: blob.type || "image/png" });
        handleFile(asFile, id);
      });
    });
  } catch (err) {
    console.error("Failed to load sample gallery", err);
  }
}

document.getElementById("scan-run-btn").addEventListener("click", runScan);

async function runScan() {
  if (!selectedFile) return;
  const btn = document.getElementById("scan-run-btn");
  const steps = document.getElementById("pipeline-steps");
  const resultCard = document.getElementById("scan-result-card");
  btn.disabled = true;
  resultCard.style.display = "none";
  steps.style.display = "flex";
  document.querySelectorAll(".pipeline-step").forEach((s) => s.classList.remove("active", "done"));

  const stepEls = document.querySelectorAll(".pipeline-step");
  const animateSteps = (async () => {
    for (const el of stepEls) {
      el.classList.add("active");
      await sleep(500);
      el.classList.remove("active");
      el.classList.add("done");
    }
  })();

  try {
    const fd = new FormData();
    fd.append("file", selectedFile);
    fd.append("state", document.getElementById("scan-state").value);
    fd.append("district", document.getElementById("scan-district").value);

    const [res] = await Promise.all([
      apiFetch("/api/scan", { method: "POST", body: fd }),
      animateSteps,
    ]);
    const data = await res.json();
    lastScanResult = data;
    renderScanResult(data);
  } catch (err) {
    alert("Scan failed: " + err.message);
  } finally {
    btn.disabled = false;
  }
}

function renderScanResult(data) {
  const resultCard = document.getElementById("scan-result-card");
  resultCard.style.display = "block";

  const banner = document.getElementById("result-banner");
  const isCompliant = data.status === "COMPLIANT";
  banner.className = "result-banner " + (isCompliant ? "compliant" : "non-compliant");
  banner.innerHTML = `<span>${isCompliant ? t("status_compliant") : t("status_non_compliant")} — ${data.report_no}</span><span>${data.score}%</span>`;

  const f = data.extracted_fields;
  const fieldMap = [
    ["field_product_name", f.product_name],
    ["field_manufacturer", f.manufacturer_name],
    ["field_address", f.manufacturer_address],
    ["field_net_quantity", [f.net_quantity_value, f.net_quantity_unit].filter(Boolean).join(" ") || f.net_quantity_raw],
    ["field_mrp", f.mrp_value ? `₹${f.mrp_value}` : ""],
    ["field_mfg_date", f.mfg_date],
    ["field_consumer_care", f.consumer_care],
  ];
  document.getElementById("extracted-fields").innerHTML = fieldMap.map(([labelKey, val]) => `
    <div class="field-row">
      <span class="label">${t(labelKey)}</span>
      <span class="value ${val ? "" : "missing"}">${val ? escapeHtml(val) : t("not_detected")}</span>
    </div>
  `).join("");

  document.getElementById("compliance-checks").innerHTML = data.compliance.checks.map((c) => `
    <div class="check-row">
      <span class="check-icon ${c.result === "PASS" ? "pass" : "fail"}">${c.result === "PASS" ? "✓" : "✕"}</span>
      <span>${escapeHtml(c.title)}</span>
    </div>
  `).join("");

  const violations = data.compliance.violations;
  document.getElementById("violations-list").innerHTML = violations.length
    ? violations.map((v) => `
        <div class="violation-card">
          <div class="v-title"><span>${escapeHtml(v.rule_title)}</span><span class="badge ${v.severity.toLowerCase()}">${v.severity}</span></div>
          <div class="v-ref">${escapeHtml(v.reference)}</div>
          <div class="v-desc">${escapeHtml(v.description)}</div>
        </div>
      `).join("")
    : `<div class="empty-state" style="padding:14px 0; text-align:left;">${t("scan_no_violations")}</div>`;

  document.getElementById("download-report-btn").onclick = () => downloadReport(data.inspection_id, data.report_no);
}

async function downloadReport(inspectionId, reportNo) {
  const res = await apiFetch(`/api/inspections/${inspectionId}/report.pdf`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${reportNo}.pdf`;
  a.click();
  URL.revokeObjectURL(url);
}

document.getElementById("new-scan-btn").addEventListener("click", () => {
  selectedFile = null;
  fileInput.value = "";
  document.getElementById("preview-wrap").style.display = "none";
  document.getElementById("scan-result-card").style.display = "none";
  document.getElementById("pipeline-steps").style.display = "none";
  document.getElementById("scan-run-btn").disabled = true;
});

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------
let historyDebounce = null;
document.getElementById("history-search").addEventListener("input", () => {
  clearTimeout(historyDebounce);
  historyDebounce = setTimeout(loadHistory, 300);
});
document.getElementById("history-filter-status").addEventListener("change", loadHistory);

async function loadHistory() {
  const q = document.getElementById("history-search").value;
  const status = document.getElementById("history-filter-status").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status_filter", status);

  try {
    const res = await apiFetch(`/api/inspections?${params.toString()}`);
    const rows = await res.json();
    const tbody = document.getElementById("history-table-body");
    tbody.innerHTML = rows.length ? rows.map((r) => `
      <tr>
        <td>${escapeHtml(r.report_no)}</td>
        <td>${escapeHtml(r.product_name || "-")}</td>
        <td>${escapeHtml(r.manufacturer_name || "-")}</td>
        <td>${escapeHtml(r.district)}, ${escapeHtml(r.state)}</td>
        <td><span class="badge ${r.compliance_status === "COMPLIANT" ? "compliant" : "non-compliant"}">${r.compliance_status === "COMPLIANT" ? t("status_compliant") : t("status_non_compliant")}</span></td>
        <td>${r.compliance_score}%</td>
        <td>${new Date(r.created_at).toLocaleDateString()}</td>
        <td><button class="btn btn-outline btn-sm" onclick="viewInspection(${r.id})">${t("history_view")}</button></td>
      </tr>
    `).join("") : `<tr><td colspan="8" class="empty-state">No inspections found</td></tr>`;
  } catch (err) {
    console.error(err);
  }
}

async function viewInspection(id) {
  const res = await apiFetch(`/api/inspections/${id}`);
  const insp = await res.json();
  const modalContent = document.getElementById("modal-content");
  modalContent.innerHTML = `
    <h3>${escapeHtml(insp.report_no)}</h3>
    <div class="field-row"><span class="label">${t("field_product_name")}</span><span>${escapeHtml(insp.product_name || "-")}</span></div>
    <div class="field-row"><span class="label">${t("field_manufacturer")}</span><span>${escapeHtml(insp.manufacturer_name || "-")}</span></div>
    <div class="field-row"><span class="label">${t("field_net_quantity")}</span><span>${escapeHtml([insp.net_quantity_value, insp.net_quantity_unit].filter(Boolean).join(" ") || "-")}</span></div>
    <div class="field-row"><span class="label">${t("field_mrp")}</span><span>${insp.mrp ? "₹" + escapeHtml(insp.mrp) : "-"}</span></div>
    <div class="field-row"><span class="label">${t("field_mfg_date")}</span><span>${escapeHtml(insp.mfg_date || "-")}</span></div>
    <div class="field-row"><span class="label">${t("history_col_status")}</span><span class="badge ${insp.compliance_status === "COMPLIANT" ? "compliant" : "non-compliant"}">${insp.compliance_status}</span></div>
    <h3 style="margin-top:16px;">${t("scan_violations")}</h3>
    ${insp.violations.length ? insp.violations.map((v) => `
      <div class="violation-card">
        <div class="v-title"><span>${escapeHtml(v.rule_title)}</span><span class="badge ${v.severity.toLowerCase()}">${v.severity}</span></div>
        <div class="v-ref">${escapeHtml(v.reference)}</div>
        <div class="v-desc">${escapeHtml(v.description)}</div>
      </div>
    `).join("") : `<div class="empty-state" style="text-align:left; padding:8px 0;">${t("scan_no_violations")}</div>`}
    <button class="btn btn-primary" style="margin-top:14px;" onclick="downloadReport(${insp.id}, '${insp.report_no}')">${t("scan_download_report")}</button>
  `;
  document.getElementById("detail-modal").style.display = "flex";
}
document.getElementById("modal-close-btn").addEventListener("click", () => {
  document.getElementById("detail-modal").style.display = "none";
});
document.getElementById("detail-modal").addEventListener("click", (e) => {
  if (e.target.id === "detail-modal") e.target.style.display = "none";
});

// ---------------------------------------------------------------------------
// Rules reference
// ---------------------------------------------------------------------------
async function loadRules() {
  try {
    const res = await apiFetch("/api/rules");
    const rules = await res.json();
    document.getElementById("rules-list").innerHTML = rules.map((r) => `
      <div class="rule-item">
        <div class="r-title"><span>${escapeHtml(r.title)}</span><span class="badge ${r.severity.toLowerCase()}">${r.severity}</span></div>
        <div class="r-ref">${escapeHtml(r.reference)}</div>
        <div class="r-desc">${escapeHtml(r.description)}</div>
      </div>
    `).join("");
  } catch (err) {
    console.error(err);
  }
}

// ---------------------------------------------------------------------------
// Re-render dynamic content when language changes
// ---------------------------------------------------------------------------
function onTranslationsApplied() {
  if (!AUTH_TOKEN) return;
  const active = document.querySelector(".sidebar-nav a.active");
  const route = active ? active.dataset.route : "dashboard";
  document.getElementById("page-title").textContent = t(ROUTE_TITLES[route] || "nav_dashboard");
  if (route === "history") loadHistory();
  if (route === "rules") loadRules();
  if (route === "scan") loadSampleGallery();
  if (lastScanResult) renderScanResult(lastScanResult);
}

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str).replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[m]));
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
if (AUTH_TOKEN && CURRENT_USER) {
  showApp();
} else {
  document.getElementById("login-screen").style.display = "flex";
}
