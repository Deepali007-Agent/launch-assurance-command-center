"""Compact retail decision views bound exclusively to the selected launch."""
from collections import Counter
import json
from pathlib import Path
import pandas as pd
import altair as alt
import streamlit as st
from orchestration.presentation import detail_table, composition_chart
from orchestration.decision_workflow import compare_runs, history_reports, ranked_actions, money
from orchestration.cycle_history import action_key


def ctx(result):
    return {'Cycle':result['cycle_name'],'Evidence':result['run_id'],'Launch':result.get('launch',{}).get('context',{})}


def render_decision(result,report,run,state,label,reason,runs):
    ops=report['operations']; context=result.get('launch',{}).get('context',{})
    st.subheader((context.get('launch_name') or result['cycle_name'])+' · '+label)
    st.caption('Launch date: '+(context.get('launch_date') or 'Not set')+' · Channel: '+(context.get('channels') or 'Not set')+' · '+context.get('scope','All supplied records'))
    if label=='Hold': st.error(reason)
    elif label=='Approved': st.success(reason)
    else: st.info(reason)
    counts=report.get('scope_counts',{})
    if counts: st.caption('Checked / supplied rows: '+' · '.join(f"{k}: {v['evaluated']:,}/{v['input']:,}" for k,v in counts.items()))
    st.caption('Checked / supplied counts are separate vendor, item and PO-line populations.')
    st.markdown('**What prevents this launch?**')
    groups={}
    for a in ops['actions']:
        key=(a['Source'],a['Missing fields'] or ('Critical source rules' if a['Severity']=='CRITICAL' else 'Source warnings'),a['Severity'])
        g=groups.setdefault(key,{'Findings':0,'lines':set(),'example':a['Evidence required']})
        g['Findings']+=1;g['lines'].update(a['Line IDs'])
    if groups:
        data=[{'Cause':s+' · '+f,'Severity':sev,'Findings':g['Findings'],'Affected PO lines':len(g['lines'])} for (s,f,sev),g in groups.items()]
        chart=pd.DataFrame(data)
        chart['Cause']=chart['Cause'].str.split(' · ').str[0].replace({'Commercial evidence':'Commercial','Po':'PO'})
        chart=chart.groupby(['Cause','Severity'],as_index=False)['Findings'].sum()
        st.altair_chart(composition_chart(chart,'Cause','Findings','Severity',domain=['CRITICAL','WARNING'],colors=['#ef6464','#ffb454'],grouped=True),use_container_width=True)
        st.caption('Labels show count and % of all correction findings; these are not unique PO-line counts.')

    else: st.write('No open source or commercial corrections in this evidence version.')
    with st.expander('Release subsets · eligible, blocked and review'):
        candidates=ops['counts'].get('Clear candidate',0);blocked=ops['counts'].get('Blocked',0);warnings=ops['counts'].get('Needs review',0)
        st.write(f'**{candidates:,} clear candidate lines · {blocked:,} blocked lines · {warnings:,} lines needing review**')
        st.caption('Disjoint PO-line populations based on linked vendor, catalog, channel and commercial findings. “Clear candidate” does not authorize release.')
        st.caption(ops['release_policy'])
        if ops['global_reasons']: st.warning('Launch-wide requirements still apply to every candidate: '+' '.join(ops['global_reasons']))
        with st.expander('Inspect or export the release subsets'):
            subset=st.selectbox('PO-line subset',['All evaluated lines','Clear candidate','Blocked','Needs review'],key='subset_'+result['run_id'])
            rows=[r for r in ops['lines'] if subset=='All evaluated lines' or r['Status']==subset]
            detail_table(rows,title='Selected PO lines',export_key='subset',context=ctx(result),hide_index=True)
            if candidates:
                st.write('To assess a separate release: create a named launch under the same cycle, set its SKU/location scope in launch setup and validate the full three-file bundle. Inspect the resulting PO lines before approval; SKU/location filters may also include other lines for the same SKU.')
    with st.expander('Commercial impact · value and missing inputs'):
        currencies=list(ops['commitment'])
        if currencies:
            currency=st.selectbox('Currency',currencies,key='impact_currency_'+result['run_id'])
            values=[{'Population':'Blocked','Commitment':float(ops['blocked_commitment'].get(currency,0))},
                    {'Population':'Needs review','Commitment':float(ops['review_commitment'].get(currency,0))},
                    {'Population':'Clear candidate','Commitment':float(ops['candidate_commitment'].get(currency,0))}]
            st.caption('Currency: '+currency)
            st.altair_chart(composition_chart(values,'Population','Commitment','Population'),use_container_width=True)
            st.caption('Labels show value and % of measured commitment in the selected currency (cost × quantity). Unknown values are excluded; no currency mixing.')
        else: st.write('**Unknown — no PO commitment can be measured from this evidence.**')
        if ops['unmeasured_lines']: st.warning(f"{ops['unmeasured_lines']:,} PO lines have unknown commitment. Measured amounts are partial and must not be read as total exposure.")
    queue=ranked_actions(state,ops,context.get('launch_date',''))
    st.markdown('**Next action**')
    if queue:
        groups={};evidence={action_key(a):a for a in ops['actions']}
        for r in queue:
            key=(r['Responsible team'],r['Owner'],r['Deadline'],r['Correction'])
            group=groups.setdefault(key,{'row':r,'lines':set(),'count':0})
            group['count']+=1;group['lines'].update(evidence.get(r['Action ID'],{}).get('Line IDs',[]))
        for i,g in enumerate(list(groups.values())[:1],1):
            r=g['row']; linked=[line for line in ops['lines'] if line['Line'] in g['lines']]
            value=' · '.join(c+' '+v for c,v in money(linked).items()) or ('Unknown' if linked else 'Launch-wide requirement')
            st.write(f"**{i}. {r['Responsible team']} · {r['Owner']} · due {r['Deadline']}** — {r['Correction']}")
            st.caption(f"{g['count']} corrections · {len(linked)} linked PO lines · {value} · {r['Escalation']}")
        st.caption('Open Actions to assign or view all corrections. Ranked by severity, deadline, then linked PO lines.')
    else: st.write('No corrections to assign. Use Review & audit for the current decision and human review.')
    with st.expander('Correction progress · previous versus current'):
        render_changes(result,report,runs)


def render_changes(result,report,runs):
    st.markdown('**Did our corrections help?**')
    chain=history_reports(result,runs)
    if not chain:
        st.caption('First saved version for this launch. Validate corrected files under the same launch to establish a comparison.')
        return
    previous,old=chain[0]
    comparison=compare_runs(report,old,[p for _,p in chain[1:]])
    st.write(' · '.join(f"**{len(comparison[k])} {k}**" for k in ('resolved','new','reopened','remaining')))
    st.caption('Compared with the immediately preceding evidence version of this launch. Changed corrections count as resolved plus new; reopened means absent in the previous version but present earlier.')
    a={r['Line'] for r in old['operations']['lines']};b={r['Line'] for r in report['operations']['lines']}
    if a!=b: st.warning(f'Population changed: {len(b-a)} PO lines added, {len(a-b)} removed. Resolved findings can reflect removed scope, not corrected data.')
    chart=[]
    for label,r in [('Previous',old),('Current',report)]:
        for status in ['Blocked','Needs review','Clear candidate']: chart.append({'Version':label,'Status':status,'PO lines':r['operations']['counts'].get(status,0)})
    st.altair_chart(composition_chart(chart,'Version','PO lines','Status',sort=['Previous','Current'],domain=['Blocked','Needs review','Clear candidate'],colors=['#ef6464','#ffb454','#4cc38a'],grouped=True,within_category=True),use_container_width=True)
    st.caption('Labels show count and % of evaluated PO lines within each version; the categories are disjoint.')
    detail_table(comparison['rows'],title='Correction changes',export_key='changes',context={**ctx(result),'Previous evidence':previous['run_id']},hide_index=True)


def render_agent_evidence(result,report):
    st.subheader('How each agent supports this decision',help='Each agent checks one dependency; orchestration joins the findings into the next business action.')
    st.caption('The retail problem: buying requests stall when vendor approvals, item setup and PO data are handled in separate queues.')
    tabs=st.tabs(['Vendor readiness','Item / Catalog readiness','PO request readiness'])
    definitions={
      'vendor':('Can we buy from this vendor?','Checks vendor data and compliance. Finance approval must also be explicitly supplied before executable PO creation.','Vendor Operations / Finance'),
      'catalog':('Is the item ready for an order?','Checks product attributes and identifiers. A valid catalog file alone does not prove that item setup is active.','Catalog Operations'),
      'po':('Can this purchase request proceed?','Checks order terms and joins vendor, category, gender, active item setup and Finance evidence.','Buying Operations')}
    sections={'vendor':'vendor_health','catalog':'sku_health','po':'po_health'}
    for kind,tab in zip(('vendor','catalog','po'),tabs):
        with tab:
            question,definition,team=definitions[kind]
            st.subheader(question,help=definition)
            st.write(definition)
            payload=json.loads((Path(result['folder'])/(kind+'.json')).read_text(encoding='utf-8'))
            population=next(p for p in report['populations'] if p['Source'].lower()==kind)
            st.write(f"{population['Total']} checked · {population['Clear']} clear · {population['Warning']} review · {population['Blocked']} blocked")
            st.caption('Counts describe this agent’s source records; downstream prerequisites and launch approval are evaluated separately.')
            st.write('Next team: '+team)
            actions=[a for a in report['actions'] if a['Source'].lower()==kind or (kind=='po' and a['Source']=='PO prerequisites')]
            if actions:
                st.write('Next step: '+'; '.join(list(dict.fromkeys(a['Evidence required'] for a in actions))[:3]))
            else:st.write('Next step: source checks are clear; inspect the remaining linked prerequisites before review.')
            detail_table(payload[sections[kind]],title='Source findings',export_key='agent_'+kind,context=ctx(result),hide_index=True)
            with st.expander('Evidence provenance'):
                st.caption('Execution: '+payload['orchestration_run_id'])
                st.json(result.get('standalone_evidence',{}).get(kind,{'origin':'Workspace invoked the installed standalone engine on the selected files.'}))
