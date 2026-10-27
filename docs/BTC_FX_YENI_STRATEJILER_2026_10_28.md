# BTC ve FX yeni strateji ailesi: robust kenar doğrulaması (2026-10-28)

Kapsam: Task 2 (5 BTC stratejisi x M5/M15 = 10 hücre) ve Task 3 (4 FX stratejisi x M15/M30 x 8 parite = 64 hücre) sonuçlarına "robust kenar" ölçütlerinin uygulanması, kayma stresi ve risk ölçekleme. Script: `scripts/strateji_dogrulama.py` (ham çıktı: `outputs/replay_strateji/dogrulama.json`, commit edilmez).

## 1. Kısa sonuç

- **Robust kenar bulunamadı: 0 / 74 hücre.** Ölçüt 1+2+4'ü (kayma stresinden önce) geçen tek hücre `fx_donchian_gunluk` M15 GBPJPY (70 işlem, PF 1.34, net +73.9 USD); 1 pip kaymada PF 0.88'e düşüp ölçüt 3'ü kaybediyor. Aday sayısı 1, robust sayısı 0.
- **Günlük +%50 (1000 USD tabanda +500 USD/gün) hedefi hiçbir yerde tutmadı.** Taban riskte (FX %5, BTC %2) hedef gün sayısı 74 hücrenin hepsinde 0; işlem yapılan günlerin ortalaması en iyi hücrede bile +18.4 USD/gün (USDCHF Donchian M30, yalnız 18 işlem; ölçüt 1 geçen hücrelerde en çok +10.6, USDCAD M15), en iyi tek gün +342 USD (USDCAD Donchian M15). Risk %20'ye çıkarılınca birkaç hedef gün çıkıyor (bölüm 6), ama bunlar ölçütleri geçmeyen hücreler.
- Ölçüt 1'i geçen yalnızca 3 hücre var (hepsi `fx_donchian_gunluk` M15: GBPJPY, EURJPY, USDCAD). >= 60 işlemli 11 hücrenin 3'ünün PF >= 1.3 çıkması (%27) rastlantıyla beklenen ~%25 oranına denk düşer (bölüm 7).
- BTC tarafında tek istikrarlı pozitif hücre `btc_keltner_geri_htf` (M5/M15, PF 1.18/1.23); PF eşiğinin altında kalıyor ve 10 USD kaymada PF 0.52/0.74'e çöküyor.
- İki "bilgi" hücresi (Donchian M15 EURJPY, USDCAD) ölçüt 1, 3 ve 4'ü geçti ama ölçüt 2'yi geçemedi (bir yarı negatif); aday değildir, ileri test gözlemi olarak not edildi.

## 2. Düzen

- **Veri:** MT5 mum önbelleği. FX: `outputs/replay_cache_fx21_{m15,m30}.json` (~2026-06-21 .. 2026-10-27), spread: `outputs/fx_spread_db_1m.json`. BTC: `outputs/replay_cache_xaubtc_{m5,m15}.json` (2026-06-20 .. 2026-10-28). Değerlendirme penceresi 14 hafta: 2026-07-21 .. 2026-10-27 (öncesi ısınma).
- **Motor:** `scripts/replay_strateji_gunluk.py`, canlı motor kapılarıyla (min_score, rr_floor, headroom, ADX >= 20, QUALITY, spread kapısı vb.). Her hücre ayrı süreç ve ayrı 1000 USD defter (FX'te her parite izole). Eklentiler `scripts/strategies/btc_aile.py` ve `fx_aile.py`; parametre ayarı/grid yok (tek sabit set), yani parametre overfit'i yok; seçme yanlılığı hücre sayısından geliyor.
- **Risk:** Günlük P&L sabit 1000 USD tabanda hesaplanır; sistem riski FX %5, BTC %2. Hedef gün = günlük net >= +500 USD, "iflas" günü = <= -700 USD.
- **Ölçütler (bağlayıcı):**
  1. 14 hafta PF >= 1.30, net > 0, >= 60 işlem.
  2. İlk 7 hafta (07-21 .. 09-07) ve son 7 hafta (09-08 .. 10-27) ayrı ayrı net > 0.
  3. Kayma stresinde PF >= 1.10 (FX `--slip-pips 1`, BTC `--slip-pips 10`, 1 pip = 1 USD).
  4. İflas günü sayısı <= 2.

  Aday = 1+2+4 (kayma koşumundan önce); robust = 1+2+3+4. Net / ilk 7h / son 7h değerleri `gun_*.json` içindeki `daily` alanından hesaplandı; 14 hafta toplamı özet dosyalarındaki net ile 74 hücrenin hepsinde eşleşti.
- **Hücre notları (kontrolör kararları):**
  - `fx_bb_donus_m30` ADX < 20 ister, canlı motorun ADX >= 20 kapısı bu adayları eler: **canlı sistem kapıları altında test edilemez/dağıtılamaz**, aday değildir. Ana koşumda toplam 2 işlem. Yalnız tanı amaçlı: kapılar kapalıyken (`--adx-min 0 --no-quality-gate`, tur `fx_yeni_nogate`) 256 işlem, toplam +68 USD, M15 +163 / M30 -95 (tutarsız). Bu sayılar aday seçiminde kullanılmadı.
  - `btc_keltner_geri_htf`, EMA20-pullback + 3 bar kırılım teyidi olarak uygulandı; Keltner ATR bantları kullanılmıyor. İsim yanıltıcıdır.
  - `btc_seans_kirilim`: ~130 sinyalden yalnızca 10-17 işlem açılması açıklanamadı; sayıları **güvenilmez** sayılmalı.

## 3. BTC tablosu (10 hücre, BTCUSD)

| Strateji | TF | İşlem | PF | Net 14h | İlk 7h | Son 7h | İflas gün | Ölçüt 1 | Ölçüt 2 |
|---|---|---|---|---|---|---|---|---|---|
| btc_donchian55_trend | m15 | 12 | 0.70 | -25.6 | -44.5 | +18.9 | 0 | H | H |
| btc_donchian55_trend | m5 | 195 | 0.96 | -42.0 | +13.7 | -55.7 | 0 | H | H |
| btc_keltner_geri_htf | m15 | 122 | 1.23 | +79.5 | +14.5 | +65.0 | 0 | H | E |
| btc_keltner_geri_htf | m5 | 481 | 1.18 | +318.6 | +2.2 | +316.5 | 0 | H | E |
| btc_nr7_kirilim | m15 | 313 | 0.98 | -23.5 | +70.5 | -94.0 | 0 | H | H |
| btc_nr7_kirilim | m5 | 1023 | 0.75 | -1332.2 | -1097.1 | -235.1 | 0 | H | H |
| btc_rsi2_bb_donus | m15 | 4 | inf | +7.1 | +7.1 | +0.0 | 0 | H | H |
| btc_rsi2_bb_donus | m5 | 30 | 0.93 | -5.9 | -4.1 | -1.8 | 0 | H | H |
| btc_seans_kirilim | m15 | 17 | 1.50 | +40.4 | +51.0 | -10.5 | 0 | H | H |
| btc_seans_kirilim | m5 | 10 | 1.38 | +8.2 | -14.5 | +22.6 | 0 | H | H |

Ölçüt 4 tüm BTC hücrelerinde geçiyor (iflas günü yok; küçük pozisyon). Ölçüt 1'i hiçbir BTC hücresi geçmiyor: PF >= 1.3 olanlar (seans kırılım, 10/17 işlem) 60 işlemin çok altında; >= 60 işlemli tek pozitif aile Keltner (PF 1.18/1.23). NR7 M5 -1332 USD (1023 işlem, maliyet erimesi). Donchian55 negatif, RSI2+BB örneklemsiz (4 ve 30 işlem). `btc_rsi2_bb_donus` M15 PF `inf` = 4 işlem, hiç zarar yok.

## 4. FX tablosu (64 hücre)

Hücre = net 14 hafta (USD) / PF / işlem. `-` = işlem yok. `*` = ölçüt 1 ve 2 geçti (aday), `†` = yalnız ölçüt 1 geçti. PF `inf` = zararlı işlem yok (tek işlem).

**M15**

| Strateji | EURUSD | GBPUSD | USDJPY | USDCAD | USDCHF | GBPJPY | EURJPY | NZDUSD |
|---|---|---|---|---|---|---|---|---|
| fx_londra_aralik | - | -25 / 0.90 / 40 | +59 / 1.75 / 17 | -2 / 0.99 / 36 | -13 / 0.21 / 2 | -70 / 0.56 / 29 | +41 / 1.29 / 32 | - |
| fx_ema200_rsi_geri | -9 / 0.93 / 29 | -39 / 0.85 / 70 | -70 / 0.58 / 44 | -60 / 0.74 / 49 | -13 / 0.93 / 50 | +89 / 1.99 / 51 | -136 / 0.46 / 65 | -7 / 0.58 / 6 |
| fx_bb_donus_m30 | - | - | +3 / inf / 1 | +4 / inf / 1 | - | - | - | - |
| fx_donchian_gunluk | -62 / 0.23 / 11 | -179 / 0.53 / 86 | -134 / 0.38 / 39 | +296 / 1.84 / 79† | -213 / 0.20 / 30 | +74 / 1.34 / 70* | +240 / 1.67 / 78† | - |

**M30**

| Strateji | EURUSD | GBPUSD | USDJPY | USDCAD | USDCHF | GBPJPY | EURJPY | NZDUSD |
|---|---|---|---|---|---|---|---|---|
| fx_londra_aralik | - | +6 / 1.04 / 36 | -20 / 0.79 / 19 | +120 / 1.70 / 37 | +4 / inf / 1 | -48 / 0.81 / 31 | +14 / 1.07 / 39 | - |
| fx_ema200_rsi_geri | -66 / 0.53 / 29 | +25 / 1.42 / 36 | -60 / 0.51 / 34 | +38 / 1.43 / 27 | +26 / 1.34 / 25 | -58 / 0.45 / 33 | +24 / 1.32 / 35 | -76 / 0.32 / 16 |
| fx_bb_donus_m30 | - | - | - | - | - | - | - | - |
| fx_donchian_gunluk | -71 / 0.25 / 15 | -53 / 0.51 / 25 | -5 / 0.71 / 7 | +110 / 1.52 / 41 | +184 / 2.47 / 18 | -40 / 0.63 / 28 | +59 / 1.64 / 35 | -15 / 0.05 / 2 |

Notlar: `fx_londra_aralik` EURUSD ve NZDUSD'de hiç işlem üretmiyor (spread kapısı: SL pip < 8 x spread). `fx_ema200_rsi_geri` toplam net -390 USD (599 işlem); hücre işaretleri M15/M30 arasında dönüyor (EURJPY -136/+24, GBPJPY +89/-58): sinyalden çok gürültü. `fx_donchian_gunluk` günlük EMA50 filtresi yüzünden ilk işlemini 2026-08-19 civarında yapıyor; "ilk 7 hafta" yarısı için fiilen yalnız ~3 haftalık sinyal var (ölçüt 2 bu strateji için zayıf bir sınama).

## 5. Aday listesi ve kayma stresi

Ölçüt 1+2+4'ü geçen hücre: 1. (Task 3'ün FX "net>0 ve PF>=1.3" sayımı 16 hücre verir, çoğu < 60 işlem; ölçüt 1 işlem eşiğiyle 3'e, ölçüt 2 ile 1'e iner.)

| Hücre | Rol | İşlem | PF | Net 14h | İlk 7h | Son 7h | Kayma PF | Kayma net | Ölçüt 3 | Sonuç |
|---|---|---|---|---|---|---|---|---|---|---|
| fx_donchian_gunluk M15 GBPJPY | aday (1+2+4) | 70 | 1.34 | +73.9 | +12.2 | +61.7 | 0.88 | -27.4 | HAYIR | robust değil |
| fx_donchian_gunluk M15 EURJPY | bilgi (1+4) | 78 | 1.67 | +240.4 | -97.0 | +337.5 | 1.19 | +87.6 | evet | ölçüt 2 başarısız |
| fx_donchian_gunluk M15 USDCAD | bilgi (1+4) | 79 | 1.84 | +296.1 | +376.3 | -80.1 | 1.15 | +74.0 | evet | ölçüt 2 başarısız |
| btc_keltner_geri_htf M5 | bilgi (2+4) | 481 | 1.18 | +318.6 | +2.2 | +316.5 | 0.52 | -1237.7 | hayır | ölçüt 1 ve 3 başarısız |
| btc_keltner_geri_htf M15 | bilgi (2+4) | 122 | 1.23 | +79.5 | +14.5 | +65.0 | 0.74 | -117.2 | hayır | ölçüt 1 ve 3 başarısız |

Komutlar (BTC için `--cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols --slip-pips 10"`, `--tur dogrulama_slip_btc_m5` / `_m15`):

```
python scripts/replay_strateji_tarama.py --tur dogrulama_slip_fx_m15 --tfs m15 --strategies fx_donchian_gunluk --symbols GBPJPY,EURJPY,USDCAD --jobs 4 --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json --slip-pips 1"
```

Yorum: GBPJPY adayı 1 pip kaymayı kaldırmıyor (net +73.9 -> -27.4). Yalnız aday GBPJPY için kayma koşumu şart koşulmuştu; EURJPY, USDCAD ve BTC Keltner koşumları bilgi amaçlıdır, aday seçimini değiştirmez. EURJPY/USDCAD Donchian kaymada PF 1.15-1.19 ile dayanıyor, ama biri ilk, diğeri son yarıda negatif; kazanma oranları ~%70 ve PF düşük (trailing kuyruk riski). İleri test gözlemi olarak not edilebilir, sonuç sayılmamalıdır.

## 6. Risk ölçekleme

Günlük P&L risk yüzdesiyle lineer ölçeklendi (FX taban %5, BTC taban %2). Hücreler: hedef gün (>= +500) / iflas günü (<= -700), 14 hafta penceresinde. Lineer varsayım pozisyon boyutu yuvarlama, marjin ve ardışık kayıp etkilerini yok sayar.

| Hücre | Risk %2 | %5 | %10 | %20 | %20'de 14h net (USD) | %20'de en kötü gün |
|---|---|---|---|---|---|---|
| GBPJPY Donchian M15 (aday) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | +295.7 | -188.0 |
| EURJPY Donchian M15 (bilgi) | 0 / 0 | 0 / 0 | 0 / 0 | 2 / 0 | +961.6 | -244.2 |
| USDCAD Donchian M15 (bilgi) | 0 / 0 | 0 / 0 | 1 / 0 | 1 / 0 | +1184.6 | -124.6 |
| BTC Keltner M5 (bilgi) | 0 / 0 | 0 / 0 | 0 / 0 | 7 / 2 | +3186.5 | -809.5 |
| BTC Keltner M15 (bilgi) | 0 / 0 | 0 / 0 | 0 / 0 | 1 / 0 | +795.5 | -388.3 |

Okuma: tek aday GBPJPY için %20 riskte bile hedef gün 0; işlem yapılan günlerin ortalaması taban riskte +2.6 USD/gün (1000 USD üzerinde ~%0.26). +500 USD/gün ortalamaya ulaşmak için yüzlerce kat risk gerekir. Hedef günlerin görüldüğü hücrelerde (USDCAD, EURJPY, BTC Keltner) bunlar kuyruk günlerinden gelir ve ölçütleri geçmez; BTC Keltner M5'te %20 risk 7 hedef gün getirirken 2 iflas günü demektir, 10 USD kaymada ise net negatife döner. Hedefe varan tek yol, kanıtlanmamış kenarın üzerine daha çok kaldıraç koymak olurdu.

## 7. Sınırlar

- **Tek rejim, 14 hafta:** Tüm veri 2026 Q3-Q4 tek dönemden (~128-130 gün); hiçbir hücre dış örneklem (farklı rejim/dönem) testi görmedi.
- **Çoklu karşılaştırma:** 74 hücre test edildi. >= 60 işlemli 11 hücrenin 3'ü PF >= 1.3 (%27); kısa örneklemde PF'nin standart sapması ~0.5 olduğundan yalnız şansla 74 hücrenin kabaca dörtte biri PF >= 1.3 verir. Ölçüt 2 bu kümeyi 1 hücreye, ölçüt 3 ise 0'a indirdi. Bu sonuç "kenar yok" ile uyumludur; "kenar var ama kaçırıldı" kanıtı da yoktur.
- **Kapı etkileşimleri:** Motorun canlı kapıları (min_score, rr_floor, headroom, ADX >= 20, QUALITY, spread) eklentilerin ham sinyalini eler; özellikle ortalamaya dönüş (bb_donus) ADX kapısıyla yapısal çelişiyor. Task 3 tanı koşumları (`fx_yeni_adx0`, `fx_yeni_nogate`, `fx_yeni_nq`) kapıları kapatmanın sonucu genel olarak iyileştirmediğini gösterdi; aday seçiminde kullanılmadı.
- **Yüksek kazanma oranı, düşük PF:** WR %65-90 ama PF ~1; motorun BE/trailing/kısmi çıkış mantığı stratejilerin kendi R/ödül yapısını ezmiş olabilir, ham sinyal kalitesi bu tabloyla tam ölçülmüyor.
- **Donchian ısınması:** Günlük EMA50 yaklaşık 50 iş günü veri ister (ilk işlem ~08-19); ilk 7 hafta yarısı kısa kalıyor.
- **Hücre güvenilirliği:** `btc_seans_kirilim` sayıları güvenilmez; `btc_keltner_geri_htf` adı gerçek mantığı (EMA20-pullback) yansıtmıyor.
- **Kayma modeli:** FX 1 pip, BTC 10 USD, her bacakta sabit; gerçek kayma (haber anı, düşük likidite) daha kötü olabilir.

## 8. Karar ve sonraki adım

1. **Hiçbir hücre canlıya veya paper'a alınmıyor.** Robust kenar sayısı 0; günlük +%50 hedefi bu stratejilerle ulaşılabilir değil (işlem günü ortalaması taban riskte yaklaşık +0.1..+1.8%).
2. `fx_bb_donus_m30` canlı kapılarla çalışmaz; yeniden denenecekse önce motorun eklenti başına ADX/QUALITY kapısını devre dışı bırakabilmesi (kontrolör kararı) gerekir. Mevcut sonuç aday değildir.
3. `fx_donchian_gunluk` pozitif hücre içeren tek aile, ama kanıt zayıf: M15'te EURUSD, GBPUSD, USDJPY ve USDCHF güçlü negatif (PF 0.20-0.53, net -62 ile -213 USD); M15 parite toplamı yalnız yaklaşık +23 USD, M30 toplamı yaklaşık +170 USD (M30'da da 5 parite negatif). Pozitif hücreler (USDCAD, EURJPY, GBPJPY, M30 USDCHF) 3-5 pariteden sonradan seçilmiştir ve sonuç pariteye özgüdür; genel bir "FX trendi" kanıtı değildir. GBPJPY kayma testinde düştü. Devam edilecekse: daha uzun veriyle (MT5 `ingest-rates`, tercihen >= 12 ay, farklı rejimler) dış örneklem testi, aynı ölçütler değiştirilmeden ve kayma stresiyle; ancak o zaman ileri test düşünülebilir.
4. BTC Keltner (EMA20-pullback) maliyete duyarlı: 10 USD kaymada çöküyor; tekrar denenecekse önce gerçek BTC spread/kayma ölçümü yapılmalı.
5. Negatif sonuç geçerli bir sonuçtur: 74 hücrelik tarama günlük +%50 hedefine dayanak olacak bir kenar üretmedi.
