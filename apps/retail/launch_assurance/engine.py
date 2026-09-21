"""Deterministic shipment/inventory scenarios, constrained actions and net impact.

Stock is projected opening stock at launch. Demand is daily from launch day 0.
Receipts arrive before demand that day. Unmet demand is lost, not backordered.
Financial deltas use one SKU/location/day ledger: no overlapping risk totals.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

VERSION='launch-assurance-1.0'

def fingerprint(data):return sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:12]

def source_checks(scenario):
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('source_checks.py'))],input=json.dumps(scenario),capture_output=True,text=True,timeout=90)
    if result.returncode:raise ValueError('Source validation failed: '+result.stderr[-1200:])
    return json.loads(result.stdout)

def eligible(checks):
    return {sku for sku,r in checks['onboarding'].items() if r['passed'] and checks['catalog'][sku]['passed'] and checks['buying'][sku]['passed']}

def shipment_predictions(scenario):
    return [dict(s,expected_day=s['promised_day']+s['milestone_delay_days']) for s in scenario['shipments']]

def simulate(scenario,clear,expedited=(),transfers=()):
    horizon=scenario['horizon_days'];ships=shipment_predictions(scenario)
    stock={(r['sku'],r['location']):r['opening_stock'] for r in scenario['stock']}
    rows=[]
    for day in range(horizon):
        for ship in ships:
            arrival=ship['expected_day']-(ship['expedite_days_saved'] if ship['id'] in expedited else 0)
            if day==max(0,arrival):stock[ship['sku'],ship['destination']]+=ship['quantity']
        for move in transfers:
            if day==0:
                donor=(move['sku'],move['from'])
                if move['quantity']>stock[donor]:raise ValueError('Transfer exceeds donor inventory')
                stock[donor]-=move['quantity']
            if day==scenario['transfer_lead_days']:stock[move['sku'],move['to']]+=move['quantity']
        for position in scenario['stock']:
            sku=position['sku'];key=(sku,position['location']);demand=position['daily_demand']
            sold=min(stock[key],demand) if sku in clear else 0
            stock[key]-=sold
            rows.append(dict(sku=sku,location=key[1],day=day,demand=demand,sold=sold,lost=demand-sold,ending_stock=stock[key],release_eligible=sku in clear))
    po={r['SKU']:r for r in scenario['pos']}
    revenue=sum(r['sold']*po[r['sku']]['Reg Retail'] for r in rows)
    gross=sum(r['sold']*(po[r['sku']]['Reg Retail']-po[r['sku']]['Cost']) for r in rows)
    expense=sum(s['expedite_cost'] for s in ships if s['id'] in expedited)+sum(t['quantity']*scenario['transfer_cost_per_unit'] for t in transfers)
    locations=[]
    for position in scenario['stock']:
        matched=[r for r in rows if (r['sku'],r['location'])==(position['sku'],position['location'])]
        losses=[r['day'] for r in matched if r['lost']]
        locations.append(dict(sku=position['sku'],location=position['location'],demand=sum(r['demand'] for r in matched),sold=sum(r['sold'] for r in matched),lost=sum(r['lost'] for r in matched),first_shortfall_day=min(losses) if losses else None,reason='Stock shortfall' if position['sku'] in clear else 'Release held',ending_stock=matched[-1]['ending_stock']))
    return dict(rows=rows,locations=locations,revenue=round(revenue,2),gross_margin=round(gross,2),action_cost=expense,net_margin=round(gross-expense,2),lost_units=sum(r['lost'] for r in rows))

def recommend(scenario,checks):
    clear=eligible(checks);baseline=simulate(scenario,clear)
    expedited=[];transfers=[];actions=[]
    def action(identifier,team,description,sku,kind,**extra):
        actions.append(dict(id=identifier,team=team,owner=team+' lead (demo role)',status='Open',action=description,sku=sku,kind=kind,**extra))
    for item in scenario['items']:
        sku=item['sku']
        if not checks['onboarding'][sku]['passed']:
            action('SETUP-'+sku,'Item Onboarding','Correct required setup fields before downstream release.',sku,'setup')
        if not checks['catalog'][sku]['passed']:
            action('CONTENT-'+sku,'Catalog Operations','Complete material and revalidate customer-facing content.',sku,'content')
        if not checks['buying'][sku]['passed']:
            action('MARGIN-'+sku,'Buying Operations','Negotiate unit cost to INR 750; revalidate against the 45% margin floor.',sku,'margin')
    # Greedy feasible sequence: test marginal benefit against the current plan.
    # This is transparent scenario policy, not a global optimization claim.
    for ship in shipment_predictions(scenario):
        if ship['sku'] not in clear or ship['expedite_days_saved']<=0:continue
        before=simulate(scenario,clear,expedited,transfers)
        after=simulate(scenario,clear,expedited+[ship['id']],transfers)
        gain=after['net_margin']-before['net_margin']
        if gain>0:
            expedited.append(ship['id'])
            action('EXPEDITE-'+ship['id'],'Logistics',f"Expedite {ship['id']} by {ship['expedite_days_saved']} days; modeled net margin gain INR {gain:,.0f}.",ship['sku'],'expedite',shipment=ship['id'],cost=ship['expedite_cost'])
    for target in scenario['stock']:
        sku=target['sku']
        if sku not in clear:continue
        current=simulate(scenario,clear,expedited,transfers)
        lost=next(r['lost'] for r in current['locations'] if (r['sku'],r['location'])==(sku,target['location']))
        if not lost:continue
        for donor in scenario['stock']:
            if donor['sku']!=sku or donor['location']==target['location']:continue
            already=sum(t['quantity'] for t in transfers if (t['sku'],t['from'])==(sku,donor['location']))
            spare=max(0,donor['opening_stock']-donor['daily_demand']*scenario['horizon_days']-donor['safety_stock']-already)
            amount=min(spare,lost)
            if amount<=0:continue
            move=dict(sku=sku,**{'from':donor['location'],'to':target['location']},quantity=amount)
            after=simulate(scenario,clear,expedited,transfers+[move])
            gain=after['net_margin']-current['net_margin']
            if gain>0:
                transfers.append(move)
                action('MOVE-'+sku+'-'+target['location'],'Inventory Operations',f"Move {amount} units from {donor['location']} to {target['location']}; retain donor demand and safety stock.",sku,'transfer',transfer=move,cost=amount*scenario['transfer_cost_per_unit'])
                break
    action('RELEASE','Launch Operations',f"Review partial release of {len(clear)} of {len(scenario['items'])} SKUs; hold remaining SKUs until source checks pass.",'Eligible subset','release')
    return dict(clear=sorted(clear),held=sorted(set(checks['onboarding'])-clear),baseline=baseline,planned=simulate(scenario,clear,expedited,transfers),actions=actions,expedited=expedited,transfers=transfers)

def revalidate(scenario,baseline_checks,plan,selected,checker=source_checks):
    revised=deepcopy(scenario);chosen=[a for a in plan['actions'] if a['id'] in selected]
    for action in chosen:
        if action['kind']=='content':
            for item in revised['items']:
                if item['sku']==action['sku']:item['material']='Cotton'
        elif action['kind']=='margin':
            for po in revised['pos']:
                if po['SKU']==action['sku']:po['Cost']=750
    checks=checker(revised);clear=eligible(checks)
    expedited=[a['shipment'] for a in chosen if a['kind']=='expedite' and a['sku'] in clear]
    transfers=[a['transfer'] for a in chosen if a['kind']=='transfer' and a['sku'] in clear]
    # Approval is a separate prerequisite. Without review, no SKU is released.
    release_reviewed=any(a['kind']=='release' for a in chosen)
    result=simulate(revised,clear if release_reviewed else set(),expedited,transfers)
    baseline=simulate(scenario,eligible(baseline_checks))
    return dict(checks=checks,revised=revised,result=result,baseline=baseline,clear=sorted(clear),release_reviewed=release_reviewed,
                protected_revenue=round(result['revenue']-baseline['revenue'],2),protected_margin=round(result['net_margin']-baseline['net_margin'],2),selected=sorted(selected),version=VERSION,fingerprint=fingerprint(revised))
