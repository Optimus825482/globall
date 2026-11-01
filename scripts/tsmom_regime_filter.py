"""TSMOM + BTC rejim filtresi: ayi piyasasinda tamamen flat kal."""
import json, urllib.request, numpy as np, datetime as dt

FEE=0.15
SYMS=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','ADAUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT','DOTUSDT']

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

def tsmom_regime(C, BTC, lookback=30, fee=FEE, use_regime=True):
    """TSMOM + opsiyonel BTC MA200 rejim filtresi. BTC: (T, C) hizalanmis."""
    n=len(C); rets=np.diff(C)/C[:-1]
    pos=np.zeros(n)
    for t in range(max(lookback,30,200), n-1):
        if use_regime:
            if BTC[t] <= BTC[t-200:t].mean():
                pos[t]=0.0
                continue
        past=C[t-lookback:t+1]
        sig=1.0 if past[-1]>past[0] else 0.0
        recent=rets[t-30:t]
        if len(recent)<5: continue
        rv=float(np.std(recent))*np.sqrt(365)
        if rv<=1e-9: continue
        pos[t]=sig*min(1.0,0.20/rv)
    net=np.zeros(n)
    for t in range(n-1):
        turn=abs(pos[t]-(pos[t-1] if t>0 else 0.0))
        net[t+1]=pos[t]*rets[t]-turn*fee/100
    return net[1:]

def stats(r):
    if len(r)<10: return None
    ar=float(np.mean(r))*365; av=float(np.std(r,ddof=1))*np.sqrt(365)
    eq=np.cumprod(1+r); peak=np.maximum.accumulate(eq); dd=eq/peak-1
    return {'total':(eq[-1]-1)*100,'sharpe':ar/av if av>0 else 0,
            'dd':dd.min()*100,'n':len(r),'pos':(eq[-1]>1)}

print("veri...", flush=True)
D={}
for s in SYMS:
    k=fetch(s)
    if len(k)<400: continue
    D[s]={'C':np.array([float(x[4]) for x in k]),'T':np.array([int(x[0]) for x in k])}

# BTC referans serisi, en kisa sembolle hizala
minlen=min(len(d['C']) for d in D.values())
btc=D['BTCUSDT']['C'][-minlen:]

print()
print("="*88)
print("TSMOM: REJIM FILTRESIZ vs FILTRELI (BTC>MA200)")
print("="*88)
print("%-16s %8s %9s %9s %9s %8s" % ("senaryo","toplam%","yillik%","Sharpe","maxDD%","pozCoin"))
print("-"*88)

for label, use_reg in (("FILTRESIZ", False), ("REJIM FILTRELI", True)):
    agg=[]; cp=0; cn=0
    for s,d in D.items():
        C=d['C'][-minlen:]
        r=tsmom_regime(C, btc, 30, use_regime=use_reg)
        st=stats(r)
        if not st: continue
        agg.append(st); cn+=1; cp += st['pos']
    if agg:
        print("%-16s %+8.1f %+8.1f %9.2f %+9.1f %6d/%d" % (
            label, np.mean([a['total'] for a in agg]),
            np.mean([a['total'] for a in agg])/(minlen/365.0),
            np.mean([a['sharpe'] for a in agg]),
            np.mean([a['dd'] for a in agg]), cp, cn))

print()
print("="*88)
print("PORTFOY (esit agirlikli 10 sembol)")
print("="*88)
for label, use_reg in (("FILTRESIZ", False), ("REJIM FILTRELI", True)):
    rets_all=[]
    for s,d in D.items():
        C=d['C'][-minlen:]
        rets_all.append(tsmom_regime(C, btc, 30, use_regime=use_reg))
    n=min(len(x) for x in rets_all)
    port=np.mean([x[:n] for x in rets_all], axis=0)
    st=stats(port)
    print("%-16s toplam %+9.2f%%  Sharpe %5.2f  maxDD %+7.2f%%  kazanan gun %.1f%%" % (
        label, st['total'], st['sharpe'], st['dd'], (port>0).mean()*100))

# BTC buy&hold kiyas
bh=np.diff(btc)/btc[:-1]
st=stats(bh)
print("%-16s toplam %+9.2f%%  Sharpe %5.2f  maxDD %+7.2f%%" % ("BTC BUY&HOLD", st['total'], st['sharpe'], st['dd']))
