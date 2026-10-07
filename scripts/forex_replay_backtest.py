#!/usr/bin/env python3
"""Forex Otonom Scalper — 7 Günlük Walk-Forward Replay (Eski vs Yeni A/B).

Aynı Yahoo Finance 5M mum serisi üzerinde iki varyantı bar-bar simüle eder:

  OLD  — CMO/CCI'siz skor, sabit spec TP/SL, DXY/korelasyon/saat filtresi yok
  NEW  — CMO+CCI+üçlü teyit, ATR çıkış motoru + kısmi kâr, DXY rejim vetosu,
         FX korelasyon kalkanı, zayıf saat kalkanı

Ek olarak NEW varyantında yeni kapılardan (DXY / SAAT / KORELASYON) bloklanan
her aday giriş için "gölge defter" tutulur: filtre ne reddettiğini ölçer
(kapı bazında varsayımsal PnL — negatifse filtre doğru karar vermiş demektir).

Kullanım:
    python scripts/forex_replay_backtest.py --days 7
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app.routers import forex  # noqa: E402
from backend.app.forex_correlation import FXCorrelationMonitor  # noqa: E402

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
INDICATOR_WINDOW = 260      # bar — canlı motor ~576 bar (2d) kullanır; hız için kırpıldı
CORR_REFRESH_EVERY = 36     # bar (≈ 3 saat)
MAX_OPEN_POSITIONS = 6
MAX_PER_SYMBOL_DIR = 3
PYRAMID_MIN_PROFIT_USD = 0.20
RISK_PCT = 1.0
BALANCE = 10000.0
TRADES_PER_BAR_CAP = 3
SHADOW_MAX_CONCURRENT = 60
BASE_BE_PIPS = 14.0         # canlı ayar varsayılanları (Motorla aynı)
BASE_TRAIL_PIPS = 20.0
BLOCKED_HOURS: List[int] = []
CATEGORY_SPREAD_PIPS = {"major": 1.2, "commodity": 2.5, "crypto": 12.0, "index": 3.0, "cross": 2.0}
# Gerçek spread profili (--spread-profile ile yüklenir): {SYMBOL: avg_pips}; boşsa kategori spread'i kullanılır
SPREAD_PROFILE: Dict[str, float] = {}
# Replay-local sembol tanımları: canlı FOREX_SYMBOLS'ta olmayan test adayları (JPY kross'ları)
REPLAY_SYMBOL_DEFS = {
    "GBPJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
    "EURJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
    "AUDJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
    # 2026-10-07 kapsam-genişletme testi: likit krosçar (kullanıcı: "daha fazla forex çifti")
    "CADJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
    "CHFJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
    "NZDJPY": {"pip_size": 0.01, "digits": 3, "category": "cross"},
    "EURGBP": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "EURCHF": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "EURAUD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "EURCAD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "EURNZD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "GBPCHF": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "GBPAUD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "GBPCAD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "GBPNZD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "AUDNZD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "AUDCAD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "AUDCHF": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "NZDCAD": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "NZDCHF": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
    "CADCHF": {"pip_size": 0.0001, "digits": 5, "category": "cross"},
}

# Krosçarların Yahoo sembolleri (fetch_all ek olarak çeker; canlı YAHOO_SYMBOL_MAP'e dokunmaz)
REPLAY_EXTRA_YF = {sym: f"{sym}=X" for sym in REPLAY_SYMBOL_DEFS}

# pip_val override'ı: spec fonksiyonu JPY'siz krosçarlar için sabit 10.0 kullanır; gerçek
# değer = 10 × quote-para-biriminin USD değeri (EURGBP: 10×GBPUSD, JPY kross: 1000/USDJPY).
# main() veriyi yükledikten sonra pencere ortalamalarıyla doldurulur ve spec sarılır.
REPLAY_PIP_VAL_OVERRIDE: Dict[str, float] = {}
# Gölge defter tutulan kapılar (yeni özellikler)
SHADOW_GATES = ("DXY", "SAAT", "KORELASYON", "ADX", "SUPERTREND", "EV",
                "SEANS", "VOLATİLİTE", "UZAMA", "REJIM", "VWAP", "ISEANS", "ACILIS",
                "HTF", "IRAD", "YAS", "SERI")


def loss_streak_on_close(streak: int, reason: str, pnl_usd: float, limit: int) -> Tuple[int, bool]:
    """Seri-SL sigortası sayacı (saf fonksiyon — replay ve canlı motor aynı kuralı kullanır).

    Kurallar:
      - Net kazançla kapanış seriyi sıfırlar (BE/trailing kazançları da seriyi bozar).
      - Tam-SL kaybı (`SL_HIT`/`SL` + pnl < 0) seriyi 1 artırır; BE/trailing çıkışları
        pnl < 0 üretemez (SL hep giriş+$1 üstünde kilitlenir) — sayılmaz.
      - Sayı `limit`e ulaşınca (0, True) döner: soğuma tetiklenir, sayaç sıfırdan başlar.
      - limit <= 0 → kapalı; pnl==0 veya diğer nedenler sayacı değiştirmez.
    """
    if pnl_usd > 0:
        return 0, False
    if limit <= 0 or pnl_usd >= 0 or reason not in ("SL_HIT", "SL"):
        return streak, False
    streak += 1
    if streak >= limit:
        return 0, True
    return streak, False

# EV kalkanı (canlı motorla aynı; WR 45 = 2026-10-06 30g replay kararı)
EV_WINDOW_SEC = 24 * 3600
EV_MIN_TRADES = 10
EV_MAX_WIN_RATE = 45.0
EV_LOSS_RISK_MULT = 3.0
EV_GUARD = True

# Ayarlanabilir tuning parametreleri (CLI ile override edilir)
TUN_MIN_SCORE = 70.0
TUN_SL_ATR_MULT = 1.1
TUN_TP_ATR_MULT = 1.4
TUN_RR_FLOOR = 1.5
TUN_HEADROOM_FOREX = 3.5
TUN_ADX_MIN = 0.0           # 0 = ADX kalkanı kapalı
TUN_ST_FILTER = False       # SuperTrend yön teyidi kapalı/kapalı
# 2026-10-06 köprü hizalama simülasyonu: --spec-atr ile spec BE/Trail'i işlem-bazlı giriş ATR'siyle
# hesaplanır (= motorun cmd ile köprüye gönderdiği ATR'li değerler; canlıda artık cmd ile taşınıyor).
# Kapalıyken replay ATR'siz spec kullanır (= köprünün ESKİ davranışı) → A/B bu ayrışmayı ölçer.
TUN_SPEC_ATR = False

# 2026-10-06 varyant mekanikleri (30 günlük replay A/B ile test ediliyor)
FX_MAJORS = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"}
TUN_FX_MIN_SCORE = 0.0      # 0 = majörler için ayrı eşik yok (min_score geçerli)
TUN_GOLD_DXY_SOFT = False   # (Tarihi) XAUUSD DXY yumuşatma — canlı artık tam muaf
TUN_GOLD_DXY_BUMP = 5.0

# 2026-10-06 NAS100/US30 özel mekanizmalar (web araştırması: seans likiditesi + Zarattini-Aziz açılış sürüşü)
INDEX_GATED = {"NAS100", "US30", "USTEC", "DJ30", "US100"}
TUN_INDEX_HOURS = None        # (başlangıç_dk, bitiş_dk) UTC dakika aralığı — endeks girişleri yalnız bu pencerede (None = kapalı)
TUN_INDEX_OPEN_DRIVE = False  # ABD açılışının ilk 5m mumu yönü 13:35-15:00 arası yön teyidi olarak zorunlu (Zarattini-Aziz 2023)

TUN_CHANDLIER = 0.0         # >0: trailing = MFE − chandelier×ATR(giriş) (0 = sabit pip trail)
TUN_MAJOR_HOURS = None      # (başlangıç, biti) UTC saat aralığı — majörler yalnız bu pencerede (None = kapalı)
TUN_MAJOR_MIN_ATR = 0.0     # majörler minimum ATR(pips) — ölü piyasa filtresi (0 = kapalı)
TUN_MAJOR_MAX_EXT = 0.0     # majörlerde fiyatın EMA21'den maks. ATR-katı uzaması — kovalamama (0 = kapalı)
GATED_EXTRAS: set = set()   # --gate-extras: majör kapılarına (seans+minATR) tabi tutulacak ek adaylar

# 2026-10-06 altın/BTC geliştirme testleri
TUN_GOLD_SESSION = False    # altın için de seans penceresi (majör kapısıyla aynı 7-20 UTC)
TUN_BTC_EMA200 = False      # BTC girişlerine EMA200(1h) yapısal rejim kapısı (BUY>EMA, SELL<EMA)
TUN_BTC_VWAP = False        # BTC girişlerine günlük VWAP kapısı (BUY>VWAP, SELL<VWAP; hacim gerektirir)
TUN_CRYPTO_SL_MULT = 0.0    # kripto kategorisi özel SL ATR çarpanı (0 = global sl_mult)
TUN_BTC_MIN_SCORE = 0.0     # BTC özel skor eşiği (0 = global min_score)

# 2026-10-06 "kazananı koştur" testi (kullanıcı sorusu: trailing devreye girince sabit TP kalksa?)
TUN_TP_MODE = "tp"          # "tp" | "no_tp_on_trail" (trailing aktiflenince TP çekilir) | "no_tp" (TP hiç yok)

# 2026-10-06 altın volatilite-adaptif BE/trailing (kullanıcı isteği: BE/SL/TP/trail her işlemde
# o işlemin giriş ATR'ine göre ölçeklensin). SL/TP zaten ATR çıkış motorunda; burada BE tetiği
# (min_be_pips tabanı) ve trailing mesafesi giriş ATR'ine bağlanır (XAUUSD'ye özel).
TUN_GOLD_VOL_EXITS = False
TUN_VOL_BE_MULT = 0.8       # BE tetik tabanı: be_mult × giriş-ATR (pip) — $1 dolar kuralı yine alt sınır
TUN_VOL_TRAIL_MULT = 1.5    # trailing mesafesi: trail_mult × giriş-ATR (pip)
TUN_VOL_TRAIL_FLOOR = 40.0  # trail alt sınırı (pip) — 15 gibi düşük değer oransal-sıkı modu açar

# 2026-10-06 dolar-kuralı BE kilidi düzeltme testleri (XAUUSD'ye özel):
TUN_BE_USD_GOLD = 1.0       # BE dolar tabanı — garantili kilit hedefi ($)
TUN_BE_RATIO_GOLD = 0.60    # altın BE anında kilitlenen kâr oranı (2026-10-06 canlı kararı: 0.40→0.60)
TUN_BE_PIP_FIXED_GOLD = 0.0 # >0: BE tetiği+tabanı lot-bağımsız sabit pip (örn. 10) — hacimden arındırma

# 2026-10-07 erken trend-dönüş/düzeltme çıkışı (kullanıcı: "trend dönüşlerini daha erken algıla,
# cooldown değil"): pozisyon açıkken sembolün kendi 5M göstergesi pozisyona karşı dönünce SL'i
# beklemeden kapat. Canlıda opposite-skor flip'i (min_score 76-78) çok geç tetikleniyor; buradaki
# amaç skorun karşı eşiğe ulaşmasını beklemeden momentum kırılmasında çıkmak.
TUN_ST_FLIP_EXIT = False    # SuperTrend(5M) yönü pozisyona karşı dönünce bar kapanışında kapat
TUN_ST_FLIP_MIN_PNL = 0.0   # >0: MOMFLIP yalnız pnl(pip) >= eşikken (kâr koruma; 0 = zararda da erken kes)
TUN_EMA_FLIP_EXIT = False   # EMA9/EMA21 çaprazı pozisyona karşı + kapanış EMA21 ötesinde → kapat
ST_EXIT_PERIOD = 10         # çıkış SuperTrend'i parametreleri (canlı sinyal ST ile aynı 10/3.0)
ST_EXIT_MULT = 3.0
TUN_EXT_GATE_XG = False     # XAU/BTC pyramid girişlerinde de EMA21 uzama kapısı (kovalamayı engelle)
TUN_ST_FLIP_TIGHTEN = 0.0   # >0: ST flip'te kapatmak yerine trailing'i bu pip'e sıkılaştır (kâr > 0 iken)

# 2026-10-07 "trend bitti" dedektörleri (giriş tarafı — kullanıcı: "trendin sona erdiğini erken
# algılayabilir miyiz?"). Çıkış tarafı chandelier ile çözüldü; buradaki hedef ölü trende YENİ
# giriş açılmasını önlemek (kayıp kümeleri tepedeki piramit yığılmalarından geliyordu).
TUN_HTF_ALIGN = False       # 15M SuperTrend yönüyle ters giriş yok (5M sıçraması HTF karşıysa = sayaç-trend giriş)
TUN_DIV_GATE = 0.0          # >0: RSI(14) uyumsuzluk eşiği — fiyat yeni zirve/dip, RSI teyit etmiyorsa giriş yok
TUN_PYR_AGE_MAX = 0         # >0: 5M SuperTrend yaşı bu barı aşınca AYNI yönde piramit (2./3. pozisyon) yok; ilk giriş serbest

# 2026-10-07 seri-SL soğuması (kullanıcı önerisi: "arka arkaya 3 SL ile kapanan işlem zararla
# kapandıysa 5 dk cooldown yapsın, sonra yeniden değerlendirsin — normal cooldown'dan hariç"):
# sembol ardışık tam-SL kayıplarını görünce kısa süreliğine YENİ giriş almaz (açık pozisyon
# yönetimi sürer; süre bitince normal değerlendirme). Kazançla kapanış seriyi sıfırlar.
TUN_LOSS_STREAK = 0         # 0 = kapalı; N = N ardışık tam-SL kaybında tetikle
TUN_LOSS_STREAK_CD = 300.0  # tetiklenince sembolün yeni giriş penceresi (saniye)

# 2026-10-07 giriş-kalibrasyonu projesi: alternatif giriş algoritmaları (--entry-mode).
# Mod kendi tetik şartını üretir; kapılar (EV/spread/korelasyon/seans) ve çıkış motoru
# klasikle BİREBİR aynıdır — adil karşılaştırma. OLD defteri hep klasik kalır (referans).
TUN_ENTRY_MODE = "classic"      # classic | london_breakout | pullback | donchian_adx
TUN_LB_BOX_END_H = 7            # Asya kutusu: 00:00 → 07:00 UTC
TUN_LB_ENTRY_END_H = 11         # tetik penceresi: 07:00 → 11:00 UTC
TUN_LB_SL_BOX_FRAC = 0.5        # SL = kutu yüksekliği × bu oran
TUN_LB_TP_R = 1.5               # TP = SL × bu R katı
TUN_LB_MIN_BOX_ATR = 0.0        # kutu yüksekliği < bu×ATR ise gün skip (0 = kapalı)
LB_STATE: Dict[Tuple[str, int, str], bool] = {}  # (sembol, gün, yön) → bugün tetiklendi
# pullback modu (araştırma ADAY 1): HTF trend + ADX rejim + EMA21'e geri çekilme + dönüş mumu
TUN_PB_ADX_MIN = 20.0
TUN_PB_TOUCH_ATR = 0.25
TUN_PB_MAX_PER_DAY = 2
# donchian_adx modu (araştırma ADAY 3+4 hibrit): Donchian-mid çaprazı + ADX + 2×ATR SL / 4×ATR TP
TUN_DA_ADX_MIN = 18.0
TUN_DA_DONCH = 20
TUN_DA_SL_ATR = 2.0
TUN_DA_TP_ATR = 4.0
# 2026-10-08 derinleştirilmiş web-araştırması modları (bkz. docs/ FX strategi araştırması):
#   donchian_pure — saf kanal kırılımı (en yüksek high/low, kapanış bazlı) + ADX; TP=trailing'e bırakılır
#   squeeze       — Bollinger bandwidth sıkışması + band dışı kapanış kırılımı
#   nr7           — Crabel NR7: son N barın en dar aralığı kırılımı
#   orb_ny        — London kutusu (07→13 UTC) → NY overlap (13→16 UTC) seans açılış-kırılımı + OR/ATR filtresi
# Ortak yeni-mod parametreleri: SL × ATR; mode_tp_atr > 0 ise sabit TP, 0 ise TP kapalı (chandelier trailing çıkar)
TUN_MODE_SL_ATR = 2.0
TUN_MODE_TP_ATR = 0.0           # 0 = sabit TP yok → --chandelier ile trail-öncelikli çıkış
TUN_SQUEEZE_BB_PCT = 20.0       # bandwidth bu persentilin altındaysa "sıkışma" sayılır
TUN_SQUEEZE_BB_PERIOD = 20
TUN_NR7_N = 7                   # NR7: son 7 barın en dar aralığı
TUN_NR7_ADX_MIN = 18.0
TUN_ORB_BOX_START_H = 7         # London kutusu başlangıç saati (UTC)
TUN_ORB_BOX_END_H = 13          # London kutusu bitiş saati (UTC)
TUN_ORB_ENTRY_START_H = 13      # tetik penceresi başlangıç (UTC)
TUN_ORB_ENTRY_END_H = 16        # tetik penceresi bitiş (UTC)
TUN_ORB_MIN_ATR = 0.0           # kutu yüksekliği / ATR alt sınırı (0 = kapalı)
TUN_ORB_MAX_ATR = 0.0           # kutu yüksekliği / ATR üst sınırı (0 = kapalı)
TUN_ORB_SL_FRAC = 0.5           # SL = kutu yüksekliği × bu oran
TUN_ORB_TP_R = 1.5              # TP = SL × bu R katı
TUN_MODE_FLAT16 = False         # 16:00 UTC'de FX pozisyonlarını zorla kapat (araştırma ADAY 5)
MODE_DAY_STATE: Dict[Tuple[str, int, str], int] = {}  # (sembol, gün, yön) → gün içi giriş sayısı
MODE_SYMBOLS: set = set()       # boş = mod tüm sembollerde; dolu = yalnız bu sembollerde


def _bb_bandwidth_series(closes: List[float], period: int = 20, mult: float = 2.0) -> List[float]:
    """Bollinger bant genişliği serisi: (upper−lower)/mid. Sıkışma (squeeze) tespiti için.

    i. değer yalnız i ve öncesi kapanışlardan türetilir (look-ahead yok). İlk period-1
    barda tanımsız → 0.0 döner. Kayan toplam/kare-toplam ile O(n) — bar başına yeniden
    hesaplama O(n²) olurdu (squeeze modu 16k barlık seride koşuyu dakikalara çıkarıyordu).
    """
    n = len(closes)
    out = [0.0] * n
    if n < period:
        return out
    s = 0.0
    s2 = 0.0
    for j in range(period):
        s += closes[j]
        s2 += closes[j] * closes[j]
    for i in range(period - 1, n):
        if i >= period:
            s += closes[i] - closes[i - period]
            s2 += closes[i] * closes[i] - closes[i - period] * closes[i - period]
        m = s / period
        if m > 0:
            var = max(0.0, s2 / period - m * m)
            out[i] = (2.0 * mult * (var ** 0.5)) / m
    return out


# Squeeze modu bandwidth serisi önbelleği: sembol → tam seri (her barda yeniden hesaplamayı önler)
_BB_BW_CACHE: Dict[str, List[float]] = {}


def _mode_session_ok(sym: str, hour: int) -> bool:
    """Araştırma ADAY 5 seans penceresi: FX 07:00-16:00 UTC; JPY çiftleri 00:00-16:00."""
    if "JPY" in sym.upper():
        return 0 <= hour < 16
    return 7 <= hour < 16


def _entry_mode_candidate(sym: str, ts: float, bars: List[Tuple], ci: int,
                          tech: Dict[str, Any], pip_size: float) -> Optional[Dict[str, Any]]:
    """Alternatif giriş modu üreticisi (classic dışı modlar). None = aday yok.

    london_breakout: Asya kutusu (00:00→TUN_LB_BOX_END_H UTC) high/low;
    tetik penceresi içinde close kutu dışına taşarsa yönünde tek giriş/gün.
    SL = kutu yüksekliği × frac, TP = SL × R. Kutu-ATR filtresi opsiyonel.
    """
    hour = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).hour

    if TUN_ENTRY_MODE == "london_breakout":
        if hour < TUN_LB_BOX_END_H or hour >= TUN_LB_ENTRY_END_H:
            return None
        day = int(ts // 86400)
        window = bars[max(0, ci - 300):ci]
        box = [b for b in window
               if int(b[0] // 86400) == day and int((b[0] % 86400) // 3600) < TUN_LB_BOX_END_H]
        if len(box) < 10:
            return None
        box_hi = max(b[2] for b in box)
        box_lo = min(b[3] for b in box)
        box_h = box_hi - box_lo
        atr_price = float(tech.get("atr") or 0.0)
        if TUN_LB_MIN_BOX_ATR > 0 and atr_price > 0 and box_h < TUN_LB_MIN_BOX_ATR * atr_price:
            return None
        c = bars[ci - 1][4]
        if c > box_hi:
            action = "BUY"
        elif c < box_lo:
            action = "SELL"
        else:
            return None
        key = (sym, day, action)
        if LB_STATE.get(key):
            return None
        LB_STATE[key] = True
        if box_h <= 0 or pip_size <= 0:
            return None
        sl_pips = (box_h * TUN_LB_SL_BOX_FRAC) / pip_size
        return {"action": action, "exits": {"sl_pips": round(sl_pips, 1), "tp_pips": round(sl_pips * TUN_LB_TP_R, 1)}}

    if TUN_ENTRY_MODE == "pullback":
        if not _mode_session_ok(sym, hour):
            return None
        adx = float(tech.get("adx") or 0.0)
        if adx < TUN_PB_ADX_MIN:
            return None
        htf = str(tech.get("htf_trend") or "")
        atr_price = float(tech.get("atr") or 0.0)
        ema21 = float(tech.get("ema21") or 0.0)
        if atr_price <= 0 or ema21 <= 0:
            return None
        c = bars[ci - 1][4]
        o = bars[ci - 1][1]
        lo8 = min(b[3] for b in bars[max(0, ci - 8):ci])
        hi8 = max(b[2] for b in bars[max(0, ci - 8):ci])
        touch = abs(c - ema21) <= TUN_PB_TOUCH_ATR * atr_price
        if not touch:
            return None
        day = int(ts // 86400)
        if htf == "BULLISH" and c > ema21 and c >= o:
            action = "BUY"
        elif htf == "BEARISH" and c < ema21 and c <= o:
            action = "SELL"
        else:
            return None
        key = (sym, day, action)
        if MODE_DAY_STATE.get(key, 0) >= TUN_PB_MAX_PER_DAY:
            return None
        MODE_DAY_STATE[key] = MODE_DAY_STATE.get(key, 0) + 1
        if action == "BUY":
            sl_pips = ((c - lo8) / pip_size) + 0.3 * atr_price / pip_size
        else:
            sl_pips = ((hi8 - c) / pip_size) + 0.3 * atr_price / pip_size
        sl_pips = max(0.8 * atr_price / pip_size, min(2.5 * atr_price / pip_size, sl_pips))
        return {"action": action, "exits": {"sl_pips": round(sl_pips, 1), "tp_pips": round(2.0 * sl_pips, 1)}}

    if TUN_ENTRY_MODE == "donchian_adx":
        if not _mode_session_ok(sym, hour):
            return None
        adx = float(tech.get("adx") or 0.0)
        if adx < TUN_DA_ADX_MIN:
            return None
        n = TUN_DA_DONCH
        window = bars[max(0, ci - (n + 1)):ci]
        if len(window) < n:
            return None
        hi_n = max(b[2] for b in window[:-1])
        lo_n = min(b[3] for b in window[:-1])
        mid = (hi_n + lo_n) / 2.0
        c = bars[ci - 1][4]
        prev_c = bars[ci - 2][4]
        prev_mid = (max(b[2] for b in window[:-2]) + min(b[3] for b in window[:-2])) / 2.0 if len(window) > 2 else mid
        atr_price = float(tech.get("atr") or 0.0)
        if atr_price <= 0:
            return None
        if prev_c <= prev_mid and c > mid:
            action = "BUY"
        elif prev_c >= prev_mid and c < mid:
            action = "SELL"
        else:
            return None
        day = int(ts // 86400)
        key = (sym, day, action)
        if MODE_DAY_STATE.get(key, 0) >= 2:
            return None
        MODE_DAY_STATE[key] = MODE_DAY_STATE.get(key, 0) + 1
        sl_pips = TUN_DA_SL_ATR * atr_price / pip_size
        tp_pips = TUN_DA_TP_ATR * atr_price / pip_size
        return {"action": action, "exits": {"sl_pips": round(sl_pips, 1), "tp_pips": round(tp_pips, 1)}}

    # ---- 2026-10-08 derinleştirilmiş web-araştırması adayları ----
    # Ortak gövde: SL/TP modül parametrelerinden; TP=0 ise çıkış chandelier trailing'e bırakılır.
    def _mode_atr_exits() -> Optional[Dict[str, float]]:
        ap = float(tech.get("atr") or 0.0)
        if ap <= 0 or pip_size <= 0:
            return None
        return {"sl_pips": round(TUN_MODE_SL_ATR * ap / pip_size, 1),
                "tp_pips": round(TUN_MODE_TP_ATR * ap / pip_size, 1)}

    if TUN_ENTRY_MODE == "donchian_pure":
        # Saf kanal kırılımı (Turtle formu): kapanış önceki N barın EN YÜKSEK high / en düşük low
        # seviyesini aşarsa. Araştırma: intraday ekstrem yerine KAPANIŞ kullanmak yanlış kırılımı
        # azaltır; orta-hat çaprazından (donchian_adx) farklı davranır ve TP'yi trailing'e bırakmak
        # Donchian'ın trend-günü kenarını kurtarır (sabit 4×ATR TP nadir trendi kesiyordu).
        if not _mode_session_ok(sym, hour):
            return None
        adx = float(tech.get("adx") or 0.0)
        if adx < TUN_DA_ADX_MIN:
            return None
        n = TUN_DA_DONCH
        window = bars[max(0, ci - (n + 1)):ci]
        if len(window) < n:
            return None
        hi_n = max(b[2] for b in window[:-1])
        lo_n = min(b[3] for b in window[:-1])
        c = bars[ci - 1][4]
        if c > hi_n:
            action = "BUY"
        elif c < lo_n:
            action = "SELL"
        else:
            return None
        day = int(ts // 86400)
        key = (sym, day, action)
        if MODE_DAY_STATE.get(key, 0) >= 2:
            return None
        MODE_DAY_STATE[key] = MODE_DAY_STATE.get(key, 0) + 1
        ex = _mode_atr_exits()
        if ex is None:
            return None
        return {"action": action, "exits": ex}

    if TUN_ENTRY_MODE == "squeeze":
        # Bollinger bant sıkışması (bandwidth düşük persentil) + band dışı kapanış kırılımı.
        # Sıkışma yön vermez; yön EMA50 tarafıyla (momentum tiebreaker) belirlenir.
        if not _mode_session_ok(sym, hour):
            return None
        period = TUN_SQUEEZE_BB_PERIOD
        if ci < period + 100:
            return None
        bw = _BB_BW_CACHE.get(sym)
        if bw is None or len(bw) < ci:
            bw = _bb_bandwidth_series([b[4] for b in bars], period, 2.0)
            _BB_BW_CACHE[sym] = bw
        recent_bw = [x for x in bw[max(0, ci - 100):ci] if x > 0]
        if len(recent_bw) < 50:
            return None
        cur_bw = bw[ci - 1]
        if cur_bw <= 0:
            return None
        thr = sorted(recent_bw)[max(0, int(len(recent_bw) * TUN_SQUEEZE_BB_PCT / 100.0) - 1)]
        if cur_bw > thr:
            return None
        closes_s = [b[4] for b in bars[:ci]]
        win = closes_s[-period:]
        m = sum(win) / period
        sd = (sum((x - m) ** 2 for x in win) / period) ** 0.5
        up, lo = m + 2.0 * sd, m - 2.0 * sd
        c = bars[ci - 1][4]
        ema50 = float(tech.get("ema50") or 0.0)
        if c > up and c >= ema50:
            action = "BUY"
        elif c < lo and c <= ema50:
            action = "SELL"
        else:
            return None
        day = int(ts // 86400)
        key = (sym, day, action)
        if MODE_DAY_STATE.get(key, 0) >= 2:
            return None
        MODE_DAY_STATE[key] = MODE_DAY_STATE.get(key, 0) + 1
        ex = _mode_atr_exits()
        if ex is None:
            return None
        return {"action": action, "exits": ex}

    if TUN_ENTRY_MODE == "nr7":
        # Crabel NR7: son N barın EN DAR aralıklı barı; ardından o barın high/low kırılımı.
        # Sıkışma sonrası genişleme etkisi belgelenmiş; yön kırılım yönünden alınır.
        if not _mode_session_ok(sym, hour):
            return None
        n = TUN_NR7_N
        if ci < n + 2:
            return None
        nr_idx = ci - 2  # bir önceki tamamlanmış bar NR mi?
        rng = [bars[j][2] - bars[j][3] for j in range(ci - n - 1, ci - 1)]
        if not rng:
            return None
        nr_range = bars[nr_idx][2] - bars[nr_idx][3]
        if nr_range <= 0 or nr_range > min(rng) + 1e-12:
            return None
        adx = float(tech.get("adx") or 0.0)
        if TUN_NR7_ADX_MIN > 0 and adx < TUN_NR7_ADX_MIN:
            return None
        nr_hi = bars[nr_idx][2]
        nr_lo = bars[nr_idx][3]
        c = bars[ci - 1][4]
        if c > nr_hi:
            action = "BUY"
        elif c < nr_lo:
            action = "SELL"
        else:
            return None
        day = int(ts // 86400)
        key = (sym, day, action)
        if MODE_DAY_STATE.get(key, 0) >= 2:
            return None
        MODE_DAY_STATE[key] = MODE_DAY_STATE.get(key, 0) + 1
        ex = _mode_atr_exits()
        if ex is None:
            return None
        return {"action": action, "exits": ex}

    if TUN_ENTRY_MODE == "orb_ny":
        # London kutusu (07→13 UTC) → NY overlap (13→16 UTC) açılış-kırılımı. Araştırma:
        # overlap en geniş saatlik aralık + en dar spread → seans kırılımının tek net-pozitif
        # penceresi; OR/ATR genişlik filtresi (çok dar = gürültü, çok geniş = tükenmiş) şart.
        if hour < TUN_ORB_ENTRY_START_H or hour >= TUN_ORB_ENTRY_END_H:
            return None
        day = int(ts // 86400)
        window = bars[max(0, ci - 400):ci]
        box = [b for b in window
               if int(b[0] // 86400) == day
               and TUN_ORB_BOX_START_H <= int((b[0] % 86400) // 3600) < TUN_ORB_BOX_END_H]
        if len(box) < 20:
            return None
        box_hi = max(b[2] for b in box)
        box_lo = min(b[3] for b in box)
        box_h = box_hi - box_lo
        atr_price = float(tech.get("atr") or 0.0)
        if atr_price <= 0 or box_h <= 0:
            return None
        if TUN_ORB_MIN_ATR > 0 and box_h < TUN_ORB_MIN_ATR * atr_price:
            return None
        if TUN_ORB_MAX_ATR > 0 and box_h > TUN_ORB_MAX_ATR * atr_price:
            return None
        c = bars[ci - 1][4]
        if c > box_hi:
            action = "BUY"
        elif c < box_lo:
            action = "SELL"
        else:
            return None
        key = (sym, day, action)
        if LB_STATE.get(key):
            return None
        LB_STATE[key] = True
        if pip_size <= 0:
            return None
        sl_pips = (box_h * TUN_ORB_SL_FRAC) / pip_size
        return {"action": action, "exits": {"sl_pips": round(sl_pips, 1),
                                            "tp_pips": round(sl_pips * TUN_ORB_TP_R, 1)}}

    return None

# 2026-10-06 kademeli alım + sepet kapatma (DCA) — kullanıcı önerisi:
# Zarardaki işlemde fiyat, giriş-SL mesafesinin TUN_DCA_DIST_FRAC oranına gelince
# TUN_DCA_LOT_MULT× lot katman açılır (ops. S/R+Fibo seviye onayıyla). Katman sonrası
# bireysel TP silahsızlaşır; sepet bar-kapanış toplam P/L'siyle yönetilir:
#   ≥ TP_USD → BASKET_TP (hepsi kapanır) | ≤ -SL_USD → BASKET_SL (hepsi kapanır)
#   ≥ BUFFER_USD → sepet BE kilidi; armed iken ≤ 0.2×BUFFER → BASKET_BE (zararsız çıkış)
TUN_DCA = False
TUN_DCA_DIST_FRAC = 0.5     # katman tetiği: giriş-SL mesafesinin bu oranında (0.5 = yarı)
TUN_DCA_LOT_MULT = 2.0      # katman lotu = ilk pozisyon lotu × bu çarpan
TUN_DCA_TP_USD = 4.0        # sepet TP hedefi ($)
TUN_DCA_SL_USD = 10.0       # sepet SL limiti ($)
TUN_DCA_BUFFER_USD = 1.0    # sepet BE kilidi tamponu ($)
TUN_DCA_LEVEL_CHECK = False # katman tetiğinde S/R+Fibo seviye onayı
TUN_DCA_LEVEL_TOL_ATR = 0.25  # seviye onayı toleransı (× ATR, fiyat cinsi)
TUN_DCA_MAX_LAYERS = 1      # pozisyon başına en fazla katman sayısı (lead hariç)
TUN_DCA_DIST_STEP = 0.0     # her katmanda tetiğin derinleşmesi (× sl0; tetikler frac, frac+step, frac+2×step...)


# ---------------------------------------------------------------------------
# Veri çekme
# ---------------------------------------------------------------------------
FETCH_INTERVAL = "5m"       # main() --interval ile override edilir (5m / 15m zaman-dilimi merdiveni)


def fetch_candles(yf_sym: str, days: int) -> Optional[List[Tuple]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}?interval={FETCH_INTERVAL}&range={days}d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["chart"]["result"][0]
            quote = result["indicators"]["quote"][0]
            ts = result.get("timestamp", [])
            o, h, l, c = quote.get("open", []), quote.get("high", []), quote.get("low", []), quote.get("close", [])
            bars = []
            for i in range(min(len(ts), len(c))):
                if None in (o[i], h[i], l[i], c[i]):
                    continue
                bars.append((float(ts[i]), float(o[i]), float(h[i]), float(l[i]), float(c[i])))
            return bars
    except Exception as exc:
        print(f"[VERI HATASI] {yf_sym}: {exc}")
        return None


def fetch_all(days: int) -> Dict[str, List[Tuple]]:
    data: Dict[str, List[Tuple]] = {}
    jobs = dict(forex.YAHOO_SYMBOL_MAP)
    jobs.update(REPLAY_EXTRA_YF)  # krosçarlar (replay-only)
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futs = {ex.submit(fetch_candles, yf, days): fx for fx, yf in jobs.items()}
        for fut in concurrent.futures.as_completed(futs, timeout=180):
            fx = futs[fut]
            try:
                bars = fut.result()
                if bars and len(bars) >= 300:
                    data[fx] = bars
                else:
                    print(f"[UYARI] {fx}: yetersiz bar ({len(bars) if bars else 0}) — atlandı")
            except Exception:
                pass
    return data


def _compute_pip_val_overrides(data: Dict[str, List[Tuple]]) -> Dict[str, float]:
    """Krosçarlar için pencere-ortalaması pip_val: 1 lot = 100.000 birim; pip değeri
    quote para birimindedir → USD'ye çevirmek için quote'un USD kuru kullanılır.
    JPY kross: 1000/USDJPY; diğer kross: 10×(QUOTEUSD ortalaması)."""
    out: Dict[str, float] = {}

    def _avg(sym: str) -> Optional[float]:
        bars = data.get(sym)
        if not bars:
            return None
        closes = [b[4] for b in bars]
        return sum(closes) / len(closes)

    for sym, defn in REPLAY_SYMBOL_DEFS.items():
        if sym not in data:
            continue
        quote = sym[3:6]
        try:
            if quote == "JPY":
                usdjpy = _avg("USDJPY")
                if usdjpy:
                    out[sym] = round(1000.0 / usdjpy, 3)
            elif quote != "USD":
                q = _avg(f"{quote}USD")
                if q:
                    out[sym] = round(10.0 * q, 3)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Simülasyon pozisyonu ve çıkış motoru
# ---------------------------------------------------------------------------
@dataclass
class SimPos:
    symbol: str
    direction: str
    lots: float
    entry_price: float
    sl_price: float
    tp_price: float
    pip_size: float
    pip_val: float
    digits: int
    opened_bar: int
    fill_adjust: float = 0.0
    be_locked: bool = False
    partial_taken: bool = False
    partial_target_pips: float = 0.0
    partial_realized_usd: float = 0.0
    trail_active: bool = False
    entry_atr_pips: float = 0.0
    mfe_pips: float = 0.0
    layer: int = 0              # 0 = ilk pozisyon, 1.. = DCA katmanı
    dca_group: bool = False     # sepet yönetimi altında (TP/BE/trail bireysel çalışmaz)
    basket_armed: bool = False  # lead'te: sepet P/L tamponu geçti (BE kilidi arm)
    no_fixed_tp: bool = False   # sabit TP yok (tp_pips<=0) — çıkış chandelier trailing'e bırakılır


class Book:
    def __init__(self, name: str):
        self.name = name
        self.balance = BALANCE
        self.realized = 0.0
        self.positions: List[SimPos] = []
        self.closed: List[Dict] = []
        self.per_symbol: Dict[str, Dict[str, float]] = {}


def be_headroom_pips(symbol: str) -> float:
    s = symbol.upper()
    if "XAU" in s or "GOLD" in s:
        return 4.0
    if "BTC" in s:
        return 25.0
    return TUN_HEADROOM_FOREX


def size_lots(symbol: str, sl_pips: float, pip_val: float) -> float:
    risk_usd = BALANCE * (RISK_PCT / 100.0)
    raw = risk_usd / (sl_pips * pip_val) if sl_pips > 0 else 0.01
    s = symbol.upper()
    if "NAS" in s or "USTEC" in s or "US30" in s or "SPX" in s:
        return round(max(0.10, min(round(raw * 10) / 10, 0.20)), 2)
    if "OIL" in s or "WTI" in s:
        return round(max(0.50, min(raw, 1.0)), 2)
    if "XAU" in s or "GOLD" in s or "BTC" in s or "ETH" in s:
        return round(max(0.01, min(raw, 0.02)), 2)
    return round(max(0.01, min(raw, 0.05)), 2)


def open_position(cand: Dict, sl_pips: float, tp_pips: float, partial_pips: float, idx: int) -> Optional[SimPos]:
    sym = cand["symbol"]
    half_spread = cand["spread_pips"] * cand["pip_size"] / 2.0
    mid = cand["price"]
    no_fixed_tp = tp_pips <= 0
    # tp_pips<=0: sabit TP yok — çıkış motorda chandelier trailing'e bırakılır. tp_price'a
    # ulaşılamayacak uzak bir seviye yazılır (manage_position TP silahını no_fixed_tp ile kapatır).
    tp_eff = tp_pips if not no_fixed_tp else 100000.0
    if cand["action"] == "BUY":
        entry = round(mid + half_spread, cand["digits"])
        sl = round(entry - sl_pips * cand["pip_size"], cand["digits"])
        tp = round(entry + tp_eff * cand["pip_size"], cand["digits"])
    else:
        entry = round(mid - half_spread, cand["digits"])
        sl = round(entry + sl_pips * cand["pip_size"], cand["digits"])
        tp = round(entry - tp_eff * cand["pip_size"], cand["digits"])
    lots = size_lots(sym, sl_pips, cand["pip_val"])
    # Canlı motorla aynı risk normalizasyonu (tek kaynak: forex.apply_risk_normalization)
    lots, risk_skip = forex.apply_risk_normalization(sym, lots, sl_pips, cand["pip_val"], BALANCE * RISK_PCT / 100.0)
    if risk_skip:
        return None
    return SimPos(
        symbol=sym, direction=cand["action"], lots=lots,
        entry_price=entry, sl_price=sl, tp_price=tp, pip_size=cand["pip_size"],
        pip_val=cand["pip_val"], digits=cand["digits"], opened_bar=idx,
        partial_target_pips=partial_pips, fill_adjust=half_spread,
        entry_atr_pips=cand.get("atr_pips", 0.0), no_fixed_tp=no_fixed_tp,
    )


def manage_position(pos: SimPos, bar: Tuple, eff_trail_pips: float, eff_be_pips: float,
                    chandelier_mult: float = 0.0, tp_mode: str = "tp",
                    min_be_pips: float = 0.0, dca_mode: bool = False) -> Optional[Tuple[str, float, float]]:
    """Bir bar'da pozisyonu yönetir. Dönüş: (reason, exit_price, partial_realized) veya None.

    Sıra (muhafazakâr): SL önce → BE kilidi → kısmi kâr → trailing → TP.
    Kısmi kâr gerçekleşmesi pozisyona yazılır; balance'a close_position'da eklenir.
    tp_mode: "no_tp_on_trail" → trailing aktiflenince TP emri çekilir (kazananı koştur);
             "no_tp" → TP hiç yok. Aktifleşen barın kendisinde TP hâlâ geçerlidir
             (canlıda TP broker tarafında bekleyen emirdir; MODIFY_SLTP ancak sonraki
             tick'te etkili olur — muhafazakâr model: bar-başı trail bayrağına bakılır).
    min_be_pips: BE kilidinin EN ERKEN tetiklenme tabanı (pip) — volatilite-adaptif BE
             için kullanılır (0 = kapalı; $1 dolar kuralı yine kendi eşikte çalışır).
    dca_mode: pozisyon DCA sepet yönetiminde (manage_dca_groups) — bireysel BE/kısmi/
             trail/TP atlanır, yalnız SL çalışır; sepet eşikleri grup yöneticisinde.
    """
    ts, o, h, l, c = bar
    pip = pos.pip_size
    direction = pos.direction
    entry = pos.entry_price
    trail_pre = pos.trail_active  # bar-başı değer — TP silahı bu bar için buna bakar

    # (1) SL önce (muhafazakâr) — çıkışta spread maliyeti uygulanır
    if direction == "BUY" and l <= pos.sl_price:
        reason = "BE" if (pos.be_locked and pos.sl_price >= entry) else "SL"
        return (reason, round(pos.sl_price - pos.fill_adjust, pos.digits), 0.0)
    if direction == "SELL" and h >= pos.sl_price:
        reason = "BE" if (pos.be_locked and pos.sl_price <= entry) else "SL"
        return (reason, round(pos.sl_price + pos.fill_adjust, pos.digits), 0.0)

    ext = h if direction == "BUY" else l
    pnl_extreme_pips = (ext - entry) / pip if direction == "BUY" else (entry - ext) / pip
    pips_for_1usd = max(0.5, round(1.0 / max(0.0001, pos.lots * pos.pip_val), 1))
    headroom = be_headroom_pips(pos.symbol)

    # Dolar-kuralı BE parametreleri (XAUUSD özel testleri; diğer semboller canlıyla aynı)
    is_gold_pos = "XAU" in pos.symbol.upper() or "GOLD" in pos.symbol.upper()
    if is_gold_pos and TUN_BE_PIP_FIXED_GOLD > 0:
        pips_be = TUN_BE_PIP_FIXED_GOLD          # lot-bağımsız sabit pip tetiği
    elif is_gold_pos:
        pips_be = max(0.5, round(TUN_BE_USD_GOLD / max(0.0001, pos.lots * pos.pip_val), 1))
    else:
        pips_be = pips_for_1usd
    lock_ratio = TUN_BE_RATIO_GOLD if is_gold_pos else 0.40

    # MFE takibi (girişten beri en iyi fiyat, pip) — chandelier trailing için
    if pos.mfe_pips < pnl_extreme_pips:
        pos.mfe_pips = pnl_extreme_pips

    # (2) BE kilidi ($1 net kâr garantisinin üstünde, %40 kâr kilidi) — sepet üyesinde atlanır
    if not pos.be_locked and not dca_mode:
        is_dollar_be = pnl_extreme_pips >= (pips_be + headroom)
        is_pip_be = eff_be_pips > 0 and pnl_extreme_pips >= eff_be_pips
        if (is_dollar_be or is_pip_be) and pnl_extreme_pips >= min_be_pips:
            locked = max(pips_be, round(pnl_extreme_pips * lock_ratio, 1))
            if direction == "BUY":
                cand = round(entry + locked * pip, pos.digits)
                if cand > pos.sl_price and cand < ext:
                    pos.sl_price = cand
                    pos.be_locked = True
            else:
                cand = round(entry - locked * pip, pos.digits)
                if (pos.sl_price == 0 or cand < pos.sl_price) and cand > ext:
                    pos.sl_price = cand
                    pos.be_locked = True

    # (3) Kısmi kâr (yalnızca NEW — OLD'da partial_target_pips=0) — sepet üyesinde atlanır
    if pos.partial_target_pips > 0 and not pos.partial_taken and not dca_mode and pnl_extreme_pips >= pos.partial_target_pips:
        pos.partial_taken = True
        close_lots = round(pos.lots / 2.0, 2)
        if 0.01 <= close_lots < pos.lots:
            partial_realized = round(pos.partial_target_pips * close_lots * pos.pip_val, 2)
            pos.lots = round(pos.lots - close_lots, 2)
            pos.partial_realized_usd = round(pos.partial_realized_usd + partial_realized, 2)
            remaining_dpp = max(0.0001, pos.lots * pos.pip_val)
            lock_pips = max(0.5, round(1.0 / remaining_dpp, 1))
            if direction == "BUY":
                lock_sl = round(entry + lock_pips * pip, pos.digits)
                if lock_sl > pos.sl_price:
                    pos.sl_price = lock_sl
            else:
                lock_sl = round(entry - lock_pips * pip, pos.digits)
                if lock_sl < pos.sl_price:
                    pos.sl_price = lock_sl
            pos.be_locked = True

    # (4) Trailing (BE sonrası): chandelier (MFE − mult×ATR_giriş) veya sabit pip trail — sepet üyesinde atlanır
    if pos.be_locked and not dca_mode:
        pips_1usd_now = max(0.5, round(1.0 / max(0.0001, pos.lots * pos.pip_val), 1))
        if chandelier_mult > 0 and pos.entry_atr_pips > 0:
            # Volatilite-adaptif: kâr tepesinden volatilite nefes payı kadar geri ver
            giveback = chandelier_mult * pos.entry_atr_pips
            cand_pips = pos.mfe_pips - giveback
            if direction == "BUY":
                cand = round(entry + cand_pips * pip, pos.digits)
                min_safe = round(entry + pips_1usd_now * pip, pos.digits)
                cand = max(cand, min_safe)
                if cand > pos.sl_price:
                    pos.sl_price = cand
                    pos.trail_active = True
            else:
                cand = round(entry - cand_pips * pip, pos.digits)
                min_safe = round(entry - pips_1usd_now * pip, pos.digits)
                cand = min(cand, min_safe)
                if pos.sl_price == 0 or cand < pos.sl_price:
                    pos.sl_price = cand
                    pos.trail_active = True
        elif eff_trail_pips > 0:
            trail_dist = eff_trail_pips * pip
            if direction == "BUY":
                cand = round(c - trail_dist, pos.digits)
                min_safe = round(entry + pips_1usd_now * pip, pos.digits)
                cand = max(cand, min_safe)
                if cand > pos.sl_price and cand > entry:
                    pos.sl_price = cand
                    pos.trail_active = True
            else:
                cand = round(c + trail_dist, pos.digits)
                min_safe = round(entry - pips_1usd_now * pip, pos.digits)
                cand = min(cand, min_safe)
                if (pos.sl_price == 0 or cand < pos.sl_price) and cand < entry:
                    pos.sl_price = cand
                    pos.trail_active = True

    # (5) TP — tp_mode'a göre silahlanır (bkz. docstring); sepet üyesinde TP manage_dca_groups'a aittir
    if dca_mode or pos.no_fixed_tp:
        tp_armed = False
    elif tp_mode == "no_tp" or (tp_mode == "no_tp_crypto" and ("BTC" in pos.symbol.upper() or "ETH" in pos.symbol.upper())):
        tp_armed = False
    elif tp_mode == "no_tp_on_trail":
        tp_armed = not trail_pre          # muhafazakâr: aktifleşen barda TP hâlâ geçerli
    elif tp_mode == "no_tp_on_trail_live":
        tp_armed = not pos.trail_active   # canlıya yakın: aktifleşen barda da TP çekilir
    else:
        tp_armed = True
    if tp_armed:
        if direction == "BUY" and h >= pos.tp_price:
            return ("TP", round(pos.tp_price - pos.fill_adjust, pos.digits), 0.0)
        if direction == "SELL" and l <= pos.tp_price:
            return ("TP", round(pos.tp_price + pos.fill_adjust, pos.digits), 0.0)
    return None


def close_position(book: Book, pos: SimPos, reason: str, exit_price: float, closed_ts: float = 0.0) -> float:
    if pos.direction == "BUY":
        pnl_pips = (exit_price - pos.entry_price) / pos.pip_size
    else:
        pnl_pips = (pos.entry_price - exit_price) / pos.pip_size
    pnl_usd = round(pnl_pips * pos.lots * pos.pip_val, 2)
    total = round(pnl_usd + pos.partial_realized_usd, 2)
    book.balance = round(book.balance + total, 2)
    book.realized = round(book.realized + total, 2)
    st = book.per_symbol.setdefault(pos.symbol, {"n": 0, "wins": 0, "pnl": 0.0})
    st["n"] = int(st["n"]) + 1
    st["pnl"] = round(st["pnl"] + total, 2)
    if total >= 0:
        st["wins"] = int(st["wins"]) + 1
    book.closed.append({
        "symbol": pos.symbol, "direction": pos.direction, "lots": pos.lots,
        "pnl_usd": total, "reason": reason, "trail": pos.trail_active,
        "closed_ts": closed_ts,
    })
    return total


def float_pnl(pos: SimPos, mark: float) -> float:
    if pos.direction == "BUY":
        pnl_pips = (mark - pos.entry_price) / pos.pip_size
    else:
        pnl_pips = (pos.entry_price - mark) / pos.pip_size
    return pnl_pips * pos.lots * pos.pip_val


def _dca_level_ok(window: List[Tuple], trigger: float, atr_price: float, direction: str) -> bool:
    """Seviye onayı (kullanıcı önerisi): katman tetiğinin TUN_DCA_LEVEL_TOL_ATR×ATR komşuluğunda
    swing low/high veya Fibo 38.2/50/61.8 retrace seviyesi var mı? (son 96 bar ~8 saat pencere)"""
    tol = TUN_DCA_LEVEL_TOL_ATR * atr_price
    highs = [b[2] for b in window]
    lows = [b[3] for b in window]
    hi, lo = max(highs), min(lows)
    levels: List[float] = []
    if direction == "BUY":
        levels = [lo] + [lo + (hi - lo) * f for f in (0.382, 0.5, 0.618)]
        for i in range(2, len(window) - 2):
            if lows[i] <= min(lows[i - 2], lows[i - 1], lows[i + 1], lows[i + 2]):
                levels.append(lows[i])
    else:
        levels = [hi] + [hi - (hi - lo) * f for f in (0.382, 0.5, 0.618)]
        for i in range(2, len(window) - 2):
            if highs[i] >= max(highs[i - 2], highs[i - 1], highs[i + 1], highs[i + 2]):
                levels.append(highs[i])
    return min(abs(trigger - lv) for lv in levels) <= tol


def manage_dca_groups(book: Book, by_ts: Dict[str, Dict[float, Tuple]], ts: float,
                      data: Dict[str, List[Tuple]], cursors: Dict[str, int], idx: int) -> None:
    """Kademeli alım + sepet kapatma (DCA) — yalnız TUN_DCA açıkken NEW kitabında çalışır.

    Kullanıcı önerisi (2026-10-06): zarardaki işlemde fiyat, giriş-SL mesafesinin
    TUN_DCA_DIST_FRAC oranına gelince TUN_DCA_LOT_MULT× lot katman açılır; katman sonrası
    bireysel TP silahsızlaşır ve sepet bar-kapanış toplam P/L'siyle yönetilir:
      tot ≥ TP_USD        → BASKET_TP (tüm üyeler kapanır)
      tot ≤ -SL_USD       → BASKET_SL (tüm üyeler kapanır)
      tot ≥ BUFFER_USD    → sepet BE kilidi arm edilir
      armed iken tot ≤ 0.2×BUFFER → BASKET_BE (zararsız çıkış — BE kilidinin sepet karşılığı)
    Katman tetiği intra-bar (low/high), sepet eşikleri bar kapanışı — muhafazakâr model.
    """
    groups: Dict[Tuple[str, str], List[SimPos]] = {}
    for pos in book.positions:
        groups.setdefault((pos.symbol, pos.direction), []).append(pos)
    for (sym, direction), members in groups.items():
        lead = next((p for p in members if p.layer == 0), None)
        if lead is None:
            continue
        bar = by_ts[sym].get(ts)
        if bar is None:
            continue
        c = bar[4]
        mark = c

        def _exit_price(p: SimPos) -> float:
            return (mark - p.fill_adjust) if p.direction == "BUY" else (mark + p.fill_adjust)

        if len(members) > 1:
            tot_pnl = sum(float_pnl(p, _exit_price(p)) for p in members)
            closed = False
            if tot_pnl >= TUN_DCA_TP_USD:
                reason = "BASKET_TP"
            elif tot_pnl <= -TUN_DCA_SL_USD:
                reason = "BASKET_SL"
            elif not lead.basket_armed and tot_pnl >= TUN_DCA_BUFFER_USD:
                lead.basket_armed = True
                reason = None
            elif lead.basket_armed and tot_pnl <= 0.2 * TUN_DCA_BUFFER_USD:
                reason = "BASKET_BE"
            else:
                reason = None
            if reason:
                dead = {id(p) for p in members}
                for p in members:
                    close_position(book, p, reason, _exit_price(p), closed_ts=ts)
                book.positions = [p for p in book.positions if id(p) not in dead]
                closed = True
            if closed:
                continue

        # --- katman tetiği: BE kilitlenmemiş lead, katman hakkı kaldıysa ---
        # Tetik mesafesi katman sırasıyla derinleşir: frac, frac+step, frac+2×step...
        # (0.5/0.2 → %50, %70, %90 — hepsi SL'in içinde; SL ~1.0'da)
        layers_open = sum(1 for p in members if p.layer > 0)
        if layers_open >= TUN_DCA_MAX_LAYERS or lead.be_locked:
            continue
        sl0 = abs(lead.entry_price - lead.sl_price)
        if sl0 <= 0:
            continue
        dist_n = TUN_DCA_DIST_FRAC + layers_open * TUN_DCA_DIST_STEP
        if direction == "BUY":
            trigger = lead.entry_price - dist_n * sl0
            hit = bar[3] <= trigger
        else:
            trigger = lead.entry_price + dist_n * sl0
            hit = bar[2] >= trigger
        if not hit:
            continue
        if TUN_DCA_LEVEL_CHECK:
            window = data[sym][max(0, cursors[sym] - 96):cursors[sym]]
            atr_price = lead.entry_atr_pips * lead.pip_size
            if len(window) < 30 or atr_price <= 0 or not _dca_level_ok(window, trigger, atr_price, direction):
                continue
        lots = round(lead.lots * TUN_DCA_LOT_MULT, 2)
        if lots <= 0:
            continue
        entry = round(c + lead.fill_adjust, lead.digits) if direction == "BUY" else round(c - lead.fill_adjust, lead.digits)
        sl = lead.sl_price  # ortak SL: fiyat lead'in SL'ine değince tüm grup aynı barda birlikte kapanır
        book.positions.append(SimPos(
            symbol=sym, direction=direction, lots=lots, entry_price=entry, sl_price=sl,
            tp_price=0.0, pip_size=lead.pip_size, pip_val=lead.pip_val, digits=lead.digits,
            opened_bar=idx, fill_adjust=lead.fill_adjust, entry_atr_pips=lead.entry_atr_pips,
            layer=layers_open + 1, dca_group=True,
        ))
        lead.dca_group = True


def manage_book(book: Book, by_ts: Dict[str, Dict[float, Tuple]], ts: float, chandelier_mult: float = 0.0,
                tp_mode: str = "tp", exit_maps: Optional[Dict[str, Any]] = None):
    still = []
    for pos in book.positions:
        bar = by_ts[pos.symbol].get(ts)
        if bar is None:
            still.append(pos)
            continue
        spec = forex.get_symbol_trading_specs(
            pos.symbol, base_be=BASE_BE_PIPS, base_trail=BASE_TRAIL_PIPS,
            atr_pips=(pos.entry_atr_pips if (TUN_SPEC_ATR and pos.entry_atr_pips > 0) else None))
        eff_trail = spec["trail_pips"]
        min_be = 0.0
        if TUN_GOLD_VOL_EXITS and ("XAU" in pos.symbol.upper() or "GOLD" in pos.symbol.upper()) and pos.entry_atr_pips > 0:
            # Volatilite-adaptif (giriş ATR'ine göre, işlem başına sabit):
            # trailing mesafesi ve BE tetik tabanı o işlemin volatilitesine ölçeklenir.
            eff_trail = max(TUN_VOL_TRAIL_FLOOR, TUN_VOL_TRAIL_MULT * pos.entry_atr_pips)
            min_be = TUN_VOL_BE_MULT * pos.entry_atr_pips
        res = manage_position(pos, bar, eff_trail, spec["be_pips"], chandelier_mult, tp_mode, min_be,
                              dca_mode=pos.dca_group)
        if res and res[0] in ("SL", "BE", "TP"):
            close_position(book, pos, res[0], res[1], closed_ts=ts)
            continue
        # (6) Erken momentum-dönüş tepkisi — SL/BE/trail/TP bu barda tetiklenmediyse:
        #     a) TUN_ST_FLIP_TIGHTEN > 0: kapatma, kâr varsa stopu bu pip mesafeye sıkılaştır
        #     b) aksi halde TUN_ST_FLIP_EXIT / TUN_EMA_FLIP_EXIT: bar kapanışında kapat (MOMFLIP)
        if TUN_ST_FLIP_TIGHTEN > 0 and _st_ema_against(pos, bar, exit_maps):
            c = bar[4]
            pnl_now = ((c - pos.entry_price) / pos.pip_size if pos.direction == "BUY"
                       else (pos.entry_price - c) / pos.pip_size)
            if pnl_now > 0:
                if pos.direction == "BUY":
                    cand = round(c - TUN_ST_FLIP_TIGHTEN * pos.pip_size, pos.digits)
                    if cand > pos.sl_price and cand > pos.entry_price:
                        pos.sl_price = cand
                        pos.trail_active = True
                else:
                    cand = round(c + TUN_ST_FLIP_TIGHTEN * pos.pip_size, pos.digits)
                    if (pos.sl_price == 0 or cand < pos.sl_price) and cand < pos.entry_price:
                        pos.sl_price = cand
                        pos.trail_active = True
            still.append(pos)
            continue
        flip = _momflip_exit(pos, bar, exit_maps)
        if flip is not None:
            close_position(book, pos, flip[0], flip[1], closed_ts=ts)
        elif (TUN_MODE_FLAT16 and TUN_ENTRY_MODE != "classic"
              and "XAU" not in pos.symbol.upper() and "BTC" not in pos.symbol.upper()
              and datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).hour == 16):
            # Araştırma ADAY 5: NY öğleden sonrası negatif → giriş-modu koşumlarında 16:00 UTC flat
            c = bar[4]
            exit_px = (round(c - pos.fill_adjust, pos.digits) if pos.direction == "BUY"
                       else round(c + pos.fill_adjust, pos.digits))
            close_position(book, pos, "SEANS16", exit_px, closed_ts=ts)
        else:
            still.append(pos)
    book.positions = still


# ---------------------------------------------------------------------------
# NASDAQ mini-motorları (ortalamaya dönüş felsefesi — ana motordan TAMAMEN bağımsız)
# ---------------------------------------------------------------------------
# RSI2  : Connors RSI(2) 5m uyarlaması — EMA200(5m) trend filtresiyle dipten alım / tepeden satım,
#         çıkış RSI(2)'nin eşik dönmesi + sert ATR stopu + gün sonu zorunlu kapanış.
# FADE  : seans-çapa fade (VWAP'ın hacimsiz kuzeni) — fiyat seans ortalamasından k×ATR sapınca
#         çapaya doğru ters işlem; hedef çapa (giriş anındaki çapa snapshotı), gün sonu kapanış.
MR_SYMBOLS = ("NAS100", "US30")
RSI2_ENABLED = False
RSI2_ENTRY = 10.0             # long tetiği RSI(2) ≤ bu (short için 100−eşik)
RSI2_EXIT = 65.0              # long çıkışı RSI(2) ≥ bu (short için 100−eşik)
RSI2_SL_ATR = 1.5             # sert stop: giriş ± 1.5×ATR(14, 5m)
FADE_ENABLED = False
FADE_K_ATR = 2.0              # seans ortalamasından k×ATR sapma → fade
FADE_SL_ATR = 1.5             # fade sert stopu
FADE_EARLY_ONLY = False       # yalnız ilk 2 saat (13:30-15:30 UTC) girişleri


def _ema_series(vals: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1.0)
    out = [vals[0]]
    e = vals[0]
    for v in vals[1:]:
        e += k * (v - e)
        out.append(e)
    return out


def _st_dir_series(bars: List[Tuple], period: int = 10, mult: float = 3.0) -> List[int]:
    """forex._compute_supertrend ile BİREBİR ratchet matematiği, tüm seri yönleri.

    Look-ahead yok: i. barın yönü yalnız i ve öncesi barlardan türetilir.
    İlk `period` bar için yön tanımsızdır (0 döner — çıkış sinyali üretmez).
    """
    n = len(bars)
    out = [0] * n
    if n < period + 2:
        return out
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    c = [b[4] for b in bars]
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, n)]
    atr_series = []
    atr_val = sum(tr[:period]) / period
    atr_series.append(atr_val)
    for i in range(period, len(tr)):
        atr_val = (atr_val * (period - 1) + tr[i]) / period
        atr_series.append(atr_val)
    hl2 = [(h[i] + l[i]) / 2.0 for i in range(n)]
    direction = 0
    final_upper = 0.0
    final_lower = 0.0
    for i in range(period, n):
        atr_i = atr_series[i - period] if (i - period) < len(atr_series) else atr_series[-1]
        upper = hl2[i] + mult * atr_i
        lower = hl2[i] - mult * atr_i
        prev_close = c[i - 1]
        if i == period:
            final_upper, final_lower = upper, lower
            direction = 1 if c[i] >= hl2[i] else -1
        else:
            final_upper = upper if (upper < final_upper or prev_close > final_upper) else final_upper
            final_lower = lower if (lower > final_lower or prev_close < final_lower) else final_lower
            if c[i] > final_upper:
                direction = 1
            elif c[i] < final_lower:
                direction = -1
        out[i] = direction
    return out


def _htf_st_map(bars: List[Tuple], period: int = 10, mult: float = 3.0) -> Dict[int, int]:
    """15M kova (ts//900) SuperTrend yönü → her 15M kova anahtarı için son TAMAMLANMIŞ
    kovanın yönü (look-ahead yok: kova k'nin içindeyken k henüz tamamlanmamıştır;
    yanıt = k'dan küçük en büyük anahtarlı kovanın yönü)."""
    by_bucket: Dict[int, List[float]] = {}
    for b in bars:
        k = int(b[0] // 900)
        bk = by_bucket.get(k)
        if bk is None:
            by_bucket[k] = [b[1], b[2], b[3], b[4]]
        else:
            bk[1] = max(bk[1], b[2])
            bk[2] = min(bk[2], b[3])
            bk[3] = b[4]
    keys = sorted(by_bucket)
    st_bars = [(k * 900.0, by_bucket[k][0], by_bucket[k][1], by_bucket[k][2], by_bucket[k][3]) for k in keys]
    dirs = _st_dir_series(st_bars, period, mult)
    out: Dict[int, int] = {}
    last_dir = 0
    for i, k in enumerate(keys):
        out[k] = last_dir
        last_dir = dirs[i]
    return out


def _st_age_map(bars: List[Tuple], period: int = 10, mult: float = 3.0) -> Dict[float, Tuple[int, int]]:
    """5M SuperTrend yönü ve yaşı (flip'ten beri geçen bar) — ts → (yön, yaş)."""
    dirs = _st_dir_series(bars, period, mult)
    out: Dict[float, Tuple[int, int]] = {}
    age = 0
    prev = 0
    for i, d in enumerate(dirs):
        if d == 0:
            age = 0
        elif d != prev:
            age, prev = 1, d
        else:
            age += 1
        out[bars[i][0]] = (d, age)
    return out


def _rsi_div_map(bars: List[Tuple], lookback: int = 12, thresh: float = 5.0) -> Dict[float, int]:
    """RSI(14) uyumsuzluk haritası: fiyat lookback penceresinin zirvesini YENİLERKEN RSI
    teyit etmiyorsa +1 (boğa tükenmesi → BUY'a karşı), dibi yenilerken −1 (ayı tükenmesi →
    SELL'e karşı). Tükenmemiş barlar haritada yer almaz."""
    closes = [b[4] for b in bars]
    rsi = _rsi_wilder(closes, 14)
    out: Dict[float, int] = {}
    n = len(bars)
    for i in range(lookback + 1, n):
        r_now = rsi[i]
        if r_now is None:
            continue
        w = closes[i - lookback:i]
        j_hi = i - lookback + max(range(lookback), key=lambda t: w[t])
        if closes[i] > closes[j_hi] and rsi[j_hi] is not None and (rsi[j_hi] - r_now) >= thresh:
            out[bars[i][0]] = 1
            continue
        j_lo = i - lookback + min(range(lookback), key=lambda t: w[t])
        if closes[i] < closes[j_lo] and rsi[j_lo] is not None and (r_now - rsi[j_lo]) >= thresh:
            out[bars[i][0]] = -1
    return out


def _st_ema_against(pos, bar: Tuple, exit_maps: Optional[Dict[str, Any]]) -> bool:
    """Pozisyona karşı momentum döndü mü? (SuperTrend yönü veya EMA9/21 çaprazı)"""
    if not exit_maps:
        return False
    i = exit_maps["ts_idx"].get(pos.symbol, {}).get(bar[0])
    if i is None:
        return False
    c = bar[4]
    if TUN_ST_FLIP_EXIT or TUN_ST_FLIP_TIGHTEN > 0:
        dirs = exit_maps["st_dirs"].get(pos.symbol, [])
        d = dirs[i] if i < len(dirs) else 0
        if (pos.direction == "BUY" and d < 0) or (pos.direction == "SELL" and d > 0):
            return True
    if TUN_EMA_FLIP_EXIT:
        e9s = exit_maps["ema9"].get(pos.symbol)
        e21s = exit_maps["ema21"].get(pos.symbol)
        if e9s and e21s and i < len(e9s) and i < len(e21s):
            e9, e21 = e9s[i], e21s[i]
            if ((pos.direction == "BUY" and c < e21 and e9 < e21)
                    or (pos.direction == "SELL" and c > e21 and e9 > e21)):
                return True
    return False


def _momflip_exit(pos, bar: Tuple, exit_maps: Optional[Dict[str, Any]]) -> Optional[Tuple[str, float]]:
    """Erken momentum-dönüş çıkışı (MOMFLIP): pozisyon açıkken sembolün 5M SuperTrend yönü
    (veya EMA9/21 çaprazı) pozisyona karşı döndüyse bar kapanışında kapat.

    Canlıdaki REVERSAL_FLIP ancak karşı yönde tam sinyal (skor ≥ 76-78) gelince tetiklenir —
    bu da hareketin çoğu bittikten sonra olur. MOMFLIP karşı skorun eşiğe ulaşmasını beklemez.
    Çıkış fiyatı bar kapanışı ± yarım spread (SL çıkışıyla aynı muhafazakâr konvansiyon).
    """
    if not exit_maps:
        return None
    if not _st_ema_against(pos, bar, exit_maps):
        return None
    c = bar[4]
    if TUN_ST_FLIP_MIN_PNL > 0:
        pnl_pips = ((c - pos.entry_price) / pos.pip_size if pos.direction == "BUY"
                    else (pos.entry_price - c) / pos.pip_size)
        if pnl_pips < TUN_ST_FLIP_MIN_PNL:
            return None
    if pos.direction == "BUY":
        return ("MOMFLIP", round(c - pos.fill_adjust, pos.digits))
    return ("MOMFLIP", round(c + pos.fill_adjust, pos.digits))


def _rsi_wilder(closes: List[float], period: int = 2) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    deltas = [closes[i + 1] - closes[i] for i in range(period)]
    avg_g = sum(max(d, 0.0) for d in deltas) / period
    avg_l = sum(max(-d, 0.0) for d in deltas) / period
    for i in range(period, len(closes)):
        if i > period:
            d = closes[i] - closes[i - 1]
            avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
            avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_l <= 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return out


def _mini_atr_series(bars: List[Tuple], period: int = 14) -> List[float]:
    trs: List[float] = []
    prev_c = bars[0][4]
    for b in bars:
        trs.append(max(b[2] - b[3], abs(b[2] - prev_c), abs(b[3] - prev_c)))
        prev_c = b[4]
    a = sum(trs[:period]) / period
    out = [a] * period
    for i in range(period, len(trs)):
        a = (a * (period - 1) + trs[i]) / period
        out.append(a)
    return out


def _mini_stats(book: Book, balance_start: float = BALANCE) -> Dict[str, Any]:
    wins = sum(1 for t in book.closed if t["pnl_usd"] >= 0)
    n = len(book.closed)
    per_symbol: Dict[str, Dict[str, float]] = {}
    by_reason: Dict[str, Dict[str, float]] = {}
    bal, peak, max_dd = balance_start, balance_start, 0.0
    for t in book.closed:
        bal = round(bal + t["pnl_usd"], 2)
        peak = max(peak, bal)
        max_dd = max(max_dd, peak - bal)
        st = per_symbol.setdefault(t["symbol"], {"n": 0, "wins": 0, "pnl": 0.0})
        st["n"] = int(st["n"]) + 1
        st["pnl"] = round(st["pnl"] + t["pnl_usd"], 2)
        if t["pnl_usd"] >= 0:
            st["wins"] = int(st["wins"]) + 1
        r = by_reason.setdefault(t["reason"], {"n": 0, "pnl_usd": 0.0})
        r["n"] = int(r["n"]) + 1
        r["pnl_usd"] = round(r["pnl_usd"] + t["pnl_usd"], 2)
    return {
        "trades": n,
        "win_rate": round(100 * wins / n, 1) if n else 0.0,
        "net_pnl_usd": round(book.realized, 2),
        "avg_pnl_usd": round(book.realized / n, 3) if n else 0.0,
        "balance": book.balance,
        "per_symbol": per_symbol,
        "exit_reasons": by_reason,
        "max_drawdown_usd": round(max_dd, 2),
    }


def _mini_close(book: Book, sym: str, direction: str, lots: float, entry: float, exit_price: float,
                reason: str, pip_size: float, pip_val: float, digits: int, ts: float) -> None:
    pnl_pips = (exit_price - entry) / pip_size if direction == "BUY" else (entry - exit_price) / pip_size
    pnl_usd = round(pnl_pips * lots * pip_val, 2)
    st = book.per_symbol.setdefault(sym, {"n": 0, "wins": 0, "pnl": 0.0})
    st["n"] = int(st["n"]) + 1
    st["pnl"] = round(st["pnl"] + pnl_usd, 2)
    if pnl_usd >= 0:
        st["wins"] = int(st["wins"]) + 1
    book.realized = round(book.realized + pnl_usd, 2)
    book.balance = round(book.balance + pnl_usd, 2)
    book.closed.append({"symbol": sym, "direction": direction, "lots": lots, "pnl_usd": pnl_usd,
                        "reason": reason, "trail": False, "closed_ts": ts})


def run_rsi2_engine(data: Dict[str, List[Tuple]], entry_start_ts: Optional[float],
                    entry_end_ts: Optional[float]) -> Dict[str, Any]:
    """Connors RSI(2) mini-motoru (5m): EMA200(5m) trend filtresi + RSI(2) aşırılık girişi,
    RSI(2) eşik dönüşü çıkışı, sert ATR stopu, gün sonu zorunlu kapanış."""
    book = Book("RSI2")
    for sym in MR_SYMBOLS:
        bars = data.get(sym) or []
        if len(bars) < 300:
            continue
        closes = [b[4] for b in bars]
        ema = _ema_series(closes, 200)
        rsi = _rsi_wilder(closes, 2)
        atr = _mini_atr_series(bars)
        item = next((i for i in forex.FOREX_SYMBOLS if i["symbol"] == sym), None)
        pip_size = item["pip_size"] if item else 1.0
        spec = forex.get_symbol_trading_specs(sym)
        pip_val, digits = spec["pip_val"], spec["digits"]
        half_spread = CATEGORY_SPREAD_PIPS.get("index", 3.0) * pip_size / 2.0
        pos = None
        cooldown_until = -1
        for i, b in enumerate(bars):
            ts, o, h, l, c = b[0], b[1], b[2], b[3], b[4]
            in_win = (entry_start_ts is None or ts >= entry_start_ts) and (entry_end_ts is None or ts < entry_end_ts)
            day_mod = int(ts % 86400)
            nxt = bars[i + 1] if i + 1 < len(bars) else None
            day_end = nxt is None or int(nxt[0] % 86400) < day_mod
            if pos is not None:
                d = pos["dir"]
                exit_reason = exit_price = None
                if d == "BUY":
                    if l <= pos["sl"]:
                        exit_reason, exit_price = "SL", round(pos["sl"] - half_spread, digits)
                    elif rsi[i] is not None and rsi[i] >= RSI2_EXIT:
                        exit_reason, exit_price = "RSI", round(c - half_spread, digits)
                    elif day_end:
                        exit_reason, exit_price = "GUNSONU", round(c - half_spread, digits)
                else:
                    if h >= pos["sl"]:
                        exit_reason, exit_price = "SL", round(pos["sl"] + half_spread, digits)
                    elif rsi[i] is not None and rsi[i] <= 100.0 - RSI2_EXIT:
                        exit_reason, exit_price = "RSI", round(c + half_spread, digits)
                    elif day_end:
                        exit_reason, exit_price = "GUNSONU", round(c + half_spread, digits)
                if exit_reason:
                    _mini_close(book, sym, d, pos["lots"], pos["entry"], exit_price, exit_reason,
                                pip_size, pip_val, digits, ts)
                    pos = None
                    cooldown_until = i + 5
                continue
            if not in_win or i < 210 or i < cooldown_until or rsi[i] is None or atr[i] <= 0:
                continue
            long_sig = c > ema[i] and rsi[i] <= RSI2_ENTRY
            short_sig = c < ema[i] and rsi[i] >= 100.0 - RSI2_ENTRY
            if not (long_sig or short_sig):
                continue
            d = "BUY" if long_sig else "SELL"
            entry = round(c + half_spread, digits) if d == "BUY" else round(c - half_spread, digits)
            sl_dist = RSI2_SL_ATR * atr[i]
            sl = round(entry - sl_dist, digits) if d == "BUY" else round(entry + sl_dist, digits)
            lots = size_lots(sym, sl_dist / pip_size, pip_val)
            if lots <= 0:
                continue
            pos = {"dir": d, "entry": entry, "sl": sl, "lots": lots}
    return _mini_stats(book)


def run_fade_engine(data: Dict[str, List[Tuple]], entry_start_ts: Optional[float],
                    entry_end_ts: Optional[float]) -> Dict[str, Any]:
    """Seans-çapa fade mini-motoru: fiyat seans ortalamasından k×ATR uzaklaşınca çapaya ters işlem.
    Hedef: giriş anındaki çapa (limit). Gün sonu zorunlu kapanış."""
    book = Book("FADE")
    for sym in MR_SYMBOLS:
        bars = data.get(sym) or []
        if len(bars) < 300:
            continue
        atr = _mini_atr_series(bars)
        item = next((i for i in forex.FOREX_SYMBOLS if i["symbol"] == sym), None)
        pip_size = item["pip_size"] if item else 1.0
        spec = forex.get_symbol_trading_specs(sym)
        pip_val, digits = spec["pip_val"], spec["digits"]
        half_spread = CATEGORY_SPREAD_PIPS.get("index", 3.0) * pip_size / 2.0
        pos = None
        cooldown_until = -1
        anchor_sum, anchor_n = 0.0, 0
        cur_day = -1
        for i, b in enumerate(bars):
            ts, o, h, l, c = b[0], b[1], b[2], b[3], b[4]
            day = int(ts // 86400)
            day_mod = int(ts % 86400)
            if day != cur_day:
                cur_day = day
                anchor_sum, anchor_n = 0.0, 0
            anchor_sum += c
            anchor_n += 1
            anchor = anchor_sum / anchor_n
            in_win = (entry_start_ts is None or ts >= entry_start_ts) and (entry_end_ts is None or ts < entry_end_ts)
            nxt = bars[i + 1] if i + 1 < len(bars) else None
            day_end = nxt is None or int(nxt[0] % 86400) < day_mod
            if pos is not None:
                d = pos["dir"]
                exit_reason = exit_price = None
                if d == "SELL":
                    if h >= pos["sl"]:
                        exit_reason, exit_price = "SL", round(pos["sl"] + half_spread, digits)
                    elif l <= pos["tp"]:
                        exit_reason, exit_price = "CAPA", round(pos["tp"] + half_spread, digits)
                    elif day_end:
                        exit_reason, exit_price = "GUNSONU", round(c + half_spread, digits)
                else:
                    if l <= pos["sl"]:
                        exit_reason, exit_price = "SL", round(pos["sl"] - half_spread, digits)
                    elif h >= pos["tp"]:
                        exit_reason, exit_price = "CAPA", round(pos["tp"] - half_spread, digits)
                    elif day_end:
                        exit_reason, exit_price = "GUNSONU", round(c - half_spread, digits)
                if exit_reason:
                    _mini_close(book, sym, d, pos["lots"], pos["entry"], exit_price, exit_reason,
                                pip_size, pip_val, digits, ts)
                    pos = None
                    cooldown_until = i + 5
                continue
            if not in_win or i < 210 or i < cooldown_until or atr[i] <= 0:
                continue
            if FADE_EARLY_ONLY and not (48600 <= day_mod < 55800):  # 13:30-15:30 UTC
                continue
            dev = c - anchor
            if dev >= FADE_K_ATR * atr[i]:
                d = "SELL"
            elif dev <= -FADE_K_ATR * atr[i]:
                d = "BUY"
            else:
                continue
            entry = round(c + half_spread, digits) if d == "BUY" else round(c - half_spread, digits)
            sl_dist = FADE_SL_ATR * atr[i]
            sl = round(entry - sl_dist, digits) if d == "BUY" else round(entry + sl_dist, digits)
            tp = round(anchor, digits)
            lots = size_lots(sym, sl_dist / pip_size, pip_val)
            if lots <= 0:
                continue
            pos = {"dir": d, "entry": entry, "sl": sl, "tp": tp, "lots": lots}
    return _mini_stats(book)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def run_replay(data: Dict[str, List[Tuple]], days: int, entry_start_ts: Optional[float] = None,
               entry_end_ts: Optional[float] = None, symbol_filter: Optional[set] = None,
               add_symbols: Optional[set] = None,
               exclude_symbols: Optional[set] = None) -> Dict[str, Any]:
    # Ek metrikler: NEW defteri için bar-bazlı özkaynak örnekleme (maks. düşüş için)
    eq_ts: List[float] = []
    eq_new: List[float] = []
    last_close: Dict[str, float] = {}
    # Yalnızca canlı motorun izin listesindeki semboller (SPX500/XAGUSD/USOIL işlem yapmaz);
    # --add-symbols ile test adayları eklenebilir (canlı allowed_symbols'a dokunmaz)
    allowed = set(forex.ForexAutoPaperSettings().allowed_symbols)
    if symbol_filter:
        allowed &= {s.upper() for s in symbol_filter}
    if add_symbols:
        allowed |= {s.upper() for s in add_symbols}
    if exclude_symbols:
        allowed -= {s.upper() for s in exclude_symbols}
    symbols = [s for s in data if s != "DXY" and s in allowed]
    by_ts = {s: {b[0]: b for b in data[s]} for s in symbols}
    # Birleşim zaman ekseni: her sembol kendi seansında bar üretir; kesişim örneklemi kısaltır
    all_ts = set()
    for s in symbols:
        all_ts.update(b[0] for b in data[s])
    common_ts = sorted(all_ts)
    span_days = (common_ts[-1] - common_ts[0]) / 86400.0 if common_ts else 0.0
    print(f"[REPLAY] {len(symbols)} sembol | {len(common_ts)} birleşik 5M bar | span ~{span_days:.1f} gün")
    warmup = INDICATOR_WINDOW

    books = {"OLD": Book("OLD"), "NEW": Book("NEW")}
    shadow_book: Dict[str, Dict[str, Any]] = {}
    corr = FXCorrelationMonitor()
    closes_cache: Dict[str, List[float]] = {}
    last_entry_bar: Dict[Tuple[str, str], int] = {}
    cursors: Dict[str, int] = {s: 0 for s in symbols}

    # Açılış sürüşü önyargısı: her UTC gününün 13:30 ilk 5m mumunun yönü (Zarattini-Aziz 2023,
    # QQQ ilk-mum devamı). 48600 sn = 13:30 UTC; mum eksikse (tatil/yarım gün) o gün teyit yok.
    open_drive_dir: Dict[Tuple[str, int], int] = {}
    if TUN_INDEX_OPEN_DRIVE:
        for s in symbols:
            if s in INDEX_GATED:
                for b in data[s]:
                    if b[0] % 86400 == 48600:
                        open_drive_dir[(s, int(b[0] // 86400))] = 1 if b[4] > b[1] else -1

    orig_dxy = forex._TECHNICAL_CACHE.get("DXY")
    dxy_list = data.get("DXY") or []

    # BTC EMA200(1h) rejim serisi: 5m barlar saatlik kapanışlara indirgenir, EMA200 saat
    # kapanışları üzerinden hesaplanır; 5m bar SAATİN İÇİNDEYKEN bir önceki TAMAMLANMIŞ
    # saatin EMA'sı kullanılır (look-ahead yok).
    btc_ema200_by_hour: Dict[int, float] = {}
    if TUN_BTC_EMA200 and "BTCUSD" in data:
        hourly: Dict[int, float] = {}
        for b in data["BTCUSD"]:
            hourly[int(b[0] // 3600)] = b[4]
        ema = None
        for hk in sorted(hourly):
            c_h = hourly[hk]
            ema = c_h if ema is None else ema + (2.0 / 201.0) * (c_h - ema)
            btc_ema200_by_hour[hk] = ema

    # BTC günlük VWAP: UTC günü başından itibaren kümülatif Σ(tp×v)/Σv (tp=(h+l+c)/3)
    btc_vwap_by_ts: Dict[float, float] = {}
    if TUN_BTC_VWAP and "BTCUSD" in data:
        vols = _load_btc_volume_map()
        cum_qv = cum_v = 0.0
        cur_day: Optional[int] = None
        for b in data["BTCUSD"]:
            day = int(b[0] // 86400)
            if day != cur_day:
                cur_day, cum_qv, cum_v = day, 0.0, 0.0
            tp = (b[2] + b[3] + b[4]) / 3.0
            v = float(vols.get(b[0], 0.0) or 0.0)
            cum_qv += tp * v
            cum_v += v
            if cum_v > 0:
                btc_vwap_by_ts[b[0]] = cum_qv / cum_v

    # Erken momentum-dönüş çıkışı (MOMFLIP) serileri: sembol başına tüm seri bir kez hesaplanır,
    # ts→index haritasıyla bar bazında okunur (look-ahead yok: i. değer yalnız i ve öncesi barlardan).
    exit_maps: Optional[Dict[str, Any]] = None
    if TUN_ST_FLIP_EXIT or TUN_EMA_FLIP_EXIT or TUN_ST_FLIP_TIGHTEN > 0:
        exit_maps = {"ts_idx": {}, "st_dirs": {}, "ema9": {}, "ema21": {}}
        for s in symbols:
            bars_s = data[s]
            exit_maps["ts_idx"][s] = {b[0]: i for i, b in enumerate(bars_s)}
            if TUN_ST_FLIP_EXIT or TUN_ST_FLIP_TIGHTEN > 0:
                exit_maps["st_dirs"][s] = _st_dir_series(bars_s, ST_EXIT_PERIOD, ST_EXIT_MULT)
            if TUN_EMA_FLIP_EXIT:
                closes_s = [b[4] for b in bars_s]
                exit_maps["ema9"][s] = _ema_series(closes_s, 9)
                exit_maps["ema21"][s] = _ema_series(closes_s, 21)

    # "Trend bitti" dedektör haritaları (giriş kapıları): HTF 15M ST yönü, 5M ST yaşı, RSI uyumsuzluk
    htf_maps: Dict[str, Dict[int, int]] = {}
    st_age_maps: Dict[str, Dict[float, Tuple[int, int]]] = {}
    div_maps: Dict[str, Dict[float, int]] = {}
    if TUN_HTF_ALIGN:
        for s in symbols:
            htf_maps[s] = _htf_st_map(data[s], ST_EXIT_PERIOD, ST_EXIT_MULT)
    if TUN_PYR_AGE_MAX > 0:
        for s in symbols:
            st_age_maps[s] = _st_age_map(data[s], ST_EXIT_PERIOD, ST_EXIT_MULT)
    if TUN_DIV_GATE > 0:
        for s in symbols:
            div_maps[s] = _rsi_div_map(data[s], 12, TUN_DIV_GATE)

    # Seri-SL sigortası durumu: kapanış tüketimi + sembol soğuma penceresi
    loss_streak: Dict[str, int] = {}
    loss_cd_until: Dict[str, float] = {}
    streak_seen = {"NEW": 0}

    for idx, ts in enumerate(common_ts):
        # Pencere sonu: o haftanın kapanışıyla dur; kalan pozisyonlar aşağıda
        # pencere içi son fiyatla kapatılır (hafta-sonu ötesine taşmaz).
        if entry_end_ts is not None and ts >= entry_end_ts:
            break
        # Sembol imleçlerini ilerlet: bars[:cursor] bu adımda kullanılabilir veri
        fresh = {}
        for s in symbols:
            bars = data[s]
            ci = cursors[s]
            while ci < len(bars) and bars[ci][0] <= ts:
                ci += 1
            cursors[s] = ci
            if ci > 0:
                last_close[s] = bars[ci - 1][4]
            fresh[s] = ci > 0 and bars[ci - 1][0] == ts and ci >= 30

        if idx < warmup:
            continue
        hour = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).hour

        # DXY rejimi (yalnız NEW): test edilmiş get_dxy_regime'i yeniden kullanmak için
        # geçici olarak _TECHNICAL_CACHE["DXY"] set edilir.
        dxy_regime = None
        if dxy_list:
            dxy_i = _bar_index_at_or_before(dxy_list, ts)
            if dxy_i is not None and dxy_i >= 15:
                w = dxy_list[max(0, dxy_i - INDICATOR_WINDOW):dxy_i + 1]
                if len(w) >= 15:
                    forex._TECHNICAL_CACHE["DXY"] = forex._compute_technical_indicators(
                        [b[4] for b in w], [b[2] for b in w], [b[3] for b in w], [b[1] for b in w], "DXY")
                    dxy_regime = forex.get_dxy_regime()

        # 1) Açık pozisyonları yönet (her iki defter + gölge defterler)
        # Chandelier yalnız NEW ve gölge defterlerde; OLD tarihi sabit pip trail kullanır
        # DCA kitabı: katman tetiği + sepet eşikleri, bireysel yönetimden ÖNCE (bar kapanışı)
        chand = TUN_CHANDLIER
        for book in books.values():
            if TUN_DCA and book.name == "NEW":
                manage_dca_groups(book, by_ts, ts, data, cursors, idx)
            manage_book(book, by_ts, ts, chandelier_mult=(chand if book.name == "NEW" else 0.0),
                        tp_mode=(TUN_TP_MODE if book.name == "NEW" else "tp"),
                        exit_maps=(exit_maps if book.name == "NEW" else None))
        for sh in shadow_book.values():
            manage_book(sh["book"], by_ts, ts, chandelier_mult=chand, exit_maps=exit_maps)

        # Seri-SL sayacını taze kapanışlarla güncelle (giriş kapısı aynı barı görür)
        if TUN_LOSS_STREAK > 0:
            while streak_seen["NEW"] < len(books["NEW"].closed):
                t_close = books["NEW"].closed[streak_seen["NEW"]]
                streak_seen["NEW"] += 1
                sym_c = t_close["symbol"]
                new_streak, tripped = loss_streak_on_close(
                    loss_streak.get(sym_c, 0),
                    "SL_HIT" if t_close["reason"] == "SL" else t_close["reason"],
                    float(t_close.get("pnl_usd", 0.0)),
                    TUN_LOSS_STREAK)
                loss_streak[sym_c] = new_streak
                if tripped:
                    loss_cd_until[sym_c] = ts + TUN_LOSS_STREAK_CD

        # Özkaynak örnekleme (NEW): kapanmış kâr + açık pozisyonların işaret fiyatıyla floating PnL
        if idx >= warmup:
            eq_ts.append(ts)
            eq_new.append(books["NEW"].balance + sum(
                float_pnl(p, last_close.get(p.symbol, p.entry_price)) for p in books["NEW"].positions))

        # 2) Korelasyon matrisi (periyodik)
        if idx % CORR_REFRESH_EVERY == 0:
            for s in symbols:
                ci = cursors[s]
                closes_cache[s] = [b[4] for b in data[s][max(0, ci - 250):ci]]
            try:
                corr.maybe_refresh(closes_cache, interval_sec=0)
            except Exception:
                pass

        # 3) Aday üretimi + kapılar (her iki varyant) — yalnız taze barı ve işlem penceresi içinde
        in_window = (entry_start_ts is None or ts >= entry_start_ts) and (entry_end_ts is None or ts < entry_end_ts)
        candidates: Dict[str, List[Dict]] = {"OLD": [], "NEW": []}
        blocked_events: List[Tuple[str, Dict]] = []

        for sym in symbols:
            if not in_window or not fresh[sym]:
                continue
            bars = data[sym]
            ci = cursors[sym]
            window = bars[max(0, ci - INDICATOR_WINDOW):ci]
            if len(window) < 30:
                continue
            closes = [b[4] for b in window]
            highs = [b[2] for b in window]
            lows = [b[3] for b in window]
            opens = [b[1] for b in window]
            item = next((i for i in forex.FOREX_SYMBOLS if i["symbol"] == sym), None)
            item = item or REPLAY_SYMBOL_DEFS.get(sym)
            pip_size = item["pip_size"] if item else 0.0001
            spread_pips = CATEGORY_SPREAD_PIPS.get(item["category"] if item else "index", 3.0)
            if sym in SPREAD_PROFILE:
                spread_pips = float(SPREAD_PROFILE[sym])  # gerçek spread profili (max_spread kapısı da buna tabi — bilinçli)
            is_commodity = ("XAU" in sym or "GOLD" in sym or "OIL" in sym)
            is_fx_major = sym in FX_MAJORS
            if sym == "BTCUSD" and TUN_BTC_MIN_SCORE > 0:
                base_req = TUN_BTC_MIN_SCORE
            elif is_commodity:
                base_req = 78.0
            elif is_fx_major and TUN_FX_MIN_SCORE > 0:
                base_req = TUN_FX_MIN_SCORE
            else:
                base_req = TUN_MIN_SCORE
            max_spread = 20.0 if ("BTC" in sym or "ETH" in sym) else 3.0
            close_now = closes[-1]

            for vname in ("OLD", "NEW"):
                book = books[vname]
                tech = forex._compute_technical_indicators(closes, highs, lows, opens, sym,
                                                           include_momentum=(vname == "NEW"))
                if not tech:
                    continue
                mode_exits: Optional[Dict[str, float]] = None
                mode_applies = (TUN_ENTRY_MODE != "classic" and vname == "NEW"
                                and (not MODE_SYMBOLS or sym in MODE_SYMBOLS))
                if not mode_applies:
                    action = tech.get("action")
                    if action not in ("BUY", "SELL"):
                        continue
                    score = float(tech["score"])
                else:
                    # Alternatif giriş algoritması (giriş-kalibrasyonu projesi): mod kendi
                    # tetik şartını üretir; kapılar ve çıkış motoru klasikle BİREBİR aynıdır.
                    # MODE_SYMBOLS verilmişse mod yalnız o sembollere uygulanır (ör. XAU/BTC
                    # klasik kalsın, yeni mod yalnız denenen çiftlerde).
                    mode_c = _entry_mode_candidate(sym, ts, bars, ci, tech, pip_size)
                    if mode_c is None:
                        continue
                    action = mode_c["action"]
                    score = 200.0            # skor kapısını otomatik geç (mod kendi şartıyla süzülür)
                    mode_exits = mode_c.get("exits")
                atr_pips = tech["atr"] / pip_size if pip_size > 0 else 15.0
                spec = forex.get_symbol_trading_specs(sym, atr_pips=atr_pips)

                def cand(gate_note: Optional[str] = None) -> Dict:
                    return {
                        "symbol": sym, "action": action, "score": score, "price": close_now,
                        "atr_pips": atr_pips, "pip_size": pip_size, "pip_val": spec["pip_val"],
                        "digits": spec["digits"], "spread_pips": spread_pips, "gate": gate_note,
                        "exits": mode_exits,
                    }

                # ---- Kapı zinciri (NEW: yeni kapılar da devrede; OLD: yalnız ortak kapılar) ----
                if vname == "NEW" and EV_GUARD:
                    ev_rows = [c["pnl_usd"] for c in book.closed
                               if c["symbol"] == sym and c.get("closed_ts", 0.0) >= ts - EV_WINDOW_SEC]
                    ev_stats = {
                        "n": len(ev_rows),
                        "net": round(sum(ev_rows), 2),
                        "win_rate": round(100.0 * sum(1 for p in ev_rows if p >= 0) / len(ev_rows), 1) if ev_rows else 0.0,
                    }
                    ev_risk_floor = BALANCE * RISK_PCT / 100.0 * EV_LOSS_RISK_MULT
                    if forex.ev_guard_decision(ev_stats, EV_MIN_TRADES, EV_MAX_WIN_RATE, ev_risk_floor):
                        blocked_events.append(("EV", cand("EV")))
                        continue
                if vname == "NEW" and BLOCKED_HOURS and forex.is_entry_hour_blocked(hour, BLOCKED_HOURS):
                    blocked_events.append(("SAAT", cand("SAAT")))
                    continue
                if vname == "NEW":
                    veto = forex.dxy_entry_veto(sym, action, dxy_regime)
                    if veto == "dxy_conflict":
                        if TUN_GOLD_DXY_SOFT and ("XAU" in sym or "GOLD" in sym):
                            # XAUUSD: sert veto yerine ekstra skor eşiği (kategori bazlı yumuşatma)
                            weak_bump = TUN_GOLD_DXY_BUMP
                        else:
                            blocked_events.append(("DXY", cand("DXY")))
                            continue
                    else:
                        weak_bump = 5.0 if veto == "dxy_strict_neutral" else 0.0
                else:
                    weak_bump = 0.0
                # 5c. Majör güçlendirme kapıları (2026-10-06 araştırma mekanizmaları, yalnız NEW):
                # Asya seansı chop'u, ölü piyasa ve kovalama (EMA21 uzaması) girişleri eler.
                # --gate-extras ile eklenen adaylar, --gold-session ile altın da kapsanır.
                _gate_syms = sym in FX_MAJORS or sym in GATED_EXTRAS or (TUN_GOLD_SESSION and ("XAU" in sym or "GOLD" in sym))
                _ext_syms = _gate_syms or (TUN_EXT_GATE_XG and ("XAU" in sym or "GOLD" in sym or "BTC" in sym))
                if vname == "NEW" and _gate_syms:
                    if TUN_MAJOR_HOURS and not (TUN_MAJOR_HOURS[0] <= hour < TUN_MAJOR_HOURS[1]):
                        blocked_events.append(("SEANS", cand("SEANS")))
                        continue
                    if TUN_MAJOR_MIN_ATR > 0 and atr_pips < TUN_MAJOR_MIN_ATR:
                        blocked_events.append(("VOLATİLİTE", cand("VOLATİLİTE")))
                        continue
                if vname == "NEW" and _ext_syms and TUN_MAJOR_MAX_EXT > 0 and float(tech.get("ema21", 0.0)) > 0 and atr_pips > 0:
                    ext_atr = ((close_now - float(tech["ema21"])) if action == "BUY"
                               else (float(tech["ema21"]) - close_now)) / (atr_pips * pip_size)
                    if ext_atr > TUN_MAJOR_MAX_EXT:
                        blocked_events.append(("UZAMA", cand("UZAMA")))
                        continue
                # 5d. BTC rejim kapıları (yalnız NEW): yapısal EMA200(1h) ve günlük VWAP yön hizası
                if vname == "NEW" and sym == "BTCUSD":
                    if TUN_BTC_EMA200:
                        ema_val = btc_ema200_by_hour.get(int(ts // 3600) - 1)
                        if ema_val is not None and ((action == "BUY" and close_now <= ema_val) or (action == "SELL" and close_now >= ema_val)):
                            blocked_events.append(("REJIM", cand("REJIM")))
                            continue
                    if TUN_BTC_VWAP:
                        vw = btc_vwap_by_ts.get(ts)
                        if vw is not None and ((action == "BUY" and close_now <= vw) or (action == "SELL" and close_now >= vw)):
                            blocked_events.append(("VWAP", cand("VWAP")))
                            continue
                # 5e. ABD endeks kapıları (yalnız NEW): seans likidite penceresi + açılış sürüşü teyidi
                if vname == "NEW" and sym in INDEX_GATED:
                    if TUN_INDEX_HOURS is not None:
                        dt_min = hour * 60 + datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).minute
                        if not (TUN_INDEX_HOURS[0] <= dt_min < TUN_INDEX_HOURS[1]):
                            blocked_events.append(("ISEANS", cand("ISEANS")))
                            continue
                    if TUN_INDEX_OPEN_DRIVE:
                        day_mod = int(ts % 86400)
                        if 48900 <= day_mod < 54000:  # 13:35-15:00 UTC — açılış penceresi
                            odir = open_drive_dir.get((sym, int(ts // 86400)))
                            if odir and ((action == "BUY" and odir < 0) or (action == "SELL" and odir > 0)):
                                blocked_events.append(("ACILIS", cand("ACILIS")))
                                continue
                if spread_pips > max_spread:
                    continue  # ortak kapı — gölge izlenmez
                req = base_req + weak_bump
                if score < req:
                    continue  # SKOR — sinyal taban eşiği, gölge izlenmez
                if vname == "NEW" and TUN_ADX_MIN > 0 and float(tech.get("adx", 25.0)) < TUN_ADX_MIN:
                    blocked_events.append(("ADX", cand("ADX")))
                    continue
                if vname == "NEW" and TUN_ST_FILTER:
                    st_dir = int(tech.get("supertrend_dir", 0))
                    if st_dir != 0 and ((action == "BUY" and st_dir < 0) or (action == "SELL" and st_dir > 0)):
                        blocked_events.append(("SUPERTREND", cand("SUPERTREND")))
                        continue
                # "Trend bitti" dedektör kapıları (yalnız NEW):
                # HTF  — 15M SuperTrend yönü tersse 5M sıçraması sayaç-trend girişidir
                if vname == "NEW" and TUN_HTF_ALIGN:
                    d15 = htf_maps.get(sym, {}).get(int(ts // 900), 0)
                    if d15 != 0 and ((action == "BUY" and d15 < 0) or (action == "SELL" and d15 > 0)):
                        blocked_events.append(("HTF", cand("HTF")))
                        continue
                # IRAD — fiyat zirve/dibi yenilerken RSI teyit etmiyorsa (uyumsuzluk = tükenme)
                if vname == "NEW" and TUN_DIV_GATE > 0:
                    div = div_maps.get(sym, {}).get(ts, 0)
                    if (action == "BUY" and div == 1) or (action == "SELL" and div == -1):
                        blocked_events.append(("IRAD", cand("IRAD")))
                        continue
                # SERI — sembol ardışık tam-SL kayıplarından sonra kısa süre yeni giriş almaz
                if vname == "NEW" and TUN_LOSS_STREAK > 0 and ts < loss_cd_until.get(sym, 0.0):
                    blocked_events.append(("SERI", cand("SERI")))
                    continue
                bias = forex.get_usd_bias(sym, action)
                if vname == "NEW" and bias != "USD_NEUTRAL":
                    pos_biases = [(p.symbol, forex.get_usd_bias(p.symbol, p.direction)) for p in book.positions]
                    ok, _r = corr.cluster_check(sym, bias, pos_biases)
                    if not ok:
                        blocked_events.append(("KORELASYON", cand("KORELASYON")))
                        continue
                same_dir = [p for p in book.positions if p.symbol == sym and p.direction == action]
                if len(same_dir) >= MAX_PER_SYMBOL_DIR:
                    continue
                if same_dir:
                    # YAS — trend yaşlandıysa (5M ST flip'ten beri N bar geçtiyse) aynı yöne
                    # piramit yok; ilk giriş serbest. (Kayıp kümeleri tepedeki yığılmalardandı.)
                    if vname == "NEW" and TUN_PYR_AGE_MAX > 0:
                        d5, age5 = st_age_maps.get(sym, {}).get(ts, (0, 0))
                        if d5 != 0 and d5 == (1 if action == "BUY" else -1) and age5 > TUN_PYR_AGE_MAX:
                            blocked_events.append(("YAS", cand("YAS")))
                            continue
                    if TUN_DCA and vname == "NEW":
                        continue  # DCA: aynı yönde ek işlem yalnız katman mekanizmasından (kâr şartlı pyramid kapalı)
                    dir_pnl = sum(p.partial_realized_usd + float_pnl(p, close_now) for p in same_dir)
                    if dir_pnl < PYRAMID_MIN_PROFIT_USD:
                        continue
                if (sym, action) in last_entry_bar and idx - last_entry_bar[(sym, action)] < 1:
                    continue
                candidates[vname].append(cand())

        # 4) Skor sırasına göre açılış (eski USD-yön sayacı kaldırıldı — korelasyon kalkanı koruyor)
        for vname, book in books.items():
            opened = 0
            for cand_d in sorted(candidates[vname], key=lambda x: -x["score"]):
                if len(book.positions) >= MAX_OPEN_POSITIONS or opened >= TRADES_PER_BAR_CAP:
                    break
                spec = forex.get_symbol_trading_specs(cand_d["symbol"], atr_pips=cand_d["atr_pips"])
                if vname == "NEW":
                    mx = cand_d.get("exits")
                    if mx:
                        # Giriş-modu çıkışları: modun kendi SL/TP'si (ATR çıkış motoru devre dışı)
                        sl_pips, tp_pips, partial = mx["sl_pips"], mx["tp_pips"], 0.0
                    else:
                        sl_mult_eff = TUN_SL_ATR_MULT
                        if TUN_CRYPTO_SL_MULT > 0 and ("BTC" in cand_d["symbol"] or "ETH" in cand_d["symbol"]):
                            sl_mult_eff = TUN_CRYPTO_SL_MULT
                        levels = forex.get_atr_exit_levels(
                            cand_d["atr_pips"], spec["sl_pips"], spec["tp_pips"],
                            sl_atr_mult=sl_mult_eff, tp_atr_mult=TUN_TP_ATR_MULT, rr_floor=TUN_RR_FLOOR)
                        sl_pips, tp_pips = levels["sl_pips"], levels["tp_pips"]
                        partial = levels["first_target_pips"]
                else:
                    sl_pips, tp_pips, partial = spec["sl_pips"], spec["tp_pips"], 0.0
                pos = open_position(cand_d, sl_pips, tp_pips, partial, idx)
                if pos is None:
                    continue  # Risk kalkanı: en küçük mümkün lot bile sert risk sınırını aşıyor
                book.positions.append(pos)
                last_entry_bar[(cand_d["symbol"], cand_d["action"])] = idx
                opened += 1

        # 5) Gölge defterler: NEW'in yeni kapılarının reddettikleri (cap'li)
        for gate, cand_d in blocked_events:
            if gate not in SHADOW_GATES:
                continue
            sh = shadow_book.setdefault(gate, {"book": Book(f"SHADOW-{gate}"), "blocked": 0})
            sh["blocked"] += 1
            if len(sh["book"].positions) >= SHADOW_MAX_CONCURRENT:
                continue
            spec = forex.get_symbol_trading_specs(cand_d["symbol"], atr_pips=cand_d["atr_pips"])
            levels = forex.get_atr_exit_levels(
                cand_d["atr_pips"], spec["sl_pips"], spec["tp_pips"],
                sl_atr_mult=TUN_SL_ATR_MULT, tp_atr_mult=TUN_TP_ATR_MULT, rr_floor=TUN_RR_FLOOR)
            spos = open_position(cand_d, levels["sl_pips"], levels["tp_pips"], levels["first_target_pips"], idx)
            if spos is not None:
                sh["book"].positions.append(spos)

        if idx % 300 == 0:
            print(f"  ... bar {idx}/{len(common_ts)} | OLD: {len(books['OLD'].closed)} işlem ${books['OLD'].balance:+.2f} | "
                  f"NEW: {len(books['NEW'].closed)} işlem ${books['NEW'].balance:+.2f}")

    # 6) Kalan pozisyonları kapat — pencere tanımlıysa pencere içi son bar fiyatıyla
    for book in list(books.values()) + [sh["book"] for sh in shadow_book.values()]:
        for pos in list(book.positions):
            bars_sym = data[pos.symbol]
            last_bar = bars_sym[-1]
            if entry_end_ts is not None:
                for b in reversed(bars_sym):
                    if b[0] < entry_end_ts:
                        last_bar = b
                        break
            reason = "EOM" if entry_end_ts is None else "HAFTA_KAPANIS"
            close_position(book, pos, reason, last_bar[4], closed_ts=last_bar[0])
        book.positions = []

    if orig_dxy is not None:
        forex._TECHNICAL_CACHE["DXY"] = orig_dxy
    else:
        forex._TECHNICAL_CACHE.pop("DXY", None)

    report: Dict[str, Any] = {"days": days, "bars": len(common_ts), "variants": {}, "gate_attribution": {}}
    if entry_start_ts or entry_end_ts:
        report["entry_window"] = {
            "start_ts": entry_start_ts,
            "end_ts": entry_end_ts,
            "start": datetime.datetime.fromtimestamp(entry_start_ts, datetime.timezone.utc).isoformat() if entry_start_ts else None,
            "end": datetime.datetime.fromtimestamp(entry_end_ts, datetime.timezone.utc).isoformat() if entry_end_ts else None,
        }
    for vname, book in books.items():
        wins = sum(1 for t in book.closed if t["pnl_usd"] >= 0)
        n = len(book.closed)
        gross_profit = sum(t["pnl_usd"] for t in book.closed if t["pnl_usd"] >= 0)
        gross_loss = abs(sum(t["pnl_usd"] for t in book.closed if t["pnl_usd"] < 0))
        pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        daily: Dict[str, float] = {}
        for t in book.closed:
            if not t.get("closed_ts"):
                continue
            d = datetime.datetime.fromtimestamp(t["closed_ts"], datetime.timezone.utc).strftime("%Y-%m-%d")
            daily[d] = round(daily.get(d, 0.0) + t["pnl_usd"], 2)
        var = {
            "trades": n,
            "win_rate": round(100 * wins / n, 1) if n else 0.0,
            "net_pnl_usd": round(book.realized, 2),
            "avg_pnl_usd": round(book.realized / n, 3) if n else 0.0,
            "profit_factor": pf,
            "balance": book.balance,
            "per_symbol": book.per_symbol,
            "daily_pnl": dict(sorted(daily.items())),
        }
        by_reason: Dict[str, Dict[str, float]] = {}
        for t in book.closed:
            r = "TRAIL" if t.get("trail") else str(t["reason"])
            st_r = by_reason.setdefault(r, {"n": 0, "pnl_usd": 0.0})
            st_r["n"] = int(st_r["n"]) + 1
            st_r["pnl_usd"] = round(st_r["pnl_usd"] + t["pnl_usd"], 2)
        var["exit_reasons"] = by_reason
        if vname == "NEW" and eq_new:
            peak = eq_new[0]
            max_dd = 0.0
            for e in eq_new:
                peak = max(peak, e)
                max_dd = max(max_dd, peak - e)
            var["max_drawdown_usd"] = round(max_dd, 2)
            var["equity_start"] = round(eq_new[0], 2)
            var["equity_end"] = round(eq_new[-1], 2)
        report["variants"][vname] = var
    for gate, sh in shadow_book.items():
        n = len(sh["book"].closed)
        pnl = round(sum(c["pnl_usd"] for c in sh["book"].closed), 2)
        wins = sum(1 for c in sh["book"].closed if c["pnl_usd"] >= 0)
        report["gate_attribution"][gate] = {
            "blocked": sh["blocked"],
            "shadow_trades": n,
            "shadow_win_rate": round(100 * wins / n, 1) if n else 0.0,
            "shadow_pnl_usd": pnl,
        }
    return report


def fetch_btc_volume_map(days: int = 32) -> Dict[float, float]:
    """Yahoo BTC-USD 5m hacim serisi (ts -> volume) — VWAP kapısı için; disk önbellekli."""
    cache = os.path.join(ROOT, "outputs", f"btc_volume_{days}d.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return {float(k): float(v) for k, v in json.load(f).items()}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=5m&range={days}d"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    ts = res.get("timestamp", [])
    vol = q.get("volume", [])
    out = {float(ts[i]): float(vol[i]) for i in range(min(len(ts), len(vol))) if vol[i] is not None}
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def _load_btc_volume_map() -> Dict[float, float]:
    try:
        return fetch_btc_volume_map(32)
    except Exception as exc:
        print(f"[UYARI] BTC hacim verisi alınamadı — VWAP kapısı etksiz: {exc}")
        return {}


def _bar_index_at_or_before(bars: List[Tuple], ts: float) -> Optional[int]:
    lo, hi = 0, len(bars) - 1
    if not bars or bars[0][0] > ts:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if bars[mid][0] <= ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


def main():
    global TUN_MIN_SCORE, TUN_SL_ATR_MULT, TUN_TP_ATR_MULT, TUN_RR_FLOOR, TUN_HEADROOM_FOREX
    global TUN_ADX_MIN, TUN_ST_FILTER, BLOCKED_HOURS, EV_GUARD
    global TUN_FX_MIN_SCORE, TUN_GOLD_DXY_SOFT, TUN_GOLD_DXY_BUMP, EV_WINDOW_SEC, EV_MAX_WIN_RATE
    global TUN_CHANDLIER, TUN_MAJOR_HOURS, TUN_MAJOR_MIN_ATR, TUN_MAJOR_MAX_EXT, GATED_EXTRAS
    global TUN_GOLD_SESSION, TUN_BTC_EMA200, TUN_BTC_VWAP, TUN_CRYPTO_SL_MULT, TUN_BTC_MIN_SCORE, TUN_TP_MODE
    global TUN_GOLD_VOL_EXITS, TUN_VOL_BE_MULT, TUN_VOL_TRAIL_MULT, TUN_VOL_TRAIL_FLOOR
    global TUN_BE_USD_GOLD, TUN_BE_RATIO_GOLD, TUN_BE_PIP_FIXED_GOLD
    global TUN_INDEX_HOURS, TUN_INDEX_OPEN_DRIVE
    global TUN_DCA, TUN_DCA_DIST_FRAC, TUN_DCA_LOT_MULT, TUN_DCA_TP_USD, TUN_DCA_SL_USD
    global TUN_DCA_BUFFER_USD, TUN_DCA_LEVEL_CHECK, TUN_DCA_LEVEL_TOL_ATR
    global TUN_DCA_MAX_LAYERS, TUN_DCA_DIST_STEP
    global RSI2_ENABLED, RSI2_ENTRY, RSI2_EXIT, FADE_ENABLED, FADE_K_ATR, FADE_EARLY_ONLY
    parser = argparse.ArgumentParser(description="Forex replay A/B (eski vs yeni algoritma)")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--cache", default="")
    parser.add_argument("--out", default=os.path.join(ROOT, "outputs", "forex_replay_7d_report.json"))
    parser.add_argument("--window", choices=["full", "recent", "prior"], default="full",
                        help="recent: son 7 gün (in-sample) | prior: önceki 7 gün (out-of-sample)")
    parser.add_argument("--start", default="", help="Giriş penceresi başlangıcı (YYYY-MM-DD, UTC) — window'u geçersiz kılar")
    parser.add_argument("--end", default="", help="Giriş penceresi sonu, dahil değil (YYYY-MM-DD, UTC)")
    parser.add_argument("--symbols", default="", help="Virgüllü sembol filtresi (örn: XAUUSD,US30,NAS100) — yalnız bu semboller işlenir")
    parser.add_argument("--add-symbols", default="", help="Virgüllü ek aday semboller (örn: XAGUSD,USOIL,GBPJPY) — izin listesine EKLENİR (test-only)")
    parser.add_argument("--exclude-symbols", default="", help="Virgüllü hariç tutulacak semboller (örn: XAUUSD,BTCUSD) — izole FX defteri için")
    parser.add_argument("--spread-profile", default="", help="JSON spread profili: sembol başına gerçek spread (pip); örn outputs/fx_spread_reality.json")
    parser.add_argument("--interval", default="5m", help="Bar zaman dilimi (5m / 15m — Aşama 3 merdiven testi; 15m'de HTF ≈ 45m olur)")
    parser.add_argument("--entry-mode", default="classic", choices=["classic", "london_breakout", "pullback", "donchian_adx", "donchian_pure", "squeeze", "nr7", "orb_ny"], help="Giriş algoritması: classic = mevcut skor sistemi; diğerleri giriş-kalibrasyonu araştırma adayları")
    parser.add_argument("--lb-box-end", type=int, default=7, help="London breakout kutu bitiş saati (UTC)")
    parser.add_argument("--lb-entry-end", type=int, default=11, help="London breakout tetik penceresi bitiş saati (UTC)")
    parser.add_argument("--lb-sl-frac", type=float, default=0.5, help="LB SL = kutu yüksekliği × bu oran")
    parser.add_argument("--lb-tp-r", type=float, default=1.5, help="LB TP = SL × bu R katı")
    parser.add_argument("--lb-min-box-atr", type=float, default=0.0, help="Min kutu yüksekliği (×ATR; 0 = kapalı)")
    parser.add_argument("--pb-adx-min", type=float, default=20.0, help="Pullback modu ADX eşiği")
    parser.add_argument("--da-adx-min", type=float, default=18.0, help="Donchian+ADX modu ADX eşiği")
    parser.add_argument("--da-sl-atr", type=float, default=2.0, help="Donchian+ADX modu SL (× ATR)")
    parser.add_argument("--da-tp-atr", type=float, default=4.0, help="Donchian+ADX modu TP (× ATR)")
    parser.add_argument("--mode-sl-atr", type=float, default=2.0, help="Yeni modlar (donchian_pure/squeeze/nr7) SL (× ATR)")
    parser.add_argument("--mode-tp-atr", type=float, default=0.0, help="Yeni modlar TP (× ATR; 0 = sabit TP yok → --chandelier trailing çıkar)")
    parser.add_argument("--squeeze-bb-pct", type=float, default=20.0, help="Squeeze modu: bandwidth persentil eşiği (alt = sıkışma)")
    parser.add_argument("--squeeze-bb-period", type=int, default=20, help="Squeeze modu Bollinger periyodu")
    parser.add_argument("--nr7-n", type=int, default=7, help="NR7 modu: en dar aralık penceresi (bar)")
    parser.add_argument("--nr7-adx-min", type=float, default=18.0, help="NR7 modu ADX eşiği (0 = kapalı)")
    parser.add_argument("--orb-box-start", type=int, default=7, help="ORB kutusu başlangıç saati UTC (London)")
    parser.add_argument("--orb-box-end", type=int, default=13, help="ORB kutusu bitiş saati UTC")
    parser.add_argument("--orb-entry-start", type=int, default=13, help="ORB tetik penceresi başlangıç saati UTC")
    parser.add_argument("--orb-entry-end", type=int, default=16, help="ORB tetik penceresi bitiş saati UTC")
    parser.add_argument("--orb-min-atr", type=float, default=0.0, help="ORB kutu yüksekliği / ATR alt sınırı (0 = kapalı)")
    parser.add_argument("--orb-max-atr", type=float, default=0.0, help="ORB kutu yüksekliği / ATR üst sınırı (0 = kapalı)")
    parser.add_argument("--orb-sl-frac", type=float, default=0.5, help="ORB SL = kutu yüksekliği × bu oran")
    parser.add_argument("--orb-tp-r", type=float, default=1.5, help="ORB TP = SL × bu R katı")
    parser.add_argument("--flat-16", action="store_true", help="16:00 UTC'de FX pozisyonlarını zorla kapat (araştırma: NY öğleden sonrası negatif) — yalnız FX çiftleri")
    parser.add_argument("--mode-symbols", default="", help="Giriş modunun uygulanacağı semboller (virgüllü; boş = tümüne). Diğer semboller classic motorla kalır — ör. XAU/BTC bozulmadan yalnız denenen çiftlerde mod")
    parser.add_argument("--gate-extras", default="", help="Virgüllü: --add-symbols ile eklenen sembollerden majör kapılarına (seans+minATR) tabi tutulacaklar")
    parser.add_argument("--min-score", type=float, default=75.0)
    parser.add_argument("--sl-mult", type=float, default=1.1)
    parser.add_argument("--tp-mult", type=float, default=1.4)
    parser.add_argument("--rr-floor", type=float, default=1.5)
    parser.add_argument("--headroom", type=float, default=3.5)
    parser.add_argument("--adx-min", type=float, default=0.0, help="ADX eşiği (0 = kapalı)")
    parser.add_argument("--st-filter", action="store_true", help="SuperTrend yön teyidini aç")
    parser.add_argument("--hours", default="", help="Engellenecek UTC saatleri, virgüllü (örn 5,15)")
    parser.add_argument("--no-ev-guard", action="store_true", help="Sembol EV kalkanını kapat")
    parser.add_argument("--fx-min-score", type=float, default=0.0, help="FX majörleri için ayrı skor eşiği (0 = min_score ile aynı)")
    parser.add_argument("--gold-dxy-soft", action="store_true", help="(Eski) XAUUSD DXY vetosunu +skora indirmek için — canlıda artık XAUUSD tamamen muaf, etki etmez")
    parser.add_argument("--gold-dxy-bump", type=float, default=5.0, help="XAUUSD DXY yumuşatma ekstra skoru")
    parser.add_argument("--ev-window", type=float, default=24.0, help="EV kalkanı bakış penceresi (saat)")
    parser.add_argument("--ev-wr", type=float, default=45.0, help="EV kronik kayıp WR eşiği (%%) — canlı default 45")
    parser.add_argument("--st-period", type=int, default=10, help="SuperTrend period (canlı default 10)")
    parser.add_argument("--st-mult", type=float, default=3.0, help="SuperTrend ATR çarpanı (canlı default 3.0)")
    parser.add_argument("--wilder-atr", action="store_true", help="#15: ATR'yi Wilder yumuşatmasıyla hesapla (ARTIK VARSAYILAN; geriye dönük uyumluluk için duruyor)")
    parser.add_argument("--plain-atr", action="store_true", help="#15 A/B kolu: eski düz 14-ortalama ATR davranışına dön")
    parser.add_argument("--gold-session", action="store_true", help="Altın için de majör seans penceresini uygula (7-20 UTC)")
    parser.add_argument("--btc-ema200", action="store_true", help="BTC girişlerine EMA200(1h) rejim kapısı")
    parser.add_argument("--btc-vwap", action="store_true", help="BTC girişlerine günlük VWAP kapısı (hacim verisi çeker)")
    parser.add_argument("--crypto-sl-mult", type=float, default=0.0, help="Kripto özel SL ATR çarpanı (0 = global)")
    parser.add_argument("--btc-min-score", type=float, default=0.0, help="BTC özel skor eşiği (0 = global min_score)")
    parser.add_argument("--no-tp-on-trail", action="store_true", help="Trailing aktiflenince sabit TP emri çekilir — muhafazakâr model (aktifleşen barda TP geçerli)")
    parser.add_argument("--no-tp-on-trail-live", action="store_true", help="Trailing aktiflenince TP çekilir — canlıya yakın model (aktifleşen barda da geçersiz; MODIFY_SLTP saniyeler içinde etkili olur)")
    parser.add_argument("--no-tp-crypto", action="store_true", help="TP yalnız BTC/ETH'de kapalı")
    parser.add_argument("--no-tp", action="store_true", help="Sabit TP tamamen kapalı (aşırı uç kontrolü)")
    parser.add_argument("--gold-vol-exits", action="store_true", help="Altında BE tetiği ve trailing mesafesi giriş-ATR'ine göre ölçeklenir")
    parser.add_argument("--vol-be-mult", type=float, default=0.8, help="BE tetik tabanı çarpanı (× giriş-ATR, pip)")
    parser.add_argument("--vol-trail-mult", type=float, default=1.5, help="Trailing mesafe çarpanı (× giriş-ATR, pip)")
    parser.add_argument("--vol-trail-floor", type=float, default=40.0, help="Trailing alt sınırı (pip); düşük değer oransal-sıkı moda izin verir")
    parser.add_argument("--be-usd-gold", type=float, default=1.0, help="Altın BE dolar tabanı (garantili kilit $)")
    parser.add_argument("--be-ratio-gold", type=float, default=0.40, help="Altın BE anında kilitlenen kâr oranı")
    parser.add_argument("--be-pip-fixed-gold", type=float, default=0.0, help="Altın BE'yi lot-bağımsız sabit pip'e bağla (0 = kapalı)")
    parser.add_argument("--dca", action="store_true", help="Kademeli alım + sepet kapatma: zarardaki işlemde dist-frac mesafede lot-mult katmanı; sepet TP/SL/BE eşikleri")
    parser.add_argument("--dca-dist-frac", type=float, default=0.5, help="Katman tetiği: giriş-SL mesafesinin bu oranında (0.5 = yarı)")
    parser.add_argument("--dca-lot-mult", type=float, default=2.0, help="Katman lotu = ilk pozisyon lotu × çarpan")
    parser.add_argument("--dca-tp-usd", type=float, default=4.0, help="Sepet TP: toplam kâr ≥ bu ($) → hepsi kapanır")
    parser.add_argument("--dca-sl-usd", type=float, default=10.0, help="Sepet SL: toplam zarar ≤ -bu ($) → hepsi kapanır")
    parser.add_argument("--dca-buffer-usd", type=float, default=1.0, help="Sepet BE kilidi tamponu ($)")
    parser.add_argument("--dca-level-check", action="store_true", help="Katman tetiğinde S/R+Fibo seviye onayı (±tol×ATR komşuluk)")
    parser.add_argument("--dca-level-tol-atr", type=float, default=0.25, help="Seviye onayı toleransı (× ATR)")
    parser.add_argument("--dca-max-layers", type=int, default=1, help="Pozisyon başına en fazla katman (3 = lead + 3 katman)")
    parser.add_argument("--dca-dist-step", type=float, default=0.0, help="Katman tetiği derinleşme adımı (× sl0; tetikler frac, frac+step, ...)")
    parser.add_argument("--dxy-exempt-extra", default="", help="DXY vetosundan muaf tutulacak ek sembol parçaları (virgüllü, test için — canlı DXY_EXEMPT_SYMBOLS'a dokunmaz)")
    parser.add_argument("--index-hours", default="", help="ABD endeksleri (NAS100/US30) giriş penceresi '1330-2000' UTC dakika (boş = kapalı)")
    parser.add_argument("--index-open-drive", action="store_true", help="ABD açılış ilk 5m mumu yönü 13:35-15:00 arası yön teyidi zorunlu")
    parser.add_argument("--mini-only", action="store_true", help="Ana replay'i atla; yalnız mini-motorları koş (hızlı test)")
    parser.add_argument("--rsi2", action="store_true", help="Connors RSI(2) mini-motorunu koş (NAS100/US30)")
    parser.add_argument("--rsi2-entry", type=float, default=10.0, help="RSI(2) giriş eşiği (long)")
    parser.add_argument("--rsi2-exit", type=float, default=65.0, help="RSI(2) çıkış eşiği (long)")
    parser.add_argument("--fade", action="store_true", help="Seans-çapa fade mini-motorunu koş (NAS100/US30)")
    parser.add_argument("--fade-k-atr", type=float, default=2.0, help="Fade sapma eşiği (× ATR)")
    parser.add_argument("--fade-early-only", action="store_true", help="Fade girişleri yalnız ilk 2 saat (13:30-15:30 UTC)")
    parser.add_argument("--chandelier", type=float, default=0.0, help="MFE−ATR chandelier trailing çarpanı (0 = sabit pip trail; scalping için ~2.0)")
    parser.add_argument("--st-flip-exit", action="store_true", help="Açık pozisyonda 5M SuperTrend yönü ters dönünce bar kapanışında kapat (MOMFLIP — erken trend-dönüş çıkışı)")
    parser.add_argument("--st-flip-min-pnl", type=float, default=0.0, help="MOMFLIP yalnız pnl(pip) ≥ eşikken uygulansın (0 = zarardayken de erken kes)")
    parser.add_argument("--st-exit-period", type=int, default=10, help="MOMFLIP çıkış SuperTrend periyodu (canlı sinyal ST: 10)")
    parser.add_argument("--st-exit-mult", type=float, default=3.0, help="MOMFLIP çıkış SuperTrend ATR çarpanı (canlı sinyal ST: 3.0)")
    parser.add_argument("--ema-flip-exit", action="store_true", help="EMA9/EMA21 çaprazı pozisyona karşı + kapanış EMA21 ötesinde → kapat")
    parser.add_argument("--ext-gate-xg", action="store_true", help="XAU/BTC girişlerinde de EMA21 uzama kapısı (--major-max-ext ile eşik) — trend tepesinde yığılmayı önler")
    parser.add_argument("--st-flip-tighten", type=float, default=0.0, help="ST flip'te kapatma; kâr varsa stopu bu pip mesafeye sıkılaştır (0 = kapalı; MOMFLIP-close ile birlikte kullanma)")
    parser.add_argument("--htf-align", action="store_true", help="15M SuperTrend yönü tersse yeni giriş yok (sayaç-trend 5M sıçramalarını ele)")
    parser.add_argument("--div-gate", type=float, default=0.0, help="RSI(14) uyumsuzluk eşiği (0 = kapalı; ~4-6): fiyat zirve/dip yenilerken RSI teyit etmiyorsa giriş yok")
    parser.add_argument("--pyr-age-max", type=int, default=0, help="5M ST yaşı bu barı aşınca aynı yönde piramit yok (0 = kapalı; 24 bar = 2 saat)")
    parser.add_argument("--loss-streak", type=int, default=0, help="N ardışık tam-SL kaybında sembol yeni giriş almaz (0 = kapalı; kullanıcı önerisi: 3)")
    parser.add_argument("--loss-streak-cd", type=float, default=300.0, help="Seri-SL tetiklenince sembol soğuma penceresi (saniye; kullanıcı önerisi: 300)")
    parser.add_argument("--max-open", type=int, default=0, help="Maksimum açık pozisyon cap'i (0 = varsayılan 6; kullanıcı testi: 99 = slot rekabeti yok)")
    parser.add_argument("--spec-atr", action="store_true", help="Spec BE/Trail'i işlem-bazlı giriş ATR'siyle hesapla (motor-cmd hizalı köprü davranışı; kapalı = eski köprü ATR'siz)")
    parser.add_argument("--major-hours", default="7-20", help="Majörler için UTC saat penceresi '7-20' (canlı default 7-20; boş = kapalı)")
    parser.add_argument("--major-min-atr", type=float, default=4.0, help="Majörler minimum ATR(pips) tabanı (canlı default 4.0; 0 = kapalı)")
    parser.add_argument("--major-max-ext", type=float, default=0.0, help="Majörlerde EMA21'den maks. ATR-katı uzama — kovalamama (0 = kapalı)")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    # Spread profili (--spread-profile): {"symbols": {"EURUSD": {"avg_pips": 1.2, ...}, ...}} → {SYM: avg_pips}
    global SPREAD_PROFILE
    if args.spread_profile:
        _sp_path = args.spread_profile if os.path.isabs(args.spread_profile) else os.path.join(ROOT, args.spread_profile)
        if os.path.exists(_sp_path):
            try:
                with open(_sp_path, encoding="utf-8") as _sp_f:
                    _sp_raw = json.load(_sp_f)
                _sp_syms = _sp_raw.get("symbols", {}) if isinstance(_sp_raw, dict) else {}
                for _sp_sym, _sp_def in _sp_syms.items():
                    if isinstance(_sp_def, dict) and _sp_def.get("avg_pips") is not None:
                        SPREAD_PROFILE[str(_sp_sym).upper()] = float(_sp_def["avg_pips"])
                print(f"[KONFIG] Spread profili yüklendi: {args.spread_profile} ({len(SPREAD_PROFILE)} sembol)")
            except (ValueError, TypeError, OSError) as _sp_err:
                print(f"[UYARI] Spread profili yüklenemedi ({args.spread_profile}): {_sp_err} — kategori spread'leri kullanılacak")
        else:
            print(f"[UYARI] Spread profili bulunamadı: {args.spread_profile} — kategori spread'leri kullanılacak")

    # Zaman-dilimi merdiveni (Aşama 3): --interval 15m ile 15m bar üzerinde replay
    global FETCH_INTERVAL
    if args.interval and args.interval != FETCH_INTERVAL:
        FETCH_INTERVAL = args.interval
        print(f"[KONFIG] Bar zaman dilimi: {FETCH_INTERVAL}")

    global TUN_ENTRY_MODE, TUN_LB_BOX_END_H, TUN_LB_ENTRY_END_H, TUN_LB_SL_BOX_FRAC, TUN_LB_TP_R, TUN_LB_MIN_BOX_ATR
    TUN_ENTRY_MODE = args.entry_mode
    TUN_LB_BOX_END_H = args.lb_box_end
    TUN_LB_ENTRY_END_H = args.lb_entry_end
    TUN_LB_SL_BOX_FRAC = args.lb_sl_frac
    TUN_LB_TP_R = args.lb_tp_r
    TUN_LB_MIN_BOX_ATR = args.lb_min_box_atr
    LB_STATE.clear()
    MODE_DAY_STATE.clear()
    global TUN_PB_ADX_MIN, TUN_DA_ADX_MIN, TUN_MODE_FLAT16
    TUN_PB_ADX_MIN = args.pb_adx_min
    TUN_DA_ADX_MIN = args.da_adx_min
    TUN_MODE_FLAT16 = args.flat_16
    global MODE_SYMBOLS
    MODE_SYMBOLS = {x.strip().upper() for x in args.mode_symbols.split(",") if x.strip()}
    global TUN_DA_SL_ATR, TUN_DA_TP_ATR
    TUN_DA_SL_ATR = args.da_sl_atr
    TUN_DA_TP_ATR = args.da_tp_atr
    global TUN_MODE_SL_ATR, TUN_MODE_TP_ATR, TUN_SQUEEZE_BB_PCT, TUN_SQUEEZE_BB_PERIOD
    global TUN_NR7_N, TUN_NR7_ADX_MIN, TUN_ORB_BOX_START_H, TUN_ORB_BOX_END_H
    global TUN_ORB_ENTRY_START_H, TUN_ORB_ENTRY_END_H, TUN_ORB_MIN_ATR, TUN_ORB_MAX_ATR
    global TUN_ORB_SL_FRAC, TUN_ORB_TP_R
    TUN_MODE_SL_ATR = args.mode_sl_atr
    TUN_MODE_TP_ATR = args.mode_tp_atr
    TUN_SQUEEZE_BB_PCT = args.squeeze_bb_pct
    TUN_SQUEEZE_BB_PERIOD = args.squeeze_bb_period
    TUN_NR7_N = args.nr7_n
    TUN_NR7_ADX_MIN = args.nr7_adx_min
    TUN_ORB_BOX_START_H = args.orb_box_start
    TUN_ORB_BOX_END_H = args.orb_box_end
    TUN_ORB_ENTRY_START_H = args.orb_entry_start
    TUN_ORB_ENTRY_END_H = args.orb_entry_end
    TUN_ORB_MIN_ATR = args.orb_min_atr
    TUN_ORB_MAX_ATR = args.orb_max_atr
    TUN_ORB_SL_FRAC = args.orb_sl_frac
    TUN_ORB_TP_R = args.orb_tp_r

    TUN_MIN_SCORE = args.min_score
    TUN_SL_ATR_MULT = args.sl_mult
    TUN_TP_ATR_MULT = args.tp_mult
    TUN_RR_FLOOR = args.rr_floor
    TUN_HEADROOM_FOREX = args.headroom
    TUN_ADX_MIN = args.adx_min
    TUN_ST_FILTER = args.st_filter
    global TUN_SPEC_ATR
    TUN_SPEC_ATR = args.spec_atr
    EV_GUARD = not args.no_ev_guard
    TUN_FX_MIN_SCORE = args.fx_min_score
    TUN_GOLD_DXY_SOFT = args.gold_dxy_soft
    TUN_GOLD_DXY_BUMP = args.gold_dxy_bump
    EV_WINDOW_SEC = args.ev_window * 3600.0
    EV_MAX_WIN_RATE = args.ev_wr
    TUN_CHANDLIER = args.chandelier
    if args.major_hours:
        parts = args.major_hours.split("-")
        TUN_MAJOR_HOURS = (int(parts[0]), int(parts[1]))
    TUN_MAJOR_MIN_ATR = args.major_min_atr
    TUN_MAJOR_MAX_EXT = args.major_max_ext
    GATED_EXTRAS = {s.strip().upper() for s in args.gate_extras.split(",") if s.strip()}
    TUN_GOLD_SESSION = args.gold_session
    TUN_BTC_EMA200 = args.btc_ema200
    TUN_BTC_VWAP = args.btc_vwap
    TUN_CRYPTO_SL_MULT = args.crypto_sl_mult
    TUN_BTC_MIN_SCORE = args.btc_min_score
    if args.no_tp:
        TUN_TP_MODE = "no_tp"
    elif args.no_tp_crypto:
        TUN_TP_MODE = "no_tp_crypto"
    elif args.no_tp_on_trail_live:
        TUN_TP_MODE = "no_tp_on_trail_live"
    elif args.no_tp_on_trail:
        TUN_TP_MODE = "no_tp_on_trail"
    TUN_GOLD_VOL_EXITS = args.gold_vol_exits
    TUN_VOL_BE_MULT = args.vol_be_mult
    TUN_VOL_TRAIL_MULT = args.vol_trail_mult
    TUN_VOL_TRAIL_FLOOR = args.vol_trail_floor
    TUN_BE_USD_GOLD = args.be_usd_gold
    TUN_BE_RATIO_GOLD = args.be_ratio_gold
    TUN_BE_PIP_FIXED_GOLD = args.be_pip_fixed_gold
    global TUN_ST_FLIP_EXIT, TUN_ST_FLIP_MIN_PNL, TUN_EMA_FLIP_EXIT, ST_EXIT_PERIOD, ST_EXIT_MULT
    TUN_ST_FLIP_EXIT = args.st_flip_exit
    TUN_ST_FLIP_MIN_PNL = args.st_flip_min_pnl
    TUN_EMA_FLIP_EXIT = args.ema_flip_exit
    ST_EXIT_PERIOD = args.st_exit_period
    ST_EXIT_MULT = args.st_exit_mult
    global TUN_EXT_GATE_XG
    TUN_EXT_GATE_XG = args.ext_gate_xg
    global TUN_ST_FLIP_TIGHTEN
    TUN_ST_FLIP_TIGHTEN = args.st_flip_tighten
    global TUN_HTF_ALIGN, TUN_DIV_GATE, TUN_PYR_AGE_MAX
    TUN_HTF_ALIGN = args.htf_align
    TUN_DIV_GATE = args.div_gate
    TUN_PYR_AGE_MAX = args.pyr_age_max
    global TUN_LOSS_STREAK, TUN_LOSS_STREAK_CD
    TUN_LOSS_STREAK = args.loss_streak
    TUN_LOSS_STREAK_CD = args.loss_streak_cd
    if args.max_open and args.max_open > 0:
        global MAX_OPEN_POSITIONS
        MAX_OPEN_POSITIONS = args.max_open
    TUN_DCA = args.dca
    TUN_DCA_DIST_FRAC = args.dca_dist_frac
    TUN_DCA_LOT_MULT = args.dca_lot_mult
    TUN_DCA_TP_USD = args.dca_tp_usd
    TUN_DCA_SL_USD = args.dca_sl_usd
    TUN_DCA_BUFFER_USD = args.dca_buffer_usd
    TUN_DCA_LEVEL_CHECK = args.dca_level_check
    TUN_DCA_LEVEL_TOL_ATR = args.dca_level_tol_atr
    TUN_DCA_MAX_LAYERS = args.dca_max_layers
    TUN_DCA_DIST_STEP = args.dca_dist_step
    if args.index_hours:
        _ih = args.index_hours.split("-")
        # HHMM formatı → dakika: "1330" = 13*60+30 = 810
        TUN_INDEX_HOURS = (int(_ih[0][:2]) * 60 + int(_ih[0][2:4]), int(_ih[1][:2]) * 60 + int(_ih[1][2:4]))
    TUN_INDEX_OPEN_DRIVE = args.index_open_drive
    RSI2_ENABLED = args.rsi2
    RSI2_ENTRY = args.rsi2_entry
    RSI2_EXIT = args.rsi2_exit
    FADE_ENABLED = args.fade
    FADE_K_ATR = args.fade_k_atr
    FADE_EARLY_ONLY = args.fade_early_only
    if args.dxy_exempt_extra:
        _extra = tuple(w.strip().upper() for w in args.dxy_exempt_extra.split(",") if w.strip())
        forex.DXY_EXEMPT_SYMBOLS = tuple(forex.DXY_EXEMPT_SYMBOLS) + _extra
    # #15 ATR yumuşatma. Canlı varsayılan artık WILDER (2026-10-07 kullanıcı
    # kararı, A/B aşağıda); replay de aynı tabanı kullanır ki ölçüm canlıyı
    # yansıtsın. `--plain-atr` eski düz-ortalama davranışına döndürür (A/B'nin
    # diğer kolu). `--wilder-atr` geriye dönük uyumluluk için kabul edilir
    # (artık varsayılanla aynı; eski komut satırları bozulmasın).
    if args.plain_atr:
        forex.ATR_USE_WILDER = False
        print("[KONFIG] ATR yumuşatma = DÜZ 14-ORTALAMA (#15 A/B kolu, eski davranış)")
    else:
        forex.ATR_USE_WILDER = True
        print("[KONFIG] ATR yumuşatma = WILDER (#15, canlı varsayılan)")
    # SuperTrend parametre denemesi: canlı fonksiyonu parametreyle sarmala (canlı kod değişmez)
    if (args.st_period, args.st_mult) != (10, 3.0):
        _orig_st = forex._compute_supertrend
        def _st_patched(h, l, c, period=10, mult=3.0, _o=_orig_st, _p=args.st_period, _m=args.st_mult):
            return _o(h, l, c, _p, _m)
        forex._compute_supertrend = _st_patched
    BLOCKED_HOURS = [int(h) for h in args.hours.split(",") if h.strip().isdigit()]
    cfg_str = (f"{args.tag} | min_score={TUN_MIN_SCORE} sl_mult={TUN_SL_ATR_MULT} tp_mult={TUN_TP_ATR_MULT} "
               f"rr_floor={TUN_RR_FLOOR} headroom={TUN_HEADROOM_FOREX} adx_min={TUN_ADX_MIN} st={TUN_ST_FILTER} "
               f"ev_guard={EV_GUARD} ev_win={args.ev_window}h ev_wr={args.ev_wr} fx_min_score={TUN_FX_MIN_SCORE or '-'} "
               f"goldDXYsoft={TUN_GOLD_DXY_SOFT}(+{TUN_GOLD_DXY_BUMP}) chandelier={TUN_CHANDLIER or '-'} "
               f"stP={args.st_period} stM={args.st_mult} goldSession={TUN_GOLD_SESSION} btcEMA200={TUN_BTC_EMA200} "
               f"btcVWAP={TUN_BTC_VWAP} cryptoSL={TUN_CRYPTO_SL_MULT or '-'} btcScore={TUN_BTC_MIN_SCORE or '-'} "
               f"majorHours={args.major_hours or '-'} majorMinAtr={TUN_MAJOR_MIN_ATR or '-'} majorMaxExt={TUN_MAJOR_MAX_EXT or '-'} "
               f"tpMode={TUN_TP_MODE} goldVol={TUN_GOLD_VOL_EXITS}(be={TUN_VOL_BE_MULT} trail={TUN_VOL_TRAIL_MULT}) "
               f"beUSD={TUN_BE_USD_GOLD} beRatio={TUN_BE_RATIO_GOLD} bePipFixed={TUN_BE_PIP_FIXED_GOLD or '-'} "
               f"momflip={TUN_ST_FLIP_EXIT}(minPnl={TUN_ST_FLIP_MIN_PNL or '-'} stP={ST_EXIT_PERIOD}/{ST_EXIT_MULT}) emaFlip={TUN_EMA_FLIP_EXIT} "
               f"htfAlign={TUN_HTF_ALIGN} divGate={TUN_DIV_GATE or '-'} pyrAge={TUN_PYR_AGE_MAX or '-'} "
               f"lossStreak={TUN_LOSS_STREAK or '-'}({TUN_LOSS_STREAK_CD:.0f}s) "
               f"idxHours={args.index_hours or '-'} idxOpenDrive={TUN_INDEX_OPEN_DRIVE} "
               f"dca={TUN_DCA}(dist={TUN_DCA_DIST_FRAC}+{TUN_DCA_DIST_STEP} lot={TUN_DCA_LOT_MULT} katman={TUN_DCA_MAX_LAYERS} tp={TUN_DCA_TP_USD} "
               f"sl={TUN_DCA_SL_USD} buf={TUN_DCA_BUFFER_USD} lvl={TUN_DCA_LEVEL_CHECK}/{TUN_DCA_LEVEL_TOL_ATR}) "
               f"hours={BLOCKED_HOURS or 'kapalı'} spreadProfile={os.path.basename(args.spread_profile) if args.spread_profile else '-'} "
               f"window={args.window} pencere={args.start or '-'}→{args.end or '-'}")
    if args.tag:
        print(f"[KONFIG] {cfg_str}")

    cache_path = args.cache or os.path.join(ROOT, "outputs", f"forex_replay_data_{args.days}d.json")
    if os.path.exists(cache_path):
        print(f"[VERI] Önbellekten yükleniyor: {cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            raw = json.load(f)
        data = {sym: [tuple(b) for b in bars] for sym, bars in raw.items()}
    else:
        print(f"[VERI] Yahoo Finance'ten {args.days} gün 5M mum çekiliyor...")
        data = fetch_all(args.days)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({sym: [list(b) for b in bars] for sym, bars in data.items()}, f)
        print(f"[VERI] Önbelleğe yazıldı: {cache_path} ({len(data)} sembol)")

    # Krosçar pip_val override'ı: pencere ortalaması quote-kurlarıyla spec sarılır
    global REPLAY_PIP_VAL_OVERRIDE
    REPLAY_PIP_VAL_OVERRIDE = _compute_pip_val_overrides(data)
    if REPLAY_PIP_VAL_OVERRIDE:
        _orig_specs_fn = forex.get_symbol_trading_specs

        def _specs_with_override(sym, **kw):
            s = dict(_orig_specs_fn(sym, **kw))
            ov = REPLAY_PIP_VAL_OVERRIDE.get(str(sym).upper())
            if ov:
                s["pip_val"] = ov
            return s

        forex.get_symbol_trading_specs = _specs_with_override
        ov_str = ", ".join(f"{k}={v}" for k, v in sorted(REPLAY_PIP_VAL_OVERRIDE.items())[:8])
        print(f"[KONFIG] Kros pip_val override ({len(REPLAY_PIP_VAL_OVERRIDE)} sembol): {ov_str}{' ...' if len(REPLAY_PIP_VAL_OVERRIDE) > 8 else ''}")

    entry_start_ts = None
    entry_end_ts = None
    if args.start:
        entry_start_ts = datetime.datetime.strptime(args.start, "%Y-%m-%d").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    if args.end:
        entry_end_ts = datetime.datetime.strptime(args.end, "%Y-%m-%d").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    elif args.window in ("recent", "prior"):
        all_last = max(bars[-1][0] for bars in data.values())
        split_ts = all_last - 7 * 86400
        if args.window == "recent":
            entry_start_ts = split_ts
        else:
            entry_end_ts = split_ts

    t0 = time.time()
    sym_filter = {s.strip().upper() for s in args.symbols.split(",") if s.strip()} or None
    add_syms = {s.strip().upper() for s in getattr(args, "add_symbols", "").split(",") if s.strip()} or None
    excl_syms = {s.strip().upper() for s in getattr(args, "exclude_symbols", "").split(",") if s.strip()} or None
    if args.mini_only:
        report = {"days": args.days, "variants": {}}
        if RSI2_ENABLED:
            report["variants"]["RSI2"] = run_rsi2_engine(data, entry_start_ts, entry_end_ts)
        if FADE_ENABLED:
            report["variants"]["FADE"] = run_fade_engine(data, entry_start_ts, entry_end_ts)
    else:
        report = run_replay(data, args.days, entry_start_ts=entry_start_ts, entry_end_ts=entry_end_ts,
                            symbol_filter=sym_filter, add_symbols=add_syms, exclude_symbols=excl_syms)
    report["config"] = cfg_str
    print(f"\n[REPLAY BİTTİ] {time.time() - t0:.1f} sn")

    print("\n" + "=" * 76)
    print(f"{'VARYANT':8s} {'İŞLEM':>6s} {'KAZANMA':>8s} {'NET PnL':>10s} {'İŞLEM BAŞINA':>13s}")
    print("-" * 76)
    for vname, v in report["variants"].items():
        print(f"{vname:8s} {v['trades']:>6d} {v['win_rate']:>7.1f}% {v['net_pnl_usd']:>+10.2f} {v['avg_pnl_usd']:>+13.3f}")
    print("-" * 76)
    new_v = report["variants"].get("NEW")
    if new_v is None:
        # Mini-only mod: NEW/OLD karşılaştırması yok — mini varyant ayrıntılarını yaz ve çık
        for vname, v in report["variants"].items():
            if v.get("max_drawdown_usd") is not None:
                print(f"{vname} Maks. Düşüş: ${v['max_drawdown_usd']:.2f}")
            print(f"\n{vname} çıkış nedenleri:")
            for r, st in sorted(v.get("exit_reasons", {}).items(), key=lambda kv: -kv[1]["n"]):
                print(f"  {r:10s} n:{st['n']:>4d} pnl:${st['pnl_usd']:+9.2f}")
            print(f"\n{vname} sembol bazlı:")
            for sym, st in sorted(v.get("per_symbol", {}).items(), key=lambda kv: kv[1]["pnl"]):
                print(f"  {sym:9s} n:{int(st['n']):>4d} win%:{100 * st['wins'] / max(1, st['n']):5.1f} pnl:${st['pnl']:+8.2f}")
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n[RAPOR] {args.out}")
        return
    if new_v.get("max_drawdown_usd") is not None:
        print(f"NEW Özkaynak: ${new_v['equity_start']:.2f} → ${new_v['equity_end']:.2f} | Maks. Düşüş: ${new_v['max_drawdown_usd']:.2f}")
    if new_v.get("daily_pnl"):
        print("\nGÜNLÜK PnL (NEW):")
        for d, pnl in new_v["daily_pnl"].items():
            bar = "+" * max(0, int(pnl / 2)) + "-" * max(0, int(-pnl / 2))
            print(f"  {d}  ${pnl:>+9.2f}  {bar}")
    print("\nKAPI KATKI ANALİZİ (NEW'in engellediklerinin gölge defter sonuçları):")
    print(f"{'KAPI':12s} {'ENGEL':>6s} {'GÖLGE İŞLEM':>11s} {'GÖLGE WR':>9s} {'GÖLGE PnL':>10s}  YORUM")
    print("-" * 76)
    for gate, g in report["gate_attribution"].items():
        verdict = "✓ doğru eledi" if g["shadow_pnl_usd"] < 0 else "✗ kâr kesiyor — eşik gevşetilmeli"
        print(f"{gate:12s} {g['blocked']:>6d} {g['shadow_trades']:>11d} {g['shadow_win_rate']:>8.1f}% {g['shadow_pnl_usd']:>+10.2f}  {verdict}")

    print("\nSembol bazlı NEW:")
    for sym, st in sorted(report["variants"]["NEW"]["per_symbol"].items(), key=lambda kv: kv[1]["pnl"]):
        print(f"  {sym:9s} n:{int(st['n']):>3d} win%:{100 * st['wins'] / max(1, st['n']):5.1f} pnl:${st['pnl']:+8.2f}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[RAPOR] {args.out}")


if __name__ == "__main__":
    main()
