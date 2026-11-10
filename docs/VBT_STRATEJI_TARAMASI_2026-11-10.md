# VECTORBT STRATEJİ TARAMASI (2026-11-10)

**Amaç:** klasik strateji ailelerini kendi MT5 verimizde **vektörel** olarak taramak; OOS + maliyet +
parametre komşuluğu ile "şanslı hücre"yi ayıklamak.

**Kurulum:** `vectorbt 1.2.0` **izole venv** (`.venv-vbt`, py3.12 + numpy 2.5 + pandas 3.1 — test edildi).
Veri: `scripts/vbt_export_mt5.py` → `outputs/vbt_data/<SEMBOL>_<TF>.csv` (UTC damgalı, 5 yıl, 7 sembol).
Tarama: `scripts/vbt_sweep.py` · kararlılık: `scripts/vbt_stability.py`.

**Disiplin:** sinyal **1 bar geciktirilir** (aynı-bar dolum yok) · IS=%70 / OOS=%30, en iyi parametre IS'te
seçilir **OOS'ta raporlanır** · maliyet sembol başına ölçülmüş tur maliyeti/2 · `freq` zorunlu ·
maliyet ×2 stresi · komşu parametre kararlılığı.

---

## 1) Tarama sonucu (55 kombinasyon)

OOS'ta **Sharpe>0.5 & PF>1.2 & işlem≥20**: **8/55**. Aile medyanları (IS→OOS farkı = aşırı uyum göstergesi):

| aile | IS medyan | OOS medyan | fark |
|---|---|---|---|
| Bollinger+ADX | 0.32 | **0.26** | 0.06 |
| EMA kesişimi | 0.82 | 0.21 | 0.61 |
| RSI(2) | 0.46 | 0.02 | 0.44 |
| Donchian | 0.68 | −0.02 | 0.70 |
| Momentum (ROC) | 0.76 | −0.03 | 0.78 |

→ Ailelerin **medyanı sıfıra yakın**; yani "genel olarak trend takibi çalışıyor" iddiası YOK. Ayakta kalanlar
tekil hücreler — ve aşağıdaki komşuluk testi bunların şans olmadığını gösteriyor.

**Maliyet ×2 stresinde aynı 8 hücre ayakta** (gold/endeks/USDJPY'de ölçülen maliyet hareketin yanında küçük).

## 2) Komşu parametre kararlılığı — asıl kanıt

| vaka | OOS Sharpe (komşular) | sonuç |
|---|---|---|
| **XAUUSD 1h Donchian** n=10/15/20/25/30/40 | **1.71 · 1.65 · 1.58 · 1.19 · 1.17 · 1.00** | **6/6 KARARLI** |
| **USDJPY 1h Donchian** n=10/15/20/25/30/40 | **1.57 · 1.54 · 0.78 · 0.73 · 0.76 · 0.47** | **6/6 KARARLI** |
| US30 1g momentum n=5/10/15/20/30 | 1.32 · 1.43 · 1.18 · 0.85 · 0.86 | 5/5 kararlı **ama IS≈0, OOS>0** → rejim şüphesi (OOS 2024-26 güçlü trend) |
| NAS100 1h momentum n=10..50 | 0.51 · 0.09 · 0.45 · 0.48 · −0.02 | 3/5 KIRILGAN |
| NAS100 1h EMA kesişimi (fast 5/10/20 × slow 100/150/200) | tüm ızgara **0.57–1.33** (46-122 işlem) | **plato** (kararlı) |

## 3) Adaylar (canlıya alınmadan önce bizim replay'de çapraz doğrulama şart)

1. **XAUUSD 1h Donchian kırılımı (n≈15-20)** — OOS Sharpe ~1.6, PF 1.55, 93-124 işlem, DD %15.
2. **USDJPY 1h Donchian (n≈10-15)** — OOS Sharpe ~1.55, PF 1.38, 189 işlem, DD %3.
3. **NAS100 1h EMA kesişimi (10-20 / 150-200)** — OOS Sharpe ~1.0-1.3, 46-83 işlem, plato.

**Dikkat çeken:** ayakta kalanların hepsi **altın / endeks / USDJPY** — yani canlı RADAR'ın hâlihazırda
pozitif olduğu enstrümanlar (XAU, USTEC, US30) + **kanıt kapsamından çıkarılmış USDJPY**. FX majörleri
(EURUSD/GBPUSD) hiçbir ailede OOS'ta ayakta kalmadı — önceki "FX majörlerinde kenar yok" bulgusuyla tutarlı.

## 4) Açık kalanlar (dürüst)

- **Tek IS/OOS dilimi**; OOS dönemi (son %30 ≈ 2024-2026) altın/endeks için güçlü trend rejimi → **yuvarlanan
  walk-forward** ve 2019-2022 alt örneklemi koşulmalı.
- **Yalnız long** taraf test edildi (`direction="longonly"`); short tarafı ölçülmedi.
- **Çoklu test**: 55 hücre; komşuluk kararlılığı riski büyük ölçüde azaltıyor ama `arch` SPA/Reality Check
  ile resmi düzeltme hâlâ yapılmadı.
- Bizim **replay motoru** (kapılar + gerçek spread + SL-first) ile çapraz doğrulama yapılmadı → sıradaki adım.

---

## 5) ÇAPRAZ DOĞRULAMA — adaylar 10 yılda TUTMADI (durum: ELENDİ)

Üç aday kol dosyası olarak yazıldı (`app/arms/donchian_break.py`, `ema_trend_cross.py`), sonra üç
bağımsız denetimden geçirildi:

### 5.1 Buy&hold ile kıyas (5 yıl, 1h, long-only)

| vaka | Sharpe | getiri | **DD** | işlem |
|---|---|---|---|---|
| XAUUSD buy&hold | 1.19 | +125% | **30%** | 1 |
| **XAUUSD Donchian(15) LONG** | **1.65** | +128% | **14%** | 419 |
| XAUUSD SHORT (aynı sinyal) | **−1.71** | −62% | 68% | 419 |
| USDJPY buy&hold | 0.86 | +40% | 16% | 1 |
| **USDJPY Donchian(10) LONG** | **1.14** | +38% | **12%** | 621 |
| USDJPY SHORT | −1.47 | −36% | 39% | 621 |
| NAS100 buy&hold | 0.72 | +72% | 37% | 1 |
| NAS100 EMA(10,200) LONG | 0.76 | +47% | **17%** | 188 |
| NAS100 SHORT | −0.78 | −41% | 51% | 188 |

**Okuma:** getiri buy&hold'dan YÜKSEK değil; kazanç **DD yarıya inmesi** (30→14%, 37→17%) ve
**short tarafı her üç enstrümanda da yıkım** (−0.8…−1.7). Yani kulp "alfa" değil, **beta + DD zamanlaması**.

### 5.2 10 YIL GÜNLÜK — rejim testi (2016-2026: 2018 düzeltmesi, 2020 çöküşü, 2022 ayı dahil)

| vaka | buy&hold Sharpe | **trend LONG Sharpe** | buy&hold getiri | trend getiri |
|---|---|---|---|---|
| XAUUSD | **0.98** | 0.68 | +236% | +93% |
| USDJPY | **0.58** | 0.37 | +48% | +19% |
| NAS100 | 1.06 | 1.04 | +487% | +306% |

**Sonuç: 5 yıllık 1h "kenarı" rejim artefaktı.** Boğa piyasasında DD kontrolü gibi görünen şey,
10 yıllık pencerede buy&hold'un **altında** kalıyor. Bu yüzden iki kol da **kayıtlı değil**
(`register_arm` yok, `EVIDENCE` negatif sonucu taşıyor, testle kilitli).

### 5.3 Metodolojik notlar (bu turda öğrenilenler)

- **Trend ailelerinde shift kontrolü geçersiz**: sinyali 5 bar kaydırmak trendi hâlâ yakalıyor →
  kontrol olarak **buy&hold** ve **ters taraf (short)** kullanılmalı.
- **Pozisyon durumu olmadan** sinyal-çıkışlı aile simüle edilemez: her sinyali veri sonuna kadar
  taşıyan naif simülatör **drift artefaktı** üretir (ölçüldü: t=18 "kenar"). `fx_arm_backtest.py`
  artık `--exit-on-opposite` için **tek pozisyonlu sıralı** simülatör kullanır.
- Tek IS/OOS dilimi + tek zaman dilimi **yetmiyor**; en az bir **rejim karşıtı pencere** (10 yıl günlük
  veya 2011-2015 altın ayısı) şart.
