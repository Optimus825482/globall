"""EDGE ANLAMLILIĞI — "gerçek kenar mı, şans mı?" (2026-11-09)

NEDEN VAR
---------
Repo geçmişinde onlarca parametre taraması var (`portfolio-*-filter-sweep-*`,
`*-regime-matrix-*`, `*-regime-refinement-*` …). Her taramada "en iyi" bir
varyant seçiliyor. **Çoklu test problemi**: N strateji/parametre denerseniz,
hepsi saf gürültü olsa bile en iyisi kağıt üzerinde pozitif Sharpe gösterir.
Bu betik o iddiayı istatistiksel olarak sınar.

KULLANILAN TESTLER (hepsi `arch` içinde, permissive lisans — MIT değil ama
"Permission is hereby granted, free of charge … without restriction"):
  * RealityCheck — White (2000) "Bootstrap Reality Check"
  * SPA          — Hansen (2005) "Superior Predictive Ability" (RC'nin,
                   zayıf modelleri eleyerek güçlendirilmiş hâli)
  * StepM        — Romano & Wolf (2005) "Stepwise Multiple Testing" (FDR benzeri)
  * MCS          — Hansen, Lunde, Nason (2011) "Model Confidence Set"

GİRDİ
-----
Bir dönem × strateji getiri matrisi (CSV: ilk kolon tarih/sıra, diğerleri
strateji). Ölçüm **LOSS = -return** üzerinden yapılır (arch API'si kayıp ister).
Benchmark varsayılan olarak sıfır getiridir ("hiç işlem yapmamak").

ÇIKTI
-----
Her strateji için: ortalama getiri, Sharpe, SPA/RC/StepM p-değerleri ve
MCS'e dahil mi. Karar: p < 0.05 olan strateji "anlamlı"; MCS dışında kalan
"istatistiksel olarak elenmiş".

DOĞRULAMA
---------
`--demo noise` : tüm seriler saf gürültü → HİÇBİRİ anlamlı çıkmamalı.
`--demo edge`  : biri gerçek pozitif ortalamalı → YALNIZ o anlamlı çıkmalı.
Bu iki demo, aracın "her şeyi anlamlı bulma" hatasına düşmediğini kanıtlar.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# arch/pandas yalnız ARAŞTIRMA katmanındadır (üretim requirements'ta yok).
try:
    import pandas as pd
    from arch.bootstrap import MCS, SPA, RealityCheck, StepM
except ImportError as exc:  # pragma: no cover
    sys.exit(
        "Eksik araştırma bağımlılığı: "
        f"{exc}. Kurulum: pip install -r backend/requirements-research.txt"
    )


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
#: `--out` verilmezse sonuç buraya yazılır (app/edge_validation.py okur).
DEFAULT_ARTIFACT = ROOT / "artifacts" / "edge_validation.json"


def _sharpe(returns: np.ndarray, bars_per_year: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    sd = float(r.std(ddof=1))
    if sd == 0:
        return 0.0
    return float(r.mean() / sd * np.sqrt(bars_per_year))


def _demo(kind: str, n_periods: int = 750, n_strategies: int = 6, seed: int = 42) -> pd.DataFrame:
    """Bilinen cevaplı sentetik veri.

    noise : hepsi ortalaması 0 → hiçbiri anlamlı olmamalı
    edge  : yalnızca ``edge_gercek`` pozitif ortalama taşır
    """
    rng = np.random.default_rng(seed)
    data = {}
    for i in range(n_strategies):
        base = rng.normal(0.0, 0.01, n_periods)  # sıfır ortalama, %1 vol
        data[f"gurultu_{i}"] = base
    if kind == "edge":
        # Gerçek kenar: +0.003/dönem ortalama, aynı vol → yıllık Sharpe ~4.7
        data["edge_gercek"] = rng.normal(0.003, 0.01, n_periods)
    return pd.DataFrame(data, index=pd.RangeIndex(n_periods, name="period"))


def load_matrix(path: str) -> pd.DataFrame:
    """CSV/parquet getiri matrisi. İlk kolon tarih/index olabilir."""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Dosya yok: {path}")
    if p.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)
        # İlk kolon sayısal değilse (tarih vb.) indekse al
        first = df.columns[0]
        if not np.issubdtype(df[first].dtype, np.number):
            df = df.set_index(first)
    df = df.apply(pd.to_numeric, errors="coerce").dropna(how="all").fillna(0.0)
    if df.shape[1] < 2:
        raise SystemExit("En az 2 strateji kolonu gerekir (karşılaştırma için).")
    return df


def run(returns: pd.DataFrame, *, reps: int = 2000, size: float = 0.05,
        bars_per_year: int = 252) -> dict:
    """Tüm testleri koştur, özet tablo döndür."""
    # ÖNEMLİ: `arch`'a pandas DataFrame verilir → sonuçlar İSİMLERLE döner
    # (`mcs.included=["CCC"]`). numpy matris verilirse konumsal diziler döner ve
    # sütun sırası eşlemesi ELLE yapılmak zorunda kalır; bir turda bu yüzden
    # NEGATİF Sharpe'lı bir strateji "ÜSTÜN" işaretlendi. İsim eşlemesi bu hata
    # sınıfını tamamen ortadan kaldırır.
    loss_df = -returns
    losses = loss_df.to_numpy(dtype=float)
    names = list(returns.columns)
    # Benchmark: "hiç işlem yapmamak" → kayıp 0. Alternatif: eşit ağırlık sepette.
    benchmark = np.zeros(losses.shape[0])

    results: dict[str, object] = {"strategies": {}, "pvalues": {}, "mcs_included": []}

    spa = SPA(benchmark, loss_df, reps=reps, block_size=None)
    spa.compute()
    rc = RealityCheck(benchmark, loss_df, reps=reps, block_size=None)
    rc.compute()
    stepm = StepM(benchmark, loss_df, size=size, reps=reps, block_size=None)
    stepm.compute()

    # arch 8.x GERÇEK API: SPA/RealityCheck `.pvalues` = Series
    # ["lower","consistent","upper"]; Hansen'ın önerdiği "consistent" alınır.
    # StepM'in p-değeri YOK — `superior_models` (hangileri anlamlı üstün) verir.
    def consistent(obj) -> float | None:
        try:
            return float(obj.pvalues.loc["consistent"])
        except Exception:
            return None

    spa_p = consistent(spa)
    rc_p = consistent(rc)
    stepm_spa_p = None
    try:
        stepm_spa_p = float(stepm.spa.pvalues.loc["consistent"])
    except Exception:
        pass
    # İSİM listesi (konum değil) — DataFrame girdi sayesinde.
    try:
        superior = [str(x) for x in stepm.superior_models]
    except Exception:
        superior = []

    mcs = MCS(loss_df, size=size, reps=reps, block_size=None)
    mcs.compute()
    try:
        included = [str(x) for x in mcs.included]
    except Exception:
        included = []

    for name in names:
        col = returns[name].to_numpy(dtype=float)
        results["strategies"][name] = {
            "mean": round(float(col.mean()), 8),
            "sharpe": round(_sharpe(col, bars_per_year), 3),
            "total_return": round(float((1 + col).prod() - 1), 6),
            "mcs_included": name in included,
            "stepm_superior": name in superior,
        }

    results["pvalues"] = {
        "reality_check": None if rc_p is None else round(rc_p, 4),
        "spa": None if spa_p is None else round(spa_p, 4),
        "stepm": None if stepm_spa_p is None else round(stepm_spa_p, 4),
        "size": size, "reps": reps, "n_periods": int(losses.shape[0]),
    }
    results["mcs_included"] = list(included)
    results["stepm_superior"] = list(superior)
    # Bütünsel hüküm: SPA anlamlı mı?
    results["verdict"] = (
        "KENAR VAR (SPA anlamlı)" if spa_p is not None and spa_p < size
        else "KENAR YOK / KANITLANAMADI (SPA anlamsız)"
    )
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Edge anlamlılığı: RC / SPA / StepM / MCS")
    ap.add_argument("--csv", help="getiri matrisi (dönem × strateji)")
    ap.add_argument("--demo", choices=["noise", "edge"], help="bilinen cevaplı sentetik veri")
    ap.add_argument("--reps", type=int, default=2000, help="bootstrap tekrarı")
    ap.add_argument("--size", type=float, default=0.05, help="anlamlılık düzeyi")
    ap.add_argument("--bars-per-year", type=int, default=252)
    ap.add_argument("--json", action="store_true", help="makine-okur çıktı")
    # 2026-11-09: sonuç ARTEFAKTA yazılabilsin. Yalnız stdout'a yazmak
    # "hangi strateji gürültü" bilgisini karar yüzeylerinden koparıyordu.
    ap.add_argument("--out", nargs="?", const=str(DEFAULT_ARTIFACT),
                    help="JSON artefakt dosyası (verilmezse varsayılan yol)")
    args = ap.parse_args(argv)

    if not args.csv and not args.demo:
        ap.error("--csv veya --demo gerekli")

    returns = _demo(args.demo) if args.demo else load_matrix(args.csv)
    res = run(returns, reps=args.reps, size=args.size, bars_per_year=args.bars_per_year)

    if args.out:
        from app import edge_validation
        print(f"artefakt yazıldı: {edge_validation.write_section('significance', res, args.out)}")

    if args.json:
        import json
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    p = res["pvalues"]
    print("=" * 78)
    print(f"EDGE ANLAMLILIĞI  ·  dönem={p['n_periods']}  strateji={len(res['strategies'])}  reps={p['reps']}")
    print("=" * 78)
    print(f"{'strateji':<26}{'ort.':>10}{'Sharpe':>9}{'StepM':>10}{'MCS':>7}")
    print("-" * 78)
    for name, s in sorted(res["strategies"].items(), key=lambda kv: -kv[1]["sharpe"]):
        mcs = "var" if s["mcs_included"] else "ELENDİ"
        stepm = "ÜSTÜN" if s["stepm_superior"] else "-"
        print(f"{name:<26}{s['mean']:>10.5f}{s['sharpe']:>9.2f}{stepm:>10}{mcs:>7}")
    print("-" * 78)
    print(f"Reality Check p = {p['reality_check']}   SPA p = {p['spa']}   StepM p = {p['stepm']}   (eşik {p['size']})")
    print(f"MCS'e dahil: {', '.join(res['mcs_included']) or '(hiçbiri)'}")
    print()
    print(f">>> HÜKÜM: {res['verdict']}")
    print()
    print("Yorum: SPA, 'en iyi strateji sadece şans eseri mi iyi görünüyor?' sorusunu")
    print("yanıtlar. p >= 0.05 ise bu evrende KANITLANMIŞ kenar yoktur; aynı veriyle")
    print("parametre taramasına devam etmek aşırı uyumu büyütür.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
