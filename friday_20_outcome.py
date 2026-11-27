"""Resolve Friday 20:00 outcome from the completed 19:45 chart candle."""
from datetime import datetime,time,timedelta,timezone
import math

def resolve_friday_20_outcome(day,now,candles,*,schedule_confirmed_for_day):
 if day.weekday()!=4:raise ValueError('Friday endpoint only')
 if now.tzinfo is None or now.utcoffset()!=timedelta(0):raise ValueError('now must be UTC')
 if not schedule_confirmed_for_day:return {'status':'pending: session schedule not confirmed for this date'}
 expected=datetime.combine(day,time(19,45),tzinfo=timezone.utc);endpoint=expected+timedelta(minutes=15)
 if now<endpoint:return {'status':'pending: Friday 20:00 has not passed'}
 seen=set();match=None;later=False
 for c in candles:
  op,end=c['open'],c['end']
  if any(t.tzinfo is None or t.utcoffset()!=timedelta(0) for t in (op,end)):raise ValueError('candle timestamps must be UTC')
  if end-op!=timedelta(minutes=15):raise ValueError('not an M15 candle')
  if op in seen:return {'status':'pending: duplicate candle timestamps'}
  seen.add(op)
  if op==expected:match=c
  if endpoint<=op<=now:later=True
 if match is None or not match['completed']:return {'status':'pending: 19:45 candle not confirmed complete'}
 if not later:return {'status':'pending: awaiting subsequent bar'}
 price=float(match['close'])
 if not math.isfinite(price) or price<=0:return {'status':'pending: invalid candle close'}
 return {'status':'confirmed chart-candle proxy','price':price,'bar_open':expected.isoformat(),'nominal_endpoint':endpoint.isoformat(),'confirmed_at':now.isoformat(),'note':'Close of the 19:45 M15 candle; not proof of a tick at exactly 20:00 or an executable fill.'}
