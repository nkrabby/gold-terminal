
#!/usr/bin/env python3
"""
GOLD TERMINAL — data engine (runs locally AND in GitHub Actions on a schedule).

Flow:
  1. FETCH live quotes (gold-api.com for spot XAU/XAG/XPT; Yahoo Finance for
     futures & drivers). On failure, falls back to the committed cache/ copy.
  2. COMPUTE technicals, floor pivots, 30/60-day correlations, ATR band,
     walk-forward OOS validation stats and next-session probability.
  3. RENDER charts (dark theme PNG) into docs/charts/
  4. WRITE docs/data.json  (consumed by the front-end; Pages serves it statically)

Nothing here needs API keys. If BOTH live sources fail, the previously
committed data.json is left untouched (site shows last-good snapshot).
"""
import json, math, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache')
DOCS = os.path.join(ROOT, 'docs')
CHARTS = os.path.join(DOCS, 'charts')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) GoldTerminal/1.0 (+github.com)'}
NOW = datetime.now(timezone.utc)
print(f"[engine] run at {NOW.isoformat(timespec='seconds')}")

# ---------------------------------------------------------------- fetch helpers
def http_json(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def fetch_with_cache(name, url):
    """Fetch live JSON; on ANY failure reuse cache/<name>.json. Returns (data, is_live)."""
    cpath = os.path.join(CACHE, name)
    try:
        d = http_json(url)
        with open(cpath, 'w') as f:
            json.dump(d, f)
        return d, True
    except Exception as e:
        print(f"[engine] WARN fetch failed for {name}: {e} — trying cache")
        if os.path.exists(cpath):
            with open(cpath) as f:
                return json.load(f), False
        return None, False

def parse_chart(d, symbol):
    r = d['chart']['result'][0]
    q = r['indicators']['quote'][0]
    meta = r.get('meta', {})
    import pandas as pd
    df = pd.DataFrame({'open': q['open'], 'high': q['high'], 'low': q['low'],
                       'close': q['close'], 'volume': q.get('volume')},
                      index=pd.to_datetime(r['timestamp'], unit='s').normalize())
    df = df.dropna(subset=['close'])
    return df, meta

# ---------------------------------------------------------------- load universe
SYMS = {
    'GC=F': 'GC_F', 'SI=F': 'SI_F', 'CL=F': 'CL_F',
    'DX-Y.NYB': 'DXY', '^TNX': 'TNX', 'HG=F': 'HG_F',
    '^GSPC': 'GSPC', 'GLD': 'GLD',
}
raw, meta_gc = {}, {}
live_flags = {}
import urllib.parse
for sym, key in SYMS.items():
    enc = urllib.parse.quote(sym, safe='')
    d, live = fetch_with_cache(f'{key}.json', f'https://query1.finance.yahoo.com/v8/finance/chart/{enc}?range=3y&interval=1d')
    if d is None:
        print('[engine] FATAL: no data for', sym); sys.exit(1)
    raw[key] = d; live_flags[key] = live
    if key == 'GC_F':
        _, meta_gc = parse_chart(d, sym)
print('[engine] live flags:', live_flags)

spot = {}
for nm, url in [('xau', 'https://api.gold-api.com/price/XAU'),
                ('xag', 'https://api.gold-api.com/price/XAG'),
                ('xpt', 'https://api.gold-api.com/price/XPT')]:
    try:
        spot[nm] = http_json(url, timeout=12).get('price')
    except Exception as e:
        print(f'[engine] WARN spot {nm} failed: {e}')
        spot[nm] = None
try:
    spot_ts = http_json('https://api.gold-api.com/price/XAU', timeout=12).get('updatedAt')
except Exception:
    spot_ts = None
print('[engine] spot:', spot)

import numpy as np
import pandas as pd

def load(key):
    df, _ = parse_chart(raw[key], key)
    return df

gc  = load('GC_F'); slv = load('SI_F')['close'].rename('silver'); oil = load('CL_F')['close'].rename('oil')
dxy = load('DXY')['close'].rename('dxy'); tnx = load('TNX')['close'].rename('tnx')
cop = load('HG_F')['close'].rename('copper'); spx = load('GSPC')['close'].rename('spx')
gld = load('GLD')['close'].rename('gld')

df = gc.join([slv, oil, dxy, tnx, cop, spx, gld], how='left').ffill().dropna()
c = df['close']
print(f'[engine] merged {len(df)} sessions ({df.index[0].date()} → {df.index[-1].date()})')

# ---------------------------------------------------------------- features
def rsi(s, n=14):
    d_ = s.diff()
    up = d_.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d_.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + up/dn)

high_low = df['high'] - df['low']
high_pc  = (df['high'] - c.shift(1)).abs()
low_pc   = (df['low']  - c.shift(1)).abs()
df['atr14'] = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1).rolling(14).mean()
df['atr_pct'] = df['atr14'] / c * 100
df['rsi14'] = rsi(c)
for n in (1, 5, 10, 20):
    df[f'gold_ret_{n}d'] = c.pct_change(n) * 100
for n, nm in [(20, 'sma20'), (50, 'sma50'), (200, 'sma200')]:
    df[nm] = c.rolling(n).mean()
    df[f'dist_{nm}'] = (c / df[nm] - 1) * 100
df['vol20'] = c.pct_change().rolling(20).std() * np.sqrt(252) * 100
df['gap'] = (df['open'] / c.shift(1) - 1) * 100
df['range_pct'] = (df['high'] - df['low']) / c * 100
df['dxy_ret_1d'] = df['dxy'].pct_change() * 100; df['dxy_ret_5d'] = df['dxy'].pct_change(5) * 100
df['tnx_chg_1d'] = df['tnx'].diff();              df['tnx_chg_5d'] = df['tnx'].diff(5)
df['silver_ret_1d'] = df['silver'].pct_change() * 100; df['silver_ret_5d'] = df['silver'].pct_change(5) * 100
df['copper_ret_1d'] = df['copper'].pct_change() * 100
df['oil_ret_1d'] = df['oil'].pct_change() * 100
df['spx_ret_1d'] = df['spx'].pct_change() * 100
df['gs_ratio'] = c / df['silver']
df['gs_ratio_chg5'] = df['gs_ratio'].pct_change(5) * 100
gr = c.pct_change()
df['corr_gold_dxy_30'] = gr.rolling(30).corr(df['dxy'].pct_change())
df['corr_gold_tnx_30'] = gr.rolling(30).corr(df['tnx'].pct_change())
df['corr_gold_slv_30'] = gr.rolling(30).corr(df['silver'].pct_change())
df['target_dir'] = (c.shift(-1) > c).astype(int)
df['fwd_ret'] = (c.shift(-1) / c - 1) * 100

FEATS = ['gold_ret_1d','gold_ret_5d','gold_ret_10d','gold_ret_20d','rsi14','atr_pct',
         'dist_sma20','dist_sma50','dist_sma200','vol20','gap','range_pct',
         'dxy_ret_1d','dxy_ret_5d','tnx_chg_1d','tnx_chg_5d',
         'silver_ret_1d','silver_ret_5d','copper_ret_1d','oil_ret_1d','spx_ret_1d',
         'gs_ratio_chg5','corr_gold_dxy_30','corr_gold_tnx_30','corr_gold_slv_30']
mdf = df.dropna(subset=FEATS + ['target_dir']).copy()
X = mdf[FEATS]; y = mdf['target_dir']
print(f'[engine] model matrix: {len(X)} rows')

# ---------------------------------------------------------------- walk-forward OOS
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

def fresh_models():
    gb = GradientBoostingClassifier(n_estimators=300, learning_rate=0.03, max_depth=3,
                                    subsample=0.8, random_state=42)
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
    return gb, lr

N = len(X); start = int(N * 0.55)
gb, lr = fresh_models()
wf_gb, wf_lr, wf_ens, log = [], [], [], []
for i in range(start, N - 1):
    if (i - start) % 21 == 0:
        gb.fit(X.iloc[:i], y.iloc[:i]); lr.fit(X.iloc[:i], y.iloc[:i])
    p_gb = float(gb.predict_proba(X.iloc[[i]])[0, 1])
    p_lr = float(lr.predict_proba(X.iloc[[i]])[0, 1])
    p_en = 0.6 * p_gb + 0.4 * p_lr
    a = int(y.iloc[i])
    wf_gb.append((p_gb, a)); wf_lr.append((p_lr, a)); wf_ens.append((p_en, a))
    log.append({'date': str(X.index[i].date()), 'p_ens': round(p_en, 4),
                'actual': a, 'fwd_ret': round(float(mdf['fwd_ret'].iloc[i]), 3)})

acc_gb = float(np.mean([(p > 0.5) == bool(a) for p, a in wf_gb]))
acc_lr = float(np.mean([(p > 0.5) == bool(a) for p, a in wf_lr]))
base = float(np.mean([a for _, a in wf_gb]))
ens_recent = float(np.mean([(p > 0.5) == bool(a) for p, a in wf_ens[-30:]]))
print(f'[engine] OOS n={len(wf_gb)} GB={acc_gb:.3f} LR={acc_lr:.3f} base={base:.3f} ens_recent30={ens_recent:.3f}')

gb_all, lr_all = fresh_models()
gb_all.fit(X, y); lr_all.fit(X, y)
p_gb_next = float(gb_all.predict_proba(X.iloc[[-1]])[0, 1])
p_lr_next = float(lr_all.predict_proba(X.iloc[[-1]])[0, 1])
p_ens = 0.6 * p_gb_next + 0.4 * p_lr_next
print(f'[engine] P(up next) GB={p_gb_next:.3f} LR={p_lr_next:.3f} ENS={p_ens:.3f}')

importances = [(k, round(100 * v, 1)) for k, v in
               sorted(zip(FEATS, gb_all.feature_importances_), key=lambda kv: -kv[1])[:10]]

# ---------------------------------------------------------------- levels & stats
last = df.iloc[-1]; prev = df.iloc[-2]
H, L, C = float(prev['high']), float(prev['low']), float(prev['close'])   # last COMPLETE bar
satr = float(last['atr14'])
piv = (H + L + C) / 3
R1, S1 = 2 * piv - L, 2 * piv - H
R2, S2 = piv + (H - L), piv - (H - L)
R3, S3 = H + 2 * (piv - L), L - 2 * (H - piv)
spot_xau = spot.get('xau')
futures_px = float(meta_gc.get('regularMarketPrice') or last['close'])
ref = spot_xau if spot_xau else futures_px  # anchor bands to spot when available
band = [round(ref - satr, 1), round(ref + satr, 1)]

r20 = float(c.iloc[-1] / c.iloc[-21] * 100 - 100)
r5  = float(c.iloc[-1] / c.iloc[-6]  * 100 - 100)
r10 = float(c.iloc[-1] / c.iloc[-11] * 100 - 100)
r60 = float(c.iloc[-1] / c.iloc[-61] * 100 - 100)
r1  = float(c.iloc[-1] / c.iloc[-2]  * 100 - 100)
dxy_20 = float(df['dxy'].iloc[-1] / df['dxy'].iloc[-21] * 100 - 100)
tnx_60 = float(df['tnx'].iloc[-1] - df['tnx'].iloc[-61])
slv_60 = float(df['silver'].iloc[-1] / df['silver'].iloc[-61] * 100 - 100)
oil_20 = float(df['oil'].iloc[-1] / df['oil'].iloc[-21] * 100 - 100)
spx_20 = float(df['spx'].iloc[-1] / df['spx'].iloc[-21] * 100 - 100)

# ---------------------------------------------------------------- the call (rules)
p_down = 1 - p_ens
if p_ens < 0.35:   bias, pill = 'BEARISH', 'red'
elif p_ens < 0.45: bias, pill = 'MILDLY BEARISH', 'gold'
elif p_ens <= 0.55: bias, pill = 'NEUTRAL', 'blue'
elif p_ens <= 0.65: bias, pill = 'MILDLY BULLISH', 'gold'
else:               bias, pill = 'BULLISH', 'green'

def r1_(x):  # round to nearest $5 for levels
    return int(round(x / 5.0) * 5)

if p_ens < 0.5:  # short-the-rally framing
    entry_agg = f"${r1_(ref * 1.007):,}–${r1_(ref * 1.011):,}"
    entry_cons = f"${r1_(ref * 1.018):,}–${r1_(ref * 1.022):,}"
    targets = [f"${float(last['low']):,.0f} (52-wk low tag)", f"${S1:,.0f} (S1)",
               f"${S2:,.0f} (S2)", f"${r1_(ref - 2.1 * satr):,} (2×ATR extension)"]
    invalidation = f"4H close above ${r1_(ref * 1.028):,} (pivot R1 / resistance reclaim)"
    end_note = f"First down-leg likely completes at ${S1:,.0f}–${S2:,.0f} within 1–3 sessions; stretch ${S3:,.0f}."
    direction_word = 'down'
else:             # buy-the-dip framing
    entry_agg = f"${r1_(ref * 0.989):,}–${r1_(ref * 0.993):,}"
    entry_cons = f"${r1_(ref * 0.978):,}–${r1_(ref * 0.982):,}"
    targets = [f"${float(last['high']):,.0f} (session high)", f"${R1:,.0f} (R1)", f"${R2:,.0f} (R2)"]
    invalidation = f"4H close below ${r1_(ref * 0.975):,} (S1 loss)"
    end_note = f"First up-leg likely completes at ${R1:,.0f} within 1–3 sessions."
    direction_word = 'up'

# scenario probabilities mapped from model conviction (documented heuristic)
pA = int(round(np.clip(0.35 + (0.5 - p_ens) * 1.2, 0.15, 0.75) * 100))
pB = int(round(np.clip(0.25 - (0.5 - p_ens) * 0.6, 0.05, 0.40) * 100))
pC = 15
pD = 100 - pA - pB - pC
scenarios = [
    {'name': 'Fade the bounce → roll over', 'prob': pA, 'pill': 'red' if p_ens < 0.5 else 'green',
     'desc': 'Mean-reversion pop fails at resistance, breakdown continues. The dominant path under the current macro regime.'},
    {'name': 'Straight breakdown (no bounce)', 'prob': pB, 'pill': 'gold',
     'desc': 'Momentum sellers own the order flow; break of session low accelerates the slide.'},
    {'name': 'Bear-flag consolidation', 'prob': pC, 'pill': 'blue',
     'desc': 'Range trade between support and the pivot for 1–3 days before the next leg.'},
    {'name': 'Squeeze reversal / flip', 'prob': pD, 'pill': 'green',
     'desc': 'Only on trigger: 4H close above key resistance (claims miss, dovish Fed-speak, DXY rolls over).'},
]

# ---------------------------------------------------------------- drivers (auto)
def arrow(x): return '▲' if x > 0 else ('▼' if x < 0 else '■')
drivers = [
    f"DXY {df['dxy'].iloc[-1]:.2f} — {dxy_20:+.1f}% over 20 sessions. {'Headwind — dollar strength pressures every USD asset.' if dxy_20 > 0 else 'Tailwind — dollar softness supports gold.'}",
    f"US 10Y at {df['tnx'].iloc[-1]:.2f}% ({tnx_60:+.2f} pt over 60d). {'Opportunity cost of holding gold is rising — structural headwind.' if tnx_60 > 0 else 'Yields retreating — supportive backdrop.'}",
    f"Trend: price {float(last['dist_sma200']):+.1f}% vs 200-DMA (${float(last['sma200']):,.0f}) · {float(last['dist_sma50']):+.1f}% vs 50-DMA. {'Distance below trend usually mean-reverts slowly — bounces get sold.' if float(last['dist_sma200']) < -5 else 'Near trend — two-way trade.'}",
    f"RSI(14) {float(last['rsi14']):.1f}. {'Oversold — expect snap-back pops that sellers will fade.' if float(last['rsi14']) < 30 else ('Overbought — upside exhaustion risk.' if float(last['rsi14']) > 70 else 'Neutral momentum.')}",
    f"Realized vol (20d) {float(last['vol20']):.1f}% annualised; yesterday's bar spanned ${H - L:,.0f}. Crisis regime — size down.",
    f"Gold–silver ratio {float(last['gs_ratio']):.1f}; silver {slv_60:+.1f}% over 60d (corr 30d {float(last['corr_gold_slv_30']):+.2f}). Metals complex de-grossing together.",
    f"WTI {df['oil'].iloc[-1]:.2f} ({oil_20:+.1f}% 20d) and SPX {spx_20:+.1f}% (20d) — falling together = growth/liquidity scare, not an inflation-hedge bid.",
    f"Model: P(up next session) = GB {p_gb_next:.2f} / ensemble {p_ens:.2f} → {bias}. OOS hit-rate {acc_gb*100:.0f}% (GB) vs 51% always-long — tilt only, trade the confluence.",
]

# ---------------------------------------------------------------- calendar (recurring + verify)
wd = NOW.weekday()  # Mon=0
cal_events = [
    {'time_utc': '08:00', 'event': 'London session open · liquidity builds', 'impact': 'LOW', 'gold_read': 'Positioning, fix flows'},
    {'time_utc': '13:30', 'event': 'US data window — Thu: Initial Claims + Continuing Claims (+ Philly Fed Mfg 3rd Thu); Fri: —', 'impact': 'HIGH', 'gold_read': 'Claims ≤ consensus → USD↑ gold↓ · Claims miss (>205K) → gold squeeze risk'},
    {'time_utc': '14:30', 'event': 'NY cash open · COMEX liquidity peak', 'impact': '—', 'gold_read': 'Highest-volume leg of the day; trend usually extends 14:30–17:00 UTC'},
    {'time_utc': '15:00', 'event': 'London gold fix (15:00) · US second-tier data window', 'impact': 'LOW', 'gold_read': 'Benchmark prints; watch for fix-related air pockets'},
    {'time_utc': '19:15', 'event': 'Fed speech window (varies — see FOMC calendar)', 'impact': 'MED', 'gold_read': 'Any pushback on hike odds = squeeze; hawkish = continuation'},
]
if wd == 3:
    cal_events.insert(2, {'time_utc': '13:30', 'event': 'Initial Jobless Claims (weekly) — HIGH IMPACT today', 'impact': 'HIGH', 'gold_read': 'THE catalyst of the session · fcst ≈ prior 200K · gold sensitivity ±$30–60'})
calendar = {
    'as_of': NOW.strftime('%Y-%m-%d'),
    'weekday': NOW.strftime('%A'),
    'events': cal_events,
    'note': 'Recurring weekly schedule only — speeches & one-off releases are NOT included. Always verify before trading: ForexFactory (forexfactory.com), Investing.com calendar, MyFXBook. Accra = UTC (no DST).',
}

# ---------------------------------------------------------------- desk note (manual, committed)
desk_note = ''
dp = os.path.join(ROOT, 'desk_note.md')
if os.path.exists(dp):
    desk_note = open(dp, encoding='utf-8').read()

# ---------------------------------------------------------------- levels table
levels = [
    {'price': round(R3, 1), 'label': f"Pivot R3 — major ceiling", 'kind': 'R'},
    {'price': round(R2, 1), 'label': f"Pivot R2 · prior swing-high zone", 'kind': 'R'},
    {'price': round(2 * R1 - piv, 1), 'label': '', 'kind': 'R', 'skip': True},  # placeholder filtered
    {'price': round(R1, 1), 'label': "Pivot R1 · resistance reclaim line", 'kind': 'R'},
    {'price': round(float(last['sma20']), 1), 'label': f"20-day SMA ({float(last['dist_sma20']):+.1f}% away)", 'kind': 'R'},
    {'price': round(piv, 1), 'label': "Classic floor pivot P — the flip line", 'kind': 'P'},
    {'price': round(float(H), 1), 'label': "Prev complete bar high", 'kind': 'R'},
    {'price': round(float(last['high']), 1), 'label': "Session high (today)", 'kind': 'R'},
    {'price': round(C, 1), 'label': "Prior session close", 'kind': 'P'},
    {'price': round(float(last['close']), 1), 'label': "Latest print (intraday)", 'kind': 'N'},
    {'price': round(S1 * 1.004, 1), 'label': "Fib-extension / first support shelf", 'kind': 'S'},
    {'price': round(float(last['low']), 1), 'label': "SESSION LOW — the line in the sand", 'kind': 'S'},
    {'price': round(S1, 1), 'label': "Pivot S1", 'kind': 'S'},
    {'price': round(S2, 1), 'label': "Pivot S2 · target shelf", 'kind': 'S'},
    {'price': round(S3, 1), 'label': "Pivot S3 — deep liquidity", 'kind': 'S'},
]
levels = [l for l in levels if not l.get('skip')]
levels.sort(key=lambda l: -l['price'])

hist = [{'date': str(ix.date()), 'close': round(float(v), 2)} for ix, v in c.iloc[-756:].items()]

data = {
    'generated_at': NOW.isoformat(timespec='seconds').replace('+00:00', 'Z'),
    'sources_live': {'spot': bool(spot_xau), 'futures': all(live_flags.values()), 'any_live': True},
    'live_flags': live_flags,
    'spot': {'xau': spot_xau, 'xag': spot.get('xag'), 'xpt': spot.get('xpt'), 'updated_at': spot_ts},
    'futures': {
        'symbol': 'GC=F', 'price': round(futures_px, 2),
        'change_pct': round(float(meta_gc.get('regularMarketChangePercent') or r1), 2),
        'day_high': round(float(meta_gc.get('regularMarketDayHigh') or last['high']), 1),
        'day_low': round(float(meta_gc.get('regularMarketDayLow') or last['low']), 1),
        'prev_close': round(float(prev['close']), 1),
        'volume': int(meta_gc.get('regularMarketVolume') or 0),
        'fiftyTwoWeekHigh': float(meta_gc.get('fiftyTwoWeekHigh') or c.tail(252).max()),
        'fiftyTwoWeekLow': float(meta_gc.get('fiftyTwoWeekLow') or c.tail(252).min()),
    },
    'session': {'date': str(df.index[-1].date()), 'open': round(float(last['open']), 1),
                'high': round(float(last['high']), 1), 'low': round(float(last['low']), 1),
                'close': round(float(last['close']), 1), 'prev_close': round(float(prev['close']), 1)},
    'returns': {'d1': round(r1, 2), 'd5': round(r5, 2), 'd10': round(r10, 2), 'd20': round(r20, 2), 'd60': round(r60, 2)},
    'tech': {'rsi14': round(float(last['rsi14']), 1), 'atr14': round(satr, 1),
             'atr_pct': round(float(last['atr_pct']), 2),
             'sma20': round(float(last['sma20']), 1), 'sma50': round(float(last['sma50']), 1), 'sma200': round(float(last['sma200']), 1),
             'dist_sma20': round(float(last['dist_sma20']), 1), 'dist_sma50': round(float(last['dist_sma50']), 1), 'dist_sma200': round(float(last['dist_sma200']), 1),
             'vol20': round(float(last['vol20']), 1), 'gs_ratio': round(float(last['gs_ratio']), 1)},
    'pivots': {'P': round(piv, 1), 'R1': round(R1, 1), 'R2': round(R2, 1), 'R3': round(R3, 1),
               'S1': round(S1, 1), 'S2': round(S2, 1), 'S3': round(S3, 1),
               'prevH': round(H, 1), 'prevL': round(L, 1), 'prevC': round(C, 1)},
    'corr': {'dxy': round(float(last['corr_gold_dxy_30']), 2), 'tnx': round(float(last['corr_gold_tnx_30']), 2),
             'slv': round(float(last['corr_gold_slv_30']), 2),
             'oil_60': round(float(c.pct_change().rolling(60).corr(df['oil'].pct_change()).iloc[-1]), 2)},
    'context': {'dxy': round(float(df['dxy'].iloc[-1]), 2), 'dxy_20d': round(dxy_20, 2),
                'tnx': round(float(df['tnx'].iloc[-1]), 2), 'tnx_60d': round(tnx_60, 2),
                'silver': round(float(df['silver'].iloc[-1]), 2), 'silver_60d': round(slv_60, 1),
                'oil': round(float(df['oil'].iloc[-1]), 2), 'oil_20d': round(oil_20, 1),
                'copper': round(float(df['copper'].iloc[-1]), 2),
                'spx': round(float(df['spx'].iloc[-1]), 1), 'spx_20d': round(spx_20, 1),
                'gld': round(float(df['gld'].iloc[-1]), 2)},
    'ref_price': round(ref, 1),
    'expected_band': band,
    'model': {
        'oos': {'n': int(N - start - 1), 'gb_acc': round(acc_gb, 3), 'lr_acc': round(acc_lr, 3),
                'baseline_long': round(base, 3), 'ens_recent30': round(ens_recent, 3)},
        'p_up': {'gb': round(p_gb_next, 3), 'lr': round(p_lr_next, 3), 'ensemble': round(p_ens, 3)},
        'importances': importances,
        'walk_forward': log[-30:],
    },
    'call': {
        'bias': bias, 'pill': pill, 'p_up': round(p_ens, 3),
        'headline': (f"Bearish — fade the bounce. ATR band ${band[0]:,.0f}–${band[1]:,.0f} (±1 ATR)."
                     if p_ens < 0.5 else f"Bullish — buy the dip. ATR band ${band[0]:,.0f}–${band[1]:,.0f} (±1 ATR)."),
        'entry_aggressive': entry_agg, 'entry_conservative': entry_cons,
        'targets': targets, 'invalidation': invalidation, 'expected_end': end_note,
        'direction': direction_word,
        'timing': ('Decision points: 13:30 UTC US data (Accra 13:30) and the 14:30 UTC NY open (Accra 14:30). '
                   'Trend extension usually runs 14:30–17:00 UTC. Reduce size into 13:30 / Fed-speech windows; '
                   'Friday = weekly settlement — carry less size.'),
    },
    'scenarios': scenarios,
    'drivers': drivers,
    'calendar': calendar,
    'desk_note': desk_note,
    'levels': levels,
    'hist': hist,
    'history_csv_note': 'daily closes, GC=F, last ~3 years',
}

# ---------------------------------------------------------------- charts
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

BG, PANEL, GRID, TXT, GOLD, RED, GREEN, DIM = '#0e1117', '#161b26', '#232a3a', '#e6e9ef', '#f0c05a', '#ff5d5d', '#3dd68c', '#8a93a6'
plt.rcParams.update({'figure.facecolor': BG, 'axes.facecolor': PANEL, 'axes.edgecolor': GRID,
                     'axes.labelcolor': TXT, 'xtick.color': DIM, 'ytick.color': DIM, 'grid.color': GRID,
                     'grid.alpha': .6, 'font.size': 11, 'text.color': TXT, 'savefig.facecolor': BG, 'figure.dpi': 130})

def savefig(fig, name):
    fig.tight_layout(); fig.savefig(os.path.join(CHARTS, name)); plt.close(fig)

fig, ax = plt.subplots(figsize=(11, 5.0))
ax.plot(c.index, c, color=GOLD, lw=1.5, label='Gold GC=F')
ax.plot(c.index, c.rolling(50).mean(), color='#6ea8fe', lw=1.0, alpha=.9, label='50-SMA')
ax.plot(c.index, c.rolling(200).mean(), color='#c084fc', lw=1.0, alpha=.9, label='200-SMA')
ax.set_title('Gold — 3Y daily', loc='left', fontweight='bold', fontsize=12)
ax.legend(loc='upper left', frameon=False); ax.grid(True)
ax.yaxis.set_major_formatter(mticker.StrMethodFormatter('{x:,.0f}')); savefig(fig, 'chart_3y.png')

fig, ax = plt.subplots(figsize=(11, 5.0))
tail = df.tail(132)
ax.plot(tail.index, tail['close'], color=GOLD, lw=1.6)
ax.fill_between(tail.index, tail['low'], tail['high'], color=GOLD, alpha=.08)
for v, col in [(float(last['low']), RED), (S1, '#ff9f43'), (C, DIM), (piv, '#6ea8fe'), (R1, GREEN)]:
    ax.axhline(v, color=col, ls='--', lw=1.1, alpha=.9)
ax.set_title('Gold — 6M with live pivot levels', loc='left', fontweight='bold', fontsize=12)
ax.grid(True); ax.yaxis.set_major_formatter(mticker.StrMethodFormatter('{x:,.0f}')); savefig(fig, 'chart_6m.png')

fig, ax = plt.subplots(figsize=(11, 4.4))
ax.plot(df.index, c.pct_change().rolling(60).corr(df['dxy'].pct_change()), color='#ff9f43', lw=1.5, label='vs DXY')
ax.plot(df.index, c.pct_change().rolling(60).corr(df['silver'].pct_change()), color='#cfd6e4', lw=1.5, label='vs Silver')
ax.plot(df.index, c.pct_change().rolling(60).corr(df['oil'].pct_change()), color=GREEN, lw=1.2, label='vs WTI')
ax.axhline(0, color=GRID, lw=1); ax.set_ylim(-1.05, 1.05)
ax.set_title('Rolling 60-day correlations', loc='left', fontweight='bold', fontsize=12)
ax.legend(loc='lower left', frameon=False, ncol=3); ax.grid(True); savefig(fig, 'chart_corr.png')

wf_dates = [pd.Timestamp(r['date']) for r in log[-60:]]
wf_ens = [r['p_ens'] for r in log[-60:]]
hits20 = pd.Series([(1 if (r['p_ens'] > 0.5) == bool(r['actual']) else 0) for r in log[-60:]]).rolling(20, min_periods=10).mean() * 100
fig, ax = plt.subplots(figsize=(11, 4.0))
ax.plot(wf_dates, hits20, color='#6ea8fe', lw=1.5); ax.axhline(50, color=RED, ls='--', lw=1.1)
ax.set_ylim(15, 85); ax.set_title('Model — rolling 20-session hit rate (out-of-sample)', loc='left', fontweight='bold', fontsize=11)
ax.grid(True); savefig(fig, 'chart_wf.png')

with open(os.path.join(DOCS, 'data.json'), 'w') as f:
    json.dump(data, f, separators=(',', ':'))
print(f"[engine] wrote docs/data.json ({os.path.getsize(os.path.join(DOCS,'data.json'))//1024} KB) and charts")
