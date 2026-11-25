"""Radar Faz 1 Quant Modülü: Hurst Exponent + Kalman Filter + Algorithmic SMC.

Saf Python + math (harici kütüphane bağımlılığı yok), deterministik, nedensel
(look-ahead yok) ve sembol başına < 1 ms çalışma süreli nicel rejim/yapı motoru.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _clean_positive_floats(values: Sequence[Any], tail: int = 120) -> List[float]:
    if not values:
        return []
    sliced = values[-tail:] if len(values) > tail else values
    out: List[float] = []
    for v in sliced:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f) and f > 0.0:
            out.append(f)
    return out


def compute_hurst_exponent(
    closes: Sequence[float],
    min_lag: int = 2,
    max_lag: int = 20,
) -> Dict[str, Any]:
    """Log-fiyat gecikme varyans ölçeklemesi ile nedensel Hurst üssü tahmini.

    tau(lag) = sqrt(mean((x[t + lag] - x[t])^2)) için log(tau) ~ H * log(lag)
    EKK (OLS) eğimi hesaplanır. En az 32 pozitif sonlu kapanış gerektirir.
    """
    valid = _clean_positive_floats(closes, tail=120)
    n = len(valid)
    if n < 32:
        return {"hurst": None, "regime": "UNKNOWN"}

    logs = [math.log(v) for v in valid]
    lo_lag = max(2, int(min_lag))
    hi_lag = min(int(max_lag), n // 2)
    if hi_lag <= lo_lag:
        return {"hurst": None, "regime": "UNKNOWN"}

    lx: List[float] = []
    ly: List[float] = []
    for lag in range(lo_lag, hi_lag + 1):
        count = n - lag
        if count <= 1:
            continue
        sq_sum = 0.0
        for i in range(count):
            d = logs[i + lag] - logs[i]
            sq_sum += d * d
        tau = math.sqrt(sq_sum / count)
        if tau > 1e-15:
            lx.append(math.log(float(lag)))
            ly.append(math.log(tau))

    m = len(lx)
    if m < 2:
        return {"hurst": None, "regime": "UNKNOWN"}

    mx = sum(lx) / m
    my = sum(ly) / m
    num = 0.0
    den = 0.0
    for a, b in zip(lx, ly):
        da = a - mx
        num += da * (b - my)
        den += da * da

    if den <= 1e-15:
        return {"hurst": None, "regime": "UNKNOWN"}

    h_raw = num / den
    if not math.isfinite(h_raw):
        return {"hurst": None, "regime": "UNKNOWN"}

    h = round(max(0.10, min(0.90, h_raw)), 3)
    if h >= 0.56:
        regime = "TREND"
    elif h <= 0.44:
        regime = "MEAN_REVERT"
    else:
        regime = "RANDOM_WALK"

    return {"hurst": h, "regime": regime}


def compute_kalman_filter(
    closes: Sequence[float],
    q: float = 1e-4,
    r: float = 1e-2,
) -> Dict[str, Any]:
    """Log-fiyat uzayında ölçek-bağımsız 1B özyinelemeli skaler Kalman filtresi.

    EURUSD (~1.08), XAUUSD (~2700) ve BTCUSD (~90000) üzerinde özdeş davranır.
    """
    valid = _clean_positive_floats(closes, tail=120)
    n = len(valid)
    if n < 10:
        return {
            "level": None,
            "slope_bps": 0.0,
            "dir": "FLAT",
            "zscore": 0.0,
            "overextended": False,
        }

    q_val = max(float(q), 1e-12)
    r_val = max(float(r), 1e-12)
    logs = [math.log(v) for v in valid]

    x_est = logs[0]
    p_cov = r_val
    estimates: List[float] = [x_est]
    residuals: List[float] = [0.0]

    for z in logs[1:]:
        p_pred = p_cov + q_val
        k_gain = p_pred / (p_pred + r_val)
        x_est = x_est + k_gain * (z - x_est)
        p_cov = (1.0 - k_gain) * p_pred
        estimates.append(x_est)
        residuals.append(z - x_est)

    last_log = logs[-1]
    last_res = last_log - x_est
    x_prev3 = estimates[-4]
    slope_bps = round((x_est - x_prev3) * 10000.0, 2)

    if slope_bps > 1.5:
        k_dir = "UP"
    elif slope_bps < -1.5:
        k_dir = "DOWN"
    else:
        k_dir = "FLAT"

    # Önceki 30 barın RMS kalıntısı (sabit hızlı düzgün trendde aşırı şişmez,
    # ani sıçramada son bar kendini maskelemez; öncül RMS 0 ise son bar dahil RMS).
    prior_win = residuals[-31:-1] if len(residuals) > 1 else []
    rms = 0.0
    if prior_win:
        rms = math.sqrt(sum(v * v for v in prior_win) / len(prior_win))
    if rms <= 1e-12:
        full_win = residuals[-30:]
        rms = math.sqrt(sum(v * v for v in full_win) / len(full_win)) if full_win else 0.0

    zscore = round(last_res / rms, 2) if rms > 1e-12 else 0.0
    overextended = abs(zscore) >= 2.2

    return {
        "level": round(math.exp(x_est), 6),
        "slope_bps": slope_bps,
        "dir": k_dir,
        "zscore": zscore,
        "overextended": overextended,
    }


def _detect_asian_sweep(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    bar_times: Optional[Sequence[Any]],
    n: int,
) -> str:
    if not bar_times or len(bar_times) < n or n < 2:
        return "NONE"

    tail_times = bar_times[-n:]
    parsed: List[Optional[int]] = []
    for bt in tail_times:
        try:
            ts = int(float(bt))
            parsed.append(ts if ts > 0 else None)
        except (TypeError, ValueError):
            parsed.append(None)

    t_last = parsed[-1]
    if t_last is None:
        return "NONE"

    dt_last = datetime.fromtimestamp(t_last, timezone.utc)
    if dt_last.hour >= 6:
        target_date = dt_last.date()
    else:
        target_date = (dt_last - timedelta(days=1)).date()

    asian_high: Optional[float] = None
    asian_low: Optional[float] = None
    for j in range(n - 1):
        ts = parsed[j]
        if ts is None:
            continue
        dt_j = datetime.fromtimestamp(ts, timezone.utc)
        if dt_j.date() == target_date and 0 <= dt_j.hour < 6:
            hj = highs[j]
            lj = lows[j]
            asian_high = hj if asian_high is None else max(asian_high, hj)
            asian_low = lj if asian_low is None else min(asian_low, lj)

    if asian_high is None or asian_low is None:
        return "NONE"

    h_last = highs[-1]
    l_last = lows[-1]
    c_last = closes[-1]

    high_swept = h_last > asian_high and c_last < asian_high
    low_swept = l_last < asian_low and c_last > asian_low
    if high_swept and not low_swept:
        return "HIGH_SWEPT"
    if low_swept and not high_swept:
        return "LOW_SWEPT"
    if high_swept and low_swept:
        return "LOW_SWEPT" if c_last >= (asian_high + asian_low) * 0.5 else "HIGH_SWEPT"
    return "NONE"


def detect_smc_structure(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    bar_times: Optional[Sequence[Any]] = None,
    swing_len: int = 3,
) -> Dict[str, Any]:
    """Nedensel SMC yapı kırılımı (BOS/CHoCH), likidite avı ve Asya kutusu taraması."""
    raw_n = min(len(opens), len(highs), len(lows), len(closes))
    s_len = max(1, int(swing_len))
    if raw_n < 2 * s_len + 2:
        return {"structure": "NONE", "sweep": "NONE", "asian_sweep": "NONE"}

    tail = min(raw_n, 240)
    o = [float(x) for x in opens[-tail:]]
    h = [float(x) for x in highs[-tail:]]
    l = [float(x) for x in lows[-tail:]]
    c = [float(x) for x in closes[-tail:]]
    n = len(c)

    # Nedensel salınım (pivot) tespiti: i indeksi yalnızca i + swing_len < n iken onaylıdır.
    swing_highs: List[Tuple[int, float]] = []
    swing_lows: List[Tuple[int, float]] = []
    for i in range(s_len, n - s_len):
        hi = h[i]
        left_h = max(h[i - s_len : i])
        right_h = max(h[i + 1 : i + s_len + 1])
        if hi >= left_h and hi > right_h:
            swing_highs.append((i, hi))

        li = l[i]
        left_l = min(l[i - s_len : i])
        right_l = min(l[i + 1 : i + s_len + 1])
        if li <= left_l and li < right_l:
            swing_lows.append((i, li))

    c_last = c[-1]
    c_prev = c[-2]
    h_last = h[-1]
    l_last = l[-1]
    o_last = o[-1]

    structure = "NONE"
    prior_dir = "NEUTRAL"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        sh1, sh2 = swing_highs[-2][1], swing_highs[-1][1]
        sl1, sl2 = swing_lows[-2][1], swing_lows[-1][1]
        if (sh2 >= sh1 and sl2 > sl1) or (sh2 > sh1 and sl2 >= sl1):
            prior_dir = "BULL"
        elif (sh2 <= sh1 and sl2 < sl1) or (sh2 < sh1 and sl2 <= sl1):
            prior_dir = "BEAR"

    bull_break = bool(swing_highs and c_last > swing_highs[-1][1] and c_prev <= swing_highs[-1][1])
    bear_break = bool(swing_lows and c_last < swing_lows[-1][1] and c_prev >= swing_lows[-1][1])

    if bull_break and not bear_break:
        if prior_dir == "BEAR" or (len(swing_highs) >= 2 and swing_highs[-1][1] < swing_highs[-2][1]):
            structure = "BULLISH_CHOCH"
        else:
            structure = "BULLISH_BOS"
    elif bear_break and not bull_break:
        if prior_dir == "BULL" or (len(swing_lows) >= 2 and swing_lows[-1][1] > swing_lows[-2][1]):
            structure = "BEARISH_CHOCH"
        else:
            structure = "BEARISH_BOS"

    sweep = "NONE"
    bull_sweep = bool(swing_lows and l_last < swing_lows[-1][1] and c_last > swing_lows[-1][1])
    bear_sweep = bool(swing_highs and h_last > swing_highs[-1][1] and c_last < swing_highs[-1][1])
    if bull_sweep and not bear_sweep:
        sweep = "BULLISH_SWEEP"
    elif bear_sweep and not bull_sweep:
        sweep = "BEARISH_SWEEP"
    elif bull_sweep and bear_sweep:
        sweep = "BULLISH_SWEEP" if c_last >= o_last else "BEARISH_SWEEP"

    asian_sweep = _detect_asian_sweep(h, l, c, bar_times, n)

    return {
        "structure": structure,
        "sweep": sweep,
        "asian_sweep": asian_sweep,
    }


def compute_hmm_regime(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> Dict[str, Any]:
    """3-Durumlu Gaussian-Markov (HMM) İleri Filtre Rejim Sınıflandırıcısı.

    Saf Python + math, nedensel ve ölçek-bağımsız:
      - State 0: LOW_VOL_RANGE    (düşük volatilite / yatay)
      - State 1: TREND_EXPANSION  (yüksek verimlilik / yönlü trend)
      - State 2: SHOCK_VOLATILITY (aşırı Parkinson aralığı / şok)
    """
    raw_n = min(len(highs), len(lows), len(closes))
    if raw_n < 25:
        return {
            "hmm_regime": "UNKNOWN",
            "hmm_confidence": 0.0,
            "hmm_probs": {"trend": 0.0, "range": 0.0, "shock": 0.0},
        }

    # Son en fazla 100 geçerli barı hizalı biçimde ayıkla
    tail = min(raw_n, 100)
    hs: List[float] = []
    ls: List[float] = []
    cs: List[float] = []
    for h_raw, l_raw, c_raw in zip(highs[-tail:], lows[-tail:], closes[-tail:]):
        try:
            hf = float(h_raw)
            lf = float(l_raw)
            cf = float(c_raw)
        except (TypeError, ValueError):
            continue
        if (
            math.isfinite(hf)
            and math.isfinite(lf)
            and math.isfinite(cf)
            and hf > 0.0
            and lf > 0.0
            and cf > 0.0
        ):
            if hf < lf:
                hf, lf = lf, hf
            hs.append(hf)
            ls.append(lf)
            cs.append(cf)

    n = len(cs)
    if n < 25:
        return {
            "hmm_regime": "UNKNOWN",
            "hmm_confidence": 0.0,
            "hmm_probs": {"trend": 0.0, "range": 0.0, "shock": 0.0},
        }

    # Nedensel bar özellikleri: log getiri + 5-bar yön verimliliği + Parkinson aralığı
    rets: List[float] = [0.0]
    for i in range(1, n):
        rets.append(math.log(cs[i] / cs[i - 1]))

    pk_ranges: List[float] = []
    for i in range(n):
        rng = math.log(hs[i] / ls[i]) if hs[i] > ls[i] else abs(rets[i])
        pk_ranges.append(max(rng, 1e-9))

    sorted_pk = sorted(pk_ranges)
    mid = n // 2
    med_pk = (
        sorted_pk[mid]
        if n % 2 == 1
        else 0.5 * (sorted_pk[mid - 1] + sorted_pk[mid])
    )
    med_pk = max(med_pk, 1e-9)

    # Emisyon parametreleri: (mu_vol, sig_vol, mu_eff, sig_eff)
    # 0: LOW_VOL_RANGE, 1: TREND_EXPANSION, 2: SHOCK_VOLATILITY
    emissions = (
        (0.75, 0.40, 0.20, 0.18),
        (1.15, 0.45, 0.70, 0.20),
        (2.20, 0.55, 0.35, 0.25),
    )
    # Yapışkan geçiş matrisi: 0.84 kendi durumu, 0.08 diğer durumlar
    trans = (
        (0.84, 0.08, 0.08),
        (0.08, 0.84, 0.08),
        (0.08, 0.08, 0.84),
    )

    alpha = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
    eps = 1e-12

    for t in range(1, n):
        w_start = max(1, t - 4)
        win_rets = rets[w_start : t + 1]
        net_move = abs(sum(win_rets))
        tot_move = sum(abs(r) for r in win_rets)
        eff = net_move / (tot_move + eps) if tot_move > eps else 0.0
        eff = max(0.0, min(1.0, eff))

        vol_ratio = max(0.1, min(6.0, pk_ranges[t] / med_pk))

        # İleri adım: tahmin + Gaussian log-olabilirlik
        log_post: List[float] = []
        for j in range(3):
            pred = (
                alpha[0] * trans[0][j]
                + alpha[1] * trans[1][j]
                + alpha[2] * trans[2][j]
            )
            mu_v, sig_v, mu_e, sig_e = emissions[j]
            zv = (vol_ratio - mu_v) / sig_v
            ze = (eff - mu_e) / sig_e
            ll = -0.5 * (zv * zv + ze * ze) - math.log(sig_v * sig_e)
            log_post.append(math.log(max(pred, 1e-30)) + ll)

        max_lp = max(log_post)
        unnorm = [math.exp(lp - max_lp) for lp in log_post]
        norm_s = sum(unnorm)
        if norm_s > 0.0 and math.isfinite(norm_s):
            alpha = [u / norm_s for u in unnorm]
        else:
            alpha = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]

    states = ("LOW_VOL_RANGE", "TREND_EXPANSION", "SHOCK_VOLATILITY")
    best_idx = max(range(3), key=lambda k: alpha[k])
    return {
        "hmm_regime": states[best_idx],
        "hmm_confidence": round(alpha[best_idx], 2),
        "hmm_probs": {
            "trend": round(alpha[1], 3),
            "range": round(alpha[0], 3),
            "shock": round(alpha[2], 3),
        },
    }


def evaluate_ohlc(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    bar_times: Optional[Sequence[Any]] = None,
    action: str = "HOLD",
) -> Dict[str, Any]:
    """Hurst + Kalman + SMC + HMM sonuçlarını tek kompakt sözlükte ve skor deltasıyla birleştirir."""
    hurst_res = compute_hurst_exponent(closes)
    kalman_res = compute_kalman_filter(closes)
    smc_res = detect_smc_structure(opens, highs, lows, closes, bar_times=bar_times)
    hmm_res = compute_hmm_regime(highs, lows, closes)

    h_val = hurst_res["hurst"]
    h_regime = hurst_res["regime"]
    k_level = kalman_res["level"]
    k_slope = kalman_res["slope_bps"]
    k_dir = kalman_res["dir"]
    k_z = kalman_res["zscore"]
    k_over = kalman_res["overextended"]
    smc_struct = smc_res["structure"]
    smc_sweep = smc_res["sweep"]
    asian_sweep = smc_res["asian_sweep"]
    hmm_regime = hmm_res["hmm_regime"]
    hmm_conf = hmm_res["hmm_confidence"]
    hmm_probs = hmm_res["hmm_probs"]

    act = str(action or "HOLD").upper()
    delta = 0.0
    if act in ("BUY", "SELL"):
        is_buy = act == "BUY"

        # 1. Hurst rejimi
        if h_regime == "TREND":
            delta += 3.0
        elif h_regime == "RANDOM_WALK":
            delta -= 4.0

        # 2. Kalman yönü & aşırı uzama (tepe/dip kovalama cezası)
        if (is_buy and k_dir == "UP") or (not is_buy and k_dir == "DOWN"):
            delta += 3.0
        elif (is_buy and k_dir == "DOWN") or (not is_buy and k_dir == "UP"):
            delta -= 3.0

        if k_over and ((is_buy and k_z >= 2.2) or (not is_buy and k_z <= -2.2)):
            delta -= 5.0

        # 3. SMC yapı kırılımı (BOS / CHoCH)
        if smc_struct in ("BULLISH_BOS", "BULLISH_CHOCH"):
            delta += 3.0 if is_buy else -3.0
        elif smc_struct in ("BEARISH_BOS", "BEARISH_CHOCH"):
            delta += 3.0 if not is_buy else -3.0

        # 4. SMC likidite avı
        if smc_sweep == "BULLISH_SWEEP":
            delta += 4.0 if is_buy else -3.0
        elif smc_sweep == "BEARISH_SWEEP":
            delta += 4.0 if not is_buy else -3.0

        # 5. Asya oturumu tuzağı (Judas swing)
        if asian_sweep == "LOW_SWEPT":
            delta += 3.0 if is_buy else -3.0
        elif asian_sweep == "HIGH_SWEPT":
            delta += 3.0 if not is_buy else -3.0

        # 6. 3-Durumlu HMM rejim düzeltmesi
        if hmm_regime == "TREND_EXPANSION" and hmm_conf >= 0.55:
            delta += 2.5
        elif hmm_regime == "SHOCK_VOLATILITY" and hmm_conf >= 0.55:
            delta -= 3.5
        elif hmm_regime == "LOW_VOL_RANGE" and hmm_conf >= 0.65:
            delta -= 2.0

        delta = round(max(-12.0, min(12.0, delta)), 1)

    badges: List[str] = []
    if h_val is not None:
        if h_regime == "TREND":
            badges.append(f"H {h_val:.2f} · TREND")
        elif h_regime == "MEAN_REVERT":
            badges.append(f"H {h_val:.2f} · YATAY")
        elif h_regime == "RANDOM_WALK":
            badges.append(f"H {h_val:.2f} · GÜRÜLTÜ")
    if hmm_regime == "TREND_EXPANSION":
        badges.append(f"HMM Trend %{int(round(hmm_conf * 100))}")
    elif hmm_regime == "SHOCK_VOLATILITY":
        badges.append(f"⚡ HMM Şok %{int(round(hmm_conf * 100))}")
    elif hmm_regime == "LOW_VOL_RANGE":
        badges.append(f"HMM Yatay %{int(round(hmm_conf * 100))}")
    if smc_sweep != "NONE":
        badges.append("⚡ SWEEP")
    if smc_struct in ("BULLISH_BOS", "BEARISH_BOS"):
        badges.append("BOS")
    elif smc_struct in ("BULLISH_CHOCH", "BEARISH_CHOCH"):
        badges.append("CHoCH")
    if asian_sweep != "NONE":
        badges.append("Asya Tuzağı")
    if k_over:
        badges.append("⚠️ Aşırı Uzamış")

    return {
        "hurst": h_val,
        "hurst_regime": h_regime,
        "kalman_level": k_level,
        "kalman_slope_bps": k_slope,
        "kalman_dir": k_dir,
        "kalman_zscore": k_z,
        "kalman_overextended": k_over,
        "smc_structure": smc_struct,
        "smc_sweep": smc_sweep,
        "asian_sweep": asian_sweep,
        "hmm_regime": hmm_regime,
        "hmm_confidence": hmm_conf,
        "hmm_probs": hmm_probs,
        "quant_score_delta": delta,
        "quant_badges": badges,
    }
