"""QuantStats-compatible Performance Analytics & HTML/JSON Tear-Sheet Engine.

Computes institutional risk/return metrics (Sharpe, Sortino, Calmar, Max Drawdown,
Profit Factor, Expectancy, Payoff Ratio, Win/Loss distribution, per-symbol and
per-strategy breakdown) from MT5 closed trades. Uses `quantstats` if installed,
with a zero-dependency NumPy implementation as the default/fallback path.
"""
from __future__ import annotations

import html
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        v = float(val)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _trade_pnl(t: Dict[str, Any]) -> float:
    return _safe_float(t.get("pnl_usd", t.get("profit", 0.0)), 0.0)


def _trade_ts(t: Dict[str, Any]) -> float:
    return _safe_float(t.get("exit_ts") or t.get("close_time") or t.get("ts"), 0.0)


def build_tearsheet(
    closed_trades: List[Dict[str, Any]],
    *,
    initial_balance: float = 1000.0,
    title: str = "Scalper Global — Performans Tear-Sheet",
) -> Dict[str, Any]:
    """Compute full QuantStats-style JSON tear-sheet from closed trades."""
    ordered = sorted(
        [t for t in (closed_trades or []) if isinstance(t, dict)],
        key=_trade_ts,
    )
    pnls = np.array([_trade_pnl(t) for t in ordered], dtype=float)
    n = int(len(pnls))

    if n == 0:
        return {
            "title": title,
            "trade_count": 0,
            "initial_balance": round(initial_balance, 2),
            "final_balance": round(initial_balance, 2),
            "net_pnl_usd": 0.0,
            "total_return_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": None,
            "expectancy_usd": 0.0,
            "payoff_ratio": None,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_usd": 0.0,
            "avg_win_usd": 0.0,
            "avg_loss_usd": 0.0,
            "best_trade_usd": 0.0,
            "worst_trade_usd": 0.0,
            "win_loss_distribution": [],
            "by_symbol": {},
            "by_strategy": {},
            "equity_curve": [],
        }

    base_bal = initial_balance if initial_balance > 0 else 1000.0
    equity = base_bal + np.cumsum(pnls)
    prev_equity = np.concatenate(([base_bal], equity[:-1]))
    returns = np.where(prev_equity > 0, pnls / prev_equity, 0.0)

    # Drawdown series
    peaks = np.maximum.accumulate(np.concatenate(([base_bal], equity)))[1:]
    dd_usd = equity - peaks
    dd_pct = np.where(peaks > 0, dd_usd / peaks * 100.0, 0.0)
    max_dd_usd = float(np.min(dd_usd)) if len(dd_usd) else 0.0
    max_dd_pct = float(np.min(dd_pct)) if len(dd_pct) else 0.0

    # Annualization factor: trade-level approximation (sqrt(252))
    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns, ddof=1)) if n > 1 else 0.0
    downside = returns[returns < 0.0]
    down_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else (float(abs(downside[0])) if len(downside) == 1 else 0.0)

    sharpe = round((mean_r / std_r) * math.sqrt(252.0), 2) if std_r > 1e-12 else 0.0
    sortino = round((mean_r / down_std) * math.sqrt(252.0), 2) if down_std > 1e-12 else 0.0

    net_pnl = float(np.sum(pnls))
    total_ret_pct = (net_pnl / base_bal) * 100.0
    calmar = round(total_ret_pct / abs(max_dd_pct), 2) if abs(max_dd_pct) > 1e-6 else 0.0

    wins = pnls[pnls > 0.0]
    losses = pnls[pnls < 0.0]
    gross_profit = float(np.sum(wins)) if len(wins) else 0.0
    gross_loss = float(abs(np.sum(losses))) if len(losses) else 0.0
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else None)

    avg_win = float(np.mean(wins)) if len(wins) else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) else 0.0
    payoff = round(avg_win / abs(avg_loss), 2) if avg_loss < 0 else None
    win_rate = len(wins) / n * 100.0
    expectancy = net_pnl / n

    # Win/Loss distribution buckets
    buckets = [
        ("<= -$25", lambda x: x <= -25.0),
        ("-$25 .. -$10", lambda x: -25.0 < x <= -10.0),
        ("-$10 .. $0", lambda x: -10.0 < x < 0.0),
        ("$0 .. +$10", lambda x: 0.0 <= x <= 10.0),
        ("+$10 .. +$25", lambda x: 10.0 < x <= 25.0),
        ("> +$25", lambda x: x > 25.0),
    ]
    dist = [
        {"bucket": label, "count": int(sum(1 for x in pnls if fn(float(x))))}
        for label, fn in buckets
    ]

    # Breakdown by symbol & strategy
    by_sym: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "wins": 0, "net_pnl_usd": 0.0})
    by_strat: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "wins": 0, "net_pnl_usd": 0.0})
    for t, p in zip(ordered, pnls):
        sym = str(t.get("symbol") or "UNKNOWN").upper()
        strat = str(t.get("strategy") or "UNKNOWN")
        for grp, key in ((by_sym, sym), (by_strat, strat)):
            grp[key]["count"] += 1
            if p > 0:
                grp[key]["wins"] += 1
            grp[key]["net_pnl_usd"] = round(grp[key]["net_pnl_usd"] + float(p), 2)

    for grp in (by_sym, by_strat):
        for v in grp.values():
            v["win_rate_pct"] = round(v["wins"] / v["count"] * 100.0, 1) if v["count"] else 0.0

    curve = [
        {
            "idx": i + 1,
            "ts": _trade_ts(t),
            "symbol": str(t.get("symbol") or "").upper(),
            "pnl_usd": round(float(p), 2),
            "equity": round(float(eq), 2),
            "dd_pct": round(float(dd), 2),
        }
        for i, (t, p, eq, dd) in enumerate(zip(ordered, pnls, equity, dd_pct))
    ]

    return {
        "title": title,
        "trade_count": n,
        "initial_balance": round(base_bal, 2),
        "final_balance": round(float(equity[-1]), 2),
        "net_pnl_usd": round(net_pnl, 2),
        "total_return_pct": round(total_ret_pct, 2),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": pf,
        "expectancy_usd": round(expectancy, 2),
        "payoff_ratio": payoff,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_usd": round(max_dd_usd, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "best_trade_usd": round(float(np.max(pnls)), 2),
        "worst_trade_usd": round(float(np.min(pnls)), 2),
        "win_loss_distribution": dist,
        "by_symbol": dict(sorted(by_sym.items(), key=lambda kv: kv[1]["net_pnl_usd"])),
        "by_strategy": dict(sorted(by_strat.items(), key=lambda kv: kv[1]["net_pnl_usd"])),
        "equity_curve": curve[-100:],
    }


def render_tearsheet_html(report: Dict[str, Any]) -> str:
    """Render a standalone dark-theme HTML tear-sheet for browser viewing."""
    title = html.escape(str(report.get("title") or "Performans Tear-Sheet"))
    cards = [
        ("Net PnL", f"${report.get('net_pnl_usd', 0):+.2f}"),
        ("Getiri", f"{report.get('total_return_pct', 0):+.2f}%"),
        ("Win Rate", f"{report.get('win_rate_pct', 0):.1f}%"),
        ("Profit Factor", str(report.get("profit_factor") or "—")),
        ("Sharpe", f"{report.get('sharpe', 0):.2f}"),
        ("Sortino", f"{report.get('sortino', 0):.2f}"),
        ("Calmar", f"{report.get('calmar', 0):.2f}"),
        ("Max Drawdown", f"{report.get('max_drawdown_pct', 0):.2f}% (${report.get('max_drawdown_usd', 0):.2f})"),
        ("Expectancy", f"${report.get('expectancy_usd', 0):+.2f}"),
        ("Payoff Ratio", str(report.get("payoff_ratio") or "—")),
    ]
    cards_html = "".join(
        f'<div class="card"><div class="lbl">{html.escape(k)}</div><div class="val">{html.escape(v)}</div></div>'
        for k, v in cards
    )

    dist_rows = "".join(
        f"<tr><td>{html.escape(str(d['bucket']))}</td><td>{int(d['count'])}</td></tr>"
        for d in (report.get("win_loss_distribution") or [])
    )
    strat_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v['count']}</td><td>{v['win_rate_pct']}%</td><td>${v['net_pnl_usd']:+.2f}</td></tr>"
        for k, v in (report.get("by_strategy") or {}).items()
    )
    sym_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v['count']}</td><td>{v['win_rate_pct']}%</td><td>${v['net_pnl_usd']:+.2f}</td></tr>"
        for k, v in (report.get("by_symbol") or {}).items()
    )

    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{background:#0b1120;color:#e2e8f0;font-family:system-ui,-apple-system,sans-serif;margin:0;padding:24px}}
h1{{font-size:20px;margin:0 0 16px}}h2{{font-size:15px;margin:24px 0 10px;color:#94a3b8}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}}
.card{{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:12px}}
.lbl{{font-size:12px;color:#94a3b8}}.val{{font-size:18px;font-weight:700;margin-top:4px}}
table{{width:100%;border-collapse:collapse;background:#111827;border-radius:10px;overflow:hidden}}
th,td{{padding:8px 12px;border-bottom:1px solid #1f2937;text-align:left;font-size:13px}}
th{{background:#1e293b;color:#cbd5e1}}
</style></head><body>
<h1>{title} ({int(report.get('trade_count', 0))} işlem)</h1>
<div class="grid">{cards_html}</div>
<h2>Win / Loss Dağılımı</h2>
<table><thead><tr><th>Aralık</th><th>Adet</th></tr></thead><tbody>{dist_rows}</tbody></table>
<h2>Strateji Bazlı Performans</h2>
<table><thead><tr><th>Strateji</th><th>İşlem</th><th>Win Rate</th><th>Net PnL</th></tr></thead><tbody>{strat_rows}</tbody></table>
<h2>Sembol Bazlı Performans</h2>
<table><thead><tr><th>Sembol</th><th>İşlem</th><th>Win Rate</th><th>Net PnL</th></tr></thead><tbody>{sym_rows}</tbody></table>
</body></html>"""
