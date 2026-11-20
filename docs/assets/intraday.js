'use strict';
(async function(){
  const el = id => document.getElementById(id);
  try {
    const res=await fetch('intraday.json?t='+Date.now(),{cache:'no-store'});
    if(!res.ok) throw Error('Snapshot unavailable');
    const d=await res.json();
    const pct=n=>(n*100).toFixed(1)+'%';
    const money=n=>'$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    el('intradayStatus').textContent='Forecasts are recorded only when the scheduled run arrives within 10 minutes of 08:00 or 13:00 UTC and data is available. GitHub Actions may be late; a missed forecast is not backfilled.';
    for (const [id,w] of Object.entries(d.windows)) {
      const m=w.validation; const f=d.forecasts.filter(x=>x.window===id).slice(-1)[0];
      const box=document.createElement('article'); box.className='intraday-window';
      const add=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;box.append(node)};
      add('h3', `${w.start_utc} → ${w.end_utc} UTC`);
      if(f){
        add('p',`Latest forecast: ${f.date} · issued ${f.issued_at}`);
        add('p',`Direction: ${f.direction.toUpperCase()} · model P(up) ${pct(f.p_up)}`);
        add('p',`Start proxy: ${money(f.start_price)} · estimated 18:00: ${money(f.estimated_end)}`);
        if (f.estimated_window_high != null && f.estimated_window_low != null) {
          add('p',`Experimental window high: ${money(f.estimated_window_high)} · window low: ${money(f.estimated_window_low)}`);
          if (f.actual_window_high != null) add('p',`Observed high: ${money(f.actual_window_high)} · low: ${money(f.actual_window_low)} (hourly futures data).`);
        } else add('p','No high/low forecast was recorded for this older forecast; no retroactive estimate is shown.');
        add('p',`Historical endpoint-return range: ${money(f.historical_range[0])} – ${money(f.historical_range[1])}`);
        add('p', f.actual ? `Outcome: ${f.actual} (${f.correct?'correct':'incorrect'}); actual 18:00: ${money(f.actual_end)}.` : 'Outcome pending.');
      } else add('p','No live forecast recorded for this window yet.');
      add('p',`Walk-forward holdout: ${pct(m.accuracy)} direction accuracy across ${m.n} days; always-up ${pct(m.always_up)}, always-down ${pct(m.always_down)}.`);
      add('p',`18:00 endpoint mean absolute error ${money(m.endpoint_mae_usd)}; unchanged-price baseline ${money(m.unchanged_price_mae_usd)}. Historical range coverage ${pct(m.historical_range_coverage)}.`);
      const e=w.extremes_validation;
      if (e && e.n) add('p',`Experimental high/low holdout, ${e.n} days: high error ${money(e.high_mae)} vs baseline ${money(e.high_baseline_mae)}; low error ${money(e.low_mae)} vs baseline ${money(e.low_baseline_mae)}. Lower is better.`);
      add('p',`Holdout ${m.holdout_start} to ${m.holdout_end}; Brier ${m.brier.toFixed(3)}.`);
      el('intradayWindows').append(box);
    }
    el('intradayDetail').textContent=`Daily expanding-window refit using earlier completed outcomes; results are not proof of an edge. Snapshot ${d.generated_at}; latest available hourly bar ${d.last_data_bar_utc}. Historical 10th–90th percentile range is calculated from prior training returns.`;
    const body=el('intradayLog');
    if(!d.forecasts.length){const cell=body.insertRow().insertCell();cell.colSpan=8;cell.textContent='No forecasts recorded yet.';}
    d.forecasts.slice().reverse().forEach(f=>{const tr=body.insertRow();[f.date,f.window,f.issued_at,f.direction,pct(f.p_up),money(f.start_price),money(f.estimated_end),f.actual?`${f.actual} — ${f.correct?'correct':'incorrect'}`:'pending'].forEach(v=>{tr.insertCell().textContent=v;});});
  }catch(e){el('intradayStatus').textContent='Intraday snapshot unavailable. Run intraday.py or check the workflow.';console.warn(e);}
})();
