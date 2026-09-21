"""Local draft buying requests; tracking never substitutes for source approval."""
from pathlib import Path
from uuid import uuid4
from datetime import date,datetime,timezone
import json,os,hashlib
import streamlit as st
import pandas as pd
from orchestration.local_safety import guarded_write

TEAMS=['Buying Operations','Vendor Operations','Catalog Operations','Finance','Launch Operations']
STATUSES=['Draft','Waiting for Finance','Waiting for Catalog','Returned to team','Ready to validate','Cancelled']

class RequestDesk:
    def __init__(self,root,cycle):
        self.path=Path(root)/(hashlib.sha256(cycle.encode()).hexdigest()+'.json')
    def load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {'revision':0,'requests':{},'events':[]}
    @guarded_write
    def save(self,key,fields,actor,reason,revision):
        state=self.load()
        if revision!=state['revision']:raise ValueError('Requests changed. Reload before saving.')
        required=['Vendor','Category','Gender','SKU','Team','Owner','Due','Status']
        if any(not str(fields.get(k,'')).strip() for k in required) or not actor.strip() or not reason.strip():
            raise ValueError('Complete the request, owner, deadline, recorder and handoff reason.')
        if fields['Team'] not in TEAMS or fields['Status'] not in STATUSES:raise ValueError('Unsupported team or request status.')
        try:date.fromisoformat(fields['Due'])
        except ValueError:raise ValueError('Use YYYY-MM-DD for the request deadline.')
        if key and key not in state['requests']:raise ValueError('Request no longer exists.')
        key=key or 'REQ-'+uuid4().hex[:10].upper()
        previous=state['requests'].get(key)
        row={k:str(fields[k]).strip() for k in required};row['Request']=key
        state['requests'][key]=row
        state['events'].append({'Request':key,'Previous':previous,'Current':row,'Recorded by':actor.strip(),'Reason':reason.strip(),'At':datetime.now(timezone.utc).isoformat()})
        state['revision']+=1;self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.'+uuid4().hex+'.tmp');tmp.write_text(json.dumps(state,indent=2));os.replace(tmp,self.path)
        return key

def render_request_desk(root,cycle):
    with st.expander('Track a buying request before item setup'):
        st.caption('Use this for a draft request that cannot yet enter validation, such as an SKU missing from Catalog. Track and return ownership here; source approval and PO execution remain separate.')
        if not cycle.strip():st.info('Name the business cycle above first.');return
        desk=RequestDesk(root,cycle);state=desk.load()
        if state['requests']:st.dataframe(pd.DataFrame(state['requests'].values()),hide_index=True,use_container_width=True)
        choice=st.selectbox('Draft request',['New request']+list(state['requests']),key='draft_choice_'+cycle)
        current=state['requests'].get(choice,{})
        with st.form('request_form_'+cycle+'_'+choice):
            values={}
            for key in ('Vendor','Category','Gender','SKU'):
                values[key]=st.text_input('Request '+key,value=current.get(key,''))
            values['Team']=st.selectbox('Request receiving team',TEAMS,index=TEAMS.index(current.get('Team',TEAMS[0])))
            values['Owner']=st.text_input('Request owner',value=current.get('Owner',''))
            values['Due']=st.text_input('Request due date',value=current.get('Due',''),placeholder='YYYY-MM-DD')
            values['Status']=st.selectbox('Request status',STATUSES,index=STATUSES.index(current.get('Status',STATUSES[0])))
            actor=st.text_input('Request recorded by');reason=st.text_input('Request handoff reason')
            save=st.form_submit_button('Save request / handoff')
        if save:
            try:desk.save(None if choice=='New request' else choice,values,actor,reason,state['revision']);st.rerun()
            except ValueError as e:st.error(str(e))
        if state['events']:
            from orchestration.presentation import detail_table
            detail_table(state['events'],title='Request handoff history',export_key='request_history',context={'Cycle':cycle},hide_index=True)
