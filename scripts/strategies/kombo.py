"""Kombinasyon eklentisi (plan v3 Task 3): hizli taramada (scripts/kombo_tarama.py) secilen
kombinasyonlari gercek replay motorunda (replay_strateji_gunluk.py) calistirir.

Tanimlar: `KOMBO_TANIM` ortam degiskenindeki JSON dosyasi; yoksa outputs/kombo/kombo_tanimlar.json.
Dosya yoksa STRATEGIES = {} (eklenti yukleyicisi bozulmaz). Dosya bicimi: liste (ya da
{"kombolar": liste}); her eleman {"ad": "kombo_<n>", "sym": "XAUUSD", "tf": "m5",
"tanim": {"tip", "a", "b", "n", "filtre", "sl_atr", "tp_r", "basabas"}}.
Kararli adlar icin liste bir kez uretilir ve yeniden yazilmaz:
  python scripts/strategies/kombo.py --olustur [--secim outputs/kombo/secim.json] [--zorla]
(secim.json'daki tum hucrelerin egitim ilk-20 satirlarindan testte PF >= 1.2 ve >= 25 islem tutanlar,
egitim skoru sirasiyla, en cok 25; yalniz basabas'ta ayrisan satirlar tek komboya baglanir cunku
motorun kendi BE'si sabittir.)

Bilesen stratejiler (yerlesik ya da eklenti) SARMALAYICININ kendi `series_for/side_for`
fonksiyonlariyla hesaplanir; sarmalayici yeniden import EDILMEZ (cift yukleme olmasin diye) —
cagri aninda `sys.modules["replay_strateji_gunluk"]` ya da `sys.modules["__main__"]` cozulur.
Sarmalayicinin sembol basina tek-slotlu `_SERIES` onbellegine dokunulmaz: her bilesen
`__kombo__<bilesen>` anahtariyla hesaplanir, sonuc saklanir, gecici anahtar silinir.

Anlambilim `kombo_tarama.py` ile AYNI (testlerle karsilastirilir):
  * bilesen yonu yalniz i >= 60 icin (oncesi 0); yon = isaret(side_for)
  * or: once a, a sessizse b;  and(N): biri bu barda, digeri [i-N+1, i] icinde ayni yonde;
    sonra(N): a'nin [i-1]'e kadar EN SON sinyali [i-N, i-1] icindeyse yon verir, b ayni yonde tetikler
  * etkin ATR (motorun SL mesafesi): tetikleyen bilesenin `atr`'si — tek/or: ateslenen,
    and: bu bardaki sinyal a'nin ise a, degilse b; sonra: b
  * filtreler (bar i kapanisinda bilinen veri): htf_ema200 (H1 EMA200 tarafi), seans_07_20 /
    seans_13_20 / seans_00_07 (giris = i+1 acilis saati, UTC), atr_yuksek / atr_dusuk (ATR14'un
    son 100 bardaki — kendisi dahil — yuzdeligi >= 50 / <= 50), adx_ge20 / adx_ge25 / adx_lt20
  * cikis: sl_atr / tp_r tanimdan; basabas motorun kendi BE'si (tanimdaki basabas YOK sayilir)
  * symbols = {kombonun sembolu}; spread_min_mult FX icin 8.0, XAUUSD/BTCUSD icin None
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VARSAYILAN_TANIM = os.path.join(_ROOT, "outputs", "kombo", "kombo_tanimlar.json")
VARSAYILAN_SECIM = os.path.join(_ROOT, "outputs", "kombo", "secim.json")

SIDE_MIN_I = 60
TF_SEC = {"m1": 60, "m3": 180, "m5": 300, "m15": 900, "m30": 1800}
TIPLER = ("tek", "or", "and", "sonra")
FILTRELER = ("htf_ema200", "seans_07_20", "seans_13_20", "seans_00_07",
             "atr_yuksek", "atr_dusuk", "adx_ge20", "adx_ge25", "adx_lt20")
FX_DISI = frozenset({"XAUUSD", "BTCUSD"})
FX_SPREAD_MIN_MULT = 8.0
HTF_SEC, HTF_EMA_N = 3600, 200
ATR_PCT_WIN = 100
ADX_N = 14


# ------------------------------------------------------------------ sarmalayici
def sarmalayici():
    """Yuklu replay_strateji_gunluk modulu (yeniden import yok)."""
    for key in ("replay_strateji_gunluk", "__main__"):
        mod = sys.modules.get(key)
        if mod is not None and hasattr(mod, "side_for") and hasattr(mod, "series_for"):
            return mod
    raise RuntimeError("kombo: replay_strateji_gunluk yuklu degil (sys.modules'ta 'replay_strateji_gunluk' "
                       "ya da side_for/series_for tanimli '__main__' yok); kombo eklentisi yalniz sarmalayici "
                       "uzerinden calisir")


# ------------------------------------------------------------------ nedensel gostergeler (saf python)
def _gecersiz(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def htf_ema(t: list, c: list, tf_sec: int, period: int = HTF_EMA_N, htf: int = HTF_SEC) -> list:
    """Bar i saati tamamliyorsa (t + tf >= saat sonu) H1 EMA o kapanisla guncellenir; period saat
    dolmadan None."""
    out: list = [None] * len(c)
    a = 2.0 / (period + 1)
    ema, cnt = None, 0
    for i in range(len(c)):
        if t[i] + tf_sec >= (t[i] // htf + 1) * htf:
            ema = c[i] if ema is None else a * c[i] + (1 - a) * ema
            cnt += 1
        if cnt >= period:
            out[i] = ema
    return out


def atr_yuzdelik(atr: list, win: int = ATR_PCT_WIN) -> list:
    """atr[i]'nin [i-win+1, i] penceresindeki yuzdelik sirasi (<= sayisi * 100 / win); eksikse None."""
    n = len(atr)
    out: list = [None] * n
    for i in range(win - 1, n):
        w = atr[i - win + 1:i + 1]
        if any(_gecersiz(v) for v in w):
            continue
        cur = w[-1]
        out[i] = sum(1 for v in w if v <= cur) * 100.0 / win
    return out


def adx(h: list, l: list, c: list, n: int = ADX_N) -> list:
    """Wilder ADX(n)."""
    m = len(c)
    out: list = [None] * m
    if m < 2 * n + 2:
        return out
    tr, pdm, mdm = [], [], []
    for k in range(m - 1):                       # k -> bar k+1
        up = h[k + 1] - h[k]
        dn = l[k] - l[k + 1]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(max(h[k + 1] - l[k + 1], abs(h[k + 1] - c[k]), abs(l[k + 1] - c[k])))
    s_tr, s_p, s_m = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n])
    dxs: list = []
    val = None
    for k in range(n - 1, m - 1):
        if k >= n:
            s_tr = s_tr - s_tr / n + tr[k]
            s_p = s_p - s_p / n + pdm[k]
            s_m = s_m - s_m / n + mdm[k]
        pdi = 100.0 * s_p / s_tr if s_tr > 0 else 0.0
        mdi = 100.0 * s_m / s_tr if s_tr > 0 else 0.0
        dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
        if val is None:
            dxs.append(dx)
            if len(dxs) == n:
                val = sum(dxs) / n
                out[k + 1] = val
        else:
            val = (val * (n - 1) + dx) / n
            out[k + 1] = val
    return out


def filtre_maskeleri(t: list, h: list, l: list, c: list, atr14: list, tf_sec: int, adlar=FILTRELER) -> dict:
    """ad -> (long_ok, short_ok) bool listeleri; bar i icin yalniz <= i verisi."""
    n = len(c)
    out: dict = {}
    adlar = list(adlar)
    if "htf_ema200" in adlar:
        e = htf_ema(t, c, tf_sec)
        out["htf_ema200"] = ([e[i] is not None and c[i] > e[i] for i in range(n)],
                             [e[i] is not None and c[i] < e[i] for i in range(n)])
    saat = [((x + tf_sec) // 3600) % 24 for x in t]
    for ad, (h0, h1) in (("seans_07_20", (7, 20)), ("seans_13_20", (13, 20)), ("seans_00_07", (0, 7))):
        if ad in adlar:
            m = [h0 <= s < h1 for s in saat]
            out[ad] = (m, m)
    if "atr_yuksek" in adlar or "atr_dusuk" in adlar:
        p = atr_yuzdelik(atr14)
        for ad, fn in (("atr_yuksek", lambda v: v >= 50), ("atr_dusuk", lambda v: v <= 50)):
            if ad in adlar:
                m = [v is not None and fn(v) for v in p]
                out[ad] = (m, m)
    if any(a.startswith("adx_") for a in adlar):
        x = adx(h, l, c)
        for ad, fn in (("adx_ge20", lambda v: v >= 20), ("adx_ge25", lambda v: v >= 25),
                       ("adx_lt20", lambda v: v < 20)):
            if ad in adlar:
                m = [v is not None and fn(v) for v in x]
                out[ad] = (m, m)
    return out


# ------------------------------------------------------------------ birlestirici (bar bazinda)
def birlestir(tip: str, A: list, B: list | None, n: int | None, i: int) -> tuple:
    """Bar i icin (yon, kaynak) — kaynak 'a' ya da 'b' (etkin ATR bileseni)."""
    a = A[i]
    if tip == "tek":
        return a, "a"
    b = B[i]
    if tip == "or":
        return (a, "a") if a != 0 else (b, "b")
    if tip == "and":
        lo = max(0, i - n + 1)
        wa, wb = A[lo:i + 1], B[lo:i + 1]
        lng = (a == 1 and 1 in wb) or (b == 1 and 1 in wa)
        sht = (a == -1 and -1 in wb) or (b == -1 and -1 in wa)
        yon = int(lng) - int(sht)
        return yon, ("a" if yon != 0 and a == yon else "b")
    if tip == "sonra":
        j = i - 1
        while j >= 0 and A[j] == 0:
            j -= 1
        if j < 0 or j < i - n or b == 0 or b != A[j]:
            return 0, "b"
        return b, "b"
    raise ValueError(f"kombo: bilinmeyen tip {tip!r}")


def filtrele(yon: int, maskeler: dict, filtre: list, i: int) -> int:
    for f in filtre:
        lng, sht = maskeler[f]
        if not (lng[i] if yon > 0 else sht[i]):
            return 0
    return yon


# ------------------------------------------------------------------ seri / yon
def _tf_sec_of(b: list) -> int | None:
    d = Counter(b[k + 1].t - b[k].t for k in range(min(len(b) - 1, 500)) if b[k + 1].t > b[k].t)
    return d.most_common(1)[0][0] if d else None


def bilesen_serisi(mod, comp: str, b: list) -> dict:
    """Sarmalayicinin series_for'u ile, gercek sembolun onbellegine dokunmadan."""
    key = f"__kombo__{comp}"
    raw = [[x.t, x.open, x.high, x.low, x.close] for x in b]
    try:
        mod._SERIES.pop(key, None)
        mod._BARS.pop(key, None)
        return mod.series_for(key, comp, raw)
    finally:
        mod._SERIES.pop(key, None)
        mod._BARS.pop(key, None)


def bilesen_yonu(mod, comp: str, s: dict, b: list) -> list:
    out = [0] * len(b)
    for i in range(SIDE_MIN_I, len(b)):
        v = mod.side_for(comp, s, b, i)
        out[i] = 1 if v and v > 0 else (-1 if v and v < 0 else 0)
    return out


def kombo_serisi(tanim: dict, tf: str, b: list, closes=None, mod=None) -> dict:
    mod = mod or sarmalayici()
    tf_sec = TF_SEC[tf]
    gercek = _tf_sec_of(b)
    if gercek is not None and gercek != tf_sec:
        raise ValueError(f"kombo: tanim tf={tf} ({tf_sec} sn) ama barlar {gercek} sn")
    tip, ca, cb, n = tanim["tip"], tanim["a"], tanim.get("b"), tanim.get("n")
    sa = bilesen_serisi(mod, ca, b)
    A = bilesen_yonu(mod, ca, sa, b)
    sb, B = None, None
    if tip != "tek":
        sb = bilesen_serisi(mod, cb, b)
        B = bilesen_yonu(mod, cb, sb, b)
    filtre = list(tanim.get("filtre") or [])
    t = [x.t for x in b]
    h, l, c = [x.high for x in b], [x.low for x in b], [x.close for x in b]
    maskeler = filtre_maskeleri(t, h, l, c, mod.wk.atr(b, 14), tf_sec, filtre) if filtre else {}
    m = len(b)
    sig, atr = [0] * m, [None] * m
    atr_a, atr_b = sa["atr"], (sb["atr"] if sb is not None else None)
    for i in range(m):
        yon, kaynak = birlestir(tip, A, B, n, i)
        if yon:
            yon = filtrele(yon, maskeler, filtre, i)
        sig[i] = yon
        atr[i] = atr_a[i] if (kaynak == "a" or atr_b is None) else atr_b[i]
    return {"sig": sig, "atr": atr, "A": A, "B": B, "bilesen": {ca: sa, **({cb: sb} if sb is not None else {})},
            "maske": maskeler, "kaynak_atr": {"a": atr_a, "b": atr_b}}


def kombo_yonu(s: dict, b, i: int) -> int:
    return s["sig"][i]


# ------------------------------------------------------------------ tanim yukleme
def tanim_dogrula(k: dict) -> None:
    t = k["tanim"]
    if t["tip"] not in TIPLER:
        raise ValueError(f"kombo {k.get('ad')}: bilinmeyen tip {t['tip']!r}")
    if t["tip"] != "tek" and not t.get("b"):
        raise ValueError(f"kombo {k.get('ad')}: '{t['tip']}' icin b bileseni yok")
    if t["tip"] in ("and", "sonra") and not (isinstance(t.get("n"), int) and t["n"] >= 1):
        raise ValueError(f"kombo {k.get('ad')}: '{t['tip']}' icin n >= 1 gerekli")
    bad = [f for f in t.get("filtre") or [] if f not in FILTRELER]
    if bad:
        raise ValueError(f"kombo {k.get('ad')}: bilinmeyen filtre {bad}")
    if k["tf"] not in TF_SEC:
        raise ValueError(f"kombo {k.get('ad')}: bilinmeyen tf {k['tf']!r}")
    if not (float(t["sl_atr"]) > 0 and float(t["tp_r"]) > 0):
        raise ValueError(f"kombo {k.get('ad')}: sl_atr/tp_r > 0 olmali")


def strateji_tanimi(k: dict) -> dict:
    tanim_dogrula(k)
    tanim, tf, sym = dict(k["tanim"]), k["tf"], k["sym"]
    return {
        "series": lambda b, closes, _t=tanim, _tf=tf: kombo_serisi(_t, _tf, b, closes),
        "side": kombo_yonu,
        "sl_atr": float(tanim["sl_atr"]), "tp_r": float(tanim["tp_r"]),
        "symbols": {sym},
        "spread_min_mult": None if sym in FX_DISI else FX_SPREAD_MIN_MULT,
        "kombo": {"sym": sym, "tf": tf, "tanim": tanim},
    }


def yukle(path: str | None = None) -> dict:
    """Tanim dosyasi -> STRATEGIES; dosya yoksa {}."""
    path = path or os.environ.get("KOMBO_TANIM") or VARSAYILAN_TANIM
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    liste = doc["kombolar"] if isinstance(doc, dict) else doc
    out: dict = {}
    for k in liste:
        if k["ad"] in out:
            raise ValueError(f"kombo: yinelenen ad {k['ad']}")
        out[k["ad"]] = strateji_tanimi(k)
    return out


# ------------------------------------------------------------------ tanim listesi uretimi
def _cikis_disi(t: dict) -> tuple:
    """Motorda ayni davranan tanimlar icin anahtar (basabas haric)."""
    return (t["tip"], t["a"], t.get("b"), t.get("n"), tuple(t.get("filtre") or []), float(t["sl_atr"]),
            float(t["tp_r"]))


def tanimlar_olustur(secim: dict, max_kombo: int = 25, min_pf: float = 1.2, min_islem: int = 25) -> list:
    """secim.json -> kombo listesi: testte tutunan tum ust satirlar, egitim skoru sirasi, en cok max_kombo."""
    satirlar = []
    for hucre, d in secim["hucreler"].items():
        sym, tf = hucre.rsplit("_", 1)
        for r in d["train_top"]:
            te = r.get("test")
            if te and te["pf"] >= min_pf and te["islem"] >= min_islem:
                satirlar.append((sym, tf, r))
    satirlar.sort(key=lambda x: (-(x[2]["train"]["skor"] or 0.0), x[0], x[1], x[2]["ad"]))
    satirlar = satirlar[:max_kombo]
    out: list = []
    idx: dict = {}
    for sym, tf, r in satirlar:
        key = (sym, tf, _cikis_disi(r["kombo"]))
        kayit = {"satir": r["ad"], "train": r["train"], "test": r["test"]}
        if key in idx:
            idx[key]["kaynak"].append(kayit)
            continue
        k = {"ad": f"kombo_{len(out) + 1}", "sym": sym, "tf": tf, "tanim": dict(r["kombo"]),
             "kaynak": [kayit]}
        idx[key] = k
        out.append(k)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="kombo tanim listesi uretimi")
    ap.add_argument("--olustur", action="store_true")
    ap.add_argument("--secim", default=VARSAYILAN_SECIM)
    ap.add_argument("--out", default=VARSAYILAN_TANIM)
    ap.add_argument("--max", type=int, default=25)
    ap.add_argument("--zorla", action="store_true", help="var olan listeyi yeniden yaz (adlar degisebilir)")
    a = ap.parse_args(argv)
    if not a.olustur:
        ap.print_help()
        return 0
    if os.path.exists(a.out) and not a.zorla:
        print(f"{a.out} zaten var (kararli adlar); yeniden yazmak icin --zorla")
        return 1
    with open(a.secim, encoding="utf-8") as fh:
        secim = json.load(fh)
    liste = tanimlar_olustur(secim, a.max)
    for k in liste:
        strateji_tanimi(k)   # dogrulama
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(liste, fh, ensure_ascii=False, indent=1)
    for k in liste:
        print(f"{k['ad']:9s} {k['sym']}_{k['tf']:4s} {k['kaynak'][0]['satir']}"
              + (f"  (+{len(k['kaynak']) - 1} es satir)" if len(k["kaynak"]) > 1 else ""))
    print(f"{len(liste)} kombo -> {a.out}")
    return 0


STRATEGIES = yukle()

if __name__ == "__main__":
    sys.exit(main())
