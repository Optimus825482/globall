"""FX ozgun giris-strateji ailesi (replay_strateji_gunluk eklentisi).

Klasik gosterge kombinasyonlarinin (MACD/RSI/Stoch/BB/Keltner/Donchian/Supertrend/HMA/Vortex/
UT Bot/ORB/NR7/pullback) disinda, yapisal/istatistiksel fikirler. Parametreler SABIT (grid yok).
Kapsam: EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF, GBPJPY, EURJPY, NZDUSD; M15 ve M30.
`spread_min_mult = 8.0`: sarmalayici, SL pip < 8 x spread pip olan adayi reddeder
(bu dosyada kapi uygulanmaz, yalniz alan tanimlanir).

  fx_seans_devri      07:00-09:00 UTC Londra hareketi >= 1.0*ATR14 ve 09:00-13:00 geri cekilme
                      hareketin %50'sini gecmediyse 13:00 UTC'de Londra yonunde giris (gunde 1);
                      SL 1.5*ATR, TP 2R.
                      Neden ozgun: bu depoda ilk kez iki seans arasinda (Londra -> New York acilisi)
                      yon devri / seans-ici momentum surekliligi denendi; depodaki seans mantigi
                      yalniz tek seansin kendi araliginin kirilimiydi (fx_londra_aralik, ORB).
  fx_pdh_pdl_supurme  Onceki gun yuksek/dusugunun (PDH/PDL) >= 0.1*ATR ustune/altina fitil atip
                      geri kapanis -> ters yon (PDH sup. SELL, PDL sup. BUY); 07-20 UTC;
                      SL = fitil ucu + 0.3*ATR (degisken SL), TP 1.5R.
                      Neden ozgun: bu depoda ilk kez onceki gunun seviyesinin stop-avi / sahte
                      kirilim (fitil-reddi) olarak ele alindi; onceki gun seviyesi hic kullanilmadi,
                      yalniz kirilim-takibi (Donchian, Londra araligi) ve gosterge donusleri vardi.
  fx_para_gucu        21 pariteden her para biriminin son 24 barlik ort. log-getirisi (parite
                      yonune gore isaretli) -> guc siralamasi; taban en guclu 2, karsi en zayif 2
                      arasindaysa ve kendi 3 bar getirisi ayni yondeyse BUY (ayna SELL); SL 2.0*ATR,
                      TP 1.5R; 07-20 UTC; saat kovasi basina 1 giris.
                      Neden ozgun: bu depoda ilk kez cok-parite (capraz piyasa) verisiyle tek
                      paritenin disindan para birimi gucu hesaplandi; tum stratejiler yalniz
                      islem paritesinin kendi barlarina bakiyordu.
  fx_doji_kumesi      Art arda >= 3 bar govde <= 0.3*aralik (kume), sonraki bar govde >= 0.6*aralik
                      ve kapanis kume yuksek/dusugunun disinda -> yon; SL = kume karsi ucu (en az
                      1.0*ATR, degisken SL), TP 2R; 07-20 UTC.
                      Neden ozgun: bu depoda ilk kez mum-ici govde/aralik orani (karar kararsizligi
                      kumesinin cozulmesi) kullanildi; daralma yalniz NR7/BB-genisligi gibi
                      aralik-buyuklugu olcusuyle aranmisti.
  fx_adr_tukenis      Gunun gerceklesen araligi >= 1.2*ADR(14) (onceki 14 kapanmis gunun ort.
                      araligi) ve kapanis gun ucunun 0.2*ATR icinde, bar ters renkli -> ucun
                      tersine giris; hedef gun orta noktasi, SL ucun 0.3*ATR otesi (degisken SL,
                      tp_r=1.0; ayrinti asagida); 07-20 UTC; gunde yon basina 1.
                      Neden ozgun: bu depoda ilk kez gunluk ortalama aralik (ADR) tukenmesi /
                      gun-ici asiri uzama bir giris kosulu oldu; gunluk veri yalniz trend filtresi
                      (gunluk EMA) olarak kullanilmisti.

Notlar
- `side(s, b, i)` yalniz i ve oncesi barlari okur; tum durumlar ileri tek gecisle (bar <= i)
  uretilir, uzun seride yeniden hesap ayni karari verir (testlerle kanitli).
- Motor sinyal barinin kapanisindan SONRAKI bar acilisinda girer (i = son kapanmis bar).
- Bar.t = bar ACILIS zamani (unix sn, UTC). "Seans 07-20" = karar barinin acilis saati [7, 20).
- Degisken SL'li stratejilerde (pdh_pdl_supurme, doji_kumesi, adr_tukenis) motorun `atr[i]`
  serisi sinyal barinda etkin SL-mesafesi olarak ezilir ve sl_atr=1.0 kullanilir (fx_aile /
  btc_ozgun ile ayni teknik). Etkin mesafe sinyal barinin KAPANISINDAN hesaplanir.
- Gun sinirlari UTC. "Kapanmis gun" = kendinden sonraki bir UTC gunune ait bar goruldukten sonra
  bitmis gun; barlarin en az %50'si (86400/tf'in yarisi) mevcut olmayan eksik gunler (Pazar
  21-24 UTC mini-gunu, veri bosluklari) PDH/PDL ve ADR'ye girmez (Pazartesi'nin onceki gunu
  Cuma'dir).

Ek tasarim kararlari (brief belirsizliklerinde, sabit):
- seans_devri: Londra hareketi = 07:00 acilisli ilk barin acilisi -> 09:00'da kapanan son barin
  kapanisi; ATR = o son barin ATR14'u. Geri cekilme = Londra bitis kapanisi ile 09:00-13:00
  penceresi karsi ucu (yukari harekette pencere dibi, asagida tepesi) arasi mesafe. Sinyal, 13:00'da
  kapanan SON barda (karar o ana kadar bilinen veriyle verilir) uretilir; motor bir sonraki bar
  acilisinda, yani 13:00 UTC'nin ilk barinda girer. Londra ve 09-13 pencereleri eksiksiz
  (tum barlar mevcut) degilse o gun sinyal yok.
- pdh_pdl_supurme: ayni barin hem PDH hem PDL supurmesi belirsiz -> sinyal yok. Gunde sinyal
  sayisi sinirlanmaz (brief sinirlamiyor).
- para_gucu: islem paritesi, `series` yalniz bar listesini aldigindan, onbellek paritelerinden
  (t, kapanis) esleserek tanimlanir (eslesme yoksa/belirsizse ValueError). Guc = para biriminin
  (en az 4 paritesi gecerliyse) pariteler uzerindeki ort. 24-bar log-getirisi (taban +, karsi -);
  bir paritenin son bari karar barindan en fazla 1 bar (tf) eski olabilir, 24 barlik pencerenin
  zaman acigi <= 26*tf olmali (hafta sonu bosluguna yayilan pencere gecersiz); 7 para biriminin
  hepsi gecerli degilse sinyal yok. Kendi 3 bar getirisi: ln(c[i]/c[i-3]), zaman acigi <= 5*tf.
  Hizalama: yalniz t_diger <= b[i].t barlari. Yukleme `_FX21_LOADER(tf_adi)` (testte enjekte
  edilebilir). Kova = UTC saat; kova basina 1 giris (yon fark etmez).
- doji_kumesi: kume = i-1'de biten kesintisiz doji dizisi (uzunluk >= 3, ust sinir yok);
  kirilim barinin yonu (kapanis > acilis / < acilis) kirilim yonuyle ayni olmali.
  SL mesafesi = max(kapanis - kume dibi (SELL: kume tepesi - kapanis), 1.0*ATR14).
- adr_tukenis: gunun araligi o barin (i) dahil gun ici yuksek/dusuk farki. ADR icin 14 kapanmis
  gun gerekir. SAPMA (brief'e gore, gerekce asagida): "gun ucu" = gunun (i dahil) en yuksek/en
  dusuk KAPANISI. Gun yuksek/dusugu (fitil dahil) ile "kapanis ucun 0.2*ATR icinde + ters renkli
  bar" birlikte fiilen hic olusmuyor (gercek veride 8 pariteyi M15'te tarayinca 1 sinyal): yesil
  bir bar gun dibinin 0.2*ATR icinde kapanirsa tum govdesi o bantta olmak zorunda. Kapanis-ucu
  okumasi ile ~parite basina 10 sinyal/tf cikar (yine de az). "Ters renkli": gun dibi kapanisina
  yakin -> yesil bar (kapanis > acilis) -> BUY; gun tepesi kapanisina yakin -> kirmizi bar -> SELL.
  TP/SL: `tp_r` sabit 1.0; SL0 = (kapanis ile gunun yuksek/dusugu arasi) + 0.3*ATR; hedef mesafe =
  |kapanis - gun orta noktasi| ve bu mesafe [0.8*SL0, 2.5*SL0] araligina KIRPILIR; etkin mesafe
  (atr[i]) bu kirpilmis deger olur, yani SL = TP = kirpilmis mesafe (1R). Orta nokta mesafesi
  tipik olarak SL0'in cok ustunde oldugundan pratikte hedef = SL = 2.5*SL0 olur: stop, "uc +
  0.3*ATR"den daha genistir (belirgin sapma; bir degisken-TP motorda olmadigi icin).
"""
from __future__ import annotations

import bisect
import json
import math
import os
import sys

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import xau_week_double_8w as wk  # noqa: E402

_ROOT = os.path.dirname(_SCRIPTS)

PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF", "GBPJPY", "EURJPY", "NZDUSD")
SPREAD_MIN_MULT = 8.0
SESSION_START_H = 7
SESSION_END_H = 20


# ------------------------------------------------------------------ yardimcilar
def _tf_sec(bars: list) -> int:
    diffs = sorted(int(bars[k + 1].t - bars[k].t) for k in range(min(len(bars) - 1, 400)))
    return diffs[len(diffs) // 2] if diffs else 900


def _ok(*vals) -> bool:
    return all(v is not None for v in vals)


def _in_session(bar) -> bool:
    return SESSION_START_H <= int(bar.t % 86400) // 3600 < SESSION_END_H


def _day_stats(b: list, tf: int):
    """Bar basina (yalniz i ve oncesini kullanarak):
    pdh, pdl  : son KAPANMIS (yeterince dolu) gunun yuksek/dusugu
    adr       : son 14 kapanmis dolu gunun ort. (yuksek-dusuk) araligi (14 gun yoksa None)
    dhi, dlo  : i'nin gununun, i DAHIL, o ana kadarki yuksek/dusugu"""
    n = len(b)
    full = 0.5 * 86400 / tf
    pdh: list = [None] * n
    pdl: list = [None] * n
    adr: list = [None] * n
    dhi: list = [None] * n
    dlo: list = [None] * n
    days: list = []  # kapanmis dolu gunler: (yuksek, dusuk)
    key = None
    hi = lo = 0.0
    cnt = 0
    for i in range(n):
        k = int(b[i].t) // 86400
        if k != key:
            if key is not None and cnt >= full:
                days.append((hi, lo))
            key, hi, lo, cnt = k, b[i].high, b[i].low, 0
        else:
            hi, lo = max(hi, b[i].high), min(lo, b[i].low)
        cnt += 1
        dhi[i], dlo[i] = hi, lo
        if days:
            pdh[i], pdl[i] = days[-1]
            if len(days) >= 14:
                adr[i] = sum(h - l for h, l in days[-14:]) / 14.0
    return pdh, pdl, adr, dhi, dlo


# ------------------------------------------------------------------ 1) seans devri
LON_START_MIN = 7 * 60
LON_END_MIN = 9 * 60
PULL_END_MIN = 13 * 60
LON_ATR = 1.0
PULL_MAX = 0.5


def _devri_series(b, closes):
    n = len(b)
    tf = _tf_sec(b)
    tfm = tf // 60
    lon_need = (LON_END_MIN - LON_START_MIN) // tfm
    pull_need = (PULL_END_MIN - LON_END_MIN) // tfm
    atr14 = wk.atr(b, 14)
    sig = [0] * n
    day = None
    lon_open = lon_end = lon_atr = None
    lon_cnt = pull_cnt = 0
    lon_first_ok = False
    lon_last_m = None
    plo = phi = None
    for i in range(n):
        d = int(b[i].t) // 86400
        if d != day:
            day = d
            lon_open = lon_end = lon_atr = None
            lon_cnt = pull_cnt = 0
            lon_first_ok = False
            lon_last_m = None
            plo = phi = None
        m_open = (int(b[i].t) % 86400) // 60
        m_close = m_open + tfm
        if LON_START_MIN <= m_open and m_close <= LON_END_MIN:
            if lon_cnt == 0:
                lon_open = b[i].open
                lon_first_ok = (m_open == LON_START_MIN)
            lon_end, lon_atr, lon_last_m = b[i].close, atr14[i], m_close
            lon_cnt += 1
        elif LON_END_MIN <= m_open and m_close <= PULL_END_MIN:
            plo = b[i].low if plo is None else min(plo, b[i].low)
            phi = b[i].high if phi is None else max(phi, b[i].high)
            pull_cnt += 1
            if m_close != PULL_END_MIN:
                continue
            if not (lon_first_ok and lon_cnt == lon_need and lon_last_m == LON_END_MIN
                    and pull_cnt == pull_need and lon_atr is not None and lon_atr > 0):
                continue
            move = lon_end - lon_open
            if abs(move) < LON_ATR * lon_atr:
                continue
            if move > 0 and (lon_end - plo) <= PULL_MAX * move:
                sig[i] = 1
            elif move < 0 and (phi - lon_end) <= PULL_MAX * (-move):
                sig[i] = -1
    return {"sig": sig}


def _devri_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 2) PDH/PDL supurme
SUP_FITIL = 0.1
SUP_SL = 0.3


def _pdh_series(b, closes):
    n = len(b)
    tf = _tf_sec(b)
    atr14 = wk.atr(b, 14)
    atr_eff = list(atr14)
    pdh, pdl, _adr, _dhi, _dlo = _day_stats(b, tf)
    sig = [0] * n
    for i in range(n):
        a = atr14[i]
        if a is None or a <= 0 or pdh[i] is None or not _in_session(b[i]):
            continue
        c = b[i].close
        sell = (b[i].high - pdh[i]) >= SUP_FITIL * a and c < pdh[i]
        buy = (pdl[i] - b[i].low) >= SUP_FITIL * a and c > pdl[i]
        if buy == sell:  # ikisi birden (belirsiz) ya da hicbiri
            continue
        if sell:
            sig[i] = -1
            atr_eff[i] = (b[i].high - c) + SUP_SL * a
        else:
            sig[i] = 1
            atr_eff[i] = (c - b[i].low) + SUP_SL * a
    return {"sig": sig, "atr": atr_eff}


def _pdh_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 3) para birimi gucu
STR_N = 24
STR_OWN_N = 3
STR_MIN_PAIRS = 4
_TF_NAME = {900: "m15", 1800: "m30"}
_FX21_CACHE: dict = {}


def _default_fx21_loader(tf_name: str) -> dict:
    """outputs/replay_cache_fx21_<tf>.json -> {PARITE: [[ts,o,h,l,c],...]}."""
    if tf_name not in _FX21_CACHE:
        path = os.path.join(_ROOT, "outputs", f"replay_cache_fx21_{tf_name}.json")
        with open(path, encoding="utf-8") as fh:
            _FX21_CACHE[tf_name] = json.load(fh)
    return _FX21_CACHE[tf_name]


_FX21_LOADER = _default_fx21_loader  # testlerde sentetik veriyle degistirilir


def _identify_pair(b: list, data: dict) -> str:
    """b'nin hangi onbellek paritesi oldugunu (t, kapanis) eslesmesiyle bulur."""
    n = len(b)
    idx = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1, max(0, n - 2), min(n - 1, 7)})
    found = []
    for p, rows in data.items():
        d = {int(r[0]): float(r[4]) for r in rows}
        if all(int(b[k].t) in d and abs(d[int(b[k].t)] - b[k].close) <= 1e-9 * max(1.0, abs(b[k].close))
               for k in idx):
            found.append(p)
    if len(found) != 1:
        raise ValueError(f"fx_para_gucu: islem paritesi onbellekten tanimlanamadi (eslesen: {found})")
    return found[0]


def _para_series(b, closes):
    n = len(b)
    tf = _tf_sec(b)
    tf_name = _TF_NAME.get(tf)
    if tf_name is None:
        raise ValueError(f"fx_para_gucu: desteklenmeyen bar araligi {tf} sn (900 / 1800)")
    data = _FX21_LOADER(tf_name)
    own = _identify_pair(b, data)
    own_base, own_quote = own[:3], own[3:]
    pr: dict = {}  # parite -> (zamanlar, 24 barlik log-getiri)
    for p, rows in data.items():
        rows = sorted(rows, key=lambda r: r[0])
        pt = [int(r[0]) for r in rows]
        pc = [float(r[4]) for r in rows]
        r24: list = [None] * len(pt)
        for k in range(STR_N, len(pt)):
            if pt[k] - pt[k - STR_N] <= (STR_N + 2) * tf and pc[k] > 0 and pc[k - STR_N] > 0:
                r24[k] = math.log(pc[k] / pc[k - STR_N])
        pr[p] = (pt, r24)
    curs = {p[k:k + 3] for p in pr for k in (0, 3)}
    sig = [0] * n
    last_bucket = None
    for i in range(STR_OWN_N, n):
        if not _in_session(b[i]):
            continue
        t = int(b[i].t)
        bucket = t // 3600
        if bucket == last_bucket:
            continue
        if t - int(b[i - STR_OWN_N].t) > (STR_OWN_N + 2) * tf or b[i].close <= 0 or b[i - STR_OWN_N].close <= 0:
            continue
        r3 = math.log(b[i].close / b[i - STR_OWN_N].close)
        if r3 == 0:
            continue
        sums: dict = {}
        cnts: dict = {}
        for p, (pt, r24) in pr.items():
            j = bisect.bisect_right(pt, t) - 1  # yalniz t_diger <= t
            if j < 0 or t - pt[j] > tf or r24[j] is None:
                continue
            for cur, sgn in ((p[:3], 1.0), (p[3:], -1.0)):
                sums[cur] = sums.get(cur, 0.0) + sgn * r24[j]
                cnts[cur] = cnts.get(cur, 0) + 1
        if any(cnts.get(c, 0) < STR_MIN_PAIRS for c in curs):
            continue
        rank = sorted(curs, key=lambda c: (sums[c] / cnts[c], c), reverse=True)  # guclu -> zayif
        top2, bot2 = set(rank[:2]), set(rank[-2:])
        if r3 > 0 and own_base in top2 and own_quote in bot2:
            sig[i] = 1
        elif r3 < 0 and own_base in bot2 and own_quote in top2:
            sig[i] = -1
        if sig[i]:
            last_bucket = bucket
    return {"sig": sig}


def _para_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 4) doji kumesi
DOJI_BODY = 0.3
DOJI_MIN = 3
BREAK_BODY = 0.6
DOJI_SL_MIN_ATR = 1.0


def _doji_series(b, closes):
    n = len(b)
    atr14 = wk.atr(b, 14)
    atr_eff = list(atr14)
    sig = [0] * n
    run = 0
    chi = clo = 0.0
    for i in range(n):
        x = b[i]
        rng = x.high - x.low
        a = atr14[i]
        if run >= DOJI_MIN and rng > 0 and a is not None and a > 0 and _in_session(x):
            body = abs(x.close - x.open)
            if body >= BREAK_BODY * rng:
                if x.close > chi and x.close > x.open:
                    sig[i] = 1
                    atr_eff[i] = max(x.close - clo, DOJI_SL_MIN_ATR * a)
                elif x.close < clo and x.close < x.open:
                    sig[i] = -1
                    atr_eff[i] = max(chi - x.close, DOJI_SL_MIN_ATR * a)
        # kume durumunu i dahil guncelle (i+1 icin)
        if rng > 0 and abs(x.close - x.open) <= DOJI_BODY * rng:
            if run == 0:
                chi, clo = x.high, x.low
            else:
                chi, clo = max(chi, x.high), min(clo, x.low)
            run += 1
        else:
            run = 0
    return {"sig": sig, "atr": atr_eff}


def _doji_side(s, b, i):
    return s["sig"][i]


# ------------------------------------------------------------------ 5) ADR tukenisi
ADR_MULT = 1.2
ADR_EDGE_ATR = 0.2
ADR_SL = 0.3
ADR_RATIO_MIN = 0.8
ADR_RATIO_MAX = 2.5


def _adr_series(b, closes):
    n = len(b)
    tf = _tf_sec(b)
    atr14 = wk.atr(b, 14)
    atr_eff = list(atr14)
    _pdh, _pdl, adr, dhi, dlo = _day_stats(b, tf)
    sig = [0] * n
    day = None
    mxc = mnc = 0.0  # gunun (i dahil) en yuksek / en dusuk KAPANISI
    fired = {1: False, -1: False}
    for i in range(n):
        d = int(b[i].t) // 86400
        c, o = b[i].close, b[i].open
        if d != day:
            day, mxc, mnc = d, c, c
            fired = {1: False, -1: False}
        else:
            mxc, mnc = max(mxc, c), min(mnc, c)
        a, ad = atr14[i], adr[i]
        if a is None or a <= 0 or ad is None or ad <= 0 or not _in_session(b[i]):
            continue
        hi, lo = dhi[i], dlo[i]
        if hi - lo < ADR_MULT * ad:
            continue
        near_lo = (c - mnc) <= ADR_EDGE_ATR * a and c > o  # gun dibi kapanisina yakin + yesil bar
        near_hi = (mxc - c) <= ADR_EDGE_ATR * a and c < o  # gun tepesi kapanisina yakin + kirmizi bar
        if near_lo == near_hi:  # ikisi birden (olanaksiz) ya da hicbiri
            continue
        if near_lo:
            side, sl0 = 1, (c - lo) + ADR_SL * a
        else:
            side, sl0 = -1, (hi - c) + ADR_SL * a
        if fired[side] or sl0 <= 0:
            continue
        mid_dist = abs(c - (hi + lo) / 2.0)
        dist = min(max(mid_dist, ADR_RATIO_MIN * sl0), ADR_RATIO_MAX * sl0)
        fired[side] = True
        sig[i] = side
        atr_eff[i] = dist
    return {"sig": sig, "atr": atr_eff}


def _adr_side(s, b, i):
    return s["sig"][i]


STRATEGIES = {
    "fx_seans_devri": {"series": _devri_series, "side": _devri_side, "sl_atr": 1.5, "tp_r": 2.0,
                       "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
    "fx_pdh_pdl_supurme": {"series": _pdh_series, "side": _pdh_side, "sl_atr": 1.0, "tp_r": 1.5,
                           "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
    "fx_para_gucu": {"series": _para_series, "side": _para_side, "sl_atr": 2.0, "tp_r": 1.5,
                     "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
    "fx_doji_kumesi": {"series": _doji_series, "side": _doji_side, "sl_atr": 1.0, "tp_r": 2.0,
                       "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
    "fx_adr_tukenis": {"series": _adr_series, "side": _adr_side, "sl_atr": 1.0, "tp_r": 1.0,
                       "symbols": set(PAIRS), "spread_min_mult": SPREAD_MIN_MULT},
}
