# Özgün BTC ve FX strateji aileleri (v2): robust kenar doğrulaması (2026-10-28)

Kapsam: v2 planının 5 özgün BTC stratejisi x M5/M15 (10 hücre) ve 5 özgün FX stratejisi x M15/M30 x 8 parite (80 hücre), toplam 90 hücre. Ölçütler v1 raporuyla (`docs/BTC_FX_YENI_STRATEJILER_2026_10_28.md`) aynıdır; değiştirilmedi. Script: `scripts/strateji_dogrulama.py` (ham çıktı: `outputs/replay_strateji/dogrulama_v2.json`, commit edilmez).

## 1. Kısa sonuç

- **Robust kenar bulunamadı: 0 / 90 hücre. Aday (ölçüt 1+2+4) sayısı da 0.** Ölçüt 1'i (PF >= 1.30, net > 0, >= 60 işlem) geçen tek hücre `fx_para_gucu` M15 GBPJPY (91 işlem, PF 1.42, net +79.6 USD); ilk 7 hafta -19.9 USD olduğu için ölçüt 2'de düşüyor, 1 pip kaymada da PF 0.77'ye çöküyor.
- **Günlük +%50 (1000 USD tabanda +500 USD/gün) hedefi hiçbir yerde tutmadı.** Taban riskte (FX %5, BTC %2) 90 hücrenin hepsinde hedef gün sayısı 0 ve iflas günü (<= -700) sayısı 0. Tüm hücrelerdeki en iyi tek gün: BTC +76.5 USD (`btc_likidite_supurme` M5), FX +88.8 USD (`fx_para_gucu` M30 USDCAD). >= 60 işlemli hücrelerde işlem günü ortalamasının en iyisi +2.05 USD/gün (`fx_para_gucu` M15 USDCAD).
- Ölçüt 2'yi 15 hücre geçiyor ama 13'ü < 60 işlemli (çoğu 3-7 işlem), yani örneklem olarak anlamsız; >= 60 işlemli ve iki yarısı da pozitif olan yalnız iki hücre var: `btc_xau_oncu` M5 (148 işlem, PF 1.17) ve `btc_verimlilik_rejimi` M15 (77 işlem, PF 1.16). İkisi de PF eşiğinin altında ve 10 USD kaymada PF 0.61 / 0.71'e çöküyor.
- **`fx_adr_tukenis` yalnızca 3 işlem üretti: "kenar yok" değil, "değerlendirilemez".** Aday sayılmadı. `btc_saat_profili` (15-29 işlem/tf) ve `fx_seans_devri` (37 işlem/tf) de çok seyrek kaldı.
- Sonuç v1 ile aynı: özgün fikirler de (saat mevsimselliği, stop avı, çapraz varlık öncüsü, para gücü, mum anatomisi, verimlilik rejimi) bu veri ve motor altında robust kenar üretmedi.

## 2. Düzen

- **Veri:** MT5 mum önbelleği. FX: `outputs/replay_cache_fx21_{m15,m30}.json` (~2026-06-21 .. 2026-10-27), spread: `outputs/fx_spread_db_1m.json`. BTC: `outputs/replay_cache_xaubtc_{m5,m15}.json` (2026-06-20 .. 2026-10-28; `btc_xau_oncu` XAUUSD'yi aynı dosyalardan okur). Değerlendirme penceresi 14 hafta: 2026-07-21 .. 2026-10-27 (öncesi ısınma).
- **Motor:** `scripts/replay_strateji_gunluk.py`, canlı motor kapılarıyla (min_score, rr_floor, headroom, ADX >= 20, QUALITY, spread kapısı vb.). Her hücre ayrı süreç ve ayrı 1000 USD defter. Eklentiler `scripts/strategies/btc_ozgun.py` ve `fx_ozgun.py`; parametre ayarı/grid yok (tek sabit set); testler ve look-ahead denetimleriyle birlikte commit edildi (`890b371a`, `cdfcf81b`).
- **Risk:** Günlük P&L sabit 1000 USD tabanda; sistem riski FX %5, BTC %2. Hedef gün = günlük net >= +500 USD, "iflas" günü = <= -700 USD.
- **Ölçütler (bağlayıcı):**
  1. 14 hafta PF >= 1.30, net > 0, >= 60 işlem.
  2. İlk 7 hafta (07-21 .. 09-07) ve son 7 hafta (09-08 .. 10-27) ayrı ayrı net > 0.
  3. Kayma stresinde PF >= 1.10 (FX `--slip-pips 1`, BTC `--slip-pips 10`); kayma koşumunda işlem > 0 ve taban işlem sayısının >= %50'si olmalı.
  4. İflas günü sayısı <= 2.

  Aday = 1+2+4 (kayma koşumundan önce); robust = 1+2+3+4. Net / ilk 7h / son 7h değerleri `gun_*.json` içindeki `daily` alanından hesaplandı.
- **Hücre notları (kontrolör kararları):**
  - `fx_adr_tukenis`, brief'ten sapıyor: "uç" günün en yüksek/en düşük **kapanışı** alındı ve TP mesafesi orta nokta mesafesine kırpıldı (brief'in harfi harfine okunuşu 8 pariteyi M15'te tararken yalnız 1 sinyal veriyor). Sonuç 3 işlem (M15 2, M30 1): **değerlendirilemez**, aday değildir.
  - `btc_saat_profili`: sinyal kovanın ilk barında üretilir, motor girişi sinyal barının kapanışından sonraki barın açılışında yaptığı için giriş kovanın **2. barının** açılışına denk gelir; sonuçlar bu zamanlamayla okunmalıdır.
  - **İşlem sayıları motor kapılarıyla ciddi ölçüde azalıyor** (düzeltilmedi): BTC'de ham sinyallerin %70-90'ı elendi (örn. `btc_likidite_supurme` M5: 2047 sinyal -> 236 işlem); FX'te 14 hafta / 8 parite toplamında `fx_para_gucu` M15 2043 sinyal -> 564 işlem, `fx_adr_tukenis` 45 -> 2. Dolayısıyla sonuç, "stratejinin kendi kenarı" ile "motor filtreleri" karışık bir ölçümdür.
- **Özgünlük (eklenti docstring'lerinden; "bu depoda ilk kez" ne denendi):**

| Strateji | Fikir | Özgünlük (bu depoda) |
|---|---|---|
| btc_saat_profili | Aynı UTC saatin önceki 20 gününün kova getirisi t-istatistiği \|t\| >= 2 ise o işaretle kova başında giriş | Gün-içi mevsimsellik / zaman-kovası istatistiği hiç denenmemişti; yalnız fiyat/gösterge koşulları vardı |
| btc_likidite_supurme | Son 20 barın dibini >= 0.2 ATR fitille süpürüp üstünde kapanış (ayna SELL); SL süpürme ucunun ötesi, TP 2R | Stop avı / likidite süpürme (fitil reddi) yoktu; yalnız kırılım takibi ve aşırı bölge dönüşleri vardı |
| btc_xau_oncu | XAUUSD 12 bar log-getiri z-skoru \|z\| >= 2 iken BTC henüz tepki vermediyse aynı yönde giriş | Çok varlıklı (lead-lag) giriş yoktu; tüm stratejiler tek sembolün kendi barlarına bakıyordu |
| btc_govde_yigini | 3 ardışık barda CLV >= 0.7 (ayna <= 0.3) ve genişleyen aralık, 3. bar kapanışında giriş | Mum-içi kapanış konumu (CLV) / mum anatomisi hiç kullanılmamıştı |
| btc_verimlilik_rejimi | Kaufman ER(20) ile rejim anahtarı: ER >= 0.6 trendde EMA20 geri çekilme, ER <= 0.2 yatayda aralık ucundan dönüş | Fiyat-yolu verimliliğiyle iki zıt mantık arasında otomatik seçim yoktu; ADX tek yönlü kapıydı |
| fx_seans_devri | Londra hareketi >= 1 ATR ve New York öncesi geri çekilme <= %50 ise 13:00 UTC'de Londra yönünde giriş | İki seans arası yön devri / seans-içi momentum sürekliliği ilk kez; mevcut seans mantığı tek seansın kendi aralık kırılımıydı (Londra aralığı, ORB) |
| fx_pdh_pdl_supurme | Önceki gün yüksek/düşüğünün (PDH/PDL) >= 0.1 ATR ötesine fitil atıp geri kapanış, ters yönde giriş; SL fitil ucu + 0.3 ATR | Önceki gün seviyesi hiç kullanılmamıştı; PDH/PDL stop avı / sahte kırılım olarak ilk kez ele alındı |
| fx_para_gucu | 21 pariteden her para biriminin son 24 bar ortalama log-getirisiyle güç sıralaması; baz en güçlü 2, karşı en zayıf 2 arasındaysa ve kendi 3 bar getirisi aynı yöndeyse giriş | Çok pariteli (çapraz piyasa) para birimi gücü ilk kez; stratejiler yalnız işlem paritesine bakıyordu |
| fx_doji_kumesi | Art arda >= 3 küçük gövdeli bar (kararsızlık kümesi), ardından küme dışında kapanan güçlü gövdeli bar yönünde giriş | Mum-içi gövde/aralık oranı ilk kez; daralma yalnız NR7 / BB genişliği gibi aralık büyüklüğüyle aranmıştı |
| fx_adr_tukenis | Günün aralığı >= 1.2 x ADR(14) iken gün ucunda ters renkli bar -> ucun tersine giriş, hedef gün orta noktası | Günlük ortalama aralık (ADR) tükenmesi / gün-içi aşırı uzama giriş koşulu olarak ilk kez; günlük veri yalnız trend filtresiydi (günlük EMA) |

## 3. BTC tablosu (10 hücre, BTCUSD)

| Strateji | TF | İşlem | PF | Net 14h | İlk 7h | Son 7h | İflas gün | Hedef gün | Ölçüt 1 | Ölçüt 2 |
|---|---|---|---|---|---|---|---|---|---|---|
| btc_govde_yigini | m15 | 6 | 1.35 | +7.0 | +7.0 | +0.0 | 0 | 0 | H | H |
| btc_govde_yigini | m5 | 26 | 1.11 | +6.9 | +5.7 | +1.2 | 0 | 0 | H | E |
| btc_likidite_supurme | m15 | 45 | 1.44 | +93.2 | +5.1 | +88.1 | 0 | 0 | H | E |
| btc_likidite_supurme | m5 | 236 | 0.71 | -587.9 | -544.3 | -43.6 | 0 | 0 | H | H |
| btc_saat_profili | m15 | 15 | 2.43 | +31.9 | -7.2 | +39.1 | 0 | 0 | H | H |
| btc_saat_profili | m5 | 29 | 0.44 | -82.0 | -28.6 | -53.4 | 0 | 0 | H | H |
| btc_verimlilik_rejimi | m15 | 77 | 1.16 | +47.5 | +28.3 | +19.2 | 0 | 0 | H | E |
| btc_verimlilik_rejimi | m5 | 307 | 0.82 | -294.8 | -433.4 | +138.5 | 0 | 0 | H | H |
| btc_xau_oncu | m15 | 20 | 1.94 | +58.7 | +35.7 | +23.1 | 0 | 0 | H | E |
| btc_xau_oncu | m5 | 148 | 1.17 | +89.2 | +44.7 | +44.6 | 0 | 0 | H | E |

Ölçüt 4 tüm BTC hücrelerinde geçiyor (iflas günü yok; küçük pozisyon). Ölçüt 1'i hiçbir BTC hücresi geçmiyor: PF >= 1.3 olanlar (`btc_govde_yigini`, `btc_likidite_supurme`, `btc_saat_profili`, `btc_xau_oncu`; hepsi M15) 6-45 işlemle 60 işlemin çok altında; >= 60 işlemli hücrelerin hiçbiri PF 1.30'a ulaşmıyor (en iyisi `btc_xau_oncu` M5, PF 1.17). Tablodaki örüntü: M15 hücreleri pozitif ama çok küçük örneklemli; M5'te (daha çok işlem) aynı fikirler zayıflıyor veya tersine dönüyor (`btc_likidite_supurme` M5 -587.9, `btc_verimlilik_rejimi` M5 -294.8, `btc_saat_profili` M5 -82.0; 5 M5 hücresinin 3'ü negatif). Nedeni (maliyet mi, gürültü mü) ayrıştırılmadı.

## 4. FX tablosu (80 hücre)

Hücre = net 14 hafta (USD) / PF / işlem. `-` = işlem yok. `†` = ölçüt 1 geçti (aday değil: ölçüt 2 başarısız), `‡` = ölçüt 2 geçti (ölçüt 1 değil; çoğu < 10 işlem, anlamsız örneklem). Hiçbir hücre aday (ölçüt 1+2+4) değil. PF `inf` = zararlı işlem yok (az işlem).

**M15**

| Strateji | EURUSD | GBPUSD | USDJPY | USDCAD | USDCHF | GBPJPY | EURJPY | NZDUSD |
|---|---|---|---|---|---|---|---|---|
| fx_seans_devri | - | -27 / 0.42 / 8 | +17 / 2.08 / 6‡ | -42 / 0.31 / 6 | - | +9 / 1.28 / 7 | +22 / 1.73 / 10 | - |
| fx_pdh_pdl_supurme | -8 / 0.48 / 6 | -71 / 0.85 / 78 | +13 / 1.10 / 39 | +235 / 2.09 / 56‡ | -76 / 0.31 / 14 | +59 / 1.53 / 39‡ | -23 / 0.87 / 55 | -32 / 0.00 / 2 |
| fx_para_gucu | -82 / 0.27 / 13 | -16 / 0.96 / 103 | -57 / 0.88 / 124 | +84 / 1.25 / 94 | -292 / 0.34 / 62 | +80 / 1.42 / 91† | -130 / 0.62 / 77 | - |
| fx_doji_kumesi | -24 / 0.22 / 5 | -45 / 0.38 / 15 | -56 / 0.08 / 6 | +2 / 1.03 / 14 | -11 / 0.28 / 3 | -8 / 0.73 / 12 | +40 / inf / 6‡ | +2 / inf / 1 |
| fx_adr_tukenis | - | - | - | +15 / inf / 1 | - | +3 / inf / 1 | - | - |

**M30**

| Strateji | EURUSD | GBPUSD | USDJPY | USDCAD | USDCHF | GBPJPY | EURJPY | NZDUSD |
|---|---|---|---|---|---|---|---|---|
| fx_seans_devri | -31 / 0.00 / 2 | +31 / 3.12 / 7‡ | +34 / 3.35 / 6 | +9 / 1.15 / 8 | +8 / inf / 2 | +45 / 3.88 / 7 | -22 / 0.32 / 5 | - |
| fx_pdh_pdl_supurme | -32 / 0.32 / 11 | -135 / 0.58 / 50 | +72 / 1.94 / 28‡ | +76 / 1.45 / 44 | -61 / 0.52 / 19 | +22 / 1.20 / 32 | -16 / 0.91 / 41 | -10 / 0.68 / 3 |
| fx_para_gucu | -32 / 0.66 / 19 | +60 / 1.28 / 67 | -92 / 0.62 / 55 | +51 / 1.21 / 58‡ | -183 / 0.51 / 63 | -27 / 0.86 / 67 | +27 / 1.25 / 40 | -13 / 0.19 / 3 |
| fx_doji_kumesi | +5 / inf / 3‡ | -4 / 0.76 / 7 | +3 / inf / 2 | +33 / 2.07 / 6‡ | -23 / 0.30 / 4 | +6 / inf / 4‡ | +3 / inf / 2 | - |
| fx_adr_tukenis | - | - | - | +2 / inf / 1 | - | - | - | - |

Strateji x TF toplamları (8 parite, işlem / net USD): `fx_seans_devri` M15 37 / -20.7, M30 37 / +75.9; `fx_pdh_pdl_supurme` M15 289 / +96.9, M30 228 / -84.3; `fx_para_gucu` M15 564 / -413.5, M30 372 / -209.1; `fx_doji_kumesi` M15 62 / -100.2, M30 28 / +23.8; `fx_adr_tukenis` M15 2 / +17.6, M30 1 / +2.4. 80 hücrenin 30'unda net > 0. >= 60 işlemli 10 FX hücresinden yalnız üçünde net > 0 (`fx_para_gucu` M15 GBPJPY PF 1.42, M30 GBPUSD PF 1.28, M15 USDCAD PF 1.25).

Notlar: `fx_para_gucu` en çok işlem üreten ve toplamda en çok kaybettiren aile (USDCHF -292 / -183, EURJPY -130). `fx_pdh_pdl_supurme` işlem sayısı yüksek ama toplam net ~0; USDCAD M15 (+235, PF 2.09) tek bir pariteye özgü ve diğer paritelerde işaret zıt. `fx_seans_devri` ve `fx_doji_kumesi` hücreleri 60 işlemin çok altında (en çok 15); M30'daki yüksek PF'ler (3.1-3.9) 6-8 işlemden gelir ve istatistiksel olarak boştur. `fx_adr_tukenis` 8 pariteden yalnız 2'sinde birer işlem verdi.

## 5. Aday listesi ve kayma stresi

**Aday (ölçüt 1+2+4) yok.** Bu nedenle kayma koşumu, PF'ye göre ilk 3 (>= 60 işlemli) hücre ile ölçüt 2'yi >= 60 işlemle geçen 2 BTC hücresi için "bilgi" olarak yapıldı. Aşağıdakiler **yalnız bilgi amaçlıdır, aday değildir**.

| Hücre | Rol | İşlem | PF | Net 14h | İlk 7h | Son 7h | Kayma işlem | Kayma PF | Kayma net | Ölçüt 3 | Sonuç |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fx_para_gucu M15 GBPJPY | bilgi (PF sırası 1, ölçüt 1) | 91 | 1.42 | +79.6 | -19.9 | +99.4 | 89 | 0.77 | -60.6 | HAYIR | ölçüt 2 ve 3 başarısız |
| fx_para_gucu M30 GBPUSD | bilgi (PF sırası 2) | 67 | 1.28 | +59.7 | -1.8 | +61.5 | 64 | 0.87 | -31.3 | HAYIR | ölçüt 1, 2, 3 başarısız |
| fx_para_gucu M15 USDCAD | bilgi (PF sırası 3) | 94 | 1.25 | +83.9 | +115.0 | -31.1 | 92 | 0.68 | -150.3 | HAYIR | ölçüt 1, 2, 3 başarısız |
| btc_xau_oncu M5 | bilgi (ölçüt 2, >= 60 işlem) | 148 | 1.17 | +89.2 | +44.7 | +44.6 | 148 | 0.61 | -298.0 | HAYIR | ölçüt 1 ve 3 başarısız |
| btc_verimlilik_rejimi M15 | bilgi (ölçüt 2, >= 60 işlem) | 77 | 1.16 | +47.5 | +28.3 | +19.2 | 76 | 0.71 | -106.0 | HAYIR | ölçüt 1 ve 3 başarısız |

Yorum: beş hücrenin beşi de maliyet stresinde PF 0.61-0.87'ye iniyor ve net negatife dönüyor. Kayma koşumlarında işlem sayıları taban değerlere çok yakın kaldığı için (>= %95) sonuç işlem elenmesinden değil, işlem başına küçük kenarın kayma maliyetini karşılayamamasından geliyor. 10 USD (BTC) ve 1 pip (FX) kayma modeli sabit bir varsayımdır.

## 6. Risk ölçekleme

Günlük P&L risk yüzdesiyle lineer ölçeklendi (FX taban %5, BTC taban %2). Hücre değerleri: hedef gün (>= +500) / iflas günü (<= -700), 14 hafta penceresinde. Lineer varsayım pozisyon boyutu yuvarlama, marjin ve ardışık kayıp etkilerini yok sayar. Tüm hücreler yalnız "bilgi" amaçlıdır (aday yok).

| Hücre | Risk %2 | %5 | %10 | %20 | %20'de 14h net (USD) | %20'de en iyi / en kötü gün |
|---|---|---|---|---|---|---|
| fx_para_gucu M15 GBPJPY | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | +318.2 | +104.8 / -67.1 |
| fx_para_gucu M30 GBPUSD | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | +238.6 | +214.6 / -115.0 |
| fx_para_gucu M15 USDCAD | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | +335.6 | +197.6 / -122.4 |
| btc_xau_oncu M5 | 0 / 0 | 0 / 0 | 0 / 0 | 1 / 0 | +892.5 | +612.7 / -530.1 |
| btc_verimlilik_rejimi M15 | 0 / 0 | 0 / 0 | 0 / 0 | 1 / 0 | +475.5 | +599.2 / -673.4 |

Okuma: üç FX hücresinde %20 riskte bile hedef gün 0. Tek hedef günler BTC'de %20 riskte (her biri 1 gün) ve yalnız kayma stresini geçemeyen hücrelerde; `btc_verimlilik_rejimi` M15'te %20 riskte en kötü gün (-673.4) iflas eşiğine (-700) çok yakın. İşlem günü ortalaması taban riskte +0.9..+2.1 USD/gün (1000 USD üzerinde ~%0.1-0.2); +500 USD/gün ortalamaya ulaşmak için yüzlerce kat risk gerekir. Kayma stresinde bu hücrelerin netleri negatif olduğundan risk artırmak zararı da büyütür.

## 7. Sınırlar

- **Tek rejim, 14 hafta:** Tüm veri 2026 Q3-Q4 tek dönemden; hiçbir hücre dış örneklem (farklı rejim/dönem) testi görmedi.
- **Çoklu karşılaştırma:** 90 hücre test edildi. Bu kadar hücrede şansla bazı hücrelerin PF >= 1.3 olması veya iki yarısının da pozitif çıkması beklenir; nitekim ölçüt 2'yi geçen 15 hücrenin 13'ü < 60 işlemli, ölçüt 1'i ise >= 60 işlemli 14 hücrenin yalnız biri geçti, ölçüt 3 bu kümeyi sıfıra indirdi. Bu nitel bir uyarıdır, bir şans oranı hesabı değildir (hücreler bağımsız da değil: aynı parite ve aynı fikir ailesi içinde korelasyon var). Sonuç "kenar yok" ile uyumludur; "kenar var ama kaçırıldı" kanıtı da yoktur.
- **Kapı etkileşimleri:** Motorun canlı kapıları (min_score, rr_floor, headroom, ADX >= 20, QUALITY, spread) ham sinyalleri ağır eliyor (bölüm 2). Özellikle karşı-trend / ortalamaya dönüş mantıkları (`fx_adr_tukenis`, `fx_doji_kumesi`, `btc_likidite_supurme`) bu kapılarla yapısal çelişebilir. Kapılar açılarak yeniden ölçüm yapılmadı.
- **Yüksek kazanma oranı, düşük PF:** BTC hücrelerinde WR %60-93 ama PF ~1; motorun BE/trailing/kısmi çıkış mantığı stratejilerin kendi R/ödül yapısını ezmiş olabilir. Doğrulanmadı.
- **Küçük örneklem:** Birçok hücre < 20 işlemli (BTC M15, `fx_seans_devri`, `fx_doji_kumesi`, `fx_adr_tukenis`); PF 2-4 ve `inf` değerleri tek bir kayıpla tersine döner.
- **Tasarım yorumları:** Brief belirsizlikleri sabit yorumlarla çözüldü (ER yatay rejim girişi, XAU z tabanı, CLV genişleme koşulu, ADR uç tanımı vb.); farklı bir yorum farklı sonuç verebilir, ayar yapmamak için değiştirilmedi.
- **Kayma modeli:** FX 1 pip, BTC 10 USD, her bacakta sabit; gerçek kayma (haber anı, düşük likidite) daha kötü olabilir.

## 8. Karar ve sonraki adım

1. **Hiçbir hücre canlıya veya paper'a alınmıyor.** Robust kenar sayısı 0, aday sayısı 0; günlük +%50 hedefi bu stratejilerle ulaşılabilir değil (işlem günü ortalaması taban riskte yaklaşık +0.1..+0.2%).
2. `fx_adr_tukenis` karara bağlanamıyor: motor kapılarıyla fiilen 3 işlem. Yeniden denenecekse önce eklenti başına kapı muafiyeti (kontrolör kararı) veya uç tanımı ele alınmalı; mevcut sonuç "veri yok"tur.
3. `fx_para_gucu` en çok işlem veren aile ama net negatif (M15 -413.5, M30 -209.1; 16 hücrenin 5'i pozitif). Tek ölçüt-1 hücresi (GBPJPY M15) pariteye özgüdür, M30'da negatiftir ve kaymada çöker; genel bir "para gücü" kenarı kanıtı değildir.
4. BTC tarafında `btc_xau_oncu` ve `btc_verimlilik_rejimi` pozitif ama PF 1.16-1.17 ve maliyete duyarlı. Tekrar denenecekse önce gerçek BTC spread/kayma ölçümü ve daha uzun veri (>= 12 ay, MT5 `ingest-rates`) gerekir; aynı ölçütler değiştirilmeden.
5. Negatif sonuç geçerli bir sonuçtur: v1 (74 hücre) ve v2 (90 hücre) birlikte 164 hücrelik tarama günlük +%50 hedefine dayanak olacak bir kenar üretmedi.

## 9. Yeniden üretim komutları

Önkoşul: önbellek dosyaları (`outputs/replay_cache_fx21_*.json`, `outputs/replay_cache_xaubtc_*.json`, `outputs/fx_spread_db_1m.json`) mevcut olmalı; `PYTHONIOENCODING=utf-8`. Sonuçlar `outputs/replay_strateji/` altına yazılır (commit edilmez).

Ana koşumlar (taban):

```
python scripts/replay_strateji_tarama.py --tur btc_ozgun --tfs m5,m15 --strategies btc_saat_profili,btc_likidite_supurme,btc_xau_oncu,btc_govde_yigini,btc_verimlilik_rejimi --jobs 5 --symbols BTCUSD --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols"

python scripts/replay_strateji_tarama.py --tur fx_ozgun --tfs m15,m30 --strategies fx_seans_devri,fx_pdh_pdl_supurme,fx_para_gucu,fx_doji_kumesi,fx_adr_tukenis --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,GBPJPY,EURJPY,NZDUSD --jobs 6 --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json"
```

Kayma koşumları (bilgi hücreleri):

```
python scripts/replay_strateji_tarama.py --tur dogrulama2_slip_fx_m15 --tfs m15 --strategies fx_para_gucu --symbols GBPJPY,USDCAD --jobs 4 --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json --slip-pips 1"
python scripts/replay_strateji_tarama.py --tur dogrulama2_slip_fx_m30 --tfs m30 --strategies fx_para_gucu --symbols GBPUSD --jobs 4 --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json --slip-pips 1"
python scripts/replay_strateji_tarama.py --tur dogrulama2_slip_btc_m5 --tfs m5 --strategies btc_xau_oncu --symbols BTCUSD --jobs 4 --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols --slip-pips 10"
python scripts/replay_strateji_tarama.py --tur dogrulama2_slip_btc_m15 --tfs m15 --strategies btc_verimlilik_rejimi --symbols BTCUSD --jobs 4 --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols --slip-pips 10"
```

İki aşamalı doğrulama (aşama 1: ölçüt 1, 2, 4 ve risk ölçekleme; aşama 2: kayma özetlerini birleştirir ve `dogrulama_v2.json`'u yeniden yazar):

```
python scripts/strateji_dogrulama.py --ozet outputs/replay_strateji/ozet_turbtc_ozgun.json outputs/replay_strateji/ozet_turfx_ozgun.json --out outputs/replay_strateji/dogrulama_v2.json --slip-tur-oneki dogrulama2_slip

python scripts/strateji_dogrulama.py --ozet outputs/replay_strateji/ozet_turbtc_ozgun.json outputs/replay_strateji/ozet_turfx_ozgun.json --out outputs/replay_strateji/dogrulama_v2.json --slip-tur-oneki dogrulama2_slip --slip-ozet outputs/replay_strateji/ozet_turdogrulama2_slip_fx_m15.json outputs/replay_strateji/ozet_turdogrulama2_slip_fx_m30.json outputs/replay_strateji/ozet_turdogrulama2_slip_btc_m5.json outputs/replay_strateji/ozet_turdogrulama2_slip_btc_m15.json

python scripts/strateji_dogrulama.py --selftest
```

Not: `--ozet`, `--out` ve `--slip-tur-oneki` bu rapor için eklendi; varsayılanlar v1 girdi/çıktılarını (`ozet_turbtc1.json`, `ozet_turfx_yeni.json`, `dogrulama.json`, `dogrulama_slip_*`) korur ve v1 aşama-1 çıktısı değişiklik öncesi ve sonrası birebir aynıdır. Aşama 1'in yazdırdığı kayma komutları yalnız script'in kendi seçtiği 3 "bilgi" hücresini kapsar; yukarıdaki komutlar PF'ye göre ilk 3 hücreyi de içerir (aşama 2'de kayma koşumu yapılmış her hücre "bilgi" olarak risk ölçeklemeye dahil edilir).
