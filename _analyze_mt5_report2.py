# -*- coding: utf-8 -*-
"""Kapanan pozisyonlari derinlemesine analiz et (kucuk-kar / trailing hipotezi).

Cikti ASCII-guvenli.
"""
import sys
import re
import html as htmllib
from collections import Counter, defaultdict
from datetime import datetime

SRC = sys.argv[1]
txt = open(SRC, "rb").read().decode("utf-16")
rows = re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S)


def cells(row_html):
    out = []
    for m in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S):
        t = re.sub(r"<[^>]+>", "", m.group(1))
        out.append(htmllib.unescape(t).replace("\xa0", " ").strip())
    return out


DATE = re.compile(r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}$")
pos = []
for r in rows:
    c = cells(r)
    if len(c) >= 14 and DATE.match(c[0]) and c[2].isalpha():
        pos.append(c)

print("KAPANAN POZISYON:", len(pos))


def num(s):
    s = (s or "").replace(" ", "").replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def dt(s):
    return datetime.strptime(s, "%Y.%m.%d %H:%M:%S")


recs = []
for c in pos:
    r = {
        "open_t": dt(c[0]), "id": c[1], "sym": c[2], "side": c[3], "comment": c[4],
        "vol": num(c[5]), "open_p": num(c[6]), "sl": num(c[7]), "tp": num(c[8]),
        "close_t": dt(c[9]) if DATE.match(c[9]) else None,
        "close_p": num(c[10]), "comm": num(c[11]), "swap": num(c[12]), "profit": num(c[13]),
    }
    if r["close_t"] and r["profit"] is not None:
        r["mins"] = (r["close_t"] - r["open_t"]).total_seconds() / 60.0
        r["net"] = (r["profit"] or 0) + (r["comm"] or 0) + (r["swap"] or 0)
        recs.append(r)

print("SURESI OLCULEBILEN:", len(recs))

profits = sorted(r["net"] for r in recs)
wins = [p for p in profits if p > 0]
losses = [p for p in profits if p < 0]
zero = [p for p in profits if p == 0]
print()
print("=== KAR DAGILIMI (net, komisyon+swap dahil) ===")
print("  toplam net        : %+.2f" % sum(profits))
print("  kazanan / kaybeden: %d / %d  (basabas %d)" % (len(wins), len(losses), len(zero)))
print("  win rate          : %.1f%%" % (100.0 * len(wins) / len(profits)))
if wins:
    print("  kazanan medyan    : %+.2f" % sorted(wins)[len(wins) // 2])
    print("  kazanan ortalama  : %+.2f" % (sum(wins) / len(wins)))
if losses:
    print("  kaybeden medyan   : %+.2f" % sorted(losses)[len(losses) // 2])
    print("  kaybeden ortalama : %+.2f" % (sum(losses) / len(losses)))

# Kucuk-kar esikleri
print()
print("=== KUCUK KAR ESIKLERI (kazananlar icinde) ===")
for th in (0.5, 1, 2, 5, 10):
    n = sum(1 for p in wins if p < th)
    tot = sum(p for p in wins if p < th)
    print("  net < $%-4s : %4d islem  (%5.1f%% kazanan)  toplam %+8.2f  = tum netin %%%.1f"
          % (th, n, 100.0 * n / len(wins), tot,
             100.0 * tot / sum(profits) if sum(profits) else 0))

# Esik bazli "bu islemler kapansa toplam ne olurdu" — kucuk karlilari cikar
print()
print("=== 'KUCUK KAZANANLARI CIKAR' DUYARLILIK (kaba, gercekci degil ama yon verir) ===")
for th in (0.5, 1, 2, 5):
    kept = [p for p in profits if not (0 < p < th)]
    print("  < $%-4s kazananlari yok say  -> net %+9.2f  (n=%d)" % (th, sum(kept), len(kept)))

# Tutma suresi
print()
print("=== TUTMA SURESI (dakika) ===")
mins = sorted(r["mins"] for r in recs)
for q in (10, 25, 50, 75, 90):
    print("  %%%-3d : %8.1f dk" % (q, mins[int(len(mins) * q / 100) - 1]))
print("  medyan kazanan : %.1f dk" % sorted(r["mins"] for r in recs if r["net"] > 0)[len(wins) // 2])
print("  medyan kaybeden: %.1f dk" % sorted(r["mins"] for r in recs if r["net"] < 0)[len(losses) // 2])

# Cok kisa suren kazananlar
print()
print("=== SURE x KAR (kazananlar) ===")
for lo, hi in ((0, 5), (5, 15), (15, 60), (60, 240), (240, 10**9)):
    g = [r for r in recs if r["net"] > 0 and lo <= r["mins"] < hi]
    if g:
        print("  %4d-%5d dk : %4d kazanan  ort %+7.2f  toplam %+9.2f"
              % (lo, hi if hi < 10**9 else 99999, len(g),
                 sum(x["net"] for x in g) / len(g), sum(x["net"] for x in g)))

# Strateji etiketleri
print()
print("=== GIRIS ETIKETLERI (comment) ===")
cnt = Counter(r["comment"] for r in recs)
for k, v in cnt.most_common(25):
    g = [r for r in recs if r["comment"] == k]
    net = sum(x["net"] for x in g)
    w = sum(1 for x in g if x["net"] > 0)
    print("  %-28s n=%4d  WR %5.1f%%  net %+9.2f  medyan tutma %6.1f dk"
          % (k[:28], v, 100.0 * w / v, net, sorted(x["mins"] for x in g)[v // 2]))

# Sembol bazli
print()
print("=== SEMBOL BAZLI ===")
bs = defaultdict(list)
for r in recs:
    bs[r["sym"]].append(r)
for k, g in sorted(bs.items(), key=lambda kv: -len(kv[1])):
    net = sum(x["net"] for x in g)
    w = sum(1 for x in g if x["net"] > 0)
    print("  %-10s n=%4d  WR %5.1f%%  net %+9.2f  ort %+6.2f"
          % (k, len(g), 100.0 * w / len(g), net, net / len(g)))
