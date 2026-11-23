#!/usr/bin/env python3
"""M15 rolling XAUUSD shadow forecasts, using completed bars only.
Revisions forecast 18:00 vs latest completed candle close. UTC server assumption.
"""
import json
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.metrics import accuracy_score,mean_absolute_error
ROOT=Path(__file__).resolve().parent; MARKET=ROOT/'market'; DOCS=ROOT/'docs'
MARKET.mkdir(exist_ok=True);DOCS.mkdir(exist_ok=True)
LOG=MARKET/'exness_rolling_log.json';OUTPUT=DOCS/'exness_rolling.json'
now=datetime.now(timezone.utc);today=now.date().isoformat()
log=json.load(LOG.open()) if LOG.exists() else []
out={'generated_at':now.isoformat(timespec='seconds').replace('+00:00','Z'),
     'status':'Waiting for M15 data', 'windows':{},'forecasts':log,
     'note':'Each revision predicts the 18:00 price relative to the latest available completed M15 candle close; the reference changes on later revisions. Estimates are experimental, not orders.',
     'warnings':['Uses broker server candle labels as UTC; historical alignment is supported by a preliminary audit, not guaranteed for all dates.',
                 'Observed tick activity does not guarantee the upstream quote is undelayed. GitHub Actions and uploader may miss updates.',
                 'The high/low estimates concern the remaining time to 18:00, not highs or lows already observed.',
                 'No trade execution, spread, slippage, commissions or financing are modeled.',
                 'Scenario zones are fixed ATR rules, not validated predictions. Touch tests use completed bid/chart candles after issue and cannot prove fills or intrabar order.',
                 'Each forecast is timestamped when generated. Backtests assume historical bars were available at their close and may be revised.']}
F=['r1','r4','r16','r48','vol32','range16','age_min','weekday']
def featurize(data,cut):
    # Only candles whose nominal close is no later than cut and are flagged complete.
    p=data[(data.index+pd.Timedelta(minutes=15)<=cut)&(data.completed)].tail(120)
    if len(p)<97:return None
    last=p.index[-1];age=(cut-(last+pd.Timedelta(minutes=15))).total_seconds()/60
    if age<0 or age>120:return None
    c=float(p.close.iloc[-1]); seq=p.close
    if c<=0:return None
    returns=seq.pct_change().dropna()
    x={'r1':(c/seq.iloc[-2]-1)*100,'r4':(c/seq.iloc[-5]-1)*100,
       'r16':(c/seq.iloc[-17]-1)*100,'r48':(c/seq.iloc[-49]-1)*100,
       'vol32':float(returns.tail(32).std()*100),
       'range16':(float(p.high.tail(16).max())-float(p.low.tail(16).min()))/c*100,
       'age_min':age,'weekday':cut.weekday()}
    if not np.isfinite(list(x.values())).all():return None
    return {'reference_price':c,'last_bar_open':last.isoformat(),'last_bar_end':(last+pd.Timedelta(minutes=15)).isoformat(),**x}

def build_scenario(data, cut, prediction, features):
    """Fixed, unoptimized ATR(14) scenario rules; NOT a trade signal."""
    p = float(prediction['p_up']); ref = float(features['reference_price'])
    closed = data[(data.index + pd.Timedelta(minutes=15) <= cut) & data.completed].tail(15)
    if len(closed) < 15 or any(closed.index.to_series().diff().iloc[1:] != pd.Timedelta(minutes=15)):
        return {'available': False, 'reason': 'Need 15 consecutive completed M15 candles for volatility.'}
    prev = closed.close.shift(1)
    tr = pd.concat([closed.high-closed.low, (closed.high-prev).abs(), (closed.low-prev).abs()], axis=1).max(axis=1)
    atr = float(tr.iloc[-14:].mean())
    if not np.isfinite(atr) or atr <= 0:
        return {'available': False, 'reason': 'Recent volatility unavailable.'}
    end = float(prediction['estimated_end'])
    if .45 < p < .55:
        return {'available': False, 'reason': 'Model direction is near neutral (45–55% up); no directional scenario.'}
    side = 'up' if p >= .55 else 'down'
    if (side == 'up' and end <= ref) or (side == 'down' and end >= ref):
        return {'available': False, 'reason': 'Direction and 18:00 price estimate disagree; no directional scenario.'}
    # Rules are intentionally simple and uncalibrated. Zones express possible
    # pullback/bounce areas relative to reference, not estimated model-probabilities.
    if side == 'up':
        a = [ref-.50*atr, ref-.25*atr]; c = [ref-1.00*atr, ref-.75*atr]
        inv = ref-1.50*atr; extreme = float(prediction['estimated_high_remaining'])
    else:
        a = [ref+.25*atr, ref+.50*atr]; c = [ref+.75*atr, ref+1.00*atr]
        inv = ref+1.50*atr; extreme = float(prediction['estimated_low_remaining'])
    return {'available': True, 'side': side, 'basis': 'uncalibrated fixed fractions of M15 ATR(14)',
            'atr_m15': round(atr,3), 'aggressive_zone': [round(v,3) for v in a],
            'conservative_zone': [round(v,3) for v in c], 'invalidation': round(inv,3),
            'estimated_18_end': round(end,3), 'estimated_extreme': round(extreme,3),
            'warning': 'Price-level scenario only; no execution, ordering, spread, timing or profitability guaranteed.'}

def evaluate_scenario(entry, bars, current_time):
    """Track proxy touches after issue, conservatively treat same-bar order as unknown."""
    scenario = entry.get('scenario') or {}
    if not scenario.get('available'): return None
    issue=pd.Timestamp(entry['issued_at']);end=pd.Timestamp(entry['date'],tz='UTC')+pd.Timedelta(hours=18)
    # Ignore the candle containing issue: high/low includes pre-forecast activity.
    first=issue.ceil('15min');last=min(pd.Timestamp(current_time).floor('15min'),end)
    if first>=end: return {'status':'no full candles after issue before window end'}
    expected=pd.date_range(first,last-pd.Timedelta(minutes=15),freq='15min') if last>first else pd.DatetimeIndex([],tz='UTC')
    h=bars.reindex(expected)
    if len(expected) and (h[['high','low','completed']].isna().any().any() or not h.completed.all()):
        return {'status':'insufficient complete bars after issue; ordering unknown'}
    def zone_result(zone):
        touched=False; t_touch=None; outcome='not touched' if last>=end else 'waiting for zone';target=scenario['estimated_18_end'];invalid=scenario['invalidation']
        for dt,row in h.iterrows():
            low,high=float(row.low),float(row.high)
            if not touched:
                if low<=zone[1] and high>=zone[0]:
                    touched=True;t_touch=dt.isoformat();outcome='zone touched; waiting'
                    if low<=target<=high or low<=invalid<=high:
                        outcome='ambiguous: zone and target/invalidation in same candle';break
                continue
            hit_t=low<=target<=high;hit_i=low<=invalid<=high
            if hit_t and hit_i:outcome='ambiguous: target and invalidation in same candle';break
            if hit_t:outcome='target touched after zone';break
            if hit_i:outcome='invalidation touched after zone';break
        if touched and outcome=='zone touched; waiting' and last>=end:outcome='zone touched; neither level observed by 18:00'
        return {'status':outcome,'first_touch_bar':t_touch}
    return {'status':'proxy only; not evidence of executable fills',
            'aggressive':zone_result(scenario['aggressive_zone']),
            'conservative':zone_result(scenario['conservative_zone'])}

def make_dataset(data,decision_hour,decision_minute):
    rows=[]
    for dt in sorted(set(data.index.date)):
        day=pd.Timestamp(dt,tz='UTC');cut=day+pd.Timedelta(hours=decision_hour,minutes=decision_minute);end=day+pd.Timedelta(hours=18)
        if cut>=end:continue
        features=featurize(data,cut)
        if features is None:continue
        # Supervision only if the 18:00 bar open exists and every 15m bar in
        # the remaining window has a complete high and low.
        if end not in data.index:continue
        expected=pd.date_range(cut,end-pd.Timedelta(minutes=15),freq='15min')
        seq=data.reindex(expected)
        if seq[['high','low','completed']].isna().any().any() or not seq.completed.all():continue
        close18=float(data.loc[end,'open']);start=features['reference_price']
        if close18<=0 or close18==start:continue
        rows.append({'date':dt.isoformat(),**features,'end':close18,'target':int(close18>start),
                     'return_pct':(close18/start-1)*100,
                     'high':max(start,close18,float(seq.high.max())),
                     'low':min(start,close18,float(seq.low.min()))})
    return pd.DataFrame(rows)

def model(train,features):
    X=train[F];x=pd.DataFrame([features])[F]
    clf=make_pipeline(StandardScaler(),LogisticRegression(C=.5,max_iter=1000)).fit(X,train.target)
    end=make_pipeline(StandardScaler(),Ridge(alpha=50)).fit(X,train.return_pct)
    hi=make_pipeline(StandardScaler(),Ridge(alpha=50)).fit(X,(train.high/train.reference_price-1)*100)
    lo=make_pipeline(StandardScaler(),Ridge(alpha=50)).fit(X,(1-train.low/train.reference_price)*100)
    p=float(clf.predict_proba(x)[0,1]); ref=float(features['reference_price'])
    return {'p_up':round(p,4),'direction':'up' if p>=.5 else 'down',
            'estimated_end':round(ref*(1+float(end.predict(x)[0])/100),3),
            'estimated_high_remaining':round(ref*(1+max(0,float(hi.predict(x)[0]))/100),3),
            'estimated_low_remaining':round(ref*(1-max(0,float(lo.predict(x)[0]))/100),3)}

def test(data):
    if len(data)<50:return {'status':'insufficient complete days','n':0}
    cut=max(40,int(len(data)*.8));result=[]
    for i in range(cut,len(data)):
        tr=data.iloc[:i];te=data.iloc[i]
        if tr.target.nunique()<2:continue
        p=model(tr,te.to_dict())
        result.append((int(te.target),p['p_up'],float(te['end']),p['estimated_end'],float(te.reference_price),float(te.high),p['estimated_high_remaining'],float(te.low),p['estimated_low_remaining']))
    if not result:return {'status':'insufficient varied targets','n':0}
    a=np.array(result)
    return {'status':'exploratory holdout','n':len(a),'direction_accuracy':round(float(accuracy_score(a[:,0],a[:,1]>=.5)),4),
            'always_up':round(float(a[:,0].mean()),4),'always_down':round(float(1-a[:,0].mean()),4),
            'end_mae':round(float(mean_absolute_error(a[:,2],a[:,3])),2),'unchanged_mae':round(float(mean_absolute_error(a[:,2],a[:,4])),2),
            'high_mae':round(float(mean_absolute_error(a[:,5],a[:,6])),2),'low_mae':round(float(mean_absolute_error(a[:,7],a[:,8])),2)}
try:
    quote=json.load((MARKET/'exness_quote.json').open());h=pd.read_csv(MARKET/'exness_m15.csv',dtype={'symbol':str})
    if quote.get('symbol')!='XAUUSD' or not h.symbol.eq('XAUUSD').all():raise ValueError('Wrong symbol')
    if int(quote.get('server_minus_utc_seconds',999))!=0:raise ValueError('Current broker server offset is not UTC')
    if len(h)<100 or h.is_current_bar.astype(int).sum()!=1 or int(h.is_current_bar.iloc[-1])!=1:raise ValueError('Missing current M15 candle or insufficient history')
    idx=pd.to_datetime(h.bar_open_server_time,format='%Y.%m.%d %H:%M:%S',utc=True,errors='raise')
    if idx.duplicated().any() or not idx.is_monotonic_increasing:raise ValueError('M15 timestamps are duplicated or unordered')
    if any((idx.dt.minute%15)!=0):raise ValueError('M15 bar timestamps not quarter-hour aligned')
    bars=pd.DataFrame({k:pd.to_numeric(h[k+'_chart']).to_numpy() for k in ('open','high','low','close')},index=idx)
    bars['completed']=h.is_current_bar.astype(int).to_numpy()==0
    if ((bars.low<=0)|(bars.high<bars[['open','close','low']].max(axis=1))|(bars.low>bars[['open','close','high']].min(axis=1))).any():raise ValueError('Invalid M15 OHLC values')
    captured=pd.Timestamp(quote['captured_utc_iso']); age=(pd.Timestamp(now)-captured).total_seconds()
    fresh=bool(-10<=age<=120 and quote.get('connected')=='1' and quote.get('tick_change_observed')=='1' and 0<=int(quote.get('seconds_since_observed_tick_change',-1))<=45 and -10<=int(quote.get('tick_age_seconds',-999))<=60)
    out['source']={'captured_at':quote['captured_utc_iso'],'quote_age_seconds_at_run':round(age),'bid':float(quote['bid']),'ask':float(quote['ask']),'fresh_at_run':fresh,'m15_rows':len(h)}
    # Score revisions using eventual 18:00 bar, retaining original reference.
    for entry in log:
        if entry.get('actual') is not None:continue
        end=pd.Timestamp(entry['date'],tz='UTC')+pd.Timedelta(hours=18)
        if end not in bars.index:continue
        price=float(bars.loc[end,'open']);ref=entry['reference_price'];actual='up' if price>ref else 'down' if price<ref else 'flat'
        entry.update(actual=actual,actual_end=round(price,3),correct=(actual==entry['direction']) if actual!='flat' else None)
    for entry in log:
        if entry.get('scenario', {}).get('available'):
            entry['scenario_tracking'] = evaluate_scenario(entry, bars, now)
    cut=captured.floor('15min');remaining=(cut.hour<18 and now.hour<18 and cut.date()==now.date())
    for window,start in [('morning',8),('afternoon',13)]:
        if now.weekday()>=5 or now.hour<start or not remaining:
            out['windows'][window]={'status':'outside active forecast window'};continue
        if not fresh:
            out['windows'][window]={'status':'waiting: Exness snapshot stale or inactive'};continue
        if cut.hour<start:
            out['windows'][window]={'status':'waiting: quote predates window'};continue
        features=featurize(bars,cut)
        if features is None:
            out['windows'][window]={'status':'waiting: completed candle missing or more than 120 minutes old'};continue
        train=make_dataset(bars,cut.hour,cut.minute)
        if len(train):train=train[train.date<today]
        if len(train)<50 or train.target.nunique()<2:
            out['windows'][window]={'status':f'insufficient training history: {len(train)} matching completed days'};continue
        metrics=test(train)
        entry=next((e for e in log if e.get('date')==today and e.get('window')==window and e.get('decision_cutoff')==cut.isoformat()),None)
        if entry is None:
            p=model(train,features); scenario=build_scenario(bars,cut,p,features); issued=datetime.now(timezone.utc)
            if issued.date()!=now.date() or issued.hour>=18:
                out['windows'][window]={'status':'window closed before forecast finished'};continue
            entry={'date':today,'window':window,'decision_cutoff':cut.isoformat(),
                   'issued_at':issued.isoformat(timespec='seconds').replace('+00:00','Z'),
                   'source_captured_at':quote['captured_utc_iso'],'model':'exness-m15-rolling-v1',
                   'reference_price':round(features['reference_price'],3),
                   'reference_bar_open':features['last_bar_open'],'reference_bar_end':features['last_bar_end'],
                   'reference_age_minutes':features['age_min'],'training_days':len(train),**p,'scenario':scenario,'actual':None}
            log.append(entry);status='new revision recorded'
        else:status='revision already recorded; waiting for another completed candle'
        out['windows'][window]={'status':status,'validation':metrics,'latest':entry}
    out['status']='validated M15 snapshot' if fresh else 'snapshot stale or inactive; no forecast updates'
except FileNotFoundError:
    out['status']='Waiting for Exness M15 data; check exporter and uploader.'
except Exception as e:
    out['status']='M15 forecast unavailable: '+str(e)
with LOG.open('w') as f:json.dump(log,f,indent=2,allow_nan=False)
out['forecasts']=log
with OUTPUT.open('w') as f:json.dump(out,f,indent=2,allow_nan=False)
print(json.dumps({'status':out['status'],'windows':{k:v['status'] for k,v in out['windows'].items()},'forecast_count':len(log)},indent=2))
