"""Generate fictional logistics inputs matching the 600 corrected PO rows."""
import csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'demo/logistics';out.mkdir(exist_ok=True)
with (ROOT/'demo/corrected/po.csv').open(encoding='utf-8-sig',newline='') as f:pos=list(csv.DictReader(f))
stock=[];ships=[]
for i,p in enumerate(pos,1):
 stock.extend([dict(sku=p['SKU'],location=p['Location'],opening_stock=0,daily_demand=10,safety_stock=0,transfer_cost_per_unit=5,transfer_lead_days=1),dict(sku=p['SKU'],location='DEMO_RESERVE',opening_stock=100,daily_demand=1,safety_stock=10,transfer_cost_per_unit=5,transfer_lead_days=1)])
 ships.append(dict(shipment_id=f'SHIP-DEMO-{i:04d}',sku=p['SKU'],destination=p['Location'],quantity=int(p['Total Quantity']),promised_day=0,milestone_delay_days=4,expedite_days_saved=3,expedite_cost=300))
for name,rows in [('inventory.csv',stock),('shipments.csv',ships)]:
 with (out/name).open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
print('Generated 1,200 inventory positions and 600 shipments; synthetic assumptions, no observed demand.')
