# ◆ Gold Terminal — XAU/USD Daily Forecast

A self-updating gold forecast website you host **free on GitHub Pages**. A scheduled GitHub Action re-fetches live market data ~every 30 minutes on weekdays, re-validates the model, regenerates charts and republishes — no server, no database, no API keys.

![Architecture](https://img.shields.io/badge/architecture-static%20site%20%2B%20GitHub%20Actions-gold)

---

## What it does

| Area | Detail |
|---|---|
| **Live spot ticker** | Streams XAU from [gold-api.com](https://gold-api.com) straight from your browser every 15 s (CORS-open, no key) |
| **Engine snapshot** (`data.json`, rebuilt by CI) | COMEX GC=F fundamentals, ATR/RSI/SMAs, floor pivots, 30/60-day correlations (DXY, 10Y, silver, WTI), walk-forward model validation, next-session probability |
| **The Call** | Rules-based bias (BEARISH / MILDLY BEARISH / NEUTRAL /…), entry zones, target chain, invalidation, timed catalysts (13:30 UTC claims, 14:30 UTC NY open) |
| **Charts** | 6M + live pivots, 3Y trend with 50/200-DMA, rolling correlations, model hit-rate — regenerated as PNGs each run |
| **UTC calendar** | Recurring weekly US release schedule (Accra = UTC) + verify links (ForexFactory / Investing.com / MyFXBook) |
| **Desk note** | `desk_note.md` — your team's macro note, rendered verbatim; edit and redeploy with `git push` |
| **CSV export** | One click downloads ~3 years of daily GC=F closes |

> ⚠ Educational tool — **not financial advice**. Next-day gold direction is near a coin-flip from technicals (this model's OOS accuracy is *below* the always-long baseline; it is used as a tilt + ATR range sizer, never as a stand-alone signal). Leveraged gold can lose more than your deposit.

---

## Deploy in 6 steps (≈ 3 minutes)

1. **Create a GitHub repo** — e.g. `gold-terminal`. Free accounts need it **public** for free Pages; private repos require a paid plan (Pages still works, just not free).
2. **Push this folder:**
   ```bash
   cd gold-terminal
   git init && git add -A && git commit -m "feat: gold terminal v1"
   git branch -M main
   git remote add origin https://github.com/<YOU>/gold-terminal.git
   git push -u origin main
   ```
3. **Enable Pages:** repo → **Settings → Pages** → *Build and deployment* → Source: **Deploy from a branch** → Branch: **main**, folder: **/docs** → **Save**.
4. **Enable the workflow:** repo → **Actions** tab → allow Actions if prompted → select **"Refresh Gold Terminal"** → **Run workflow** (first manual run).
5. **Visit** `https://<YOU>.github.io/gold-terminal/` — live within ~2 min.
6. **(Optional) speed**: the spot ticker is already live client-side; the engine refreshes every 30 min Mon–Fri via cron and on every `git push` if you edit `desk_note.md`.

That's it — the Action commits updated `data.json` + charts back to `main` and Pages republishes automatically.

---

## How the auto-refresh works

```
cron '*/30 * * * 1-5'  ──►  refresh.yml  ──►  update.py
                                                │  1. fetch gold-api.com (spot) + Yahoo Finance (futures, 3y daily)
                                                │     └─ on failure → cache/*.json (last good raw data)
                                                │  2. features → walk-forward model → pivots/correlations/ATR
                                                │  3. matplotlib charts → docs/charts/*.png
                                                ▼
                                          docs/data.json  ──►  committed by bot  ──►  GitHub Pages
                                                                  (only if changed)
```

**Staleness handling** — if both gold-api and Yahoo are unreachable, CI falls back to `cache/` and the site badge shows age; the browser keeps last good render and labels it "stale". GitHub Pages CDN caches ~10 min; `data.json` is fetched with a `?t=` cache-buster each minute.

### Cadence knobs
- More/less frequent: edit the `cron:` in `.github/workflows/refresh.yml` (e.g. `*/15 * * * 1-5`)
- Weekend gold: add `6` to the day range or leave as is (markets closed, data static anyway)
- Bias thresholds: `p_ens < 0.35` / `< 0.45` / `> 0.65` cutoffs in `update.py`

### What is NOT automated (by design)
The narrative macro note. Edit **`desk_note.md`** weekly (Fed path, tariff/geopolitics, positioning). It ships with the next workflow run or push.

---

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python update.py                 # fetch + rebuild docs/data.json & charts
python -m http.server 8080 --directory docs
# open http://localhost:8080
```

Project layout:

```
update.py                 # engine (fetch → model → levels → charts → data.json)
desk_note.md              # your editable macro note
cache/                    # last-good raw Yahoo JSON (fallback on fetch failure)
docs/                     # ← GitHub Pages root
  index.html              #   app shell (static, zero build)
  assets/style.css        #   design system (dark, gold accent)
  assets/app.js           #   renderers + live ticker + 60 s data.json poll + CSV export
  data.json               #   ← generated each run (committed)
  charts/*.png            #   ← generated each run (committed)
.github/workflows/refresh.yml
requirements.txt
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Pages shows 404 | Settings → Pages → Source must be **main /docs**; wait 2–3 min after first deploy |
| Action fails at `pip install` | Re-run; Yahoo occasionally rate-limits — the engine retries next cron tick and falls back to `cache/` |
| Charts stale but ticker live | Normal: ticker is browser-live; charts/model refresh every 30 min. Check Actions tab for last run |
| Spot ticker shows "—" | gold-api.com down or blocked by your network; hard-refresh. Everything else is served from `data.json` |
| Bot commits not appearing | Actions must be enabled; workflow needs `contents: write` (already set). Check repo **Settings → Actions → General → Workflow permissions → Read and write** |
| Yahoo blocked in your country | The **spot ticker still works**; engine falls back to committed `cache/`. For a permanent fix, point `update.py` at your broker's API (OANDA/Exness/MT5) — the pipeline is source-agnostic below the fetch layer |

---

## Disclaimer

For **education and analysis only** — not investment, legal, or tax advice. Model output is a probabilistic tilt with *documented sub-baseline OOS accuracy*. Markets gap; stops slip; leverage magnifies losses (potentially beyond deposit at retail brokers). Verify every level against your own chart and consult a licensed, SEC/BoG-regulated adviser in your jurisdiction before trading. Past performance ≠ future results.
