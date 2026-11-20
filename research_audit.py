#!/usr/bin/env python3
"""Exploratory point-in-time session/model comparisons and Yahoo revision audit.
Not a deployable model selector. No orders or new live forecasts are generated.
"""
import json, os, urllib.request, urllib.parse
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss
import intraday as base  # also updates intraday snapshot and live forecast log

ROOT = os.path.dirname(os.path.abspath(__file__))
now = datetime.now(timezone.utc)
SYMS={'silver':'SI=F','oil':'CL=F','dollar':'DX-Y.NYB','copper':'HG=F','yield':'^TNX','equity':'^GSPC'}
feeds={}; feed_status={}
for key,sym in SYMS.items():
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(sym,safe='')+'?range=730d&interval=1h'
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=30) as r: raw=json.load(r)['chart']['result'][0]
        q=raw['indicators']['quote'][0]
        z=pd.DataFrame({'close':q['close']},index=pd.to_datetime(raw['timestamp'],unit='s',utc=True)).sort_index().dropna()
        z=z[~z.index.duplicated(keep='first')]; z=z[z.index <= pd.Timestamp(now)]
        feeds[key]=z
        feed_status[key]={'symbol':sym,'rows':len(z),'latest_bar_start_utc':z.index[-1].isoformat(),
                          'regular_market_time_utc':datetime.fromtimestamp(raw['meta']['regularMarketTime'],timezone.utc).isoformat() if raw['meta'].get('regularMarketTime') else None}
    except Exception as e:
        feed_status[key]={'symbol':sym,'error':str(e)}
        print('Missing feed',key,e)
if len(feeds)!=len(SYMS): raise RuntimeError('Research needs all requested feeds; refusing partial comparison')

# Compare completed hourly gold bars from the last 7 days with the previous saved
# retrieval. Both retrievals are after each bar's end; first run establishes baseline.
auditpath=os.path.join(ROOT,'quote_audit.json')
if os.path.exists(auditpath):
    with open(auditpath) as f: audit=json.load(f)
else: audit={'last_snapshot':{},'runs':[]}
cutoff=pd.Timestamp(now)-pd.Timedelta(days=7)
old=audit.get('last_snapshot',{})
frame=base.bars[(base.bars.index>=cutoff)&(base.bars.index+pd.Timedelta(hours=1)<=pd.Timestamp(now))].dropna()
snapshot={t.isoformat():{k:round(float(row[k]),5) for k in ['open','high','low','close']} for t,row in frame.iterrows()}
common=set(old)&set(snapshot)
revisions=[{'bar_utc':t,'before':old[t],'after':snapshot[t]} for t in sorted(common) if old[t]!=snapshot[t]]
audit['runs'].append({'retrieved_at':now.isoformat(), 'compared_bars':len(common),'revised_bars':len(revisions), 'revisions':revisions[:20]})
audit['runs']=audit['runs'][-100:];audit['last_snapshot']=snapshot
with open(auditpath,'w') as f: json.dump(audit,f,indent=2,allow_nan=False)

# Use only completed auxiliary bars: assume 1-hour bar duration and latest bar
# is available at bar_start + 1h. The vendor offers no archived receipt times;
# this optimistic assumption must be audited prospectively.
def enrich(df,start):
    out=df.copy(); decision=pd.to_datetime(out.index,utc=True)+pd.Timedelta(hours=start)
    for key,feed in feeds.items():
        z=feed.copy(); z['r1']=z.close.pct_change(fill_method=None)*100; z['r4']=z.close.pct_change(4,fill_method=None)*100
        z['available']=z.index+pd.Timedelta(hours=1)
        left=pd.DataFrame({'decision':decision, 'row':np.arange(len(out))}).sort_values('decision')
        right=z[['available','r1','r4']].dropna().sort_values('available')
        matched=pd.merge_asof(left,right,left_on='decision',right_on='available',direction='backward',tolerance=pd.Timedelta(hours=72)).sort_values('row')
        out[key+'_r1']=matched.r1.to_numpy(); out[key+'_r4']=matched.r4.to_numpy()
        out[key+'_age_hours']=(matched.decision-matched.available).dt.total_seconds().to_numpy()/3600
    return out.dropna(subset=base.FEATURES+[k+'_'+a for k in feeds for a in ['r1','r4','age_hours']]+['target'])

EXTRA=[k+'_'+x for k in feeds for x in ['r1','r4','age_hours']]
def compare(start,end):
    dataset=enrich(base.dataset(start,end),start)
    if len(dataset)<160: raise RuntimeError('Insufficient aligned history for '+str((start,end)))
    cut=int(len(dataset)*.8); predictions=[]
    for i in range(cut,len(dataset)):
        train=dataset.iloc[:i]; test=dataset.iloc[[i]]
        row={'date':test.index[0], 'actual':int(test.target.iloc[0]), 'start':float(test.start_price.iloc[0]), 'end':float(test.end_price.iloc[0])}
        for name, features in [('gold',base.FEATURES),('macro',base.FEATURES+EXTRA)]:
            clf=make_pipeline(StandardScaler(),LogisticRegression(C=.5,max_iter=1000))
            clf.fit(train[features],train.target.astype(int))
            row[name]=float(clf.predict_proba(test[features])[0,1])
        predictions.append(row)
    y=np.array([p['actual'] for p in predictions]); results={}
    for name in ('gold','macro'):
        probs=np.array([p[name] for p in predictions]); pnl=np.array([(1 if p[name]>=.5 else -1)*(p['end']-p['start']) for p in predictions]); hit=float(accuracy_score(y,probs>=.5))
        results[name]={'accuracy':round(hit,4),'brier':round(float(brier_score_loss(y,probs)),4),
                       'mean_gross_usd_per_oz':round(float(pnl.mean()),2),
                       'net_usd_per_oz_at_round_trip_cost':{str(c):round(float(pnl.mean()-c),2) for c in (1,3,5)}}
    return {'start_utc':f'{start:02d}:00','end_utc':f'{end:02d}:00','n':len(y),
            'start_date':predictions[0]['date'],'end_date':predictions[-1]['date'],
            'always_up':round(float(y.mean()),4),'always_down':round(float(1-y.mean()),4),'models':results}

comparisons={}
for s,e in [(8,18),(13,18),(8,13),(10,18)]:
    comparisons[f'{s:02d}-{e:02d}']=compare(s,e)
report={'generated_at':now.isoformat(), 'comparisons':comparisons,'feed_status':feed_status,
        'audit':audit['runs'][-1],
        'assumptions':['Retrospective exploratory tests; comparing windows on the same data creates selection bias.',
                       'All models refit daily on earlier completed outcomes; shared chronological final 20% per aligned window.',
                       'One-hour feeds are assumed available one hour after timestamp; actual historical publication delays and revisions are unknown.',
                       'Auxiliary features are the last completed bar and 1/4-bar return with max 72-hour age, not news surprises or inflation releases.',
                       'Costs of $1/$3/$5 per troy ounce round trip are illustrative, not observed broker quotes.',
                       'Gross P&L assumes a fill at the forecast-time hourly bar open, which a later-issued forecast cannot achieve; results are optimistic and omit financing and market impact.',
                       'This is not automatic model promotion. Paper trade out of sample with actual timestamped executable quotes first.']}
with open(os.path.join(ROOT,'docs','research.json'),'w') as f: json.dump(report,f,indent=2,allow_nan=False)
print(json.dumps(report,indent=2,allow_nan=False))
