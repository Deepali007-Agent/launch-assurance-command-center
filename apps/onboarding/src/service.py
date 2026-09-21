"""Vendor onboarding orchestration and reporting services."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import pandas as pd

from agents import assess_vendor
from kpis import calculate_kpis
from repository import VendorRepository

REQUIRED_COLUMNS = {"vendor_id", "legal_name", "country", "contact_email"}
APPROVAL_READY = {"Information Review", "Compliance Review", "Commercial Review", "Approval Decision"}


class VendorIQService:
    def __init__(self, db_path="data/vendor_iq.db"):
        self.repo = VendorRepository(db_path)

    def validate_frame(self, frame: pd.DataFrame):
        frame = frame.copy().fillna("")
        frame.columns = [str(c).strip().lower() for c in frame.columns]
        missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
        structural = []
        if missing:
            structural.append({"field": ", ".join(missing), "issue": "Required column is missing", "how_to_fix": "Add the named column(s) and upload again."})
            return [], frame.to_dict("records"), structural
        duplicated = frame["vendor_id"].astype(str).str.strip().duplicated(keep=False)
        rejected = frame[duplicated | frame["vendor_id"].astype(str).str.strip().eq("")].copy()
        accepted = frame[~(duplicated | frame["vendor_id"].astype(str).str.strip().eq(""))].copy()
        for vendor_id in rejected["vendor_id"].astype(str).unique():
            structural.append({"field": "vendor_id", "issue": f"Duplicate or blank identifier: {vendor_id or '(blank)'}", "how_to_fix": "Provide one unique, stable vendor ID per vendor."})
        return accepted.to_dict("records"), rejected.to_dict("records"), structural

    def ingest(self, frame: pd.DataFrame, replace=True):
        accepted, rejected, errors = self.validate_frame(frame)
        if accepted:
            with self.repo.transaction():
                if replace:
                    self.repo.replace_portfolio(accepted)
                else:
                    self.repo.upsert_many(accepted)
                self.assess_all()
        return {"accepted": len(accepted), "rejected": len(rejected), "errors": errors, "rejected_records": rejected}

    def assess_all(self):
        for vendor in self.repo.vendors():
            assessments = assess_vendor(vendor)
            self.repo.save_assessments(vendor["vendor_id"], int(vendor["revision"]), assessments)
            ready = all(a["severity"] != "Critical" for a in assessments)
            current = vendor.get("status", "Received")
            if current in {"Received", "Structural Validation", "Information Review"}:
                target = "Approval Decision" if ready else "Correction Required"
                self.repo.transition(vendor["vendor_id"], target, "Approval & Handoff Agent",
                                     "Automated validation completed; human decision remains required.", "Assessment completed")

    def snapshot(self):
        vendors = pd.DataFrame(self.repo.vendors())
        assessments = pd.DataFrame(self.repo.latest_assessments())
        audit = pd.DataFrame(self.repo.audit())
        if not vendors.empty:
            vendors["submitted_at"] = pd.to_datetime(vendors["submitted_at"], errors="coerce", utc=True)
            vendors["age_days"] = ((pd.Timestamp.now(tz="UTC") - vendors["submitted_at"]).dt.total_seconds() / 86400).fillna(0).round(1)
        return vendors, assessments, audit

    def kpis(self):
        vendors, assessments, audit = self.snapshot()
        return calculate_kpis(vendors, assessments, audit)

    def decision(self, vendor_id, action, note, actor="Human approver"):
        if action == "Approve vendor":
            latest = [a for a in self.repo.latest_assessments() if a["vendor_id"] == vendor_id]
            critical = [f for a in latest for f in a.get("findings", []) if f.get("severity") == "Critical"]
            if critical:
                raise ValueError("Approval blocked: resolve all critical findings before approval.")
        transitions = {
            "Approve vendor": ("Handoff Ready", "Vendor approved"),
            "Request correction": ("Correction Required", "Correction requested"),
            "Place on hold": ("On Hold", "Vendor placed on hold"),
            "Reject vendor": ("Rejected", "Vendor rejected"),
            "Release hold": ("Approval Decision", "Hold released"),
            "Prepare system-ready handoff": ("Handoff Ready", "Handoff payload prepared"),
            "Mark created in system simulation": ("Created in System (Simulated)", "Simulated system creation"),
        }
        target, event = transitions[action]
        self.repo.transition(vendor_id, target, actor, note, event)

    def handoff_payload(self, vendor_id):
        vendor = next(v for v in self.repo.vendors() if v["vendor_id"] == vendor_id)
        safe_fields = ["vendor_id", "legal_name", "trading_name", "country", "market", "currency",
                       "tax_id", "registration_id", "payment_terms", "incoterms", "lead_time_days",
                       "minimum_order_quantity", "return_terms"]
        return {k: vendor.get(k, "") for k in safe_fields} | {"simulation": True, "prepared_at": datetime.now(timezone.utc).isoformat()}
