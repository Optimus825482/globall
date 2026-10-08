# FX TREND-SCALPING — M15 ZAMAN-DILIMI MERDIVENI (ORB + JPY KOLLARI)
## Kapı + maliyet eşiğinin M15'e taşınması: replay kanıtı

- **Tarih:** 2026-10-08 · **Sahip:** Erkan
- **Motor:** `scripts/forex_replay_backtest.py` · **Sürücü:** `scripts/fx_m15_ladder_windows.py` · **Cache üretici:** `scripts/fx_build_m15_cache.py`
- **Veri:** `outputs/replay_cache_60d_fxwide_m15.json` (34 sembol, 15m; 5m cache'in 3'er barı indirgenmiş) — 2026-07-15 23:00 → 2026-10-07 07:45 UTC
- **Kapsam:** 12 FX çifti izole defter (XAU/BTC/endeks hariç) · JPY kolu = GBPJPY+EURJPY · 99 eşzamanlı slot · maliyet = **gerçek p95 spread profili** (`outputs/fx_spread_p95.json`, 2× stres: `fx_spread_p95_x2.json`) · `--skip-old`
- **Baraj (protokol):** ≥2 ayrık pencerede pozitif **+** OOS (L30) pozitif **+** ≥100 işlem **+** 2× maliyet stresinde ayakta kalma
- **Karar özeti:** **M15 merdiveni de barajı GEÇMEDİ.** Tek bir kol dışında tüm adaylar 2× maliyet altında negatife döndü; o kol da OOS'ta negatif.

---

## 0. EN ÖNEMLİ ÜÇ BULGU

1. **`--interval 15m` + `--cache` SESSİZCE 5m koşar.** Motorda `--interval` yalnızca Yahoo fetch URL'ini değiştirir; önbellek verildiğinde yeniden örnekleme yapılmaz ve rapora bar boyu yazılmaz. Bu yüzden M15 testi için **gerçek 15m cache** üretildi (`scripts/fx_build_m15_cache.py`); aksi halde "M15" sonucu sahte olurdu.
2. **FX'te BE tetiği pip-kuralı değil, DOLAR kuralıdır** (`$1 + headroom`, `forex_replay_backtest.py:1079-1099`). Bu yüzden 5m için kalibre edilmiş mesafeyi `--be-pips` ile "esnetmek" işe yaramaz (bkz. 5.1: X kolu = M kolu, birebir aynı sonuç). Gerçek A/B için motora `--be-usd-fx 0` (dolar-kuralı BE'yi kapat) eklendi.
3. **2× maliyet stresi varsayılan ayarlarla GÜVENİLMEZ**: motorun 3.0-pip spread kapısı 2× profilde EURNZD/GBPNZD girişlerini tamamen keser, yani işlem kümesi değişir. Temiz stres için `--max-spread 99` ile kapı izole edildi. **Bu izole testte bütün M15 adayları çöktü.**

---

## 1. YÖNTEM VE DÜZELTİLEN TUZAK

### 1.1 Gerçek 15m barlar üretildi (zorunlu)
`forex_replay_backtest.py` içinde `--interval` yalnızca Yahoo Finance istek URL'ini değiştirir (`:878`, `:882`, `:2587-2589`);
`--cache` verildiğinde **yeniden örnekleme yapılmaz** (`:2825-2837`). Yani `--interval 15m --cache <5m dosyası>` çağrısı sessizce **5m barlarla** koşar ve raporda bar boyu alanı olmadığı için (`:2885`) çıktı sahte-M15 olarak arşivlenebilir.
→ Bu turda `scripts/fx_build_m15_cache.py` ile 3×5m → 1×15m indirgeme yapıldı: **`outputs/replay_cache_60d_fxwide_m15.json`** (34 sembol, sembol başına ~5.628 bar; 5m'de ~16.885).
→ `orb_ny` modunun "kutuda ≥20 bar" şartı (`:606`) 15m'de 07-13 kutusu = 24 bar ile **ilk kez sağlanıyor**; 5m'de aynı kutu 72 bar idi. Bu, 15m'de ORB'nin gerçekten koşabildiği ilk tur.

### 1.2 Ölçekleme (neden 1.7?)
BE/trail spec mesafeleri 5m için kalibre (BE=14 pip, trail=20 pip; `forex_replay_backtest.py:48-49`). Bu depoda 12 FX çifti / 24 Ağu-7 Eki ölçümü: **ATR(14) 15m ÷ 5m medyan oranı = 1.735** (teorik √3 = 1.732; çift aralığı 1.23-2.13).
→ 15m kolu için ölçekli çıkış: **BE 14 → 24 pip, trail 20 → 35 pip**. `--rel-atr-lookback` 576 → **192** (2 gün korunur).

### 1.3 Pencereler
| Kod | Aralık | Rol |
|---|---|---|
| U3 | 16 Tem – 1 Ağu | görülmemiş (veri başı; H1 ısınma payı kısa) |
| W1 | 25 Tem – 10 Ağu | görülmemiş |
| PX | 10 – 31 Ağu | görülmüş |
| AU | 1 Ağu – 14 Eyl | görülmüş (geniş) |
| **L30** | **7 Eyl – 7 Eki** | **protokol OOS** |

---


## 2. M15 ANA TARAMA (1x p95 MALİYET)


**Tablo A — M15 ana tarama (1x p95 maliyet, varsayilan spread kapisi 3.0 pip)**

| Konfig | U3 (n) | W1 (n) | PX (n) | AU (n) | L30 (n) | Poz/N | Σ n |
|---|---|---|---|---|---|---|---|
| M1 ORB + trail2.5 + H1 kapi | **+36.39** (40) | **+93.95** (35) | **-25.15** (42) | **-29.45** (85) | **-101.73** (71) | **2/5** | 273 |
| M2 = M1 + rel-ATR bandi | **+36.39** (40) | **+84.15** (32) | **-25.15** (42) | **-39.25** (82) | **-101.73** (71) | **2/5** | 267 |
| M3 = M1 + 16:00 flat | **+10.81** (40) | **+71.15** (35) | **-4.37** (42) | **+22.26** (85) | **-21.12** (71) | **3/5** | 273 |
| M4 = M1 + bant + flat16 | **+10.81** (40) | **+61.35** (32) | **-4.37** (42) | **+12.46** (82) | **-21.12** (71) | **3/5** | 267 |
| M5 Asya 04-09 -> Londra 09-13 | **+40.96** (45) | **+22.99** (41) | **-35.15** (57) | **-187.91** (123) | **-116.67** (104) | **2/5** | 370 |
| M6 = M1 sabit 1.5R TP (kontrol) | **+36.39** (40) | **+97.63** (35) | **-21.55** (42) | **-24.72** (85) | **-99.65** (71) | **2/5** | 273 |
| M7 JPY Donchian+ADX + H1 + bant | **+14.40** (26) | **+17.07** (17) | **+13.14** (36) | **+57.31** (64) | **+17.75** (42) | **5/5** | 185 |
| M8 JPY Donchian saf + chand2.5 + H1 + bant | **+11.45** (20) | **+42.19** (21) | **-59.95** (34) | **+52.43** (68) | **+23.88** (45) | **4/5** | 188 |
| M9 = M7 + 16:00 flat | **+27.07** (26) | **+20.12** (17) | **+12.66** (36) | **+56.83** (64) | **+14.73** (42) | **5/5** | 185 |
| M10 = M7 bantsiz | **+10.15** (28) | **+40.88** (31) | **+5.04** (42) | **+91.52** (87) | **+10.35** (56) | **5/5** | 244 |
| M11 JPY kapi/band YOK (kontrol) | **+13.66** (58) | **+59.65** (62) | **-39.51** (85) | **+3.05** (178) | **+57.48** (128) | **4/5** | 511 |

**Okuma (Tablo A, 1× p95 maliyet):**
- **JPY kolu en güçlü görünen**: M7 (Donchian+ADX+H1 kapı+bant) ve M10 (bantsız) **5/5 pencerede pozitif**; M8 4/5. Ancak işlem sayıları küçük (17-87/pencere) ve **çıkışların %66-75'i BE** (yani kâr, mikro-BE mekaniğinden geliyor), net kazanç işlem başına **+0,10 … +1,05 $**.
- **ORB kolu**: M1 (çıplak trail) 2/5 ve OOS **−101,73**; **M3 (M1 + 16:00 flat) 3/5**, OOS −21,12; M5 (Asya→Londra kutusu) 2/5 ve AU'da −187,91 (en kötü).
- **`--rel-atr-band` [0.8×, 3.0×] 15m'de çoğu pencerede bağlamıyor**: M2 ile M1 U3/PX/L30'da **birebir aynı**; yalnız W1 (+93,95 → +84,15) ve AU (−29,45 → −39,25) pencerelerinde bağlıyor ve etkisi **negatif**. M4 ile M3 de aynı desen. Doğrulama: bandı [5.0×, 6.0×] yapınca 0 işlem ve **RELATR 44 aday elendi** → kapı çalışıyor, marjı çok geniş (15m ATR medyana daha yakın).
- **M6 (sabit 1.5R TP) ile M1 işaret değiştirmiyor**: farklar tek haneli (W1 +97,63 vs +93,95; PX −21,55 vs −25,15; L30 −99,65 vs −101,73) → sabit TP'yi kaldırmak M15'te de anlamlı bir kenar üretmiyor.

---

## 3. ÇIKIŞ MİMARİSİ A/B (kullanıcı sorusunun M15 ayağı)

### 3.1 İlk deneme boşa çıktı — ve bu bir bulgu
X kolu, "BE'yi ATR'ye ölçekle" hipotezini `--be-pips 24 --trail-pips 35` ile test etti. Sonuç: **M koluyla birebir aynı** (tüm pencerelerde n, net, PF, exit dağılımı aynı). Nedeni `:1079-1099` — FX'te BE tetiği bir **dolar** kuralıdır (`$1 + headroom`), `eff_be_pips` sadece ek `or` koşuludur. Yani "BE'yi büyütmek" mümkün değildi.

### 3.2 Gerçek A/B: dolar-kuralı BE kapatıldı
Motora `--be-usd-fx` eklendi (varsayılan 1.0 = canlı davranış; 0 = dolar-kuralı BE kapalı).

**Tablo B — X kolu: `--be-pips 24` (dolar-kurali BE acikken) — ETKISIZ**

| Konfig | U3 (n) | W1 (n) | PX (n) | AU (n) | L30 (n) | Poz/N | Σ n |
|---|---|---|---|---|---|---|---|
| X1 = M1 + be-pips 24 (ETKISIZ - bkz. 5.1) | **+36.39** (40) | **+93.95** (35) | **-25.15** (42) | **-29.45** (85) | **-101.73** (71) | **2/5** | 273 |
| X2 = M4 + be-pips 24 (ETKISIZ) | **+10.81** (40) | **+61.35** (32) | **-4.37** (42) | **+12.46** (82) | **-21.12** (71) | **3/5** | 267 |
| X3 = M7 + be-pips 24 (ETKISIZ) | **+14.40** (26) | **+17.07** (17) | **+13.14** (36) | **+57.31** (64) | **+12.36** (42) | **5/5** | 185 |
| X4 = M8 + be-pips 24 (ETKISIZ) | **+11.45** (20) | **+42.19** (21) | **-59.95** (34) | **+52.43** (68) | **+23.88** (45) | **4/5** | 188 |

**Tablo C — Y kolu: cikis mimarisi A/B (dolar-kurali BE kapatildi)**

| Konfig | U3 (n) | W1 (n) | PX (n) | AU (n) | L30 (n) | Poz/N | Σ n |
|---|---|---|---|---|---|---|---|
| Y1 = M1, dolar-kurali BE KAPALI | **+10.45** (40) | **+72.82** (35) | **-62.64** (42) | **-151.21** (85) | **-147.88** (71) | **2/5** | 273 |
| Y2 = M1 + pip-BE 24 (dolar BE kapali) | **+35.71** (40) | **+30.60** (35) | **-28.92** (42) | **-153.75** (85) | **-174.52** (71) | **2/5** | 273 |
| Y3 = M3 + pip-BE 24 (dolar BE kapali) | **+31.63** (40) | **+70.83** (35) | **+23.97** (42) | **+63.54** (85) | **-3.24** (71) | **4/5** | 273 |
| Y4 = M7, dolar-kurali BE KAPALI | **-5.30** (24) | **-21.89** (15) | **+15.21** (36) | **+71.22** (64) | **+23.03** (42) | **3/5** | 181 |
| Y5 = M7 + pip-BE 24 (dolar BE kapali) | **-46.25** (24) | **-40.49** (15) | **+20.29** (36) | **+42.32** (64) | **-30.11** (42) | **2/5** | 181 |

**Okuma (Tablo C):**
- **ORB**: dolar-BE'yi kapatmak (Y1) OOS'u −101,73 → **−147,88**'e kötüleştirdi; ama **flat16 + 24-pip pip-BE** (Y3) ile ORB **4/5 pozitif** ve OOS **−3,24** (M3'te −21,12). Aynı giriş sinyali, üç farklı çıkış mimarisi, OOS'ta −147,88 / −21,12 / **−3,24**.
- **JPY**: dolar-BE'yi kapatmak (Y4) U3/W1'de kötüleştirdi (5/5 → 3/5), OOS hafif iyileşti (+17,75 → +23,03). 24-pip pip-BE (Y5) JPY'de net kötü.
- Sonuç: **çıkış mimarisi giriş sinyalinden daha belirleyici**, ama "daha geniş çıkış daha iyi" diye tek yönlü bir kural yok; etki çift/kol bazlı.

---

## 4. TEMİZ MALİYET STRESİ (2× p95)

### 4.1 Varsayılan stres neden güvenilmez
Motorun giriş kapısı `spread_pips > max_spread` (`:2226`), FX için `max_spread = 3.0` (`:2109`). 2× profilde **EURNZD (1,7→3,4)** ve **GBPNZD (2,1→4,2)** girişleri **tamamen kesilir**; işlem kümesi değişir (ör. M3 L30: n=71 → 49). Bu yüzden varsayılan 2× sonucu likidite/maliyet kıyası değil, **farklı bir strateji** kıyasıdır.
→ Kapı `--max-spread 99` ile izole edildi; 1× ve 2× kolları **aynı işlem kümesini** görür (kalan n farkı ≤3, EV-kalkanının geri beslemesinden).

### 4.2 İzole 1× kontrol (Tablo D) — M kollarıyla birebir
Kapı izolasyonu tek başına sonucu değiştirmiyor (1×'te hiçbir çift 3,0 pip'i aşmıyor) → D ≡ A.

### 4.3 İzole 2× stres (Tablo E) — BARİYERİN KIRILDIĞI YER

**Tablo D — C kolu @1x maliyet, izole kapi (`--max-spread 99`)**

| Konfig | U3 (n) | W1 (n) | PX (n) | AU (n) | L30 (n) | Poz/N | Σ n |
|---|---|---|---|---|---|---|---|
| C1 = M3 (1x/2x izole kapi) | **+10.81** (40) | **+71.15** (35) | **-4.37** (42) | **+22.26** (85) | **-21.12** (71) | **3/5** | 273 |
| C2 = M7 (1x/2x izole kapi) | **+14.40** (26) | **+17.07** (17) | **+13.14** (36) | **+57.31** (64) | **+17.75** (42) | **5/5** | 185 |
| C3 = M8 (1x/2x izole kapi) | **+11.45** (20) | **+42.19** (21) | **-59.95** (34) | **+52.43** (68) | **+23.88** (45) | **4/5** | 188 |
| C4 = M10 (1x/2x izole kapi) | **+10.15** (28) | **+40.88** (31) | **+5.04** (42) | **+91.52** (87) | **+10.35** (56) | **5/5** | 244 |

**Tablo E — C kolu @2x maliyet, izole kapi (`--max-spread 99`) — TEMIZ STRES**

| Konfig | U3 (n) | W1 (n) | PX (n) | AU (n) | L30 (n) | Poz/N | Σ n |
|---|---|---|---|---|---|---|---|
| C1 = M3 (1x/2x izole kapi) | **+16.61** (40) | **+72.17** (35) | **-9.89** (42) | **-4.32** (85) | **-25.28** (71) | **2/5** | 273 |
| C2 = M7 (1x/2x izole kapi) | **-5.64** (25) | **+6.05** (17) | **-8.88** (35) | **+30.41** (63) | **-11.62** (43) | **2/5** | 183 |
| C3 = M8 (1x/2x izole kapi) | **+1.39** (20) | **+37.63** (21) | **-74.52** (34) | **+5.19** (68) | **+0.10** (45) | **4/5** | 188 |
| C4 = M10 (1x/2x izole kapi) | **-10.28** (27) | **+26.84** (31) | **-19.10** (40) | **+58.85** (85) | **-21.63** (57) | **2/5** | 240 |

**Okuma (Tablo E) — 2× p95 maliyet, aynı işlem kümesi:**
- **C2 (M7, JPY, 1×'te 5/5) → 2/5 ve OOS +17,75 → −11,62.** C4 (M10, 5/5) → 2/5, OOS +10,35 → −21,63.
- C3 (M8) → 3/5, OOS +23,88 → **+0,10** (PF 1.00).
- C1 (ORB+flat16) → 3/5, OOS −21,12 → −25,28.
- **Hiçbir kol OOS'ta pozitif kalmıyor.** 5/5 olan JPY kollarının tüm fazlası maliyet farkına eşit ya da ondan küçük: işlem başına +0,42 $ kâr, 2× maliyette −0,28 $'a dönüyor.

### 4.4 En iyi çıkış mimarisi bile 2×'te düşüyor (Tablo F)

**Tablo F — Z kolu: en iyi cikis mimarileri @2x maliyet (izole kapi)**

| Konfig | U3 (n) | W1 (n) | PX (n) | AU (n) | L30 (n) | Poz/N | Σ n |
|---|---|---|---|---|---|---|---|
| Z1 = Y3 @2x maliyet | **+24.46** (40) | **+59.38** (35) | **+14.44** (42) | **+25.48** (85) | **-44.91** (71) | **4/5** | 273 |
| Z2 = Y4 @2x maliyet | **-25.08** (23) | **-30.91** (15) | **+14.49** (34) | **+57.19** (61) | **-4.51** (43) | **2/5** | 176 |
| Z3 = Y5 @2x maliyet | **-50.53** (24) | **-43.61** (15) | **+19.66** (34) | **+29.50** (61) | **-47.72** (43) | **2/5** | 177 |

**Okuma (Tablo F):** Z1 (ORB, flat16 + 24-pip pip-BE, dolar-BE kapalı) 1×'te 4/5 ve OOS −3,24 iken 2×'te OOS **−44,91**. Z2/Z3 (JPY) 2/5. **M15'te 2× maliyete dayanan tek bir kol yok.**

### 4.5 Referans: confounded 2× kolu (Tablo G)
Kapı açıkken koşulan 2× kolu, kaybedilen likidite nedeniyle bazı pencerelerde **daha iyi** görünüyor (ör. S2 L30 +19,88 vs izole C1 −25,28). Bu, "2× maliyet iyileştirir" demek değil; **işlem kümesinin daralmasının** artefaktıdır. Kanıt olarak kullanılmamalıdır.

**Tablo G — S kolu @2x maliyet, VARSAYILAN kapi (confounded; kiyas icin)**

| Konfig | U3 (n) | W1 (n) | PX (n) | AU (n) | L30 (n) | Poz/N | Σ n |
|---|---|---|---|---|---|---|---|
| S1 = M1 @2x (kapi ACIIK - confounded) | **+26.90** (35) | **+72.69** (30) | **-21.96** (37) | **-43.29** (73) | **-40.40** (49) | **2/5** | 224 |
| S2 = M3 @2x (kapi ACIIK - confounded) | **+0.66** (35) | **+55.40** (30) | **+4.68** (37) | **+12.54** (73) | **+19.88** (49) | **5/5** | 224 |
| S3 = M7 @2x (kapi ACIIK - confounded) | **-5.64** (25) | **+6.05** (17) | **-8.88** (35) | **+30.41** (63) | **-11.62** (43) | **2/5** | 183 |
| S4 = M8 @2x (kapi ACIIK - confounded) | **+1.39** (20) | **+37.63** (21) | **-74.52** (34) | **+5.19** (68) | **+0.10** (45) | **4/5** | 188 |
| S5 = M10 @2x (kapi ACIIK - confounded) | **-10.28** (27) | **+26.84** (31) | **-19.10** (40) | **+58.85** (85) | **-21.63** (57) | **2/5** | 240 |

---

## 5. YÖNTEM NOTLARI VE TUZAKLAR (kanıtlı)

### 5.1 `--be-pips` neden etkisiz kaldı
`forex_replay_backtest.py:1079-1099`: FX için BE tetiği `pips_be = 1/(lots×pip_val)` + `headroom` (varsayılan 3.5 pip) ile **dolar** kuralıdır; `eff_be_pips` yalnızca **ek** bir `or` koşuludur. Dolayısıyla BE tetiğini büyütmek için dolar kuralını kapatmak gerekir.
**Kanıt:** X kolu (M1/M3/M7/M8 + `--be-pips 24 --trail-pips 35`) sonuçları M koluyla **birebir aynı** (n, net, PF, exit dağılımı). Tablo B vs Tablo A.

### 5.2 Ampirik ATR ölçekleme oranı (neden 1.7?)
Bu depo, 12 FX çifti, 24 Ağu–7 Eki: ATR(14) 15m/5m medyan oranı = **1.735** (teorik √3 = 1.732). Çift bazında 1.23 (EURCHF) – 2.13 (NZDUSD).
→ 15m kolu için ölçekli çıkış mesafesi: BE **14 → 24 pip**, trail **20 → 35 pip**.

### 5.3 Bağımsız harness denetimi (subagent, salt-okuma)
`outputs/fx_trend_research/M15_harness_audit.md` — 15m'de anlamı değişen **8 kritik** nokta + 17 yorum uyarısı:
- `time_stop_bars = H×12` (5m varsayımı) → 15m'de süre 3× olur (`:730`, `:823`).
- `_adr_pips` penceresi `12*24*days` → 14 gün yerine ~53 gün (`:329`).
- `_htf_st_map` 900 sn kovası → 15m'de "HTF" kapısı aynı-TF SuperTrend'e dönüşür (`:1474-1489`).
- `orb_filtered` (15 dk kutu) ve `tokyo_fix` (00:50-01:00) 15m'de **0 aday** üretir.
- `--rel-atr-band` medyan penceresi (576 bar) 2 gün yerine ~8 gün olur; bu koşuda `--rel-atr-lookback 192` ile düzeltildi.
- `--htf-ema200-gate` **etkilenmez** (H1 EMA200 gerçek saatlik kovalardan hesaplanır).
- Rapor `config` alanında bar boyu / cache dosyası yok → sahte M15 arşivlenebilir.

### 5.4 Örneklem gücü uyarısı
7 günlük pencere 5m'de ~2.016, 15m'de ~672 bar; işlem sayısı tipik olarak **~3× azalır**. U3/W1 pencereleri veri setinin en başında olduğu için H1 EMA200 ısınma payı kısadır (kapı yine filtreliyor, ama "tam eşdeğer" sayılmamalı). U3 ⊂ W1 olduğu için "5/5 pozitif" ifadesi ~4 ayrık pencereye karşılık gelir.

### 5.5 Bu turda motora eklenen (varsayılanı DEĞİŞTİRMEYEN) araştırma anahtarları
`--be-usd-fx` (1.0 = canlı), `--be-pips` (0 = spec), `--trail-pips` (0 = spec), `--max-spread` (3.0 = canlı). Dördü de varsayılanda **eski davranışı birebir korur**; hiçbiri canlı politikaya bağlı değildir.


**Regresyon kontrolü (yapıldı):** yeni anahtarların hiçbiri verilmeden, 5m varsayılan yolda daha önceki bir sonuç birebir tekrar üretildi — `A2_orb_trail25_h1` L30: **n=66, net −44,19 $, PF 0,68** (hem yeni hem eski koşuda aynı). Yani canlı davranış değişmedi.

---

## 6. KARAR

| Kol | 1× maliyet | 2× maliyet (izole) | Baraj | Karar |
|---|---|---|---|---|
| ORB M15 + trail + H1 kapı (M1) | 2/5 (OOS −101,73) | S1 2/5 (OOS −40,40) | ✗ | **RED** |
| ORB M15 + flat16 (M3/C1) | 3/5 (OOS −21,12) | C1 3/5 (OOS −25,28) | ✗ | **RED** |
| En iyi ORB çıkış mimarisi (Y3/Z1) | **4/5** (OOS −3,24) | Z1 4/5 (**OOS −44,91**) | ✗ | **PAPER-ONLY (izleme)** |
| JPY Donchian+ADX + H1 kapı (M7/C2) | **5/5** (OOS +17,75) | C2 2/5 (**OOS −11,62**) | ✗ | **RED** |
| JPY Donchian+ADX + H1 (M10/C4) | **5/5** (OOS +10,35) | C4 2/5 (**OOS −21,63**) | ✗ | **RED** |
| JPY Donchian saf + chand (M8/C3) | 4/5 (OOS +23,88) | C3 3/5 (OOS +0,10) | ✗ | **RED** |
| JPY + ölçekli pip-BE (Y4/Y5) | 3/5 | Z2/Z3 2/5 (OOS −4,51 / −47,72) | ✗ | **RED** |

**Kanıtla sabitlenen üç teknik bulgu:**
1. **H1 EMA200 kapısı M15'te de tek başına kâr üretmiyor** ama zararı küçültmeye devam ediyor (JPY kontrol M11 3/5 → kapılı M7 5/5 @1×; ORB'da M1 → M2 ... M3 yönünde iyileşme).
2. **16:00 UTC flat (flat16) ORB'da sistematik iyileştirme**: M1→M3 beş pencerenin dördünde iyileşti (ör. PX −25,15 → −4,37; AU −29,45 → +22,26).
3. **Çıkış mimarisi, giriş sinyalinden daha belirleyici**: aynı ORB girişiyle dolar-BE'yi kapatıp 24-pip pip-BE'ye geçmek (Y3) OOS'u −21,12 → −3,24'e taşıdı; buna karşılık dolar-BE'yi kapatıp pip-BE **koymamak** (Y1) OOS'u −147,88'e düşürdü. Yani kazanç "geniş çıkış" değil, **"mikro-BE ölçeğinin doğru ayarı"**ndan geliyor.

**Neden M15 avantajı beklenen yönde çıkmadı:** bağımsız web araştırması (`outputs/fx_trend_research/A10_m15_vs_m5.md`) da aynı yönde: ES ORB'da devam oranı 5dk %63,3 → 15dk %65,8 / 30dk %70,7 **artıyor**, ama **medyan maksimum uzama ORB genişliğinin 1,62× → 0,85× → 0,54× katına düşüyor**; yani "daha az sahte kırılım, işlem başına daha kötü R". Backtrex 10 yıllık GBPUSD **M15** Asya-kutusu→Londra kırılımı: 2.432 işlem, PF 0,72, **−%60**; aynı ailenin EURUSD **H1** hali 1.230 işlem, PF 0,87, −%28. [UYGULAYICI] Gaona ve ark. (Frontiers, 2026): 10 FX çiftinin tamamı 30-dk ufkunu seçti ama **maliyet sonrası FX majörlerinin hepsi negatif** (−0,0048% … −0,0159% işlem başına). [AKADEMIK]

**Canlı politika:** DEĞİŞMEDİ. Hiçbir M15 kolu paper dışına çıkarılmadı, parametre sabitlenmedi.

---

## 7. ARTEFAKTLAR

| Ne | Yol |
|---|---|
| 15m cache | `outputs/replay_cache_60d_fxwide_m15.json` |
| Cache üretici | `scripts/fx_build_m15_cache.py` |
| M15 sürücü (dalgalar: m15, m15exit, m15exit2, m15stress, m15cost1-3) | `scripts/fx_m15_ladder_windows.py` |
| Ham sonuçlar | `outputs/fxsweep3/*.json` + `_summary_*.json` + `_log_*.txt` |
| 2× maliyet profili | `outputs/fx_spread_p95_x2.json` |
| Bağımsız harness denetimi | `outputs/fx_trend_research/M15_harness_audit.md` |
| Zaman-dilimi merdiveni web araştırması | `outputs/fx_trend_research/A10_m15_vs_m5.md` |
| Önceki kollar | `docs/FX_TREND_SCALPING_TOP5_2026-10-08.md`, `docs/FX_TREND_SCALPING_TAKIP_2026-10-08.md` |
