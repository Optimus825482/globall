# DONCHIAN+ADX GÜNLÜK GİRİŞ SINIRI — 2 → 4 (2026-11-12)

## Ne ölçüldü
`donchian_adx` canlı defterin **en güçlü modu** çıktı (OOS PF 1,33). Ama `donchian_max_per_day = 2`
sınırı (yön başına) frekansı kısıyordu. Sınır 2 / 4 / sınırsız karşılaştırıldı.

**Düzeltilmiş maliyet + gerçek UTC; 30 gün IS + önceki 30 gün OOS.**

| Pencere | cap | işlem | isabet % | PF | net $ | maxDD $ |
|---|---|---|---|---|---|---|
| cur | 2 | 1.057 | 74,6 | 1,25 | 13.737 | 5.081 |
| cur | **4** | **1.761** | **76,6** | **1,30** | **25.414** | **4.522** |
| cur | 0 | 2.315 | 76,5 | 1,24 | 26.687 | 7.948 |
| prior | 2 | 929 | 74,9 | 1,33 | 15.103 | 5.081 |
| prior | **4** | **1.551** | **76,6** | **1,32** | **23.524** | **4.522** |
| prior | 0 | 2.068 | 76,5 | 1,27 | 25.496 | 7.948 |

**2× maliyet stresi (cap=4):** PF **1,23** (cur) / **1,28** (prior), net +20.076/+20.663 $,
DD 4.768 $ → kill kriterini (≥1,10) geçti.

## Karar
`donchian_max_per_day = 4`. Net **~%85 artıyor**, PF artıyor, **DD düşüyor** (5.081 → 4.522).
Sınırsız (0) net'i biraz daha artırıyor ama PF düşüp DD %76 fırlıyor → **4 tatlı nokta**.
Geri alma: `2`.

⚠️ Canlıda kayıtlı ayar varsa **panelden** de 4 yapılmalı (kod varsayılanı kayıtlı ayarı ezmez).

## Ders (tuzak)
İlk denemede bayrağı **yanlış fonksiyona** yamaladım: `_arm_donchian_candidate` (`--combined`
kolları) yerine `TUN_ENTRY_MODE == "donchian_adx"` bloğu (satır ~768) yamalanmalıydı.
Yanlış yamada cap=1/4/0 **birebir aynı** çıktı; `cap=1` ile doğrulayınca fark görüldü
(575 işlem vs 1.057) ve doğru blok bulundu. **Kural: A/B "aynı" çıkarsa önce bayrağın
etki ettiğini kanıtla** (bu turda ikinci kez aynı tuzağa düştüm).
