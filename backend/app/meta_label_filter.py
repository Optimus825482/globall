"""Meta-Labeling False-Signal Filter (Triple-Barrier ML + Calibrated Regime Prior).

Decouples trade direction (primary strategy) from trade quality/sizing (meta-model).
Supports:
  1. `triple_barrier_label(...)`: López de Prado triple-barrier labeling (TP / SL / vertical timeout).
  2. `train_meta_model_from_trades(closed_trades)`: trains a regularized LogisticRegression
     meta-classifier from MT5 closed trade history (persisted via joblib).
  3. `score_meta_signal(...)`: blends live ML probability (when trained on >= 20 trades)
     with the calibrated microstructure/regime prior.
"""
from __future__ import annotations

import math
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence

import numpy as np

_RECENT_EVALS: Deque[Dict[str, Any]] = deque(maxlen=120)
_ML_MODEL: Any = None
_ML_META: Dict[str, Any] = {"trained": False, "n_samples": 0, "trained_at": None, "accuracy": None}
_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "meta_label_model.joblib"

_DAILY_MAP = {"ALIGNED": 1.0, "NEUTRAL": 0.0, "COUNTER": -1.0}
_HURST_MAP = {"TREND": 1.0, "MEAN_REVERT": 0.0, "RANDOM_WALK": -1.0, "UNKNOWN": 0.0}
_HMM_MAP = {"TREND_EXPANSION": 1.0, "LOW_VOL_RANGE": 0.0, "SHOCK_VOLATILITY": -1.0, "UNKNOWN": 0.0}
_MACRO_MAP = {"SUPPORTIVE": 1.0, "NEUTRAL": 0.0, "OPPOSING": -1.0}


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-10.0, min(10.0, x))))


def triple_barrier_label(
    entry_price: float,
    future_highs: Sequence[float],
    future_lows: Sequence[float],
    direction: str,
    tp_dist: float,
    sl_dist: float,
    max_bars: int = 24,
) -> int:
    """López de Prado Triple-Barrier label: 1 if TP hit first, 0 if SL or vertical expiry."""
    if entry_price <= 0 or tp_dist <= 0 or sl_dist <= 0:
        return 0
    d = str(direction or "").upper()
    tp = entry_price + tp_dist if d == "BUY" else entry_price - tp_dist
    sl = entry_price - sl_dist if d == "BUY" else entry_price + sl_dist
    horizon = min(len(future_highs), len(future_lows), max(1, int(max_bars)))
    for i in range(horizon):
        hi = float(future_highs[i])
        lo = float(future_lows[i])
        if d == "BUY":
            if lo <= sl:
                return 0
            if hi >= tp:
                return 1
        else:
            if hi >= sl:
                return 0
            if lo <= tp:
                return 1
    return 0


def _feature_vector(
    direction: str,
    daily_alignment: str,
    hurst_regime: str,
    hmm_regime: str,
    kalman_zscore: float,
    macro_alignment: str,
    spread_sl_ratio: float,
    hour_utc: int = 12,
) -> List[float]:
    d_sign = 1.0 if str(direction or "").upper() == "BUY" else -1.0
    aligned_z = float(kalman_zscore) * d_sign
    rad = 2.0 * math.pi * (int(hour_utc) % 24) / 24.0
    return [
        d_sign,
        _DAILY_MAP.get(str(daily_alignment).upper(), 0.0),
        _HURST_MAP.get(str(hurst_regime).upper(), 0.0),
        _HMM_MAP.get(str(hmm_regime).upper(), 0.0),
        max(-4.0, min(4.0, aligned_z)),
        _MACRO_MAP.get(str(macro_alignment).upper(), 0.0),
        max(0.0, min(1.0, float(spread_sl_ratio))),
        math.sin(rad),
        math.cos(rad),
    ]


def train_meta_model_from_trades(
    closed_trades: Sequence[Dict[str, Any]],
    *,
    min_samples: int = 20,
    save_to_disk: bool = True,
    require_feature_coverage: bool = False,
) -> Dict[str, Any]:
    """Train a regularized LogisticRegression meta-model from MT5 closed trades."""
    global _ML_MODEL, _ML_META
    X_rows: List[List[float]] = []
    y_rows: List[int] = []
    covered_count = 0

    for tr in closed_trades or []:
        if not isinstance(tr, dict):
            continue
        try:
            pnl = float(tr.get("pnl_usd", tr.get("profit", 0.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        ts = float(tr.get("exit_ts") or tr.get("close_time") or time.time())
        hour_utc = int((ts // 3600) % 24)
        d_align = str(tr.get("daily_alignment") or "NEUTRAL")
        h_reg = str(tr.get("hurst_regime") or "UNKNOWN")
        hmm_reg = str(tr.get("hmm_regime") or "UNKNOWN")
        kz_val = float(tr.get("kalman_zscore") or 0.0)
        if (
            d_align.upper() != "NEUTRAL"
            or h_reg.upper() != "UNKNOWN"
            or hmm_reg.upper() != "UNKNOWN"
            or kz_val != 0.0
        ):
            covered_count += 1
        feats = _feature_vector(
            direction=str(tr.get("direction") or "BUY"),
            daily_alignment=d_align,
            hurst_regime=h_reg,
            hmm_regime=hmm_reg,
            kalman_zscore=kz_val,
            macro_alignment=str(tr.get("macro_alignment") or "NEUTRAL"),
            spread_sl_ratio=float(tr.get("spread_sl_ratio") or 0.0),
            hour_utc=hour_utc,
        )
        X_rows.append(feats)
        y_rows.append(1 if pnl > 0.0 else 0)

    if len(X_rows) < min_samples or len(set(y_rows)) < 2:
        return {
            "ok": False,
            "trained": False,
            "n_samples": len(X_rows),
            "reason": f"Yetersiz veya tek sınıflı veri ({len(X_rows)} < {min_samples})",
        }

    if require_feature_coverage and (covered_count / len(X_rows)) < 0.30:
        return {
            "ok": False,
            "trained": False,
            "n_samples": len(X_rows),
            "reason": "Yetersiz rejim özelliği kapsamı",
        }

    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    X = np.asarray(X_rows, dtype=float)
    y = np.asarray(y_rows, dtype=int)
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(C=0.5, max_iter=300, class_weight="balanced")),
    ])
    model.fit(X, y)
    acc = round(float(model.score(X, y)), 3)

    _ML_MODEL = model
    _ML_META = {
        "trained": True,
        "n_samples": len(X_rows),
        "trained_at": round(time.time(), 2),
        "accuracy": acc,
    }
    if save_to_disk:
        try:
            import joblib
            _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump({"model": model, "meta": _ML_META}, _MODEL_PATH)
        except Exception:  # noqa: BLE001
            pass

    return {"ok": True, **_ML_META}


def _ensure_loaded_model() -> Any:
    global _ML_MODEL, _ML_META
    if _ML_MODEL is not None:
        return _ML_MODEL
    if _MODEL_PATH.exists():
        try:
            import joblib
            blob = joblib.load(_MODEL_PATH)
            if isinstance(blob, dict) and blob.get("model") is not None:
                _ML_MODEL = blob["model"]
                _ML_META = dict(blob.get("meta") or _ML_META)
        except Exception:  # noqa: BLE001
            pass
    return _ML_MODEL


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
    hour_utc: Optional[int] = None,
) -> Dict[str, Any]:
    """Compute calibrated meta-probability (ML-blended when trained) and soft sizing multiplier."""
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

    rule_prob = _sigmoid(logit)
    model_source = "rule_prior"
    prob = rule_prob

    model = _ensure_loaded_model()
    if model is not None:
        ml_acc = _ML_META.get("accuracy")
        ml_n = int(_ML_META.get("n_samples") or 0)
        if (ml_acc is not None and float(ml_acc) < 0.52) or ml_n < 30:
            reasons.append("ML_SKIP_LOW_ACC")
        else:
            try:
                hr = int((time.time() // 3600) % 24) if hour_utc is None else int(hour_utc)
                x = np.asarray([_feature_vector(
                    d, daily_alignment, hurst_regime, hmm_regime,
                    kalman_zscore, macro_alignment, spread_sl_ratio, hr,
                )], dtype=float)
                ml_prob = float(model.predict_proba(x)[0][1])
                prob = 0.55 * ml_prob + 0.45 * rule_prob
                model_source = "ml_blend"
                reasons.append(f"ML_PROB({ml_prob:.2f})")
            except Exception:  # noqa: BLE001
                pass

    prob = round(max(0.05, min(0.95, prob)), 3)
    if prob < 0.45:
        verdict = "REDUCE"
        size_mult = round(max(0.45, min(0.80, 0.45 + (prob - 0.15) * 1.15)), 2)
    elif prob >= 0.72:
        verdict = "BOOST"
        size_mult = round(min(1.25, 1.10 + (prob - 0.72) * 0.65), 2)
    else:
        verdict = "PASS"
        size_mult = round(0.85 + ((prob - 0.45) / 0.27) * 0.20, 2)

    rec = {
        "ts": round(time.time(), 2),
        "symbol": str(symbol or "").upper(),
        "direction": d,
        "meta_prob": prob,
        "verdict": verdict,
        "size_mult": size_mult,
        "model_source": model_source,
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
        "model_meta": dict(_ML_META),
        "by_verdict": counts,
        "recent": items[:25],
    }
