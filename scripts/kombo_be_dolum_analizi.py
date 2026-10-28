#!/usr/bin/env python3
"""Kombo v3 robust hucreleri icin cikis-nedeni ozeti + kar kilidi ("BE") kotumser dolum duyarliligi.

Rapor: docs/KOMBINASYON_TARAMASI_2026_10_28.md bolum 5-7. Motor dosyalarina DOKUNMAZ.

Alt komutlar
------------
  dolum        Tek hucre: motoru (replay_strateji_gunluk.main) sarilmis fonksiyonlarla bir kez kosar.
  dolum-hepsi  7 robust hucre x {14 hafta, holdout} icin `dolum`u ayri sureclerde kosar
               -> outputs/kombo/be_dolum.json
  ozet         rep_tkombo_v3_*.json kapanan islemlerinden cikis karisimi, yon, holdout, risk olcekleme,
               5 setin gosterge toplami, eszamanlilik; be_dolum.json varsa kotumser net
               -> outputs/kombo/be_dolum_ozet.json (+ stdout)

Kotumser dolum algoritmasi (`dolum`; kod ile rapor ayni olcutu kullanir)
------------------------------------------------------------------------
Motorda manage_position(pos, bar) her barda once SL'yi kontrol eder (BUY: low <= sl_price,
SELL: high >= sl_price) ve vurulursa dolumu HER ZAMAN `sl_price -/+ fill_adjust` fiyatindan yapar;
bar stopun otesinde acilsa bile. Ancak SL kontrolunden SONRA ayni barin high/low'u ile BE kilidi /
trailing stopu yukari tasir; yeni stop ilk kez sonraki barda kontrol edilir.
1. `rp.manage_position` sarilir: her cagrida, orijinal fonksiyon CAGRILMADAN ONCE
   (pozisyon kimligi -> (bar, pos.sl_price)) kaydedilir. Bu, o barin basinda gecerli olan ve o barda
   vurulan stop seviyesidir (SL kontrolu stop degistirilmeden once yapilir).
2. `rp.close_position(book, pos, reason, ...)` sarilir. Yalniz `book.name == "NEW"` (golge defterler
   haric) ve reason in {"SL", "BE"} ise: bar = cikis bari (stopun vuruldugu bar), o = bar[1] (o barin
   acilisi), stop = adim 1'deki sl_price.
     BUY : o < stop ise fark_pip = (o - stop) / pip   (negatif)
     SELL: o > stop ise fark_pip = (stop - o) / pip   (negatif)
     aksi halde 0.
   Yani olcut: "stop cikisinin gerceklestigi bar, o barin basindaki stop seviyesinin otesinde acildi".
   Stop bir onceki barin high/low'una gore tasindigi ve acilis ~ onceki kapanis oldugundan, BE icin bu
   pratikte "kilidi kuran (ya da son tasiyan) barin kapanisi yeni stopun gerisinde kaldi" demektir.
   Ilk (orijinal) SL'deki bosluklar da sayilir (reason "SL").
3. fark_usd = fark_pip * pos.lots * pos.pip_val (kapanistaki lot; kismi kapanis sonrasi kalan lot).
   Spread/fill_adjust her iki dolumda ayni oldugundan farka girmez; motorda komisyon yok;
   kayma kosumu kullanilmaz (taban, kaymasiz).
4. Kotumser net = motor neti + sum(fark_usd). Bu ADDITIF, SONRADAN bir duzeltmedir, yeniden kosum
   DEGILDIR: sonraki islemlerin lot/bakiye etkisi ve kotu dolum sonrasi pozisyonun erken/gec kapanmasinin
   tek-pozisyon zincirine etkisi modellenmez.
Sarilmis kosumun islem sayisi ve neti tabanla ayni olmali (`esit_taban` alani); gecici rep/gun dosyalari silinir.

Kullanim
--------
  python scripts/kombo_be_dolum_analizi.py dolum-hepsi --jobs 7
  python scripts/kombo_be_dolum_analizi.py ozet
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REP = os.path.join(ROOT, "outputs", "replay_strateji")
KOMBO = os.path.join(ROOT, "outputs", "kombo")

# (ad, tf, sembol, 14h grup oneki, holdout/kayma grup oneki)
HUCRELER = [("kombo_1", "m5", "XAUUSD", "xauusd_m5", "xau_m5"), ("kombo_4", "m5", "XAUUSD", "xauusd_m5", "xau_m5"),
            ("kombo_9", "m5", "XAUUSD", "xauusd_m5", "xau_m5"), ("kombo_5", "m15", "XAUUSD", "xauusd_m15", "xau_m15"),
            ("kombo_7", "m15", "XAUUSD", "xauusd_m15", "xau_m15"), ("kombo_14", "m15", "EURJPY", "eurjpy_m15", "fx_m15"),
            ("kombo_16", "m15", "EURJPY", "eurjpy_m15", "fx_m15")]
PENCERE = {"14h": ("2026-07-21", "2026-10-28"), "hold": ("2026-06-21", "2026-07-21")}
TABAN_RISK = {"XAUUSD": 10.0, "EURJPY": 5.0}
SETLER = ["kombo_1", "kombo_4", "kombo_9", "kombo_5", "kombo_14"]  # 5 farkli sinyal seti (ciftlerden biri)
RISKLER = [2, 5, 10, 20]


def cache_for(sym: str, tf: str) -> str:
    return f"outputs/replay_cache_xaubtc_{tf}.json" if sym in ("XAUUSD", "BTCUSD") else f"outputs/replay_cache_fx21_{tf}.json"


def tag_for(ad: str, tf: str, sym: str, g14: str, gh: str, pencere: str, kayma: bool = False) -> str:
    if pencere == "14h":
        return f"tkombo_v3_{'slip_' + gh if kayma else g14}_{ad}_{tf}_{sym}"
    return f"tkombo_v3_holdout_{'slip_' if kayma else ''}{gh}_{ad}_{tf}_{sym}"


# ------------------------------------------------------------------ dolum (tek hucre)
def bosluk_fark(direction: str, acilis: float, stop: float, pip: float, lots: float, pip_val: float) -> tuple:
    """Adim 2-3: cikis bari stopun otesinde acildiysa (BUY: acilis < stop; SELL: acilis > stop) acilis dolumunun
    stop dolumuna gore farki (pip, USD; her zaman <= 0), aksi halde (0, 0)."""
    if direction == "BUY":
        fark = (acilis - stop) / pip if acilis < stop else 0.0
    else:
        fark = (stop - acilis) / pip if acilis > stop else 0.0
    return round(fark, 2), round(fark * lots * pip_val, 2)


def cmd_dolum(a) -> None:
    os.chdir(ROOT)
    for p in (ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import replay_strateji_gunluk as g  # kombo eklentisi sys.modules["replay_strateji_gunluk"]'i kullanir
    rp = g.rp
    orig_manage, orig_close = rp.manage_position, rp.close_position
    son: dict = {}
    kayit: list = []

    # SimPos'ta kararli bir kimlik alani (ticket vb.) yok -> anahtar id(pos). Deger pozisyonun KENDISINI de
    # tuttugu icin nesne kayit silinene kadar toplanamaz, dolayisiyla id yeniden kullanilamaz; ayrica
    # `kayit[0] is pos` ile dogrulanir ve kapanista kayit silinir.
    def manage(pos, bar, *args, **kw):
        son[id(pos)] = (pos, bar, pos.sl_price)  # adim 1: bar basindaki stop
        return orig_manage(pos, bar, *args, **kw)

    def close(book, pos, reason, exit_price, closed_ts=0.0):
        k = son.pop(id(pos), None)
        if book.name == "NEW" and reason in ("SL", "BE") and k is not None and k[0] is pos:
            _, bar, stop = k
            fark_pip, fark_usd = bosluk_fark(pos.direction, bar[1], stop, pos.pip_size, pos.lots, pos.pip_val)
            kayit.append({"reason": reason, "dir": pos.direction, "fark_pip": fark_pip, "fark_usd": fark_usd,
                          "ts": bar[0]})
        return orig_close(book, pos, reason, exit_price, closed_ts=closed_ts)

    rp.manage_position, rp.close_position = manage, close
    fx = a.symbol not in ("XAUUSD", "BTCUSD")
    extra = "--all-symbols" + (" --spread-profile outputs/fx_spread_db_1m.json" if fx else "")
    tag = f"bedolum_{a.strategy}_{a.tf}_{a.symbol}_{a.start}"
    sys.argv = ["replay_strateji_gunluk.py", "--strategy", a.strategy, "--tf", a.tf, "--symbols", a.symbol,
                "--cache", cache_for(a.symbol, a.tf), "--start", a.start, "--end", a.end, "--tag", tag, f"--extra={extra}"]
    g.main()
    new = json.load(open(os.path.join(REP, f"rep_{tag}.json"), encoding="utf-8"))["variants"]["NEW"]
    for f in (f"rep_{tag}.json", f"gun_{tag}.json"):
        try:
            os.remove(os.path.join(REP, f))
        except OSError:
            pass
    bos = [r for r in kayit if r["fark_pip"] < 0]
    out = {"strateji": a.strategy, "tf": a.tf, "sembol": a.symbol, "start": a.start, "end": a.end,
           "islem": new["trades"], "net": new["net_pnl_usd"], "pf": new["profit_factor"],
           "stop_cikis": len(kayit), "bosluk_n": len(bos), "bosluk_be_n": sum(1 for r in bos if r["reason"] == "BE"),
           "bosluk_usd": round(sum(r["fark_usd"] for r in bos), 2)}
    out["kotumser_net"] = round(out["net"] + out["bosluk_usd"], 2)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("DOLUM", json.dumps(out))


def cmd_dolum_hepsi(a) -> None:
    tmp = os.path.join(KOMBO, "be_dolum_parca")
    os.makedirs(tmp, exist_ok=True)
    isler = [(ad, tf, sym, pen) for ad, tf, sym, _, _ in HUCRELER for pen in PENCERE]

    def kos(job):
        ad, tf, sym, pen = job
        st, en = PENCERE[pen]
        out = os.path.join(tmp, f"{ad}_{pen}.json")
        rc = subprocess.call([sys.executable, os.path.abspath(__file__), "dolum", "--strategy", ad, "--tf", tf,
                              "--symbol", sym, "--start", st, "--end", en, "--out", out],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return job, rc, out

    sonuc: dict = {}
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for (ad, tf, sym, pen), rc, out in ex.map(kos, isler):
            if rc != 0:
                raise SystemExit(f"dolum basarisiz: {ad} {pen} rc={rc}")
            d = json.load(open(out, encoding="utf-8"))
            taban = json.load(open(os.path.join(REP, f"rep_{tag_for(ad, tf, sym, *[h for h in HUCRELER if h[0] == ad][0][3:], pen)}.json"),
                                   encoding="utf-8"))["variants"]["NEW"]
            d["esit_taban"] = (d["islem"] == taban["trades"] and abs(d["net"] - taban["net_pnl_usd"]) < 0.01)
            sonuc.setdefault(ad, {})[pen] = d
            print(f"{ad:9s} {pen:4s} islem {d['islem']} net {d['net']} stop {d['stop_cikis']} bosluk {d['bosluk_n']} "
                  f"(BE {d['bosluk_be_n']}) {d['bosluk_usd']} -> kotumser {d['kotumser_net']} esit_taban {d['esit_taban']}")
    with open(os.path.join(KOMBO, "be_dolum.json"), "w", encoding="utf-8") as fh:
        json.dump(sonuc, fh, indent=1)


# ------------------------------------------------------------------ ozet
def _gun(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _pf(xs):
    g = sum(x for x in xs if x > 0)
    l = -sum(x for x in xs if x < 0)
    return round(g / l, 2) if l > 0 else ("inf" if g > 0 else None)


def istatistik(closed: list) -> dict:
    c = [t for t in closed if t.get("closed_ts")]
    p = [t["pnl_usd"] for t in c]
    rs = defaultdict(list)
    for t in c:
        rs[t["reason"] + ("+trail" if t.get("trail") else "")].append(t["pnl_usd"])
    be = [t["pnl_usd"] for t in c if t["reason"] == "BE"]
    brut = sum(x for x in p if x > 0)
    gunluk = defaultdict(float)
    for t in c:
        gunluk[_gun(t["closed_ts"])] += t["pnl_usd"]
    return {
        "n": len(c), "pf": _pf(p), "net": round(sum(p), 2),
        "nedenler": {k: {"n": len(v), "toplam": round(sum(v), 2), "ort": round(statistics.mean(v), 2)} for k, v in sorted(rs.items())},
        "be_islem_payi": round(100 * len(be) / max(1, len(c)), 1),
        "be_brut_kar_payi": round(100 * sum(x for x in be if x > 0) / brut, 1) if brut > 0 else None,
        # yalniz BETIMSEL: BE disi islemlerin P&L toplami; "kilitsiz kosum" DEGIL
        "be_disi_islem_pnl": round(sum(t["pnl_usd"] for t in c if t["reason"] != "BE"), 2),
        "medyan": round(statistics.median(p), 2) if p else None,
        "yon": {s: {"n": len(q), "pf": _pf(q), "net": round(sum(q), 2)}
                for s in ("BUY", "SELL") for q in [[t["pnl_usd"] for t in c if t["direction"] == s]]},
        "ilk_kapanis": _gun(min(t["closed_ts"] for t in c)) if c else None,
        "son_kapanis": _gun(max(t["closed_ts"] for t in c)) if c else None,
        "gunluk": {d: round(v, 2) for d, v in sorted(gunluk.items())},
    }


def _say(gunluk: dict) -> dict:
    v = list(gunluk.values())
    return {"hedef": sum(1 for x in v if x >= 500), "iflas": sum(1 for x in v if x <= -700), "net": round(sum(v), 1),
            "en_iyi": round(max(v), 1) if v else None, "en_kotu": round(min(v), 1) if v else None, "gun": len(v)}


def cmd_ozet(a) -> None:
    hucre: dict = {}
    for ad, tf, sym, g14, gh in HUCRELER:
        hucre[ad] = {"tf": tf, "sembol": sym}
        for pen in PENCERE:
            for kayma in (False, True):
                tag = tag_for(ad, tf, sym, g14, gh, pen, kayma)
                closed = json.load(open(os.path.join(REP, f"rep_{tag}.json"), encoding="utf-8"))["variants"]["NEW"]["closed"]
                hucre[ad][pen + ("_kayma" if kayma else "")] = istatistik(closed)
    risk = {ad: {pen: {r: _say({d: v * r / TABAN_RISK[h["sembol"]] for d, v in h[pen]["gunluk"].items()}) for r in RISKLER}
                 for pen in PENCERE} for ad, h in hucre.items()}
    toplam: dict = {}
    for pen in PENCERE:
        toplam[pen] = {}
        for r in RISKLER + ["sistem"]:
            t = defaultdict(float)
            for ad in SETLER:
                f = 1.0 if r == "sistem" else r / TABAN_RISK[hucre[ad]["sembol"]]
                for d, v in hucre[ad][pen]["gunluk"].items():
                    t[d] += v * f
            toplam[pen][str(r)] = _say(t)
    # eszamanli pozisyon (5 set): acilis = onbellek bars[opened_bar][0]
    onb = {}
    esz = {}
    for pen in PENCERE:
        aralik = []
        for ad in SETLER:
            _, tf, sym, g14, gh = [h for h in HUCRELER if h[0] == ad][0]
            key = cache_for(sym, tf)
            onb.setdefault(key, json.load(open(os.path.join(ROOT, key), encoding="utf-8")))
            bars = onb[key][sym]
            for t in json.load(open(os.path.join(REP, f"rep_{tag_for(ad, tf, sym, g14, gh, pen)}.json"), encoding="utf-8"))["variants"]["NEW"]["closed"]:
                aralik.append((bars[t["opened_bar"]][0], t["closed_ts"]))
        ev = sorted([(o, 1) for o, _ in aralik] + [(c, -1) for _, c in aralik], key=lambda x: (x[0], x[1]))
        cur = mx = 0
        sure: Counter = Counter()
        prev = None
        for ts, d in ev:
            if prev is not None and cur > 0:
                sure[cur] += ts - prev
            cur += d
            mx = max(mx, cur)
            prev = ts
        tot = sum(sure.values()) or 1
        esz[pen] = {"max": mx, "zaman_payi_%": {k: round(100 * v / tot, 1) for k, v in sorted(sure.items())}}
    dolum_p = os.path.join(KOMBO, "be_dolum.json")
    dolum = json.load(open(dolum_p, encoding="utf-8")) if os.path.exists(dolum_p) else None
    out = {"hucre": hucre, "risk": risk, "toplam_5_set": toplam, "eszamanli": esz, "be_dolum": dolum}
    with open(os.path.join(KOMBO, "be_dolum_ozet.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    for ad, h in hucre.items():
        print(f"\n== {ad} {h['sembol']} {h['tf']}")
        for k in ("14h", "14h_kayma", "hold", "hold_kayma"):
            s = h[k]
            print(f"  {k:10s} n {s['n']} PF {s['pf']} net {s['net']} BE% {s['be_islem_payi']} BEbrut% {s['be_brut_kar_payi']} "
                  f"BE-disi-pnl {s['be_disi_islem_pnl']} med {s['medyan']} yon {s['yon']}")
            print(f"             nedenler {s['nedenler']}")
        if dolum and ad in dolum:
            print("  dolum", {p: (d["bosluk_n"], d["bosluk_usd"], d["kotumser_net"], d["esit_taban"]) for p, d in dolum[ad].items()})
    print("\nToplam (5 set):", json.dumps(toplam))
    print("Eszamanli:", json.dumps(esz))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dolum")
    d.add_argument("--strategy", required=True)
    d.add_argument("--tf", required=True)
    d.add_argument("--symbol", required=True)
    d.add_argument("--start", required=True)
    d.add_argument("--end", required=True)
    d.add_argument("--out", required=True)
    h = sub.add_parser("dolum-hepsi")
    h.add_argument("--jobs", type=int, default=7)
    sub.add_parser("ozet")
    a = ap.parse_args()
    {"dolum": cmd_dolum, "dolum-hepsi": cmd_dolum_hepsi, "ozet": cmd_ozet}[a.cmd](a)


if __name__ == "__main__":
    main()
