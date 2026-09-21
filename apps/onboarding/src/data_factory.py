"""Generate readable synthetic Vendor IQ Pro demonstration portfolios."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import pandas as pd

NAMES = ["Northstar Foods", "BlueHarbor Textiles", "Evergreen Home", "Solstice Beauty", "Cedar & Stone",
         "Aurora Electronics", "Meadowbrook Produce", "Summit Sports", "Willow Kids", "Atlas Essentials",
         "Coastal Pantry", "Lumen Living", "Heritage Coffee", "Riverbend Wellness", "Oakline Furniture",
         "Ember Kitchen", "Silverleaf Apparel", "Terra Pet Care", "Horizon Stationery", "Crown Artisan"]
COUNTRIES = [("United Kingdom", "GBP"), ("India", "INR"), ("Germany", "EUR"), ("United States", "USD"), ("France", "EUR")]


def make_dataset(count=500, profile="mixed", seed=42):
    rng = random.Random(seed)
    today = datetime.now(timezone.utc).date()
    rows = []
    for i in range(count):
        base = NAMES[i % len(NAMES)]
        country, currency = COUNTRIES[i % len(COUNTRIES)]
        ready = profile == "clean" or (profile == "mixed" and i % 5 == 0)
        expiry_days = 400
        if profile == "expiry": expiry_days = [-30, 14, 45, 75, 180][i % 5]
        elif not ready: expiry_days = [-10, 20, 60, 180][i % 4]
        correction = profile == "correction" or (not ready and i % 3 == 0)
        age_days = (i % 70) + 1
        activation_days = 8 + (i % 24)
        submitted = datetime.now(timezone.utc) - timedelta(days=age_days)
        completed = ready and i % 4 == 0 and age_days >= activation_days
        approved_at = submitted + timedelta(days=activation_days) if completed else None
        lifecycle = "Handoff Ready" if completed else "Received"
        planned_value = [75000, 180000, 420000, 900000, 1500000][i % 5]
        strategic_tier = ["Strategic", "Growth", "Core", "Transactional"][i % 4]
        launch_date = today + timedelta(days=[14, 30, 60, 120][i % 4])
        rows.append({
            "vendor_id": f"VND-{i+1:05d}", "legal_name": f"{base} {country} Ltd", "trading_name": base,
            "vendor_type": ["Brand", "Distributor", "Manufacturer"][i % 3], "country": country,
            "market": ["UK", "EU", "India", "North America"][i % 4], "currency": "INR",
            "tax_id": f"TAX{100000+i}" if ready or i % 4 else "", "registration_id": f"REG{500000+i}" if ready or i % 6 else "",
            "primary_contact": f"Operations Team {i % 12 + 1}", "contact_email": f"vendor{i+1}@example.com",
            "payment_terms": "Net 30" if ready or i % 7 else "", "incoterms": "DAP" if ready or i % 6 else "",
            "lead_time_days": 21 if ready or i % 8 else "", "minimum_order_quantity": 100 if ready or i % 9 else 0,
            "return_terms": "30-day agreed returns" if ready or i % 10 else "", "bank_information_status": "Verified" if ready or i % 5 else "Pending",
            "document_type": ["Insurance", "Tax Certificate", "Ethical Trade", "Vendor Authorization"][i % 4],
            "document_status": "Valid" if expiry_days >= 0 else "Expired", "document_issue_date": str(today - timedelta(days=300)),
            "document_expiry_date": str(today + timedelta(days=expiry_days)), "insurance_status": "Valid" if ready or i % 6 else "Pending",
            "ethical_trade_status": "Approved" if ready or i % 7 else "Pending", "sustainability_status": "Reviewed",
            "vendor_authorization": "Valid" if ready or i % 8 else "Missing", "submitted_at": submitted.isoformat(),
            "onboarding_owner": ["Vendor Onboarding", "Master Data"][i % 2], "compliance_owner": "Compliance",
            "commercial_owner": ["Buying", "Commercial"][i % 2], "lifecycle_status": lifecycle,
            "revision_number": 3 if correction else 1, "source_business_unit": ["Grocery", "Home", "Fashion", "General Merchandise"][i % 4],
            "planned_purchase_value": planned_value, "value_currency": "INR", "planned_item_count": 8 + (i % 35),
            "strategic_tier": strategic_tier, "planned_launch_date": str(launch_date),
            "downstream_dependency": ["Purchase order release", "Catalog item onboarding", "Range launch", "Market activation"][i % 4],
            "approved_at": approved_at.isoformat() if approved_at else ""
        })
    return pd.DataFrame(rows)


def write_datasets(folder="data"):
    path = Path(folder); path.mkdir(exist_ok=True)
    specs = [("clean_approval_ready.csv", 120, "clean", 11), ("mixed_quality_500.csv", 500, "mixed", 42),
             ("correction_resubmission.csv", 160, "correction", 22), ("documentation_expiry.csv", 180, "expiry", 33)]
    for name, count, profile, seed in specs:
        make_dataset(count, profile, seed).to_csv(path / name, index=False)


if __name__ == "__main__":
    write_datasets()
