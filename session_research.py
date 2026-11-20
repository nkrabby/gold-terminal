#!/usr/bin/env python3
"""Exploratory, timezone-aware Tokyo/London/New York session comparison.
Runs research_audit (and intraday) as part of the existing refresh pipeline.
"""
import json, os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss
import research_audit as research

base=research.base
sessions={
    'Asia (Tokyo proxy)': {'zone':'Asia/Tokyo','local_start':9,'local_end':15},
    'London': {'zone':'Europe/London','local_start':8,'local_end':16},
    'New York': {'zone':'America/New_York','local_start':8,'local_end':16},
}
frames={}
for name,cfg in sessions.items():
    parts=[]
    # Each pair of UTC hours corresponds to a local-time DST regime. All selected
    # dates here have start/end on same UTC date; reject future incompatible configs.
    all_dates=sorted(set(base.bars.index.date))
    pairs=set()
    for d in all_dates:
        midnight=pd.Timestamp(d).tz_localize(cfg['zone'])
        start=(midnight+pd.Timedelta(hours=cfg['local_start'])).tz_convert('UTC')
        end=(midnight+pd.Timedelta(hours=cfg['local_end'])).tz_convert('UTC')
        if start.date()!=d or end.date()!=d or end.hour<=start.hour:
            raise ValueError('Session crosses UTC date; dataset builder needs adaptation')
        pairs.add((start.hour,end.hour))
    for sh,eh in sorted(pairs):
        df=base.dataset(sh,eh)
        keep=[]
        for ds in df.index:
            local=pd.Timestamp(ds).tz_localize(cfg['zone'])
            t=(local+pd.Timedelta(hours=cfg['local_start'])).tz_convert('UTC')
            u=(local+pd.Timedelta(hours=cfg['local_end'])).tz_convert('UTC')
            keep.append(t.hour==sh and u.hour==eh)
        df=df.loc[keep]
        if len(df): parts.append(research.enrich(df,sh))
    frames[name]=pd.concat(parts).sort_index()
    cfg['utc_hour_pairs']=[f'{s:02d}:00–{e:02d}:00' for s,e in sorted(pairs)]
# Intersect dates to compare the same days and use the same train/holdout cutoff.
common=set.intersection(*(set(df.index) for df in frames.values()))
dates=sorted(common)
if len(dates)<160: raise RuntimeError('Not enough common session days')
cut=int(len(dates)*.8); out={}
for name,cfg in sessions.items():
    d=frames[name].loc[dates]; records=[]
    for i in range(cut,len(d)):
        tr=d.iloc[:i]; te=d.iloc[[i]]; row=te.iloc[0]
        pred={'date':te.index[0], 'actual':int(row.target), 'start':float(row.start_price), 'end':float(row.end_price)}
        for model, features in [('gold',base.FEATURES),('macro',base.FEATURES+research.EXTRA)]:
            clf=make_pipeline(StandardScaler(),LogisticRegression(C=.5,max_iter=1000))
            clf.fit(tr[features],tr.target.astype(int))
            pred[model]=float(clf.predict_proba(te[features])[0,1])
        records.append(pred)
    actual=np.array([r['actual'] for r in records]); models={}
    for model in ('gold','macro'):
        p=np.array([r[model] for r in records])
        pnl=np.array([(1 if r[model]>=.5 else -1)*(r['end']-r['start']) for r in records])
        models[model]={'accuracy':round(float(accuracy_score(actual,p>=.5)),4),
                       'brier':round(float(brier_score_loss(actual,p)),4),
                       'gross_mean_usd_oz':round(float(pnl.mean()),2),
                       'net_at_3_usd_cost':round(float(pnl.mean()-3),2)}
    out[name]={**cfg,'n':len(records),'holdout_start':records[0]['date'],'holdout_end':records[-1]['date'],
               'always_up':round(float(actual.mean()),4),'always_down':round(float(1-actual.mean()),4),'models':models}
report={'generated_at':datetime.now(timezone.utc).isoformat(), 'common_days':len(dates), 'sessions':out,
        'notes':['Session definitions are research conventions, not official universal market hours. Asia uses Tokyo only.',
                 'Timezone conversion incorporates daylight saving; hourly GC=F bar opens proxy start/end prices.',
                 'Matching dates across all sessions and excluding missing bars can create selection bias.',
                 'Daily expanding refit uses only earlier days; gold-only and macro models are tested on identical days.',
                 'Historical vendor availability/revisions unknown; hourly OHLC assumes finalized on the hour.',
                 'Simulated trades at session opening prices are optimistic: actual forecasts and fills arrive later.',
                 'A $3/oz round-trip cost is illustrative, not broker pricing; no financing, slippage distribution or risk controls.',
                 'Exploratory results do not justify automatic model promotion.']}
with open(os.path.join(research.ROOT,'docs','sessions.json'),'w') as f: json.dump(report,f,indent=2,allow_nan=False)
print(json.dumps(report,indent=2))
