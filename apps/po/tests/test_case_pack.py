import pytest
from tests.test_po_engine import valid_row
from domain.po_engine import validate_row, build_decision_support


@pytest.mark.parametrize('quantity,pack',[(24,6),(6,6),(30,2),('24.0','6.0'),(24.0,6.0),(600000,12)])
def test_whole_packs_pass_divisibility(quantity,pack):
    result=validate_row(valid_row(**{'Total Quantity':quantity,'Case-pack':pack}),0)
    assert result['status']!='FAIL'
    assert 'Case-pack Divisibility' not in result['error_types']


@pytest.mark.parametrize('quantity,pack',[(23,6),(25,6),(5,6),(15,6)])
def test_partial_packs_block_order(quantity,pack):
    result=validate_row(valid_row(**{'Total Quantity':quantity,'Case-pack':pack}),0)
    assert result['status']=='FAIL'
    assert 'Case-pack Divisibility' in result['error_types']
    assert build_decision_support([result])[0]['recommendation']=='HOLD'


@pytest.mark.parametrize('field',['Case-pack','Total Quantity'])
@pytest.mark.parametrize('value',[0,-6,6.5,'6.5','',None,'bad',float('nan'),float('inf'),True])
def test_invalid_units_never_truncate_or_crash(field,value):
    result=validate_row(valid_row(**{field:value}),0)
    assert result['status']=='FAIL'
    assert 'Case-pack Divisibility' not in result['error_types']
    assert build_decision_support([result])[0]['recommendation']=='HOLD'


def test_pack_one_keeps_existing_warning():
    result=validate_row(valid_row(**{'Case-pack':1}),0)
    assert result['status']=='WARN'
    assert 'Case-pack = 1' in result['error_types']
