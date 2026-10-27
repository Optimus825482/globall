# Plan v2: Özgün (daha önce denenmemiş) strateji aileleri — BTC ve FX

Tarih: 2026-10-28 · Şube: main · Yöntem: subagent-driven · Önceki plan: `2026-10-28-btc-fx-yeni-stratejiler.md` (altyapı hazır: eklenti yükleyici, driver, doğrulama scripti).

## Spec (bağlayıcı)

**Amaç.** Bu depoda şimdiye kadar denenmiş klasik gösterge kombinasyonlarının (MACD/RSI/Stoch/BB/Keltner/Donchian/Supertrend/HMA/Vortex/UT Bot/ORB/NR7/pullback) DIŞINDA kalan, yapısal/istatistiksel fikirlere dayanan ÖZGÜN giriş kuralları tasarlayıp aynı altyapıda (replay motoru + eklenti + doğrulama) test etmek. Başarı ölçütü v1 ile aynı "robust kenar":
1. 14 hafta (21 Tem – 27 Eki 2026) PF ≥ 1.30, net > 0, ≥ 60 işlem.
2. İlk 7 hafta (21 Tem – 7 Eyl) VE son 7 hafta (8 Eyl – 27 Eki) ayrı ayrı net > 0.
3. Kayma stresinde (FX `--slip-pips 1`; BTC `--slip-pips 10`) PF ≥ 1.10.
4. Gün P&L ≤ −700 olan gün ≤ 2.
Günlük +500 USD hedefi ayrıca raporlanır.

**Altyapı (değiştirilmez):** `scripts/replay_strateji_gunluk.py` (eklenti arayüzü: `STRATEGIES = {ad: {series(bars_eng, closes)->dict, side(s, bars_eng, i)->int, sl_atr, tp_r, symbols, spread_min_mult}}`; `bars_eng` = `ha_supertrend_mt5_7d.Bar(t, open, high, low, close)`; wrapper `s["atr"]` ekler; değişken SL için `s["atr"][i]` sinyal barında ezilip `sl_atr=1.0` kullanılabilir), `scripts/replay_strateji_tarama.py`, `scripts/strateji_dogrulama.py`, `scripts/forex_replay_backtest.py`. Örnek eklentiler: `scripts/strategies/btc_aile.py`, `fx_aile.py` (ve testleri).

**Veri:** `outputs/replay_cache_xaubtc_{m5,m15}.json` (XAUUSD, BTCUSD), `outputs/replay_cache_fx21_{m15,m30}.json` (21 parite), spread `outputs/fx_spread_db_1m.json`. Eklenti, çapraz varlık/çapraz parite için bu JSON dosyalarını doğrudan okuyabilir (format `{SYM: [[ts_sn,o,h,l,c],...]}`); hizalama zaman damgasıyla ve YALNIZ `t ≤ bars[i].t` barlarıyla (look-ahead yok). Bar aralığı (tf) seri içinde medyan `t` farkından türetilir ve doğru önbellek dosyası seçilir.

**Global kısıtlar:** v1 ile aynı (look-ahead yok; eklenti dosyası tek, yardımcı dosya yok; her strateji ≥ 1 sinyal + ≥ 1 look-ahead testi, çapraz varlık okuyan stratejilerde look-ahead testi çapraz seriyi de keser; grid yok, tek sabit parametre seti; FX `spread_min_mult = 8.0`, M15/M30; BTC M5/M15; risk sistem varsayılanı; sonuç JSON commit edilmez; dürüst rapor). Her strateji docstring'inde "neden özgün / bu depoda neyin denenmediği" bir cümleyle yazılır.

## Task 1 — Özgün BTC ailesi (`scripts/strategies/btc_ozgun.py`, `symbols={"BTCUSD"}`, test `test_btc_ozgun.py`)

1. `btc_saat_profili` — Nedensel gün-içi mevsimsellik: her bar için son 20 işlem günündeki aynı UTC saat dilimine (saat başı, 24 kova) ait ortalama log-getiri ve t-istatistiği (ort/std×√n) hesaplanır (yalnız geçmiş günler). |t| ≥ 2.0 ve o saatin işareti ile aynı yönde, saat kovası başladığında (ilk bar) giriş; SL 1.5×ATR, TP 1.0R; kova başına 1 işlem.
2. `btc_likidite_supurme` — Likidite süpürme dönüşü: bar, son 20 barın en düşüğünü ≥ 0.2×ATR aşağı taşar (fitil) ve kapanış o seviyenin üstünde → BUY (ayna SELL); SL = süpürme ucunun 0.3×ATR altı (değişken SL, atr ezme tekniği), TP 2R.
3. `btc_xau_oncu` — Çapraz varlık öncüsü: XAUUSD'nin son 12 barlık log-getiri z-skoru (60 bar pencere) |z| ≥ 2.0 iken BTC'de aynı yönde giriş, yalnız BTC'nin kendi son 12 bar getirisi ters/düz işaretliyse (henüz tepki vermemiş); SL 1.5×ATR, TP 1.5R. XAU barları `outputs/replay_cache_xaubtc_{tf}.json` içinden, `t ≤ bars[i].t` ile hizalanır.
4. `btc_govde_yigini` — Mum anatomisi momentumu: ardışık 3 barın her birinde CLV = (C−L)/(H−L) ≥ 0.7 ve aralık bir öncekinden büyük (ateşleme) → 3. barın kapanışında BUY (ayna ≤ 0.3 SELL); SL = 3 barın en düşüğü (değişken SL), TP 2R; 10 bar içinde tekrar yok.
5. `btc_verimlilik_rejimi` — Kaufman verimlilik oranı ER(20) rejim anahtarı: ER ≥ 0.6 → trend rejimi: EMA(20)'ye geri çekilip rejim yönünde kapanış → giriş; ER ≤ 0.2 → yatay rejim: fiyat 20-bar aralığının %10 ucunda ve kapanış içe dönerse ters yön; SL 1.5×ATR, TP 1.5R.
Koşum: `python scripts/replay_strateji_tarama.py --tur btc_ozgun --tfs m5,m15 --strategies <5 ad> --jobs 5 --symbols BTCUSD --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols"`. Rapor tablosu + yorum.

## Task 2 — Özgün FX ailesi (`scripts/strategies/fx_ozgun.py`, 8 parite EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF, GBPJPY, EURJPY, NZDUSD; `spread_min_mult=8.0`; test `test_fx_ozgun.py`)

1. `fx_seans_devri` — Seans devri momentumu: 07:00–09:00 UTC Londra hareketi ≥ 1.0×ATR(14) ve 09:00–13:00 geri çekilme hareketin %50'sini geçmediyse, 13:00 UTC'de (ilk bar) Londra yönünde giriş; SL 1.5×ATR, TP 2R; günde 1.
2. `fx_pdh_pdl_supurme` — Önceki gün yüksek/düşük süpürmesi: fiyat PDH'nin ≥ 0.1×ATR üstüne fitil atar, kapanış PDH altında → SELL (ayna PDL BUY); yalnız 07–20 UTC; SL = fitil ucu + 0.3×ATR (değişken SL), TP 1.5R. Gün sınırı UTC; önceki gün = kapanmış gün.
3. `fx_para_gucu` — Para birimi gücü teyidi: 21 parite önbelleğinden (`replay_cache_fx21_{tf}.json`) her para birimi için son 24 barlık ortalama log-getiri (parite yönüne göre işaretli) → güç puanı; işlem paritesinde taban para birimi en güçlü 2, karşı para birimi en zayıf 2 arasındaysa ve kendi 3-bar getirisi aynı yöndeyse BUY (ayna SELL); SL 2.0×ATR, TP 1.5R; 07–20 UTC; kova başına (saat) 1 giriş.
4. `fx_doji_kumesi` — Doji kümesi kırılımı: ardışık ≥ 3 bar gövde ≤ 0.3×aralık (küme), sonraki bar gövde ≥ 0.6×aralık ve kapanış küme yüksek/düşüğünün dışında → yön; SL = küme karşı ucu (değişken SL, en az 1.0×ATR), TP 2R; 07–20 UTC.
5. `fx_adr_tukenis` — ADR tükeniş: günün gerçekleşmiş aralığı ≥ 1.2×ADR(14) (ADR = önceki 14 kapanmış günün ortalama aralığı) ve kapanış günün ucunun 0.2×ATR içinde, bar ters renkli → ucun tersine giriş; hedef gün orta noktası (TP = |kapanış − orta|/SL oranı, 0.8–2.5 arasına kırpılır; `tp_r` sabit 1.0 kabul edilip SL ona göre ölçeklenebilir — implementer basit ve belgelenmiş bir yol seçer), SL = uc + 0.3×ATR; 07–20 UTC; günde yön başına 1.
Koşum: `--tur fx_ozgun --tfs m15,m30 --strategies <5 ad> --jobs 6 --symbols <8 parite> --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json"`. Rapor tablosu + yorum.

## Task 3 — Doğrulama ve rapor

`scripts/strateji_dogrulama.py`'yi yeniden kullan (gerekirse `--ozet` argümanlarıyla tur adlarını parametreleştir; script arayüzü v1 raporuyla uyumlu kalır). Ölçüt 1+2+4 adayları → kayma koşumu (`--tur dogrulama2_slip_*`) → ölçüt 3 → risk ölçekleme (2/5/10/20) → rapor `docs/OZGUN_STRATEJILER_2026_10_28.md` (bölümler v1 raporu gibi; ayrıca "özgünlük" sütunu: hangi fikir, depoda ilk kez). Aday yoksa açıkça yaz.
