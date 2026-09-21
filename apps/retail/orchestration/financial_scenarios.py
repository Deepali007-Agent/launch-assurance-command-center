"""Separate, explicitly assumed financial scenarios. No inferred sales forecast."""
from decimal import Decimal, InvalidOperation
from orchestration.reconciliation import normalize


def financial_scenarios(po, affected_skus=(), affected_vendors=(), affected_pos=(), sell_through=None, affected_line_ids=None):
    po=normalize(po); total=len(po); measured=0; amounts={}
    if sell_through is not None:
        rate=Decimal(str(sell_through))/100
        if not rate.is_finite() or not 0<=rate<=1: raise ValueError('Sell-through assumption must be between 0 and 100 percent.')
    else: rate=None
    for row in po.to_dict('records'):
        try:
            price=Decimal(str(row.get('reg_retail',''))); cost=Decimal(str(row.get('cost','')))
            qty=Decimal(str(row.get('total_quantity',row.get('quantity',''))))
            currency=str(row.get('currency','')).strip().upper()
            if any(not x.is_finite() or x<=0 for x in (price,cost,qty)): continue
            if len(currency)!=3 or not currency.isascii() or not currency.isalpha(): continue
            if max(price,cost)*qty>Decimal('1000000000000'): continue
            revenue=(price*qty).quantize(Decimal('.01')); margin=((price-cost)*qty).quantize(Decimal('.01'))
        except (InvalidOperation,ValueError): continue
        measured+=1
        impacted=(str(row.get('sku','')).strip().upper() in affected_skus or str(row.get('vendor_id','')).strip().upper() in affected_vendors or str(row.get('po_id','')).strip().upper() in affected_pos)
        if affected_line_ids is not None:
            from orchestration.decision_workflow import line_id
            impacted=line_id(row) in affected_line_ids
        value=amounts.setdefault(currency,{'Retail value at full sell-through':Decimal(0),'Gross margin at full sell-through':Decimal(0),'Affected retail value':Decimal(0),'Affected gross margin':Decimal(0)})
        value['Retail value at full sell-through']+=revenue;value['Gross margin at full sell-through']+=margin
        if impacted:value['Affected retail value']+=revenue;value['Affected gross margin']+=margin
    rows=[]
    for currency,values in sorted(amounts.items()):
        row={'Currency':currency,**{k:str(v) for k,v in values.items()}}
        if rate is not None:
            row['Scenario revenue exposure']=str((values['Affected retail value']*rate).quantize(Decimal('.01')))
            row['Scenario gross margin exposure']=str((values['Affected gross margin']*rate).quantize(Decimal('.01')))
        rows.append(row)
    return {'rows':rows,'coverage_pct':round(100*measured/total,2) if total else 0,'measured_lines':measured,'total_lines':total,'sell_through_pct':sell_through,
        'basis':'Retail value = reg_retail × PO quantity. Gross margin = (reg_retail − cost) × quantity. Affected lines counted once. Scenario exposure multiplies affected values by the user sell-through assumption.',
        'limitations':'Scenario estimates, not observed lost sales, forecast demand or net profit. No FX conversion; taxes, discounts, returns and other costs excluded. Missing inputs remain unmeasured.'}
