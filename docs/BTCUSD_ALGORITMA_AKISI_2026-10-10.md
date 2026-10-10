# BTCUSD Algoritma Akışı — 2026-10-10 (düzeltmelerden SONRA)

**Kapsam:** `backend/app/routers/forex.py` (otonom forex motoru, 6.9k satır), `scripts/mt5_bridge.py`, `scripts/forex_replay_backtest.py`.
**Amaç:** 2026-10-10 denetiminde bulunan P0/P1/P2 sorunları düzeltildikten sonra BTCUSD'nin **uçtan uca karar akışını** tek belgede yeniden yazmak.
**İlgili belgeler:** bulgular ve kanıtlar → `BTCUSD_ALGORITMA_INCELEME_RAPORU_2026-10-10.md`; kalibrasyon → `FOREX_BTCUSD_MOMENTUM_KALIBRASYON_2026-10-10.md`.

---

## 0. Bir bakışta ne değişti

| Katman | Önce | Sonra |
|---|---|---|
| Sembol normalizasyonu | `sym == "BTCUSD"` tam eşitlik; `BTCUSD.m` gelince BTC kuralları sessizce düşer | `canonical_symbol()` (motor) + `to_app_symbol()` (köprü) sonek/kısa-ad normalize eder |
| Donchian akışı | BTC `mode_symbols` içinde (replay izole: −$27.50/113 işlem) | **BTC çıkarıldı** → `["XAUUSD","GBPJPY","EURJPY"]` |
| EV kalkanı | BTC koşulsuz muaf | **BTC muaf değil** (`btc_ev_exempt=False`), XAU muafiyeti korunur |
| Net-negatif fren | yok | mekanizma var, **varsayılan KAPALI** (A/B'de PnL düşürdü) |
| Risk normalizasyonu | kriptoda `risk_skip` zorla iptal → aşırı lot kullanılabiliyor | lot kategori tabanına **sabitlenir** (`crypto_risk_clamp_enabled=True`) |
| Emir sonucu | köprü hatayı yalnız konsola yazar; motor emri "açıldı" sanar | `command_results` kanalı; hata → soğuma geri açılır |
| Flip | BTC flip'te karşı bacak kapanır, 60 sn düz kalır | `_LAST_BTC_EXIT_TIME = 0.0` → gerçekten ters yöne döner |
| Ayar kalıcılığı | bellek-içi + tüm-nesne değişimi | diske yazılır + **kısmi merge** |
| Sembol dedup | kaynak-kapsamlı (S3/LB yalnız kendi adayını düşürür) | **tüm kaynaklarda sembol-bazlı tam dedup** |

---

## 1. Sembol yüzeyi

```
FOREX_SYMBOLS["BTCUSD"]   forex.py:192-202
  category   = "crypto"
  pip_size   = 1.0     digits = 2
  base/quote = BTC / USD
  tv_symbol  = BINANCE:BTCUSDT
  default_price = 66500.0
```

- **Pip USD değeri:** `get_symbol_trading_specs()` → `pip_val = 1.0` (kategori tablosundan; sabit, 10× hatası **yok** — `forex.py:1230` yorumu geçmiş düzeltmeyi anlatıyor).
- **Kanonikleştirme (P2-7):** `canonical_symbol()` (`forex.py:431`) — `BTCUSD.m`, `BTCUSD.micro`, `BTC` → hepsi `BTCUSD`. Bu olmadan aşağıdaki **tam eşitlik** dalları (BTC soğuması, `btc_min_score`, EV muafiyeti, spread genişletmesi) sonekli sembolde sessizce düşüyordu.
  - Değişmez (invariant): `canonical_symbol`'ün ürettiği **her** ad `FOREX_SYMBOLS ∪ _RETIRED_FOREX_SYMBOLS` içinde olmalı. Bu yüzden `XBRUSD → USOIL` (UKOIL **değil** — UKOIL iki listede de yok).
- **Köprü tarafı:** `to_app_symbol()` (`mt5_bridge.py`) aynı işi yapar; bilinmeyen kısa adı (GOLD/BTC/WTI) eski davranışla olduğu gibi geçirir, kanonikleştirmeyi motor üstlenir.

---

## 2. Aday üretimi — BTC'yi besleyen üç kaynak

Döngü her **1.5 sn**'de bir tarar (`forex.py:3946`). Adaylar `get_forex_radar()` + mod üreticilerinden toplanır (`4270-4625`).

| # | Kaynak | BTC durumu | `entry_source` | Çıkış kuralı |
|---|---|---|---|---|
| 1 | **Klasik M1/M5 Çoklu Radar** | ✅ aktif (`RADAR_SCAN_SYMBOLS`, `224`) | *(boş)* | TP **YOK**; BE + trailing/chandelier; SL 1.5×ATR |
| 2 | Donchian+ADX | ❌ **çıkarıldı** (`mode_symbols`, `3213`) | `donchian` | — |
| 3 | EMA+ADX geri-çekilme | — (`ema_adx_symbols=["XAUUSD"]`) | `ema_adx_pullback` | — |
| 4 | **S3 (Supertrend+RSI) 15m** | ✅ aktif (`s3_symbols_15m`, `3235`) | `s3_15m` | SL 1.5×ATR / **TP 2.0×ATR** |
| 5 | **London Breakout** | ✅ aktif (`lb_symbols`, `3242`) | `london_breakout` | SL = kutu × 0.5 / TP = SL × R |

> **P0-2 kanıtı:** 32 gün, p95 spread, izole BTC — klasik kol **+$396.19** / donchian kol **−$8.94** (113 işlem, %63.7 WR). Donchian GBPJPY/EURJPY için kalibre edilmişti; BTC'de kanıtlanmadan çalışıyordu.

**P1-8 dedup (düzeltildi):** Her kaynak aday eklerken artık `symbol` bazında **tam dedup** yapar (`4350`, `4507`, `4603`). Önceden S3/LB yalnız kendi adayını düşürüyordu → aynı BTC aynı listede farklı yönlerde iki adayla bulunup ardışık taramalarda **flip churn** üretiyordu.

---

## 3. Giriş kapı zinciri (BTCUSD için, sırayla)

`for cand in candidates:` (`forex.py:4751`) — **kapılardan biri `continue` derse o aday düşer**; döngü başına en fazla **1 emir** (`break`, `5434`).

### A. Pozisyon/kapsam ön kapıları

| # | Kapı | Satır | BTC notu |
|---|---|---|---|
| 0 | `allowed_symbols` kapsamı | `4759` | Kesin — güçlü sinyal bile dışarı çıkamaz |
| 1 | Yön geçerliliği (`BUY`/`SELL`) | `4762` | — |
| 2 | **Seri-SL + yön bazlı seri-SL soğuması** | `4768` | `loss_streak_limit=3`; sembol **veya** (sembol,yön) 3 ardışık tam-SL → `loss_streak_cooldown_sec=300` sn yeni giriş yok (flip dahil, açık pozisyon yönetimi sürer) |

### B. Soğuma kalkanları

| # | Kapı | Satır | BTC notu |
|---|---|---|---|
| 2b | **BTC Özel Soğuma** | `4943` | Süre artık `btc_cooldown_sec` (P2-6: eskiden kodda 60 sabitti). Kapanıştan sonra N sn yeni giriş yok |
| 3 | Sembol soğuması | `4965` | BTC için 60 sn (altın `gold_cooldown_sec`) |

### C. Kayıp-uyarlamalı frenler

| # | Kapı | Satır | BTC notu |
|---|---|---|---|
| 3b | **Sembol EV Kalkanı** | `4985` | **BTC artık MUAF DEĞİL.** `ev_guard_enabled=True` ve `btc_ev_exempt=False` → BTC de 24 saatlik pencerede değerlendirilir: `_collect_symbol_ev` + `ev_guard_decision` (min işlem / maks WR / zarar tabanı). XAU muafiyeti korunur. Geri alma: `btc_ev_exempt=True` |
| 3c | **BTC net-negatif freni** | `5014` | Mekanizma mevcut ama **varsayılan KAPALI** (`btc_net_negative_guard_enabled=False`). Açılırsa: son 6 saatte ≥6 işlem ve net < $0 → BTC yeni giriş almaz. A/B: 32g PnL **+$373 → +$222**, iki pencerede de negatif → açılmadı |

> **P0-3 özeti:** Eski kod BTC'yi EV kalkanından muaf tutuyordu ve "60 sn soğuma" kayıp-uyarlamalı değildi → SL/TP salınımı (SL, TP, SL, SL, TP, SL…) hiçbir fren takılmadan net-negatif seri üretebiliyordu. Artık **EV kalkanı BTC'de aktif**; net-negatif fren ise kanıtla sınanıp kapalı bırakıldı.

### D. Piyasa rejimi / kalite kapıları

| # | Kapı | Satır | BTC notu |
|---|---|---|---|
| 4 | **DXY rejim filtresi** | `5036` | BTC **DXY vetosundan muaf** (`forex.py:485`); `weak_symbol_score_bump` BTC'ye uygulanmaz |
| 5b | Parite korelasyon kalkanı | `5061` | \|ρ\|≥0.85 aynı-USD-bias çakışması sınırlanır — BTC'yi asıl etkileyen kapı budur ("slot" değil) |
| 5c | Majör FX güçlendirme | `5090` | FX'e özel; BTC kapsam dışı |
| 6 | **Spread filtresi** | `5114` | BTC/ETH'te limit `max(50, max_spread_pips×10)` — `pip_size=1.0` telafisi |
| 7 | **Skor eşiği** | `5128` | BTC özel: `btc_min_score` (varsayılan **76.0**; 0 ise global `min_score`). Emtia 78.0 kuralı BTC'ye uygulanmaz |
| 7b | ADX trend gücü | `5149` | Klasik BTC adayı için geçerli |
| 7c | **SuperTrend yön teyidi** | `5163` | Klasik BTC adayı için geçerli. **İstisna:** `s3_*` ve `ema_adx_pullback` atlar (kendi yön motorlarını taşırlar — replay PURE koşumu) |

> Not: Donchian BTC'de artık üretilmediği için "donchian adayı SuperTrend vetosuna takılıyor" sorunu BTC'de kendiliğinden kapandı.

---

## 4. Lot ve risk (P0-4 düzeltmesi)

```
is_crypto = "BTC" in sym or "ETH" in sym          forex.py:5268
lot_ceiling = 50.0                                 forex.py:5287   (kripto kategori tavanı)
mt5_lots = max(0.01, min(raw_calc_lots, 50.0))     forex.py:5288
raw_calc_lots = risk_usd / (sl_pips × pip_val)     forex.py:5263
risk_usd = aktif_bakiye × risk_per_trade_pct/100   forex.py:5262
```

**Risk normalizasyonu (`5302`)** — ATR ile genişleyen SL'de lot bütçeyi aşabilir:

```
mt5_lots, risk_skip = apply_risk_normalization(sym, mt5_lots, sl_pips, pip_val, risk_usd)
if risk_skip and (is_crypto or is_gold):
    if crypto_risk_clamp_enabled:          # ← varsayılan True
        mt5_lots = 0.01                    # kripto kategori TABANI
        risk_skip = False                  # işlem devam eder, lot güvenli
    else:
        risk_skip = False                  # ESKİ davranış: aşırı lot korunur
if risk_skip:  → işlem pas geçilir
```

**Önce:** kriptoda `risk_skip` **koşulsuz** iptal ediliyordu → geniş 1.5×ATR BTC SL'i ile işlem 2× sert risk bandını **bilerek** aşabiliyordu.
**Sonra:** lot kategori tabanına (0.01) sabitlenir; risk asla artmaz, aday da ezilmez.

**Gerçek risk logu:** emir açılışında `actual_risk_usd = mt5_lots × sl_pips × pip_val` hesaplanıp karar akışına yazılır (`5418`, `5423`).

---

## 5. Çıkış motoru

### 5.1 Emir seviyesinde (giriş anında kurulur)

| Aday | SL | TP | Kısmi kâr |
|---|---|---|---|
| **Klasik BTC** | **1.5×ATR** (`crypto_sl_atr_mult`) | **YOK** (`crypto_tp_enabled=False`) | — |
| S3 15m | 1.5×ATR (`s3_sl_atr`) | **2.0×ATR** (`s3_tp_atr_15m`) | — |
| London Breakout | kutu × `lb_sl_box_frac` | SL × `lb_tp_r` | — |

```
atr_exit_enabled=True (varsayılan):
    BTC/ETH → get_atr_exit_levels(..., sl_atr_mult=crypto_sl_atr_mult)   forex.py:5207
    diğer   → get_atr_exit_levels(atr_pips, spec["sl_pips"], spec["tp_pips"])
```

- **P2-10 uyarısı:** `atr_exit_enabled=False` iken `crypto_sl_atr_mult` ayarlıysa BTC sessizce `spec["sl_pips"]`'e dönerdi. Artık karar akışına 300 sn'de bir uyarı düşer (`5218-5233`).
- Klasik BTC'de sabit TP kurulmadığı için kazanç **BE kilidi + trailing/chandelier** ile koşturulur (2026-10-06 30g replay kazananı).

### 5.2 Pozisyon seviyesinde (her taramada, açık pozisyonlar)

`forex.py:3804-4180` — sırayla:

1. **(a) Başabaş (BE) denetimi** (`4027`) — volatilite ve R tabanlı dinamik eşik; `calculate_breakeven_target()`. `breakeven_activated=True` işaretlenir.
2. **(b) Trailing SL** (`4081`) — BE aktifse veya kâr `eff_trail_pips`'i geçtiyse:
   - **Chandelier** (`chandelier_atr_mult=1.2`): kâr tepesinden 1.2×ATR geri verilince kilit
   - Sabit-pip trail (chandelier kapalıysa)
   - Trailing SL asla 1$ BE seviyesinin **altına inmez** (`4091`, `4108`)
3. **(b2) TP iptali** (`4125`) — `tp_cancel_on_trail=True` (canlı varsayılan AÇIK): trailing devreye girince sabit TP emri çekilir (`pos["tp_price"]=0`) ve MT5'te `MODIFY_SLTP tp_action='cancel'` kuyruğa girer. Uzun trendi TP'ye takılmadan koşturur. Klasik BTC zaten TP'siz → etkisiz.
4. **(c) Kapanış denetimi** (`4173`) — TP_HIT / SL_HIT / BE_HIT; ayrıca seans kapanışı ve ST-flip (S3 5m) çıkışları.

---

## 6. Emir gönderimi ve **sonuç geri bildirimi** (P0-1 düzeltmesi)

### Önce (hatalı)

```
köprü:  if not res.get("success"): print(...)          # yalnız konsol
motor:  commands = list(pending); pending.clear()      # KOŞULSUZ temizle
        _LAST_SYMBOL_ENTRY_TIME[sym] = now_ts          # 60 sn soğumaya ayarla
```

Broker emri reddederse motor yine de "açıldı" sanar → panel hayalet bekler, gerçekte pozisyon yok, aday 60 sn yeniden üretilmez. **BTC en çok maruz kalan semboldü** (geniş SL + lot tavanı nedeniyle en olası ret alan sembol).

### Sonra (düzeltilmiş)

**Köprü tarafı** (`mt5_bridge.py`):
```
_COMMAND_RESULTS: list = []          # son sync'ten beri biriken sonuçlar
_COMMAND_RESULT_CAP = 50
record_command_result(cmd, res, error=None)
  → {id, action, symbol, ticket, success, retcode, error, ts}
sync payload: "command_results": list(_COMMAND_RESULTS)
başarılı sync sonrası: _COMMAND_RESULTS.clear()
```
Her emir (OPEN/CLOSE/CLOSE_PARTIAL/CLOSE_ALL/MODIFY_SLTP) `try/except` içinde çalıştırılır; istisna da sonuç olarak raporlanır — sessiz yutma yok.

**Motor tarafı** (`forex.py:6880`):
```
if req.command_results:
    for _cr in req.command_results:
        if not _cr["success"] and _cr["action"] == "OPEN_ORDER":
            _LAST_SYMBOL_ENTRY_TIME.pop(sym, None)   # giriş soğumasını GERİ AÇ
            if "XAU" in sym or "GOLD" in sym: _LAST_GOLD_EXIT_TIME = 0.0
            if "BTC" in sym:                  _LAST_BTC_EXIT_TIME  = 0.0
        → karar akışına "❌ MT5 emri BAŞARISIZ … soğuma geri açıldı" / "✅ MT5 emri uygulandı"
```
`retcode`/`success` alanı olmayan **eski köprü sürümleriyle geriye dönük uyumlu** (`command_results` boş gelir).

---

## 7. Flip (ters dönüş) semantiği — P1-6 düzeltmesi

Aynı sembolde zıt yönlü aday ve mevcut pozisyon varsa (`forex.py:4838`):

```
1. Zıt yöndeki bekleyen OPEN_ORDER komutları temizlenir
2. _LAST_SYMBOL_ENTRY_TIME[sym] = 0.0            # sembol soğuması sıfır
3. "XAU"/"GOLD" → _LAST_GOLD_EXIT_TIME = 0.0     # (mevcut)
4. "BTC"       → _LAST_BTC_EXIT_TIME  = 0.0      # ← P1-6: EKLENDİ
5. Döngü devam eder → yeni yön emri açılır
```

**Önce:** `_close_position_internal` BTC çıkış saatini *şimdi* yapıyordu ama flip bloğu `_LAST_BTC_EXIT_TIME`'ı sıfırlamıyordu → hemen ardından 2b kapısı (`4948`) yeni yönü 60 sn reddediyordu. Sonuç: yorumun vaat ettiği "anında ters yöne geç" BTC'de gerçekleşmiyor, flip **kapanıp düz kalıyordu**. MT5 yolunda kapanış kuyruklu olduğu için paper ve MT5 BTC aynı sinyalde farklı davranıyordu — artık ikisi de dönüyor.

---

## 8. Ayar yüzeyi — BTC'ye dokunan alanlar

`ForexAutoPaperSettings` (`forex.py:3155`), **diske kalıcı** (`_settings_store_path()`, `3283`) ve endpoint **kısmi merge** yapar (`5708`, P1-5).

| Ayar | Varsayılan | Etki |
|---|---|---|
| `crypto_sl_atr_mult` | `1.5` | BTC SL genişliği (0 = global 1.1×ATR) |
| `crypto_tp_enabled` | `False` | Klasik BTC'de sabit TP yok |
| `btc_min_score` | `76.0` | BTC giriş skor eşiği (0 = global `min_score`) |
| `btc_cooldown_sec` | `60.0` | BTC çıkış→giriş soğuması (P2-6: artık panelden) |
| `btc_ev_exempt` | **`False`** | BTC EV kalkanından muaf mı (P0-3) |
| `btc_net_negative_guard_enabled` | **`False`** | BTC net-negatif pencere freni (A/B'de kapalı kaldı) |
| `crypto_risk_clamp_enabled` | **`True`** | Kriptoda risk-skip yerine lot tabanı (P0-4) |
| `tp_cancel_on_trail` | `True` | Trailing girince TP iptal (canlı kazanılan V03) |
| `chandelier_atr_mult` | `1.2` | Kâr tepesinden geri verme tavanı |
| `loss_streak_limit` | `3` | Seri-SL sigortası |
| `loss_streak_cooldown_sec` | `300.0` | Seri-SL soğuması |
| `max_positions_per_symbol` | `1` | BTC'de tek pozisyon (P2-5: yorum düzeltildi) |
| `donchian_adx_min` / `donchian_max_per_day` | `18.0` / `2` | P2-9: kodda sabitti → ayara taşındı (BTC artık donchian kullanmıyor) |

**P1-5 kanıtı:** eskiden `POST /auto-paper/settings` **tüm nesneyi** değiştiriyordu → eksik alan içeren herhangi bir gövde `btc_min_score`→76.0, `crypto_sl_atr_mult`→1.5, `allowed_symbols`→22'lik varsayılan olarak **sessizce sıfırlıyordu**. Artık `merge_settings_payload()` yalnız gönderilen alanları uygular.

**P1-7:** `reset-symbol-guards` (tam sıfırlama) artık `_SYMBOL_DIR_LOSS_STREAK` ve `_SYMBOL_DIR_LOSS_COOLDOWN_UNTIL`'ı da temizler (`5845`) — eskiden BTC 3 ardışık BUY SL sonrası "temiz sayfa" dense bile BUY kapısı kapalı kalıyordu.

---

## 9. Uçtan uca akış (özet şema)

```
[1.5 sn döngü]
  │
  ├─ SL/TP/trailing/BE güncelle (açık pozisyonlar)        3804-4180
  │     └─ BE kilidi → chandelier trailing → TP iptali → TP/SL/BE_HIT kapanış
  │
  ├─ Aday üretimi                                          4270-4625
  │     ├─ Klasik radar (BTC ✅)          entry_source=""
  │     ├─ Donchian+ADX  (BTC ❌ çıktı)   entry_source="donchian"
  │     ├─ EMA+ADX (XAU)                  entry_source="ema_adx_pullback"
  │     ├─ S3 15m (BTC ✅)                entry_source="s3_15m"
  │     └─ London Breakout (BTC ✅)       entry_source="london_breakout"
  │     └─ ★ her kaynakta sembol-bazlı TAM dedup (P1-8)
  │
  └─ Kapı zinciri  (for cand in candidates)                4751
        allowed_symbols → yön → seri-SL/yön-seri-SL (300sn)
        → BTC soğuma (btc_cooldown_sec) → sembol soğuma (60sn)
        → ★ EV kalkanı (BTC ARTIK MUAF DEĞİL)              4985
        → BTC net-negatif freni (varsayılan KAPALI)        5014
        → DXY vetosu (BTC muaf) → korelasyon kümesi
        → spread (BTC: max(50, ×10)) → skor (btc_min_score=76)
        → ADX → SuperTrend (s3/EAP muaf)
        → lot: kripto tavan 50, risk_normalize → ★ lot TABANA SABİTLE
        → emir gönder (MT5 kuyruk / paper defter)
        → ★ köprü command_results → başarısızsa soğuma GERİ AÇ
        → break  (döngü başına en fazla 1 emir)
```

---

## 10. Kalan bilinen sınırlar (bilinçli)

| # | Konu | Durum |
|---|---|---|
| P2-2 | Replay motorunda `mode_exclusive` yok | GBPJPY/EURJPY klasik sinyali simüle edilir; BTC'yi doğrudan etkilemez, portföy toplamını kiritir. Bilinen sınır |
| P2-8 | BTC `pip_val` her iki tarafta sabit `1.0` | Broker kontrat boyutu okunmuyor. Bilinen sınır (10× hatası **değil**) |
| P2-3 | BTC spread >$100 ise `_LIVE_SPREAD_PIPS` güncellenmez → sentetik 12.0 | `pip_size=1.0` nedeniyle; düşük önem |
| — | Net-negatif fren | Mekanizma var, kanıt gelirse `btc_net_negative_guard_enabled=True` ile açılır |
| — | Canlı −$70.69 tekrar üretilemedi | 32g replay +$396; 2 günlük/75 işlemlik örneklem yetersiz. Kapatma kararı için 30-60 gün canlıya-parite replay şart |

---

## 11. Doğrulama durumu

- **AST parse:** üç dosya da geçer.
- **Test paketi:** `test_forex_enhancements.py + test_forex_auto_paper.py + test_forex_improvements.py` = **190 test, tümü geçiyor** (sistem Python 3.12).
- **Yeni regresyon testleri:** `command_results` soğuma geri açma · kısmi ayar merge'i · BTC'nin donchian dışı olması · net-negatif frenin varsayılan kapalı olması · `crypto_risk_clamp_enabled` · `canonical_symbol` sonek normalizasyonu · **evren invariant'ı** (kanonikleştirme spec'siz sembol sızdırmaz) · donchian eşiklerinin ayardan okunması.
- **Replay A/B (32g, p95 spread, izole BTC, `--skip-old`):**
  - BASE (EV açık) **2330 işlem / %65.1 / +$396.19**
  - `--no-ev-guard` (canlı parite) 2588 / %63.4 / +$373.01
  - donchian_adx 113 / %63.7 / **−$8.94** → P0-2 çıkarması doğrulandı

**Araç tuzağı (tekrar düşmemek için):** replay'de `--spread-profile outputs/fx_spread_p95.json` **tam yolu** verilmeli. Çıplak dosya adı sessizce çözülemez ve yalnız `[UYARI]` satırıyla sentetik kategori spread'lerine düşer → tüm A/B sonuçları geçersiz olur.

---

*Bu belge, 2026-10-10 denetim bulgularının tamamı düzeltildikten sonraki kodu anlatır. Satır numaraları çalışma ağacındaki güncel dosyalara aittir.*
