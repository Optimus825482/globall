"""Portföy risk katmanı (2026-10-30; araştırma raporu: Alan 3 + kart 2.4 + kart 1.6).

LLM'den BAĞIMSIZ, deterministik kapı: yeni girişten önce portföyün durumuna bakar.
  - Maruziyet: pozisyonlar para birimi bacaklarına ayrılır (EURUSD BUY = +EUR −USD), USD net riski.
  - Isı (heat): stop'a kadar toplam risk / özsermaye, SL'siz pozisyon = sınırsız risk.
  - Drawdown merdiveni: tepeden düşüş arttıkça lot çarpanı ×0.75/×0.5/×0.25, günlük/haftalık limit, kill switch.
  - Maliyet-R: (spread + komisyon) / stop; stop ≥ k×spread; saatlik spread yüzdeliği.
  - Kaybedene ekleme yasağı (ortalama düşürme/martingale).

Modlar (`risk_gate_mode`): off | shadow (VARSAYILAN: yalnız günlüğe yazar, motoru değiştirmez) | enforce.
KILL SWITCH elle açılırsa (`risk_kill_switch`) mod ne olursa olsun yeni giriş engellenir.
Eşikler araştırmada KAYNAKSIZ başlangıç değerleridir; önce gölge modda kalibre edilmelidir.
"""
from __future__ import annotations

import json
import logging
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("scalper.portfolio_risk")

CONTRACT_SIZE = {"XAU": 100.0, "XAG": 5000.0, "BTC": 1.0, "ETH": 1.0}
FX_CODES = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY")
DD_LADDER = ((8.0, 0.25), (5.0, 0.50), (3.0, 0.75))     # (tepeden düşüş %, lot çarpanı)
HYSTERESIS_PCT = 1.0
PEAK_WINDOW_DAYS = 30
SPREAD_MIN_SAMPLES = 30
SPREAD_PCTL = 0.90


# --------------------------------------------------------------------------- maruziyet

def contract_size(symbol: str) -> float:
    sym = symbol.upper()
    for k, v in CONTRACT_SIZE.items():
        if sym.startswith(k):
            return v
    if sym in ("USTEC", "NAS100", "US30", "US100", "NDX", "DJ30", "WS30"):
        return 1.0
    return 100000.0


def legs_of(symbol: str) -> Tuple[str, str]:
    """(taban, karşı) para birimi/varlık. XAUUSD → (XAU, USD); BTCUSD → (BTC, USD); EURJPY → (EUR, JPY)."""
    sym = symbol.upper()
    if len(sym) == 6 and sym[:3] in FX_CODES and sym[3:] in FX_CODES:
        return sym[:3], sym[3:]
    for k in CONTRACT_SIZE:
        if sym.startswith(k):
            return k, "USD"
    return sym, "USD"


def usd_per_unit(ccy: str, prices: Dict[str, float]) -> Optional[float]:
    """1 birim para biriminin USD karşılığı (canlı fiyatlardan)."""
    if ccy == "USD":
        return 1.0
    direct = prices.get(ccy + "USD")
    if direct:
        return float(direct)
    inv = prices.get("USD" + ccy)
    if inv:
        return 1.0 / float(inv)
    return None


def position_notional_usd(symbol: str, lots: float, prices: Dict[str, float]) -> Optional[float]:
    base, _quote = legs_of(symbol)
    unit = usd_per_unit(base, prices)
    if unit is None:
        return None
    return abs(lots) * contract_size(symbol) * unit


def exposure_matrix(positions: List[Dict[str, Any]], prices: Dict[str, float]) -> Dict[str, Any]:
    """Net USD-notional bacak maruziyeti: {EUR: +x, USD: −x, XAU: +y, ...}."""
    legs: Dict[str, float] = defaultdict(float)
    missing: List[str] = []
    for p in positions or []:
        sym = str(p.get("symbol", "")).upper()
        sign = 1.0 if str(p.get("direction", "")).upper() == "BUY" else -1.0
        n = position_notional_usd(sym, float(p.get("lots", 0) or 0), prices)
        if n is None:
            missing.append(sym)
            continue
        base, quote = legs_of(sym)
        legs[base] += sign * n
        legs[quote] -= sign * n
    gross = sum(abs(v) for v in legs.values())
    return {"legs": {k: round(v, 2) for k, v in sorted(legs.items(), key=lambda kv: -abs(kv[1]))},
            "usd_net": round(legs.get("USD", 0.0), 2), "gross": round(gross, 2), "missing_prices": sorted(set(missing))}


# --------------------------------------------------------------------------- ısı (heat)

def position_risk_usd(p: Dict[str, Any], pip_size: float, pip_val: float) -> Tuple[float, bool]:
    """(stop'a kadar risk $, SL_yok_mu). Kâr kilitleyen stop (BUY'da SL>giriş) risk 0 sayılır."""
    sl = float(p.get("sl_price", 0) or 0)
    if sl <= 0:
        return 0.0, True
    entry = float(p.get("entry_price", 0) or 0)
    sign = 1.0 if str(p.get("direction", "")).upper() == "BUY" else -1.0
    dist = sign * (entry - sl)                       # >0: stop girişin kayıp tarafında
    if dist <= 0 or pip_size <= 0:
        return 0.0, False
    return (dist / pip_size) * pip_val * float(p.get("lots", 0) or 0), False


def portfolio_heat(positions: List[Dict[str, Any]], equity: float,
                   specs: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
    by_symbol: Dict[str, float] = defaultdict(float)
    by_ccy: Dict[str, float] = defaultdict(float)
    usd_signed = 0.0
    unlimited: List[Any] = []
    total = 0.0
    for p in positions or []:
        sym = str(p.get("symbol", "")).upper()
        spec = specs(sym) or {}
        risk, no_sl = position_risk_usd(p, float(spec.get("pip_size") or 0), float(spec.get("pip_val") or 0))
        if no_sl:
            unlimited.append(p.get("ticket"))
            continue
        total += risk
        by_symbol[sym] += risk
        base, quote = legs_of(sym)
        by_ccy[base] += risk
        by_ccy[quote] += risk
        sign = 1.0 if str(p.get("direction", "")).upper() == "BUY" else -1.0
        usd_signed += risk * (-sign if quote == "USD" else sign if base == "USD" else 0.0)
    eq = max(equity, 1e-9)
    return {"heat_usd": round(total, 2), "heat_pct": round(100.0 * total / eq, 2),
            "usd_net_risk_usd": round(usd_signed, 2), "usd_net_risk_pct": round(100.0 * usd_signed / eq, 2),
            "by_symbol": {k: round(v, 2) for k, v in by_symbol.items()},
            "by_currency": {k: round(v, 2) for k, v in by_ccy.items()}, "no_sl_tickets": unlimited}


# --------------------------------------------------------------------------- drawdown

def drawdown_state(equity: float, peak: float, day_start: float, week_start: float, prev_level: int = 0,
                   daily_limit_pct: float = 3.0, weekly_limit_pct: float = 6.0, kill_dd_pct: float = 12.0) -> Dict[str, Any]:
    """Saf fonksiyon: tepeden düşüş merdiveni + günlük/haftalık kayıp limitleri. level 0..4 (4 = kill)."""
    dd = max(0.0, 100.0 * (peak - equity) / peak) if peak > 0 else 0.0
    daily = 100.0 * (equity - day_start) / day_start if day_start > 0 else 0.0
    weekly = 100.0 * (equity - week_start) / week_start if week_start > 0 else 0.0
    level, mult = 0, 1.0
    thresholds = [(kill_dd_pct, 4, 0.0)] + [(thr, i, m) for i, (thr, m) in zip((3, 2, 1), DD_LADDER)]
    for thr, lvl, m in thresholds:
        # histerezis: bir üst seviyedeyken ancak eşiğin 1 puan altına inince inilir
        eff = thr - HYSTERESIS_PCT if prev_level >= lvl else thr
        if dd >= eff:
            level, mult = lvl, m
            break
    return {"dd_pct": round(dd, 2), "daily_pct": round(daily, 2), "weekly_pct": round(weekly, 2), "level": level,
            "mult": mult, "kill": level >= 4,
            "daily_breach": daily <= -abs(daily_limit_pct), "weekly_breach": weekly <= -abs(weekly_limit_pct)}


class RiskState:
    """Özsermaye tepesi (30 günlük kayan), gün/hafta başı özsermaye ve son seviye. Kalıcı (llm_settings.risk_state)."""

    def __init__(self) -> None:
        self.daily_max: Dict[str, float] = {}
        self.day_key = ""
        self.day_start = 0.0
        self.week_key = ""
        self.week_start = 0.0
        self.level = 0
        self.loaded = False

    def to_json(self) -> str:
        return json.dumps({"daily_max": self.daily_max, "day_key": self.day_key, "day_start": self.day_start,
                           "week_key": self.week_key, "week_start": self.week_start, "level": self.level})

    def load(self, raw: Optional[str]) -> None:
        try:
            d = json.loads(raw or "{}")
        except Exception:  # noqa: BLE001
            d = {}
        self.daily_max = {str(k): float(v) for k, v in (d.get("daily_max") or {}).items()}
        self.day_key, self.day_start = str(d.get("day_key") or ""), float(d.get("day_start") or 0)
        self.week_key, self.week_start = str(d.get("week_key") or ""), float(d.get("week_start") or 0)
        self.level = int(d.get("level") or 0)
        self.loaded = True

    def update(self, equity: float, now: float) -> bool:
        """Gün/hafta sınırlarını ve tepeyi günceller. Döner: durum değişti mi (kaydetmek için)."""
        dt = datetime.fromtimestamp(now, timezone.utc)
        day, week = dt.strftime("%Y-%m-%d"), f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        changed = False
        if day != self.day_key:
            self.day_key, self.day_start, changed = day, equity, True
        if week != self.week_key:
            self.week_key, self.week_start, changed = week, equity, True
        if equity > self.daily_max.get(day, 0.0):
            self.daily_max[day] = equity
            changed = True
        cutoff = datetime.fromtimestamp(now - PEAK_WINDOW_DAYS * 86400, timezone.utc).strftime("%Y-%m-%d")
        for k in [k for k in self.daily_max if k < cutoff]:
            self.daily_max.pop(k)
            changed = True
        return changed

    @property
    def peak(self) -> float:
        return max(self.daily_max.values()) if self.daily_max else 0.0


STATE = RiskState()


# --------------------------------------------------------------------------- spread istatistiği

_SPREADS: Dict[Tuple[str, int], deque] = defaultdict(lambda: deque(maxlen=300))


def record_spread(symbol: str, spread_pips: float, now: Optional[float] = None) -> None:
    if spread_pips and spread_pips > 0:
        hour = datetime.fromtimestamp(now or time.time(), timezone.utc).hour
        _SPREADS[(symbol.upper(), hour)].append(float(spread_pips))


def spread_percentile(symbol: str, hour: int, q: float = SPREAD_PCTL) -> Optional[float]:
    vals = sorted(_SPREADS.get((symbol.upper(), hour), ()))
    if len(vals) < SPREAD_MIN_SAMPLES:
        return None
    return vals[min(len(vals) - 1, int(math.ceil(q * len(vals))) - 1)]


# --------------------------------------------------------------------------- giriş kapısı

def evaluate_entry(ctx: Dict[str, Any], cfg: Dict[str, Any], account: Dict[str, Any], positions: List[Dict[str, Any]],
                   prices: Dict[str, float], specs: Callable[[str], Dict[str, Any]], state: RiskState,
                   now: Optional[float] = None) -> Dict[str, Any]:
    """Saf karar: {decision: allow|block, mult, reasons[{code,text}], metrics}. Mod/yürütme çağıranındır."""
    now = now or time.time()
    sym, direction = ctx["symbol"].upper(), ctx["direction"].upper()
    equity = float(account.get("equity") or account.get("balance") or 0.0)
    reasons: List[Dict[str, str]] = []
    metrics: Dict[str, Any] = {"equity": equity}

    # 1) Kill switch
    if cfg.get("kill_switch"):
        reasons.append({"code": "kill_switch", "text": "Kill switch AÇIK: yeni giriş yok"})

    # 2) Drawdown merdiveni + günlük/haftalık limit
    dd = drawdown_state(equity, state.peak or equity, state.day_start or equity, state.week_start or equity, state.level,
                        cfg.get("daily_loss_pct", 3.0), cfg.get("weekly_loss_pct", 6.0), cfg.get("kill_dd_pct", 12.0))
    metrics["drawdown"] = dd
    mult = dd["mult"]
    if dd["kill"]:
        reasons.append({"code": "kill_dd", "text": f"Tepeden düşüş %{dd['dd_pct']} ≥ kill eşiği: otomatik durdurma"})
    if dd["daily_breach"]:
        reasons.append({"code": "daily_loss", "text": f"Günlük kayıp %{dd['daily_pct']} limiti aştı"})
    if dd["weekly_breach"]:
        reasons.append({"code": "weekly_loss", "text": f"Haftalık kayıp %{dd['weekly_pct']} limiti aştı"})

    # 3) Isı ve USD net risk (yeni işlem dahil)
    spec = specs(sym) or {}
    pip_size, pip_val = float(spec.get("pip_size") or ctx.get("pip_size") or 0), float(spec.get("pip_val") or ctx.get("pip_val") or 0)
    lots = float(ctx.get("lots") or 0) * mult
    heat = portfolio_heat(positions, equity, specs)
    new_risk = float(ctx.get("sl_pips") or 0) * pip_val * lots
    metrics.update(heat=heat, new_trade_risk_usd=round(new_risk, 2), lots_after_mult=round(lots, 3))
    if equity > 0:
        total_after = heat["heat_usd"] + new_risk
        metrics["heat_after_pct"] = round(100.0 * total_after / equity, 2)
        if total_after > cfg.get("heat_limit_pct", 6.0) / 100.0 * equity:
            reasons.append({"code": "heat", "text": f"Portföy ısısı %{metrics['heat_after_pct']} > limit %{cfg.get('heat_limit_pct', 6.0)}"})
        base, quote = legs_of(sym)
        sign = 1.0 if direction == "BUY" else -1.0
        usd_sign = -sign if quote == "USD" else sign if base == "USD" else 0.0
        usd_after = heat["usd_net_risk_usd"] + usd_sign * new_risk
        metrics["usd_net_after_pct"] = round(100.0 * usd_after / equity, 2)
        if abs(usd_after) > cfg.get("usd_net_limit_pct", 3.0) / 100.0 * equity:
            reasons.append({"code": "usd_net", "text": f"Net USD riski %{metrics['usd_net_after_pct']} > limit %{cfg.get('usd_net_limit_pct', 3.0)}"})
    if heat["no_sl_tickets"]:
        reasons.append({"code": "no_sl", "text": f"{len(heat['no_sl_tickets'])} açık pozisyonda SL yok (sınırsız risk)"})

    # 4) Maliyet-R ve spread kapıları
    spread = float(ctx.get("spread_pips") or 0)
    sl_pips = float(ctx.get("sl_pips") or 0)
    if spread > 0 and sl_pips > 0:
        comm_pips = (float(ctx.get("comm_per_lot") or 0) / pip_val) if pip_val > 0 else 0.0
        cost_r = (spread + comm_pips) / sl_pips
        metrics.update(cost_r=round(cost_r, 3), spread_pips=round(spread, 2))
        if cost_r > cfg.get("cost_r_max", 0.25):
            reasons.append({"code": "cost_r", "text": f"Maliyet {cost_r:.2f}R > {cfg.get('cost_r_max', 0.25)}R (spread+komisyon / stop)"})
        if sl_pips < cfg.get("stop_spread_mult", 8.0) * spread:
            reasons.append({"code": "stop_vs_spread", "text": f"Stop {sl_pips:.0f}p < {cfg.get('stop_spread_mult', 8.0):.0f}× spread ({spread:.1f}p)"})
        hour = datetime.fromtimestamp(now, timezone.utc).hour
        p90 = spread_percentile(sym, hour)
        if p90 is not None:
            metrics["spread_p90"] = round(p90, 2)
            if spread > p90:
                reasons.append({"code": "spread_pctl", "text": f"Spread {spread:.1f}p bu saatin %{int(SPREAD_PCTL * 100)} yüzdeliğinin ({p90:.1f}p) üstünde"})

    # 5) Kaybedene ekleme yasağı (ortalama düşürme)
    if cfg.get("block_losing_adds", True):
        for p in positions or []:
            if (str(p.get("symbol", "")).upper() == sym and str(p.get("direction", "")).upper() == direction
                    and float(p.get("pnl_usd", 0) or 0) < 0):
                reasons.append({"code": "losing_add", "text": f"{sym} {direction} pozisyonu zararda: kaybedene ekleme yasak"})
                break

    # lot çarpanı sonrası taban kontrolü
    if mult < 1.0 and lots < 0.01 and float(ctx.get("lots") or 0) < 10:
        reasons.append({"code": "lot_floor", "text": f"Drawdown çarpanı ×{mult} sonrası lot < 0.01"})
    decision = "block" if reasons else "allow"
    if reasons and all(r["code"] in ("no_sl",) for r in reasons):
        decision = "block"
    return {"decision": decision, "mult": mult, "reasons": reasons, "metrics": metrics}


def adjust_lots(lots: float, mult: float) -> float:
    """Drawdown çarpanını lota uygular (0.01 adıma aşağı yuvarlama; büyük lotlarda tam sayı)."""
    new = lots * mult
    if lots >= 10:
        return float(max(1, int(new)))
    return round(math.floor(new * 100 + 1e-9) / 100.0, 2)


# --------------------------------------------------------------------------- MT5 durumuyla birleşik çağrı

def settings_cfg(settings: Any) -> Dict[str, Any]:
    g = lambda k, d: getattr(settings, k, d)  # noqa: E731
    return {"mode": g("risk_gate_mode", "shadow"), "kill_switch": bool(g("risk_kill_switch", False)),
            "heat_limit_pct": float(g("risk_heat_limit_pct", 6.0)), "usd_net_limit_pct": float(g("risk_usd_net_limit_pct", 3.0)),
            "daily_loss_pct": float(g("risk_daily_loss_pct", 3.0)), "weekly_loss_pct": float(g("risk_weekly_loss_pct", 6.0)),
            "kill_dd_pct": float(g("risk_kill_dd_pct", 12.0)), "cost_r_max": float(g("risk_cost_r_max", 0.25)),
            "stop_spread_mult": float(g("risk_stop_spread_mult", 8.0)), "block_losing_adds": bool(g("risk_block_losing_adds", True))}


async def refresh_state(equity: float, now: Optional[float] = None) -> RiskState:
    """Durumu DB'den bir kez yükler, güncel özsermayeyle günceller, değiştiyse kaydeder."""
    from app import database
    now = now or time.time()
    if not STATE.loaded:
        STATE.load(await database.get_llm_setting("risk_state", "{}"))
    if equity > 0 and STATE.update(equity, now):
        await database.set_llm_setting("risk_state", STATE.to_json())
    return STATE


def live_prices(fx: Any) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in (fx._LIVE_PRICES_CACHE or {}).items():
        try:
            out[str(k).upper()] = float(v)
        except (TypeError, ValueError):
            continue
    return out


async def check_entry(ctx: Dict[str, Any], settings: Any) -> Dict[str, Any]:
    """Motorun/fırsat taramasının çağırdığı giriş: karar + günlük + (enforce ise) engelleme bilgisi.

    Dönen: {blocked, mult, mode, enforced, decision, reasons, metrics}. `blocked` yalnız enforce modunda (ya da kill switch)
    True olabilir; shadow modda `decision` block olsa da `blocked` False kalır ve günlüğe 'would block' yazılır.
    """
    from app import database
    from app.routers import forex as fx

    cfg = settings_cfg(settings)
    mode = cfg["mode"]
    if mode == "off" and not cfg["kill_switch"]:
        return {"blocked": False, "mult": 1.0, "mode": mode, "enforced": False, "decision": "allow", "reasons": [], "metrics": {}}
    st = fx._MT5_STATE
    account = dict(st.get("account") or {})
    positions = list(st.get("open_positions") or [])
    equity = float(account.get("equity") or account.get("balance") or 0.0)
    state = await refresh_state(equity)
    ctx = {**ctx}
    if ctx.get("spread_pips"):
        record_spread(ctx["symbol"], float(ctx["spread_pips"]))
    res = evaluate_entry(ctx, cfg, account, positions, live_prices(fx), lambda s: fx.get_symbol_trading_specs(s), state)
    if res["metrics"]["drawdown"]["level"] != state.level:
        state.level = res["metrics"]["drawdown"]["level"]
        await database.set_llm_setting("risk_state", state.to_json())
    kill = cfg["kill_switch"]
    enforced = mode == "enforce" or kill
    blocked = enforced and res["decision"] == "block"
    if kill and not blocked:
        blocked = True
    if res["decision"] == "block" or res["mult"] < 1.0:
        try:
            await database.log_risk_gate({"symbol": ctx["symbol"], "direction": ctx["direction"], "lots": ctx.get("lots"),
                                          "mult": res["mult"], "decision": res["decision"], "mode": mode, "enforced": enforced,
                                          "reasons": res["reasons"], "metrics": res["metrics"]})
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk kapısı günlüğü yazılamadı: %s", exc)
    return {"blocked": blocked, "mult": res["mult"] if enforced else 1.0, "mode": mode, "enforced": enforced,
            "decision": res["decision"], "reasons": res["reasons"], "metrics": res["metrics"]}


async def snapshot(settings: Any) -> Dict[str, Any]:
    """Salt-okunur portföy görünümü (LLM aracı + rapor): maruziyet, ısı, drawdown, kapı modu."""
    from app.routers import forex as fx
    cfg = settings_cfg(settings)
    st = fx._MT5_STATE
    account = dict(st.get("account") or {})
    positions = list(st.get("open_positions") or [])
    equity = float(account.get("equity") or account.get("balance") or 0.0)
    state = await refresh_state(equity)
    prices = live_prices(fx)
    dd = drawdown_state(equity, state.peak or equity, state.day_start or equity, state.week_start or equity, state.level,
                        cfg["daily_loss_pct"], cfg["weekly_loss_pct"], cfg["kill_dd_pct"])
    heat = portfolio_heat(positions, equity, lambda s: fx.get_symbol_trading_specs(s))
    limit_usd = cfg["heat_limit_pct"] / 100.0 * equity
    return {"connected": bool(st.get("connected")), "account": {k: account.get(k) for k in ("balance", "equity", "margin", "free_margin", "leverage", "server")},
            "open_positions": len(positions), "exposure": exposure_matrix(positions, prices), "heat": heat, "drawdown": dd,
            "risk_budget_remaining_usd": round(max(0.0, limit_usd - heat["heat_usd"]), 2),
            "risk_budget_remaining_pct": round(max(0.0, cfg["heat_limit_pct"] - heat["heat_pct"]), 2),
            "gate": {"mode": cfg["mode"], "kill_switch": cfg["kill_switch"], "limits": {k: cfg[k] for k in (
                "heat_limit_pct", "usd_net_limit_pct", "daily_loss_pct", "weekly_loss_pct", "kill_dd_pct", "cost_r_max", "stop_spread_mult")}},
            "peak_equity": state.peak}


# --------------------------------------------------------------------------- stres senaryoları ve marj (kart 3.5)

STRESS_SCENARIOS = {
    "altin_-5": "Altın −%5",
    "usd_+2": "USD +%2 (USD-karşı pariteler düşer, USD-taban pariteler yükselir)",
    "btc_-15": "Bitcoin −%15",
    "risk_off": "Risk-off: JPY +%3, AUD/NZD −%2, altın +%2, BTC −%10",
    "hafta_sonu_bosluk": "Hafta sonu boşluğu: pozisyon aleyhine FX %0.6, altın %2 (stop boşluk fiyatından dolar)",
}
STRESS_LOSS_LIMIT_PCT = 5.0
STRESS_MARGIN_FLOOR_PCT = 300.0


def shock_pct(symbol: str, scenario: str) -> float:
    """Senaryoda sembol fiyatının yüzde değişimi (yön işaretli; hafta sonu boşluğu ayrı ele alınır)."""
    sym = symbol.upper()
    base, quote = legs_of(sym)
    if scenario == "altin_-5":
        return -5.0 if base == "XAU" else 0.0
    if scenario == "btc_-15":
        return -15.0 if base == "BTC" else 0.0
    if scenario == "usd_+2":
        if quote == "USD":
            return -2.0
        if base == "USD":
            return 2.0
        return 0.0
    if scenario == "risk_off":
        if base == "XAU":
            return 2.0
        if base == "BTC":
            return -10.0
        move = {"JPY": 3.0, "AUD": -2.0, "NZD": -2.0}
        return move.get(base, 0.0) - move.get(quote, 0.0)        # taban güçlenirse çift yükselir
    return 0.0


def stress_test(positions: List[Dict[str, Any]], equity: float, margin_used: float,
                specs: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
    """Anlık şoklar: senaryo başına zarar ($, % özsermaye) ve şok sonrası marj seviyesi."""
    out: Dict[str, Any] = {}
    for key, label in STRESS_SCENARIOS.items():
        total, worst = 0.0, (None, 0.0)
        for p in positions or []:
            sym = str(p.get("symbol", "")).upper()
            spec = specs(sym) or {}
            pip, pv = float(spec.get("pip_size") or 0), float(spec.get("pip_val") or 0)
            price = float(p.get("current_price") or p.get("entry_price") or 0)
            if pip <= 0 or pv <= 0 or price <= 0:
                continue
            sign = 1.0 if str(p.get("direction", "")).upper() == "BUY" else -1.0
            if key == "hafta_sonu_bosluk":
                if not is_weekend_symbol(sym):
                    continue
                gap = 0.02 if sym.startswith("XAU") else 0.006
                move_px = -sign * gap * price                      # pozisyon aleyhine
            else:
                move_px = shock_pct(sym, key) / 100.0 * price
            pnl = sign * move_px / pip * pv * float(p.get("lots", 0) or 0)
            total += pnl
            if pnl < worst[1]:
                worst = (f"{sym} {p.get('direction')}", pnl)
        eq_after = equity + total
        margin_level = (eq_after / margin_used * 100.0) if margin_used > 0 else None
        pct = 100.0 * total / equity if equity > 0 else 0.0
        breach = pct <= -STRESS_LOSS_LIMIT_PCT or (margin_level is not None and margin_level < STRESS_MARGIN_FLOOR_PCT)
        out[key] = {"label": label, "pnl_usd": round(total, 2), "pnl_pct": round(pct, 2),
                    "margin_level_after_pct": round(margin_level, 1) if margin_level is not None else None,
                    "worst_position": worst[0], "breach": bool(breach)}
    return out


def is_weekend_symbol(symbol: str) -> bool:
    return not symbol.upper().startswith(("BTC", "ETH"))


# --------------------------------------------------------------------------- işlem listesinde Monte Carlo (kart 3.6)

def monte_carlo_drawdown(r_values: List[float], risk_pct: float = 1.0, n_sims: int = 3000, block: int = 4,
                         horizon: Optional[int] = None, dd_limit_pct: float = 10.0, seed: int = 7) -> Dict[str, Any]:
    """R katında işlem sonuçlarının BLOK bootstrap'ı: maksimum düşüş dağılımı ve P(DD > limit).

    Blok bootstrap kayıp kümelenmesini korur (düz karıştırma yok eder). N < 50 → yetersiz veri.
    risk_pct: işlem başı riskin özsermaye yüzdesi (R → % dönüşümü).
    """
    import random
    n = len(r_values)
    if n < 50:
        return {"n": n, "ok": False, "note": "Yetersiz veri (<50 işlem): Monte Carlo güvenilmez, muhafazakâr varsayılan kullanın"}
    rng = random.Random(seed)
    horizon = horizon or min(n, 200)
    dds: List[float] = []
    for _ in range(n_sims):
        seq: List[float] = []
        while len(seq) < horizon:
            start = rng.randrange(0, n)
            seq.extend(r_values[(start + i) % n] for i in range(block))
        eq, peak, max_dd = 100.0, 100.0, 0.0
        for r in seq[:horizon]:
            eq *= 1.0 + r * risk_pct / 100.0
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)
        dds.append(max_dd)
    dds.sort()
    q = lambda p: dds[min(len(dds) - 1, int(p * len(dds)))]  # noqa: E731
    mean_r = sum(r_values) / n
    return {"n": n, "ok": True, "risk_pct": risk_pct, "horizon_trades": horizon, "mean_r": round(mean_r, 3),
            "dd_p50": round(q(0.5), 2), "dd_p90": round(q(0.9), 2), "dd_p95": round(q(0.95), 2), "dd_p99": round(q(0.99), 2),
            "p_dd_over_limit": round(sum(1 for d in dds if d > dd_limit_pct) / len(dds), 3), "dd_limit_pct": dd_limit_pct,
            "note": "Geçmiş işlem dağılımından türetilir; kenar yoksa/örneklem küçükse yanıltıcıdır."}


# --------------------------------------------------------------------------- boyut önerisi (kart 3.4)

def shrunk_win_rate_lower(wins: int, n: int, prior_p: float = 0.5, m: float = 30.0, z: float = 0.84) -> float:
    """Kazanma oranı için büzülmüş tahminin alt sınırı (~%80 tek yönlü): (kazanç + m·prior)/(n + m) − z·SE."""
    n = max(0, n)
    p = (wins + m * prior_p) / (n + m)
    se = (p * (1 - p) / (n + m)) ** 0.5
    return max(0.0, p - z * se)


def kelly_cap_pct(p_lower: float, rr: float, fraction: float = 0.25, n_trades: int = 0) -> float:
    """Kesirli Kelly üst sınırı (özsermaye %). N < 100 ise kesir 0.1-0.25 aralığına inmez: min(fraction, 0.15)."""
    if rr <= 0:
        return 0.0
    f = p_lower - (1 - p_lower) / rr
    frac = fraction if n_trades >= 100 else min(fraction, 0.15)
    return round(max(0.0, f * frac * 100.0), 6)


def sizing_suggestion(symbol: str, sl_pips: float, pip_val: float, equity: float, dd_mult: float, budget_remaining_usd: float,
                      base_risk_pct: float = 0.5, edge: Optional[Dict[str, Any]] = None, min_lot: float = 0.01,
                      lot_step: float = 0.01) -> Dict[str, Any]:
    """En kısıtlayıcı sınır kazanır: temel %risk × drawdown çarpanı, kalan ısı bütçesi, (varsa) kesirli Kelly tavanı.

    edge = {"wins", "n", "rr"}. Lot aşağı yuvarlanır; en küçük lot riski sınırın %20'sinden fazla aşıyorsa 0 (reddet).
    """
    if equity <= 0 or sl_pips <= 0 or pip_val <= 0:
        return {"lots": 0.0, "binding": "geçersiz girdi", "risk_usd": 0.0}
    limits = {"temel_risk": equity * base_risk_pct / 100.0 * dd_mult, "kalan_isi_butcesi": max(0.0, budget_remaining_usd)}
    if edge and edge.get("n", 0) > 0:
        pl = shrunk_win_rate_lower(int(edge.get("wins", 0)), int(edge["n"]))
        cap = kelly_cap_pct(pl, float(edge.get("rr", 1.5)), 0.25, int(edge["n"])) / 100.0 * equity
        limits["kesirli_kelly"] = cap
        limits["_p_lower"] = pl
    binding = min((k for k in limits if not k.startswith("_")), key=lambda k: limits[k])
    risk_usd = limits[binding]
    raw = risk_usd / (sl_pips * pip_val)
    lots = math.floor(raw / lot_step + 1e-9) * lot_step
    if lots < min_lot:
        floor_risk = min_lot * sl_pips * pip_val
        if floor_risk > risk_usd * 1.2:
            return {"lots": 0.0, "binding": binding, "risk_usd": 0.0, "reason": f"en küçük lot riski ${floor_risk:.2f} sınırı (${risk_usd:.2f}) %20'den fazla aşıyor",
                    "limits_usd": {k: round(v, 2) for k, v in limits.items() if not k.startswith("_")}}
        lots = min_lot
    return {"lots": round(lots, 2), "binding": binding, "risk_usd": round(lots * sl_pips * pip_val, 2),
            "limits_usd": {k: round(v, 2) for k, v in limits.items() if not k.startswith("_")},
            "win_rate_lower": round(limits.get("_p_lower", 0.0), 3) if "_p_lower" in limits else None}
