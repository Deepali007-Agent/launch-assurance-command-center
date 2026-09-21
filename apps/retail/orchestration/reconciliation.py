"""Cycle reconciliation. PO commitment is counted once, in its supplied currency."""
from decimal import Decimal, InvalidOperation
import pandas as pd

VERSION = 'retail-cycle-controls-2.0'


def normalize(frame):
    frame = frame.copy()
    frame.columns = [str(c).strip().lower().replace(' ', '_').replace('-', '_') for c in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError('Duplicate column names after normalization.')
    return frame


def reconcile(frames):
    missing = {'vendor', 'catalog', 'po'} - frames.keys()
    if missing:
        raise ValueError('Missing datasets: ' + ', '.join(sorted(missing)))
    frames = {k: normalize(v) for k, v in frames.items()}
    required = {'vendor': ['vendor_id'], 'catalog': ['sku', 'vendor_id'], 'po': ['sku', 'vendor_id', 'po_id']}
    for kind, fields in required.items():
        frame = frames[kind]
        if len(frame) == 0:
            raise ValueError(f'{kind}: no records supplied.')
        for field in fields:
            if field not in frame:
                raise ValueError(f'{kind}: missing mandatory column {field}.')
            frame[field] = frame[field].fillna('').astype(str).str.strip().str.upper()
            if frame[field].eq('').any():
                raise ValueError(f'{kind}: blank {field}.')
    for kind, fields in [('vendor', ['vendor_id']), ('catalog', ['sku']), ('po', ['po_id', 'sku', 'location'] if 'location' in frames['po'] else ['po_id', 'sku'])]:
        if frames[kind].duplicated(fields).any():
            raise ValueError(f'{kind}: duplicate identity ({", ".join(fields)}).')
    vendors = set(frames['vendor'].vendor_id)
    mapping = dict(zip(frames['catalog'].sku, frames['catalog'].vendor_id))
    issues = []
    for kind in ('catalog', 'po'):
        for vendor in sorted(set(frames[kind].vendor_id) - vendors):
            issues.append(f'{kind}: vendor {vendor} is missing from Vendor.')
    for row in frames['po'].itertuples():
        if row.sku not in mapping:
            issues.append(f'PO: SKU {row.sku} is missing from Catalog.')
        elif mapping[row.sku] != row.vendor_id:
            issues.append(f'PO: vendor for {row.sku} does not match Catalog.')
    return frames, list(dict.fromkeys(issues))


def financial_basis(po, affected_skus=(), affected_vendors=(), affected_pos=()):
    po = normalize(po)
    totals, exposed = {}, {}
    measured = 0
    reasons = set()
    quantity = 'total_quantity' if 'total_quantity' in po else 'quantity'
    for row in po.to_dict('records'):
        currency = str(row.get('currency', '')).strip().upper()
        try:
            cost, qty = Decimal(str(row.get('cost', ''))), Decimal(str(row.get(quantity, '')))
            if not cost.is_finite() or not qty.is_finite() or cost <= 0 or qty <= 0:
                raise InvalidOperation
            if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
                reasons.add('Missing or invalid currency')
                continue
            value = (cost * qty).quantize(Decimal('0.01'))
            if value > Decimal('1000000000000'):
                reasons.add('Commercial value exceeds the supported review limit')
                continue
        except (InvalidOperation, ValueError):
            reasons.add('Missing, nonfinite or nonpositive cost / quantity')
            continue
        measured += 1
        totals[currency] = totals.get(currency, Decimal(0)) + value
        impacted = (str(row.get('sku', '')).strip().upper() in affected_skus or
                    str(row.get('vendor_id', '')).strip().upper() in affected_vendors or
                    str(row.get('po_id', '')).strip().upper() in affected_pos)
        if impacted:
            exposed[currency] = exposed.get(currency, Decimal(0)) + value
    return {'basis': 'PO cost × quantity; each PO line counted once; no FX conversion',
            'total_lines': len(po), 'measured_lines': measured,
            'coverage_pct': round(100 * measured / len(po), 2) if len(po) else 0,
            'commitment_by_currency': {k: str(v) for k, v in sorted(totals.items())},
            'affected_commitment_by_currency': {k: str(exposed.get(k, Decimal(0))) for k in sorted(totals)},
            'limitations': sorted(reasons)}


def cycle_report(frames, payloads):
    frames, issues = reconcile(frames)
    populations = []
    affected = {}
    actions = []
    specs = [('vendor', 'vendor_intelligence', 'vendor_health', 'vendor_id', ('total_vendors', 'ready_vendors', 'warning_vendors', 'critical_vendors'), 'Vendor Operations'),
             ('catalog', 'catalog', 'sku_health', 'sku', ('total_skus', 'clean_skus', 'warning_skus', 'critical_skus'), 'Catalog Operations'),
             ('po', 'po_intelligence', 'po_health', 'po_id', ('total_lines', 'ready_lines', 'warning_lines', 'blocked_lines'), 'Buying Operations')]
    for kind, section, health, identifier, fields, owner in specs:
        summary = payloads[kind][section]
        counts = [summary.get(field) for field in fields]
        if any(type(n) is not int or n < 0 for n in counts) or sum(counts[1:]) != counts[0] or counts[0] != len(frames[kind]):
            raise ValueError(f'{kind}: source counts do not reconcile to input rows.')
        rows = payloads[kind][health]
        if len(rows) != counts[0]:
            raise ValueError(f'{kind}: row evidence does not reconcile to the source summary.')
        actual = [sum(row.get('severity') == severity for row in rows) for severity in ('NONE', 'WARNING', 'CRITICAL')]
        if actual != counts[1:]:
            raise ValueError(f'{kind}: severity counts differ from the source summary.')
        populations.append(dict(Source=kind.title(), Total=counts[0], Clear=counts[1], Warning=counts[2], Blocked=counts[3]))
        affected[kind] = {str(row[identifier]).strip().upper() for row in rows if row.get('severity') != 'NONE'}
        for row in rows:
            if row.get('severity') == 'NONE':
                continue
            actions.append({'Source': kind.title(), 'Identifier': row[identifier], 'Severity': row['severity'],
                            'Owner': owner, 'Due': 'Before release' if row['severity'] == 'CRITICAL' else 'Before approval',
                            'Evidence required': ', '.join(row.get('issues') or row.get('affected_fields') or ['Correct source record']),
                            'Status': 'Open', 'Revalidation': 'Required'})
    finance = financial_basis(frames['po'], affected['catalog'], affected['vendor'], affected['po'])
    cycles = {p.get('business_cycle_id') for p in payloads.values()}
    if len(cycles) != 1 or not all(cycles):
        issues.append('Source evidence does not share one business cycle.')
    return {'version': VERSION, 'populations': populations, 'reconciliation_issues': issues,
            'financial': finance, 'actions': actions,
            'approval_eligible': not issues and finance['coverage_pct'] == 100 and not any(r['Blocked'] for r in populations)}

