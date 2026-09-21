"""Deterministic item-onboarding assessment used by Onboarding Intelligence."""
from __future__ import annotations

import pandas as pd


REQUIRED = ("sku", "product_name", "vendor_id", "brand", "category", "price")
CUSTOMER_FIELDS = ("description", "image_url", "colour", "size", "material")


def sample_items(count: int = 240) -> pd.DataFrame:
    rows = []
    for index in range(1, count + 1):
        row = {
            "sku": f"ITEM-{index:05d}", "product_name": f"Onboarding Item {index:03d}",
            "vendor_id": f"VND-{((index - 1) % 60) + 1:05d}", "brand": f"Brand {((index - 1) % 12) + 1}",
            "category": ["Fashion", "Home", "Kitchen", "Beauty", "Electronics", "Footwear"][index % 6],
            "price": 299 + index * 3, "description": f"Customer-facing description for item {index}",
            "image_url": f"https://example.com/item-{index}.jpg", "colour": "Black",
            "size": "M", "material": "Standard", "submitted_at": "2026-08-01",
        }
        if index % 10 == 0:
            row["description"] = ""
        if index % 15 == 0:
            row["image_url"] = ""
        if index % 24 == 0:
            row["brand"] = ""
        rows.append(row)
    return pd.DataFrame(rows)


def assess_items(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    data = frame.copy().fillna("")
    data.columns = [str(column).strip().lower() for column in data.columns]
    for column in (*REQUIRED, *CUSTOMER_FIELDS):
        if column not in data:
            data[column] = ""
    data["sku"] = data["sku"].astype(str).str.strip()
    duplicate = data["sku"].duplicated(keep=False) | data["sku"].eq("")
    rows = []
    for index, item in data.iterrows():
        missing_required = [field for field in REQUIRED if not str(item.get(field, "")).strip()]
        missing_customer = [field for field in CUSTOMER_FIELDS if not str(item.get(field, "")).strip()]
        if duplicate.loc[index]:
            missing_required = sorted(set(missing_required + ["sku (blank or duplicated)"]))
        if missing_required:
            status, severity = "Correction required", "Critical"
        elif missing_customer:
            status, severity = "Review warnings", "Warning"
        else:
            status, severity = "Approval ready", "None"
        completeness = 100 * sum(bool(str(item.get(field, "")).strip()) for field in (*REQUIRED, *CUSTOMER_FIELDS)) / (len(REQUIRED) + len(CUSTOMER_FIELDS))
        rows.append({
            "SKU": item.get("sku") or "(blank)", "Product": item.get("product_name") or "—",
            "Vendor ID": item.get("vendor_id") or "—", "Status": status,
            "Highest severity": severity, "Completeness (%)": round(completeness, 1),
            "Affected attributes": "; ".join(missing_required + missing_customer) or "None",
            "Accountable team": "Supplier / Item Onboarding" if missing_required else "Catalog Operations" if missing_customer else "Approval Team",
            "Required action": "Correct mandatory item fields and resubmit" if missing_required else "Complete customer-facing attributes or accept warnings" if missing_customer else "Proceed to governed approval",
        })
    detail = pd.DataFrame(rows)
    unique = detail.drop_duplicates("SKU", keep="first")
    total = len(unique)
    correction = int(unique["Status"].eq("Correction required").sum())
    warning = int(unique["Status"].eq("Review warnings").sum())
    ready = int(unique["Status"].eq("Approval ready").sum())
    readiness = round(100 * (ready + 0.5 * warning) / total, 1) if total else 0.0
    summary = {"submitted": total, "approval_ready": ready, "warnings": warning,
               "correction_required": correction, "readiness": readiness,
               "decision": "BLOCKED" if correction else "CONDITIONAL" if warning else "READY"}
    return detail, summary
