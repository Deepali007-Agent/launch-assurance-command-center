"""Local batch-linked logistics intake and auditable reviewer choices."""
import json
from datetime import date,datetime,timezone
import pandas as pd
import streamlit as st
from .uploaded import STOCK,SHIP,POLICY,prepare,comparisons,basis
from orchestration.presentation import detail_table
from .observability import event

def tables(store):
 with store.connect(True) as db:
  db.executescript('CREATE TABLE IF NOT EXISTS logistics_inputs(batch TEXT PRIMARY KEY,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS logistics_reviews(id INTEGER PRIMARY KEY AUTOINCREMENT,batch TEXT NOT NULL,basis TEXT NOT NULL,payload TEXT NOT NULL);')
def load(store,batch):
 tables(store)
 with store.connect() as db:
  row=db.execute('SELECT payload FROM logistics_inputs WHERE batch=?',(batch,)).fetchone()
 return json.loads(row[0]) if row else None

def record_review(store,batch,input_data,input_basis,sku,option,decision,actor,reason,owner,due):
 if not all(str(v).strip() for v in (actor,reason,owner,due)):raise ValueError('Reviewer, justification, owner and due date are required.')
 if decision not in ('Accept','Reject','Defer','Override'):raise ValueError('Invalid review decision.')
 date.fromisoformat(due)
 # Guard concurrent source and logistics edits inside the same write transaction.
 with store.connect(True) as db:
  token=db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE batch=?',(batch,)).fetchone()[0]
  row=db.execute('SELECT payload FROM logistics_inputs WHERE batch=?',(batch,)).fetchone()
  if not row or basis(token,json.loads(row[0]))!=input_basis or basis(token,input_data)!=input_basis:raise ValueError('Inputs or source evidence changed. Refresh and reassess before reviewing.')
  choices=comparisons(prepare(store.board(batch),input_data['stock'],input_data['shipments'],input_data['horizon']))
  selected=next((r for r in choices if r['SKU']==sku and r['Option']==option),None)
  if selected is None or decision in ('Accept','Override') and not selected['Feasible']:raise ValueError('This option is unavailable; critical requirements cannot be overridden.')
  record={'Time (UTC)':datetime.now(timezone.utc).isoformat(),'SKU':sku,'Option':option,'Decision':decision,'Reviewer':actor,'Justification':reason,'Owner':owner,'Due':due,'Team':'Logistics' if option=='Expedite' else 'Inventory Operations' if option=='Reallocate stock' else 'Launch Operations','Policy':POLICY}
  db.execute('INSERT INTO logistics_reviews(batch,basis,payload) VALUES(?,?,?)',(batch,input_basis,json.dumps(record)))
 event('recommendation_review_recorded',batch=batch,policy=POLICY,decision=decision,basis=input_basis)

def render(store,batch):
 if not batch:return
 st.subheader('Shipment and stock decisions',help='Compare operational alternatives using this batch’s current execution gates and your uploaded location data.')
 data=load(store,batch)
 with st.expander('Upload shipment and inventory inputs',expanded=data is None):
  st.caption('INR only. One inventory row per SKU/location; constant daily demand over a 1–31 day horizon. Day 0 is the launch date. Use PO location codes for shipment destinations. No forecast accuracy or carrier capacity is assumed.')
  left,right=st.columns(2)
  for col,cols,label in [(left,STOCK,'inventory'),(right,SHIP,'shipments')]:
   col.download_button('Download '+label+' template',','.join(cols)+'\n',label+'-template.csv','text/csv',key='log_template_'+label,help='Header-only template; fill explicit inputs for the selected batch.')
  with st.form('batch_logistics'):
   launch_date=st.date_input('Operational launch date',value=date.fromisoformat(data['launch_date']) if data else date.today(),help='Day zero for arrivals and the demand horizon.')
   horizon=st.number_input('Assessment horizon (days)',min_value=1,max_value=31,value=data['horizon'] if data else 7,help='Days of constant daily demand modeled from launch.')
   inv=st.file_uploader('Inventory and daily demand CSV',type=['csv'],help='Opening inventory, daily demand, safety reserve and transfer assumptions by SKU/location.')
   ship=st.file_uploader('Shipment milestones CSV',type=['csv'],help='Promised arrival offset, observed delay, quantity and offered expedite time/cost.')
   if st.form_submit_button('Validate and save logistics inputs'):
    try:
     if inv is None or ship is None:raise ValueError('Upload both files together to replace this batch’s logistics assumptions.')
     payload={'launch_date':str(launch_date),'horizon':int(horizon),'stock':pd.read_csv(inv,keep_default_na=False).to_dict('records'),'shipments':pd.read_csv(ship,keep_default_na=False).to_dict('records')}
     prepare(store.board(batch),payload['stock'],payload['shipments'],payload['horizon'])
     with store.connect(True) as db:db.execute('INSERT OR REPLACE INTO logistics_inputs VALUES(?,?)',(batch,json.dumps(payload,allow_nan=False)))
     event("logistics_inputs_saved",batch=batch,policy=POLICY,stock_rows=len(payload["stock"]),shipment_rows=len(payload["shipments"]))
     st.rerun()
    except (ValueError,KeyError,TypeError) as exc:st.error(str(exc))
 if not data:
  st.info('Add shipment and inventory inputs to compare commercial options for this uploaded batch. No demo values are substituted.');return
 try:
  model=prepare(store.board(batch),data['stock'],data['shipments'],data['horizon']);rows=comparisons(model)
 except (ValueError,KeyError,TypeError) as exc:st.error('Reassessment required: '+str(exc));return
 current=basis(store.token(batch),data)
 picks=[r for r in rows if r['Recommendation']=='Recommended']
 cols=st.columns(3)
 cols[0].metric('Execution-eligible SKUs',f"{sum(model['allowed'].values())}/{len(model['allowed'])}",help='Every PO line for a SKU must satisfy the existing execution gates; no review here can change those gates.')
 cols[1].metric('Potential sales improvement',f"INR {sum(r['Revenue impact (INR)'] for r in picks):,.0f}",help='Recommended individual option per SKU versus no action; modeled potential, not realized sales.')
 cols[2].metric('Potential net margin improvement',f"INR {sum(r['Net margin impact (INR)'] for r in picks):,.0f}",help='Modeled incremental margin after the selected expedite or transfer cost. Individual alternatives cannot be added together for the same SKU.')
 st.caption(f"Launch {data['launch_date']} · {data['horizon']} days · Policy {POLICY}. Recomputed from current source gates. Estimates assume receipts arrive before daily demand; unmet demand is lost. Transfers use opening donor surplus after reserving the full demand horizon and safety stock.")
 skus=sorted(model['prices']);selected_sku=st.selectbox('Compare alternatives for SKU',skus,help='Three comparable choices for one SKU; unavailable options include their blocking constraints.')
 selected=[r for r in rows if r['SKU']==selected_sku]
 st.dataframe(pd.DataFrame(selected).drop(columns=['Transfer','Data completeness','Reversible','Operational risk','Selection basis']),hide_index=True,width='stretch')
 st.caption('Selection: highest net margin among feasible individual options; no action wins ties. This compares candidate options, not a globally optimal network plan. Sensitivity reruns the same option at +20% demand; it is not statistical confidence. Capacity and execution reliability are not assessed.')
 with st.expander('Record a recommendation decision',expanded=False):
  st.caption('A recorded choice is reversible before dispatch. This prototype does not dispatch stock, book transport or grant source approval. Source changes make old choices stale.')
  with st.form('logistics_review'):
   option=st.selectbox('Option',['Take no action','Expedite','Reallocate stock'])
   decision=st.selectbox('Decision',['Accept','Reject','Defer','Override'])
   actor=st.text_input('Logistics reviewer',help='Recorded name; this local prototype does not authenticate users.')
   owner=st.text_input('Accountable action owner',help='Person responsible for following up with Logistics, Inventory or Launch Operations.')
   due=st.date_input('Action due date',value=date.fromisoformat(data['launch_date']))
   reason=st.text_area('Decision justification',help='Explain the choice, especially when overriding the recommended feasible option.')
   if st.form_submit_button('Record decision'):
    try:record_review(store,batch,data,current,selected_sku,option,decision,actor,reason,owner,str(due));st.success('Decision recorded; no external execution occurred.')
    except ValueError as exc:st.error(str(exc))
 with store.connect() as db:history=[{**json.loads(r['payload']),'Evidence current':r['basis']==current} for r in db.execute('SELECT basis,payload FROM logistics_reviews WHERE batch=? ORDER BY id DESC',(batch,))]
 detail_table([{k:v for k,v in r.items() if k!='Transfer'} for r in rows],title='All SKU alternatives',export_key='uploaded_logistics_options',context={'Batch':batch,'Policy':POLICY,'Basis':current})
 detail_table(history,title='Logistics decisions and ownership',export_key='uploaded_logistics_history')
