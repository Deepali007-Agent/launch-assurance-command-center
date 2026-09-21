"""Compare explicitly selected standalone results to freshly evaluated uploaded inputs."""
import json
from datetime import datetime, timezone
from orchestration.intake import validate_publication

def reconcile_standalone(selected,fresh):
    if set(selected)!={'vendor','catalog','po'}:raise ValueError('Select all three standalone results.')
    cycles=set();references={}
    health={'vendor':'vendor_health','catalog':'sku_health','po':'po_health'}
    for kind,payload in selected.items():
        validate_publication(payload)
        if payload['schema']!=f'retail-intelligence.{kind}.v1':raise ValueError('Wrong source package for '+kind)
        cycles.add(payload['business_cycle_id'])
        stamp=payload.get('generated_at') or payload.get('provenance',{}).get('validated_at') or payload.get('published_at')
        try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(stamp.replace('Z','+00:00'))).total_seconds()
        except (ValueError,TypeError,AttributeError):raise ValueError('Standalone '+kind+' result needs a timezone-aware validation timestamp.')
        if age< -300 or age>86400:raise ValueError('Standalone '+kind+' evidence is stale; validate and publish again.')
        encode=lambda rows: sorted(json.dumps(r,sort_keys=True,default=str) for r in rows)
        if payload['policy_version']!=fresh[kind]['policy_version'] or encode(payload.get(health[kind],[]))!=encode(fresh[kind].get(health[kind],[])):
            raise ValueError('Standalone '+kind+' results do not match the selected files and current source rules. Revalidate and republish the same scope.')
        references[kind]={'source_run':payload['orchestration_run_id'],'source_cycle':payload['business_cycle_id'],'policy':payload['policy_version'],'verified_at':stamp,
            'method':'Source findings and policy matched a fresh run on the uploaded originals; source packages do not contain complete file hashes.'}
    if len(cycles)!=1:raise ValueError('Standalone results belong to different business cycles.')
    return references
