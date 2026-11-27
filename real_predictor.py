"""Experimental causal gold-only four-hour-to-midnight predictor.

No external news, macro inputs, execution, or network. The app has not been
integrated. Friday labels are excluded: historical close calendar unverified.
Training filters Mon–Thu observed daily breaks empirically, which is not proof
of trading hours; callers must treat output as research only.
"""
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression,Ridge
F=['r1','r4','r16','r48','vol32','range16','age_min','weekday']

def features(bars,cut):
 p=bars[(bars.index+pd.Timedelta(minutes=15)<=cut)&bars.completed].tail(120)
 if len(p)<97:return None
 seq=p.close;ref=float(seq.iloc[-1]);age=(cut-(p.index[-1]+pd.Timedelta(minutes=15))).total_seconds()/60
 if ref<=0 or age<0:return None
 r=seq.pct_change().dropna();x={'r1':(ref/seq.iloc[-2]-1)*100,'r4':(ref/seq.iloc[-5]-1)*100,'r16':(ref/seq.iloc[-17]-1)*100,'r48':(ref/seq.iloc[-49]-1)*100,'vol32':float(r.tail(32).std()*100),'range16':(float(p.high.tail(16).max())-float(p.low.tail(16).min()))/ref*100,'age_min':age,'weekday':cut.weekday()}
 if not np.isfinite(list(x.values())).all():return None
 return {'reference_price':ref,'reference_end':(p.index[-1]+pd.Timedelta(minutes=15)).isoformat(),**x}

def dataset(bars,cut,end_hour=24):
 rows=[]
 for d in sorted(set(bars.index.date)):
  day=pd.Timestamp(d,tz='UTC')
  if day.date()>=cut.date() or day.weekday()>=4:continue
  testcut=day+pd.Timedelta(hours=cut.hour,minutes=cut.minute);end=day+pd.Timedelta(hours=end_hour)
  f=features(bars,testcut)
  if f is None:continue
  expected=pd.date_range(testcut,end-pd.Timedelta(minutes=15),freq='15min'); seq=bars.reindex(expected)
  if seq.empty or pd.isna(seq.close.iloc[-1]) or not bool(seq.completed.iloc[-1]):continue
  missing=seq[seq.close.isna()]
  if len(missing)>4 or any(t.hour not in (21,22) for t in missing.index):continue
  seen=seq.dropna(subset=['close','high','low','completed'])
  if len(seen)!=len(seq)-len(missing) or not seen.completed.all():continue
  endprice=float(seq.close.iloc[-1]);ref=f['reference_price']
  if endprice==ref:continue
  rows.append({**f,'target':int(endprice>ref),'return_pct':(endprice/ref-1)*100,'high_pct':(max(ref,float(seen.high.max()))/ref-1)*100,'low_pct':(1-min(ref,float(seen.low.min()))/ref)*100})
 return pd.DataFrame(rows)

def predict_from_history(history,cut,decision):
 """history has UTC index and open/high/low/close/completed, with no future rows.
 cut is the data cutoff; no post-cut information is used, even if present.
 """
 if cut.tzinfo is None or cut.utcoffset().total_seconds()!=0:raise ValueError('UTC cutoff required')
 if cut.weekday()>=5:raise ValueError('Weekend forecasting disabled')
 if cut.weekday()==4 and cut.hour>=20:raise ValueError('Friday 20:00 endpoint already reached')
 friday=cut.weekday()==4;end_hour=20 if friday else 24
 bars=history.loc[history.index+pd.Timedelta(minutes=15)<=cut].copy()
 f=features(bars,cut)
 if not f:raise ValueError('Insufficient completed history')
 if f['reference_end']!=decision['reference_bar_end'] or abs(f['reference_price']-decision['reference_close'])>1e-7:raise ValueError('Reference mismatch')
 tr=dataset(bars,cut,end_hour=end_hour)
 if len(tr)<50 or tr.target.nunique()!=2:raise ValueError('Insufficient verified eligible training days')
 X=tr[F];x=pd.DataFrame([f])[F]
 clf=make_pipeline(StandardScaler(),LogisticRegression(C=.5,max_iter=1000)).fit(X,tr.target)
 def reg(y):return float(make_pipeline(StandardScaler(),Ridge(alpha=50)).fit(X,y).predict(x)[0])
 p=float(clf.predict_proba(x)[0,1]);ref=f['reference_price'];e=ref*(1+reg(tr.return_pct)/100)
 hi=ref*(1+max(0,reg(tr.high_pct))/100);lo=ref*(1-max(0,reg(tr.low_pct))/100)
 result={'model':'gold-only-friday-20-v1' if friday else 'gold-only-4h-research-v1','p_up':round(p,4),'direction':'up' if p>=.5 else 'down','estimated_end':round(e,3),'estimated_high_remaining':round(hi,3),'estimated_low_remaining':round(lo,3),'training_days':len(tr),'training_policy':'prior Mon–Thu only, same cutoff time and endpoint; no Friday historical labels','scope':'research only; Friday 20:00 UTC endpoint' if friday else 'research only; Monday–Thursday midnight endpoint','warning':'No demonstrated trading edge. Calendar breaks and availability are assumptions.'}
 from price_map import build_map
 result['scenario']=build_map(bars,cut,result,ref)
 return result
