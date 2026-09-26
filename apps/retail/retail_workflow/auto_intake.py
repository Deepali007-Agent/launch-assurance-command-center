"""Local, single-writer intake. Immutable, hashed submissions; no approval side effects."""
import hashlib
import io
import json
from pathlib import Path
from datetime import date
import pandas as pd
from .store import WorkflowStore, now

ROLES = {"vendor", "catalog", "po"}

def schema(store):
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS auto_batches(external_id TEXT PRIMARY KEY,batch TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auto_jobs(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
          external_id TEXT NOT NULL,batch TEXT NOT NULL DEFAULT '',state TEXT NOT NULL,
          stage TEXT NOT NULL,detail TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auto_revisions(external_id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS auto_worker(id INTEGER PRIMARY KEY,heartbeat TEXT NOT NULL);
        """)

def read_submission(folder):
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8-sig'))
    for field in ('submission_id','batch_key','launch_name','submitted_by'):
        if not isinstance(manifest.get(field),str) or not manifest[field].strip():
            raise ValueError('Manifest requires '+field)
    if type(manifest.get('revision')) is not int or manifest['revision']<1:raise ValueError('Positive integer revision required.')
    files=manifest.get('files',{})
    if not ROLES.issubset(files) or set(files)-ROLES-{'inventory','shipments'}:
        raise ValueError('Provide vendor, catalog and po files; inventory and shipments are optional together.')
    if ('inventory' in files)!=('shipments' in files):
        raise ValueError('Inventory and shipments must be submitted together.')
    frames={}
    for role,spec in files.items():
        path=(folder/spec['name']).resolve()
        if not path.is_relative_to(folder.resolve()) or path.suffix.lower()!='.csv':
            raise ValueError('Only CSV files inside the submission folder are allowed.')
        data=path.read_bytes()
        if len(data)>20_000_000:raise ValueError('File exceeds 20 MB local intake limit.')
        if hashlib.sha256(data).hexdigest()!=spec['sha256']:
            raise ValueError(role+': checksum mismatch; file is incomplete or changed. Submit a new sealed folder.')
        frames[role]=pd.read_csv(io.BytesIO(data),keep_default_na=False)
        if frames[role].empty:raise ValueError(role+': file is empty.')
    # Structural checks happen before any business evidence is written.
    for role,key in [('vendor','vendor_id'),('catalog','sku')]:
        frame=frames[role]
        if key not in frame or frame[key].astype(str).str.strip().eq('').any() or frame[key].astype(str).str.strip().duplicated().any():
            raise ValueError(role+': unique nonblank '+key+' values required.')
    po=frames['po']
    if not {'PO_ID','SKU'}.issubset(po.columns):raise ValueError('PO_ID and SKU columns are required.')
    keys=po['PO_ID'].astype(str).str.strip()+'|'+po['SKU'].astype(str).str.strip()+'|'+po.get('line_id',pd.Series('',index=po.index)).astype(str)
    if keys.duplicated().any() or po[['PO_ID','SKU']].astype(str).apply(lambda s:s.str.strip().eq('')).any().any():
        raise ValueError('PO lines need nonblank identifiers and unique PO/SKU/line_id keys.')
    for team,assignment in manifest.get('owners',{}).items():
        from .store import TEAMS
        if team not in TEAMS or not str(assignment.get('name','')).strip():raise ValueError('Invalid owner mapping.')
        date.fromisoformat(assignment['due'])
    fingerprint=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    return manifest,frames,fingerprint

def update(store,identifier,state,stage,detail):
    with store.connect(True) as db:
        db.execute('UPDATE auto_jobs SET state=?,stage=?,detail=?,updated=? WHERE id=?',(state,stage,detail,now(),identifier))

def process(store,folder,repo_factory):
    manifest,frames,fingerprint=read_submission(folder)
    identifier=manifest['submission_id'];external=manifest['batch_key'];actor=manifest['submitted_by']
    with store.connect(True) as db:
        old=db.execute('SELECT * FROM auto_jobs WHERE id=?',(identifier,)).fetchone()
        if old:
            if old['fingerprint']!=fingerprint:raise ValueError('Submission ID already used with different contents; create a new submission ID.')
            if old['state'] in ('Complete','Needs correction','Cancelled'):return
        latest=db.execute('SELECT revision FROM auto_revisions WHERE external_id=?',(external,)).fetchone()
        if not old and latest and manifest['revision']<=latest[0]:raise ValueError('Stale revision rejected; submit a newer correction.')
        # One outstanding submission per batch prevents an old retry overwriting a correction.
        pending=db.execute("SELECT id FROM auto_jobs WHERE external_id=? AND id<>? AND state IN ('Processing','Retry required')",(external,identifier)).fetchone()
        if pending:raise ValueError('Retry or explicitly cancel earlier submission '+pending['id']+' first.')
        mapping=db.execute('SELECT batch FROM auto_batches WHERE external_id=?',(external,)).fetchone()
        if mapping:batch=mapping[0]
        else:
            from uuid import uuid4
            batch='BATCH-'+uuid4().hex[:12].upper()
            db.execute('INSERT INTO batches VALUES(?,?,?)',(batch,manifest['launch_name'],now()))
            db.execute('INSERT INTO auto_batches VALUES(?,?)',(external,batch))
            store._event(db,batch,'','Automatic batch created',actor,{'source':'local sealed folder'})
        db.execute("INSERT OR IGNORE INTO auto_jobs VALUES(?,?,?,?,'Processing','Received','',?)",(identifier,fingerprint,external,batch,now()))
        db.execute('INSERT INTO auto_revisions VALUES(?,?) ON CONFLICT(external_id) DO UPDATE SET revision=MAX(revision,excluded.revision)',(external,manifest['revision']))
    try:
        # PO also has an agents package; load the vendor engine under a unique name.
        import importlib.util
        spec=importlib.util.spec_from_file_location('intake_vendor_engine',Path(__file__).resolve().parents[2]/'onboarding/src/agents.py')
        vendor_engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(vendor_engine)
        assess_vendor=vendor_engine.assess_vendor
        from domain.po_engine import validate_row
        from .ui import records,save_onboarding,process_catalog_queue
        update(store,identifier,'Processing','Onboarding','Validating vendor and mandatory item information.')
        assessments=pd.DataFrame([dict(a,vendor_id=v['vendor_id']) for v in records(frames['vendor']) for a in assess_vendor(v)])
        save_onboarding(store,batch,frames['vendor'],assessments,frames['catalog'],actor)
        update(store,identifier,'Processing','Catalog','Checking content for items that passed mandatory setup.')
        process_catalog_queue(store,batch,repo_factory(batch))
        update(store,identifier,'Processing','Buying','Checking PO rules; existing approval gates remain binding.')
        results=[validate_row(row,i) for i,row in frames['po'].iterrows()]
        store.ingest_pos(batch,records(frames['po']),results,actor)
        if 'inventory' in frames:
            from launch_assurance.uploaded import prepare
            from launch_assurance.uploaded_ui import tables
            payload={'stock':records(frames['inventory']),'shipments':records(frames['shipments']),
                     'horizon':manifest.get('horizon',7),'launch_date':manifest.get('launch_date','')}
            try:
                date.fromisoformat(payload['launch_date'])
                prepare(store.board(batch),payload['stock'],payload['shipments'],payload['horizon'])
            except (ValueError,KeyError,TypeError) as exc:
                update(store,identifier,'Needs correction','Logistics','Source checks saved. Logistics not replaced: '+str(exc));return
            tables(store)
            with store.connect(True) as db:
                db.execute('INSERT OR REPLACE INTO logistics_inputs VALUES(?,?)',(batch,json.dumps(payload,allow_nan=False)))
        owners=manifest.get('owners',{})
        for row in store.requests(batch):
            assignment=owners.get(row['team'])
            if assignment and not row['owner']:
                date.fromisoformat(assignment['due'])
                # Intake states are derived by source processing, not manual work-status choices.
                # Assign only if still unassigned; preserve state and concurrent human edits.
                with store.connect(True) as db:
                    current=store._get(db,row['id'])
                    if not current['owner'] and current['team']==row['team']:
                        db.execute('UPDATE requests SET owner=?,due=?,etag=etag+1 WHERE id=?',
                                   (assignment['name'].strip(),assignment['due'],row['id']))
                        store._event(db,batch,row['id'],'Ownership changed',actor,
                                     {'to_team':row['team'],'to_owner':assignment['name'].strip(),
                                      'due':assignment['due'],'status':current['work_status'],
                                      'reason':'Automatic intake owner mapping'})
        blocked=sum(r['Status']=='Blocked' for r in store.board(batch))
        update(store,identifier,'Complete','Awaiting team review',f'{blocked} blocked requests. Open this launch for actions; human approvals remain required.')
    except Exception as exc:
        update(store,identifier,'Retry required','Processing interrupted',str(exc))
        raise

def scan(store,inbox,repo_factory):
    schema(store)
    with store.connect(True) as db:db.execute('INSERT OR REPLACE INTO auto_worker VALUES(1,?)',(now(),))
    outcomes=[]
    def order(folder):
        try:
            m=json.loads((folder/'manifest.json').read_text(encoding='utf-8-sig'))
            return (str(m.get('batch_key','')),int(m.get('revision',0)),folder.name)
        except (OSError,ValueError,TypeError):return ('',0,folder.name)
    for folder in sorted(Path(inbox).iterdir(),key=order):
        if not folder.is_dir() or not (folder/'manifest.json').exists():continue
        try:process(store,folder,repo_factory);outcomes.append((folder.name,'Checked'))
        except Exception as exc:outcomes.append((folder.name,str(exc)))
    return outcomes
