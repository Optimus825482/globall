"""Combo3 (M5, yalnız altın) giriş kolu — replay `scripts/replay_strateji_gunluk.py`
`combo3` stratejisinin canlı karşılığı (2026-10-28).

Kural (kapanmış M5 barları, look-ahead yok; karar barı dizinin son elemanı):
  ut_bot        : UT Bot iz süren stop (ATR(10) × 1.0); kapanış stopu yukarı keserse BUY,
                  aşağı keserse SELL.
  donch_vortex  : kapanış önceki barın Donchian(20) üstünü aşarsa ve VI+ > VI− → BUY;
                  altını kırarsa ve VI− > VI+ → SELL.
  vortex_adx    : VI+(14) / VI−(14) kesişimi (ADX kapısı motorun genel ADX kalkanıdır).
  combo3        : üçünün birleşimi; ilk ateşleyen yön (sıra: ut_bot, donch_vortex, vortex).
Çıkış: SL = sl_atr × ATR(14) (Wilder), TP = tp_r × SL. BE/trailing motorun.

Replay kanıtı (docs/REPLAY_STRATEJI_TARAMA_2026_10_27.md): yalnız XAUUSD, risk %20,
14 hafta 83 günün 33'ü ≥ +%50; AMA 2 pip kayma ile PF 1.81 → 1.09. Bu yüzden canlıya
DÜŞÜK riskle (varsayılan %1) ve KAYMA ÖLÇÜMÜ ile alınır; risk artırımı ölçüme bağlıdır.

Bu modül saf fonksiyonlardan oluşur (test edilebilir); forex.py canlı döngüde çağırır.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

COMBO3_ENTRY_SOURCE = "combo3_m5"
COMBO3_STRATEGY = "COMBO3_M5"
COMBO3_LABEL = "Combo3 UTBot+Donchian/Vortex (M5)"
COMBO3_COMMENT_TAG = "CMB3"
MIN_BARS = 60


def _f(bar: Dict[str, Any], key: str) -> float:
    return float(bar.get(key) or 0.0)


def atr_wilder(bars: List[Dict[str, Any]], period: int = 14) -> List[Optional[float]]:
    """TradingView ta.atr: TR'nin RMA'sı (ilk değer SMA tohumu)."""
    n = len(bars)
    tr: List[Optional[float]] = [None] * n
    for i in range(1, n):
        pc = _f(bars[i - 1], "close")
        h, l = _f(bars[i], "high"), _f(bars[i], "low")
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out
    seed = sum(tr[1:period + 1]) / period  # type: ignore[arg-type]
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period  # type: ignore[operator]
        out[i] = prev
    return out


def ut_bot_stop(bars: List[Dict[str, Any]], key: float = 1.0, period: int = 10) -> List[Optional[float]]:
    """QuantNomad UT Bot iz süren stop (replay ut_bot ile birebir)."""
    a = atr_wilder(bars, period)
    stop: List[Optional[float]] = [None] * len(bars)
    for i in range(1, len(bars)):
        if a[i] is None:
            continue
        loss = key * a[i]  # type: ignore[operator]
        src, prev_src, prev = _f(bars[i], "close"), _f(bars[i - 1], "close"), stop[i - 1]
        if prev is None:
            stop[i] = src - loss
        elif src > prev and prev_src > prev:
            stop[i] = max(prev, src - loss)
        elif src < prev and prev_src < prev:
            stop[i] = min(prev, src + loss)
        elif src > prev:
            stop[i] = src - loss
        else:
            stop[i] = src + loss
    return stop


def vortex(bars: List[Dict[str, Any]], period: int = 14):
    """TV Vortex: VI+ = Sum(|H − L[1]|, n) / Sum(TR, n); VI− = Sum(|L − H[1]|, n) / Sum(TR, n)."""
    n = len(bars)
    tr = [0.0] * n
    vmp = [0.0] * n
    vmm = [0.0] * n
    for i in range(1, n):
        h, l, pc = _f(bars[i], "high"), _f(bars[i], "low"), _f(bars[i - 1], "close")
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
        vmp[i] = abs(h - _f(bars[i - 1], "low"))
        vmm[i] = abs(l - _f(bars[i - 1], "high"))
    vip: List[Optional[float]] = [None] * n
    vim: List[Optional[float]] = [None] * n
    for i in range(period, n):
        st = sum(tr[i - period + 1:i + 1])
        if st > 0:
            vip[i] = sum(vmp[i - period + 1:i + 1]) / st
            vim[i] = sum(vmm[i - period + 1:i + 1]) / st
    return vip, vim


def donchian(bars: List[Dict[str, Any]], period: int = 20):
    n = len(bars)
    hi: List[Optional[float]] = [None] * n
    lo: List[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        win = bars[i - period + 1:i + 1]
        hi[i] = max(_f(b, "high") for b in win)
        lo[i] = min(_f(b, "low") for b in win)
    return hi, lo


def _cross_up(fast, slow, i: int) -> bool:
    a, b, c, d = fast[i - 1], slow[i - 1], fast[i], slow[i]
    return None not in (a, b, c, d) and a <= b and c > d


def _cross_down(fast, slow, i: int) -> bool:
    a, b, c, d = fast[i - 1], slow[i - 1], fast[i], slow[i]
    return None not in (a, b, c, d) and a >= b and c < d


def combo3_sides(bars: List[Dict[str, Any]]) -> Dict[str, int]:
    """Karar barı (son eleman) için üç alt kuralın yönü: +1 BUY, −1 SELL, 0 yok."""
    i = len(bars) - 1
    out = {"ut_bot": 0, "donch_vortex": 0, "vortex_adx": 0}
    if i < MIN_BARS:
        return out
    c, pc = _f(bars[i], "close"), _f(bars[i - 1], "close")
    ut = ut_bot_stop(bars)
    if ut[i] is not None and ut[i - 1] is not None:
        if pc <= ut[i - 1] and c > ut[i]:  # type: ignore[operator]
            out["ut_bot"] = 1
        elif pc >= ut[i - 1] and c < ut[i]:  # type: ignore[operator]
            out["ut_bot"] = -1
    vip, vim = vortex(bars, 14)
    hi, lo = donchian(bars, 20)
    if None not in (hi[i - 1], lo[i - 1], vip[i], vim[i]):
        if c > hi[i - 1] and vip[i] > vim[i]:  # type: ignore[operator]
            out["donch_vortex"] = 1
        elif c < lo[i - 1] and vim[i] > vip[i]:  # type: ignore[operator]
            out["donch_vortex"] = -1
    if _cross_up(vip, vim, i):
        out["vortex_adx"] = 1
    elif _cross_down(vip, vim, i):
        out["vortex_adx"] = -1
    return out


def combo3_entry(bars: Optional[List[Dict[str, Any]]], pip_size: float,
                 sl_atr: float = 1.5, tp_r: float = 2.0) -> Optional[Dict[str, Any]]:
    """Kapanmış M5 barlarından Combo3 adayı. None = aday yok.

    Döner: {"action", "sl_pips", "tp_pips", "atr", "close", "bar_time", "sub", "which"}.
    """
    if not bars or len(bars) <= MIN_BARS or pip_size <= 0:
        return None
    sides = combo3_sides(bars)
    which = next((k for k in ("ut_bot", "donch_vortex", "vortex_adx") if sides[k]), None)
    if which is None:
        return None
    side = sides[which]
    i = len(bars) - 1
    atr = atr_wilder(bars, 14)[i]
    if atr is None or atr <= 0:
        return None
    sl_pips = round(float(sl_atr) * atr / pip_size, 1)
    if sl_pips <= 0 or math.isnan(sl_pips):
        return None
    return {
        "action": "BUY" if side == 1 else "SELL",
        "sl_pips": sl_pips,
        "tp_pips": round(sl_pips * float(tp_r), 1),
        "atr": float(atr),
        "close": _f(bars[i], "close"),
        "bar_time": int(bars[i].get("time") or 0),
        "sub": sides,
        "which": which,
    }


def slippage_record(cmd: Dict[str, Any], result: Dict[str, Any], pip_size: float) -> Optional[Dict[str, Any]]:
    """Köprü emir sonucundan kayma kaydı üretir (pip, pozitif = aleyhe).

    signal_slip : fill − sinyal barı kapanışı (yön düzeltmeli) → karar→fill toplam maliyeti
    exec_slip   : fill − istek fiyatı (tick) → broker icra kayması
    spread_*    : sinyal anı ve icra anı spread (pip)
    """
    try:
        fill = result.get("fill_price")
        req_price = result.get("req_price")
        if fill is None or pip_size <= 0:
            return None
        fill = float(fill)
        direction = str(cmd.get("direction") or result.get("direction") or "").upper()
        sgn = 1.0 if direction == "BUY" else -1.0
        sig_px = cmd.get("signal_price") if cmd.get("signal_price") is not None else result.get("signal_price")
        rec: Dict[str, Any] = {
            "ts": float(result.get("exec_ts") or 0.0),
            "symbol": str(cmd.get("symbol") or result.get("symbol") or "").upper(),
            "direction": direction,
            "entry_source": cmd.get("entry_source") or result.get("entry_source") or "",
            "strategy_tag": cmd.get("strategy_tag") or result.get("strategy_tag") or "",
            "lots": float(cmd.get("lots") or result.get("lots") or 0.0),
            "fill_price": fill,
            "req_price": None if req_price is None else float(req_price),
            "signal_price": None if sig_px is None else float(sig_px),
            "signal_bar_time": cmd.get("signal_bar_time") or result.get("signal_bar_time"),
            "created_ts": cmd.get("created_ts") or result.get("created_ts"),
            "spread_pips_signal": cmd.get("spread_pips_signal") if cmd.get("spread_pips_signal") is not None else result.get("spread_pips_signal"),
            "spread_pips_exec": result.get("spread_pips_exec"),
            "latency_ms": result.get("latency_ms"),
            "retcode": result.get("retcode"),
            "ticket": result.get("ticket"),
        }
        if req_price is not None:
            rec["exec_slip_pips"] = round(sgn * (fill - float(req_price)) / pip_size, 2)
        if sig_px is not None:
            rec["signal_slip_pips"] = round(sgn * (fill - float(sig_px)) / pip_size, 2)
        if rec.get("created_ts") and rec["ts"]:
            rec["decision_to_fill_sec"] = round(rec["ts"] - float(rec["created_ts"]), 2)
        return rec
    except Exception:
        return None


def slippage_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Etiket bazında kayma/spread özeti (ortalama, medyan, p90, adet)."""
    def _stats(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"n": 0}
        s = sorted(vals)
        n = len(s)
        return {
            "n": n,
            "mean": round(sum(s) / n, 2),
            "median": round(s[n // 2], 2),
            "p90": round(s[min(n - 1, int(0.9 * (n - 1)))], 2),
            "max": round(s[-1], 2),
            "min": round(s[0], 2),
        }

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(str(r.get("strategy_tag") or r.get("entry_source") or "?"), []).append(r)
    out: Dict[str, Any] = {}
    for tag, rows in groups.items():
        out[tag] = {
            "trades": len(rows),
            "exec_slip_pips": _stats([float(r["exec_slip_pips"]) for r in rows if r.get("exec_slip_pips") is not None]),
            "signal_slip_pips": _stats([float(r["signal_slip_pips"]) for r in rows if r.get("signal_slip_pips") is not None]),
            "spread_pips_exec": _stats([float(r["spread_pips_exec"]) for r in rows if r.get("spread_pips_exec") is not None]),
            "latency_ms": _stats([float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]),
            "decision_to_fill_sec": _stats([float(r["decision_to_fill_sec"]) for r in rows if r.get("decision_to_fill_sec") is not None]),
        }
    return out
