# -*- coding: utf-8 -*-
"""forex_scalper_islemler_2026-10-07.csv analiz: kâr geri verme + kayıp kümeleri."""
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime

PATH = r"D:\scalperagent_global\forex_scalper_islemler_2026-10-07.csv"

SCALPER_REASONS = ("Scalper", "Zarar Durdur", "Kâr Al", "Kısmi")
MANUAL = ("IC Markets MT5",)

rows = []
with open(PATH, encoding="utf-8-sig") as f:
    rdr = csv.DictReader(f, delimiter=";")
    for r in rdr:
        t_in = datetime.strptime(r["Giriş Zamanı (UTC+3)"].split(" UTC+3")[0], "%Y-%m-%d %H:%M:%S")
        t_out = datetime.strptime(r["Çıkış Zamanı (UTC+3)"].split(" UTC+3")[0], "%Y-%m-%d %H:%M:%S")
        dur = r["Süre"]
        m = re.match(r"(?:(\d+) dk )?(\d+) sn", dur)
        mins = (int(m.group(1) or 0) * 60 + int(m.group(2))) / 60.0
        rows.append({
            "ticket": r["Bilet No"],
            "sym": r["Sembol"],
            "dir": r["Yön"],
            "lot": float(r["Lot"].replace(",", ".")),
            "entry": float(r["Giriş Fiyatı"]),
            "exit": float(r["Çıkış Fiyatı"]),
            "t_in": t_in,
            "t_out": t_out,
            "mins": mins,
            "reason": r["Çıkış Nedeni"],
            "pips": float(r["Kâr/Zarar (Pip)"].replace("+", "")),
            "usd": float(r["Net Getiri (USD)"].replace("+", "")),
            "win": r["Sonuç"].startswith("KAZANÇ"),
            "scalper": any(x in r["Çıkış Nedeni"] for x in SCALPER_REASONS),
        })

print(f"TOPLAM satır: {len(rows)}  | scalper kaynaklı: {sum(1 for r in rows if r['scalper'])}  | manuel/MT5: {sum(1 for r in rows if not r['scalper'])}")

# --- 1. Genel özet (scalper işlemi) ---
sc = [r for r in rows if r["scalper"]]
print("\n=== SCALPER İŞLEMLERİ ÖZET ===")
print(f"n={len(sc)}  net=${sum(r['usd'] for r in sc):+.2f}  WR={100*sum(r['win'] for r in sc)/len(sc):.1f}%")

by_sym = defaultdict(list)
for r in sc:
    by_sym[r["sym"]].append(r)
print("\nSembol bazında:")
print(f"{'Sembol':<8} {'n':>4} {'net$':>9} {'WR%':>6} {'avgWin$':>8} {'avgLoss$':>9} {'medSüre(dk)':>11}")
for sym in sorted(by_sym, key=lambda s: -abs(sum(r['usd'] for r in by_sym[s]))):
    ts = by_sym[sym]
    wins = [r["usd"] for r in ts if r["usd"] > 0]
    losses = [r["usd"] for r in ts if r["usd"] <= 0]
    print(f"{sym:<8} {len(ts):>4} {sum(r['usd'] for r in ts):>+9.2f} "
          f"{100*len(wins)/len(ts):>6.1f} {sum(wins)/max(1,len(wins)):>8.2f} {sum(losses)/max(1,len(losses)):>9.2f} "
          f"{sorted(r['mins'] for r in ts)[len(ts)//2]:>11.1f}")

# Yön kırılımı
print("\nYön bazında (scalper):")
for d in ("BUY", "SELL"):
    ts = [r for r in sc if r["dir"] == d]
    if not ts:
        continue
    wins = [r["usd"] for r in ts if r["usd"] > 0]
    print(f"  {d}: n={len(ts)} net=${sum(r['usd'] for r in ts):+.2f} WR={100*len(wins)/len(ts):.1f}% "
          f"avgWin=${sum(wins)/max(1,len(wins)):.2f} avgLoss=${sum(r['usd'] for r in ts if r['usd']<=0)/max(1,len(ts)-len(wins)):.2f}")

# --- 2. Kayıp kümeleri: aynı sembolde üst üste zarar (trend dönüşü/düzeltme kanıtı) ---
print("\n=== KAYIP KÜMELERİ (aynı sembol, ardışık zararlar, ≤40 dk arayla) ===")
for sym, ts in by_sym.items():
    ts.sort(key=lambda r: r["t_out"])
    i = 0
    while i < len(ts):
        if ts[i]["usd"] <= 0:
            j = i
            cluster = [ts[i]]
            while j + 1 < len(ts) and ts[j + 1]["usd"] <= 0 and (ts[j + 1]["t_out"] - ts[j]["t_out"]).total_seconds() <= 40 * 60:
                j += 1
                cluster.append(ts[j])
            if len(cluster) >= 2:
                net = sum(r["usd"] for r in cluster)
                t0, t1 = cluster[0]["t_in"], cluster[-1]["t_out"]
                dirs = [r["dir"] for r in cluster]
                # küme öncesi/sonrası yön: kümenin ilk işleminden önceki ve son işleminden sonraki işlem
                idx0 = ts.index(cluster[0])
                idx1 = ts.index(cluster[-1])
                pre = ts[idx0 - 1]["dir"] if idx0 > 0 else "-"
                post = ts[idx1 + 1]["dir"] if idx1 + 1 < len(ts) else "-"
                flip = "FLIP" if (pre != "-" and post != "-" and pre != post) else ""
                print(f"  {sym:<7} {t0:%d %H:%M}→{t1:%H:%M}  n={len(cluster)}  net=${net:+.2f}  yön={dirs[0]}{'(çift yön!)' if len(set(dirs))>1 else ''}  önce={pre} sonra={post} {flip}")
            i = j + 1
        else:
            i += 1

# --- 3. Kâr geri verme proxy: BE/trailing'de kapanan ama sadece küçük kâr kilitleyen işlemler ---
print("\n=== 'GERİ VERME' ŞÜPHELİLERİ (scalper, SL/BE/trail ile kapanıp ≤$20 kilit, süre>10dk) ===")
susp = [r for r in sc if r["win"] and r["mins"] >= 10 and 0 < r["usd"] <= 20]
for r in sorted(susp, key=lambda x: -x["mins"]):
    print(f"  {r['sym']:<7} {r['t_in']:%d %H:%M}→{r['t_out']:%H:%M} {r['mins']:>5.0f}dk {r['dir']:<4} lot={r['lot']:<5} kilit=+{r['usd']:.2f}$ ({r['pips']:+.1f} pip) {r['reason'][:20]}")
tot_lock = sum(r["usd"] for r in susp)
print(f"  → Bu {len(susp)} işlemde toplam kilitlenen: ${tot_lock:+.2f} (uzun bekleyişlerin bedeli)")

# --- 4. Lot büyümesi trendi (risk eskalasyonu) ---
print("\n=== LOT ESKELEASYONU (sembole göre ilk→son 5 işlem ort. lotu) ===")
for sym in ("BTCUSD", "XAUUSD"):
    ts = sorted([r for r in sc if r["sym"] == sym], key=lambda r: r["t_in"])
    n = len(ts)
    chunks = 4
    seg = max(1, n // chunks)
    parts = [ts[i:i + seg] for i in range(0, n, seg)][:chunks]
    print(f"  {sym}: " + " | ".join(f"{sum(x['lot'] for x in p)/len(p):.2f}" for p in parts))

# --- 5. Zaman ekseninde net PnL (30 dk kovalar) ---
print("\n=== 30 DK KOVALAR (net $) — scalper ===")
buckets = defaultdict(float)
for r in sc:
    key = r["t_out"].strftime("%d %H:")
    key += "00" if r["t_out"].minute < 30 else "30"
    buckets[key] += r["usd"]
for k in sorted(buckets, key=lambda x: (x.split()[0], x.split()[1])):
    v = buckets[k]
    bar = "#" * int(min(50, abs(v) / 25))
    print(f"  {k} {v:+9.2f} {'+' if v>=0 else '-'}{bar}")
