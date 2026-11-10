# GitHub + YouTube Derin Araştırması — Otonom FX Kârlılığı ve LLM Fırsat Taraması

**Tarih:** 2026-11-10 · **Kapsam:** (A) otonom forex işlemlerinin başarısı/kârlılığı, (B) LLM fırsat taramasının başarısı/kârlılığı
**Yöntem:** 4 paralel araştırma kolu (işlem yönetimi · etiketleme/doğrulama · LLM hattı · veri & backtest gerçekçiliği). Her GitHub adayının metadata'sı `gh api repos/...` ile bu oturumda çekildi; kaynak kod/README okundu. Doğrulanamayan iddialar açıkça işaretlendi.

---

## 0) Güven sınırı — bu raporun iddia seviyesi

1. **Hiçbir adayın bizim verimizdeki kazancı ÖLÇÜLMEDİ.** Aşağıdaki tüm "beklenen fayda" ifadeleri hipotezdir; kabul ölçütü replay A/B (`scripts/forex_replay_backtest.py`) veya bilinen-cevap sentetik testidir.
2. **Yıldız sayısı kanıt değildir.** Örn. `TauricResearch/TradingAgents` ★121.636 (doğrulandı) ama reposu kendi README'sinde "sonuçlar garanti edilmez, araştırma iskeleti" diyor — yalnız değerlendirme harness'ı fikri alındı.
3. **Ajan çıktısında yanlış çıkan 3 iddia düzeltildi** (aşağıda §1.3). Rapora alınan her sayı koddan/`gh api`'den teyitlidir.

---

## 0.5 ÖLÇÜM SONUCU — gerçek defter (aynı gün koşuldu, hipotezlerin bir kısmı DÜŞTÜ)

Rapor yazıldıktan hemen sonra iki ölçüm betiği yazıldı ve **MT5 hesabının kendi defterinde** koşuldu (ICMarketsSC-Demo 53077151, equity ~415 USD):
`scripts/fx_intrabar_ambiguity.py` (belirsizlik bandı + gerçek swap) · `scripts/fx_symbol_expectancy.py` (sembol bazlı R beklentisi + ölçülen maliyet + kararlılık).

### A) İntrabar belirsizlik: **%1.9** → P1 DEĞİL (kendi teşhisim düzeltildi)
- 4367 kapanmış pozisyon / 60 gün: **81 işlemde** çıkış barında iki bariyer de düşüyor (%1.9).
- Bunların yalnız **10'u** tick ile çözülebildi (tick derinliği sınırı) → çözülenlerde "SL-first" varsayımı 2/10 doğru çıktı.
- Ama hacim küçük: replay sonucunu "temelden sarsan" bir belirsizlik **yok**. §2.5 "en kritik" sıralamasından **çıkarıldı**, izleme maddesine indirildi.
- Yol boyunca çıkan iki gerçek bulgu:
  - Pozisyonların **%33'ünde TP emri yok** (`no_tp`/runner modu) → o işlemlerde "TP mi SL mi önce" sorusu zaten anlamsız.
  - **SL neredeyse hiç taşınmıyor**: 4322 pozisyonda SL'in girişin kâr tarafına taşındığı vaka **1**. Yani "trailing" SL'i kaydırmıyor, pozisyonu piyasadan kapatıyor (`reason=EXPERT`). Broker etiketi ile (240/276 "SL ama kazanç") aynı kök: **etiketler değil, fiyat kanıtı esastır**.

### B) Gerçek swap vs komisyon (modellenmemiş kalem ölçüldü)
- 60 gün: swap toplamı **−19 USD**, komisyon **−2761 USD**. Yani maliyetin asıl kalemi **komisyon**, swap değil (swap beklentisi bu FX/endeks setinde ihmal edilebilir).

### C) ASIL KÖK NEDEN ÖLÇÜLDÜ: payoff 0.50 (gereken 0.67)
`fx_symbol_expectancy.py --days 60`: **4315 işlem, isabet %59.4, ortalama kazanan +0.43R, ortalama kaybeden −0.87R → beklenti −0.097R/işlem, net −9750 USD.**

| Ölçüm | Değer |
|---|---|
| Ortalama kazanan | **+0.43R** |
| Ortalama kaybeden | **−0.87R** |
| Payoff (kaz/kay) | **0.50** |
| Bu payoff ile break-even isabet | **%66.8** |
| Gerçek isabet | %59.4 (açık **7,4 puan**) |
| Ölçülen maliyet (komisyon+spread p50) | ort **0.061R** (küçük!) |

**Okuma:** Kaybeden neredeyse tam stop (−0.87R) ama kazanan ancak yarım risk (+0.43R). Yani sistem "kaybedeni tam yiyor, kazananı yarıda kesiyor". Maliyet ikincil (0.061R). Bu, önceki "geometri" teşhisini **para cinsinden doğruluyor** ve hedefi netleştiriyor: payoff **0.50 → 0.67** (o zaman break-even %40'a iner).

**Sembol ayrışması (n≥30, 60 günün İKİ yarısında da negatif olanlar):** EURJPY −0.474R · USDJPY **−0.402R (−2401 USD, isabet %36.8)** · GBPJPY −0.269 · USDCHF −0.246 · NZDUSD −0.242 · AUDUSD −0.237 · EURUSD −0.132 · USDCAD −0.115 · GBPUSD −0.089 · **XAUUSD −0.051R (−790 USD, n=961)** · **BTCUSD −0.049R (−2193 USD, n=1260)**. Pozitif güvenilir: **yalnız US30** (+0.034R, isabet %77.6). USTEC belirsiz (+0.023R).
⚠️ Kritik ayrım: XAUUSD/BTCUSD'de **maliyet R 0.036-0.038 = sorun maliyet değil, payOff** (0.47/0.50). Yani "hatalı sembolü kes" yetmez; en hacimli iki sembol de geometri sorunundan zarar ediyor. Maliyetin gerçekten yüksek olduğu yerler ayrı: AUDNZD 0.204R, UNIUSD 0.204, BNBUSD 0.290, LNKUSD 0.331, XTZUSD 0.326, ADAUSD 0.385 (bunlar zaten allowlist dışı/legacy).
⚠️ Bu seçim **in-sample**'dır (aynı 60 günün yarıları); kalıcı blok kararı replay A/B ile teyit edilmeli.

### D) Değişen öncelik sırası
1. **Payoff/geometri A/B** (kazananı erken kesme: TP genişliği, trailing mesafesi, kısmi-kâr oranı) — ölçüte PF değil **payoff + beklenti R**.
2. **Sembol kesme/limitleme** (USDJPY, EURJPY, GBPJPY, USDCHF, NZDUSD, AUDUSD) — mekanizma hazır (`blocked_symbols`), ölçüm yukarıda.
3. 1:1 falsifikasyon + n-bar çıkış (giriş kalitesi tavanı).
4. LLM tarafı (§4) — defter ölçümünden bağımsız.

---

## 1) Mevcut durum — kendi kodumuzdan doğrulananlar

| Bulgu | Kanıt |
|---|---|
| Replay **zaten muhafazakâr tie-break** kullanıyor: SL → BE → kısmi → trailing → TP | `scripts/forex_replay_backtest.py:2174` docstring + gövde |
| Veri kaynağı artık MT5 köprüsü: `historical_candles`, `source ∈ {mt5_icmarkets_tick, *_5m_downsampled}` | `scripts/forex_replay_backtest.py:1818-1827` |
| Tick'ten bar + **gerçek spread profili** üreten betik VAR | `scripts/fx_build_tick_cache.py` (`mt5.copy_ticks_range` + `COPY_TICKS_ALL`) |
| Gerçek spread profili DB'ye yazılıyor | `backend/app/database.py:4572` |
| Pozisyon boyutu **sabit %1 risk** (`RISK_PCT = 1.0`), vol-hedefleme yok | `scripts/forex_replay_backtest.py:52` |
| Zaman stopu altyapısı hazır (`time_stop_bars`), yalnız belirli modlarda kullanılıyor | `scripts/forex_replay_backtest.py:1973, 2583` |
| Araştırma katmanı ayrı ve kurulu: `vectorbt, pandas, arch, purgedcv, statsmodels` | `backend/requirements-research.txt` |
| PBO/DSR/CPCV zaten var; `pypbo` ve `mlfinlab` **gerekmez** | aynı dosyadaki notlar + `scripts/purged_cpcv_report.py` |

### 1.3 Ajan iddialarından düzeltilenler
- ❌ "Replay TP-first varsayıyor, SL-first'e çevir" → **yanlış**; kod zaten SL-first (§1 satır 1). Gerçek boşluk: *belirsizliğin büyüklüğünün ölçülmemiş olması* → §2.5.
- ❌ "`docs/FX_KALIBRASYON_PLANI.md` Aşama 4" → **böyle bir dosya yok** (repo'da doğrulandı). Referans rapora alınmadı.
- ❌ "`purgedcv` / `pypbo` ekleyelim" → `purgedcv` zaten kurulu, `pypbo` bilinçli olarak dışarıda bırakılmış (AGPL + PBO zaten `arch` ile var).

---

## 2) P1 — Kök nedene ve ölçüm dürüstlüğüne dokunanlar

Kök neden defteri: 276 işlemde PF 0.624, isabet **%56.2**, break-even **%67.2** → açık **11 puan**. Yani kazanma sıklığı yeterli, **geometri + maliyet** yetmiyor. Aşağıdaki maddeler doğrudan bu açığı hedefler.

### 2.1 Stop mesafesi, tutma süresiyle hizalı mı? (Carver)
- **Kaynak (doğrulanmış alıntı):** Rob Carver, *Systematic Investor* Ep.226, 2023-01-15 — "He says 1.5 ATR, I would say that's way too tight… It's not about optimizing the ideal exit, it's about making sure that the stop is aligned in time with the holding period of the underlying trading signal" (16/64'lük sistem için ~**7 ATR** öneriyor).
- **Neden önemli:** Bizim stopumuz bar cinsinden tutma süresine göre 3-4 kat sıkı olabilir; sıkı stop, gürültüyle çıkışı tetikler → isabet %56'da kalırken kazanan bacak kısalır.
- **Bağlanır:** `--sl-mult` / SL-ATR tüneli + `TUN_CHANDELIER` eşzamanlı ölçeklenir.
- **Ölçüm:** replay A/B — SL 1.5 / 3 / 5 × ATR, **aynı giriş kümesi**, ayrı OOS pencerede. Metrikler: PF, avgWin/avgLoss, break-even isabet, maxDD.
- **Risk:** geniş stop tek başına DD büyütür → §2.2 ile birlikte uygulanmalı.

### 2.2 Volatilite-hedefli pozisyon boyutu (sabit %1 yerine)
- **Kaynak (kaynaktan okundu):** `pst-group/pysystemtrade` — ★3.620, push 2026-11-02, GPL-3.0. `systems/positionsizing.py:71-198`: `vol_scalar = cash_vol_target / instr_value_vol`, ardından `subsystem_position_raw = vol_scalar * forecast / avg_abs_forecast`.
- **Bağlanır:** `RISK_PCT=1.0` (replay:52) ve canlı motor lot hesabı. Ağır bağımlılık → **formül port edilir, import edilmez**.
- **Ölçüm:** aynı sinyaller, lot = vol-ölçekli vs sabit; maxDD, sembol-bazlı PnL varyansı, PF kararlılığı.
- **Beklenen fayda (hipotez):** maxDD düşer; PF seviyesi değişmese bile **hayatta kalma** artar — 414 USD'lik hesapta %67 tepeden düşüşün bir kısmı boyutlandırma kaynaklı.

### 2.3 Falsifikasyon testi: 1R:1R sabit test (Grimes)
- **Kaynak:** Adam Grimes, "Consistently Profitable Mindset & Trading Techniques" — transkriptte: 1:1 kâr/stop ile sistemi test et; isabet %50'yi geçmiyorsa hiçbir çıkış ayarı kurtarmaz. (Kanal/tarih doğrulanamadı, yöntem net.)
- **Neden:** "Çıkış motoru mu, giriş sinyali mi suçlu?" sorusunu tek koşuda ayırır. Ucuz ve bağımlılıksız.
- **Ölçüm:** replay'e 1:1 sabit kolu; isabet + **Wilson alt sınırı** (%95) break-even'in altındaysa giriş kalitesi zaten yetersiz → §2.1/2.2 tek başına yetmez, strateji seti değişmeli.

### 2.4 Saf sinyal testi: n-bar çıkış (Davey)
- **Kaynak:** Better System Trader #162 "Building Effective Entries And Exits" (bölüm: 13:00 n-bar exit ile girişi stop/hedeften izole etme; 18:00 çoğu göstergenin %45-55 bandı).
- **Bağlanır:** mevcut `time_stop_bars` alanı (`replay:1973`) 1/3/6/12 bar ile A/B.
- **Beklenen fayda:** "bizim exit katmanımız sinyale ne katıyor/ne götürüyor" sorusunun sayısal cevabı.

### 2.5 İntrabar belirsizlik bandı — ölçüm dürüstlüğü (P1, en kritik)
Bar içinde hem SL hem TP'ye değen işlemlerde sıra varsayımı sonucu belirler. Kodumuz SL-first (muhafazakâr) varsayıyor — doğru tercih — ama **etkinin büyüklüğü bilinmiyor**.
- **Yapılacak:** (1) SL/TP'si aynı 5m barı paylaşan işlem alt-kümesini say; (2) o alt-küme için `mt5.copy_ticks_range` ile tick yolunu çöz (betik zaten var: `fx_build_tick_cache.py`); (3) tick yoksa iki senaryoyu (SL-first / TP-first) koşup PF–isabet–break-even **bandını** raporla.
- **Kaynak/teyit:** MT5 resmi `copy_ticks_range` (`COPY_TICKS_ALL`, bid+ask+time_msc); MQL5 forum 519515: M1-OHLC modu dakikaya yalnız 4 tick yerleştirir ve **barda tek spread** kullanır → OHLC ile intrabar çözülemez. Dukascopy yedeği: `Leo4815162342/dukascopy-node` (MIT, ★960, push 2026-10-28). Uyarı: Dukascopy feed ≠ broker feed, kesin fiyat değil.
- **Beklenen fayda:** Ölçülen PF/isabet değerlerine **güven aralığı** kazandırır; "iyileştirme mi, varsayım değişikliği mi" ayrımı netleşir. Bu yapılmadan diğer tüm A/B'lerin sonucu tartışmalıdır.
- **Ek maliyet kalemi (aynı başlık):** swap/taşıma — MT5 `SYMBOL_SWAP_LONG/SHORT`, `SYMBOL_SWAP_MODE`, `SYMBOL_SWAP_ROLLOVER3DAYS` (Çarşamba 3×). Gece tutulan pozisyon sayısı × swap = R maliyeti; mevcut `cost_r` hesabına girmiyor.

### 2.6 Ardışık kayıp / seri-SL sigortası (fikir ödünç)
- **Kaynak:** `freqtrade/freqtrade` ★56.710, push 2026-11-09, GPL-3.0 — `plugins/protections/{stoploss_guard, cooldown_period, max_drawdown_protection}.py`; `docs/stoploss.md`: stop çok sıkı ayarlanırsa dolum kaçırma riski artar.
- **Bağlanır:** `_abstain_blocks` (kanıt kapısı) yanına "seri kayıp sonrası cooldown" — kapı kararı yine gölge önce.
- **Ölçüm:** replay'de protection state machine A/B; metrik: ardışık kayıp kümesi sayısı, maxDD.

---

## 3) ML hattı (`backend/app/forex_ml.py`) — mevcut sorun: test skill ~0.04, CV negatife kaçabiliyor

| # | Aday | Doğrulanmış metadata | Ne yapar | Bağlanır | Ölçüm / doğrulama | Öncelik |
|---|---|---|---|---|---|---|
| 3.1 | **Meta-labeling** (birincil sinyal + ikincil P(win)) | `stefan-jansen/machine-learning-for-trading` ★21.769, MIT, push 2026-11-06 (bakımlı); anlatım: Hudson & Thames "Meta-Labeling: Theory and Framework" (2022-10-19) + "Calibration and Position Sizing" (2023-03-10) | Birincil model yönü verir, ikincil model **yalnız işlem alıp almamaya** karar verir → precision↑, işlem sayısı↓ | `forex_ml.py` ikinci lojistik + `ml_probability.py` | Replay A/B (meta açık/kapalı, aynı sinyaller): precision, işlem başına R, işlem sayısı | **P1** |
| 3.2 | **Örnek benzersizliği ağırlığı** (`sample_weight ∝ 1/uniqueness`) | Denklem kaynağı `hudson-and-thames/mlfinlab` ★4.973 ama push 2023-10-02 + **lisans NOASSERTION (ticari kullanım yasak)** → **kütüphaneyi kurma, denklemi yaz** | Örtüşen etiketlerin yapay örnek çoğalmasını keser | `forex_ml.py` fit ağırlıkları | Bilinen-cevap sentetik (bariyerleri elle ayarlı seri, etiketler önceden bilinir) + ağırlık öncesi/sonrası Brier | **P1** |
| 3.3 | **CV'ye embargo/gap** | scikit-learn `TimeSeriesSplit(gap=k)` — sklearn zaten üretimde | Etiket ufku sızıntısını kapatır | `forex_ml.py` bloklu CV | Sızıntı enjekte edilmiş sentetik seride gap'siz yüksek / gap'li düşük skill göstermeli | **P1** |
| 3.4 | **Drift alarmı** | `online-ml/river` ★6.143, BSD-3-Clause, push 2026-11-09; `ADWIN`, `PageHinkley`, `KSWIN`, `DriftRetrainingClassifier` | Kaymayı CV sonucundan **önce** yakalar; retrain tetikler | `forex_ml.py` eğitim/skor akışı | Sentetik: t=500'de ortalama 0→0.5σ kayar; alarm ±50 bar içinde mi? Sonra gerçek veride alarmlı-retrain vs sabit takvim A/B | **P1** (deps: scipy/numpy/narwhals; pandas opsiyonel → kurulum testi şart) |
| 3.5 | **Venn-Abers / beta kalibrasyon** | `ip200/venn-abers` ★208, MIT, push 2026-09-02 (**pandas ister → port**); `betacal/python` ★32, MIT, push 2024-02-12 (yavaş) | İzotonik tek olasılık yerine `[p0,p1]` + "belirsiz" çıktısı; küçük n'de daha az aşırı uyum | `ml_probability.py` alternatif kalibratör | Sentetik ezilmiş skorlar: ECE önce/sonra + kapsama | P2 |
| 3.6 | **Çift-CV çapraz kontrolü** | `eslazarev/purged-cross-validation` ★63, MIT, push 2026-11-08 | Bağımsız CPCV implementasyonu → bizim betiğin bug yakalayıcısı | `scripts/purged_cpcv_report.py` yanında | Aynı K'da kat indeksleri birebir karşılaştırılır | P3 (pandas) |

**Elenenler:** `mlfinlab` (lisans + 2023'te dondu) · `alibi-detect` (Business Source License, ticari üretim yasak) · `scikit-multiflow` (river'ın atası, durdu) · `MAPIE`/split-conformal (ikili etikette bilgisiz çıktı — daha önce ölçtük; sınıf-koşullu kapsama çözülmeden geri gelmemeli) · `Evidently`/`NannyML` (pandas/plotly ağır; NannyML'in **etiket-gecikmeli** performans kestirimi fikri ilginç → P3 izleme).

---

## 4) LLM fırsat taraması — ölçülen iki kusur: (i) veto değer katmıyor (ΔR −0.02), (ii) "21-AI konsensüsü" sabit üretiyor şüphesi

| # | Aday | Doğrulanmış metadata | Ne yapar | Bağlanır | Ölçüm / doğrulama | Öncelik |
|---|---|---|---|---|---|---|
| 4.1 | **`instructor` — şemalı çıktı** | ★14.100, MIT, push 2026-11-09 | Pydantic şeması + validation-retry; serbest metin onarımı yerine **yapı garantisi** | `llm_analysis.py:chat(json_mode=...)`, `llm_trade_review.py:parse_verdict` (bugün `_balanced_objects`/`_repair_scalar_tokens` ile gevşek onarım → %16 hata) | `backend/evals/golden_cases.json` (9 vaka, dosya doğrulandı) + 10 bozuk-JSON vakası; hedef parse hatası <%2 | **P1** |
| 4.2 | **Sözel (verbalized) güven** | arXiv:2305.14975, **EMNLP 2023** (ACL Anthology 2023.emnlp-main.330) | RLHF'li modellerde sözel güven, log-prob'dan daha iyi kalibre | Dosyaya sayısal güven alanı → mevcut `llm_calibration.py:walk_forward_metrics/suggest_threshold` | Gölge kayıtlarda **ECE** + eşik önerisi; LLM'li vs LLM'siz aynı sinyalde ΔR | **P1** (yeni modül açma — mevcut kalibrasyon çekirdeğine enjekte et) |
| 4.3 | **Self-consistency k=5** | arXiv:2203.11171, **ICLR 2023** | k örnek + çoğunluk; örnekler arası **uyuşmazlık = belirsizlik** | `llm_trade_review._ask_once` | **Şüpheyi doğrudan ölçer:** aynı snapshot 20 kez → çıktı entropisi; entropi ≈0 ise "sabit üretim" kanıtlanır. İkinci adım: uyuşmazlık → abstention | **P1** |
| 4.4 | **Judge pozisyon yanlılığı swap testi** | arXiv:2406.07791 (AACL-IJCNLP 2025) | Aynı içeriği A/B ve B/A sunup karar değişimini ölçer | `routers/llm_chat.py` OctoBot konsensüsü (`consensus_threshold=0.60`) | Permütasyonlu sunumda karar değişim yüzdesi >%20 ise konsensüs **kanıt değil** | **P1** (bağımlılık sıfır) |
| 4.5 | **Haber dedup + novelty** | `ekzhu/datasketch` ★2.980, MIT, push 2026-10-26 (MinHash LSH) | Tekrarlayan haberleri eler; `1 − max_jaccard(son 24s)` yenilik skoru | `forex_news*.py`, `opportunity_trades.news_effect`, `context_extras.compact_lines` | Benzersiz haber oranı; novelty ↔ ΔR korelasyonu | P2 |
| 4.6 | **Retrieval: BM25 + rerank** | `xhluca/bm25s` ★1.822, MIT, push 2026-11-02 (**numpy+numba, hafif**); reranker `FlagEmbedding` ★12.307 → **torch, ayrı servis** | Bağlam seçimini skor tabanlı yapar (şu an bloklar sabit) | `context_extras.py` | Bağlam isabeti, prompt token, ΔR | P2 (reranker P3) |
| 4.7 | **Maliyet: prompt caching + batch + yönlendirme** | OpenAI Batch (doğrulanmış: %50 indirim, 24 saat pencere → **yalnız gece eval**); `BerriAI/litellm` ★62.997 (lisans SPDX tanınmıyor → kontrol et) | Tekrarlı promptta input maliyeti düşer; çok sağlayıcıyı tek noktada toplar | `llm_analysis.py` | $/1000 değerlendirme metriği panelde görünür olur | P2 |

**Elenenler:** `TauricResearch/TradingAgents` (★121.636 — kendi README'si getiri garantisini reddediyor; yalnız harness fikri) · `virattt/ai-hedge-fund` (★64.602, "proof of concept, gerçek işlem yapmaz") · `FinMem`/`FinAgent` (2024'te durdu) · `RouteLLM` (2024-08, terk) · Çince finansal olay çıkarımı repoları (CFEED/Doc2EDAG — İngilizce FX'te kullanılamaz) · `HKUDS/Vibe-Trading` (LLM trader hype'ı, çıkış/pozisyon kanıtı yok).

---

## 5) Önerilen uygulama sırası (her adım tek başına ölçülebilir)

| Sıra | İş | Neden bu sırada | Başarı ölçütü (kabul kapısı) |
|---|---|---|---|
| 1 | **İntrabar belirsizlik bandı + swap maliyeti** (§2.5) | Diğer tüm A/B'lerin güvenilirliği buna bağlı | Aynı 276 işlem: SL-first/TP-first PF bandı raporlanır; swap `cost_r`'ye eklenir |
| 2 | **1:1 falsifikasyon testi** (§2.3) | Giriş kalitesinin tavanını 1 koşuda söyler | 1R isabet + Wilson alt sınırı; < %50 → strateji seti değişimi gündeme gelir |
| 3 | **SL mesafesi A/B (1.5/3/5 ATR) + vol-hedefli lot** (§2.1-2.2) | Kök neden açığının (11 puan) doğrudan adresi | OOS pencerede PF ve maxDD birlikte iyileşmeli (biri bozulursa reddet) |
| 4 | **LLM: şemalı çıktı + sözel güven + self-consistency** (§4.1-4.3) | %16 parse hatası ve "sabit üretim" şüphesi aynı turda kapanır | Parse hatası <%2; ECE ölçülür; entropi testi kararı verir |
| 5 | **Judge swap testi** (§4.4) | Konsensüsün kanıt olup olmadığını belirler | Karar değişimi <%10 ise konsensüs kullanılabilir |
| 6 | **ML: meta-labeling + uniqueness ağırlığı + gap'li CV** (§3.1-3.3) | Aynı turda yapılmalı; üçü de CV varyansını hedefler | Bilinen-cevap testleri geçer + OOS skill > 0 |
| 7 | **river drift alarmı** (§3.4) | Kayma zaten ölçülüyor (CV negatif) | Sentetik alarm testi ±50 bar + gerçek veride alarmlı-retrain A/B |

---

## 6) Doğrulanmış kaynak tablosu (bu oturumda `gh api`)

| Repo | ★ | Son push | Lisans |
|---|---|---|---|
| freqtrade/freqtrade | 56.710 | 2026-11-09 | GPL-3.0 |
| QuantConnect/Lean | 22.466 | 2026-11-09 | Apache-2.0 |
| stefan-jansen/machine-learning-for-trading | 21.769 | 2026-11-06 | MIT |
| dottxt-ai/outlines | 16.006 | 2026-09-21 | Apache-2.0 |
| 567-labs/instructor | 14.100 | 2026-11-09 | MIT |
| virattt/ai-hedge-fund | 64.602 | 2026-11-09 | MIT |
| TauricResearch/TradingAgents | 121.636 | 2026-11-04 | Apache-2.0 |
| online-ml/river | 6.143 | 2026-11-09 | BSD-3-Clause |
| pst-group/pysystemtrade | 3.620 | 2026-11-02 | GPL-3.0 |
| ekzhu/datasketch | 2.980 | 2026-10-26 | MIT |
| xhluca/bm25s | 1.822 | 2026-11-02 | MIT |
| Leo4815162342/dukascopy-node | 960 | 2026-10-28 | MIT |
| esvhd/pypbo | 145 | 2026-07-06 | **AGPL-3.0** (kullanma: PBO zaten var) |
| hudson-and-thames/mlfinlab | 4.973 | **2023-10-02** | **NOASSERTION** (ticari yasak) |

**Terk edilmiş/bakımsız bulunanlar:** `mementum/backtrader` (2024-08), `pyalgotrade` (arşivli), `blankly` (2024-12), `mlfinlab` (2023-10), `sherpa`-benzeri ölü LLM-finans repoları (§4 elenenler).

---

## 7) YouTube kolunda bulunanlar (somut yöntem içerenler)

| Video / kanal | Tarih | Alınan somut yöntem | Doğrulama |
|---|---|---|---|
| Rob Carver — Systematic Investor Ep.226 | 2023-01-15 | Stop mesafesi tutma süresiyle hizalanmalı; 1.5 ATR fazla sıkı, 16/64 için ~7 ATR | Metin alıntısı (§2.1) |
| Rob Carver — "3 ways traders kill their trading strategies" | — | 7:20 maliyet küçümseme, 14:00 çok parametre | Bölüm işaretleri |
| Rob Carver — Systematic Investor Ep.375 | — | 57:01 "günlük trade ediyorsan tick şart değil" → tick yatırımı kararı için girdi | Bölüm işaretleri |
| Kevin Davey — Better System Trader #162 | — | n-bar exit ile girişi izole etme | Bölüm işaretleri |
| Adam Grimes — trading techniques | — | 1:1 kâr/stop falsifikasyon testi | Transkript (kanal/tarih doğrulanamadı) |
| Stanford Online — CME295 L8 "LLM Evaluation" | 2025-12-02 | 33:44 structured outputs, 38:47 judge pozisyon/verbosity yanlılığı | Zaman damgaları |
| Hudson & Thames — Meta-Labeling serisi | 2022-10-19 / 2023-03-10 | Meta-labeling: kalibrasyon + pozisyon boyutlandırma | Başlık/tarih |
| Weaviate Podcast #119 (Outlines yazarları) | — | Logit düzeyinde kısıtlı çözümleme | Bölüm işaretleri |

---

## 8) Özet: iki hedefe en yüksek kaldıraç

1. **Kârlılık (A):** Kök neden geometri+maliyet. En yüksek kaldıraç sırası: **ölçüm bandı (§2.5) → 1:1 falsifikasyon (§2.3) → stop mesafesi (§2.1) + vol-hedefli lot (§2.2)**. Hiçbiri yeni kütüphane gerektirmez; hepsi replay A/B ile aynı gün ölçülebilir.
2. **LLM taraması (B):** Bugünkü kusurlar ölçülmüş (parse %16, veto ΔR −0.02, sabit çıktı şüphesi). En yüksek kaldıraç: **şemalı çıktı (§4.1) + sözel güven (§4.2) + self-consistency entropi testi (§4.3)**, ardından **judge swap testi (§4.4)**.
3. **Kural:** Yukarıdaki hiçbir sayı "kazanç" olarak sunulmaz; her madde kendi kabul kapısından geçmezse geri alınır.
