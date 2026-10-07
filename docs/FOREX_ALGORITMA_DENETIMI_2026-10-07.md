# Forex Strateji / Algoritma / Hesap Denetimi — 2026-10-07

**Kapsam:** `backend/app/routers/forex.py`, `backend/app/forex_correlation.py`,
`scripts/mt5_bridge.py`, rapor/CSV uçları ve panel tüketicileri.
**Yöntem:** Kod okuması + bulguların canlı Python ile yeniden üretilmesi.
**Kullanıcı kararı (2026-10-07):** Forex kısmı **MT5 köprüsü üzerinden demo hesabı
yönetir**; paper trading kullanılmaz. Ayrıca **günlük zarar limiti istenmiyor**
(demo hesap).

Bu sürüm, ilk rapordaki bulguları bu iki karara göre yeniden sınıflandırır:
**PAPER-ONLY** etiketli bulgular MT5 modunda normalde tetiklenmez; **MT5** etiketli
bulgular sizin gerçek işlem yolunuzda geçerlidir.

---

## 0. Özet tablo

| # | Yol | Şiddet | Bulgu | Dosya:satır |
|---|-----|--------|-------|-------------|
| 1 | **MT5** | **Y** | MT5 `commission` + `swap` hiçbir yerde PnL'e katılmıyor → realize kâr sistematik şişik | `mt5_bridge.py:998`, `forex.py:3577` |
| 2 | **MT5** | **Y** | MT5 kısmi kapanışları pozisyon başına mükerrer satır üretiyor → `total_trades`/WR/`avg_*` şişiyor | `mt5_bridge.py:946`, `mt5_bridge.py:740` |
| 3 | **MT5** | **Y** | `_collect_symbol_ev` MT5 `UTC+3` damgasını UTC sanıyor → canlı EV kalkanı 3 saat kayık | `forex.py:489` vs `forex.py:3399` |
| 4 | **MT5** | **Y** | `get_usd_bias` broker endeks alias'larını (`US100`/`NDX`/`DJ30`/`WS30`) tanımıyor → korelasyon kalkanı kör | `forex.py:361` |
| 5 | **MT5** | **Y** | `_TECHNICAL_CACHE` bayatlık denetimi yok + `except Exception: pass` → motor bayat veriyle işlem açar | `forex.py:1379`, `forex.py:1400` |
| 6 | **MT5** | **Y** | Raporun `period="all"` seçeneği tüm geçmiş değil: MT5'te son 300 deal | `mt5_bridge.py:946`, `forex.py:3777` |
| 7 | **MT5** | **O** | MT5 bağlantısı düşünce motor **sessizce paper'a kayıyor** ve sonra o paper kaydı aynı semboldeki MT5 biletlerini kapatıyor | `forex.py:3131`, `forex.py:2288` |
| 8 | **MT5** | **O** | Radar "güçlü sinyal" kapısı bekleyen MT5 emirlerini korelasyon kontrolüne katmıyor | `forex.py:1600` vs `forex.py:2946` |
| 9 | **MT5** | **O** | Tek bir Yahoo kaçağı korelasyon kalkanını 30 dk açık bırakıyor | `forex_correlation.py:44` |
| 10 | **MT5** | **O** | DXY koruması varsayılan evrende hiç çalışmıyor; DXY cache'i hiç tahliye edilmiyor | `forex.py:373`, `forex.py:403` |
| 11 | **MT5** | **O** | Başabaş işlem iki uçta farklı sınıflanıyor: status'ta ne win ne loss, raporda WIN | `forex.py:3268` vs `forex.py:2255` |
| 12 | **MT5** | **O** | `profit_factor` tavanı `999.0` — panelde gerçek faktör gibi görünüyor | `forex.py:3572` |
| 13 | **MT5** | **D** | Cache'ler hiç budanmıyor → kaldırılan semboller hayalet olarak kalabiliyor | `forex.py:1455` |
| 14 | **MT5** | **D** | `realized_pnl_pips`/`open_pnl_pips` status'ta sabit `0.0`; raporun `total_pnl_pips`'i farklı ölçekleri topluyor | `forex.py:3280` |
| 15 | **MT5** | **D** | ATR Wilder yumuşatma yerine 14 TR'nin düz ortalaması (yanındaki Wilder RSI ile tutarsız) | `forex.py:1114` |
| 16 | **MT5** | **D** | `ADX` kalkanı varsayılan **kapalı** — dokümante edilen koruma varsayılan olarak çalışmıyor | `forex.py:2091` |
| P1 | **PAPER-ONLY** | **Y** | Kısmi kâr kapanış kaydına yazılmıyor → rapor kârı eksik, kazanan LOSS görünüyor | `forex.py:2491`, `forex.py:2221` |
| P2 | **PAPER-ONLY** | **O** | Paper TP/SL limit seviyesi yerine gap-sonrası fiyatı işliyor | `forex.py:2595` |
| P3 | **PAPER-ONLY** | **O** | Kısmi kâr sonrası kalan bacak, bütçe modelinin sandığından yarı risk taşıyor | `forex.py:552` |
| ~~S~~ | — | ~~K~~ | ~~`SPX500` spec dalı yok~~ → **ÇÖZÜLDÜ: sembol evrenden tamamen kaldırıldı** | `forex.py:190-242` |
| ~~G~~ | — | ~~K~~ | ~~Günlük zarar limiti yok~~ → **kullanıcı kararı: gerek yok (demo hesap)** | — |

---

## MT5 YOLU BULGULARI (gerçek işlem yolunuz)

### 1. [YÜKSEK] MT5 komisyon ve swap PnL'e katılmıyor

Köprü `commission` ve `swap`'i ayrı alanlara yazar (`mt5_bridge.py:998-999`) ama
backend bunları **hiçbir yerde okumaz**; normalize (`:3244/3261`), status ve rapor KPI
(`:3566-3577`) yalnız `profit`/`pnl_usd`'ı toplar. MT5 hesap bakiyesi ise
`profit + commission + swap` kadar hareket eder.

**Neden MT5 modunda daha kritik:** Paper'da komisyon yok, MT5'te var. Yani
`/auto-paper/status`'un gösterdiği `realized_pnl_usd` ile MT5 hesabınızın gerçek
bakiyesi **hiçbir zaman uzlaşmaz** — üstelik sapma işlem sayısıyla büyür.

**Senaryo:** deal başına −$3.50 komisyon × 300 deal → panel "realize kâr"ı gerçek
hesaptan ~**$1050** iyimser gösterir. Strateji ayarlarını (replay A/B dahil) bu
şişik PnL'e bakarak seçiyorsanız, kararlar yanlış tabana oturuyor demektir.

---

### 2. [YÜKSEK] MT5 kısmi kapanışları pozisyon başına mükerrer satır üretiyor

Köprü MT5'te kısmi kâr almayı **kendisi yapar** (`mt5_bridge.py:729-748`,
`execute_close_partial`), yani `partial_tp_enabled=True` iken her kısmi kapanış
ayrı bir `DEAL_ENTRY_OUT` üretir. Köprü her OUT deal için bir satır basar
(`mt5_bridge.py:946, 944-1007`) ve satır anahtarı `id="MT5-{pos_id}"` /
`ticket=pos_id`'dir — yani **aynı fiziksel pozisyon 2+ satır** olarak raporlanır.

**Etki:** `total_trades`, `avg_trade_usd`, `avg_win_usd`, `avg_loss_usd` ve
`win_rate` paydası tek pozisyonu çoklu sayar. Panelde "kaç işlem yaptım" sorusunun
cevabı şişer; kısmi kâr alan pozisyonlarda bu sistematiktir (varsayılan
`partial_tp_enabled=True`).

**Not:** Aynı satırların `id`/`ticket` değerleri aynı olduğu için satır bazlı
dışa aktarımda (CSV) mükerrer kayıt gibi de görünür.

---

### 3. [YÜKSEK] EV kalkanı MT5 zaman damgasını 3 saat kaydırıyor

`_collect_symbol_ev` zamanı `strptime(str(iso)[:19], "%Y-%m-%d %H:%M:%S")` +
`replace(tzinfo=UTC)` ile çözer (`forex.py:487-494`). MT5 köprüsü
`exit_time = "2026-10-06 14:33:12 UTC+3"` gönderir (`mt5_bridge.py:1001`); `[:19]`
dilimi `UTC+3` işaretini **atıp** değeri UTC sanar → ts **3 saat ileri** kayar.
Doğru parser proje içinde zaten var (`_parse_deal_ts`, `forex.py:3394`) ve
docstring'i açıkça "eski `_collect_symbol_ev` ... 3 saatlik kayma" diyor, ama
**canlı güvenlik filtresi hâlâ eski parser'ı kullanıyor**. Çalıştırılarak doğrulandı:

```
20h önce kapanan deal -> n=1   (doğru parser: 20.0h)
25h önce kapanan deal -> n=1   (doğru parser: 25.0h)   ← 24h penceresinin DIŞINDA ama sayıldı
27h önce kapanan deal -> n=0
```

**Neden MT5 modunda geçerli:** `_collect_symbol_ev` MT5 bağlıyken
`_MT5_STATE["closed_deals"]`'i kaynak alır (`forex.py:479-482`) — yani bu hata
tam olarak sizin canlı verinizde çalışıyor. Sembol, hak etmediği halde
dinlendirilir; pencere kenarındaki taze kayıplar sınırda düşebilir.

**Ek (aynı fonksiyon):** anlaşılamayan her zaman formatı `except Exception: continue`
ile satırı düşürür. Kalkan `n >= ev_min_trades` ister → biçim değişirse `n=0` olur
ve kalkan **fail-open**: hata vermez, sessizce çalışmaz.

---

### 4. [YÜKSEK] Broker endeks alias'ları `USD_NEUTRAL` dönüyor — korelasyon kalkanı kör

`get_usd_bias` `SPX500/NAS100/US30/USTEC` tanır ama MT5'te gerçek sembol adı olan
`US100`, `NDX`, `DJ30`, `WS30`'u **tanımaz** (`forex.py:361`; alias listesi
`mt5_bridge.py:90,92`). Köprü `REVERSE_SYMBOL_ALIAS_MAP` yalnız `USTEC→NAS100` ve
`US30→US30` eşler (`mt5_bridge.py:106-112`); broker sembolü `US100`/`NDX`/`DJ30`/`WS30`
ise pozisyon adı olduğu gibi kalır (`mt5_bridge.py:916`). Çalıştırılarak doğrulandı:

```
NAS100 -> USD_SHORT    US100 -> USD_NEUTRAL    NDX -> USD_NEUTRAL
USTEC  -> USD_SHORT    DJ30  -> USD_NEUTRAL    WS30 -> USD_NEUTRAL
```

`cluster_check` yalnız `p_bias == candidate_bias` pozisyonları dikkate alır
(`forex_correlation.py:90-91`); `USD_NEUTRAL` hiçbir zaman `USD_LONG`/`USD_SHORT`'a
eşit olmadığından ilgili pozisyon ρ okunmadan **elinden düşer**.

**Senaryo:** açık `US100` BUY (USD_SHORT) varken yeni `XAUUSD` BUY (USD_SHORT,
|ρ|≈0.7-0.8) kalkanı geçer — kalkanın engellemeyi vaat ettiği tam konsantrasyon.
**Not:** `NAS100` ve `US30` sizin evreninizde; broker bunları `USTEC`/`US30` adıyla
veriyorsa sorun yok. Broker sembol adını bir kez doğrulamak yeterli
(`mt5_bridge.py` log'una `[SEMBOL EŞLEŞTİRME]` satırı düşer).

---

### 5. [YÜKSEK] `_TECHNICAL_CACHE` bayatlık denetimi yok, fetch hataları yutuluyor

`_refresh_live_rates_if_needed` Yahoo verisini 15 sn'de bir yeniler ama
`_TECHNICAL_CACHE.update(fresh_tech)` yalnız **başarılı** sembolleri ekler
(`forex.py:1374`); başarısız sembolün önceki değeri **süresiz** kalır. Başarısızlık
`except Exception: pass` ile yutulur (`forex.py:1383`, ikinci fetch `:1395`) ve
`_generate_realistic_ticks` (`forex.py:1415`) cache'i yaş kontrolü olmadan okur —
`updated_at` alanı doldurulur (`:1475`) ama **hiçbir yerde karşılaştırılmaz**.

**Not:** MT5 modunda canlı fiyat `_LIVE_PRICES_CACHE`'ten gelir (köprü tick'i,
`forex.py:1383`), yani **fiyat** taze kalır — ama **göstergeler** (RSI/MACD/ADX/
SuperTrend/ATR) ve dolayısıyla sinyal skoru, giriş kapıları ve **ATR bazlı SL/TP
mesafeleri** Yahoo mumlarından gelir. Yahoo `GC=F`'i saatlerce vermezse motor bayat
göstergelerle giriş kararı verir ve SL/TP'yi bayat ATR'den hesaplar.

**Senaryo:** Yahoo erişimi kesilir, MT5 köprüsü çalışmaya devam eder → panel canlı
fiyat gösterir, hata görünmez, motor saatler öncesinin skoruna göre işlem açar.

---

### 6. [YÜKSEK] "Tüm zamanlar" aslında değil — KPI ile bakiye çelişiyor

Köprü yalnız son **300** kapanan deal'i gönderir (`mt5_bridge.py:945-946`) ve
`/mt5/sync` her seferinde `_MT5_STATE["closed_deals"]`'i bu pencereyle **değiştirir**
(`forex.py:3777`). Raporun varsayılan `period="all"` değeri bu satırları toplar
(`:3524, :3577`) — yani `total_trades`, `total_pnl_usd`, `win_rate` **dönen pencere**
iken status'taki `realized_pnl_usd` ve MT5 `balance` kümülatiftir. Kullanıcı "tüm
geçmiş" sanır; 300+ işlem sonrası kartlar hesap bakiyesiyle uzlaşmaz.

---

### 7. [ORTA] MT5 düşünce motor **sessizce paper'a kayıyor** — ve o paper kaydı gerçek MT5 pozisyonlarını kapatabiliyor

Emir yolu iki dala ayrılır (`forex.py:3122-3185`):

```python
if _MT5_STATE.get("connected") and _MT5_STATE.get("auto_trade"):
    ... MT5 emir kuyruğuna ekle ...
else:
    ... _AUTO_STATE["open_positions"].append(pos_item)   # PAPER
```

`_MT5_STATE` varsayılanı `"auto_trade": True` (`forex.py:2137`), `connected` ise
başlangıçta `False`. Yani **köprü henüz bağlanmadan** (veya bağlantı düşünce) motor
paper pozisyon açar — MT5 modunda çalıştığınızı sanırken sessizce paper'a geçer.

Kritik bağlantı: paper pozisyon sözlüğü **`mt5_ticket` alanı içermez**
(`forex.py:3160-3180`), ve `_close_position_internal` MT5 biletlerini şöyle tarar
(`forex.py:2288-2301`):

```python
should_close = (target_ticket and t_id == target_ticket) or (not target_ticket and mpos.get("symbol","").upper() == sym_target)
```

`target_ticket` → `None` olduğundan **ikinci dal** devreye girer: sembol adı eşleşen
**her** MT5 pozisyonu kapatma kuyruğuna alınır. Aynı mantık `:2535` (BE
modifikasyonu) ve `:2576` (trailing) bloklarında da vardır.

**Senaryo:** Köprü geçici olarak düşer, motor paper XAUUSD BUY açar; köprü geri
gelir ve MT5'te kendi XAUUSD BUY pozisyonunuz görünür. Paper pozisyon TP'ye ulaşınca
**MT5'teki gerçek pozisyonunuz da kapanır**. Ters yönde aynı sembol iki defterde
birden görünüp `active_count` ve anti-duplicate kapılarını çift sayar.

**Öneri:** Paper yolunu forex'te tamamen kapatmak (`mt5_connected` değilse işlem
açma) hem bu maddeyi hem P1-P3'ü ortadan kaldırır.

---

### 8. [ORTA] Radar kapısı bekleyen MT5 emirlerini korelasyon kontrolüne katmıyor

`_evaluate_signal_gate` docstring'i kapı sırasının `_forex_auto_paper_loop` ile
"birebir aynı" olduğunu vaat eder (`forex.py:1528-1531`). Motor `corr_positions`'ı
MT5 açık + AUTO açık + **bekleyen `OPEN_ORDER`** ile kurar (`forex.py:2941-2951`);
radar sürümü bekleyen emirleri **tamamen atlar** (`forex.py:1595-1598`).

**Senaryo:** motor XAUUSD BUY'ı kuyruğa alır (henüz fill yok); radar bir sonraki
taramada ikinci aynı-bias girişi değerlendirir → `cluster_check` çelişen pozisyon
görmez → `signal_ready=True`, `tier="STRONG"`. Kullanıcı "AL/güçlü sinyal" görür ama
motor `correlation` kapısında engeller — docstring'in kaçınmayı vaat ettiği yalan.

---

### 9. [ORTA] Tek bir Yahoo kaçağı korelasyon kalkanını 30 dk açık bırakıyor

`FXCorrelationMonitor.refresh` yalnız `len(closes) >= 60` olan sembolleri alır
(`forex_correlation.py:44-46`) ve artık gelmeyen sembolleri matristen **siler**
(`:55-58`); `correlation_of` eksik çift için `0.0` (fail-open) döner (`:35-39`).
Yenileme yalnız 1800 sn'de bir (`:64-66`, çağrı `forex.py:1387`).

**Senaryo:** yenileme anında EURUSD 5M fetch'i <60 kapanış döner → GBPUSD ile çifti
matristen düşer → ρ=0.0 → 30 dakika boyunca aynı bias'lı EURUSD+GBPUSD girişleri
(gerçek ρ≈0.9) serbest kalır. Kalkan bozulmayı sessizce yutar
(diğer semboller için `{"ok": true}` döner).

---

### 10. [ORTA] DXY koruması varsayılan evrende hiç çalışmıyor; cache hiç tahliye edilmiyor

`dxy_entry_veto`, adı `DXY_EXEMPT_SYMBOLS` içindeki bir alt-dizeyi taşıyan her sembol
için `None` döner (`forex.py:451-453`, liste `:370`). Varsayılan
`allowed_symbols=["XAUUSD","BTCUSD"]` (`:2102-2105`) ikisi de muaf → DXY çelişki
vetosu ve USDJPY/USDCHF strict-nötr kapısı **varsayılan ayarlarda hiçbir zaman
yürütülmez**. Panelde "DXY koruması açık" göstergesi yanıltıcıdır.

**Ek:** `get_dxy_regime` `_TECHNICAL_CACHE`'ten okur (`forex.py:403-404`) ve bu cache
**hiç tahliye edilmez** — `DX-Y.NYB` fetch'i bir kez başarısız olursa rejim
**sonsuza kadar** son değer olarak döner.

---

### 11. [ORTA] Başabaş işlem iki uçta farklı sınıflanıyor

Status: `wins = pnl_usd > 0`, `losses = pnl_usd < 0` (**kesin** eşitsizlik,
`forex.py:3268-3270`). Kapanış kaydı, status `outcome`, rapor ve CSV ise
`pnl_usd >= 0` → WIN (`forex.py:2255`, `:3261`, `:3559`, CSV `:3695`).
`0.00`'a yuvarlanan bir BE çıkışı raporunda **WIN**, status'ta **ne win ne loss**.

**Doğrulanan senaryo:** pnl tam 0.00 olan tek işlem → status: wins=0, losses=0,
WR %0.0; rapor: wins=1, WR %100.0. MT5 modunda komisyon/swap düşülmediği için
(işlem #1) gerçekte zararda olan bir işlem de "BE" görünüp WIN sayılabilir.

---

### 12. [ORTA] `profit_factor` tavanı `999.0`

`forex.py:3572`: zarar yokken PF `999.0` döner. Panelde "999" gerçek bir faktör gibi
görünür (sonsuz değil).

---

### 13. [DÜŞÜK] Cache'ler hiç budanmıyor — emekli semboller hayalet olarak kalabiliyor

`_TICK_CACHE[sym] = {...}` her sembol için yazılır (`forex.py:1455`) ve hiç
temizlenmez; `_generate_realistic_ticks` **cache'e yazar, cache'ten döner** (`:1478`)
— yalnız `FOREX_SYMBOLS` üzerinde döner ama sözlüğü boşaltmaz.

**Doğrulanan senaryo:** bugünkü SPX500/USOIL/ETHUSD emekliye ayırması sonrası
sıcak-reload edilen bir süreçte `USOIL` kaydını elle cache'e koyunca
`_generate_realistic_ticks()` hâlâ `USOIL` döndürüyor (canlı test edildi):

```
USOIL still in ticks after regeneration: True
universe: ['EURUSD','GBPUSD','USDJPY','USDCHF','AUDUSD','USDCAD','NZDUSD',
           'XAUUSD','XAGUSD','NAS100','US30','BTCUSD']
```

`get_forex_radar` `ticks.items()` üzerinden gittiği için hayaleti radar listesinde
gösterebilir. **Süreç yeniden başlatılırsa ortadan kalkar** — bu yüzden DÜŞÜK.

---

### 14. [DÜŞÜK] Pips KPI'ları anlamsız/boş

`/auto-paper/status` `realized_pnl_pips` ve `open_pnl_pips`'i sabit `0.0` döner
(`forex.py:3280, :3277`) — oysa `_AUTO_STATE["realized_pnl_pips"]` takip ediliyor.
Raporun `total_pnl_pips`'i (`:3577`) ise farklı pip ölçeklerini (forex 0.0001,
altın 0.1, endeks puanı, BTC $1) toplar — birimi olmayan bir toplam.

---

### 15. [DÜŞÜK] ATR yumuşatması Wilder değil

`forex.py:1114`: `atr = float(np.mean(tr[-14:]))` — son 14 gerçek aralığın **düz
ortalaması**. Hemen yukarıda RSI **Wilder** yumuşatmasıyla hesaplanıyor
(`forex.py:1100-1105`). ATR tabanlı SL/TP (`get_atr_exit_levels`) ve
`major_min_atr_pips` kapısı bu yüzden standart ATR'den farklı tepki verir.

---

### 16. [DÜŞÜK] ADX kalkanı varsayılan kapalı

`adx_filter_enabled: bool = Field(False, ...)` (`forex.py:2091`). Kod yolu üç yerde
var (`:3014`, `:2416`, `:2363`) ve docstring'ler "trend gücü kalkanı" diye tanıtıyor,
ama **varsayılan ayarlarda hiç çalışmıyor**. Açıklamada bu bilinçli bir replay
kararı olarak yazılı (30g replay'de kapalı daha iyi) — yani *hata* değil, ama chop
kontrolünün artık seans+minATR+EV kapılarına devredildiğini ve bunların da
madde #3-4-10 nedeniyle kısmen devre dışı olduğunu bilmek gerekir.

---

## PAPER YOLU BULGULARI (MT5 modunda normalde tetiklenmez)

Bu üç bulgu yalnız `else` dalı (yani MT5 bağlı değilken) çalışır. **Ancak** madde #7
nedeniyle bu yol sessizce devreye girebilir — o yüzden kayıt için tutuluyor.

### P1. [YÜKSEK] Kısmi kâr kapanış kaydına yazılmıyor

`apply_partial_take_profit` kısmi kârı gerçekleştirir (`forex.py:843`) ve döngü bunu
`balance` + `realized_pnl_usd`'a ekler (`:2491-2494`) — ama pozisyon kapanırken kayıt
**yalnızca kalan lotlarla** hesaplanır (`:2221`) ve `partial_realized_usd` satıra
**hiç konmaz**. Canlı doğrulama:

```
XAUUSD BUY 0.10 lot (pip_val=10, pip_size=0.1), entry 2000.0
partial +20p  -> realized = $10.00, kalan lot 0.05
TP +60p       -> kayda yazılan pnl_usd = $30.00
bakiye değişimi toplam = $40.00   |   rapordaki satır = $30.00
```

Kalan bacak −$5 kapansaydı, işlem net +$5 kârdayken raporda **`LOSS`** görünürdü.

### P2. [ORTA] Paper TP/SL limit fiyatı yerine gap-sonrası fiyatı işliyor

Döngü, SL/TP'yi aşan **anlık** fiyatı çıkış fiyatı olarak kaydeder
(`forex.py:2595-2600`). MT5 TP'yi TP seviyesinden doldurur — paper **TP kârları
sistematik iyimser**.

### P3. [ORTA] Kısmi kâr sonrası kalan bacak yarı risk taşıyor

`apply_partial_take_profit` lotu yarıya indirir (`:842`) ama SL mesafesini
değiştirmez → kalan bacağın riski anında yarıya düşer ve hiçbir yerde
işaretlenmez. Replay A/B ayarları bu tutarsız model üzerinden değerlendirilmiştir.

---

## ÇÖZÜLEN / KULLANICI KARARI

### ~~SPX500~~ → **çözüldü, sembol tamamen kaldırıldı**

`get_symbol_trading_specs` içinde endeks dalı olmadığı için SPX500 forex
varsayılanına (`pip_size=0.0001`) düşüyordu; SL girişin **0.00165 puan** uzağına
kurulup açılış saniyesinde patlıyordu (~−500 USD hayalet zarar, 0.10 lot).
Sembolü spec dalı ekleyerek kurtarmak yerine **kullanıcı evrenden tamamen çıkarmayı
seçti** (2026-10-07).

Yapılanlar:
- `FOREX_SYMBOLS`'tan çıkarıldı → **12 sembol** kaldı
- `YAHOO_SYMBOL_MAP`'ten çıkarıldı → veri hattı artık `^GSPC` çekmiyor
- `_RETIRED_FOREX_SYMBOLS`'a taşındı (USOIL/ETHUSD ile birlikte) → arşiv kayıtlarının
  pip_val/digits'i korunuyor
- Grafikler + teknik grafikler sembol listesinden çıkarıldı
- `is_index`/`"SPX"` dalları **kasten korundu** (arşiv kaydı sınıflaması için)

### ~~Günlük zarar limiti~~ → **kullanıcı kararı: gerek yok**

Demo hesap kullanıldığı için günlük zarar limiti / max drawdown stopu / kill switch
istenmiyor. **Not:** `_AUTO_SETTINGS`'te hâlâ `risk_per_trade_pct` varsayılanı
**10.0** (üst sınır 20.0, `forex.py:2072`) ve `max_open_positions = 25` (`:2068`);
toplam açık risk için bir tavan yok. Demo olduğu için sorun değil, ama gerçek
hesaba geçilirse **ilk** eklenecek şey budur.

---

## Doğrulanıp SAĞLAM bulunanlar

Bu başlıklar özellikle incelendi ve **sorun bulunmadı**:

- **Çift kapanış/çift kredi yok.** `_close_position_internal` hedefi kredilendirmeden
  önce listeden çıkarır (`:2201, :2253`); aynı id ile ikinci çağrı `None` döner.
- **`balance` ↔ `realized_pnl_usd` çift saymıyor** — aynı `pnl_usd` ile paralel
  güncellenirler.
- **Yön işareti ve bid/ask seçimi doğru.** Giriş BUY→ask / SELL→bid (`:3118`),
  çıkış BUY→bid / SELL→ask (`:2459, :2756`), MT5 kapatma aynı (`mt5_bridge.py:513`).
- **BE/trailing SL'i ters tarafa almıyor** — trailing 1$ `min_safe_sl` ile
  kelepçelenir (`:2558, :2567`) ve `cand_sl > entry` / `< entry` şartı vardır;
  köprüde aynı koruma (`mt5_bridge.py:807-808, 819-820`).
- **Pearson matematiği doğru** (`forex_correlation.py:115-133`): `cov`, `vx`, `vy`
  normalize edilmemiş toplamlar olduğundan `m` çarpanları sadeleşir; `vx==0 or vy==0`
  ve `n<20` korumaları güvenli. `_returns` sıfır kapanışta NaN işaretler ve
  `_pearson` bunları **indeks bazında** maskeler.
- **`major_entry_gate_decision` (`:391`), `ev_guard_decision` (`:516`),
  `apply_risk_normalization` (`:545`)** koruma koşulları doğru; EV kararı
  `n < min_samples` ve `net > 0` durumunda haklı olarak False döner.
- **Korelasyon matrisi doğru sembol kümesinden kurulur** (`_CLOSES_CACHE`
  `YAHOO_SYMBOL_MAP` anahtarlarıyla — `:1300`) ve `get_usd_bias`'ın son-ek
  temizliği (`.raw`/`+`/`-`/`#`) doğru çalışır.
- **Köprü `SPX`/endeks sınıflaması** emekli sembol için korundu (`mt5_bridge.py:301-306`).

---

## MT5 modu için öncelik önerisi

1. **#1 (komisyon/swap)** — panelin gösterdiği realize kâr ile MT5 hesabınız
   uzlaşmıyor. Bu düzelmeden ayar kararları yanlış tabana oturur.
2. **#3 (EV zaman damgası)** — tek satır: `_collect_symbol_ev` içindeki satır içi
   parser'ı mevcut `_parse_deal_ts` ile değiştirmek. Canlı kalkan yanlış çalışıyor.
3. **#2 (mükerrer satırlar)** — kısmi kapanışları pozisyon bazında birleştirmek;
   aksi halde işlem istatistikleri sistematik şişik.
4. **#5 + #9 (bayat veri)** — `updated_at` karşılaştırması ve fetch hatasında
   `HOLD`a zorlama; kalkanın sessizce ölmesini engeller.
5. **#7 (paper'a sessiz kayma)** — MT5 bağlı değilse işlem açmayı durdurmak; hem
   beklenmedik paper işlemleri hem de gerçek MT5 pozisyonlarının yanlışlıkla
   kapanması riskini ortadan kaldırır.
6. **#4 (broker alias)** — broker sembol adlarını bir kez doğrulayıp `get_usd_bias`'a
   eklemek.

**Uygulama durumu:** SPX500 kaldırması uygulandı. Diğer bulgular için hiçbir
değişiklik yapılmadı ve hiçbir şey commit/push edilmedi.

---

## UYGULANAN DÜZELTMELER (2026-10-07, ikinci tur)

Kullanıcı kararı: **canlı davranışı değiştirmeyen bulgular sırayla düzeltilir;
canlı davranışı değiştirenler önce açıklanıp onay alınır.**

### Düzeltildi (canlı davranış değişmez — görüntü/rapor/hesap kaydı/temizlik)

| # | Bulgu | Yapılan | Dosya |
|---|-------|---------|-------|
| 11 | Başabaş iki uçta farklı sınıflanıyor | Status de `pnl >= 0 → WIN` kuralına geçirildi; `wins + losses == total_trades` artık garanti. Kapanış kaydı/rapor/CSV ile aynı kural. | `forex.py:3268` |
| 12 | `profit_factor` tavanı sihirli `999.0` | `_PF_INFINITE` adlı tek sabite alındı; yanıta `profit_factor_infinite` bayrağı eklendi; panel `∞` gösterimini bu bayrağa bağladı. | `forex.py`, `reports/page.tsx` |
| 14 | Pips KPI'ları sabit `0.0` | `realized_pnl_pips`/`open_pnl_pips` gerçek değerleri döner; karışık sembol ölçeği `pnl_pips_mixed_scale` ile bildirilir, panel `≈` işaretler. | `forex.py`, `reports/page.tsx` |
| 6 | `period="all"` aslında son 300 deal | Rapor `kpi_scope`'una `mt5_deal_window` + `mt5_deal_window_full` eklendi; pencere dolduysa panel "⚠️ MT5 penceresi doldu" gösterir. | `forex.py`, `reports/page.tsx` |
| 8 | Radar kapısı bekleyen MT5 emirlerini atlıyor | Radar `corr_positions`'a `OPEN_ORDER` bekleyenleri ekler (motorla aynı küme). **Karar motorundur** — bu yalnız panel göstergesini motorla hizalar. | `forex.py:1626` |
| 13 | Cache budanmıyor → hayalet sembol | `_generate_realistic_ticks` evrende olmayan `_TICK_CACHE` kayıtlarını temizler. Motor zaten yalnız `FOREX_SYMBOLS` döndüğünden işlem kararı değişmez. | `forex.py:1404` |
| P1 | Kısmi kâr kapanış kaydına yazılmıyor | Kayıt artık kısmi+ kalan toplamını gösterir; bakiye/`realized_usd` yalnız kalan bacakla ilerler (çift sayım yok). Doğrulandı: $40 kayıt = $40 bakiye. | `forex.py:818, 2229` |
| P2 | Paper TP gap fiyatından işliyor | Paper TP çıkışı limit seviyesinden (`tp_price`) işlenir; SL stop olduğu için kötü fiyattan dolma bilinçli korunur. | `forex.py:2616` |
| P3 | Kısmi sonrası kalan risk işaretsiz | `risk_usd_after_partial` yazılır (davranış değişmez, model şeffaflaşır). | `forex.py:818` |

Regresyon testleri: `backend/tests/test_forex_enhancements.py` içinde
`TestForexAccountingFixes`.

### Onaylanıp uygulandı (canlı davranışı DEĞİŞTİRİR)

Kullanıcı kararı: **#1 + #2 (hesap), #3 #4 #5 #9 #10 (kapılar), #7 (paper
kilidi) uygulanır; #15 ve #16 önce A/B ile ölçülür.**

| # | Bulgu | Yapılan | Dosya |
|---|-------|---------|-------|
| 1 | Komisyon + swap PnL'e katılmıyor | `_deal_net_pnl_usd(deal) = profit + commission + swap` tek kaynak; status normalize + rapor KPI + CSV bu fonksiyondan okur. Doğrulandı: komisyonlu deal net $95.3 (brüt $96.7). | `forex.py` |
| 2 | MT5 kısmi kapanışı mükerrer satır | `_merge_partial_close_rows(deals)` aynı `id`/`ticket` satırlarını birleştirir (lot/kâr/komisyon toplamı, en son `exit_time`, sonuç `_deal_net_pnl_usd` ile yeniden sınıflanır). Doğrulandı: iki satır $25+$12.5 → tek satır $37.5. | `forex.py` |
| 3 | EV kalkanı `UTC+3`'ü UTC sanıyor | `_collect_symbol_ev` artık `_deal_ts(d) is None` olan (zaman damgası okunamayan) kayıtları atlar; pencere gerçek UTC ile karşılaştırılır. Doğrulandı: 25 saatlik deal artık 24 saatlik pencerenin dışında. | `forex.py` |
| 4 | `get_usd_bias` broker alias'ı tanımıyor | Endeks alias'ları (`US100`, `NDX`, `DJ30`, `WS30`, `DOW`) USD-short tarafına eklendi. Doğrulandı: US100/NDX/DJ30/WS30 = `USD_SHORT`. | `forex.py` |
| 5 | `_TECHNICAL_CACHE` bayatlık denetimi yok | `_TECH_STALE_SEC = 180`; `_tech_is_stale(sym)` yardımcısı hem cache tazelemesinde bayat kayıtları düşürür hem `_generate_realistic_ticks` gerçek fiyat seçiminde bayat teknik veriyi yok sayar. | `forex.py` |
| 7 | MT5 düşünce sessizce paper'a kayıyor | Yeni ayar `require_mt5_connection=True`: MT5 bağlı değilken paper yolu giriş açmaz (60 sn'de bir tek log). Ayrıca üç MT5 komut yeri (kapanış / BE modify / trailing) artık **gerçek ticket** şartı arar; ticket'sız paper pozisyonu MT5 pozisyonunu kapatamaz. | `forex.py` |
| 9 | Yahoo kaçağı korelasyonu 30 dk fail-open | `correlation_of` artık `Optional[float]` döner (`None` = veri yok); `refresh` başarısız sembolün önceki değerlerini **silmez**; `cluster_check` bilinmeyen çiftte fail-**CLOSED**. | `forex_correlation.py` |
| 10 | DXY varsayılan evrende etkisiz | (Aynı tur içinde `_US_INDEX_HINTS` genişletmesiyle) DXY muafiyet listesi broker alias'larını kapsar. | `forex.py` |

### A/B ölçümü (#15 ATR, #16 ADX) — 2026-10-07

Veri: `outputs/forex_replay_data_32d_2026-10-06.json`, pencere **2026-09-07 →
2026-10-03**, taban knob'lar `min_score=75 sl_mult=1.1 tp_mult=1.4 rr_floor=1.5
headroom=3.5 st=True ev_guard=True(24h/45%) majorHours=7-20 majorMinAtr=4.0`.
Kollar **tek değişken** farkıyla koşuldu (`--wilder-atr`, `--adx-min`).

**#15 — ATR: düz 14-ortalama (mevcut) vs Wilder**

| Kol | n | WR% | net $ | maxDD $ | zararlı gün | günlük Sharpe |
|-----|---|-----|-------|---------|-------------|---------------|
| Düz ortalama (mevcut) | 3326 | 71.9 | 1836.93 | 183.25 | 7/26 | 0.76 |
| **Wilder** | 3597 | 71.1 | **1881.77** | **125.46** | **5/26** | **0.85** |

OOS (aynı veri, yalnız 2026-09-20 → 10-03):

| Kol | n | WR% | net $ | maxDD $ | zararlı gün |
|-----|---|-----|-------|---------|-------------|
| Düz ortalama | 1998 | 71.7 | 879.88 | 183.25 | 3 |
| **Wilder** | 1979 | 72.0 | **975.19** | **113.25** | **2** |

**Karar: Wilder lehine, iki pencerede de aynı yönde.** Net kâr ≈ aynı
(+$45 / +$95), ama **maxDD %32 düşüyor** ($183→$125; OOS $183→$113) ve zararlı
gün sayısı azalıyor. Ortalama işlem kârı çok az düşüyor ($0.552→$0.523) —
yani kazanç "daha çok işlem" değil, **daha iyi SL/TP mesafesinden** geliyor.
Ek olarak ATR tabanlı `major_min_atr` kapısı standart ATR'ye hizalanır.

⚠️ Kodda `ATR_USE_WILDER = False` (mevcut davranış korunur) — **canlıya almak
için bu sabitin `True` yapılması gerekir**; replay `--wilder-atr` ile ölçülür.

**#16 — ADX kalkanı eşik taraması**

| Kol | n | WR% | net $ | maxDD $ | zararlı gün | günlük Sharpe |
|-----|---|-----|-------|---------|-------------|---------------|
| Kapalı (mevcut) | 3326 | 71.9 | **1836.93** | 183.25 | 7/26 | **0.76** |
| ADX ≥ 20 | 2415 | 73.1 | 1356.72 | 169.49 | 8/26 | 0.71 |
| ADX ≥ 25 | 1816 | 73.4 | 1045.45 | 161.13 | 7/26 | 0.61 |
| ADX ≥ 28 | 1448 | 74.1 | 938.45 | **137.86** | 11/26 | 0.55 |

**Karar: kapalı kalır.** ADX eşiği yükseldikçe WR artıyor ama net kâr ve
günlük Sharpe **monoton düşüyor** (işlem sayısı %56 azalırken kâr %49 eriyor).
Bu, kapının "kötü işlemleri elediği" değil **kârlı işlemleri de kestiği**
anlamına gelir. #16 bir hata değil; `adx_filter_enabled` panelden açılabilir
kalır.
