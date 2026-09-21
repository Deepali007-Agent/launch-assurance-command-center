"""Durable cycle reopening and auditable remediation assignments."""
from orchestration.local_safety import guarded_write
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import os
from uuid import uuid4

_LOCK = threading.RLock()


def saved_cycles(runs: Path):
    """Return the newest evidence version for each persisted cycle."""
    latest = {}
    for path in sorted(runs.glob('*/result.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            result = json.loads(path.read_text(encoding='utf-8'))
            cycle_id = result.get('review_scope_id') or result.get('business_cycle_id')
            if cycle_id and cycle_id not in latest:
                result['saved_at'] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                latest[cycle_id] = result
        except (OSError, ValueError):
            continue
    return latest


@dataclass
class SavedInput:
    name: str
    payload: bytes

    def getvalue(self):
        return self.payload


def saved_inputs(result, runs: Path):
    folder = Path(result['folder']).resolve()
    if not folder.is_relative_to(runs.resolve()):
        raise ValueError('Saved evidence must belong to this workspace.')
    uploads = {}
    for kind in ('vendor', 'catalog', 'po'):
        name = result['files'][kind]
        suffix = Path(name).suffix.lower()
        if suffix not in {'.csv', '.xlsx'}:
            raise ValueError('Saved evidence uses an unsupported format.')
        payload = (folder / (kind + suffix)).read_bytes()
        if hashlib.sha256(payload).hexdigest() != result['hashes'][kind]:
            raise ValueError(f'Saved {kind} evidence has changed. Supply the original file or revalidate a replacement.')
        uploads[kind] = SavedInput(name, payload)
    return uploads


def action_key(action):
    evidence = [action.get(k, '') for k in ('Source', 'Identifier', 'Severity', 'Evidence required')]
    if action.get('SKU') or action.get('Location'):
        evidence += [action.get('SKU',''),action.get('Location','')]
    return hashlib.sha256(json.dumps(evidence, ensure_ascii=False).encode()).hexdigest()[:24]


class ActionRegistry:
    def __init__(self, root: Path, cycle_id: str):
        if not re.fullmatch(r'CYCLE-[A-F0-9]{16}', cycle_id):
            raise ValueError('Invalid cycle identity.')
        self.path = root / (cycle_id + '.json')

    def load(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'actions': {}, 'events': []}

    def _save(self, state):
        state['revision'] = state.get('revision', 0) + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.' + uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)

    @guarded_write
    def observe(self, actions, run_id):
        """Only a completed revalidation can resolve an action."""
        with _LOCK:
            state = self.load()
            current = {action_key(action): action for action in actions}
            for key, row in state['actions'].items():
                if key not in current and row['status'] != 'Resolved by revalidation':
                    row.update(status='Resolved by revalidation', resolved_run_id=run_id)
                    state['events'].append({'event': 'RESOLVED_BY_REVALIDATION', 'action_id': key, 'run_id': run_id, 'actor': 'SYSTEM', 'at': datetime.now(timezone.utc).isoformat()})
            for key, action in current.items():
                old = state['actions'].get(key, {})
                if old.get('status') == 'Resolved by revalidation':
                    old.pop('resolved_run_id', None)
                    state['events'].append({'event': 'REOPENED_BY_REVALIDATION', 'action_id': key, 'run_id': run_id, 'actor': 'SYSTEM', 'at': datetime.now(timezone.utc).isoformat()})
                state['actions'][key] = old | {'evidence': action, 'run_id': run_id,
                    'assigned_owner': old.get('assigned_owner', ''), 'due_date': old.get('due_date', ''),
                    'status': old.get('status', 'Open') if old.get('status') != 'Resolved by revalidation' else 'Open'}
            self._save(state)

    @guarded_write
    def assign_group(self, action_ids, owner, deadline, actor, reason, escalation_owner='', expected_revision=None, assigned_team=None):
        """Assign a filtered correction batch atomically; evidence and dependencies stay intact."""
        if not all(str(v).strip() for v in (owner,actor,reason)):
            raise ValueError('Owner, recorder and reason are required.')
        try: date.fromisoformat(deadline)
        except (ValueError,TypeError): raise ValueError('A calendar deadline in YYYY-MM-DD format is required.')
        with _LOCK:
            state=self.load()
            if expected_revision is not None and expected_revision!=state.get('revision',len(state['events'])):
                raise ValueError('Actions changed in another session. Reload before saving.')
            keys=list(dict.fromkeys(action_ids))
            if not keys or any(k not in state['actions'] or state['actions'][k]['status']=='Resolved by revalidation' for k in keys):
                raise ValueError('Choose active correction actions.')
            for key in keys:
                row=state['actions'][key]
                previous_owner=row.get('assigned_owner','')
                previous_team=row.get('assigned_team') or row['evidence'].get('Owner','')
                if assigned_team: row['assigned_team']=assigned_team.strip()
                row.update(assigned_owner=owner.strip(),due_date=deadline,escalation_owner=escalation_owner.strip())
                state['events'].append({'event':'ASSIGNMENT_UPDATED','action_id':key,'run_id':row['run_id'],
                    'actor':actor.strip(),'reason':reason.strip(),'previous_owner':previous_owner,'previous_team':previous_team,'assigned_team':row.get('assigned_team',previous_team),'assigned_owner':owner.strip(),'due_date':deadline,
                    'escalation_owner':escalation_owner.strip(),'at':datetime.now(timezone.utc).isoformat()})
            self._save(state)

    @guarded_write
    def assign(self, action_id, assigned_owner, due_date, status, actor, reason, dependencies=None, expected_revision=None, escalation_owner=None, escalation_note=None, assigned_team=None):
        if not actor.strip() or not reason.strip():
            raise ValueError('Your name and an assignment reason are required.')
        if not assigned_owner.strip():
            raise ValueError('A named action owner is required.')
        try:
            date.fromisoformat(due_date)
        except (ValueError, TypeError):
            raise ValueError('A calendar deadline in YYYY-MM-DD format is required.')
        if status not in {'Open', 'In progress', 'Waiting for approval', 'Returned to team', 'Ready to revalidate'}:
            raise ValueError('Only source revalidation can resolve an action.')
        with _LOCK:
            state = self.load()
            if expected_revision is not None and expected_revision != state.get('revision', len(state['events'])):
                raise ValueError('Actions changed in another session. Reload before saving.')
            if action_id not in state['actions']:
                raise ValueError('Unknown action.')
            row = state['actions'][action_id]
            if row['status'] == 'Resolved by revalidation':
                raise ValueError('This action was resolved by revalidation.')
            from orchestration.action_queue import validate_dependencies
            dependencies = validate_dependencies(state['actions'], action_id, dependencies if dependencies is not None else row.get('dependencies', []))
            previous_owner=row.get('assigned_owner','')
            previous_team=row.get('assigned_team') or row['evidence'].get('Owner','')
            if assigned_team is not None:
                if not assigned_team.strip(): raise ValueError('Receiving team is required.')
                row['assigned_team']=assigned_team.strip()
            row['dependencies'] = dependencies
            row.update(assigned_owner=assigned_owner.strip(), due_date=due_date, status=status)
            if escalation_owner is not None: row['escalation_owner']=escalation_owner.strip()
            if escalation_note is not None: row['escalation_note']=escalation_note.strip()
            state['events'].append({'event': 'ASSIGNMENT_UPDATED', 'action_id': action_id,
                'run_id': row['run_id'], 'actor': actor.strip(), 'reason': reason.strip(),
                'previous_owner':previous_owner,'previous_team':previous_team,'assigned_team':row.get('assigned_team',previous_team),
                'assigned_owner': assigned_owner.strip(), 'due_date': due_date, 'status': status, 'dependencies': dependencies,
                'escalation_owner': row.get('escalation_owner',''), 'escalation_note':row.get('escalation_note',''),
                'at': datetime.now(timezone.utc).isoformat()})
            self._save(state)
