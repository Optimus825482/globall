"""Kombo taramasi Task 2: tarama_<sym>_<tf>.json dosyalarindan secim.json ve TARAMA_OZET.md uretir.

Kullanim:
  python scripts/kombo_secim.py [--dir outputs/kombo] [--max-aday 25] [--min-pf 1.2] [--min-islem 25]
  python scripts/kombo_secim.py --selftest

Kurallar (Task 2 kontrolor kararlari):
- Hucre basina egitim ilk 20'den ayni "taban" (tip/a/b/n) icin en cok 2 varyant tutulur (egitim sirasiyla).
- Dogrulama adayi: taban-kapli listeden, testte PF >= min-pf ve >= min-islem islem VE yalniz eklenti
  stratejilerinden (btc_aile, fx_aile, btc_ozgun, fx_ozgun) kurulu olanlar. Adaylar EGITIM skoruna gore
  siralanir ve en cok max-aday kadari alinir; test verisiyle yeniden siralama yapilmaz.
- Istatistik: 20x20=400 ust satirdan kacinin testte PF >= 1.2 tuttugu (coklu karsilastirma olcusu).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EKLENTI_STRATEJILERI = frozenset([
    "btc_seans_kirilim", "btc_rsi2_bb_donus", "btc_donchian55_trend", "btc_keltner_geri_htf", "btc_nr7_kirilim",
    "fx_londra_aralik", "fx_ema200_rsi_geri", "fx_bb_donus_m30", "fx_donchian_gunluk",
    "btc_saat_profili", "btc_likidite_supurme", "btc_xau_oncu", "btc_govde_yigini", "btc_verimlilik_rejimi",
    "fx_seans_devri", "fx_pdh_pdl_supurme", "fx_para_gucu", "fx_doji_kumesi", "fx_adr_tukenis",
])
TABAN_TAVAN = 2
EVREN = ([(s, tf) for s in ("BTCUSD", "XAUUSD") for tf in ("m5", "m15")]
         + [(s, tf) for s in ("EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "GBPJPY", "EURJPY", "NZDUSD")
            for tf in ("m15", "m30")])


def bilesenler(kombo: dict) -> list:
    return [x for x in (kombo.get("a"), kombo.get("b")) if x]


def eklentili_mi(kombo: dict) -> bool:
    """Tum bilesenler eklenti stratejisi mi (Task 3 kombo eklentisi icin gerekli)."""
    return all(a in EKLENTI_STRATEJILERI for a in bilesenler(kombo))


def taban(kombo: dict) -> tuple:
    return (kombo.get("tip"), kombo.get("a"), kombo.get("b"), kombo.get("n"))


def taban_kapla(satirlar: list, tavan: int = TABAN_TAVAN) -> list:
    """Sirayi bozmadan her tabandan en cok `tavan` satir tutar."""
    sayac: dict = {}
    out = []
    for r in satirlar:
        k = taban(r["kombo"])
        if sayac.get(k, 0) >= tavan:
            continue
        sayac[k] = sayac.get(k, 0) + 1
        out.append(r)
    return out


def tutundu(r: dict, min_pf: float, min_islem: int = 0) -> bool:
    t = r.get("test")
    return bool(t) and t["pf"] >= min_pf and t["islem"] >= min_islem


def sec(hucreler: dict, max_aday: int = 25, min_pf: float = 1.2, min_islem: int = 25) -> dict:
    """hucreler: {"SYM_tf": tarama json dict}. secim.json icerigini dondurur."""
    out_h = {}
    tum_adaylar = []
    ist = {"top_satir": 0, "testte_tutunan": 0, "testte_tutunan_min_islem": 0,
           "eklenti_bilesenli_tutunan": 0, "yerlesik_bilesenli_tutunan": 0,
           "taban_kapli_satir": 0, "taban_kapli_tutunan": 0, "aday_havuzu": 0}
    yerlesik_en_iyi = []
    for ad, d in hucreler.items():
        sym, tf = ad.rsplit("_", 1)
        top = d["train_top"]
        kapli = taban_kapla(top)
        ist["top_satir"] += len(top)
        ist["taban_kapli_satir"] += len(kapli)
        for r in top:
            if tutundu(r, min_pf):
                ist["testte_tutunan"] += 1
                ist["eklenti_bilesenli_tutunan" if eklentili_mi(r["kombo"]) else "yerlesik_bilesenli_tutunan"] += 1
            if tutundu(r, min_pf, min_islem):
                ist["testte_tutunan_min_islem"] += 1
        ist["taban_kapli_tutunan"] += sum(1 for r in kapli if tutundu(r, min_pf))
        aday = []
        for sira, r in enumerate(kapli):
            ok = tutundu(r, min_pf, min_islem)
            ek = eklentili_mi(r["kombo"])
            if ok and ek:
                aday.append({"sira": sira + 1, **r})
            elif ok and not ek:
                yerlesik_en_iyi.append({"sym": sym, "tf": tf, "tanim": r["kombo"], "ad": r["ad"],
                                        "train": r["train"], "test": r["test"]})
        out_h[ad] = {"train_top": top, "aday": aday}
        for r in aday:
            tum_adaylar.append({"sym": sym, "tf": tf, "tanim": r["kombo"], "ad_kisa": r["ad"],
                                "train": r["train"], "test": r["test"]})
    ist["aday_havuzu"] = len(tum_adaylar)
    tum_adaylar.sort(key=lambda x: (-x["train"]["skor"], -x["train"]["net"], x["sym"], x["tf"], x["ad_kisa"]))
    secilen = []
    for i, c in enumerate(tum_adaylar[:max_aday], 1):
        secilen.append({"ad": f"kombo_{i}", "sym": c["sym"], "tf": c["tf"], "tanim": c["tanim"],
                        "train": c["train"], "test": c["test"], "ad_kisa": c["ad_kisa"]})
    yerlesik_en_iyi.sort(key=lambda x: -x["train"]["skor"])
    ist["min_pf"] = min_pf
    ist["min_islem_aday"] = min_islem
    ist["max_aday"] = max_aday
    ist["taban_tavan"] = TABAN_TAVAN
    return {"hucreler": out_h, "dogrulama_adaylari": secilen, "istatistik": ist,
            "yerlesik_bilesenli_iyi_hucreler": yerlesik_en_iyi[:25]}


def _e(x):
    return x.replace("|", "\\|")


def _f(x, n=2):
    return f"{x:.{n}f}"


def ozet_md(secim: dict) -> str:
    s = secim["istatistik"]
    L = ["# Kombo taramasi: Task 2 ozeti", "",
         "Egitim 2026-07-21..09-08 (siralama), test 09-08..10-28 (egitim sonrasi bir kez okundu). "
         "Skor = PF x min(1, n/80), n >= 40. Hizli simulator = kaba on eleme.", "",
         "## Hucre tablosu (egitim 1. kombo ve testi)", "",
         "| Hucre | Egitim 1. kombo | Egit n/PF | Test n/PF/net | Top-20 testte PF>=1.2 | Aday |", "|---|---|---|---|---|---|"]
    for ad, h in secim["hucreler"].items():
        top = h["train_top"]
        if not top:
            L.append(f"| {ad} | - | - | - | 0/0 | 0 |")
            continue
        r = top[0]
        t = r["test"]
        tut = sum(1 for x in top if tutundu(x, s["min_pf"]))
        L.append(f"| {ad} | `{_e(r['ad'])}` | {r['train']['islem']}/{_f(r['train']['pf'])} | "
                 f"{t['islem']}/{_f(t['pf'])}/{_f(t['net'], 1)} | {tut}/{len(top)} | {len(h['aday'])} |")
    L += ["", "## Sayilar", "",
          f"- Top-20 satir: {s['top_satir']}; testte PF >= {s['min_pf']}: **{s['testte_tutunan']}** "
          f"(>= {s['min_islem_aday']} test islemi sartiyla {s['testte_tutunan_min_islem']}).",
          f"- Tutunanlardan eklenti-bilesenli: {s['eklenti_bilesenli_tutunan']}, yerlesik-bilesenli: {s['yerlesik_bilesenli_tutunan']}.",
          f"- Taban kapagi (<= {s['taban_tavan']}/taban) sonrasi: {s['taban_kapli_satir']} satir, {s['taban_kapli_tutunan']} tutundu.",
          f"- Aday havuzu (taban-kapli, test PF>={s['min_pf']}, n>={s['min_islem_aday']}, yalniz eklenti): {s['aday_havuzu']}; "
          f"dogrulamaya {len(secim['dogrulama_adaylari'])} (egitim skoruna gore, max {s['max_aday']}).", "",
          "## Dogrulama adaylari (egitim skoru sirasi)", "",
          "| Ad | Hucre | Tanim | Egit n/PF/net | Test n/PF/net |", "|---|---|---|---|---|"]
    for c in secim["dogrulama_adaylari"]:
        L.append(f"| {c['ad']} | {c['sym']}_{c['tf']} | `{_e(c['ad_kisa'])}` | {c['train']['islem']}/{_f(c['train']['pf'])}/{_f(c['train']['net'], 1)} | "
                 f"{c['test']['islem']}/{_f(c['test']['pf'])}/{_f(c['test']['net'], 1)} |")
    if not secim["dogrulama_adaylari"]:
        L.append("| (yok) | | | | |")
    L += ["", "## Yerlesik bilesenli iyi hucreler (yalniz bilgi, Task 3'e girmez)", "",
          "| Hucre | Tanim | Egit n/PF | Test n/PF/net |", "|---|---|---|---|"]
    for c in secim["yerlesik_bilesenli_iyi_hucreler"][:15]:
        L.append(f"| {c['sym']}_{c['tf']} | `{_e(c['ad'])}` | {c['train']['islem']}/{_f(c['train']['pf'])} | "
                 f"{c['test']['islem']}/{_f(c['test']['pf'])}/{_f(c['test']['net'], 1)} |")
    return "\n".join(L) + "\n"


def yukle(dizin: Path) -> dict:
    h = {}
    for p in sorted(dizin.glob("tarama_*_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if not d.get("test_okundu"):
            raise SystemExit(f"{p.name}: test_okundu degil")
        sym, tf = p.stem[len("tarama_"):].rsplit("_", 1)
        if (sym, tf) not in EVREN:  # evren disi (ornegin eski smoke) dosyalar atlanir
            continue
        h[f"{sym}_{tf}"] = d
    return h


def _satir(a, b, tip="or", n=None, pf_t=1.5, n_t=30, skor=1.0, nf=60):
    return {"kombo": {"tip": tip, "a": a, "b": b, "n": n, "filtre": [], "sl_atr": 1.5, "tp_r": 2.0, "basabas": False},
            "ad": f"{tip}({a},{b})", "train": {"islem": nf, "pf": 2.0, "net": 100.0, "skor": skor},
            "test": {"islem": n_t, "pf": pf_t, "net": 10.0}}


def selftest() -> None:
    s = [_satir("btc_nr7_kirilim", "fx_seans_devri") for _ in range(4)] + [_satir("btc_nr7_kirilim", "fx_adr_tukenis")]
    assert len(taban_kapla(s)) == 3
    assert taban_kapla(s)[2]["kombo"]["b"] == "fx_adr_tukenis"
    assert eklentili_mi(s[0]["kombo"]) and not eklentili_mi(_satir("combo3", "fx_seans_devri")["kombo"])
    assert eklentili_mi({"tip": "tek", "a": "fx_seans_devri", "b": None})
    h = {"BTCUSD_m15": {"train_top": [
        _satir("combo3", "fx_seans_devri", pf_t=2.0, skor=9),                 # yerlesik: aday degil
        _satir("btc_nr7_kirilim", "fx_adr_tukenis", pf_t=1.25, skor=3),        # aday
        _satir("btc_nr7_kirilim", "fx_doji_kumesi", pf_t=1.1, skor=5),         # test PF dusuk
        _satir("fx_seans_devri", "fx_adr_tukenis", pf_t=3.0, n_t=10, skor=6),  # az test islemi
        _satir("fx_seans_devri", "fx_doji_kumesi", pf_t=5.0, skor=2),          # aday; test PF yuksek ama egitim skoru dusuk
    ]}}
    r = sec(h, max_aday=25)
    assert [c["ad_kisa"] for c in r["dogrulama_adaylari"]] == [
        "or(btc_nr7_kirilim,fx_adr_tukenis)", "or(fx_seans_devri,fx_doji_kumesi)"]
    assert r["dogrulama_adaylari"][0]["ad"] == "kombo_1"
    i = r["istatistik"]
    assert i["top_satir"] == 5 and i["testte_tutunan"] == 4 and i["eklenti_bilesenli_tutunan"] == 3
    assert i["yerlesik_bilesenli_tutunan"] == 1 and i["testte_tutunan_min_islem"] == 3
    assert len(sec(h, max_aday=1)["dogrulama_adaylari"]) == 1
    assert ozet_md(r).startswith("# Kombo")
    print("selftest OK")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=str(ROOT / "outputs" / "kombo"))
    ap.add_argument("--max-aday", type=int, default=25)
    ap.add_argument("--min-pf", type=float, default=1.2)
    ap.add_argument("--min-islem", type=int, default=25)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        selftest()
        return
    dizin = Path(a.dir)
    secim = sec(yukle(dizin), a.max_aday, a.min_pf, a.min_islem)
    (dizin / "secim.json").write_text(json.dumps(secim, ensure_ascii=False, indent=1), encoding="utf-8")
    (dizin / "TARAMA_OZET.md").write_text(ozet_md(secim), encoding="utf-8")
    print(json.dumps(secim["istatistik"], ensure_ascii=False))
    print(f"adaylar: {len(secim['dogrulama_adaylari'])} -> {dizin / 'secim.json'}")


if __name__ == "__main__":
    main()
