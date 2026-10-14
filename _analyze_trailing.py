# -*- coding: utf-8 -*-
"""MT5 ReportHistory -> trailing / BE kilit analizi.

Amac: "trailing/BE cok erken devreye giriyor" iddiasini SAYIYLA sinamak.

Kaynak bolumler (tek-hucreli baslik satirlari ile ayrilir):
  Pozisyonlar : Zaman|Pozisyon|Sembol|Tur|Yorum|Hacim|Fiyat|S/L|T/P|Zaman|Fiyat|Komisyon|Swap|Kar
  Emirler     : Acilis|Emir|Sembol|Tur|Hacim|Fiyat|S/L|T/P|Zaman|Durum|Yorum
  Islemler    : Zaman|Islem|Sembol|Tur|Yon|Hacim|Fiyat|Emir|Maliyet|Komisyon|Ucret|Swap|Kar|Bakiye|Yorum

OLCULEN KANIT (canli MT5 defterinden):
  * Pozisyonlar bolumundeki S/L = KAPANIS anindaki (trail/BE ile tasinmis) stop.
    -> gercek cikis seviyesi. Islemler'deki "[sl X]" yorumu ile ayni.
  * Emirler bolumundeki giris emrinin S/L = GIRIS anindaki ilk stop.
    -> 1R'nin paydasi budur.
  * Ikisinin farki = trail/BE'nin stopu tasidigi mesafe.
"""
import sys
import re
import html as htmllib
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

SRC = sys.argv[1]
txt = open(SRC, "rb").read().decode("utf-16")

DATE = re.compile(r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}$")


def cells(row_html):
    out = []
    for m in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S):
        t = re.sub(r"<[^>]+>", "", m.group(1))
        out.append(htmllib.unescape(t).replace("\xa0", " ").strip())
    return out


def afold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def num(s):
    s = (s or "").replace(" ", "").replace(",", "")
    if s in ("", "-", "market"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def dt(s):
    return datetime.strptime(s, "%Y.%m.%d %H:%M:%S")


def pip_spec(sym):
    s = sym.upper()
    if "XAU" in s or "GOLD" in s:
        return 0.10, 10.0, "XAU"
    if "XAG" in s or "SILVER" in s:
        return 0.01, 50.0, "XAG"
    if "BTC" in s:
        return 1.0, 1.0, "BTC"
    if "ETH" in s:
        return 1.0, 1.0, "ETH"
    if "US30" in s or "DJ30" in s or "WS30" in s:
        return 1.0, 1.0, "US30"
    if "NAS100" in s or "USTEC" in s or "US100" in s or "NDX" in s:
        return 1.0, 1.0, "NAS100"
    if "JPY" in s:
        return 0.01, 6.60, "JPY"
    return 0.0001, 10.0, "FX"


# M5 (high-low)/pip ortalamasi — 2026-10-13 denetim dokumanindaki olculen degerler
ATR_PIPS = {
    "XAUUSD": 39.8, "BTCUSD": 165.9, "US30": 20.2, "NAS100": 30.0,
    "GBPUSD": 4.5, "USDJPY": 2.8, "GBPJPY": 6.0,
}
# canli ayarlar (D:\data\forex_auto_settings.json)
CHANDELIER_ATR_MULT = 0.3
GOLD_BE_LOCK_RATIO = 0.6
OTHER_BE_LOCK_RATIO = 0.40
HEADROOM = {"XAU": 4.0, "BTC": 25.0, "OTHER": 3.5}

parts = re.split(r"(<tr[^>]*>.*?</tr>)", txt, flags=re.S)
SEC = {"Pozisyonlar": "pos", "Emirler": "ord", "Islemler": "deal",
       "Acik pozisyonlar": "open", "Sonuclar": "res", "Bakiye Dususu:": "dd"}
section = "header"
pos_rows, ord_rows, deal_rows, res_rows = [], [], [], []
for p in parts:
    if not p.startswith("<tr"):
        continue
    c = cells(p)
    if not c:
        continue
    if len(c) == 1:
        key = SEC.get(afold(c[0]).strip())
        if key:
            section = key
        continue
    if section == "pos" and len(c) >= 14 and DATE.match(c[0]):
        pos_rows.append(c)
    elif section == "ord" and len(c) == 11 and DATE.match(c[0]):
        ord_rows.append(c)
    elif section == "deal" and len(c) == 15 and DATE.match(c[0]):
        deal_rows.append(c)
    elif section == "res":
        res_rows.append(c)

print("Pozisyon: %d | Emir: %d | Islem: %d | Sonuc satiri: %d"
      % (len(pos_rows), len(ord_rows), len(deal_rows), len(res_rows)))

recs = []
for c in pos_rows:
    op, cp, pr = num(c[6]), num(c[10]), num(c[13])
    if None in (op, cp, pr) or not DATE.match(c[9]):
        continue
    side = afold(c[3]).lower()
    sym = c[2]
    pip, pip_val, fam = pip_spec(sym)
    vol = num(c[5]) or 0.0
    r = {
        "open_t": dt(c[0]), "pid": c[1], "sym": sym, "side": side,
        "comment": c[4], "vol": vol, "open_p": op,
        "pos_sl": num(c[7]),          # KAPANIS anindaki (tasinmis) stop
        "pos_tp": num(c[8]),
        "close_t": dt(c[9]), "close_p": cp,
        "comm": num(c[11]) or 0.0, "swap": num(c[12]) or 0.0, "profit": pr,
        "pip": pip, "pip_val": pip_val, "fam": fam,
    }
    r["net"] = r["profit"] + r["comm"] + r["swap"]
    r["mins"] = (r["close_t"] - r["open_t"]).total_seconds() / 60.0
    r["sgn"] = 1.0 if side == "buy" else -1.0
    r["pts"] = r["sgn"] * (cp - op)
    r["pips"] = r["pts"] / pip
    r["atr"] = ATR_PIPS.get(sym.upper())
    r["dollar_per_pip"] = max(0.0001, vol * pip_val)
    r["pips_for_1usd"] = max(0.5, round(1.0 / r["dollar_per_pip"], 1))
    hr = HEADROOM.get("XAU" if fam == "XAU" else ("BTC" if fam == "BTC" else "OTHER"))
    r["be_trigger_pips"] = round(min(r["pips_for_1usd"] + hr, 999), 1)
    recs.append(r)
recs.sort(key=lambda x: x["open_t"])
print("Gecerli kapanan pozisyon: %d | %s -> %s"
      % (len(recs), recs[0]["open_t"], recs[-1]["close_t"]))

# --- giris emirleri: S/L = GIRIS anindaki ilk stop (1R'nin paydasi) ---
entry_by_key = {}
for c in ord_rows:
    cm = c[10]
    if cm.startswith("[sl") or cm.startswith("[tp"):
        continue
    entry_by_key[(c[2], c[8], afold(c[3]).lower())] = {
        "sl": num(c[6]), "tp": num(c[7]), "comment": cm, "price": num(c[5]),
    }

# --- cikis islemleri ---
exit_by_key = defaultdict(list)
for c in deal_rows:
    if afold(c[4]).lower() != "out":
        continue
    exit_by_key[(c[2], c[0])].append({
        "price": num(c[6]), "profit": num(c[12]) or 0.0,
        "comm": num(c[9]) or 0.0, "swap": num(c[11]) or 0.0, "comment": c[14],
    })

SL_RE = re.compile(r"^\[sl\s+([\d.]+)\]$")
n_me = n_mx = 0
for r in recs:
    e = entry_by_key.get((r["sym"], r["open_t"].strftime("%Y.%m.%d %H:%M:%S"), r["side"]))
    if e:
        n_me += 1
        r["entry_sl"], r["entry_tp"], r["entry_comment"] = e["sl"], e["tp"], e["comment"]
    else:
        r["entry_sl"] = r["entry_tp"] = None
        r["entry_comment"] = ""
    outs = exit_by_key.get((r["sym"], r["close_t"].strftime("%Y.%m.%d %H:%M:%S")), [])
    r["n_out"] = len(outs)
    final = outs[-1] if outs else None
    if final:
        n_mx += 1
        r["exit_p"], r["exit_comment"] = final["price"], final["comment"]
        m = SL_RE.match(final["comment"].strip())
        r["exit_sl"] = float(m.group(1)) if m else None
    else:
        r["exit_p"], r["exit_comment"], r["exit_sl"] = r["close_p"], "", None

    if r["n_out"] > 1:
        r["exit_kind"] = "PARTIAL"
    elif r["exit_sl"] is not None:
        r["exit_kind"] = "TRAILED_SL"
    elif "Scalper Partial" in r["exit_comment"]:
        r["exit_kind"] = "PARTIAL"
    elif "Scalper Close" in r["exit_comment"]:
        r["exit_kind"] = "HARD_CLOSE"
    else:
        r["exit_kind"] = "OTHER"

    # 1R paydasi = GIRIS anindaki stop (yoksa kapanis stopu)
    init = r["entry_sl"] if r["entry_sl"] else r["pos_sl"]
    r["init_sl"] = init
    r["init_src"] = "entry" if r["entry_sl"] else ("pos" if r["pos_sl"] else "none")
    r["risk_pts"] = abs(r["open_p"] - init) if init else None
    r["risk_pips"] = (r["risk_pts"] / r["pip"]) if r["risk_pts"] else None
    r["risk_atr"] = (r["risk_pips"] / r["atr"]) if (r["risk_pips"] and r["atr"]) else None
    r["R"] = (r["pts"] / r["risk_pts"]) if r["risk_pts"] else None

    # kapanis stopunun girise gore konumu (isaretli pips) = korunan kar
    fin = r["pos_sl"] if r["pos_sl"] else r["exit_sl"]
    if fin:
        r["lock_pts"] = r["sgn"] * (fin - r["open_p"])
        r["lock_pips"] = r["lock_pts"] / r["pip"]
        r["lock_usd"] = r["lock_pips"] * r["dollar_per_pip"]
        r["lock_R"] = (r["lock_pts"] / r["risk_pts"]) if r["risk_pts"] else None
        r["lock_atr"] = (r["lock_pips"] / r["atr"]) if r["atr"] else None
        if init:
            r["sl_move_pips"] = r["sgn"] * (fin - init) / r["pip"]
            r["sl_move_atr"] = r["sl_move_pips"] / r["atr"] if r["atr"] else None
        else:
            r["sl_move_pips"] = r["sl_move_atr"] = None
        # BE formulu tersine: kilit = max($1, MFE*ratio)  ->  MFE >= kilit/ratio
        ratio = GOLD_BE_LOCK_RATIO if r["fam"] == "XAU" else OTHER_BE_LOCK_RATIO
        r["mfe_be_pips"] = (r["lock_pips"] / ratio) if r["lock_pips"] > 0 else None
        r["giveback_be_pips"] = (r["mfe_be_pips"] - r["lock_pips"]) if r["mfe_be_pips"] else None
        r["mfe_ch_pips"] = (r["lock_pips"] + CHANDELIER_ATR_MULT * r["atr"]) if r["atr"] and r["lock_pips"] > 0 else None
        r["giveback_ch_pips"] = (CHANDELIER_ATR_MULT * r["atr"]) if r["atr"] and r["lock_pips"] > 0 else None
    else:
        for k in ("lock_pts", "lock_pips", "lock_usd", "lock_R", "lock_atr",
                  "sl_move_pips", "sl_move_atr", "mfe_be_pips", "giveback_be_pips",
                  "mfe_ch_pips", "giveback_ch_pips"):
            r[k] = None

print("Eslesen giris emri: %d/%d | cikis islemi: %d/%d" % (n_me, len(recs), n_mx, len(recs)))
print("1R kaynagi: %s" % dict(Counter(r["init_src"] for r in recs)))

eq = [r for r in recs if r["pos_sl"] and r["exit_sl"] and abs(r["pos_sl"] - r["exit_sl"]) < 1e-9]
print("Pozisyon S/L == cikis [sl] seviyesi : %d / %d  -> Pozisyonlar bolumundeki S/L KAPANIS stopu"
      % (len(eq), sum(1 for r in recs if r["exit_sl"])))
moved = [r for r in recs if r["sl_move_pips"] is not None and abs(r["sl_move_pips"]) > 0.05]
print("Stop GIRISE gore TASINMIS (trail/BE) : %d / %d (%5.1f%%)"
      % (len(moved), sum(1 for r in recs if r["sl_move_pips"] is not None),
         100.0 * len(moved) / max(1, sum(1 for r in recs if r["sl_move_pips"] is not None))))


def stat(name, vals, fmt="%+9.2f"):
    if not vals:
        print("  %-30s (veri yok)" % name)
        return
    v = sorted(vals)
    print(("  %-30s n=%4d  p10 " + fmt + " | medyan " + fmt + " | p90 " + fmt + " | ort " + fmt)
          % (name, len(v), v[int(len(v) * .1)], v[len(v) // 2],
             v[min(len(v) - 1, int(len(v) * .9))], sum(v) / len(v)))


wins = [r for r in recs if r["net"] > 0]
losses = [r for r in recs if r["net"] < 0]
gm = sum(r["net"] for r in wins) / max(1, len(wins))
lm = sum(r["net"] for r in losses) / max(1, len(losses))

print()
print("=== 1. GENEL ===")
print("  net %+.2f USD | brut %+.2f | komisyon %+.2f | swap %+.2f"
      % (sum(r["net"] for r in recs), sum(r["profit"] for r in recs),
         sum(r["comm"] for r in recs), sum(r["swap"] for r in recs)))
print("  kazanan %d / kaybeden %d  WR %.1f%%" % (len(wins), len(losses), 100.0 * len(wins) / len(recs)))
print("  ort kazanan %+.3f | ort kaybeden %+.3f | odul/risk %.3f"
      % (gm, lm, gm / abs(lm) if lm else 0))
print("  basabas icin gereken WR %.1f%% -> gercek WR %.1f%% (acik %.1f puan)"
      % (100.0 / (1 + gm / abs(lm)) if lm else 0, 100.0 * len(wins) / len(recs),
         (100.0 / (1 + gm / abs(lm)) if lm else 0) - 100.0 * len(wins) / len(recs)))

print()
print("=== 2. CIKIS MEKANIZMASI ===")
for k, n in Counter(r["exit_kind"] for r in recs).most_common():
    g = [r for r in recs if r["exit_kind"] == k]
    print("  %-11s n=%4d  net %+9.2f  ort %+6.2f  medyan tutma %6.1f dk"
          % (k, n, sum(x["net"] for x in g), sum(x["net"] for x in g) / n,
             sorted(x["mins"] for x in g)[n // 2]))

print()
print("=== 3. 1R (giris stopu) ve TASIMA MESAFESI ===")
stat("giris stopu (pips)", [r["risk_pips"] for r in recs if r["risk_pips"]], "%+9.1f")
stat("giris stopu (ATR)", [r["risk_atr"] for r in recs if r["risk_atr"]], "%+9.2f")
stat("stop tasima (pips)", [r["sl_move_pips"] for r in recs if r["sl_move_pips"] is not None], "%+9.1f")
stat("stop tasima (ATR)", [r["sl_move_atr"] for r in recs if r["sl_move_atr"] is not None], "%+9.2f")

print()
print("=== 4. KILIT SEVIYESI — KAZANANLAR (giris goreli korunan kar) ===")
stat("korunan kar (USD)", [r["lock_usd"] for r in wins if r["lock_usd"] is not None])
stat("korunan kar (pips)", [r["lock_pips"] for r in wins if r["lock_pips"] is not None], "%+9.1f")
stat("korunan kar (R)", [r["lock_R"] for r in wins if r["lock_R"] is not None], "%+9.2f")
stat("korunan kar (ATR)", [r["lock_atr"] for r in wins if r["lock_atr"] is not None], "%+9.2f")
lu = [r["lock_usd"] for r in wins if r["lock_usd"] is not None]
la = [r["lock_atr"] for r in wins if r["lock_atr"] is not None]
if lu:
    for th in (1.0, 1.5, 2.0, 3.0, 5.0, 10.0):
        n = sum(1 for v in lu if v < th)
        print("    korunan kar < %5.2f USD : %4d (%5.1f%%)" % (th, n, 100.0 * n / len(lu)))
if la:
    for th in (0.2, 0.3, 0.5, 1.0):
        n = sum(1 for v in la if v < th)
        print("    korunan kar < %.1f ATR   : %4d (%5.1f%%)" % (th, n, 100.0 * n / len(la)))

print()
print("=== 5. KAZANAN KAPANIS R DAGILIMI (1R = giris stopu) ===")
wr = sorted(r["R"] for r in wins if r["R"] is not None)
if wr:
    for p in (10, 25, 50, 75, 90):
        print("    p%-3d : %+.2f R" % (p, wr[min(len(wr) - 1, int(len(wr) * p / 100))]))
    for th in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
        n = sum(1 for x in wr if x < th)
        print("    kazananlarin %5.1f%%'i %.2f R ALTINDA (%d)" % (100.0 * n / len(wr), th, n))

print()
print("=== 6. GERI VERILEN (BE/chandelier formulu tersine) — KAZANANLAR ===")
stat("BE varsayimi: MFE (pips)", [r["mfe_be_pips"] for r in wins if r["mfe_be_pips"]], "%+9.1f")
stat("BE varsayimi: geri verilen (pips)", [r["giveback_be_pips"] for r in wins if r["giveback_be_pips"]], "%+9.1f")
stat("Chandelier varsayimi: geri verilen (pips)", [r["giveback_ch_pips"] for r in wins if r["giveback_ch_pips"]], "%+9.1f")
ga = [r["giveback_be_pips"] for r in wins if r["giveback_be_pips"] and r["atr"]]
g_a = [(r["giveback_be_pips"] / r["atr"]) for r in wins if r["giveback_be_pips"] and r["atr"]]
stat("BE geri verilen (ATR)", g_a, "%+9.2f")

print()
print("=== 7. KAYBEDENLERDE BE/TRAIL IZI ===")
ls = [r for r in losses if r["lock_pts"] is not None]
above = [r for r in ls if r["lock_pts"] > 0]
below = [r for r in ls if r["lock_pts"] <= 0]
print("  kaybeden, kilit bilinen: %d" % len(ls))
print("  kapanis stopu giris USTUNDE (kilit vardi ama zarar): %d (%5.1f%%) net %+.2f"
      % (len(above), 100.0 * len(above) / max(1, len(ls)), sum(x["net"] for x in above)))
print("  kapanis stopu giris ALTINDA (BE hic devreye girmedi): %d (%5.1f%%) net %+.2f"
      % (len(below), 100.0 * len(below) / max(1, len(ls)), sum(x["net"] for x in below)))
stat("kaybeden korunan kar (USD)", [r["lock_usd"] for r in ls if r["lock_usd"] is not None])
stat("kaybeden kapanis R", [r["R"] for r in ls if r["R"] is not None], "%+9.2f")

print()
print("=== 8. SEMBOL BAZLI ===")
g = defaultdict(list)
for r in recs:
    g[r["sym"]].append(r)
for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
    w = [x for x in v if x["net"] > 0]
    lk = sorted(x["lock_usd"] for x in w if x["lock_usd"] is not None)
    lka = sorted(x["lock_atr"] for x in w if x["lock_atr"] is not None)
    print("  %-7s n=%4d WR %5.1f%% net %+8.2f ort %+6.2f | ATR %5.1f p | 1R medyan %5.1f p"
          % (k, len(v), 100.0 * len(w) / len(v), sum(x["net"] for x in v),
             sum(x["net"] for x in v) / len(v), v[0]["atr"] or 0,
             sorted(x["risk_pips"] for x in v if x["risk_pips"])[len([x for x in v if x["risk_pips"]]) // 2]
             if any(x["risk_pips"] for x in v) else 0))
    print("           kazanan korunan kar medyan %5.2f USD (%5.2f ATR) | ort kazanan %+5.2f | ort kaybeden %+6.2f"
          % (lk[len(lk) // 2] if lk else 0, lka[len(lka) // 2] if lka else 0,
             sum(x["net"] for x in w) / len(w) if w else 0,
             sum(x["net"] for x in v if x["net"] < 0) / max(1, len([x for x in v if x["net"] < 0]))))

print()
print("=== 9. ZAMAN KESITI (chandelier canliya 2026-10-13 ~11:30) ===")
CUT = datetime(2026, 10, 13, 11, 30)
for label, sub in (("ONCESI", [r for r in recs if r["open_t"] < CUT]),
                   ("SONRASI", [r for r in recs if r["open_t"] >= CUT])):
    if not sub:
        continue
    w = [x for x in sub if x["net"] > 0]
    lo = [x for x in sub if x["net"] < 0]
    lk = sorted(x["lock_usd"] for x in w if x["lock_usd"] is not None)
    lka = sorted(x["lock_atr"] for x in w if x["lock_atr"] is not None)
    print("  %-8s n=%4d WR %5.1f%% net %+8.2f | ort kazanan %+5.2f | ort kaybeden %+6.2f | ort tutma %5.1f dk"
          % (label, len(sub), 100.0 * len(w) / len(sub), sum(x["net"] for x in sub),
             sum(x["net"] for x in w) / max(1, len(w)),
             sum(x["net"] for x in lo) / max(1, len(lo)), sum(x["mins"] for x in sub) / len(sub)))
    if lk:
        print("           kazanan korunan kar medyan %5.2f USD (%5.2f ATR) | %s"
              % (lk[len(lk) // 2], lka[len(lka) // 2] if lka else 0,
                 dict(Counter(x["exit_kind"] for x in sub))))

print()
print("=== 10. GUN / SAAT (2026-10-13) ===")
g = defaultdict(list)
for r in recs:
    g[r["open_t"].strftime("%Y-%m-%d")].append(r)
for k in sorted(g):
    v = g[k]
    w = [x for x in v if x["net"] > 0]
    print("  %s n=%4d WR %5.1f%% net %+9.2f" % (k, len(v), 100.0 * len(w) / len(v), sum(x["net"] for x in v)))
h = defaultdict(list)
for r in recs:
    if r["open_t"].strftime("%Y-%m-%d") == "2026-10-13":
        h[r["open_t"].hour].append(r)
print("  -- 2026-10-13 saatlik --")
for k in sorted(h):
    v = h[k]
    w = [x for x in v if x["net"] > 0]
    print("    %02d:00 n=%3d WR %5.1f%% net %+8.2f" % (k, len(v), 100.0 * len(w) / len(v), sum(x["net"] for x in v)))

print()
print("=== 11. STRATEJI (yorum) BAZLI ===")
g = defaultdict(list)
for r in recs:
    g[re.sub(r"\s+\d+$", "", r["comment"]) or "(bos)"].append(r)
for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
    w = [x for x in v if x["net"] > 0]
    print("  %-11s n=%4d WR %5.1f%% net %+8.2f ort %+6.2f medyan tutma %6.1f dk"
          % (k[:11], len(v), 100.0 * len(w) / len(v), sum(x["net"] for x in v),
             sum(x["net"] for x in v) / len(v), sorted(x["mins"] for x in v)[len(v) // 2]))

print()
print("=== 12. ORNEK ISLEMLER ===")
print("  --- en buyuk 10 KAZANAN ---")
for r in sorted(wins, key=lambda x: -x["net"])[:10]:
    print("   %s %-7s %-4s vol %.2f | %6.1f dk | net %+7.2f | R %+5.2f | kilit %+6.1f p (%+5.2f ATR) %s"
          % (r["open_t"].strftime("%m-%d %H:%M"), r["sym"], r["side"], r["vol"], r["mins"],
             r["net"], r["R"] or 0, r["lock_pips"] or 0, r["lock_atr"] or 0, r["exit_kind"]))
print("  --- en buyuk 10 KAYBEDEN ---")
for r in sorted(losses, key=lambda x: x["net"])[:10]:
    print("   %s %-7s %-4s vol %.2f | %6.1f dk | net %+7.2f | R %+5.2f | kilit %+6.1f p (%+5.2f ATR) %s"
          % (r["open_t"].strftime("%m-%d %H:%M"), r["sym"], r["side"], r["vol"], r["mins"],
             r["net"], r["R"] or 0, r["lock_pips"] or 0, r["lock_atr"] or 0, r["exit_kind"]))

print()
print("=== 13. TUTMA SURESI BANTLARI ===")
for lo, hi in ((0, 1), (1, 3), (3, 5), (5, 15), (15, 60), (60, 10**9)):
    v = [r for r in recs if lo <= r["mins"] < hi]
    if not v:
        continue
    w = [x for x in v if x["net"] > 0]
    print("  %5s-%-5s dk : n=%4d WR %5.1f%% net %+9.2f ort %+6.2f"
          % (lo, (hi if hi < 10**9 else "+"), len(v), 100.0 * len(w) / len(v),
             sum(x["net"] for x in v), sum(x["net"] for x in v) / len(v)))

print()
print("=== 14. R CINSINDEN SIZINTI (1R = giris stopu) ===")
mfeR = [r["mfe_be_pips"] / r["risk_pips"] for r in wins
        if r["mfe_be_pips"] and r["risk_pips"]]
gbR = [r["giveback_be_pips"] / r["risk_pips"] for r in wins
       if r["giveback_be_pips"] and r["risk_pips"]]
rrR = [r["R"] for r in wins if r["R"] is not None]
stat("BE-tersine TEPE (R) [alt sinir]", mfeR, "%+9.2f")
stat("geri verilen (R)", gbR, "%+9.2f")
stat("fiilen alinan (R)", rrR, "%+9.2f")
if mfeR:
    for th in (0.5, 1.0):
        n = sum(1 for x in mfeR if x >= th)
        print("    tepe >= %.1f R olan kazanan : %4d (%5.1f%%)" % (th, n, 100.0 * n / len(mfeR)))
    tot_peak = sum(r["mfe_be_pips"] * r["dollar_per_pip"] for r in wins
                   if r["mfe_be_pips"]) 
    tot_real = sum(r["pts"] / r["pip"] * r["dollar_per_pip"] for r in wins)
    print("    kazananlarin tepe kari toplam %+9.2f USD | fiilen alinan %+9.2f USD"
          % (tot_peak, tot_real))

print()
print("=== 15. EV KARSILASTIRMASI (islem basi, USD) ===")
n = len(recs)
print("    gerceklesen              : %+7.4f / islem  (toplam %+8.2f)" % (sum(r["net"] for r in recs) / n, sum(r["net"] for r in recs)))
# kontrafaktuel: kazananlar BE-tersine tepede kapansaydi (geri verilen geri alinsa)
add = sum(r["giveback_be_pips"] * r["dollar_per_pip"] for r in wins if r["giveback_be_pips"])
print("    tepe yakalansa (ust sinir): %+7.4f / islem  (+%8.2f geri alinan)"
      % ((sum(r["net"] for r in recs) + add) / n, add))
print("    NOT: 'tepe yakalansa' bir UST SINIRDIR; BE-tersine MFE yalnizca kilit tabanin")
print("         uzerinde oldugunda gecerlidir, bu yuzden gercek tepe bundan BUYUK olabilir.")

print()
print("=== 17. HACIM / RISK BUTCESI (1R = lot x giris_stop x pip_val) ===")
# Bakiye zaman serisi: Islemler bolumundeki "Bakiye" kolonundan (c[13])
bal_series = []
for c in deal_rows:
    b = num(c[13])
    if b is not None:
        bal_series.append((dt(c[0]), b))
bal_series.sort()
for r in recs:
    bal = None
    for t, b in bal_series:
        if t <= r["open_t"]:
            bal = b
        else:
            break
    r["bal"] = bal
    r["risk_usd"] = (r["vol"] * r["risk_pips"] * r["pip_val"]) if r["risk_pips"] else None
    r["risk_pct"] = (100.0 * r["risk_usd"] / bal) if (r["risk_usd"] and bal) else None

stat("1R riski (USD)", [r["risk_usd"] for r in recs if r["risk_usd"]], "%+9.2f")
stat("1R riski (% bakiye)", [r["risk_pct"] for r in recs if r["risk_pct"]], "%+9.2f")
stat("lot", [r["vol"] for r in recs], "%+9.2f")
if bal_series:
    print("  bakiye araligi: %.2f -> %.2f USD" % (bal_series[0][1], bal_series[-1][1]))
rp = [r["risk_pct"] for r in recs if r["risk_pct"]]
if rp:
    for th in (2.0, 5.0, 7.5, 10.0, 15.0, 20.0):
        n = sum(1 for v in rp if v > th)
        print("    1R riski > %5.1f%% bakiye : %4d (%5.1f%%)" % (th, n, 100.0 * n / len(rp)))
print("  -- sembol bazli lot / risk --")
g = defaultdict(list)
for r in recs:
    g[r["sym"]].append(r)
for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
    lots = sorted(x["vol"] for x in v)
    rps = sorted(x["risk_pct"] for x in v if x["risk_pct"])
    print("    %-7s n=%4d lot min/medyan/maks %5.2f / %5.2f / %5.2f | 1R risk medyan %5.2f%% bakiye"
          % (k, len(v), lots[0], lots[len(lots) // 2], lots[-1],
             rps[len(rps) // 2] if rps else 0))
print("  -- 1R riski > 10%% bakiye olan islemler --")
big = sorted([r for r in recs if r["risk_pct"] and r["risk_pct"] > 10.0],
             key=lambda x: -x["risk_pct"])
print("    adet: %d | net toplam %+.2f USD" % (len(big), sum(x["net"] for x in big)))
for r in big[:12]:
    print("     %s %-7s %-4s lot %5.2f | 1R %6.2f USD = %5.1f%% bakiye | net %+7.2f"
          % (r["open_t"].strftime("%m-%d %H:%M"), r["sym"], r["side"], r["vol"],
             r["risk_usd"] or 0, r["risk_pct"] or 0, r["net"]))

print()
print("=== 18. SONUC BOLUMU ===")
for c in res_rows:
    print("  " + " | ".join(c))
