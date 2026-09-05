"""
Rule-Based Compliance Engine
-----------------------------
Step 6 of the pipeline: compares AI-extracted fields against the
Legal Metrology (Packaged Commodities) Rules, 2011 and produces a
pass/fail verdict per declaration plus an overall compliance score.
"""
import json
import os
from ocr_engine import min_required_mm

RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "dataset",
                           "legal_metrology_rules.json")

with open(RULES_PATH, "r") as f:
    RULES = {r["id"]: r for r in json.load(f)["rules"]}


def check_compliance(fields: dict, qty_font_boxes: list):
    """
    fields: output of ocr_engine.classify_fields()
    qty_font_boxes: output of ocr_engine.net_qty_font_heights() -- the
        bounding boxes specifically for the net-quantity declaration, which
        is what the Second Schedule's tiered minimum letter-height rule
        actually governs (not every word on the label).
    Returns dict: {checks: [...], violations: [...], score, status}
    """
    checks = []
    violations = []

    def fail(rule_id, extra=""):
        r = RULES[rule_id]
        violations.append({
            "rule_id": rule_id,
            "rule_title": r["title"],
            "reference": r["reference"],
            "description": r["description"] + (f" {extra}" if extra else ""),
            "severity": r["severity"],
        })
        checks.append({"rule_id": rule_id, "title": r["title"], "result": "FAIL"})

    def ok(rule_id):
        r = RULES[rule_id]
        checks.append({"rule_id": rule_id, "title": r["title"], "result": "PASS"})

    # R1 Product Name
    if fields.get("product_name"):
        ok("R1_PRODUCT_NAME")
    else:
        fail("R1_PRODUCT_NAME")

    # R2 Manufacturer name
    if fields.get("manufacturer_name"):
        ok("R2_MANUFACTURER_NAME")
    else:
        fail("R2_MANUFACTURER_NAME")

    # R3 Manufacturer address
    if fields.get("manufacturer_address"):
        ok("R3_MANUFACTURER_ADDRESS")
    else:
        fail("R3_MANUFACTURER_ADDRESS", "No address block detected near manufacturer name.")

    # R4 Net quantity (must have numeric value + valid unit)
    if fields.get("net_quantity_value") and fields.get("net_quantity_unit"):
        ok("R4_NET_QUANTITY")
    else:
        extra = ""
        if fields.get("net_quantity_raw") and not fields.get("net_quantity_value"):
            extra = f"Found non-standard declaration: '{fields['net_quantity_raw']}'."
        fail("R4_NET_QUANTITY", extra)

    # R5 MRP
    if fields.get("mrp_value") and fields.get("mrp_compliant_phrase"):
        ok("R5_MRP")
    elif fields.get("mrp_value") and not fields.get("mrp_compliant_phrase"):
        fail("R5_MRP", "MRP figure found but missing '₹' symbol and/or 'inclusive of all taxes' wording.")
    else:
        fail("R5_MRP", "No MRP declaration detected.")

    # R6 Mfg/Packing date
    if fields.get("mfg_date"):
        ok("R6_MFG_DATE")
    else:
        fail("R6_MFG_DATE")

    # R7 Consumer care
    if fields.get("consumer_care"):
        ok("R7_CONSUMER_CARE")
    else:
        fail("R7_CONSUMER_CARE")

    # R8 Font size -- checked specifically against the net-quantity
    # declaration's bounding boxes (see net_qty_font_heights docstring)
    required_mm = min_required_mm(fields.get("net_quantity_value"), fields.get("net_quantity_unit"))
    undersized = [b for b in qty_font_boxes if 0 < b["height_mm"] < required_mm]
    if qty_font_boxes and not undersized:
        ok("R8_FONT_SIZE")
    elif undersized:
        worst = min(undersized, key=lambda b: b["height_mm"])
        fail("R8_FONT_SIZE",
             f"Net quantity text '{worst['text']}' measured ~{worst['height_mm']}mm; "
             f"minimum required is {required_mm}mm for this pack size.")
    else:
        ok("R8_FONT_SIZE")  # no matching boxes found -> don't penalize in this lightweight demo

    total = len(checks)
    passed = sum(1 for c in checks if c["result"] == "PASS")
    score = round((passed / total) * 100, 1) if total else 0.0
    status = "COMPLIANT" if not violations else "NON_COMPLIANT"

    return {
        "checks": checks,
        "violations": violations,
        "score": score,
        "status": status,
    }


def all_rules():
    return list(RULES.values())
