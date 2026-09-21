from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Float, Integer, MetaData, String, Table, Text, create_engine, delete, insert, select, update

from ..contracts import AgentAssessment, CatalogItem, DomainDecision, DomainEvent, ReworkEvent
from ..enums import LifecycleStatus


class CatalogRepository:
    """Database-neutral repository backed by SQLite or DATABASE_URL."""

    def __init__(self, database_url: str | None = None):
        self._local = threading.local()
        self.database_url = database_url or os.getenv("DATABASE_URL") or "sqlite:///data/catalog_operations.db"
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(self.database_url, future=True)
        self.metadata = MetaData()
        self._define_tables()
        self.metadata.create_all(self.engine)

    @contextmanager
    def connection(self, write=False):
        active = getattr(self._local, 'connection', None)
        if active is not None:
            yield active
            return
        with (self.engine.begin() if write else self.engine.connect()) as connection:
            yield connection

    @contextmanager
    def transaction(self):
        with self.connection(write=True) as connection:
            self._local.connection = connection
            try:
                yield
            finally:
                self._local.connection = None

    def _define_tables(self) -> None:
        self.workflow_runs = Table("workflow_runs", self.metadata,
            Column("workflow_run_id", String(64), primary_key=True), Column("source_name", String(255)),
            Column("status", String(40), nullable=False), Column("received_count", Integer, default=0),
            Column("accepted_count", Integer, default=0), Column("rejected_count", Integer, default=0),
            Column("created_at", DateTime(timezone=True), nullable=False))
        self.current_items = Table("current_items", self.metadata,
            Column("sku", String(64), primary_key=True), Column("workflow_run_id", String(64), nullable=False),
            Column("revision_number", Integer, nullable=False), Column("lifecycle_status", String(50), nullable=False),
            Column("item_json", JSON, nullable=False), Column("updated_at", DateTime(timezone=True), nullable=False))
        self.item_versions = Table("item_versions", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True), Column("sku", String(64), nullable=False),
            Column("workflow_run_id", String(64), nullable=False), Column("revision_number", Integer, nullable=False),
            Column("item_json", JSON, nullable=False), Column("created_at", DateTime(timezone=True), nullable=False))
        self.assessments = Table("agent_assessments", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True), Column("sku", String(64), nullable=False),
            Column("workflow_run_id", String(64), nullable=False), Column("agent_name", String(80), nullable=False),
            Column("status", String(30), nullable=False), Column("readiness_score", Float, nullable=False),
            Column("severity", String(30), nullable=False), Column("assessment_json", JSON, nullable=False),
            Column("evaluated_at", DateTime(timezone=True), nullable=False))
        self.decisions = Table("domain_decisions", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True), Column("sku", String(64), nullable=False),
            Column("workflow_run_id", String(64), nullable=False), Column("decision", String(40), nullable=False),
            Column("composite_readiness", Float, nullable=False), Column("decision_json", JSON, nullable=False),
            Column("decided_at", DateTime(timezone=True), nullable=False))
        self.domain_events = Table("domain_events", self.metadata,
            Column("event_id", String(64), primary_key=True), Column("sku", String(64), nullable=False),
            Column("workflow_run_id", String(64), nullable=False), Column("event_type", String(80), nullable=False),
            Column("previous_status", String(50)), Column("new_status", String(50)),
            Column("reason_code", String(80)), Column("source", String(50)),
            Column("event_json", JSON, nullable=False), Column("occurred_at", DateTime(timezone=True), nullable=False))
        self.rework_events = Table("rework_events", self.metadata,
            Column("rework_id", String(64), primary_key=True), Column("sku", String(64), nullable=False),
            Column("vendor_id", String(64)), Column("workflow_stage", String(80)),
            Column("attribute_name", String(80)), Column("reason_code", String(80)),
            Column("source", String(50)), Column("revision_number", Integer),
            Column("resolution_hours", Float), Column("event_json", JSON, nullable=False),
            Column("opened_at", DateTime(timezone=True), nullable=False), Column("resolved_at", DateTime(timezone=True)))
        self.executive_actions = Table("executive_actions", self.metadata,
            Column("action_id", String(64), primary_key=True), Column("status", String(30), nullable=False),
            Column("owner", String(120), nullable=False), Column("priority", String(10), nullable=False),
            Column("scope", String(255), nullable=False), Column("action_json", JSON, nullable=False),
            Column("run_ids_json", JSON, nullable=False), Column("updated_at", DateTime(timezone=True), nullable=False))
        self.publications = Table("retail_intelligence_publications", self.metadata,
            Column("publication_id", String(64), primary_key=True),
            Column("orchestration_run_id", String(80), nullable=False, unique=True),
            Column("status", String(30), nullable=False), Column("attempt_count", Integer, nullable=False),
            Column("endpoint", String(500)), Column("publication_json", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            Column("published_at", DateTime(timezone=True)))

    def create_workflow_run(self, run_id: str, source_name: str, received: int, accepted: int, rejected: int) -> None:
        with self.connection(write=True) as conn:
            conn.execute(insert(self.workflow_runs).values(workflow_run_id=run_id, source_name=source_name,
                status="VALIDATED", received_count=received, accepted_count=accepted, rejected_count=rejected,
                created_at=datetime.now(timezone.utc)))

    def clear_catalog(self) -> None:
        """Clear the active test portfolio and its governed audit records."""
        with self.connection(write=True) as conn:
            for table in (
                self.executive_actions, self.rework_events, self.domain_events, self.decisions, self.assessments,
                self.item_versions, self.current_items, self.workflow_runs,
            ):
                conn.execute(delete(table))

    @staticmethod
    def _item_from_json(data: dict[str, Any]) -> CatalogItem:
        return CatalogItem(
            sku=data["sku"], vendor_id=data["vendor_id"], vendor_name=data.get("vendor_name", ""),
            product_name=data["product_name"], brand=data.get("brand", ""), category=data["category"],
            description=data.get("description", ""), price=Decimal(str(data["price"])) if data.get("price") is not None else None,
            gtin=data.get("gtin", ""), image_url=data.get("image_url", ""), colour=data.get("colour", ""),
            size=data.get("size", ""), material=data.get("material", ""),
            submitted_at=datetime.fromisoformat(data["submitted_at"]), workflow_run_id=data["workflow_run_id"],
            source_record=data.get("source_record", {}), revision_number=int(data.get("revision_number", 1)),
            lifecycle_status=LifecycleStatus(data.get("lifecycle_status", LifecycleStatus.RECEIVED.value)),
        )

    def get_current_item(self, sku: str) -> CatalogItem | None:
        with self.connection() as conn:
            row = conn.execute(select(self.current_items.c.item_json).where(self.current_items.c.sku == sku)).scalar_one_or_none()
        return self._item_from_json(row) if row else None

    def save_item_version(self, item: CatalogItem) -> None:
        payload, now = item.to_dict(), datetime.now(timezone.utc)
        with self.connection(write=True) as conn:
            conn.execute(insert(self.item_versions).values(sku=item.sku, workflow_run_id=item.workflow_run_id,
                revision_number=item.revision_number, item_json=payload, created_at=now))
            conn.execute(delete(self.current_items).where(self.current_items.c.sku == item.sku))
            conn.execute(insert(self.current_items).values(sku=item.sku, workflow_run_id=item.workflow_run_id,
                revision_number=item.revision_number, lifecycle_status=item.lifecycle_status.value,
                item_json=payload, updated_at=now))

    def update_status(self, sku: str, status: LifecycleStatus) -> None:
        item = self.get_current_item(sku)
        if not item:
            raise KeyError(f"Unknown SKU: {sku}")
        item.lifecycle_status = status
        payload = item.to_dict()
        with self.connection(write=True) as conn:
            conn.execute(update(self.current_items).where(self.current_items.c.sku == sku).values(
                lifecycle_status=status.value, item_json=payload, updated_at=datetime.now(timezone.utc)))

    def save_assessments(self, values: list[AgentAssessment]) -> None:
        if not values: return
        with self.connection(write=True) as conn:
            conn.execute(insert(self.assessments), [{"sku": a.entity_id, "workflow_run_id": a.workflow_run_id,
                "agent_name": a.agent_name, "status": a.status.value, "readiness_score": a.readiness_score,
                "severity": a.severity.value, "assessment_json": a.to_dict(), "evaluated_at": a.evaluated_at} for a in values])

    def save_decision(self, value: DomainDecision) -> None:
        with self.connection(write=True) as conn:
            conn.execute(insert(self.decisions).values(sku=value.sku, workflow_run_id=value.workflow_run_id,
                decision=value.decision.value, composite_readiness=value.composite_readiness,
                decision_json=value.to_dict(), decided_at=value.decided_at))

    def save_events(self, values: list[DomainEvent]) -> None:
        if not values: return
        with self.connection(write=True) as conn:
            conn.execute(insert(self.domain_events), [{"event_id": e.event_id, "sku": e.entity_id,
                "workflow_run_id": e.workflow_run_id, "event_type": e.event_type,
                "previous_status": e.previous_status, "new_status": e.new_status,
                "reason_code": e.reason_code, "source": e.source, "event_json": e.to_dict(),
                "occurred_at": e.occurred_at} for e in values])

    def save_rework_events(self, values: list[ReworkEvent]) -> None:
        if not values: return
        with self.connection(write=True) as conn:
            conn.execute(insert(self.rework_events), [{"rework_id": e.rework_id, "sku": e.sku,
                "vendor_id": e.vendor_id, "workflow_stage": e.workflow_stage, "attribute_name": e.attribute_name,
                "reason_code": e.reason_code, "source": e.source, "revision_number": e.revision_number,
                "resolution_hours": e.resolution_hours, "event_json": e.to_dict(), "opened_at": e.opened_at,
                "resolved_at": e.resolved_at} for e in values])

    def _json_rows(self, table: Table, json_column: Column, sku: str | None = None) -> list[dict[str, Any]]:
        statement = select(json_column)
        if sku and "sku" in table.c:
            statement = statement.where(table.c.sku == sku)
        with self.connection() as conn:
            return list(conn.execute(statement).scalars())

    def list_current_items(self) -> list[dict[str, Any]]: return self._json_rows(self.current_items, self.current_items.c.item_json)
    def list_assessments(self, sku: str | None = None) -> list[dict[str, Any]]: return self._json_rows(self.assessments, self.assessments.c.assessment_json, sku)
    def list_decisions(self, sku: str | None = None) -> list[dict[str, Any]]: return self._json_rows(self.decisions, self.decisions.c.decision_json, sku)
    def list_events(self, sku: str | None = None) -> list[dict[str, Any]]: return self._json_rows(self.domain_events, self.domain_events.c.event_json, sku)
    def list_rework_events(self, sku: str | None = None) -> list[dict[str, Any]]: return self._json_rows(self.rework_events, self.rework_events.c.event_json, sku)
    def list_item_versions(self, sku: str | None = None) -> list[dict[str, Any]]: return self._json_rows(self.item_versions, self.item_versions.c.item_json, sku)

    def synchronize_executive_actions(self, actions: list[dict[str, Any]], run_ids: list[str]) -> None:
        """Upsert current priorities and close those removed by revalidation."""
        now = datetime.now(timezone.utc)
        current_ids = {value["action_id"] for value in actions}
        with self.connection(write=True) as conn:
            existing = list(conn.execute(select(self.executive_actions)).mappings())
            for row in existing:
                if row["action_id"] not in current_ids and row["status"] not in {"CLOSED", "CANCELLED"}:
                    payload = dict(row["action_json"])
                    payload.update(status="CLOSED", closed_at=now.isoformat(), closure_reason="Resolved by revalidation")
                    conn.execute(update(self.executive_actions).where(self.executive_actions.c.action_id == row["action_id"]).values(
                        status="CLOSED", action_json=payload, run_ids_json=run_ids, updated_at=now))
            for action in actions:
                prior = next((row for row in existing if row["action_id"] == action["action_id"]), None)
                payload = dict(action)
                if prior and prior["status"] in {"ASSIGNED", "IN_PROGRESS", "CORRECTED", "REVALIDATING"}:
                    payload["status"] = prior["status"]
                    payload["opened_at"] = prior["action_json"].get("opened_at", payload["opened_at"])
                    payload["owner"] = prior["action_json"].get("owner", payload["owner"])
                values = dict(status=payload["status"], owner=payload["owner"], priority=payload["priority"],
                    scope=payload["scope"], action_json=payload, run_ids_json=run_ids, updated_at=now)
                if prior:
                    conn.execute(update(self.executive_actions).where(self.executive_actions.c.action_id == action["action_id"]).values(**values))
                else:
                    conn.execute(insert(self.executive_actions).values(action_id=action["action_id"], **values))

    def list_executive_actions(self, active_only: bool = False) -> list[dict[str, Any]]:
        statement = select(self.executive_actions.c.action_json)
        if active_only:
            statement = statement.where(self.executive_actions.c.status.not_in(["CLOSED", "CANCELLED"]))
        with self.connection() as conn:
            return list(conn.execute(statement).scalars())

    def update_executive_action(self, action_id: str, status: str, owner: str | None = None) -> None:
        allowed = {"OPEN", "ASSIGNED", "IN_PROGRESS", "CORRECTED", "REVALIDATING", "CLOSED", "CANCELLED"}
        if status not in allowed:
            raise ValueError(f"Unsupported action status: {status}")
        with self.connection(write=True) as conn:
            row = conn.execute(select(self.executive_actions).where(self.executive_actions.c.action_id == action_id)).mappings().one_or_none()
            if not row:
                raise KeyError(f"Unknown executive action: {action_id}")
            payload = dict(row["action_json"]); payload["status"] = status
            if owner: payload["owner"] = owner
            if status == "CLOSED": payload["closed_at"] = datetime.now(timezone.utc).isoformat()
            conn.execute(update(self.executive_actions).where(self.executive_actions.c.action_id == action_id).values(
                status=status, owner=payload["owner"], action_json=payload, updated_at=datetime.now(timezone.utc)))

    @staticmethod
    def _date(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    def save_publication(self, publication: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        with self.connection(write=True) as conn:
            conn.execute(insert(self.publications).values(
                publication_id=publication["publication_id"], orchestration_run_id=publication["orchestration_run_id"],
                status=publication["status"], attempt_count=int(publication.get("attempt_count") or 0),
                endpoint=publication.get("endpoint"), publication_json=publication,
                created_at=self._date(publication.get("created_at")) or now, updated_at=now,
                published_at=self._date(publication.get("published_at"))))

    def get_publication(self, publication_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute(select(self.publications.c.publication_json).where(
                self.publications.c.publication_id == publication_id)).scalar_one_or_none()

    def get_publication_by_orchestration_run(self, orchestration_run_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute(select(self.publications.c.publication_json).where(
                self.publications.c.orchestration_run_id == orchestration_run_id)).scalar_one_or_none()

    def list_publications(self) -> list[dict[str, Any]]:
        return self._json_rows(self.publications, self.publications.c.publication_json)

    def update_publication(self, publication_id: str, status: str, attempt_count: int,
                           acknowledgement: dict[str, Any] | None = None, last_error: str | None = None,
                           endpoint: str | None = None, published_at: str | None = None) -> None:
        publication = self.get_publication(publication_id)
        if not publication:
            raise KeyError(f"Unknown publication: {publication_id}")
        publication.update(status=status, attempt_count=attempt_count, acknowledgement=acknowledgement,
                           last_error=last_error, endpoint=endpoint or publication.get("endpoint"),
                           published_at=published_at or publication.get("published_at"))
        with self.connection(write=True) as conn:
            conn.execute(update(self.publications).where(self.publications.c.publication_id == publication_id).values(
                status=status, attempt_count=attempt_count, endpoint=publication.get("endpoint"),
                publication_json=publication, updated_at=datetime.now(timezone.utc),
                published_at=self._date(publication.get("published_at"))))
