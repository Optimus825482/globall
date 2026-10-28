#!/usr/bin/env python3
"""BTC/FX yeni strateji ailesi: "robust kenar" olcutlerinin uygulanmasi.

Girdi (outputs/replay_strateji/, commit edilmez):
  ozet_turbtc1.json      Task 2 (BTC, 10 hucre)
  ozet_turfx_yeni.json   Task 3 (FX, 64 hucre)
  gun_<tag>.json         her hucrenin ayrintisi ("daily" = gun -> P&L, sabit 1000$ taban)

Olcutler (Spec, baglayici):
  1. 14 hafta (2026-07-21..2026-10-27) PF >= 1.30, net > 0, islem >= 60.
  2. Ilk 7 hafta (07-21..09-07) VE son 7 hafta (09-08..10-27) ayri ayri net > 0.
  3. Kayma stresinde (FX --slip-pips 1; BTC --slip-pips 10) PF >= 1.10.
  4. Gun P&L <= -700 USD ("iflas") gun sayisi <= 2.
Aday = olcut 1, 2 ve 4'u gecen hucre (kayma kosumundan ONCE); olcut 3 sonra eklenir;
"robust" = 1+2+3+4 hepsi.

Kullanim:
  python scripts/strateji_dogrulama.py                  # olcut 1,2,4 + tablo + dogrulama.json
  python scripts/strateji_dogrulama.py --slip-ozet outputs/replay_strateji/ozet_turdogrulama_slip_fx_m15.json \
        outputs/replay_strateji/ozet_turdogrulama_slip_btc_m5.json   # olcut 3'u birlestirir
  python scripts/strateji_dogrulama.py --selftest        # sentetik 3 satirla olcut fonksiyonu testi
Parametreler (v2 ozgun aileler; varsayilanlar v1 davranisini korur):
  --ozet a.json b.json   girdi ozetleri (varsayilan: ozet_turbtc1.json ozet_turfx_yeni.json)
  --out dosya.json       cikti (varsayilan: outputs/replay_strateji/dogrulama.json)
  --slip-tur-oneki ON    basilan kayma komutlarinin --tur oneki (varsayilan: dogrulama_slip)
  Ornek: python scripts/strateji_dogrulama.py --ozet outputs/replay_strateji/ozet_turbtc_ozgun.json \
         outputs/replay_strateji/ozet_turfx_ozgun.json --out outputs/replay_strateji/dogrulama_v2.json \
         --slip-tur-oneki dogrulama2_slip
Iki asamali kullanim: 1. cagri adaylari ve kayma komutlarini basar; kayma kosumlari bittikten
sonra ayni komut --slip-ozet ile tekrar calistirilir (kayma ozetleri eski cikti uzerine yazmaz;
her --tur ayri dosya). Risk olcekleme (2/5/10/20%) adaylar icin (aday yoksa PF'ye gore ilk 3,
yalniz bilgi) dogrulama.json'da "risk_olcek" altinda; gunluk P&L risk/taban ile lineer olceklenir
(FX taban %5, BTC taban %2).
v3 (kombo_* eklentisi): grup sembolden (XAUUSD -> XAU: taban %10, kayma 2 pip; BTCUSD -> BTC; digerleri FX);
--test-penceresi rep_<tag>.json kapanan islemlerinden test penceresi (son 7h) PF/net/islem ve olcut 5 (test PF >= 1.2) ekler.
  python scripts/strateji_dogrulama.py --ozet outputs/replay_strateji/ozet_turkombo_v3_*.json          --out outputs/replay_strateji/dogrulama_v3.json --slip-tur-oneki kombo_v3_slip --test-penceresi [--slip-ozet ...]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "outputs", "replay_strateji")

D0, D_MID, D1 = "2026-07-21", "2026-09-08", "2026-10-28"   # [D0, D_MID) ilk 7h, [D_MID, D1) son 7h
PF_MIN, MIN_TRADES, SLIP_PF_MIN = 1.30, 60, 1.10
SLIP_MIN_FRAC = 0.5   # kayma kosumunda taban islem sayisinin en az bu orani olmali
RUIN_USD, MAX_RUIN_DAYS, TARGET_USD = -700.0, 2, 500.0
BASE_RISK = {"FX": 5.0, "BTC": 2.0, "XAU": 10.0}
SLIP_PIPS = {"FX": 1, "BTC": 10, "XAU": 2}
TEST_PF_MIN = 1.2   # v3 (--test-penceresi): son 7 hafta (test penceresi) kapanan islemlerden PF
RISKS = (2, 5, 10, 20)
DEFAULT_OZET = ("ozet_turbtc1.json", "ozet_turfx_yeni.json")
DEFAULT_OUT = "dogrulama.json"
DEFAULT_SLIP_PREFIX = "dogrulama_slip"


def grup_of(strat: str, sym: str = "") -> str:
    """BTC stratejileri 'btc_' onekli (v1 ve v2); digerleri FX. v3 kombo_* stratejileri sembole gore
    (XAUUSD -> XAU, BTCUSD -> BTC, digerleri FX)."""
    if strat.startswith("kombo_"):
        return {"XAUUSD": "XAU", "BTCUSD": "BTC"}.get(sym, "FX")
    return "BTC" if strat.startswith("btc_") else "FX"


def test_window_stats(closed: list) -> dict:
    """Kapanan islemlerden (closed_ts) test penceresi [D_MID, D1) PF / net / islem. Zarar yoksa PF inf."""
    from datetime import datetime, timezone
    pnl = [t["pnl_usd"] for t in closed if t.get("closed_ts")
           and D_MID <= datetime.fromtimestamp(t["closed_ts"], timezone.utc).strftime("%Y-%m-%d") < D1]
    gw = sum(v for v in pnl if v > 0)
    gl = -sum(v for v in pnl if v < 0)
    pf = (gw / gl) if gl > 0 else (math.inf if gw > 0 else (None if not pnl else 0.0))
    return {"test_islem": len(pnl), "test_net": round(sum(pnl), 2), "test_pf": pf}


def pf_val(x):
    """JSON'daki pf -> float; surucunun "PF 999" degeri (hic zarar yok) -> inf.
    None / sayiya cevrilemeyen deger -> None = DEGERLENDIRILEMEDI (asla inf degil: fail-closed)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    return math.inf if v >= 999.0 else v


def window_stats(daily: dict[str, float]) -> dict:
    d14 = {d: v for d, v in daily.items() if D0 <= d < D1}
    first = sum(v for d, v in d14.items() if d < D_MID)
    last = sum(v for d, v in d14.items() if d >= D_MID)
    return {
        "net14": round(sum(d14.values()), 2), "net_ilk7": round(first, 2), "net_son7": round(last, 2),
        "iflas": sum(1 for v in d14.values() if v <= RUIN_USD),
        "hedef": sum(1 for v in d14.values() if v >= TARGET_USD),
        "gun": len(d14),
    }


def criteria(trades: int, pf: "float | None", net14: float, net_ilk7: float, net_son7: float, iflas: int) -> dict:
    """Olcut 1, 2, 4 (olcut 3 kayma kosumundan gelir). pf: zarar yoksa math.inf."""
    c1 = pf is not None and trades > 0 and pf >= PF_MIN and net14 > 0 and trades >= MIN_TRADES
    c2 = net_ilk7 > 0 and net_son7 > 0
    c4 = iflas <= MAX_RUIN_DAYS
    return {"c1": c1, "c2": c2, "c4": c4, "aday": c1 and c2 and c4}


def risk_table(daily: dict[str, float], base: float) -> dict:
    out = {}
    d14 = {d: v for d, v in daily.items() if D0 <= d < D1}
    for r in RISKS:
        k = r / base
        vals = [v * k for v in d14.values()]
        out[str(r)] = {"hedef_gun": sum(1 for v in vals if v >= TARGET_USD),
                       "iflas_gun": sum(1 for v in vals if v <= RUIN_USD),
                       "net": round(sum(vals), 1), "en_iyi_gun": round(max(vals), 1) if vals else 0.0,
                       "en_kotu_gun": round(min(vals), 1) if vals else 0.0}
    return out


def parse_tag(tag: str, tur: str) -> tuple[str, str, str]:
    """t<tur>_<strateji>_<tf>_<SEMBOL> -> (strateji, tf, sembol)."""
    rest = tag[len(f"t{tur}_"):]
    rest, sym = rest.rsplit("_", 1)
    strat, tf = rest.rsplit("_", 1)
    return strat, tf, sym


def load_cells(ozets=DEFAULT_OZET, test_penceresi: bool = False) -> list[dict]:
    cells = []
    for fn in ozets:
        oz = json.load(open(fn if os.path.isabs(fn) or os.path.exists(fn) else os.path.join(OUT_DIR, fn), encoding="utf-8"))
        for row in oz["rows"]:
            strat, tf, sym = parse_tag(row["tag"], oz["tur"])
            g = json.load(open(os.path.join(OUT_DIR, f"gun_{row['tag']}.json"), encoding="utf-8"))
            ws = window_stats(g["daily"])
            pf = pf_val(row.get("pf"))
            if row["trades"] == 0 and pf is None:
                pf = 0.0   # islemsiz hucre: PF tanimsiz, olcut 1'de acikca basarisiz (criteria trades > 0 ister)
            cell = {"strateji": strat, "tf": tf, "sembol": sym, "grup": grup_of(strat, sym),
                    "tag": row["tag"], "islem": row["trades"], "pf": pf, "net_ozet": row["net"], **ws}
            cell.update(criteria(cell["islem"], pf, ws["net14"], ws["net_ilk7"], ws["net_son7"], ws["iflas"]))
            cell["daily"] = g["daily"]
            if test_penceresi:
                rep = json.load(open(os.path.join(OUT_DIR, f"rep_{row['tag']}.json"), encoding="utf-8"))
                cell.update(test_window_stats(rep["variants"]["NEW"].get("closed", [])))
                cell["c5"] = cell["test_pf"] is not None and cell["test_islem"] > 0 and cell["test_pf"] >= TEST_PF_MIN
            cells.append(cell)
    return cells


def slip_ok(slip_pf, slip_trades: int, base_trades: int) -> tuple[bool, str]:
    """Olcut 3, fail-closed: PF yok/None, islem yok ya da islem sayisi tabanin %50'sinin altindaysa gecmez."""
    if slip_pf is None:
        return False, "PF yok (degerlendirilemedi)"
    if slip_trades <= 0:
        return False, "kayma kosumunda islem yok"
    if slip_trades < SLIP_MIN_FRAC * base_trades:
        return False, f"islem sayisi {slip_trades} < taban {base_trades} x {SLIP_MIN_FRAC:.0%}"
    return slip_pf >= SLIP_PF_MIN, ""


def merge_slip(cells: list[dict], paths: list[str]) -> int:
    idx = {(c["strateji"], c["tf"], c["sembol"]): c for c in cells}
    n = 0
    for p in paths:
        oz = json.load(open(p, encoding="utf-8"))
        for row in oz["rows"]:
            if row.get("rc") != 0 or "pf" not in row:
                print(f"  [UYARI] kayma satiri atlandi (rc={row.get('rc')}, pf yok): {row.get('tag')} -> olcut 3 degerlendirilmedi")
                continue
            strat, tf, sym = parse_tag(row["tag"], oz["tur"])
            c = idx.get((strat, tf, sym))
            if c is None:
                continue
            c["slip_pf"] = pf_val(row["pf"])
            c["slip_net"] = row.get("net")
            c["slip_islem"] = row.get("trades") or 0
            c["c3"], note = slip_ok(c["slip_pf"], c["slip_islem"], c["islem"])
            if note:
                print(f"  [UYARI] kayma {strat} {tf} {sym}: {note} -> olcut 3 basarisiz")
            n += 1
    return n


def fmt_pf(x) -> str:
    return "n/a" if x is None else ("inf" if x == math.inf else f"{x:.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slip-ozet", nargs="*", default=[], help="kayma kosumu ozet json'lari (olcut 3)")
    ap.add_argument("--ozet", nargs="+", default=list(DEFAULT_OZET), help="girdi ozet json'lari")
    ap.add_argument("--out", default=DEFAULT_OUT, help="cikti json (yalniz dosya adi ise outputs/replay_strateji altina; dizin iceren goreli yol CWD'ye gore cozulur)")
    ap.add_argument("--slip-tur-oneki", default=DEFAULT_SLIP_PREFIX, help="kayma komutlarinda --tur oneki")
    ap.add_argument("--test-penceresi", action="store_true",
                    help="v3: rep_<tag>.json kapanan islemlerinden test penceresi (son 7h) PF/net; olcut 5 = test PF >= 1.2")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    cells = load_cells(a.ozet, a.test_penceresi)
    n_slip = merge_slip(cells, a.slip_ozet) if a.slip_ozet else 0
    cells.sort(key=lambda c: (c["grup"], c["strateji"], c["tf"], c["sembol"]))

    print(f"{'grup':4s} {'strateji':22s} {'tf':3s} {'sembol':7s} {'islem':>5s} {'PF':>5s} {'net14':>8s} {'ilk7':>8s} {'son7':>8s} {'iflas':>5s}  c1 c2 c4  slipPF  c3")
    for c in cells:
        sp = fmt_pf(c["slip_pf"]) if "slip_pf" in c else "-"
        c3 = ("E" if c.get("c3") else "H") if "c3" in c else "-"
        print(f"{c['grup']:4s} {c['strateji']:22s} {c['tf']:3s} {c['sembol']:7s} {c['islem']:5d} {fmt_pf(c['pf']):>5s} "
              f"{c['net14']:8.1f} {c['net_ilk7']:8.1f} {c['net_son7']:8.1f} {c['iflas']:5d}  "
              f"{'E' if c['c1'] else '.'}  {'E' if c['c2'] else '.'}  {'E' if c['c4'] else '.'}   {sp:>6s}  {c3}")

    adaylar = [c for c in cells if c["aday"]]
    robust = [c for c in adaylar if c.get("c3")]
    print(f"\nHucre {len(cells)}; olcut1: {sum(c['c1'] for c in cells)}, olcut2: {sum(c['c2'] for c in cells)}, "
          f"olcut4: {sum(c['c4'] for c in cells)}; ADAY (1+2+4): {len(adaylar)}; robust (1+2+3+4): {len(robust)} "
          f"(kayma sonucu birlestirilen hucre: {n_slip})")
    if a.test_penceresi:
        for c in cells:
            print(f"  TEST {c['strateji']} {c['tf']} {c['sembol']}: test islem {c['test_islem']} PF {fmt_pf(c['test_pf'])} "
                  f"net {c['test_net']} c5={'E' if c['c5'] else 'H'}")
        print(f"robust + test PF >= {TEST_PF_MIN} (1+2+3+4+5): {sum(1 for c in robust if c['c5'])}")
    for c in adaylar:
        print(f"  ADAY {c['strateji']} {c['tf']} {c['sembol']}: islem {c['islem']} PF {fmt_pf(c['pf'])} net14 {c['net14']}")

    # Bilgi amacli (aday DEGIL): olcut 1'i gecen ama aday olmayan hucreler + olcut 2'yi gecen >=60 islemli net>0 hucreler.
    # Kayma kosumu yapilmis (ornegin PF'ye gore ilk 3 'bilgi' icin elle kosulan) hucreler de bilgi olarak eklenir.
    yakin = [c for c in cells if not c["aday"] and (c["c1"] or (c["c2"] and c["islem"] >= MIN_TRADES and c["net14"] > 0)
                                                   or "slip_pf" in c)]
    for c in adaylar:
        c["rol"] = "aday"
    for c in yakin:
        c["rol"] = "bilgi"
    bilgi = not adaylar
    sec = adaylar + yakin
    if bilgi:
        print("\nADAY YOK. 'bilgi' hucreleri (olcut 1 gecen; ya da olcut 2 + >=60 islem + net>0; ya da kayma sonucu birlestirilmis "
              "hucre) YALNIZ BILGI amaclidir, aday degildir.")
    for c in yakin:
        print(f"  BILGI {c['strateji']} {c['tf']} {c['sembol']}: islem {c['islem']} PF {fmt_pf(c['pf'])} net14 {c['net14']} "
              f"c1={c['c1']} c2={c['c2']}")
    for c in sec:
        c["risk_olcek"] = risk_table(c["daily"], BASE_RISK[c["grup"]])

    print("\nKayma kosumu komutlari (aday/bilgi hucreleri):")
    gruplar: dict[tuple[str, str, str], dict] = {}
    for c in sec:
        g = gruplar.setdefault((c["grup"], c["tf"], c["sembol"] if c["grup"] in ("BTC", "XAU") else ""), {"s": set(), "y": set()})
        g["s"].add(c["strateji"]); g["y"].add(c["sembol"])
    for (grup, tf, _), g in sorted(gruplar.items()):
        tur = f"{a.slip_tur_oneki}_{grup.lower()}_{tf}"
        cache = "outputs/replay_cache_xaubtc_{tf}.json" if grup in ("BTC", "XAU") else "outputs/replay_cache_fx21_{tf}.json"
        extra = f"--all-symbols --slip-pips {SLIP_PIPS[grup]}" + (" --spread-profile outputs/fx_spread_db_1m.json" if grup == "FX" else "")
        print(f'  python scripts/replay_strateji_tarama.py --tur {tur} --tfs {tf} --strategies {",".join(sorted(g["s"]))} '
              f'--symbols {",".join(sorted(g["y"]))} --jobs 4 --cache-pattern "{cache}" "--extra={extra}"')

    out_cells = []
    for c in cells:
        d = {k: (("inf" if v == math.inf else v) if k in ("pf", "slip_pf", "test_pf") else v) for k, v in c.items() if k != "daily"}
        out_cells.append(d)
    out = {"kriterler": {"pf_min": PF_MIN, "min_islem": MIN_TRADES, "slip_pf_min": SLIP_PF_MIN,
                         "iflas_usd": RUIN_USD, "max_iflas_gun": MAX_RUIN_DAYS, "hedef_usd": TARGET_USD,
                         "pencere": [D0, D_MID, D1]},
           "n_hucre": len(cells), "n_aday": len(adaylar), "n_robust": len(robust),
           "aday_yok": bilgi, "hucreler": out_cells,
           "risk_olcek": {f"{c['strateji']}_{c['tf']}_{c['sembol']}": c["risk_olcek"] for c in sec}}
    path = a.out if os.path.isabs(a.out) or os.path.dirname(a.out) else os.path.join(OUT_DIR, a.out)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nYazildi: {path}")
    return 0


def selftest() -> int:
    inf = math.inf
    # 1: tum olcutleri gecer; 2: PF dusuk; 3: son 7h negatif + 3 iflas gunu
    r1 = criteria(80, 1.45, 120.0, 70.0, 50.0, 0)
    r2 = criteria(80, 1.20, 120.0, 70.0, 50.0, 0)
    r3 = criteria(80, 1.60, 120.0, 190.0, -70.0, 3)
    assert r1 == {"c1": True, "c2": True, "c4": True, "aday": True}, r1
    assert r2["c1"] is False and r2["aday"] is False, r2
    assert r3["c1"] and not r3["c2"] and not r3["c4"] and not r3["aday"], r3
    assert criteria(59, 2.0, 10.0, 5.0, 5.0, 0)["c1"] is False          # islem < 60
    assert criteria(60, inf, 10.0, 5.0, 5.0, 2)["aday"] is True          # PF=inf, 2 iflas gunu sinirda gecer
    ws = window_stats({"2026-07-20": 999.0, "2026-07-21": 10.0, "2026-09-07": 5.0, "2026-09-08": -800.0, "2026-10-27": 1.0, "2026-10-28": 99.0})
    assert ws["net_ilk7"] == 15.0 and ws["net_son7"] == -799.0 and ws["iflas"] == 1 and ws["net14"] == -784.0, ws
    rt = risk_table({"2026-07-21": 100.0, "2026-07-22": -150.0}, 5.0)    # 20% => x4: +400 / -600; 10% => x2
    assert rt["20"]["iflas_gun"] == 0 and rt["20"]["hedef_gun"] == 0 and rt["20"]["en_kotu_gun"] == -600.0, rt
    rt = risk_table({"2026-07-21": 150.0, "2026-07-22": -150.0}, 5.0)
    assert rt["20"]["hedef_gun"] == 1 and rt["20"]["iflas_gun"] == 0 and rt["2"]["hedef_gun"] == 0, rt
    rt = risk_table({"2026-07-21": -200.0}, 5.0)
    assert rt["20"]["iflas_gun"] == 1 and rt["10"]["iflas_gun"] == 0, rt
    assert grup_of("btc_xau_oncu") == "BTC" and grup_of("fx_para_gucu") == "FX" and grup_of("fx_donchian_gunluk") == "FX"
    assert grup_of("btc_xau_oncu", "XAUUSD") == "BTC" and grup_of("fx_para_gucu", "BTCUSD") == "FX"   # v1/v2 ada gore
    assert (grup_of("kombo_1", "XAUUSD"), grup_of("kombo_2", "BTCUSD"), grup_of("kombo_3", "EURJPY")) == ("XAU", "BTC", "FX")
    ts = lambda d: int(__import__("datetime").datetime.fromisoformat(d + "T12:00:00+00:00").timestamp())
    tw = test_window_stats([{"closed_ts": ts("2026-09-07"), "pnl_usd": 999.0}, {"closed_ts": ts("2026-09-08"), "pnl_usd": 30.0},
                            {"closed_ts": ts("2026-10-27"), "pnl_usd": -20.0}, {"closed_ts": ts("2026-10-28"), "pnl_usd": -500.0},
                            {"closed_ts": None, "pnl_usd": 5.0}])
    assert tw == {"test_islem": 2, "test_net": 10.0, "test_pf": 1.5}, tw
    assert test_window_stats([])["test_pf"] is None and test_window_stats([{"closed_ts": ts("2026-09-09"), "pnl_usd": 1.0}])["test_pf"] == inf
    assert parse_tag("tbtc_ozgun_btc_xau_oncu_m15_BTCUSD", "btc_ozgun") == ("btc_xau_oncu", "m15", "BTCUSD")
    assert parse_tag("tfx_ozgun_fx_pdh_pdl_supurme_m30_EURJPY", "fx_ozgun") == ("fx_pdh_pdl_supurme", "m30", "EURJPY")
    ap_t = argparse.ArgumentParser(); ap_t.add_argument("--ozet", nargs="+", default=list(DEFAULT_OZET))
    assert ap_t.parse_args([]).ozet == list(DEFAULT_OZET) and ap_t.parse_args(["--ozet", "a.json", "b.json"]).ozet == ["a.json", "b.json"]
    assert parse_tag("tbtc1_btc_keltner_geri_htf_m5_BTCUSD", "btc1") == ("btc_keltner_geri_htf", "m5", "BTCUSD")
    # fail-open durumlari: PF yok / islem yok
    assert pf_val(None) is None and pf_val("n/a") is None and pf_val(999.0) == inf and pf_val(1.2) == 1.2
    assert criteria(0, 0.0, 0.0, 0.0, 0.0, 0)["c1"] is False            # 0 islem
    assert criteria(0, inf, 5.0, 5.0, 5.0, 0)["c1"] is False            # 0 islem, PF=inf bile gecmez
    assert criteria(80, None, 50.0, 25.0, 25.0, 0)["c1"] is False       # PF yok
    assert slip_ok(None, 70, 70)[0] is False                            # slip PF null
    assert slip_ok(inf, 0, 70)[0] is False                              # slip 0 islem (PF 999/inf olsa bile)
    assert slip_ok(1.5, 20, 70)[0] is False                             # taban islemin %50'sinin altinda
    assert slip_ok(1.05, 70, 70)[0] is False and slip_ok(1.10, 70, 70)[0] is True and slip_ok(1.5, 35, 70)[0] is True
    # merge_slip uctan uca: pf null ve 0 islemli satir c3'u True yapmamali
    import tempfile
    cells = [{"strateji": "s", "tf": "m15", "sembol": "X", "islem": 70}, {"strateji": "s", "tf": "m15", "sembol": "Y", "islem": 70}]
    oz = {"tur": "t", "rows": [{"tag": "tt_s_m15_X", "rc": 0, "pf": None, "net": 0, "trades": 70},
                               {"tag": "tt_s_m15_Y", "rc": 0, "pf": 999, "net": 0, "trades": 0}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(oz, fh)
    merge_slip(cells, [fh.name])
    os.unlink(fh.name)
    assert cells[0]["c3"] is False and cells[1]["c3"] is False, cells
    print("selftest OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
