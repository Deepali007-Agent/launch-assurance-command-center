from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from ..contracts import AgentAssessment, CatalogItem, ReworkEvent
from ..enums import ReworkReason, ReworkSource, Severity
from ..rules import finding
from .base import assessment

MATERIAL_FIELDS = ("vendor_id", "vendor_name", "product_name", "brand", "category", "description", "price", "gtin", "image_url", "colour", "size", "material")


class ItemReworkAgent:
    name = "ITEM_REWORK_AGENT"

    def compare(self, previous: CatalogItem | None, current: CatalogItem, source: str = ReworkSource.VENDOR.value, reason_code: str = ReworkReason.VENDOR_REQUESTED_AMENDMENT.value) -> tuple[AgentAssessment, list[ReworkEvent]]:
        # Rework is a post-live vendor amendment. Pre-live corrections create a
        # new immutable item version but are not counted as operational rework.
        if previous is None or previous.lifecycle_status.value != "CREATED_IN_ERP_SIMULATED":
            return assessment(current, self.name, [], 100, []), []
        now = datetime.now(timezone.utc)
        changes: list[ReworkEvent] = []
        for attribute in MATERIAL_FIELDS:
            old, new = getattr(previous, attribute), getattr(current, attribute)
            if old != new:
                opened = previous.submitted_at
                changes.append(ReworkEvent(
                    rework_id=str(uuid4()), sku=current.sku, vendor_id=current.vendor_id,
                    workflow_stage="POST_LIVE_VENDOR_AMENDMENT", attribute_name=attribute,
                    previous_value=str(old) if old is not None else None,
                    updated_value=str(new) if new is not None else None,
                    reason_code=reason_code, source=source, revision_number=current.revision_number,
                    opened_at=opened, resolved_at=now,
                    resolution_hours=max(0.0, (now - opened).total_seconds() / 3600),
                    downstream_impact="Live catalog change requires revalidation and controlled republication.",
                ))
        findings = [finding("ITEM_REVISED", e.attribute_name, f"{e.attribute_name} changed in revision {current.revision_number}.", Severity.WARNING.value) for e in changes]
        score = max(0, 100 - len(changes) * 5)
        actions = ["Review material changes and repeat affected validations."] if changes else []
        return assessment(current, self.name, findings, score, actions), changes
