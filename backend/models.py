import datetime
from sqlalchemy import (Column, Integer, String, Float, DateTime, Text,
                         ForeignKey, Boolean)
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(String, default="Inspector")  # Inspector, Senior Officer, Admin, Analyst
    state = Column(String, default="Madhya Pradesh")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Inspection(Base):
    __tablename__ = "inspections"
    id = Column(Integer, primary_key=True, index=True)
    report_no = Column(String, unique=True, index=True)
    product_name = Column(String)
    manufacturer_name = Column(String)
    manufacturer_address = Column(String)
    net_quantity_value = Column(String)
    net_quantity_unit = Column(String)
    mrp = Column(String)
    mfg_date = Column(String)
    consumer_care = Column(String)
    raw_ocr_text = Column(Text)
    image_path = Column(String)
    inspector_id = Column(Integer, ForeignKey("users.id"))
    inspector_name = Column(String)
    state = Column(String)
    district = Column(String)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    compliance_status = Column(String)  # COMPLIANT / NON_COMPLIANT
    compliance_score = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    violations = relationship("Violation", back_populates="inspection",
                               cascade="all, delete-orphan")


class Violation(Base):
    __tablename__ = "violations"
    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer, ForeignKey("inspections.id"))
    rule_id = Column(String)
    rule_title = Column(String)
    reference = Column(String)
    description = Column(Text)
    severity = Column(String)

    inspection = relationship("Inspection", back_populates="violations")
