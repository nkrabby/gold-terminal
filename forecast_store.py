"""Experimental four-hour log storage. Does not generate or publish forecasts.

An advisory lock serialises local processes only, not separate GitHub runners.
Host must serialize workflows and handle Git push conflicts without losing data.
"""
import fcntl, json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

class StoreError(Exception):pass

def utc(s):
 try:
  x=datetime.fromisoformat(s.replace('Z','+00:00'))
  if x.tzinfo is None or x.utcoffset().total_seconds()!=0:raise ValueError()
  return x
 except Exception as e:raise StoreError('Invalid UTC timestamp') from e

class ForecastStore:
 def __init__(self,path):self.path=Path(path)
 def _read(self):
  if not self.path.exists():return {'version':1,'forecasts':{},'outcomes':{}}
  try:
   x=json.loads(self.path.read_text())
   if x.get('version')!=1 or not isinstance(x['forecasts'],dict) or not isinstance(x['outcomes'],dict):raise ValueError()
   return x
  except Exception as e:raise StoreError('Existing log is invalid; not overwritten') from e
 def _write(self,x):
  text=json.dumps(x,indent=2,allow_nan=False)+'\n';name=None
  try:
   with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.path.parent,delete=False) as f:
    name=f.name;f.write(text);f.flush();os.fsync(f.fileno())
   os.replace(name,self.path);name=None
  finally:
   if name and os.path.exists(name):os.unlink(name)
 def _action(self,fn):
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with open(str(self.path)+'.lock','a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   data=self._read();changed,result=fn(data)
   if changed:self._write(data)
   return result
 def record_forecast(self,decision,forecast,issued_at):
  if decision.get('status')!='eligible':raise StoreError('Decision is not eligible')
  issued=utc(issued_at);scheduled=utc(decision['scheduled_for']);key=decision['key']
  if issued<scheduled or issued.date()!=scheduled.date():raise StoreError('Issue time outside scheduled day or before slot')
  # Reject issue after the four-hour period, even if the caller used an old decision.
  if (issued-scheduled).total_seconds()>=14400:raise StoreError('Issue belongs to a later slot')
  if not isinstance(forecast,dict) or not forecast:raise StoreError('Missing forecast')
  def action(data):
   if key in data['forecasts']:return False,False
   data['forecasts'][key]={'issued_at':issued_at,'decision':decision,'forecast':forecast}
   return True,True
  return self._action(action)
 def record_outcome(self,key,outcome):
  if outcome.get('status')!='confirmed chart-candle proxy':raise StoreError('Only confirmed candle proxy can be recorded')
  confirmed=utc(outcome['confirmed_at'])
  def action(data):
   if key not in data['forecasts']:raise StoreError('No issued forecast for outcome')
   if confirmed < utc(data['forecasts'][key]['issued_at']):raise StoreError('Outcome predates forecast')
   if key in data['outcomes']:return False,False
   data['outcomes'][key]=outcome
   return True,True
  return self._action(action)
