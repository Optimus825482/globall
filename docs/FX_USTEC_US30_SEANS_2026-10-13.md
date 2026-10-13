# USTEC + US30 Seans-Açılış Deneyi (2026-10-13)

**İstek:** "XAGUSD istemiyorum; sistemde USTEC için ve US30 için koş."

**Bağlam:** London Sign (NY-açılışı sign-momentum) top-5 turundan sonra tek ayakta kalan
kanıtlı aileydi; kalan açık soru, bu kolun **USTEC/NAS100'e genişletilip genişletilemeyeceği**ydi
(US30 zaten canlı LS kapsamındadır). Bu koşum o soruyu iki bağımsız pencerede + defter-katkı
(yönetişim barı #6) ölçer.

Araç: `scripts/forex_replay_backtest.py` · Cache: `outputs/replay_cache_60d_fxwide.json`
(kanonik) · Spread: `outputs/fx_spread_idx.json` (p95; NAS100 = USTEC alias 1.0 pip).

---

## 0. İki teknik gerçek (koşumdan önce saptandı)

1. **USTEC = NAS100 alias'ıdır.** `forex.py:407` (`"USTEC": "NAS100"`). `FOREX_SYMBOLS`'te
   **yalnız NAS100** vardır; "USTEC" adlı bir kayıt YOKTUR. Canlı boru hattı (tick üretimi,
   LS/klasik blıkları, `_ls_item` araması) sembolü `FOREX_SYMBOLS`'te arar → canlıda
   `ls_symbols`'e "USTEC" yazmak **hiçbir şey yapmaz**; doğru ad **NAS100**'dür.
   Bu yüzden replay koşumları NAS100 anahtarıyla yapıldı (cache'teki `USTEC` dizisi
   `replay_cache_idx_relabel_5m.json` ile NAS100'e relabel edildi).

2. **İki cache farklı sağlayıcıdan gelir ve işaret döndürür.** US30 London Sign:
   kanonik `fxwide` cache'te W1 OOS **+30.41** (WR %81), tek-seferlik `idx_5m` cache'te
   **−3.20** (WR %77). Aynı sembol, aynı pencere, aynı kural → farklı sonuç. Seviyeler ve
   bar aralıkları farklı (USTEC 09-15 12:00: idx 28953.8 vs fxwide 29082.1). **Kanonik kaynak
   = fxwide** (BE-düzeltmesi, London Sign, top-5 — tüm kanıtlı kararlar fxwide ile üretildi).
   `idx_5m` yalnız `fx_str_h48_campaign.py`'a özel tek seferlik veri; karar için kullanılmaz.

---

## 1. London Sign kolu — USTEC (NAS100) + US30

Pencere: **W2 (IS) 08-01→09-07** · **W1 (OOS) 09-07→10-07** · **W3 07-14→08-01**.
Kural: 13:30-14:00 UTC sign → 14:00-14:30 tek giriş/gün, SL 1.5×ATR, TP yok (chandelier), 3s EoD.

| Sembol | W1 OOS | W2 (IS) | W3 |
|---|---|---|---|
| **USTEC (NAS100)** | **+83.29** · n21 · WR %85.7 | **+57.56** · n25 · WR %80.0 | **+43.17** · n10 · WR %90.0 |
| US30 (zaten canlı) | +30.41 · n21 · WR %81.0 | +30.15 · n25 · WR %92.0 | +50.03 · n10 · WR %100 |

**Üç pencerenin üçünde de USTEC pozitif.** İşaret tutarlı.

### Defter-katkı testi (yönetişim barı #6): LS XAU+US30 → + NAS100

| Pencere | LS XAU+US30 (canlı) | LS XAU+US30+NAS100 | Fark | XAU/US30 pnl |
|---|---:|---:|---:|---|
| W1 OOS | +64.39 | **+171.03** | **+106.64** | birebir sabit |
| W2 (IS) | +171.19 | **+228.75** | **+57.56** | birebir sabit |
| W3 | +64.95 | **+108.12** | **+43.17** | birebir sabit |

XAU ve US30 pnl'i her pencerede **birebir aynı kalıyor** → NAS100 LS'te bağımsız çalışıyor,
mevcut defteri bozmuyor, üstüne temiz artı ekliyor.

### Maliyet şoku (W1 OOS, LS XAU+US30+NAS100)

| slip/bacak | net | NAS100 pnl | WR |
|---|---:|---:|---:|
| 0p | +171.03 | +106.64 | %85.7 |
| 1p | +151.31 | +100.16 | %85.7 |
| 2p | **+131.67** | **+93.72** | %85.7 (**sabit**) |

NAS100 maliyete dayanıklı (WR hiç düşmüyor) — London Sign'ın XAU/US30'daki imzasıyla aynı.

---

## 2. Klasik kol — USTEC (NAS100) izole

| Pencere | n | WR% | net$ | PF |
|---|---:|---:|---:|---:|
| W1 OOS | 639 | 73.1 | **+262.95** | 1.26 |
| W2 (IS) | 712 | 68.5 | **−13.52** | 0.99 |
| W3 | 371 | 79.2 | +345.85 | 1.32 |

**W2 negatif → işaret dönüyor.** Yönetişim barını (iki bağımsız pencerede pozitif) geçmiyor.

### Tam canlı defter A/B (klasik, tüm canlı evren)

| Pencere | NAS100 YOK | NAS100 VAR | NAS100 katkısı |
|---|---:|---:|---:|
| W1 OOS | +2444.87 | +2651.23 | **+207.45** |
| W2 (IS) | +5619.94 | +5495.50 | **−55.75** |

Klasik NAS100 de bir pencere artı, diğerinde eksi → **işaret dönüyor**, defter barını geçmiyor.

---

## 3. Mimari kısıt (belirleyici bulgu)

Canlı motorun **kapsam kapısı** (`forex.py:5357`) tüm adayları — London Sign dahil —
`allowed_symbols` ile eler:

```python
if sym not in _AUTO_SETTINGS.allowed_symbols:
    continue   # LS adayı da buraya takılır
```

Değişmez kural (`test_forex_auto_paper.py` ile kilitli): `allowed_symbols ⊆ FOREX_SYMBOLS`
(hayalet-parite kilidi). NAS100 `FOREX_SYMBOLS`'te, USTEC değil.

**Sonuç:** NAS100'ü `ls_symbols`'e eklemek TEK BAŞINA yetmez; `allowed_symbols`'a da eklemek
gerekir — ama bu klasik radarı da otomatik açar (klasik NAS100 işaret-tutarsız, bkz. §2).
Ayrıca canlı LS bloğu sembolü `FOREX_SYMBOLS`'te arar (`_ls_item`), yani ad **NAS100** olmalıdır.

---

## 4. Karar

| Kol | Sembol | İki/üç pencerede | Defteri bozuyor mu | Verdict |
|---|---|---|---|---|
| **London Sign** | USTEC (NAS100) | **3/3 pozitif** | hayır (+$107/+$58/+$43) | ✅ kanıt GEÇTİ |
| Klasik radar | USTEC (NAS100) | ✗ (W2 negatif) | ✗ (W1 +, W2 −) | ❌ işaret dönüyor |

**USTEC'i London Sign koluna eklemek kanıtlıdır; klasik radar koluna eklemek DEĞİLDİR.**
Ancak mevcut mimari ikisini ayıramıyor: `allowed_symbols` kapısı LS'i de kapsıyor.

### Diğer kollar — NAS100 izole ölçüm (2026-10-13)

| Kol | W1 OOS | W2 (IS) | n | Karar |
|---|---:|---:|---:|---|
| London Sign | **+83.29** | **+57.56** | 10–25 | ✅ EKLE |
| EMA+ADX pullback | **+3.25** | **+71.00** | 33–37 | ✅ EKLE |
| Donchian+ADX | **+23.37** | **+2.57** | 32–47 | ✅ EKLE |
| Klasik radar | +262.95 | **−13.52** | 371–712 | ⚠ kullanıcı kararıyla eklenir |
| **S3 (Supertrend+RSI)** | **−16.62** | **−3.44** | 11 | ❌ **iki pencerede de NEGATİF → eklenmedi** |
| London Breakout | 0 işlem | 0 işlem | — | NAS100'de Asya kutusu yok |

### Uygulama (2026-10-13) — CANLIYA ALINDI (kullanıcı kararı: "tüm kollarda aç")

Kullanıcı "USTEC'i tüm kollarda aç" dedi; S3 kolu NAS100'de iki pencerede de negatif çıktığı
için **S3 hariç** tüm kollara eklendi:

- `backend/app/routers/forex.py` — `allowed_symbols` += NAS100; `ls_symbols` += NAS100;
  `ema_adx_symbols` += NAS100; `mode_symbols` += NAS100. **S3 (`s3_symbols_5m/15m`) DOKUNULMADI.**
- Kalıcı `forex_auto_settings.json` (`/data`) — aynı listeler güncellendi; ayrıca **bayat
  hayalet girdiler temizlendi** (`s3_symbols_5m`'den AUDNZD; `lb_symbols`'ten 11 hayalet kros).
  Eklenen `ls_symbols` anahtarı (dosyada yoktu → kod varsayılanı geçerliydi).
- `backend/tests/test_forex_enhancements.py`, `test_forex_improvements.py` — `allowed_symbols`
  9→10 kilidi; NAS100 artık izinli, USTEC alias'ı hâlâ dışarıda.
- `backend/tests/test_forex_auto_paper.py` — `ls_symbols` sıralama kilidi NAS100 ile güncellendi.

**Geri alma:** panelden NAS100'ü ilgili listeden çıkar (veya `git revert`); kalıcı dosyada da
çıkarılmalı yoksa kod varsayılanını maskeler.

### Not — S3 neden dışarıda

Kullanıcı "tüm kollarda aç" dedi; ancak S3 (Supertrend+RSI) NAS100'de W1 **−16.62** / W2
**−3.44** (n=11, iki pencerede de negatif) → zarar ürettiği ölçülmüş tek koldur. Kullanıcının
ilk ilkesi ("zararla kapanan işlemlerin karar mekanizmasını düzelt") gereği **eklenmedi**;
kullanıcı onayı bu istisnayı kapsıyor. Sonradan istenirse `s3_symbols_15m`'e eklenebilir.

---

## 5. Dürüst sınırlar

1. **USTEC kararı NAS100 verisiyle alındı** — endeks CFD'leri için kanonik 5m cache yalnız
   NAS100/US30 içerir; USTEC adıyla canlı sembol ayrı ölçülmedi (alias olduğu varsayımı
   forex.py:407'ye dayanır).
2. **n düşük** (LS pencere başına n = 10–25) — London Sign zaten "yüksek-hasılat, düşük-sıklık"
   bir koldur; USTEC'te de öyle.
3. **Replay canlıya vekil değil** (MT5 tick gecikme/slipaj, kısmi-TP+BE+chandelier etkileşimi
   modellenmiyor).
4. **İki cache çelişkisi bir uyarıdır:** endeks kararları veri-kaynağına duyarlı. Karar öncesi
   kaynak doğrulanmalı (burada fxwide seçildi — kanıtlı kararların kaynağı).

**Artefaktlar:** `outputs/idx_ls_w*.json`, `outputs/ls{,A,B}_w*.json`, `outputs/lss_*_w1.json`,
`outputs/ustec_iso_*.json`, `outputs/nas100_classic_w*.json`, `outputs/book_{noN,N}_w{1,2}.json`.
