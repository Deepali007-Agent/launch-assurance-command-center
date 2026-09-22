"""Compact interactive vertical slice; every change is explicitly a simulation."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import json
import sqlite3
import pandas as pd
import altair as alt
import streamlit as st
from orchestration.presentation import detail_table
from .scenario import make_scenario
from .engine import source_checks,recommend,revalidate,shipment_predictions,fingerprint,VERSION

DB=Path(__file__).resolve().parents[1]/'data/launch_assurance_demo.db'

def load():
    if st.session_state.get('_la_public_mode'):
        if '_la_demo_state' not in st.session_state:
            st.session_state['_la_demo_state']={'scenario':make_scenario(),'history':[],'assignments':{}}
        return st.session_state['_la_demo_state']
    DB.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS demo (id INTEGER PRIMARY KEY, state TEXT NOT NULL)')
        row=db.execute('SELECT state FROM demo WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {'scenario':make_scenario(),'history':[],'assignments':{}}

def save(state,event,actor='Demo operator'):
    state['history'].append({'Time (UTC)':datetime.now(timezone.utc).strftime('%d-%m-%y %H:%M:%S'),'Event':event,'Recorded by':actor,'Input version':fingerprint(state['scenario'])})
    if st.session_state.get('_la_public_mode'):
        st.session_state['_la_demo_state']=state
        return
    DB.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS demo (id INTEGER PRIMARY KEY, state TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO demo VALUES (1,?)',(json.dumps(state),))

def metric(column,label,value,definition):
    column.metric(label,value,help=definition);column.caption(definition)

def render(show_title=True):
    from orchestration.header_definitions import DEFINITIONS
    DEFINITIONS.update({'Launch plan':'A recommended eligible subset and operational interventions for this synthetic launch.','Actions & revalidation':'Assign responsibility, simulate selected interventions and measure the resulting scenario delta.','Agent evidence':'Source checks and explicit assumptions behind this launch recommendation.','Scenario inputs & assumptions':'Small fictional inputs used to demonstrate the complete decision chain.','Launch':'Current decision, actions and evidence for the launch selected above.','History':'Earlier saved launch assessments and their source evidence.','Detailed impact & Excel':'Per-location totals, daily stock flows and an exportable audit of the modeled outcome.'})
    if show_title:st.subheader('Launch Assurance Command Center',help='Connects item readiness, buying, shipments and location stock to one launch decision.')
    st.caption('Synthetic vertical slice · Existing source engines + deterministic shipment/inventory scenarios · No live ERP, carrier or inventory connection.')
    state=load();scenario=state['scenario']
    st.write(f"**{scenario['name']}** · {date.fromisoformat(scenario['date']).strftime('%d-%m-%y')} · {scenario['channel']} · 4 SKUs · Mumbai / Delhi · INR")
    with st.expander('Scenario inputs & assumptions',expanded=False):
        st.caption('One SKU has missing material; another has a 33.3% buying margin. Two Mumbai shipments miss launch. Delhi can donate stock while retaining its own demand and safety stock. Vendor/Finance approval is an explicit synthetic assumption, not a new approval of real records.')
        with st.form('la_inputs'):
            cols=st.columns(3)
            demand=cols[0].number_input('Mumbai daily demand per SKU',min_value=1,max_value=100,value=int(scenario['stock'][0]['daily_demand']),help='Constant synthetic daily unit demand during the seven-day launch window.')
            delay=cols[1].number_input('Shipment A milestone delay (days)',min_value=0,max_value=14,value=int(scenario['shipments'][0]['milestone_delay_days']),help='Expected arrival equals promised launch-day arrival plus this observed milestone delay; not a trained forecast.')
            expense=cols[2].number_input('Shipment A expedite cost (INR)',min_value=0,max_value=100000,value=int(scenario['shipments'][0]['expedite_cost']),help='Incremental modeled freight cost deducted from protected margin.')
            if st.form_submit_button('Save assumptions and invalidate results'):
                for row in scenario['stock']:
                    if row['location']=='Mumbai':row['daily_demand']=int(demand)
                scenario['shipments'][0]['milestone_delay_days']=int(delay);scenario['shipments'][0]['expedite_cost']=int(expense)
                state.pop('checks',None);state.pop('plan',None);state.pop('after',None)
                save(state,'Assumptions changed; previous assessment invalidated');st.rerun()
        st.caption('Demo location mapping: buying-system code TX maps to Mumbai; Delhi is existing donor stock. Stock is projected inventory at launch. Receipts arrive before daily demand. Unmet demand is lost, not backordered. Transfers take one day; donor demand and safety stock are reserved. Costs and prices are per sellable unit. No statistical confidence is claimed.')
        if st.button('Reset synthetic scenario',help='Resets this demo only; existing connected batches are untouched.'):
            state={'scenario':make_scenario(),'history':state['history'],'assignments':{}}
            save(state,'Synthetic scenario reset');st.rerun()
    if st.button('Run launch assessment',type='primary',help='Runs installed source checks and computes the shipment, stock and action scenario.'):
        try:
            with st.spinner('Running source engines and linked scenario…'):
                state['checks']=source_checks(scenario);state['plan']=recommend(scenario,state['checks']);state.pop('after',None)
            save(state,'Five-domain launch assessment completed');st.rerun()
        except (ValueError,OSError) as exc:st.error(str(exc))
    if 'plan' not in state:
        st.info('Run the assessment to follow onboarding → content → buying → shipment → location stock → release plan → owners → revalidation.');return
    plan=state['plan'];checks=state['checks'];after=state.get('after')
    columns=st.columns(4)
    metric(columns[0],'Ready for review',f"{len(plan['clear'])} / {len(scenario['items'])} SKUs",'SKUs passing setup, Catalog and buying gates; human review remains required.')
    metric(columns[1],'Demand at risk',f"{plan['baseline']['lost_units']:,} units",'Unfulfilled modeled demand across eight SKU/location pairs over seven days, including held SKUs.')
    impact=after or {'protected_revenue':plan['planned']['revenue']-plan['baseline']['revenue'],'protected_margin':plan['planned']['net_margin']-plan['baseline']['net_margin']}
    metric(columns[2],'Potential sales recovered',f"INR {impact['protected_revenue']:,.0f}",'Incremental fulfilled units × retail price versus unchanged baseline; potential, not realized revenue.')
    metric(columns[3],'Potential net margin improvement',f"INR {impact['protected_margin']:,.0f}",'Incremental gross margin less expedite and transfer costs; excludes tax, returns and other operating costs.')
    if not after:st.caption('Impact above is the recommended logistics plan for initially eligible SKUs. Simulate corrections and revalidate to calculate the combined impact.')
    blockers=[a for a in plan['actions'] if a['kind'] in ('setup','content','margin')]
    if blockers:
        st.write('**Blocking the remaining SKUs:** '+ ' · '.join(a['sku']+' — '+a['team']+': '+a['action'] for a in blockers))
    tabs=st.tabs(['Launch plan','Actions & revalidation','Agent evidence'])
    with tabs[0]:
        if plan['clear'] and plan['held']:st.warning(f"Recommend PARTIAL RELEASE: {', '.join(plan['clear'])}. Hold {', '.join(plan['held'])}.")
        elif plan['clear']:st.success('All SKUs pass source gates; review operational risks and approve the simulated release separately.')
        else:st.error('HOLD: no SKU passes all source gates.')
        if after:st.info(f"Revalidated: {len(after['clear'])}/4 SKUs eligible · Simulated human review: {'recorded' if after['release_reviewed'] else 'pending'} · {after['result']['lost_units']} units remain unfulfilled.")
        st.subheader('Top Recommended Actions',help='Concrete interventions chosen in dependency order; logistics actions require positive modeled net-margin benefit.')
        table=[]
        for i,a in enumerate(plan['actions'],1):
            assignment=state['assignments'].get(a['id'],{})
            table.append({'#':i,'SKU / scope':a['sku'],'Next action':a['action'],'Team':assignment.get('team',a['team']),'Owner':assignment.get('owner',a['owner']),'Due':date.fromisoformat(assignment.get('due',scenario['date'])).strftime('%d-%m-%y'),'State':'Simulated and revalidated' if after and a['id'] in after['selected'] else 'Open'})
        st.dataframe(pd.DataFrame(table),hide_index=True,width='stretch')
        comparison=[]
        end=after['result'] if after else plan['planned']
        for phase,result in [('Baseline',plan['baseline']),('Revalidated' if after else 'Recommended plan',end)]:
            total=result['lost_units']
            for location in ['Mumbai','Delhi']:
                value=sum(r['lost'] for r in result['locations'] if r['location']==location)
                comparison.append({'Location':location,'Phase':phase,'Unmet units':value,'Label':f"{value} ({value/total:.0%})" if total else '0 (0%)'})
        data=pd.DataFrame(comparison)
        bars=alt.Chart(data).mark_bar().encode(x=alt.X('Location:N',axis=alt.Axis(labelAngle=0)),xOffset='Phase:N',y=alt.Y('Unmet units:Q',axis=alt.Axis(format='d')),color='Phase:N',tooltip=['Location','Phase','Unmet units'])
        labels=bars.mark_text(dy=-8).encode(text='Label:N')
        st.altair_chart((bars+labels).properties(height=260),width='stretch')
        st.caption('Labels show unit counts and each location’s share of all unmet demand within that scenario. Counts include release holds; see evidence to distinguish them from stock shortages.')
    with tabs[1]:
        st.subheader('Assign ownership',help='Save a named owner, receiving team and due date in this demo’s local audit trail.')
        with st.form('la_assign'):
            selected=st.selectbox('Action to assign',[a['id'] for a in plan['actions']],help='Stable action identifier for the same SKU and intervention.')
            team=st.selectbox('Receiving team',['Catalog Operations','Buying Operations','Logistics','Inventory Operations','Launch Operations','Item Onboarding'],help='Accountable team receiving this request; reassignments do not remove validation gates.')
            owner=st.text_input('Named owner',help='Person accountable for the action; demo role defaults are not named assignments.')
            due=st.date_input('Due date',value=date.fromisoformat(scenario['date']),help='Deadline recorded with this assignment.')
            actor=st.text_input('Assignment recorded by',help='Name recorded in this local prototype; no authenticated role claim.')
            if st.form_submit_button('Assign / reassign'):
                if not owner.strip() or not actor.strip():st.error('Enter the owner and the person recording the assignment.')
                else:
                    state['assignments'][selected]=dict(team=team,owner=owner.strip(),due=str(due))
                    save(state,f'Assigned {selected} to {team} / {owner.strip()} due {due}',actor.strip());st.rerun()
        st.subheader('Simulate interventions and revalidate',help='Applies selected synthetic corrections, reruns source checks and recomputes the same daily inventory ledger.')
        st.caption('This changes only the demo. Content is completed with Cotton; negotiated cost becomes INR 750. Expedite and transfer confirmations are assumed. Nothing is sent to a carrier or ERP.')
        picked=st.multiselect('Interventions to simulate',[a['id'] for a in plan['actions']],default=[a['id'] for a in plan['actions']],format_func=lambda key:next(a['action'] for a in plan['actions'] if a['id']==key),help='Choose a subset to compare outcomes. Release requires the separate simulated review action.')
        reviewer=st.text_input('Simulation reviewer',help='Required name recorded for the simulated decision; not an enterprise approval.')
        if st.button('Simulate selected actions & revalidate',type='primary',help='Reruns Catalog and PO checks and recalculates net commercial impact without double-counting actions.'):
            if not reviewer.strip():st.error('Enter a simulation reviewer.')
            else:
                try:
                    with st.spinner('Revalidating corrected source evidence and stock flows…'):state['after']=revalidate(scenario,checks,plan,picked)
                    save(state,'Simulated interventions: '+', '.join(picked),reviewer.strip());st.rerun()
                except (ValueError,OSError) as exc:st.error(str(exc))
        detail_table(state['history'],title='Decision history',export_key='la_history',context={'Launch':scenario['name'],'Mode':'Synthetic simulation'})
    with tabs[2]:
        st.subheader('How the five agents contribute',help='Existing source rules plus two transparent scenario models; no trained predictive model is claimed.')
        agent_rows=[{'Agent':'1 · Onboarding','Finding':f"{sum(r['passed'] for r in checks['onboarding'].values())}/4 pass mandatory item + vendor checks",'Consequence':'Eligible to assess content; no real ERP creation'},
                    {'Agent':'2 · Catalog','Finding':'; '.join(sku+': '+('; '.join(r['findings']) or 'Clear') for sku,r in checks['catalog'].items()),'Consequence':'Hold content-defective SKU from this launch'},
                    {'Agent':'3 · Buying Ops','Finding':'; '.join(sku+f": {r['margin_pct']}% margin" for sku,r in checks['buying'].items()),'Consequence':'Require margin ≥45% and no blocking PO errors'},
                    {'Agent':'4 · Shipment','Finding':'Expected arrival = promised day + observed milestone delay','Consequence':'Evaluate paid expedite only where it adds net margin'},
                    {'Agent':'5 · Inventory','Finding':'Daily SKU/location stock ledger versus seven-day demand','Consequence':'Transfer available surplus; preserve donor demand and safety stock'}]
        st.dataframe(pd.DataFrame(agent_rows),hide_index=True,width='stretch')
        st.caption('Decision policy: apply source gates → assess feasible expedites → assess surplus transfers → request release review. This greedy sequence is explainable, not a claim of global optimization. Estimates have no calibrated confidence interval.')
        shipments=[]
        for s in shipment_predictions(scenario):
            shipments.append({'Shipment':s['id'],'SKU':s['sku'],'Destination':s['destination'],'Promised':scenario['date'],'Expected':str(date.fromisoformat(scenario['date'])+timedelta(days=s['expected_day'])),'Delay days':s['milestone_delay_days'],'Expedite days saved':s['expedite_days_saved']})
        detail_table(shipments,title='Shipment assumptions',export_key='la_shipments')
        end=after['result'] if after else plan['planned']
        detail_table([{**r,'Scenario':'Baseline'} for r in plan['baseline']['locations']]+[{**r,'Scenario':'Revalidated' if after else 'Recommended'} for r in end['locations']],title='Location stockout evidence',export_key='la_stock')
        detail_table(end['rows'],title='Daily inventory ledger',export_key='la_daily',context={'Launch':scenario['name'],'Days':7,'Currency':'INR','Rule version':VERSION,'Input fingerprint':fingerprint(after['revised'] if after else scenario)})
        financial=[{'Scenario':label,'Revenue':r['revenue'],'Gross margin':r['gross_margin'],'Action costs':r['action_cost'],'Net margin':r['net_margin'],'Unfulfilled units':r['lost_units']} for label,r in [('Baseline',plan['baseline']),('Revalidated' if after else 'Recommended',end)]]
        detail_table(financial,title='Commercial comparison',export_key='la_value',context={'Basis':'Modeled seven-day sales; not actual revenue','Currency':'INR'})
