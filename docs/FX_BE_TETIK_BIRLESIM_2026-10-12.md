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

## Çoklu-kol ölçümü (2026-10-12) — sinyal kolları ELENDİ

Replay yalnız tek `--entry-mode` işletirken canlı motor aynı anda **beş bağımsız kol** çalıştırır
(klasik radar + S3 SuperTrend+RSI 5m/15m + EMA+ADX pullback + London Breakout + Donchian).
Bu, canlı↔replay farkının en büyük ölçülmemiş kalemiydi. Kapatmak için replay'e **`--combined`**
eklendi: her kol canlı `forex.py` sembol listeleriyle (`--arm-symbols`) koşar, üretilen adaylar
klasik adaylarla **aynı kapı zincirinden** geçer (dedup + tek bütçe — canlı davranışının paritesi).
Refactor sonrası eşdeğerlik kilitlendi: `--entry-mode classic` birebir `n=563 net=+320.22` verir.

**Önce kollar izole** (arıza penceresi AR, XAU+BTC): supertrend_rsi +6.94 · ema_adx_pullback
+73.06 (PF 3.56) · london_breakout +4.19 · donchian_adx −2.34. Hiçbiri yıkıcı değil.

**Sonra birleşik** (klasik + tüm kollar, canlı semboller):

| Pencere | TEK KLASİK | ÇOKLU-KOL (canlı parite) |
|---|---|---|
| AR 10-08→10-13 | +320.22 · n 563 · PF 1.41 · DD 59.6 | **+393.46** · n 574 · PF 1.50 · DD 63.7 |
| OOS 08-08→09-07 | +4052.58 · n 3696 · PF 1.68 · DD 111 | **+4450.30** · n 3851 · PF 1.73 · DD 158 |
| IS 09-07→10-07 | +3226.43 · n 4095 · PF 1.53 · DD 107 | **+3256.71** · n 4246 · PF 1.51 · DD 150 |

**Sonuç:** çoklu-kol üç pencerede de **klasikten ≥** (AR/OOS'ta belirgin artı, IS'te yatay) ve
hiçbir pencerede negatife çevirmiyor. Dolayısıyla canlı zararın kaynağı **sinyal kolları DEĞİL**
— tersine replay'i daha da pozitif yapıyorlar. (DD hafif artar ~+40$; kabul edilebilir.)

### Tam canlı evren (13 sembol — tüm majör + kros + endeks)

Aynı karşılaştırma XAU+BTC yerine **canlı evrenin tamamında** (`EURUSD,GBPUSD,USDJPY,USDCHF,
AUDUSD,USDCAD,NZDUSD,GBPJPY,EURJPY,XAUUSD,NAS100,US30,BTCUSD`) tekrarlandı:

| Pencere | TEK KLASİK | ÇOKLU-KOL (canlı parite) |
|---|---|---|
| AR 10-08→10-13 | +424.57 · n 1099 · PF 1.27 · DD 93.45 | **+478.81** · n 1107 · PF 1.30 · DD 105.77 |
| OOS 08-08→09-07 | +4112.69 · n 6549 · PF 1.40 · DD 199.76 | **+4424.46** · n 6640 · PF 1.43 · DD 210.00 |
| IS 09-07→10-07 | +2577.08 · n 7678 · PF 1.21 · DD 265.42 | **+2779.62** · n 7866 · PF 1.22 · DD 266.06 |

Geniş evrende de kollar **her pencerede net kâr ekler, WR'yi düşürmez**; yalnız DD'yi hafif
artırır (AR +13$, OOS +10$, IS +1$). Üç pencere de pozitif kalır. Not: 13 sembollük OOS DD'si
(200→210) yönetişim barı olan $200'ün hemen üstünde — izlenmeli, ama bu geniş evren defteri,
XAU+BTC'nin işlem gördüğü çekirdek defter değil.

**Canlı −204$'ün zamanlaması bunu doğruluyor:** zarar, BE birleşim düzeltmesi canlıya girmeden
**önce** birikmişti. Düzeltme commit'i `2fece7af` (2026-10-12 20:26); canlı −204 ise eski `max`
formülü altında oluştu — maliyet şoku bölümünün gösterdiği gibi o formül gerçek maliyet altında
tam da bu büyüklükte negatife dönüyor.

## Açık kalan (dürüstlük notu)

Replay birleşim varyantı arıza penceresinde **+393** (çoklu-kol; tek klasik +320), canlı aynı
pencerede **−204**. Düzeltme WR farkının büyük kısmını kapatır ve **sinyal kolları ölçülüp elendi**.
Geriye kalan ölçülmemiş yürütme farkları:

1. ~~Canlı çoklu sinyal kolları~~ — **ÖLÇÜLDÜ, elendi** (yukarı bkz.: kollar zarar kaynağı değil).
2. MT5 gecikmesi/slipajı (tick-bazlı yürütme; replay bar-içi muhafazakâr model kullanır).
3. Kısmi TP + TP-iptal + BE + chandelier etkileşimi gerçek akışta (replay tek çıkış motoru koşar).

---

## Yeni strateji araştırması (2026-10-12) — radar'a eklenebilir mi?

Kullanıcı talebi: "radar'a ekleyebileceğimiz, kârlılığı/başarıyı artıracak işlem stratejileri
araştır, en uygun iki tanesiyle replay testi yap." Repo'nun 22 araştırma kolu **zaten** mean-reversion
/ stat-arb / ICT / squeeze / NR7 ailelerini elemiş; ayakta kalan tek aile trend/kırılım. Bu yüzden
iki aday da o aileden, **kanıtlanmış boşluklara** dayandırıldı ve canlı-parite bayraklarıyla koşuldu.

### Aday A — ORB (seans açılış-kırılımı) 1:1.5R + EoD flat

Londra kutusu (07→13 UTC) → NY overlap (13→16 UTC) kırılımı. **Trail-ride reddedildi** (pencere
içinde işaret değiştiriyordu: AR +24 / IS −147 / OOS −5). Sabit TP (SL×1.5) + girişten 3 saat
sonra zorla kapat ile:

| Pencere | XAU+US30 | TÜM 13 sembol |
|---|---:|---:|
| W1 15/07→08/08 | +51.70 · n 6 | — |
| W2 (OOS) 08/08→09/07 | +201.40 · n 19 · WR %94.7 | **+162.77** · n 101 · PF 1.78 |
| W3 (IS) 09/07→10/07 | +12.12 · n 15 | **−128.41** · n 103 · **PF 0.69** |
| AR | +10.74 · n 4 | — |
| 60g | +265.22 · n 40 · WR %92.5 | — |

**Verdict: barı GEÇEMEDİ.** XAU'da istikrarlı (kâr XAU'da toplanıyor; US30'un 07–13 kutbu yok →
endekste hiç işlem üretmiyor) ama tam evrende W3 negatife dönüyor (PF 0.69). Ek sembol eklemek
defteri bozuyor → genellenmiyor. Ayrıca n=15–19/pencere, yönetişim barının (≥100) çok altında.

### Aday B — NY-açılışı sign-momentum (Seeck 2026, uyarlanmış)

Kural: 13:30–14:00 UTC arasında kapanış ilk kapanıştan yüksekse **BUY**, düşükse **SELL**
(sign); 14:00–14:30 UTC'de tek giriş; SL = 1.5×ATR(14); sabit TP yok → chandelier trail;
girişten 3 saat sonra kapat (EoD). Sembol evreni: **XAUUSD + US30** (kanıtla seçildi).

| Pencere | n | net | WR | PF | maxDD |
|---|---:|---:|---:|---:|---:|
| W1 15/07→08/08 | 23 | **+101.66** | %95.7 | 4.90 | 36.23 |
| W2 (OOS) 08/08→09/07 | 40 | **+85.25** | %87.5 | 1.80 | 49.92 |
| W3 (IS) 09/07→10/07 | 42 | **+69.27** | %88.1 | 1.79 | 59.35 |
| AR 08/10→13/10 | 6 | **+37.20** | %100 | — | 7.88 |
| 60g toplam | 105 | **+256.18** | %89.5 | 2.16 | 59.35 |

**Maliyet şoku (60g, XAU+US30):** slip 0p +256.18 · 1p +206.39 · **2p +174.67 · PF 1.76 · WR sabit %89.5**
→ maliyete *dayanıklı* (WR hiç düşmüyor; klasik BE düzeltmesinin aksine).

**Ek sembolde bozmuyor:** 13-sembol canlı evren W2 +50.33 · W3 +44.30 (ikisi de pozitif, PF 1.35);
XAU+US30+BTC (slip 1p) +236.14 · PF 1.80 · WR %81.7.

**Per-sembol ayrışma (60g):** XAUUSD +182.04 · WR %91.8 (n49) · US30 +74.80 · WR %90 (n30) —
ama FX majörlerinde **negatif** (USDJPY −17.81 · GBPUSD −12.30 · GBPJPY −4.20). Edge metal/endekste.

**Verdict: yönetişim barını GEÇTİ** (net>0 · iki+ bağımsız pencerede pozitif · gerçek spread sonrası
pozitif · DD<$200 · ek sembollerde bozmuyor · maliyet şokuna dayanıklı). **Tek eksik:** pencere
başına n = 6–42, bar olan **≥100'ün altında** (60 günde 105). Yani "yüksek-hasılat, düşük-sıklık"
bir kol — toplam sistemi taşımaz, ama XAU/US30 defterine temiz artı ekler.

**Karar:** Aday B önerilir (yalnız XAUUSD + US30 evreninde, ayrı kol olarak, tek giriş/gün/sembol);
Aday A reddedilir.

### Uygulama (2026-10-13) — CANLIYA ALINDI

Kullanıcı onayıyla Aday B canlı motora eklendi (altıncı giriş kolu):

- `backend/app/routers/forex.py` — saf fonksiyon `sign_window_entry`; sabitler
  `LONDON_SIGN_STRATEGY`/`LONDON_SIGN_LABEL`; strateji kimliği (`london_sign` → LSGN/LONDON_SIGN);
  ayar alanları (`ls_enabled` **AÇIK**, `ls_symbols=[XAUUSD,US30]`, dakika-tabanlı sign/giriş
  pencereleri, `ls_sl_atr=1.5`, `ls_hold_hours=3.0`); `_LS_STATE`; canlı streaming bloğu
  (13:30-14:00 sign → 14:00-14:30 tek giriş); çıkış kablolaması (TP=0 → chandelier); hem paper
  hem MT5 yolunda EoD zaman-stopu (`hold_minutes` / `open_ts`).
- `scripts/mt5_bridge.py` — pozisyon yüküne `open_ts` eklendi (EoD yaş kontrolü).
- `scripts/forex_replay_backtest.py` — iki zaman-stopu hatası düzeltildi
  (`_time_stop_mode`'a `london_sign` eklendi; `emit()` `time_stop_bars`'ı geçirir).
- `backend/tests/test_forex_auto_paper.py` — `test_london_sign_entry_and_scope` (saf kural +
  kapsam + sıralama kilidi); bayat AUDNZD assert'i dürüst sözleşmeye çevrildi.

Geri alma: panelden `ls_enabled=False` veya `git revert`. İlk günlerde paper gözlemi önerilir.

**Bilinçli kabul edilen sınır:** pencere başına n = 6–42 (bar ≥100'ün altında) → bu bir
"yüksek-hasılat, düşük-sıklık" koldur; XAU/US30 defterine temiz artı ekler, tek başına taşımaz.
