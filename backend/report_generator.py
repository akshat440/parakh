import os
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                 Paragraph, Spacer, Image as RLImage)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "generated_reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

FONTS_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")

# ReportLab's built-in fonts (Helvetica/Times) have no glyph for the Indian
# Rupee sign (U+20B9) and render a blank box instead. DejaVu Sans is bundled
# in assets/fonts/ so this renders correctly regardless of what fonts (if
# any) happen to be installed on the deploy host.
_FONTS_REGISTERED = False


def _ensure_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(FONTS_DIR, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(FONTS_DIR, "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", os.path.join(FONTS_DIR, "DejaVuSans-Oblique.ttf")))
        _FONTS_REGISTERED = True
    except Exception:
        pass  # falls back to Helvetica below -- report still generates


def _font(bold=False):
    if not _FONTS_REGISTERED:
        return "Helvetica-Bold" if bold else "Helvetica"
    return "DejaVuSans-Bold" if bold else "DejaVuSans"


# A4 is 210mm wide. With 15mm left/right margins that leaves 180mm of usable
# width -- every table below is sized to fit inside that, which is what was
# actually missing before (tables were previously wider than the page,
# causing the rightmost column to print past the margin and get clipped).
PAGE_MARGIN = 15 * mm
CONTENT_WIDTH = 210 * mm - 2 * PAGE_MARGIN  # 180mm


def generate_pdf_report(inspection, violations, image_path=None):
    _ensure_fonts()
    base_font = _font()
    bold_font = _font(bold=True)

    styles = getSampleStyleSheet()
    brand_style = ParagraphStyle("Brand", parent=styles["Normal"], fontName=bold_font,
                                  textColor=colors.HexColor("#FF9933"), fontSize=13)
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"],
                                  fontName=bold_font, textColor=colors.HexColor("#0B3D91"))
    h2 = ParagraphStyle("H2", parent=styles["Heading2"],
                         fontName=bold_font, textColor=colors.HexColor("#0B3D91"))
    normal = ParagraphStyle("NormalDV", parent=styles["Normal"], fontName=base_font, fontSize=9.5, leading=13)
    italic = ParagraphStyle("ItalicDV", parent=styles["Italic"],
                             fontName=(_font() if not _FONTS_REGISTERED else "DejaVuSans-Oblique"),
                             fontSize=8.5, textColor=colors.HexColor("#5B6472"))
    cell = ParagraphStyle("Cell", parent=normal, fontSize=9, leading=12)
    cell_bold = ParagraphStyle("CellBold", parent=cell, fontName=bold_font)
    header_cell = ParagraphStyle("HeaderCell", parent=cell, fontName=bold_font, textColor=colors.white)

    def P(text, style=cell):
        return Paragraph(str(text) if text not in (None, "") else "-", style)

    filepath = os.path.join(REPORTS_DIR, f"{inspection.report_no}.pdf")
    doc = SimpleDocTemplate(filepath, pagesize=A4,
                             topMargin=15 * mm, bottomMargin=16 * mm,
                             leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN)
    story = []

    story.append(Paragraph("PARAKH", brand_style))
    story.append(Paragraph("GOVERNMENT OF INDIA", normal))
    story.append(Paragraph("Ministry of Consumer Affairs, Food &amp; Public Distribution", normal))
    story.append(Paragraph("Legal Metrology (Packaged Commodities) Compliance Report", title_style))
    story.append(Spacer(1, 6))

    status_color = colors.HexColor("#1B873F") if inspection.compliance_status == "COMPLIANT" else colors.HexColor("#C62828")
    # Columns sum to 180mm (label, value, label, value) -- fits CONTENT_WIDTH exactly.
    meta_table_data = [
        [P("Report No.", cell_bold), P(inspection.report_no), P("Date", cell_bold), P(inspection.created_at.strftime("%d-%b-%Y"))],
        [P("Product", cell_bold), P(inspection.product_name or "-"), P("Status", cell_bold),
         Paragraph(inspection.compliance_status, ParagraphStyle("st", parent=cell_bold, textColor=status_color))],
        [P("Manufacturer", cell_bold), P(inspection.manufacturer_name or "-"), P("Score", cell_bold), P(f"{inspection.compliance_score}%")],
        [P("Inspector", cell_bold), P(inspection.inspector_name or "-"), P("Location", cell_bold), P(f"{inspection.district}, {inspection.state}")],
    ]
    t = Table(meta_table_data, colWidths=[30 * mm, 72 * mm, 24 * mm, 54 * mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8F0FE")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#E8F0FE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    if image_path and os.path.exists(image_path):
        try:
            story.append(Paragraph("Scanned Label Image", h2))
            story.append(RLImage(image_path, width=65 * mm, height=85 * mm))
            story.append(Spacer(1, 8))
        except Exception:
            pass

    story.append(Paragraph("Extracted Declarations", h2))
    decl_data = [
        [P("Field", header_cell), P("Extracted Value", header_cell)],
        [P("Product Name"), P(inspection.product_name or "NOT DETECTED")],
        [P("Manufacturer"), P(inspection.manufacturer_name or "NOT DETECTED")],
        [P("Address"), P(inspection.manufacturer_address or "NOT DETECTED")],
        [P("Net Quantity"), P(f"{inspection.net_quantity_value or ''} {inspection.net_quantity_unit or ''}".strip() or "NOT DETECTED")],
        [P("MRP"), P(f"Rs. {inspection.mrp}" if inspection.mrp else "NOT DETECTED")],
        [P("Mfg/Packing Date"), P(inspection.mfg_date or "NOT DETECTED")],
        [P("Consumer Care"), P(inspection.consumer_care or "NOT DETECTED")],
    ]
    dt = Table(decl_data, colWidths=[45 * mm, CONTENT_WIDTH - 45 * mm])
    dt.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(dt)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Violation Summary", h2))
    if violations:
        v_data = [[P("Rule", header_cell), P("Reference", header_cell),
                   P("Severity", header_cell), P("Description", header_cell)]]
        for v in violations:
            sev_color = colors.HexColor("#C62828") if v["severity"] == "HIGH" else colors.HexColor("#B8860B")
            v_data.append([
                P(v["rule_title"]), P(v["reference"]),
                Paragraph(v["severity"], ParagraphStyle("sev", parent=cell_bold, textColor=sev_color)),
                P(v["description"]),
            ])
        vt = Table(v_data, colWidths=[32 * mm, 32 * mm, 20 * mm, CONTENT_WIDTH - 84 * mm])
        vt.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B00020")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(vt)
    else:
        story.append(Paragraph("No violations detected. Package is fully compliant.", normal))

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "This report is auto-generated by the AI-based Legal Metrology Compliance "
        "System. Findings should be verified by an authorized Legal Metrology Officer "
        "before initiating enforcement action.", italic))

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(base_font, 7.5)
        canvas.setFillColor(colors.HexColor("#5B6472"))
        canvas.drawString(PAGE_MARGIN, 10 * mm,
                           f"Generated {datetime.datetime.utcnow().strftime('%d-%b-%Y %H:%M UTC')} "
                           f"\u2022 Report {inspection.report_no}")
        canvas.drawRightString(A4[0] - PAGE_MARGIN, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return filepath
