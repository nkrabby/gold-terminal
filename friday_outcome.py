"""Conservative Friday outcome resolver for current screenshot schedule only.

No network access or side effects. Not integrated with the forecasting app.
"""
from datetime import datetime, time, timedelta, timezone
import math

UTC=timezone.utc

def resolve_friday_outcome(day, now, candles, *, schedule_confirmed_for_day):
    """Find the completed 21:45 Friday M15 chart close after a later bar exists.

    Inputs: day is a Friday date, now an aware UTC datetime; candles have open,
    end, completed, close. The caller must validate provenance, symbol and OHLC,
    and must confirm this actual date's schedule (including holidays and DST).
    Never infer fills or prices during the weekend gap.
    """
    if day.weekday()!=4: raise ValueError('date must be Friday')
    if now.tzinfo is None or now.utcoffset()!=timedelta(0):
        raise ValueError('now must be timezone-aware UTC')
    if not schedule_confirmed_for_day:
        return {'status':'pending: Friday schedule not confirmed for this date'}
    expected=datetime.combine(day,time(21,45),tzinfo=UTC)
    close_at=datetime.combine(day,time(21,58),tzinfo=UTC)
    if now < close_at:
        return {'status':'pending: Friday session has not closed'}
    ordered=sorted(candles,key=lambda c:c['open'])
    opens=[]
    for c in ordered:
        op,end=c['open'],c['end']
        if any(t.tzinfo is None or t.utcoffset()!=timedelta(0) for t in (op,end)):
            raise ValueError('candle timestamps must be UTC')
        if end-op!=timedelta(minutes=15): raise ValueError('not an M15 candle')
        if op in opens: return {'status':'pending: duplicate candle timestamps'}
        opens.append(op)
    matches=[c for c in ordered if c['open']==expected]
    if len(matches)!=1 or not matches[0]['completed']:
        return {'status':'pending: Friday final candle not confirmed complete'}
    if any(c['open'].date()==day and c['open']>expected for c in ordered):
        return {'status':'pending: Friday candles conflict with expected schedule'}
    # New bar must already exist by now; its mere existence is not a fill.
    if not any(close_at < c['open'] <= now for c in ordered):
        return {'status':'pending: awaiting subsequent bar after Friday close'}
    price=float(matches[0]['close'])
    if not math.isfinite(price) or price<=0: return {'status':'pending: invalid Friday close'}
    return {'status':'confirmed chart-candle proxy', 'price':price,
            'bar_open':expected.isoformat(), 'scheduled_close':close_at.isoformat(),
            'confirmed_at':now.isoformat(),
            'note':'Last price in the Friday 21:45 chart candle, not proof of an exact 21:58 tick or an executable fill.'}
