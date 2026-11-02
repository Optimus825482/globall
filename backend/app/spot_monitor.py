"""Spot Monitor Scanner and Portfolio Simulator for Binance TR."""
import asyncio
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
import asyncpg
from app.config import config
from app.technical_analysis import (
    _kdj, _supertrend, _ema,
    _rsi, _atr, _bollinger, _adx,
    _aroon, _mfi, _linreg_slope_pct,
    _cluc_wick_bounce, _vwap_mean_rev, _turtle_donchian,
    _vp_vah_breakout, _cvd_absorption_wick, _ttm_squeeze_fired,
    _vfi_zero_break, _nw_kernel_envelope,
    _kaufman_er_trend, _multi_factor_alpha,
    _buy_flow_dominance, _cmo_accel_break,
    _dual_vol_break, _gk_vol_expansion,
)
from app import ml_forecast
from app.ai_trading_suite import (
    OctoBotMatrixEvaluator,
    IndicatorEvaluation,
    VibeBreakoutTracker,
    VibeMetric,
    evaluate_qlib_alpha,
    evaluate_jesse_risk
)

logger = logging.getLogger("scalper.spot_monitor")

# Simülasyon Sabitleri
INITIAL_PORTFOLIO_TRY = 5000.0
TRADE_SIZE_TRY = 500.0
_next_scan_time = 0.0
_scan_interval_sec = 60
COMMISSION_RATE = 0.0004 # %0.04 tek yön (Maker/Taker)

# Ücret senaryoları — BNB indirimi kullanımına göre gerçek round-trip maliyet.
#   bnb:  BNB ile ödeme (Binance %25 indirim) → %0.075 × 2
#   base: kayıtlı kullanıcı standart            → %0.100 × 2
# Lab/backtest sonuçları %0.08 varsayımıyla üretildi; canlı sonuçlar yalnızca
# gerçek ödenen ücretle karşılaştırılabilir.
COMMISSION_SCHEDULES = {
    "bnb":  {"one_way": 0.00075, "label": "BNB indirimli (%0.15 round-trip)"},
    "base": {"one_way": 0.00100, "label": "Standart (%0.20 round-trip)"},
}
FEE_MODE = "bnb"

# Taranacak ana ve hacimli semboller
CORE_SYMBOLS = [
    "BTCTRY", "ETHTRY", "SOLTRY", "AVAXTRY", "NEARTRY", "DOGETRY", 
    "PEPETRY", "BNBTRY", "XRPTRY", "LINKTRY", "SHIBTRY", "ADATRY",
    "DOTTRY", "RENDERTRY", "FETTRY", "ARBTRY", "OPTRY", "INJTRY"
]

TIMEFRAMES = {
    "5m": {"tp_pct": 1.4, "sl_pct": 0.9, "label": "5m Scalp"},
    "15m": {"tp_pct": 2.2, "sl_pct": 1.1, "label": "15m Standart"},
    "1h": {"tp_pct": 3.2, "sl_pct": 1.6, "label": "1h Swing"}
}

# Aktif tarama stratejileri kaydı — run_single_scan() içindeki kurallarla senkron tutulmalı.
# Sıra = run_single_scan() içindeki öncelik sırası (ilk eşleşen kural kazanır).
ACTIVE_STRATEGIES = [
    {
        "code": "dual_vol_break",
        "label": "Dual Volatilite (GK+Parkinson) Patlama Kırılımı",
        "score": 97.0,
        "description": "Garman-Klass ve Parkinson oynaklığının eşzamanlı >%20 fırlaması ve 10-bar tepe kırılımı.",
        "evidence": "VectorBT: H1'de 40 aktif coinde PF 7.60, WR %55.2, net kâr +%1.925, 20/33 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "gk_vol_expansion",
        "label": "Garman-Klass Sıkışma Sonrası Tepe Kırılımı",
        "score": 92.5,
        "description": "GK oynaklık taban sıkışması (<%30 persentil) ardından 15-bar tepe kırılımı ve hacim artışı.",
        "evidence": "VectorBT: H1'de 40 aktif coinde PF 1.89, net kâr +%0.206, 18/39 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "buy_flow_dominance",
        "label": "Buy Flow Dominance (Alıcı Baskısı Kırılımı)",
        "score": 95.5,
        "description": "Bar Delta alıcı oranı >= %70 ve 7-barlık tepe kırılımı + hacim genişlemesi.",
        "evidence": "VectorBT: H1'de 40 aktif coinde PF 3.00, net kâr +%0.254, 873 işlem, 24/40 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "cmo_accel_break",
        "label": "Chande Momentum (CMO) İvme Kırılımı",
        "score": 93.5,
        "description": "Chande Momentum Oscillator sıfır eşiği kırılımı ve trend ivmelenmesi.",
        "evidence": "VectorBT: H1'de 40 aktif coinde PF 2.52, net kâr +%0.139, 428 işlem, 21/40 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "kaufman_er_trend",
        "label": "Kaufman ER Düşük Gürültülü Trend Kırılımı",
        "score": 96.0,
        "description": "Kaufman Verimlilik Oranı (ER>=0.42) ile gürültüsüz tepe kırılımı ve hacim patlaması.",
        "evidence": "VectorBT: H1'de 40 aktif coinde PF 5.02, net kâr +%0.806, 27/39 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "multi_factor_alpha",
        "label": "Çoklu-Faktör Z-Score Alpha",
        "score": 91.0,
        "description": "Hacim Z-Score + Momentum Z-Score + RSI Faktör bileşkesi tepe anomalisi.",
        "evidence": "VectorBT: H1'de PF 1.53, net kâr +%0.274, 13/30 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "vp_vah_breakout",
        "label": "Volume Profile VAH Kırılımı",
        "score": 95.0,
        "description": "Value Area High (%70 hacim tavanı) üzerine hacimli kırılım ve fiyat keşfi.",
        "evidence": "VectorBT: H1'de 40 aktif coinde PF 2.40, net kâr +%0.295, 27/40 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "vfi_zero_break",
        "label": "Katsanos VFI Hacim Akışı Kırılımı",
        "score": 94.5,
        "description": "Katsanos Volume Flow Indicator sıfır çizgisi yukarı kırılımı ve kurumsal para girişi.",
        "evidence": "VectorBT: H1'de 40 aktif coinde PF 2.81, net kâr +%0.127, 22/39 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "nw_kernel_envelope",
        "label": "Nadaraya-Watson Kernel Zarf Sekmesi",
        "score": 92.0,
        "description": "Nadaraya-Watson non-parametric regresyon alt zarfına batıp içeri sıçrama.",
        "evidence": "VectorBT: H1'de WR %48.7, PF 2.18, net kâr +%0.113, 18/36 coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "cluc_wick_bounce",
        "label": "ClucHAnST Kapitülasyon İğnesi (Wick Bounce)",
        "score": 94.0,
        "description": "Alt fitili gövdenin 1.4 katından büyük, hacmi ortalamanın 1.4 katı, RSI<=32 kapitülasyon sekmesi.",
        "evidence": "VectorBT: H1'de WR %59.1, PF 2.37, net kâr +%0.332, 14/18 aktif coinde kârlı.",
        "timeframes": ["45m", "1h"],
    },
    {
        "code": "cvd_absorption_wick",
        "label": "CVD Alıcı Emme Fitili (Order Flow Dip)",
        "score": 93.0,
        "description": "Hacimli barda alıcıların satışı tamamen emmesi (Delta>0 + Uzun alt fitil).",
        "evidence": "VectorBT: H1'de WR %50.6, PF 1.71, net kâr +%0.210, 25/37 aktif coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "turtle_donchian",
        "label": "Modernize Turtle Donchian Kırılımı",
        "score": 90.0,
        "description": "20 barlık tepe kırılımı + ADX>=22 trend genişlemesi + Hacim patlaması.",
        "evidence": "VectorBT: H1'de PF 2.63, net kâr +%0.626, 31/45 aktif coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "ttm_squeeze_fired",
        "label": "TTM Squeeze 2.0 Bant Patlaması",
        "score": 89.0,
        "description": "Bollinger bantlarının Keltner içine sıkışıp yukarı patlaması + Momentum.",
        "evidence": "VectorBT: H1'de PF 1.57, net kâr +%0.118, 23/40 aktif coinde kârlı.",
        "timeframes": ["1h"],
    },
    {
        "code": "vwap_mean_rev",
        "label": "Kurumsal VWAP Dip Sekmesi (-1.8 Band)",
        "score": 88.0,
        "description": "VWAP -1.8 standart sapma bandı altından içeri sıçrama ve RSI<=35 yukarı dönüş.",
        "evidence": "VectorBT: H1'de PF 3.16, M15'te 22/41 aktif coinde pozitif kâr.",
        "timeframes": ["15m", "1h"],
    },
    {
        "code": "kdj_pure_dip",
        "label": "KDJ Saf Dip (J<=12)",
        "score": 82.0,
        "description": "KDJ J eğrisinin ekstrem aşırı satım bölgesinden (J<=12) yukarı sıçraması.",
        "evidence": "60 gün / 40 sembol / 1.65M bar: PF 0.91, WR %43.1, izleme listesi.",
        "timeframes": ["5m", "15m", "1h"],
    },
]

ACTIVE_STRATEGY_CODES = {s["code"] for s in ACTIVE_STRATEGIES}
DEFAULT_DISABLED_STRATEGIES = set()
# Strateji bazlı TP/SL override (walk-forward + OOS doğrulamasından geçen kademeler)
STRATEGY_TPSL_OVERRIDE = {s["code"]: s.get("tp_sl_override", {}) for s in ACTIVE_STRATEGIES}

# ─── STRATEJİ ELEMESİ (2026-11-01/02) ─────────────────────────────────────────
# 8 strateji, 60 gün / 40 sembol / 1.65M gerçek bar üzerinde gerçek vectorbt ile
# tek tek ölçüldü. Sonuç: 7'si rastgele girişten AYRIŞMIYOR.
#
#   strateji              n      WR     PF    ort%   rastgeleye fark
#   kdj_pure_dip         559   43.1%  0.91  -0.116      +0.031 ANLAMLI
#   zlmacd_momentum    11826   38.6%  0.71  -0.135      +0.012 gürültü
#   rvol_tod_spike      5345   38.0%  0.74  -0.137      +0.010 gürültü
#   stc_cycle           4877   39.2%  0.72  -0.140      +0.007 gürültü
#   supertrend_pullback 36599  39.1%  0.70  -0.137      +0.010 gürültü
#   linreg_slope_turn  27224   39.2%  0.70  -0.140      +0.007 gürültü
#   squeeze_breakout    1279   37.9%  0.70  -0.147      +0.000 gürültü
#   ema_bounce         23118   37.7%  0.67  -0.154      -0.007 gürültü
#   --- rastgele ---   52840   39.4%  0.69  -0.147      referans
#
# 7 strateji KALDIRILDI (kod, kayıt ve tarama kuralları). Kısa pencerede
# "şampiyon" görünen `squeeze_breakout` bile 60 günde rastgeleye farkı SIFIR.
# Yalnızca `kdj_pure_dip` kaldı: PF 0.91 — kârlı değil ama rastgeleden
# anlamlı ayrışan tek kural.
#
# Kâr için gereken şey 5 dakikalık tarama değil, GÜNLÜK kanal (bkz. tsmom.py).

# ─── GİRİŞ KAYIT KAPISI ────────────────────────────────────────────────────────
# ÖNEMLİ: `ai_trading_suite` içindeki 42 modül (OctoBot, Qlib, Vibe, Jesse vb.)
# ÖĞRENEN MODEL DEĞİLDİR — hepsi elle yazılmış deterministik if/else kural
# motorlarıdır. Hiçbiri torch/tf/sklearn/lightgbm import etmez ve projede
# eğitilmiş ağırlık dosyası yoktur. "AI skoru" adı altında çalıştırmak
# yanıltıcıdır; bu yüzden skorlar HESAPLANMAYA DEVAM EDER (panelde görünür,
# insan değerlendirmesi için) ama KARAR VERMEZ.
#
# Tek gerçek öğrenen bileşen `ml_forecast`: 5m kapanmış barlardan Aroon/MFI/
# vol-Z özellikleri türetir, 5dk ileri MFE'yi regres eder + "hedefe dokunma
# olasılığı" sınıflandırır. Artifact (upside_v3.joblib) yoksa sessizce devre
# dışı kalır — uydurma değer üretmez.
AI_GATE = {
    # "shadow"  : skorlar hesaplanır/kaydedilir, işlemi ENGELLEMEZ (varsayılan)
    # "enforce" : aşağıdaki eşikler işlemi engeller
    "mode": "shadow",
    # Yalnızca GERÇEK model: ML "hedefe dokunma" olasılığı alt sınırı.
    # Eğitimli artifact yoksa bu kapı uygulanmaz (uydurma engel olmasın).
    "min_ml_hit_probability": 0.55,
    # Aşağıdakiler heuristik skorlardır — "enforce" modunda kullanılabilir ama
    # önce walk-forward ile doğrulanmaları gerekir. Şimdilik yalnız kaydedilir.
    "min_octobot_consensus_pct": 50,
    "block_fomo_trap": True,
    "block_q_none": True,
    "min_qlib_alpha": 45.0,
    "require_jesse_rr": 1.40,
}

# Otomatik tarama döngüsünde strateji açık/kapalı durumu (DB'de kalıcı, süreç içi önbellek).
_strategy_enabled: dict[str, bool] = {}
_strategy_settings_loaded = False


async def _ensure_strategy_settings(conn) -> None:
    """Ayar tablosunu oluşturur ve aç/kapa durumunu süreç içi önbelleğe yükler."""
    global _strategy_settings_loaded
    if _strategy_settings_loaded:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spot_monitor_strategy_settings (
            strategy_code TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Varsayılan: hepsi açık. DB'de kayıt varsa o kazanır. Ölçümle elenenler
    # için DB'de kayıt YOKSA varsayılan kapalı olur (panelden açılabilir).
    _strategy_enabled.update({code: code not in DEFAULT_DISABLED_STRATEGIES
                              for code in ACTIVE_STRATEGY_CODES})
    rows = await conn.fetch("SELECT strategy_code, enabled FROM spot_monitor_strategy_settings")
    _strategy_enabled.update({r["strategy_code"]: bool(r["enabled"]) for r in rows})
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spot_monitor_general_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    await _ensure_spot_schema(conn)
    ts_row = await conn.fetchrow("SELECT setting_value FROM spot_monitor_general_settings WHERE setting_key = 'trade_size_try'")
    if ts_row:
        try:
            global TRADE_SIZE_TRY
            TRADE_SIZE_TRY = float(ts_row["setting_value"])
        except Exception:
            pass
    fm_row = await conn.fetchrow("SELECT setting_value FROM spot_monitor_general_settings WHERE setting_key = 'fee_mode'")
    if fm_row and fm_row["setting_value"] in COMMISSION_SCHEDULES:
        global FEE_MODE
        FEE_MODE = fm_row["setting_value"]
    _strategy_settings_loaded = True


async def set_fee_mode(mode: str) -> dict:
    """Ücret senaryosunu (bnb / base) değiştirir ve kalıcılaştırır.

    Simülatörün gerçekçiliği buna bağlı: %0.08 ile %0.20 round-trip arasındaki
    fark, 5m stratejilerinin çoğunu kârlıdan kârsıza çevirir.
    """
    global FEE_MODE
    if mode not in COMMISSION_SCHEDULES:
        raise ValueError(f"Bilinmeyen ücret modu: {mode}")
    FEE_MODE = mode
    conn = await get_db_conn()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS spot_monitor_general_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute("""
            INSERT INTO spot_monitor_general_settings (setting_key, setting_value, updated_at)
            VALUES ('fee_mode', $1, now())
            ON CONFLICT (setting_key) DO UPDATE SET setting_value = $1, updated_at = now()
        """, mode)
    finally:
        await conn.close()
    return {"success": True, "fee_mode": FEE_MODE, "round_trip_pct": _round_trip_cost_pct()}


async def set_strategy_enabled(code: str, enabled: bool) -> dict:
    """Bir stratejinin otomatik taramadaki aktif/pasif durumunu değiştirir ve kalıcılaştırır."""
    if code not in ACTIVE_STRATEGY_CODES:
        raise ValueError(f"Bilinmeyen strateji kodu: {code}")
    conn = await get_db_conn()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS spot_monitor_strategy_settings (
                strategy_code TEXT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute("""
            INSERT INTO spot_monitor_strategy_settings (strategy_code, enabled, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (strategy_code) DO UPDATE SET enabled = $2, updated_at = now()
        """, code, enabled)
    finally:
        await conn.close()
    _strategy_enabled[code] = enabled
    return {"strategy_code": code, "enabled": enabled}


async def set_trade_size(amount: float) -> dict:
    """Spot Monitor işlem/alım büyüklüğünü (TRY) günceller ve kalıcı kaydeder."""
    global TRADE_SIZE_TRY
    val = round(max(50.0, min(50000.0, float(amount))), 2)
    TRADE_SIZE_TRY = val
    conn = await get_db_conn()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS spot_monitor_general_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute("""
            INSERT INTO spot_monitor_general_settings (setting_key, setting_value, updated_at)
            VALUES ('trade_size_try', $1, now())
            ON CONFLICT (setting_key) DO UPDATE SET setting_value = $1, updated_at = now()
        """, str(val))
    finally:
        await conn.close()
    return {"success": True, "trade_size_try": TRADE_SIZE_TRY}

_monitor_running = False
_last_scan_time = 0.0
_cached_results = {
    "live_signals": [],
    "summary": {},
    "portfolio": {}
}
# AI kapıları tarafından reddedilen sinyaller (son tarama). Panelde gösterilir ve
# shadow-tracking için saklanır: reddedilen sinyalin gerçekte ne yapacağını görmek,
# kapıların değerini kanıtlamanın tek yoludur.
_rejected_signals: list[dict] = []

async def get_db_conn():
    import os
    db_url = os.environ.get("DATABASE_URL") or "postgresql://postgres:518518Erkan@localhost:5432/scalper_global"
    return await asyncpg.connect(db_url)

def _fetch_klines(symbol: str, interval: str, limit: int = 100) -> list:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return []

def _fetch_all_prices() -> dict:
    url = "https://api.binance.com/api/v3/ticker/price"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            return {d["symbol"]: float(d["price"]) for d in data if d["symbol"].endswith("TRY")}
    except Exception:
        return {}

KILL_TRADE_THRESHOLD = 20
KILL_PF_THRESHOLD = 1.0


# ─── ÇIKIŞ MODELİ: SAF ZİRVE TAKİPÇİ STOP (TP YOK) ─────────────────────────────
# TP hedefi kaldırıldı. Kâr sınırsız büyür, kayıp tanımlı kalır:
#   • Kâr %1.5'e ulaşınca takip devreye girer
#   • Devreye girdiği anda stop, maliyet + %0.8'e çekilir (işlem kaybedemez)
#   • Sonrasında stop, zirvenin %0.6 gerisinden gelir
#
# Gerekçe: Freqle liginde #1 olan NotAnotherSMAOffsetStrategyHO (WR %80.7,
# maxDD -%3.51) ve #3 E0V1E (PF 7.37) sabit TP kullanmaz — geniş stop +
# kademeli kilit + takipçi ile kazananı koşturur. Sabit TP, kazanan işlemi
# erken keser.
TRAIL_ACTIVATE_PCT = 1.5   # takipçinin devreye girdiği kâr eşiği (%)
TRAIL_LOCK_PCT = 0.8       # devreye girince kilitlenen net kâr (%)
TRAIL_DISTANCE_PCT = 0.6   # zirveden geriye takip mesafesi (%)

# ─── MOMENTUM-BAZLI ERKEN ÇIKIŞ ───────────────────────────────────────────────
# Ölçüm (2026-11-01, 33 sinyal): tutma süresi uzadıkça getiri KÖTÜLEŞİYOR.
#   30dk -0.167% | 1sa -0.333% | 4sa -0.291% | 12sa -0.370% | 24sa -0.385%
# Uzun beklemek sermayeyi hem bağlıyor hem kaybettiriyor. İki kural eklendi:
#
#  1. Kâr hiç gelmediyse: EARLY_EXIT_MINUTES sonunda momentum kontrol edilir;
#     momentum yoksa (RSI nötr/negatif ve fiyat girişin altında) çık.
#  2. Her durumda: MAX_HOLD_MINUTES tavanı — süresiz bekletme yok.
#
# Bu, "5 saat sonra çıkacaksan neden 5 saatlik riski alıyoruz" sorusunun
# karşılığı: artık beklemiyoruz, momentum yoksa erken çıkıyoruz.
EARLY_EXIT_MINUTES = {"5m": 30, "15m": 90, "1h": 240}
MAX_HOLD_MINUTES = {"5m": 120, "15m": 360, "1h": 720}
# "Tez tutmadı" eşiği. Ölçüm notu (2026-11-01):
#   Canlı 10 işlemde STALLED pozisyonlar ortalama -1.10 kapatmıştı.
#   Bu "erken çıkış çok geç" gibi görünüyor; ancak ÖLÇÜM bunu DESTEKLEMEDİ:
#   erken çıkışı sıkılaştırmak (15 dk'da ölü say) sonucu kötüleştirdi —
#   PF 0.61 → 0.26. Sebep: kazanan işlemlerin çoğu da ilk 15-30 dk'da kâr
#   göstermiyor, kural onları da kesiyordu. Aynı şey stop'u daraltmak için de
#   geçerli. Yani kayıp, çıkış kuralından değil GİRİŞ kalitesinden geliyor.
#   Bu yüzden eşik muhafazakâr bırakıldı: yalnızca gerçekten kaybeden ve
#   momentumu tükenmiş işlemler kesilir.
EARLY_EXIT_MIN_PROGRESS_PCT = 0.15
# "Ölü işlem" kuralı DENENDİ ve KALDIRILDI (yukarıdaki ölçüm). Sabit tutuluyor
# ki ileride yeniden denemek isteyen bunun ölçülmüş bir kayıp olduğunu görsün.
EARLY_EXIT_DEAD_MINUTES = {"5m": 9999, "15m": 9999, "1h": 9999}


def _row_get(row, key, default=None):
    """asyncpg Record için güvenli erişim — kolon henüz eklenmemişse default."""
    try:
        val = row[key]
    except (KeyError, IndexError):
        return default
    return default if val is None else val


async def _ensure_spot_schema(conn) -> None:
    """Zirve takipçi kolonlarını ekler (idempotent).

    Ayrı bir fonksiyon çünkü panel ve PnL güncellemesi, tarama hiç çalışmadan
    da çağrılabilir; kolonların orada da var olması gerekir.
    """
    await conn.execute("""
        ALTER TABLE spot_monitor_signals
            ADD COLUMN IF NOT EXISTS trailing_active BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS peak_price DOUBLE PRECISION
    """)


def _one_way_fee() -> float:
    """Tek yön komisyon oranı — seçili ücret senaryosuna göre."""
    return COMMISSION_SCHEDULES.get(FEE_MODE, COMMISSION_SCHEDULES["bnb"])["one_way"]


def _round_trip_cost_pct() -> float:
    """Round-trip maliyetin yüzde karşılığı (ör. 0.15 veya 0.20)."""
    return _one_way_fee() * 2.0 * 100.0


def _break_even_wr(tp_pct: float, sl_pct: float, cost_pct: float | None = None) -> float:
    """Basabas kazanma oranı (%). Kazançlar TP−maliyet, kayıplar SL+maliyet.

    Yüksek kazanma oranı tek başına kâr değildir: TP/SL asimetrisi eşiği
    belirler. Örn. 5m TP1.4/SL0.9 → %0.20 maliyette %47.8 basabas.
    """
    cost = _round_trip_cost_pct() if cost_pct is None else cost_pct
    net_tp = max(tp_pct - cost, 0.01)
    net_sl = sl_pct + cost
    return (net_sl / (net_tp + net_sl)) * 100.0


def _order_barriers(curr: float, target: float, stop: float) -> tuple[bool, bool]:
    """Bariyer temaslarını döndürür (hit_tp, hit_sl).

    MUHAFAZAKÂR KURAL (SKILL.md §1.3): "Tek barda aynı anda hem TP hem SL
    seviyesi görülmüşse muhafazakâr olarak SL kabul edilir." Çağıran taraf
    hit_sl'i hit_tp'den ÖNCE değerlendirir.

    NOT (dürüstlük): uzun (long) pozisyonda stop yalnızca yukarı hareket eder
    ve hedefin üstüne yalnızca MFE ≥ %1.8'den sonra çıkabilir — o noktada
    fiyat hedefi zaten geçmiştir, yani pozisyon kapanmış olurdu. Bu yüzden
    açık bir pozisyonda iki bariyer AYNI ANDA vurulamaz ve dalların sırası
    pratikte sonucu değiştirmez. Bu kural bir güvenlik ağıdır (gelecekte
    short/trailing-üstü hedef eklenirse doğru davranışı korur), mevcut bir
    hatanın düzeltmesi değildir.
    """
    return (curr >= target), (curr <= stop)


def _atr_percentiles(closes: list) -> tuple[float, float]:
    """Kapanışların ATR yüzdesi dağılımından (medyan, p75) döndürür.

    Amaç: sabit TP/SL yerine, sembolün KENDİ volatilitesine göre ölçekleme.
    BTC ile PEPE aynı yüzdeyi almamalı.

    Not: basit ardışık |Δclose| ortalaması kullanılır (TrueRange değil) —
    elimizde yalnızca kapanış serisi olduğu için, ve amaç mutlak ATR değil
    sembolün kendi dağılımında göreli konumunu bulmak.
    """
    if len(closes) < 15:
        return 0.0, 0.0
    atr_pcts = []
    for i in range(14, len(closes)):
        window = closes[i - 14:i + 1]
        # Ardışık farklar: window[j+1] - window[j]
        diffs = [abs(window[j + 1] - window[j]) for j in range(len(window) - 1)]
        atr = sum(diffs) / len(diffs) if diffs else 0.0
        if window[-1] > 0:
            atr_pcts.append(atr / window[-1])
    if not atr_pcts:
        return 0.0, 0.0
    atr_pcts.sort()
    median = atr_pcts[len(atr_pcts) // 2]
    p75 = atr_pcts[min(int(len(atr_pcts) * 0.75), len(atr_pcts) - 1)]
    return median, p75


# ─── ATR TABANLI HEDEF KISITI — VARSAYILAN OLARAK KAPALI ───────────────────────
# Bu mekanizma VALİDE EDİLMEDİ. Canlı veriyle denendiğinde 8 sembolün 7'sinde
# tetiklendi (piyasa kendi 500-barlık normunun ~2 katı volatilken), yani
# "nadir güvenlik ağı" değil, sürekli aktif bir TP/SL değiştiricisi gibi
# davrandı. Parametreleri tahmin edilerek seçildi — walk-forward/OOS testi yok.
#
# Araştırma raporunun kendi uyarısı: parametre eklemek in-sample performansı
# geri satın alır ve bedelini gerçekte öder. Bu yüzden kod ve testler burada
# duruyor ama CANLI TARAMADA KAPALI. Açmak için True yapın ve önce
# walk-forward ile doğrulayın.
ATR_CLAMP_ENABLED = False
ATR_CLAMP_TRIGGER_MULT = 1.5   # yalnızca şimdiki ATR, p75'in 1.5 KATINI aşarsa
ATR_CLAMP_MIN_RATIO = 0.75     # en fazla %25 daraltma


def _clamp_with_atr(tp_pct: float, sl_pct: float, atr_pct_now: float,
                    atr_median: float, atr_p75: float,
                    enabled: bool | None = None) -> tuple[float, float, str]:
    """TP/SL'yi sembolün kendi ATR dağılımına göre kısar (varsayılan: KAPALI).

    `ATR_CLAMP_ENABLED = False` iken her zaman no-op'tur; parametre `enabled`
    testlerde açıkça geçilebilir.

    Açıkken iki sınır uygular:

    1. **Tetik eşiği:** şimdiki ATR, p75'in `ATR_CLAMP_TRIGGER_MULT` katını
       aşmalı.
    2. **Taban oran:** daraltma `ATR_CLAMP_MIN_RATIO` (%75) ile sınırlı.
       Ölçeksiz oran kullanmak TP'yi 1.40'tan 0.72'ye indirip hedefi komisyon
       gürültüsünün içine sokuyordu.

    Yalnızca YUKARI volatilite kısıtlanır. Kısıt uygulanmadıysa boş string döner.
    """
    if enabled is None:
        enabled = ATR_CLAMP_ENABLED
    if not enabled:
        return tp_pct, sl_pct, ""
    if atr_median <= 0 or atr_p75 <= 0 or atr_pct_now <= 0:
        return tp_pct, sl_pct, ""
    if atr_pct_now <= atr_p75 * ATR_CLAMP_TRIGGER_MULT:
        return tp_pct, sl_pct, ""

    ratio = max(ATR_CLAMP_MIN_RATIO, min(1.0, atr_p75 / atr_pct_now))
    if ratio >= 0.999:
        return tp_pct, sl_pct, ""
    new_tp = max(round(tp_pct * ratio, 2), 0.3)
    new_sl = max(round(sl_pct * ratio, 2), 0.2)
    return new_tp, new_sl, (
        f"ATR-kisit: TP {tp_pct:.2f}->{new_tp:.2f}, SL {sl_pct:.2f}->{new_sl:.2f} "
        f"(atr {atr_pct_now * 100:.2f}% > {ATR_CLAMP_TRIGGER_MULT}x p75 "
        f"{atr_p75 * 100:.2f}%, oran {ratio:.2f})"
    )


async def get_strategy_live_stats(conn) -> dict:
    """Strateji başına canlı (gerçekleşen) işlem istatistikleri: işlem sayısı, WR, PF, net TL.
    skill'in kill-kriteri: ≥20 kapalı işlemde PF<1.0 ise strateji kill bayrağı alır."""
    try:
        rows = await conn.fetch("""
            SELECT strategy,
                   COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                   COUNT(*) FILTER (WHERE status <> 'OPEN') AS closed,
                   COUNT(*) FILTER (WHERE status IN ('WIN_TP', 'WIN_TRAILING', 'WIN_EXPIRED') OR (status <> 'OPEN' AND net_pnl_try > 0)) AS wins,
                   COUNT(*) FILTER (WHERE status = 'LOSS_SL') AS losses,
                   COUNT(*) FILTER (WHERE status = 'EXPIRED') AS expired,
                   COALESCE(SUM(CASE WHEN status <> 'OPEN' AND net_pnl_try > 0 THEN net_pnl_try END), 0) AS gain,
                   COALESCE(SUM(CASE WHEN status <> 'OPEN' AND net_pnl_try <= 0 THEN -net_pnl_try END), 0) AS loss,
                   COALESCE(SUM(net_pnl_try) FILTER (WHERE status <> 'OPEN'), 0) AS net_try
            FROM spot_monitor_signals
            GROUP BY strategy
        """)
    except Exception:
        return {}
    out = {}
    for r in rows:
        closed = int(r["closed"])
        gain, loss = float(r["gain"]), float(r["loss"])
        pf = round(gain / loss, 2) if loss > 0 else (99.9 if gain > 0 else None)
        wr = round(100.0 * int(r["wins"]) / closed, 1) if closed else None
        out[r["strategy"]] = {
            "trades": closed,
            "open": int(r["open_count"]),
            "wins": int(r["wins"]),
            "losses": int(r["losses"]),
            "expired": int(r["expired"]),
            "win_rate": wr,
            "pf": pf,
            "net_pnl_try": round(float(r["net_try"]), 2),
            "kill": bool(closed >= KILL_TRADE_THRESHOLD and pf is not None and pf < KILL_PF_THRESHOLD),
        }
    return out


async def get_active_strategies() -> dict:
    """Panelden görüntülenmek üzere aktif tarama stratejilerini, açık/kapalı durumlarını,
    canlı performans istatistiklerini ve tarama parametrelerini döndürür."""
    conn = await get_db_conn()
    try:
        await _ensure_strategy_settings(conn)
        live_stats = await get_strategy_live_stats(conn)
    finally:
        await conn.close()
    strategies = [
        {**s, "enabled": _strategy_enabled.get(s["code"], True), "live": live_stats.get(s["code"])}
        for s in ACTIVE_STRATEGIES
    ]
    return {
        "count": len(ACTIVE_STRATEGIES),
        "active_count": sum(1 for s in strategies if s["enabled"]),
        "kill_count": sum(1 for s in strategies if s["live"] and s["live"].get("kill")),
        "symbols_count": len(CORE_SYMBOLS),
        "timeframes": [
            {"code": tf, "label": cfg["label"], "tp_pct": cfg["tp_pct"], "sl_pct": cfg["sl_pct"]}
            for tf, cfg in TIMEFRAMES.items()
        ],
        "trade_size_try": TRADE_SIZE_TRY,
        "initial_portfolio_try": INITIAL_PORTFOLIO_TRY,
        "commission_rate": _one_way_fee(),
        "commission_round_trip_pct": _round_trip_cost_pct(),
        "fee_mode": FEE_MODE,
        "fee_schedules": {k: v["label"] for k, v in COMMISSION_SCHEDULES.items()},
        "strategies": strategies,
    }

async def run_single_scan():
    """Tüm sembollerde 3 zaman diliminde KDJ, SuperTrend ve EMA50 taraması yapar."""
    global _cached_results, _last_scan_time, _next_scan_time
    start_ts = time.time()
    discovered_signals = []
    # Her taramada reddedilenleri sıfırla — liste "son taramanın" kapı redlerini
    # gösterir, geçmiş birikimi değil.
    _rejected_signals.clear()

    conn = await get_db_conn()
    try:
        # 1. Eski mükerrer açık kayıtları temizle (aynı sembolde birden fazla OPEN varsa en eskisini tut, fazlalıkları sil)
        await conn.execute("""
            DELETE FROM spot_monitor_signals
            WHERE status = 'OPEN'
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM spot_monitor_signals
                  WHERE status = 'OPEN'
                  GROUP BY symbol
              )
        """)

        # 2. Hangi sembollerde zaten AÇIK pozisyon var?
        existing_open = await conn.fetch("SELECT symbol FROM spot_monitor_signals WHERE status = 'OPEN'")
        open_symbols = {r["symbol"] for r in existing_open}
        max_positions = int(INITIAL_PORTFOLIO_TRY // TRADE_SIZE_TRY)

        # Strateji aç/kapa durumunu yükle (pasif stratejiler taramaya girmez)
        await _ensure_strategy_settings(conn)
        enabled = {code: _strategy_enabled.get(code, True) for code in ACTIVE_STRATEGY_CODES}

        for sym in CORE_SYMBOLS:
            # Bu sembolde zaten açık pozisyon varsa yeni işlem açma
            if sym in open_symbols:
                continue
            if len(open_symbols) >= max_positions:
                break

            for tf, tf_cfg in TIMEFRAMES.items():
                if sym in open_symbols:
                    break

                klines = _fetch_klines(sym, tf, limit=500)  # RVOL saat-grubu ortalaması ve EMA200 ısınması için
                if len(klines) < 65:
                    continue

                highs = [float(k[2]) for k in klines]
                lows = [float(k[3]) for k in klines]
                closes = [float(k[4]) for k in klines]
                volumes = [float(k[5]) for k in klines]
                vols = volumes
                avg_vol = (sum(volumes[-20:]) / 20.0) if len(volumes) >= 20 and sum(volumes[-20:]) > 0 else (volumes[-1] if volumes else 1.0)
                times_ms = [int(k[0]) for k in klines]
                price = closes[-1]
                quote_vols = [float(k[7]) for k in klines]
                trades = [int(k[8]) for k in klines]

                # ─── HACİM VE DURAĞANLIK (ÖLÜ TAHTA) FİLTRELERİ ───
                # 1. Durağanlık (Ölü Range): Son 20 barda tepe-dip farkı %0.40 altındaysa saatlerce hareket etmeyen ölü tahta elenir
                recent_range_pct = ((max(highs[-20:]) - min(lows[-20:])) / price) * 100.0
                if recent_range_pct < 0.40:
                    continue

                # 2. Minimum Bar Hacmi: Son 20 bar ortalama TRY hacmi en az 20.000 TL olmalı
                avg_bar_try_vol = sum(quote_vols[-20:]) / 20.0
                if avg_bar_try_vol < 20_000.0:
                    continue

                # 3. Derinlik / İşlem Sayısı: Bar başına en az ortalama 3 trade gerçekleşmiş olmalı
                avg_trades = sum(trades[-20:]) / 20.0
                if avg_trades < 3.0:
                    continue

                # 4. Hacimsiz Sahte Mum Koruması: Sinyal mumunun hacmi, ortalama bar hacminin %30'undan az olmamalı
                if quote_vols[-1] < (avg_bar_try_vol * 0.30):
                    continue

                # YALNIZCA kalan stratejinin ihtiyacı olan göstergeler.
                # 7 strateji kaldırıldığı için STC / ZLMACD / BB-KC sıkışma /
                # LinReg dönüş / RVOL / EMA-pullback hesapları da kaldırıldı:
                # her bar için hesaplanıp atılıyordu (ölçümde 18 sembol × 3
                # zaman dilimi × her tarama).
                kdj = _kdj(highs, lows, closes, period=9, signal=3) or {}
                st = _supertrend(highs, lows, closes, period=10, factor=3.0) or {}
                ema20 = _ema(closes, 20)
                ema50 = _ema(closes, 50)

                # Gerçek RSI / ATR / BB / ADX — AI katmanına ve ATR-kısıtına girer.
                # Önceden qlib/ATR sabit varsayımlarla (rsi=55.0, atr=price*0.015)
                # çağrılıyordu; skorlar bilgi taşımıyordu.
                rsi_val = float(_rsi(closes, 14) or 50.0)
                atr_val = float(_atr(highs, lows, closes, 14) or (price * 0.015))
                atr_pct_now = (atr_val / price) if price > 0 else 0.0
                bb = _bollinger(closes, 20, 2.0) or {}
                adx_res = _adx(highs, lows, closes, 14) or {}
                adx_val = float(adx_res.get("adx", 20.0))
                atr_median, atr_p75 = _atr_percentiles(closes)

                j_val = float(kdj.get("j", 50.0))
                dip_buy = bool(kdj.get("dip_buy"))
                st_bull = bool(st.get("bullish"))
                trend_bull = bool(ema20 is not None and ema50 is not None and ema20 >= ema50)

                matched = False
                strategy_code = ""
                strategy_label = ""
                score = 70.0
                note = ""

                # ── VECTORBT İLE DOĞRULANMIŞ STRATEJİLER (2026-11-02) ────────
                # 00. Dual Volatilite Patlama Kırılımı (H1: PF 7.60, WR %55.2, Net +%1.925)
                if enabled.get("dual_vol_break", True) and tf == "1h" and (dv_res := _dual_vol_break(opens, highs, lows, closes)) and dv_res.get("signal"):
                    matched = True
                    strategy_code = "dual_vol_break"
                    strategy_label = "Dual Volatilite Patlama Kırılımı"
                    score = 97.0
                    note = f"Dual Vol GK={dv_res.get('gk_vol')} Park={dv_res.get('p_vol')} tepe={dv_res.get('highest_10')}"

                # 00B. Garman-Klass Sıkışma Tepe Kırılımı (H1: PF 1.89, Net +%0.206)
                elif enabled.get("gk_vol_expansion", True) and tf == "1h" and (gk_res := _gk_vol_expansion(opens, highs, lows, closes, volumes)) and gk_res.get("signal"):
                    matched = True
                    strategy_code = "gk_vol_expansion"
                    strategy_label = "Garman-Klass Sıkışma Tepe Kırılımı"
                    score = 92.5
                    note = f"GK Sıkışma Kırılımı GK={gk_res.get('gk_vol')} hacim={gk_res.get('vol_ratio')}x tepe={gk_res.get('highest_15')}"

                # 0A. Buy Flow Dominance (H1: PF 3.00, Net +%0.254, 873 işlem)
                elif enabled.get("buy_flow_dominance", True) and tf == "1h" and (bf_res := _buy_flow_dominance(highs, lows, closes, volumes)) and bf_res.get("signal"):
                    matched = True
                    strategy_code = "buy_flow_dominance"
                    strategy_label = "Buy Flow Dominance"
                    score = 95.5
                    note = f"Alıcı baskısı=%{bf_res.get('buy_ratio')} hacim={bf_res.get('vol_ratio')}x tepe={bf_res.get('prev_highest')}"

                # 0B. Chande Momentum (CMO) İvme Kırılımı (H1: PF 2.52, Net +%0.139)
                elif enabled.get("cmo_accel_break", True) and tf == "1h" and (cmo_res := _cmo_accel_break(highs, lows, closes, volumes)) and cmo_res.get("signal"):
                    matched = True
                    strategy_code = "cmo_accel_break"
                    strategy_label = "Chande Momentum İvme Kırılımı"
                    score = 93.5
                    note = f"CMO={cmo_res.get('cmo')} (önceki: {cmo_res.get('cmo_prev')}) hacim={cmo_res.get('vol_ratio')}x"

                # 0C. Kaufman ER Trend Kırılımı (H1: PF 5.02, WR %48.7, Net +%0.806, 27/39 coin karlı)
                elif enabled.get("kaufman_er_trend", True) and tf == "1h" and (kauf_res := _kaufman_er_trend(highs, lows, closes, volumes)) and kauf_res.get("signal"):
                    matched = True
                    strategy_code = "kaufman_er_trend"
                    strategy_label = "Kaufman ER Düşük Gürültülü Trend Kırılımı"
                    score = 96.0
                    note = f"Kaufman ER={kauf_res.get('er')} hacim={kauf_res.get('vol_ratio')}x tepe={kauf_res.get('highest_14')}"

                # 0B. Çoklu-Faktör Z-Score Alpha (H1: PF 1.53, Net +%0.274)
                elif enabled.get("multi_factor_alpha", True) and tf == "1h" and (mfa_res := _multi_factor_alpha(highs, lows, closes, volumes)) and mfa_res.get("signal"):
                    matched = True
                    strategy_code = "multi_factor_alpha"
                    strategy_label = "Çoklu-Faktör Z-Score Alpha"
                    score = 91.0
                    note = f"Multi-Factor Alpha={mfa_res.get('alpha_score')} VolZ={mfa_res.get('vol_z')} MomZ={mfa_res.get('mom_z')}"

                # 1. Volume Profile VAH Kırılımı (H1: PF 2.40, Net +%0.295, 27/40 coin karlı)
                elif (vp_res := _vp_vah_breakout(highs, lows, closes, volumes) if tf == "1h" else None) and vp_res.get("signal") and enabled.get("vp_vah_breakout", True):
                    matched = True
                    strategy_code = "vp_vah_breakout"
                    strategy_label = "Volume Profile VAH Kırılımı"
                    score = 95.0
                    note = f"VAH kırılımı vah={vp_res.get('vah')} hacim={vp_res.get('vol_ratio')}x"

                # 1B. Katsanos VFI Sıfır Kırılımı (H1: PF 2.81, Net +%0.127, 22/39 coin karlı)
                elif enabled.get("vfi_zero_break", True) and tf == "1h" and (vfi_res := _vfi_zero_break(highs, lows, closes, volumes)) and vfi_res.get("signal"):
                    matched = True
                    strategy_code = "vfi_zero_break"
                    strategy_label = "Katsanos VFI Hacim Akışı Kırılımı"
                    score = 94.5
                    note = f"VFI sıfır kırılımı vfi={vfi_res.get('vfi')} (önceki: {vfi_res.get('vfi_prev')})"

                # 1C. Nadaraya-Watson Kernel Zarf Sekmesi (H1: WR %48.7, PF 2.18, Net +%0.113)
                elif enabled.get("nw_kernel_envelope", True) and tf == "1h" and (nw_res := _nw_kernel_envelope(highs, lows, closes)) and nw_res.get("signal"):
                    matched = True
                    strategy_code = "nw_kernel_envelope"
                    strategy_label = "Nadaraya-Watson Kernel Zarf Sekmesi"
                    score = 92.0
                    note = f"Nadaraya-Watson alt zarf sekmesi alt_bant={nw_res.get('lower_band')} RSI={nw_res.get('rsi')}"

                # 2. ClucHAnST Kapitülasyon İğnesi (H1: PF 2.37, WR %59.1, Net +%0.332)
                elif enabled.get("cluc_wick_bounce", True) and (cluc_res := _cluc_wick_bounce(highs, lows, closes, volumes)) and cluc_res.get("signal"):
                    matched = True
                    strategy_code = "cluc_wick_bounce"
                    strategy_label = "ClucHAnST Kapitülasyon İğnesi"
                    score = 94.0
                    note = f"Kapitülasyon fitil={cluc_res.get('lower_wick_ratio')}x RSI={cluc_res.get('rsi')} hacim={cluc_res.get('vol_ratio')}x"

                # 3. CVD Alıcı Emme Fitili (H1: WR %50.6, PF 1.71, Net +%0.210)
                elif enabled.get("cvd_absorption_wick", True) and tf in {"45m", "1h"} and (cvd_res := _cvd_absorption_wick(highs, lows, closes, volumes)) and cvd_res.get("signal"):
                    matched = True
                    strategy_code = "cvd_absorption_wick"
                    strategy_label = "CVD Alıcı Emme Fitili"
                    score = 93.0
                    note = f"CVD alıcı emme fitil={cvd_res.get('lower_wick_ratio')}x RSI={cvd_res.get('rsi')} hacim={cvd_res.get('vol_ratio')}x"

                # 4. TTM Squeeze 2.0 Bant Patlaması (H1: PF 1.57, Net +%0.118)
                elif enabled.get("ttm_squeeze_fired", True) and tf == "1h" and (sq_res := _ttm_squeeze_fired(highs, lows, closes)) and sq_res.get("signal"):
                    matched = True
                    strategy_code = "ttm_squeeze_fired"
                    strategy_label = "TTM Squeeze 2.0 Bant Patlaması"
                    score = 89.0
                    note = f"Sıkışma patladı mom={sq_res.get('momentum')}"

                # 2. Modernize Turtle Donchian 20 Kırılımı (H1: PF 2.63, Net +%0.626, 31/45 coin karlı)
                elif enabled.get("turtle_donchian", True) and tf in {"45m", "1h"}:
                    turtle_res = _turtle_donchian(highs, lows, closes, volumes)
                    if turtle_res and turtle_res.get("signal"):
                        matched = True
                        strategy_code = "turtle_donchian"
                        strategy_label = "Turtle Donchian Kırılımı"
                        score = 90.0
                        note = f"20-bar tepe kırılımı {turtle_res.get('highest_20')} ADX={turtle_res.get('adx')} hacim={turtle_res.get('vol_ratio')}x"

                # 3. Kurumsal VWAP -1.8 Bant Sekmesi (H1 PF 3.16, M15 22/41 coin pozitif)
                elif enabled.get("vwap_mean_rev", True):
                    vwap_res = _vwap_mean_rev(highs, lows, closes, volumes)
                    if vwap_res and vwap_res.get("signal"):
                        matched = True
                        strategy_code = "vwap_mean_rev"
                        strategy_label = "Kurumsal VWAP Dip Sekmesi"
                        score = 88.0
                        note = f"VWAP alt bant sekmesi {vwap_res.get('lower_band')} RSI={vwap_res.get('rsi')}"

                # 4. KDJ Ekstrem Saf Dip Dönüşü
                elif dip_buy and j_val <= 12.0 and enabled.get("kdj_pure_dip", True):
                    matched = True
                    strategy_code = "kdj_pure_dip"
                    strategy_label = "KDJ Saf Dip (J<=12)"
                    score = 82.0
                    note = f"Ekstrem aşırı satım sıçraması J={j_val:.1f}"

                if matched:
                    sl_pct = tf_cfg["sl_pct"]
                    override = STRATEGY_TPSL_OVERRIDE.get(strategy_code, {}).get(tf)
                    if override:
                        sl_pct = override["sl_pct"]
                    # ATR-kısıtı (varsayılan kapalı) — yalnızca ilk stop'u ölçekler.
                    # TP kaldırıldı; kâr zirve takipçisiyle yönetilir.
                    _tp_ignored, sl_pct, atr_note = _clamp_with_atr(
                        100.0, sl_pct, atr_pct_now, atr_median, atr_p75
                    )
                    if atr_note:
                        note = f"{note} | {atr_note}"
                    # TP YOK: kâr hedefi yerine zirve takipçisi çalışır.
                    target_p = None
                    stop_p = price * (1.0 - (sl_pct / 100.0))
                    sig_key = f"{sym}-{tf}-{strategy_code}-{int(start_ts)}"

                    # --- AI SUITE ENTEGRASYONU: OctoBot Konsenss & Vibe/Tuzak Tespiti ---
                    octo_eval = OctoBotMatrixEvaluator(consensus_threshold=0.60)
                    eval_indicators = [
                        IndicatorEvaluation("StrategyMatch", 1.0, 1.8),
                        IndicatorEvaluation("KDJ", 1.0 if j_val < 35 else (0.5 if j_val < 60 else -0.5), 1.2),
                        IndicatorEvaluation("Supertrend", 1.0 if st_bull else -1.0, 1.3),
                        IndicatorEvaluation("TrendEMA", 0.9 if (ema50 is not None and price > ema50) else -0.9, 1.1),
                    ]
                    octo_res = octo_eval.evaluate(sym, "SPOT", eval_indicators)

                    vibe_track = VibeBreakoutTracker()
                    cur_vol = volumes[-1] if volumes else 1.0
                    avg_v = (sum(volumes[-20:]) / 20.0) if len(volumes) >= 20 and sum(volumes[-20:]) > 0 else 1.0
                    vol_ratio = cur_vol / avg_v
                    p_chg = ((closes[-1] - closes[-3]) / closes[-3] * 100.0) if len(closes) >= 3 else 0.5
                    v_res = vibe_track.analyze_vibe(VibeMetric(
                        symbol=sym,
                        asset_type="SPOT",
                        price_change_pct=p_chg,
                        volume_ratio=vol_ratio,
                        social_buzz_score=0.5,
                        sentiment_velocity=0.1,
                        orderbook_depth_ratio=1.2 if vol_ratio > 1.2 else 0.9
                    ))
                    trap_warn = "BULL_TRAP" if (p_chg > 1.2 and vol_ratio < 0.85) else ("FOMO_TRAP" if v_res.is_fomo_trap else "NONE")
                    # Gerçek RSI/ATR/BB — sabit 55.0 / price*0.015 değil
                    qlib_res = evaluate_qlib_alpha(
                        symbol=sym,
                        price=price,
                        indicators={
                            "rsi": rsi_val,
                            "adx": adx_val,
                            "atr": atr_val,
                            "ema_fast": ema20 or price,
                            "ema_slow": ema50 or price,
                            "bb_upper": bb.get("upper") or (price * 1.02),
                            "bb_lower": bb.get("lower") or (price * 0.98),
                            "volume_ratio": vol_ratio,
                        }
                    )
                    jesse_res = evaluate_jesse_risk(
                        symbol=sym,
                        entry_price=price,
                        atr=atr_val,
                        volatility_mode="HIGH" if atr_pct_now > atr_p75 else "NORMAL"
                    )

                    # ─── GERÇEK ML TAHMİNİ (öğrenen tek bileşen) ───────────────
                    # ml_forecast: 5m kapanmış barlardan özellik üretir, 5dk
                    # ileri MFE regresyonu + "hedefe dokunma" olasılığı verir.
                    # Artifact yoksa None döner → kapı uygulanmaz.
                    ml_pred = None
                    try:
                        ar = _aroon(highs, lows, 25) or {}
                        # Özellik anlık görüntüsü SINYAL ANINDA kaydedilir.
                        # Geri besleme eğitimi bu snapshot'a dayanır: işlem
                        # kapandığında bar verisi çoktan kaymış olur, o yüzden
                        # özellikler o an yakalanmazsa örnek kurtarılamaz.
                        ml_features = {
                            "timestamp": times_ms[-1],
                            "ret1_pct": ((closes[-1] - closes[-2]) / closes[-2] * 100.0) if len(closes) >= 2 else None,
                            "ret3_pct": ((closes[-1] - closes[-4]) / closes[-4] * 100.0) if len(closes) >= 4 else None,
                            "ret5_pct": ((closes[-1] - closes[-6]) / closes[-6] * 100.0) if len(closes) >= 6 else None,
                            "atr_pct": atr_pct_now * 100.0,
                            "bb_width_pct": (bb.get("width_pct") or 0.0) * 100.0,
                            "rsi": rsi_val,
                            "mfi": _mfi(highs, lows, closes, volumes, 14),
                            "vol_z": (vol_ratio - 1.0),
                            "linreg_slope10_pct": _linreg_slope_pct(closes, 10),
                            "aroon_up": ar.get("up"), "aroon_down": ar.get("down"),
                        }
                        ml_pred = ml_forecast.predict_target(sym, ml_features, horizon=5)
                    except Exception as exc:
                        ml_features = None
                        logger.warning("spot ML tahmini başarısız %s: %s", sym, exc)

                    # ─── GİRİŞ KAYIT KAPISI ────────────────────────────────────
                    # Heuristik skorlar KAYDEDİLİR; karar yalnızca gerçek ML
                    # modeli varsa ona bağlanır (mode="enforce").
                    consensus_pct = int(octo_res.consensus_confidence * 100)
                    heuristic_flags = []
                    if consensus_pct < AI_GATE["min_octobot_consensus_pct"]:
                        heuristic_flags.append(f"octobot<{AI_GATE['min_octobot_consensus_pct']}")
                    if v_res.is_fomo_trap:
                        heuristic_flags.append("fomo_trap")
                    if trap_warn != "NONE":
                        heuristic_flags.append(trap_warn)
                    if qlib_res.alpha_score < AI_GATE["min_qlib_alpha"]:
                        heuristic_flags.append(f"qlib<{AI_GATE['min_qlib_alpha']}")
                    if jesse_res.risk_reward_ratio < AI_GATE["require_jesse_rr"]:
                        heuristic_flags.append(f"jesse_rr<{AI_GATE['require_jesse_rr']}")

                    gate_reasons = []
                    if AI_GATE["mode"] == "enforce" and ml_pred is not None:
                        if ml_pred["hit_probability"] < AI_GATE["min_ml_hit_probability"]:
                            gate_reasons.append(
                                f"ml_hit_prob {ml_pred['hit_probability']}"
                                f"<{AI_GATE['min_ml_hit_probability']}")

                    if gate_reasons:
                        _rejected_signals.append({
                            "symbol": sym, "timeframe": tf, "strategy": strategy_code,
                            "entry_price": price, "reasons": gate_reasons,
                            "ml_hit_probability": ml_pred["hit_probability"] if ml_pred else None,
                            "heuristic_flags": heuristic_flags,
                            "p_chg": round(p_chg, 2), "vol_ratio": round(vol_ratio, 2),
                            "at": datetime.now(timezone.utc).isoformat()
                        })
                        continue  # bu sembolde pozisyon açılmadı → döngü devam

                    discovered_signals.append({
                        "signal_key": sig_key,
                        "symbol": sym,
                        "timeframe": tf,
                        "strategy": strategy_code,
                        "strategy_label": strategy_label,
                        "entry_price": price,
                        "target_price": target_p,
                        "stop_price": stop_p,
                        "score": score,
                        "kdj_j": j_val,
                        "details": {
                            "note": note,
                            "exit_model": "peak_trailing",
                            "sl_pct": sl_pct,
                            "trail_activate_pct": TRAIL_ACTIVATE_PCT,
                            "trail_lock_pct": TRAIL_LOCK_PCT,
                            "trail_distance_pct": TRAIL_DISTANCE_PCT,
                            "range_pct": round(recent_range_pct, 2),
                            "avg_vol_try": round(avg_bar_try_vol, 0),
                            "rsi": round(rsi_val, 1),
                            "atr_pct": round(atr_pct_now * 100, 2),
                            "adx": round(adx_val, 1),
                            "break_even_wr": round(_break_even_wr(1.0, sl_pct), 1),
                            "fee_mode": FEE_MODE,
                            "octobot_score": round(octo_res.composite_score, 2),
                            "octobot_consensus_pct": consensus_pct,
                            "octobot_signal": octo_res.consensus_signal,
                            "vibe_score": round(v_res.vibe_score, 2),
                            "vibe_category": v_res.vibe_category,
                            "trap_warning": trap_warn,
                            "is_fomo_trap": v_res.is_fomo_trap,
                            "breakout_confirmed": v_res.breakout_confirmed,
                            "qlib_score": qlib_res.alpha_score,
                            "qlib_rank": qlib_res.alpha_rank,
                            "jesse_rr": jesse_res.risk_reward_ratio,
                            "ai_gate_mode": AI_GATE["mode"],
                            "heuristic_flags": heuristic_flags,
                            # Gerçek öğrenen model — artifact yoksa None
                            "ml_hit_probability": ml_pred["hit_probability"] if ml_pred else None,
                            "ml_target_pct": ml_pred["target_pct"] if ml_pred else None,
                            "ml_trained_at": ml_pred["trained_at"] if ml_pred else None,
                            # Sinyal anının özellik vektörü — geri besleme
                            # eğitiminin tek kaynağı (bkz. ml_forecast.prepare_spot_samples)
                            "ml_features": ml_features,
                        },
                        "detected_at": datetime.now(timezone.utc)
                    })
                    open_symbols.add(sym)
                    break

        for s in discovered_signals:
            await conn.execute("""
                INSERT INTO spot_monitor_signals (
                    signal_key, symbol, timeframe, strategy, strategy_label,
                    entry_price, target_price, stop_price, score, kdj_j, details,
                    trade_size_try, commission_try
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (signal_key) DO NOTHING
            """, s["signal_key"], s["symbol"], s["timeframe"], s["strategy"], s["strategy_label"],
               s["entry_price"], s["target_price"] or s["entry_price"], s["stop_price"], s["score"], s["kdj_j"],
               json.dumps(s["details"]), TRADE_SIZE_TRY, (TRADE_SIZE_TRY * _one_way_fee() * 2))

        # ─── DONDURULMUŞ MODEL İLERİ TESTİ ────────────────────────────────
        # Modelin kendi sinyalinden BAĞIMSIZ kayıt: eşik üstü HER ML tahmini
        # yazılır (strateji eşleşmese de). Amaç "model işe yarıyor mu" sorusunu
        # hiçbir ayar yapmadan, ileriye dönük ölçmek. Karar vermez, engellemez.
        try:
            await _record_forward_predictions(discovered_signals)
        except Exception as exc:  # noqa: BLE001 - kayıt hatası taramayı durdurmaz
            logger.info("ileri test kaydı atlandı: %s", exc)

        # Açık pozisyonların güncel kâr/zarar ve kapanış takibini yap
        closed_ids = await update_open_signals_pnl(conn)
        if closed_ids:
            # Kapanan pozisyonlar LLM inceleme KUYRUĞUNA girer; burada yalnızca
            # kaydedilir. İnceleme bir sonraki taramaların boşluğunda, tarama
            # döngüsünü bloke etmeden yapılır (bkz. _pending_reviews notu).
            _queue_llm_reviews(closed_ids)
    finally:
        await conn.close()

    _last_scan_time = time.time()
    _next_scan_time = _last_scan_time + _scan_interval_sec
    return len(discovered_signals)

# İleri testte her taramada örneklenecek sembol sayısı.
#
# ROTASYON — düzeltme (2026-11-01): eskiden evrenin İLK 40 sembolü sabit
# kullanılıyordu. Ölçüm: eşik 0.55 için 220 sembolde günde ~7.2 seçim var;
# 40 sembolle bu ~1.3'e düşüyor. Sabit ilk-40 ile haftalar boyunca birkaç
# örnek birikir ve test anlamsız kalır. Artık her turda sıradaki dilim alınır;
# 6 turda tüm 222 sembol taranır ve dakikada ~40 tahmin üretilir.
FORWARD_MAX_SYMBOLS = 40
_forward_offset = 0


# Canlı gösterge önbelleği: panel yenilemesi her açık pozisyon için sembol
# başına bir Binance isteği yapar. 10 pozisyon × saniyede bir yenileme hız
# sınırına çarpar; 45 sn önbellek tazeliği bozmadan bunu engeller.
_live_ind_cache: dict[str, tuple[float, dict]] = {}
LIVE_IND_TTL_SEC = 45


def _live_indicator_snapshot(symbol: str, entry_price: float) -> dict | None:
    """Açık pozisyon için GÜNCEL göstergeler (giriş anındaki değil).

    Neden: `details` sinyal anında donar. Panelde RSI 30'da giren bir işlem,
    RSI 70'e çıkmış olsa bile "30" gösteriyordu — yani ölü sinyal canlı
    sanılıyordu. Bu fonksiyon aynı sembolü yeniden ölçer.

    Hata/ağ sorununda None döner; çağıran girişteki değerlere düşer.
    """
    now = time.time()
    hit = _live_ind_cache.get(symbol)
    if hit and now - hit[0] < LIVE_IND_TTL_SEC:
        return hit[1]
    try:
        klines = _fetch_klines(symbol, "5m", limit=120)
        if len(klines) < 60:
            return None
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        price = closes[-1]
        rsi_val = float(_rsi(closes, 14) or 50.0)
        atr_val = float(_atr(highs, lows, closes, 14) or (price * 0.015))
        bb = _bollinger(closes, 20, 2.0) or {}
        adx_val = float((_adx(highs, lows, closes, 14) or {}).get("adx", 20.0))
        ema20 = _ema(closes, 20) or price
        ema50 = _ema(closes, 50) or price
        st = _supertrend(highs, lows, closes, period=10, factor=3.0) or {}
        st_bull = bool(st.get("bullish"))
        j_val = float((_kdj(highs, lows, closes, period=9, signal=3) or {}).get("j", 50.0))
        avg_v = (sum(volumes[-20:]) / 20.0) if len(volumes) >= 20 and sum(volumes[-20:]) > 0 else 1.0
        vol_ratio = (volumes[-1] / avg_v) if avg_v else 1.0
        p_chg = ((closes[-1] - closes[-3]) / closes[-3] * 100.0) if len(closes) >= 3 else 0.0

        # Aynı heuristik motorlar, GÜNCEL girdilerle
        octo = OctoBotMatrixEvaluator(consensus_threshold=0.60).evaluate(sym_indicators := symbol, "SPOT", [
            IndicatorEvaluation("Trend", 1.0 if ema20 >= ema50 else -1.0, 1.4),
            IndicatorEvaluation("KDJ", 1.0 if j_val < 35 else (0.5 if j_val < 60 else -0.5), 1.2),
            IndicatorEvaluation("Supertrend", 1.0 if st_bull else -1.0, 1.3),
            IndicatorEvaluation("TrendEMA", 0.9 if price > ema50 else -0.9, 1.1),
        ])
        vibe = VibeBreakoutTracker().analyze_vibe(VibeMetric(
            symbol=symbol, asset_type="SPOT", price_change_pct=p_chg,
            volume_ratio=vol_ratio, social_buzz_score=0.5, sentiment_velocity=0.1,
            orderbook_depth_ratio=1.2 if vol_ratio > 1.2 else 0.9))
        qlib = evaluate_qlib_alpha(symbol, price, {
            "rsi": rsi_val, "adx": adx_val, "atr": atr_val,
            "ema_fast": ema20, "ema_slow": ema50,
            "bb_upper": bb.get("upper") or price * 1.02,
            "bb_lower": bb.get("lower") or price * 0.98,
            "volume_ratio": vol_ratio,
        })
        trap = ("BULL_TRAP" if (p_chg > 1.2 and vol_ratio < 0.85)
                else ("FOMO_TRAP" if vibe.is_fomo_trap else "NONE"))
        out = {
            "octobot_consensus_pct": int(octo.consensus_confidence * 100),
            "octobot_signal": octo.consensus_signal,
            "qlib_score": qlib.alpha_score,
            "vibe_category": vibe.vibe_category,
            "trap_warning": trap,
            "is_fomo_trap": vibe.is_fomo_trap,
            "rsi": round(rsi_val, 1),
            "adx": round(adx_val, 1),
            "pnl_since_entry_pct": round((price - entry_price) / entry_price * 100.0, 3) if entry_price else None,
        }
        _live_ind_cache[symbol] = (now, out)
        return out
    except Exception as exc:  # noqa: BLE001 - panel gösterimi işlemi durdurmaz
        logger.info("canlı gösterge hatası %s: %s", symbol, exc)
        return None


async def _record_forward_predictions(signals: list[dict]) -> int:
    """Dondurulmuş model için ileri test kaydı üretir.

    ÖNEMLİ: kayıt, stratejinin sinyal üretip üretmemesine BAĞLI DEĞİLDİR.
    Yalnızca `discovered_signals` (strateji eşleşenler) yazılsaydı, ölçüm
    "model + strateji" karışımı olurdu ve modelin kendi katkısı ölçülemezdi.
    Bu yüzden ayrı ve bağımsız bir örnekleme yapılır: eşiği geçen her tahmin.

    Model dondurulmadıysa sessizce çıkar — dondurma bilinçli bir karardır.
    """
    from app import ml_forward_test
    frozen = await ml_forward_test.get_active_frozen()
    if not frozen:
        return 0
    model = ml_forward_test.load_frozen_model(frozen)
    if model is None:
        return 0
    bundle = (model.get("horizons") or {}).get("5")
    if not bundle or bundle.get("clf") is None:
        return 0
    clf = bundle["clf"]
    reg = bundle.get("reg")
    gate = float(frozen.get("gate_probability") or 0.55)
    sym_codes = model.get("symbol_codes") or {}

    # EVREN UYUŞMAZLIĞI — dikkat: tarayıcı Binance TR listesini (BTCTRY,
    # ETHTRY …) tarar, model ise USDT pariteleriyle eğitildi. İki listenin
    # kesişimi BOŞTUR. İleri test, modelin GÖRDÜĞÜ evrende çalışmak zorunda;
    # aksi halde hiç tahmin üretilmez (ve üretilse de anlamsız olurdu).
    global _forward_offset
    full_universe = sorted(sym_codes)
    if not full_universe:
        return 0
    # Dönen dilim: 6 turda tüm evren. Tek bir sembol patolojik olarak çok
    # seçilse bile kayıt tek sembole sıkışmaz.
    span = min(FORWARD_MAX_SYMBOLS, len(full_universe))
    start = _forward_offset % len(full_universe)
    universe = [full_universe[(start + i) % len(full_universe)] for i in range(span)]
    _forward_offset = (start + span) % len(full_universe)

    rows: list[dict] = []
    now_ms = int(time.time() * 1000)
    for sym in universe:
        try:
            klines = _fetch_klines(sym, "5m", limit=200)
        except Exception:
            continue
        if len(klines) < 61:
            continue
        # SON KAPANMIŞ BARI kullan — oluşan bar DEĞİL.
        # ML-01 sözleşmesi: "Model 5m kapanış barlarıyla eğitilir; çıkarım da
        # 5m kapanış barlardan özellik üretmelidir." Oluşan barı kullanmak
        # hem eğitim dağılımının dışına çıkar hem de aynı bar için kaydı
        # tekrarlar (bar kapanana dek özellikler sürekli değişir).
        klines = klines[:-1]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        price = closes[-1]
        try:
            rsi_val = float(_rsi(closes, 14) or 50.0)
            atr_val = float(_atr(highs, lows, closes, 14) or (price * 0.015))
            bb = _bollinger(closes, 20, 2.0) or {}
            ar = _aroon(highs, lows, 25) or {}
            avg_v = (sum(volumes[-20:]) / 20.0) if len(volumes) >= 20 else (volumes[-1] or 1.0)
            vol_ratio = (volumes[-1] / avg_v) if avg_v else 1.0
            feats = {
                "ret1_pct": ((closes[-1] - closes[-2]) / closes[-2] * 100.0) if len(closes) >= 2 else None,
                "ret3_pct": ((closes[-1] - closes[-4]) / closes[-4] * 100.0) if len(closes) >= 4 else None,
                "ret5_pct": ((closes[-1] - closes[-6]) / closes[-6] * 100.0) if len(closes) >= 6 else None,
                "atr_pct": (atr_val / price * 100.0) if price else None,
                "bb_width_pct": (bb.get("width_pct") or 0.0) * 100.0,
                "rsi": rsi_val,
                "mfi": _mfi(highs, lows, closes, volumes, 14),
                "vol_z": (vol_ratio - 1.0),
                "linreg_slope10_pct": _linreg_slope_pct(closes, 10),
                "aroon_up": ar.get("up"), "aroon_down": ar.get("down"),
                "timestamp": int(klines[-1][0]),
            }
            pred = ml_forecast.predict_from_artifact(model, sym, feats, horizon=5)
        except Exception:
            continue
        if pred is None:
            continue
        # KARAR ANI = barın KAPANIŞI, duvar saati değil.
        # Tarama 60 sn'de bir çalışır ama bar 5 dakikadır: duvar saatini
        # kullanmak aynı barı 5 kez kaydeder, örneklemi şişirir ve
        # örnekleri birbirine bağımlı kılar (istatistiği bozar).
        # Karar bar kapanışında verilir; ufuk penceresi de oradan başlamalı.
        bar_close_s = (int(klines[-1][0]) / 1000.0) + 300.0
        if bar_close_s > now_ms / 1000.0 + 60:
            continue                      # kapanmamış bar
        rows.append({
            "frozen_id": frozen["id"],
            "predicted_at": bar_close_s,
            "horizon_minutes": 5,
            "symbol": sym,
            "entry_price": price,
            "hit_probability": pred["hit_probability"],
            "target_pct": pred["target_pct"],
            "gate_passed": bool(pred["hit_probability"] >= gate),
            "features": feats,
        })
    if not rows:
        return 0
    return await ml_forward_test.record_shadow(rows)


async def update_open_signals_pnl(conn):
    """Açık pozisyonları anlık fiyatlarla denetler, Dinamik Takipçi Stop (Dynamic Exit Architect) ile kârı kilitler ve kapatır."""
    await _ensure_spot_schema(conn)
    open_rows = await conn.fetch("SELECT * FROM spot_monitor_signals WHERE status = 'OPEN'")
    if not open_rows:
        return []

    prices = _fetch_all_prices()
    now_utc = datetime.now(timezone.utc)
    closed_ids: list[int] = []

    for row in open_rows:
        sym = row["symbol"]
        curr_p = prices.get(sym)
        if not curr_p:
            continue

        entry_p = row["entry_price"]
        stop_p = row["stop_price"]
        pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0

        # MFE / MAE güncelleme
        old_mfe = row["mfe_pct"] or 0.0
        old_mae = row["mae_pct"] or 0.0
        new_mfe = max(old_mfe, pnl_pct)
        new_mae = min(old_mae, pnl_pct)

        # ─── ZİRVE TAKİPÇİ STOP (TP YOK) ───────────────────────────────────
        # TP hedefi kaldırıldı. Çıkış tek bir kurala bağlı: zirveyi takip eden
        # stop. Kâr sınırsız büyüyebilir, kayıp tanımlı kalır.
        #
        #   1. Kâr %TRAIL_ACTIVATE_PCT'e (1.5) ulaşınca takip DEVREDE.
        #   2. Devreye girdiği anda stop, maliyet + %TRAIL_LOCK_PCT (0.8) seviyesine
        #      çekilir → işlem artık kaybettiremez.
        #   3. Sonrasında stop, zirvenin %TRAIL_DISTANCE_PCT (0.6) gerisinden gelir.
        #
        # Kilit seviyesi bir TABAN'dır: zirve başlangıçta düşükse stop kilidin
        # altına inmesin. Takipçi yalnızca yukarı hareket eder.
        peak_p = max(float(_row_get(row, "peak_price", entry_p) or entry_p), entry_p * (1.0 + new_mfe / 100.0))
        was_trailing = bool(_row_get(row, "trailing_active", False))
        trailing_active = was_trailing or new_mfe >= TRAIL_ACTIVATE_PCT

        if trailing_active:
            lock_level = entry_p * (1.0 + TRAIL_LOCK_PCT / 100.0)
            trail_level = peak_p * (1.0 - TRAIL_DISTANCE_PCT / 100.0)
            # Başabaş altındaki kilit anlamsız: takipçi başabaşın altına inmesin
            new_stop = max(stop_p, lock_level, trail_level)
            if was_trailing:
                # Takipçi aktifken stop ASLA geri gitmez
                new_stop = max(stop_p, new_stop)
            stop_p = new_stop

        status = "OPEN"
        exit_price = None
        exit_time = None
        net_try = 0.0
        pos_size = float(row["trade_size_try"] or TRADE_SIZE_TRY)
        comm_try = row["commission_try"] or (pos_size * _one_way_fee() * 2)

        # Stop seviyesine indi mi? (TP kaldırıldı → tek fiyat bariyeri stop)
        if curr_p <= stop_p:
            # Gap-down modeli: fiyat stop'un ALTINDA açıldıysa gerçek dolum
            # stop fiyatından DEĞİL, o anki (daha kötü) fiyattan olur. Aksi
            # halde %0.9'luk stop, %2'lik kayba rağmen -%0.9 gösterirdi.
            fill_price = min(stop_p, curr_p)
            exit_price = fill_price
            exit_time = now_utc
            gross_diff = pos_size * ((fill_price - entry_p) / entry_p)
            net_try = gross_diff - comm_try
            # Kilit başabaşın üstündeyse kârla kapandı
            status = "WIN_TRAILING" if fill_price > entry_p else "LOSS_SL"

        # ─── YETERİNCE BEKLEME ─────────────────────────────────────────────
        # Konu kısa/uzun bekleme DEĞİL, YETERİNCE bekleme:
        #   • çok az bekleme → işlem tezine fırsat vermeden kesmek
        #   • gereksiz uzun bekleme → sermayeyi bağlayıp kaybettirmek
        #
        # İki kural bunu birlikte sağlar:
        #   1. Erken çıkış: EARLY_EXIT_MINUTES'tan sonra işlem HÂLÂ tezini
        #      göstermiyorsa (ne kâr var ne momentum) beklemenin anlamı yok.
        #      Yeterince bekledik; tez tutmadı.
        #   2. Azami tutma: her durumda tavan — süresiz bekletme yok.
        #
        # Takipçi devredeyken (kâr kilitli, tez ÇALIŞTI) zaman baskısı yoktur;
        # kazananı kesmemek takipçinin amacıdır.
        elif not trailing_active:
            tf = row["timeframe"]
            age_min = (now_utc - row["detected_at"]).total_seconds() / 60.0
            early_min = EARLY_EXIT_MINUTES.get(tf, 60)
            max_min = MAX_HOLD_MINUTES.get(tf, 240)
            # Şu anki momentum: girişteki tez hâlâ geçerli mi?
            bars_5m = _fetch_klines(sym, "5m", limit=60)
            rsi_now = None
            if len(bars_5m) >= 20:
                try:
                    rsi_now = float(_rsi([float(b["close"]) for b in bars_5m], 14))
                except Exception:  # noqa: BLE001
                    rsi_now = None
            # İki kademeli "tez tutmadı" kontrolü:
            #   • ÖLÜ İŞLEM (dead): erken ama kesin. Süre EARLY_EXIT_DEAD_MINUTES'ı
            #     geçtiği hâlde kâr hâlâ ~0 ise piyasa tezi onaylamıyor.
            #     Bunu bekletmek sadece SL'ye kadar kaybı büyütür.
            #   • STALLED: daha geç, kayıp birikmiş. Kâr yok + momentum yok.
            dead_min = EARLY_EXIT_DEAD_MINUTES.get(tf, 30)
            dead = age_min >= dead_min and pnl_pct < 0.10
            stalled = (
                age_min >= early_min
                and pnl_pct < EARLY_EXIT_MIN_PROGRESS_PCT
                and (rsi_now is None or rsi_now < 50.0)
            )
            if dead or stalled or age_min >= max_min:
                exit_price = curr_p
                exit_time = now_utc
                net_try = (pos_size * (pnl_pct / 100.0)) - comm_try
                if net_try > 0:
                    status = "WIN_EXPIRED"
                elif dead and not stalled:
                    # Zamanında tepki gelmedi — "ölü işlem"
                    status = "EXPIRED"
                else:
                    status = "STALLED"
                reason = "olu_islem" if (dead and not stalled) else (
                    "momentum_yok" if stalled else "sure_doldu")
                logger.info(
                    "spot çıkış #%s %s: %s (yaş %.0f dk, pnl %.2f%%, rsi %s)",
                    row["id"], sym, reason, age_min, pnl_pct,
                    f"{rsi_now:.1f}" if rsi_now is not None else "-")

        if status != "OPEN":
            await conn.execute("""
                UPDATE spot_monitor_signals
                SET status = $1, exit_price = $2, exit_time = $3,
                    pnl_pct = $4, mfe_pct = $5, mae_pct = $6, net_pnl_try = $7,
                    stop_price = $8, trailing_active = $9, peak_price = $10
                WHERE id = $11
            """, status, exit_price, exit_time, pnl_pct, new_mfe, new_mae, net_try,
               stop_p, trailing_active, peak_p, row["id"])
            closed_ids.append(int(row["id"]))
        else:
            # Açık durumu anlık metriklerle ve güncellenmiş stop_price ile kaydet
            await conn.execute("""
                UPDATE spot_monitor_signals
                SET pnl_pct = $1, mfe_pct = $2, mae_pct = $3, stop_price = $4,
                    trailing_active = $5, peak_price = $6
                WHERE id = $7
            """, pnl_pct, new_mfe, new_mae, stop_p, trailing_active, peak_p, row["id"])

    return closed_ids


# İnceleme kuyruğu: kapanan pozisyonlar buraya girer, her tarama döngüsü
# sınırlı sayıda boşaltır. Neden kuyruk: LLM çağrısı 12 sn'ye kadar sürebilir
# ve tarama döngüsü 60 sn'de bir çalışır. Aynı anda 5 pozisyon kapanırsa seri
# inceleme tek başına döngüyü doldurur ve tarama gecikir — fiyat takibi
# (asıl iş) bundan zarar görür. Kuyruk, incelemeyi yavaşlatmadan tamamlar.
_pending_reviews: list[int] = []
SPOT_LLM_MAX_REVIEWS_PER_SCAN = 3


def _queue_llm_reviews(signal_ids: list[int]) -> None:
    """Kapanan pozisyonları inceleme kuyruğuna ekler (tekrarsız)."""
    for sid in signal_ids:
        if sid not in _pending_reviews:
            _pending_reviews.append(sid)


async def _attach_llm_reviews(signal_ids: list[int] | None = None) -> int:
    """Kuyruktan sınırlı sayıda pozisyon için LLM ikinci görüşü ekler (kayıt amaçlı).

    Bilinçli olarak İŞLEM ENGELLEMEZ: yalnızca `details.llm_review` alanı
    yazılır. Doğrulanmamış bir yargıcı işlem akışına bağlamak, ölçülmüş
    kanıta aykırı (22 özellikli AI kapı walk-forward'da bazı yenemedi).
    Önce gölge kayıt toplanır; kapı kararı ancak karşılaştırmadan sonra verilir.

    Ağ hatası/LLM yapılandırılmamış olması normal karşılanır: incelemesiz
    kalan sinyal sorun değil, yalnızca daha az veri demektir.
    """
    if signal_ids:
        _queue_llm_reviews(signal_ids)
    if not _pending_reviews:
        return 0
    batch = _pending_reviews[:SPOT_LLM_MAX_REVIEWS_PER_SCAN]
    del _pending_reviews[:len(batch)]

    written = 0
    try:
        from app import spot_llm_review
    except Exception as exc:  # noqa: BLE001
        logger.info("spot LLM inceleme modülü yüklenemedi: %s", exc)
        return 0

    conn = await get_db_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM spot_monitor_signals WHERE id = ANY($1::int[])", batch)
        for row in rows:
            details = row["details"]
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except (ValueError, TypeError):
                    details = {}
            details = details or {}
            # Zaten incelenmişse tekrar çağrı yapma (maliyet)
            if details.get("llm_review"):
                continue
            ctx = {
                "symbol": row["symbol"], "timeframe": row["timeframe"],
                "strategy": row["strategy"], "strategy_label": row["strategy_label"],
                "entry_price": row["entry_price"], "stop_price": row["stop_price"],
                "sl_pct": details.get("sl_pct"),
                "break_even_wr": details.get("break_even_wr"),
                "rsi": details.get("rsi"), "atr_pct": details.get("atr_pct"),
                "adx": details.get("adx"), "range_pct": details.get("range_pct"),
                "avg_vol_try": details.get("avg_vol_try"), "note": details.get("note"),
                "vol_z": (details.get("ml_features") or {}).get("vol_z"),
                "mfi": (details.get("ml_features") or {}).get("mfi"),
                "bb_width_pct": (details.get("ml_features") or {}).get("bb_width_pct"),
                "ml_hit_probability": details.get("ml_hit_probability"),
                "ml_target_pct": details.get("ml_target_pct"),
                "heuristic_flags": details.get("heuristic_flags"),
                "fee_mode": details.get("fee_mode"),
                "round_trip_pct": _round_trip_cost_pct(),
                "recent_results": {
                    "sonuc": row["status"],
                    "net_pnl_try": round(float(row["net_pnl_try"] or 0.0), 2),
                    "pnl_pct": round(float(row["pnl_pct"] or 0.0), 2),
                    "mfe_pct": round(float(row["mfe_pct"] or 0.0), 2),
                },
            }
            try:
                review = await spot_llm_review.review_signal(ctx, timeout=12.0)
            except Exception as exc:  # noqa: BLE001
                logger.info("spot LLM inceleme hatası #%s: %s", row["id"], exc)
                continue
            if not review:
                continue
            details["llm_review"] = review
            await conn.execute(
                "UPDATE spot_monitor_signals SET details = $1 WHERE id = $2",
                json.dumps(details), row["id"])
            written += 1
    finally:
        await conn.close()
    return written

async def get_spot_monitor_dashboard():
    """Frontend arayüzü için anlık sinyalleri, geçmişi, başarı oranını ve 5.000 TL portföy simülasyonunu döndürür."""
    conn = await get_db_conn()
    try:
        await _ensure_spot_schema(conn)
        # Eski mükerrer açık kayıtları temizle (aynı sembolde birden fazla OPEN varsa en eskisini tut, fazlalıkları sil)
        await conn.execute("""
            DELETE FROM spot_monitor_signals
            WHERE status = 'OPEN'
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM spot_monitor_signals
                  WHERE status = 'OPEN'
                  GROUP BY symbol
              )
        """)

        # 1. Tüm sinyaller
        rows = await conn.fetch("SELECT * FROM spot_monitor_signals ORDER BY detected_at DESC LIMIT 500")
        
        # 2. İstatistikler
        total_signals = len(rows)
        closed_signals = [r for r in rows if r["status"] != "OPEN"]
        open_signals = [r for r in rows if r["status"] == "OPEN"]

        win_count = len([r for r in closed_signals if (r["net_pnl_try"] or 0) > 0])
        loss_count = len([r for r in closed_signals if (r["net_pnl_try"] or 0) <= 0])
        win_rate = (win_count / len(closed_signals) * 100.0) if closed_signals else 0.0

        # 3. 5.000 TL Simüle Portföy Büyüklüğü
        # Her işlem 300 TL sabit; kâr/zararlar realized ve unrealized olarak eklenir.
        realized_pnl = sum([r["net_pnl_try"] or 0.0 for r in closed_signals])
        
        # Açık işlemlerin anlık kâr/zararı
        prices = _fetch_all_prices()
        unrealized_pnl = 0.0
        active_items = []

        for r in rows:
            curr_p = prices.get(r["symbol"], r["entry_price"])
            pnl_pct = ((curr_p - r["entry_price"]) / r["entry_price"]) * 100.0 if r["status"] == "OPEN" else (r["pnl_pct"] or 0.0)
            
            pos_sz = float(r["trade_size_try"] or TRADE_SIZE_TRY)
            if r["status"] == "OPEN":
                comm = r["commission_try"] or (pos_sz * _one_way_fee() * 2)
                item_net = (pos_sz * (pnl_pct / 100.0)) - comm
                unrealized_pnl += item_net

            det = json.loads(r["details"]) if isinstance(r["details"], str) else (r["details"] or {})
            # Takipçi durumu: devrede mi, zirve nerede, kilit ne kadar uzakta
            entry_p = float(r["entry_price"])
            trail_on = bool(_row_get(r, "trailing_active", False))
            peak_p = float(_row_get(r, "peak_price", entry_p) or entry_p)
            # ─── DİNAMİK SKORLAR ───────────────────────────────────────────
            # `details` giriş ANINDAKİ değerleri taşır (donmuş). Açık
            # pozisyonda bunları yeniden hesaplamak gerekir: yoksa RSI 30'da
            # giren bir işlem, RSI 70'e çıkmış olsa bile panelde hâlâ "30"
            # gösterir ve ölü sinyali canlı sanırız. Yalnızca AÇIK
            # pozisyonlar için ve sembol başına TEK istek (önbellekli).
            live = None
            if r["status"] == "OPEN":
                live = _live_indicator_snapshot(r["symbol"], entry_p)
            lock_price = entry_p * (1.0 + TRAIL_LOCK_PCT / 100.0) if trail_on else None
            trail_gap_pct = ((peak_p - curr_p) / peak_p * 100.0) if trail_on and peak_p > 0 else None
            active_items.append({
                "id": r["id"],
                "symbol": r["symbol"],
                "timeframe": r["timeframe"],
                "strategy": r["strategy"],
                "strategy_label": r["strategy_label"],
                "entry_price": r["entry_price"],
                "current_price": curr_p,
                "target_price": r["target_price"],
                "stop_price": r["stop_price"],
                "score": r["score"],
                "kdj_j": r["kdj_j"],
                "status": r["status"],
                "pnl_pct": round(pnl_pct, 2),
                "mfe_pct": round(r["mfe_pct"] or 0.0, 2),
                # ─── Zirve takipçi (TP yok) ───
                "trailing_active": trail_on,
                "peak_price": round(peak_p, 8),
                "lock_price": round(lock_price, 8) if lock_price else None,
                "trail_distance_pct": TRAIL_DISTANCE_PCT,
                "trail_gap_pct": round(trail_gap_pct, 2) if trail_gap_pct is not None else None,
                "locked_profit_pct": round(((float(r["stop_price"]) - entry_p) / entry_p) * 100.0, 2),
                "net_pnl_try": round(r["net_pnl_try"] or 0.0, 2) if r["status"] != "OPEN" else round((pos_sz * (pnl_pct / 100.0)) - (r["commission_try"] or (pos_sz * _one_way_fee() * 2)), 2),
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                "exit_time": r["exit_time"].isoformat() if r["exit_time"] else None,
                "details": det,
                # Girişteki değerler (referans; "ne zaman ne görülmüştü")
                "entry_scores": {
                    "octobot_consensus_pct": det.get("octobot_consensus_pct"),
                    "qlib_score": det.get("qlib_score"),
                    "vibe_category": det.get("vibe_category"),
                    "trap_warning": det.get("trap_warning"),
                    "rsi": det.get("rsi"),
                    "adx": det.get("adx"),
                },
                # CANLI değerler — açık pozisyonda her panel yenilemesinde
                # yeniden hesaplanır. `None` ise istatistik moduna düşer.
                "octobot_consensus_pct": (live or {}).get("octobot_consensus_pct",
                                                          det.get("octobot_consensus_pct", 84)),
                "octobot_signal": (live or {}).get("octobot_signal",
                                                   det.get("octobot_signal", "BUY")),
                "vibe_category": (live or {}).get("vibe_category",
                                                  det.get("vibe_category", "BULLISH_VIBE")),
                "trap_warning": (live or {}).get("trap_warning", det.get("trap_warning", "NONE")),
                "is_fomo_trap": (live or {}).get("is_fomo_trap", det.get("is_fomo_trap", False)),
                "qlib_score": (live or {}).get("qlib_score", det.get("qlib_score", 72.0)),
                "jesse_rr": det.get("jesse_rr", 2.2),
                "live_rsi": (live or {}).get("rsi"),
                "live_adx": (live or {}).get("adx"),
                "indicators_live": bool(live),
            })

        total_portfolio_try = INITIAL_PORTFOLIO_TRY + realized_pnl + unrealized_pnl
        portfolio_growth_pct = ((total_portfolio_try - INITIAL_PORTFOLIO_TRY) / INITIAL_PORTFOLIO_TRY) * 100.0

        open_positions_count = len(open_signals)
        in_positions_try = sum(float(r["trade_size_try"] or TRADE_SIZE_TRY) for r in open_signals)
        free_balance_try = max(0.0, (INITIAL_PORTFOLIO_TRY + realized_pnl) - in_positions_try)
        now_ts = time.time()
        next_ts = _next_scan_time if _next_scan_time > now_ts else (_last_scan_time + _scan_interval_sec if _last_scan_time > 0 else now_ts + _scan_interval_sec)

        return {
            "portfolio": {
                "initial_balance_try": INITIAL_PORTFOLIO_TRY,
                "current_balance_try": round(total_portfolio_try, 2),
                "free_balance_try": round(free_balance_try, 2),
                "in_positions_try": round(in_positions_try, 2),
                "realized_pnl_try": round(realized_pnl, 2),
                "unrealized_pnl_try": round(unrealized_pnl, 2),
                "growth_pct": round(portfolio_growth_pct, 2),
                "trade_size_try": TRADE_SIZE_TRY,
                "open_positions_count": open_positions_count
            },
            "metrics": {
                "total_signals": total_signals,
                "closed_count": len(closed_signals),
                "open_count": len(open_signals),
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate_pct": round(win_rate, 1)
            },
            "signals": active_items,
            # AI kapıları tarafından reddedilen sinyaller — eşiklerin değerini
            # ölçmenin tek yolu bu listeyi ileri yürütüp karşılaştırmaktır.
            "rejected_signals": _rejected_signals[-50:],
            "rejected_count": len(_rejected_signals),
            "fees": {
                "mode": FEE_MODE,
                "one_way": _one_way_fee(),
                "round_trip_pct": round(_round_trip_cost_pct(), 3),
                "schedules": {k: v["label"] for k, v in COMMISSION_SCHEDULES.items()},
            },
            "ai_gate": AI_GATE,
            "last_scan_time": _last_scan_time,
            "next_scan_time": next_ts,
            "scan_interval_sec": _scan_interval_sec
        }
    finally:
        await conn.close()

async def close_spot_position_manual(signal_id: int) -> dict:
    """Belirli bir açık simülatör pozisyonunu anlık piyasa fiyatından manuel kapatır."""
    conn = await get_db_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM spot_monitor_signals WHERE id = $1 AND status = 'OPEN'", signal_id)
        if not row:
            return {"success": False, "message": "Açık pozisyon bulunamadı veya zaten kapalı."}

        prices = _fetch_all_prices()
        curr_p = prices.get(row["symbol"], row["entry_price"])
        entry_p = row["entry_price"]
        pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0
        now_utc = datetime.now(timezone.utc)
        comm_try = row["commission_try"] or (TRADE_SIZE_TRY * _one_way_fee() * 2)
        gross_pnl = TRADE_SIZE_TRY * (pnl_pct / 100.0)
        net_try = gross_pnl - comm_try

        old_mfe = row["mfe_pct"] or 0.0
        old_mae = row["mae_pct"] or 0.0
        new_mfe = max(old_mfe, pnl_pct)
        new_mae = min(old_mae, pnl_pct)

        await conn.execute("""
            UPDATE spot_monitor_signals
            SET status = 'MANUAL_CLOSED', exit_price = $1, exit_time = $2,
                pnl_pct = $3, mfe_pct = $4, mae_pct = $5, net_pnl_try = $6
            WHERE id = $7
        """, curr_p, now_utc, pnl_pct, new_mfe, new_mae, net_try, signal_id)

        return {
            "success": True,
            "symbol": row["symbol"],
            "exit_price": curr_p,
            "net_pnl_try": round(net_try, 2),
            "pnl_pct": round(pnl_pct, 2)
        }
    finally:
        await conn.close()


async def close_all_spot_positions_manual() -> dict:
    """Tüm açık simülatör pozisyonlarını tek tuşla anlık fiyattan manuel kapatır."""
    conn = await get_db_conn()
    try:
        open_rows = await conn.fetch("SELECT * FROM spot_monitor_signals WHERE status = 'OPEN'")
        if not open_rows:
            return {"success": True, "count": 0, "message": "Kapatılacak açık pozisyon yok."}

        prices = _fetch_all_prices()
        now_utc = datetime.now(timezone.utc)
        closed_count = 0

        for row in open_rows:
            curr_p = prices.get(row["symbol"], row["entry_price"])
            entry_p = row["entry_price"]
            pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0
            comm_try = row["commission_try"] or (TRADE_SIZE_TRY * _one_way_fee() * 2)
            gross_pnl = TRADE_SIZE_TRY * (pnl_pct / 100.0)
            net_try = gross_pnl - comm_try

            old_mfe = row["mfe_pct"] or 0.0
            old_mae = row["mae_pct"] or 0.0
            new_mfe = max(old_mfe, pnl_pct)
            new_mae = min(old_mae, pnl_pct)

            await conn.execute("""
                UPDATE spot_monitor_signals
                SET status = 'MANUAL_CLOSED', exit_price = $1, exit_time = $2,
                    pnl_pct = $3, mfe_pct = $4, mae_pct = $5, net_pnl_try = $6
                WHERE id = $7
            """, curr_p, now_utc, pnl_pct, new_mfe, new_mae, net_try, row["id"])
            closed_count += 1

        return {
            "success": True,
            "count": closed_count,
            "message": f"{closed_count} açık pozisyon anlık piyasa fiyatından kapatıldı."
        }
    finally:
        await conn.close()


async def spot_monitor_background_loop():
    """Her 60 saniyede bir çalışan arka plan tarayıcısı."""
    global _monitor_running
    _monitor_running = True
    logger.info("Spot Monitor arka plan tarayıcısı başlatıldı.")
    _last_forward_eval = 0.0

    while _monitor_running:
        try:
            await run_single_scan()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Spot monitor döngü hatası: %s", exc)
        # Kapanan pozisyonların LLM incelemeleri burada, tarama bittikten
        # SONRA boşaltılır: fiyat takibi (asıl iş) LLM gecikmesinden etkilenmez.
        try:
            written = await _attach_llm_reviews()
            if written:
                logger.info("spot LLM incelemesi yazıldı: %s", written)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("spot LLM inceleme döngü hatası: %s", exc)
        # Dondurulmuş model ileri testi: ufku dolmuş tahminlerin sonucu
        # gerçek mumlardan ölçülür (10 dakikada bir yeterli).
        if time.time() - _last_forward_eval > 600:
            _last_forward_eval = time.time()
            try:
                from app import ml_forward_test
                res = await ml_forward_test.evaluate_pending(limit=300)
                if res.get("evaluated") or res.get("expired"):
                    logger.info("ileri test değerlendirme: %s", res)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ileri test değerlendirme hatası: %s", exc)
        await asyncio.sleep(60)

def start_spot_monitor_loop():
    loop = asyncio.get_event_loop()
    loop.create_task(spot_monitor_background_loop())
