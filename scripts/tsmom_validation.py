"""TSMOM dayaniklilik: ayi piyasasi + walk-forward + donem tutarliligi."""
import json, urllib.request, numpy as np, datetime as dt

FEE = 0.15
SYMS = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT',
        'DOGEUSDT','LINKUSDT','AVAXUSDT','DOTUSDT']

def fetch(sym, days=2600):
    out=[]; end=None
    while len(out)<days:
        q=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit=1000"
        if end: q+=f"&endTime={end}"
        req=urllib.request.Request(q,headers={"User-Agent":"Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req,timeout=25) as r: k=json.loads(r.read().decode())
        except Exception: break
        if not k: break
        out=k+out; end=int(k[0][0])-1
        if len(k)<1000: break
    return out[-days:]

def tsmom(C, T, lookback, fee=FEE):
    n=len(C); rets=np.diff(C)/C[:-1]
    pos=np.zeros(n); prev=0.0
    for t in range(max(lookback,30), n-1):
        past=C[t-lookback:t+1]
        sig=1.0 if past[-1]>past[0] else 0.0
        recent=rets[t-30:t]
        if len(recent)<5: continue
        rv=float(np.std(recent))*np.sqrt(365)
        if rv<=1e-9: continue
        pos[t]=sig*min(1.0, 0.20/rv)
    net=np.zeros(n)
    for t in range(n-1):
        turn=abs(pos[t]-(pos[t-1] if t>0 else 0.0))
        net[t+1]=pos[t]*rets[t]-turn*fee/100
    return net[1:], T[1:]

def stats(r):
    if len(r)<10: return None
    ar=float(np.mean(r))*365; av=float(np.std(r,ddof=1))*np.sqrt(365)
    eq=np.cumprod(1+r); peak=np.maximum.accumulate(eq); dd=eq/peak-1
    return {'total':(eq[-1]-1)*100,'ann':ar*100,'sharpe':ar/av if av>0 else 0,
            'dd':dd.min()*100,'n':len(r),
            'tstat': float(np.mean(r)/(np.std(r,ddof=1)/np.sqrt(len(r)))) if np.std(r,ddof=1)>0 else 0}

print("veri cekiliyor...", flush=True)
DATA={}
for s in SYMS:
    k=fetch(s)
    if len(k)<400: continue
    DATA[s]={'C':np.array([float(x[4]) for x in k]),
             'T':np.array([int(x[0]) for x in k])}
print(f"{len(DATA)} sembol, en uzun {max(len(d['C']) for d in DATA.values())} gun")

# Donem tanimlari (BTC referans)
btc=DATA['BTCUSDT']
t0=dt.datetime.utcfromtimestamp(btc['T'][0]/1000)
t1=dt.datetime.utcfromtimestamp(btc['T'][-1]/1000)
print(f"aralik: {t0:%Y-%m-%d} -> {t1:%Y-%m-%d}")

# BTC'nin 200 gunluk ortalamasina gore rejim
def regime_mask(C, T, win=200):
    n=len(C); out=np.zeros(n,dtype=bool)
    for i in range(win,n):
        out[i]= C[i] > C[i-win:i].mean()
    return out

print()
print("="*84)
print("1) REJIM TESTI: BULL vs BEAR ayri ayri")
print("="*84)
print("%-12s %6s %9s %9s %8s %8s" % ("rejim","gun","toplam%","Sharpe","maxDD%","pozCoin"))
print("-"*84)
for label, want_bull in (("BULL (BTC>MA200)", True), ("BEAR (BTC<MA200)", False)):
    agg=[]; coins_pos=0; coins_n=0; days_total=0
    for s,d in DATA.items():
        C,T=d['C'],d['T']
        reg=regime_mask(C,T,200)
        r,ts = tsmom(C,T,30)
        # tsmom() net[1:] ve T[1:] dondurur -> ikisi ayni uzunlukta (n-1).
        # Rejim maskesi n elemanli, o yuzden reg[1:] ile hizalanir.
        m = reg[1:1+len(r)]
        sel = r[m] if want_bull else r[~m]
        st=stats(sel)
        if not st: continue
        coins_n+=1
        if st['total']>0: coins_pos+=1
        agg.append(st); days_total+=st['n']
    if agg:
        print("%-12s %6d %+8.1f %8.2f %+8.1f %6d/%d" % (
            label, days_total, np.mean([a['total'] for a in agg]),
            np.mean([a['sharpe'] for a in agg]),
            np.mean([a['dd'] for a in agg]), coins_pos, coins_n))

print()
print("="*84)
print("2) WALK-FORWARD: 6 ay egitim / 6 ay test, kayan")
print("="*84)
print("%-22s %8s %9s %9s" % ("pencere","gun","Sharpe","toplam%"))
print("-"*84)
# BTC uzerinde zaman pencereleri
C,T=btc['C'],btc['T']
r,ts=tsmom(C,T,30)
n=len(r)
win=180  # ~6 ay
wins=[]
for start in range(0, n-win, win):
    seg=r[start:start+win]
    st=stats(seg)
    if st: wins.append((start,st))
for i,(start,st) in enumerate(wins):
    s0=dt.datetime.utcfromtimestamp(ts[start]/1000)
    print("%-22s %8d %9.2f %+9.2f" % (f"W{i+1} {s0:%Y-%m}", st['n'], st['sharpe'], st['total']))
if wins:
    pos=sum(1 for _,s in wins if s['sharpe']>0)
    print("-"*84)
    print("pozitif pencere: %d/%d  |  ortalama Sharpe %.2f" % (
        pos, len(wins), np.mean([s['sharpe'] for _,s in wins])))

print()
print("="*84)
print("3) TUTARLILIK: ayni strateji, farkli bakis uzunluklari")
print("="*84)
print("%-10s %9s %9s %9s %8s" % ("bakış","toplam%","Sharpe","maxDD%","pozCoin"))
print("-"*84)
for lb in (10,20,30,45,60,90,120):
    agg=[]; cp=0; cn=0
    for s,d in DATA.items():
        rr,tt=tsmom(d['C'],d['T'],lb)
        st=stats(rr)
        if st: agg.append(st); cn+=1; cp += (st['total']>0)
    if agg:
        print("%-10d %+8.1f %9.2f %+9.1f %6d/%d" % (
            lb, np.mean([a['total'] for a in agg]),
            np.mean([a['sharpe'] for a in agg]),
            np.mean([a['dd'] for a in agg]), cp, cn))
