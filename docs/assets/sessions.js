'use strict';
(async()=>{
 const body=document.getElementById('sessionRows'), info=document.getElementById('sessionInfo');
 try{
  const res=await fetch('sessions.json?t='+Date.now(),{cache:'no-store'});if(!res.ok)throw Error('Unavailable');
  const d=await res.json(),pct=x=>(100*x).toFixed(1)+'%';
  for(const [name,r] of Object.entries(d.sessions)){
   const row=body.insertRow();[name,r.utc_hour_pairs.join(' / '),r.n,pct(r.models.gold.accuracy),pct(r.models.macro.accuracy),pct(r.always_down),'$'+r.models.gold.net_at_3_usd_cost.toFixed(2)].forEach(x=>row.insertCell().textContent=x);
  }
  info.textContent=`Matched session holdout: ${Object.values(d.sessions)[0].holdout_start} through ${Object.values(d.sessions)[0].holdout_end}; snapshot ${d.generated_at}. Returns use indicative futures bar opens, not broker fills. $3/oz cost is hypothetical; opening-price execution is optimistic and latency, financing and market impact are not captured. Missing-data selection, revisions and data availability can affect results; this comparison does not promote models.`;
 }catch(e){info.textContent='Session research unavailable; check the workflow.';console.warn(e);}
})();
