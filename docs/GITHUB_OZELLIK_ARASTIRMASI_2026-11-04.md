# GitHub Özellik Araştırması: FOREX & SPOT Taramayı Güçlendirecek Ek Özellikler

**Tarih:** 2026-11-04 · **Kapsam:** GitHub'daki açık kaynak projeler taranarak mevcut sisteme eklenebilir özellik fikirleri
**Mevcut envanter:** MT5 köprüsü (forex.py, 11.8k satır) + Binance TR public REST (spot_monitor.py, 15 strateji), ccxt yok, vectorbt ölçüm disiplini, AI_GATE (ml_forecast), ekonomik takvim (TradingView+Investing), CSM/korelasyon/DXY veto, portfolio_risk + circuit_breaker, LLM katmanı, VAPID web-push (forex tarafı).

---

## P1 — Kısa vade (düşük maliyet, yüksek etki)

### 1. Spot'a push bildirimi (şu an yalnız polling)
- **Durum:** VAPID web-push altyapısı `alerting.py`/`vapid.py` ile forex tarafında VAR; spot-monitor 60 sn'de bir polling.
- **GitHub referansı:** [binwiederhier/ntfy](https://github.com/binwiederhier/ntfy) — self-hostable, HTTP POST ile anlık push; [ntfy topic](https://github.com/topics/ntfy)'de sinyal-alerter örnekleri var.
- **Yapılacak:** Var olan web-push boru hattını spot sinyallerine bağlamak en ucuz yol; ntfy ikincil/telefona ek kanal.

### 2. Vadeli piyasa bağlamı filtresi: OI + Funding + Likidasyon (spot yönü)
- **Kaynak (anahtarsız, public):** Binance Futures `fapi/v1/openInterest`, `premiumIndex` (funding), `!forceOrder@arr` WS (likidasyonlar). Ref: [sammchardy/python-binance](https://github.com/sammchardy/python-binance), [philipperemy/binance-futures](https://github.com/philipperemy/binance-futures), [ChadThackray/binance-liquidations-2022](https://github.com/ChadThackray/binance-liquidations-2022), [HuakunShen/binance-data-loader](https://github.com/HuakunShen/binance-data-loader) (Binance Vision tarihsel).
- **Kullanım:** OI↑+fiyat↑ = sağlıklı trend onayı; funding aşırısı = sıkışma uyarısı; likidasyon kaskadı = kapitülasyon → `cluc_wick_bounce` ile konfluans. AI_GATE'e ikinci bağımsız sinyal girdisi.
- **⚠️ Doğrulama şart:** Sunucudan `fapi.binance.com` erişilebilirliği (TR geo-kısıtı olabilir). Erişilemezse Bybit/OKX public alternatifi test edilmeli. ('opens' NameError dersi: canlı doğrulama olmadan entegre etme.)

### 3. FOREX backtest derinliği: Dukascopy ücretsiz tick verisi
- **Kaynak:** [dukascopy-python (PyPI)](https://pypi.org/project/dukascopy-python), [Praveens1234/dukascopy-downloader](https://github.com/Praveens1234/dukascopy-downloader), [keyhankamyar/TickVault](https://github.com/keyhankamyar/TickVault), [saleem-latif/duka-data](https://github.com/saleem-latif/duka-data) (M5→D1 OHLC **+ spread barları**), CLI tarafında [dukascopy-node](https://www.dukascopy-node.app).
- **Kullanım:** `forex_replay_backtest.py` şu an 7g; 20+ yıl tick ile derin walk-forward + spread-modeli. Strateji adayı testleri (FX dalga araştırmaları) için altın standart veri.

### 4. COT pozisyon verisi (forex kurumsal sentiment)
- **Kaynak:** [NDelventhal/cot_reports](https://github.com/NDelventhal/cot_reports) (CFTC COT), [cot-reports topic](https://github.com/topics/cot-reports), [cftc-cot-viewer](https://github.com/proprietary/cftc-cot-viewer).
- **Kullanım:** Haftalık kurumsal net pozisyon percentil'i → mevcut `USD bias` (forex.py:1327) ve `dxy_entry_veto`'ya ek girdi. Ekstrem pozisyonlama = ters dönüş uyarısı.

---

## P2 — Orta vade

### 5. Likidite süpürme / akıllı para stratejileri (iki pazar için de)
- **Kaynak:** [joshyattridge/smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts) — pip-installable: order block, FVG, BOS/CHoCH, likidite (equal highs/lows), swing yapısı. Ayrıca [SrsBlack/ict-knowledge-library](https://github.com/SrsBlack/ict-knowledge-library) (kavram referansı), [smart-money topic](https://github.com/topics/smart-money).
- **Kullanım:** FX'te `FVG_PULLBACK` zaten var → OB/CHoCH modülleri aynı desene eklenir. Spot'ta **liquidity sweep** adayı roster testine girer (vectorbt ölçümü, rastgeleden ayrışmazsa elenir — mevcut disiplin).
- **SMT diverjansı:** Mevcut korelasyon kalkanı (|ρ|≥0.85) SMT tespiti için altyapı — korele çiftlerin uyumsuz tepe/dibi tespiti veto/teyit olarak eklenebilir.

### 6. Meta-labeling ile AI_GATE güçlendirme
- **Kaynak:** [hudson-and-thames/mlfinlab (labeling.py)](https://github.com/hudson-and-thames/mlfinlab/blob/master/mlfinlab/labeling/labeling.py) (kısmen ücretli), [saleh-mir/triple-barrier](https://github.com/saleh-mir/triple-barrier), [triple-barrier topic](https://github.com/topics/triple-barrier), [H&T araştırma yazısı](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method).
- **Kullanım:** Strateji sinyali = birincil, ML = "bu sinyale girilsin mi" ikincil meta-etiket. Mevcut `ml_forward_test` + `ml_forecast` boru hattına bilimsel çerçeve; triple-barrier etiketleri TP/SL'ye birebir oturur.

### 7. Gerçek HMM rejim modeli
- **Durum:** `hmm_regime_classifier.py` kural-bazlı (dürüstçe belgelenmiş). `hmmlearn` ile gerçek fit + walk-forward; forex'te DXY veto, spot'ta BTC rejim kalkanını besler.

### 8. Volatilite tahmini (GARCH/HAR-RV)
- **Kaynak:** [ayk5511/volatility-forecasting](https://github.com/ayk5511/volatility-forecasting) (GARCH vs HAR yarışı), [chibui191/bitcoin_volatility_forecasting](https://github.com/chibui191/bitcoin_volatility_forecasting), `arch` paketi (QuantInsti tutorial'ları).
- **Kullanım:** GK+Parkinson realized vol yerine yarıdan fazlası: T+1 vol tahmini → TP/SL mesafesi ve pozisyon boyutu girdisi (`VOLATILITY_SIZING` config'i zaten var).

### 9. FinGPT haber skoru (FX)
- **Kaynak:** [ai4finance-foundation/fingpt](https://github.com/ai4finance-foundation/fingpt) — pretrained sentiment checkpoint'leri; [news-sentiment topic](https://github.com/topics/news-sentiment).
- **Durum:** `fingpt_sentiment.py` sözlük tabanlı → model checkpoint ile yükseltme; LLM altyapısı (`llm_analysis.py`) zaten var, ağırlık gerekmezse mevcut chat-LLM de skorlayıcı olabilir.

---

## P3 — Uzun vade / altyapı

### 10. REST → WebSocket geçişi (spot)
- **Kaynak:** [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed) — Binance dahil ~30 borsada normalize trades/book(L2/L3) akışı; [order-flow-imbalance topic](https://github.com/topics/order-flow-imbalance).
- **Kullanım:** 60 sn REST taramasının yanına gerçek-zamanlı book imbalance + aggTrades CVD; `buy_flow_dominance`/`cvd_absorption_wick` stratejileri kline-delta'dan gerçek akışa yükselir.

### 11. On-chain / balina akışı (spot)
- **Kaynak:** [ErcinDedeoglu/crypto-market-data](https://github.com/ErcinDedeoglu/crypto-market-data) (ücretsiz on-chain+derivatif veri indeksi), [Whale-Tracker-Analytics](https://github.com/HyperIllusionistTap/Whale-Tracker-Analytics), [Whale Alert free tier](https://whale-alert.io).
- **Kullanım:** Borsa girişi/çıkışı → BTC rejim kalkanına ek bağlam. Düşük öncelik: gürültü yüksek, sinyal zamanlaması zayıf.

### 12. Freqtrade'in koruma kataloğu (referans mimari)
- **Kaynak:** [freqtrade](https://github.com/freqtrade/freqtrade) — Protections ([docs](https://www.freqtrade.io/en/2021.9/includes/protections)): StoplossGuard, MaxDrawdown, CooldownPeriod, LowProfitPairs; Hyperopt; Telegram kontrol; FreqAI.
- **Kullanım:** Mevcut `circuit_breaker.py` + `loss_streak` + kill-switch'e **MaxDrawdown-bazlı global koruma** eklenebilir; Telegram kontrol paneli fikri (komutla tarama/durdurma) roadmap'e alınabilir.

### 13. TA kütüphanesi modernizasyonu (bilgi notu)
- **Durum:** Orijinal pandas-ta 2025 ortasında kaldırıldı ([topluluk](https://www.reddit.com/r/algotrading/comments/1ldm0kb/what_happened_to_pandasta_python_package)). Devam eden fork'lar: [pandas-ta-openbb](https://pypi.org/project/pandas-ta-openbb) (OpenBB bakımı), [xgboosted/pandas-ta-classic](https://github.com/xgboosted/pandas-ta-classic) (224 gösterge+62 formasyon, TA-Lib'siz), [bukosabino/ta](https://github.com/bukosabino/ta).
- **Kullanım:** Göstergeler şu an elle yazılı (forex.py) — bağımlılık eklemek yerine yalnızca yeni gösterge ihtiyacında referans/clean-room kaynak olarak kullanılır.

### 14. Strateji adayı havuzu
- **Kaynak:** [marketcalls/vectorbt-backtesting-skills](https://github.com/marketcalls/vectorbt-backtesting-skills) (vectorbt uyumlu strateji koleksiyonu), [polakowo/vectorbt](https://github.com/polakowo/vectorbt) + [resources](https://vectorbt.dev/getting-started/resources), [backtesting topic](https://github.com/topics/backtesting).
- **Kullanım:** Silinen 7 strateji dersini hatırla: aday havuzu genişletilir ama hepsi vectorbt + OOS elemesinden geçer.

---

## Öncelik Özeti

| # | Özellik | Pazar | Maliyet | Etki | Ön koşul/risk |
|---|---|---|---|---|---|
| 1 | Spot push bildirimi (VAPID/ntfy) | Spot | Çok düşük | Bildirim gecikmesi 60sn→anlık | Yok |
| 2 | OI+Funding+Likidasyon bağlamı | Spot | Düşük | Yön teyidi + kapitülasyon konfluansı | fapi erişim doğrulaması |
| 3 | Dukascopy tick backtest | Forex | Düşük | Replay'i 7g→yıllara taşır | İndirme rate-limit |
| 4 | COT pozisyon girdisi | Forex | Düşük | USD bias'a haftalık kurumsal bağlam | Haftalık gecikme |
| 5 | SMC/likidite sweep stratejisi | Her ikisi | Orta | Yeni strateji adayları | vectorbt eleme disiplini |
| 6 | Meta-labeling (AI_GATE) | Her ikisi | Orta | Gate'i bilimselleştirir | Overfit riski |
| 7 | Gerçek HMM rejim | Her ikisi | Orta | Kural-bazlıdan gerçek modele | Fit kalitesi |
| 8 | GARCH/HAR vol tahmini | Her ikisi | Orta | TP/SL + sizing girdisi | — |
| 9 | FinGPT haber skoru | Forex | Orta | Takvim ötesi haber akışı | Model/LLM maliyeti |
| 10 | WebSocket (cryptofeed) | Spot | Yüksek | Latency + gerçek order flow | Mimari değişiklik |

## Genel Uyarılar
- Binance TR spot REST kullanılıyor; global Binance (özellikle fapi) TR'den erişim engelli olabilir — her yeni veri kaynağı sunucudan canlı doğrulanmalı.
- ML tabanlı önerilerde (6,7,8,9) mevcut OOS/kill-kriteri (PF<1.0) disiplini aynen uygulanmalı; overfit = 'opens' NameError'dan daha pahalı hata.
- Myfxbook retail sentiment gibi resmi API'si olmayan kaynaklar scraping gri alanı — önerilmedi.

## Kaynaklar
- https://github.com/binwiederhier/ntfy · https://github.com/topics/ntfy
- https://github.com/sammchardy/python-binance · https://github.com/philipperemy/binance-futures · https://github.com/ChadThackray/binance-liquidations-2022 · https://github.com/HuakunShen/binance-data-loader
- https://pypi.org/project/dukascopy-python · https://github.com/Praveens1234/dukascopy-downloader · https://github.com/keyhankamyar/TickVault · https://github.com/saleem-latif/duka-data · https://www.dukascopy-node.app
- https://github.com/NDelventhal/cot_reports · https://github.com/topics/cot-reports · https://github.com/proprietary/cftc-cot-viewer
- https://github.com/joshyattridge/smart-money-concepts · https://github.com/SrsBlack/ict-knowledge-library · https://github.com/topics/smart-money
- https://github.com/hudson-and-thames/mlfinlab · https://github.com/saleh-mir/triple-barrier · https://github.com/topics/triple-barrier · https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method
- https://github.com/ayk5511/volatility-forecasting · https://github.com/chibui191/bitcoin_volatility_forecasting
- https://github.com/ai4finance-foundation/fingpt · https://github.com/topics/news-sentiment
- https://github.com/bmoscon/cryptofeed · https://github.com/topics/order-flow-imbalance
- https://github.com/ErcinDedeoglu/crypto-market-data · https://github.com/HyperIllusionistTap/Whale-Tracker-Analytics · https://whale-alert.io
- https://github.com/freqtrade/freqtrade · https://www.freqtrade.io/en/2021.9/includes/protections
- https://pypi.org/project/pandas-ta-openbb · https://github.com/xgboosted/pandas-ta-classic · https://github.com/bukosabino/ta
- https://github.com/marketcalls/vectorbt-backtesting-skills · https://github.com/polakowo/vectorbt · https://vectorbt.dev/getting-started/resources
- https://github.com/wilsonfreitas/awesome-quant
