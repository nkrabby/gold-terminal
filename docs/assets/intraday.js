'use strict';
(async function(){
  const el = id => document.getElementById(id);
  try {
    const res=await fetch('intraday.json?t='+Date.now(),{cache:'no-store'});
    if(!res.ok) throw Error('Snapshot unavailable');
    const d=await res.json();
    const pct=n=>(n*100).toFixed(1)+'%';
    const money=n=>'$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    el('intradayStatus').textContent='Once each window opens, the model can issue one forecast before 18:00 using the latest available completed Yahoo hourly candle. A source update at most 20 minutes old is required; it may be delayed. The actual issue time and reference age are shown; forecasts are not backdated.';
    const intro=el('intradayCard')?.querySelector('p'); if(intro) intro.textContent='Yahoo gold futures forecasts from 08:00 or 13:00 toward 18:00 Accra/UTC. A delayed issue uses the latest completed candle at its decision cutoff.';
    const fine=el('intradayCard')?.querySelector('p.fineprint:not(#intradayDetail)'); if(fine) fine.textContent='Experimental research only. Data can be delayed, missing or revised; a recent quote does not guarantee a final candle. Estimated high/low cover the decision hour to 18:00 and may include movement before issuance. Yahoo futures and Exness spot use different prices; the Exness daily model also has a different endpoint.';
    for (const [id,w] of Object.entries(d.windows)) {
      const m=w.validation; const f=d.forecasts.filter(x=>x.window===id).slice(-1)[0];
      const box=document.createElement('article'); box.className='intraday-window';
      const add=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;box.append(node)};
      add('h3', `${w.start_utc} → ${w.end_utc} UTC`);
      add('p', `Engine status: ${w.status || 'requires updated engine'}.`);
      if(f){
        add('p',`Latest forecast: ${f.date} · issued ${f.issued_at}`);
        add('p',`Direction: ${f.direction.toUpperCase()} · model P(up) ${pct(f.p_up)}`);
        add('p',`Reference: ${money(f.start_price)} · estimated 18:00: ${money(f.estimated_end)}.`);
        if(f.reference_bar_end) add('p', `Reference candle ended ${f.reference_bar_end}; age at issue ${f.reference_age_minutes} minutes. Cutoff ${f.feature_cutoff_utc} UTC. Yahoo source timestamp ${f.source_quote_time||'unknown'} (age ${f.source_quote_age_minutes??'unknown'} minutes at issue).`);
        if (f.estimated_window_high != null && f.estimated_window_low != null) {
          add('p',`Experimental window high: ${money(f.estimated_window_high)} · window low: ${money(f.estimated_window_low)}`);
          if (f.actual_window_high != null) add('p',`Observed high: ${money(f.actual_window_high)} · low: ${money(f.actual_window_low)} (hourly futures data).`);
        } else add('p','No high/low forecast was recorded for this older forecast; no retroactive estimate is shown.');
        add('p',`Historical endpoint-return range: ${money(f.historical_range[0])} – ${money(f.historical_range[1])}`);
        add('p', f.actual ? `Outcome: ${f.actual}${f.correct===null?' (flat)':f.correct?' (correct)':' (incorrect)'}; actual 18:00: ${money(f.actual_end)}${f.endpoint_error_usd!=null?'; price error '+money(f.endpoint_error_usd):''}.` : 'Outcome pending.');
      } else add('p','No live forecast recorded for this window yet.');
      add('p',`Scheduled-time historical simulation (not the delayed-issue strategy): ${pct(m.accuracy)} direction accuracy across ${m.n} days; always-up ${pct(m.always_up)}, always-down ${pct(m.always_down)}.`);
      add('p',`18:00 endpoint mean absolute error ${money(m.endpoint_mae_usd)}; unchanged-price baseline ${money(m.unchanged_price_mae_usd)}. Historical range coverage ${pct(m.historical_range_coverage)}.`);
      const live=d.forecasts.filter(x=>x.window===id&&x.model==='intraday-v4'&&x.actual&&x.actual!=='flat'&&Number.isFinite(x.endpoint_error_usd)&&Number.isFinite(x.unchanged_error_usd));
      if(live.length){const acc=live.filter(x=>x.correct===true).length/live.length;const avg=k=>live.reduce((sum,x)=>sum+x[k],0)/live.length;add('p',`Recorded v4 outcomes: ${live.length}; direction ${pct(acc)}; average endpoint error ${money(avg('endpoint_error_usd'))} vs unchanged-price ${money(avg('unchanged_error_usd'))}. Small samples are inconclusive.`)}
      else add('p','Recorded v4 outcome comparison: waiting for confirmed results.');
      const e=w.extremes_validation;
      if (e && e.n) add('p',`Experimental high/low holdout, ${e.n} days: high error ${money(e.high_mae)} vs baseline ${money(e.high_baseline_mae)}; low error ${money(e.low_mae)} vs baseline ${money(e.low_baseline_mae)}. Lower is better.`);
      add('p',`Holdout ${m.holdout_start} to ${m.holdout_end}; Brier ${m.brier.toFixed(3)}.`);
      el('intradayWindows').append(box);
    }
    el('intradayDetail').textContent=`Expanding-window refit uses earlier completed outcomes; retraining does not guarantee improvement. Holdout assumes timely, unrevised historical bars. Snapshot ${d.generated_at}; latest available hourly bar ${d.last_data_bar_utc}. Historical 10th–90th percentile range is calculated from prior training returns.`;
    const body=el('intradayLog');
    if(!d.forecasts.length){const cell=body.insertRow().insertCell();cell.colSpan=8;cell.textContent='No forecasts recorded yet.';}
    d.forecasts.slice().reverse().forEach(f=>{const tr=body.insertRow();[f.date,f.window,f.issued_at,f.direction,pct(f.p_up),money(f.start_price),money(f.estimated_end),f.actual?`${f.actual} — ${f.correct===null?'flat':f.correct?'correct':'incorrect'}`:'pending'].forEach(v=>{tr.insertCell().textContent=v;});});
  }catch(e){el('intradayStatus').textContent='Intraday snapshot unavailable. Run intraday.py or check the workflow.';console.warn(e);}
})();
