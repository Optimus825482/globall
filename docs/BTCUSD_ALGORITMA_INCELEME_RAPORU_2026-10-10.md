# BTCUSD Algoritma İnceleme Raporu — 2026-10-10

**Kapsam:** `backend/app/routers/forex.py` (6837 satır, otonom forex motoru), `scripts/mt5_bridge.py` (1311), `scripts/forex_replay_backtest.py` (3524, çalışma ağacında değiştirilmiş), `frontend/app/settings`, `backend/tests/test_forex_*`.
**Yöntem:** 8 paralel bağımsız ajan + yazar doğrulaması (kod okuma, AST taraması) + canlı işlem CSV analizi + gerçek replay A/B (32 günlük önbellek, p95 spread).
**Etiketler:** **[DOĞRULANDI]** = kod/veri ile birebir teyit edildi · **[ŞÜPHELİ]** = kod okumasıyla makul ama çalışma-zamanı teyidi gerekir.
**Not:** Global `CLAUDE.md` jCodeMunch-MCP'yi zorunlu tutuyor; bu oturumda jCodeMunch araçları kayıtlı değildi (ToolSearch boş döndü). Bu nedenle keşif yerel Read/Grep/AST ile yapıldı.

> **DURUM (2026-10-10, düzeltmelerden sonra):** Bu rapordaki **tüm P0, P1 ve P2 bulguları** ele alındı. Uygulanan düzeltmeler ve düzeltme-sonrası uçtan uca BTC akışı için → **[`BTCUSD_ALGORITMA_AKISI_2026-10-10.md`](BTCUSD_ALGORITMA_AKISI_2026-10-10.md)**. Özet: P0-1 ✅ (her iki yarı) · P0-2 ✅ · P0-3 ✅ (EV muafiyeti kaldırıldı; net-negatif fren mekanizması kuruldu ama **A/B kanıtıyla varsayılan KAPALI**) · P0-4 ✅ · P1-5 ✅ · P1-6 ✅ · P1-7 ✅ · P1-8 ✅ · P2-4/5/6/7/9/10 ✅ · P2-2/P2-8 bilinçli sınır olarak bırakıldı. Test: **190/190 geçiyor**.

---

## ⚠️ Önce okuyun: Replay A/B araç tuzağı

Bu rapordaki **tüm replay sayıları** `--spread-profile outputs/fx_spread_p95.json` ile üretildi. Çıplak dosya adı (`--spread-profile fx_spread_p95.json`) **sessizce** çözülemez ve yalnız bir `[UYARI]` satırıyla sentetik kategori spread'lerine düşer → sonuçlar sessizce farklılaşır (n:2294/+$97.01 vs n:2330/+$396.19). İlk A/B denemesinde bu tuzağa düşüldü; tüm ara koşular geçersiz sayılıp yeniden yapıldı. **Tam yol verin.**

---

## 0. Yönetici Özeti

BTCUSD, canlı defterde **tek zarar eden sembol**. 2026-10-08→10-09 aralığındaki 75 işlemde **−$70.69** (XAUUSD +$89, US30 +$149). Ancak inceleme, zararın **tek bir "sinyal kötü" hatası olmadığını**, üç ayrı katmanda biriktiğini gösteriyor:

1. **Muhasebe/motor katmanı — BTC zararı panelde olduğundan az/kayık görünebilir.** MT5 köprüsü emir hatalarını motora **hiç iletmiyor** ve motor bekleyen emirleri **koşulsuz** temizliyor → broker reddettiği BTC emri "açıldı" sanılıyor (**P0 #1**). Ayrıca BTC agresif çıkış/risk muafiyetleriyle (EV kilidi yok, `risk_skip` bypass) korumasız kalıyor (**P0 #3, #4**).
2. **Çıkış/strateji katmanı — dört akış + dengesiz R.** BTC aynı anda 4 aday üreticiden besleniyor (klasik radar + donchian + S3-15m + London Breakout); donchian BTC replay'de **negatif** (**P0 #2**). Klasik BTC kolunda TP kapalı + 1.5×ATR geniş SL, kazançları kısa kesip zararları uzun koşturuyor — canlıda ortalama kazanç $8.96 / ortalama zarar $18.55.
3. **Panel/config katmanı — ayarlar kalıcı değil ve tüm-nesne değişimi tehlikeli.** `_AUTO_SETTINGS` yalnız bellektedir; her yeniden başlatmada panel ayarları koda döner ve `btc_min_score`/`crypto_sl_atr_mult` sessizce varsayılana sıfırlanabilir (**P1 #5**).

**Kritik denge notu:** 32 günlük replay'de canlı-ayar BTCUSD **+$396** (PF 1.16) veriyor; yani canlı −$70 **replay'de tekrarlanmıyor**. Canlı örneklem 2 gün / 75 işlem (sadece `BUY` ağırlığı %85) ve whipsaw rejiminde. **Sonuç:** BTC'yi hemen kapatmak yerine, önce **P0 muhasebe/motor düzeltmeleri** yapılmalı; strateji kapatma kararı için 30-60 günlük canlıya-parite replay şart.

---

## 1. BTCUSD Algoritma Haritası

**Sembol yüzeyi:**
- Spec: `FOREX_SYMBOLS` `forex.py:191-202` — `category="crypto"`, `pip_size=1.0`, `digits=2`, `tv_symbol="BINANCE:BTCUSDT"`.
- Pip USD değeri: `get_symbol_trading_specs` `forex.py:1226-1234` → `pip_val=1.0` (sabit; **10× hatası YOK** — `forex.py:3834` yorumu geçmiş düzeltmeyi anlatıyor).
- Tarama evreni: `RADAR_SCAN_SYMBOLS` `forex.py:224-226` = {XAUUSD, US30, BTCUSD, GBPUSD, AUDUSD, NZDJPY, AUDNZD}.
- DXY muafiyeti: `forex.py:485` (BTC DXY vetosundan muaf).

**Aday üreticileri (BTC dördüne de dahil):**

| Akış | Liste/satır | Çıkış kuralı |
|---|---|---|
| Klasik radar | `RADAR_SCAN_SYMBOLS` `225` | TP **YOK**, BE+trailing; SL 1.5×ATR |
| Donchian+ADX | `mode_symbols` `3168` | SL 2×ATR / TP 4×ATR (`5018-5022`) |
| S3 (Supertrend+RSI) 15m | `s3_symbols_15m` `3187` | SL 1.5×ATR / TP 2.0×ATR (`5029-5034`) |
| London Breakout | `lb_symbols` `3195` | kutu×frac SL / R TP (`5038-5043`) |

**Akış:** tarama (1.5 sn, `3797`) → SL/TP/trailing/BE güncelle (`3804-4040`) → aday üretimi (`4120-4485`) → kapı zinciri (`for cand in candidates`, `4585`) → karar (döngü başına en fazla 1 emir, `break 5208`).

**Ayar yüzeyi (`ForexAutoPaperSettings`, `3117`):** `crypto_sl_atr_mult=1.5` (`3152`), `crypto_tp_enabled=False` (`3153`), `btc_min_score=76.0` (`3154`), `max_open_positions=99` (`3121`), `max_positions_per_symbol=1` (`3122`), global `min_score=75` (`3123`).

---

## 2. Kritik Bulgular (P0)

### P0-1 — [DOĞRULANDI] MT5 emir hataları motora hiç ulaşmıyor; bekleyen emirler koşulsuz temizleniyor
**Dosya:** `scripts/mt5_bridge.py:1294-1295`, `backend/app/routers/forex.py:6617-6618`

Köprü, başarısız `order_send` sonucunu **yalnızca `print` eder** ve sync yükünde sonuç kanalı yoktur:
```python
# mt5_bridge.py:1294-1295
if res and not res.get("success"):
    print(f"  ❌ [İŞLEM İPTAL/HATA]: {res.get('error')}")
```
```python
# mt5_bridge.py:1194-1201 — sync yükü
payload = {"account":…, "positions":…, "deals":…, "ticks":…, "candles":…, "version":"1.0.1"}
```
```python
# forex.py:6617-6618 — bekleyen emirler koşulsuz boşaltılıyor
commands = list(_MT5_STATE["pending_commands"])
_MT5_STATE["pending_commands"].clear()
```

**Senaryo:** BTC emri (geniş 1.5×ATR SL + 50-lot tavan nedeniyle `Not enough money`/geçersiz hacim en olası reddi alan sembol) broker tarafından reddedilir → köprü sadece konsola yazar → motor emri "gönderildi" sayar, `_LAST_SYMBOL_ENTRY_TIME` zaten 60 sn soğumaya ayarlanmıştır (`4679`), aday tekrar üretilmez → **motor açık pozisyon sanır, panel hayalet bekler, gerçekte pozisyon yok.** BTC en çok maruz kalan semboldür.

**Öneri:** Sync yüküne `command_results` (id/action/retcode/success) ekle; motor yalnız sonuç onaylanınca bekleyen emri temizlesin; `success:False`'da 60 sn soğumayı geri açsın.

### P0-2 — [DOĞRULANDI] BTC'nin donchian_adx kolu replay'de NEGATİF; canlıda aktif
**Dosya:** `forex.py:3168` (BTC `mode_symbols`), `forex.py:4147-4196`; kanıt: yazar A/B, `outputs/btc_audit_DONCH.json`

Aynı pencere/spread'de (32 gün, p95 BTC 5.0 pip):

| Kol | n | WR | Net $ |
|---|---|---|---|
| Klasik (canlı ayar) | 2330 | 65.1% | **+396.19** |
| **donchian_adx** (`adx≥18`, SL 2×ATR/TP 4×ATR) | 113 | 63.7% | **−27.50** |

BTC donchian kolu 113 işlemde zarar; GBPJPY/EURJPY için kalibre edilmiş mod (`mode_exclusive` onları koruyor, `3172`) BTC'de kanıtlanmadan çalışıyor. Ayrıca donchian BTC'yi SuperTrend vetosuna takılı bırakıyor (`4972`, EAP/S3 muaf).

**Öneri:** BTC'yi `mode_symbols`'ten çıkar (XAUUSD donchian'ı pozitif olduğu için kalsın) veya BTC donchian için BTC'ye özel A/B bitene kadar kapat.

### P0-3 — [DOĞRULANDI] BTC (ve XAU) EV kilidinden muaf; seri-SL tek başına ikame etmiyor
**Dosya:** `forex.py:4812` (muafiyet), `forex.py:4773-4788` (60 sn soğuma), `forex.py:653-674` (seri-SL)

```python
# forex.py:4812
if _AUTO_SETTINGS.ev_guard_enabled and sym not in ("XAUUSD", "BTCUSD"):
```
BTC'nin "60 sn soğuma" koruması **kayıp-uyarlamalı değil** — sadece çıkış→giriş hız sınırı (`_LAST_BTC_EXIT_TIME`). Seri-SL ise **yalnız 3 ARDIŞIK tam-SL**'de tetiklenir (`pnl<0` + `SL_HIT`; tek kazanç sayacı sıfırlar). **Senaryo:** BTC SL, TP, SL, SL, TP, SL… deseniyle salınır → ne EV kilidi (muaf) ne seri-SL (ardışık değil) durdurur → net-negatif BTC, `risk_per_trade_pct=5` (`3120`) ile sınırsız sermaye yakar.

**Öneri:** BTC'yi EV muafiyetinden çıkar veya BTC'ye **net-negatif-pencere** tabanlı bir fren ver; durum raporunu (`3415/3422`) gerçek kurala hizala.

### P0-4 — [DOĞRULANDI] Kripto/altında `risk_skip` zorla kapatılıyor → hard risk bandı aşılabiliyor
**Dosya:** `forex.py:5084-5086`

```python
mt5_lots, risk_skip = apply_risk_normalization(sym, mt5_lots, sl_pips, pip_val, risk_usd)
if risk_skip and (is_crypto or is_gold):
    risk_skip = False
```
Kripto/altın için lot-normalizasyon skip kapısı **her zaman** iptal edilir (yorum: "kripto ve altında pas yok"). Geniş 1.5×ATR BTC SL'i ile birleşince işlem, 2× sert risk bandını **bilerek** aşabilir. Bu, BTC'nin en büyük tek risk kaldıracı.

**Öneri:** Kriptoda skip yerine lotu tavana sabitle (mevcut `lot_ceiling=50.0`, `5070-5072`) ve gerçek risk-USD'yi logla; ya da 1.5×ATR SL'i `risk_skip`'i tetiklemeyecek şekilde sınırla.

---

## 3. Yüksek / Orta Bulgular (P1)

### P1-5 — [DOĞRULANDI] `POST /auto-paper/settings` tüm-nesne değişimi + kalıcı değil; BTC eşikleri sessizce sıfırlanabilir
**Dosya:** `forex.py:5482-5488`, `forex.py:3225`; panel `AutoSettingsPanel.tsx:150-176`

```python
# forex.py:5487-5488
new_settings.enabled = _AUTO_STATE["enabled"]
_AUTO_SETTINGS = new_settings      # ← birleştirme YOK
```
Eksik alan içeren **herhangi** bir gövde (eski panel sürümü, `curl`, hatta test harness'i `test_forex_auto_paper.py:38` kısmi nesne POST ediyor) `btc_min_score`→76.0, `crypto_sl_atr_mult`→1.5, `allowed_symbols`→22'lik varsayılan, `max_open_positions`→99 olarak **sessizce sıfırlar**. Ayrıca `_AUTO_SETTINGS` yalnız bellektedir; yeniden başlatmada (yalnız `.enabled` yeniden uygulanır, `5452`) panel config'i kaybolur.

> **Hafıza iddiası** "parametre paneli tekilleştirildi": **düzenleme yüzeyi için DOĞRU** (tek panel `AutoSettingsPanel`, tek endpoint), **kalıcılık için YANLIŞ** (bellek-içi, restart'ta sıfırlanır) ve **varsayılan sembol listesi 4 yerde ıraksıyor** (`forex.py:3161`, `settings/page.tsx:116`, `AutoSettingsPanel.tsx:57`, `btc-gold/page.tsx:460`).

**Öneri:** Endpoint'i birleştirme (merge) yap; `_AUTO_SETTINGS`'i JSON/DB'ye kalıcılaştır ve startup'ta yükle.

### P1-6 — [DOĞRULANDI] BTC ters-dönüş (flip): karşı bacak kapanır, ters giriş 60 sn soğumaya takılır
**Dosya:** `forex.py:4678-4681` vs `forex.py:3611-3613` ve `4773-4788`

```python
# forex.py:4678-4681 — flip sıfırlaması (yalnız altın)
_LAST_SYMBOL_ENTRY_TIME[sym] = 0.0
if "XAU" in sym or "GOLD" in sym:
    _LAST_GOLD_EXIT_TIME = 0.0
```
`_close_position_internal` flip sırasında BTC çıkış saatini **şimdi** yapar (`3611-3613`), ama flip bloğu `_LAST_BTC_EXIT_TIME`'ı sıfırlamaz → hemen ardından BTC kapısı (`4777`) yeni yönü reddeder. Sonuç: yorumun aksine ("anında ters yöne geç"), BTC flip'te **kapanır ve düz kalır**. MT5 yolunda kapanış kuyruklu `CLOSE_ORDER` olduğu için saat senkron ayarlanmaz → **paper ve MT5 BTC aynı sinyalde farklı davranır.**

> Bir başka ajan (risk) bu bulguyu bağımsız olarak doğruladı; "flip-reset UnboundLocalError" geçmiş bug'ı ise **DÜZELTİLMİŞ** (`global` bildirimi `3790`'da tam; AST taraması + regresyon testi `test_forex_auto_paper.py:334-345`).

### P1-7 — [DOĞRULANDI] `reset-symbol-guards` yön-seviyesi soğumayı temizlemiyor
**Dosya:** `forex.py:5594-5598`

Tam sıfırlama `_SYMBOL_LOSS_STREAK` / `_SYMBOL_LOSS_COOLDOWN_UNTIL` temizler ama `_SYMBOL_DIR_LOSS_STREAK` (`3252`) ve `_SYMBOL_DIR_LOSS_COOLDOWN_UNTIL` (`3253`) **temizlenmez** (hiçbir yerde `.clear()` yok). Açık pozisyon kontrolü de yok. **Senaryo:** BTC 3 ardışık **BUY** SL → `(BTCUSD,"BUY")` 5 dk donar; operatör "temiz sayfa" der → BUY kapısı (`4606`) hâlâ reddeder.

**Öneri:** Yön sayaçlarını da temizle; `len(open_positions)>0` iken ev idaresi çalışıyorsa yüksek sesle logla/reddet.

### P1-8 — [DOĞRULANDI] Çoklu-akış adayları + flip churn (BTC'de 4 akış)
**Dosya:** donchian ek `4186` (tüm BTC adayını düşürür), S3 ek `4340-4341`, LB ek `4436-4437` (yalnız **kendi** adayını düşürür)

Tek taramada çift-açılış **YOK** (`break 5208` + `max_positions_per_symbol=1`). Ama S3/LB dedup'ı kaynak-kapsamlı olduğundan BTC aynı listede birden çok adayla (farklı yön) bulunabilir → ardışık 1.5 sn taramalarda **flip churn** (kapat+aç, spread maliyeti). Flip bloğu (`4621-4648`) soğuma kontrollerinden **önce** çalışır ve `score=200` taşıyan donchian/S3/LB adayları `min_score`'u her zaman geçer.

**Öneri:** Tüm kaynaklarda tek tip sembol-dedup uygula; mod adayları için ters-dönüşte ek onay iste.

---

## 4. Düşük Öneme (P2)

| # | Bulgu | Dosya:satır |
|---|---|---|
| 1 | Donchian bekleme logu gerçek kapıyı söylemiyor (ADX-altı/seans/gün-limiti gizli); log ADX varsayılanı `0` (`4173`) iken karar ADX varsayılanı `25.0` (`4150`) | `forex.py:4160-4181` vs `4150` |
| 2 | Replay'de `mode_exclusive` yok → GBPJPY/EURJPY klasik sinyali simüle ediliyor (BTC'yi doğrudan etkilemez, portföy toplamını kirletir) | `forex_replay_backtest.py` (yok) |
| 3 | BTC spread >$100 ise `_LIVE_SPREAD_PIPS` güncellenmez → sentetik 12.0'a düşer (pip_size=1.0 nedeniyle) | `forex.py:6565` |
| 4 | Köprü BTC lot tavanı `max_forex_lot`(=10)'a düşer; motor `lot_ceiling=50.0` hesaplar → sessiz kırpma | `mt5_bridge.py:443` vs `forex.py:5070-5072` |
| 5 | `max_pyr` yorumu "Varsayılan: 3" ama alan varsayılanı 1 | `forex.py:4694` |
| 6 | `_btc_scan_note` 60 sn'i sabit kodlar, EV durumunu atlar (yalnız görüntü, drift) | `forex.py:3711-3761` |
| 7 | BTC ters/mt5↔app haritalarında yok; sonekli broker sembolü (`BTCUSD.m`) `sym=="BTCUSD"` yollarını kırar | `mt5_bridge.py:189`, `forex.py:396` |
| 8 | BTC pip_val her iki tarafta sabit `1.0` (kontrat boyutu broker'dan okunmuyor) | `mt5_bridge.py:311`, `forex.py:1230` |
| 9 | Donchian `adx_min=18.0` ve `max_per_day=2` kodda sabit; diğer akışlar ayardan okuyor | `forex.py:4150-4151` |
| 10 | `crypto_sl_atr_mult` yalnız `atr_exit_enabled=True` iken uygulanır; kapatılırsa BTC sessizce `spec["sl_pips"]`'e döner | `forex.py:5006` |

---

## 5. Doğrulanıp SAĞLAM bulunanlar (yanlış-pozitif önleme)

- **pip_val 10× hatası YOK** — her iki tarafta `1.0` (`forex.py:1230`, paylaşılan `get_symbol_trading_specs`); replay de aynı fonksiyonu kullanır.
- **Replay spread şişirmesi YOK** — replay varsayılanı 12 pip (kategorik), gerçek BTC spread ~5.3 (`outputs/fx_spread_reality.json`); yani replay canlıdan **daha iyimser değil, daha kötümser**.
- **Çift-açılış (tek tarama) YOK** — `break 5208` + `max_positions_per_symbol=1`.
- **"flip-reset UnboundLocalError" bug'ı DÜZELTİLMİŞ** — `global` bildirimi tam (`3790`), regresyon testi mevcut.
- **10-07 denetiminin ~19 düzeltmesi koddadır** — `_deal_net_pnl_usd`, `_merge_partial_close_rows`, `require_mt5_connection`, `_TECH_STALE_SEC`, `ATR_USE_WILDER`, `_PF_INFINITE`, `_tech_is_stale`, `correlation_of→Optional` hepsi yerinde.
- **Testler:** `test_forex_enhancements.py + test_forex_auto_paper.py + test_forex_improvements.py` = **190 test, tümü geçiyor** (sistem Python 3.12; 8 yeni regresyon testi düzeltmelerle eklendi).
- **Slot hipotezi koddan ÇÜRÜK** — `max_open_positions=99` iken global cap (`4086`) pratikte bağlayıcı değil; JPY krosları `USD_NEUTRAL` olduğundan (`465-474`) BTC ile aynı korelasyon kümesine giremez. BTC'yi asıl etkileyen, **korelasyon-küme kapısı** (`4863-4888`) — geniş evren aynı-USD-bias pozisyonu artırıp BTC'yi bloklayabilir, ama bu "slot" değil.

---

## 6. Canlı Veri + Replay Kanıtı

**Canlı defter (`forex_scalper_islemler_2026-10-10.csv`, 187 işlem, 10-08→10-09):**

| Sembol | n | Net $ | WR | Avg Win | Avg Loss | PF |
|---|---|---|---|---|---|---|
| US30 | 38 | **+149.39** | 65.8% | — | — | — |
| XAUUSD | 66 | **+89.07** | 71.2% | — | — | — |
| GBPUSD | 8 | −11.36 | 37.5% | — | — | — |
| **BTCUSD** | **75** | **−70.69** | **64.0%** | **+8.96** | **−18.55** | **0.86** |

BTC strateji dağılımı: M1/M5 Çoklu Radar n=71 net **−$42.11** (XAU aynı strateji +$119); S3 n=2 **−$36.89**; MT5 n=2 +$8.31. BTC'de **kayıp tutma süresi > kazanç tutma süresi** (16.5 dk vs 12.6 dk).

**Replay A/B (32 gün, p95 spread, izole BTC), `outputs/btc_audit_*.json`:**

| Kol | n | WR | Net $ |
|---|---|---|---|
| **BASE (canlı ayar: no-TP, 1.5×SL)** | 2330 | 65.1% | **+396.19** |
| TP açık | 2407 | 65.0% | +311.10 |
| Dar SL (1.1×) | 2502 | 57.5% | +298.51 |
| donchian_adx | 113 | 63.7% | **−27.50** |

**Yorum:** Replay, canlı ayarın BTC'de uzun vadede **pozitif** olduğunu söylüyor; canlı −$70 **tekrarlanmıyor**. Dolayısıyla canlı zarar (a) 2 günlük/75 işlemlik küçük örneklem + whipsaw rejimi, (b) `DONCH` kolunun canlıda çalışıp replay'de izole-negatif olması, (c) P0-1 (görünmeyen reddedilen emirler) ve P0-3/#4 (fren yok) etkileşimi olabilir. **TP/SL knob'larını değiştirmek replay'de kârı DÜŞÜRÜYOR** — bu yüzden "TP aç" tipi naif düzeltme önerilmez.

---

## 7. Öncelikli Düzeltme Listesi — UYGULAMA DURUMU

| Öncelik | Bulgu | Dosya:satır | Kapsam | Durum |
|---|---|---|---|---|
| **P0-1** | Emir-sonuç kanalı ekle; bekleyen emri yalnız onayda temizle | `mt5_bridge.py:1294`, `forex.py:6617` | Muhasebe | ✅ **UYGULANDI** (köprü `command_results` + motor işleme; başarısız OPEN → soğuma geri açılır; regresyon testi var) |
| **P0-2** | BTC'yi donchian `mode_symbols`'ten çıkar (replay negatif) | `forex.py:3168` | Strateji | ✅ **UYGULANDI** → `["XAUUSD","GBPJPY","EURJPY"]`; A/B doğruladı (donchian BTC −$8.94) |
| **P0-3** | BTC'yi EV muafiyetinden çıkar / net-negatif fren ver | `forex.py:4812` | Risk | ✅ **UYGULANDI** — `btc_ev_exempt=False`; net-negatif fren kuruldu ama **A/B'de PnL düşürdü** (+$373→+$222, iki pencerede negatif) → varsayılan **KAPALI**, mekanizma korunuyor |
| **P0-4** | Kriptoda `risk_skip` yerine lot tavanı uygula + risk logla | `forex.py:5085` | Risk | ✅ **UYGULANDI** — `crypto_risk_clamp_enabled=True`; lot kategori tabanına sabitlenir, `actual_risk_usd` loglanır |
| **P1-5** | Settings endpoint'ini merge yap + kalıcılaştır | `forex.py:5482`, `3225` | Panel | ✅ **UYGULANDI** — kısmi merge + `forex_auto_settings.json` diske yazılır, startup'ta yüklenir |
| **P1-6** | Flip bloğunda `_LAST_BTC_EXIT_TIME=0` | `forex.py:4680` | Motor | ✅ **UYGULANDI** — `4852`; BTC flip artık gerçekten ters yöne dönüyor (paper/MT5 parite) |
| **P1-7** | `reset-symbol-guards` yön sayaçlarını da temizle | `forex.py:5594` | Risk | ✅ **UYGULANDI** — `_SYMBOL_DIR_LOSS_STREAK` + `_SYMBOL_DIR_LOSS_COOLDOWN_UNTIL` de temizlenir |
| **P1-8** | Tüm akışlarda tek tip sembol-dedup | `forex.py:4186/4340/4436` | Motor | ✅ **UYGULANDI** — donchian/EAP/S3/LB hepsi sembol-bazlı tam dedup |
| **P2** | Log/panel/köprü temizliği (bkz. Bölüm 4) | — | Bakım | ✅ **P2-4/5/6/7/9/10 UYGULANDI**; P2-2 (`mode_exclusive` replay'de yok) ve P2-8 (BTC `pip_val` sabit) bilinçli sınır olarak bırakıldı |

---

## 8. Test Önerileri (canlıya almadan önce)

1. **Canlıya-parite preset:** `--crypto-sl-mult 1.5 --no-tp-crypto --btc-min-score 76 --max-open 99 --loss-streak 3` + replay motoruna `mode_exclusive` ve BTC 60 sn çıkış-soğuması eklenmesi. Şu an varsayılan replay (max-open 6, TP açık, soğuma yok) BTC'yi temsil etmiyor.
2. **P0-2 doğrulaması:** BTC donchian'ı kapat → BTCUSD 30-60 günlük IS/OOS replay. Beklenti: donchian katkısı çıkarıldığında BTC net'i iyileşir.
3. **P0-3 doğrulaması:** BTC'ye net-negatif-pencere freni (24 saat / WR<45%) → replay A/B, işaret-tutarlılık 4 pencerede.
4. **P0-1 izleme:** Köprüye `command_results` eklendikten sonra reddedilen emir oranını logla; BTC'de ret oranı ölç.
5. **P1-6 testi:** BTC flip'i paper vs MT5 yolunda aynı mı — birim testi.
6. **Regresyon:** 182 forex testi + yeni bulgular için hedefli testler (`test_forex_auto_paper.py` genişletme).

---

## 9. Kapsam Önerisi

**XAU+BTC dar kapsamı koru — ama gerekçe "slot" değil.** Kod, `max_open_positions=99`'da slot rekabeti olmadığını ve JPY kroslarının `USD_NEUTRAL` olduğunu gösteriyor (slot hipotezi koddan çürük). Geniş evren BTC'yi **korelasyon-küme kapısı** (`4863-4888`) üzerinden bloklayabilir. Dolayısıyla BTC'yi korumanın doğru kaldıraçları: (i) `allowed_symbols`'ü dar tutmak, (ii) korelasyon kapısını BTC lehine ayarlamak — `max_open_positions` **değil**.

**Nihai tavsiye:** BTCUSD'yi hemen kapatma. Sırayla: **P0 muhasebe/motor düzeltmeleri → parite-replay → P0-2/P0-3 A/B →** ancak 30-60 gün canlıya-parite replay BTC'de negatif-tutarlıysa kapat. Mevcut 2 günlük/75 işlemlik canlı veri bu karar için yetersiz.

---

*Rapor 8 bağımsız paralel ajan + yazar doğrulaması + canlı CSV analizi + 4 gerçek replay koşusu ile üretildi. Tüm satır numaraları çalışma ağacındaki güncel dosyalara aittir.*
