"""Meta-Labeling False-Signal Filter (Calibrated Microstructure & Regime Probability Scorer).

Decouples trade direction (primary strategy) from trade quality/sizing (meta-model).
Evaluates context features (Daily Bias, Hurst, HMM, Kalman Z-score, Macro Alignment,
Spread/SL cost) and returns a calibrated probability `meta_prob` in [0.05, 0.95] plus
a soft lot multiplier (`0.6x` when weak, `1.0x` normal, `1.15x` high-conviction).
Logs recent evaluations for live shadow/diagnostics tracking.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Any, Deque, Dict, List

_RECENT_EVALS: Deque[Dict[str, Any]] = deque(maxlen=120)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-10.0, min(10.0, x))))


def score_meta_signal(
    symbol: str,
    direction: str,
    *,
    daily_alignment: str = "NEUTRAL",
    hurst_regime: str = "UNKNOWN",
    hmm_regime: str = "UNKNOWN",
    kalman_zscore: float = 0.0,
    macro_alignment: str = "NEUTRAL",
    spread_sl_ratio: float = 0.0,
) -> Dict[str, Any]:
    """Compute calibrated meta-probability and soft sizing multiplier."""
    logit = 0.15  # mild positive prior for primary-verified signals
    reasons: List[str] = []

    # 1) 1D EMA 12/50 Daily Bias
    if daily_alignment == "ALIGNED":
        logit += 0.45
        reasons.append("1D_ALIGNED(+)")
    elif daily_alignment == "COUNTER":
        logit -= 0.55
        reasons.append("1D_COUNTER(-)")

    # 2) Hurst Regime
    if hurst_regime == "TREND":
        logit += 0.30
        reasons.append("HURST_TREND(+)")
    elif hurst_regime == "RANDOM_WALK":
        logit -= 0.35
        reasons.append("HURST_NOISE(-)")

    # 3) HMM Regime
    if hmm_regime == "TREND_EXPANSION":
        logit += 0.25
        reasons.append("HMM_TREND(+)")
    elif hmm_regime == "SHOCK_VOLATILITY":
        logit -= 0.70
        reasons.append("HMM_SHOCK(-)")

    # 4) Kalman Overextension in trade direction
    d = str(direction or "").upper()
    aligned_z = kalman_zscore if d == "BUY" else -kalman_zscore
    if aligned_z >= 1.8:
        logit -= 0.45
        reasons.append(f"KALMAN_STRETCH({kalman_zscore:+.1f})")
    elif -0.5 <= aligned_z <= 1.0:
        logit += 0.15

    # 5) Macro Lead-Lag Alignment
    if macro_alignment == "SUPPORTIVE":
        logit += 0.35
        reasons.append("MACRO_SUPPORT(+)")
    elif macro_alignment == "OPPOSING":
        logit -= 0.45
        reasons.append("MACRO_OPPOSE(-)")

    # 6) Spread / SL Friction
    if spread_sl_ratio > 0.20:
        logit -= 0.35
        reasons.append(f"SPREAD_COST({spread_sl_ratio:.2f})")

    prob = round(_sigmoid(logit), 3)
    if prob < 0.45:
        verdict = "REDUCE"
        size_mult = 0.6
    elif prob >= 0.72:
        verdict = "BOOST"
        size_mult = 1.15
    else:
        verdict = "PASS"
        size_mult = 1.0

    rec = {
        "ts": round(time.time(), 2),
        "symbol": str(symbol or "").upper(),
        "direction": d,
        "meta_prob": prob,
        "verdict": verdict,
        "size_mult": size_mult,
        "reasons": reasons,
    }
    _RECENT_EVALS.appendleft(rec)
    return rec


def get_meta_filter_stats() -> Dict[str, Any]:
    """Return summary stats & recent evaluations for /api/forex/diagnostics/today-audit."""
    items = list(_RECENT_EVALS)
    counts = {"BOOST": 0, "PASS": 0, "REDUCE": 0}
    for it in items:
        v = it.get("verdict", "PASS")
        if v in counts:
            counts[v] += 1
    avg_p = round(sum(it["meta_prob"] for it in items) / len(items), 3) if items else 0.0
    return {
        "total_evaluated": len(items),
        "avg_meta_prob": avg_p,
        "by_verdict": counts,
        "recent": items[:25],
    }
