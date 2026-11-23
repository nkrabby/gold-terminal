"""Build a public-safe research dashboard snapshot without changing the log."""
import json,os,tempfile
from pathlib import Path
from datetime import datetime,timezone
from forecast_store import ForecastStore

def snapshot(root,status,now=None,bars=None):
 root=Path(root); store=ForecastStore(root/'market'/'four_hour_research_log.json');data=store._read()
 now=now or datetime.now(timezone.utc)
 entries=[]
 for key,record in sorted(data['forecasts'].items(),reverse=True)[:100]:
  decision=record['decision'];p=record['forecast'];outcome=data['outcomes'].get(key)
  tracking=None
  scenario=p.get('scenario') or {}
  if bars is not None and scenario.get('available'):
   import pandas as pd
   from price_map import track_zone
   issued=pd.Timestamp(record['issued_at']);end=pd.Timestamp(key[:10],tz='UTC')+pd.Timedelta(days=1)
   tracking={name:track_zone(scenario,scenario[name+'_zone'],bars,issued,now,end) for name in ('aggressive','conservative')}
  entries.append({'key':key,'issued_at':record['issued_at'],'scheduled_for':decision['scheduled_for'],'reference_bar_end':decision['reference_bar_end'],'reference_close':decision['reference_close'],'reference_age_minutes':decision['reference_age_minutes'],'prediction':p,'outcome':outcome,'tracking':tracking})
 return {'generated_at':(now or datetime.now(timezone.utc)).isoformat(),'status':status,'entries':entries,'note':'Research only. Newer data may not be reflected; updates can be skipped or delayed. Friday forecasting is disabled. Regular session hours may be assumed rather than verified; holidays or broker changes can invalidate them.'}

def publish_snapshot(root,status,now=None,bars=None):
 root=Path(root);out=root/'docs'/'four_hour_research.json';out.parent.mkdir(parents=True,exist_ok=True);text=json.dumps(snapshot(root,status,now,bars),indent=2,allow_nan=False);name=None
 try:
  with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=out.parent,delete=False) as f:name=f.name;f.write(text);f.flush();os.fsync(f.fileno())
  os.replace(name,out);name=None
 finally:
  if name and os.path.exists(name):os.unlink(name)
 return out
