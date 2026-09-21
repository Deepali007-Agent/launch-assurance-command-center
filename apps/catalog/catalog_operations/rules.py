from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

SUPPORTED_CATEGORIES = {
    "accessories", "apparel", "beauty", "electronics", "fashion",
    "footwear", "home", "kitchen", "sports",
}

CATEGORY_REQUIRED_ATTRIBUTES = {
    "apparel": ("colour", "size", "material"),
    "fashion": ("colour", "size", "material"),
    "footwear": ("colour", "size", "material"),
    "beauty": ("description", "brand"),
    "electronics": ("description", "brand"),
    "kitchen": ("description", "material"),
    "sports": ("description",),
    "accessories": ("colour", "material"),
    "home": ("description", "material"),
}

RULE_VERSION = "catalog-operations-1.0"
SKU_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$")
VENDOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$")


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.lower() in {"nan", "none", "null", "nat"}


def parse_price(value: Any) -> Decimal | None:
    if is_blank(value):
        return None
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
        return parsed if parsed.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def is_valid_gtin(value: str) -> bool:
    if is_blank(value):
        return True
    digits = str(value).strip()
    if not digits.isdigit() or len(digits) not in {8, 12, 13, 14}:
        return False
    payload = [int(c) for c in digits[:-1]]
    check_digit = int(digits[-1])
    total = sum(d * (3 if (len(payload) - i) % 2 else 1) for i, d in enumerate(payload))
    return (10 - total % 10) % 10 == check_digit


def finding(code: str, field: str, message: str, severity: str) -> dict[str, str]:
    return {"code": code, "field": field, "message": message, "severity": severity}
