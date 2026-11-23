'use strict';
(async()=>{
 const status=document.getElementById('fourHourStatus');
 const list=document.getElementById('fourHourForecasts');
 const price=v=>typeof v==='number'&&Number.isFinite(v)?'$'+v.toFixed(2):'unavailable';
 const paragraph=(parent,text)=>{const p=document.createElement('p');p.textContent=text;parent.append(p)};
 try {
  const response=await fetch('four_hour_research.json?t='+Date.now(),{cache:'no-store'});
  if(!response.ok)throw new Error('snapshot unavailable');
  const data=await response.json();
  status.textContent=`${data.status.status} · snapshot generated ${data.generated_at}. ${data.note}`;
  if(!Array.isArray(data.entries))throw new Error('invalid forecasts');
  if(!data.entries.length){paragraph(list,'No four-hour forecasts recorded yet.');return}
  for(const f of data.entries.slice(0,20)){
   const box=document.createElement('article');box.className='intraday-window';
   const heading=document.createElement('h3');heading.textContent=`${f.key} UTC`;box.append(heading);
   paragraph(box,`Issued ${f.issued_at}; scheduled ${f.scheduled_for}.`);
   paragraph(box,`Reference ${price(f.reference_close)} · candle ended ${f.reference_bar_end} · age at scheduling ${f.reference_age_minutes} min.`);
   const p=f.prediction||{};
   const probability=typeof p.p_up==='number'&&Number.isFinite(p.p_up)?`${(p.p_up*100).toFixed(1)}%`:'unavailable';
   paragraph(box,`Direction: ${String(p.direction||'unavailable').toUpperCase()} · probability up ${probability} · endpoint estimate ${price(p.estimated_end)}.`);
   paragraph(box,`Estimated remaining high ${price(p.estimated_high_remaining)} · low ${price(p.estimated_low_remaining)}. Training: ${p.training_days??'unavailable'} earlier days.`);
   const z=p.scenario;
   if(z&&z.available){
    paragraph(box,`Uncalibrated possible start zones — aggressive ${price(z.aggressive_zone[0])}–${price(z.aggressive_zone[1])}; conservative ${price(z.conservative_zone[0])}–${price(z.conservative_zone[1])}.`);
    paragraph(box,`Invalidation ${price(z.invalidation)} · endpoint target ${price(z.target)}.`);
    if(f.tracking)paragraph(box,`Candle-touch proxy, not a fill: aggressive ${f.tracking.aggressive.status}; conservative ${f.tracking.conservative.status}.`);
   }else if(z)paragraph(box,`No directional price map: ${z.reason}`);
   paragraph(box,f.outcome?`Outcome: ${price(f.outcome.price)} — ${f.outcome.status}, confirmed ${f.outcome.confirmed_at}.`:'Outcome pending; no closing price has been confirmed.');
   paragraph(box,'Chart-price research only. No fill, trade, profit or predictive edge is guaranteed.');
   list.append(box);
  }
 }catch(error){status.textContent='Four-hour research snapshot unavailable or invalid; check the workflow.';console.warn(error)}
})();
