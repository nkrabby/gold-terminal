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
bars = pd.DataFrame({k: q[k] for k in ('open', 'high', 'low', 'close')},
                    index=pd.to_datetime(result['timestamp'], unit='s', utc=True)).sort_index()
bars = bars[~bars.index.duplicated(keep='first')]
bars = bars[(bars.index.minute == 0) & (bars.index.second == 0)]
bars = bars[bars.index <= pd.Timestamp(NOW)]
FEATURES = ['ret_1h', 'ret_4h', 'ret_12h', 'ret_24h', 'vol_24h', 'range_12h', 'dist_24h', 'weekday']
WINDOWS = {'morning': {'start': 8, 'end': 18}, 'afternoon': {'start': 13, 'end': 18}}

def dataset(start, end):
    rows = []
    for date in sorted(set(bars.index.date)):
        day = pd.Timestamp(date, tz='UTC')
        instant, endtime = day + pd.Timedelta(hours=start), day + pd.Timedelta(hours=end)
        if instant not in bars.index or pd.isna(bars.loc[instant, 'open']):
            continue
        # The current hourly bar contributes its open only. All OHLC information
        # used in features comes from hourly bars ending no later than start.
        past = bars.loc[bars.index < instant].dropna(subset=['high', 'low', 'close']).tail(72)
        if len(past) < 50 or past.index[-1] != instant - pd.Timedelta(hours=1):
            continue
        p = float(bars.loc[instant, 'open'])
        if not np.isfinite(p) or p <= 0: continue
        def ret(n): return float((p / past['close'].iloc[-n] - 1) * 100)
        returns = past['close'].pct_change().dropna()
        f = {'ret_1h': ret(1), 'ret_4h': ret(4), 'ret_12h': ret(12), 'ret_24h': ret(24),
             'vol_24h': float(returns.tail(24).std() * 100),
             'range_12h': float((past['high'].tail(12).max() - past['low'].tail(12).min()) / p * 100),
             'dist_24h': float((p / past['close'].tail(24).mean() - 1) * 100),
             'weekday': float(day.weekday())}
        if not all(np.isfinite(list(f.values()))): continue
        endprice = float(bars.loc[endtime, 'open']) if endtime in bars.index and pd.notna(bars.loc[endtime, 'open']) else np.nan
        if np.isfinite(endprice) and endprice == p: continue # exact flat outcomes excluded from binary test
        rows.append({'date': date.isoformat(), 'start_price': p, 'end_price': endprice, **f})
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
    data = dataset(start, end); complete = data.dropna(subset=['target']).copy()
    metrics, backtest = evaluate(complete)
    for entry in log:
        if entry.get('model') != 'intraday-v2' or entry.get('window') != name: continue
        if entry.get('actual') is None and entry['date'] in complete.index:
            r = complete.loc[entry['date']]
            actual = 'up' if r.target else 'down'
            entry.update(actual=actual, actual_start=round(float(r.start_price),2),
                         actual_end=round(float(r.end_price),2), return_pct=round(float(r.return_pct),4),
                         correct=entry['direction']==actual)
    # 08:00 or 13:00 bar open is known only after the bar begins. A run may
    # publish at most 10 minutes late; the displayed issue time always says when.
    if NOW.hour == start and NOW.minute <= 10 and today in data.index and not any(e.get('date') == today and e.get('window') == name and e.get('model') == 'intraday-v2' for e in log):
        train = complete[complete.index < today]
        if len(train) >= 120 and train.target.nunique() == 2:
            p = prediction(train, data.loc[[today]])
            log.append({'date': today, 'window': name, 'issued_at': NOW.isoformat(timespec='seconds').replace('+00:00','Z'),
                        'feature_cutoff_utc': f'{start:02d}:00', 'model': 'intraday-v2', 'training_n': len(train),
                        **p, 'actual': None})
    windows[name] = {'start_utc': f'{start:02d}:00', 'end_utc': f'{end:02d}:00',
                     'history_days': len(complete), 'validation': metrics, 'validation_predictions': backtest}
with open(logpath, 'w') as f: json.dump(log, f, indent=2, allow_nan=False)
out = {'generated_at': NOW.isoformat(timespec='seconds').replace('+00:00','Z'),
       'source': 'Yahoo Finance GC=F hourly futures; hourly bar opens',
       'last_data_bar_utc': bars.index[-1].isoformat(), 'windows': windows,
       'forecasts': [e for e in log if e.get('model') == 'intraday-v2'],
       'limitations': ['Quotes can be delayed, revised or missing. Futures prices differ from broker XAU/USD.',
                       'Estimated endpoint is a separate regression from the directional classifier and may disagree.',
                       'Historical 10th–90th return range is unconditional, not a calibrated prediction interval.',
                       'Accuracy and endpoint MAE are historical holdout results; no spread, slippage or trading costs.',
                       'Backtest assumes hourly bar open is available at its timestamp; actual data may be delayed.',
                       'Forecasts may be issued up to 10 minutes late; any preceding move has already happened.']}
with open(os.path.join(ROOT, 'docs', 'intraday.json'), 'w') as f: json.dump(out, f, indent=2, allow_nan=False)
print(json.dumps({'generated_at':out['generated_at'],'windows':{k:v['validation'] for k,v in windows.items()},'forecast_count':len(out['forecasts'])}, indent=2))
