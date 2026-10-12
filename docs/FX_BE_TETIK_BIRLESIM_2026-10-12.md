# BE Tetik Formülü: `max` → Birleşim (2026-10-12)

**Sorun (kullanıcı):** Zararla kapanan işlemlerin **karar mekanizmasındaki** hatayı bul ve kârlıya
çevir. Zaman filtresi / sembol kapatma **çözüm değil**.

**Kök neden:** Başabaş (BE) stopunun tetik eşiği, `backend/app/routers/forex.py::calculate_breakeven_target`
ve `scripts/mt5_bridge.py::check_and_apply_dynamic_exits` içinde tabanların **en büyüğü** olarak
hesaplanıyordu:

```python
min_trigger_pips = max(pips_for_1usd + headroom,  sl_pips * 0.40,  atr_pips * 0.50,  eff_be_pips)
```

Yani BE ancak kâr `0.4×SL` **veya** `0.5×ATR` **veya** `eff_be` eşiğine ulaşınca kilitleniyordu —
altın için tipik olarak **25–37 pip**. Bu mesafeye koşamayan bir kazanç, BE'ye hiç kilitlenmeden
geri dönüp **tam ATR stopuyla** kapanıyordu. Fonksiyonun kendi docstring'i ise "veya" diyordu:
**kod ile niyet çelişiyordu.**

Replay motoru (`scripts/forex_replay_backtest.py::manage_position`) aynı eşiği **birleşim** olarak
kuruyordu (`$1+hurdle` **VEYA** `eff_be`). Canlı↔replay sapmasının kaynağı buydu.

## Kanıt — dört bağımsız pencere, tek değişken

Replay'e `--be-trigger` düğmesi eklendi (union / usd / dollar / max_r / max_atr / max_r_atr / min_r_atr).
Koşum: XAUUSD+BTCUSD, canlı-parite bayrakları (`--st-filter --spec-atr --no-tp-on-trail-live
--chandelier 1.2 --no-tp-crypto --crypto-sl-mult 1.5 --major-hours 7-20 --major-min-atr 2.5
--max-spread 10 --loss-streak 3`), gerçek spread profili.

| Pencere | union = **YENİ** | dollar = max($1,eff_be) | max_r_atr = **ESKİ (canlı)** |
|---|---:|---:|---:|
| 10-08→10-13 | **+318.58** · WR %75.7 · DD 58.7 | +165.82 · %64.6 · DD 136.0 | +144.16 · %63.1 · DD 148.9 |
| 09-07→10-07 | **+3278.73** · WR %75.7 · DD 106.7 | — | −186.77 · %61.0 · DD 787.0 |
| 08-08→09-07 | **+4022.48** · WR %75.3 · DD 110.1 | +870.59 · %60.8 · DD 377.4 | +708.57 · %59.4 · DD 380.5 |
| 07-15→08-15 | **+1916.42** · WR %80.5 · DD 97.3 | +256.23 · %57.0 · DD 600.0 | +256.23 · %57.0 · DD 600.0 |

**İzolasyon:** Suçlu tek bir taban değil, `max` **birleşiminin kendisi**. `max_r`, `max_atr`,
`max_r_atr`, `min_r_atr` ve `dollar` varyantlarının hepsi aynı çukura düşer; yalnız-$1 (`usd`)
ve birleşim (`union`) varyantları iyidir. `eff_be` tabanı `max` içine girdiği anda WR ~%60'a çöker.

**Canlı veriyle bağımsız uyum:** Canlı 12 Ekim WR %59.8 — eski formülün replay replikası %63.1,
birleşim varyantı %75.7. Sapmayı kapatan katman tam olarak budur.

## Değişiklik

- `backend/app/routers/forex.py::calculate_breakeven_target` — tetik `min($1+hurdle, eff_be)`;
  `be_r_mult`/`be_atr_mult` imzada kalır ama tetikte kullanılmaz.
- `scripts/mt5_bridge.py::check_and_apply_dynamic_exits` — aynı düzeltme (canlı MT5 yolu).
- `backend/tests/test_forex_enhancements.py` — eski sözleşmeyi kodlayan test kanıta göre güncellendi;
  kök-neden regresyon kilidi (`test_be_trigger_is_union_not_cumulative_max`) ve FX/kripto kapsam
  testi eklendi.

Yeni davranış, replay'in **zaten test edilmiş varsayılanına** hizalanır — yeni bir strateji
icat edilmez; canlı, ölçülmüş konfigürasyona getirilir.

## Yönetişim barı

OOS 30g net>0 ✓ · n≥100 ✓ · maxDD<$200 ✓ (OOS 110.1 / IS 106.7) · iki bağımsız pencerede pozitif ✓
(dört pencerenin dördünde) · gerçek spread sonrası ✓ · XAU+BTC defterini düşürmüyor ✓
(dört pencerede de net ve WR arttı).

## Maliyet şoku (slipaj) — düzeltme gerçek yürütme altında ayakta mı?

Replay'e `--slip-pips` eklendi: giriş ve çıkış **her bacak** için aleyhte slip (`pip_size × slip`).
İki formül aynı koşullarda, XAU+BTC, canlı-parite bayrakları, gerçek spread.

| Pencere | slip/bacak | union (YENİ) net · $/işlem · WR · PF | max_r_atr (ESKİ) net · $/işlem · WR · PF |
|---|---:|---|---|
| AR 10-08→10-13 | 0 | +320.22 · +0.57 · 76.0 · 1.41 | +177.73 · +0.41 · 65.5 · 1.20 (DD 174.67) |
| AR | 1.0p | +212.93 · +0.39 · 75.7 · 1.27 | +120.76 · +0.30 · 65.3 · 1.13 (DD 194.38) |
| AR | 2.0p | **+45.18 · +0.09 · 73.9 · 1.05** | **+19.35 · +0.05 · 64.7 · 1.02 (DD 201.55)** |
| OOS 08-08→09-07 | 0 | +4052.58 · +1.10 · 75.6 · 1.68 | +557.00 · +0.21 · 59.4 · 1.06 (DD 404.69) |
| OOS | 1.0p | +3014.40 · +0.82 · 74.5 · 1.47 | +180.44 · +0.07 · 59.1 · 1.02 (DD 564.90) |
| OOS | 2.0p | **+2160.18 · +0.60 · 73.9 · 1.32** | **−275.01 · −0.10 · 58.7 · 0.97 (DD 615.11)** |

(IS 09-07→10-07: YENİ +3226.43→+1465.97, PF 1.53→1.22, hep pozitif.)

**Bulgular:**

1. **Eski formül gerçek maliyet altında ölüyor.** 2 pip/bacakta OOS net negatife döner (PF 0.97,
   DD 615$). Eski kenar kâğıt üstündeydi; canlı −204$ zarar bu tabloyla tutarlı.
2. **Yeni formül ayakta kalıyor.** Aynı koşulda PF 1.32, +2160$, DD eskinin yarısından az.
   Fark "daha kârlı" değil, **hayatta kalma**.
3. **Dürüst sınır:** arıza penceresi (AR) her iki formülde de kırılgan; 2p'de YENİ +0.09$/işlem'e
   iner. Marj YENİ lehine ~2× ve DD yarı, ama çalkantılı kısa pencerede ince. Geniş pencerelerde
   fark 30-60×.

## Bilinçli kabul edilen risk

BE erken kilitlenince chop'ta "küçük kâr kilidi → BE vuruşu" sayısı artar (BE çıkışları 155→360).
Ölçüm bu maliyetin kazanca göre küçük olduğunu ve işaret-tutarlı olduğunu gösteriyor; ancak gerçek
piyasada ilk günlerde paper gözlemi önerilir.

## Açık kalan (dürüstlük notu)

Replay birleşim varyantı arıza penceresinde **+318**, canlı aynı pencerede **−204**. Düzeltme
WR farkının büyük kısmını kapatır (canlı %59.8 → replay eski-formül %63.1 → birleşim %75.7),
ama canlı ile replay arasında **yürütme katmanı** farkı sürüyor ve ölçülmedi:

1. Canlı motorun **çoklu sinyal kolları** (S3 SuperTrend+RSI, London Breakout, EMA+ADX pullback,
   Donchian) replay `--entry-mode classic` koşumunda YOK.
2. MT5 gecikmesi/slipajı (tick-bazlı yürütme; replay bar-içi muhafazakâr model kullanır).
3. Kısmi TP + TP-iptal + BE + chandelier etkileşimi gerçek akışta.
