"""Batch-linked, deterministic alternatives. No ERP or carrier execution."""
import math
from collections import defaultdict
from hashlib import sha256
import json
POLICY='uploaded-logistics-1.0'
STOCK=('sku','location','opening_stock','daily_demand','safety_stock','transfer_cost_per_unit','transfer_lead_days')
SHIP=('shipment_id','sku','destination','quantity','promised_day','milestone_delay_days','expedite_days_saved','expedite_cost')

def number(value,name,integer=False):
 try:n=float(value)
 except (TypeError,ValueError):raise ValueError(f'{name}: supply a number.')
 if not math.isfinite(n) or n<0 or (integer and n!=int(n)):raise ValueError(f'{name}: expected a finite non-negative '+('integer.' if integer else 'number.'))
 return int(n) if integer else n

def prepare(board,stock,shipments,horizon):
 horizon=number(horizon,'Horizon',True)
 if not 1<=horizon<=31:raise ValueError('Horizon must be 1–31 days.')
 pos=[r for r in board if r['kind']=='po']
 if not pos:raise ValueError('Upload and validate PO requests for this batch first.')
 groups=defaultdict(list)
 for r in pos:groups[str(r['payload'].get('SKU','')).strip()].append(r)
 prices={};allowed={};quantities={};locations={}
 for sku,rows in groups.items():
  if not sku:raise ValueError('A PO request has no SKU.')
  payloads=[r['payload'] for r in rows]
  if any(str(p.get('currency','')).upper()!='INR' for p in payloads):raise ValueError(f'{sku}: valid INR currency required before commercial modeling.')
  amounts={(number(p.get('Cost'),'Cost'),number(p.get('Reg Retail'),'Reg Retail')) for p in payloads}
  if len(amounts)!=1 or any(c<=0 or p<=0 for c,p in amounts):raise ValueError(f'{sku}: requires consistent positive unit cost and retail price across its PO lines.')
  prices[sku]=next(iter(amounts));allowed[sku]=all(r['Execution eligible'] for r in rows)
  quantities[sku]=sum(number(p.get('Total Quantity'),'PO quantity',True) for p in payloads)
  locations[sku]={str(p.get('Location','')).strip() for p in payloads}
 def required(rows,columns):
  if not rows:raise ValueError('Provide both inventory and shipment rows (a zero-quantity shipment can explicitly indicate no inbound stock).')
  for row in rows:
   missing=[c for c in columns if c not in row or str(row[c]).strip()=='']
   if missing:raise ValueError('Missing fields: '+', '.join(missing))
 required(stock,STOCK);required(shipments,SHIP)
 clean_stock=[];keys=set()
 for row in stock:
  r=dict(row);r['sku']=str(r['sku']).strip();r['location']=str(r['location']).strip();key=(r['sku'],r['location'])
  if r['sku'] not in groups or key in keys:raise ValueError('Unknown SKU or duplicate SKU/location inventory: '+str(key))
  keys.add(key)
  for c in STOCK[2:]:r[c]=number(r[c],c,c not in ('transfer_cost_per_unit',))
  clean_stock.append(r)
 if {s for s,l in keys}!=set(groups):raise ValueError('Inventory must cover every PO SKU in this batch; partial coverage cannot be presented as a complete launch.')
 clean_ship=[];ids=set();inbound=defaultdict(int)
 for row in shipments:
  r=dict(row)
  for c in SHIP[:3]:r[c]=str(r[c]).strip()
  if r['shipment_id'] in ids:raise ValueError('Duplicate shipment ID.')
  ids.add(r['shipment_id'])
  if (r['sku'],r['destination']) not in keys:raise ValueError('Shipment must match an uploaded SKU/location inventory row.')
  if r['destination'] not in locations[r['sku']]:raise ValueError('Shipment destination must match the PO Location; use the same explicit location code.')
  for c in SHIP[3:]:r[c]=number(r[c],c,c!='expedite_cost')
  inbound[r['sku']]+=r['quantity'];clean_ship.append(r)
 if any(q>quantities[s] for s,q in inbound.items()):raise ValueError('Inbound shipment quantity exceeds the batch PO quantity for a SKU.')
 return dict(stock=clean_stock,shipments=clean_ship,horizon=horizon,prices=prices,allowed=allowed)

def ledger(model,sku,expedite=False,move=None,demand_factor=1):
 rows=[r for r in model['stock'] if r['sku']==sku];stock={r['location']:r['opening_stock'] for r in rows};sold=lost=0;daily_loss=[]
 cost=0
 if move:stock[move['from']]-=move['quantity'];cost=move['quantity']*move['unit_cost']
 ships=[s for s in model['shipments'] if s['sku']==sku]
 for s in ships:
  if expedite and s['expedite_days_saved']>0 and s['promised_day']+s['milestone_delay_days']>0:cost+=s['expedite_cost']
 for day in range(model['horizon']):
  for s in ships:
   arrival=max(0,s['promised_day']+s['milestone_delay_days']-(s['expedite_days_saved'] if expedite else 0))
   if arrival==day:stock[s['destination']]+=s['quantity']
  if move and day==move['lead_days']:stock[move['to']]+=move['quantity']
  for r in rows:
   demand=math.ceil(r['daily_demand']*demand_factor)
   amount=min(stock[r['location']],demand) if model['allowed'][sku] else 0
   stock[r['location']]-=amount;sold+=amount;lost+=demand-amount
   daily_loss.append({'location':r['location'],'day':day,'lost':demand-amount})
 unit_cost,retail=model['prices'][sku]
 return dict(revenue=sold*retail,margin=sold*(retail-unit_cost)-cost,cost=cost,unmet=lost,ending=stock,daily_loss=daily_loss)

def comparisons(model):
 output=[]
 for sku in sorted(model['prices']):
  baseline=ledger(model,sku);ships=[s for s in model['shipments'] if s['sku']==sku]
  options=[('Take no action',True,'Baseline; existing execution gates remain binding.',baseline,None)]
  can_exp=model['allowed'][sku] and any(s['quantity'] and s['expedite_days_saved']>0 and s['promised_day']+s['milestone_delay_days']>0 for s in ships)
  options.append(('Expedite',can_exp,'Source approvals/setup pending.' if not model['allowed'][sku] else 'No shipment with a reducible delay.' if not can_exp else 'Assumes the uploaded expedite offer is confirmed.',ledger(model,sku,True) if can_exp else baseline,None))
  best=None;best_result=None
  rows=[r for r in model['stock'] if r['sku']==sku]
  if model['allowed'][sku]:
   for donor in rows:
    spare=max(0,donor['opening_stock']-donor['daily_demand']*model['horizon']-donor['safety_stock'])
    for target in rows:
     if target['location']==donor['location'] or not spare or donor['transfer_lead_days']>=model['horizon']:continue
     quantity=min(spare,sum(r['lost'] for r in baseline['daily_loss'] if r['location']==target['location'] and r['day']>=donor['transfer_lead_days']))
     if not quantity:continue
     move=dict(sku=sku,**{'from':donor['location'],'to':target['location']},quantity=quantity,unit_cost=donor['transfer_cost_per_unit'],lead_days=donor['transfer_lead_days'])
     result=ledger(model,sku,move=move)
     if best_result is None or result['margin']>best_result['margin']:best,best_result=move,result
  options.append(('Reallocate stock',best is not None,'Source approvals/setup pending.' if not model['allowed'][sku] else 'No donor surplus after reserving demand and safety stock, or transfer arrives outside the horizon.' if best is None else f"Move {best['quantity']} units {best['from']} → {best['to']}; reserve donor demand and safety stock.",best_result or baseline,best))
  winner=max((o for o in options if o[1]),key=lambda o:o[3]['margin'])[0]
  stress_options=[]
  for n,f,reason,res,m in options:
   if not f:continue
   stressed=ledger(model,sku,n=='Expedite',m,demand_factor=1.2)
   reserve_ok=not m or stressed['ending'][m['from']]>=next(r['safety_stock'] for r in rows if r['location']==m['from'])
   if reserve_ok:stress_options.append((n,stressed['margin']))
  stress_winner=max(stress_options,key=lambda r:r[1])[0]
  for name,feasible,reason,result,move in options:
   stress=ledger(model,sku,name=='Expedite',move,demand_factor=1.2) if feasible else baseline
   stress_base=ledger(model,sku,demand_factor=1.2)
   gain=result['margin']-baseline['margin']
   output.append({'SKU':sku,'Option':name,'Feasible':feasible,'Revenue impact (INR)':result['revenue']-baseline['revenue'] if feasible else None,'Net margin impact (INR)':gain if feasible else None,'Unmet units':result['unmet'] if feasible else None,'Recommendation':'Recommended' if name==winner else 'Alternative' if feasible else 'Unavailable','Reason':reason,'Selection basis':'Highest net margin among feasible individual options; no-action wins ties.','Sensitivity +20% demand (INR)':stress['margin']-stress_base['margin'] if feasible else None,'Reversible':'Review can be changed before dispatch; physical execution is not modeled.','Preferred option at +20% demand':stress_winner,'Donor reserve at +20% demand':('Not applicable' if not move else 'Preserved' if stress['ending'][move['from']]>=next(r['safety_stock'] for r in rows if r['location']==move['from']) else 'BREACHED — reassess transfer'),'Operational risk':'Not assessed: capacity and execution reliability were not supplied.','Data completeness':'Required model fields supplied; source validity does not establish forecast accuracy.','Transfer':move})
 return output

def basis(token,data):return sha256(json.dumps([POLICY,token,data],sort_keys=True,default=str).encode()).hexdigest()
