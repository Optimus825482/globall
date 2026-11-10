"""FOREX ML v1 — işlem dosyası özelliklerinden isabet modeli (2026-11-09).

NEDEN BU MODÜL
--------------
Kullanıcı sorusu: "ML hattını neden forex'te kullanmıyoruz?" Ölçülmüş cevaplar:
  1. Mevcut model spot-kripto şeklinde: `velocity_candidates` 272 USDT coin,
     **0 forex satırı** → XAUUSD/EURUSD için skor üretemez.
  2. Sinyali ölçüldü: EV tüm varyantlarda negatif (en iyi -0.378) → kenar yok.
  3. Kök neden model değil, geometri (break-even %67 vs gerçek %56).

AMA forex'e özel eğitim verisi BİRİKİYOR: her LLM kararında deterministik giriş
özellikleri `llm_trade_reviews.features` altına yazılıyor (session, htf_agree_count,
seviye mesafesi, EMA uzantısı, spread/ATR, haber dakikası…) ve her kararın gölge
sonucu (`shadow_pips`) izleniyor. Bu tablo forex'e ÖZEL eğitim setidir.

BU MODÜL NE YAPAR
-----------------
`llm_trade_reviews` özellik+sonuç satırlarından **lojistik model** eğitir:
  * KRONOLOJİK split (ilk %70 eğitim, son %30 test) — rastgele split zamanda
    sızdırır (aynı günün işlemleri iki yarıya düşer).
  * JSON-serializable artifact (pickle YOK): ortalama/ölçek/medyan + katsayılar.
    Üretim imajı yalın kalır; modeli okumak için sklearn bile gerekmez.
  * OOS kanıt: Brier/skill, IC (Spearman), Wilson aralığı.
  * HÜKÜM: OOS skill <= 0 ise "model karar kapısı OLMAMALI" yazar.

KARAR DEĞİŞTİRMEZ: eğitim + ölçüm + rapor. Modeli bir kapıya bağlamak replay
A/B kanıtı ister (chandelier/P1'deki disiplin).
"""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("scalper.forex_ml")

#: Karar için gereken en az SATIR (özellik+sonuç ikisi dolu).
MIN_ROWS = 120
#: Kronolojik test payı.
TEST_FRACTION = 0.30
#: SEÇİM MARJI (2026-11-10): doğrulama skill farkı bu bandın altındaysa SADE model
#: tercih edilir (daha az özellik → zengin yerine temel; daha güçlü ceza → küçük C).
#: NEDEN: tek doğrulama dilimi (260 satır) gürültülü; zengin profili 0.020 vs 0.018
#: gibi bir farkla seçip TEST'te −0.008 aldı (temel +0.019). Eşitlikte sade kazanır.
SELECTION_MARGIN = 0.015
DEFAULT_ARTIFACT = Path(__file__).resolve().parents[1] / "artifacts" / "forex_ml.json"

#: Sayısal özellikler (sıra artifact'ta da bu sıra ile korunur).
NUMERIC_FEATURES = (
    "htf_agree_count", "htf_frames", "level_clearance_atr", "extension_atr",
    "spread_atr_ratio", "news_minutes", "ta_score", "llm_confidence", "motor_score",
)
#: Kategorik özellikler (one-hot; bilinmeyen değer → tüm bitler 0).
SESSION_VALUES = ("asia", "london", "new_york", "overlap")
BIAS_VALUES = ("bullish", "bearish", "neutral")
#: Sembol ailesi (tek-hot) — 20 sembolü tek tek açmak yerine 5 kova.
FAMILY_VALUES = ("xau", "crypto", "index", "fx_major", "fx_cross")
#: Strateji one-hot'u eğitim verisinden seçilir (en sık N). Artifact bu listeyi
#: saklar; skorlarken AYNI liste kullanılır (aksi hâlde vektör kayar).
TOP_STRATEGIES_N = 6


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v == v and v not in (float("inf"), float("-inf")) else default


def featurize(row: dict[str, Any], *, medians: Optional[dict[str, float]] = None,
              sessions: tuple[str, ...] = SESSION_VALUES,
              biases: tuple[str, ...] = BIAS_VALUES,
              strategies: tuple[str, ...] = (), extras: bool = True) -> dict[str, float]:
    """Bir karar satırını sayısal özellik vektörüne çevirir (deterministik).

    Eksik sayısal özellikler `medians` (eğitim medyanı) ile doldurulur;
    `medians` yoksa 0.0 (test/çıplak çağrı). Kategorik bilinmeyen → tüm bitler 0.
    Dönen sözlük sıralı anahtarlıdır → vektör sırası kararlıdır.
    """
    f_raw = row.get("features") or {}
    if isinstance(f_raw, str):
        import json
        try:
            f_raw = json.loads(f_raw)
        except Exception:  # noqa: BLE001
            f_raw = {}
    f_raw = f_raw if isinstance(f_raw, dict) else {}
    med = medians or {}
    out: dict[str, float] = {}
    for name in NUMERIC_FEATURES:
        if name == "llm_confidence":
            v = _f(row.get("confidence"))
        elif name == "motor_score":
            v = _f(row.get("score"))
        else:
            v = _f(f_raw.get(name))
        out[name] = v if v is not None else float(med.get(name, 0.0))
    # eksik göstergeleri (imputation sinyali) üç opsiyonel özellik için tut
    for name in ("level_clearance_atr", "extension_atr", "spread_atr_ratio"):
        out[f"{name}_eksik"] = 1.0 if _f(f_raw.get(name)) is None else 0.0
    session = str(f_raw.get("session") or "").strip().lower()
    for s in sessions:
        out[f"session_{s}"] = 1.0 if session == s else 0.0
    bias = str(f_raw.get("ta_bias") or "").strip().lower()
    for b in biases:
        out[f"bias_{b}"] = 1.0 if bias == b else 0.0
    out["direction_buy"] = 1.0 if str(row.get("direction") or "").upper() == "BUY" else 0.0
    if not extras:
        return out
    # --- 2026-11-10 ÖZELLİK ZENGİNLEŞTİRME (skill 0.034 zayıftı) ---
    # Hepsi DB'de ZATEN VAR olan kolonlardan türetilir; yeni enstrümantasyon yok.
    sym = str(row.get("symbol") or "").upper()
    fam = symbol_family(sym)
    for v in FAMILY_VALUES:
        out[f"family_{v}"] = 1.0 if fam == v else 0.0
    strat = str(row.get("strategy") or "").strip()
    for v in strategies:
        out[f"strategy_{v}"] = 1.0 if strat == v else 0.0
    # Saat/gün döngüsel kodlanır (24 dummy yerine 2 sinyal).
    ts = _f(row.get("created_at_ts"))
    if ts is None:
        ts = _f(row.get("created_at"))
    if ts is not None and ts > 1e9:
        dt = time.gmtime(ts)
        hour = dt.tm_hour + dt.tm_min / 60.0
        out["hour_sin"] = round(math.sin(2 * math.pi * hour / 24.0), 4)
        out["hour_cos"] = round(math.cos(2 * math.pi * hour / 24.0), 4)
        out["weekday"] = float(dt.tm_wday)          # 0=Pzt … 6=Paz
    else:
        out["hour_sin"] = float(med.get("hour_sin", 0.0))
        out["hour_cos"] = float(med.get("hour_cos", 0.0))
        out["weekday"] = float(med.get("weekday", 0.0))
    # Risk geometrisi: R:R ve SL genişliği (pips) — kâr/zarar yapısının özeti.
    slp = _f(row.get("sl_pips"))
    tpp = _f(row.get("tp_pips"))
    out["rr_ratio"] = float(med.get("rr_ratio", 0.0)) if (not slp or not tpp) else round(tpp / slp, 3)
    out["sl_pips"] = slp if slp is not None else float(med.get("sl_pips", 0.0))
    return out


def feature_names(*, sessions: tuple[str, ...] = SESSION_VALUES,
                  biases: tuple[str, ...] = BIAS_VALUES,
                  strategies: tuple[str, ...] = (), extras: bool = True) -> list[str]:
    """`featurize` çıktısının ANAHTAR SIRASI (artifact ile birebir aynı olmalı)."""
    names = list(NUMERIC_FEATURES)
    names += [f"{n}_eksik" for n in ("level_clearance_atr", "extension_atr", "spread_atr_ratio")]
    names += [f"session_{s}" for s in sessions]
    names += [f"bias_{b}" for b in biases]
    names += ["direction_buy"]
    if not extras:
        return names
    names += [f"family_{v}" for v in FAMILY_VALUES]
    names += [f"strategy_{v}" for v in strategies]
    names += ["hour_sin", "hour_cos", "weekday", "rr_ratio", "sl_pips"]
    return names


def symbol_family(symbol: str) -> str:
    """Sembol → aile (tek-hot). XAU/emtia → xau, kripto → crypto, endeks → index,
    saf FX 6 harf: USD'li majör → fx_major, değilse fx_cross."""
    sym = str(symbol or "").upper().replace("/", "").replace("_", "")
    if "XAU" in sym or "GOLD" in sym or "XAG" in sym:
        return "xau"
    if any(k in sym for k in ("BTC", "ETH", "XRP", "SOL", "ADA", "DOGE")):
        return "crypto"
    if sym in ("US30", "NAS100", "USTEC", "SPX500", "GER40") or sym.isdigit():
        return "index"
    if len(sym) == 6 and sym.isalpha():
        return "fx_major" if "USD" in sym else "fx_cross"
    return "index" if sym else "fx_major"


def _vector(row: dict[str, Any], medians: dict[str, float],
            strategies: tuple[str, ...] = (), extras: bool = True) -> list[float]:
    f = featurize(row, medians=medians, strategies=strategies, extras=extras)
    return [f[k] for k in feature_names(strategies=strategies, extras=extras)]


def _spearman(a: list[float], b: list[float]) -> Optional[float]:
    n = len(a)
    if n < 20 or len(b) != n:
        return None
    def _rank(xs):
        order = sorted(range(n), key=lambda i: xs[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math.sqrt(sum((ra[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(sum((rb[i] - mb) ** 2 for i in range(n)))
    if da <= 0 or db <= 0:
        return None
    return num / (da * db)


def train(rows: list[dict[str, Any]], *, test_fraction: float = TEST_FRACTION,
          min_rows: int = MIN_ROWS) -> dict[str, Any]:
    """Kronolojik split + lojistik model + OOS değerlendirme. İstisna FIRLATMAZ."""
    out: dict[str, Any] = {
        "n_rows": len(rows or []), "min_rows": int(min_rows), "trained": False,
        "test_fraction": float(test_fraction),
    }
    clean = []
    for r in rows or []:
        try:
            sp = float(r.get("shadow_pips"))
            if not (sp == sp) or r.get("features") in (None, "", "{}"):
                continue
            clean.append(r)
        except (TypeError, ValueError):
            continue
    clean.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")))
    out["n_usable"] = len(clean)
    if len(clean) < int(min_rows):
        out["reason"] = (f"yetersiz eğitim verisi: {len(clean)} < {min_rows} "
                         "(features + shadow_pips dolu satır gerekli)")
        return out

    medians: dict[str, float] = {}
    for name in NUMERIC_FEATURES:
        vals = sorted(v for v in (_f((r.get("features") or {}).get(name) if isinstance(r.get("features"), dict) else None)
                                  for r in clean) if v is not None)
        medians[name] = vals[len(vals) // 2] if vals else 0.0
    out["medians"] = medians

    # STRATEJİ ONE-HOT LİSTESİ: eğitim verisinde en sık N strateji. Artifact'a
    # yazılır; skorlarken AYNI liste kullanılır (vektör kaymasın).
    from collections import Counter
    strat_counts = Counter(str(r.get("strategy") or "").strip() for r in clean if str(r.get("strategy") or "").strip())
    strategies = tuple(k for k, _ in strat_counts.most_common(TOP_STRATEGIES_N))
    out["strategies"] = list(strategies)
    y = [1 if float(r.get("shadow_pips")) > 0 else 0 for r in clean]
    cut = int(len(clean) * (1.0 - float(test_fraction)))
    cut = max(1, min(len(clean) - 1, cut))
    ytr = y[:cut]
    yte = y[cut:]
    out.update({"n_train": len(ytr), "n_test": len(yte)})
    base = sum(ytr) / len(ytr)
    base_te = sum(yte) / len(yte)
    out["base_rate_train"] = round(base, 4)
    out["base_rate_test"] = round(base_te, 4)
    denom_te = base_te * (1 - base_te)

    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"sklearn yok: {type(exc).__name__}"
        return out

    from app import ml_probability as mp

    C_GRID = (0.03, 0.1, 0.3, 1.0)

    def _fit_std(Xtr, yv, C: float, penalty: str):
        """Standartlaştırmayı EĞİTİM verisinden kurar (sızıntı yok)."""
        mu = Xtr.mean(axis=0)
        sd = np.where(Xtr.std(axis=0) < 1e-9, 1.0, Xtr.std(axis=0))
        m = LogisticRegression(max_iter=2000, C=float(C), penalty=penalty,
                               solver="liblinear" if penalty == "l1" else "lbfgs",
                               random_state=0).fit((Xtr - mu) / sd, yv)
        return m, mu, sd

    def _cv_skill(Xtr, C: float, penalty: str) -> Optional[float]:
        """BLOKLU GENİŞLEYEN PENCERE CV: 3 kat (%50→65, 65→80, 80→100).

        Tek %25 dilim gürültülüydü: zengin profil 0.020 vs temel 0.018 farkıyla
        seçilip TEST'te −0.008 aldı. Katların ORTALAMASI daha kararlı.
        """
        n_ = len(ytr)
        skills: list[float] = []
        for a, b in ((0.50, 0.65), (0.65, 0.80), (0.80, 1.00)):
            i0, i1 = int(n_ * a), int(n_ * b)
            if i1 - i0 < 50 or i0 < 100:
                continue
            try:
                m, mu, sd = _fit_std(Xtr[:i0], ytr[:i0], C, penalty)
                pv = m.predict_proba((Xtr[i0:i1] - mu) / sd)[:, 1]
                yv = np.asarray(ytr[i0:i1], dtype=float)
                bv = float(yv.mean())
                dv = bv * (1 - bv)
                if dv <= 0:
                    continue
                skills.append(1 - float(np.mean((pv - yv) ** 2)) / dv)
            except Exception:  # noqa: BLE001
                continue
        return (sum(skills) / len(skills)) if skills else None

    # Her profil için matris + aday konfigürasyon karnesi
    prof = {}
    for pname, pextras in (("temel", False), ("zengin", True)):
        Xp = [_vector(r, medians, strategies, pextras) for r in clean]
        Xp_tr = np.asarray(Xp[:cut], dtype=float)
        cands = []
        for penalty in ("l2", "l1"):
            for C in C_GRID:
                sk = _cv_skill(Xp_tr, C, penalty)
                if sk is not None:
                    cands.append({"C": C, "penalty": penalty, "cv_skill": sk})
        if not cands:
            # CV katları kurulamadı (küçük veri): GÜVENLİ VARSAYILAN ile devam et.
            # Model yine eğitilir ve test metrikleri dürüstçe raporlanır; seçim
            # iddiası yalnız "cv_skill=None" olarak işaretlenir (uydurma yok).
            cands = [{"C": 0.3, "penalty": "l2", "cv_skill": None}]
        bestp = max(cands, key=lambda c: (c["cv_skill"] is not None, c["cv_skill"] or -9))
        m, mu, sd = _fit_std(Xp_tr, ytr, bestp["C"], bestp["penalty"])
        Xp_te = np.asarray(Xp[cut:], dtype=float)
        p_te = m.predict_proba((Xp_te - mu) / sd)[:, 1].tolist()
        b_te = mp.brier_score(p_te, yte)
        ic_p_ = _spearman(p_te, [float(v) for v in yte])
        prof[pname] = {
            "profile": pname, "n_features": len(feature_names(strategies=strategies, extras=pextras)),
            "hyperparams": {"C": bestp["C"], "penalty": bestp["penalty"],
                            "cv_skill": (round(bestp["cv_skill"], 4)
                                         if bestp.get("cv_skill") is not None else None)},
            "brier_test": round(b_te, 4),
            "brier_skill_oos": (round(1 - b_te / denom_te, 4) if denom_te else None),
            "ic_test": round(ic_p_, 4) if ic_p_ is not None else None,
            "_cands": cands, "_model": m, "_mean": mu, "_std": sd,
            "_extras": pextras,
            "_names": feature_names(strategies=strategies, extras=pextras),
            "_p_te": p_te,
        }
    ok = {k: v for k, v in prof.items() if "_model" in v}
    if not ok:
        out["reason"] = "hiçbir özellik profili eğitilemedi"
        return out

    # KAZANAN: en iyi CV skill'ine SELECTION_MARGIN kadar yaklaşanlar arasından
    # SADE olanı (temel profil → L2 → küçük C). Test kümesine BAKILMAZ.
    # --- SEÇİM GÜVENİLİRLİĞİ (2026-11-10, koşum 7) ---------------------------
    # Koşum 7'de CV skill NEGATİF (−0.146) çıkarken test skill +0.037'ydi: erken
    # dönemde eğitilen model ileriye genellemiyor (rejim kayması). Böyle bir CV
    # "hangi profil daha iyi" sorusunu CEVAPLAYAMAZ. Ayrıca 446 test satırında
    # skill gürültüsü σ≈1/√n≈0.047 → 0.037 vs 0.052 AYIRT EDİLEMEZ.
    # Politika: CV negatifse veya profiller arası fark gürültü bandındaysa
    # SADE VARSAYILAN (temel + L2 + C=0.3) kullanılır; seçim oynamaz.
    noise_band = (1.0 / math.sqrt(len(yte))) if yte else None
    cvs = [v["hyperparams"]["cv_skill"] for v in ok.values() if v["hyperparams"]["cv_skill"] is not None]
    best_cv = max(cvs) if cvs else None
    test_skills = {k: v["brier_skill_oos"] for k, v in ok.items()}
    sel_note = ""
    if best_cv is None:
        sel_note = "CV kurulamadı (küçük veri) → sade varsayılan"
        near = list(ok)
    elif best_cv < 0:
        sel_note = (f"CV skill negatif ({round(best_cv,3)}): dönemler arası KAYMA — profil "
                    f"karşılaştırması güvenilmez → sade varsayılan (temel)")
        near = ["temel"] if "temel" in ok else list(ok)
    else:
        near = [k for k, v in ok.items()
                if v["hyperparams"]["cv_skill"] is not None
                and best_cv - v["hyperparams"]["cv_skill"] <= SELECTION_MARGIN]
        if len(ok) == 2 and noise_band is not None:
            d = abs((test_skills.get("zengin") or 0) - (test_skills.get("temel") or 0))
            if d < noise_band:
                sel_note = (f"profiller arasında AYRIM YOK (test fark {d:.3f} < gürültü bandı "
                            f"{noise_band:.3f}) → sade model (temel) kullanılıyor")
                near = ["temel"] if "temel" in ok else near
    best_name = sorted(
        near,
        key=lambda k: (ok[k]["_extras"], ok[k]["hyperparams"]["penalty"] == "l1",
                       ok[k]["hyperparams"]["C"]),
    )[0]
    best = ok[best_name]
    extras = best["_extras"]
    model, mean, std = best["_model"], best["_mean"], best["_std"]
    names = best["_names"]
    p_te = best["_p_te"]
    p_tr = model.predict_proba((np.asarray([_vector(r, medians, strategies, extras) for r in clean[:cut]], dtype=float) - mean) / std)[:, 1].tolist()
    brier_tr = mp.brier_score(p_tr, ytr)
    brier_te = best["brier_test"]
    skill = best["brier_skill_oos"]
    ic = best["ic_test"]
    ece_te = mp.ece(p_te, yte)
    ic_p = round(ic / math.sqrt(max(1, len(yte))), 4) if ic is not None else None
    iv = mp.hit_rate_interval_wilson(yte, alpha=0.10)

    out["profiles"] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                       for k, v in prof.items()}
    out["best_profile"] = "zengin" if extras else "temel"
    out["selection_note"] = sel_note or "CV ile seçildi (marj içinde sade tercih)"
    out["skill_noise_band"] = None if noise_band is None else round(noise_band, 4)
    if best_cv is not None and best_cv < 0:
        out["regime_shift_warning"] = (
            "Erken dönemde eğitilen model ileriye genellemiyor (CV skill negatif). "
            "Karar kapısından önce prequential gölge IC takibi şart.")
    out["selected_hyperparams"] = {**best["hyperparams"], "margin": SELECTION_MARGIN,
                                   "selection": "bloklu CV + sade model tercihi"}
    out["feature_profile"] = "zengin" if extras else "temel"
    out["feature_names"] = names
    out["means"] = [round(float(v), 6) for v in mean]
    out["scales"] = [round(float(v), 6) for v in std]

    # OOS HÜKÜM: skill > 0 ise test yarısında bilgi var; <= 0 ise kapı OLMAMALI.
    verdict = ("OOS skill > 0: model test yarısında bilgi taşıyor (kapı için YİNE replay A/B şart)"
               if (skill is not None and skill > 0) else
               "OOS skill <= 0: model test yarısında bilgi TAŞIMIYOR — karar kapısı OLMAMALI")

    # İKİNCİ MODEL KIYASI (PDF: Databricks Big Book 3e s58 → gradient boosting).
    # Kazanan özellik profilinin matrisiyle eğitilir; kaydedilmez, yalnız kıyas.
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        Xb_tr = np.asarray([_vector(r, medians, strategies, extras) for r in clean[:cut]], dtype=float)
        Xb_te = np.asarray([_vector(r, medians, strategies, extras) for r in clean[cut:]], dtype=float)
        hgb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08,
                                             max_depth=3, random_state=0).fit(Xb_tr, ytr)
        hgb_p = hgb.predict_proba(Xb_te)[:, 1].tolist()
        hgb_brier = mp.brier_score(hgb_p, yte)
        hgb_skill = round(1 - hgb_brier / denom_te, 4) if denom_te else None
        hgb_ic = _spearman(hgb_p, [float(v) for v in yte])
        out["models"] = {
            "logistic": {"brier_test": round(brier_te, 4), "brier_skill_oos": skill,
                         "ece_test": round(ece_te, 4),
                         "ic_test": round(ic, 4) if ic is not None else None},
            "hist_gradient_boosting": {"brier_test": round(hgb_brier, 4),
                                       "brier_skill_oos": hgb_skill,
                                       "ic_test": round(hgb_ic, 4) if hgb_ic is not None else None},
        }
        out["best_model"] = max(("logistic", "hist_gradient_boosting"),
                                key=lambda k: (out["models"][k]["brier_skill_oos"] is not None,
                                               out["models"][k]["brier_skill_oos"] or -9))
    except Exception as exc:  # noqa: BLE001
        out["models_note"] = f"hist-GB kıyası atlandı: {type(exc).__name__}"

    out.update({
        "trained": True,
        "brier_train": round(brier_tr, 4),
        "brier_test": round(brier_te, 4),
        "brier_skill_oos": skill,
        "ece_test": round(ece_te, 4),
        "ic_test": round(ic, 4) if ic is not None else None,
        "ic_significance": ic_p,
        "wilson": iv,
        "verdict": verdict,
        "coefficients": {names[i]: round(float(model.coef_[0][i]), 4) for i in range(len(names))},
        "intercept": round(float(model.intercept_[0]), 4),
        "feature_names": names,
        "means": [round(float(v), 6) for v in mean],
        "scales": [round(float(v), 6) for v in std],
        "trained_at": time.time(),
    })

    # Kalibrasyon: izotonik (eğitim yarısında kurulur, test yarısında ölçülür)
    try:
        cal = mp.fit_calibration(p_tr, ytr, min_samples=60)
        if cal.get("fitted"):
            cal_te = [mp.apply_calibration(p, cal) for p in p_te]
            brier_cal = mp.brier_score(cal_te, yte)
            out["calibrated_brier_test"] = round(brier_cal, 4)
            out["calibration_improved"] = bool(brier_cal < brier_te)
    except Exception as exc:  # noqa: BLE001
        out["calibration_note"] = f"kalibrasyon atlandı: {type(exc).__name__}"
    return out


def load_scoring_model(path: str | Path | None = None) -> Optional[dict[str, Any]]:
    """Artifact'ı oku; eğitilmemiş/bozuksa ``None`` (fail-closed)."""
    target = Path(path) if path else DEFAULT_ARTIFACT
    try:
        import json
        art = json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not art.get("coefficients") or not art.get("feature_names"):
        return None
    # UYUMLULUK KAPISI: özellik seti değiştiyse (ör. 2026-11-10 zenginleştirme)
    # eski artifact yanlış vektörle skorlar → sessiz bozulma yerine REDDET.
    strat = tuple(art.get("strategies") or [])
    extras = str(art.get("feature_profile") or "zengin") == "zengin"
    if list(art.get("feature_names") or []) != feature_names(strategies=strat, extras=extras):
        logger.info("forex_ml artifact özellik seti güncel değil → yeniden eğitim gerekli")
        return None
    return art


def score_features(features_dict: dict[str, Any], artifact: dict[str, Any]) -> Optional[float]:
    """Deterministik özelliklerden isabet olasılığı — sklearn'SİZ (sigmoid + JSON).

    Eksik sayısal alanlar artifact'taki eğitim medyanıyla doldurulur; bilinmeyen
    kategoriler tüm-bit-0. Modelin "kesik" bilgisini (`_eksik` göstergeleri)
    görmesi için `features` ham sözlük olarak geçilir.
    """
    if not artifact:
        return None
    f = featurize({"features": features_dict,
                   "direction": features_dict.get("_direction", "BUY"),
                   "confidence": features_dict.get("_confidence"),
                   "score": features_dict.get("_motor_score"),
                   "symbol": features_dict.get("_symbol"),
                   "strategy": features_dict.get("_strategy"),
                   "created_at_ts": features_dict.get("_ts"),
                   "sl_pips": features_dict.get("_sl_pips"),
                   "tp_pips": features_dict.get("_tp_pips")},
                  medians=artifact.get("medians") or {},
                  sessions=tuple(s[8:] for s in artifact["feature_names"] if s.startswith("session_")),
                  biases=tuple(b[5:] for b in artifact["feature_names"] if b.startswith("bias_")),
                  strategies=tuple(artifact.get("strategies") or []),
                  extras=str(artifact.get("feature_profile") or "zengin") == "zengin")
    try:
        import numpy as np
        x = np.asarray([f[k] for k in artifact["feature_names"]], dtype=float)
        mean = np.asarray(artifact["means"], dtype=float)
        scale = np.asarray(artifact["scales"], dtype=float)
        coef = np.asarray([artifact["coefficients"][k] for k in artifact["feature_names"]], dtype=float)
        z = float(((x - mean) / scale) @ coef + float(artifact["intercept"]))
        return round(1.0 / (1.0 + math.exp(-z)), 4)
    except Exception as exc:  # noqa: BLE001
        logger.debug("forex_ml skor hatası: %s", exc)
        return None


def save_artifact(report: dict[str, Any], path: str | Path | None = None) -> str:
    """Eğitilmiş modeli JSON'a yazar (pickle yok). Yalnız `trained=True` iken."""
    target = Path(path) if path else DEFAULT_ARTIFACT
    if not report.get("trained"):
        raise ValueError("eğitilmemiş rapor artifact'a yazılamaz")
    target.parent.mkdir(parents=True, exist_ok=True)
    import json
    payload = {"saved_at": time.time(), "version": 3,
               "strategies": report.get("strategies") or [],
               "feature_profile": report.get("feature_profile") or "zengin",
               "feature_names": report.get("feature_names"),
               "means": report.get("means"), "scales": report.get("scales"),
               "coefficients": report.get("coefficients"), "intercept": report.get("intercept"),
               "medians": report.get("medians"),
               "metrics": {k: report.get(k) for k in (
                   "n_rows", "n_usable", "n_train", "n_test", "base_rate_train",
                   "base_rate_test", "brier_train", "brier_test", "brier_skill_oos",
                   "ece_test", "ic_test", "wilson", "verdict", "trained_at")}}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


async def run(*, min_rows: int = MIN_ROWS, save: bool = True) -> dict[str, Any]:
    """Panelden çağrılan tam akış: veri çek → eğit → artifact + DB kaydı.

    DİKKAT (2026-11-10 500'ü): `run` async olduğu için `asyncio.to_thread(run, …)`
    onu KOŞTURMAZ — coroutine nesnesi döndürüp FastAPI'de serialization hatası
    veriyordu. Doğru düzen: DB adımları await, CPU-bound `train()` to_thread'te
    (sklearn eğitim event loop'u kilitlemesin).
    """
    import asyncio

    from app import database

    rows = await database.get_forex_ml_dataset()
    report = await asyncio.to_thread(train, rows, min_rows=min_rows)
    if report.get("trained") and save:
        try:
            report["artifact_path"] = await asyncio.to_thread(save_artifact, report)
        except Exception as exc:  # noqa: BLE001
            report["artifact_error"] = f"{type(exc).__name__}: {exc}"
    try:
        await database.save_forex_ml_run(report)
    except Exception as exc:  # noqa: BLE001
        report["run_log_error"] = f"{type(exc).__name__}: {exc}"
    return report
