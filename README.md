# Parakh — AI-Based Legal Metrology (Packaged Commodities) Compliance System

**Parakh** (परख, Hindi for "to test / verify / assay") is a working demo of
an AI-powered inspection system that scans packaged-commodity
label images, extracts the declarations mandated under the **Legal Metrology
Act, 2009** and the **Legal Metrology (Packaged Commodities) Rules, 2011**,
checks them against a rule engine, and produces a compliance report — built
for the SIH-style "Ministry of Consumer Affairs, Food & Public Distribution"
problem statement.

This is a **real, runnable, end-to-end pipeline** (not a mockup): it uses
actual OpenCV preprocessing, actual Tesseract OCR, a heuristic/regex
document-understanding layer (swap-in-ready for LayoutLMv3/Donut in
production), a rule engine encoding the Second Schedule font-size
requirements, and a FastAPI backend backing a multi-language web frontend.

```
parakh/
├── backend/            FastAPI app: OCR, rule engine, auth, PDF reports, DB
├── dataset/            Synthetic label generator + ground-truth CSV + rules JSON
├── frontend/           Government-portal-style SPA (HTML/CSS/JS), 6 languages
└── README.md           You are here
```

---

## 1. Quick Start (local demo)

### Prerequisites
- Python 3.10+
- Tesseract OCR installed on the system (`sudo apt install tesseract-ocr`)
- A modern browser

### Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate      # optional but recommended
pip install -r requirements.txt

# (only once) seed demo users + 60 sample inspections for the dashboard
python3 seed_data.py

# start the API
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API is now live at `http://localhost:8000`. Interactive API docs are
auto-generated at `http://localhost:8000/docs`.

### Frontend

In a second terminal:

```bash
cd frontend
python3 -m http.server 8080
```

Open `http://localhost:8080` in your browser.

> The frontend calls the API at `http://localhost:8000` by default. To point
> it at a different backend URL (e.g. after deployment), set
> `window.LM_API_BASE = "https://your-api-host"` in a `<script>` tag before
> `js/app.js` loads in `index.html`.

### Demo login credentials

The login screen has one-tap **Quick Demo Access** cards for all four roles
below — no typing required. The same accounts also work through the manual
username/password form if you prefer:

| Username     | Password     | Role           |
|--------------|--------------|----------------|
| `inspector1` | `inspect123` | Inspector      |
| `officer1`   | `officer123` | Senior Officer |
| `analyst1`   | `analyst123` | Analyst        |
| `admin`      | `admin123`   | Admin          |

These accounts (plus 60 sample historical inspections for the dashboard) are
seeded automatically the first time the backend starts — you don't need to
run `seed_data.py` by hand, though you still can if you want to reset/reseed.

### Try a scan

Go to **Scan Product** — the page opens with a gallery of 14 bundled demo
product labels (`dataset/labels/PRD0001.png` … `PRD0014.png`, mirrored into
`frontend/assets/samples/`) that you can click to instantly load and run
through the full pipeline, no file picker needed. Each was generated with a
known mix of compliant and non-compliant declarations (see
`dataset/ground_truth.csv`), so you can demo both a fully compliant result
and several rule violations (missing address, vague net quantity, malformed
MRP wording, undersized font, etc.) live, end to end, in seconds.

You can also point a phone camera at a real product label — the OCR/rule
pipeline works on any image, though accuracy on messy real-world packaging
will depend on lighting, angle and Tesseract's language pack.

---

## 2. How the pipeline works

1. **Image capture** — user uploads/drags a label photo in the Scan page.
2. **Preprocessing** (`backend/ocr_engine.py`) — OpenCV grayscale, CLAHE
   contrast enhancement, denoising, adaptive threshold. Blur and contrast
   scores are also computed to flag poor-quality photos.
3. **OCR** — Tesseract (`pytesseract.image_to_data`) extracts text plus
   per-word bounding boxes (needed later for font-size analysis).
4. **Field classification** — a regex/heuristic layer
   (`ocr_engine.classify_fields`) turns raw OCR text into structured fields:
   product name, manufacturer, address, net quantity + unit, MRP, mfg/pack
   date, consumer care. This stands in for a document-AI model
   (LayoutLMv3/Donut) — the interface is intentionally simple to swap out.
5. **Font-size analysis** — bounding-box pixel heights are converted to mm
   (assuming a known DPI) and compared against the Legal Metrology Second
   Schedule tiers (1mm / 2mm / 4mm depending on pack size).
6. **Rule engine** (`backend/rule_engine.py`) — compares extracted fields
   against `dataset/legal_metrology_rules.json` and produces a per-rule
   PASS/FAIL, an overall compliance score, and a violations list with legal
   references.
7. **Report + dashboard** — the inspection and any violations are persisted
   to SQLite; a PDF report can be generated on demand
   (`backend/report_generator.py`); the dashboard aggregates all inspections
   for compliance-rate, top-offender and violation-type analytics, plus a
   map of inspection locations.

## 3. Swapping in production-grade models

This build intentionally uses lightweight, dependency-light components so
it runs anywhere without GPUs or API keys. For a production deployment,
the natural upgrade path (without changing the API contract) is:

| Stage                  | Demo build                  | Production upgrade                          |
|-------------------------|------------------------------|----------------------------------------------|
| Label region detection  | (not implemented — full image OCR'd directly) | YOLOv8/YOLOv11 fine-tuned on packaging photos |
| OCR                     | Tesseract                    | PaddleOCR (better for dense/rotated Indian packaging, multilingual) |
| Field classification    | Regex/heuristics             | LayoutLMv3 / Donut / a vision-language model (Qwen2.5-VL, Llama 3.2 Vision) prompted to extract structured JSON |
| Deployment DB           | SQLite                        | PostgreSQL |
| File storage            | Local disk                    | AWS S3 / MinIO |

Each of these is a drop-in replacement behind the same function signatures
in `ocr_engine.py`, so the rest of the system (rule engine, API, frontend)
does not need to change.

## 4. Multi-language support

The frontend ships with 6 languages: English, Hindi, Marathi, Tamil, Telugu
and Kannada (`frontend/locales/*.json`). The language switcher persists the
choice in `localStorage` and re-renders all static UI text and dynamic
scan/history content immediately, without a page reload. Adding a language
means adding one more `locales/<code>.json` file with the same keys as
`en.json` and registering it in `SUPPORTED_LANGS` in `frontend/js/i18n.js`.

## 5. Regenerating the sample dataset

```bash
cd dataset
python3 generate_dataset.py
```

This regenerates `dataset/labels/*.png` and `dataset/ground_truth.csv` with a
fresh (seeded, reproducible) set of compliant/non-compliant synthetic labels.

## 6. Known limitations of this demo build

- Field classification is regex-based, not a trained model — it works well
  on clearly printed labels (like the synthetic dataset) but will need a
  real document-AI model for messy, low-quality, or highly varied real-world
  packaging photography.
- Font-size analysis assumes a fixed DPI; a production system should read
  DPI from image metadata or use a reference object/ruler in the frame for
  calibration.
- Authentication is a simple JWT/bcrypt scheme for demo purposes — swap in
  your organization's SSO/Government login system for production use.
- The "GPS location" evidence field is present in the data model but not
  populated from the browser's geolocation API in this build.
