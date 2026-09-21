"""Launch problem registry and deterministic coverage; no predictive claims."""
from datetime import date
from hashlib import sha256
import json
from orchestration.reconciliation import normalize

REGISTRY_VERSION = 'launch-controls-1.0'
PROBLEMS = [
 (1,'Incomplete onboarding data','Onboarding + Catalog','vendor, catalog','Mandatory attributes; channel fields','implemented'),
 (2,'Late PO errors','Buying Operations','po','Commercial and operational PO rules','implemented'),
 (3,'Recurring supplier failures','Vendor Intelligence','OTIF, ASN, compliance history','Historical supplier performance','planned'),
 (4,'Catalog defects','Catalog Intelligence','catalog','Content, identifiers and policy checks','implemented'),
 (5,'Unclear financial impact','Executive Orchestrator','po cost, quantity, currency','Measured commitment; no lost-revenue estimate','implemented'),
 (6,'Stockouts and excess stock','Inventory Intelligence','inventory, demand, open POs','SKU-location availability','planned'),
 (7,'Promotion and trend demand shifts','Scenario Lab','sales, promotions, seasonality','Demand scenarios','planned'),
 (8,'Unreliable inventory records','Inventory Reliability','ERP, warehouse, store inventory','Physical and system reconciliation','planned'),
 (9,'Avoidable returns','Returns / CX Intelligence','returns, reasons, product feedback','Return-driver analysis','planned'),
 (10,'Reactive shipment delays','Vendor + PO Risk','shipment milestones, lead-time history','Delivery risk prediction','planned'),
 (11,'Conflicting SKU and vendor records','Data Reliability','vendor, catalog, po','Exact identifiers, duplicates and relationships','implemented'),
 (12,'Untrustworthy recommendations','Governance','versioned evidence, review audit','Freshness, rule evidence and human gate','implemented'),
]

def context(launch_date='', channels='', locations='', requirements='', required_problems=()):
    if launch_date:
        date.fromisoformat(launch_date)
    fields = sorted({x.strip().lower().replace(' ', '_') for x in requirements.split(',') if x.strip()})
    return {'launch_date':launch_date,'channels':channels.strip(),'locations':locations.strip(),
            'required_catalog_fields':fields,'required_problems':sorted(set(map(int,required_problems))),
            'scope':'All records in the three supplied files', 'registry_version':REGISTRY_VERSION}

def fingerprint(value):
    return sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def evaluate(value, frames, report):
    blockers=[]; findings=[]
    catalog=normalize(frames['catalog'])
    for field in value['required_catalog_fields']:
        missing = catalog if field not in catalog else catalog[catalog[field].fillna('').astype(str).str.strip().eq('')]
        for _, row in missing.iterrows():
            findings.append({'Source':'Launch requirements','Identifier':str(row.get('sku','Unknown SKU')),
                'Severity':'CRITICAL','Owner':'Catalog Operations','Due':value['launch_date'] or 'Before launch',
                'Evidence required':f'Supply {field} for the declared channel requirements',
                'Status':'Open','Revalidation':'Required'})
    if findings: blockers.append(f'{len(findings)} mandatory launch attribute gaps require correction.')
    if value['launch_date'] and date.fromisoformat(value['launch_date']) < date.today():
        blockers.append('The planned launch date has passed; confirm a new launch date and revalidate.')
    rows=[]
    for number,problem,owner,inputs,scope,implementation in PROBLEMS:
        supported=implementation=='implemented'
        state='Evaluated' if supported else 'Not yet supported'
        outcome='See source findings' if supported else 'No conclusion available'
        if number==1 and findings:outcome='Hold: mandatory launch attributes missing'
        if number==5 and report['financial']['coverage_pct']<100:state='Evidence missing';outcome='Hold: incomplete commercial coverage'
        if number==11:outcome='Passed' if not report['reconciliation_issues'] else 'Hold: conflicting evidence'
        if number==12:outcome='Human decision required; freshness checked at review'
        required=number in value['required_problems']
        if required and not supported:blockers.append(f'Required control unavailable: {problem}.')
        rows.append({'Priority':number,'Problem':problem,'Responsible workspace':owner,'Coverage':state,
                     'Scope':scope,'Required inputs':inputs,'Required for this launch':required,'Outcome':outcome})
    return {'context':value,'context_hash':fingerprint(value),'coverage':rows,'blockers':blockers,'actions':findings}

def prioritized(actions, launch_date):
    return sorted(actions,key=lambda a:(0 if a.get('Severity') in {'CRITICAL','BLOCKED'} else 1,a.get('Due') or launch_date or '9999',a.get('Source',''),a.get('Identifier','')))
