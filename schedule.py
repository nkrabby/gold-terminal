"""Experimental four-hour XAUUSD scheduling rules; no forecasting or network I/O.
Schedule reflects user's current screenshot, not a guaranteed future calendar.
"""
from datetime import timedelta, time

SLOTS = (8, 12, 16, 20)

def select_update(now, captured, candles, issued_keys, *, fresh_snapshot, utc_server_verified, schedule_confirmed_for_day=False):
    """Decide eligibility, without issuing or recording any forecast.

    Candle dictionaries contain open/end UTC datetimes, completed bool, and close.
    The caller must validate feed activity and persist a successful issue atomically.
    """
    for stamp in (now, captured):
        if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
            raise ValueError('timezone-aware UTC timestamps required')
    if not schedule_confirmed_for_day:
        return {'status': 'session schedule not confirmed for this date'}
    if not utc_server_verified:
        return {'status': 'server offset not verified; waiting'}
    age = (now-captured).total_seconds()
    if not fresh_snapshot or not (-10 <= age <= 120):
        return {'status': 'fresh validated market snapshot required'}
    if now.weekday() >= 5:
        return {'status': 'weekend; no new forecast'}
    if now.hour < 8:
        return {'status': 'before first update'}
    if now.weekday() == 4 and now.time() >= time(20,0):
        return {'status': 'Friday 20:00 forecast endpoint reached; no new forecast'}
    if time(21,58) <= now.time() < time(23,0):
        return {'status': 'scheduled market break; no new forecast'}
    slot = max(h for h in SLOTS if h <= now.hour)
    start = now.replace(hour=slot, minute=0, second=0, microsecond=0)
    key = f'{now.date().isoformat()}T{slot:02d}'
    if key in issued_keys:
        return {'status': 'already issued this four-hour block', 'key': key}
    if captured < start or captured.date() != now.date():
        return {'status': 'quote predates four-hour block', 'key': key}
    available = []
    for candle in candles:
        opening, ending = candle['open'], candle['end']
        for stamp in (opening, ending):
            if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
                raise ValueError('candle timestamps must be UTC')
        if ending-opening != timedelta(minutes=15):
            raise ValueError('not an M15 candle')
        if candle['completed'] and ending <= min(captured,now) and float(candle['close']) > 0:
            available.append(candle)
    if not available:
        return {'status': 'no completed candle available', 'key': key}
    ref = max(available, key=lambda c: c['end'])
    return {'status': 'eligible', 'key': key, 'scheduled_for': start.isoformat(),
            'reference_close': float(ref['close']), 'reference_bar_end': ref['end'].isoformat(),
            'reference_age_minutes': round((now-ref['end']).total_seconds()/60, 2),
            'delay_minutes': round((now-start).total_seconds()/60, 2),
            'endpoint': '20:00 UTC Friday' if now.weekday() == 4 else 'midnight UTC',
            'note': 'Do not backdate issuance; verify broker schedule and holiday changes.'}
