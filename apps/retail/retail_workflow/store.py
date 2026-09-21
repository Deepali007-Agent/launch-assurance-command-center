"""Versioned request ledger, durable handoffs and explicitly simulated ERP outbox.

SQLite transactions protect all state transitions. Approval is tied to a source
version; dependent execution additionally checks current upstream receipts.
This prototype records the actor's name; it does not authenticate their role.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
import math
import os
import sqlite3
import html
import re

ROOT=Path(__file__).resolve().parents[1]
TEAMS=('Vendor Operations','Finance','Item Onboarding','Catalog Operations','Buying Operations')
MANDATORY_ITEM=('sku','vendor_id','product_name','brand','category','price')
ENRICHMENT=('description','image_url','colour','size','material','gtin','monthly_revenue','monthly_units','gross_margin_pct')


class Conflict(ValueError): pass
class ReadConnection(sqlite3.Connection): pass


def now(): return datetime.now(timezone.utc).isoformat()
def encode(value): return json.dumps(value,sort_keys=True,default=str,allow_nan=False)
def digest(value): return sha256(encode(value).encode()).hexdigest()
def blank(value): return value is None or str(value).strip().lower() in ('','nan','none','null')
def text(value): return '' if blank(value) else str(value).strip()
def normalized(value): return text(value).casefold()
def plain(value): return html.unescape(re.sub(r'<[^>]+>','',str(value)))


class WorkflowStore:
    def __init__(self,path=None):
        self.path=Path(path or os.getenv('RETAIL_WORKFLOW_DB') or ROOT/'data/shared_workflow.db')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(
              id TEXT PRIMARY KEY,batch TEXT NOT NULL,kind TEXT NOT NULL,entity TEXT NOT NULL,
              version INTEGER NOT NULL,etag INTEGER NOT NULL,payload TEXT NOT NULL,
              team TEXT NOT NULL,owner TEXT NOT NULL DEFAULT '',due TEXT NOT NULL DEFAULT '',
              work_status TEXT NOT NULL DEFAULT 'Open',UNIQUE(batch,kind,entity));
            CREATE TABLE IF NOT EXISTS versions(request TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,
              created_at TEXT NOT NULL,PRIMARY KEY(request,version));
            CREATE TABLE IF NOT EXISTS intake_sources(request TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assessments(request TEXT NOT NULL,version INTEGER NOT NULL,engine TEXT NOT NULL,
              status TEXT NOT NULL,findings TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(request,version,engine));
            CREATE TABLE IF NOT EXISTS approvals(request TEXT NOT NULL,version INTEGER NOT NULL,basis TEXT NOT NULL,actor TEXT NOT NULL,
              reason TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(request,version));
            CREATE TABLE IF NOT EXISTS handoffs(id TEXT PRIMARY KEY,request TEXT NOT NULL,version INTEGER NOT NULL,
              state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',receipt TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,UNIQUE(request,version));
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,batch TEXT NOT NULL,request TEXT NOT NULL,
              event TEXT NOT NULL,actor TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,request TEXT NOT NULL,version INTEGER NOT NULL,
              basis TEXT NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL,receipt TEXT NOT NULL,created_at TEXT NOT NULL,
              UNIQUE(request,version,basis));
            CREATE INDEX IF NOT EXISTS request_batch ON requests(batch,kind);
            CREATE INDEX IF NOT EXISTS event_batch ON events(batch,id);
            ''')

    @contextmanager
    def connect(self,write=False):
        db=sqlite3.connect(self.path,timeout=30,factory=ReadConnection)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write: db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback();raise
        finally: db.close()

    def _event(self,db,batch,request,event,actor,detail):
        db.execute('INSERT INTO events(batch,request,event,actor,detail,created_at) VALUES(?,?,?,?,?,?)',
                   (batch,request,event,actor,encode(detail),now()))

    def batches(self):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM batches ORDER BY created_at DESC')]

    def create_batch(self,name,actor):
        if not text(name) or not text(actor):raise ValueError('Enter a batch name and your name.')
        identifier='BATCH-'+uuid4().hex[:12].upper()
        with self.connect(True) as db:
            db.execute('INSERT INTO batches VALUES(?,?,?)',(identifier,text(name),now()))
            self._event(db,identifier,'','Batch created',actor,{'name':name})
        return identifier

    @staticmethod
    def _row(row):
        if row is None:return None
        data=dict(row);data['payload']=json.loads(data['payload']);return data

    def _get(self,db,identifier):
        result=self._row(db.execute('SELECT * FROM requests WHERE id=?',(identifier,)).fetchone())
        if not result:raise ValueError('Request does not exist.')
        return result

    def _find(self,db,batch,kind,entity):
        if hasattr(db,'request_view'):return db.request_view.get((batch,kind,text(entity)))
        return self._row(db.execute('SELECT * FROM requests WHERE batch=? AND kind=? AND entity=?',(batch,kind,text(entity))).fetchone())

    def _prime_read_view(self,db,batch):
        """One transaction-local snapshot; never reused across writes or reruns."""
        requests=[self._row(r) for r in db.execute('SELECT * FROM requests WHERE batch=? ORDER BY kind,entity',(batch,))]
        db.request_view={(r['batch'],r['kind'],r['entity']):r for r in requests}
        db.assessment_view={(r['request'],r['version'],r['engine']):dict(r) for r in db.execute('SELECT a.* FROM assessments a JOIN requests r ON r.id=a.request AND r.version=a.version WHERE r.batch=?',(batch,))}
        db.approval_view={(r['request'],r['version'],r['basis']) for r in db.execute('SELECT a.* FROM approvals a JOIN requests r ON r.id=a.request AND r.version=a.version WHERE r.batch=?',(batch,))}
        db.receipt_view={(r['request'],r['version'],r['basis']):dict(r) for r in db.execute("SELECT a.* FROM outbox a JOIN requests r ON r.id=a.request AND r.version=a.version WHERE r.batch=? AND a.state='Acknowledged (simulated)'",(batch,))}
        db.gate_view={}
        return requests

    def requests(self,batch,kind=None):
        with self.connect() as db:
            sql='SELECT * FROM requests WHERE batch=?';args=[batch]
            if kind:sql+=' AND kind=?';args.append(kind)
            return [self._row(r) for r in db.execute(sql+' ORDER BY kind,entity',args)]

    def _upsert(self,db,batch,kind,entity,payload,actor):
        if not db.execute('SELECT 1 FROM batches WHERE id=?',(batch,)).fetchone():raise ValueError('Choose an existing workflow batch.')
        entity=text(entity)
        if not entity:raise ValueError('A stable entity identifier is required.')
        old=self._find(db,batch,kind,entity)
        packed=encode(payload)
        if old and encode(old['payload'])==packed:return old,False
        identifier=old['id'] if old else 'REQ-'+uuid4().hex[:16].upper()
        version=old['version']+1 if old else 1
        team={'vendor':'Vendor Operations','item':'Item Onboarding','po':'Buying Operations'}[kind]
        if old:
            db.execute('UPDATE requests SET version=?,etag=etag+1,payload=?,work_status=? WHERE id=?',
                       (version,packed,'Revalidation required',identifier))
        else:
            db.execute('INSERT INTO requests(id,batch,kind,entity,version,etag,payload,team) VALUES(?,?,?,?,1,1,?,?)',
                       (identifier,batch,kind,entity,packed,team))
        db.execute('INSERT INTO versions VALUES(?,?,?,?)',(identifier,version,packed,now()))
        self._event(db,batch,identifier,'Source revised' if old else 'Request created',actor,
                    {'kind':kind,'entity':entity,'version':version,'previous_version':old['version'] if old else None})
        return self._get(db,identifier),True

    def _assess(self,db,request,engine,status,findings):
        old=db.execute('SELECT * FROM assessments WHERE request=? AND version=? AND engine=?',
                       (request['id'],request['version'],engine)).fetchone()
        if old:
            if old['status']!=status or old['findings']!=encode(findings):
                raise Conflict('This version already has different evidence; submit a new version instead.')
            return
        db.execute('INSERT INTO assessments VALUES(?,?,?,?,?,?)',
                   (request['id'],request['version'],engine,status,encode(findings),now()))
        self._event(db,request['batch'],request['id'],'Assessment recorded',engine,{'version':request['version'],'status':status,'findings':findings})

    @staticmethod
    def mandatory_item(payload):
        findings=['Complete '+field for field in MANDATORY_ITEM if blank(payload.get(field))]
        try:
            if not math.isfinite(float(payload.get('price'))) or float(payload['price'])<=0:raise ValueError()
        except (TypeError,ValueError):findings.append('Provide a finite positive item price in INR')
        if 'currency' in payload and normalized(payload['currency'])!='inr':findings.append('Supply item prices in INR')
        return list(dict.fromkeys(findings))

    def ingest_onboarding(self,batch,vendors,items,vendor_results,actor):
        if not text(actor):raise ValueError('Enter the name recording this intake.')
        for records,key in ((vendors,'vendor_id'),(items,'sku')):
            ids=[text(p.get(key)) for p in records]
            if not ids or any(not i for i in ids) or len(ids)!=len(set(ids)):raise ValueError('Intake requires unique nonblank '+key+' values.')
        transferred=blocked=0
        with self.connect(True) as db:
            for payload in vendors:
                result=vendor_results.get(text(payload['vendor_id']))
                if result is None:raise ValueError('Vendor evidence missing for '+text(payload['vendor_id']))
                clean={k:v for k,v in payload.items() if k not in ('age_days','status','revision')}
                clean['_validation_evidence']=result
                request,changed=self._upsert(db,batch,'vendor',payload['vendor_id'],clean,actor)
                self._assess(db,request,'Vendor',result['status'],result['findings'])
            for payload in items:
                original=dict(payload)
                existing=self._find(db,batch,'item',payload.get('sku'))
                if existing:
                    baseline=db.execute('SELECT payload FROM intake_sources WHERE request=?',(existing['id'],)).fetchone()
                    if baseline:
                        previous=json.loads(baseline['payload']);payload=dict(payload)
                        for field in ENRICHMENT:
                            if payload.get(field)==previous.get(field) and field in existing['payload']:
                                payload[field]=existing['payload'][field]
                request,changed=self._upsert(db,batch,'item',payload['sku'],payload,actor)
                db.execute('INSERT INTO intake_sources VALUES(?,?) ON CONFLICT(request) DO UPDATE SET payload=excluded.payload',(request['id'],encode(original)))
                findings=self.mandatory_item(payload)
                if not self._find(db,batch,'vendor',payload.get('vendor_id')):findings.append('Provide the linked vendor in this batch')
                self._assess(db,request,'Item intake','Blocked' if findings else 'Clear',findings)
                if findings:blocked+=1;continue
                # Content preparation may proceed while vendor approval is pending.
                # Purchasing and simulated master creation retain their own gates.
                cursor=db.execute('INSERT OR IGNORE INTO handoffs(id,request,version,state,created_at) VALUES(?,?,?,?,?)',
                                  ('HO-'+uuid4().hex[:16],request['id'],request['version'],'Pending',now()))
                if cursor.rowcount:
                    db.execute('UPDATE requests SET team=?,work_status=?,etag=etag+1 WHERE id=?',('Catalog Operations','Awaiting Catalog',request['id']))
                    self._event(db,batch,request['id'],'Sent to Catalog',actor,{'version':request['version'],'vendor_approval':'Separate purchasing prerequisite'})
                transferred+=1
        return {'queued':transferred,'blocked':blocked}

    def catalog_queue(self,batch):
        with self.connect() as db:
            return [{**self._row(r),'handoff_state':r['handoff_state'],'attempts':r['attempts'],'handoff_error':r['handoff_error']}
                for r in db.execute('''SELECT r.*,h.state AS handoff_state,h.attempts,h.error AS handoff_error
                    FROM requests r JOIN handoffs h ON h.request=r.id AND h.version=r.version
                    WHERE r.batch=? AND h.state IN ('Pending','Failed') ORDER BY r.entity''',(batch,))]

    def complete_catalog(self,snapshots,results,actor='Catalog engine'):
        with self.connect(True) as db:
            for snapshot in snapshots:
                request=self._get(db,snapshot['id'])
                if request['version']!=snapshot['version']:raise Conflict('Item changed while Catalog was processing it. Retry the current version.')
                if request['entity'] not in results:raise ValueError('Catalog returned no result for '+request['entity'])
            for snapshot in snapshots:
                request=self._get(db,snapshot['id']);result=results[request['entity']]
                self._assess(db,request,'Catalog',result['status'],result['findings'])
                handoff=db.execute('SELECT * FROM handoffs WHERE request=? AND version=?',(request['id'],request['version'])).fetchone()
                if handoff['state']=='Accepted':continue
                db.execute('UPDATE handoffs SET state=?,attempts=attempts+1,error=?,receipt=? WHERE id=?',
                           ('Accepted','','CATALOG-'+digest(result)[:16],handoff['id']))
                db.execute('UPDATE requests SET work_status=?,etag=etag+1 WHERE id=?',
                           ('Awaiting approval' if result['status'] in ('Clear','Review') else 'Correction required',request['id']))
                self._event(db,request['batch'],request['id'],'Catalog receipt',actor,{'version':request['version'],'status':result['status'],'receipt':handoff['id']})

    def fail_catalog(self,snapshots,error):
        with self.connect(True) as db:
            for snapshot in snapshots:
                request=self._get(db,snapshot['id'])
                if request['version']!=snapshot['version']:continue
                db.execute("UPDATE handoffs SET state='Failed',attempts=attempts+1,error=? WHERE request=? AND version=? AND state!='Accepted'",
                           (str(error)[:1000],request['id'],request['version']))
                self._event(db,request['batch'],request['id'],'Catalog handoff failed','Catalog engine',{'error':str(error)[:1000],'version':request['version']})

    def enrich(self,batch,rows,actor):
        if not rows or not text(actor):raise ValueError('Provide corrected rows and your name.')
        if len({text(r.get('sku')) for r in rows})!=len(rows):raise ValueError('Duplicate SKU in the correction file.')
        with self.connect(True) as db:
            changes=[]
            for row in rows:
                request=self._find(db,batch,'item',row.get('sku'))
                if not request:raise ValueError('Unknown SKU; create it through Onboarding first: '+text(row.get('sku')))
                intake=self._assessment(db,request,'Item intake')
                if not intake or intake['status']!='Clear':raise ValueError('Resolve mandatory setup findings in Onboarding before enriching '+request['entity'])
                if text(row.get('workflow_revision'))!=str(request['version']):raise Conflict('Outdated enrichment template for '+request['entity']+'. Download the current template.')
                for field in MANDATORY_ITEM+('gender','currency'):
                    if field in row and text(row[field])!=text(request['payload'].get(field)):
                        # Excel/CSV numeric representations may differ while equal.
                        if field=='price' and float(row[field])==float(request['payload'][field]):continue
                        raise ValueError('Return changes to '+field+' to Item Onboarding; Catalog owns enrichment attributes.')
                payload=dict(request['payload'])
                payload.update({key:row[key] for key in ENRICHMENT if key in row})
                changes.append((request,payload))
            for request,payload in changes:
                new,changed=self._upsert(db,batch,'item',request['entity'],payload,actor)
                if not changed:continue
                self._assess(db,new,'Item intake','Clear',[])
                db.execute('INSERT INTO handoffs(id,request,version,state,created_at) VALUES(?,?,?,?,?)',('HO-'+uuid4().hex[:16],new['id'],new['version'],'Pending',now()))
                self._event(db,batch,new['id'],'Enrichment returned for validation',actor,{'version':new['version']})
        return len(changes)

    def ingest_pos(self,batch,rows,results,actor):
        if not text(actor):raise ValueError('Enter the name recording this PO request.')
        if len(rows)!=len(results):raise ValueError('Every PO line needs its source result.')
        keys=[]
        for row in rows:
            po=text(row.get('PO_ID',row.get('po_id')));sku=text(row.get('sku',row.get('SKU')))
            if not po or not sku:raise ValueError('Connected buying requires PO_ID and sku on every line.')
            keys.append(po+'|'+sku+'|'+text(row.get('line_id')))
        if len(set(keys))!=len(keys):raise ValueError('Repeated PO/SKU pairs require a stable line_id column.')
        identifiers=[]
        with self.connect(True) as db:
            for key,payload,result in zip(keys,rows,results):
                payload=dict(payload,_validation_evidence={'status':result['status'],'errors':result['errors'],'warnings':result['warnings']})
                request,changed=self._upsert(db,batch,'po',key,payload,actor)
                self._assess(db,request,'PO',{'PASS':'Clear','WARN':'Review','FAIL':'Blocked'}[result['status']],result['errors']+result['warnings'])
                identifiers.append(request['id'])
        return identifiers

    def _assessment(self,db,request,engine):
        if hasattr(db,'assessment_view'):return db.assessment_view.get((request['id'],request['version'],engine))
        row=db.execute('SELECT * FROM assessments WHERE request=? AND version=? AND engine=?',(request['id'],request['version'],engine)).fetchone()
        return dict(row) if row else None

    def _approved(self,db,request):
        if request['work_status'] in ('On hold','Returned'):return False
        if hasattr(db,'approval_view'):return (request['id'],request['version'],self._basis(db,request)) in db.approval_view
        return bool(db.execute('SELECT 1 FROM approvals WHERE request=? AND version=? AND basis=?',(request['id'],request['version'],self._basis(db,request))).fetchone())

    def _basis(self,db,request):
        dependencies=[]
        if request['kind'] in ('item','po'):
            payload=request['payload'];vendor=self._find(db,request['batch'],'vendor',payload.get('vendor_id',payload.get('Vendor ID')))
            if vendor:dependencies.append((vendor['id'],vendor['version']))
        if request['kind']=='po':
            item=self._find(db,request['batch'],'item',request['payload'].get('sku',request['payload'].get('SKU')))
            if item:dependencies.append((item['id'],item['version']))
        return digest({'request':request['id'],'version':request['version'],'dependencies':dependencies})

    def _receipt(self,db,request):
        if hasattr(db,'receipt_view'):return db.receipt_view.get((request['id'],request['version'],self._basis(db,request)))
        return db.execute("SELECT * FROM outbox WHERE request=? AND version=? AND basis=? AND state='Acknowledged (simulated)'",
                          (request['id'],request['version'],self._basis(db,request))).fetchone()

    def _gates(self,db,request,execution=False):
        key=(request['id'],execution)
        if hasattr(db,'gate_view') and key in db.gate_view:return db.gate_view[key]
        result=self._gates_uncached(db,request,execution)
        if hasattr(db,'gate_view'):db.gate_view[key]=result
        return result

    def _gates_uncached(self,db,request,execution=False):
        kind=request['kind'];payload=request['payload'];reasons=[]
        engine={'vendor':'Vendor','item':'Catalog','po':'PO'}[kind]
        assessment=self._assessment(db,request,engine)
        if not assessment:reasons.append(({'vendor':'Vendor Operations','item':'Catalog Operations','po':'Buying Operations'}[kind],engine+' validation is missing for this version'))
        elif assessment['status']=='Blocked':
            reasons.append(({'vendor':'Vendor Operations','item':'Catalog Operations','po':'Buying Operations'}[kind],engine+' correction required: '+'; '.join(plain(f) for f in json.loads(assessment['findings']))))
        if request['work_status'] in ('On hold','Returned'):reasons.append((request['team'],'Request is held or returned; resolve the handoff and return it to Open before review'))
        if kind=='item':
            intake=self._assessment(db,request,'Item intake')
            if not intake or intake['status']!='Clear':reasons.insert(0,('Item Onboarding','Mandatory item setup data is incomplete'+(': '+'; '.join(json.loads(intake['findings'])) if intake else '')))
        if kind=='po' or (kind=='item' and execution):
            vendor=self._find(db,request['batch'],'vendor',payload.get('vendor_id',payload.get('Vendor ID')))
            if not vendor:reasons.append(('Vendor Operations','Linked vendor is missing from this batch'))
            else:
                if self._gates(db,vendor):reasons.append(('Vendor Operations','Linked vendor has unresolved source requirements'))
                if not self._approved(db,vendor):reasons.append(('Finance','Current vendor version requires Finance approval'))
                if not self._receipt(db,vendor):reasons.append(('Vendor Operations','Vendor master has no current simulated ERP acknowledgement'))
        if kind=='po':
            item=self._find(db,request['batch'],'item',payload.get('sku',payload.get('SKU')))
            if not item:reasons.append(('Item Onboarding','Requested SKU has not been onboarded in this batch'))
            else:
                if self._gates(db,item,True):reasons.append(('Catalog Operations','Linked item still has content, setup or vendor prerequisites'))
                if not self._approved(db,item):reasons.append(('Catalog Operations','Current item version requires Catalog approval'))
                if not self._receipt(db,item):reasons.append(('Catalog Operations','Item setup has no current simulated ERP acknowledgement'))
                if normalized(payload.get('vendor_id',payload.get('Vendor ID')))!=normalized(item['payload'].get('vendor_id')):reasons.append(('Buying Operations','PO vendor does not match the item vendor'))
                for field,alias in [('category','Class'),('gender','Gender')]:
                    requested=payload.get(field,payload.get(alias));actual=item['payload'].get(field)
                    if blank(requested) or blank(actual) or normalized(requested)!=normalized(actual):
                        reasons.append(('Buying Operations',field.title()+' must be supplied and match the Catalog item'))
        if execution and not self._approved(db,request):reasons.append(({'vendor':'Finance','item':'Catalog Operations','po':'Buying Operations'}[kind],'Current version needs a recorded human approval'))
        return list(dict.fromkeys(reasons))

    def gates(self,identifiers,execution=False):
        with self.connect() as db:return {key:self._gates(db,self._get(db,key),execution) for key in identifiers}

    def approve(self,selections,actor,reason,accept_warnings=False):
        if not text(actor) or not text(reason):raise ValueError('A named reviewer and decision reason are required.')
        with self.connect(True) as db:
            requests=[]
            for identifier,etag in selections:
                request=self._get(db,identifier)
                if request['etag']!=etag:raise Conflict('Request changed. Refresh before recording approval.')
                gates=self._gates(db,request)
                if gates:raise ValueError(request['entity']+': '+gates[0][1])
                assessment=self._assessment(db,request,{'vendor':'Vendor','item':'Catalog','po':'PO'}[request['kind']])
                if assessment and assessment['status']=='Review' and not accept_warnings:
                    raise ValueError('Explicitly acknowledge the noncritical warnings for '+request['entity']+' before approval.')
                requests.append(request)
            for request in requests:
                if not self._approved(db,request):
                    db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?) ON CONFLICT(request,version) DO UPDATE SET basis=excluded.basis,actor=excluded.actor,reason=excluded.reason,created_at=excluded.created_at',
                               (request['id'],request['version'],self._basis(db,request),actor,reason,now()))
                    db.execute("UPDATE requests SET work_status='Approved',etag=etag+1 WHERE id=?",(request['id'],))
                    self._event(db,request['batch'],request['id'],'Human approval',actor,{'version':request['version'],'reason':reason,'noncritical_warnings_acknowledged':bool(accept_warnings),'responsibility':{'vendor':'Finance','item':'Catalog Operations','po':'Buying Operations'}[request['kind']]})

    def assign(self,identifier,etag,team,owner,due,status,actor,reason):
        if team not in TEAMS or status not in ('Open','In progress','Waiting approval','Returned','On hold'):raise ValueError('Choose a valid team and work status.')
        if not text(actor) or not text(reason):raise ValueError('Record your name and the handoff reason.')
        if due:
            try:datetime.strptime(due,'%Y-%m-%d')
            except ValueError:raise ValueError('Deadline must be YYYY-MM-DD.')
        with self.connect(True) as db:
            request=self._get(db,identifier)
            if request['etag']!=etag:raise Conflict('Request changed. Refresh and retry the assignment.')
            db.execute('UPDATE requests SET team=?,owner=?,due=?,work_status=?,etag=etag+1 WHERE id=?',(team,text(owner),due,status,identifier))
            self._event(db,request['batch'],identifier,'Ownership changed',actor,{'from_team':request['team'],'from_owner':request['owner'],'to_team':team,'to_owner':owner,'due':due,'status':status,'reason':reason})

    def simulate_erp(self,selections,actor,reason):
        if not text(actor) or not text(reason):raise ValueError('Record your name and reason for the simulation.')
        with self.connect(True) as db:
            requests=[]
            for identifier,etag in selections:
                request=self._get(db,identifier)
                if request['etag']!=etag:raise Conflict('Request changed. Refresh before simulation.')
                gates=self._gates(db,request,True)
                if gates:raise ValueError(request['entity']+': '+gates[0][1])
                requests.append(request)
            for request in requests:
                basis=self._basis(db,request)
                identifier='ERP-SIM-'+digest([request['id'],request['version'],basis])[:20]
                receipt='ACK-SIM-'+identifier.removeprefix('ERP-SIM-')
                inserted=db.execute('INSERT OR IGNORE INTO outbox VALUES(?,?,?,?,?,?,?,?)',
                    (identifier,request['id'],request['version'],basis,'Acknowledged (simulated)',encode(request['payload']),receipt,now()))
                if inserted.rowcount:
                    self._event(db,request['batch'],request['id'],'ERP acknowledgement (simulated)',actor,{'version':request['version'],'receipt':receipt,'reason':reason,'simulation':True})

    def history(self,batch):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM events WHERE batch=? ORDER BY id DESC',(batch,))]

    def token(self,batch):
        with self.connect() as db:return db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE batch=?',(batch,)).fetchone()[0]

    def findings(self,batch,kind=None):
        with self.connect() as db:
            rows=db.execute('SELECT r.kind,r.entity,a.engine,a.status,a.findings FROM assessments a JOIN requests r ON r.id=a.request AND r.version=a.version WHERE r.batch=?',(batch,)).fetchall()
            return [{'Type':r['kind'],'Record':r['entity'],'Stage':r['engine'],'Outcome':r['status'],'Finding':plain(message)} for r in rows if not kind or r['kind']==kind for message in json.loads(r['findings'])]

    def board(self,batch):
        with self.connect() as db:
            db.execute('BEGIN')
            requests=self._prime_read_view(db,batch)
            rows=[]
            for request in requests:
                gates=self._gates(db,request);execution_gates=self._gates(db,request,True)
                approved=self._approved(db,request)
                receipt=self._receipt(db,request)
                assessment=self._assessment(db,request,{'vendor':'Vendor','item':'Catalog','po':'PO'}[request['kind']])
                status='Blocked' if gates else 'Approved' if approved else 'Ready for approval'
                if not execution_gates and receipt:status='ERP acknowledged (simulated)'
                reason=gates[0] if gates else execution_gates[0] if execution_gates else (request['team'],'No prerequisites remain; simulated acknowledgement is available')
                rows.append({**request,'Status':status,'Next team':reason[0],'Next action':reason[1],
                             'Approval eligible':not gates,'Execution eligible':not execution_gates,
                             'Approved':approved,'ERP receipt':receipt['receipt'] if receipt and not execution_gates else '',
                             'Warning review':bool(assessment and assessment['status']=='Review'),
                             'Blockers':[{'team':t,'reason':r} for t,r in execution_gates]})
            return rows
