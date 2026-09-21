"""Generate entirely fictional 600-row demo inputs; no source data is read."""
import copy
import csv
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'demo'

def write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def generate():
    today=date.today();submitted=datetime.now(timezone.utc).isoformat()
    clean={k:[] for k in ('vendor','catalog','po')}
    for i in range(1,601):
        vendor=f'VENDOR-DEMO-{i:04d}';sku=f'SKU-DEMO-{i:04d}';name=f'Fictional Supplier {i:04d}'
        clean['vendor'].append(dict(vendor_id=vendor,legal_name=name,trading_name=name,vendor_type='Manufacturer',country='India',market='IN',currency='INR',tax_id=f'DEMO-NOT-VALID-TAX-{i:04d}',registration_id=f'DEMO-NOT-VALID-REG-{i:04d}',primary_contact=f'Fictional Contact {i}',contact_email=f'demo{i}@example.com',payment_terms='Net 45',incoterms='FOB',lead_time_days=30,minimum_order_quantity=24,return_terms='Defects accepted within 30 days',bank_information_status='Verified',document_type='Business registration',document_status='Approved',document_issue_date=str(today-timedelta(days=30)),document_expiry_date=str(today+timedelta(days=365)),insurance_status='Valid',ethical_trade_status='Approved',sustainability_status='Current',vendor_authorization='Approved',submitted_at=submitted,onboarding_owner='Vendor Operations',compliance_owner='Compliance',commercial_owner='Buying',lifecycle_status='Received',revision_number=1,source_business_unit='Fashion',planned_purchase_value=39000,value_currency='INR',planned_item_count=1,strategic_tier='Core',planned_launch_date=str(today+timedelta(days=60)),downstream_dependency='Catalog and PO',approved_at=''))
        digits=f'200000{i:06d}';gtin=digits+str((-sum(int(x)*(1 if j%2==0 else 3) for j,x in enumerate(digits)))%10)
        clean['catalog'].append(dict(sku=sku,vendor_id=vendor,vendor_name=name,product_name=f'Demo Cotton Shirt {i}',brand='Fictional Demo Brand',category='Apparel',gender='Men',description='Synthetic cotton shirt with regular fit and reinforced seams for demonstration only.',price=1500,gtin=gtin,image_url=f'https://example.com/demo/{sku}.jpg',colour='Black',size='M',material='Cotton',submitted_at=submitted,vendor_approved=True,monthly_sales=90000,gross_margin_pct=52))
        clean['po'].append({'Vendor ID':vendor,'Vendor Name':name,'Division':'Menswear','Class':'Apparel','Sub-Class':'Shirts','Vendor Style':f'DEMO-STYLE-{i:04d}','Description':'Synthetic demonstration cotton shirt','Color':'Black','Case-pack':6,'Cost':650,'Reg Retail':1500,'Original Retail':1500,'Total Quantity':60,'Location':'TX','Ship Dates':str(today+timedelta(days=30)),'Cancel Dates':str(today+timedelta(days=51)),'PO_ID':f'PO-DEMO-{i:04d}','Brand Name':'Fictional Demo Brand','SKU':sku,'currency':'INR','gender':'Men'})
    dirty=copy.deepcopy(clean);answers=[]
    for kind,start,field,value in [('vendor',1,'tax_id',''),('vendor',16,'contact_email','invalid-email'),('catalog',31,'size',''),('catalog',46,'material',''),('catalog',61,'image_url',''),('po',76,'Cancel Dates',str(today)),('po',91,'currency',''),('po',106,'Cost',0),('po',121,'Total Quantity',0),('po',136,'Total Quantity',61)]:
        for i in range(start,start+15):
            row=dirty[kind][i-1];answers.append(dict(file=kind+'.csv',record=i,csv_row=i+1,field=field,deliberate_value=value,corrected_value=row[field]));row[field]=value
    for label,bundle in [('corrected',clean),('with_errors',dirty)]:
        for kind,rows in bundle.items():write(ROOT/label/(kind+'.csv'),rows)
    write(ROOT/'error_answer_key.csv',answers)
    print('Generated six synthetic CSV files, 600 data rows each.')

if __name__=='__main__':generate()
