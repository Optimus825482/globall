# Combo3 Stratejisi — 21 Parite (GBP/USD/EUR/NZD/JPY/CAD/CHF) × M5/M15/M30 Testi

Tarih: 2026-10-28 · Motor: mevcut replay (`forex_replay_backtest.py`), yalnız giriş stratejisi Combo3 (UT Bot ∪ Donchian+Vortex ∪ Vortex, SL 1.5×ATR, TP 2R)
Veri: MT5 → `outputs/replay_cache_fx21_{m5,m15,m30}.json` (20 Haz – 27 Eki 2026) · Koşucu: `scripts/replay_strateji_tarama.py --tur fx1` · Özet: `outputs/replay_strateji/ozet_turfx1.json`

## 1. Kısa sonuç

**Combo3 altındaki kenarını hiçbir paritede göstermiyor.** 63 hücrenin (21 parite × 3 dilim) 61'i net zararda; yalnız GBPNZD M30 (+107, PF 1.08) ve CHFJPY M30 (+106, PF 1.09) sıfır civarında artı. Hiçbir hücrede hiçbir gün +500 USD (1000 → 1500) görülmedi. Dilim toplamları: M5 −107.0k, M15 −40.7k, M30 −16.0k (21 hücre, 1000 USD taban, FX risk %5 sistem ayarı).

## 2. Düzen

- Her parite ayrı defterde (izole; slot/korelasyon rekabeti yok), 14 hafta (21 Tem – 27 Eki), 7 hafta alt pencere (8 Eyl –).
- Motor varsayılanları: FX risk bütçesi %5 (sistem), majör seans 07–20 UTC ve min ATR 4 pip kapıları, ADX ≥ 20, EV kalkanı, kategori spread (majör 1.2 pip, kros 2.0 pip), kros pip değeri pencere kuruyla; BE/trailing/kısmi çıkış motorun.
- Altınla aynı giriş dilimi (M5) + M15 + M30. M3 koşulmadı (M5 zaten en kötü dilim).
- Kayma stresi uygulanmadı: taban sonuç zaten negatif.

## 3. Sonuç tablosu (14 hafta; net USD, 1000 taban)

| Parite | M5 net / PF / WR | M15 net / PF / WR | M30 net / PF / WR |
|---|---|---|---|
| GBPNZD | −3112 / 0.59 / 64 | −447 / 0.86 / 75 | **+107 / 1.08 / 79** |
| CHFJPY | −3137 / 0.60 / 60 | −561 / 0.83 / 70 | **+106 / 1.09 / 78** |
| USDJPY | −2153 / 0.67 / 60 | −499 / 0.79 / 68 | −156 / 0.82 / 72 |
| GBPJPY | −3047 / 0.62 / 61 | −559 / 0.81 / 72 | −184 / 0.86 / 77 |
| EURNZD | −3026 / 0.60 / 61 | −824 / 0.77 / 71 | −314 / 0.82 / 74 |
| EURJPY | −4040 / 0.55 / 54 | −1612 / 0.58 / 65 | −338 / 0.83 / 69 |
| NZDJPY | −4873 / 0.44 / 47 | −1849 / 0.55 / 59 | −426 / 0.74 / 70 |
| EURUSD | −4014 / 0.52 / 44 | −1448 / 0.60 / 58 | −503 / 0.68 / 65 |
| USDCHF | −2924 / 0.65 / 48 | −1429 / 0.56 / 57 | −528 / 0.60 / 62 |
| GBPUSD | −3454 / 0.54 / 50 | −1116 / 0.62 / 62 | −571 / 0.59 / 64 |
| GBPCHF | −4866 / 0.50 / 44 | −1310 / 0.73 / 58 | −580 / 0.71 / 65 |
| GBPCAD | −5184 / 0.41 / 46 | −2201 / 0.51 / 61 | −587 / 0.73 / 69 |
| USDCAD | −2999 / 0.66 / 49 | −858 / 0.75 / 63 | −701 / 0.61 / 63 |
| NZDUSD | −4004 / 0.50 / 38 | −1837 / 0.49 / 51 | −752 / 0.46 / 57 |
| NZDCAD | −6274 / 0.37 / 40 | −2953 / 0.41 / 51 | −999 / 0.58 / 62 |
| CADJPY | −4848 / 0.52 / 47 | −1880 / 0.59 / 60 | −1016 / 0.53 / 65 |
| EURCAD | −5671 / 0.40 / 42 | −2259 / 0.55 / 58 | −1115 / 0.54 / 62 |
| EURCHF | −7802 / 0.26 / 30 | −3770 / 0.43 / 44 | −1462 / 0.55 / 56 |
| NZDCHF | −9820 / 0.21 / 22 | −4150 / 0.41 / 38 | −1581 / 0.54 / 50 |
| CADCHF | −9512 / 0.24 / 24 | −3890 / 0.35 / 40 | −1781 / 0.37 / 49 |
| EURGBP | −12286 / 0.14 / 17 | −5233 / 0.27 / 30 | −2601 / 0.33 / 41 |

Günlük hedef (+500) hiçbir hücrede 0'dan büyük değil; iflas günü (≤ −700) de yok (FX lotları küçük).

## 4. Okuma

- **Maliyet / stop oranı:** Combo3'ün stopu 1.5×ATR(14). Altında M5 ATR ~5 USD = 50 pip; stop 75 pip, spread 2.5 pip (%3). EURGBP/EURCHF/CADCHF/NZDCHF gibi düşük volatiliteli paritelerde M5 ATR 2–4 pip; stop 3–6 pip, kros spread 2 pip → maliyet stopun %30–60'ı. WR %15–30'a düşüyor. Dilim büyüdükçe (M30) ATR ve stop büyüyor, maliyet payı düşüyor, sonuçlar sıfıra yaklaşıyor; yine de kenar yok.
- **Altın neden farklıydı:** altında kâr BE-kilidi mekaniğinden gelen çok sayıda küçük kazançtı (işlem başına ~5 pip, stopun %7'si); FX'te aynı 5 pip spread + kayma ile yenir. Altındaki sonuç da 2 pip kaymada PF 1.09'a düşmüştü (bkz. `docs/REPLAY_STRATEJI_TARAMA_2026_10_27.md`); FX bu kırılganlığın sınır koşulu.
- **JPY çaprazları ve GBPNZD M30** en az kötü; ama PF ≤ 1.09 ve 14 haftada +100 USD, spread stresi olmadan. Canlıya alınacak bir şey yok.

## 5. M1 ve M3 — yerel Postgres'ten, gerçek spread ile (01:23 ek)

Veri önce yerel DB'ye çekildi: `scripts/mt5_to_postgres.py ingest-rates` (yeni mod; MT5 `copy_rates` parçalı, `historical_candles` kaynak `mt5_icmarkets_rates`): 3 dk 785.854 bar (10 Tem – 28 Eki), 1 dk 2.099.097 bar (22 Tem – 28 Eki; terminal 1 dk geçmişi ~100k barla sınırlı, 14 haftalık pencerenin ilk günü eksik). Spread profili DB'deki bar açılış spread'inden (`mt5_spread_profile` → `outputs/fx_spread_db_1m.json`; örn. GBPUSD 0.43 pip, EURUSD 1.81, CHFJPY 1.88) ve replay `--spread-profile` ile kullanıldı. Motor DB okuyucusu sembol filtreli yapıldı (1 dk tabloda 42M kripto satırı). Koşum: `replay_strateji_tarama.py --tur fxdb_m3 / fxdb_m1 --db`.

| | Hücre | Pozitif | Toplam net | Hedef gün (+500) | En iyi |
|---|---|---|---|---|---|
| M3 | 21 | 0 | −93.1k | 1 (EURCAD, tek gün) | USDCAD −958 PF 0.90 |
| M1 | 21 | 0 | −143.1k | 0 | USDCAD −593 PF 0.90 |

M3 en kötüler: EURGBP −8727 (WR %19), NZDUSD −6084, GBPCHF −6029, EURUSD −5885. M1 en kötüler: EURGBP −13341 (WR %13), EURCHF −11517, GBPCHF −11394, CADCHF −10819. Dilim küçüldükçe zarar büyüyor (M30 −16k → M15 −41k → M5 −107k → M3 −93k* → M1 −143k; *M3 gerçek spread ile, diğerleri kategori spread ile).

Gerçek spread (çoğu paritede kategori spread'inden düşük) sonucu değiştirmedi: sorun spread değil, kuralın FX'te yön isabeti (%13–58) ve 1.5×ATR stopun dakikalık dilimlerde birkaç pip olması.

## 6. Karar

Combo3 kolu FX paritelerine **genişletilmemeli**; `combo3_symbols` yalnız XAUUSD kalır. FX için farklı bir stop/hedef ölçeği (ATR katı değil, spread katı tabanlı) ve farklı bir giriş ailesi gerekir; bu test onu kapsamıyor.
