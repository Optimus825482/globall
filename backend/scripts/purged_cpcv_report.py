"""AŞIRI UYUM DENETİMİ — PSR / DSR / PBO / MinTRL (+ CPCV bağlantısı) (2026-11-09)

NEDEN VAR
---------
Sistemin kill kriteri PF<1.0. Ama **çoklu test** problemi PF'yi de şişirir:
20 strateji denerseniz, hepsi saf gürültü olsa bile en iyisi pozitif PF/Sharpe
gösterir. Bu betik üç soruyu yanıtlar:

1. **PSR (Probabilistic Sharpe Ratio)** — gözlenen Sharpe, "gerçek beceri 0"
   hipotezine göre istatistiksel olarak anlamlı mı? (örneklem uzunluğu, çarpıklık
   ve basıklığı hesaba katar — naif `Sharpe>1` kontrolünden çok daha dürüst.)
2. **DSR (Deflated Sharpe Ratio)** — kaç farklı konfigürasyon denendiğini
   cezalandırır. "100 varyant taradım, en iyisi 2.1 Sharpe" → DSR bunu yer.
3. **PBO (Probability of Backtest Overfitting, CSCV)** — seçilen "en iyi"
   konfigürasyonun test dışı dönemde medyanın ALTINA düşme olasılığı.
   PBO > 0.5 ise seçim süreci aşırı uyumlu; kenar değil, gürültü seçilmiş.
4. **MinTRL (Minimum Track Record Length)** — gözlenen Sharpe'ın anlamlı
   sayılması için gereken minimum gözlem sayısı. Elimizdeki veri bundan
   kısaysa "kanıt yok" demektir.

KÜTÜPHANE
---------
`purgedcv` (MIT, aktif — 2026-11-08 push). **AGPL `pypbo`'ya gerek yok**:
PBO da bu pakette. `mlfinlab` (lisansı SPDX tanınmıyor, 2023'te donmuş)
KULLANILMAZ.

GİRDİ
-----
Dönem × strateji getiri matrisi (CSV/parquet) veya `--demo`.
Sütunlar = denenen konfigürasyonlar (parametre varyantları dahil) — bu, DSR/PBO
için "kaç deneme yapıldı" bilgisini doğal olarak taşır.

DOĞRULAMA
---------
`--demo noise` : PSR düşük (<0.95), PBO yüksek → "aşırı uyum riski" hükmü.
`--demo edge`  : PSR yüksek (>=0.95), PBO düşük → "kanıtlanmış" hükmü.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import pandas as pd
    import purgedcv
except ImportError as exc:  # pragma: no cover
    sys.exit(
        f"Eksik araştırma bağımlılığı: {exc}. "
        "Kurulum: pip install -r backend/requirements-research.txt"
    )

#: PSR/DSR için "anlamlı" kabul edilen eşik (tek taraflı %5).
SIGNIFICANCE = 0.95
#: PBO üstünde seçim süreci aşırı uyumlu sayılır.
PBO_DANGER = 0.50


def _sharpe(returns: np.ndarray, bars_per_year: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    sd = float(r.std(ddof=1))
    return 0.0 if sd == 0 else float(r.mean() / sd * np.sqrt(bars_per_year))


def _demo(kind: str, n_periods: int = 900, n_configs: int = 8, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = {f"cfg_{i}": rng.normal(0.0, 0.01, n_periods) for i in range(n_configs)}
    if kind == "edge":
        data["cfg_gercek"] = rng.normal(0.0035, 0.01, n_periods)
    return pd.DataFrame(data, index=pd.RangeIndex(n_periods, name="period"))


def load_matrix(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Dosya yok: {path}")
    df = pd.read_parquet(p) if p.suffix.lower() in {".parquet", ".pq"} else pd.read_csv(p)
    first = df.columns[0]
    if not np.issubdtype(df[first].dtype, np.number):
        df = df.set_index(first)
    df = df.apply(pd.to_numeric, errors="coerce").dropna(how="all").fillna(0.0)
    if df.shape[1] < 2:
        raise SystemExit("En az 2 konfigürasyon kolonu gerekir.")
    return df


def run(returns: pd.DataFrame, *, bars_per_year: int = 252) -> dict:
    names = list(returns.columns)
    arr = returns.to_numpy(dtype=float)
    sharpes = np.array([_sharpe(arr[:, j], bars_per_year) for j in range(arr.shape[1])])

    # Denenen konfigürasyon sayısı: DSR'nin cezalandırdığı "kaç kez baktım".
    try:
        n_trials = int(purgedcv.effective_n_trials(sharpes))
    except Exception:
        n_trials = int(len(names))
    var_sharpe = float(np.var(sharpes, ddof=1)) if sharpes.size > 1 else 0.0

    # PBO: (n_configs, n_obs) — CSCV
    pbo_value = None
    pbo_detail = {}
    try:
        pb = purgedcv.probability_of_backtest_overfitting(arr.T, n_splits=min(16, max(4, arr.shape[0] // 20)))
        pbo_value = float(getattr(pb, "pbo", pb) if not isinstance(pb, (int, float)) else pb)
        # purgedcv 0.1.x PBOResult alanları: pbo, n_combos, slope, logits
        for attr in ("n_combos", "slope"):
            v = getattr(pb, attr, None)
            if v is not None:
                pbo_detail[attr] = v
    except Exception as exc:
        pbo_detail["error"] = f"{type(exc).__name__}: {exc}"

    rows = {}
    for j, name in enumerate(names):
        col = arr[:, j]
        sh = float(sharpes[j])
        skew = float(pd.Series(col).skew())
        kurt = float(pd.Series(col).kurt()) + 3.0  # pandas fazlalık basıklık → gerçek
        try:
            psr = float(purgedcv.probabilistic_sharpe_ratio(col, benchmark_skill=0.0))
        except Exception:
            psr = None
        try:
            dsr = float(purgedcv.deflated_sharpe_ratio(
                col, n_trials=max(2, n_trials), var_sharpe=max(var_sharpe, 1e-12),
                bars_per_year=bars_per_year))
        except Exception:
            dsr = None
        try:
            mtrl = float(purgedcv.min_track_record_length(
                observed_sharpe=sh, target_sharpe=0.0, alpha=0.05,
                skew=skew if np.isfinite(skew) else 0.0,
                kurtosis=kurt if np.isfinite(kurt) else 3.0))
        except Exception:
            mtrl = None
        rows[name] = {
            "sharpe": round(sh, 3),
            "psr": None if psr is None else round(psr, 4),
            "dsr": None if dsr is None else round(dsr, 4),
            "min_track_length": None if mtrl is None else round(mtrl, 1),
            "periods": int(col.size),
            "enough_data": None if mtrl is None else bool(col.size >= mtrl),
        }

    best = max(rows.items(), key=lambda kv: kv[1]["sharpe"]) if rows else (None, {})
    psr_best = best[1].get("psr")
    dsr_best = best[1].get("dsr")

    if pbo_value is not None and pbo_value > PBO_DANGER:
        verdict = "AŞIRI UYUM RİSKİ (PBO yüksek) — seçilen 'en iyi' büyük olasılıkla gürültü"
    elif psr_best is not None and dsr_best is not None and psr_best >= SIGNIFICANCE and dsr_best >= SIGNIFICANCE:
        verdict = "KANITLANMIŞ (PSR ve DSR eşiği aştı)"
    else:
        verdict = "KANITLANAMADI — örneklem/deneme sayısı yetersiz ya da kenar yok"

    return {
        "strategies": rows,
        "best": best[0],
        "n_trials": n_trials,
        "var_sharpe": round(var_sharpe, 6),
        "pbo": None if pbo_value is None else round(pbo_value, 4),
        "pbo_detail": pbo_detail,
        "thresholds": {"psr_dsr": SIGNIFICANCE, "pbo_danger": PBO_DANGER},
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PSR / DSR / PBO / MinTRL denetimi")
    ap.add_argument("--csv", help="getiri matrisi (dönem × konfigürasyon)")
    ap.add_argument("--demo", choices=["noise", "edge"])
    ap.add_argument("--bars-per-year", type=int, default=252)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.csv and not args.demo:
        ap.error("--csv veya --demo gerekli")

    returns = _demo(args.demo) if args.demo else load_matrix(args.csv)
    res = run(returns, bars_per_year=args.bars_per_year)

    if args.json:
        import json
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print("=" * 88)
    print(f"AŞIRI UYUM DENETİMİ · dönem={returns.shape[0]} konfig={returns.shape[1]} "
          f"deneme(n_trials)={res['n_trials']}")
    print("=" * 88)
    print(f"{'konfig':<20}{'Sharpe':>9}{'PSR':>9}{'DSR':>9}{'MinTRL':>9}{'dönem':>8}  veri")
    print("-" * 88)
    for name, r in sorted(res["strategies"].items(), key=lambda kv: -kv[1]["sharpe"]):
        psr = "-" if r["psr"] is None else f"{r['psr']:.3f}"
        dsr = "-" if r["dsr"] is None else f"{r['dsr']:.3f}"
        mtrl = "-" if r["min_track_length"] is None else f"{r['min_track_length']:.0f}"
        flag = "YETER" if r["enough_data"] else "YETERSİZ"
        print(f"{name:<20}{r['sharpe']:>9.2f}{psr:>9}{dsr:>9}{mtrl:>9}{r['periods']:>8}  {flag}")
    print("-" * 88)
    pbo = res["pbo"]
    print(f"PBO = {pbo}  (>{res['thresholds']['pbo_danger']} ise seçim süreci aşırı uyumlu) {res['pbo_detail']}")
    print(f"En iyi: {res['best']}  |  eşik PSR/DSR >= {res['thresholds']['psr_dsr']}")
    print()
    print(f">>> HÜKÜM: {res['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
