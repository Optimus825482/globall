"""TSMOM'u GERCEK gunluk veriyle test et (Binance'ten, yillar)."""
import json, urllib.request, numpy as np, sys

FEE = 0.15

def fetch_daily(sym, days=1500):
    """Binance gunluk mumlar."""
    out = []
    end = None
    while len(out) < days:
        q = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit=1000"
        if end: q += f"&endTime={end}"
        req = urllib.request.Request(q, headers={"User-Agent":"Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                k = json.loads(r.read().decode())
        except Exception as e:
            break
        if not k: break
        out = k + out
        end = int(k[0][0]) - 1
        if len(k) < 1000: break
    return out[-days:]

def tsmom(C, lookback, vol_win=30, vol_target=0.20, fee=FEE):
    n = len(C)
    rets = np.diff(C)/C[:-1]
    pos = np.zeros(n); prev = 0.0; trades = 0
    for t in range(max(lookback, vol_win), n-1):
        past = C[t-lookback:t+1]
        sig = 1.0 if past[-1] > past[0] else 0.0   # spot: long-only
        recent = rets[t-vol_win:t]
        if len(recent) < 5: continue
        rv = float(np.std(recent))*np.sqrt(365)
        if rv <= 1e-9: continue
        lev = min(1.0, vol_target/rv)
        pos[t] = sig*lev
        if abs(pos[t]-prev) > 1e-6: trades += 1; prev = pos[t]
    net = np.zeros(n)
    for t in range(n-1):
        turn = abs(pos[t] - (pos[t-1] if t>0 else 0.0))
        net[t+1] = pos[t]*rets[t] - turn*fee/100
    return net[1:], trades, pos

def stats(r):
    if len(r)==0: return None
    ar = float(np.mean(r))*365; av = float(np.std(r,ddof=1))*np.sqrt(365)
    eq = np.cumprod(1+r); peak = np.maximum.accumulate(eq); dd = eq/peak-1
    return {'total': (eq[-1]-1)*100, 'ann': ar*100, 'vol': av*100,
            'sharpe': ar/av if av>0 else 0, 'dd': dd.min()*100,
            'win': (r>0).mean()*100, 'n': len(r)}

SYMS = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT','DOTUSDT']
print("=== TSMOM -- GERCEK GUNLUK VERI (Binance) ===")
print()
data = {}
for s in SYMS:
    k = fetch_daily(s, 1500)
    if len(k) < 200: 
        print(f'  {s}: yetersiz ({len(k)} gun)'); continue
    data[s] = np.array([float(x[4]) for x in k])
    print(f'  {s}: {len(k)} gun ({k[0][0]//86400000} -> {k[-1][0]//86400000})', flush=True)

print()
print('%-8s %6s | %-34s | %-16s' % ('bakış','', '  TSMOM (spot long-only)','  BUY & HOLD'))
print('%-8s %6s | %8s %7s %8s %9s | %8s %7s' % ('','gun','toplam%','Sharpe','maxDD%','islem','toplam%','Sharpe'))
print('-'*92)
for lb in (10, 20, 30, 60, 120):
    ts_all, bh_all = [], []
    tf_sum = tf_n = 0
    for s, C in data.items():
        r, trades, pos = tsmom(C, lb)
        st = stats(r)
        if not st: continue
        ts_all.append(st); tf_sum += st['total']; tf_n += 1
    if not ts_all: continue
    # portfoy: esit agirlikli
    for s, C in list(data.items())[:1]:
        bh = stats(np.diff(C)/C[:-1])
    print('%-8s %6d | %+8.2f %7.2f %+8.2f %9s | %+8.2f %7.2f' % (
        f'lb={lb}', ts_all[0]['n'], tf_sum/tf_n,
        np.mean([x['sharpe'] for x in ts_all]),
        np.mean([x['dd'] for x in ts_all]),
        '-', bh['total'], bh['sharpe']))
