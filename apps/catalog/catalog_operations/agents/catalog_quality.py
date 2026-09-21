from __future__ import annotations

from ..contracts import AgentAssessment, CatalogItem
from ..enums import Severity
from ..rules import CATEGORY_REQUIRED_ATTRIBUTES, finding
from .base import assessment


class CatalogQualityAgent:
    name = "CATALOG_QUALITY_AGENT"

    def evaluate(self, item: CatalogItem) -> AgentAssessment:
        findings, actions = [], []
        score = 100.0
        title_words = item.product_name.split()
        if len(title_words) < 2:
            findings.append(finding("WEAK_TITLE", "product_name", "Product title is too short for clear identification.", Severity.WARNING.value)); actions.append("Improve the product title."); score -= 12
        if len(item.product_name) > 120:
            findings.append(finding("TITLE_TOO_LONG", "product_name", "Product title exceeds 120 characters.", Severity.WARNING.value)); score -= 8
        if len(item.description.split()) < 6:
            findings.append(finding("WEAK_DESCRIPTION", "description", "Description lacks sufficient customer-facing detail.", Severity.WARNING.value)); actions.append("Add a descriptive customer-facing summary."); score -= 18
        if not item.image_url:
            findings.append(finding("IMAGE_MISSING", "image_url", "No product image is available for publication.", Severity.WARNING.value)); actions.append("Add a valid product image URL."); score -= 15
        for attribute in CATEGORY_REQUIRED_ATTRIBUTES.get(item.category.casefold(), ()):
            if not getattr(item, attribute):
                findings.append(finding("CATEGORY_ATTRIBUTE_MISSING", attribute, f"{attribute} is required for {item.category} publication readiness.", Severity.CRITICAL.value))
                actions.append(f"Complete required category attribute: {attribute}.")
                score -= 15
        for attribute in ("brand", "colour", "size", "material"):
            if not getattr(item, attribute):
                findings.append(finding("ATTRIBUTE_INCOMPLETE", attribute, f"{attribute} is missing and may reduce customer clarity.", Severity.WARNING.value)); score -= 4
        return assessment(item, self.name, findings, score, actions)
