'use strict';
(async()=>{
 const el=id=>document.getElementById(id),money=n=>'$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}),pct=n=>(n*100).toFixed(1)+'%';
 try{
  const r=await fetch('exness_rolling.json?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('snapshot unavailable');const d=await r.json();
  el('rollingStatus').textContent=d.status+(d.source?` · Exness quote captured ${d.source.captured_at}; freshness tested at engine run.`:'');
  for(const [key,w] of Object.entries(d.windows)){
   const box=document.createElement('article');box.className='intraday-window';const add=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;box.append(n)};
   add('h3',key==='morning'?'08:00–18:00 UTC':'13:00–18:00 UTC');add('p',w.status);
   const f=w.latest;
   if(f){add('p',`Issued ${f.issued_at}; decision cutoff ${f.decision_cutoff}.`);
    add('p',`Last completed candle ended ${f.reference_bar_end}; reference ${money(f.reference_price)} (age ${f.reference_age_minutes} min at cutoff).`);
    add('p',`Direction ${f.direction.toUpperCase()} · P(up) ${pct(f.p_up)} · 18:00 estimate ${money(f.estimated_end)}.`);
    add('p',`Experimental remaining high ${money(f.estimated_high_remaining)} · low ${money(f.estimated_low_remaining)}.`);
    const z=f.scenario;
    if(!z) add('p','Price map not recorded for this older forecast; it will not be created retroactively.');
    else if(!z.available) add('p',`No price map: ${z.reason}`);
    else {
      add('p',`Experimental ${z.side.toUpperCase()} scenario · M15 ATR(14) ${money(z.atr_m15)}.`);
      add('p',`Aggressive possible start: ${money(z.aggressive_zone[0])}–${money(z.aggressive_zone[1])}.`);
      add('p',`Conservative possible start: ${money(z.conservative_zone[0])}–${money(z.conservative_zone[1])}.`);
      add('p',`Invalidation reference ${money(z.invalidation)} · estimated 18:00 ${money(z.estimated_18_end)} · estimated remaining extreme ${money(z.estimated_extreme)}.`);
      if(f.scenario_tracking){const t=f.scenario_tracking;add('p',`Touch tracking (not fills): ${t.status}. ${t.aggressive ? 'Aggressive: '+t.aggressive.status+'. Conservative: '+t.conservative.status+'.' : ''}`);}
    }

    if(f.actual)add('p',`18:00 outcome ${money(f.actual_end)}: ${f.actual}.`);
   }
   const m=w.validation;if(m&&m.n)add('p',`Same-time holdout ${m.n} days: accuracy ${pct(m.direction_accuracy)}, always-down ${pct(m.always_down)}; endpoint average error ${money(m.end_mae)} vs unchanged baseline ${money(m.unchanged_mae)}.`);
   el('rollingWindows').append(box);
  }
  const body=el('rollingLog');if(!d.forecasts.length){const c=body.insertRow().insertCell();c.colSpan=7;c.textContent='No M15 revisions recorded yet.';}
  d.forecasts.slice().reverse().slice(0,100).forEach(f=>{const row=body.insertRow();[f.window,f.decision_cutoff,f.issued_at,money(f.reference_price),f.direction,money(f.estimated_end),f.actual?`${f.actual} (${money(f.actual_end)})`:'pending',f.scenario_tracking ? (f.scenario_tracking.aggressive ? `Aggressive: ${f.scenario_tracking.aggressive.status}; conservative: ${f.scenario_tracking.conservative.status}` : f.scenario_tracking.status) : 'not tracked'].forEach(v=>{row.insertCell().textContent=v;});});
 }catch(e){el('rollingStatus').textContent='M15 forecast unavailable; check GitHub Actions and uploader.';console.warn(e)}
})();
