"""Run an installed standalone engine in its own Python process."""
import json
import sys
from pathlib import Path

import pandas as pd


def run(kind, source, output):
    sys.path.insert(0, str(Path.cwd()))
    source, output = Path(source), Path(output)
    frame = pd.read_csv(source, dtype=str, keep_default_na=False) if source.suffix.lower() == '.csv' else pd.read_excel(source, dtype=str, keep_default_na=False)
    if frame.empty:
        raise ValueError('The uploaded file contains no records.')
    if kind == 'vendor':
        sys.path.insert(0, str(Path.cwd() / 'src'))
        from src.service import VendorIQService
        from src.publishing import build_publication
        service = VendorIQService(db_path=str(output.parent / 'vendor.db'))
        result = service.ingest(frame, replace=True)
        if result['errors'] or result['rejected']:
            raise ValueError(str(result))
        vendors, assessments, _ = service.snapshot()
        payload = build_publication(vendors, assessments, service.kpis())
    elif kind == 'catalog':
        from catalog_operations.persistence.repository import CatalogRepository
        from catalog_operations.services import process_upload
        from catalog_operations.intelligence import build_intelligence
        from catalog_operations.publishing import build_publication_payload
        repo = CatalogRepository('sqlite:///' + (output.parent / 'catalog.db').as_posix())
        result = process_upload(frame, source.name, repo, replace_catalog=True)
        if result.ingestion.errors:
            raise ValueError('; '.join(e.message for e in result.ingestion.errors[:15]))
        payload = build_publication_payload(build_intelligence(repo))
        repo.engine.dispose()
    else:
        from domain.input_pipeline import validate_upload
        from domain.contracts import RunMetadata
        from domain.po_engine import validate_row, build_financial, build_sla, build_vendor_scorecard, build_division, build_decision_support
        from domain.publishing import build_publication
        validation = validate_upload(frame)
        if validation.errors:
            raise ValueError('; '.join(validation.errors))
        results = [validate_row(row, i) for i, row in validation.dataframe.iterrows()]
        vendors = build_vendor_scorecard(results)
        payload = build_publication(RunMetadata.create(source.name, len(results)), results,
                                    build_financial(results), vendors, build_division(results),
                                    build_sla(results), [], build_decision_support(results, vendors))
    # A distinct execution must never be mistaken for an earlier approval.
    payload['orchestration_run_id'] += '-' + output.parent.name
    output.write_text(json.dumps(payload, default=str), encoding='utf-8')


if __name__ == '__main__':
    run(*sys.argv[1:])
