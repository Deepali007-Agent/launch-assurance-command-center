from __future__ import annotations

from ..contracts import AgentAssessment, CatalogItem
from ..enums import Severity
from ..rules import SKU_PATTERN, VENDOR_PATTERN, finding, is_valid_gtin
from .base import assessment


class ItemIntakeAgent:
    name = "ITEM_INTAKE_AGENT"

    def evaluate(self, item: CatalogItem) -> AgentAssessment:
        findings, actions = [], []
        checks = (("sku", item.sku, 25), ("vendor_id", item.vendor_id, 20), ("product_name", item.product_name, 20), ("category", item.category, 15), ("price", item.price, 20))
        score = 100.0
        for field, value, weight in checks:
            if value is None or str(value).strip() == "":
                findings.append(finding("REQUIRED_FIELD_MISSING", field, f"{field} is required for intake.", Severity.CRITICAL.value))
                actions.append(f"Supply a valid {field}.")
                score -= weight
        if item.sku and not SKU_PATTERN.fullmatch(item.sku):
            findings.append(finding("INVALID_SKU", "sku", "SKU contains unsupported characters or length.", Severity.CRITICAL.value)); score -= 15
        if item.vendor_id and not VENDOR_PATTERN.fullmatch(item.vendor_id):
            findings.append(finding("INVALID_VENDOR_ID", "vendor_id", "Vendor identifier format is invalid.", Severity.CRITICAL.value)); score -= 15
        if item.price is not None and item.price < 0:
            findings.append(finding("INVALID_PRICE", "price", "Price cannot be negative.", Severity.CRITICAL.value)); score -= 20
        if item.gtin and not is_valid_gtin(item.gtin):
            findings.append(finding("INVALID_GTIN", "gtin", "GTIN length or checksum is invalid.", Severity.CRITICAL.value)); score -= 20
        return assessment(item, self.name, findings, score, actions)
