import os
import datetime
import random
from typing import Optional

import jwt
import bcrypt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import Base, engine, get_db
import models
import ocr_engine
import rule_engine
import report_generator
import seed_data

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Parakh - Legal Metrology Compliance API", version="1.0.0")


@app.on_event("startup")
def _seed_demo_data_on_startup():
    """Ensure the 4 demo login accounts (and sample inspection history)
    always exist, even on a fresh/empty database (new deploy, cleared DB,
    etc). Without this, a missing/empty DB makes every login fail with a
    generic 'Invalid username or password' with no obvious cause.
    seed_data.seed() is idempotent -- it checks for existing users/
    inspections and no-ops if they're already there -- so this is safe to
    run on every startup."""
    try:
        seed_data.seed()
    except Exception as exc:  # never block API startup over seeding
        print(f"[startup] demo data seeding skipped: {exc}")

ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("LM_ALLOWED_ORIGINS", "*").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.environ.get("LM_SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def create_token(user: models.User):
    payload = {
        "sub": user.username,
        "role": user.role,
        "full_name": user.full_name,
        "uid": user.id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=12),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(models.User).filter(models.User.username == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@app.post("/api/auth/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == username).first()
    valid = user and bcrypt.checkpw(password.encode("utf-8"), user.hashed_password.encode("utf-8"))
    if not valid:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "state": user.state,
        },
    }


@app.get("/api/auth/me")
def me(user: models.User = Depends(get_current_user)):
    return {"username": user.username, "full_name": user.full_name,
            "role": user.role, "state": user.state}


# ---------------------------------------------------------------------------
# Rules reference
# ---------------------------------------------------------------------------
@app.get("/api/rules")
def get_rules():
    return rule_engine.all_rules()


# ---------------------------------------------------------------------------
# Scan pipeline
# ---------------------------------------------------------------------------
INDIA_STATE_COORDS = {
    "Madhya Pradesh": (23.2599, 77.4126), "Maharashtra": (19.7515, 75.7139),
    "Delhi": (28.7041, 77.1025), "Karnataka": (15.3173, 75.7139),
    "Tamil Nadu": (11.1271, 78.6569),
}


@app.post("/api/scan")
async def scan_product(
    file: UploadFile = File(...),
    state: str = Form("Madhya Pradesh"),
    district: str = Form("Bhopal"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    contents = await file.read()

    # Persist original image
    ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    saved_name = f"{ts}_{file.filename}"
    saved_path = os.path.join(UPLOAD_DIR, saved_name)
    with open(saved_path, "wb") as f:
        f.write(contents)

    # Steps 2, 4, 5: preprocess, OCR, classify -- tries multiple
    # preprocessing variants and keeps whichever extracted more fields
    # (see ocr_engine.run_ocr_best / preprocess_variants docstrings)
    full_text, boxes, fields, gray_img, variant_used = ocr_engine.run_ocr_best(contents)
    blur = ocr_engine.blur_score(gray_img)
    contrast = ocr_engine.contrast_score(gray_img)

    # Font size analysis (full word list, returned to the client for
    # transparency/debugging) and the net-quantity-specific subset that the
    # rule engine actually checks against the Second Schedule thresholds
    font_analysis = ocr_engine.analyze_font_sizes(boxes)
    qty_font_boxes = ocr_engine.net_qty_font_heights(fields, font_analysis)

    # Step 6: rule engine
    result = rule_engine.check_compliance(fields, qty_font_boxes)

    report_no = f"LM{ts}"
    lat, lng = INDIA_STATE_COORDS.get(state, (22.9734, 78.6569))
    lat += random.uniform(-0.4, 0.4)
    lng += random.uniform(-0.4, 0.4)

    insp = models.Inspection(
        report_no=report_no,
        product_name=fields.get("product_name", ""),
        manufacturer_name=fields.get("manufacturer_name", ""),
        manufacturer_address=fields.get("manufacturer_address", ""),
        net_quantity_value=fields.get("net_quantity_value", ""),
        net_quantity_unit=fields.get("net_quantity_unit", ""),
        mrp=fields.get("mrp_value", ""),
        mfg_date=fields.get("mfg_date", ""),
        consumer_care=fields.get("consumer_care", ""),
        raw_ocr_text=full_text,
        image_path=saved_path,
        inspector_id=user.id,
        inspector_name=user.full_name,
        state=state,
        district=district,
        latitude=lat,
        longitude=lng,
        compliance_status=result["status"],
        compliance_score=result["score"],
    )
    db.add(insp)
    db.flush()

    for v in result["violations"]:
        db.add(models.Violation(
            inspection_id=insp.id, rule_id=v["rule_id"], rule_title=v["rule_title"],
            reference=v["reference"], description=v["description"], severity=v["severity"],
        ))
    db.commit()
    db.refresh(insp)

    return {
        "inspection_id": insp.id,
        "report_no": insp.report_no,
        "image_quality": {
            "blur_score": round(blur, 1),
            "contrast_score": round(contrast, 1),
            "blur_flag": blur < 40,
            "contrast_flag": contrast < 35,
        },
        "ocr_text": full_text,
        "extracted_fields": fields,
        "font_analysis": font_analysis[:30],
        "compliance": result,
        "status": insp.compliance_status,
        "score": insp.compliance_score,
    }


# ---------------------------------------------------------------------------
# Inspections / history
# ---------------------------------------------------------------------------
@app.get("/api/inspections")
def list_inspections(
    status_filter: Optional[str] = None,
    state: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = db.query(models.Inspection)
    if status_filter:
        query = query.filter(models.Inspection.compliance_status == status_filter)
    if state:
        query = query.filter(models.Inspection.state == state)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (models.Inspection.product_name.ilike(like)) |
            (models.Inspection.manufacturer_name.ilike(like)) |
            (models.Inspection.report_no.ilike(like))
        )
    rows = query.order_by(models.Inspection.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "report_no": r.report_no, "product_name": r.product_name,
            "manufacturer_name": r.manufacturer_name, "state": r.state,
            "district": r.district, "compliance_status": r.compliance_status,
            "compliance_score": r.compliance_score, "inspector_name": r.inspector_name,
            "created_at": r.created_at.isoformat(),
            "latitude": r.latitude, "longitude": r.longitude,
        } for r in rows
    ]


@app.get("/api/inspections/{inspection_id}")
def get_inspection(inspection_id: int, db: Session = Depends(get_db),
                    user: models.User = Depends(get_current_user)):
    insp = db.query(models.Inspection).filter(models.Inspection.id == inspection_id).first()
    if not insp:
        raise HTTPException(404, "Inspection not found")
    return {
        "id": insp.id, "report_no": insp.report_no, "product_name": insp.product_name,
        "manufacturer_name": insp.manufacturer_name, "manufacturer_address": insp.manufacturer_address,
        "net_quantity_value": insp.net_quantity_value, "net_quantity_unit": insp.net_quantity_unit,
        "mrp": insp.mrp, "mfg_date": insp.mfg_date, "consumer_care": insp.consumer_care,
        "state": insp.state, "district": insp.district, "inspector_name": insp.inspector_name,
        "compliance_status": insp.compliance_status, "compliance_score": insp.compliance_score,
        "created_at": insp.created_at.isoformat(),
        "violations": [
            {"rule_id": v.rule_id, "rule_title": v.rule_title, "reference": v.reference,
             "description": v.description, "severity": v.severity}
            for v in insp.violations
        ],
    }


@app.get("/api/inspections/{inspection_id}/report.pdf")
def download_report(inspection_id: int, db: Session = Depends(get_db),
                     user: models.User = Depends(get_current_user)):
    insp = db.query(models.Inspection).filter(models.Inspection.id == inspection_id).first()
    if not insp:
        raise HTTPException(404, "Inspection not found")
    violations = [
        {"rule_title": v.rule_title, "reference": v.reference,
         "description": v.description, "severity": v.severity}
        for v in insp.violations
    ]
    path = report_generator.generate_pdf_report(insp, violations, insp.image_path)
    return FileResponse(path, media_type="application/pdf",
                         filename=f"{insp.report_no}.pdf")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.get("/api/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    total = db.query(models.Inspection).count()
    compliant = db.query(models.Inspection).filter(
        models.Inspection.compliance_status == "COMPLIANT").count()
    non_compliant = total - compliant

    by_state = db.query(models.Inspection.state, func.count(models.Inspection.id)) \
        .group_by(models.Inspection.state).all()

    by_manufacturer = db.query(models.Inspection.manufacturer_name,
                                func.count(models.Inspection.id)) \
        .filter(models.Inspection.compliance_status == "NON_COMPLIANT") \
        .group_by(models.Inspection.manufacturer_name) \
        .order_by(func.count(models.Inspection.id).desc()).limit(10).all()

    by_rule = db.query(models.Violation.rule_title, func.count(models.Violation.id)) \
        .group_by(models.Violation.rule_title) \
        .order_by(func.count(models.Violation.id).desc()).all()

    recent = db.query(models.Inspection).order_by(
        models.Inspection.created_at.desc()).limit(8).all()

    heatmap = db.query(models.Inspection).filter(
        models.Inspection.latitude.isnot(None)).limit(300).all()

    return {
        "total_scanned": total,
        "compliant": compliant,
        "non_compliant": non_compliant,
        "compliance_rate": round((compliant / total) * 100, 1) if total else 0,
        "by_state": [{"state": s, "count": c} for s, c in by_state],
        "top_offenders": [{"manufacturer": m or "Unknown", "violations": c} for m, c in by_manufacturer],
        "violations_by_rule": [{"rule": r, "count": c} for r, c in by_rule],
        "recent_inspections": [
            {"report_no": r.report_no, "product_name": r.product_name,
             "status": r.compliance_status, "created_at": r.created_at.isoformat()}
            for r in recent
        ],
        "heatmap_points": [
            {"lat": h.latitude, "lng": h.longitude, "status": h.compliance_status,
             "product": h.product_name, "state": h.state}
            for h in heatmap
        ],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat()}
