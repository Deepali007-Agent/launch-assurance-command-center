from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .contracts import AgentAssessment, DomainDecision, IngestionResult
from .ingestion import ingest_dataframe
from .orchestrator import CatalogOperationsOrchestrator
from .persistence.repository import CatalogRepository


@dataclass(slots=True)
class WorkflowResult:
    ingestion: IngestionResult
    evaluations: list[tuple[list[AgentAssessment], DomainDecision]]


def process_upload(
    df: pd.DataFrame, source_name: str, repository: CatalogRepository, replace_catalog: bool = False,
) -> WorkflowResult:
    ingestion = ingest_dataframe(df)
    if replace_catalog and ingestion.errors:
        return WorkflowResult(ingestion, [])
    with repository.transaction():
        if replace_catalog:
            repository.clear_catalog()
        rejected_rows = len({e.message.split(":", 1)[0] for e in ingestion.errors if e.message.startswith("Row ")})
        repository.create_workflow_run(ingestion.workflow_run_id, source_name, len(df), len(ingestion.items), rejected_rows)
        orchestrator = CatalogOperationsOrchestrator(repository)
        evaluations = [orchestrator.evaluate(item) for item in ingestion.items]
    return WorkflowResult(ingestion, evaluations)
