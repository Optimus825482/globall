# -*- coding: utf-8 -*-
"""CSV işlemlerine Yahoo 5m mumlarıyla MFE/MAE analizi: kâr geri verme miktarı.

Her işlem için giriş→çıkış arasındaki 5m barlardan:
  MFE = maksimum lehte hareket (pip), MAE = maksimum aleyhte hareket (pip)
"Kâr geri verme" = MFE − gerçekleşen pip. Bu, MOMFLIP/chandelier'in ne kurtaracağını gösterir.
"""
import csv
import json
import urllib.request
from datetime import datetime, timezone

PATH = r"D:\scalperagent_global\forex_scalper_islemler_2026-10-07.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

PIP_SIZE = {"XAUUSD": 0.1, "BTCUSD": 1.0, "ETHUSD": 0.1, "NAS100": 1.0, "US30": 1.0,
            "USDJPY": 0.01, "EURUSD": 0.0001, "GBPUSD": 0.0001, "USDCHF": 0.0001, "USDCAD": 0.0001}


def fetch(sym: str, days: int = 6):
    yf = {"XAUUSD": "GC=F", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
          "NAS100": "^NDX", "US30": "^DJI", "USDJPY": "JPY=X",
          "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDCHF": "CHF=X", "USDCAD": "CAD=X"}[sym]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf}?interval=5m&range={days}d"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(res.get("timestamp", [])):
        h, l = q.get("high", [])[i], q.get("low", [])[i]
        if h is None or l is None:
            continue
        bars.append((ts, h, l))
    return bars


rows = []
with open(PATH, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f, delimiter=";"):
        reason = r["Çıkış Nedeni"]
        if not any(x in reason for x in ("Scalper", "Zarar Durdur", "Kâr Al")):
            continue
        t_in = datetime.strptime(r["Giriş Zamanı (UTC+3)"].split(" UTC+3")[0], "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=timezone.utc)
        t_out = datetime.strptime(r["Çıkış Zamanı (UTC+3)"].split(" UTC+3")[0], "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=timezone.utc)
        rows.append({
            "sym": r["Sembol"], "dir": r["Yön"],
            "lot": float(r["Lot"].replace(",", ".")),
            "entry": float(r["Giriş Fiyatı"]), "exit": float(r["Çıkış Fiyatı"]),
            "t_in": t_in.timestamp(), "t_out": t_out.timestamp(),
            "pips": float(r["Kâr/Zarar (Pip)"].replace("+", "")),
            "usd": float(r["Net Getiri (USD)"].replace("+", "")),
            "win": r["Sonuç"].startswith("KAZANÇ"),
        })

caches = {}
for sym in {r["sym"] for r in rows} & set(PIP_SIZE):
    try:
        caches[sym] = fetch(sym)
        print(f"[VERI] {sym}: {len(caches[sym])} bar")
    except Exception as e:
        print(f"[VERI HATASI] {sym}: {e}")

print(f"\n{'Sembol':<7} {'Zaman':<11} {'Yön':<4} {'MFE':>7} {'MAE':>7} {'Net':>7} {'GeriVer':>8} {'Sonuç'}")
PIP_VAL = {"XAUUSD": 10.0, "BTCUSD": 0.62, "ETHUSD": 0.1, "NAS100": 1.0, "US30": 1.0,
           "USDJPY": 6.7, "EURUSD": 10.0, "GBPUSD": 10.0, "USDCHF": 11.5, "USDCAD": 7.3}

giveback_usd_total = 0.0
giveback_trades = 0
big_givebacks = []
for r in sorted(rows, key=lambda x: x["t_in"]):
    bars = caches.get(r["sym"])
    ps = PIP_SIZE.get(r["sym"], 0.0001)
    if not bars:
        continue
    win = [b for b in bars if r["t_in"] - 120 <= b[0] <= r["t_out"] + 120]
    if len(win) < 2:
        continue
    if r["dir"] == "BUY":
        mfe = (max(b[1] for b in win) - r["entry"]) / ps
        mae = (r["entry"] - min(b[2] for b in win)) / ps
    else:
        mfe = (r["entry"] - min(b[2] for b in win)) / ps
        mae = (max(b[1] for b in win) - r["entry"]) / ps
    gave = mfe - r["pips"]
    if gave > 15:
        giveback_trades += 1
        gb_usd = gave * r["lot"] * PIP_VAL.get(r["sym"], 1.0)
        giveback_usd_total += gb_usd
        if gave > 25:
            big_givebacks.append((r, mfe, mae, gave, gb_usd))
        tag = " ***" if gave > 40 else ""
        print(f"{r['sym']:<7} {datetime.fromtimestamp(r['t_in'], tz=timezone.utc) - __import__('datetime').timedelta(hours=3):%d %H:%M}  {r['dir']:<4} "
              f"{mfe:>7.1f} {mae:>7.1f} {r['pips']:>7.1f} {gave:>8.1f} {'KAR' if r['win'] else 'ZARAR'}{tag}")

print(f"\n→ MFE'den ≥15 pip geri veren işlem: {giveback_trades}/{len(rows)}")
print(f"→ Tahmini geri verilen toplam değer: ${giveback_usd_total:+.2f}")
print("\n=== EN BÜYÜK 12 GERİ VERME (MFE−gerçekleşen > 25 pip) ===")
for r, mfe, mae, gave, gb in sorted(big_givebacks, key=lambda x: -x[4])[:12]:
    print(f"  {r['sym']:<7} {datetime.fromtimestamp(r['t_in']):%d %H:%M} {r['dir']:<4} "
          f"MFE={mfe:>6.1f} pip | kapanış={r['pips']:>6.1f} pip | geri verilen={gave:>6.1f} pip ≈ ${gb:>7.2f} "
          f"({'kâr' if r['win'] else 'ZARAR'} ile kapandı)")
