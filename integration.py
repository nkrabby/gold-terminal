"""Local orchestration prototype, no broker/GitHub access and no real model.
Caller validates live XAUUSD snapshot, adapts candle input, supplies predictor,
calendar verification, and serializes any remote workflow. Not deployable alone.
"""
from datetime import date, datetime, timezone, timedelta
from schedule import select_update
from friday_outcome import resolve_friday_outcome
from friday_20_outcome import resolve_friday_20_outcome
from midnight_outcome import resolve_midnight_outcome
from forecast_store import ForecastStore

def issue_once(path, now, captured, candles, *, fresh_snapshot, utc_server_verified, schedule_confirmed_for_day, predictor, clock=None):
    """Compute one forecast at most per block; never backdate it.

    predictor(decision, candles) returns a dict. This function rejects empty model
    output but does not validate model mathematics; predictor must be causal and
    production-validated. now must be read immediately before model execution; clock defaults to actual UTC time.
    Inject a clock only for tests, never to backdate a live forecast.
    """
    store=ForecastStore(path)
    existing=store._read()['forecasts']
    recent=[datetime.fromisoformat(v['issued_at'].replace('Z','+00:00')) for v in existing.values()]
    if recent and now-max(recent)<timedelta(hours=4):
        return {'status':'waiting: at least four hours between actual forecast issue times'}
    decision=select_update(now,captured,candles,set(existing),fresh_snapshot=fresh_snapshot,utc_server_verified=utc_server_verified,schedule_confirmed_for_day=schedule_confirmed_for_day)
    if decision['status']!='eligible':return decision
    forecast=predictor(decision,candles)
    # Re-read time after fitting. Forecasts that finish in another slot, during
    # a closure, or after the snapshot becomes stale must never be recorded.
    finished = (clock or (lambda: datetime.now(timezone.utc)))()
    final = select_update(finished,captured,candles,set(),fresh_snapshot=fresh_snapshot,utc_server_verified=utc_server_verified,schedule_confirmed_for_day=schedule_confirmed_for_day)
    if recent and finished-max(recent)<timedelta(hours=4):
        return {'status':'waiting: at least four hours between actual forecast issue times'}
    if final.get('status') != 'eligible' or final.get('key') != decision['key']:
        return {'status':'forecast expired before completion; not recorded'}
    if final['reference_bar_end'] != decision['reference_bar_end']:
        return {'status':'reference changed while forecasting; not recorded'}
    created=store.record_forecast(decision,forecast,finished.isoformat())
    return {'status':'forecast recorded' if created else 'already recorded', 'key':decision['key']}

def score_one(path,key,now,candles,*,schedule_confirmed_for_day):
    store=ForecastStore(path); data=store._read()
    if key not in data['forecasts']:return {'status':'no forecast'}
    day=date.fromisoformat(key[:10])
    model=data['forecasts'][key].get('forecast',{}).get('model')
    fn=resolve_friday_20_outcome if day.weekday()==4 and model=='gold-only-friday-20-v1' else resolve_friday_outcome if day.weekday()==4 else resolve_midnight_outcome
    result=fn(day,now,candles,schedule_confirmed_for_day=schedule_confirmed_for_day)
    if result['status']!='confirmed chart-candle proxy':return result
    saved=store.record_outcome(key,result)
    return {'status':'outcome recorded' if saved else 'outcome already recorded','outcome':result}
