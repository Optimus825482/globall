# -*- coding: utf-8 -*-
"""MT5 ReportHistory (UTF-16) — Pozisyonlar bolumunu satir bazli ayristir.

Kolonlar: Zaman | Pozisyon | Sembol | Tur | [yorum] | Hacim | Fiyat | S/L | T/P
          | Zaman | Fiyat | Komisyon | Swap | Kar        (14 hucre)

Bolum siniri: "Pozisyonlar" basligi ile "Emirler" basligi arasi.
"""
import sys
import re
import html as htmllib
from collections import Counter, defaultdict
from datetime import datetime

SRC = sys.argv[1]
txt = open(SRC, "rb").read().decode("utf-16")


def cells(row_html):
    out = []
    for m in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S):
        t = re.sub(r"<[^>]+>", "", m.group(1))
        out.append(htmllib.unescape(t).replace("\xa0", " ").strip())
    return out


def ascii_fold(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


DATE = re.compile(r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}$")
parts = re.split(r"(<tr[^>]*>.*?</tr>)", txt, flags=re.S)

# Bolum basliklari da <tr> ICINDE gelir (tek hucreli, colspan'li satir):
# <tr><td colspan=14><b>Pozisyonlar</b></td></tr>. Bu yuzden bolum gecisi
# satirin KENDI hucrelerinden tespit edilir; satirlar arasi metinden degil.
SECTION_NAMES = {"Pozisyonlar": "pos", "Emirler": "ord",
                 "Islemler": "deal", "Acik pozisyonlar": "open"}
section = "header"
pos_rows, order_rows, deal_rows = [], [], []
for p in parts:
    if not p.startswith("<tr"):
        continue
    c = cells(p)
    if not c:
        continue
    if len(c) == 1:
        key = SECTION_NAMES.get(ascii_fold(c[0]).strip())
        if key:
            section = key
        continue
    flat_first = ascii_fold(" ".join(c[:3]))
    if "Zaman" in flat_first and "Sembol" in ascii_fold(" ".join(c)):
        continue  # kolon baslik satiri
    if len(c) >= 13 and DATE.match(c[0]):
        if section == "pos":
            pos_rows.append(c)
        elif section == "ord":
            order_rows.append(c)
        else:
            deal_rows.append(c)

print("POZISYON SATIRI: %d | EMIR: %d | ISLEM: %d"
      % (len(pos_rows), len(order_rows), len(deal_rows)))


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
for c in pos_rows:
    open_p, close_p = num(c[6]), num(c[10])
    profit = num(c[13])
    if None in (open_p, close_p, profit):
        continue
    r = {
        "open_t": dt(c[0]), "id": c[1], "sym": c[2], "side": c[3].lower(),
        "comment": c[4], "vol": num(c[5]), "open_p": open_p,
        "sl": num(c[7]), "tp": num(c[8]),
        "close_t": dt(c[9]) if DATE.match(c[9]) else None, "close_p": close_p,
        "comm": num(c[11]) or 0.0, "swap": num(c[12]) or 0.0, "profit": profit,
    }
    if not r["close_t"]:
        continue
    r["mins"] = (r["close_t"] - r["open_t"]).total_seconds() / 60.0
    r["net"] = r["profit"] + r["comm"] + r["swap"]
    r["mfe"] = (close_p - open_p) if r["side"] == "buy" else (open_p - close_p)  # ham fiyat
    recs.append(r)

recs.sort(key=lambda r: r["open_t"])
print("GECERLI KAPANAN POZISYON: %d" % len(recs))
print("Ilk islem: %s | Son islem: %s" % (recs[0]["open_t"], recs[-1]["close_t"]))

net_all = sum(r["net"] for r in recs)
wins = [r for r in recs if r["net"] > 0]
losses = [r for r in recs if r["net"] < 0]
gm = sum(r["net"] for r in wins) / max(1, len(wins))
lm = sum(r["net"] for r in losses) / max(1, len(losses))
print()
print("=== GENEL ===")
print("  toplam net        : %+.2f USD" % net_all)
print("  brut kar          : %+.2f | komisyon %+.2f | swap %+.2f"
      % (sum(r["profit"] for r in recs), sum(r["comm"] for r in recs), sum(r["swap"] for r in recs)))
print("  kazanan / kaybeden: %d / %d   WR %.1f%%" % (len(wins), len(losses), 100.0 * len(wins) / len(recs)))
print("  ort kazanan %+.3f | ort kaybeden %+.3f | odul/risk %.2f" % (gm, lm, abs(lm) / gm if gm else 0))
print("  en buyuk kazanan %+.2f | en buyuk kaybeden %+.2f"
      % (max(r["net"] for r in recs), min(r["net"] for r in recs)))

print()
print("=== KAR BANDI DAGILIMI (net) ===")
bands = [(-10**9, -20), (-20, -10), (-10, -5), (-5, -2), (-2, -1), (-1, -0.5), (-0.5, 0),
         (0, 0.5), (0.5, 1), (1, 2), (2, 5), (5, 10), (10, 10**9)]
for lo, hi in bands:
    g = [r for r in recs if lo <= r["net"] < hi]
    if g:
        bar = "#" * min(60, len(g))
        print("  %+8.1f .. %+8.1f : %4d  toplam %+9.2f  %s" % (lo, hi, len(g), sum(x["net"] for x in g), bar))

print()
print("=== TUTMA SURESI ===")
mins = sorted(r["mins"] for r in recs)
for q in (10, 25, 50, 75, 90, 99):
    print("  %-3d%% : %8.1f dk" % (q, mins[min(len(mins) - 1, int(len(mins) * q / 100))]))
for lo, hi in ((0, 1), (1, 3), (3, 5), (5, 15), (15, 60), (60, 240), (240, 10**9)):
    g = [r for r in recs if lo <= r["mins"] < hi]
    if g:
        w = sum(1 for x in g if x["net"] > 0)
        print("  %5s-%-6s dk : n=%4d WR %5.1f%% net %+9.2f ort %+6.2f"
              % (lo, (hi if hi < 10**9 else "+"), len(g), 100.0 * w / len(g),
                 sum(x["net"] for x in g), sum(x["net"] for x in g) / len(g)))

print()
print("=== SL / TP / CIKIS IMZASI ===")
print("  SL dolu: %d/%d   TP dolu: %d/%d"
      % (sum(1 for r in recs if r["sl"]), len(recs), sum(1 for r in recs if r["tp"]), len(recs)))
tp_hit = [r for r in recs if r["tp"] and abs(r["close_p"] - r["tp"]) < 1e-9]
sl_hit = [r for r in recs if r["sl"] and abs(r["close_p"] - r["sl"]) < 1e-9]
print("  kapanis TP'ye esit: %d   kapanis SL'ye esit: %d   diger: %d"
      % (len(tp_hit), len(sl_hit), len(recs) - len(tp_hit) - len(sl_hit)))

print()
print("=== 1R = |acilis - SL| VASTASIYLA R ANALIZI ===")
rr = [r for r in recs if r["sl"] and abs(r["open_p"] - r["sl"]) > 0]
for r in rr:
    r["risk"] = abs(r["open_p"] - r["sl"])
    r["R"] = r["mfe"] / r["risk"]
print("  SL'si olan pozisyon: %d / %d" % (len(rr), len(recs)))
if rr:
    rvals = sorted(r["R"] for r in rr)
    print("  KAPANIS R dagilimi:")
    for q in (10, 25, 50, 75, 90):
        print("    %-3d%% : %+.2f R" % (q, rvals[min(len(rvals) - 1, int(len(rvals) * q / 100))]))
    for th in (0.2, 0.5, 1.0, 1.5, 2.0, 3.0):
        n = sum(1 for r in rr if 0 < r["R"] < th)
        print("    0 < R < %.1f  : %4d  (%5.1f%%)" % (th, n, 100.0 * n / len(rr)))
    wr = sorted(r["R"] for r in rr if r["net"] > 0)
    if wr:
        print("  KAZANANLARIN kapanis R'si (n=%d):" % len(wr))
        for q in (25, 50, 75, 90):
            print("    %-3d%% : %+.2f R" % (q, wr[min(len(wr) - 1, int(len(wr) * q / 100))]))
        for th in (0.3, 0.5, 0.75, 1.0, 1.5, 2.0):
            n = sum(1 for x in wr if x < th)
            print("    kazananlarin %5.1f%%'i %.2f R'nin ALTINDA kapandi (%d adet)"
                  % (100.0 * n / len(wr), th, n))

print()
print("=== STRATEJI (yorum) BAZLI ===")
g = defaultdict(list)
for r in recs:
    g[re.sub(r"\s+\d+$", "", r["comment"]) or "(bos)"].append(r)
for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
    w = sum(1 for x in v if x["net"] > 0)
    print("  %-10s n=%4d WR %5.1f%% net %+9.2f ort %+6.2f medyan tutma %6.1f dk"
          % (k[:10], len(v), 100.0 * w / len(v), sum(x["net"] for x in v),
             sum(x["net"] for x in v) / len(v), sorted(x["mins"] for x in v)[len(v) // 2]))

print()
print("=== SEMBOL / YON ===")
g = defaultdict(list)
for r in recs:
    g[(r["sym"], r["side"])].append(r)
for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
    w = sum(1 for x in v if x["net"] > 0)
    print("  %-8s %-4s n=%4d WR %5.1f%% net %+9.2f ort %+6.2f medyan tutma %6.1f dk"
          % (k[0], k[1], len(v), 100.0 * w / len(v), sum(x["net"] for x in v),
             sum(x["net"] for x in v) / len(v), sorted(x["mins"] for x in v)[len(v) // 2]))

# Gun bazli
print()
print("=== GUN BAZLI ===")
g = defaultdict(list)
for r in recs:
    g[r["open_t"].strftime("%Y-%m-%d")].append(r)
for k in sorted(g):
    v = g[k]
    w = sum(1 for x in v if x["net"] > 0)
    print("  %s n=%4d WR %5.1f%% net %+9.2f" % (k, len(v), 100.0 * w / len(v), sum(x["net"] for x in v)))
