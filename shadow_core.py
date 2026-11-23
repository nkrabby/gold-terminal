# Functions executed with an explicit market-data namespace by exness_shadow.py.

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
        if len(past) < 50 or past.index[-1] != instant - pd.Timedelta(hours=1):
            continue
        p = float(past.close.iloc[-1]) if anchor == 'prior_close' else float(bars.loc[instant, 'open'])
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
                     'session_high': session_high, 'session_low': session_low, **f})
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
