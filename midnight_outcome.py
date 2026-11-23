"""Monday–Thursday midnight endpoint, using only a confirmed M15 candle.

Experimental local component; no network or order execution. Caller must
validate the symbol, candle OHLC and applicable session calendar.
"""
from datetime import datetime,time,timedelta,timezone
import math
UTC=timezone.utc

def resolve_midnight_outcome(day, now, candles, *, schedule_confirmed_for_day):
    if day.weekday() not in range(4):
        raise ValueError('midnight endpoint is for Monday–Thursday only')
    if now.tzinfo is None or now.utcoffset()!=timedelta(0):
        raise ValueError('now must be timezone-aware UTC')
    if not schedule_confirmed_for_day:
        return {'status':'pending: session schedule not confirmed for this date'}
    expected=datetime.combine(day,time(23,45),tzinfo=UTC)
    endpoint=expected+timedelta(minutes=15)
    if now < endpoint: return {'status':'pending: midnight has not passed'}
    seen=set();match=None;later=False
    for c in candles:
        op,end=c['open'],c['end']
        if any(t.tzinfo is None or t.utcoffset()!=timedelta(0) for t in (op,end)):
            raise ValueError('candle timestamps must be UTC')
        if end-op!=timedelta(minutes=15):raise ValueError('not an M15 candle')
        if op in seen:return {'status':'pending: duplicate candle timestamps'}
        seen.add(op)
        if op==expected:match=c
        if endpoint<=op<=now:later=True
    if match is None or not match['completed']:
        return {'status':'pending: 23:45 candle not confirmed complete'}
    if not later:return {'status':'pending: awaiting subsequent bar'}
    price=float(match['close'])
    if not math.isfinite(price) or price<=0:return {'status':'pending: invalid candle close'}
    return {'status':'confirmed chart-candle proxy','price':price,
            'bar_open':expected.isoformat(),'nominal_endpoint':endpoint.isoformat(),
            'confirmed_at':now.isoformat(),
            'note':'Close of the 23:45 chart candle; not proof of a tick at exactly midnight or an executable fill.'}
