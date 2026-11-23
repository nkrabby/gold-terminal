'use strict';
(async()=>{
 const el=id=>document.getElementById(id),money=n=>'$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}),pct=n=>(n*100).toFixed(1)+'%';
 try{
  const res=await fetch('exness_shadow.json?t='+Date.now(),{cache:'no-store'});if(!res.ok)throw Error('snapshot unavailable');
  const d=await res.json(),src=d.source;
  el('exnessShadowStatus').textContent=d.status+(src?` · Captured ${src.captured_at}, bid ${money(src.bid)}, ask ${money(src.ask)}. Freshness was checked at engine run, not continuously.`:'');
  for(const [key,w] of Object.entries(d.windows)){
   const box=document.createElement('article');box.className='intraday-window';
   const add=(tag,text)=>{let n=document.createElement(tag);n.textContent=text;box.append(n)};
   const f=d.forecasts.filter(x=>x.window===key).slice(-1)[0],m=w.validation;
   add('h3',`${w.start_utc} → ${w.end_utc} UTC`);add('p',`Latest run: ${w.status}.`);
   if(f){add('p',`${f.date} · issued ${f.issued_at} · ${f.direction.toUpperCase()} · P(up) ${pct(f.p_up)}.`);
    add('p',`Prior-close reference ${money(f.start_price)} · 18:00 estimate ${money(f.estimated_end)}.`);
    if(f.estimated_window_high!=null)add('p',`Experimental high ${money(f.estimated_window_high)} · low ${money(f.estimated_window_low)}.`);
    if(f.actual)add('p',`Actual 18:00 ${money(f.actual_end)} · ${f.actual}${f.correct===null?'':f.correct?' (correct)':' (incorrect)'}.`);
   }else add('p','No live shadow forecast recorded for this window yet.');
   add('p',`Exness holdout ${m.n} days: ${pct(m.accuracy)} direction accuracy; always-down ${pct(m.always_down)}. Endpoint average error ${money(m.endpoint_mae_usd)}; unchanged baseline ${money(m.unchanged_price_mae_usd)}.`);
   el('exnessShadowWindows').append(box);
  }
  const body=el('exnessShadowLog');if(!d.forecasts.length){const c=body.insertRow().insertCell();c.colSpan=8;c.textContent='No Exness shadow forecasts recorded yet.';}
  d.forecasts.slice().reverse().forEach(f=>{const row=body.insertRow();[f.date,f.window,f.issued_at,f.direction,pct(f.p_up),money(f.start_price),money(f.estimated_end),f.actual?`${f.actual}${f.correct===null?'':f.correct?' — correct':' — incorrect'}`:'pending'].forEach(v=>{row.insertCell().textContent=v;});});
 }catch(e){el('exnessShadowStatus').textContent='Exness shadow snapshot unavailable. Check installation and GitHub Actions.';console.warn(e)}
})();
