from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from onboarding_intelligence import build_onboarding_intelligence


def _vendors():
    return pd.DataFrame([
        {"vendor_id": "V1", "legal_name": "Blocked Vendor", "status": "Correction Required", "age_days": 5,
         "planned_purchase_value": 1000, "value_currency": "INR"},
        {"vendor_id": "V2", "legal_name": "Ready Vendor", "status": "Approval Decision", "age_days": 2,
         "planned_purchase_value": 2000, "value_currency": "USD"},
    ])


def _assessments():
    return pd.DataFrame([
        {"vendor_id": "V1", "findings": [{"severity": "Warning", "field": "payment_terms", "owner": "Buying"},
                                             {"severity": "Critical", "field": "tax_id", "owner": "Compliance"}]},
        {"vendor_id": "V2", "findings": []},
    ])


def _items():
    base = {"product_name": "Item", "brand": "Brand", "category": "Home", "price": 100,
            "description": "Good", "image_url": "https://example.com/x.jpg", "colour": "Blue", "size": "M", "material": "Cotton"}
    return pd.DataFrame([{"sku": "S1", "vendor_id": "V1", **base}, {"sku": "S2", "vendor_id": "V2", **base}])


def test_linked_vendor_blocker_propagates_to_clean_item():
    result = build_onboarding_intelligence(_vendors(), _assessments(), _items())
    row = result["item_health"].set_index("SKU").loc["S1"]
    assert row["Effective status"] == "Blocked by vendor"
    assert result["item"]["blocked_by_vendor"] == 1


def test_highest_vendor_severity_controls_root_cause_and_decision():
    result = build_onboarding_intelligence(_vendors(), _assessments(), _items())
    row = result["vendor_health"].set_index("Vendor ID").loc["V1"]
    assert row["Severity"] == "Critical"
    assert row["Root cause"] == "Tax Id"
    assert result["decision"] == "HOLD"


def test_business_value_uses_only_inr_and_unique_skus():
    duplicated = pd.concat([_items(), _items().iloc[[1]]], ignore_index=True)
    result = build_onboarding_intelligence(_vendors(), _assessments(), duplicated)
    assert result["item"]["total"] == 2
    assert result["blocked_value_inr"] == 1000
    assert result["value_coverage_pct"] == 50.0


def test_unmatched_vendor_is_reconciliation_exception_not_item_defect():
    items = _items()
    items.loc[1, "vendor_id"] = "V-NOT-IN-VENDOR-DATA"
    result = build_onboarding_intelligence(_vendors(), _assessments(), items)
    row = result["item_health"].set_index("SKU").loc["S2"]
    assert row["Status"] == "Approval ready"
    assert row["Effective status"] == "Pending reconciliation"
    assert result["item"]["decision"] == "GO"
    assert result["reconciliation"]["unmatched"] == 1
