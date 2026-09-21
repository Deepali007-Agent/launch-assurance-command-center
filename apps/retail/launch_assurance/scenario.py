"""Entirely synthetic, intentionally small scenario with traceable assumptions."""
from datetime import date, timedelta

def make_scenario():
    launch=date.today()+timedelta(days=7)
    vendor=dict(vendor_id='VENDOR-LA-001',legal_name='Fictional Launch Supplier',tax_id='DEMO-TAX-NOT-REAL',registration_id='DEMO-REG-NOT-REAL',country='India',currency='INR',payment_terms='Net 45',contact_email='launch@example.com',bank_information_status='Verified',document_status='Approved',document_expiry_date=str(launch+timedelta(days=365)),insurance_status='Valid',ethical_trade_status='Approved',vendor_authorization='Approved',incoterms='FOB',return_terms='Defects returnable',lead_time_days=30,minimum_order_quantity=6)
    items=[];pos=[];stock=[];shipments=[]
    for code,label in [('A','Black'),('B','Blue'),('C','Green'),('D','Red')]:
        sku='LA-DRESS-'+code
        items.append(dict(sku=sku,vendor_id=vendor['vendor_id'],vendor_name=vendor['legal_name'],product_name=f'Demo {label} Cotton Dress',brand='Fictional Launch Brand',category='Apparel',gender='Women',description='A cotton dress with reinforced seams and a comfortable regular fit.',price=1500,image_url=f'https://example.com/demo/{code}.jpg',colour=label,size='M',material='' if code=='B' else 'Cotton',vendor_approved=True,submitted_at=date.today().isoformat(),monthly_sales=90000,gross_margin_pct=60))
        pos.append({'PO_ID':'PO-LA-'+code,'SKU':sku,'Vendor ID':vendor['vendor_id'],'Vendor Name':vendor['legal_name'],'Division':'Womenswear','Class':'Apparel','Sub-Class':'Dresses','Vendor Style':'STYLE-LA-'+code,'Description':f'Demo {label} cotton dress','Color':label,'Case-pack':6,'Cost':1000 if code=='C' else 600,'Reg Retail':1500,'Original Retail':1500,'Total Quantity':180,'Location':'TX','Ship Dates':str(launch-timedelta(days=3)),'Cancel Dates':str(launch+timedelta(days=18)),'Brand Name':'Fictional Launch Brand','currency':'INR','gender':'Women'})
        stock.extend([dict(sku=sku,location='Mumbai',opening_stock=20,daily_demand=20,safety_stock=10),dict(sku=sku,location='Delhi',opening_stock=120,daily_demand=5,safety_stock=20)])
        shipments.append(dict(id='SHIP-'+code,sku=sku,destination='Mumbai',quantity=180,promised_day=0,milestone_delay_days=4 if code=='A' else 6 if code=='D' else 0,expedite_days_saved=3 if code=='A' else 0,expedite_cost=2000 if code=='A' else 0))
    return dict(id='LA-DEMO-001',name='Festive Dress Launch',date=str(launch),channel='Online · regional fulfilment',currency='INR',horizon_days=7,margin_floor_pct=45,transfer_lead_days=1,transfer_cost_per_unit=20,vendor=vendor,items=items,pos=pos,stock=stock,shipments=shipments)
