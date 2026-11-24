'use strict';
(async function(){
  const el=id=>document.getElementById(id);
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
  const num=n=>typeof n==='number'&&Number.isFinite(n);
  const pct=n=>num(n)?(n*100).toFixed(1)+'%':'—';
  const money=n=>num(n)?'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  const metric=(label,value,cls='')=>{const box=node('div','focus-metric');box.append(node('span','focus-caption',label),node('strong',cls,value));return box};
  const outcome=f=>!f.actual?'Outcome pending.':`Outcome: ${f.actual}${f.correct===null?' (flat)':f.correct?' (correct)':' (incorrect)'} · actual 18:00 ${money(f.actual_end)}${num(f.endpoint_error_usd)?' · endpoint error '+money(f.endpoint_error_usd):''}.`;
  try{
    const res=await fetch('intraday.json?t='+Date.now(),{cache:'no-store'});if(!res.ok)throw Error('Snapshot unavailable');
    const d=await res.json();if(!d.windows||!Array.isArray(d.forecasts))throw Error('Invalid snapshot');
    el('intradayStatus').textContent='One forecast per window when qualifying Yahoo data is available. Forecasts can be issued late and are never backdated. A source timestamp within 20 minutes is required, but data can still be delayed or revised.';
    const list=el('intradayWindows');list.replaceChildren();
    const today=new Date().toISOString().slice(0,10);
    for(const [id,w] of Object.entries(d.windows)){
      const all=d.forecasts.filter(x=>x.window===id),f=all.slice(-1)[0];
      const card=node('article','focus-latest yahoo-window');
      const head=node('div','focus-latest-head');head.append(node('h3','',`${w.start_utc} → ${w.end_utc} UTC`));
      head.append(node('span','yahoo-pill '+(!f?'pending':f.date!==today?'old':''),!f?'WAITING':f.date!==today?'EARLIER FORECAST':'RECORDED'));card.append(head);
      card.append(node('p','focus-sub',`Engine: ${w.status||'status unavailable'}.`));
      if(f){
        if(f.date!==today)card.append(node('p','focus-sub yahoo-alert',`This is an earlier forecast from ${f.date}, not a forecast issued today.`));
        card.append(node('p','focus-sub',`Forecast date ${f.date} · issued ${f.issued_at||'unknown'} · ${f.model||'model unknown'}`));
        const grid=node('div','focus-metrics');grid.append(metric('DIRECTION',String(f.direction||'unavailable').toUpperCase(),f.direction==='up'?'up':f.direction==='down'?'down':''),metric('PROBABILITY UP',pct(f.p_up)),metric('REFERENCE',money(f.start_price)),metric('ESTIMATED 18:00',money(f.estimated_end)));card.append(grid);
        if(f.reference_bar_end)card.append(node('p','focus-sub',`Completed reference candle ended ${f.reference_bar_end} · age at issue ${f.reference_age_minutes??'unknown'} min · decision cutoff ${f.feature_cutoff_utc||'unknown'} UTC.`));
        else card.append(node('p','focus-sub',`Reference: ${f.anchor||'hourly bar open (legacy)'}.`));
        if(f.source_quote_time)card.append(node('p','focus-sub',`Yahoo source timestamp ${f.source_quote_time} · age at issue ${f.source_quote_age_minutes??'unknown'} min.`));
        card.append(node('p','focus-sub',`Experimental decision-hour high ${money(f.estimated_window_high)} · low ${money(f.estimated_window_low)}. Independent estimates; they may include movement before issue.`));
        if(num(f.actual_window_high)&&num(f.actual_window_low))card.append(node('p','focus-sub',`Observed high ${money(f.actual_window_high)} · low ${money(f.actual_window_low)} (hourly futures data).`));
        if(Array.isArray(f.historical_range))card.append(node('p','focus-sub',`Historical return range: ${money(f.historical_range[0])} – ${money(f.historical_range[1])}. Not a calibrated prediction interval.`));
        card.append(node('p','focus-sub',outcome(f)));
      }else card.append(node('div','focus-empty','No live forecast has been recorded for this window yet.'));
      const details=node('details','yahoo-details');details.append(node('summary','','Performance & research details'));
      const live=all.filter(x=>x.model==='intraday-v4'&&x.actual&&x.actual!=='flat'&&num(x.endpoint_error_usd)&&num(x.unchanged_error_usd));
      if(live.length){const avg=k=>live.reduce((a,x)=>a+x[k],0)/live.length;details.append(node('p','focus-sub',`Recorded v4 outcomes: ${live.length} · direction ${pct(live.filter(x=>x.correct===true).length/live.length)} · average endpoint error ${money(avg('endpoint_error_usd'))} vs unchanged-price baseline ${money(avg('unchanged_error_usd'))}. Small samples are inconclusive.`))}
      else details.append(node('p','focus-sub','Recorded v4 outcome comparison: waiting for confirmed results.'));
      const m=w.validation||{};details.append(node('p','focus-sub',`Scheduled-start historical simulation — not the delayed-issue strategy: ${pct(m.accuracy)} direction accuracy across ${m.n??'—'} days; always-up ${pct(m.always_up)}, always-down ${pct(m.always_down)}.`));
      details.append(node('p','focus-sub',`Endpoint mean absolute error ${money(m.endpoint_mae_usd)} vs unchanged-price ${money(m.unchanged_price_mae_usd)} · historical range coverage ${pct(m.historical_range_coverage)}.`));
      const e=w.extremes_validation;if(e&&e.n)details.append(node('p','focus-sub',`Experimental high/low holdout (${e.n} days): high error ${money(e.high_mae)} vs baseline ${money(e.high_baseline_mae)}; low error ${money(e.low_mae)} vs baseline ${money(e.low_baseline_mae)}.`));
      details.append(node('p','focus-sub',`Holdout ${m.holdout_start||'—'} to ${m.holdout_end||'—'} · Brier ${num(m.brier)?m.brier.toFixed(3):'—'}. Lower error and Brier are better.`));card.append(details);list.append(card);
    }
    el('intradayDetail').textContent=`Snapshot ${d.generated_at||'unknown'} · latest Yahoo hourly bar ${d.last_data_bar_utc||'unknown'} · source quote ${d.source_quote_time||'unknown'}. Expanding-window refit uses earlier completed outcomes; retraining does not guarantee improvement. Historical tests assume timely, unrevised bars.`;
    const body=el('intradayLog');body.replaceChildren();
    if(!d.forecasts.length){const cell=body.insertRow().insertCell();cell.colSpan=8;cell.textContent='No forecasts recorded yet.'}
    d.forecasts.slice().reverse().forEach(f=>{const row=body.insertRow();[f.date,f.window,f.issued_at,f.direction,pct(f.p_up),money(f.start_price),money(f.estimated_end),f.actual?`${f.actual} — ${f.correct===null?'flat':f.correct?'correct':'incorrect'}`:'pending'].forEach(v=>{row.insertCell().textContent=v??'—'})});
  }catch(e){el('intradayStatus').textContent='Yahoo snapshot unavailable. Check the GitHub workflow and try again.';console.warn(e)}
})();
