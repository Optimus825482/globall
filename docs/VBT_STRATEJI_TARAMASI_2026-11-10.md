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
