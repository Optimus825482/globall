# KOL AYAR DEĞİŞİKLİĞİ — UYGULAMA VE 1-2 HAFTALIK İZLEME

**Tarih:** 2026-11-12 · **Kollar:** `london_breakout` (lb), `ema_adx_pullback` (ema_adx) · **Durum:** ikisi de **zaten canlıydı**; değişen sembol listeleri

## 1) Ne değişti ve neden

Her iki listenin de 2026-10-08'de **yanlış maliyet tablosuyla** (major = 1,2 pip; gerçek 0,1-0,2) seçildiği ölçüldü. Düzeltilmiş maliyet + gerçek UTC saatle, **iki bağımsız pencerede** (IS = son 30 gün, OOS = önceki 30 gün) yeniden ölçüldü.

| Ayar | Eski | Yeni |
|---|---|---|
| `lb_symbols` | XAUUSD, GBPUSD, **USDJPY**, BTCUSD, **USDCHF**, US30 | XAUUSD, GBPUSD, US30, BTCUSD, **AUDUSD**, **NAS100** |
| `ema_adx_symbols` | XAUUSD, NAS100 | XAUUSD, NAS100, **USDJPY**, **US30** |

Gerekçe (IS/OOS net $):
- lb çıkarılan: **USDCHF −327/−727**, **USDJPY −340/−148**
- lb eklenen: **AUDUSD +1.831/+708**, **NAS100 +298/+287**
- ema_adx eklenen: **USDJPY +2.521/+3.003**, **US30 +862/+508**

Detay: `docs/GIRIS_MODU_YENIDEN_TARAMA_2026-11-12.md` §8-§9.

## 2) ⚠️ ÖNCE PANEL (yoksa hiçbir şey değişmedi)

Kod varsayılanı **kayıtlı ayar dosyasını ezmez**. Sunucuda `forex_auto_settings.json` varsa eski listeler yürürlükte kalır.

**Kontrol (açılış logunda):**
- Eski liste kayıtlıysa şu uyarı çıkar:
  `[FX AYAR] lb_symbols ölçümle uyuşmuyor ... ['USDCHF','USDJPY'] NEGATİF → çıkarılmalı`
  `[FX AYAR] ema_adx_symbols eksik: ['US30','USDJPY']`
- Uyarı yoksa panel/liste ölçümle uyumlu.

**Düzeltme:** Ayarlar > Auto Paper (LB / EMA+ADX) → sembol listelerini yukarıdaki yeni değerlerle kaydet.

## 3) Uygulandı mı — 5 dakikalık doğrulama

```bash
python scripts/arm_live_report.py --days 7
```

Çıktıda beklenen:
- `london_breakout USDCHF/USDJPY  çıkarıldı → yeni işlem: 0  ✅ ayar işledi`
- Eklenen sembollerde `islem: >0` (birkaç gün içinde) veya en azından `tarama` kaydı >0
- ⚠️ "ÖLÇÜLEMEDİ (defter boş)" yazıyorsa defterde hiç işlem yok → **kanıt yok**, 0'a bakıp "oldu" demeyin.

## 4) 1-2 haftalık izleme — karar kuralı

Her hafta aynı komut; `kol × sembol` tablosu:

| Durum | Karar |
|---|---|
| n ≥ 20 **ve** PF < 1,0 | o sembolü koldan **çıkar** |
| n < 20 | **karar yok** (sayı üretme) |
| PF ≥ 1,0 | devam |

Kill kriteri repo geneliyle aynı: iki pencerede biri negatif / DD > 200 $ / 2× maliyette PF < 1,1.

## 5) Beklenen etki (yön, dolar değil)

- lb'de iki negatif sembolün çıkması: replay'de 60 günde **+1.542 $** iyileşme yönünde.
- Eklenen semboller: lb **+3.124 $**, ema_adx **+5.524 $** yönünde.
- **Replay mutlak doları canlıya taşınmaz** — yalnız yön ve sıralama.

## 6) Dürüst riskler

- Örneklem küçük: lb'de sembol başına 15-28 işlem/pencere; canlıda 1-2 hafta **karar için yetersiz** olabilir → "yetersiz" demekten çekinme.
- **XAUUSD konsantrasyonu:** ema_adx kârının %85+'ı XAUUSD'den. Bu listeye sembol eklemek çeşitlendirme *değildir*.
- lb'nin **sinyal kenarı yok** (bağımsız kol: +0,008R, t=0,31). Kâr motorun çıkış yığınından geliyor; bu yüzden sembol seçimi sinyal kalitesinden değil, **maliyet/çıkış etkileşiminden** besleniyor. Beklentiyi buna göre kur.
- Ayar değişikliği **kendi başına bir A/B değildir**: canlıda aynı anda başka değişiklikler olursa (yeni strateji, spread rejimi) etkiyi ayırmak zorlaşır.
