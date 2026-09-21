from __future__ import annotations

from urllib.parse import urlparse

from ..contracts import AgentAssessment, CatalogItem
from ..enums import Severity
from ..rules import SUPPORTED_CATEGORIES, finding, is_valid_gtin
from .base import assessment


class PolicyValidationAgent:
    name = "POLICY_VALIDATION_AGENT"

    def evaluate(self, item: CatalogItem) -> AgentAssessment:
        findings, actions = [], []
        score = 100.0
        if item.category.casefold() not in SUPPORTED_CATEGORIES:
            findings.append(finding("UNSUPPORTED_CATEGORY", "category", "Category is not enabled by the current policy set.", Severity.CRITICAL.value)); actions.append("Map the item to a supported category."); score -= 35
        if item.gtin and not is_valid_gtin(item.gtin):
            findings.append(finding("GTIN_POLICY_FAILURE", "gtin", "GTIN fails identifier policy.", Severity.CRITICAL.value)); actions.append("Correct or remove the invalid GTIN."); score -= 30
        if item.price is None or item.price < 0:
            findings.append(finding("PRICE_POLICY_FAILURE", "price", "A non-negative price is required.", Severity.CRITICAL.value)); score -= 30
        if item.image_url:
            parsed = urlparse(item.image_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                findings.append(finding("INVALID_IMAGE_URL", "image_url", "Image URL must be an absolute HTTP(S) URL.", Severity.WARNING.value)); actions.append("Provide a valid image URL."); score -= 10
        approved = item.source_record.get("vendor_approved")
        if approved is not None and str(approved).strip().lower() not in {"true", "yes", "1", "approved"}:
            findings.append(finding("VENDOR_NOT_APPROVED", "vendor_id", "Vendor approval status is not approved.", Severity.CRITICAL.value)); actions.append("Complete vendor approval before handoff."); score -= 30
        return assessment(item, self.name, findings, score, actions)
