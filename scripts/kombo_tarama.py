#!/usr/bin/env python3
"""Kombinasyon taramasi v3 — sinyal onbellegi + hizli tarama motoru.

Plan: docs/superpowers/plans/2026-10-28-kombinasyon-taramasi-v3.md (Task 1).

Iki alt komut:

  sinyal-uret  Her (sembol, tf) icin onbellek barlarini yukler; 33 stratejinin her biri icin
               `replay_strateji_gunluk.series_for/side_for` ile side[i] in {-1,0,+1} ve etkin ATR
               (degisken SL'li eklentilerde sinyal barinda ezilmis ATR) dizilerini
               outputs/kombo/sinyal_<sym>_<tf>.json dosyasina yazar. Eklenti `symbols` kisiti YOK
               sayilir; bir strateji o sembolde hata verirse atlanir ve loglanir.

  tara         Sinyal dosyasini okur, kombinasyon uzayini YALNIZ egitim penceresinde simule eder ve
               siralar (asama A: tum tekler + ciftler sl 1.5 / tp 2.0 / filtresiz; asama B: ilk 200
               taban x 10 filtre secenegi x 32 cikis varyanti). Egitim ilk 20'si yazildiktan SONRA
               test penceresi bir kez okunur ve ayni dosyaya `test` alanı olarak eklenir. Test
               penceresine bakilarak hicbir siralama/parametre degistirilmez.

Simulator (basit, tutarli):
  * sinyal bari i kapanisi -> giris i+1 acilisi + yon*(spread/2 + kayma)
  * SL mesafesi = sl_atr * atr_eff[i]; TP = tp_r * SL mesafesi (dolum fiyatindan)
  * her barda once SL (low/high), sonra TP; SL bosluklu acilista acilis fiyatindan (kotu yon)
  * basabas: lehte 1R gorulen barin SONRAKI barindan itibaren stop = dolum fiyati
  * cikis maliyeti: spread/2 (+ kayma, yalniz stop tipi cikista: SL / basabas)
  * tek pozisyon; pozisyon acikken (cikis barindan once) yeni sinyal yok
  * pencere sonunda acik pozisyon son pencere barinin kapanisindan kapatilir (pencere disi bar yok)
  * lot = 1000 * risk% / (SL pip * birim deger), 0.01'e asagi yuvarlanir, [0.01, 50]
  * gunluk defter: her gun 1000 USD (lot hep 1000'den), gun P&L (cikis gunu, UTC) >= +500 hedef,
    <= -700 iflas; ayrica kumulatif net, PF = brut kazanc / brut kayip, maxDD (kumulatif egri).

Kullanim (repo kokunden, PYTHONIOENCODING=utf-8):
  python scripts/kombo_tarama.py sinyal-uret --symbols BTCUSD --tfs m15
  python scripts/kombo_tarama.py tara --symbols BTCUSD --tfs m15 [--risk 2] [--max-kombo 5000] [--jobs 4]
  (--symbols/--tfs bos = Spec evreni: BTCUSD/XAUUSD m5+m15, 8 FX m15+m30)
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import multiprocessing
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
OUT_DIR = os.path.join(ROOT, "outputs", "kombo")
SPREAD_DB = os.path.join(ROOT, "outputs", "fx_spread_db_1m.json")

# ------------------------------------------------------------------ sabitler (Spec)
TRAIN = ("2026-07-21", "2026-09-08")   # 21 Tem 00:00 UTC <= t < 8 Eyl
TEST = ("2026-09-08", "2026-10-28")    # 8 Eyl <= t < 28 Eki
KASA = 1000.0
HEDEF_USD = 500.0
IFLAS_USD = -700.0
SL_ATR_SET = (1.0, 1.5, 2.0, 3.0)
TP_R_SET = (1.0, 1.5, 2.0, 3.0)
BASABAS_SET = (False, True)
A_SL, A_TP, A_BE = 1.5, 2.0, False     # asama A cikisi
AND_N = (1, 3, 6)                      # AND(a,b,N): ikisi ayni yonde son N bar icinde (N=1 ayni bar)
SONRA_N = (3, 6, 12)                   # sonra(a,b,N): a son N bar icinde yon verdi, b ayni yonde tetikler
FILTRELER = ("htf_ema200", "seans_07_20", "seans_13_20", "seans_00_07",
             "atr_yuksek", "atr_dusuk", "adx_ge20", "adx_ge25", "adx_lt20")
MIN_ISLEM = 40
TAM_ISLEM = 80
TOP_B = 200
TOP_N = 20
PAD = 64            # pencere oncesi baglam bari (AND/sonra gecmisi icin; bu barlarda islem yok)
SIDE_MIN_I = 60     # side_for yalniz i >= 60 icin cagrilir
LOT_MIN, LOT_MAX, LOT_ADIM = 0.01, 50.0, 0.01
PF_TAVAN = 999.0
FX_PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "GBPJPY", "EURJPY", "NZDUSD")
EVREN = {"BTCUSD": ("m5", "m15"), "XAUUSD": ("m5", "m15"), **{p: ("m15", "m30") for p in FX_PAIRS}}
TF_SEC = {"m1": 60, "m3": 180, "m5": 300, "m15": 900, "m30": 1800}
RISK_VARSAYILAN = {"BTCUSD": 2.0, "XAUUSD": 10.0}   # FX 5
FX_SLIP_PIPS = 1.0
BTC_SPREAD, BTC_SLIP = 5.0, 10.0      # pip = 1 USD
XAU_SPREAD, XAU_SLIP = 2.5, 2.0       # pip = 0.1
SPREAD_VARSAYILAN = 1.5


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def ts_of(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


# ------------------------------------------------------------------ sembol ozellikleri
def pip_size(sym: str) -> float:
    if sym == "BTCUSD":
        return 1.0
    if sym == "XAUUSD":
        return 0.1
    return 0.01 if sym.endswith("JPY") else 0.0001


def risk_varsayilan(sym: str) -> float:
    return RISK_VARSAYILAN.get(sym, 5.0)


def spread_profili() -> dict:
    try:
        with open(SPREAD_DB, encoding="utf-8") as fh:
            raw = json.load(fh).get("symbols", {})
        return {k: float(v["avg_pips"]) for k, v in raw.items() if v.get("avg_pips") is not None}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return {}


def maliyet(sym: str, profil: dict | None = None) -> tuple:
    """(spread_pips, kayma_pips): BTC 5/10 USD, XAU 2.5/2 pip, FX profil/1 pip."""
    if sym == "BTCUSD":
        return BTC_SPREAD, BTC_SLIP
    if sym == "XAUUSD":
        return XAU_SPREAD, XAU_SLIP
    prof = spread_profili() if profil is None else profil
    return float(prof.get(sym, SPREAD_VARSAYILAN)), FX_SLIP_PIPS


def birim_deger(sym: str, kur: float = 1.0) -> float:
    """1 lot icin 1 pip'in USD degeri. kur = 1 quote biriminin USD degeri (FX)."""
    if sym == "XAUUSD":
        return 100.0 * 0.1       # 100 oz x 0.1
    if sym == "BTCUSD":
        return 1.0               # 1 BTC x 1.0
    return 100000.0 * pip_size(sym) * kur


def cache_yolu(sym: str, tf: str) -> str:
    grp = "xaubtc" if sym in ("XAUUSD", "BTCUSD") else "fx21"
    return os.path.join(ROOT, "outputs", f"replay_cache_{grp}_{tf}.json")


_CACHE: dict = {}


def cache_yukle(sym: str, tf: str) -> dict:
    path = cache_yolu(sym, tf)
    if path not in _CACHE:
        with open(path, encoding="utf-8") as fh:
            _CACHE[path] = json.load(fh)
    return _CACHE[path]


def kur_hesapla(sym: str, t0: int, t1: int, data: dict | None = None, tf: str = "m15") -> float:
    """1 quote biriminin USD degeri; quote USD degilse fx21 onbelleginden pencere ortalamasi."""
    if sym in ("XAUUSD", "BTCUSD"):
        return 1.0
    q = sym[3:]
    if q == "USD":
        return 1.0
    if data is None:
        data = cache_yukle("EURUSD", tf)

    def ort(p):
        cs = [float(r[4]) for r in data[p] if t0 <= r[0] < t1]
        if not cs:
            cs = [float(r[4]) for r in data[p]]
        return sum(cs) / len(cs)

    if "USD" + q in data:
        return 1.0 / ort("USD" + q)
    if q + "USD" in data:
        return ort(q + "USD")
    raise ValueError(f"{sym}: quote-USD kuru bulunamadi")


def lot_hesapla(risk_usd, sl_pips, birim):
    """Vektorel: lot = risk / (SL pip * birim), 0.01 asagi yuvarlama, [0.01, 50]."""
    raw = np.asarray(risk_usd, dtype=float) / (np.asarray(sl_pips, dtype=float) * birim)
    lot = np.floor(raw / LOT_ADIM + 1e-9) * LOT_ADIM
    return np.clip(lot, LOT_MIN, LOT_MAX)


# ------------------------------------------------------------------ sinyal-uret
def _r(v, nd=10):
    if v is None:
        return None
    v = float(v)
    if not math.isfinite(v):
        return None
    return float(f"{v:.{nd}g}")


def sinyal_uret(sym: str, tf: str, stratejiler=None, out_dir: str = OUT_DIR) -> str:
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    import replay_strateji_gunluk as rg  # noqa: E402  (eklentileri yukler)

    t_bas = time.time()
    bars = cache_yukle(sym, tf)[sym]
    bars = sorted(bars, key=lambda r: r[0])
    n = len(bars)
    rg._BARS.pop(sym, None)
    rg._SERIES.pop(sym, None)
    b = rg.bars_of(sym, bars)
    atr14 = [_r(v) for v in rg.wk.atr(b, 14)]
    names = list(stratejiler or rg.STRATEGIES)
    sinyaller, atr_eff, hatalar, sureler = {}, {}, {}, {}
    for k, strat in enumerate(names):
        t0 = time.time()
        try:
            s = rg.series_for(sym, strat, bars)
            b = rg.bars_of(sym, bars)
            side = [0] * n
            for i in range(SIDE_MIN_I, n):
                v = rg.side_for(strat, s, b, i)
                side[i] = 1 if v and v > 0 else (-1 if v and v < 0 else 0)
            atr = [_r(v) for v in s["atr"]]
        except Exception as e:  # noqa: BLE001 — strateji bu sembolde calismiyor: atla
            hatalar[strat] = f"{type(e).__name__}: {e}"[:300]
            log(f"  {sym} {tf} {strat}: ATLANDI ({hatalar[strat][:120]})")
            continue
        finally:
            rg._SERIES.pop(sym, None)
        sinyaller[strat] = side
        farkli = any((x is None) != (y is None) or (x is not None and abs(x - y) > 1e-9 * max(1.0, abs(y)))
                     for x, y in zip(atr, atr14))
        if farkli:
            atr_eff[strat] = atr
        sureler[strat] = round(time.time() - t0, 2)
        nz = sum(1 for v in side if v)
        log(f"  {sym} {tf} [{k + 1}/{len(names)}] {strat}: {nz} sinyal{' (atr_eff)' if farkli else ''} "
            f"{sureler[strat]}s")
    spread, slip = maliyet(sym)
    doc = {
        "sym": sym, "tf": tf, "tf_sec": TF_SEC[tf], "n": n,
        "t": [int(r[0]) for r in bars],
        "o": [float(r[1]) for r in bars], "h": [float(r[2]) for r in bars],
        "l": [float(r[3]) for r in bars], "c": [float(r[4]) for r in bars],
        "pip_size": pip_size(sym), "spread_pips": spread, "slip_pips": slip,
        "atr14": atr14,
        "side": sinyaller,          # strateji -> dense [-1/0/+1] * n
        "atr_eff": atr_eff,          # yalniz atr14'ten farkli olanlar (digerleri = atr14)
        "hatalar": hatalar, "sure_sn": sureler,
        "uretim": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"sinyal_{sym}_{tf}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    log(f"{sym} {tf}: {len(sinyaller)} strateji, {len(hatalar)} atlandi, {time.time() - t_bas:.1f}s -> {path}")
    return path


# ------------------------------------------------------------------ gostergeler / filtreler (nedensel)
def htf_ema(t, c, tf_sec: int, period: int = 200, htf: int = 3600) -> np.ndarray:
    """H1 EMA200: bar i saati tamamlarsa (t+tf >= saat sonu) EMA o kapanisla guncellenir.
    Deger bar i kapanisinda bilinen son tamamlanmis saatin EMA'si; period saat dolmadan NaN."""
    n = len(c)
    out = np.full(n, np.nan)
    a = 2.0 / (period + 1)
    ema, cnt = None, 0
    tl, cl = np.asarray(t).tolist(), np.asarray(c, dtype=float).tolist()
    for i in range(n):
        if tl[i] + tf_sec >= (tl[i] // htf + 1) * htf:
            ema = cl[i] if ema is None else a * cl[i] + (1 - a) * ema
            cnt += 1
        if cnt >= period:
            out[i] = ema
    return out


def atr_yuzdelik(atr, win: int = 100) -> np.ndarray:
    """ATR(14)'un son `win` bardaki (kendisi dahil) yuzdelik sirasi (0-100); eksikse NaN."""
    a = np.asarray(atr, dtype=float)
    n = len(a)
    out = np.full(n, np.nan)
    if n < win:
        return out
    w = np.lib.stride_tricks.sliding_window_view(a, win)   # w[k] = a[k:k+win], son eleman a[k+win-1]
    cur = w[:, -1:]
    pct = (w <= cur).sum(axis=1) * 100.0 / win
    ok = ~np.isnan(w).any(axis=1)
    out[win - 1:] = np.where(ok, pct, np.nan)
    return out


def adx_seri(h, l, c, n: int = 14) -> np.ndarray:
    """Wilder ADX(n)."""
    h, l, c = (np.asarray(x, dtype=float) for x in (h, l, c))
    m = len(c)
    out = np.full(m, np.nan)
    if m < 2 * n + 2:
        return out
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    pdm = np.where((up > dn) & (up > 0), up, 0.0).tolist()
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0).tolist()
    tr = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])]).tolist()
    s_tr, s_p, s_m = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n])
    dxs = []
    adx = None
    for k in range(n - 1, m - 1):          # k: tr/dm indeksi, bar = k+1
        if k >= n:
            s_tr = s_tr - s_tr / n + tr[k]
            s_p = s_p - s_p / n + pdm[k]
            s_m = s_m - s_m / n + mdm[k]
        pdi = 100.0 * s_p / s_tr if s_tr > 0 else 0.0
        mdi = 100.0 * s_m / s_tr if s_tr > 0 else 0.0
        dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
        if adx is None:
            dxs.append(dx)
            if len(dxs) == n:
                adx = sum(dxs) / n
                out[k + 1] = adx
        else:
            adx = (adx * (n - 1) + dx) / n
            out[k + 1] = adx
    return out


def filtre_maskeleri(t, o, h, l, c, atr14, tf_sec: int) -> dict:
    """ad -> (long_ok, short_ok) bool dizileri; bar i sinyali icin yalniz <= i verisi."""
    t = np.asarray(t, dtype=np.int64)
    c = np.asarray(c, dtype=float)
    ema = htf_ema(t, c, tf_sec)
    with np.errstate(invalid="ignore"):
        ema_l, ema_s = c > ema, c < ema
    saat = ((t + tf_sec) // 3600) % 24        # giris (i+1 acilisi) saati, UTC
    pct = atr_yuzdelik(atr14)
    adx = adx_seri(h, l, c)
    with np.errstate(invalid="ignore"):
        m = {
            "htf_ema200": (ema_l, ema_s),
            "seans_07_20": (saat >= 7) & (saat < 20),
            "seans_13_20": (saat >= 13) & (saat < 20),
            "seans_00_07": (saat >= 0) & (saat < 7),
            "atr_yuksek": pct >= 50,
            "atr_dusuk": pct <= 50,
            "adx_ge20": adx >= 20,
            "adx_ge25": adx >= 25,
            "adx_lt20": adx < 20,
        }
    return {k: (v if isinstance(v, tuple) else (v, v)) for k, v in m.items()}


# ------------------------------------------------------------------ kombinasyonlar
def _pencere_say(x: np.ndarray, n: int) -> np.ndarray:
    """x (bool) icin [i-n+1, i] araligindaki True sayisi."""
    cs = np.cumsum(x.astype(np.int32))
    out = cs.copy()
    if n < len(cs):
        out[n:] = cs[n:] - cs[:-n]
    return out


def kombo_birlestir(tip: str, A, B=None, n=None, src_a: int = 0, src_b: int = 0) -> tuple:
    """(sig int8, src int16): src = sinyali tetikleyen bilesenin atr kimligi."""
    A = np.asarray(A, dtype=np.int8)
    m = len(A)
    if tip == "tek":
        return A.copy(), np.full(m, src_a, dtype=np.int16)
    B = np.asarray(B, dtype=np.int8)
    if tip == "or":                       # ilk ateslenen: once a, sonra b
        sig = np.where(A != 0, A, B).astype(np.int8)
        src = np.where(A != 0, src_a, src_b).astype(np.int16)
        return sig, src
    if tip == "and":                      # biri bu barda, digeri son n bar icinde ayni yonde
        a_u, a_d, b_u, b_d = A == 1, A == -1, B == 1, B == -1
        wa_u, wa_d = _pencere_say(a_u, n) > 0, _pencere_say(a_d, n) > 0
        wb_u, wb_d = _pencere_say(b_u, n) > 0, _pencere_say(b_d, n) > 0
        lng = (a_u & wb_u) | (b_u & wa_u)
        sht = (a_d & wb_d) | (b_d & wa_d)
        sig = (lng.astype(np.int8) - sht.astype(np.int8)).astype(np.int8)
        src = np.where((sig != 0) & (A == sig), src_a, src_b).astype(np.int16)
        return sig, src
    if tip == "sonra":                    # a'nin [i-n, i-1] icindeki en son sinyali yon verir, b tetikler
        idx = np.where(A != 0, np.arange(m), -1)
        last = np.maximum.accumulate(idx)
        prev = np.empty(m, dtype=np.int64)
        prev[0] = -1
        prev[1:] = last[:-1]
        ar = np.arange(m)
        ok = (prev >= 0) & (prev >= ar - n)
        yon = np.where(prev >= 0, A[np.maximum(prev, 0)], 0)
        sig = np.where(ok & (B != 0) & (B == yon), B, 0).astype(np.int8)
        return sig, np.full(m, src_b, dtype=np.int16)
    raise ValueError(tip)


def filtre_uygula(sig: np.ndarray, maske: tuple | None) -> np.ndarray:
    if maske is None:
        return sig
    ok = np.where(sig > 0, maske[0], maske[1])
    return np.where(ok, sig, 0).astype(np.int8)


def kombo_adi(k: dict) -> str:
    if k["tip"] == "tek":
        g = k["a"]
    elif k["tip"] == "or":
        g = f"or({k['a']},{k['b']})"
    else:
        g = f"{k['tip']}({k['a']},{k['b']},{k['n']})"
    f = "+".join(k.get("filtre") or []) or "-"
    return f"{g}|{f}|sl{k['sl_atr']}_tp{k['tp_r']}{'_be' if k['basabas'] else ''}"


def kombo(tip, a, b=None, n=None, filtre=None, sl_atr=A_SL, tp_r=A_TP, basabas=A_BE) -> dict:
    return {"tip": tip, "a": a, "b": b, "n": n, "filtre": list(filtre or []),
            "sl_atr": float(sl_atr), "tp_r": float(tp_r), "basabas": bool(basabas)}


def cikis_varyantlari() -> list:
    """sl_atr x tp_r x basabas; tp_r <= 1 iken basabas etkisiz (TP 1R'de/once) -> tekrari atlanir."""
    return [(s, t, b) for s in SL_ATR_SET for t in TP_R_SET for b in BASABAS_SET if not (b and t <= 1.0)]


def asama_a_uzayi(names, and_n=AND_N, sonra_n=SONRA_N) -> list:
    out = [kombo("tek", a) for a in names]
    out += [kombo("or", a, b) for a, b in itertools.combinations(names, 2)]
    out += [kombo("and", a, b, n) for a, b in itertools.combinations(names, 2) for n in and_n]
    out += [kombo("sonra", a, b, n) for a, b in itertools.permutations(names, 2) for n in sonra_n]
    return out


# ------------------------------------------------------------------ veri
def veri_yukle(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return veri_hazirla(doc)


def veri_hazirla(doc: dict) -> dict:
    """Sinyal dokumani -> numpy veri (+ nedensel filtre maskeleri, tum dizi uzerinde)."""
    t = np.asarray(doc["t"], dtype=np.int64)
    o, h, l, c = (np.asarray(doc[k], dtype=float) for k in ("o", "h", "l", "c"))
    atr14 = np.array([np.nan if v is None else v for v in doc["atr14"]], dtype=float)
    names = list(doc["side"].keys())
    side = np.array([doc["side"][s] for s in names], dtype=np.int8).reshape(len(names), len(t))
    atr_tab = [atr14]
    atr_id = {}
    for s in names:
        if s in doc.get("atr_eff", {}):
            atr_id[s] = len(atr_tab)
            atr_tab.append(np.array([np.nan if v is None else v for v in doc["atr_eff"][s]], dtype=float))
        else:
            atr_id[s] = 0
    tf_sec = int(doc.get("tf_sec") or TF_SEC[doc["tf"]])
    return {
        "sym": doc["sym"], "tf": doc["tf"], "tf_sec": tf_sec,
        "t": t, "o": o, "h": h, "l": l, "c": c, "names": names, "side": side,
        "atr_tab": np.vstack(atr_tab), "atr_id": atr_id,
        "pip": float(doc["pip_size"]), "spread": float(doc["spread_pips"]), "slip": float(doc["slip_pips"]),
        "maske": filtre_maskeleri(t, o, h, l, c, atr14, tf_sec),
        "hatalar": doc.get("hatalar", {}),
    }


# ------------------------------------------------------------------ ilk isabet (seyrek tablo)
def seyrek_tablo(x: np.ndarray, asagi: bool) -> list:
    """asagi=True: blok minimumu (+inf dolgu); False: blok maksimumu (-inf dolgu). Uzunluk m+1."""
    pad = np.inf if asagi else -np.inf
    fn = np.minimum if asagi else np.maximum
    m = len(x)
    tabs = [np.append(np.asarray(x, dtype=float), pad)]
    p = 1
    while (1 << (p - 1)) < m:
        prev, half = tabs[-1], 1 << (p - 1)
        sh = np.full(m + 1, pad)
        sh[:m + 1 - half] = prev[half:]
        tabs.append(fn(prev, sh))
        p += 1
    return tabs


def ilk_isabet(tabs: list, start, level, asagi: bool) -> np.ndarray:
    """Her k icin en kucuk j >= start[k], x[j] <= level[k] (asagi) / >= level[k]; yoksa m."""
    m = len(tabs[0]) - 1
    pos = np.minimum(np.asarray(start, dtype=np.int64), m)
    level = np.asarray(level, dtype=float)
    for p in range(len(tabs) - 1, -1, -1):
        blk = tabs[p][pos]
        hit = (blk <= level) if asagi else (blk >= level)
        pos = np.where(hit | (pos >= m), pos, np.minimum(pos + (1 << p), m))
    return pos


# ------------------------------------------------------------------ pencere baglami
class Pencere:
    """Bir zaman penceresi [t0, t1) icin dilimlenmis diziler (+ PAD bar gecmis baglam).

    Islem acilabilen sinyal barlari: yerel [start, m-2] (giris i+1 pencere icinde). Pencere
    disindaki (t >= t1) hicbir bar bu nesnede yoktur."""

    def __init__(self, veri: dict, t0: int, t1: int, ad: str, risk_pct: float, kur: float = 1.0):
        t = veri["t"]
        ws = int(np.searchsorted(t, t0, "left"))
        we = int(np.searchsorted(t, t1, "left"))
        lo = max(0, ws - PAD)
        sl = slice(lo, we)
        self.ad, self.t0, self.t1 = ad, t0, t1
        self.sym = veri["sym"]
        self.t = t[sl]
        self.o, self.h, self.l, self.c = (veri[k][sl] for k in ("o", "h", "l", "c"))
        self.m = len(self.t)
        self.start = ws - lo
        self.names = veri["names"]
        self.nidx = {s: k for k, s in enumerate(self.names)}
        self.side = veri["side"][:, sl]
        self.atr_tab = veri["atr_tab"][:, sl]
        self.atr_id = veri["atr_id"]
        self.maske = {k: (a[sl], b[sl]) for k, (a, b) in veri["maske"].items()}
        self.pip = veri["pip"]
        self.half = veri["spread"] * self.pip / 2.0
        self.slip = veri["slip"] * self.pip
        self.kur = kur
        self.birim = birim_deger(self.sym, kur)
        self.risk_pct = risk_pct
        self.risk_usd = KASA * risk_pct / 100.0
        self.gun = self.t // 86400
        self._low = seyrek_tablo(self.l, True) if self.m else None
        self._high = seyrek_tablo(self.h, False) if self.m else None
        self._tablo: dict = {}

    def tablo(self, sl_atr: float, tp_r: float, be: bool) -> tuple:
        key = (float(sl_atr), float(tp_r), bool(be and tp_r > 1.0))
        if key not in self._tablo:
            self._tablo[key] = cikis_tablosu(self, *key)
        return self._tablo[key]


def cikis_tablosu(ctx: Pencere, sl_atr: float, tp_r: float, be: bool) -> tuple:
    """Her atr kimligi K, yon (0=long, 1=short) ve sinyal bari i icin: (cikis bari, P&L USD).
    Gecersiz (pencere disi giris / atr yok) = cikis -1."""
    K, m = ctx.atr_tab.shape[0], ctx.m
    ex_tab = np.full((K, 2, m), -1, dtype=np.int32)
    pnl_tab = np.zeros((K, 2, m), dtype=float)
    if m < 2 or ctx.start > m - 2:
        return ex_tab, pnl_tab
    i = np.arange(ctx.start, m - 1)
    e = i + 1
    o, h, l, c = ctx.o, ctx.h, ctx.l, ctx.c
    for k in range(K):
        atr = ctx.atr_tab[k, i]
        valid = np.isfinite(atr) & (atr > 0)
        if not valid.any():
            continue
        iv, ev, dist = i[valid], e[valid], sl_atr * atr[valid]
        for di, d in enumerate((1, -1)):
            fill = o[ev] + d * (ctx.half + ctx.slip)
            SL = fill - d * dist
            TP = fill + d * tp_r * dist
            if d > 0:
                jS = ilk_isabet(ctx._low, ev, SL, True)
                jT = ilk_isabet(ctx._high, ev, TP, False)
            else:
                jS = ilk_isabet(ctx._high, ev, SL, False)
                jT = ilk_isabet(ctx._low, ev, TP, True)
            ex = np.full(len(iv), m - 1, dtype=np.int64)
            px = c[m - 1] - d * ctx.half + np.zeros(len(iv))     # pencere sonu kapanisi
            sl_hit = (jS < m) & (jS <= jT)
            tp_hit = ~sl_hit & (jT < m)
            jSc = np.minimum(jS, m - 1)
            sl_px = np.minimum(SL, o[jSc]) if d > 0 else np.maximum(SL, o[jSc])
            ex = np.where(sl_hit, jS, np.where(tp_hit, jT, ex))
            px = np.where(sl_hit, sl_px - d * (ctx.half + ctx.slip), np.where(tp_hit, TP - d * ctx.half, px))
            if be:
                R1 = fill + d * dist
                j1 = ilk_isabet(ctx._high, ev, R1, False) if d > 0 else ilk_isabet(ctx._low, ev, R1, True)
                on = (j1 < m) & (j1 < jS) & (jT > j1)
                if on.any():
                    w = np.flatnonzero(on)
                    st = j1[w] + 1
                    if d > 0:
                        jB = ilk_isabet(ctx._low, st, fill[w], True)
                    else:
                        jB = ilk_isabet(ctx._high, st, fill[w], False)
                    jT_w = jT[w]
                    be_hit = (jB < m) & (jB <= jT_w)
                    tp_w = ~be_hit & (jT_w < m)
                    jBc = np.minimum(jB, m - 1)
                    be_px = np.minimum(fill[w], o[jBc]) if d > 0 else np.maximum(fill[w], o[jBc])
                    ex[w] = np.where(be_hit, jB, np.where(tp_w, jT_w, m - 1))
                    px[w] = np.where(be_hit, be_px - d * (ctx.half + ctx.slip),
                                     np.where(tp_w, TP[w] - d * ctx.half, c[m - 1] - d * ctx.half))
            pips = d * (px - fill) / ctx.pip
            lot = lot_hesapla(ctx.risk_usd, dist / ctx.pip, ctx.birim)
            ex_tab[k, di, iv] = ex
            pnl_tab[k, di, iv] = lot * pips * ctx.birim
    return ex_tab, pnl_tab


# ------------------------------------------------------------------ degerlendirme
def _zincir(nxt: list) -> list:
    out, k, n = [], 0, len(nxt)
    while k < n:
        out.append(k)
        k = nxt[k]
    return out


def islemler(ctx: Pencere, sig: np.ndarray, src: np.ndarray, sl_atr, tp_r, be) -> tuple:
    """Tek pozisyon simulasyonu -> (sinyal bari, cikis bari, pnl) dizileri (alinan islemler)."""
    ex_tab, pnl_tab = ctx.tablo(sl_atr, tp_r, be)
    if ctx.m < 2 or ctx.start > ctx.m - 2:
        z = np.zeros(0, dtype=np.int64)
        return z, z, np.zeros(0)
    idx = np.flatnonzero(sig[ctx.start:ctx.m - 1]) + ctx.start
    if not len(idx):
        z = np.zeros(0, dtype=np.int64)
        return z, z, np.zeros(0)
    dk = (sig[idx] < 0).astype(np.int64)
    a = src[idx].astype(np.int64)
    ex = ex_tab[a, dk, idx]
    ok = ex >= 0
    idx, dk, a, ex = idx[ok], dk[ok], a[ok], ex[ok]
    if not len(idx):
        z = np.zeros(0, dtype=np.int64)
        return z, z, np.zeros(0)
    nxt = np.searchsorted(idx, ex, "left")     # cikis barindan once gelen sinyaller atlanir
    tk = np.asarray(_zincir(nxt.tolist()), dtype=np.int64)
    return idx[tk], ex[tk].astype(np.int64), pnl_tab[a[tk], dk[tk], idx[tk]]


def metrikler(pnl: np.ndarray, gun: np.ndarray) -> dict:
    n = int(len(pnl))
    if n == 0:
        return {"islem": 0, "pf": 0.0, "net": 0.0, "wr": 0.0, "maxdd": 0.0, "iflas_gun": 0,
                "hedef_gun": 0, "islem_gun": 0, "skor": None}
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    pf = gw / gl if gl > 0 else (PF_TAVAN if gw > 0 else 0.0)
    pf = min(pf, PF_TAVAN)
    eq = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate(([0.0], eq)))[1:]
    dd = float((peak - eq).max())
    u, inv = np.unique(gun, return_inverse=True)
    dsum = np.bincount(inv, weights=pnl)
    return {
        "islem": n, "pf": round(pf, 4), "net": round(float(eq[-1]), 2),
        "wr": round(float((pnl > 0).mean()), 4), "maxdd": round(dd, 2),
        "iflas_gun": int((dsum <= IFLAS_USD).sum()), "hedef_gun": int((dsum >= HEDEF_USD).sum()),
        "islem_gun": int(len(u)),
        "skor": round(pf * min(1.0, n / TAM_ISLEM), 4) if n >= MIN_ISLEM else None,
    }


def kombo_sinyali(ctx: Pencere, k: dict) -> tuple:
    A = ctx.side[ctx.nidx[k["a"]]]
    B = ctx.side[ctx.nidx[k["b"]]] if k.get("b") else None
    sig, src = kombo_birlestir(k["tip"], A, B, k.get("n"), ctx.atr_id[k["a"]],
                               ctx.atr_id[k["b"]] if k.get("b") else 0)
    for f in k.get("filtre") or []:
        sig = filtre_uygula(sig, ctx.maske[f])
    return sig, src


def kombo_calistir(ctx: Pencere, k: dict) -> dict:
    sig, src = kombo_sinyali(ctx, k)
    _i, ex, pnl = islemler(ctx, sig, src, k["sl_atr"], k["tp_r"], k["basabas"])
    return metrikler(pnl, ctx.gun[ex])


def _sira_anahtari(r):
    return (-(r["m"]["skor"] if r["m"]["skor"] is not None else -1.0), -r["m"]["net"], r["ad"])


def egitim_sirala(ctx: Pencere, names=None, top_b: int = TOP_B, max_kombo: int | None = None,
                  and_n=AND_N, sonra_n=SONRA_N, ilerleme: bool = True) -> tuple:
    """YALNIZ egitim baglami alir; asama A + asama B; tum sonuclari skora gore siralar.

    Donus: (sirali sonuc listesi [{"kombo","ad","m"}], sayaclar)."""
    names = list(names if names is not None else ctx.names)
    uzay = asama_a_uzayi(names, and_n, sonra_n)
    if max_kombo is not None:
        uzay = uzay[:max_kombo]
    t0 = time.time()
    sonuc, gorulen = [], set()
    for j, k in enumerate(uzay):
        r = {"kombo": k, "ad": kombo_adi(k), "m": kombo_calistir(ctx, k)}
        sonuc.append(r)
        gorulen.add(r["ad"])
        if ilerleme and (j + 1) % 1000 == 0:
            log(f"  {ctx.sym} A {j + 1}/{len(uzay)} ({time.time() - t0:.1f}s)")
    n_a = len(sonuc)
    taban = sorted(sonuc, key=_sira_anahtari)[:top_b]
    cikislar = cikis_varyantlari()
    butce = None if max_kombo is None else max(0, max_kombo - n_a)
    n_b, t1 = 0, time.time()
    secenekler = [None] + list(FILTRELER)
    toplam_b = len(taban) * len(secenekler) * len(cikislar)
    dur = False
    for bi, base in enumerate(taban):
        bk = base["kombo"]
        sig0, src = kombo_sinyali(ctx, {**bk, "filtre": []})
        for f in secenekler:
            sig = filtre_uygula(sig0, ctx.maske[f]) if f else sig0
            for (s, t, b) in cikislar:
                k = {**bk, "filtre": [f] if f else [], "sl_atr": s, "tp_r": t, "basabas": b}
                ad = kombo_adi(k)
                if ad in gorulen:
                    continue
                if butce is not None and n_b >= butce:
                    dur = True
                    break
                _i, ex, pnl = islemler(ctx, sig, src, s, t, b)
                sonuc.append({"kombo": k, "ad": ad, "m": metrikler(pnl, ctx.gun[ex])})
                gorulen.add(ad)
                n_b += 1
            if dur:
                break
        if ilerleme and (bi + 1) % 20 == 0:
            log(f"  {ctx.sym} B taban {bi + 1}/{len(taban)} ({n_b} sim, {time.time() - t1:.1f}s)")
        if dur:
            break
    sonuc.sort(key=_sira_anahtari)
    say = {"stage_a": n_a, "stage_b": n_b, "stage_b_plan": toplam_b,
           "nitelikli": sum(1 for r in sonuc if r["m"]["skor"] is not None),
           "sure_a_sn": round(t1 - t0, 1), "sure_b_sn": round(time.time() - t1, 1)}
    return sonuc, say


def tara_veri(veri: dict, risk_pct: float | None = None, max_kombo: int | None = None,
              top_b: int = TOP_B, top_n: int = TOP_N, out_path: str | None = None,
              kur_fn=None, ilerleme: bool = True) -> dict:
    """Walk-forward: egitimde sirala -> ilk top_n yaz -> test penceresini bir kez oku -> yaz."""
    sym, tf = veri["sym"], veri["tf"]
    risk = risk_varsayilan(sym) if risk_pct is None else risk_pct
    kur_fn = kur_fn or (lambda s, a, b: kur_hesapla(s, a, b, tf=tf))
    tr0, tr1, te0, te1 = ts_of(TRAIN[0]), ts_of(TRAIN[1]), ts_of(TEST[0]), ts_of(TEST[1])
    # kullanilabilir stratejiler: hata vermeyen ve EGITIM bitisinden once en az 1 sinyali olan
    # (test penceresindeki sinyal varligi evreni etkilemez)
    k_tr1 = int(np.searchsorted(veri["t"], tr1, "left"))
    names = [s for k, s in enumerate(veri["names"]) if np.any(veri["side"][k, :k_tr1] != 0)]
    egitim = Pencere(veri, tr0, tr1, "egitim", risk, kur_fn(sym, tr0, tr1))
    t_bas = time.time()
    sirali, say = egitim_sirala(egitim, names, top_b=top_b, max_kombo=max_kombo, ilerleme=ilerleme)
    top = [{"kombo": r["kombo"], "ad": r["ad"], "train": r["m"]} for r in sirali[:top_n]
           if r["m"]["skor"] is not None]
    params = {
        "sym": sym, "tf": tf, "train": list(TRAIN), "test": list(TEST), "risk_pct": risk,
        "kasa": KASA, "hedef_usd": HEDEF_USD, "iflas_usd": IFLAS_USD,
        "pip_size": veri["pip"], "spread_pips": veri["spread"], "slip_pips": veri["slip"],
        "birim_usd_pip_lot_train": egitim.birim, "kur_train": egitim.kur,
        "a_cikis": {"sl_atr": A_SL, "tp_r": A_TP, "basabas": A_BE}, "and_n": list(AND_N),
        "sonra_n": list(SONRA_N), "filtreler": list(FILTRELER), "sl_atr_set": list(SL_ATR_SET),
        "tp_r_set": list(TP_R_SET), "basabas_set": list(BASABAS_SET), "top_b": top_b,
        "min_islem": MIN_ISLEM, "skor": "PF x min(1, islem/80), islem >= 40",
        "max_kombo": max_kombo, "stratejiler": names,
        "atlanan": {**veri.get("hatalar", {}),
                    **{s: "sinyal yok" for s in veri["names"] if s not in names}},
        "egitim_bar": int(egitim.m - egitim.start),
    }
    doc = {"universe_size": say["stage_a"] + say["stage_b"], "stage_a": say["stage_a"],
           "stage_b": say["stage_b"], "nitelikli": say["nitelikli"], "train_top": top,
           "params": params, "sure_sn": {"a": say["sure_a_sn"], "b": say["sure_b_sn"]},
           "test_okundu": False}
    if out_path:
        _yaz(out_path, doc)
    # ---- test penceresi: siralama bitti, yalniz ilk top_n bir kez okunur
    test = Pencere(veri, te0, te1, "test", risk, kur_fn(sym, te0, te1))
    for r in top:
        r["test"] = kombo_calistir(test, r["kombo"])
    doc["params"].update({"birim_usd_pip_lot_test": test.birim, "kur_test": test.kur,
                          "test_bar": int(test.m - test.start)})
    doc["test_okundu"] = True
    doc["test_tutunan_pf12"] = sum(1 for r in top if r["test"]["islem"] > 0 and r["test"]["pf"] >= 1.2)
    doc["sure_sn"]["toplam"] = round(time.time() - t_bas, 1)
    if out_path:
        _yaz(out_path, doc)
    return doc


def _yaz(path: str, doc: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def tara(sym: str, tf: str, risk_pct=None, max_kombo=None, top_b=TOP_B, out_dir: str = OUT_DIR) -> str:
    t0 = time.time()
    src = os.path.join(out_dir, f"sinyal_{sym}_{tf}.json")
    if not os.path.exists(src):
        raise SystemExit(f"sinyal dosyasi yok: {src} (once sinyal-uret)")
    veri = veri_yukle(src)
    log(f"{sym} {tf}: veri yuklendi ({len(veri['names'])} strateji, {len(veri['t'])} bar, "
        f"{time.time() - t0:.1f}s)")
    out = os.path.join(out_dir, f"tarama_{sym}_{tf}.json")
    doc = tara_veri(veri, risk_pct, max_kombo, top_b, out_path=out)
    log(f"{sym} {tf}: A {doc['stage_a']} + B {doc['stage_b']} = {doc['universe_size']} kombo, "
        f"nitelikli {doc['nitelikli']}, testte PF>=1.2: {doc['test_tutunan_pf12']}/{len(doc['train_top'])}, "
        f"{time.time() - t0:.1f}s -> {out}")
    for r in doc["train_top"][:5]:
        a, b = r["train"], r["test"]
        log(f"    {r['ad']}: egitim n={a['islem']} pf={a['pf']} net={a['net']} | "
            f"test n={b['islem']} pf={b['pf']} net={b['net']}")
    return out


# ------------------------------------------------------------------ CLI
def _isler(args) -> list:
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else list(EVREN)
    out = []
    for s in syms:
        tfs = [x.strip() for x in args.tfs.split(",") if x.strip()] if args.tfs else list(EVREN.get(s, ("m15",)))
        out += [(s, tf) for tf in tfs]
    return out


def _is_sinyal(job):
    sym, tf, strats = job
    try:
        return sinyal_uret(sym, tf, strats)
    except Exception as e:  # noqa: BLE001
        log(f"{sym} {tf}: HATA {type(e).__name__}: {e}")
        return None


def _is_tara(job):
    sym, tf, risk, mk, tb = job
    try:
        return tara(sym, tf, risk, mk, tb)
    except Exception as e:  # noqa: BLE001
        log(f"{sym} {tf}: HATA {type(e).__name__}: {e}")
        return None


def _kos(fn, jobs: list, n_jobs: int) -> list:
    if n_jobs <= 1 or len(jobs) <= 1:
        return [fn(j) for j in jobs]
    with multiprocessing.Pool(min(n_jobs, len(jobs))) as pool:
        return pool.map(fn, jobs, chunksize=1)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("sinyal-uret", "tara"):
        p = sub.add_parser(name)
        p.add_argument("--symbols", default="", help="virgullu; bos = Spec evreni")
        p.add_argument("--tfs", default="", help="virgullu (m5,m15,m30); bos = sembol varsayilani")
        p.add_argument("--jobs", type=int, default=1, help="sembol x tf paralel surec sayisi")
        if name == "sinyal-uret":
            p.add_argument("--strategies", default="", help="virgullu alt kume (bos = 33'un hepsi)")
        else:
            p.add_argument("--risk", type=float, default=None, help="risk %% (bos = sistem: FX 5, BTC 2, XAU 10)")
            p.add_argument("--max-kombo", type=int, default=None, help="toplam simulasyon tavani (bos = sinirsiz)")
            p.add_argument("--top-b", type=int, default=TOP_B, help="asama B'ye gecen taban sayisi")
    args = ap.parse_args(argv)
    isler = _isler(args)
    t0 = time.time()
    log(f"{args.cmd}: {len(isler)} is ({', '.join(f'{s}_{t}' for s, t in isler)}), jobs={args.jobs}")
    if args.cmd == "sinyal-uret":
        strats = [s.strip() for s in args.strategies.split(",") if s.strip()] or None
        res = _kos(_is_sinyal, [(s, tf, strats) for s, tf in isler], args.jobs)
    else:
        res = _kos(_is_tara, [(s, tf, args.risk, args.max_kombo, args.top_b) for s, tf in isler], args.jobs)
    ok = sum(1 for r in res if r)
    log(f"{args.cmd}: {ok}/{len(isler)} tamam, {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
