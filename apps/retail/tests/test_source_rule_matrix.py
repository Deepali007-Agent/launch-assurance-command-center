"""Single-rule certification against the installed source authorities."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
import sys
import pandas as pd
import pytest

APPS=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APPS/'onboarding/src'))
sys.path.insert(0,str(APPS/'catalog'))
sys.path.insert(0,str(APPS/'po'))
spec=importlib.util.spec_from_file_location('cert_vendor_controls',APPS/'onboarding/src/agents.py')
vendor=importlib.util.module_from_spec(spec);spec.loader.exec_module(vendor)
from domain.po_engine import validate_row
from domain.input_pipeline import REQUIRED_COLUMNS
from catalog_operations.ingestion import ingest_dataframe
from catalog_operations.agents.catalog_quality import CatalogQualityAgent
from catalog_operations.agents.policy_validation import PolicyValidationAgent

PACK=APPS.parent/'demo/corrected'
@pytest.fixture(scope='module')
def source_rows():
    return {k:pd.read_csv(PACK/f'{k}.csv',dtype=str,keep_default_na=False).iloc[0].to_dict() for k in ('vendor','catalog','po')}

@pytest.mark.parametrize('field,value,severity',[
 *[(f,'','Critical') for f in ('legal_name','tax_id','registration_id','country','currency','payment_terms','incoterms','return_terms','lead_time_days')],
 ('contact_email','invalid','Warning'),('bank_information_status','pending','Critical'),
 ('document_status','missing','Critical'),('document_status','expired','Critical'),('document_status','rejected','Critical'),
 ('document_expiry_date','invalid','Critical'),('document_expiry_date','2000-01-01','Critical'),
 ('document_expiry_date',(datetime.now(timezone.utc)+timedelta(days=20)).date().isoformat(),'Warning'),
 ('document_expiry_date',(datetime.now(timezone.utc)+timedelta(days=60)).date().isoformat(),'Warning'),
 *[(f,'pending','Critical') for f in ('insurance_status','ethical_trade_status','vendor_authorization')],
 ('minimum_order_quantity','0','Warning'),('minimum_order_quantity','NaN','Warning'),('minimum_order_quantity','bad','Warning'),
 ('revision_number','3','Warning')])
def test_vendor_individual_rule(source_rows,field,value,severity):
    record=source_rows['vendor']|{field:value}
    findings=[f for result in vendor.assess_vendor(record) for f in result['findings']]
    assert any(f['field']==field and f['severity']==severity for f in findings)
    assert all(f['owner'] and f['how_to_fix'] for f in findings)

@pytest.mark.parametrize('field',REQUIRED_COLUMNS)
def test_po_each_mandatory_field(source_rows,field):
    result=validate_row(source_rows['po']|{field:''},0)
    assert result['status']=='FAIL'
    assert any(field in msg for msg in result['errors'])

@pytest.mark.parametrize('field,value,status',[
 ('Division','Unknown','FAIL'),('Sub-Class','Unknown','WARN'),('Cost','1000','WARN'),
 ('Original Retail','500','WARN'),('Ship Dates','bad','FAIL'),('Cancel Dates','bad','FAIL'),
 ('Cancel Dates','2000-01-01','FAIL'),('Total Quantity','0','FAIL'),('Total Quantity','6','WARN'),
 ('Case-pack','0','FAIL'),('Case-pack','1','WARN'),('Case-pack','bad','FAIL'),('Location','UNKNOWN','WARN'),
 *[(f,v,'FAIL') for f in ('Cost','Reg Retail','Original Retail') for v in ('0','-1','NaN','Infinity','bad')],
 ('Total Quantity','Infinity','FAIL')])
def test_po_individual_rule(source_rows,field,value,status):
    result=validate_row(source_rows['po']|{field:value},0)
    assert result['status']==status,result

@pytest.mark.parametrize('field,value,code',[
 ('product_name','One','WEAK_TITLE'),('product_name','Long title '*20,'TITLE_TOO_LONG'),
 ('description','Short','WEAK_DESCRIPTION'),('image_url','','IMAGE_MISSING'),
 ('size','','CATEGORY_ATTRIBUTE_MISSING'),('colour','','CATEGORY_ATTRIBUTE_MISSING'),('material','','CATEGORY_ATTRIBUTE_MISSING'),
 ('brand','','ATTRIBUTE_INCOMPLETE'),('category','Unknown','UNSUPPORTED_CATEGORY'),
 ('image_url','invalid','INVALID_IMAGE_URL'),('vendor_approved','no','VENDOR_NOT_APPROVED')])
def test_catalog_individual_rule(source_rows,field,value,code):
    ingestion=ingest_dataframe(pd.DataFrame([source_rows['catalog']|{field:value}]))
    if ingestion.errors:
        assert any(e.code == code for e in ingestion.errors)
        return
    findings=[f for evaluator in (CatalogQualityAgent(),PolicyValidationAgent()) for f in evaluator.evaluate(ingestion.items[0]).findings]
    assert any(f['code']==code for f in findings),findings

@pytest.mark.parametrize('field,value',[('gtin','123'),('price','-1'),('price','bad'),('price','NaN'),('sku',''),('vendor_id','')])
def test_catalog_structural_rejection(source_rows,field,value):
    assert ingest_dataframe(pd.DataFrame([source_rows['catalog']|{field:value}])).errors


def test_multiple_defects_count_one_po(source_rows):
    result=validate_row(source_rows['po']|{'Cost':'bad','Case-pack':'0','Cancel Dates':'bad'},0)
    assert result['status']=='FAIL' and len(result['errors'])>=3


def test_recovery_that_introduces_new_defect(source_rows):
    clean=source_rows['po']
    assert validate_row(clean|{'Case-pack':'0'},0)['status']=='FAIL'
    assert validate_row(clean,0)['status']=='PASS'
    assert validate_row(clean|{'Ship Dates':'bad'},0)['status']=='FAIL'

def test_catalog_batch_rolls_back_on_evaluator_failure(source_rows,tmp_path,monkeypatch):
    from catalog_operations.persistence.repository import CatalogRepository
    from catalog_operations.services import process_upload
    from catalog_operations.orchestrator import CatalogOperationsOrchestrator
    repo=CatalogRepository('sqlite:///'+(tmp_path/'catalog.db').as_posix())
    process_upload(pd.DataFrame([source_rows['catalog']]),'original.csv',repo,True)
    original=repo.list_current_items()
    def fail(*args,**kwargs): raise RuntimeError('Injected evaluator failure')
    monkeypatch.setattr(CatalogOperationsOrchestrator,'evaluate',fail)
    with pytest.raises(RuntimeError,match='Injected'):
        process_upload(pd.DataFrame([source_rows['catalog']|{'sku':'REPLACEMENT'}]),'new.csv',repo,True)
    assert repo.list_current_items()==original
    repo.engine.dispose()
