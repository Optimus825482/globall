"""MT5 Historical Data Fetcher & Replay Engine for Rejected Strategies.

Uses IC Markets MT5 terminal via MetaTrader5 Python API.
30-day causal replay for each rejected symbol/strategy pair.
"""
from __future__ import annotations

import datetime
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import MetaTrader5 as mt5

# ── Configuration ───────────────────────────────────────────────────────────
INITIAL_BALANCE = 10_000.0  # TRY paper balance
COMMISSION_PCT = 0.0035  # round-trip (0.35%)
SPREAD_PCT = 0.0002  # assumed spread 0.02%
SLIPPAGE_PCT = 0.0001  # assumed slippage 0.01%
ORDER_PCT = 0.05  # 5% of balance per trade
MT5_TIMEFRAMES = {
    "1m": mt5.TIMEFRAME_M1,
    "3m": mt5.TIMEFRAME_M3,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
    "1d": mt5.TIMEFRAME_D1,
}

# Symbol alias map (MT5 → our naming)
SYMBOL_ALIAS = {
    "USTEC": "NAS100",
    "US30": "US30",
    "XAUUSD": "XAUUSD",
    "BTCUSD": "BTCUSD",
}

# Reverse alias for MT5 lookup
MT5_SYMBOLS = {
    "NAS100": "USTEC",
    "US30": "US30",
    "XAUUSD": "XAUUSD",
    "BTCUSD": "BTCUSD",
    "NZDJPY": "NZDJPY",
    "AUDNZD": "AUDNZD",
    "GBPCHF": "GBPCHF",
    "EURCAD": "EURCAD",
    "CHFJPY": "CHFJPY",
    "CADJPY": "CADJPY",
    "GBPNZD": "GBPNZD",
    "GBPAUD": "GBPAUD",
    "GBPCAD": "GBPCAD",
    "AUDCAD": "AUDCAD",
    "EURAUD": "EURAUD",
    "CADCHF": "CADCHF",
    "AUDCHF": "AUDCHF",
    "GBPJPY": "GBPJPY",
    "EURJPY": "EURJPY",
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "USDCHF": "USDCHF",
    "AUDUSD": "AUDUSD",
}


@dataclass
class Bar:
    time: datetime.datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int


@dataclass
class Trade:
    entry_time: datetime.datetime
    entry_price: float
    direction: str
    quantity: float
    exit_time: Optional[datetime.datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    fees: float = 0.0


def mt5_symbol(sym: str) -> str:
    return MT5_SYMBOLS.get(sym.upper(), sym.upper())


def ensure_symbol_in_marketwatch(sym: str) -> bool:
    """Add symbol to Market Watch if not already there."""
    msym = mt5_symbol(sym)
    selected = mt5.symbol_select(msym, True)
    if not selected:
        # Try without suffix
        info = mt5.symbol_info(msym)
        if info is None:
            return False
    return True


def fetch_bars(sym: str, tf: str, days: int = 30) -> List[Bar]:
    """Fetch historical bars from MT5."""
    msym = mt5_symbol(sym)
    if not ensure_symbol_in_marketwatch(msym):
        raise RuntimeError(f"Symbol {msym} not available in MT5")

    mt5_tf = MT5_TIMEFRAMES.get(tf, mt5.TIMEFRAME_M5)
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    utc_from = utc_now - datetime.timedelta(days=days)

    rates = mt5.copy_rates_range(msym, mt5_tf, utc_from, utc_now)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data for {msym} {tf}")

    bars = []
    for r in rates:
        t = datetime.datetime.fromtimestamp(r["time"], tz=datetime.timezone.utc)
        bars.append(Bar(
            time=t,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            tick_volume=int(r["tick_volume"]),
        ))
    return bars


def donchian_channels(bars: List[Bar], period: int = 20) -> Tuple[List[float], List[float], List[float]]:
    """Donchian Channel: upper, lower, mid."""
    upper = []
    lower = []
    mid = []
    for i in range(len(bars)):
        if i < period - 1:
            upper.append(math.nan)
            lower.append(math.nan)
            mid.append(math.nan)
            continue
        window = bars[i - period + 1:i + 1]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        upper.append(hi)
        lower.append(lo)
        mid.append((hi + lo) / 2)
    return upper, lower, mid


def adx_series(bars: List[Bar], period: int = 14) -> List[float]:
    """Simplified ADX(14)."""
    tr_list = []
    plus_dm = []
    minus_dm = []
    for i in range(1, len(bars)):
        curr = bars[i]
        prev = bars[i - 1]
        tr = max(curr.high - curr.low, abs(curr.high - prev.close), abs(curr.low - prev.close))
        up = curr.high - prev.high
        down = prev.low - curr.low
        pdm = up if up > down and up > 0 else 0
        mdm = down if down > up and down > 0 else 0
        tr_list.append(tr)
        plus_dm.append(pdm)
        minus_dm.append(mdm)

    adx = [math.nan] * len(bars)
    if len(tr_list) < period * 2:
        return adx

    atr = sum(tr_list[:period]) / period
    pdi = sum(plus_dm[:period]) / period
    mdi = sum(minus_dm[:period]) / period

    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        pdi = (pdi * (period - 1) + plus_dm[i]) / period
        mdi = (mdi * (period - 1) + minus_dm[i]) / period
        if atr == 0:
            dx = 0
        else:
            p = 100 * pdi / atr
            m = 100 * mdi / atr
            dx = 100 * abs(p - m) / (p + m) if (p + m) > 0 else 0
        # ADX smoothing
        idx = i + 1
        if idx == period * 2:
            adx[idx] = dx
        elif idx > period * 2:
            prev_adx = adx[idx - 1] if not math.isnan(adx[idx - 1]) else dx
            adx[idx] = (prev_adx * (period - 1) + dx) / period
    return adx


def supertrend(bars: List[Bar], atr_period: int = 10, factor: float = 3.0) -> Tuple[List[float], List[int]]:
    """Simplified SuperTrend. Returns (st_line, direction). direction: 1=uptrend, -1=downtrend."""
    # ATR
    atr_vals = []
    for i in range(1, len(bars)):
        curr = bars[i]
        prev = bars[i - 1]
        tr = max(curr.high - curr.low, abs(curr.high - prev.close), abs(curr.low - prev.close))
        atr_vals.append(tr)

    atr_smoothed = []
    for i in range(len(atr_vals)):
        if i < atr_period - 1:
            atr_smoothed.append(math.nan)
        elif i == atr_period - 1:
            atr_smoothed.append(sum(atr_vals[:atr_period]) / atr_period)
        else:
            atr_smoothed.append((atr_smoothed[-1] * (atr_period - 1) + atr_vals[i]) / atr_period)

    # Basic HL2
    hl2 = [(b.high + b.low) / 2 for b in bars]

    st_line = [math.nan] * len(bars)
    direction = [0] * len(bars)

    for i in range(atr_period, len(bars)):
        if math.isnan(atr_smoothed[i - 1]):
            continue
        upper = hl2[i] + factor * atr_smoothed[i - 1]
        lower = hl2[i] - factor * atr_smoothed[i - 1]

        if i == atr_period:
            st_line[i] = upper if bars[i].close <= upper else lower
            direction[i] = -1 if bars[i].close <= upper else 1
        else:
            if bars[i].close > st_line[i - 1]:
                st_line[i] = lower
                direction[i] = 1
            else:
                st_line[i] = upper
                direction[i] = -1

    return st_line, direction


def rsi_series(closes: List[float], period: int = 14) -> List[float]:
    """RSI(14)."""
    rsi = [math.nan] * len(closes)
    if len(closes) < period + 1:
        return rsi

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return rsi


# ── Replay engines ──────────────────────────────────────────────────────────

def replay_donchian_adx(
    bars: List[Bar],
    sym: str,
    adx_min: float = 18.0,
    max_per_day: int = 2,
) -> Tuple[List[Trade], Dict]:
    """Donchian(20) + ADX(14) replay."""
    upper, lower, mid = donchian_channels(bars, 20)
    adx = adx_series(bars, 14)
    is_jpy = "JPY" in sym.upper()

    trades: List[Trade] = []
    position: Optional[Trade] = None
    day_counts: Dict[str, int] = {}
    cash = INITIAL_BALANCE
    equity = [cash]

    buy_cost = (SPREAD_PCT / 2 + SLIPPAGE_PCT)
    sell_cost = buy_cost

    for i in range(1, len(bars)):
        b = bars[i]
        prev = bars[i - 1]
        hour = b.time.hour
        day_key = b.time.strftime("%Y-%m-%d")

        if day_key not in day_counts:
            day_counts = {"BUY": 0, "SELL": 0}

        # Exit first (simple: next bar open)
        if position is not None:
            # Simple trailing: chandelier or ST — here just hold until opposite signal or end
            pass

        # Entry check
        if math.isnan(mid[i]) or math.isnan(adx[i]) or math.isnan(mid[i - 1]):
            continue

        if adx[i] < adx_min:
            continue

        if is_jpy:
            if not (0 <= hour < 16):
                continue
        else:
            if not (7 <= hour < 16):
                continue

        action = None
        if prev.close <= mid[i - 1] and b.close > mid[i]:
            if day_counts.get("BUY", 0) < max_per_day:
                action = "BUY"
        elif prev.close >= mid[i - 1] and b.close < mid[i]:
            if day_counts.get("SELL", 0) < max_per_day:
                action = "SELL"

        if action and position is None:
            order_value = cash * ORDER_PCT
            entry_fill = b.close * (1 + buy_cost)
            entry_fee = order_value * COMMISSION_PCT / 2
            if order_value + entry_fee > cash:
                order_value = cash / (1 + COMMISSION_PCT / 2)
                entry_fee = order_value * COMMISSION_PCT / 2
            qty = order_value / entry_fill
            cash -= order_value + entry_fee
            position = Trade(
                entry_time=b.time,
                entry_price=entry_fill,
                direction=action,
                quantity=qty,
            )
            day_counts[action] = day_counts.get(action, 0) + 1

        equity.append(cash + (position.quantity * b.close * (1 - sell_cost) if position else 0))

    # Close at end
    if position:
        last = bars[-1]
        exit_fill = last.close * (1 - sell_cost)
        proceeds = position.quantity * exit_fill
        exit_fee = proceeds * COMMISSION_PCT / 2
        cash += proceeds - exit_fee
        position.exit_time = last.time
        position.exit_price = exit_fill
        position.exit_reason = "end_of_data"
        position.pnl = proceeds - exit_fee - position.quantity * position.entry_price - (position.quantity * position.entry_price * COMMISSION_PCT / 2)
        position.fees = position.quantity * position.entry_price * COMMISSION_PCT / 2 + exit_fee
        trades.append(position)

    gross_profit = sum(max(t.pnl, 0) for t in trades)
    gross_loss = -sum(min(t.pnl, 0) for t in trades)
    peak = INITIAL_BALANCE
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    return trades, {
        "trades": len(trades),
        "wins": sum(1 for t in trades if t.pnl > 0),
        "losses": sum(1 for t in trades if t.pnl <= 0),
        "net_pnl": cash - INITIAL_BALANCE,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown": max_dd,
        "final_balance": cash,
    }


def replay_london_breakout(
    bars: List[Bar],
    sym: str,
    box_end_utc: int = 8,
    entry_end_utc: int = 11,
    max_per_day: int = 1,
) -> Tuple[List[Trade], Dict]:
    """London Breakout replay: Asia box (00:00-box_end) hi/lo, breakout in (box_end-entry_end)."""
    trades: List[Trade] = []
    position: Optional[Trade] = None
    cash = INITIAL_BALANCE
    equity = [cash]

    buy_cost = (SPREAD_PCT / 2 + SLIPPAGE_PCT)
    sell_cost = buy_cost

    day_box: Dict[str, Dict] = {}  # date -> {hi, lo, box_end_bar}
    day_counts: Dict[str, Dict[str, int]] = {}

    for i, b in enumerate(bars):
        day_key = b.time.strftime("%Y-%m-%d")
        hour = b.time.hour

        if day_key not in day_box:
            day_box[day_key] = {"hi": b.high, "lo": b.low, "ended": False}
            day_counts[day_key] = {"BUY": 0, "SELL": 0}

        # Update Asia box
        if hour < box_end_utc and not day_box[day_key]["ended"]:
            day_box[day_key]["hi"] = max(day_box[day_key]["hi"], b.high)
            day_box[day_key]["lo"] = min(day_box[day_key]["lo"], b.low)
        elif hour >= box_end_utc:
            day_box[day_key]["ended"] = True

        box = day_box[day_key]

        # Entry check
        if box_end_utc <= hour < entry_end_utc and position is None and box["ended"]:
            action = None
            if b.close > box["hi"] and day_counts[day_key]["BUY"] < max_per_day:
                action = "BUY"
            elif b.close < box["lo"] and day_counts[day_key]["SELL"] < max_per_day:
                action = "SELL"

            if action:
                order_value = cash * ORDER_PCT
                entry_fill = b.close * (1 + buy_cost)
                entry_fee = order_value * COMMISSION_PCT / 2
                if order_value + entry_fee > cash:
                    order_value = cash / (1 + COMMISSION_PCT / 2)
                    entry_fee = order_value * COMMISSION_PCT / 2
                qty = order_value / entry_fill
                cash -= order_value + entry_fee
                position = Trade(
                    entry_time=b.time,
                    entry_price=entry_fill,
                    direction=action,
                    quantity=qty,
                )
                day_counts[day_key][action] += 1

        # Simple exit: hold until end of day or opposite signal
        if position and hour >= 20:
            exit_fill = b.close * (1 - sell_cost)
            proceeds = position.quantity * exit_fill
            exit_fee = proceeds * COMMISSION_PCT / 2
            cash += proceeds - exit_fee
            position.exit_time = b.time
            position.exit_price = exit_fill
            position.exit_reason = "end_of_day"
            position.pnl = proceeds - exit_fee - position.quantity * position.entry_price - (position.quantity * position.entry_price * COMMISSION_PCT / 2)
            position.fees = position.quantity * position.entry_price * COMMISSION_PCT / 2 + exit_fee
            trades.append(position)
            position = None

        equity.append(cash + (position.quantity * b.close * (1 - sell_cost) if position else 0))

    # Close remaining
    if position:
        last = bars[-1]
        exit_fill = last.close * (1 - sell_cost)
        proceeds = position.quantity * exit_fill
        exit_fee = proceeds * COMMISSION_PCT / 2
        cash += proceeds - exit_fee
        position.exit_time = last.time
        position.exit_price = exit_fill
        position.exit_reason = "end_of_data"
        position.pnl = proceeds - exit_fee - position.quantity * position.entry_price - (position.quantity * position.entry_price * COMMISSION_PCT / 2)
        position.fees = position.quantity * position.entry_price * COMMISSION_PCT / 2 + exit_fee
        trades.append(position)

    gross_profit = sum(max(t.pnl, 0) for t in trades)
    gross_loss = -sum(min(t.pnl, 0) for t in trades)
    peak = INITIAL_BALANCE
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    return trades, {
        "trades": len(trades),
        "wins": sum(1 for t in trades if t.pnl > 0),
        "losses": sum(1 for t in trades if t.pnl <= 0),
        "net_pnl": cash - INITIAL_BALANCE,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown": max_dd,
        "final_balance": cash,
    }


def replay_s3_supertrend(
    bars: List[Bar],
    sym: str,
) -> Tuple[List[Trade], Dict]:
    """S3 Supertrend+RSI pullback replay (simplified)."""
    st_line, st_dir = supertrend(bars, 10, 3.0)
    rsi = rsi_series([b.close for b in bars], 14)

    trades: List[Trade] = []
    position: Optional[Trade] = None
    cash = INITIAL_BALANCE
    equity = [cash]

    buy_cost = (SPREAD_PCT / 2 + SLIPPAGE_PCT)
    sell_cost = buy_cost

    for i in range(1, len(bars)):
        b = bars[i]
        prev = bars[i - 1]

        # Simplified S3: Supertrend direction change + RSI filter
        if math.isnan(st_dir[i]) or math.isnan(st_dir[i - 1]) or math.isnan(rsi[i]):
            equity.append(cash + (position.quantity * b.close * (1 - sell_cost) if position else 0))
            continue

        # Exit on ST flip
        if position:
            if position.direction == "BUY" and st_dir[i] == -1:
                exit_fill = b.close * (1 - sell_cost)
                proceeds = position.quantity * exit_fill
                exit_fee = proceeds * COMMISSION_PCT / 2
                cash += proceeds - exit_fee
                position.exit_time = b.time
                position.exit_price = exit_fill
                position.exit_reason = "st_flip"
                position.pnl = proceeds - exit_fee - position.quantity * position.entry_price - (position.quantity * position.entry_price * COMMISSION_PCT / 2)
                position.fees = position.quantity * position.entry_price * COMMISSION_PCT / 2 + exit_fee
                trades.append(position)
                position = None
            elif position.direction == "SELL" and st_dir[i] == 1:
                exit_fill = b.close * (1 + sell_cost)
                proceeds = position.quantity * exit_fill
                exit_fee = proceeds * COMMISSION_PCT / 2
                cash += proceeds - exit_fee
                position.exit_time = b.time
                position.exit_price = exit_fill
                position.exit_reason = "st_flip"
                position.pnl = proceeds - exit_fee - position.quantity * position.entry_price - (position.quantity * position.entry_price * COMMISSION_PCT / 2)
                position.fees = position.quantity * position.entry_price * COMMISSION_PCT / 2 + exit_fee
                trades.append(position)
                position = None

        # Entry: ST direction change + RSI confirmation
        if position is None:
            action = None
            if st_dir[i] == 1 and st_dir[i - 1] == -1 and rsi[i] > 40:
                action = "BUY"
            elif st_dir[i] == -1 and st_dir[i - 1] == 1 and rsi[i] < 60:
                action = "SELL"

            if action:
                order_value = cash * ORDER_PCT
                entry_fill = b.close * (1 + buy_cost) if action == "BUY" else b.close * (1 - buy_cost)
                entry_fee = order_value * COMMISSION_PCT / 2
                if order_value + entry_fee > cash:
                    order_value = cash / (1 + COMMISSION_PCT / 2)
                    entry_fee = order_value * COMMISSION_PCT / 2
                qty = order_value / entry_fill
                cash -= order_value + entry_fee
                position = Trade(
                    entry_time=b.time,
                    entry_price=entry_fill,
                    direction=action,
                    quantity=qty,
                )

        equity.append(cash + (position.quantity * b.close * (1 - sell_cost) if position else 0))

    # Close remaining
    if position:
        last = bars[-1]
        exit_fill = last.close * (1 - sell_cost) if position.direction == "BUY" else last.close * (1 + sell_cost)
        proceeds = position.quantity * exit_fill
        exit_fee = proceeds * COMMISSION_PCT / 2
        cash += proceeds - exit_fee
        position.exit_time = last.time
        position.exit_price = exit_fill
        position.exit_reason = "end_of_data"
        position.pnl = proceeds - exit_fee - position.quantity * position.entry_price - (position.quantity * position.entry_price * COMMISSION_PCT / 2)
        position.fees = position.quantity * position.entry_price * COMMISSION_PCT / 2 + exit_fee
        trades.append(position)

    gross_profit = sum(max(t.pnl, 0) for t in trades)
    gross_loss = -sum(min(t.pnl, 0) for t in trades)
    peak = INITIAL_BALANCE
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    return trades, {
        "trades": len(trades),
        "wins": sum(1 for t in trades if t.pnl > 0),
        "losses": sum(1 for t in trades if t.pnl <= 0),
        "net_pnl": cash - INITIAL_BALANCE,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown": max_dd,
        "final_balance": cash,
    }


# ── Main test runner ────────────────────────────────────────────────────────

REJECTED_STRATEGIES = {
    "donchian_adx": {
        "symbols": ["BTCUSD"],  # Removed from mode_symbols
        "tf": "5m",
        "fn": replay_donchian_adx,
    },
    "london_breakout": {
        "symbols": ["GBPCHF", "EURCAD", "CHFJPY", "GBPNZD", "CADJPY",
                      "GBPAUD", "GBPCAD", "AUDCAD", "EURAUD", "CADCHF", "AUDCHF"],
        "tf": "5m",
        "fn": replay_london_breakout,
    },
    "s3_5m": {
        "symbols": ["AUDNZD"],  # Removed from s3_symbols_5m
        "tf": "5m",
        "fn": replay_s3_supertrend,
    },
    "classic_13cross": {
        "symbols": ["NZDJPY", "AUDNZD", "GBPCHF", "EURCAD", "CHFJPY", "CADJPY",
                     "GBPNZD", "GBPAUD", "GBPCAD", "AUDCAD", "EURAUD", "CADCHF", "AUDCHF"],
        "tf": "5m",
        "fn": replay_donchian_adx,  # Use as proxy for classic momentum
    },
}


def run_all_tests(days: int = 30) -> Dict:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    print(f"[MT5] Connected: {mt5.account_info().login}")

    results = {}
    for strategy_name, cfg in REJECTED_STRATEGIES.items():
        print(f"\n{'='*60}")
        print(f"STRATEGY: {strategy_name}")
        print(f"{'='*60}")
        results[strategy_name] = {}

        for sym in cfg["symbols"]:
            try:
                bars = fetch_bars(sym, cfg["tf"], days)
                trades, stats = cfg["fn"](bars, sym)
                results[strategy_name][sym] = stats
                win_rate = stats["wins"] / stats["trades"] * 100 if stats["trades"] else 0
                print(f"  {sym:10s} | trades={stats['trades']:3d} | wins={stats['wins']:3d} | "
                      f"net=${stats['net_pnl']:8.2f} | PF={stats['profit_factor'] or 0:.2f} | "
                      f"WR={win_rate:5.1f}% | DD=${stats['max_drawdown']:7.2f}")
            except Exception as exc:
                print(f"  {sym:10s} | ERROR: {exc}")
                results[strategy_name][sym] = {"error": str(exc)}

    mt5.shutdown()
    return results


def save_report(results: Dict, days: int, path: Optional[str] = None):
    if path is None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = f"outputs/mt5_rejected_strategies_{days}d_{ts}.json"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[REPORT] Saved to {path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    results = run_all_tests(args.days)
    save_report(results, args.days, args.output)
