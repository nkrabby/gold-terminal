# Session comparison update

This patch adds a session research panel while preserving the 08:00–18:00 and
13:00–18:00 Accra-time forecasts. It does not create live Asia/London/New York
session forecasts or promote the macro model.

Research definitions (local market time): Tokyo 09:00–15:00; London 08:00–16:00;
New York 08:00–16:00. These are conventions, not universally agreed session
boundaries. Tokyo is only a proxy for the wider Asian trading session. Python
time zones handle daylight saving for London and New York. The New York period
is a market-session convention, NOT the NYSE stock-market opening time.

The test intersects all three sessions' dates, compares gold-only and market-proxy
features on those dates, and uses expanding-window training with the last 20% for
testing. Missing bars, Yahoo data revisions and unknown publication latency can
bias results. $3/oz is a hypothetical round-trip cost. Starting-bar-open fills
are optimistic because the bar's opening price must arrive before a forecast can
be calculated. No model is automatically promoted.

## Install on GitHub

This is a patch for an existing Gold Terminal repository, not a standalone app.
Upload the included files into matching paths, preserving all other files.
Do NOT overwrite existing forecast_log.json or quote_audit.json. Keep your cache,
requirements.txt, docs/charts and favicon.

Upload or replace: update.py, intraday.py, research_audit.py, session_research.py,
docs/index.html, docs/intraday.json, docs/research.json, docs/sessions.json,
docs/assets/app.js, docs/assets/style.css, docs/assets/intraday.js,
docs/assets/research.js, docs/assets/sessions.js, and the workflow at
.github/workflows/refresh.yml. On GitHub use Code → Add file → Upload files or
edit files directly. If your computer hides .github, open the workflow on GitHub
and paste in the supplied workflow's contents.

Set Settings → Pages → Build and deployment → Source = GitHub Actions. Run
Actions → Refresh Gold Terminal → Run workflow. The workflow fetches hourly
feeds, updates the original forecasts and audits, tests sessions, commits output,
and explicitly deploys. It may fail if Yahoo blocks requests; schedules can run
late and therefore miss forecast windows. All updates are local until uploaded.
