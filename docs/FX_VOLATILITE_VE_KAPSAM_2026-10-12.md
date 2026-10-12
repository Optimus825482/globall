# FX Volatilite Eşiği ve Kapsam Genişletme — Replay Bulguları (2026-10-12)

**İstek:** (a) forex otonom algoritmalarını incele/analiz et, (b) volatilite filtresini
biraz gevşet, (c) daha fazla parite çifti ekle.

**Yöntem:** Önce ölç, sonra yaz. İki bağımsız pencerede (IS 2026-08-01→09-07,
OOS 2026-09-07→10-07), gerçek p95 spread profiliyle (`outputs/fx_spread_p95.json`),
`scripts/forex_replay_backtest.py` ile A/B. Bar: OOS net>0 · OOS n≥100 ·
maxDD<$200 · her iki pencerede pozitif · XAU+BTC defterini düşürmüyor.

**Sonuç (kısa):** Her iki istek de kanıt barını **geçemedi**. Canlı varsayılanlarda
hiçbir işlem davranışı değişmedi; yalnız **panel dürüstlüğü** düzeltildi (istenen
kapsam seçeneği: "kanıtlı olanları bağla + paneli düzelt" → kanıtlı çift yok, panel düzeltildi).

Sürücüler: `work/fx_sw/atr_sweep.py`, `work/fx_sw/cross_sweep.py`,
`work/fx_sw/fullbook_atr.py`. Çıktılar: `work/fx_sw/out/`.

---

## 1. Volatilite filtresi: 2.5 → 1.5 **UYGULANMADI**

`major_min_atr_pips` yalnız 7 majöre (`FX_MAJORS_SET`) uygulanır.

### İzole majör defteri (7 majör, max-open 99)

| config | pencere | n | WR% | net$ | PF | DD$ |
|---|---|---:|---:|---:|---:|---:|
| atr2.5 | IS | 1455 | 55.3 | −224.26 | 0.90 | 263.97 |
| atr2.5 | OOS | 1636 | 55.3 | −322.07 | 0.88 | 358.72 |
| atr2.0 | IS | 1575 | 56.1 | −197.19 | 0.92 | 278.41 |
| atr2.0 | OOS | 1738 | 54.8 | −402.49 | 0.86 | 434.27 |
| **atr1.5** | **IS** | 1699 | 56.2 | −206.21 | 0.92 | 336.45 |
| **atr1.5** | **OOS** | 1794 | 54.0 | **−521.38** | 0.83 | 547.63 |
| atr1.0 | IS | 1771 | 55.8 | −282.02 | 0.90 | 361.19 |
| atr1.0 | OOS | 1826 | 54.2 | −482.17 | 0.85 | 506.56 |

### İşaret tutarlılığı (2.5'e göre fark)

| config | ΔIS | ΔOOS | sonuç |
|---|---:|---:|---|
| atr2.0 | +27.07 | −80.42 | **İŞARET DÖNÜYOR** |
| atr1.5 | +18.05 | −199.31 | **İŞARET DÖNÜYOR** |
| atr1.0 | −57.76 | −160.10 | tutarlı ama her iki pencere de tabandan KÖTÜ |

### Tam canlı defter (13 sembol, XAU+BTC dahil)

| atr | pencere | n | net$ | PF | DD$ |
|---|---|---:|---:|---:|---:|
| 2.5 | IS | 8955 | 5425.49 | 1.39 | 207.74 |
| 2.5 | OOS | 9295 | **2403.64** | 1.17 | 341.61 |
| 2.0 | IS | 8936 | 5436.07 | 1.39 | 195.49 |
| 2.0 | OOS | 9320 | 2256.95 | 1.16 | 350.22 |
| **1.5** | IS | 9167 | 5564.21 | 1.39 | 200.45 |
| **1.5** | OOS | 9320 | **2157.91** | 1.15 | 338.55 |
| 1.0 | IS | 9130 | 5542.85 | 1.39 | 216.35 |
| 1.0 | OOS | 9413 | 2251.64 | 1.16 | 325.68 |

**Karar:** 1.5 eşiği IS'te +$138 kazandırırken OOS'te **−$246** kaybettiriyor —
geçmişe uyum, gelecekte bozulma (klasik overfit işareti). Projenin kendi kuralı
(`cikis-tp-iptal-trailing-testi` dersi): *penceler arası işaret değiştiren katman
genellenmez.* **2.5 korundu.**

---

## 2. Aday kros çiftleri: 13/13 **ELENDİ**

`allowed_symbols`'te olup `FOREX_SYMBOLS`'te olmayan 13 kros, kanıtlandıkları
strateji koluyla (LB veya S3), izole defterde, iki pencerede:

| sembol | kol | IS net | IS n | OOS net | OOS n | OOS PF | OOS DD |
|---|---|---:|---:|---:|---:|---:|---:|
| GBPCHF | LB | −12.55 | 22 | 19.55 | 20 | 1.96 | 14.95 |
| EURCAD | LB | −20.25 | 21 | 15.45 | 19 | 1.96 | 13.15 |
| CHFJPY | LB | 42.65 | 21 | 22.64 | 21 | 1.96 | 25.50 |
| CADJPY | LB | 13.86 | 16 | 25.56 | 18 | 2.57 | 15.37 |
| GBPNZD | LB | 10.50 | 15 | −1.41 | 16 | 0.91 | 10.86 |
| GBPAUD | LB | 25.05 | 20 | −4.74 | 16 | 0.85 | 27.25 |
| GBPCAD | LB | −59.55 | 25 | 7.65 | 20 | 1.20 | 27.00 |
| AUDCAD | LB | −33.00 | 13 | −35.80 | 13 | 0.23 | 39.55 |
| EURAUD | LB | −0.46 | 16 | −0.81 | 12 | 0.94 | 8.81 |
| CADCHF | LB | −32.60 | 16 | −45.00 | 15 | 0.10 | 48.20 |
| AUDCHF | LB | −38.90 | 18 | −49.30 | 16 | 0.14 | 52.75 |
| NZDJPY | S3 | −29.84 | 49 | −7.33 | 51 | 0.89 | 27.49 |
| AUDNZD | S3 | −9.56 | 98 | −61.09 | 74 | 0.51 | 69.73 |

**Barı geçen: YOK.** En yakın aday AUDNZD bile OOS n=74 < 100 ve net −$61.
Örneklem küçüklüğü barı *tasarım gereği* eliyor: 12–25 işlemlik bir pencerede
pozitif net, gürültüden ayırt edilemez. Bu, reponun önceki 36-konfig × 5-pencere
süpürmesinin "adayların hiçbiri barı geçmedi" bulgusunu **bağımsız olarak teyit eder**
(`FX_STRATEJI_ARASTIRMASI_2026-10-08.md`).

### Not: replay pip_val kusuru (verdict'i değiştirmez)

`_compute_pip_val_overrides` (`forex_replay_backtest.py:1245`) `CADUSD`/`CHFUSD`
aramaları cache'te olmadığı için 5 kros (EURCAD, GBPCAD, AUDCAD, CADCHF, AUDCHF)
+ GBPCHF'te override uygulayamıyor → 10.0 varsayılanı kalıyor. Ancak motorda
`lots = risk_usd/(sl_pips·pip_val)` ve `pnl = pips·lots·pip_val` olduğundan pip_val
PnL'den büyük ölçüde sadeleşir; etki yalnız lot yuvarlamasındadır. **Ayrıca bu 6
sembolün tamamı barı zaten `n≥100` şartından kaybediyor** (en yüksek OOS n = 25),
yani kusur düzeltilse de verdict değişmez. Canlıda ise spec dalının tamamı
`pip_val`'i yanlış hesaplıyor (Bölüm 4) — o ayrı bir doğruluk borcu.

---

## 3. UYGULANAN: Panel dürüstlüğü (hayalet parite düzeltmesi)

**Bulgu:** `allowed_symbols` varsayılanı 22 çift listeliyordu ama tick üretimi yalnız
`FOREX_SYMBOLS` (13 sembol) üzerinde dönüyor (`_generate_realistic_ticks`,
`forex.py:2101`) ve tüm giriş akışları `ticks.get(sym)` kapısından geçiyor
(LB `forex.py:4885`, S3 `forex.py:4792`). Sonuç: 13 kros panelde "seçili"
görünüyor ama **istatistiksel olarak imkânsız** şekilde hiç işlem açamıyordu.

**Düzeltme — `allowed_symbols` ⊆ `FOREX_SYMBOLS`:**

| Yer | Değişiklik |
|---|---|
| `forex.py` `allowed_symbols` | 22 → **9** (`XAUUSD, BTCUSD, GBPJPY, EURJPY, US30, GBPUSD, AUDUSD, USDJPY, USDCHF`) |
| `forex.py` `lb_symbols` | 17 → **6** (11 hayalet kros çıkarıldı) |
| `forex.py` `s3_symbols_5m` | `["XAUUSD", "AUDNZD"]` → **`["XAUUSD"]`** |
| `forex.py` `RADAR_SCAN_SYMBOLS` | NZDJPY/AUDNZD çıkarıldı (tick üretemiyorlardı) |
| `forex.py` `_enforce_universe_invariant()` (YENİ) | Varsayılan, kalıcı-dosya yüklemesi ve `merge_settings_payload` yollarının **hepsinde** hayaletleri atar + uyarır |
| `AutoSettingsPanel.tsx` `ALL_SYMBOLS` | Zaten `FOREX_SYMBOLS` ile tutarlıydı; değişmez notu eklendi |

**Neden filtrelemek yerine çıkarmak:** Filtre (akışta `continue`) panelin
yalan söylemeye devam etmesini sağlar ve kullanıcı yine "seçtim ama işlem olmuyor"
diye bakar. Kaldırınca panel gerçeği gösterir; kilit testler bunu kalıcı kılar.

**Risk:** Sıfır. Bu 13 sembol için canlıda açılmış pozisyon yok (açamazlardı),
istatistik yok, arşiv kaydı yok. Çıkarma, önceki durumu bire bir geri getirir.

---

## 4. Açık kalan doğruluk borcu (bu işin parçası değil)

`get_symbol_trading_specs` `else` dalı (`forex.py:1306`) ve MT5 köprüsü aynası
(`scripts/mt5_bridge.py`) **USD-dışı quote'lu her kros için `pip_val=10.0`**
sabitini döndürüyor. `pip_val`, SL/TP/lot matematiğine giren bir değerdir
(`_LB_STATE` çıkışı, `apply_risk_normalization`), bu yüzden ileride bu kroslardan
biri kanıtla eklenirse **önce** düzeltilmelidir:

```
pip_val = 10 × (1 USD'nin quote cinsinden değeri)
  CAD → 10 / USDCAD   (~7.2)      CHF → 10 / USDCHF   (~11.4)
  AUD → 10 × AUDUSD   (~6.6)      NZD → 10 × NZDUSD   (~5.8)
  JPY → 1000 / USDJPY (~6.3)      USD → 10 (değişmez)
```

Şu an canlıda USD-dışı quote'lu **işlenen** kros olmadığı için bu borç zararsız
(GBPJPY/EURJPY JPY dalından geçiyor, doğru hesaplanıyor). Kayıt için burada.

---

## Karar özeti

| İstek | Kanıt | Karar |
|---|---|---|
| Volatiliteyi gevşet | 2.5→1.5: IS +$138 / OOS **−$246**, işaret dönüyor | **Uygulanmadı** — 2.5 korundu |
| Daha fazla parite | 13 adayın 13'ü barı geçemedi (en yüksek OOS n=74) | **Eklenmedi** — kanıt yok |
| Panel/evren uyumu | 13 hayalet çift asla işlem açamıyordu | **Düzeltildi** — `allowed_symbols ⊆ FOREX_SYMBOLS` + 3 kilit test |

Kullanıcı isteği kanıtla çeliştiğinde **kanıt kazandı**; volatilite değişikliği
kullanıcının kendi risk kararı olarak açıkça geri alınabilir (tek satır:
`forex.py:3190` `major_min_atr_pips` + kalıcı dosya sıfırlama), ama varsayılan
olarak yazılmadı. Aynı şekilde bir çift eklemek istenirse önce Bölüm 4'teki
pip_val düzeltmesi, sonra legal `FOREX_SYMBOLS` girdisi ve replay kanıtı gerekir.
