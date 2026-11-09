# GitHub Derin Araştırması — LLM Modeli & Forex Radar Geliştirmeleri

**Tarih:** 2026-11-09 · **Kapsam:** LLM analiz/gate katmanı + Forex Radar/sinyal üretimi + ML ölçüm katmanı
**Yöntem:** Üç paralel araştırma hattı (LLM ajanları, FX radar/strateji, ML ölçüm) + **kararları belirleyen iddiaların elle doğrulanması** (`gh api` kimlik doğrulamalı, `pypi.org` JSON, repo kaynak dosya içerikleri).
**Önceki rapor:** `docs/GITHUB_OZELLIK_ARASTIRMASI_2026-11-04.md` (spot push, OI/funding, Dukascopy, COT). Bu rapor onu **tekrarlamaz**; LLM + radar derinleşmesine odaklanır.

---

## 0. Yönetici özeti

Sistemin en büyük açığı **"daha iyi model"** değil, **"modelin ve sinyalin haklı olup olmadığını kanıtlayan ölçüm katmanı"**. Ölçüm olmadan yapılan her iyileştirme, aşırı uyumu daha ikna edici biçimde paketlemekten ibaret kalır.

**En net 3 hamle:**

| # | Hamle | Neden | Kanıt |
|---|---|---|---|
| **1** | `arch` ile **SPA + RealityCheck + StepM + MCS** testlerini ölçüm katmanına al | "Yüzlerce parametre taradım, en iyisi +X çıktı" iddiasını istatistiksel olarak doğrular/çürütür. Repoda zaten onlarca `sweep/matrix` denemesi var → çoklu-test problemi somut | `arch/bootstrap/multiple_comparison.py` içeriği okundu: `__all__ = ["MCS","SPA","RealityCheck","StepM"]` ✓ |
| **2** | `purgedcv` (MIT) ile **CPCV + purged/embargo CV + PSR/DSR** | Tek backtest yolunun yanılsamasını kırar; PF<1.0 kill kriterinin istatistiksel kardeşi | `nr` sayfası doğrulandı: `eslazarev/purged-cross-validation`, 63★, **MIT**, push 2026-11-08, PyPI `purgedcv 0.1.12` ✓ |
| **3** | `calibration.py`'ye **olasılık kalibrasyonu + Brier/ECE + çekimserlik (abstention)** | Modülün kendi docstring'i "No machine learning, no parameter fitting" diyor; ML hit olasılığı kalibre değilse filtre yanıltıcıdır | `calibration.py` başlığı okundu ✓ |

**İkinci düzlem (radar tarafı):** `cot_reports` (MIT) ile **COT kurumsal pozisyonlanma** — FX'te fiyat-dışı, gerçek kenara en yakın veri; `talipp` (MIT) ile **artımlı indikatör** → canlı taramada CPU/gecikme düşüşü; `smart-money-concepts` (MIT) ile **order block / FVG / likidite süpürme** → `forex_patterns.py` + `snapback_service.py` güçlenir.

**En kritik mimari kısıt (raporun en önemli bulgusu):** Üretim imajı **bilinçli olarak yalın** — `backend/requirements.txt` içinde quant yığınından yalnız `numpy==2.4.6` + `scikit-learn==1.6.1` var. **`app/` içinde tek bir `import pandas` bile yok.** Bu yüzden pandas/scipy/statsmodels gerektiren her öneri **araştırma katmanına** (`requirements-research.txt` + `backend/scripts/`) gitmeli, üretime yalnız **üretilmiş artefakt (JSON/parquet)** olarak girmelidir. Aksi halde Docker imajı ve soğuk başlangıç şişer.

---

## 1. Doğrulama ve düzeltmeler (şeffaflık)

Bu raporu yazmadan önce karar verici iddiaları **kendim** doğruladım. Üç düzeltme çıktı:

| İddia | Durum | Gerçek |
|---|---|---|
| `llm_second_eye.py` çıktısı `ONAY/TEMKİN/KARŞI` | ❌ **YANLIŞ** (araştırma girdisinde benim hatam) | Şema: `{"verdict":"DEVAM\|FAKE\|BELIRSIZ","confidence":0-100,...}` — `llm_second_eye.py:48,72` ✓ Yani gate "bu sinyal gerçek mi, sahte mi?" sorusunu cevaplıyor → **tam olarak meta-labeling** |
| `requirements-research.txt`'teki `vectorbt==1.1.0` sürüm uyuşmazlığı riski | ❌ **YANLIŞ** | PyPI'de **1.1.0 mevcut**, en yeni 1.2.0 ✓ (`pypi.org/pypi/vectorbt/json`) |
| `vectorbt` lisansı (Commons Clause) **"hemen aksiyon gerektiriyor"** | ⚠️ **ABARTILI** | `vectorbt` repo genelinde **tek bir yerde** import ediliyor: `backend/scripts/vectorbt_research.py:21`. Üretim `app/` kodunda **hiç** import yok (yalnız yorum/fonksiyon adı benzerliği) → lisans riski **iç araştırma araçlarıyla sınırlı**, düşük |
| `mlfinlab` / `pandas-ta` riski | ⚠️ **İLGİSİZ** | İkisi de bu repoda **hiç kullanılmıyor** (`grep` → 0) |
| `pandas-ta` ana reposu 404 | ✅ **DOĞRU** | `gh api repos/twopirllc/pandas-ta` → **404 Not Found** ✓ (kullanmadığımız için bize etkisi yok) |
| `backtesting.py` AGPL-3.0 | ✅ **DOĞRU** | `gh api` → `AGPL-3.0` ✓ (kullanmıyoruz; **kullanmayın**) |
| `TradingAgents` 121.4k ★ | ✅ **DOĞRU** | `gh api` → `stargazers_count: 121414` ✓ |
| `mlfinlab` açık kaynak değil | ✅ **DOĞRU (temkinli ifade)** | `spdx_id: NOASSERTION`, son push **2023-10-02** (donmuş). Lisans metni SPDX tanınmıyor → kullanmadan önce elle okunmalı. **Kullanmıyoruz, önermiyoruz.** |
| `arch` içinde SPA/RealityCheck/StepM/MCS var | ✅ **DOĞRU** | Kaynak dosya okundu: `__all__ = ["MCS","SPA","RealityCheck","StepM"]` ✓ Lisans: permissive (Kevin Sheppard, NCSA tipi) ✓ |
| `portfolio_risk.py` ATR(14)/ATR(100) vol çarpanı | ✅ **DOĞRU** | `portfolio_risk.py:238` — `ATR(14)/ATR(100) > 2 ya da yüzdelik > 95 → ×0.4` ✓ |
| `calibration.py`'de ML yok | ✅ **DOĞRU** | Docstring: *"No machine learning, no parameter fitting — plain counting"* ✓ |

**Yıldız/lisans sayıları** `gh api` ile **2026-11-09** anlık görüntüsüdür; hızla değişirler.

---

## 2. BÖLÜM A — LLM modeli ve LLM katmanı

### 2.1 Mevcut durum (kod kanıtlı)

| Bileşen | Dosya | Görülen işlev |
|---|---|---|
| Teknik yorum | `app/llm_analysis.py` | Yorum metni üretimi |
| **AI gate / ikinci göz** | `app/llm_second_eye.py` | `DEVAM\|FAKE\|BELIRSIZ` + `confidence` + `bull_thesis`, `parse_verdict()` ile eşanlamlı/kurtarma ayrıştırması (273-301) |
| İşlem incelemesi | `app/llm_trade_review.py`, `app/spot_llm_review.py` | Kapanan işlem sonrası analiz |
| Bellek / embedding | `app/memory_service.py`, `app/embedding_worker.py` | Vektör bellek |
| Sohbet + araç çağırma | `app/routers/llm_chat.py`, `forex_chat.py` | SSE akış, araç çağrıları (`execute_vectorbt_optimal_params` vb.) |
| Öğrenme | `app/chat_prediction_learning.py`, `agent_learning.py`, `self_learning.py` | Geri besleme döngüleri |

**Gözlem:** Çıktı zaten yapılandırılmış (`verdict` + `confidence`), ama **iki şey eksik**: (a) **şema garantisi** (şu an regex/serbest metin kurtarma var — `parse_verdict` bunun kanıtı), (b) **güven kalibrasyonu ve çekimserlik**.

### 2.2 Öneriler

#### A1 — Yapılandırılmış çıktı garantisi: `instructor` + Pydantic  · **P1 · S maliyet**

| | |
|---|---|
| Repo | `567-labs/instructor` — 14.1k★, MIT, aktif |
| Alternatif | `dottxt-ai/outlines` 16k★ Apache-2.0 (şema-garantili üretim), `BoundaryML/baml` 9.5k★ Apache-2.0 |
| Ne kazandırır | `parse_verdict()`'teki regex/eşanlamlı kurtarma katmanına olan ihtiyacı ortadan kaldırır; `verdict`/`confidence` alanları **tip düzeyinde** garanti olur |
| Eşleme | `llm_second_eye.py` (asıl kazanç), `llm_analysis.py`, `llm_trade_review.py` |
| Risk | Düşük. Sağlayıcı-agnostik yapıyı bozmaz (OpenAI-uyumlu base_url desteklenir) |

**Ek kural (halüsinasyon savunması):** Fiyat/RSI/ATR gibi sayıları **LLM'e hesaplatmayın**; araç çıktısından verin ve dönen JSON'daki sayısal alanları **deterministik olarak araç çıktısıyla karşılaştırın**. Şema garantisi "tip doğru" der, "sayı doğru" demez.

#### A2 — Bellek güçlendirme: `pgvector` + BGE-M3 + reranker · **P1 · S/M maliyet**

| | |
|---|---|
| Repo | `pgvector/pgvector` — 23.6k★, PostgreSQL Lisansı, push 2026-11-09 |
| Embedding/rerank | `FlagOpen/FlagEmbedding` — 12.3k★, MIT (BGE-M3 + `bge-reranker`) |
| Neden | **Postgres zaten var** → yeni altyapı gerekmez. **DÜZELTME (uygulama sırasında ölçüldü): pgvector ZATEN KURULU** — `migrations/001_pgvector_schema.sql:1 CREATE EXTENSION vector`, `memory_documents` + `embedding_jobs` + `memory_service` çalışıyor. **Kalan gerçek boşluk: (a) HNSW index'i yorum satırı** (`001_pgvector_schema.sql:202` — "controlled maintenance job" notuyla kapatılmış), (b) **reranker yok** (arama `1-(embedding <=> $1::halfvec)` + ağırlıklı skorla yapılıyor) |
| ALMA | `tensorchord/pgvecto.rs` (halefi VectorChord oldu, 2025-02'de durdu) |
| Risk | Düşük |

#### A3 — Maliyet: router + semantik önbellek · **P2 · S maliyet**

`BerriAI/litellm` (62.9k★, çekirdeği MIT ama NOASSERTION/EE katmanı var) ile **küçük yerel model → analiz/özet**, **büyük model → kritik karar** yönlendirmesi. `zilliztech/GPTCache` (8.2k★, MIT) ile tekrar eden sinyal yorumlarını önbellekle.
**Uyarı:** semantik cache'te yanlış eşleşme riski → benzerlik eşiği + TTL zorunlu.
**ALMA:** `lm-sys/RouteLLM` (2024-08'den beri sessiz).

#### A4 — Yerel model · **P3 · M/L maliyet**

Fine-tune (`hiyouga/LlamaFactory` 76k★ Apache-2.0) + serving (`ollama` 186.4k★ MIT / `vllm-project/vllm` 96.6k★ Apache-2.0).
**Kritik uyarı:** finansa uyarlanmış açık ağırlıkların çoğu **2025 başında dondu ve lisansları belirsiz**. `SUFE-AIFLM-Lab/Fin-R1` (822★) → **lisans dosyası YOK** → hukuki risk, **ALMA**. Sağlıklı yol: genel amaçlı güçlü küçük model + kendi verinizle LoRA.

#### A5 — LLM ajan orkestrasyonu · **P2 · M maliyet**

`TauricResearch/TradingAgents` (121.4k★, Apache-2.0) ve `virattt/ai-hedge-fund` (64.6k★, MIT) → **referans mimari olarak değerli** (analist→araştırmacı→trader→risk tartışması deseni `agent_learning.py`'ye ilham verir), ama **üretimde kopyalanmamalı**: token maliyeti yüksek, deterministik değil, canlı para kararı için uygun değil.
`microsoft/qlib` (50.1k★, **MIT**) → LLM değil, nicel altyapı; triple-barrier + rolling etiketlemenin MIT'li referansı.

---

## 3. BÖLÜM B — Forex Radar / sinyal üretimi

### 3.1 Mevcut durum

`combined_radar.py`, `unified_signals.py`, `rising_signals.py`, `early_discovery.py`, `microflow.py`, `master_surge.py`, `snapback_service.py`, `forex_indicators.py`, `forex_patterns.py`, `macd_mtf.py`, `macro_sentiment_service.py`, `derivatives_service.py`, `correlation.py`, `forex_correlation.py`, `market_intelligence.py`, `tsmom.py`, `portfolio_risk.py`.

**Gözlem:** Radar tarafı **zengin**; eksik olan (a) test edilebilir **rejim istatistiği**, (b) **fiyat-dışı yön sinyali (COT)**, (c) canlı taramada **artımlı hesap** (CPU/gecikme).

### 3.2 Öneriler

| # | Repo | ★ / Lisans | Eşleme | Karar | Maliyet |
|---|---|---|---|---|---|
| B1 | `statsmodels/statsmodels` — `tsa/regime_switching` (MarkovRegression, MarkovAutoregression) | 11.7k / BSD-3 | `market_intelligence.py` rejim kapısı: "chop'ta sus" | **AL** | M (pandas/scipy → araştırma katmanı) |
| B2 | `deepcharles/ruptures` | 2.1k / BSD-2 | `master_surge.py`, `early_discovery.py` — sıçrama/çöküş **başlangıcı** | **AL** | S |
| B3 | `NDelventhal/cot_reports` | **202 / MIT** | `macro_sentiment_service.py` — kurumsal net pozisyon + haftalık değişim | **AL** | S |
| B4 | `nardew/talipp` | **545 / MIT** | `combined_radar.py`, `macd_mtf.py` — **O(1) artımlı** indikatör → CPU/gecikme düşer | **AL** | S |
| B5 | `rsheftel/pandas_market_calendars` | **1006 / MIT** | Seans pencereleri: London/NY geçişi, seans açılış/kapanış filtreleri | **AL** | S |
| B6 | `joshyattridge/smart-money-concepts` | **2149 / MIT** (pypi `smartmoneyconcepts`) | `forex_patterns.py`, `snapback_service.py` — order block, FVG, likidite süpürme, BOS/CHoCH | **AL** | M |
| B7 | `TA-Lib/ta-lib-python` | 12.4k / BSD-2 | `forex_indicators.py` — kanonik RSI/ATR doğrulaması (Wilder uyumu) | **DENE** | M (C kütüphanesi derleme yükü) |
| B8 | `bashtage/arch` (GARCH/EGARCH + HAR-RV) | 1672 / permissive | `portfolio_risk.py` — ATR oranı yerine **model tabanlı** vol | **AL** | M |
| B9 | `PyPortfolio/PyPortfolioOpt` (Kelly / risk-parity / HRP) | 6157 / MIT | `portfolio_risk.py` — sabit lot yerine **kısmi Kelly** | **AL** | M |
| B10 | `mortada/fredapi` | 1666 / Apache-2.0 | `tsmom.py` — carry / faiz farkı | **AL** | S |
| B11 | `microsoft/qlib` | 50.1k / MIT | Triple-barrier + rolling etiketleme deseni | **DENE** | M |
| B12 | `stefan-jansen/arbitragelab` | 706 / BSD-3 | `forex_correlation.py` — koentegrasyon / pair taraması | **DENE** | M |
| B13 | `nautechsystems/nautilus_trader` | 31.4k / LGPL-3.0 | Tick-seviyesi event-driven paper doğrulama | **DENE** (LGPL uyarısı) | L |
| B14 | `jesse-ai/jesse` | 8.8k / MIT | Canlı tarayıcı + routing mimarisi deseni | **DENE** | M |
| B15 | `freqtrade/freqtrade` (+ `freqtrade-strategies`) | 56.7k / GPL-3.0 | FreqAI **walk-forward retrain** deseni → `self_learning.py`; hazır strateji fikirleri | **DENE** (GPL: kod kopyalamayın, **fikir alın**) | M |

**Somut alınacak fikirler:** freqtrade-strategies'den *opening-range / seans kırılımı* şablonları; `hummingbot`'tan (21.1k★ Apache-2.0) yalnız **laddered exit** fikri; jesse'den **strateji kilitleme + canlı/paper ayrımı** desenini sertleştirme.

**ALMA:** `mementum/backtrader` (2024-08'den beri atıl), `peerchemist/finta` (arşivli), `TulipCharts/tulipy` (2021, yerine `tulipindicators`), `QuantConnect/Lean` (Python ekosistemi yeterli, L maliyet), `StockSharp` (tescilli EULA), `twopirllc/pandas-ta` (**404**).

---

## 4. BÖLÜM C — ML ölçüm katmanı (en yüksek ROI)

### 4.1 Mevcut durum

- `app/ml_forecast.py` — `HistGradientBoosting`, **`FEATURE_VERSION = "v3"`**, kendi Wilder RSI/ATR/BB genişliği yardımcıları, `freeze_current_model()` deseni var
- `app/ml_forward_test.py` — kendi walk-forward'ı
- `app/calibration.py` — **ML yok**, kova sayımı + `confidence_multiplier` (walk-forward-safe)
- `app/forecast_learning.py`, `self_learning.py`, `promotion.py`, `latency_stats.py`
- Log dosyalarında **onlarca** `sweep / matrix / regime-refinement` varyantı → **çoklu-test problemi somut ve gerçek**

### 4.2 Öneriler

| # | Repo | ★ / Lisans | Ne verir | Eşleme | Karar |
|---|---|---|---|---|---|
| C1 | `bashtage/arch` → `bootstrap/multiple_comparison.py` | 1672 / permissive | **White's Reality Check, Hansen SPA, Romano-Wolf StepM, Model Confidence Set** — doğrulandı | Yeni `edge_significance.py` → `ml_forward_test.py`, `promotion.py` | **AL · P1** |
| C2 | `eslazarev/purged-cross-validation` (PyPI `purgedcv 0.1.12`) | 63 / **MIT** | Purged k-fold + embargo + **CPCV** + PSR/**DSR** (deflated Sharpe) | `ml_forward_test.py`'deki el yapımı CV'nin yerine | **AL · P1** |
| C3 | `esvhd/pypbo` | 145 / **AGPL-3.0** | Probability of Backtest Overfitting (CSCV) | `promotion.py` | **ALGORİTMAYI TAŞI**, import etme (AGPL §13) |
| C4 | `stefan-jansen/machine-learning-for-trading` | 21.8k / **MIT** | DSR/Sharpe çıkarımı, purged CV, sinyal değerlendirme **referans kodu** | `forecast_learning.py` | **AL · P1** (kod uyarla) |
| C5 | `Nixtla/statsforecast` | 4969 / Apache-2.0 | **Dürüst baseline**: AutoARIMA/ETS/Theta | `ml_forward_test.py`: "ML baseline'ı yeniyor mu?" | **AL · P1** |
| C6 | `EFS-OpenSource/calibration-framework` (netcal) | 382 / Apache-2.0 | ECE, reliability diagram, temperature scaling | `calibration.py` | **AL · P1** |
| C7 | `scikit-learn` (**zaten kurulu**) | 68.1k / BSD-3 | `CalibratedClassifierCV` (izotonik/Platt) + `brier_score_loss` | `calibration.py`, `ml_forecast.py` | **AL · P1** |
| C8 | `scikit-learn-contrib/MAPIE` | 1673 / BSD-3 | Konformal tahmin aralıkları | `ml_forecast.py` çıktısına belirsizlik | **DENE · P2** |
| C9 | `stefan-jansen/alphalens-reloaded` | 685 / Apache-2.0 | **IC / kuantil getiri / turnover** | `pattern_research.py`, `chat_pattern_replay.py` | **AL · P2** |
| C10 | `online-ml/river` | 6142 / BSD-3 | **ADWIN drift tespiti** | `self_learning.py` izleme | **DENE · P2** |
| C11 | `mlflow/mlflow` | 28.7k / Apache-2.0 | Deney izi, model kaydı (lokal SQLite yeterli) | `self_learning.py`, `promotion.py` | **AL · P2** |
| C12 | `ranaroussi/quantstats` | 7836 / Apache-2.0 | Dürüst performans raporu | `portfolio_analytics.py` | **AL · P2** |
| C13 | `Nixtla/mlforecast` | 1304 / Apache-2.0 | Global model + lag/date özellik + gap'li CV | `freqai_features.py`, `ml_forecast.py` | **DENE · P2** |
| C14 | `treeverse/dvc` | 16k / Apache-2.0 | Veri+model hash'i; "hangi veriyle eğitildi" | `ml_forecast.py` `FEATURE_VERSION` deseni | **AL · P2** |
| C15 | `PyPortfolio/PyPortfolioOpt`, `Riskfolio-Lib` | 6157 MIT / 4597 BSD-3 | Kelly, tail-risk (CVaR/EVaR) | `portfolio_risk.py` | **DENE · P2** |
| C16 | `lightgbm-org/LightGBM` | 19k / MIT | HistGB'ye alternatif | `ml_forecast.py` | **DENE · P3** |

**Kritik kavramsal eşleşme:** `llm_second_eye`'nin `DEVAM|FAKE|BELIRSIZ` çıktısı **zaten bir meta-label**tir (birincil sinyal gerçek mi?). López de Prado meta-labeling'i burada doğal oturuyor: **birincil sinyal** = radar; **ikincil model** = LLM gate. Yapılması gereken: LLM güvenini **ham sayı olarak kullanmayı bırakıp kalibre etmek** (C6/C7) ve **çekimserlik eşiği** koymak — güven < eşik ise `BELIRSIZ` değil, **işlem yok**.

**ALMA (net):** `hudson-and-thames/mlfinlab` (SPDX tanınmıyor, 2023-10-02'den beri donmuş → meta-labeling'i C2 + C4 ile yazın), `donlnz/nonconformist` (2021-03, bayat), `time-series-foundation-models/lag-llama` (2025-06, bayat), `yli188/WorldQuant_alpha101_code` (**lisans yok**, 2019'da donmuş — üstelik cross-sectional hisse mantığı FX'e doğrudan taşınamaz).

---

## 5. Lisans riski tablosu (ticari ürün açısından)

| Kütüphane | Lisans | Bu repoda kullanım | Aksiyon |
|---|---|---|---|
| `vectorbt` | **Apache-2.0 + Commons Clause** (metin okundu: *"does not grant the right to Sell the Software"*) | **Yalnız** `scripts/vectorbt_research.py:21` | İç araştırmada OK. Ticari satışa konu bir özelliğin **çekirdeği** yapılmayın |
| `backtesting.py` | **AGPL-3.0** | Kullanılmıyor | **Almayın** (ağ üzerinden hizmette kaynak açıklama yükü) |
| `mlfinlab` | **SPDX tanınmıyor**, 2023'te donmuş | Kullanılmıyor | **Almayın**; C2+C4 ile ikame |
| `deepchecks` | AGPL-3.0 | Kullanılmıyor | Import etme; fikri taşı |
| `nautilus_trader` | LGPL-3.0 | Kullanılmıyor | Bağlama şekline dikkat |
| `edtechre/pybroker` | Commons Clause | Kullanılmıyor | Ticari satışta dikkat |
| `arch`, `purgedcv`, `cot_reports`, `talipp`, `smart-money-concepts`, `pandas_market_calendars`, `quantstats`, `mlflow`, `dvc`, `alphalens-reloaded`, `PyPortfolioOpt`, `fredapi`, `MAPIE`, `river`, `ruptures`, `statsforecast`, `mlforecast`, `netcal`, `qlib`, `ml4t` | MIT / Apache-2.0 / BSD / permissive (hepsi `gh api` ile doğrulandı) | — | **Temiz** |

---

## 6. Mimari karar: yalın üretim + zengin araştırma katmanı

```
backend/requirements.txt          → numpy, scikit-learn  (ÜRETİM, yalın kalır)
backend/requirements-research.txt → pandas, statsmodels, arch, vectorbt, puis...
backend/scripts/*.py              → ağır hesaplar, offline
        │
        └── artefakt (JSON/parquet) ──► app/ katmanı okur (pandas gerekmez)
```

**Neden:** `app/` içinde **tek bir `import pandas` yok** (doğrulandı). Yeni kütüphaneleri doğrudan üretime sokmak Docker imajını ve soğuk başlangıcı şişirir; ayrıca `curl_cffi` dersinde (dosya yorumunda yazılı) görüldüğü üzere **requirements'ta olmayan paket sessizce devre dışı kalıyor**. Bu yüzden:
- **Ölçüm** (C1-C5) → araştırma katmanı, çıktısı bir **rapor/JSON** olarak `promotion.py` kapısına girer
- **Kalibrasyon** (C6-C7) → `scikit-learn` **zaten kurulu** → doğrudan üretime girebilir (S maliyet)
- **COT / seans / talipp** → S maliyet, bağımlılık-hafif; üretime girebilir (`talipp` saf Python)

---

## 7. Yol Haritası

### P1 — hemen (yüksek ROI, düşük risk)
1. **`arch` → yeni `edge_significance.py`**: SPA + RealityCheck + StepM + MCS. `ml_forward_test.py` ve `promotion.py`'ye bağla. *(araştırma katmanı)*
2. **`purgedcv` → `ml_forward_test.py`**: el yapımı CV yerine CPCV + PSR/DSR. *(araştırma katmanı)*
3. **`calibration.py` genişlet**: sklearn `CalibratedClassifierCV` + `brier_score_loss` **+ ECE/reliability (netcal)** + **çekimserlik eşiği**. *(üretime girebilir — sklearn zaten kurulu)*
4. **`statsforecast` baseline**: AutoARIMA/ETS/Theta → "ML baseline'ı yeniyor mu?" alarmı.
5. **`statsmodels` `multipletests`**: BH/Holm/FDR düzeltmesi (sweep'leriniz için).
6. **`instructor` + Pydantic**: `llm_second_eye.py` çıktı şemasını garantile; `parse_verdict` kurtarma katmanını sadeleştir.
7. **`pgvector` + BGE-M3 + reranker**: `embedding_worker.py` + `memory_service.py`.

### P2 — doğrulama sonrası
8. `cot_reports` → `macro_sentiment_service.py` (fiyat-dışı yön sinyali)
9. `talipp` → `combined_radar.py` artımlı indikatör
10. `pandas_market_calendars` → seans filtreleri
11. `smart-money-concepts` → `forex_patterns.py` + `snapback_service.py`
12. `ruptures` + `statsmodels` MarkovRegression → `market_intelligence.py` rejim kapısı
13. `arch` GARCH + `PyPortfolioOpt` kısmi Kelly → `portfolio_risk.py`
14. `alphalens-reloaded` → sinyal IC/kuantil ölçümü
15. `mlflow` + `dvc` → deney izi ve tekrar üretilebilirlik
16. `river` ADWIN → `self_learning.py` drift alarmı
17. `litellm` router + `GPTCache` → LLM maliyet

### P3 — deneysel
18. `nautilus_trader` tick doğrulaması · `jesse` routing deseni · `qlib` triple-barrier · `MAPIE` konformal aralık · `mlforecast` global model · LightGBM · yerel LLM (LoRA + Ollama)

---

## 8. Kaynaklar

**Doğrulanan repolar (gh api, 2026-11-09):** `bashtage/arch` · `eslazarev/purged-cross-validation` · `esvhd/pypbo` · `stefan-jansen/machine-learning-for-trading` · `Nixtla/statsforecast` · `Nixtla/mlforecast` · `EFS-OpenSource/calibration-framework` · `scikit-learn-contrib/MAPIE` · `stefan-jansen/alphalens-reloaded` · `online-ml/river` · `deepcharles/ruptures` · `mlflow/mlflow` · `treeverse/dvc` · `ranaroussi/quantstats` · `PyPortfolio/PyPortfolioOpt` · `mortada/fredapi` · `microsoft/qlib` · `statsmodels/statsmodels` · `nardew/talipp` · `NDelventhal/cot_reports` · `rsheftel/pandas_market_calendars` · `joshyattridge/smart-money-concepts` · `567-labs/instructor` · `pgvector/pgvector` · `FlagOpen/FlagEmbedding` · `BerriAI/litellm` · `TauricResearch/TradingAgents` · `kernc/backtesting.py` · `polakowo/vectorbt` · `hudson-and-thames/mlfinlab` · `twopirllc/pandas-ta` (404)

**Yerel kanıt dosyaları:** `backend/app/llm_second_eye.py:48,72` · `backend/app/calibration.py` (docstring) · `backend/app/portfolio_risk.py:238` · `backend/app/ml_forecast.py:6,29` · `backend/requirements.txt` · `backend/requirements-research.txt` · `backend/scripts/vectorbt_research.py:21`

---

## 9. UYGULAMA — P1 turu (2026-11-09, commit'ler bu bölümün altında)

Araştırmanın P1 maddeleri koda döküldü. **Her araç bilinen cevaplı sentetik veriyle doğrulandı** — "çalışıyor gibi görünüyor" değil, beklenen sonucu verdiği kanıtlandı.

### 9.1 Eklenenler

| Dosya | Ne yapar | Katman |
|---|---|---|
| `backend/app/ml_probability.py` | İzotonik kalibrasyon + Brier/log-loss/**ECE**/güvenilirlik kovaları + **çekimserlik** (başabaş olasılık) + walk-forward bölme + JSON artefakt | **ÜRETİM** (yalnız numpy+sklearn — `requirements.txt`'te zaten var) |
| `backend/tests/test_ml_probability.py` | 22 test: metrik matematiği, aşırı-güven tespiti, yetersiz örnekte eğri kurulmaması, monotonluk, kalibrasyonun Brier/ECE'yi iyileştirmesi, çekimserlik, kalıcılık | test |
| `backend/scripts/edge_significance.py` | **RealityCheck + SPA + StepM + MCS** ("en iyi strateji şans mı?") | ARAŞTIRMA (`arch`) |
| `backend/scripts/purged_cpcv_report.py` | **PSR + DSR + PBO (CSCV) + MinTRL** | ARAŞTIRMA (`purgedcv`) |
| `backend/scripts/report_probability_calibration.py` | DB'den (`velocity_candidates`: `ml_hit_probability` → `touched_target`) eğri kurar, eğitim/test ayrı raporlar, artefakt yazar | OPS |
| `backend/app/llm_second_eye.py` | **Pydantic şema kapısı**: `SecondEyeVerdict` + `validate_verdict()`; çıktıya `schema_ok` / `schema_issues` ölçüm alanları | **ÜRETİM** (pydantic zaten var) |
| `backend/tests/test_llm_second_eye_schema.py` | 13 test: şema normalizasyonu, geçersiz rejim/tp/sl temizliği, eş anlamlı eşleme, kurtarma bayrağı, geriye dönük alan uyumu | test |
| `backend/scripts/baseline_and_multiple_testing.py` | (a) **baseline**: model vs `always_long`/`persistence`/`coin` + binom testi — "ML aptal kuralı yeniyor mu?" (b) **multitest**: BH/Holm/Bonferroni düzeltmesi | ARAŞTIRMA (`statsmodels`+`scipy`) |
| `backend/scripts/create_hnsw_index.py` | `memory_embeddings` HNSW index bakım işi: durumu ölçer, `CONCURRENTLY` ile kurar (canlı yazmayı bloklamaz), boş tabloda kurmaz | OPS |
| `backend/requirements-research.txt` | `arch==8.0.0`, `purgedcv==0.1.12`, `statsmodels==0.15.0` + neden/gerekçe | meta |

### 9.2 Doğrulama kanıtları

**`edge_significance.py`** — iki bilinen senaryo:

| Demo | Beklenen | Ölçülen |
|---|---|---|
| `--demo noise` (6 saf gürültü serisi) | hiçbiri anlamlı olmamalı | SPA p=**0.394**, RC p=0.43, StepM p=0.42 → **"KENAR YOK"** ✓ |
| `--demo edge` (1 gerçek kenar + 6 gürültü) | yalnız `edge_gercek` anlamlı | SPA p=**0.000**, `edge_gercek` **ÜSTÜN** + MCS'te, 6 gürültü **ELENDİ** ✓ |

**`purged_cpcv_report.py`**:

| Demo | Beklenen | Ölçülen |
|---|---|---|
| `--demo noise` | PSR<0.95, PBO yüksek | PSR 0.859, DSR 0.261, **PBO 0.446** → "KANITLANAMADI" ✓ |
| `--demo edge` | PSR/DSR≥0.95, PBO düşük | PSR **1.000**, DSR **1.000**, **PBO 0.000** → "KANITLANMIŞ" ✓ |

**`test_ml_probability.py`**: 22/22 geçti. Ölçülen örnek — ham olasılık %85-95 diyen ama gerçek isabet %60 olan 400 gözlemde izotonik eğri Brier'i **düşürdü** ve ECE'yi iyileştirdi; kalibre değer 0.90'dan <0.80'e indi (aşırı güven düzeltildi).

**`baseline_and_multiple_testing.py`**:

| Senaryo | Beklenen | Ölçülen |
|---|---|---|
| `baseline --demo noise` | model baseline'ı geçmemeli | isabet 0.498, p(vs yazı-tura)**=0.562** → "KANIT YOK" ✓ |
| `baseline --demo edge` | anlamlı iyi | isabet 0.592, p**=0.000** → "BASELINE'DAN ANLAMLI İYİ" ✓ |
| `multitest --method fdr_bh` (p = .001/.02/.04/.2/.6) | ilk ikisi geçer, üçüncüsü elenir | adj = .005/.050/**.0667** → hayatta kalan 2 ✓ (elle hesap birebir) |
| `--method holm` | yalnız birincisi | adj = .005/**.080**/**.120** → 1 ✓ |
| `--method bonferroni` | yalnız birincisi | adj = .005/**.100**/**.200** → 1 ✓ |

**`create_hnsw_index.py --dry-run`** (gerçek yerel Postgres): `pgvector=VAR`, `memory_embeddings=VAR (0 satır)`, `HNSW index=YOK` → boş tabloda index **kurmadı**, doğru uyarıyı verdi ✓ (migration'ın "backfill'den sonra kur" notuna uygun).

**`test_llm_second_eye_schema.py`** + mevcut `test_llm_second_eye.py`: 43/43 geçti — şema kapısı **hiçbir mevcut davranışı bozmadı**.

**Tüm backend paketi:** `1941 passed, 2 failed`. İki kırmızı **önceden vardı** (`test_forex_enhancements.py::test_gold_dynamic_atr_buffer`, `::test_btcusd_integration_and_specs` — ATR tampon değer kayması, temiz HEAD'de de kırmızı).

### 9.3 Uygulama sırasında yakalanan 3 gerçek hata (araçların kendisinde)

1. **`arch` sütun hizalaması** — `numpy` matris verildiğinde `mcs.included`/`stepm.superior_models` **konumsal** dizi döner ve sütun sırası garanti değildir; ilk sürümde Sharpe'ı **−0.73** olan bir gürültü serisi "ÜSTÜN" işaretlendi. Çözüm: `arch`'a **pandas DataFrame** verilir → sonuçlar **isimlerle** döner (`["edge_gercek"]`), konumsal eşleme tamamen kalkar.
2. **`arch` p-değer etiketleri** — `SPA.pvalues` indeksi `["lower","consistent","upper"]`'dır (`"SPA"` diye bir etiket YOK); `StepM`'in **p-değeri hiç yok**, `superior_models` verir. İlk sürüm `None` döndürüyordu (her zaman "kenar yok" derdi — fail-safe ama işe yaramaz).
3. **`validate_verdict` yedek yolu** — şema tamamen tutmadığında yalnız `verdict`/`confidence` temizleniyordu; `regime="trendy"` gibi geçersiz değerler aşağı akışa sızıyordu. Yedek normalizasyon artık `regime`/`suggested_tp_pct`/`suggested_sl_pct`/`reasons` alanlarını da temizliyor (testle kilitli).

### 9.4 Bu turda YAPILMAYANLAR (gerekçeli)

| Madde | Neden |
|---|---|
| `statsforecast` baseline (P1-4) | **`baseline_and_multiple_testing.py` ile karşılandı** — naif kurallar (always_long / persistence / coin) + tek taraflı binom testi. `statsforecast`'ın `numba`/LLVM derleme zinciri bu ihtiyaç için gereğinden ağır |
| HNSW index (P1-7) | **YAPILDI ama migration olarak DEĞİL**: `scripts/create_hnsw_index.py`. `CREATE INDEX CONCURRENTLY` transaction içinde çalışamaz; migration koşucusu tek transaction kullanıyor. Betik gerçek DB'de dry-run ile doğrulandı. **Çalıştırılması gerekiyor:** embedding backfill'inden sonra `python scripts/create_hnsw_index.py` |
| BGE reranker (P1-7) | Model ağırlığı indirmesi + servis bağımlılığı gerektirir; canlı arama yolunu değiştirir. Ölçüm yapılmadan açmak riskli |
| `instructor` (P1-6) | **Gereksiz çıktı**: aynı garanti `pydantic` + `validate_verdict` ile sağlandı, yeni bağımlılık eklenmedi |
| P2/P3 maddeleri (COT, talipp, SMC, seans, GARCH, Kelly, alphalens, mlflow, DVC, river, litellm) | Bu turun kapsamı P1'di; her biri ayrı entegrasyon ve doğrulama turu istiyor |

---

## 10. GÖLGE (SHADOW) KALİBRASYON — canlı ölçüm, sıfır karar değişikliği (2026-11-09)

`ml_probability` modülü hazırdı ama **canlı giriş kapısına bağlanmadı** — bilinçli: eşiği ölçümsüz açmak, `calibration.py`'nin kendi docstring'inin uyardığı hatanın aynısı olurdu. Bunun yerine **gölge mod** eklendi.

### 10.1 Ne yapar

Her canlı ML tahmininde (`ml_forecast.predict_target` → tek giriş noktası):

```
ham olasılık → kalibre olasılık → çekimserlik hükmü   (SADECE LOG + SAYAÇ)
```

Karar **değişmez**. Amaç 1-2 hafta sonra `velocity_candidates` sonuçlarıyla karşılaştırıp **eşiği kanıtla** açmak.

| Dosya | İş |
|---|---|
| `app/ml_shadow.py` | `observe()` / `counters()` / `reset_counters()`; artefakt **mtime kontrollü** okunur (yeni artefakt restart gerektirmez) |
| `app/config.py` | `ML_CALIBRATION_SHADOW_ENABLED` (varsayılan **açık**), `ML_CALIBRATION_ARTIFACT`, `ML_CALIBRATION_REWARD_RISK` (varsayılan 1.5) |
| `app/ml_forecast.py` | `predict_target()` içine tek kanca — dönen sözlük **aynen** korunur |
| `app/routers/system.py` | `/api/system/health` yanıtına `ml_calibration` bloğu (gözlem, çekimser oranı, ort. ham/kalibre, `artifact_loaded`) |
| `tests/test_ml_shadow.py` | 8 test |

### 10.2 Testlerin kilitlediği davranış

1. Gölge kapalıyken hiçbir iş yapılmaz (`observe → None`).
2. Artefakt yokken **ham olasılık korunur**, `calibrated=False` işaretlenir ("düzeltmiş gibi" davranmaz).
3. Artefakt varken kalibre değer uygulanır; çekimserlik eşiğin altında **yakalanır** (0.90 → kalibre 0.10 < eşik 0.40).
4. **`predict_target` gölge açıkken de kapalıyken de AYNI sözlüğü döndürür** — en önemli kilit (mock'lu test).
5. `observe()` hata durumunda **istisna fırlatmaz** (bozuk artefakt testi dahil) — tahmin yolu ölçüm yüzünden asla düşmez.
6. RR değişince eşik değişir (RR=3.0 → p*=0.25).
7. Sayaçlar doğru; `reset_counters` sıfırlar.

### 10.3 Uygulama sırasında yakalanan 2 hata

1. **`config` modül mü nesne mi?** Proje `from .config import config` ile **nesneyi** kullanıyor. `ml_shadow`'ta `from app import config` yazmıştım → `ML_CALIBRATION_ARTIFACT` bulunamadı, gölge mod sessizce `artifact: ''` ile çalıştı. Düzeltildi + yorumla kilitlendi.
2. **Uzun dict literal'ine gömülü atama** — `/api/system/health` yanıtı tek satırlık dev bir dict; yeni anahtarı eklerken atama cümlesi dict'in ortasına düştü ve dosya sözdizimi hatası verdi. Bölge bütün olarak yeniden yazıldı (import sonrası doğrulandı).

### 10.4 Nasıl açılır (kanıt toplandıktan sonra)

```bash
# 1) artefaktı üret (haftalık/aylık)
python -m scripts.report_probability_calibration --save artifacts/ml_calibration.json --rr 1.5
# 2) health'te sayacı izle
curl -s localhost:8000/api/system/health | jq .ml_calibration
# 3) çekimser oranı mantıklıysa VE test kümesinde Brier/ECE iyileştiyse:
#    eşiği canlı kapıya bağla (ayrı, ölçülmüş bir değişiklik)
```

Sağlık bloğu: `enabled`, `artifact_loaded`, `artifact_samples`, `observations`, `calibrated_observations`, `would_abstain`, `abstain_rate_pct`, `mean_raw`, `mean_calibrated`.

**Tüm backend testleri:** `1949 passed, 2 failed` (2 kırmızı önceden var).

---

## 11. P2 TURU — Seans pencereleri (P2-10)

### 11.1 Neden `pandas_market_calendars` DEĞİL

Araştırma P2-10 için `pandas_market_calendars` öneriyordu. **Üretim imajında pandas yok** (`requirements.txt`: numpy + scikit-learn). FX seans sınırları sabit UTC saatleridir → pandas gerekmez. Aynı işlev **bağımlılıksız** (yalnız `datetime`) yazıldı: `app/session_windows.py`.

### 11.2 Ne sağlıyor

| Fonksiyon | Çıktı |
|---|---|
| `active_sessions(dt)` | aynı anda açık seanslar (`asia`, `london`, `new_york`) |
| `in_overlap(dt)` | Londra ∩ NY (12:00–16:00 UTC) — günün en likit penceresi |
| `is_dead_zone(dt)` | 21:00+ UTC veya hafta sonu → düşük likidite |
| `liquidity_score(dt)` | 0.0 (kapalı) → 1.0 (örtüşme) |
| `spread_risk_window(dt)` | seans açılış/kapanışına ±15 dk → `"open"`/`"close"` |
| `is_weekend_closed(dt)` | Cuma 21:00 UTC → Pazar 21:00 UTC kapalı |
| `describe(dt)` | tek sözlükte tüm bağlam + Türkçe etiket |

Ölçülen çıktı (2026-11-09, Pazartesi):

```
02:00 UTC  likidite=0.50  Asya
08:00 UTC  likidite=0.80  Asya + Londra
10:00 UTC  likidite=0.80  Londra
13:00 UTC  likidite=1.00  Londra+NY örtüşmesi (en likit)
18:00 UTC  likidite=0.80  New York
22:00 UTC  likidite=0.20  Ölü bölge (düşük likidite)
Cumartesi  likidite=0.00  PİYASA KAPALI (hafta sonu)
```

### 11.3 Entegrasyon — SKORLAMAYA DOKUNMADAN

| Yer | Ne eklendi |
|---|---|
| `combined_radar.build_unified_envelope()` | `"session": session_windows.describe()` — **bilgi alanı, `score`'a girmez** |
| `/api/system/health` → `market.session` | aynı bağlam, ops/UI görünürlüğü |

**Bilinçli karar:** seans bilgisini skorlamaya/kapıya sokmak **backtest ister**. Bu turda yalnız görünürlük sağlandı; filtre olarak kullanmak ölçülmüş bir sonraki adımdır (aynı disiplin: `ml_shadow`).

### 11.4 Testler

`tests/test_session_windows.py` — **23 test**: seans sınıflandırma, örtüşme sınırları (16:00 kesme), ölü bölge, hafta sonu geçişleri (Cuma 21:00 / Pazar 21:00), spread-risk penceresi, naif datetime'ın UTC sayılması, farklı tz dönüşümü, gece yarısını aşan pencere mantığı.

**Yakalanan 1 hata:** Pazar 21:00'de piyasa *açılıyor* ama seans yok → likidite 0.0 değil **0.2 (ölü bölge)**. Test beklentim yanlıştı, kod doğruydu; test gerçek davranışa göre düzeltildi ve Asya skorundan küçük olduğu kilitlendi.

**Tüm backend:** `1972 passed, 2 failed` (2 kırmızı önceden var).

---

## 12. P2 TURU — COT kurumsal pozisyonlanma (P2-8)

### 12.1 Araştırma raporundaki iddia ÇÜRÜTÜLDÜ (kaynak dosya yanlıştı)

Araştırma "`NDelventhal/cot_reports` kullan" diyordu. Kaynağı **kendim indirip ölçtüm**:

| Dosya | Boyut | İçerik |
|---|---|---|
| `fut_disagg_txt_2026.zip` (önce denenen) | 2.1 MB | **333 market, YALNIZ EMTİA — hiç FX yok** (doğrulandı) |
| `fut_fin_txt_2026.zip` (doğru olan) | 632 KB | **FX var**: EUR, GBP, JPY, CHF, CAD, AUD, MXN |

Yani FX sözleşmeleri **TFF (Traders in Financial Futures)** raporunda. Ayrıca bu dosya
`Noncommercial_*` değil `Dealer_*` / `Asset_Mgr_*` / **`Lev_Money_*`** kolonlarını taşıyor —
eski legacy şema **yok**. Bu aslında daha iyi: "sıcak para" (leveraged money) ile
"gerçek para" (asset manager) ayrışıyor ve **ikisinin ayrışması başlı başına bilgi**.

### 12.2 Eklenenler

| Dosya | İş |
|---|---|
| `app/cot_positions.py` | Saf hesaplama + artefakt okuyucu. **Yalnız stdlib** (json/math/os), ağ YOK. `parse_rows`, `build_artifact`, `bias()`, `summary()`; mtime kontrollü önbellek |
| `scripts/fetch_cot_positions.py` | CFTC zip indir → artefakt JSON. `--file` (yerel zip), `--year` (çoklu), `--dry-run` |
| `tests/test_cot_positions.py` | 16 test (aşağıda) |
| `.gitignore` | `backend/artifacts/` (üretilen artefaktlar commit edilmez — takvim önbelleğiyle aynı sınıf) |
| `/api/system/health` | `cot` bloğu (rapor tarihi, tazelik, para birimi duruşları) |

### 12.3 GERÇEK VERİYLE doğrulama (2026-11-03 raporu)

```
kur       OI        lev_net   lev %OI  asset %OI   bias   duruş  kalabalık  Δhafta
MXN   283,227      +71,381    +25.2      -12.8   +0.93    LONG       %44    +0.74
CAD   348,660      -86,302    -24.8       +4.7   -0.93   SHORT       %74    +2.05
AUD   328,599      +50,106    +15.2      -39.8   +0.77    LONG       %38    +0.35
CHF   133,162      -16,845    -12.7      -15.7   -0.69   SHORT     %94 ⚠    +0.27
GBP   245,590      +26,663    +10.9      -49.3   +0.62    LONG       %47    +4.09
EUR   876,122      -78,559     -9.0      +16.5   -0.54   SHORT     %99 ⚠    -0.72
JPY   380,641      -14,817     -3.9      +20.9   -0.25   SHORT        %3    +0.02
Ayrışma (sıcak para ↔ gerçek para ZIT yönde): AUD, CAD, EUR, GBP, JPY, MXN
Bu raporda YOK (uydurulmadı): NZD
```

Yorum: **EUR %99 kalabalık kısa** ve asset manager'lar uzun → klasik sıkışma adayı.
`NZD` bu dosyada yok; modül onu **uydurmaz**, `unavailable` listesinde bildirir.

### 12.4 Testlerin kilitlediği davranış (16 test)

1. `parse_rows` net/%-OI doğru hesaplar.
2. **Çapraz kur satırları atılır** (`EURO FX/BRITISH POUND XRATE` EUR'u ikinci kez saymamalı — çift sayım hata sınıfı).
3. OI=0 veya eksik lev kolonu → satır atılır (sıfıra bölme yok).
4. `bias` tanh ölçeğinde, işareti doğru, NEUTRAL bandı çalışıyor.
5. `crowding_pct` **mutlak** pozisyonun tarihsel yüzdeligi; %90 eşiği `crowded`.
6. `change_wow_pct` tek noktada None.
7. `divergence` üç durumlu (True/False/None).
8. `load_artifact` yok/bozuk → None; **mtime değişince yeniden okur**.
9. `summary`/`bias` tazelik ve bilinmeyen kur davranışı.
10. `NZD` `unavailable` listesinde.

**Yakalanan test hatası:** `test_summary_without_artifact` gerçek artefakt diske yazıldıktan sonra kırıldı (test ortama bağımlıydı). `COT_ARTIFACT_PATH` env'i geçici olarak var olmayan yola çekilerek **yalıtıldı** — testler artık repo durumundan bağımsız.

### 12.5 NE YAPMAZ (dürüstlük)

`bias()` bir **al/sat sinyali değil, bağlamdır**. COT haftalıktır ve **~3 gün gecikmelidir**;
skorlamaya/kapıya sokmak backtest ister. Şu an yalnız `/api/system/health` ve rapor
yüzeyinde görünür — radar skorlamasına **girmedi** (bilinçli).

**Tüm backend:** `1988 passed, 2 failed` (2 kırmızı önceden var).

---

## 13. P2 TURU — Sinyal IC/kuantil ölçümü (P2-14) · **İLK GERÇEK BULGU**

### 13.1 Neden `alphalens-reloaded` değil

`alphalens` pandas + scipy ister; üretim imajında ikisi de yok. IC (Spearman) ve
kuantil getirisi **saf numpy** ile hesaplanabilir → `app/signal_edge.py`
(`information_coefficient`, `ic_tstat`, `quantile_returns`, `monotonicity`,
`align_forward_returns`). 21 test. Ağır tearsheet gerekirse `alphalens`
araştırma katmanında ayrıca koşulabilir.

### 13.2 GERÇEK ÜRETİM VERİSİYLE ÖLÇÜM — 65.471 aday, 180 gün

`scripts/report_signal_edge.py` yerel Postgres'teki `velocity_candidates`
üzerinde koştu:

| Ölçüm | n | IC | t | Tekdüze? | Hüküm |
|---|---|---|---|---|---|
| `ml_hit_probability` → MFE | 53.596 | **0.216** | 50,8 | ✅ evet | Güçlü |
| `velocity_score` → MFE | 65.471 | **0.111** | 28,5 | ✅ evet | Anlamlı |
| `ml_hit_probability` → `touched_target` | 53.596 | 0.074 | 17,1 | ❌ **HAYIR** | Sorunlu |

Kuantil tablosu (`ml_hit_probability` → MFE) — **düzgün artan**:

```
Q1 1.19%   Q2 1.46%   Q3 1.81%   Q4 2.06%   Q5 2.74%
```

Ama **hedefe değme** oranı tekdüze DEĞİL:

```
Q1 0.198   Q2 0.278   Q3 0.324   Q4 0.310   Q5 0.299   ← tepe Q3'te, Q5 daha kötü
```

### 13.3 Kök neden — ÖLÇÜLDÜ ve DOĞRULANDI

| Dilim | ort. olasılık | ort. **hedef %** | ort. MFE % | MFE/hedef | isabet |
|---|---|---|---|---|---|
| Q1 | 0.006 | 2.077 | 1.194 | 0.57 | 0.198 |
| Q2 | 0.020 | 2.138 | 1.464 | 0.68 | 0.278 |
| Q3 | 0.046 | 2.324 | 1.807 | 0.78 | 0.324 |
| Q4 | 0.088 | 2.533 | 2.062 | 0.81 | 0.310 |
| Q5 | 0.248 | **2.893** | 2.742 | **0.95** | 0.299 |

`target_pct` olasılıkla birlikte **büyüyor** (Spearman **0.537**). Yani modelin
"hit probability"si aslında **hareketin BÜYÜKLÜĞÜNÜ** iyi sıralıyor; ama hedef de
aynı oranda büyüdüğü için **hedefe değme oranı** üst dilimde düşüyor
(Q5'te MFE/hedef 0.95 → hedefin dibinde kalıyor).

**Sonuç:** "olasılık yüksek = isabet yüksek" varsayımı **üst dilimde yanlış**.
`ml_probability`'nin `touched_target` üzerinde kalibre edilmesi (P1-3) ve hedef
boyutunun olasılıktan **ayrıştırılması** tam olarak bu boşluğu hedefliyor. Bu,
ölçüm katmanı olmadan görülemeyecek bir bulgu.

### 13.4 Ne YAPILMADI (bilinçli)

Hedef boyutu/olasılık bağını değiştirmek **backtest ister**. Bu turda yalnız
ölçüm ve kanıt üretildi. Sıradaki adım: `ml_probability` artefaktı + hedef
ayrıştırma varyantının A/B'si (PBO/DSR ile).

**Tüm backend:** `2009 passed, 2 failed` (2 kırmızı önceden var).

---

## 14. HEDEF-OLASILIK BAĞINI AYIRMA — KARŞI-OLGUSAL BACKTEST

**Soru:** §13'te bulunan bozukluğu (hedef olasılıkla birlikte büyüyor, üst dilim hedefe daha az değiyor) hedefi olasılıktan **ayırarak** düzeltmek beklenen değeri iyileştirir mi?
**Araç:** `scripts/backtest_target_decoupling.py` · **Veri:** 65.471 aday, 180 gün, yerel Postgres.

### 14.1 Yöntem ve dürüst sınır

`mfe_pct` (gerçekleşen maksimum elverişli hareket) karşı-olgusal hedef için kullanılabilir: `mfe_pct ≥ T'` ise T' seviyesine **bir noktada** ulaşılmıştır. Ancak bu "**stop'tan ÖNCE** ulaşıldı" demek değildir — MFE zamanlaması veride yok. Bu yüzden varsayım uydurmak yerine **iki sınır** hesaplandı:

* **alt sınır (garanti):** `touched_target=True` **ve** `T' ≤ target_pct` → gerçek (daha büyük) hedefe stop'tan önce ulaşılmış, küçük hedefe de kesinlikle ulaşılmıştır.
* **üst sınır (iyimser):** `mfe_pct ≥ T'` — sıralama bilinmiyor.

Gerçek değer bu ikisinin arasındadır. **Üst sınır bile negatifse** karar kesindir.

Ekonomi **veriden** ölçüldü (varsayım değil): sabit stop **1.50%**, işlem maliyeti **0.35 puan**. Değerlendirme gürültüsü yok sayılabilir: `intrabar_ambiguous` = **%0,05** (25 / 52.341).

### 14.2 Mevcut tasarım (taban)

| | Değer |
|---|---|
| İsabet | **%28,2** |
| Ortalama hedef | %2,393 |
| **Brüt EV** (maliyet öncesi) | **−0,403 puan** |
| Net EV | **−0,477 puan** |
| Brüt break-even isabet (T/SL=1,60) | **%38,5** → açık **+10,4 puan** |

> **Dikkat:** brüt EV zaten negatif. Yani **maliyet ana sorun değil** (maliyetin etkisi sadece −0,073 puan).

### 14.3 Sabit hedef ızgarası

| T' (%) | isabet alt | isabet üst | EV alt | **EV üst** | BE isabet | tekdüze (üst) |
|---|---|---|---|---|---|---|
| 0,50 | 0,282 | 0,736 | −1,287 | **−0,378** | 0,925 | ✅ |
| 1,00 | 0,282 | 0,571 | −1,146 | **−0,422** | 0,740 | ✅ |
| 1,50 | 0,282 | 0,450 | −1,005 | **−0,501** | 0,617 | ✅ |
| 2,00 | 0,229 | 0,358 | −1,049 | **−0,597** | 0,529 | ✅ |
| 2,50 | 0,089 | 0,256 | −1,494 | **−0,827** | 0,463 | ✅ |
| 3,00 | 0,039 | 0,191 | −1,674 | **−0,990** | 0,411 | ✅ |

**İki bulgu:**
1. **Ayrıştırma tekdüzelik bozukluğunu DÜZELTİYOR** — T' ≤ 1,5% için isabet oranı olasılıkla birlikte tekdüze artıyor (§13'teki bozukluk kayboldu) ✅
2. **Ama EV hiçbir hedefte pozitif değil** — iyimser üst sınırda bile en iyisi **−0,378** (T=0,5%)

### 14.4 ATR tabanlı (olasılıktan tamamen bağımsız) hedef

| k×ATR | hedef ort. | isabet (üst) | EV (üst) | BE isabet |
|---|---|---|---|---|
| 4 | 2,689% | 0,313 | **−0,538** | 0,442 |
| 6 | 4,034% | 0,169 | **−0,916** | 0,334 |
| 8 | 5,379% | 0,086 | **−1,261** | 0,269 |

Hepsi negatif. Ayrıştırma **tek başına yeterli değil**.

### 14.5 Bootstrap ve kararlılık

En iyi varyant (T=0,5%) vs mevcut: **ΔEV = +0,098 puan**, %95 GA **[+0,086, +0,112]** → istatistiksel olarak **anlamlı** ve **iki zaman yarısında da tutarlı** (aşırı uyum kokusu yok). Ama sonuç hâlâ **negatif**.

### 14.6 SEÇİCİLİK de kurtarmıyor (belirleyici ölçüm)

Gerçekleşen net EV, olasılık on-dilimlerinde:

| Dilim | ort. p | isabet | net EV | brüt EV |
|---|---|---|---|---|
| D1 | 0,003 | 0,162 | −0,488 | −0,920 |
| D5 | 0,039 | **0,335** | **−0,391** | −0,237 |
| D9 | 0,156 | 0,321 | −0,453 | −0,143 |
| **D10** | 0,340 | 0,278 | **−0,570** | −0,234 |

`velocity_score` on-dilimleri de tümüyle negatif (−0,434 … −0,530). **En iyi dilim bile −0,434.** Yani "eşiği yükselt, sadece iyi adayları al" **çalışmıyor**: hiçbir alt küme kârlı değil.

### 14.7 KÖK NEDEN — geometri, hedef değil

Brüt break-even: `p·T = (1−p)·SL` → mevcut isabet (%28,2) ve T (%2,39) ile:

```
gereken SL = p·T/(1−p) = 0,282 × 2,393 / 0,718 = 0,94%
```

**Yani stop'un 1,50% → ~0,94% olması gerekir (%37 daraltma).** Ama daraltma isabeti de düşüreceği için bu **bedava değil**. Alternatif (SL sabitken) gereken T = **3,82%** — gerçekçi değil.

Ek not: işlemlerin **%20'si `MAX_HORIZON_EXPIRED`** ve net **−0,365** ile kapanıyor (ısınma/trend çıkışı ~0'da). Bu bacak başlı başına bir iyileştirme alanı.

### 14.8 HÜKÜM

1. **Hedefi olasılıktan ayırmak, sıralama bozukluğunu düzeltir** (kanıtlandı) — ama **kârlılığı çözmez**.
2. **Bağlayıcı kısıt hedef boyutu değil**, `stop/target geometrisi × isabet oranı`. 1,5% stop + 2,4% hedef için %38,5 isabet gerekiyor; aday havuzu **her olasılık düzeyinde** %28 civarı veriyor.
3. **Maliyet (0,35 puan) ikincil** — brüt EV zaten −0,403.
4. **Doğru sonraki adım:** stop/hedef geometrisini (ör. SL 0,9-1,1% ya da ATR tabanlı asimetrik) **yeniden değerlendirme döngüsüyle** test etmek — karşı-olgusal MFE aritmetiği bunu **kanıtlayamaz** (sıralama bilinmiyor). Alternatif: `MAX_HORIZON_EXPIRED` bacağını ayrı tasarlamak.

**Not:** `ml_probability` kalibrasyonu + gölge mod artık hazır; geometri değiştiğinde "kalibre olasılık eşiği" **ölçülerek** seçilebilir.
