"""PO charts tied to the current assessment, with explicit denominators."""
from collections import Counter, defaultdict
import altair as alt
import pandas as pd


def outcome_rows(results):
    counts=Counter(row['status'] for row in results)
    total=len(results)
    return [{'Outcome':label,'Lines':counts[status],'% of lines':100*counts[status]/total if total else 0}
            for status,label in [('PASS','Checks clear'),('WARN','Review'),('FAIL','Blocked')]]


def issue_rows(results):
    counts=Counter(issue for row in results for issue in set(row.get('error_types',[])))
    return [{'Issue':issue,'Affected lines':count,'% of lines':100*count/len(results)}
            for issue,count in counts.most_common(6)]


def exposure_rows(results):
    values=defaultdict(float)
    for row in results:
        if row.get('is_flagged') and row.get('commercial_value_included',True):
            values[row.get('division') or 'Unspecified']+=max(0,float(row.get('cost_val') or 0))
    total=sum(values.values())
    return [{'Division':name,'Flagged commitment (INR)':value,'% of flagged commitment':100*value/total if total else 0}
            for name,value in sorted(values.items(),key=lambda item:item[1],reverse=True) if value>0]


def bar_chart(rows,category,value,share):
    frame=pd.DataFrame(rows)
    frame['Label']=[f'{v:,.0f} ({p:.1f}%)' for v,p in zip(frame[value],frame[share])]
    base=alt.Chart(frame).encode(
        x=alt.X(category+':N',sort=None,title=None,axis=alt.Axis(labelAngle=0,labelLimit=155)),
        y=alt.Y(value+':Q',title=value,scale=alt.Scale(zero=True),axis=alt.Axis(format=',.0f')),
        tooltip=[category,alt.Tooltip(value+':Q',format=',.0f'),alt.Tooltip(share+':Q',format='.1f')],
    )
    bars=base.mark_bar(color='#7f91ef',cornerRadiusTopLeft=4,cornerRadiusTopRight=4)
    labels=base.mark_text(dy=-10,color='#eef2ff',fontSize=12).encode(text='Label:N')
    return (bars+labels).properties(height=255).configure_view(stroke=None)
