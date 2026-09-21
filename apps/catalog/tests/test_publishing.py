import pandas as pd
import pytest

from catalog_operations.intelligence import build_intelligence
from catalog_operations.publishing import (
    FAILED, PUBLISHED, READY_TO_PUBLISH, PublicationConfig, RetailIntelligencePublisher,
)
from catalog_operations.services import process_upload


def _intelligence(valid_df, repository):
    process_upload(valid_df, "publish.csv", repository)
    return build_intelligence(repository)


def test_parent_platform_payload_has_governed_schema_and_run_ids(valid_df, repository):
    intelligence = _intelligence(valid_df, repository)
    publication = RetailIntelligencePublisher(repository, PublicationConfig()).prepare(intelligence)

    assert publication["status"] == READY_TO_PUBLISH
    assert publication["payload"]["schema"] == "retail-intelligence.catalog.v1"
    assert publication["payload"]["orchestration_run_id"].startswith("ORCH-")
    assert publication["payload"]["dataset_run_ids"]
    assert publication["payload"]["synchronization_status"] == "VERIFIED"
    assert publication["payload"]["executive_decision"]["decision"]


def test_authenticated_publish_records_parent_acknowledgement(valid_df, repository):
    intelligence = _intelligence(valid_df, repository)
    calls = []
    def transport(endpoint, token, publication_id, payload, timeout):
        calls.append((endpoint, token, publication_id, payload, timeout))
        return 202, {"acknowledgement_id": "RIP-ACK-1001", "accepted": True}
    publisher = RetailIntelligencePublisher(
        repository, PublicationConfig("https://retail.example/api/catalog", "secret", max_attempts=3),
        transport=transport, sleep=lambda _: None,
    )
    publication = publisher.prepare(intelligence)
    result = publisher.publish(publication["publication_id"])

    assert result["status"] == PUBLISHED
    assert result["attempt_count"] == 1
    assert result["acknowledgement"]["http_status"] == 202
    assert result["acknowledgement"]["response"]["acknowledgement_id"] == "RIP-ACK-1001"
    assert calls[0][1] == "secret"
    assert calls[0][2] == publication["publication_id"]


def test_retry_then_publish_is_idempotent(valid_df, repository):
    intelligence = _intelligence(valid_df, repository)
    attempts = {"count": 0}
    def transport(*_):
        attempts["count"] += 1
        return (503, {"message": "busy"}) if attempts["count"] < 3 else (200, {"accepted": True})
    publisher = RetailIntelligencePublisher(
        repository, PublicationConfig("https://retail.example/api/catalog", "secret", max_attempts=3),
        transport=transport, sleep=lambda _: None,
    )
    publication = publisher.prepare(intelligence)
    result = publisher.publish(publication["publication_id"])

    assert result["status"] == PUBLISHED
    assert result["attempt_count"] == 3
    assert publisher.publish(publication["publication_id"])["attempt_count"] == 3


def test_failed_publication_records_error_and_can_be_retried(valid_df, repository):
    intelligence = _intelligence(valid_df, repository)
    publisher = RetailIntelligencePublisher(
        repository, PublicationConfig("https://retail.example/api/catalog", "secret", max_attempts=2),
        transport=lambda *_: (500, {"message": "down"}), sleep=lambda _: None,
    )
    publication = publisher.prepare(intelligence)
    result = publisher.publish(publication["publication_id"])

    assert result["status"] == FAILED
    assert result["attempt_count"] == 2
    assert "HTTP 500" in result["last_error"]


def test_publish_requires_endpoint_and_authentication(valid_df, repository):
    intelligence = _intelligence(valid_df, repository)
    publisher = RetailIntelligencePublisher(repository, PublicationConfig())
    publication = publisher.prepare(intelligence)
    with pytest.raises(ValueError, match="URL and token"):
        publisher.publish(publication["publication_id"])
