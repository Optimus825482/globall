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
    _kdj, _supertrend, _ema_pullback_bounce, _stc, _zlmacd, _ema, _bb_kc_squeeze,
    _linreg_slope_turn, _rvol_tod_spike, _rsi, _atr, _bollinger, _adx,
    _aroon, _mfi, _linreg_slope_pct,
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
        "code": "squeeze_breakout",
        "label": "Trend + BB Sıkışma + Hacim Patlaması",
        "score": 98.0,
        "description": "EMA50 ana trendi içinde Bollinger-Keltner volatilite sıkışması sonrası %125+ hacim patlamasıyla üst bant kırılımı.",
        "evidence": "162.000 mum Lab Şampiyonu: 409 işlem, PF 1.56, +%37.15 Net Kâr (INJ PF 3.69, AVAX PF 2.65). "
                    "5m walk-forward: TP 1.0 / SL 1.5 → WR %66.1, PF 1.47 (OOS)",
        "timeframes": ["5m", "15m", "1h"],
        # 5m: spot_tpsl_optimizer.json 768 konfigürasyon taraması sonucu.
        # Canlı varsayılan (TP 1.4 / SL 0.9) basabas WR'si %42.6; geniş stop
        # (SL 1.5) bunu %33.3'e indirip WR'yi %42.6 → %66.1'e taşıyor.
        "tp_sl_override": {
            "5m": {"tp_pct": 1.0, "sl_pct": 1.5},
            "15m": {"tp_pct": 2.2, "sl_pct": 1.1},
        },
    },
    {
        "code": "zlmacd_momentum",
        "label": "Zero-Lag MACD + Momentum + Trend",
        "score": 94.0,
        "description": "ZLMACD histogramının sıfırı yukarı kesmesi + EMA20 ≥ EMA50 ana trend filtresi.",
        "evidence": "OP & Trend Şampiyonu: PF 2.17; hızlı momentum kırılımları",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "stc_cycle",
        "label": "Schaff Trend Cycle (STC Hacimli Dip)",
        "score": 92.0,
        "description": "STC'nin 25 seviyesinin altından yukarı kırılmasıyla hacimli döngüsel dip dönüş girişi.",
        "evidence": "SOL/LINK/NEAR şampiyonu: WinRate %64+, PF 2.79",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "ema_bounce",
        "label": "EMA 50 Sekmesi + KDJ Dip",
        "score": 90.0,
        "description": "Ana trend içinde EMA50 desteğine geri çekilme + KDJ dip teyidiyle sekme girişi.",
        "evidence": "Trend içi geri çekilme filtresi; güçlü boğa trendlerinde yüksek başarı",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "zlmacd_momentum",
        "label": "Zero-Lag MACD + Momentum",
        "score": 90.0,
        "description": "ZLMACD histogramının sıfırı yukarı kesmesi + EMA20 ≥ EMA50 trend filtresi.",
        "evidence": "OP şampiyonu: PF 2.17",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "supertrend_pullback",
        "label": "SuperTrend Pullback (KDJ Dip)",
        "score": 88.0,
        "description": "SuperTrend boğa yönündeyken KDJ dip kesişimiyle trend içi geri çekilme girişi.",
        "evidence": "SuperTrend(10, 3.0) dinamik ATR trend filtresi",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "linreg_slope_turn",
        "label": "LinReg Eğim Dönüşü + Hacim",
        "score": 86.0,
        "description": "Doğrusal regresyon eğiminin sıfırın üstüne çıkması (momentum dönüşü) + Volume Oscillator > 0 (alım hacmi baskın) + EMA50 trend filtresi.",
        "evidence": "Lab v3 (5m): WR %55.8, PF 1.53, 12/18 coin; 1500 bar H2 pozitif",
        "timeframes": ["5m", "15m", "1h"],
    },
    {
        "code": "rvol_tod_spike",
        "label": "Zaman-Çapalı RVOL Patlaması",
        "score": 84.0,
        "description": "Bar hacmi aynı saat-of-gün ortalamasının 2 katını aşarken kapanışın EMA20'yi yukarı kesmesi (kurumsal saat hacmi + momentum).",
        "evidence": "Lab v5 (5m, IS): WR %66.7, PF 2.61, 13/16 coin; 7/9 komşu plato pozitif; OOS ince örneklem",
        "timeframes": ["5m"],
        "tp_sl_override": {"5m": {"tp_pct": 2.0, "sl_pct": 1.2}},
    },
    {
        "code": "kdj_pure_dip",
        "label": "KDJ Saf Dip (J≤12)",
        "score": 82.0,
        "description": "KDJ J eğrisinin ekstrem aşırı satım bölgesinden (J≤12) yukarı sıçraması.",
        "evidence": "Ekstrem dip yakalayıcı destek kuralı",
        "timeframes": ["5m", "15m", "1h"],
    },
]

ACTIVE_STRATEGY_CODES = {s["code"] for s in ACTIVE_STRATEGIES}
# Strateji bazlı TP/SL override (walk-forward + OOS doğrulamasından geçen kademeler)
STRATEGY_TPSL_OVERRIDE = {s["code"]: s.get("tp_sl_override", {}) for s in ACTIVE_STRATEGIES}

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

                kdj = _kdj(highs, lows, closes, period=9, signal=3) or {}
                st = _supertrend(highs, lows, closes, period=10, factor=3.0) or {}
                ema = _ema_pullback_bounce(closes, lows, period=50, tolerance_pct=0.010) or {}
                stc = _stc(closes, period=10, fast=23, slow=50) or {}
                zl = _zlmacd(closes, fast=12, slow=26, signal=9) or {}
                sq = _bb_kc_squeeze(highs, lows, closes) or {}
                lr = _linreg_slope_turn(closes, volumes) or {}
                rv = _rvol_tod_spike(times_ms, closes, volumes) or {}
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
                ema_bounce = bool(ema.get("pullback_bounce"))
                dist_ema = ema.get("dist_pct")

                stc_dip = bool(stc.get("dip_buy"))
                stc_val = float(stc.get("stc", 50.0))

                sq_break = bool(sq.get("breakout"))
                sq_bb_up = float(sq.get("bb_upper", 0.0))
                sq_width = float(sq.get("bb_width_pct", 0.0))

                zl_cross = bool(zl.get("bullish_cross"))
                zl_hist = float(zl.get("hist", 0.0))
                trend_bull = bool(ema20 is not None and ema50 is not None and ema20 >= ema50)

                matched = False
                strategy_code = ""
                strategy_label = ""
                score = 70.0
                note = ""

                # 1. Trend + BB-KC Sıkışma + Hacim Patlaması (162.000 Mum Lab Şampiyonu PF 1.56, +%37.15 Net Kâr)
                if sq_break and trend_bull and (vols[-1] >= avg_vol * 1.25) and enabled.get("squeeze_breakout", True):
                    matched = True
                    strategy_code = "squeeze_breakout"
                    strategy_label = "Trend + BB Sıkışma + Hacim Patlaması"
                    score = 98.0
                    note = f"EMA50 ustu BB-KC sikisma kirilimi + Hacim {vols[-1]/avg_vol:.2f}x (BBU={sq_bb_up:.6g})"

                # 2. Zero-Lag MACD + EMA 20/50 Momentum Sıçraması (OP/AVAX Şampiyonu PF 2.17)
                elif zl_cross and trend_bull and enabled.get("zlmacd_momentum", True):
                    matched = True
                    strategy_code = "zlmacd_momentum"
                    strategy_label = "Zero-Lag MACD + Momentum + Trend"
                    score = 94.0
                    note = f"ZLMACD sıfırı yukarı kesti (Hist={zl_hist:.4f}), EMA20>=EMA50"

                # 3. Schaff Trend Cycle (STC) Hacimli Dip Dönüşü
                elif stc_dip and (vols[-1] >= avg_vol * 1.15) and enabled.get("stc_cycle", True):
                    matched = True
                    strategy_code = "stc_cycle"
                    strategy_label = "Schaff Trend Cycle (STC Hacimli Dip)"
                    score = 92.0
                    note = f"STC 25 altından yukarı kırdı (STC={stc_val:.1f}), Hacim={vols[-1]/avg_vol:.2f}x"

                # 4. EMA 50 Pullback Bounce + KDJ Dip
                elif ema_bounce and (dip_buy or j_val <= 25.0) and trend_bull and enabled.get("ema_bounce", True):
                    matched = True
                    strategy_code = "ema_bounce"
                    strategy_label = "EMA 50 Sekmesi + KDJ Dip"
                    score = 90.0
                    note = f"EMA50 desteginde (%{dist_ema}), KDJ J={j_val:.1f}"

                # 5. SuperTrend Boğada KDJ Dip Kesişimi
                elif st_bull and dip_buy and enabled.get("supertrend_pullback", True):
                    matched = True
                    strategy_code = "supertrend_pullback"
                    strategy_label = "SuperTrend Pullback (KDJ Dip)"
                    score = 88.0
                    note = f"SuperTrend Boğada, KDJ J={j_val:.1f} yukarı kesti"

                # 6. LinReg Eğim Dönüşü + Hacim (Lab v3: 5m WR %55.8, PF 1.53, 1500 bar H2 pozitif)
                elif lr.get("slope_turn") and enabled.get("linreg_slope_turn", True):
                    matched = True
                    strategy_code = "linreg_slope_turn"
                    strategy_label = "LinReg Eğim Dönüşü + Hacim"
                    score = 86.0
                    note = f"LinReg egim sifir ustu donus (slope={lr.get('slope', 0):.3f}), VolOsc={lr.get('vo', 0):.1f}, EMA50 ustu"

                # 7. Zaman-Çapalı RVOL Patlaması (Lab v5: sadece 5m kanıtlı, TP2.0/SL1.2)
                elif rv.get("signal") and tf == "5m" and enabled.get("rvol_tod_spike", True):
                    matched = True
                    strategy_code = "rvol_tod_spike"
                    strategy_label = "Zaman-Çapalı RVOL Patlaması"
                    score = 84.0
                    note = f"Saat-bazli RVOL={rv.get('rvol', 0):.1f}x patlamasi, EMA20 ustu kesisme"

                # 8. KDJ Ekstrem Saf Dip Dönüşü
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

        # Süre Aşımı (5m için 60 dk, 15m için 150 dk, 1h için 360 dk)
        # Takipçi devredeyse süre aşımı UYGULANMAZ — kazanan işlemi kesmemek
        # takipçinin amacıdır. Yalnızca kâra geçmemiş pozisyonlar zamanla kapanır.
        elif not trailing_active and (now_utc - row["detected_at"]).total_seconds() > (3600 if row["timeframe"] == "5m" else (9000 if row["timeframe"] == "15m" else 21600)):
            exit_price = curr_p
            exit_time = now_utc
            gross_ret = pos_size * (pnl_pct / 100.0)
            net_try = gross_ret - comm_try
            status = "WIN_EXPIRED" if net_try > 0 else "EXPIRED"

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
                "octobot_consensus_pct": det.get("octobot_consensus_pct", 84),
                "octobot_signal": det.get("octobot_signal", "BUY"),
                "vibe_category": det.get("vibe_category", "BULLISH_VIBE"),
                "trap_warning": det.get("trap_warning", "NONE"),
                "is_fomo_trap": det.get("is_fomo_trap", False),
                "qlib_score": det.get("qlib_score", 72.0),
                "jesse_rr": det.get("jesse_rr", 2.2)
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
