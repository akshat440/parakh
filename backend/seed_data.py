import random
import datetime
import bcrypt
from database import SessionLocal, engine, Base
from models import User, Inspection, Violation
from rule_engine import all_rules

random.seed(7)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

STATES_DISTRICTS = {
    "Madhya Pradesh": ["Bhopal", "Indore", "Gwalior", "Jabalpur"],
    "Maharashtra": ["Mumbai", "Pune", "Nagpur"],
    "Delhi": ["New Delhi", "Dwarka"],
    "Karnataka": ["Bengaluru", "Mysuru"],
    "Tamil Nadu": ["Chennai", "Coimbatore"],
}

MANUFACTURERS = ["Nestlé Foods India Pvt. Ltd.", "Amul Dairy Cooperative Ltd.",
                  "BPL Electro Appliances Ltd.", "Radhika Opto Electronics Ltd.",
                  "Patanjali Ayurved Ltd.", "ABC Foods Pvt. Ltd."]

PRODUCTS = ["Choco Delight Biscuits", "Basmati Rice Premium", "Herbal Shampoo",
            "Refined Sunflower Oil", "Washing Detergent Powder", "LED Bulb 18W"]

INSPECTORS = ["Himanshu Singh", "Priya Sharma", "Rajesh Kumar", "Ananya Iyer",
              "Vikram Rathore"]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if not db.query(User).first():
        users = [
            User(username="admin", hashed_password=hash_password("admin123"),
                 full_name="System Admin", role="Admin", state="Madhya Pradesh"),
            User(username="inspector1", hashed_password=hash_password("inspect123"),
                 full_name="Himanshu Singh", role="Inspector", state="Madhya Pradesh"),
            User(username="officer1", hashed_password=hash_password("officer123"),
                 full_name="Priya Sharma", role="Senior Officer", state="Maharashtra"),
            User(username="analyst1", hashed_password=hash_password("analyst123"),
                 full_name="Ananya Iyer", role="Analyst", state="Delhi"),
        ]
        db.add_all(users)
        db.commit()

    if db.query(Inspection).count() > 0:
        print("Inspections already seeded, skipping.")
        db.close()
        return

    rules = all_rules()
    now = datetime.datetime.utcnow()

    for i in range(1, 61):
        state = random.choice(list(STATES_DISTRICTS.keys()))
        district = random.choice(STATES_DISTRICTS[state])
        is_compliant = random.random() > 0.42
        num_violations = 0 if is_compliant else random.randint(1, 4)
        chosen_rules = random.sample(rules, num_violations) if num_violations else []

        days_ago = random.randint(0, 45)
        created = now - datetime.timedelta(days=days_ago, hours=random.randint(0, 23))

        insp = Inspection(
            report_no=f"LM{created.strftime('%Y%m')}{i:04d}",
            product_name=random.choice(PRODUCTS),
            manufacturer_name=random.choice(MANUFACTURERS),
            manufacturer_address="Registered address on file" if random.random() > 0.15 else "",
            net_quantity_value=str(random.choice([70, 100, 200, 500, 1])),
            net_quantity_unit=random.choice(["g", "kg", "ml", "L"]),
            mrp=str(random.choice([20, 45, 99, 149, 299])),
            mfg_date=f"{random.choice(['January','March','June','August','November'])} 2026",
            consumer_care="1800-123-4567" if random.random() > 0.2 else "",
            raw_ocr_text="",
            image_path="",
            inspector_name=random.choice(INSPECTORS),
            state=state,
            district=district,
            latitude=None,
            longitude=None,
            compliance_status="COMPLIANT" if is_compliant else "NON_COMPLIANT",
            compliance_score=100.0 if is_compliant else round(100 - num_violations * 14.3, 1),
            created_at=created,
        )
        db.add(insp)
        db.flush()

        for r in chosen_rules:
            db.add(Violation(
                inspection_id=insp.id,
                rule_id=r["id"],
                rule_title=r["title"],
                reference=r["reference"],
                description=r["description"],
                severity=r["severity"],
            ))

    db.commit()
    db.close()
    print("Seeded 60 demo inspections + 4 users.")


if __name__ == "__main__":
    seed()
