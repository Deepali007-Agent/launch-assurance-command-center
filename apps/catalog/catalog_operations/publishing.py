from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


READY_TO_PUBLISH = "READY_TO_PUBLISH"
PUBLISHED = "PUBLISHED"
FAILED = "FAILED"


@dataclass(frozen=True)
class PublicationConfig:
    endpoint: str = ""
    token: str = ""
    timeout_seconds: int = 15
    max_attempts: int = 3

    @classmethod
    def from_env(cls) -> "PublicationConfig":
        return cls(
            endpoint=os.getenv("RETAIL_INTELLIGENCE_API_URL", "").strip(),
            token=os.getenv("RETAIL_INTELLIGENCE_API_TOKEN", "").strip(),
            timeout_seconds=max(1, int(os.getenv("RETAIL_INTELLIGENCE_TIMEOUT_SECONDS", "15"))),
            max_attempts=max(1, min(5, int(os.getenv("RETAIL_INTELLIGENCE_MAX_ATTEMPTS", "3")))),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.token)


def build_publication_payload(intelligence: dict[str, Any]) -> dict[str, Any]:
    orchestration = intelligence["orchestration"]
    catalog = intelligence["catalog"]
    return {
        "schema": "retail-intelligence.catalog.v1",
        "evaluator_type": "deterministic",
        "input_contract_version": "retail-source-input-1.0",
        "evidence_contract_version": "retail-cycle-controls-2.0",
        "schema_version": "1.1",
        "source": "CATALOG_IQ_PRO",
        "business_cycle_id": os.getenv("RETAIL_BUSINESS_CYCLE_ID", "").strip(),
        "orchestration_run_id": f'{orchestration["orchestration_run_id"]}-ONB1',
        "dataset_run_ids": orchestration["synchronization"]["run_ids"],
        "generated_at": orchestration["generated_at"],
        "policy_version": orchestration["policy_version"],
        "currency": orchestration["currency"],
        "publication_status": READY_TO_PUBLISH,
        "synchronization_status": orchestration["synchronization"]["status"],
        "executive_decision": {
            "decision": orchestration["decision"],
            "reason": orchestration["decision_reason"],
            "conflicts_resolved": orchestration["conflicts_resolved"],
        },
        "catalog": catalog,
        "item_onboarding": {
            "submitted_items": catalog["total_skus"],
            "validation_cleared": catalog["clean_skus"],
            "approval_ready": catalog["clean_skus"],
            "warning_items": catalog["warning_skus"],
            "correction_required": catalog["critical_skus"],
            "erp_ready": sum(1 for row in intelligence["sku"] if str(row.get("status", "")).upper() in {"ERP_READY", "ERP-READY"}),
            "readiness_score": catalog["readiness"],
            "decision": "BLOCKED" if catalog["critical_skus"] else "CONDITIONAL" if catalog["warning_skus"] else "READY",
            "calculation_note": "Unique governed SKUs; each SKU is counted once at its latest validated state.",
        },
        "sku_health": intelligence["sku"],
        "vendor_intelligence": intelligence["vendor"],
        "division_performance": intelligence["division"],
        "revenue_impact": intelligence["revenue"],
        "customer_experience": intelligence["customer"],
        "leadership_actions": orchestration["actions"],
        "provenance": orchestration["provenance"],
    }


def _http_post(endpoint: str, token: str, publication_id: str, payload: dict[str, Any], timeout: int) -> tuple[int, Any]:
    request = Request(
        endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "Idempotency-Key": publication_id, "X-CatalogIQ-Schema": payload["schema"]},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except HTTPError as error:
        body = error.read().decode("utf-8")
        try: parsed = json.loads(body) if body else {}
        except json.JSONDecodeError: parsed = {"message": body}
        return error.code, parsed


class RetailIntelligencePublisher:
    def __init__(self, repository, config: PublicationConfig | None = None,
                 transport: Callable | None = None, sleep: Callable[[float], None] = time.sleep):
        self.repository = repository
        self.config = config or PublicationConfig.from_env()
        self.transport = transport or _http_post
        self.sleep = sleep

    def prepare(self, intelligence: dict[str, Any]) -> dict[str, Any]:
        payload = build_publication_payload(intelligence)
        existing = self.repository.get_publication_by_orchestration_run(payload["orchestration_run_id"])
        if existing:
            return existing
        publication = {
            "publication_id": f"PUB-{uuid4().hex[:16].upper()}",
            "orchestration_run_id": payload["orchestration_run_id"],
            "dataset_run_ids": payload["dataset_run_ids"], "status": READY_TO_PUBLISH,
            "attempt_count": 0, "endpoint": self.config.endpoint, "payload": payload,
            "acknowledgement": None, "last_error": None,
            "created_at": datetime.now(timezone.utc).isoformat(), "published_at": None,
        }
        self.repository.save_publication(publication)
        return publication

    def publish(self, publication_id: str) -> dict[str, Any]:
        publication = self.repository.get_publication(publication_id)
        if not publication:
            raise KeyError(f"Unknown publication: {publication_id}")
        if publication["status"] == PUBLISHED:
            return publication
        if not self.config.is_configured:
            raise ValueError("Retail Intelligence API URL and token are not configured.")
        if publication["payload"].get("synchronization_status") != "VERIFIED":
            raise ValueError("Only a synchronized executive decision package can be published.")
        last_error = None
        for attempt in range(1, self.config.max_attempts + 1):
            total_attempt = int(publication.get("attempt_count") or 0) + attempt
            try:
                status_code, response = self.transport(
                    self.config.endpoint, self.config.token, publication_id,
                    publication["payload"], self.config.timeout_seconds,
                )
                if 200 <= status_code < 300:
                    acknowledgement = {"http_status": status_code, "received_at": datetime.now(timezone.utc).isoformat(),
                                       "response": response}
                    self.repository.update_publication(publication_id, PUBLISHED, total_attempt,
                        acknowledgement=acknowledgement, endpoint=self.config.endpoint,
                        published_at=datetime.now(timezone.utc).isoformat())
                    return self.repository.get_publication(publication_id)
                last_error = f"HTTP {status_code}: {response}"
            except Exception as error:  # network and transport failures are recorded, never swallowed
                last_error = f"{type(error).__name__}: {error}"
            if attempt < self.config.max_attempts:
                self.sleep(min(2 ** (attempt - 1), 4))
        self.repository.update_publication(publication_id, FAILED,
            int(publication.get("attempt_count") or 0) + self.config.max_attempts,
            last_error=last_error, endpoint=self.config.endpoint)
        return self.repository.get_publication(publication_id)
