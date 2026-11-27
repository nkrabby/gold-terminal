"""Research-only standalone integration prototype. NOT READY TO DEPLOY.

The GitHub workflow and UI are not yet connected. Requires explicit calendar
verification by date, and never rewrites legacy log files.
"""
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
import numpy as np
import pandas as pd
from integration import issue_once,score_one
from forecast_store import ForecastStore
from real_predictor import predict_from_history

UTC=timezone.utc

def read_feed(root,now):
 market=Path(root)/'market';q=json.loads((market/'exness_quote.json').read_text());h=pd.read_csv(market/'exness_m15.csv',dtype={'symbol':str})
 if q.get('symbol')!='XAUUSD' or len(h)<100 or not h.symbol.eq('XAUUSD').all():raise ValueError('Wrong symbol or insufficient history')
 if int(q.get('server_minus_utc_seconds',999))!=0:raise ValueError('Server offset is not UTC')
 captured=pd.Timestamp(q['captured_utc_iso']);
 if captured.tzinfo is None or captured.utcoffset()!=timedelta(0):raise ValueError('Quote capture must be UTC')
 idx=pd.to_datetime(h.bar_open_server_time,format='%Y.%m.%d %H:%M:%S',utc=True,errors='raise')
 if idx.duplicated().any() or not idx.is_monotonic_increasing or (idx.dt.minute%15!=0).any() or (idx.dt.second!=0).any():raise ValueError('Invalid M15 timestamp sequence')
 flags=pd.to_numeric(h.is_current_bar,errors='raise').to_numpy()
 if not np.isin(flags,[0,1]).all() or flags.sum()!=1 or flags[-1]!=1:raise ValueError('Must have exactly one last current candle')
 bars=pd.DataFrame({k:pd.to_numeric(h[k+'_chart'],errors='raise').to_numpy() for k in ('open','high','low','close')},index=idx);bars['completed']=flags==0
 if not np.isfinite(bars[['open','high','low','close']].to_numpy()).all() or ((bars.low<=0)|(bars.high<bars[['open','close','low']].max(axis=1))|(bars.low>bars[['open','close','high']].min(axis=1))).any():raise ValueError('Invalid chart prices')
 bid,ask=float(q['bid']),float(q['ask']);
 if not np.isfinite([bid,ask]).all() or bid<=0 or ask<bid:raise ValueError('Invalid quote')
 age=(pd.Timestamp(now)-captured).total_seconds()
 fresh=bool(-10<=age<=120 and q.get('connected')=='1' and q.get('tick_change_observed')=='1' and 0<=int(q.get('seconds_since_observed_tick_change',-1))<=45 and -10<=int(q.get('tick_age_seconds',-999))<=60)
 if idx.iloc[-1]>captured+pd.Timedelta(seconds=10):raise ValueError('M15 history is ahead of quote')
 return q,captured,bars,fresh

def as_candles(bars):
 return [{'open':t.to_pydatetime(),'end':(t+pd.Timedelta(minutes=15)).to_pydatetime(),'completed':bool(r.completed),'close':float(r.close)} for t,r in bars.iterrows()]

def run(root,*,clock=lambda:datetime.now(UTC)):
 root=Path(root);now=clock();log=root/'market'/'four_hour_research_log.json';config=root/'market'/'verified_session_dates.json'
 try:
  q,captured,bars,fresh=read_feed(root,now)
  settings=json.loads(config.read_text()) if config.exists() else {}
  dates=set(settings.get('confirmed_utc_dates',[]))
  # Explicit opt-in to the screenshot's regular schedule; not live verification.
  # Holidays, seasonal broker changes and outages can invalidate this assumption.
  assumed=settings.get('assume_regular_screenshot_schedule') is True
  candles=as_candles(bars);store=ForecastStore(log)
  existing=store._read()
  scored=[]
  for key in existing['forecasts']:
   if key in existing['outcomes']:continue
   outcome=score_one(log,key,now,candles,schedule_confirmed_for_day=(key[:10] in dates or assumed))
   scored.append({'key':key,'status':outcome['status']})
  cut=captured.floor('15min')
  def predict(d,unused):return predict_from_history(bars,cut,d)
  result=issue_once(log,now,captured.to_pydatetime(),candles,fresh_snapshot=fresh,utc_server_verified=True,schedule_confirmed_for_day=(now.date().isoformat() in dates or assumed),predictor=predict,clock=clock)
  return {'status':result['status'],'decision':result,'scoring':scored,'quote_captured_at':captured.isoformat(),'snapshot_fresh':fresh,'schedule_mode':'screenshot schedule assumed, not verified live' if assumed else 'manual date confirmation','warning':'Research only. Calendar may be wrong on holidays or broker changes; chart prices do not prove fills.'}
 except Exception as e:
  return {'status':'unavailable: '+str(e),'warning':'No new forecast recorded from this failure. Check logs and input data.'}

if __name__=='__main__':
 from dashboard_snapshot import publish_snapshot
 root=Path(__file__).resolve().parent
 result=run(root)
 try:
  _,_,bars,_=read_feed(root,datetime.now(UTC))
 except Exception:bars=None
 publish_snapshot(root,result,datetime.now(UTC),bars)
 print(json.dumps(result,indent=2,allow_nan=False))
