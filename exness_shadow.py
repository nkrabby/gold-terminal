#!/usr/bin/env python3
"""Independent Exness XAUUSD shadow forecasts; no trades and no credentials.
Consumes market files uploaded by the user's Mac. Assumes verified UTC server
labels for this sample. Does not replace Yahoo forecasts.
"""
import ast, json
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, brier_score_loss, mean_absolute_error

ROOT=Path(__file__).resolve().parent
NOW=datetime.now(timezone.utc)
INPUT=ROOT/'market'; OUT=ROOT/'docs'/'exness_shadow.json'; LOG=INPUT/'exness_shadow_log.json'
INPUT.mkdir(exist_ok=True);OUT.parent.mkdir(exist_ok=True)
if LOG.exists():
    with LOG.open() as f: log=json.load(f)
else: log=[]
result={'generated_at':NOW.isoformat(timespec='seconds').replace('+00:00','Z'),
        'mode':'shadow — educational; no orders and no model promotion',
        'status':'No validated Exness market snapshot available', 'windows':{}, 'forecasts':log,
        'warnings':['Times assume broker historical server timestamps were UTC. Prior sample supported this, but it is not proven for all dates.',
                    'Feed change observed is not proof of no upstream delays. Past candles may be revised.',
                    'An actual forecast may be issued after the reference candle close and no fill at that close is assumed.',
                    'Model predictions are experimental; spread, slippage, commission and financing are not included.']}
try:
    with (INPUT/'exness_quote.json').open() as f: quote=json.load(f)
    h=pd.read_csv(INPUT/'exness_h1.csv',dtype={'symbol':str})
    if quote.get('symbol')!='XAUUSD' or not (h['symbol']=='XAUUSD').all(): raise ValueError('Wrong symbol in quote or history')
    if int(quote.get('server_minus_utc_seconds',99999))!=0: raise ValueError('Current broker server offset is not UTC; historical time mapping requires review')
    if len(h)<160 or h['is_current_bar'].astype(int).sum()!=1 or int(h['is_current_bar'].iloc[-1])!=1: raise ValueError('History missing current candle or too short')
    idx=pd.to_datetime(h['bar_open_server_time'],format='%Y.%m.%d %H:%M:%S',utc=True,errors='raise')
    if idx.duplicated().any() or not idx.is_monotonic_increasing: raise ValueError('History timestamps are duplicated or unordered')
    bars=pd.DataFrame({k:pd.to_numeric(h[k+'_chart']).to_numpy() for k in ('open','high','low','close')},index=idx)
    if ((bars['low']<=0) | (bars['high']<bars[['open','close','low']].max(axis=1)) | (bars['low']>bars[['open','close','high']].min(axis=1))).any(): raise ValueError('Invalid OHLC prices')
    source_time=pd.Timestamp(quote['captured_utc_iso'])
    if source_time.tzinfo is None: raise ValueError('Quote timestamp missing timezone')
    quote_age=(pd.Timestamp(NOW)-source_time).total_seconds()
    fresh=bool(-10<=quote_age<=120 and quote.get('connected')=='1' and quote.get('tick_change_observed')=='1' and 0<=int(quote.get('seconds_since_observed_tick_change',-1))<=45 and -10<=int(quote.get('tick_age_seconds',-999))<=60)
    result['source']={'symbol':'XAUUSD','captured_at':quote['captured_utc_iso'], 'quote_age_seconds_at_run':round(quote_age),
                      'bid':float(quote['bid']),'ask':float(quote['ask']), 'fresh_at_run':fresh, 'history_rows':len(h)}
    # Reuse the same model code; extract pure functions instead of importing and
    # executing the Yahoo refresh. Bars are broker-server H1, assumed UTC.
    tree=ast.parse((ROOT/'shadow_core.py').read_text())
    names={'dataset','fit','prediction','extreme_prediction','evaluate','evaluate_extremes'}
    funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    features=['ret_1h','ret_4h','ret_12h','ret_24h','vol_24h','range_12h','dist_24h','weekday']
    env={'pd':pd,'np':np,'bars':bars,'FEATURES':features,'make_pipeline':make_pipeline,'StandardScaler':StandardScaler,
         'LogisticRegression':LogisticRegression,'Ridge':Ridge,'accuracy_score':accuracy_score,
         'brier_score_loss':brier_score_loss,'mean_absolute_error':mean_absolute_error}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),'shadow_core.py','exec'),env)
    for name,start in [('morning',8),('afternoon',13)]:
        data=env['dataset'](start,18,anchor='prior_close');complete=data.dropna(subset=['target']).copy()
        metrics,_=env['evaluate'](complete); extrema=env['evaluate_extremes'](complete)
        for entry in log:
            if entry.get('window')!=name or entry.get('actual') is not None or entry['date'] not in complete.index: continue
            row=complete.loc[entry['date']]
            # Score against the originally recorded anchor, not a revised close.
            actual='up' if float(row.end_price)>float(entry['start_price']) else ('down' if float(row.end_price)<float(entry['start_price']) else 'flat')
            entry.update(actual=actual,actual_end=round(float(row.end_price),3),correct=(actual==entry['direction']) if actual!='flat' else None)
            if pd.notna(row.session_high) and pd.notna(row.session_low):
                entry.update(actual_window_high=round(float(row.session_high),3),actual_window_low=round(float(row.session_low),3))
        today=NOW.date().isoformat();entry=next((e for e in log if e['date']==today and e['window']==name),None)
        status='already recorded' if entry else 'not recorded for today'
        cutoff=NOW.replace(hour=start,minute=0,second=0,microsecond=0)
        if not entry and NOW.hour==start and NOW.minute<=10:
            if not fresh: status='not recorded: Exness snapshot is stale or inactive'
            elif source_time.to_pydatetime()<cutoff: status='not recorded: quote predates forecast window'
            elif today not in data.index: status='not recorded: prior completed hour is unavailable'
            elif idx.iloc[-1] < pd.Timestamp(cutoff): status='not recorded: history export has not rolled into current hour'
            else:
                train=complete[complete.index<today]
                if len(train)<160 or train.target.nunique()<2: status='not recorded: insufficient training history'
                else:
                    p=env['prediction'](train,data.loc[[today]]); ex=env['extreme_prediction'](train,data.loc[[today]])
                    if ex: p.update(ex)
                    issued=datetime.now(timezone.utc)
                    if issued.date()!=NOW.date() or issued.hour!=start or issued.minute>10:
                        status='not recorded: computation completed after the cutoff'
                    else:
                        entry={'model':'exness-shadow-v1','date':today,'window':name,
                               'issued_at':issued.isoformat(timespec='seconds').replace('+00:00','Z'),
                               'source_captured_at':quote['captured_utc_iso'],'quote_bid_at_capture':float(quote['bid']),
                               'quote_ask_at_capture':float(quote['ask']),'anchor':'previous completed broker H1 close',
                               'training_n':len(train),**p,'actual':None}
                        log.append(entry);status='forecast recorded'
        elif not entry and NOW.weekday()<5 and (NOW.hour>start or (NOW.hour==start and NOW.minute>10)):
            status='missed: no forecast recorded before the cutoff'
        result['windows'][name]={'start_utc':f'{start:02d}:00','end_utc':'18:00','status':status,
                                 'history_days':len(complete),'validation':metrics,'extremes_validation':extrema}
    result['status']='Data validated; fresh' if fresh else 'Data validated, but snapshot is stale or inactive; no new forecast will be recorded'
except Exception as e:
    result['status']='No usable Exness data: '+str(e)
# Always keep the saved log, including during data outages. Use JSON only.
with LOG.open('w') as f: json.dump(log,f,indent=2,allow_nan=False)
result['forecasts']=log
with OUT.open('w') as f: json.dump(result,f,indent=2,allow_nan=False)
print(json.dumps({'generated_at':result['generated_at'],'status':result['status'],
                  'windows':{k:v['status'] for k,v in result['windows'].items()},'forecast_count':len(log)},indent=2))
