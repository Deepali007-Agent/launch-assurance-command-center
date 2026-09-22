"""Reproducible synthetic record-level benchmark; no production or user-study claim."""
import csv,json,sys,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'apps/onboarding/src'),str(ROOT/'apps/catalog'),str(ROOT/'apps/po')]
from agents import assess_vendor
from catalog_operations.ingestion import ingest_dataframe
from catalog_operations.agents.catalog_quality import CatalogQualityAgent
from catalog_operations.agents.policy_validation import PolicyValidationAgent
from domain.po_engine import validate_row
import pandas as pd

# Authored expectations, independent of predicted outputs; pending external review.
CRITICAL={'tax_id','size','material','Cancel Dates','currency','Cost','Total Quantity'}
def load(path):
 with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def assess(kind,rows):
 result=[]
 for i,row in enumerate(rows):
  if kind=='vendor':
   findings=[f for a in assess_vendor(row) for f in a['findings']]
   severity='Critical' if any(f['severity']=='Critical' for f in findings) else 'Warning' if findings else 'Clear'
   messages=[f["field"]+': '+f['issue'] for f in findings]
  elif kind=='catalog':
   parsed=ingest_dataframe(pd.DataFrame([row]))
   if parsed.errors:severity='Critical';messages=[e.message for e in parsed.errors]
   else:
    findings=[f for a in (CatalogQualityAgent(),PolicyValidationAgent()) for f in a.evaluate(parsed.items[0]).findings]
    severity='Critical' if any(str(f['severity']).lower()=='critical' for f in findings) else 'Warning' if findings else 'Clear'
    messages=[str(f) for f in findings]
  else:
   r=validate_row(row,i);severity={'FAIL':'Critical','WARN':'Warning','PASS':'Clear'}[r['status']];messages=r['errors']+r['warnings']
  result.append((severity,messages))
 return result

def main():
 out=ROOT/'benchmark';out.mkdir(exist_ok=True)
 answers=load(ROOT/'demo/error_answer_key.csv');details=[];summary=[]
 for kind in ('vendor','catalog','po'):
  expected={int(r['record'])-1:('Critical' if r['field'] in CRITICAL else 'Warning') for r in answers if r['file']==kind+'.csv'}
  started=time.perf_counter();dirty=assess(kind,load(ROOT/f'demo/with_errors/{kind}.csv'));clean=assess(kind,load(ROOT/f'demo/corrected/{kind}.csv'))
  elapsed=time.perf_counter()-started
  tp=sum(i in expected and s!='Clear' for i,(s,_) in enumerate(dirty));fp=sum(i not in expected and s!='Clear' for i,(s,_) in enumerate(dirty));fn=len(expected)-tp;tn=len(dirty)-len(expected)-fp
  precision=tp/(tp+fp) if tp+fp else None;recall=tp/(tp+fn) if tp+fn else None
  summary.append(dict(domain=kind,records=len(dirty),inserted_error_records=len(expected),true_positive=tp,false_positive=fp,false_negative=fn,true_negative=tn,precision=precision,recall=recall,false_positive_rate=fp/(fp+tn) if fp+tn else None,f1=2*precision*recall/(precision+recall) if precision and recall else 0,critical_recall=sum(dirty[i][0]=='Critical' for i,s in expected.items() if s=='Critical')/sum(s=='Critical' for s in expected.values()),severity_correct=sum(dirty[i][0]==s for i,s in expected.items()),corrections_cleared=sum(clean[i][0]=='Clear' for i in expected),corrected_unexpected_findings=sum(s!='Clear' for s,_ in clean),seconds_dirty_and_corrected=round(elapsed,3)))
  for i,(s,m) in enumerate(dirty):details.append(dict(domain=kind,csv_row=i+2,expected=expected.get(i,'Clear'),observed=s,corrected_observed=clean[i][0],findings=' | '.join(m)))
 report={'basis':'Synthetic authored cases; expectations require independent business review. Record-level metrics, not per-finding metrics. Negative cases are the remaining generated records. This is regression evidence, not real-world detection accuracy. Ownership and handoff correctness require the separate workflow suite; they are not inferred from source severity.','dataset_hashes':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'demo').glob('*/*.csv'))},'results':summary}
 (out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 with (out/'record_results.csv').open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=list(details[0]));w.writeheader();w.writerows(details)
 lines=['# Synthetic validation benchmark','',report['basis'],'','| Domain | Records | Precision | Recall | Critical recall | False positives | Cleared corrections |','|---|---:|---:|---:|---:|---:|---:|']
 for r in summary:lines.append(f"| {r['domain']} | {r['records']} | {r['precision']:.1%} | {r['recall']:.1%} | {r['critical_recall']:.1%} | {r['false_positive']} | {r['corrections_cleared']}/{r['inserted_error_records']} |")
 (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps(summary,indent=2))
 if any(r['false_positive'] or r['false_negative'] or r['severity_correct']!=r['inserted_error_records'] or r['corrections_cleared']!=r['inserted_error_records'] or r['corrected_unexpected_findings'] for r in summary):raise SystemExit('Synthetic benchmark expectations did not pass; inspect the report.')
if __name__=='__main__':main()
