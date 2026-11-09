"""BASELINE KARŞILAŞTIRMASI + ÇOKLU-TEST DÜZELTMESİ (2026-11-09)

İKİ İŞ YAPAR
============

1) `baseline` — "ML modeli naif kuralı yeniyor mu?"
----------------------------------------------------
Her ML projesinin en ucuz filtresi: model, **aptal bir baseline'ı** geçemiyorsa
işe yaramaz. Bu komut bir tahmin serisini üç naif kurala karşı test eder:

    always_long  : her zaman al (piyasanın uzun vade sürüklenmesi)
    persistence  : önceki barın yönünü tekrarla (momentum-0)
    coin         : yazı tura (rastgele)

Ölçülen: isabet oranı, alınan işlemlerin ortalama getirisi ve **tek taraflı
binom testi** ile "baseline'dan anlamlı iyi mi?" (p-değeri). Model gerçekten
kenar taşımıyorsa p büyük çıkar — bu, aşırı uyumlu bir modele güvenmeyi
engelleyen en ucuz kalkandır.

Girdi CSV kolonları: `pred` (model yönü: +1 / -1 / 0) ve `ret` (gerçekleşen
getiri). Model olasılık üretiyorsa `--prob-col` ile eşik uygulanır.

2) `multitest` — çoklu-test düzeltmesi
--------------------------------------
Parametre taraması N varyant deniyorsa, "en iyi"nin p-değeri **düzeltilmemiş**
ise yanıltıcıdır. `statsmodels.multipletests` ile düzeltir:

    fdr_bh      : Benjamini-Hochberg (keşif odaklı, en güçlü)
    holm        : Holm-Bonferroni (FWER, daha muhafazakâr)
    bonferroni  : en muhafazakâr

Girdi CSV: `name, pvalue` (sweep/deney tablosu). Çıktı: düzeltilmiş p ve karar.

NEDEN ARAŞTIRMA KATMANI: `statsmodels` + `scipy` üretim imajında YOK
(`requirements.txt` bilinçli yalın: numpy + scikit-learn). Bu betikler
`backend/scripts/` altında koşar; sonuçları rapor/JSON olarak taşınır.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import pandas as pd
    from scipy import stats
    from statsmodels.stats.multitest import multipletests
except ImportError as exc:  # pragma: no cover
    sys.exit(f"Eksik araştırma bağımlılığı: {exc}. "
             "Kurulum: pip install -r backend/requirements-research.txt")


# ---------------------------------------------------------------------------
# 1) Baseline karşılaştırması
# ---------------------------------------------------------------------------

def _binom_p(better: int, total: int) -> float:
    """Tek taraflı binom testi: 'better' sayısı yazı-turadan anlamlı fazla mı?"""
    if total <= 0:
        return 1.0
    return float(stats.binomtest(better, total, 0.5, alternative="greater").pvalue)


def compare_baselines(pred: np.ndarray, ret: np.ndarray) -> dict:
    """Tahmin serisini naif kurallarla karşılaştır (dönem bazlı)."""
    n = int(min(len(pred), len(ret)))
    pred = np.asarray(pred[:n], dtype=float)
    ret = np.asarray(ret[:n], dtype=float)
    valid = np.isfinite(pred) & np.isfinite(ret)
    pred, ret = pred[valid], ret[valid]
    if pred.size == 0:
        return {"error": "geçerli gözlem yok"}

    mask = pred != 0                      # modelin işlem açtığı barlar
    taken = int(mask.sum())
    hit = int((np.sign(pred[mask]) == np.sign(ret[mask])).sum()) if taken else 0
    model_mean = float((np.sign(pred[mask]) * ret[mask]).mean()) if taken else 0.0

    rows: dict[str, dict] = {}
    # always_long: her bar +1
    long_hit = int((ret > 0).sum())
    rows["always_long"] = {
        "trades": int(ret.size),
        "hit_rate": round(float(long_hit / ret.size), 4) if ret.size else None,
        "mean_return": round(float(ret.mean()), 8),
    }
    # persistence: önceki barın yönü
    if ret.size > 1:
        pers_pred = np.sign(ret[:-1])
        pers_ret = ret[1:]
        pers_mask = pers_pred != 0
        pers_taken = int(pers_mask.sum())
        rows["persistence"] = {
            "trades": pers_taken,
            "hit_rate": round(float((pers_pred[pers_mask] == np.sign(pers_ret[pers_mask])).mean()), 4) if pers_taken else None,
            "mean_return": round(float((pers_pred[pers_mask] * pers_ret[pers_mask]).mean()), 8) if pers_taken else 0.0,
        }
    # coin: 0.5 beklenti
    rows["coin"] = {"trades": int(ret.size), "hit_rate": 0.5, "mean_return": 0.0}

    model = {
        "trades": taken,
        "coverage": round(taken / pred.size, 4) if pred.size else 0.0,
        "hit_rate": round(hit / taken, 4) if taken else None,
        "mean_return": round(model_mean, 8),
        "binom_p_vs_coin": round(_binom_p(hit, taken), 6) if taken else None,
    }
    # Modeli always_long'a karşı: modelin AL sinyallerinin isabeti > taban oran mı?
    long_pred = pred > 0
    lp = int(long_pred.sum())
    lp_hit = int((ret[long_pred] > 0).sum()) if lp else 0
    base_rate = float((ret > 0).mean()) if ret.size else 0.5
    p_vs_long = None
    if lp > 0:
        p_vs_long = float(stats.binomtest(lp_hit, lp, max(base_rate, 1e-9),
                                          alternative="greater").pvalue)

    verdict = "KANIT YOK (baseline'ı anlamlı geçmiyor)"
    if model["binom_p_vs_coin"] is not None and model["binom_p_vs_coin"] < 0.05:
        verdict = "YAZI-TURADAN ANLAMLI İYİ"
    if p_vs_long is not None and p_vs_long < 0.05:
        verdict = "BASELINE'DAN (always_long) ANLAMLI İYİ"

    return {"model": model, "baselines": rows, "base_rate": round(base_rate, 4),
            "p_vs_always_long": None if p_vs_long is None else round(p_vs_long, 6),
            "n": int(pred.size), "verdict": verdict}


def _demo_baseline(kind: str, n: int = 2000, seed: int = 5):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0, 0.01, n)
    if kind == "edge":
        # Model gerçekten yön biliyor: işaret doğruluk olasılığı %58
        pred = np.where(rng.random(n) < 0.58, np.sign(ret), -np.sign(ret))
    else:
        # Saf gürültü tahmini: yön bağımsız
        pred = rng.choice([-1.0, 1.0], size=n)
    return pred, ret


# ---------------------------------------------------------------------------
# 2) Çoklu-test düzeltmesi
# ---------------------------------------------------------------------------

def correct_multiple(pvals, names, method: str = "fdr_bh", alpha: float = 0.05) -> dict:
    p = np.asarray(list(pvals), dtype=float)
    p = np.clip(p, 0.0, 1.0)
    if p.size == 0:
        return {"error": "p-değeri yok"}
    reject, adj, _, _ = multipletests(p, alpha=alpha, method=method)
    rows = []
    for i, name in enumerate(names):
        rows.append({
            "name": str(name),
            "p_raw": round(float(p[i]), 6),
            "p_adjusted": round(float(adj[i]), 6),
            "significant_raw": bool(p[i] < alpha),
            "significant_adjusted": bool(reject[i]),
        })
    rows.sort(key=lambda r: r["p_adjusted"])
    survived = sum(1 for r in rows if r["significant_adjusted"])
    killed = sum(1 for r in rows if r["significant_raw"] and not r["significant_adjusted"])
    return {
        "method": method, "alpha": alpha, "n_tests": int(p.size),
        "survived": survived, "killed_by_correction": killed, "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Baseline karşılaştırması ve çoklu-test düzeltmesi")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("baseline", help="model vs naif kurallar")
    b.add_argument("--csv", help="kolonlar: pred, ret")
    b.add_argument("--pred-col", default="pred")
    b.add_argument("--ret-col", default="ret")
    b.add_argument("--prob-col", help="olasılık kolonu (>=0.5 al, <0.5 sat)")
    b.add_argument("--demo", choices=["noise", "edge"])

    m = sub.add_parser("multitest", help="BH/Holm/Bonferroni düzeltmesi")
    m.add_argument("--csv", help="kolonlar: name, pvalue")
    m.add_argument("--method", default="fdr_bh", choices=["fdr_bh", "holm", "bonferroni"])
    m.add_argument("--alpha", type=float, default=0.05)

    args = ap.parse_args(argv)

    if args.cmd == "baseline":
        if args.demo:
            pred, ret = _demo_baseline(args.demo)
        elif args.csv:
            df = pd.read_csv(args.csv)
            pred = df[args.pred_col].to_numpy(dtype=float)
            if args.prob_col:
                prob = df[args.prob_col].to_numpy(dtype=float)
                pred = np.where(prob >= 0.5, 1.0, -1.0)
            ret = df[args.ret_col].to_numpy(dtype=float)
        else:
            ap.error("--csv veya --demo gerekli")
        res = compare_baselines(pred, ret)
        print("=" * 74)
        print("BASELINE KARŞILAŞTIRMASI — model aptal kuralı yeniyor mu?")
        print("=" * 74)
        mo = res.get("model") or {}
        print(f"gözlem={res.get('n')}  taban isabet oranı={res.get('base_rate')}")
        print()
        print(f"{'kural':<16}{'işlem':>8}{'isabet':>9}{'ort.getiri':>12}")
        print("-" * 74)
        for name, r in res.get("baselines", {}).items():
            hr = "-" if r["hit_rate"] is None else f"{r['hit_rate']:.3f}"
            print(f"{name:<16}{r['trades']:>8}{hr:>9}{r['mean_return']:>12.6f}")
        hr = "-" if mo.get("hit_rate") is None else f"{mo['hit_rate']:.3f}"
        print(f"{'MODEL':<16}{mo.get('trades', 0):>8}{hr:>9}{mo.get('mean_return', 0):>12.6f}")
        print("-" * 74)
        print(f"model kapsama={mo.get('coverage')}  p(vs yazı-tura)={mo.get('binom_p_vs_coin')}"
              f"  p(vs always_long)={res.get('p_vs_always_long')}")
        print()
        print(f">>> HÜKÜM: {res.get('verdict')}")
        return 0

    if args.cmd == "multitest":
        if not args.csv:
            ap.error("--csv gerekli (kolonlar: name, pvalue)")
        df = pd.read_csv(args.csv)
        name_col = "name" if "name" in df.columns else df.columns[0]
        p_col = "pvalue" if "pvalue" in df.columns else df.columns[-1]
        res = correct_multiple(df[p_col].tolist(), df[name_col].tolist(),
                              method=args.method, alpha=args.alpha)
        print("=" * 74)
        print(f"ÇOKLU-TEST DÜZELTMESİ · yöntem={res['method']} · test={res['n_tests']} · alfa={res['alpha']}")
        print("=" * 74)
        print(f"{'ad':<32}{'p (ham)':>11}{'p (düzeltilmiş)':>17}  karar")
        print("-" * 74)
        for r in res["rows"]:
            karar = "GEÇTİ" if r["significant_adjusted"] else (
                "düzeltmede ELENDİ" if r["significant_raw"] else "-")
            print(f"{r['name'][:31]:<32}{r['p_raw']:>11.5f}{r['p_adjusted']:>17.5f}  {karar}")
        print("-" * 74)
        print(f"hayatta kalan: {res['survived']}  ·  düzeltmeyle elenen: {res['killed_by_correction']}")
        print()
        print("Uyarı: her taramada 'en iyi' varyantı seçmeden önce bu tabloya bakın.")
        print("Düzeltmeden sonra anlamlılığını kaybeden varyant, gürültüdür.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
