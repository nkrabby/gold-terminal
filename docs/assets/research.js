'use strict';
(async()=>{
  const body=document.getElementById('researchRows'), info=document.getElementById('researchInfo');
  try{
    const response=await fetch('research.json?t='+Date.now(),{cache:'no-store'});
    if(!response.ok)throw Error('Unavailable');
    const d=await response.json(), pct=x=>(100*x).toFixed(1)+'%';
    for(const [name,r] of Object.entries(d.comparisons)){
      let row=body.insertRow();
      [name,r.n,pct(r.models.gold.accuracy),pct(r.models.macro.accuracy),pct(r.always_down), '$'+r.models.macro.net_usd_per_oz_at_round_trip_cost['3']].forEach(x=>row.insertCell().textContent=x);
    }
    info.textContent=`Updated ${d.generated_at}. One simulated directional trade per day; $3 per oz round-trip cost is an example, not a broker quote. Historic start-price fills are not necessarily achievable after the forecast is issued. Gold revisions: ${d.audit.revised_bars} changes among ${d.audit.compared_bars} comparable bars in the latest audit (zero comparable bars means no conclusion). Actual historical feed delays remain unknown.`;
  }catch(e){info.textContent='Research snapshot unavailable; check the workflow.';console.warn(e)}
})();
