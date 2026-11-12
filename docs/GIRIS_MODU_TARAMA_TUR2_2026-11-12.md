# GİRİŞ MODU TARAMASI — TUR 2 (2026-11-12)

**Ayar:** ölçülen saat-duyarlı spread + `--bar-tz-offset 2` (doğru UTC), `--skip-old`,
30 gün IS + önceki 30 gün OOS. Ölçüt: **IS PF ≥ 1,05 ve OOS PF ≥ 1,05 ve OOS n ≥ 40**.

## Sonuç: 4 aday tarandı — **hepsi elendi**

| Mod | IS PF | IS net | IS n | OOS PF | OOS net | OOS n | Karar |
|---|---|---|---|---|---|---|---|
| `nr7` | 1,03 | +1.677 $ | 1.119 | **0,91** | −5.314 $ | 978 | ❌ elendi |
| `orb_ny` | **0,49** | −9.370 $ | 192 | **0,37** | −10.238 $ | 165 | ❌ elendi |
| `tokyo_fix` | 0,71 | −808 $ | 35 | 0,59 | −974 $ | 29 | ❌ elendi (n çok küçük) |
| `squeeze_kc` | 0,71 | −1.290 $ | 78 | 0,71 | −1.155 $ | 71 | ❌ elendi |

**Yorum:** `nr7` en yakınıydı (IS 1,03) ama OOS'ta 0,91 → daralma kırılımı bu evrende
kenar üretmiyor. `orb_ny` (NY açılış aralığı) belirgin şekilde zarar: açılış
momentesi maliyeti karşılamıyor. `tokyo_fix` örneklem olarak da yetersiz (n=35).

## Şimdiye kadar taranan modlar (doğru maliyet+saat ile)

| Tur | Modlar | Sonuç |
|---|---|---|
| 1 | london_breakout · ema_adx_pullback · pullback · supertrend_rsi | **4 geçti** (lb ve eap zaten canlı) |
| 1 | reopen_fade · squeeze | elendi |
| 2 | nr7 · orb_ny · tokyo_fix · squeeze_kc | **4 elendi** |

## Dosyalar
`outputs/ns_<mod>_{IS,OOS}.json` (gitignore'da; koşular tekrar üretilebilir)


## Tur-2b: 4 mod daha (aynı ayar, aynı ölçüt)

| Mod | IS PF | IS net | IS n | OOS PF | OOS net | OOS n | Karar |
|---|---|---|---|---|---|---|---|
| **`donchian_adx`** | **1,25** | +13.737 $ | 1.057 | **1,33** | +15.103 $ | 929 | ✅ **ZATEN CANLI** (doğrulandı) |
| **`squeeze_exp`** | **1,28** | +4.185 $ | 318 | **1,24** | +3.323 $ | 280 | ✅ aday — 2× stres **1,16 / 1,12** (sınırda) |
| `donchian_pure` | 1,12 | +6.598 $ | 999 | 0,94 | −3.147 $ | 878 | ❌ elendi |
| `bb_bandwalk` | 0,67 | −1.258 $ | 90 | 0,70 | −1.007 $ | 81 | ❌ elendi |

**`squeeze_exp` 2× maliyet stresi:** PF **1,16** (cur) / **1,12** (prior), net +2.523/+1.727 $,
DD 3.412 $, n=316/278 → kill kriterini (≥1,10) **iki pencerede de kıtı kıtına** geçti.
Üç kapıyı da geçen tek *yeni* aday; ama marj ince (prior 1,12) ve örneklem küçük →
canlıya almadan önce **kol dosyası + sinyal-seviyesi ölçüm** (london_breakout dersi:
replay kârı motorun çıkış yığınından gelebilir) ve gölge şart.

**`donchian_adx` 2× maliyet stresi:** PF **1,20** (cur) / **1,28** (prior), net +11.149/+12.939 $,
DD 5.711 $ → üç kapıyı da geçti. Canlı blokta `donchian_adx_entry` + `donchian_adx_min`/
`donchian_max_per_day` ayarları mevcut → **canlı defterdeki en güçlü mod**; sembol listesi ve
`max_per_day=2` sınırı bu kanıtla gözden geçirilmeli (frekansı sınırlıyor olabilir).

## Özet: 18 mod tarandı, 3 geçti (hepsi zaten canlı), 11 elendi
