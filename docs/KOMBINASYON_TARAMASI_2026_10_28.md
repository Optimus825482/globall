# Kombinasyon taraması v3 — rapor (2026-10-28)

Plan: `docs/superpowers/plans/2026-10-28-kombinasyon-taramasi-v3.md` · Kod: `scripts/kombo_tarama.py`, `scripts/kombo_secim.py`, `scripts/strategies/kombo.py`, `scripts/strateji_dogrulama.py` (v3 eklentileri), `scripts/replay_strateji_tarama.py` (`--start/--end`), `scripts/kombo_be_dolum_analizi.py` (bölüm 5–7).
Bu raporda kombolar **her zaman tam tanım dizesi + sembol/tf** ile anılır. `kombo_<n>` adları yalnız `outputs/kombo/kombo_tanimlar.json` numaralandırmasıdır. `outputs/kombo/secim.json` içindeki `kombo_1..3` **farklı** kombolardır, karıştırılmamalı.

## 1. Kısa sonuç

- Gerçek motorda 17 kombodan **7 hücre** beş ölçütün hepsini geçti. Bunlar **5 farklı sinyal setine** karşılık geliyor; XAUUSD m15 çifti ile EURJPY m15 çifti aynı sinyalin yalnız TP'si farklı varyantları. Setler birbirinden bağımsız değil: 3'ü XAUUSD m5'te, 4'ü XAUUSD'de. Hepsi XAUUSD (m5 ve m15) ve EURJPY m15 hücrelerinde; BTC'de hiçbir kombo geçmedi.
- **+500 USD/gün hedefi tutmuyor.** Sistem riskinde (XAU %10, FX %5) 14 haftada en iyi hücrenin hedef günü 2. Beş setin günlük toplamı da (yalnız gösterge niteliğinde) 76 günün 2'sinde hedefi aşıyor, holdout'ta hiç aşmıyor. %20 risk ile bile 14 haftada yalnız 7 gün.
- **Temiz holdout sonucu karışık; sonucu kısmen destekliyor.** Seçimde hiç kullanılmamış 21 Haz – 20 Tem 2026 penceresinde:
  - XAUUSD m5'teki üç hücre kaymalı koşumda da pozitif.
  - XAUUSD m15 çifti ile EURJPY m15 çifti negatif.
  - Örneklem küçük: XAU m5 dışındaki hücrelerde 7–21 işlem var.
- **XAU sonuçları motorun kâr kilidi ("BE") dolum modeline duyarlı.** Bu kilit, 14 haftada işlemlerin %47–93'ünü küçük kârla kapatıyor. Bağımlılık kötümser dolum testiyle ölçüldü (bölüm 5.2): stop çıkışının (SL veya BE) gerçekleştiği bar, o barın başında geçerli olan stop seviyesinin ötesinde açıldıysa (BUY: açılış < stop; SELL: açılış > stop), dolum stop fiyatı yerine o barın açılışından yapılır. Bu test altında 14 haftada iki XAU m5 hücresi (kombo_1 ve kombo_4) negatife dönüyor.
- **Karar:** Gerçek para yok. Yalnız XAUUSD m5 üçlüsü için düşük riskli (%2) demo ileri testi öneriliyor. Bu testin asıl amacı canlı kâr kilidi dolumlarını ölçmek (bölüm 9).

## 2. Yöntem

**İki aşamalı yöntem.**
1. **Hızlı tarama** (`kombo_tarama.py`). Sinyal önbelleği kullanılıyor; giriş i+1 açılışında, maliyet olarak spread + kayma, tek pozisyon, sembol başına izole 1000 USD defter.
   - Kombinasyon tipleri: `tek`, `or(a,b)`, `and(a,b,N∈{1,3,6})`, `sonra(a,b,N∈{3,6,12})`.
   - Dokuz filtre: `htf_ema200`, `seans_07_20/13_20/00_07`, `atr_yuksek/atr_dusuk`, `adx_ge20/ge25/lt20`.
   - 28 çıkış varyantı: sl_atr {1,1.5,2,3} × tp_r {1,1.5,2,3} × başabaş {yok, 1R}. tp ≤ 1R iken başabaş etkisiz olduğu için bu kopyalar elendi.
   - Kademeli tarama: aşama A tüm tabanları sl1.5/tp2.0 ile tarar. Aşama B ilk 200 tabanı {filtresiz + 9 filtre} × 28 çıkış ile tarar.
2. **Gerçek motor doğrulaması.** `scripts/strategies/kombo.py` eklentisi `replay_strateji_gunluk.py` → `forex_replay_backtest.py` üzerinden 14 hafta koşuyor. Motor kendi kapılarını, canlı BE/trailing/kısmi kâr mantığını ve `spread_min_mult` kuralını uyguluyor. Hızlı simülatördeki başabaş bayrağı motorda **etkisiz**, çünkü motor her zaman kendi BE'sini kullanıyor.

**Uzay büyüklüğü.** 20 hücre (BTCUSD/XAUUSD m5+m15, 8 FX paritesi m15+m30) × hücre başına yaklaşık 60,5–61,1 bin kombinasyon. Toplam **1 217 786** kombinasyon simüle edildi. Bunların 703 650'si en az 40 eğitim işlemi şartını karşılıyor.

**Walk-forward.** Sıralama yalnız eğitim penceresinde yapıldı (2026-07-21 – 09-07). Skor: PF × min(1, n/80), n ≥ 40. Her hücrenin eğitim ilk 20'si test penceresinde (09-08 – 10-27) **bir kez** okundu. Test verisine bakılarak hiçbir parametre değiştirilmedi.

**Seçim yanlılığı ölçüsü.**
- 20 hücre × ilk 20 = 400 satırın yalnız **19'u (%4,75)** testte PF ≥ 1,2 tuttu (hepsi ≥ 25 test işlemli).
- Medyan PF eğitimde 1,47, testte 0,72. Testte net > 0 olan satır 45/400.
- 14 hücrede tutunan satır yok; 16 FX hücresinden yalnız EURJPY m15 (4) ve EURUSD m15 (1) tutundu.

Bu tutunma oranı rastgele beklentiye yakın. Çoklu karşılaştırma uyarısı geçerli.

**Gerçek motor adayları.** 19 tutunan satırın hepsi doğrulamaya alındı; yerleşik bileşenli olanlar da dahil (kontrolör kararı, plan sapması). Dürüstlük notu: yerleşik bileşenli komboları dahil etme kararı, Task 2'nin test penceresi okunduktan **sonra** alındı (en iyi test hücreleri yerleşik bileşenliydi). Aynı kararla Task 2'deki taban başına en çok 2 varyant kapağı da kaldırıldı: kapakla 14 satır tutunuyordu, kapaksız 19; örneğin BTCUSD m15 `or(combo3_onay,btc_keltner_geri_htf)` tabanı 4 satırla girdi. Yani aday kümesinin kendisi test penceresine bakılarak genişletildi; bu, c5'in bağımsızlığını bir kat daha zayıflatıyor (bkz. bölüm 8). Yalnız başabaş bayrağında ayrışan iki çift motorda özdeş olduğu için **17 kombo** kaldı.

**Ölçütler (v1/v2 ile aynı + test):**

| Ölçüt | Koşul |
|---|---|
| c1 | 14 hafta PF ≥ 1,30, ≥ 60 işlem, net > 0 |
| c2 | iki 7 haftalık yarı ayrı ayrı > 0 |
| c3 | kayma stresinde PF ≥ 1,10 (XAU 2 pip, FX 1 pip, BTC 10 USD; her bacakta) |
| c4 | iflas günü (≤ −700 USD) ≤ 2 |
| c5 | motorun test penceresi (09-08 – 10-27) PF ≥ 1,2 |

## 3. Tarama özeti (hücre başına eğitim 1. kombo ve tutunanlar)

| Hücre | Eğitim 1. kombo (tam tanım) | Eğitim n/PF | Test n/PF/net | İlk 20'den testte PF ≥ 1,2 |
|---|---|---|---|---|
| BTCUSD m15 | `or(combo3_onay,btc_keltner_geri_htf)\|seans_07_20\|sl3.0_tp1.5` | 55/3,02 | 51/1,29/+132 | 6/20 |
| BTCUSD m5 | `sonra(vortex_adx,hma_ao,6)\|atr_yuksek\|sl3.0_tp3.0_be` | 88/2,19 | 99/0,73/−257 | 1/20 |
| EURJPY m15 | `or(psar_macd,btc_saat_profili)\|adx_ge20\|sl3.0_tp1.0` | 67/2,00 | 61/1,03/+43 | 4/20 |
| EURJPY m30 | `or(donch_vortex,btc_likidite_supurme)\|htf_ema200\|sl1.0_tp1.5` | 83/1,25 | 115/0,84/−603 | 0/20 |
| EURUSD m15 | `or(cmo_bb,psar_macd)\|adx_ge20\|sl2.0_tp2.0` | 78/1,09 | 82/0,70/−1031 | 1/20 |
| EURUSD m30 | `or(psar_macd,fx_ema200_rsi_geri)\|-\|sl1.5_tp2.0` | 65/1,31 | 71/0,54/−1467 | 0/20 |
| GBPJPY m15 | `or(btc_donchian55_trend,btc_likidite_supurme)\|adx_ge20\|sl1.5_tp3.0_be` | 93/1,67 | 98/0,28/−2222 | 0/20 |
| GBPJPY m30 | `or(ut_bot,btc_donchian55_trend)\|-\|sl1.5_tp3.0` | 53/1,83 | 76/0,43/−1945 | 0/20 |
| GBPUSD m15 | `or(fisher_st,btc_verimlilik_rejimi)\|adx_lt20\|sl3.0_tp1.0` | 43/2,66 | 38/0,82/−193 | 0/20 |
| GBPUSD m30 | `or(wpr_ema_trend,btc_saat_profili)\|atr_yuksek\|sl1.0_tp1.0` | 66/1,23 | 64/0,96/−63 | 0/20 |
| NZDUSD m15 | `or(coral_trend,btc_nr7_kirilim)\|-\|sl3.0_tp1.5` | 79/0,95 | 60/0,59/−940 | 0/20 |
| NZDUSD m30 | `and(vortex_adx,combo3,6)\|-\|sl1.5_tp3.0` | 73/1,06 | 86/0,46/−2329 | 0/20 |
| USDCAD m15 | `sonra(ut_bot,combo3,6)\|-\|sl3.0_tp2.0_be` | 63/2,13 | 72/0,78/−466 | 0/20 |
| USDCAD m30 | `or(coral_trend,combo3)\|adx_ge20\|sl2.0_tp2.0_be` | 76/1,30 | 105/0,47/−2092 | 0/20 |
| USDCHF m15 | `or(btc_saat_profili,fx_seans_devri)\|atr_dusuk\|sl3.0_tp1.0` | 44/2,75 | 45/0,60/−585 | 0/20 |
| USDCHF m30 | `or(ut_bot,btc_verimlilik_rejimi)\|seans_07_20\|sl1.5_tp3.0` | 78/1,04 | 60/0,64/−990 | 0/20 |
| USDJPY m15 | `or(vortex_adx,cmo_bb)\|-\|sl3.0_tp1.0` | 85/1,48 | 100/0,62/−1161 | 0/20 |
| USDJPY m30 | `or(psar_macd,fx_donchian_gunluk)\|-\|sl1.5_tp1.0` | 79/1,57 | 103/0,73/−822 | 0/20 |
| XAUUSD m15 | `sonra(btc_nr7_kirilim,combo3,6)\|atr_yuksek\|sl1.0_tp2.0_be` | 80/2,27 | 58/0,86/−425 | 3/20 |
| XAUUSD m5 | `sonra(ut_bot,combo3,12)\|seans_00_07\|sl3.0_tp3.0_be` | 87/2,19 | 102/1,47/+2158 | 4/20 |

Hızlı simülatörde XAU riski %10, FX %5, BTC %2. Eğitimdeki 1. kombo, testte tutunan tek kombo değil. Tutunan 19 satırın tamamı bölüm 4'te.

## 4. Gerçek motor doğrulaması (17 kombo)

Kaynak: `outputs/replay_strateji/dogrulama_v3.json`, `ozet_turkombo_v3_*.json`.

Kolonlar:
- **Hızlı:** kombo_tarama simülatörü.
- **Motor:** 14 hafta (07-21 – 10-27).
- **Test pencere:** motorun kapanan işlemlerinden 09-08 – 10-27.
- **Kayma:** c3 koşumu. "-" kayma koşumu yapılmadı demek (c1/c2 zaten geçmedi).
- E = geçti, H = geçmedi.

| Ad | Hücre | Tam tanım | Hızlı eğitim n/PF | Hızlı test n/PF | Motor 14h n/PF/net | İlk 7h / son 7h net | Kayma PF/net | Test pencere n/PF/net | c1 | c2 | c3 | c4 | c5 | Sonuç |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| kombo_1 | XAUUSD m5 | `sonra(ut_bot,combo3,12)\|seans_00_07\|sl3.0_tp3.0_be` | 87/2,19 | 102/1,47 | 421/2,33/+3390 | +847 / +2543 | 1,71/+2123 | 225/3,31/+2543 | E | E | E | E | E | **ROBUST** |
| kombo_2 | BTCUSD m15 | `or(combo3_onay,btc_keltner_geri_htf)\|seans_07_20\|sl3.0_tp1.5` (+1 eş satır: `…_be`) | 55/3,02 | 51/1,29 | 84/0,94/−16 | −33 / +16 | - | 37/1,16/+16 | H | H | - | E | H | geçmedi |
| kombo_3 | XAUUSD m5 | `or(btc_rsi2_bb_donus,btc_saat_profili)\|atr_dusuk\|sl1.0_tp3.0_be` | 60/2,75 | 47/1,42 | 49/4,68/+1922 | +1812 / +110 | - | 21/1,26/+110 | H | E | - | E | E | geçmedi (n < 60) |
| kombo_4 | XAUUSD m5 | `or(hma_ao,tsi_ema50)\|seans_13_20\|sl1.5_tp2.0` | 79/2,07 | 94/1,29 | 72/2,72/+876 | +344 / +532 | 1,85/+560 | 43/2,31/+532 | E | E | E | E | E | **ROBUST** |
| kombo_5 | XAUUSD m15 | `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp3.0_be` | 71/2,26 | 69/1,21 | 90/5,23/+1765 | +1213 / +552 | 4,71/+1616 | 42/6,45/+552 | E | E | E | E | E | **ROBUST** |
| kombo_6 | BTCUSD m15 | `or(tsi_ema50,combo3_onay)\|seans_07_20\|sl3.0_tp1.5` | 46/3,47 | 41/1,68 | 37/1,57/+57 | +38 / +19 | - | 15/1,46/+19 | H | E | - | E | E | geçmedi |
| kombo_7 | XAUUSD m15 | `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp2.0_be` | 80/1,96 | 74/1,38 | 90/4,74/+1560 | +1008 / +552 | 4,24/+1411 | 42/6,45/+552 | E | E | E | E | E | **ROBUST** |
| kombo_8 | BTCUSD m5 | `or(cmo_bb,btc_rsi2_bb_donus)\|atr_dusuk\|sl3.0_tp3.0` | 76/2,05 | 75/1,64 | 68/0,79/−58 | −94 / +36 | - | 29/1,56/+36 | H | H | - | E | E | geçmedi |
| kombo_9 | XAUUSD m5 | `sonra(btc_keltner_geri_htf,combo3,3)\|atr_yuksek\|sl2.0_tp1.0` | 73/2,07 | 94/1,24 | 74/5,04/+1236 | +805 / +431 | 3,16/+922 | 42/2,41/+431 | E | E | E | E | E | **ROBUST** |
| kombo_10 | XAUUSD m15 | `or(tsi_ema50,btc_donchian55_trend)\|-\|sl1.5_tp3.0_be` | 81/1,87 | 95/1,21 | 36/9,31/+839 | +732 / +107 | - | 21/2,06/+107 | H | E | - | E | E | geçmedi (n < 60) |
| kombo_11 | BTCUSD m15 | `or(combo3_onay,btc_keltner_geri_htf)\|-\|sl3.0_tp1.5_be` | 80/1,82 | 74/1,27 | 162/1,03/+12 | −1 / +13 | - | 69/1,07/+13 | H | H | - | E | H | geçmedi |
| kombo_12 | BTCUSD m15 | `or(combo3_onay,btc_keltner_geri_htf)\|seans_07_20\|sl2.0_tp2.0_be` | 79/1,66 | 79/1,21 | 84/1,08/+26 | +3 / +23 | 0,61/−151 | 37/1,20/+23 | H | E | H | E | H | geçmedi |
| kombo_13 | BTCUSD m15 | `or(stoch_kijun,combo3_onay)\|seans_07_20\|sl3.0_tp1.5_be` | 43/2,99 | 41/1,40 | 32/1,68/+53 | +15 / +37 | - | 11/2,89/+37 | H | E | - | E | E | geçmedi |
| kombo_14 | EURJPY m15 | `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.5_be` (+1 eş satır: `sl1.5_tp1.5`, BE'siz) | 81/1,48 | 82/1,39 | 62/3,97/+332 | +121 / +211 | 1,56/+118 | 31/5,40/+211 | E | E | E | E | E | **ROBUST** |
| kombo_15 | EURJPY m15 | `or(btc_saat_profili,fx_pdh_pdl_supurme)\|atr_dusuk\|sl1.5_tp2.0_be` | 70/1,50 | 64/1,55 | 54/2,78/+227 | +39 / +188 | - | 30/3,97/+188 | H | E | - | E | E | geçmedi (n < 60) |
| kombo_16 | EURJPY m15 | `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.0` | 86/1,30 | 88/1,70 | 62/3,92/+326 | +136 / +190 | 1,54/+113 | 31/4,96/+190 | E | E | E | E | E | **ROBUST** |
| kombo_17 | EURUSD m15 | `or(vortex_adx,btc_likidite_supurme)\|seans_07_20\|sl3.0_tp1.5` | 51/1,39 | 38/1,65 | 95/0,81/−75 | −30 / −45 | - | 63/0,83/−45 | H | H | - | E | H | geçmedi |

Kayma koşumunda test penceresi PF'leri: kombo_1 2,34; kombo_4 1,58; kombo_9 1,44; kombo_5 ve kombo_7 5,55; kombo_14 1,82; kombo_16 1,56.

Hızlı simülatör ile motor arasında işlem sayısı ve PF çok farklı. Örneğin XAUUSD m5 `sonra(ut_bot,combo3,12)|seans_00_07|sl3.0_tp3.0_be` için:

| Kaynak | Pencere | İşlem | PF |
|---|---|---|---|
| Hızlı simülatör | eğitim | 87 | 2,19 |
| Hızlı simülatör | test | 102 | 1,47 |
| Motor | 14 hafta | 421 | 2,33 |

Fark büyük olasılıkla motorun çıkış yönetiminden ve pullback giriş modundan geliyor. Motorun kısa tuttuğu işlemler tek pozisyon kuralı altında daha çok giriş fırsatı bırakıyor.

## 5. Çıkış-nedeni karışımı ve BE bağımlılığı

**Motordaki "BE" ne demek?** Gerçek başabaş değil, bir kâr kilidi.
- Fiyat lehte yaklaşık 1 USD + pay gördüğünde kilit devreye giriyor. Pay XAU'da 4 pip; tetik "union" kuralıyla belirleniyor.
- Stop, giriş + max(1 USD karşılığı, **0,40 × MFE**) seviyesine çekiliyor.
- Bu stopla kapanan işlem "BE" olarak etiketleniyor ve küçük kârla kapanıyor.
- "+trail": çıkış anında trailing etkindi.

Kaynak: `rep_tkombo_v3_*.json` kapanan işlemlerinin `reason` ve `trail` alanları. Koşum 14 hafta, kaymasız.

### 5.1 Tablo (14 hafta, robust hücreler)

| Ad / hücre / tanım | n | BE n / toplam | BE+trail n / toplam | TP (+trail) n / toplam | SL n / toplam | Diğer | BE payı (işlem) | BE'nin brüt kârdaki payı | BE dışı işlemlerin P&L toplamı (betimsel) | Medyan işlem | BUY n/PF/net | SELL n/PF/net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| kombo_1 XAUUSD m5 `sonra(ut_bot,combo3,12)\|seans_00_07\|sl3.0_tp3.0_be` | 421 | 352 / +2495 | 39 / +1952 | 5 / +1484 | 25 / −2542 | – | %92,9 | %75,0 | **−1057** | +5,8 | 217/2,13/+1824 | 204/2,69/+1566 |
| kombo_4 XAUUSD m5 `or(hma_ao,tsi_ema50)\|seans_13_20\|sl1.5_tp2.0` | 72 | 63 / +749 | 1 / +52 | 3 / +584 | 5 / −509 | – | %88,9 | %57,8 | +75 | +8,8 | 36/3,82/+567 | 36/2,00/+309 |
| kombo_9 XAUUSD m5 `sonra(btc_keltner_geri_htf,combo3,3)\|atr_yuksek\|sl2.0_tp1.0` | 74 | 59 / +677 | 5 / +169 | 7 / +696 | 3 / −306 | – | %86,5 | %54,9 | +390 | +10,6 | 38/3,98/+613 | 36/7,23/+623 |
| kombo_5 XAUUSD m15 `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp3.0_be` | 90 | 72 / +739 | 12 / +830 | 2 / +614 | 4 / −417 | – | %93,3 | %71,9 | +196 | +8,4 | 40/∞ (kayıpsız)/+1334 | 50/2,03/+431 |
| kombo_7 XAUUSD m15 `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp2.0_be` | 90 | 72 / +739 | 12 / +830 | 2 / +409 | 4 / −417 | – | %93,3 | %79,3 | **−9** | +8,4 | 40/∞/+1129 | 50/2,03/+431 |
| kombo_14 EURJPY m15 `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.5_be` | 62 | 40 / +137 | – | 14 / +306 | 7 / −111 | HAFTA_KAPANIS 1 / −1 | %64,5 | %31,0 | +194 | +3,5 | 42/2,00/+112 | 20/∞/+219 |
| kombo_16 EURJPY m15 `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.0` | 62 | 29 / +79 | – | 25 / +359 | 7 / −111 | HAFTA_KAPANIS 1 / −1 | %46,8 | %18,1 | +247 | +3,8 | 42/2,00/+112 | 20/∞/+214 |

Okuma:
- **XAU hücrelerinin profili "çok sık küçük kâr, seyrek tam kayıp".**
  - Kazanma oranı %93–96. Ortalama BE kârı +7…+12 USD, ortalama SL yaklaşık −100 USD (%10 risk). Bu yüzden PF'ler 2,3–5,2.
  - "BE dışı işlemlerin P&L toplamı" kolonu yalnız **betimseldir**: BE ile kapanmayan işlemlerin toplamı (XAUUSD m5 `sonra(ut_bot,combo3,12)|seans_00_07|sl3.0_tp3.0_be` için −1057, XAUUSD m15 `…sl2.0_tp2.0_be` için −9). Bu bir "kilitsiz koşum" değildir. Kilit olmasaydı bu işlemler başka yerde kapanırdı ve tek pozisyon zinciri değişirdi. Karşı-olgusal sonuç olarak okunmamalı.
  - Kâr kilidine bağımlılık iddiası bu çıkarmaya değil, bölüm 5.2'deki kötümser dolum testine dayanıyor.
- **Yön dağılımı:** XAU hücrelerinde 14 haftada hem BUY hem SELL kârlı. Bu, sonucun salt altın trend betası olmadığını tek başına göstermez: sık küçük kâr kilidi her iki yönü de kârlı gösterebilir. Holdout'ta da XAUUSD m15 `or(fisher_st,donch_vortex)|atr_dusuk|…` SELL tarafı 7 işlemde −136.
- **EURJPY daha az BE bağımlı (%47–65 BE).** Ama BUY ile SELL arasında asimetri var:
  - Kaymalı koşumda BUY tarafı negatif: EURJPY `…sl1.5_tp1.5_be` BUY 41/0,77/−44; `…sl1.5_tp1.0` BUY 41/0,83/−33.
  - Net kârın büyük kısmı 20 SELL işleminden geliyor.

### 5.2 Kâr kilidi dolum duyarlılığı (ek kontrol)

**Ne ölçüldü.** Motor (`manage_position`) her barda önce SL'yi kontrol ediyor (BUY: low ≤ stop; SELL: high ≥ stop). Vurulursa dolum **her zaman stop fiyatından** (± spread ayarı) yapılıyor; bar stopun ötesinde açılsa bile. SL kontrolünden sonra aynı barın high/low'u (MFE) ile BE kilidi/trailing stopu taşıyor; yeni stop ilk kez sonraki barda kontrol ediliyor.

**Canlıyla karşılaştırma.**
- Canlı döngü (`_forex_auto_paper_loop`) her 1,5 s'de kilit hesaplıyor ve MT5'e `MODIFY_SLTP` gönderiyor. Tick düzeyinde kesintisiz yönetimde dolum gerçekten kilit fiyatına yakın olur, yani motorun modeli ideal durumu temsil ediyor.
- Öte yandan canlıda MFE barın en uç değeri değil, 1,5 s'lik örneklerden görülen değer. Bunun üstüne değişiklik gecikmesi ve broker stop seviyesi kısıtları var.

**Kötümser sınır (kodla aynı ölçüt, `scripts/kombo_be_dolum_analizi.py dolum`).** Stop çıkışının (SL veya BE) gerçekleştiği bar, o barın başında geçerli olan stop seviyesinin ötesinde açıldıysa (BUY: açılış < stop; SELL: açılış > stop), dolum stop fiyatı yerine o barın açılışından yapılır.
- Stop, bir önceki barın high/low'una göre taşındığı ve açılış ≈ önceki kapanış olduğu için BE'de bu pratikte şu anlama geliyor: stopu kuran (ya da son taşıyan) barın kapanışı yeni stopun gerisinde kaldı. İlk SL'deki boşluklar da sayılıyor.
- Fark = (açılış − stop)/pip × kapanıştaki lot × pip_val (BUY; SELL'de işaret ters, fark her zaman ≤ 0). Spread ayarı iki dolumda aynı olduğu için farka girmiyor, motorda komisyon yok, taban kaymasız koşum.
- Kötümser net = motor neti + farkların toplamı. Bu **sonradan yapılan toplamsal bir düzeltme, yeniden koşum değil**: sonraki işlemlerin lot/bakiye etkisi ve tek pozisyon zincirindeki değişim modellenmiyor.
- Motor dosyası değiştirilmedi: `manage_position` ve `close_position` sarmalandı, yalnız NEW defteri (gölge defterler hariç) sayıldı. Sarmalanmış koşumun işlem sayısı ve neti 14 hücre-pencerenin hepsinde tabanla birebir aynı (`esit_taban`).

| Ad / hücre / tanım | Stop çıkışı (SL+BE) | Açılışı stopun ötesinde olan | Fark (USD) | 14h net → kötümser | Holdout net → kötümser |
|---|---|---|---|---|---|
| kombo_1 XAUUSD m5 `sonra(ut_bot,combo3,12)\|seans_00_07\|sl3.0_tp3.0_be` | 416 | 212 (hepsi BE) | −3587 | +3390 → **−197** | +670 → **−55** |
| kombo_4 XAUUSD m5 `or(hma_ao,tsi_ema50)\|seans_13_20\|sl1.5_tp2.0` | 69 | 42 | −1104 | +876 → **−228** | +111 → **−282** |
| kombo_9 XAUUSD m5 `sonra(btc_keltner_geri_htf,combo3,3)\|atr_yuksek\|sl2.0_tp1.0` | 67 | 34 | −604 | +1236 → +632 | +292 → +186 |
| kombo_5 XAUUSD m15 `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp3.0_be` | 88 | 46 | −1185 | +1765 → +580 | −68 → −157 |
| kombo_7 XAUUSD m15 `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp2.0_be` | 88 | 46 | −1185 | +1560 → +375 | −68 → −157 |
| kombo_14 EURJPY m15 `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.5_be` | 47 | 18 (17 BE) | −80 | +332 → +252 | −18 → −19 |
| kombo_16 EURJPY m15 `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.0` | 36 | 15 (14 BE) | −62 | +326 → +264 | −26 → −26 |

**Sonuç.**
- XAU stop çıkışlarının yaklaşık yarısında çıkış barı stopun ötesinde açılmış. Yani stop, gerisinde kapanılan bir fitile göre kurulmuş.
- Kötümser dolumda XAUUSD m5'in en büyük örneklemli iki hücresi negatife dönüyor: `sonra(ut_bot,combo3,12)|seans_00_07|sl3.0_tp3.0_be` ve `or(hma_ao,tsi_ema50)|seans_13_20|sl1.5_tp2.0`.
- XAUUSD m5 `sonra(btc_keltner_geri_htf,combo3,3)|atr_yuksek|sl2.0_tp1.0` iki pencerede de pozitif kalıyor.
- Gerçek değer ideal ile kötümser arasında. Bunu ancak canlı (demo) dolum verisi belirler.

## 6. Temiz holdout (21 Haz – 20 Tem 2026)

**Pencere.** Seçimde hiç kullanılmadı: eğitim 07-21'de başlıyor, sinyal önbelleklerinin ilk barı XAU 06-21 22:00 UTC, FX 06-21 21:30 UTC.
- Giriş penceresi `--start 2026-06-21 --end 2026-07-21`. Son kapanış 07-20; 07-21 sonrasına taşan işlem yok.
- Motor ve maliyetler 14 haftalık koşumla aynı. Kayma koşumu: XAU 2 pip, FX 1 pip (her bacakta).

**Isınma kısıtı.** Önbellekler pencerenin başında başladığı için göstergelerin ısınması kısa:
- H1 EMA200 tabanlı bileşenler/filtreler ilk ~8–9 işlem gününde susuyor.
- `btc_saat_profili` ≥ 10 önceki gün istiyor; EURJPY hücrelerinde ilk işlem 07-01.
- Etkin pencere XAU m5'te ~4 hafta (ilk kapanış 06-23…06-25), XAU m15'te ~3,5 hafta (06-26), EURJPY'de ~3 hafta (07-01).

**Kapsam.** Holdout yalnız **kombo seçimi** açısından temiz. Motorun çıkış parametreleri (BE oranı vb.) ve 33 bileşen stratejinin tasarımı daha önceki çalışmalarda hangi verilerle ayarlandıysa ondan bağımsız değil.

| Ad / hücre / tanım | n | PF | Net | Çıkışlar (kaymasız) | BUY / SELL net | Kayma n / PF / net | Kayma çıkışları |
|---|---|---|---|---|---|---|---|
| kombo_1 XAUUSD m5 `sonra(ut_bot,combo3,12)\|seans_00_07\|sl3.0_tp3.0_be` | 80 | 3,26 | **+670** | BE 69 (+450), BE+trail 8 (+517), SL 3 (−297) | +483 / +187 | 80 / 1,98 / **+407** | BE 68, BE+trail 8, SL 4 |
| kombo_4 XAUUSD m5 `or(hma_ao,tsi_ema50)\|seans_13_20\|sl1.5_tp2.0` | 21 | 1,55 | **+111** | BE 16 (+98), BE+trail 3 (+214), SL 2 (−201) | +25 / +86 | 21 / 1,82 / **+174** | BE 15, BE+trail 4, SL 2 |
| kombo_9 XAUUSD m5 `sonra(btc_keltner_geri_htf,combo3,3)\|atr_yuksek\|sl2.0_tp1.0` | 14 | ∞ (kayıpsız) | **+292** | BE 11 (+131), BE+trail 2 (+68), TP+trail 1 (+93) | +83 / +209 | 14 / ∞ / **+169** | BE 12, BE+trail 2 |
| kombo_5 XAUUSD m15 `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp3.0_be` | 13 | 0,67 | **−68** | BE 11 (+137), SL 2 (−205) | +67 / −136 | 13 / 0,54 / **−97** | BE 11, SL 2 |
| kombo_7 XAUUSD m15 `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp2.0_be` | 13 | 0,67 | **−68** | (kombo_5 ile özdeş; TP'ye ulaşan yok) | +67 / −136 | 13 / 0,54 / **−97** | BE 11, SL 2 |
| kombo_14 EURJPY m15 `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.5_be` | 7 | 0,61 | **−18** | BE 3 (+7), TP 1 (+22), SL 3 (−47) | −25 / +6 | 7 / 0,30 / **−50** | BE 2, TP 1, SL 4 |
| kombo_16 EURJPY m15 `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.0` | 7 | 0,45 | **−26** | BE 3 (+7), TP 1 (+14), SL 3 (−47) | −25 / −1 | 7 / 0,20 / **−58** | BE 2, TP 1, SL 4 |

Haftalık (kaymasız):
- `sonra(ut_bot,combo3,12)|seans_00_07|sl3.0_tp3.0_be`: 5 haftanın 5'i pozitif (+139, +278, +9, +172, +72). Kaymalı koşumda 4/5.
- `sonra(btc_keltner_geri_htf,combo3,3)|atr_yuksek|sl2.0_tp1.0`: 5/5 pozitif.
- `or(hma_ao,tsi_ema50)|seans_13_20|sl1.5_tp2.0`: 4/4 pozitif, ama küçük (+7…+69). Kaymalı koşumda net daha yüksek çıkıyor: 1 BE işlemi trailing'e dönüştü, kayma lot/pip eşiklerini kaydırıyor. Bu, sonucun yol bağımlılığını gösteriyor.

**Holdout kararı: kısmen destekliyor.**

| Hücre grubu | Holdout sonucu | Değerlendirme |
|---|---|---|
| XAUUSD m5, 3 hücre | Kaymalı koşumda da pozitif; ama en büyük örneklemli iki hücrenin holdout kârı da kötümser dolum altında siliniyor (bölüm 5.2) | Zayıf/koşullu destek: örneklem gerçekten bağımsız (80 / 21 / 14 işlem), ama 3 hücreden 2'si kötümser dolumda holdout'ta da negatif; 21 ve 14 işlem az |
| XAUUSD m15 çifti | Negatif (13 işlem) | Desteklemiyor |
| EURJPY m15 çifti | Negatif (7 işlem; BTC için tasarlanmış bileşenler) | Desteklemiyor |

İstatistiksel güç zayıf: XAU m5 dışında hiçbir hücrede holdout tek başına anlamlı değil.

## 7. Risk ölçekleme ve hedef gün

Yöntem:
- Günlük P&L (kapanış günü, UTC) taban riskten **doğrusal** ölçeklendi. Taban XAU %10, FX %5; ölçek = hedef% / taban%.
- Hedef gün ≥ +500 USD, iflas günü ≤ −700 USD.
- Doğrusal ölçek yaklaşık bir varsayım: lot yuvarlaması (0,01), lot tavanı ve BE tetiklerinin lot büyüklüğüne bağlı olması (1 USD kuralı) gerçekte doğrusallığı bozar.

**14 hafta** (hedef gün / iflas gün / net USD / en iyi gün):

| Ad / hücre / tanım | %2 | %5 | %10 | %20 |
|---|---|---|---|---|
| kombo_1 XAUUSD m5 `sonra(ut_bot,combo3,12)\|seans_00_07\|sl3.0_tp3.0_be` | 0/0/678/154 | 0/0/1695/386 | 2/0/3390/772 | 3/0/6780/1544 |
| kombo_4 XAUUSD m5 `or(hma_ao,tsi_ema50)\|seans_13_20\|sl1.5_tp2.0` | 0/0/175/50 | 0/0/438/125 | 0/0/876/250 | 1/0/1753/501 |
| kombo_9 XAUUSD m5 `sonra(btc_keltner_geri_htf,combo3,3)\|atr_yuksek\|sl2.0_tp1.0` | 0/0/247/44 | 0/0/618/111 | 0/0/1236/221 | 0/0/2472/442 |
| kombo_5 XAUUSD m15 `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp3.0_be` | 0/0/353/63 | 0/0/883/159 | 0/0/1765/317 | 2/0/3530/634 |
| kombo_7 XAUUSD m15 `or(fisher_st,donch_vortex)\|atr_dusuk\|sl2.0_tp2.0_be` | 0/0/312/43 | 0/0/780/107 | 0/0/1560/214 | 0/0/3120/428 |
| kombo_14 EURJPY m15 `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.5_be` | 0/0/133/11 | 0/0/332/28 | 0/0/663/56 | 0/0/1327/112 |
| kombo_16 EURJPY m15 `or(btc_saat_profili,btc_xau_oncu)\|atr_dusuk\|sl1.5_tp1.0` | 0/0/130/12 | 0/0/326/29 | 0/0/652/59 | 0/0/1305/117 |

- **Holdout:** hiçbir hücrede, hiçbir risk düzeyinde hedef günü yok. En iyi gün: `sonra(ut_bot,combo3,12)|seans_00_07|sl3.0_tp3.0_be` için %20'de +431.
- **İflas günü** hiçbir yerde yok. En kötü gün %20'de yaklaşık −200 (XAU) ve −64 (EURJPY).

**"Hepsi birlikte" (gösterge niteliğinde).**

Hesap şöyle yapıldı:
- 5 farklı sinyal setinin günlük P&L'i toplandı (bağımsız değil: 3'ü XAUUSD m5'te). Setler: XAU m5 üçlüsü, XAU m15'ten `…sl2.0_tp3.0_be`, EURJPY'den `…sl1.5_tp1.5_be`.
- Çiftlerin her birinden 14 haftalık neti yüksek olan varyant seçildi; holdout'ta çift üyeleri özdeş ya da çok yakın.
- Bu toplam, **5 ayrı izole 1000 USD defterin** (toplam 5000 USD sermaye) toplamıdır; tek bir 1000 USD defter değildir.

Tek 1000 USD defterde aynı işlem başı riskle koşmak şu sonuçları doğurur:
- 14 haftada en çok 5 eşzamanlı pozisyon oluşuyor (zamanın %90'ında 1, %7,6'sında 2, %2'sinde ≥ 3). Bu, anlık risk yükünün %50'ye (5 × %10) çıkabileceği anlamına gelir.
- Üç XAU m5 hücresi aynı sembolde; motorun sembol başı tek pozisyon kuralı ortak defterde girişleri bloklayabilir.
- Kasa ortak olduğu için kayıplar birbirinin lot büyüklüğünü etkiler.

| Pencere | Risk | Hedef gün | İflas gün | Net | En iyi gün | En kötü gün | İşlem günü |
|---|---|---|---|---|---|---|---|
| 14 hafta | sistem (XAU %10, FX %5) | 2 | 0 | +7599 | +855 | −157 | 76 |
| 14 hafta | %2 | 0 | 0 | +1586 | +171 | −31 | 76 |
| 14 hafta | %5 | 0 | 0 | +3966 | +428 | −78 | 76 |
| 14 hafta | %10 | 2 | 0 | +7931 | +855 | −157 | 76 |
| 14 hafta | %20 | 7 | 0 | +15862 | +1711 | −313 | 76 |
| holdout | sistem | 0 | 0 | +986 | +242 | −116 | 22 |
| holdout | %20 | 0 | 0 | +1936 | +484 | −231 | 22 |

+500/gün, tek bir 1000 USD defterle makul riskte ulaşılabilir değil. 5 defter ve %20 riskte bile 14 haftada 7 gün, holdout'ta 0 gün. Ayrıca bu sayılar BE dolumlarının ideal olduğu varsayımına dayanıyor (bölüm 5.2).

## 8. Sınırlar

1. **c5 bağımsız değil.** Test penceresi (09-08 – 10-27), c2'nin ikinci yarısıyla aynı. Bu 17 kombo zaten hızlı simde bu pencerede PF ≥ 1,2 tuttuğu için seçildi. Motordaki c5'in bağımsızlığı yalnız farklı çıkış yönetiminden geliyor. Gerçekten dokunulmamış tek veri, bölüm 6'daki holdout.
2. **Kombo tanımları commit dışı bir dosyada.** `outputs/kombo/kombo_tanimlar.json` gitignore kapsamında. Yeniden üretim `python scripts/strategies/kombo.py --olustur` ile `secim.json`'dan yapılıyor; ad sırası kararlı. Robust 7 tanım burada **aynen** veriliyor:
   ```
   {"ad": "kombo_1", "sym": "XAUUSD", "tf": "m5", "tanim": {"tip": "sonra", "a": "ut_bot", "b": "combo3", "n": 12, "filtre": ["seans_00_07"], "sl_atr": 3.0, "tp_r": 3.0, "basabas": true}}
   {"ad": "kombo_4", "sym": "XAUUSD", "tf": "m5", "tanim": {"tip": "or", "a": "hma_ao", "b": "tsi_ema50", "n": null, "filtre": ["seans_13_20"], "sl_atr": 1.5, "tp_r": 2.0, "basabas": false}}
   {"ad": "kombo_9", "sym": "XAUUSD", "tf": "m5", "tanim": {"tip": "sonra", "a": "btc_keltner_geri_htf", "b": "combo3", "n": 3, "filtre": ["atr_yuksek"], "sl_atr": 2.0, "tp_r": 1.0, "basabas": false}}
   {"ad": "kombo_5", "sym": "XAUUSD", "tf": "m15", "tanim": {"tip": "or", "a": "fisher_st", "b": "donch_vortex", "n": null, "filtre": ["atr_dusuk"], "sl_atr": 2.0, "tp_r": 3.0, "basabas": true}}
   {"ad": "kombo_7", "sym": "XAUUSD", "tf": "m15", "tanim": {"tip": "or", "a": "fisher_st", "b": "donch_vortex", "n": null, "filtre": ["atr_dusuk"], "sl_atr": 2.0, "tp_r": 2.0, "basabas": true}}
   {"ad": "kombo_14", "sym": "EURJPY", "tf": "m15", "tanim": {"tip": "or", "a": "btc_saat_profili", "b": "btc_xau_oncu", "n": null, "filtre": ["atr_dusuk"], "sl_atr": 1.5, "tp_r": 1.5, "basabas": true}}
   {"ad": "kombo_16", "sym": "EURJPY", "tf": "m15", "tanim": {"tip": "or", "a": "btc_saat_profili", "b": "btc_xau_oncu", "n": null, "filtre": ["atr_dusuk"], "sl_atr": 1.5, "tp_r": 1.0, "basabas": false}}
   ```
   Motorda `basabas` alanı etkisiz; motor her zaman canlı BE'yi kullanıyor. `kombo_tanimlar.json` mevcutken `kombo_tarama.py sinyal-uret` kombo_*'ları da bileşen olarak üretir. Task 1 taramasını tekrarlarken `KOMBO_TANIM=yok.json` verilmeli.
3. **BTC: hiçbir kombo geçmedi.** 6 BTC kombosunun hiçbiri c1'i geçmedi: hızlı simdeki kenar motorda kayboluyor.
4. **EURJPY kombosu tasarım dışı sembolde.** Bileşenleri BTC için tasarlanmış (`btc_saat_profili`, `btc_xau_oncu`), tesadüf riski yüksek. Holdout'ta 7 işlem ve negatif; kayma altında BUY tarafı negatif.
5. **Tek rejim.** Tüm veri yaklaşık 4 aylık tek bir dönem (2026-06-21 – 10-27). Başka yıl, volatilite rejimi veya haber yoğunluğu sınanmadı.
6. **Sonuç büyük ölçüde motorun kâr kilidine bağlı (bölüm 5).** XAU m5'in iki hücresi kötümser dolumda negatif. Canlı BE dolum kalitesi ölçülmeden XAU sonuçları güvenilir sayılmamalı.
7. **Örneklem küçük.** Test penceresi 31–43 işlem; tek istisna `sonra(ut_bot,combo3,12)|seans_00_07|sl3.0_tp3.0_be` (225). Holdout 7–21 işlem; istisna yine aynı kombo (80).
8. **Çoklu karşılaştırma.** 1,2 milyon kombinasyon arasından seçim yapıldı; 400 üst satırın %4,75'i testte tutundu. Robust etiketi iyimser okunmalı.
9. Mevcut v1 `dogrulama.json`, HEAD sürümüyle yeniden üretildiğinde farklı çıkıyor. Bu Task 3'te not edildi ve v3 ile ilgisiz.

## 9. Karar ve sonraki adım

**Gerçek parayla işlem yok.** Kombinasyon taraması 7 hücreyi ölçütlerden geçirdi, ama:
- holdout yalnız XAUUSD m5 üçlüsünü destekledi;
- bu üçlünün ikisi kâr kilidi dolum varsayımına duyarlı;
- +500/gün hedefi makul riskte ulaşılamıyor.

**Demo (paper) ileri testi önerisi:**

| Konu | Öneri |
|---|---|
| Hücreler | Yalnız XAUUSD m5: `sonra(ut_bot,combo3,12)\|seans_00_07\|sl3.0_tp3.0_be`, `or(hma_ao,tsi_ema50)\|seans_13_20\|sl1.5_tp2.0`, `sonra(btc_keltner_geri_htf,combo3,3)\|atr_yuksek\|sl2.0_tp1.0`. Her biri ayrı izole demo defterde. |
| Kapsam dışı | XAUUSD m15 çifti ve EURJPY m15 çifti holdout'ta negatif; kâğıt teste alınmıyor, yalnız gözlem. |
| Risk | **%2** (sistemin %10'u yerine). Amaç para kazanmak değil, dolum kalitesini ölçmek. %2'de SL kaybı yaklaşık −20 USD. |
| Süre | En az 4 hafta veya hücre başına ≥ 40 kapanmış işlem (hangisi sonra gelirse). |
| Ölçülecekler | (a) Her BE/SL çıkışında hedef kilit fiyatı ile gerçek dolum farkı (pip), bölüm 5.2'deki ideal–kötümser aralığın neresine düştüğü. (b) Motor aynı günlerde yeniden koşulduğunda işlem eşleşmesi (sinyal paritesi). (c) Maliyet sonrası PF. |
| Geçme ölçütü | Maliyet sonrası PF ≥ 1,3; medyan BE dolum kaybı, kötümser senaryonun yarısından az; hiçbir hücrede net < −%10 kasa. |
| Durma ölçütü | Herhangi bir hücrede 20 işlem sonrası PF < 1,0 veya BE dolumları sistematik olarak kötümser tarafta. |
| Sonra | Geçen hücreler için risk kademeli artırılabilir: %2 → %5. +500/gün hedefi bu sinyal setleriyle gerçekçi değil; hedef ya düşürülmeli ya da sermaye artırılmalı. |

## 10. Yeniden üretim komutları

Komutlar bash / Git Bash içindir (`$W` değişkeni ve `{a,b}` küme genişletmesi kullanılıyor; PowerShell/cmd'de elle açılmalı).

```bash
# 1) Sinyal önbelleği + hızlı tarama (20 hücre)
#    kombo_tanimlar.json mevcutsa: KOMBO_TANIM=yok.json önüne ekleyin
python scripts/kombo_tarama.py sinyal-uret --jobs 6
python scripts/kombo_tarama.py tara --jobs 6
python scripts/kombo_secim.py            # outputs/kombo/secim.json + TARAMA_OZET.md

# 2) Kombo tanımları (19 tutunan satır -> 17 kombo)
python scripts/strategies/kombo.py --olustur

# 3) Gerçek motor, 14 hafta (sembol x tf başına ayrı --tur), örnek XAU m5 ve EURJPY m15:
python scripts/replay_strateji_tarama.py --tur kombo_v3_xauusd_m5 --tfs m5 --strategies kombo_1,kombo_3,kombo_4,kombo_9 --symbols XAUUSD --jobs 5 --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols"
python scripts/replay_strateji_tarama.py --tur kombo_v3_eurjpy_m15 --tfs m15 --strategies kombo_14,kombo_15,kombo_16 --symbols EURJPY --jobs 5 --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json"
#    (diğerleri: kombo_v3_xauusd_m15, kombo_v3_btcusd_m15, kombo_v3_btcusd_m5, kombo_v3_eurusd_m15)

# 4) Ölçütler + kayma (script kayma komutlarını basar; çalıştırıp --slip-ozet ile tekrar)
python scripts/strateji_dogrulama.py --ozet outputs/replay_strateji/ozet_turkombo_v3_{btcusd_m15,btcusd_m5,eurjpy_m15,eurusd_m15,xauusd_m15,xauusd_m5}.json \
   --out outputs/replay_strateji/dogrulama_v3.json --slip-tur-oneki kombo_v3_slip --test-penceresi \
   [--slip-ozet outputs/replay_strateji/ozet_turkombo_v3_slip_{btc_m15,fx_m15,xau_m15,xau_m5}.json]

# 5) Temiz holdout (21 Haz - 20 Tem), kaymasız ve kaymalı
W="--start 2026-06-21 --end 2026-07-21"
python scripts/replay_strateji_tarama.py --tur kombo_v3_holdout_xau_m5  --tfs m5  --strategies kombo_1,kombo_4,kombo_9 --symbols XAUUSD --jobs 3 --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols" $W
python scripts/replay_strateji_tarama.py --tur kombo_v3_holdout_xau_m15 --tfs m15 --strategies kombo_5,kombo_7 --symbols XAUUSD --jobs 2 --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols" $W
python scripts/replay_strateji_tarama.py --tur kombo_v3_holdout_fx_m15  --tfs m15 --strategies kombo_14,kombo_16 --symbols EURJPY --jobs 2 --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json" $W
python scripts/replay_strateji_tarama.py --tur kombo_v3_holdout_slip_xau_m5  --tfs m5  --strategies kombo_1,kombo_4,kombo_9 --symbols XAUUSD --jobs 3 --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols --slip-pips 2" $W
python scripts/replay_strateji_tarama.py --tur kombo_v3_holdout_slip_xau_m15 --tfs m15 --strategies kombo_5,kombo_7 --symbols XAUUSD --jobs 2 --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols --slip-pips 2" $W
python scripts/replay_strateji_tarama.py --tur kombo_v3_holdout_slip_fx_m15  --tfs m15 --strategies kombo_14,kombo_16 --symbols EURJPY --jobs 2 --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --slip-pips 1 --spread-profile outputs/fx_spread_db_1m.json" $W
```

**Bölüm 5–7 hesapları:** `scripts/kombo_be_dolum_analizi.py`. Algoritma, script'in docstring'inde ve bölüm 5.2'de aynı ölçütle tanımlı.
```bash
# Kötümser dolum (7 hücre x {14 hafta, holdout}; ayrı süreçler) -> outputs/kombo/be_dolum.json
python scripts/kombo_be_dolum_analizi.py dolum-hepsi --jobs 7
# Tek hücre:
python scripts/kombo_be_dolum_analizi.py dolum --strategy kombo_1 --tf m5 --symbol XAUUSD --start 2026-07-21 --end 2026-10-28 --out x.json
# Çıkış karışımı, yön, holdout, risk ölçekleme, 5 set toplamı, eşzamanlılık -> outputs/kombo/be_dolum_ozet.json
python scripts/kombo_be_dolum_analizi.py ozet
```
`ozet` için kaynaklar:
- Kapanan işlemler `outputs/replay_strateji/rep_<tag>.json` → `variants.NEW.closed`. Tag biçimi: `tkombo_v3_<grup>_<tf>_<kombo>_<tf>_<SYM>`, kayma için `tkombo_v3_slip_<xau|fx>_…`, holdout için `tkombo_v3_holdout_[slip_]<xau|fx>_<tf>_…`.
- Çıkış nedeni = `reason` (+ `trail` true ise "+trail"), yön = `direction`, gün = `closed_ts` UTC günü.
- Eşzamanlılıkta açılış zamanı = önbellekteki `bars[opened_bar][0]`.
- "BE dışı işlemlerin P&L toplamı" betimseldir (bkz. 5.1).
