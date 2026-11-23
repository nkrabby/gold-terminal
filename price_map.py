"""Uncalibrated scenario zones and conservative completed-bar touch proxy."""
from datetime import timedelta, timezone
import numpy as np
import pandas as pd

def build_map(bars,cut,pred,ref):
 p=bars[(bars.index+pd.Timedelta(minutes=15)<=cut)&bars.completed].tail(15)
 if len(p)<15 or any(p.index.to_series().diff().iloc[1:]!=pd.Timedelta(minutes=15)):
  return {'available':False,'reason':'Need 15 consecutive completed M15 bars'}
 prev=p.close.shift(1);tr=pd.concat([p.high-p.low,(p.high-prev).abs(),(p.low-prev).abs()],axis=1).max(axis=1);atr=float(tr.iloc[-14:].mean())
 probability=float(pred['p_up']);end=float(pred['estimated_end'])
 if not np.isfinite(atr) or atr<=0:return {'available':False,'reason':'ATR unavailable'}
 if .45<probability<.55:return {'available':False,'reason':'Direction probability is near neutral'}
 side=1 if probability>=.55 else -1
 if (end-ref)*side<=0:return {'available':False,'reason':'Direction and endpoint disagree'}
 def zone(a,b):return sorted([round(ref-side*a*atr,3),round(ref-side*b*atr,3)])
 return {'available':True,'side':'up' if side==1 else 'down','atr_m15':round(atr,3),'aggressive_zone':zone(.25,.5),'conservative_zone':zone(.75,1.0),'invalidation':round(ref-side*1.5*atr,3),'target':round(end,3),'note':'Uncalibrated volatility rules, not a trade signal.'}

def track_zone(scenario,zone,bars,issued,now,end):
 """Use full M15 bars after issue; gaps or same-bar order are unknown.
 The issue candle is excluded. Scheduled breaks are not filled/interpolated.
 """
 for t in (issued,now,end):
  if t.tzinfo is None or t.utcoffset()!=timedelta(0):raise ValueError('UTC timestamps required')
 start=pd.Timestamp(issued).ceil('15min');last=min(pd.Timestamp(now).floor('15min'),pd.Timestamp(end));target=float(scenario['target']);invalid=float(scenario['invalidation']);zlo,zhi=zone
 if last<=start:return {'status':'waiting for completed bars'}
 expected=pd.date_range(start,last-pd.Timedelta(minutes=15),freq='15min');seen=bars.reindex(expected);touched=False;prev=None
 for ts,x in seen.iterrows():
  if pd.isna(x.open) or pd.isna(x.close) or pd.isna(x.high) or pd.isna(x.low) or pd.isna(x.completed) or not x.completed:return {'status':'unknown: missing completed candle','at':ts.isoformat()}
  if prev is not None and any(min(prev,x.open)<level<max(prev,x.open) for level in (zlo,zhi,target,invalid)):
   return {'status':'unknown: price gap crossed a relevant level','at':ts.isoformat()}
  lo,hi=float(x.low),float(x.high);hit_z=lo<=zhi and hi>=zlo;hit_t=lo<=target<=hi;hit_i=lo<=invalid<=hi
  if not touched:
   if hit_z:
    touched=True
    if hit_t or hit_i:return {'status':'ambiguous: zone and outcome in same candle','at':ts.isoformat()}
   elif hit_t or hit_i:return {'status':'level reached before zone; scenario expired','at':ts.isoformat()}
  else:
   if hit_t and hit_i:return {'status':'ambiguous: target and invalidation in same candle','at':ts.isoformat()}
   if hit_t:return {'status':'target touched after zone','at':ts.isoformat()}
   if hit_i:return {'status':'invalidation touched after zone','at':ts.isoformat()}
  prev=float(x.close)
 if pd.Timestamp(now)>=pd.Timestamp(end):return {'status':'zone touched; no outcome by endpoint' if touched else 'zone not observed by endpoint'}
 return {'status':'zone touched; waiting' if touched else 'waiting for zone'}
