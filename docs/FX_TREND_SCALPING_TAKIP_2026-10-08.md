# TAKİP İŞİ — (1) ORB kolu çıkış mimarisiyle, (2) JPY kolu 2 ek pencere
**Tarih:** 2026-10-08 · **Motor:** `scripts/forex_replay_backtest.py` · **Sürücü:** `scripts/fx_orb_exit_jpy_windows.py`
**Ayarlar (ortak):** 12 FX çifti (izole defter, XAU/BTC/endeks hariç), 99 slot, **gerçek p95 spread profili** (`outputs/fx_spread_p95.json`), 5m kapanmış mumlar, `--skip-old`.

---

## 0. ÖZET KARAR

| İstek | Sonuç | Durum |
|---|---|---|
| (1) ORB + araştırmanın önerdiği çıkış mimarisi | Çıkış değişikliği (sabit TP kapat → chandelier trailing / 10R hedef) ORB'u **kurtarmadı**. Asıl iyileştirme **H1 EMA200 kapısı**ndan geldi: `A2` 6 pencerenin 3'ünde pozitif. Ama protokolün OOS penceresi (7 Eyl–7 Eki) **−44,19 $** ve çapraz pencere −20,76 $ → **baraj geçilmedi**. | **REDDEDİLDİ (aktivasyon) / PAPER-ONLY** |
| (2) JPY kolu, 2 ek (hiç görülmemiş) pencere | İki yeni pencerede de **negatif**: U1 (16–24 Tem) `jp_dp_h1` −14,78 / `jp_da_h1` −14,87; U2 (24–31 Tem) −?/+0,70 / −24,77. 6 pencerenin 4'ü negatif → pencere şansı. | **REDDEDİLDİ (aktivasyon)** |

**Tek cümle:** FX'te trend-scalping ailelerinin hiçbiri, gerçek spread maliyeti altında, **birden fazla ayrık pencerede tutarlı** pozitif üretmedi. H1 EMA200 kapısı en faydalı tekil iyileştirme olarak doğrulandı (ORB'u 6 pencerede 0/6'dan 3/6'ya taşıdı, JPY'de de zararı küçültüyor) — ama tek başına kenar yaratmıyor.

---

## 1. İŞ 1 — ORB KOLU: ÇIKIŞ MİMARİSİ DENEMESİ

**Hipotez (A1/A5/A8 araştırması):** "Sabit TP trendi öldürür" → sabit 1,5R TP yerine (a) chandelier trailing, (b) 10R hedef, (c) seans sonu flat denenmeli.

**Pencereler:** PX 10–31 Ağu (görülmüş) · XV 10 Ağu–7 Eyl (görülmüş) · L30 7 Eyl–7 Eki (protokol OOS) · **U1 16–24 Tem (görülmemiş)** · **U2 24–31 Tem (görülmemiş)** · **U3 16 Tem–1 Ağu (görülmemiş)**

| Konfig | U1 | U2 | U3 | PX | XV | L30 | Poz/N |
|---|---:|---:|---:|---:|---:|---:|---:|
| **A1** trail 2,5×ATR, TP yok | −32,22 (29) | −9,91 (40) | −42,13 (69) | −53,40 (74) | −65,68 (102) | −126,72 (106) | **0/6** |
| **A2** A1 + **H1 EMA200 kapısı** | −15,87 (21) | **+24,78** (23) | **+8,91** (44) | **+1,26** (39) | −20,76 (56) | −44,19 (66) | **3/6** |
| **A4** 10R sabit hedef (trail yok) | −36,29 (29) | −21,01 (40) | −57,30 (69) | −51,48 (74) | −72,43 (102) | −162,06 (106) | **0/6** |
| **A6** A2 + genişlik [0,25–1,5]×ATR | 0 işlem | 0 işlem | 0 işlem | 0 işlem | 0 işlem | – | – |
| **C1** Londra 07–09 kutusu → 09–16 + trail + H1 | −32,92 (25) | −43,67 (28) | −76,59 (53) | −18,40 (66) | −108,71 (97) | −152,98 (109) | **0/6** |
| **C2** C1 + 16:00 UTC flat | −32,20 (25) | −43,67 (28) | −75,87 (53) | −18,40 (66) | −108,71 (97) | – | **0/5** |
| **C3** genişlik [1,0–4,0]×ATR + trail + H1 | +6,60 (**n=5**) | −7,16 (9) | −0,56 (14) | −11,30 (14) | −14,39 (24) | – | n yetersiz |

*(parantez içi = işlem sayısı; tüm değerler NET $ ve gerçek p95 spread sonrası)*

### Bulgular
1. **Sabit TP'yi kaldırmak yetmiyor.** A1 (trailing, TP yok) L30'da −126,72 $; aynı pencerede ESKİ sabit 1,5R kurgusu (`orb_tp15`, 30g) −120,65 $ idi → fark yok. A4 (10R hedef, Zarattini tarzı) **en kötü** sonuç (−162,06 $). Zarattini'nin 10R kurgusu hisse endeksinde çalışıyor; FX'te maliyet+whipsaw onu öldürüyor.
2. **Asıl fark kapıdan geliyor.** Tek değişken H1 EMA200 kapısı: A1 → A2 iyileşmesi 6 pencerenin **6'sında** pozitif yönde (−32→−16, −10→**+25**, −42→**+9**, −53→**+1**, −66→−21, −127→−44). Bu, A4 kolunun "kapı PF'i artırır, hacmi düşürür" bulgusunu **bağımsız olarak doğruluyor**.
3. **Kutu seçimi kritik:** Londra 07–09 kutusu → 09–16 devam (C1) **her pencerede negatif**; NY-overlap kutusu (13–16 tetik) daha iyi. Yani A1'in işaret ettiği "Londra açılışı" sinyali, bizim motorun kapanış-bazlı kırılım uygulamasıyla **çalışmıyor** — sinyal değil, uygulama farkı olabilir (SSRN 7008318 sinyali *işaret*/sign bazlıydı, kırılım bazlı değil).
4. **Genişlik filtresi işe yaramadı:** [0,25–1,5]×ATR 6 saatlik kutuda her şeyi eliyor (0 işlem); [1,0–4,0] ise 5–24 işlem bırakıyor → örneklem yok.
5. **Motor kısıtı (şeffaflık):** `orb_ny` implementasyonu kutuda **≥20 bar** şartı koyuyor (`len(box) < 20: return None`). Bu yüzden 1 saatlik kutu (12 bar) tanım gereği 0 işlem üretir — ilk A3/A5 denemeleri bu nedenle boş döndü, düzeltilmiş hali C1/C2'dir.

### Karar
ORB ailesi **aktivasyon barajını geçmedi**: A2 3/6 pencerede pozitif ama **OOS (L30) negatif** ve çapraz pencere negatif. Kapı + trailing kombinasyonu **izleme listesinde kalır**, canlıya alınmaz.

---

## 2. İŞ 2 — JPY KOLU: HİÇ GÖRÜLMEMİŞ 2 PENCERE

**Pencereler:** U1 16–24 Tem (8 gün), U2 24–31 Tem (8 gün), U3 16 Tem–1 Ağu (16 gün, birleşik). Önceki kanıt: 1 Ağu–14 Eyl, 7 Eyl–7 Eki, 10 Ağu–7 Eyl.

| Konfig | 1 Ağu–14 Eyl | 7 Eyl–7 Eki | 10 Ağu–7 Eyl | **U1** | **U2** | **U3** | Poz/N |
|---|---:|---:|---:|---:|---:|---:|---:|
| `jp_da_h1` (Donchian+ADX+H1 kapı) | +71,68 (118) | +26,92 (85) | −52,80 (78) | **−14,87 (19)** | **−24,77 (19)** | **−39,64 (38)** | 2/6 |
| `jp_dp_h1` (Donchian saf+chand2.5+H1) | +54,87 (102) | +142,74 (76) | −27,93 (66) | **−14,78 (16)** | **+0,70 (20)** | **−14,08 (36)** | 3/6 |
| `jp_da_tp4` (kapı YOK, kontrol) | −8,69 (223) | −17,68 (165) | – | −27,03 (39) | −42,31 (41) | −69,34 (80) | 0/5 |
| `jp_classic` (kontrol) | −281,94 (2.664) | −784,81 (2.496) | – | −182,54 (321) | −207,44 (250) | −365,70 (522) | 0/5 |

### Bulgular
1. **Yeni pencerelerde JPY kolu negatif.** `jp_dp_h1` iki yeni pencerede −14,78 ve +0,70; birleşik 16 günde −14,08. `jp_da_h1` üçünde de negatif (−14,87 / −24,77 / −39,64).
2. **Toplam skor: 2 pozitif / 4 negatif pencere.** Daha önceki "+142,74 $" OOS sonucu **tek pencere**; aynı konfig iki yeni pencerede ve çapraz pencerede negatif. Bu, "pencere şansı" teşhisini **doğruluyor**.
3. **H1 kapısı yine zararı küçültüyor** (aynı pencerelerde `jp_da_tp4` −27/−42/−69 iken `jp_da_h1` −15/−25/−40) → kapı faydalı ama kenar yaratmıyor.
4. **Örneklem uyarısı:** yeni pencereler 16–38 işlem (baraj ≥100). Bu yüzden bu pencereler **yön kontrolü** sayılır, "kanıt" değil. Kanıt değeri: 2 bağımsız pencerede işaretin negatife dönmesi, örneklem küçük de olsa **tutarsızlık** yönünde güçlü bir sinyal.
5. **Teknik uyarı:** U1/U2 pencereleri veri setinin en başında (veri 15 Tem 23:00'te başlıyor) → H1 EMA200 gibi uzun indikatörlerin ısınma payı bu pencerelerde daha kısa. Kapının yine de filtreleme yaptığı görülüyor (kontrol 39 işlem → kapılı 19), ama bu pencereyi "tam eşdeğer" saymamak gerekir.
6. Klasik motor JPY'de yine felaket (−182 / −207 / −366) → mevcut canlı politika (klasik FX kapalı) **doğru**.

### Karar
JPY kolu **REDDEDİLDİ (aktivasyon)**. Canlı gölge-defterde izlemeye devam edilebilir ama **parametre sabitleme veya canlıya alma yok**.

---

## 3. BİRLEŞİK SONUÇ VE SONRAKİ ADIM

| Aile | Test edilen pencere | Pozitif | Baraj (2 pencere + OOS>0) | Karar |
|---|---|---|---|---|
| ORB + trail + H1 kapı (A2) | 6 | 3 | ✗ (OOS −44,19) | PAPER-ONLY |
| ORB çıplak / 10R / Londra 2h | 6 | 0 | ✗ | RED |
| JPY Donchian + H1 kapı | 6 | 2–3 | ✗ (yeni pencereler negatif) | PAPER-ONLY |
| JPY klasik motor | 5 | 0 | ✗ | RED |

**Kanıtla sabitlenen iki teknik bulgu:**
1. **H1 EMA200 trend kapısı**, test edilen her ailede zararı küçültüyor (6/6 ORB penceresi, 3/3 JPY penceresi). Motor aracı olarak kalıcı; **ama tek başına kâr üretmiyor**.
2. **Sabit TP'yi kaldırmak/trailing'e geçmek** FX 5m'de ölçülebilir bir iyileştirme üretmedi (A1 ≈ eski `orb_tp15`; 10R hedef daha kötü). Araştırmanın "TP'yi kaldır" bulgusu **hisse/futures** kanıtına dayanıyor ve FX maliyet yapısında karşılığı yok.

**Önerilen sonraki adım (yeni fikir, mevcut kanıtla tutarlı):** Kapı + maliyet eşiği kombinasyonunu **M15**'e taşımak: `--interval 15m` + `--htf-ema200-gate` + `--rel-atr-band` + `--flat-16`. A6/A7 kollarının "30 dk ufku 1–15 dk'dan iyi" ve "düşük frekans maliyeti düşürür" bulgusu bunu destekliyor. Baraj: 2 ayrık pencere + ≥100 işlem + 2× maliyet stresi.

---

## 4. ARTEFAKTLAR
- Sürücü: `scripts/fx_orb_exit_jpy_windows.py` (`--wave a|b|c|d|orb_seen|orb_unseen`)
- Ham sonuçlar: `outputs/fxsweep2/*.json`, özetler: `_summary_{b,orb_unseen,orb_seen,c,d}.json`, loglar: `_log_*.txt`
- Maliyet profili: `outputs/fx_spread_p95.json` (p95, muhafazakâr)
- Ana sentez raporu: `docs/FX_TREND_SCALPING_TOP5_2026-10-08.md`
