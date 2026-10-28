"""Kombo XAU (M5) giriş kolu — replay `scripts/strategies/kombo.py` (plan v3) ile seçilen
üç kombinasyonun canlı karşılığı (2026-10-28).

Kombolar (DEFAULT_KOMBOLAR):
  kombo_1 (KMB1): sonra(ut_bot → combo3, n=12), seans 00–07 UTC, SL 3.0×ATR, TP 3R
  kombo_4 (KMB4): or(hma_ao, tsi_ema50), seans 13–20 UTC, SL 1.5×ATR, TP 2R
  kombo_9 (KMB9): sonra(btc_keltner_geri_htf → combo3, n=3), ATR14 yüzdeliği ≥ 50, SL 2.0×ATR, TP 1R

Anlambilim replay ile birebir (parite testi: backend/tests/test_kombo_m5.py):
  * bileşen yönü yalnız i >= 60 için (öncesi 0)
  * or: önce a, a sessizse b;  sonra(n): a'nın [i-1]'e kadar EN SON sinyali j, j >= i-n ve
    b[i] == a[j] ise b[i]
  * etkin ATR: tetikleyen bileşenin ATR'si — tüm bileşenlerde ATR14 (Wilder, SMA tohumu;
    replay `wk.atr` = `eng.wilder_rma` ile aynı, combo3_m5.atr_wilder)
  * seans: saat = ((t + 300) // 3600) % 24, t = bar AÇILIŞ zamanı (giriş = sonraki barın açılışı)
  * atr_yuksek/atr_dusuk: ATR14'ün son 100 bardaki (kendisi dahil) yüzdeliği >= 50 / <= 50

Kapanmış M5 barları ({"time","open","high","low","close"}, time = bar açılışı, UTC sn);
karar barı dizinin son elemanı; look-ahead yok; numpy yok; scripts/ importu yok.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .combo3_m5 import _cross_down, _cross_up, _f, atr_wilder, donchian, ut_bot_stop, vortex

KOMBO_ENTRY_SOURCE = "kombo_m5"
KOMBO_STRATEGY = "KOMBO_M5"
KOMBO_LABEL = "Kombo XAU (M5) — ut_bot→combo3 / hma_ao∪tsi / keltner→combo3"
KOMBO_COMMENT_PREFIX = "KMB"
MIN_BARS = 260  # EMA200 + tampon

SIDE_MIN_I = 60
ATR_PCT_WIN = 100
TF_SEC = 300
TIPLER = ("tek", "or", "sonra")
BILESENLER = ("ut_bot", "combo3", "hma_ao", "tsi_ema50", "btc_keltner_geri_htf")
FILTRELER = ("seans_00_07", "seans_07_20", "seans_13_20", "atr_yuksek", "atr_dusuk")
_SEANSLAR = {"seans_00_07": (0, 7), "seans_07_20": (7, 20), "seans_13_20": (13, 20)}

KOMBO_TAGS = {"kombo_1": "KMB1", "kombo_4": "KMB4", "kombo_9": "KMB9"}
DEFAULT_KOMBOLAR: List[Dict[str, Any]] = [
    {"ad": "kombo_1", "tag": "KMB1",
     "tanim": {"tip": "sonra", "a": "ut_bot", "b": "combo3", "n": 12, "filtre": ["seans_00_07"],
               "sl_atr": 3.0, "tp_r": 3.0}},
    {"ad": "kombo_4", "tag": "KMB4",
     "tanim": {"tip": "or", "a": "hma_ao", "b": "tsi_ema50", "n": None, "filtre": ["seans_13_20"],
               "sl_atr": 1.5, "tp_r": 2.0}},
    {"ad": "kombo_9", "tag": "KMB9",
     "tanim": {"tip": "sonra", "a": "btc_keltner_geri_htf", "b": "combo3", "n": 3, "filtre": ["atr_yuksek"],
               "sl_atr": 2.0, "tp_r": 1.0}},
]


# ------------------------------------------------------------------ doğrulama
def tanim_dogrula(tanim: Any) -> None:
    """Canlı portun desteklediği tanım değilse ValueError."""
    if not isinstance(tanim, dict):
        raise ValueError(f"kombo: tanim dict olmali ({type(tanim).__name__})")
    tip = tanim.get("tip")
    if tip not in TIPLER:
        raise ValueError(f"kombo: desteklenmeyen tip {tip!r} (destekli: {TIPLER})")
    if tanim.get("a") not in BILESENLER:
        raise ValueError(f"kombo: desteklenmeyen bilesen a={tanim.get('a')!r} (destekli: {BILESENLER})")
    if tip != "tek" and tanim.get("b") not in BILESENLER:
        raise ValueError(f"kombo: '{tip}' icin desteklenen b bileseni gerekli (b={tanim.get('b')!r})")
    if tip == "sonra":
        n = tanim.get("n")
        if not (isinstance(n, int) and not isinstance(n, bool) and n >= 1):
            raise ValueError(f"kombo: 'sonra' icin n >= 1 tamsayi gerekli (n={n!r})")
    filtre = tanim.get("filtre") or []
    if not isinstance(filtre, (list, tuple)):
        raise ValueError(f"kombo: filtre liste olmali ({filtre!r})")
    bad = [f for f in filtre if f not in FILTRELER]
    if bad:
        raise ValueError(f"kombo: desteklenmeyen filtre {bad} (destekli: {FILTRELER})")
    try:
        sl_atr, tp_r = float(tanim["sl_atr"]), float(tanim["tp_r"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"kombo: sl_atr/tp_r sayi olmali ({exc})") from None
    if not (sl_atr > 0 and tp_r > 0):
        raise ValueError(f"kombo: sl_atr/tp_r > 0 olmali (sl_atr={sl_atr}, tp_r={tp_r})")


# ------------------------------------------------------------------ göstergeler (replay ile aynı işlem sırası)
def _ema(values: List[float], period: int) -> List[Optional[float]]:
    """xau_week_double_8w.ema: ilk değer SMA tohumu (index period-1)."""
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _ema_sparse(values: List[Optional[float]], period: int) -> List[Optional[float]]:
    """zlmacd_wavetrend_mtf_xau_btc.ema_on_sparse: None'lar atlanarak EMA."""
    idx = [i for i, v in enumerate(values) if v is not None]
    compact = _ema([values[i] for i in idx], period)  # type: ignore[misc]
    out: List[Optional[float]] = [None] * len(values)
    for pos, i in enumerate(idx):
        out[i] = compact[pos]
    return out


def _sma(values: List[Optional[float]], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    for i in range(n - 1, len(values)):
        win = values[i - n + 1:i + 1]
        if any(v is None for v in win):
            continue
        out[i] = sum(win) / n  # type: ignore[arg-type]
    return out


def _wma(values: List[Optional[float]], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    den = n * (n + 1) / 2.0
    for i in range(n - 1, len(values)):
        win = values[i - n + 1:i + 1]
        if any(v is None for v in win):
            continue
        out[i] = sum((k + 1) * v for k, v in enumerate(win)) / den  # type: ignore[operator]
    return out


def _hma(values: List[float], n: int) -> List[Optional[float]]:
    half = _wma(values, max(1, n // 2))  # type: ignore[arg-type]
    full = _wma(values, n)  # type: ignore[arg-type]
    diff = [None if a is None or b is None else 2 * a - b for a, b in zip(half, full)]
    return _wma(diff, max(1, int(round(math.sqrt(n)))))


def _awesome(bars: List[Dict[str, Any]]) -> List[Optional[float]]:
    hl2 = [(_f(x, "high") + _f(x, "low")) / 2 for x in bars]
    f, s = _sma(hl2, 5), _sma(hl2, 34)  # type: ignore[arg-type]
    return [None if a is None or c is None else a - c for a, c in zip(f, s)]


def _tsi(values: List[float], long: int = 25, short: int = 13, sig: int = 13):
    m: List[Optional[float]] = [None] + [values[i] - values[i - 1] for i in range(1, len(values))]
    am = [None if v is None else abs(v) for v in m]
    num = _ema_sparse(_ema_sparse(m, long), short)
    den = _ema_sparse(_ema_sparse(am, long), short)
    t = [None if a is None or c in (None, 0) else 100.0 * a / c for a, c in zip(num, den)]
    return t, _ema_sparse(t, sig)


def seans_saati(t: Any, tf_sec: int = TF_SEC) -> int:
    """Bar açılışı t → girişin (sonraki bar açılışı) UTC saati."""
    return ((int(t) + tf_sec) // 3600) % 24


def atr_yuzdelik(atr: List[Optional[float]], win: int = ATR_PCT_WIN) -> List[Optional[float]]:
    """atr[i]'nin [i-win+1, i] penceresindeki yüzdelik sırası (<= sayısı * 100 / win); eksikse None."""
    n = len(atr)
    out: List[Optional[float]] = [None] * n
    for i in range(win - 1, n):
        w = atr[i - win + 1:i + 1]
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in w):
            continue
        cur = w[-1]
        out[i] = sum(1 for v in w if v <= cur) * 100.0 / win  # type: ignore[operator]
    return out


def filtre_maskeleri(times: List[Any], atr14: List[Optional[float]], adlar) -> Dict[str, Tuple[list, list]]:
    """ad -> (long_ok, short_ok); bar i için yalnız <= i verisi."""
    adlar = list(adlar or [])
    out: Dict[str, Tuple[list, list]] = {}
    saat = None
    for ad in adlar:
        if ad in _SEANSLAR:
            if saat is None:
                saat = [seans_saati(t) for t in times]
            h0, h1 = _SEANSLAR[ad]
            m = [h0 <= s < h1 for s in saat]
            out[ad] = (m, m)
    if "atr_yuksek" in adlar or "atr_dusuk" in adlar:
        p = atr_yuzdelik(atr14)
        if "atr_yuksek" in adlar:
            m = [v is not None and v >= 50 for v in p]
            out["atr_yuksek"] = (m, m)
        if "atr_dusuk" in adlar:
            m = [v is not None and v <= 50 for v in p]
            out["atr_dusuk"] = (m, m)
    return out


# ------------------------------------------------------------------ birleştirici
def birlestir(tip: str, A: List[int], B: Optional[List[int]], n: Optional[int], i: int) -> Tuple[int, str]:
    """Bar i için (yön, kaynak) — kaynak 'a' ya da 'b' (etkin ATR bileşeni)."""
    a = A[i]
    if tip == "tek":
        return a, "a"
    b = B[i]  # type: ignore[index]
    if tip == "or":
        return (a, "a") if a != 0 else (b, "b")
    if tip == "sonra":
        j = i - 1
        while j >= 0 and A[j] == 0:
            j -= 1
        if j < 0 or j < i - n or b == 0 or b != A[j]:  # type: ignore[operator]
            return 0, "b"
        return b, "b"
    raise ValueError(f"kombo: desteklenmeyen tip {tip!r}")


def filtrele(yon: int, maskeler: Dict[str, Tuple[list, list]], filtre: List[str], i: int) -> int:
    for f in filtre:
        lng, sht = maskeler[f]
        if not (lng[i] if yon > 0 else sht[i]):
            return 0
    return yon


# ------------------------------------------------------------------ bileşen yön serileri
class Gostergeler:
    """Bir bar dizisi için tembel hesaplanan göstergeler ve bileşen yön serileri (paylaşımlı)."""

    def __init__(self, bars: List[Dict[str, Any]]):
        self.bars = bars
        self.n = len(bars)
        self.close = [_f(x, "close") for x in bars]
        self.times = [int(x.get("time") or 0) for x in bars]
        self._cache: Dict[str, Any] = {}

    def _get(self, key: str, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    @property
    def atr14(self) -> List[Optional[float]]:
        return self._get("atr14", lambda: atr_wilder(self.bars, 14))

    def yon(self, comp: str) -> List[int]:
        fn = {
            "ut_bot": self._ut_bot,
            "donch_vortex": self._donch_vortex,
            "vortex_adx": self._vortex_adx,
            "combo3": self._combo3,
            "hma_ao": self._hma_ao,
            "tsi_ema50": self._tsi_ema50,
            "btc_keltner_geri_htf": self._keltner,
        }.get(comp)
        if fn is None:
            raise ValueError(f"kombo: desteklenmeyen bilesen {comp!r}")
        return self._get("yon:" + comp, fn)

    def _bos(self) -> List[int]:
        return [0] * self.n

    def _ut_bot(self) -> List[int]:
        u = self._get("ut", lambda: ut_bot_stop(self.bars, 1.0, 10))
        c = self.close
        out = self._bos()
        for i in range(SIDE_MIN_I, self.n):
            if u[i] is None or u[i - 1] is None:
                continue
            if c[i - 1] <= u[i - 1] and c[i] > u[i]:
                out[i] = 1
            elif c[i - 1] >= u[i - 1] and c[i] < u[i]:
                out[i] = -1
        return out

    def _vortex(self):
        return self._get("vortex", lambda: vortex(self.bars, 14))

    def _donch_vortex(self) -> List[int]:
        vp, vm = self._vortex()
        hi, lo = self._get("donchian", lambda: donchian(self.bars, 20))
        c = self.close
        out = self._bos()
        for i in range(SIDE_MIN_I, self.n):
            if None in (hi[i - 1], lo[i - 1], vp[i], vm[i]):
                continue
            if c[i] > hi[i - 1] and vp[i] > vm[i]:
                out[i] = 1
            elif c[i] < lo[i - 1] and vm[i] > vp[i]:
                out[i] = -1
        return out

    def _vortex_adx(self) -> List[int]:
        vp, vm = self._vortex()
        out = self._bos()
        for i in range(SIDE_MIN_I, self.n):
            if _cross_up(vp, vm, i):
                out[i] = 1
            elif _cross_down(vp, vm, i):
                out[i] = -1
        return out

    def _combo3(self) -> List[int]:
        """İlk ateşleyen yön (sıra: ut_bot, donch_vortex, vortex_adx) — bar bazında."""
        u, d, v = self.yon("ut_bot"), self.yon("donch_vortex"), self.yon("vortex_adx")
        return [x or y or z for x, y, z in zip(u, d, v)]

    def _hma_ao(self) -> List[int]:
        h = _hma(self.close, 21)
        ao = _awesome(self.bars)
        out = self._bos()
        for i in range(SIDE_MIN_I, self.n):
            if None in (h[i], h[i - 1], ao[i], ao[i - 1]):
                continue
            if ao[i - 1] <= 0 < ao[i] and h[i] > h[i - 1]:  # type: ignore[operator]
                out[i] = 1
            elif ao[i - 1] >= 0 > ao[i] and h[i] < h[i - 1]:  # type: ignore[operator]
                out[i] = -1
        return out

    def _tsi_ema50(self) -> List[int]:
        t, g = _tsi(self.close)
        e = _ema(self.close, 50)
        c = self.close
        out = self._bos()
        for i in range(SIDE_MIN_I, self.n):
            if e[i] is None:
                continue
            if _cross_up(t, g, i) and t[i] < 0 and c[i] > e[i]:  # type: ignore[operator]
                out[i] = 1
            elif _cross_down(t, g, i) and t[i] > 0 and c[i] < e[i]:  # type: ignore[operator]
                out[i] = -1
        return out

    def _keltner(self) -> List[int]:
        """btc_aile._kelt_side: EMA200 tarafı + önceki kapanış EMA20'nin ters tarafında + yönlü
        bar + kapanış önceki 3 barın en yükseğini/düşüğünü aşar."""
        mid = _ema(self.close, 20)
        e200 = _ema(self.close, 200)
        b = self.bars
        out = self._bos()
        for i in range(max(SIDE_MIN_I, 4), self.n):
            mid1, e = mid[i - 1], e200[i]
            if mid1 is None or e is None:
                continue
            c, o, c1 = self.close[i], _f(b[i], "open"), self.close[i - 1]
            hh3 = max(_f(x, "high") for x in b[i - 3:i])
            ll3 = min(_f(x, "low") for x in b[i - 3:i])
            if c > e and c1 < mid1 and c > o and c > hh3:
                out[i] = 1
            elif c < e and c1 > mid1 and c < o and c < ll3:
                out[i] = -1
        return out


# ------------------------------------------------------------------ kombo serisi / giriş
def _seri(g: Gostergeler, tanim: Dict[str, Any]) -> Tuple[List[int], List[Optional[float]]]:
    tip = tanim["tip"]
    A = g.yon(tanim["a"])
    B = g.yon(tanim["b"]) if tip != "tek" else None
    filtre = list(tanim.get("filtre") or [])
    maskeler = filtre_maskeleri(g.times, g.atr14, filtre) if filtre else {}
    n = tanim.get("n")
    sig = [0] * g.n
    for i in range(g.n):
        yon, _kaynak = birlestir(tip, A, B, n, i)
        if yon:
            yon = filtrele(yon, maskeler, filtre, i)
        sig[i] = yon
    # Etkin ATR: tetikleyen bileşenin ATR'si; replay'de tüm bileşenlerin "atr"si ATR14 (wk.atr).
    return sig, list(g.atr14)


def kombo_side_series(bars: List[Dict[str, Any]], tanim: Dict[str, Any]) -> Tuple[List[int], List[Optional[float]]]:
    """Tüm seri için (bar başına sinyal +1/−1/0, bar başına etkin ATR)."""
    tanim_dogrula(tanim)
    return _seri(Gostergeler(bars or []), tanim)


def sl_tp_pips(sl_atr: float, tp_r: float, atr: Optional[float], pip_size: float) -> Optional[Tuple[float, float]]:
    try:
        if atr is None or not (float(atr) > 0) or not (float(pip_size) > 0):
            return None
        sl = round(float(sl_atr) * float(atr) / float(pip_size), 1)
    except (TypeError, ValueError):
        return None
    if sl <= 0 or math.isnan(sl) or math.isinf(sl):
        return None
    return sl, round(sl * float(tp_r), 1)


def kombo_entries(bars: Optional[List[Dict[str, Any]]], pip_size: float,
                  kombolar: Optional[List[Dict[str, Any]]] = None,
                  sl_atr_override: Optional[float] = None) -> List[Dict[str, Any]]:
    """Son (kapanmış) bar için ateşleyen kombolar; her biri için bir karar sözlüğü.

    Döner: [{"ad","tag","action","sl_pips","tp_pips","atr","close","bar_time","tanim"}, ...]; yoksa [].
    Geçersiz tanım ValueError fırlatır (yapılandırma hatası sessiz geçmesin).
    """
    kombolar = DEFAULT_KOMBOLAR if kombolar is None else kombolar
    for k in kombolar:
        tanim_dogrula(k.get("tanim"))
    try:
        if not bars or len(bars) < MIN_BARS or not (float(pip_size) > 0):
            return []
    except (TypeError, ValueError):
        return []
    g = Gostergeler(bars)
    i = g.n - 1
    out: List[Dict[str, Any]] = []
    for k in kombolar:
        tanim = k["tanim"]
        sig, atr = _seri(g, tanim)
        yon = sig[i]
        if not yon:
            continue
        sl_atr = float(sl_atr_override) if sl_atr_override is not None else float(tanim["sl_atr"])
        r = sl_tp_pips(sl_atr, float(tanim["tp_r"]), atr[i], pip_size)
        if r is None:
            continue
        ad = str(k.get("ad") or "")
        out.append({
            "ad": ad,
            "tag": k.get("tag") or KOMBO_TAGS.get(ad) or KOMBO_COMMENT_PREFIX,
            "action": "BUY" if yon > 0 else "SELL",
            "sl_pips": r[0],
            "tp_pips": r[1],
            "atr": float(atr[i]),  # type: ignore[arg-type]
            "close": g.close[i],
            "bar_time": g.times[i],
            "tanim": tanim,
        })
    return out
