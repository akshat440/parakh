"""
Synthetic Label Dataset Generator
----------------------------------
Generates realistic-looking packaged-commodity label images (front-of-pack
style) with KNOWN ground truth, so the OCR + Rule Engine pipeline can be
demoed and evaluated end-to-end without needing to source real product
photography (which would raise copyright/trademark concerns for a demo).

Each generated label deliberately contains a mix of:
  - Fully compliant declarations
  - Missing declarations (manufacturer address, consumer care, date, etc.)
  - Malformed declarations (no unit on net quantity, MRP without
    "inclusive of taxes", bad date format)
  - Undersized font for one field (to exercise font-size-analysis)

Output:
  dataset/labels/<product_id>.png      -> the label image
  dataset/ground_truth.csv             -> what SHOULD be detected + violations
"""

import csv
import json
import os
import random
import shutil
from PIL import Image, ImageDraw, ImageFont

random.seed(42)

OUT_DIR = os.path.join(os.path.dirname(__file__), "labels")
os.makedirs(OUT_DIR, exist_ok=True)

DPI = 150  # assumed print resolution, used later for mm<->px conversion
MM_PER_INCH = 25.4
PX_PER_MM = DPI / MM_PER_INCH

# Try to get a real TTF; fall back to default bitmap font if unavailable.
def get_font(size_px):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return ImageFont.truetype(c, size_px)
    return ImageFont.load_default()


MANUFACTURERS = [
    ("Nestlé Foods India Pvt. Ltd.", "Plot 12, Industrial Area, Gurugram, Haryana - 122001"),
    ("Amul Dairy Cooperative Ltd.", "Amul Dairy Road, Anand, Gujarat - 388001"),
    ("BPL Electro Appliances Ltd.", "Unit-7, Survey No.57/3, Daman & Diu - 396210"),
    ("Radhika Opto Electronics Ltd.", "Survey No. 57/2, Daman, Dadra & Nagar Haveli - 396210"),
    ("Patanjali Ayurved Ltd.", "Patanjali Food & Herbal Park, Haridwar, Uttarakhand - 249404"),
    ("ABC Foods Pvt. Ltd.", None),  # address missing on purpose (violation)
]

PRODUCTS = [
    ("Choco Delight Biscuits", "g", [70, 100, 150, 200, 500]),
    ("Basmati Rice Premium", "kg", [1, 5, 10]),
    ("Herbal Shampoo", "ml", [180, 340, 650]),
    ("Refined Sunflower Oil", "L", [1, 2, 5]),
    ("Washing Detergent Powder", "kg", [1, 2, 4]),
    ("LED Bulb 18W", "Nos.", [1, 2, 4]),  # count-based item -> declared as "Nos." (number of pieces)
]

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def mm_to_px(mm):
    return int(round(mm * PX_PER_MM))


def wrap_text_to_width(draw, text, font, max_width_px):
    """Word-wrap text so it never overflows max_width_px.

    draw.text() does not clip or wrap on its own -- text that's wider than
    the image simply gets cut off silently at the canvas edge. For a
    longer manufacturer address this was truncating the trailing digits of
    the pincode, which fed a genuinely-present address into the OCR/rule
    pipeline as a partial line with no digits in it, in turn producing a
    false "missing address" (R3) violation on an otherwise fully compliant
    label. Wrapping onto as many lines as needed keeps the full text on
    the visible canvas.
    """
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width_px or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def required_font_mm(value, unit):
    """Mirrors backend/ocr_engine.py:min_required_mm -- kept as a standalone
    copy here so the dataset generator has no import dependency on the
    backend package. A 'compliant' generated label must use a net-quantity
    font at or above this tier so it is actually compliant, not just
    labelled that way."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    unit = (unit or "").lower()
    grams_or_ml = v * 1000 if unit in ("kg", "l", "litre", "litres") else v
    if grams_or_ml <= 200:
        return 1.0
    elif grams_or_ml <= 1000:
        return 2.0
    else:
        return 4.0


def draw_label(product_id, defects):
    """defects: set of strings describing which declarations to break/omit"""
    W, H = mm_to_px(105), mm_to_px(120)  # ~105x120mm pack face
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    name, unit, qty_options = random.choice(PRODUCTS)
    mfr_name, mfr_addr = random.choice(MANUFACTURERS)

    if "small_font_qty" in defects:
        # The undersized-font demo needs a pack size/unit string that
        # Tesseract can still OCR correctly at a font smaller than the
        # legal minimum. Empirically, very short strings like "1 L" or
        # "500 g" garble badly below ~2mm, while multi-digit quantities in
        # the 4mm tier (>1000 g/ml) stay legible down to ~1.7-2.0mm and
        # leave clear headroom below their legal minimum. Restrict to
        # that tier and use a fixed, tested-legible 2.0mm font below.
        eligible = [(n, u, [q for q in opts if required_font_mm(q, u) >= 4.0])
                    for n, u, opts in PRODUCTS]
        eligible = [(n, u, opts) for n, u, opts in eligible if opts]
        name, unit, qty_options = random.choice(eligible)

    qty = random.choice(qty_options) if qty_options else None

    y = mm_to_px(6)
    pad = mm_to_px(5)

    # Border (simulate pack edge)
    d.rectangle([2, 2, W - 3, H - 3], outline="black", width=2)

    # ---- Product name ----
    if "missing_name" not in defects:
        f = get_font(mm_to_px(6))
        d.text((pad, y), name, font=f, fill="black")
    y += mm_to_px(10)

    # ---- Manufacturer ----
    if "missing_manufacturer" not in defects:
        f = get_font(mm_to_px(3.2))
        d.text((pad, y), f"Mfg by: {mfr_name}", font=f, fill="black")
        y += mm_to_px(5)
        if mfr_addr and "missing_address" not in defects:
            max_width = W - 2 * pad
            addr_lines = wrap_text_to_width(d, mfr_addr, f, max_width)
            for line in addr_lines:
                d.text((pad, y), line, font=f, fill="black")
                y += mm_to_px(4.2)
            y += mm_to_px(1.8)
        else:
            y += mm_to_px(6)
    else:
        y += mm_to_px(11)

    # ---- Net quantity ----
    if qty is not None:
        if "malformed_qty" in defects:
            qty_text = f"Net Qty: Large Pack"
        else:
            qty_text = f"Net Qty: {qty} {unit}"
        # Size the net-quantity font at a comfortable margin above whatever
        # this specific pack size legally requires (1/2/4mm tiers), so a
        # "compliant" label is genuinely compliant regardless of pack size.
        # The "small_font_qty" defect uses a fixed 2.0mm font -- tested to
        # OCR reliably for the 4mm-tier quantities the eligible-product
        # filter above restricts this defect to, while still sitting
        # clearly below their 4mm legal minimum. (Below ~1.7mm, short
        # strings like "1 L" or "500 g" start garbling under Tesseract,
        # which would make the declaration read as "missing" rather than
        # "undersized" -- the wrong violation for this demo case.)
        if "small_font_qty" in defects:
            font_mm = 2.0
        else:
            # +2.5mm (not +1.0mm) margin above the legal minimum. Digit
            # glyphs in this font render shorter than their nominal point
            # size -- e.g. a "10" set at a nominal 5mm font measured only
            # ~3.7mm tall by OCR -- so a smaller margin left some
            # genuinely-compliant labels measuring just under their legal
            # minimum and failing R8 by accident. This margin was set
            # empirically comfortable across all digit/unit combinations
            # in this dataset (see dataset regression check).
            font_mm = required_font_mm(qty, unit) + 2.5
        f = get_font(mm_to_px(font_mm))
        if "missing_qty" not in defects:
            d.text((pad, y), qty_text, font=f, fill="black")
        y += mm_to_px(7)

    # ---- MRP ----
    mrp_val = random.choice([20, 45, 55, 99, 149, 299, 599])
    if "missing_mrp" not in defects:
        if "malformed_mrp" in defects:
            mrp_text = f"Price Rs. {mrp_val}"  # missing ₹ symbol + "incl of taxes"
        else:
            mrp_text = f"MRP ₹{mrp_val} (Inclusive of all taxes)"
        f = get_font(mm_to_px(3.5))
        d.text((pad, y), mrp_text, font=f, fill="black")
    y += mm_to_px(7)

    # ---- Mfg/Packing date ----
    month = random.choice(MONTHS)
    yr = random.choice([2025, 2026])
    if "missing_date" not in defects:
        if "malformed_date" in defects:
            date_text = "Best before 6 months"  # no explicit mfg/pack date
        else:
            date_text = f"Packed: {month} {yr}"
        f = get_font(mm_to_px(3))
        d.text((pad, y), date_text, font=f, fill="black")
    y += mm_to_px(6)

    # ---- Consumer care ----
    if "missing_care" not in defects:
        f = get_font(mm_to_px(2.6))
        d.text((pad, y), "Consumer Care: 1800-123-4567, care@example.com",
                font=f, fill="black")
    y += mm_to_px(6)

    img.save(os.path.join(OUT_DIR, f"{product_id}.png"))

    return {
        "product_id": product_id,
        "product_name": name if "missing_name" not in defects else "",
        "manufacturer_name": mfr_name if "missing_manufacturer" not in defects else "",
        "manufacturer_address": (mfr_addr or "") if "missing_manufacturer" not in defects and "missing_address" not in defects else "",
        "net_quantity_value": qty if qty is not None else "",
        "net_quantity_unit": unit if unit else "",
        "mrp": mrp_val,
        "mfg_month_year": f"{month} {yr}",
        "defects": ";".join(sorted(defects)) if defects else "none",
    }


DEFECT_POOL = [
    set(),  # fully compliant
    {"missing_address"},
    {"missing_manufacturer"},
    {"malformed_qty"},
    {"missing_mrp"},
    {"malformed_mrp"},
    {"missing_date"},
    {"malformed_date"},
    {"missing_care"},
    {"small_font_qty"},
    {"missing_address", "malformed_mrp"},
    {"missing_care", "missing_date"},
    set(),
    set(),
]


DEFECT_LABELS = {
    "missing_address": "Manufacturer address missing",
    "missing_manufacturer": "Manufacturer name missing",
    "malformed_qty": "Vague / non-standard net quantity",
    "missing_mrp": "MRP declaration missing",
    "malformed_mrp": "MRP missing 'inclusive of taxes' wording",
    "missing_date": "Manufacturing/packing date missing",
    "malformed_date": "Malformed date declaration",
    "missing_care": "Consumer care details missing",
    "small_font_qty": "Font size below legal minimum",
}

FRONTEND_SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets", "samples")


def build_manifest_entry(row):
    is_compliant = row["defects"] == "none"
    if is_compliant:
        hint = "Fully compliant label"
    else:
        parts = [DEFECT_LABELS.get(d, d) for d in row["defects"].split(";")]
        hint = "; ".join(parts) if len(parts) == 1 else f"Multiple violations: {', '.join(parts)}"
    return {
        "id": row["product_id"],
        "file": f"{row['product_id']}.png",
        "title": row["product_name"],
        "manufacturer": row["manufacturer_name"] or "Unknown",
        "expected": "COMPLIANT" if is_compliant else "NON_COMPLIANT",
        "hint": hint,
    }


def main():
    rows = []
    for i, defects in enumerate(DEFECT_POOL, start=1):
        pid = f"PRD{i:04d}"
        rows.append(draw_label(pid, defects))

    csv_path = os.path.join(os.path.dirname(__file__), "ground_truth.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} label images in {OUT_DIR}")
    print(f"Ground truth written to {csv_path}")

    # Keep the frontend's bundled demo gallery in sync automatically: copy
    # the freshly generated images and (re)write manifest.json from the same
    # in-memory rows, so the gallery never drifts out of sync with the
    # dataset the way a hand-maintained copy would.
    if os.path.isdir(os.path.join(os.path.dirname(__file__), "..", "frontend")):
        os.makedirs(FRONTEND_SAMPLES_DIR, exist_ok=True)
        for row in rows:
            src = os.path.join(OUT_DIR, f"{row['product_id']}.png")
            dst = os.path.join(FRONTEND_SAMPLES_DIR, f"{row['product_id']}.png")
            shutil.copyfile(src, dst)

        manifest = [build_manifest_entry(r) for r in rows]
        manifest.sort(key=lambda m: (m["expected"] != "COMPLIANT",))
        manifest_path = os.path.join(FRONTEND_SAMPLES_DIR, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"Synced {len(rows)} sample images + manifest.json to {FRONTEND_SAMPLES_DIR}")


if __name__ == "__main__":
    main()
