"""
OCR & Information Extraction Engine
------------------------------------
Implements Steps 2, 4 and 5 of the pipeline described in the project spec:
  - Image preprocessing (OpenCV: grayscale, denoise, contrast, deskew)
  - OCR text extraction (Tesseract via pytesseract)
  - AI-based field classification (regex/heuristic "document understanding"
    layer that plays the role of LayoutLM/Donut in this lightweight demo
    build -- swap-in-ready for a transformer model in production)
  - Font-size analysis (bounding-box height -> mm, compared against the
    Legal Metrology Second Schedule thresholds)
"""
import re
import io
import cv2
import numpy as np
import pytesseract
from PIL import Image

ASSUMED_DPI = 150  # must match generator; in production, read from EXIF/scan settings
MM_PER_INCH = 25.4


def px_to_mm(px, dpi=ASSUMED_DPI):
    return (px / dpi) * MM_PER_INCH


# ---------------------------------------------------------------------------
# Step 2: Image preprocessing
# ---------------------------------------------------------------------------
def preprocess_variants(image_bytes: bytes):
    """Returns a list of (name, processed_img) candidate preprocessings,
    plus the raw grayscale image (used for blur/contrast scoring).

    A single fixed pipeline (CLAHE + denoise + adaptive threshold) works
    well for the flat, evenly-lit synthetic labels this project generates,
    but measurably HURTS OCR quality on real product photography -- glossy
    jars, busy multi-colour packaging and photographed (not scanned) labels
    lose more legibility to the binarization step than they gain from it.
    Returning multiple candidates lets the caller OCR each one and keep
    whichever variant actually extracted more fields, instead of committing
    up front to one preprocessing strategy that only suits synthetic input.
    """
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    denoised = cv2.fastNlMeansDenoising(enhanced, h=7)
    thresholded = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )

    variants = [
        ("threshold", thresholded),  # best for flat, scanned/synthetic labels
        ("clahe_only", enhanced),    # best for photographed real packaging
    ]
    return variants, gray


def preprocess_image(image_bytes: bytes):
    """Back-compat single-pipeline entry point (adaptive-threshold image +
    grayscale). Prefer run_ocr_best() for new callers -- it tries multiple
    preprocessing variants and keeps whichever extracts more fields."""
    variants, gray = preprocess_variants(image_bytes)
    thresholded = dict(variants)["threshold"]
    return thresholded, gray


def blur_score(gray: np.ndarray) -> float:
    """Laplacian variance -- lower means blurrier."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def contrast_score(gray: np.ndarray) -> float:
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    hist /= hist.sum() + 1e-9
    # simple spread metric: std dev of pixel intensities
    return float(gray.std())


# ---------------------------------------------------------------------------
# Step 4: OCR
# ---------------------------------------------------------------------------
def run_ocr(processed_img: np.ndarray):
    """Returns (full_text, list_of_word_boxes[{text,left,top,width,height,conf}])"""
    config = "--oem 3 --psm 6"
    data = pytesseract.image_to_data(processed_img, config=config,
                                      output_type=pytesseract.Output.DICT)
    full_text = pytesseract.image_to_string(processed_img, config=config)

    boxes = []
    n = len(data["text"])
    for i in range(n):
        txt = data["text"][i].strip()
        if not txt:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        boxes.append({
            "text": txt,
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
            "height": data["height"][i],
            "conf": conf,
        })
    return full_text, boxes


# ---------------------------------------------------------------------------
# Step 5: AI-based field classification (regex/heuristic "document AI")
# ---------------------------------------------------------------------------
UNIT_PATTERN = r"(?:kg|gm|gms|g|ml|mL|litres|litre|L|l|Nos\.?|Pieces?|Pcs\.?|N)\b"

RE_NET_QTY = re.compile(
    r"(?:Net\s*Qty|Net\s*Quantity|Net\s*Wt|Net\s*Weight)\s*[:\-]?\s*"
    r"([\d.]+)\s*(" + UNIT_PATTERN + r")",
    re.IGNORECASE,
)
RE_NET_QTY_VAGUE = re.compile(
    r"(?:Net\s*Qty|Net\s*Quantity)\s*[:\-]?\s*([A-Za-z ]{3,20})", re.IGNORECASE)

RE_MRP_GOOD = re.compile(
    r"(?:MRP)?\s*[₹Rs\.]{0,4}\s*(\d{1,6}(?:\.\d{1,2})?)\s*"
    r"\(?\s*(Incl(?:usive)?\.?\s*of\s*all\s*taxes)\s*\)?",
    re.IGNORECASE,
)
RE_MRP_ANY = re.compile(r"(?:MRP|Price|Rs\.?|₹)\s*[:\-]?\s*[₹]?\s*(\d{1,6})", re.IGNORECASE)

RE_DATE_GOOD = re.compile(
    r"(?:Pack(?:ed|ing)?|Mfg|Manufactured|Mfd)\.?\s*(?:on|date)?\s*[:\-]?\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{1,2}/\d{4})",
    re.IGNORECASE,
)

RE_MFG_LINE = re.compile(
    r"(?:Mfg\.?\s*by|Manufactured\s*by|Packed\s*by|Marketed\s*by)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)

RE_CARE = re.compile(
    r"(Consumer\s*Care|Customer\s*Care).{0,80}",
    re.IGNORECASE,
)

RE_PHONE_OR_EMAIL = re.compile(r"(\d{4}[- ]?\d{3}[- ]?\d{4}|[\w.+-]+@[\w-]+\.[\w.-]+)")


def classify_fields(full_text: str, boxes):
    """Heuristic field classifier -- stands in for a LayoutLM/Donut model."""
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]
    result = {
        "product_name": "",
        "manufacturer_name": "",
        "manufacturer_address": "",
        "net_quantity_value": "",
        "net_quantity_unit": "",
        "net_quantity_raw": "",
        "mrp_value": "",
        "mrp_compliant_phrase": False,
        "mfg_date": "",
        "consumer_care": "",
    }

    # Product name heuristic: first substantial line that isn't a keyworded field
    keyword_markers = ["mfg", "manufactur", "net qty", "net quantity", "mrp",
                        "price", "packed", "consumer care", "customer care", "rs.", "₹"]
    for l in lines:
        low = l.lower()
        if len(l) > 3 and not any(k in low for k in keyword_markers):
            result["product_name"] = l
            break

    # Manufacturer
    m = RE_MFG_LINE.search(full_text)
    if m:
        result["manufacturer_name"] = m.group(1).strip()
        # naive address: scan the next few NON-BLANK lines (labels often have
        # a blank line or two of vertical spacing between the manufacturer
        # name and the address block, so blank lines must be skipped rather
        # than counted as one of the "next lines")
        idx = full_text.find(m.group(0))
        after_lines = [l.strip() for l in full_text[idx + len(m.group(0)):].splitlines()]
        non_blank = [l for l in after_lines if l]
        # A line that itself matches one of the OTHER known declaration
        # patterns (net qty, MRP, date, consumer care) is never the address
        # -- without this check, a label that genuinely has no address line
        # prints (say) "Net Qty: 10 kg" directly under the manufacturer
        # name, and the old digit-and-length heuristic below would wrongly
        # grab that as the "address" (it has a digit and is >8 chars),
        # masking a real R3 missing-address violation.
        other_field_patterns = (RE_NET_QTY, RE_NET_QTY_VAGUE, RE_MRP_GOOD,
                                 RE_MRP_ANY, RE_DATE_GOOD, RE_CARE)
        for l in non_blank[:3]:
            if any(p.search(l) for p in other_field_patterns):
                continue
            if len(l) > 8 and re.search(r"\d", l):
                result["manufacturer_address"] = l
                break

    # Net quantity
    m = RE_NET_QTY.search(full_text)
    if m:
        result["net_quantity_value"] = m.group(1)
        result["net_quantity_unit"] = m.group(2)
        result["net_quantity_raw"] = m.group(0)
    else:
        m2 = RE_NET_QTY_VAGUE.search(full_text)
        if m2:
            result["net_quantity_raw"] = m2.group(1).strip()

    # MRP
    m = RE_MRP_GOOD.search(full_text)
    if m:
        result["mrp_value"] = m.group(1)
        result["mrp_compliant_phrase"] = True
    else:
        m2 = RE_MRP_ANY.search(full_text)
        if m2:
            result["mrp_value"] = m2.group(1)
            result["mrp_compliant_phrase"] = False

    # Date
    m = RE_DATE_GOOD.search(full_text)
    if m:
        result["mfg_date"] = m.group(1).strip()

    # Consumer care
    m = RE_CARE.search(full_text)
    if m:
        snippet = m.group(0)
        contact = RE_PHONE_OR_EMAIL.search(snippet)
        result["consumer_care"] = snippet.strip() if contact else ""

    return result


def _field_richness(fields: dict) -> int:
    """Counts how many declaration fields a classification actually
    populated. mrp_compliant_phrase is a boolean flag, not a detected
    value, so it's excluded -- otherwise its default `False` would
    silently count as "detected" and bias the comparison."""
    return sum(1 for k, v in fields.items() if k != "mrp_compliant_phrase" and v)


def run_ocr_best(image_bytes: bytes):
    """Runs OCR + field classification against every preprocessing variant
    from preprocess_variants() and keeps whichever one actually extracted
    the most declaration fields, rather than committing to a single fixed
    preprocessing pipeline that only suits one kind of input (see
    preprocess_variants docstring for why this matters on real photos).

    Returns (full_text, boxes, fields, gray, variant_name).
    """
    variants, gray = preprocess_variants(image_bytes)
    candidates = []
    for name, processed in variants:
        full_text, boxes = run_ocr(processed)
        fields = classify_fields(full_text, boxes)
        candidates.append({
            "name": name, "full_text": full_text, "boxes": boxes,
            "fields": fields, "score": _field_richness(fields),
        })
    best = max(candidates, key=lambda c: c["score"])
    return best["full_text"], best["boxes"], best["fields"], gray, best["name"]


# ---------------------------------------------------------------------------
# Step: Font size analysis
# ---------------------------------------------------------------------------
def min_required_mm(net_qty_value, net_qty_unit):
    """Second Schedule tiered minimum font height requirement."""
    try:
        v = float(net_qty_value)
    except (TypeError, ValueError):
        return 1.0
    unit = (net_qty_unit or "").lower()
    grams_or_ml = v
    if unit in ("kg", "l", "litre", "litres"):
        grams_or_ml = v * 1000
    if grams_or_ml <= 200:
        return 1.0
    elif grams_or_ml <= 1000:
        return 2.0
    else:
        return 4.0


def net_qty_font_heights(fields: dict, font_analysis: list):
    """
    The Second Schedule's tiered minimum-letter-height requirement applies
    specifically to the net quantity declaration -- not to every word on the
    label (manufacturer address, consumer care and date text are governed by
    separate, less prescriptive legibility rules). Scanning every OCR'd word
    against the tiered threshold produces false positives (e.g. a
    hyphen-in-address or a small "Consumer Care" line failing a check that
    was never meant to apply to it). This isolates just the bounding boxes
    that correspond to the extracted net-quantity value/unit tokens.
    """
    value = str(fields.get("net_quantity_value") or "").strip()
    unit = str(fields.get("net_quantity_unit") or "").strip().lower()
    if not value and not unit:
        return []
    matches = []
    for b in font_analysis:
        # strip common punctuation so "kg" vs "kg," or "180" vs "180ml" (if
        # tesseract merges tokens) still line up, but require the whole
        # cleaned token to equal the value/unit -- never a loose substring
        # match, which previously caused false hits (e.g. the "5" in a
        # phone number "1800-123-4567" spuriously matching a "5 kg" net
        # quantity).
        cleaned = b["text"].strip().strip(".,()%").lower()
        combined = f"{value}{unit}".lower()
        if value and cleaned == value.lower():
            matches.append(b)
        elif unit and cleaned == unit.lower():
            matches.append(b)
        elif combined and cleaned == combined:
            # Tesseract sometimes merges an unspaced "2L"/"180ml" into one
            # token rather than two -- still the net-quantity declaration,
            # so it must count as a match rather than being silently
            # dropped (which previously made a genuinely undersized font
            # look like a missing declaration).
            matches.append(b)
    return matches


def analyze_font_sizes(boxes, dpi=ASSUMED_DPI):
    """Returns list of {text, height_mm} for words with reasonable confidence.

    Punctuation-only tokens (hyphens, commas, single brackets, etc.) are
    excluded: their bounding boxes are inherently short (a hyphen glyph is a
    thin horizontal stroke, not a full character height) and would otherwise
    trigger false-positive font-size violations that have nothing to do with
    how legibly the actual declaration text is printed.
    """
    out = []
    for b in boxes:
        if b["conf"] < 0:
            continue
        # Require at least 2 alphanumeric characters for a token to count
        # as "declaration text" subject to the minimum font-size rule.
        alnum_chars = [c for c in b["text"] if c.isalnum()]
        if len(alnum_chars) < 2:
            continue
        out.append({
            "text": b["text"],
            "height_px": b["height"],
            "height_mm": round(px_to_mm(b["height"], dpi), 2),
        })
    return out
