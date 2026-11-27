'use strict';
(async()=>{
 const status=document.getElementById('fourHourStatus'),list=document.getElementById('fourHourForecasts');
 const price=v=>typeof v==='number'&&Number.isFinite(v)?'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
 const elem=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
 const pct=v=>typeof v==='number'&&Number.isFinite(v)?(100*v).toFixed(1)+'%':'—';
 const metric=(label,value,cls='')=>{const box=elem('div','focus-metric');box.append(elem('span','focus-caption',label),elem('strong',cls,value));return box};
 const zone=z=>Array.isArray(z)&&z.length===2?price(z[0])+' – '+price(z[1]):'—';
 try{
  const res=await fetch('four_hour_research.json?t='+Date.now(),{cache:'no-store'});if(!res.ok)throw Error('snapshot unavailable');const d=await res.json();if(!Array.isArray(d.entries))throw Error('invalid data');
  status.textContent=`${d.status?.status||'Status unavailable'} · Snapshot generated ${d.generated_at||'time unavailable'}. Times are UTC.`;
  list.replaceChildren();if(!d.entries.length){list.append(elem('div','focus-empty','No four-hour forecast has been recorded yet. The engine waits for fresh Exness data and sufficient history.'));return}
  const [f,...history]=d.entries,p=f.prediction||{},z=p.scenario,box=elem('article','focus-latest');
  const head=elem('div','focus-latest-head');head.append(elem('h3','',`Latest forecast · ${f.key} UTC`),elem('span','focus-time',`Issued ${f.issued_at||'unknown'}`));box.append(head);
  const metrics=elem('div','focus-metrics');const direction=String(p.direction||'unavailable').toUpperCase();metrics.append(metric('DIRECTION',direction,p.direction==='up'?'up':p.direction==='down'?'down':''),metric('PROBABILITY UP',pct(p.p_up)),metric('REFERENCE',price(f.reference_close)),metric('ESTIMATED ENDPOINT',price(p.estimated_end)));box.append(metrics);
  box.append(elem('p','focus-sub',`Forecast endpoint: ${p.model==='gold-only-friday-20-v1'?'Friday 20:00 UTC':p.model==='gold-only-4h-research-v1'?'midnight UTC':'see forecast record'} · ${p.training_policy||'training policy unavailable'}.`));
  box.append(elem('p','focus-sub',`Last completed candle ended ${f.reference_bar_end||'unknown'} · reference age at scheduling ${f.reference_age_minutes??'unknown'} min · ${p.training_days??'unknown'} prior training days.`));
  box.append(elem('p','focus-sub',`Estimated remaining high ${price(p.estimated_high_remaining)} · low ${price(p.estimated_low_remaining)}. These are separate estimates, not guaranteed levels.`));
  if(z?.available){const map=elem('div','focus-map');map.append(metric('AGGRESSIVE START ZONE',zone(z.aggressive_zone)),metric('CONSERVATIVE START ZONE',zone(z.conservative_zone)),metric('INVALIDATION REFERENCE',price(z.invalidation)));box.append(map);if(f.tracking)box.append(elem('p','focus-sub',`Candle-touch proxy (not fills): aggressive ${f.tracking.aggressive?.status||'unknown'}; conservative ${f.tracking.conservative?.status||'unknown'}.`));}
  else if(z)box.append(elem('p','focus-sub',`Price map unavailable: ${z.reason||'unknown'}.`));
  box.append(elem('p','focus-sub',f.outcome?`Confirmed chart-close proxy: ${price(f.outcome.price)} (${f.outcome.confirmed_at||'time unknown'}).`:'Outcome pending until the endpoint candle is confirmed.'));list.append(box);
  if(history.length){const detail=elem('details','focus-history');detail.append(elem('summary','',`Earlier forecasts (${history.length})`));for(const v of history){const q=v.prediction||{};detail.append(elem('div','focus-history-row',`${v.key} · ${q.model==='gold-only-friday-20-v1'?'ends Friday 20:00 UTC':'endpoint per record'} · issued ${v.issued_at} · ${String(q.direction||'unavailable').toUpperCase()} · reference ${price(v.reference_close)} · estimate ${price(q.estimated_end)} · ${v.outcome?'outcome '+price(v.outcome.price):'outcome pending'}`))}list.append(detail)}
 }catch(e){status.textContent='Four-hour research snapshot unavailable. If the update is newly installed, run the GitHub workflow and check its status.';console.warn(e)}
})();
