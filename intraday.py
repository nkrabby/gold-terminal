#!/usr/bin/env python3
"""Two point-in-time intraday research forecasts. UTC = Accra time.
GC=F hourly bar opens are indicative futures proxies, not executable spot prices.
"""
import json, os, urllib.request
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import accuracy_score, brier_score_loss, mean_absolute_error

ROOT = os.path.dirname(os.path.abspath(__file__))
NOW = datetime.now(timezone.utc)
URL = 'https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?range=730d&interval=1h'
req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=35) as r:
    result = json.load(r)['chart']['result'][0]
q = result['indicators']['quote'][0]
source_epoch = result.get('meta', {}).get('regularMarketTime')
source_time = datetime.fromtimestamp(source_epoch, timezone.utc) if source_epoch else None
bars = pd.DataFrame({k: q[k] for k in ('open', 'high', 'low', 'close')},
                    index=pd.to_datetime(result['timestamp'], unit='s', utc=True)).sort_index()
bars = bars[~bars.index.duplicated(keep='first')]
bars = bars[(bars.index.minute == 0) & (bars.index.second == 0)]
bars = bars[bars.index <= pd.Timestamp(NOW)]
FEATURES = ['ret_1h', 'ret_4h', 'ret_12h', 'ret_24h', 'vol_24h', 'range_12h', 'dist_24h', 'weekday']
WINDOWS = {'morning': {'start': 8, 'end': 18}, 'afternoon': {'start': 13, 'end': 18}}

def dataset(start, end, anchor="bar_open"):
    rows = []
    for date in sorted(set(bars.index.date)):
        day = pd.Timestamp(date, tz='UTC')
        instant, endtime = day + pd.Timedelta(hours=start), day + pd.Timedelta(hours=end)
        if anchor == 'bar_open' and (instant not in bars.index or pd.isna(bars.loc[instant, 'open'])):
            continue
        # The current hourly bar contributes its open only. All OHLC information
        # used in features comes from hourly bars ending no later than start.
        past = bars.loc[bars.index < instant].dropna(subset=['high', 'low', 'close']).tail(72)
        if len(past) < 50 or (anchor == 'bar_open' and past.index[-1] != instant - pd.Timedelta(hours=1)):
            continue
        p = float(past.close.iloc[-1]) if anchor == 'prior_close' else float(bars.loc[instant, 'open'])
        if not np.isfinite(p) or p <= 0: continue
        def ret(n):
            # With a prior-close anchor, compare to an earlier close rather than
            # dividing the reference by itself (which would make ret_1h zero).
            lag = -(n+1) if anchor == 'prior_close' else -n
            return float((p / past['close'].iloc[lag] - 1) * 100)
        returns = past['close'].pct_change().dropna()
        f = {'ret_1h': ret(1), 'ret_4h': ret(4), 'ret_12h': ret(12), 'ret_24h': ret(24),
             'vol_24h': float(returns.tail(24).std() * 100),
             'range_12h': float((past['high'].tail(12).max() - past['low'].tail(12).min()) / p * 100),
             'dist_24h': float((p / past['close'].tail(24).mean() - 1) * 100),
             'weekday': float(day.weekday())}
        if not all(np.isfinite(list(f.values()))): continue
        endprice = float(bars.loc[endtime, 'open']) if endtime in bars.index and pd.notna(bars.loc[endtime, 'open']) else np.nan
        if np.isfinite(endprice) and endprice == p: continue # exact flat outcomes excluded from binary test
        # Require every hourly bar to have completed and an 18:00 open to exist;
        # partial intraday high/low must never become a training label.
        hours = pd.date_range(instant, endtime - pd.Timedelta(hours=1), freq='1h')
        span = bars.reindex(hours)
        if np.isfinite(endprice) and span[['high', 'low']].notna().all().all():
            session_high = max(p, endprice, float(span.high.max()))
            session_low = min(p, endprice, float(span.low.min()))
        else:
            session_high = session_low = np.nan
        rows.append({'date': date.isoformat(), 'start_price': p, 'end_price': endprice,
                     'session_high': session_high, 'session_low': session_low, 'reference_bar_end': (past.index[-1] + pd.Timedelta(hours=1)).isoformat(), **f})
    df = pd.DataFrame(rows).set_index('date')
    df['return_pct'] = (df.end_price / df.start_price - 1) * 100
    df['target'] = np.where(df.return_pct.notna(), (df.return_pct > 0).astype(int), np.nan)
    return df

def fit(train):
    direction = make_pipeline(StandardScaler(), LogisticRegression(C=.5, max_iter=1000))
    value = make_pipeline(StandardScaler(), Ridge(alpha=50.0))
    direction.fit(train[FEATURES], train.target.astype(int))
    value.fit(train[FEATURES], train.return_pct)
    return direction, value

def prediction(train, test):
    direction, value = fit(train)
    prob = float(direction.predict_proba(test[FEATURES])[0, 1])
    change = float(value.predict(test[FEATURES])[0])
    start = float(test.start_price.iloc[0])
    # Historical unconditional return percentiles, not a calibrated prediction interval.
    lo, hi = np.quantile(train.return_pct, [.10, .90])
    return {'p_up': round(prob, 4), 'direction': 'up' if prob >= .5 else 'down',
            'start_price': round(start, 2), 'predicted_return_pct': round(change, 4),
            'estimated_end': round(start * (1 + change / 100), 2),
            'historical_range': [round(start * (1 + lo / 100), 2), round(start * (1 + hi / 100), 2)]}

def extreme_prediction(train, test):
    """Estimate window extremes as percent distances, using only completed days."""
    valid = train.dropna(subset=['session_high', 'session_low']).copy()
    if len(valid) < 120:
        return None
    hi = (valid.session_high / valid.start_price - 1) * 100
    lo = (1 - valid.session_low / valid.start_price) * 100
    high_model = make_pipeline(StandardScaler(), Ridge(alpha=50.0)).fit(valid[FEATURES], hi)
    low_model = make_pipeline(StandardScaler(), Ridge(alpha=50.0)).fit(valid[FEATURES], lo)
    start = float(test.start_price.iloc[0])
    high_pct = max(0.0, float(high_model.predict(test[FEATURES])[0]))
    low_pct = max(0.0, float(low_model.predict(test[FEATURES])[0]))
    return {'estimated_window_high': round(start * (1 + high_pct / 100), 2),
            'estimated_window_low': round(start * (1 - low_pct / 100), 2),
            'baseline_high': round(start * (1 + float(hi.median()) / 100), 2),
            'baseline_low': round(start * (1 - float(lo.median()) / 100), 2)}

def evaluate_extremes(complete):
    """Same chronological split; earlier days only, compare median-excursion baseline."""
    cut = int(len(complete) * .8); records = []
    for i in range(cut, len(complete)):
        train, test = complete.iloc[:i], complete.iloc[[i]]
        if pd.isna(test.session_high.iloc[0]) or pd.isna(test.session_low.iloc[0]): continue
        est = extreme_prediction(train, test)
        if est is None: continue
        records.append({**est, 'date': test.index[0],
                        'actual_high': float(test.session_high.iloc[0]),
                        'actual_low': float(test.session_low.iloc[0])})
    if not records: return {'n': 0}
    def error(pred, actual):
        return round(float(np.mean([abs(r[pred] - r[actual]) for r in records])), 2)
    return {'n': len(records), 'first_date': records[0]['date'], 'last_date': records[-1]['date'],
            'high_mae': error('estimated_window_high', 'actual_high'),
            'high_baseline_mae': error('baseline_high', 'actual_high'),
            'low_mae': error('estimated_window_low', 'actual_low'),
            'low_baseline_mae': error('baseline_low', 'actual_low')}

def evaluate(complete):
    if len(complete) < 160: raise RuntimeError('Insufficient hourly history')
    cut = int(len(complete) * .8); preds = []
    for i in range(cut, len(complete)):
        train = complete.iloc[:i]; test = complete.iloc[[i]]
        if train.target.nunique() < 2: continue
        p = prediction(train, test); actual = int(test.target.iloc[0])
        preds.append({'date': test.index[0], 'p_up': p['p_up'], 'actual': actual,
                      'estimated_end': p['estimated_end'], 'actual_end': round(float(test.end_price.iloc[0]), 2),
                      'start_price': p['start_price'], 'range_low': p['historical_range'][0],
                      'range_high': p['historical_range'][1]})
    a = np.array([p['actual'] for p in preds]); prob = np.array([p['p_up'] for p in preds])
    estimates = np.array([p['estimated_end'] for p in preds]); ends = np.array([p['actual_end'] for p in preds]); starts = np.array([p['start_price'] for p in preds])
    coverage = np.mean([p['range_low'] <= p['actual_end'] <= p['range_high'] for p in preds])
    return {'n': len(a), 'accuracy': round(float(accuracy_score(a, prob >= .5)), 4),
            'always_up': round(float(a.mean()), 4), 'always_down': round(float(1-a.mean()), 4),
            'brier': round(float(brier_score_loss(a, prob)), 4),
            'endpoint_mae_usd': round(float(mean_absolute_error(ends, estimates)), 2),
            'unchanged_price_mae_usd': round(float(mean_absolute_error(ends, starts)), 2),
            'historical_range_coverage': round(float(coverage), 4),
            'holdout_start': preds[0]['date'], 'holdout_end': preds[-1]['date']}, preds

logpath = os.path.join(ROOT, 'forecast_log.json')
if os.path.exists(logpath):
    with open(logpath) as f: log = json.load(f)
else:
    log = []
today = NOW.date().isoformat(); windows = {}
for name, config in WINDOWS.items():
    start, end = config['start'], config['end']
    # Keep bar-open datasets for existing v2 records and research imports.
    legacy = dataset(start, end); legacy_complete = legacy.dropna(subset=['target']).copy()
    historical = dataset(start, end, anchor='prior_close'); complete = historical.dropna(subset=['target']).copy()
    metrics, backtest = evaluate(complete)
    extreme_metrics = evaluate_extremes(complete)
    for entry in log:
        if entry.get('window') != name or entry.get('actual') is not None: continue
        if entry.get('model') == 'intraday-v2' and entry['date'] in legacy_complete.index:
            row = legacy_complete.loc[entry['date']]
            actual = 'up' if row.target else 'down'
            entry.update(actual=actual, actual_start=round(float(row.start_price),2),
                         actual_end=round(float(row.end_price),2),return_pct=round(float(row.return_pct),4),
                         correct=entry['direction']==actual)
        elif entry.get('model') in ('intraday-v3','intraday-v4'):
            endpoint = pd.Timestamp(entry['date'],tz='UTC')+pd.Timedelta(hours=end)
            # Never assume the endpoint before it has occurred or backfill a forecast.
            if pd.Timestamp(NOW)>=endpoint and source_time and pd.Timestamp(source_time)>=endpoint and endpoint in bars.index and pd.notna(bars.loc[endpoint,'open']):
                actual_price=float(bars.loc[endpoint,'open']);ref=float(entry['start_price'])
                actual='up' if actual_price>ref else 'down' if actual_price<ref else 'flat'
                entry.update(actual=actual,actual_end=round(actual_price,2),return_pct=round((actual_price/ref-1)*100,4),
                             correct=(entry['direction']==actual) if actual!='flat' else None,
                             endpoint_error_usd=round(abs(float(entry['estimated_end'])-actual_price),2),
                             unchanged_error_usd=round(abs(ref-actual_price),2))
    # Preserve legacy v2 high/low outcome scoring. For v4, highs/lows are
    # historical whole-decision-hour estimates, not guaranteed post-issue paths.
    for entry in log:
        if entry.get('model')!='intraday-v2' or entry.get('window')!=name: continue
        if 'estimated_window_high' not in entry or entry.get('actual_window_high') is not None or entry['date'] not in legacy_complete.index: continue
        row=legacy_complete.loc[entry['date']]
        if pd.notna(row.session_high) and pd.notna(row.session_low):
            entry.update(actual_window_high=round(float(row.session_high),2),actual_window_low=round(float(row.session_low),2),
                         high_error_usd=round(abs(entry['estimated_window_high']-row.session_high),2),
                         low_error_usd=round(abs(entry['estimated_window_low']-row.session_low),2))
    status='outside forecast window'
    existing=any(e.get('date')==today and e.get('window')==name and e.get('model') in ('intraday-v2','intraday-v3','intraday-v4') for e in log)
    if existing: status='forecast already recorded'
    elif NOW.weekday()<5 and start<=NOW.hour<end:
        age=(NOW-source_time).total_seconds() if source_time else None
        cutoff=NOW.replace(hour=start,minute=0,second=0,microsecond=0)
        source_ok=bool(source_time and source_time>=cutoff and -30<=age<=1200)
        if not source_ok:status='waiting for a recent Yahoo source timestamp; never assume candle finality'
        else:
            decision_hour=NOW.hour
            actual_data=dataset(decision_hour,end,anchor='prior_close')
            training=actual_data.dropna(subset=['target']);training=training[training.index<today]
            if today not in actual_data.index: status='no usable completed reference candle or history'
            elif len(training)<120 or training.target.nunique()<2:status='insufficient matching completed training days'
            else:
                row=actual_data.loc[[today]];p=prediction(training,row);extremes=extreme_prediction(training,row)
                if extremes:p.update(extremes)
                issued=datetime.now(timezone.utc)
                if issued.date()!=NOW.date() or issued.hour!=decision_hour or issued.hour>=end or (issued-source_time).total_seconds()>1200:
                    status='calculation finished after cutoff or quote became stale; retry next run'
                else:
                    ref_end=pd.Timestamp(row.reference_bar_end.iloc[0]);ref_age=round((pd.Timestamp(issued)-ref_end).total_seconds()/60,1)
                    log.append({'date':today,'window':name,'issued_at':issued.isoformat(timespec='seconds').replace('+00:00','Z'),
                                'feature_cutoff_utc':f'{decision_hour:02d}:00','model':'intraday-v4','anchor':'latest available completed hourly close at cutoff',
                                'reference_bar_end':ref_end.isoformat(),'reference_age_minutes':ref_age,'source_quote_time':source_time.isoformat(),'source_quote_age_minutes':round((issued-source_time).total_seconds()/60,1),
                                'training_n':len(training),**p,'actual':None})
                    status='forecast recorded; later updates do not revise this entry'
    windows[name]={'start_utc':f'{start:02d}:00','end_utc':f'{end:02d}:00','history_days':len(complete),
                   'validation':metrics,'extremes_validation':extreme_metrics,'validation_predictions':backtest,'status':status}
with open(logpath, 'w') as f: json.dump(log, f, indent=2, allow_nan=False)
out = {'generated_at': NOW.isoformat(timespec='seconds').replace('+00:00','Z'),
       'source': 'Yahoo Finance GC=F hourly futures; completed hourly close reference; endpoint 18:00 bar open',
       'source_quote_time': source_time.isoformat() if source_time else None,
       'last_data_bar_utc': bars.index[-1].isoformat(), 'windows': windows,
       'forecasts': [e for e in log if e.get('model') in ('intraday-v2','intraday-v3','intraday-v4')],
       'limitations': ['Quotes can be delayed, revised or missing. Futures prices differ from broker XAU/USD.',
                       'Estimated endpoint and window extrema are separate regressions from the directional classifier and may disagree.',
                       'Extrema are illustrative estimates, not guarantees, resistance/support, turning times, or trade instructions.',
                       'Historical 10th–90th return range is unconditional, not a calibrated prediction interval.',
                       'Accuracy and endpoint MAE are historical holdout results; no spread, slippage or trading costs.',
                       'Backtest assumes historical candle closes were available at their nominal close. Live data may be delayed or revised.',
                       'Forecast may issue later in the window without backdating. Reference can be old; past movement and the ongoing candle may precede issuance.',
                       'Freshness of source quote does not guarantee the latest historical candle is final.',
                       'Exness forecasts may use different endpoint times and symbols; those results are not a direct head-to-head comparison.']}
with open(os.path.join(ROOT, 'docs', 'intraday.json'), 'w') as f: json.dump(out, f, indent=2, allow_nan=False)
print(json.dumps({'generated_at':out['generated_at'],'windows':{k:v['validation'] for k,v in windows.items()},'forecast_count':len(out['forecasts'])}, indent=2))
