"""Explicit launch subsets and user-maintained, immutable policy versions."""
import hashlib
import json
import re
from pathlib import Path
from orchestration.reconciliation import normalize


def tokens(text):
    return sorted({x.strip().upper() for x in text.split(',') if x.strip()})


def scoped_frames(frames, skus='', locations=''):
    frames={k:normalize(v) for k,v in frames.items()}
    wanted=tokens(skus); places=tokens(locations)
    for kind,fields in [('catalog',['sku','vendor_id']),('vendor',['vendor_id']),('po',['sku','vendor_id'])]:
        for field in fields:
            if field not in frames[kind]: raise ValueError(f'{kind}: missing scope identifier {field}.')
    catalog=frames['catalog']; po=frames['po']; vendor=frames['vendor']
    if wanted:
        missing=set(wanted)-set(catalog.sku.astype(str).str.strip().str.upper())
        if missing: raise ValueError('Unknown scope SKUs: '+', '.join(sorted(missing)))
        catalog=catalog[catalog.sku.astype(str).str.strip().str.upper().isin(wanted)]
        po=po[po.sku.astype(str).str.strip().str.upper().isin(wanted)]
    if places:
        if 'location' not in po: raise ValueError('PO location is required for location filtering.')
        missing=set(places)-set(po.location.astype(str).str.strip().str.upper())
        if missing: raise ValueError('Unknown scope locations: '+', '.join(sorted(missing)))
        po=po[po.location.astype(str).str.strip().str.upper().isin(places)]
        catalog=catalog[catalog.sku.astype(str).str.strip().str.upper().isin(po.sku.astype(str).str.strip().str.upper())]
    if wanted or places:
        ids=set(catalog.vendor_id.astype(str).str.strip().str.upper()) | set(po.vendor_id.astype(str).str.strip().str.upper())
        vendor=vendor[vendor.vendor_id.astype(str).str.strip().str.upper().isin(ids)]
    result={'vendor':vendor.copy(),'catalog':catalog.copy(),'po':po.copy()}
    if any(v.empty for v in result.values()): raise ValueError('Launch scope must contain vendors, catalog SKUs and PO lines.')
    return result


def scope_identity(cycle_id, launch_name):
    return 'CYCLE-'+hashlib.sha256((cycle_id+'|'+launch_name.strip()).encode()).hexdigest()[:16].upper() if launch_name.strip() else cycle_id


class PolicyStore:
    def __init__(self, root): self.root=Path(root)
    def list(self):
        return {p.stem:json.loads(p.read_text(encoding='utf-8')) for p in sorted(self.root.glob('*.json'))}
    def save(self,name,version,fields,basis,actor):
        if not all(str(x).strip() for x in (name,version,fields,basis,actor)):
            raise ValueError('Policy name, version, required fields, basis and author are required.')
        required=sorted({x.strip().lower().replace(' ','_') for x in fields.split(',') if x.strip()})
        if not required or any(not re.fullmatch(r'[a-z][a-z0-9_]*',x) for x in required): raise ValueError('Use valid catalog column names separated by commas.')
        policy={'name':name.strip(),'version':version.strip(),'fields':required,'basis':basis.strip(),'author':actor.strip(),'authority':'Local team policy; not external channel certification'}
        key=hashlib.sha256((policy['name']+'|'+policy['version']).encode()).hexdigest()[:24]
        self.root.mkdir(parents=True,exist_ok=True)
        from orchestration.local_safety import local_lock
        with local_lock(self.root/'policy.lock'):
            path=self.root/(key+'.json')
            if path.exists(): raise ValueError('That policy version already exists. Create a new version.')
            path.write_text(json.dumps(policy,indent=2),encoding='utf-8')
        return key
