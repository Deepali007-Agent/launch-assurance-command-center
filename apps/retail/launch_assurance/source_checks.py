"""Run existing source engines in isolation; no live dataset or database writes."""
import importlib.util
import json
from pathlib import Path
import sys

def check(scenario):
    retail=Path(__file__).resolve().parents[1]
    if (retail.parent/'onboarding/src').exists():
        roots={k:retail.parent/v for k,v in [('vendor','onboarding'),('catalog','catalog'),('po','po')]}
    else:
        desktop=retail.parent.parent
        roots={k:desktop/v for k,v in [('vendor','item_onboarding_agent'),('catalog','CatalogIQ Pro'),('po','po_intelligence')]}
    sys.path[:0]=[str(roots['vendor']/'src'),str(roots['catalog']),str(roots['po']),str(retail)]
    spec=importlib.util.spec_from_file_location('launch_vendor_checks',roots['vendor']/'src/agents.py')
    vendor=importlib.util.module_from_spec(spec);spec.loader.exec_module(vendor)
    from retail_workflow.store import MANDATORY_ITEM, blank
    from catalog_operations.persistence.repository import CatalogRepository
    from catalog_operations.services import process_upload
    from domain.po_engine import validate_row
    import pandas as pd
    vendor_results=vendor.assess_vendor(scenario['vendor'])
    vendor_blocked=any(r['severity']=='Critical' for r in vendor_results)
    onboarding={row['sku']:{'passed':not vendor_blocked and not any(blank(row.get(k)) for k in MANDATORY_ITEM),'reason':'Mandatory item fields and vendor source checks; human approvals are simulated scenario assumptions.'} for row in scenario['items']}
    repo=CatalogRepository('sqlite:///:memory:')
    checked=process_upload(pd.DataFrame(scenario['items']),'launch-assurance-synthetic',repo,replace_catalog=True)
    if checked.ingestion.errors:raise ValueError('; '.join(e.message for e in checked.ingestion.errors))
    catalog={}
    for assessments,decision in checked.evaluations:
        findings=decision.critical_blockers+decision.warnings
        catalog[decision.sku]={'passed':not findings,'findings':[str(f.get('message') or f.get('code') or f) for f in findings]}
    repo.engine.dispose()
    buying={}
    for i,row in enumerate(scenario['pos']):
        result=validate_row(row,i)
        margin=(float(row['Reg Retail'])-float(row['Cost']))/float(row['Reg Retail'])*100
        buying[row['SKU']]={'passed':result['status']!='FAIL' and margin>=scenario['margin_floor_pct'],'margin_pct':round(margin,2),'findings':result['errors']+result['warnings']}
    return {'onboarding':onboarding,'catalog':catalog,'buying':buying,'source':'Existing Onboarding mandatory-field contract, Vendor validators, Catalog service and PO domain engine'}

if __name__=='__main__':
    print(json.dumps(check(json.loads(sys.stdin.read())),default=str))
