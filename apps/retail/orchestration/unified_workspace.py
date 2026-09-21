"""Single upload-to-review journey using the installed standalone engines."""
from datetime import date
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pandas as pd
import streamlit as st
from orchestration.presentation import explained_metric, detail_table
import altair as alt

from orchestration.intake import (validate_publication, catalog_publication_to_assessment,
    onboarding_publications_to_assessment, po_publication_to_assessment)
from orchestration.action_queue import queue_rows
from orchestration.decision_workflow import enrich_report, load_report, decision_state, ranked_actions, VERSION as WORKFLOW_VERSION
from orchestration.decision_views import render_decision, render_agent_evidence
from orchestration.launch_scope import scoped_frames, scope_identity, PolicyStore
from orchestration.financial_scenarios import financial_scenarios
from orchestration.local_safety import local_lock, create_backup, verify_backup, restore_copy
from orchestration.contracts import AgentAssessment
from orchestration.launch_controls import context as launch_context, evaluate as evaluate_launch, fingerprint as launch_fingerprint, prioritized, PROBLEMS
from orchestration.workspace_questions import render_questions
from orchestration.reconciliation import cycle_report, VERSION
from orchestration.cycle_history import saved_cycles, saved_inputs, ActionRegistry, action_key

ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = ROOT
APPS = ROOT.parent
RUNS = ROOT / 'data' / 'workspace_runs'
KINDS = {'vendor': 'Vendor onboarding', 'catalog': 'Item onboarding', 'po': 'Purchase orders'}


def read_frame(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.suffix.lower() == '.csv' else pd.read_excel(path, dtype=str, keep_default_na=False)


def check_links(files):
    from orchestration.reconciliation import reconcile
    _, issues = reconcile({key: read_frame(path) for key, path in files.items()})
    return issues


def execute(files, folder, progress=lambda text: None, business_cycle_id=None):
    issues = check_links(files)
    if issues:
        raise ValueError('\n'.join(issues[:30]) + (f'\n…and {len(issues)-30} more.' if len(issues) > 30 else ''))
    projects = {'vendor': APPS / 'onboarding', 'catalog': APPS / 'catalog', 'po': APPS / 'po'}
    payloads = {}
    env = dict(os.environ, RETAIL_BUSINESS_CYCLE_ID=business_cycle_id or folder.name)
    for key in KINDS:
        progress(f'Checking {KINDS[key]}…')
        python = sys.executable
        output = folder / f'{key}.json'
        result = subprocess.run([str(python), str(CODE_ROOT / 'orchestration' / 'unified_agent_runner.py'), key, str(files[key]), str(output)],
                                cwd=projects[key], env=env, capture_output=True, text=True, timeout=240,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            (folder / f'{key}-error.txt').write_text(result.stderr, encoding='utf-8')
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'The agent did not return a result.'
            raise ValueError(f'{KINDS[key]}: {detail}')
        payloads[key] = json.loads(output.read_text(encoding='utf-8'))
        validate_publication(payloads[key])
        progress(f'{KINDS[key]} complete — evidence validated.')
    return payloads


def stable_text(label, value='', **kwargs):
    st.session_state.setdefault(kwargs['key'], value)
    return st.text_input(label, **kwargs)

def stable_checkbox(label, value=False, **kwargs):
    st.session_state.setdefault(kwargs['key'], value)
    return st.checkbox(label, **kwargs)

def stable_multiselect(label, options, default=None, **kwargs):
    st.session_state.setdefault(kwargs['key'], default or [])
    return st.multiselect(label, options, **kwargs)

def stable_number(label, value=0.0, **kwargs):
    st.session_state.setdefault(kwargs['key'], value)
    return st.number_input(label, **kwargs)



def validate_cycle(uploads, cycle_name, cycle_id, current_launch, previous_result, store, ledger, progress=lambda message: None, standalone_payloads=None):
    """One transactionally guarded validation path shared by UI and acceptance tests."""
    if standalone_payloads is not None and set(standalone_payloads)!={'vendor','catalog','po'}:
        raise ValueError('Choose all three standalone publications or turn off standalone reconciliation.')
    launch_name=current_launch.get('launch_name','')
    launch_date=current_launch.get('launch_date','')
    sku_scope=current_launch.get('sku_scope','')
    location_scope=current_launch.get('location_scope','')
    scenario_pct=current_launch.get('sell_through_pct')
    review_scope_id=scope_identity(cycle_id,launch_name)
    folder=RUNS/('WORKSPACE-'+uuid4().hex[:16].upper())
    folder.mkdir(parents=True)
    files={}
    for key,upload in uploads.items():
        files[key]=folder/(key+Path(upload.name).suffix.lower())
        files[key].write_bytes(upload.getvalue())
    try:
        with local_lock(ROOT/'data/maintenance.lock',timeout=1):
            latest = saved_cycles(RUNS).get(review_scope_id)
            if latest and (not previous_result or previous_result.get('review_scope_id', previous_result['business_cycle_id']) != review_scope_id or latest['run_id'] != previous_result['run_id']):
                raise ValueError('This launch already exists or changed in another session. Open its saved version before revalidating.')
            evaluated_frames = scoped_frames({key:read_frame(path) for key,path in files.items()},sku_scope,location_scope)
            scoped_dir=folder/'evaluated_inputs';scoped_dir.mkdir()
            evaluated_files={}
            for key,frame in evaluated_frames.items():
                evaluated_files[key]=scoped_dir/(key+'.csv');frame.to_csv(evaluated_files[key],index=False)
            payloads = execute(evaluated_files, folder, progress, review_scope_id)
            standalone_refs={}
            if standalone_payloads:
                from orchestration.standalone_bridge import reconcile_standalone
                standalone_refs=reconcile_standalone(standalone_payloads,payloads)
                (folder/'standalone_inputs.json').write_text(json.dumps(standalone_payloads),encoding='utf-8')
            progress('Reconciling Vendor → Item → PO links and commercial coverage…')
            report = cycle_report(evaluated_frames, payloads)
            launch = evaluate_launch(current_launch, evaluated_frames, report)
            report['actions'] = prioritized(report['actions'] + launch['actions'], launch_date)
            report['reconciliation_issues'] += launch['blockers']
            affected_skus={str(a['Identifier']).strip().upper() for a in report['actions'] if a['Source'] in {'Catalog','Launch requirements'}}
            affected_vendors={str(a['Identifier']).strip().upper() for a in report['actions'] if a['Source']=='Vendor'}
            affected_pos={str(a['Identifier']).strip().upper() for a in report['actions'] if a['Source']=='Po'}
            from orchestration.reconciliation import financial_basis
            report['financial']=financial_basis(evaluated_frames['po'],affected_skus,affected_vendors,affected_pos)
            report['financial_scenarios']=financial_scenarios(evaluated_frames['po'],affected_skus,affected_vendors,affected_pos,scenario_pct)
            report['scope_counts']={key:{'input':len(read_frame(files[key])),'evaluated':len(frame)} for key,frame in evaluated_frames.items()}
            report=enrich_report(evaluated_frames,payloads,report,current_launch)
            report['reconciliation_issues']=list(dict.fromkeys(report['reconciliation_issues']+report['operations']['global_reasons']))
            (folder / 'reconciliation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            payloads['po']['cycle_evidence'] = {'financial': report['financial'], 'reconciliation_issues': report['reconciliation_issues'], 'version': VERSION}
            publications = {}
            for key, payload in payloads.items():
                pub_id = f'PUB-{folder.name}-{key}'
                store.receive(pub_id, payload)
                publications[key] = store.get(pub_id)
            assessments = [onboarding_publications_to_assessment(publications['vendor'], publications['catalog']),
                           catalog_publication_to_assessment(publications['catalog']), po_publication_to_assessment(publications['po'])]
            assessments[-1].release_blockers = report['reconciliation_issues'] + (["Commercial evidence is incomplete; supply cost, quantity and currency for every PO line."] if report['financial']['coverage_pct'] < 100 else [])
            assessments[-1].source_run_id += '-LAUNCH-' + launch['context_hash'][:16]
            run = ledger.synchronize({a.agent_id: a for a in assessments})
            result = {'review_scope_id':review_scope_id,'launch': launch, 'business_cycle_id': cycle_id, 'previous_run_id': previous_result['run_id'] if previous_result and previous_result.get('review_scope_id', previous_result['business_cycle_id']) == review_scope_id else None, 'cycle_name': cycle_name.strip(), 'rule_version': VERSION, 'workflow_version':WORKFLOW_VERSION, 'run_id': run['orchestration_run_id'], 'folder': str(folder),
                      'files': {key: upload.name for key, upload in uploads.items()},
                      'standalone_evidence':standalone_refs, 'hashes': {key: hashlib.sha256(upload.getvalue()).hexdigest() for key, upload in uploads.items()}}
            (folder / 'result.json').write_text(json.dumps(result), encoding='utf-8')
            ActionRegistry(ROOT / 'data' / 'cycle_actions', review_scope_id).observe(report['actions'], result['run_id'])
        return result
    except Exception as error:
        (folder/'failure.txt').write_text(str(error),encoding='utf-8')
        raise


def render_workspace(store, ledger):
    st.caption('Upload → Validate with three engines → Resolve issues → Human review')
    history = saved_cycles(RUNS)
    if st.session_state.get('resume_after_validation'):
        st.session_state['saved_cycle_choice']=st.session_state.pop('resume_after_validation')
    if 'saved_cycle_choice' not in st.session_state and history:
        st.session_state['saved_cycle_choice'] = next(iter(history))
    chosen = st.selectbox('Open a saved cycle', ['New cycle'] + list(history),
                          format_func=lambda key: key if key == 'New cycle' else f"{history[key].get('cycle_name', key)} · {history[key].get('launch', {}).get('context', {}).get('launch_name', 'Default launch')} · {key}",
                          key='saved_cycle_choice')
    if chosen != st.session_state.get('loaded_cycle_choice'):
        st.session_state.pop('validation_failure',None)
        previous_choice = st.session_state.get('loaded_cycle_choice')
        st.session_state['loaded_cycle_choice'] = chosen
        for prefix in ['launch_name_','sku_scope_','location_scope_','launch_date_','channels_','locations_','fields_','required_','scenario_','sellthrough_','policy_']:
            st.session_state.pop(prefix+chosen, None)
        if chosen != 'New cycle':
            selected = history[chosen]
            st.session_state['workspace_result'] = selected
            st.session_state['business_cycle_name'] = selected.get('cycle_name', chosen)
            st.session_state.setdefault('cycle_ids', {})[selected.get('cycle_name', chosen)] = selected['business_cycle_id']
        elif previous_choice is not None:
            st.session_state.pop('workspace_result', None)
            st.session_state['business_cycle_name'] = ''
    with st.expander('Upload or replace files', expanded=not bool(st.session_state.get('workspace_result'))):
        restored = {}
        if st.session_state.get('workspace_result'):
            try:
                restored = saved_inputs(st.session_state['workspace_result'], RUNS)
                st.caption('Saved inputs are verified against their evidence hashes. Upload a replacement or deselect a saved input to change the cycle.')
            except (OSError, ValueError, KeyError) as error:
                st.error(str(error))
        uploads = {}
        onboarding_upload, catalog_upload, po_upload = st.tabs(['Onboarding Intelligence', 'Catalog Intelligence', 'PO / Buying Intelligence'])

        def upload_source(key):
            label = KINDS[key]
            replacement = st.file_uploader(label, type=['xlsx', 'csv'], key=f'workspace_{chosen}_{key}')
            use_saved = key in restored and stable_checkbox(f'Use saved {label} file', value=True, key=f'use_saved_{chosen}_{key}')
            uploads[key] = replacement or (restored[key] if use_saved else None)
            if use_saved and not replacement:
                st.caption('Saved input: ' + restored[key].name)

        with onboarding_upload:
            vendor_column, item_column = st.columns(2)
            with vendor_column:
                upload_source('vendor')
            with item_column:
                upload_source('catalog')
            st.caption('Upload vendor and item files for the same business cycle. The item file also feeds Catalog Intelligence.')
        with catalog_upload:
            st.caption('Catalog quality checks use the Item onboarding file. Add or replace it under Onboarding Intelligence.')
            if uploads.get('catalog'):
                st.caption('Linked item file: ' + uploads['catalog'].name)
            else:
                st.info('No item file selected yet.')
        with po_upload:
            upload_source('po')
    standalone_payloads=None
    with st.expander('Use results published by standalone agents'):
        st.caption('Optional: upload the same original files above, then select three published results from one business cycle. We rerun the installed rules to verify their findings before joining them; an unrelated latest result is never selected automatically.')
        use_standalone=st.checkbox('Reconcile selected standalone results',key='use_standalone')
        if use_standalone:
            standalone_payloads={}
            publications=store.list_publications()
            for kind in KINDS:
                eligible={r['publication_id']:r for r in publications if r['payload']['schema']==f'retail-intelligence.{kind}.v1'}
                chosen_pub=st.selectbox(kind.title()+' published result',['Upload JSON']+list(eligible),key='published_'+kind)
                if chosen_pub!='Upload JSON':standalone_payloads[kind]=eligible[chosen_pub]['payload']
                else:
                    source=st.file_uploader(kind.title()+' published JSON',type=['json'],key='publication_json_'+kind)
                    if source:
                        try:standalone_payloads[kind]=json.loads(source.getvalue())
                        except (ValueError,UnicodeDecodeError):st.error('Invalid '+kind+' JSON package.')
            st.caption('In each standalone workbench: validate the file, set the same business-cycle ID and publish to the local intake or export its publication JSON. Evidence must be less than 24 hours old. Original files remain required because publications lack full input hashes.')
    cycle_name = stable_text('Business cycle name', placeholder='e.g. Autumn launch · week 38', key='business_cycle_name')
    setup_controls = st.container()
    run_controls = st.container()
    overview_view, actions_view, evidence_view, review_view = st.tabs(['Launch decision', 'Actions', 'Evidence', 'Review & audit'])
    with actions_view:
        from orchestration.request_desk import render_request_desk
        request_cycle=st.session_state.setdefault('cycle_ids',{}).setdefault(cycle_name.strip(),'CYCLE-'+uuid4().hex[:16].upper()) if cycle_name.strip() else ''
        render_request_desk(ROOT/'data/buying_requests',request_cycle)
    with review_view:
        render_local_maintenance()
    with evidence_view:
        stored_launch = st.session_state.get('workspace_result', {}).get('launch', {}).get('context', {})
        with setup_controls, st.expander('Launch setup · name, date, channel & scope', expanded=not bool(st.session_state.get('workspace_result'))):
            st.caption('Keep the cycle name and change the launch name to create a separately reviewed launch from the same inputs. Blank filters include all records. Policies are maintained locally by your team.')
            launch_name = stable_text('Launch name', value=stored_launch.get('launch_name', ''), placeholder='e.g. Web phase 1', key='launch_name_'+chosen)
            sku_scope = stable_text('SKU scope', value=stored_launch.get('sku_scope', ''), placeholder='Comma-separated SKU IDs; blank = all', key='sku_scope_'+chosen)
            location_scope = stable_text('PO location scope', value=stored_launch.get('location_scope', ''), placeholder='Comma-separated location IDs; blank = all', key='location_scope_'+chosen)
            launch_date = stable_text('Planned launch date', value=stored_launch.get('launch_date', ''), placeholder='YYYY-MM-DD', key='launch_date_' + chosen)
            channels = stable_text('Launch channels', value=stored_launch.get('channels', ''), key='channels_' + chosen)
            locations = stable_text('Launch locations', value=stored_launch.get('locations', ''), key='locations_' + chosen)
            fields = stable_text('Mandatory catalog fields for these channels', value=', '.join(stored_launch.get('manual_catalog_fields', stored_launch.get('required_catalog_fields', []))), placeholder='e.g. size, material, image_url', key='fields_' + chosen)
            policies = PolicyStore(ROOT/'data/channel_policies').list()
            policy_id = st.selectbox('Channel requirement version', ['Manual requirements']+list(policies), index=(['Manual requirements']+list(policies)).index(stored_launch.get('policy_id')) if stored_launch.get('policy_id') in policies else 0, format_func=lambda k: k if k=='Manual requirements' else policies[k]['name']+' · '+policies[k]['version'], key='policy_'+chosen)
            scenario_enabled=stable_checkbox('Include an explicit sell-through scenario', value=stored_launch.get('sell_through_pct') is not None, key='scenario_'+chosen)
            scenario_pct=stable_number('Assumed sell-through (%)',min_value=0.0,max_value=100.0,value=float(stored_launch.get('sell_through_pct',100)),key='sellthrough_'+chosen) if scenario_enabled else None
            required = stable_multiselect('Additional controls required before approval', [p[0] for p in PROBLEMS if p[-1]=='planned'], default=stored_launch.get('required_problems', []), format_func=lambda n: next(p[1] for p in PROBLEMS if p[0]==n), key='required_' + chosen)
            st.caption('PO prerequisites: matching vendor, category and explicit gender; active catalog setup; Finance approval; no critical source defects. Missing evidence blocks executable PO creation.')
        try:
            current_launch = launch_context(launch_date, channels, locations, fields, required)
            current_launch['po_dependency_policy']='vendor-category-gender-1'
            if launch_name.strip() or sku_scope.strip() or location_scope.strip() or policy_id != 'Manual requirements' or scenario_enabled:
                current_launch.update(launch_name=launch_name.strip(),sku_scope=sku_scope.strip(),location_scope=location_scope.strip(),manual_catalog_fields=current_launch['required_catalog_fields'])
                current_launch['scope']='Explicit SKU/location selection' if sku_scope.strip() or location_scope.strip() else 'All records in the three supplied files'
                if policy_id != 'Manual requirements':
                    current_launch.update(policy_id=policy_id,policy=policies[policy_id])
                    current_launch['required_catalog_fields']=sorted(set(current_launch['required_catalog_fields'])|set(policies[policy_id]['fields']))
                if scenario_enabled: current_launch['sell_through_pct']=scenario_pct
        except ValueError:
            st.error('Enter a valid planned launch date in YYYY-MM-DD format.')
            return
        with review_view:
            render_policy_editor()
        st.caption('All three files must describe the same business cycle.')
        with st.expander('Which file goes where? / Download test files', expanded=False):
            st.write('Vendor onboarding: vendor file. Item onboarding: catalog file from the test pack (the item_onboarding file is an identical copy). Purchase orders: PO file. Keep the first sheet as Data and one header row.')
            st.write('Item onboarding: sku, vendor_id, product_name, category, price; include gtin, brand, description, image_url, colour, size, material, vendor_approved for full checks. Preserve GTIN as text.')
            testpack = ROOT / 'data' / 'retail-certified-cycles.zip'
            if testpack.exists():
                st.download_button('Download certified cycle files', testpack.read_bytes(), testpack.name)
            st.caption('Start with mixed-400 to see warnings and blockers. Use recovery-400 to test correction. Supply currency, cost and quantity on every PO line. Separate reject files test invalid inputs and mismatched links.')
        with run_controls:
            if sku_scope.strip() or location_scope.strip():
                st.warning(f'Subset selected: SKUs {sku_scope or "all"}; PO locations {location_scope or "all"}. Only matching records will be checked. Change filters in Launch setup above.')
            else:
                st.caption('Scope: all records in the three supplied files. No SKU or location filter.')
            missing = [KINDS[key] for key in KINDS if not uploads.get(key)]
            if not cycle_name.strip(): missing.append('business cycle name')
            if missing: st.caption('To start, add: ' + ', '.join(missing) + '.')
            run_requested = st.button('Validate uploaded files', type='primary', disabled=bool(missing))
            st.caption('Checks vendor eligibility, item/catalog quality and PO rules, then reconciles their linked evidence. Approval remains a separate human decision.')
        if run_requested:
            previous_result = st.session_state.pop('workspace_result', None)
            st.session_state.pop('validation_failure',None)
            cycle_ids = st.session_state.setdefault('cycle_ids', {})
            cycle_id = cycle_ids.setdefault(cycle_name.strip(), 'CYCLE-' + uuid4().hex[:16].upper())
            with run_controls, st.status('Running your checks…', expanded=True) as status:
                try:
                    result=validate_cycle(uploads,cycle_name.strip(),cycle_id,current_launch,previous_result,store,ledger,st.write,standalone_payloads=standalone_payloads)
                    st.session_state['workspace_result']=result
                    st.session_state['resume_after_validation']=result['review_scope_id']
                    status.update(label='Checks complete',state='complete',expanded=False)
                    st.rerun()
                except Exception as error:
                    st.session_state['validation_failure']=str(error)
                    if previous_result:
                        st.session_state['workspace_result']=previous_result
                    status.update(label='Validation needs attention',state='error',expanded=False)
                    st.error(str(error))
                    st.info('Correct the files or launch setup, then validate again. This attempt has no approval available.')
    result = st.session_state.get('workspace_result')
    if result and st.session_state.get('validation_failure'):
        overview_view.error('The latest validation failed: '+st.session_state['validation_failure'])
        overview_view.info('No current release decision is available. Saved inputs and launch setup remain available above so you can correct and retry.')
        return
    if not result:
        if st.session_state.get('validation_failure'): overview_view.error('Validation did not complete: '+st.session_state['validation_failure'])
        overview_view.info('Upload your three files, name the cycle and select Validate uploaded files above. Results and graphs will appear here after validation.')
        return
    policy_upgrade=result.get('launch',{}).get('context',{}).get('po_dependency_policy')!='vendor-category-gender-1'
    comparable_launch=dict(current_launch)
    if policy_upgrade: comparable_launch.pop('po_dependency_policy',None)
    if (result.get('launch') and launch_fingerprint(comparable_launch) != result['launch']['context_hash']):
        overview_view.info('Launch scope or requirements changed. Run checks again before reviewing this version. Use Validate uploaded files above to revalidate.')
        return
    if not result.get('launch') and current_launch != launch_context():
        overview_view.info('Run checks to evaluate the new launch requirements. Use Validate uploaded files above to revalidate.')
        return
    if cycle_name.strip() != result.get('cycle_name', cycle_name.strip()) or any(not uploads[key] or hashlib.sha256(uploads[key].getvalue()).hexdigest() != result['hashes'][key] for key in KINDS):
        overview_view.info('Your files have changed. Run checks again to review this version. Use Validate uploaded files above to revalidate.')
        render_questions()
        return
    run = ledger.get(result['run_id'])
    # Recheck freshness whenever the review is shown, including an approval click.
    run = ledger.synchronize({key: AgentAssessment(**dict(value, identifiers=set(value['identifiers']))) for key, value in run['assessments'].items()})
    decision = run['decision_detail']
    report=load_report(result)
    legacy=result.get('workflow_version')!=WORKFLOW_VERSION
    label,reason=decision_state(run,report['operations'],legacy or policy_upgrade)
    if policy_upgrade: reason='Revalidate to evaluate Finance approval, active item setup and Vendor / Category / Gender prerequisites. Saved findings remain available below.'
    registry=ActionRegistry(ROOT/'data/cycle_actions',result.get('review_scope_id',result['business_cycle_id']))
    # Saved legacy evidence is inspectable, but new correction tracking activates on revalidation.
    state=registry.load()
    if legacy:
        state={'actions':{action_key(a):{'evidence':a,'run_id':result['run_id'],'status':'Open','assigned_owner':'','due_date':''} for a in report['actions']},'events':[]}
    with overview_view:
        render_decision(result,report,run,state,label,reason,RUNS)
        from orchestration.retail_guidance import request_decisions
        with st.expander('What can proceed while approvals are pending?'):
            st.caption('Prototype policy: teams may prepare draft item or PO requests in parallel. Executable PO creation waits for Finance approval, active item setup and all critical checks. This app does not create ERP records.')
            detail_table(request_decisions(result,report),title='Vendor / Category / Gender requests',export_key='request_dependencies',context={'Evidence':result['run_id']},hide_index=True)
    with evidence_view:
        render_agent_evidence(result,report)
    with evidence_view, st.expander('Supporting controls and commercial evidence'):
        if result.get('launch'):
            st.subheader('Launch readiness & control coverage')
            st.caption('Launch: ' + (current_launch['launch_date'] or 'Date not specified') + ' · Channels: ' + (current_launch['channels'] or 'Not specified') + ' · Locations: ' + (current_launch['locations'] or 'Not specified'))
            detail_table(pd.DataFrame(result['launch']['coverage']), hide_index=True, title='Control coverage', export_key='unified_workspace_4', context={'Cycle':result['business_cycle_id'],'Evidence':result['run_id'],'Launch':result.get('launch', {})})
            st.caption('Evaluated describes coverage, not a pass. Unsupported capabilities provide no assurance. Release values use PO commitment; optional financial scenarios are separate estimates.')
        else:
            st.info('Revalidate this saved cycle to add launch control coverage.')
        if report:
            detail_table(pd.DataFrame(report['populations']), hide_index=True, use_container_width=True, title='Source populations', export_key='unified_workspace_5', context={'Cycle':result['business_cycle_id'],'Evidence':result['run_id'],'Launch':result.get('launch', {})})
            st.caption('Separate populations: vendors, unique SKUs and PO lines. These are not additive unique business records.')
            finance = report['financial']
            left, right = st.columns(2)
            explained_metric(left, 'Commercial evidence coverage', f"{finance['coverage_pct']:.1f}%")
            explained_metric(right, 'Reconciliation', 'Passed' if not report['reconciliation_issues'] else 'Needs attention')
            st.write('Commercial commitment and affected value')
            st.caption(finance['basis'])
            money_rows = [{'Currency': currency, 'PO commitment': value, 'Affected commitment': finance['affected_commitment_by_currency'][currency]}
                          for currency, value in finance['commitment_by_currency'].items()]
            if money_rows:
                detail_table(pd.DataFrame(money_rows), hide_index=True, title='Commercial values', export_key='unified_workspace_6', context={'Cycle':result['business_cycle_id'],'Evidence':result['run_id'],'Launch':result.get('launch', {})})
            else:
                st.warning('Not measurable yet. Supply explicit currency, positive cost and quantity.')
            if report.get('scope_counts'):
                st.caption('Evaluated / supplied: ' + ' · '.join(f"{k}: {v['evaluated']} / {v['input']}" for k,v in report['scope_counts'].items()))
            if report.get('financial_scenarios'):
                with st.expander('Margin & revenue scenarios', expanded=False):
                    scenario=report['financial_scenarios']
                    st.caption(f"Retail/margin input coverage: {scenario['coverage_pct']}% · Sell-through assumption: {scenario['sell_through_pct'] if scenario['sell_through_pct'] is not None else 'Not supplied'}")
                    if scenario['rows']: detail_table(pd.DataFrame(scenario['rows']),hide_index=True, title='Financial scenarios', export_key='unified_workspace_7', context={'Cycle':result['business_cycle_id'],'Evidence':result['run_id'],'Launch':result.get('launch', {})})
                    else: st.info('Not measurable: supply positive reg_retail, cost, quantity and currency.')
                    st.caption(scenario['basis']);st.caption(scenario['limitations'])
            for limitation in finance['limitations']:
                st.caption(limitation)
    if report:
        with actions_view:
            # Launch setup corrections already appear in the actionable queue.
            setup_reasons=set(report.get('operations',{}).get('global_reasons',[]))
            other_issues=[issue for issue in dict.fromkeys(report['reconciliation_issues']) if issue not in setup_reasons]
            if other_issues:
                st.warning(' '.join(other_issues))
            if legacy:
                st.warning('Validate this saved launch with the updated controls to activate assignment and approval. The decision page shows the corrections derived from its saved files.')
                detail_table(report['actions'],title='Corrections to activate',export_key='legacy_actions',hide_index=True)
            else:
                render_action_assignments(result, report)
            st.download_button('Download source action queue', pd.DataFrame(report['actions']).to_csv(index=False), 'cycle-actions.csv')
    with evidence_view:
        render_questions(run)
    with review_view:
        st.caption(f"Cycle {result.get('business_cycle_id', 'Legacy')} · Evidence {result['run_id']}")
        st.subheader(label)
        st.write(reason)
        detail_table(pd.DataFrame(run['events']), hide_index=True, title='Review history', export_key='unified_workspace_1', context={'Cycle':result['business_cycle_id'],'Evidence':result['run_id'],'Launch':result.get('launch', {})})
        with st.expander('Details & downloads', expanded=False):
            st.download_button('Download review evidence', json.dumps(run, indent=2, default=str), 'retail-review.json')
        st.caption('Approval records the review decision; it does not send orders to an ERP or approve vendors in the source systems.')
        st.caption('Approval is unavailable while corrections, missing launch setup or stale evidence prevent review.')
        with st.expander('Record your decision', expanded=False):
            actor = stable_text('Your name', key='workspace_approver')
            reason = stable_text('Decision note', key='workspace_reason')
            approved = stable_checkbox('I have reviewed the findings', key='workspace_reviewed_' + result['run_id'])
            if st.button('Approve review', disabled=legacy or policy_upgrade or report['operations']['critical_findings'] > 0 or run['status'] != 'AWAITING_HUMAN_APPROVAL' or decision['status'] == 'BLOCKED' or not actor.strip() or not reason.strip() or not approved):
                try:
                    ledger.decide_human_gate(result['run_id'], True, actor, reason, expected_gate=run['human_gate_status'])
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

            if st.button('Hold review', disabled=legacy or run['status'] not in {'AWAITING_HUMAN_APPROVAL', 'COMPLETED', 'REJECTED'} or not actor.strip() or not reason.strip()):
                try:
                    ledger.decide_human_gate(result['run_id'], False, actor, reason, expected_gate=run['human_gate_status'])
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))


def render_action_assignments(result, report):
    registry = ActionRegistry(ROOT / 'data' / 'cycle_actions', result.get('review_scope_id', result['business_cycle_id']))
    if not registry.path.exists():
        registry.observe(report['actions'], result['run_id'])
    state = registry.load()
    launch_date = result.get('launch', {}).get('context', {}).get('launch_date', '')
    rows = ranked_actions(state, report['operations'], launch_date)
    if launch_date:
        days = (date.fromisoformat(launch_date) - date.today()).days
        st.caption(f'Launch target {launch_date} · {abs(days)} days ' + ('overdue' if days < 0 else 'remaining'))
    if not rows:
        st.info('No open source corrections. Any control-coverage blockers are shown above.')
    else:
        frame = pd.DataFrame(rows)
        chart_data = frame.groupby(['Timing', 'Severity']).size().reset_index(name='Actions')
        from orchestration.presentation import composition_chart
        st.altair_chart(composition_chart(chart_data,'Timing','Actions','Severity',sort=['Overdue','Due today','Next 7 days','Later','No date'],domain=['CRITICAL','BLOCKED','WARNING'],colors=['#ef6464','#d94c4c','#ffb454'],grouped=True),use_container_width=True)
        st.caption('Labels show count and % of all open actions, grouped by deadline and severity. An affected PO line can have multiple actions.')
        left, right = st.columns(2)
        timing = left.selectbox('Deadline filter', ['All deadlines','Overdue','Due today','Next 7 days','Later','No date'], key='timing_'+result['business_cycle_id'])
        ownership = right.selectbox('Owner filter', ['All owners','Unassigned'] + sorted(set(frame['Owner']) - {'Unassigned'}), key='owner_'+result['business_cycle_id'])
        visible = frame
        if timing != 'All deadlines': visible=visible[visible.Timing==timing]
        if ownership != 'All owners': visible=visible[visible.Owner==ownership]
        team_filter=st.selectbox('Accountable team',['All teams']+sorted(set(frame['Responsible team'])),key='team_filter_'+result['run_id'],help='Filters recommendations, the detailed queue and batch assignment by current receiving team.')
        if team_filter!='All teams':visible=visible[visible['Responsible team']==team_filter]
        source_filter=st.selectbox('Correction source',['All sources']+sorted(set(frame['Source'])),key='source_filter_'+result['run_id'])
        if source_filter!='All sources': visible=visible[visible.Source==source_filter]
        impact_currencies=sorted({currency for action in report['actions'] for currency in action.get('Commitment by currency',{})})
        order=st.selectbox('Rank recommendations by',['Severity, deadline, affected lines']+['Severity, commitment in '+c for c in impact_currencies],key='queue_order_'+result['run_id'])
        if order.startswith('Severity, commitment in '):
            currency=order.rsplit(' ',1)[-1]
            by_id={action_key(a):a for a in report['actions']}
            visible=visible.assign(_critical=visible.Severity.isin(['CRITICAL','BLOCKED']),_value=visible['Action ID'].map(lambda k:float(by_id[k].get('Commitment by currency',{}).get(currency,0))))
            visible=visible.sort_values(['_critical','_value'],ascending=[False,False]).drop(columns=['_critical','_value'])
            st.caption('Values in other currencies and unmeasured values are not comparable; inspect their flags before prioritizing.')
        from orchestration.retail_guidance import recommended_actions
        st.subheader('Top Recommended Actions',help='Ranked corrections grouped by issue and ownership, with distinct affected SKUs and PO lines.')
        recommendations=recommended_actions(visible.to_dict('records'),report['operations'])
        from orchestration.retail_guidance import recommendations_by_team
        team_groups=recommendations_by_team(recommendations)
        shown=list(team_groups) if team_filter=='All teams' else [team_filter]
        team_tabs=st.tabs([team+' · '+str(len(team_groups[team])) for team in shown])
        for team,team_tab in zip(shown,team_tabs):
            with team_tab:
                team_rows=team_groups[team]
                if not team_rows:
                    st.caption('No open corrections for this team under the selected filters.')
                    continue
                st.caption(f"{len(team_rows)} recommended groups · {sum(r['Corrections'] for r in team_rows)} correction findings. Showing the top 10 groups for this team.")
                columns=['No.','Type','Category','SKUs impacted','Recommended action','Owner','Due']
                st.dataframe(pd.DataFrame(team_rows[:10])[columns],hide_index=True,use_container_width=True,
                    column_config={name:st.column_config.Column(name,help=definition,width={'No.':45,'Type':90,'Category':125,'SKUs impacted':100,'Recommended action':300,'Owner':120,'Due':100}.get(name)) for name,definition in {
                        'No.':'Priority rank within this team under the selected ordering.', 'Type':'Critical prevents proceeding; Needs review requires a reviewer.',
                        'Category':'The missing field or validation issue to correct.', 'SKUs impacted':'Distinct SKUs linked to this issue group; groups can overlap.',
                        'Recommended action':'The correction needed before revalidation.',
                        'Owner':'The named person assigned to act.', 'Due':'The correction deadline or launch target.'}.items()})
        st.caption('Team tabs organize recommendations. Use Accountable team above to scope the detailed queue and assignments. Reassigned corrections move to their receiving team.')
        detail_table(visible.drop(columns=['Action ID','Days remaining']), hide_index=True, height=280, title='Action queue', export_key='unified_workspace_2', context={'Cycle':result['business_cycle_id'],'Evidence':result['run_id'],'Launch':result.get('launch', {})})
        st.caption('Critical issues first, then deadline. Unassigned deadlines use the launch target. Waiting on counts unresolved prerequisites; assignment does not clear release blockers.')
        with st.expander('Assign all filtered corrections together'):
            st.write(f'{len(visible)} active corrections match these filters.')
            with st.form('batch_assign_'+result['run_id']):
                batch_team=st.selectbox('Batch receiving team',['Keep current teams','Vendor Operations','Catalog Operations','Buying Operations','Finance','Launch Operations'])
                batch_owner=st.text_input('Batch owner')
                batch_due=st.text_input('Batch deadline',placeholder='YYYY-MM-DD')
                batch_escalation=st.text_input('Batch escalation contact')
                batch_actor=st.text_input('Batch recorded by')
                batch_reason=st.text_input('Batch assignment reason')
                batch_save=st.form_submit_button('Assign filtered corrections',disabled=visible.empty)
            if batch_save:
                try:
                    registry.assign_group(visible['Action ID'].tolist(),batch_owner,batch_due,batch_actor,batch_reason,batch_escalation,expected_revision=state.get('revision',len(state['events'])),assigned_team=None if batch_team=='Keep current teams' else batch_team)
                    st.rerun()
                except ValueError as error: st.error(str(error))
        with st.expander('Assign or return to a team', expanded=False):
            available = visible['Action ID'].tolist()
            if available:
                label=lambda key: state['actions'][key]['evidence']['Source'] + ' · ' + state['actions'][key]['evidence']['Identifier']
                action_id=st.selectbox('Action', available, format_func=label, key='edit_action_'+result['business_cycle_id'])
                current=state['actions'][action_id]
                st.write(current['evidence'].get('Evidence required',''))
                with st.form('assignment_'+result['business_cycle_id']+action_id):
                    a,b=st.columns(2)
                    team=st.selectbox('Receiving team',['Vendor Operations','Catalog Operations','Buying Operations','Finance','Launch Operations'],index=['Vendor Operations','Catalog Operations','Buying Operations','Finance','Launch Operations'].index(current.get('assigned_team') or current['evidence'].get('Owner','Launch Operations')) if (current.get('assigned_team') or current['evidence'].get('Owner','Launch Operations')) in ['Vendor Operations','Catalog Operations','Buying Operations','Finance','Launch Operations'] else 4,help='The team accountable for the next correction; reassignment is recorded in history.')
                    owner=a.text_input('Named action owner',value=current['assigned_owner'])
                    deadline=b.text_input('Calendar deadline',value=current['due_date'] or launch_date,placeholder='YYYY-MM-DD')
                    options=['Open','In progress','Waiting for approval','Returned to team','Ready to revalidate']
                    status=st.selectbox('Work status',options,index=options.index(current['status']))
                    prerequisites=st.multiselect('Prerequisite actions', [k for k in state['actions'] if k!=action_id], default=current.get('dependencies',[]),format_func=label)
                    escalation_owner=st.text_input('Escalation contact',value=current.get('escalation_owner',''))
                    escalation_note=st.text_input('Escalation note / next step',value=current.get('escalation_note',''))
                    st.caption('Escalation is recorded locally; no email or message is sent.')
                    actor=st.text_input('Assignment recorded by')
                    reason=st.text_input('Assignment reason')
                    save=st.form_submit_button('Save action assignment')
                if save:
                    try:
                        registry.assign(action_id,owner,deadline,status,actor,reason,prerequisites,expected_revision=state.get('revision',len(state['events'])),escalation_owner=escalation_owner,escalation_note=escalation_note,assigned_team=team)
                        st.rerun()
                    except ValueError as error: st.error(str(error))
            else: st.caption('No actions match these filters.')
    with st.expander('Action history & export', expanded=False):
        detail_table(pd.DataFrame(state['events']),hide_index=True,height=200, title='Action history', export_key='unified_workspace_3', context={'Cycle':result['business_cycle_id'],'Evidence':result['run_id'],'Launch':result.get('launch', {})})
        st.download_button('Download action audit', json.dumps(state,indent=2),'cycle-action-audit.json')


def render_policy_editor():
    with st.expander('Maintain channel requirement versions', expanded=False):
        st.caption('Local team policies only. Published versions are immutable; select the version above and revalidate to apply it.')
        with st.form('new_policy_version'):
            a,b=st.columns(2)
            name=a.text_input('Policy name');version=b.text_input('Policy version')
            fields=st.text_input('Required catalog columns')
            basis=st.text_input('Policy source or internal rationale')
            actor=st.text_input('Policy author')
            save=st.form_submit_button('Save new policy version')
        if save:
            try:
                with local_lock(ROOT/'data/maintenance.lock'):
                    PolicyStore(ROOT/'data/channel_policies').save(name,version,fields,basis,actor)
                st.rerun()
            except ValueError as error: st.error(str(error))


def render_local_maintenance():
    with st.expander('Local backups & recovery', expanded=False):
        st.caption('Creates a checksummed archive of local platform evidence, policies, actions and SQLite data. Recovery extracts a new copy; it never replaces live data.')
        if st.button('Create verified local backup'):
            try:
                archive=create_backup(ROOT/'data', ROOT/'backups')
                st.success('Verified backup saved: '+str(archive))
            except (ValueError,OSError) as error: st.error(str(error))
        backups=sorted((ROOT/'backups').glob('retail-*.zip'),key=lambda p:p.stat().st_mtime,reverse=True)
        if backups:
            selected=st.selectbox('Saved backup',backups,format_func=lambda p:p.name)
            if st.button('Verify and recover to a new folder'):
                try:
                    target=restore_copy(selected,ROOT/'recovery'/('restored-'+uuid4().hex[:12]))
                    st.success('Verified recovery copy: '+str(target))
                    st.caption('This is an offline recovery copy. The running workspace continues using its current data.')
                except (ValueError,OSError) as error: st.error(str(error))

