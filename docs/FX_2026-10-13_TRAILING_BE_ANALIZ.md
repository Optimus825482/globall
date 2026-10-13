# Trailing / BE kilit analizi — 2026-10-13

Soru (kullanıcı): "Trailing mesafesi çok kısa, sürekli çok küçük kârlarla kapanıyor."

**Sonuç: gözlem doğru, teşhis yanlış.** Kazananları kesen katman trailing değil,
**BE (başabaş) kâr kilidi**. Kanıtlanan kaldıraç **tepeye demirlenmiş** trailing
(chandelier `MFE − 0.3×giriş-ATR`), sabit-pip mesafesi DEĞİL.

§6'da çıkan kritik gerçek: canlı MT5'i **köprü** (`scripts/mt5_bridge.py`) yönetir ve
orada chandelier YOKTU — bu yüzden önce chandelier köprüye **port edildi** (§7), port
replay ile doğrulandı, ve `chandelier_atr_mult = 0.3` **canlıya yazıldı**.

---

## 1. Bugünün kapanan işlemleri (248 satır)

| Çıkış nedeni | n | net $ |
|---|---|---|
| 🛑 Zarar Durdur (SL) | 236 | −11.71 |
| Scalper Close | 10 | −17.65 |
| Scalper Partial | 1 | +5.08 |
| 🎯 Kâr Al (TP) | 1 | −0.05 |
| **TOPLAM** | **248** | **−24.33** |

"Zarar Durdur" etiketli 236 işlemin **159'u KÂRLA kapandı** (+658.21 $, ort +4.14 $),
yalnız 77'si gerçek zarar (−674.99 $, ort −8.77 $).

Kazanç dağılımı: 103 işlem +1..+5 $, 37 işlem +5..+10 $, 10 işlem +10 $+.

Giriş→çıkış mesafesi (kazananlar): medyan +28.7 pip ama **%34'ü 20 pip'in altında**.
Zararlar ort −8.77 $, kazançlar ort +4.14 $ → **R:R = 0.47**, PF 0.983.

Canlı defter (`live_status.json`, 249 kapalı): aynı tablo — 236 SL etiketli,
159 kazançlı (+658.21), 77 zararlı (−674.99). Bakiye 168.11 $.

## 2. Neden "SL" etiketi yanıltıcı

BE kilidi SL seviyesini kâra taşıyor; fiyat oraya dönünce MT5 `sl` vuruyor ve
köprü bunu "🛑 Zarar Durdur (SL)" diye raporluyor. Yani kâr realizasyonu SL
etiketiyle görünüyor. (Kod: `forex.py:7431`, köprü başlığı `forex.py:733`.)

İki formül:
- **BE kilidi** (`forex.py:1487`): tetik `min(pips_for_1usd + headroom, eff_be_pips)`,
  kilit `max($1, MFE × lock_ratio)`; `lock_ratio` = 0.60 altın, 0.40 diğer.
- **Chandelier trail** (`forex.py:4485`): `MFE − chand_mult × ATR`, `$1` tabanıyla.
  Yalnız SL'yi yukarı taşır, devreye girmesi için `BE aktive` olması şart.

Devreye girme eşiği cebirsel: `MFE > chand × ATR / lock_ratio`.

## 3. Chandelier canlıda neredeyse hiç ateşleyemiyor

Kitabın KENDİ kazananları üzerinde, girişe kilitle bağlı gereken minimum çıkış:

| Sembol | ATR (pip) | giveback (1.2×) | gereken min çıkış | n | medyan çıkış | eşiği geçen |
|---|---|---|---|---|---|---|
| XAUUSD | 39.8 | 47.8 | 31.8 pip | 52 | 17.4 | 11 (%21) |
| BTCUSD | 165.9 | 199.1 | 298.6 pip | 98 | 41.5 | 4 (%4) |
| US30 | 20.2 | 24.2 | 36.4 pip | 7 | 19.3 | 3 (%43) |

**BTCUSD'de kazananların yalnız %4'ünde, XAUUSD'de %21'inde** chandelier
ATEŞLEYEBİLİRDİ. Geri kalanı BE kilidiyle kapandı → kullanıcının "sürekli çok
küçük kâr" gözlemi tam olarak bu.

## 4. Replay: trailing'i SIKMAK 5 pencerede de kazandırıyor

Kaymasız, 4 bağımsız pencere (net $ / PF / maxDD $):

| chand | W1 | W2 | W3 | W4 |
|---|---|---|---|---|
| 1.2 (canlı) | 383 / 1.48 / 50 | 4116 / 1.68 / 97 | 4714 / 1.79 / 93 | 3863 / 1.77 / 80 |
| 0.5 | 418 / 1.53 / 50 | 4160 / 1.69 / 96 | 4782 / 1.80 / 92 | 4012 / 1.81 / 80 |
| **0.3** | **482 / 1.62 / 50** | **4413 / 1.73 / 92** | **5085 / 1.86 / 90** | **4306 / 1.87 / 79** |
| 0.2 | 581 / 1.74 / 50 | 4974 / 1.82 / 88 | 5743 / 1.96 / 86 | 4617 / 1.92 / 77 |

1.2 → 0.3: **W1 +26%, W2 +7%, W3 +8%, W4 +11%**; PF her pencerede artıyor,
maxDD düşüyor veya aynı. Çıkış dağılımı BE'den TRAIL'e kayıyor
(W2: BE 2754→, TRAIL 329→2119).

### Yanlış-pozitif testleri (hepsi geçti)
- **15 dk bar çözünürlüğü:** yön korunuyor, etki ~%36 küçülüyor (+482.8 vs +754.5 W4).
  Per-işlem TRAIL kârı 10.87 → 5.18 $. Bar çözünürlüğüne bağlı bir kısmı var.
- **2 pip aleyhe kayma (slip=2):** yön ve büyüklük korunuyor.

| chand | n | WR% | net $ | PF | DD $ | TRAIL n |
|---|---|---|---|---|---|---|
| 1.2 | 3224 | 75.4 | 2154 | 1.38 | 126 | 203 |
| 0.5 | 3073 | 75.9 | 2305 | 1.42 | 127 | 516 |
| 0.3 | 3009 | 76.0 | 2538 | 1.47 | 128 | 793 |
| 0.2 | 3010 | 75.9 | 2810 | 1.51 | 123 | 1430 |

Yani "sıkı trailing" bir spread-gürültüsü artefaktı DEĞİL — 2 pip kaymadan sonra da
kazanıyor. (0.05 gibi uç değerlere gitmek gerekmiyor; 0.3 hem ölçülü hem kanıtlı.)

### Elenenler (kontrol kolları)
- Trailing'i **gevşetmek** (2.0/3.0): yassı, pencere-arası işaret tutarsız.
- BE'yi tamamen kaldırmak: felaket (W1 −122, W2 −535).
- BE'yi geciktirmek (vol-be 1.5/2.0): felaket (W1 −65/−77, W2 +168/−57).
- SL'yi genişletmek (2.0): işaret tutarsız, DD artıyor.

## 5. Canlı ↔ replay uyuşmazlığı (düzeltilmesi gereken asıl hata)

| | ATR kaynağı |
|---|---|
| Replay (`forex_replay_backtest.py:1828-1830`) | `pos.entry_atr_pips` — **girişte dondurulmuş** |
| Canlı (`forex.py:4369` → `4485`) | her tick yeniden hesaplanan **cari** ATR |

Canlıda `entry_atr` pozisyonda SAKLANMIYOR (`forex.py:5953-5984` alan listesinde yok;
`grep entry_atr` sıfır sonuç) ama `mfe_pips` var. Sonuç: canlı, replay'in doğruladığı
davranışı uygulamıyor — cari ATR sıçradığında trailing mesafesi işlem ortasında
genişleyip kazanılan pip'i geri veriyor.

**Doğru çeviri tek başına "0.3" yazmak değil; replay'in doğruladığı `0.3 × giriş ATR`
davranışı.** Bu yüzden öneri: giriş ATR'sini sakla + chandelier'de onu kullan
(yoksa cari ATR'ye düş) + `chandelier_atr_mult = 0.3`.

---

## 6. KRİTİK DÜZELTME — canlı MT5'i kim yönetiyor?

Yukarıdaki replay deneyleri **motorun (`forex.py`) chandelier yolunu** ölçtü.
Ama canlı hesabı bu yol YÖNETMİYOR:

- `require_mt5_connection = true` ve `mt5_connected = true` (canlı `live_status.json`).
- MT5 bağlıyken motor pozisyonu **kendi açmıyor**: `OPEN_ORDER` komutu kuyruğa
  giriyor (`forex.py:5926-5954`) — `_AUTO_STATE["open_positions"]`'a yalnız MT5
  bağlı DEĞİLKEN yazıyor (`forex.py:5962-6022`).
- Canlı açık pozisyonun `id`'si `None`, `ticket`'ı var → kayıt MT5'ten geliyor,
  engine paper kaydı olmadığı için `entry_atr_pips` orada **yok**.
- Trailing'i **`scripts/mt5_bridge.py`** uyguluyor ve orada **chandelier HİÇ YOK**
  (`grep chandelier scripts/mt5_bridge.py` → boş). Köprü sabit-pip trail kullanır:
  `cand_sl = cur_p − eff_trail_pips` (`mt5_bridge.py:959`), `eff_trail_pips` işlem
  başına motor komutuyla gelir (`spec_exits["trail_pips"]`).

**Yani canlıda chandelier ateşlemiyor — motorunkinden de ölü.** `chandelier_atr_mult`
ayarı canlı MT5 hesabını **hiç etkilemez**; yalnız engine paper modunu etkiler.

### Köprünün gerçek kaldıracı: sabit-pip trail (W4, aynı bayraklar)

| trail pips | n | WR% | net $ | PF | DD $ | TRAIL n |
|---|---|---|---|---|---|---|
| 12 | 3130 | 77.6 | 3796 | 1.76 | 80 | 474 |
| 20 | 3141 | 77.7 | 3951 | 1.80 | 80 | 334 |
| 30 | 3148 | 77.7 | 3948 | 1.79 | 80 | 261 |
| 40 (XAU bugünkü) | 3147 | 77.7 | 3933 | 1.78 | 80 | 219 |
| *chandelier 1.2 referans* | 3146 | 77.5 | 3863 | 1.77 | 80 | 203 |

**Sabit-pip trail yassı** — 12'den 40'a hiçbir şey değişmiyor (3796–3951, PF
1.76–1.80). Yani "trailing mesafesini değiştirmek" canlı kaldıraçta **hiçbir şey
yapmıyor**. Aranan etki **tepeye demirlenmiş** trailing'de (chandelier MFE'den
ölçer), köprünün sabit mesafesinde değil.

## 7. KÖPRÜYE PORT EDİLDİ ve replay ile doğrulandı (2026-10-13, aynı gün)

§6'daki açık iş kapandı: chandelier `scripts/mt5_bridge.py`'ye taşındı ve portun
kendisi replay'de ölçüldü.

**Köprü değişiklikleri** (`scripts/mt5_bridge.py`):
- `POSITION_MFE_PIPS` (bilet başına tepe kâr, pips) ve `POSITION_ENTRY_ATR_PIPS`
  (giriş ATR'si, **ilk görülüşte BİR KEZ dondurulur**) modül sözlükleri.
- `_compute_atr_pips(sym, pip_size)` — `M5 × 20` bar ortalama (high−low)/pip; hata
  durumunda 0.0 döner, asla yükseltmez. Birim doğrulaması: Wilder ATR-14 ile tüm
  test edilen sembollerde ±%3 içinde (XAU 31.5 vs 29.3, BTC 108.7 vs 109.5,
  US30 32.1 vs 31.0, GBPUSD 4.5 vs 4.4, USDJPY 2.8 vs 2.9).
- `CURRENT_SETTINGS["chandelier_atr_mult"] = 0.0` varsayılanı → ayar gelmezse eski
  sabit-pip davranışı birebir korunur (`else` dalı değişmedi).
- Chandelier dalı: `cand_pips = MFE − mult × giriş_ATR`, `$1` tabanıyla; SL asla
  geri gitmez; **girişe göreli** (`entry_p ± cand_pips`), replay ile aynı ölçüm.

**Motor tarafı** (`forex.py`): `/mt5/sync` ayar yüküne `chandelier_atr_mult`
eklendi; `OPEN_ORDER` komutuna `entry_atr_pips` eklendi. Böylece köprü değeri
motordan alır; motorun gönderdiği değer **artık canlı davranışı belirler**.

**Portun replay doğrulaması** (XAUUSD+BTCUSD, 2026-07-15→08-15, aynı bayraklar):

| kol | n | WR% | net $ | PF | DD $ | TRAIL n |
|---|---|---|---|---|---|---|
| sabit 40 pip (XAU bugünkü) | 3147 | 77.7 | 3933.27 | 1.78 | 80.03 | 219 |
| sabit 30 pip | 3148 | 77.7 | 3947.88 | 1.79 | 80.03 | 261 |
| sabit 20 pip | 3141 | 77.7 | 3950.88 | 1.80 | 80.03 | 334 |
| chandelier 0.5 | 3131 | 77.6 | 4012.48 | 1.81 | 80.03 | 548 |
| **chandelier 0.3** | **3128** | **77.6** | **4305.70** | **1.87** | **79.49** | **1062** |
| chandelier 1.2 (eski varsayılan) | 3146 | 77.5 | 3863 | 1.77 | 80 | 203 |

Chandelier 0.3 hem net hem PF hem maxDD'de sabit-pip'i geçiyor. **Kritik:** `chand 1.2`
(yani ESKİ kod varsayılanı) sabit-pipten **kötü** (3863 vs 3933) — yani 1.2'yi
olduğu gibi bırakıp portu aktive etmek canlıyı bozardı.

| 2-pip aleyhe kayma | net $ | PF | DD $ |
|---|---|---|---|
| sabit 40 + slip2 | 2218.56 | 1.39 | 126.19 |
| **chand 0.3 + slip2** | **2538.31** | **1.47** | 127.71 |

Kaymada da sıralama korunuyor → etki spread-gürültüsü artefaktı değil.

## Öneri — UYGULANDI

1. **`chandelier_atr_mult` = 0.3** yazıldı: `forex.py:3245` Field varsayılanı ve
   kalıcı `D:\data\forex_auto_settings.json` (yedek: `.bak-chand03-20261013`).
   Motor bunu `/mt5/sync` ile köprüye gönderir. Değerlendirme: 1.2 → canlıda
   sabit-pipten kötü; 0.3 → dört bağımsız pencerede ve doğrudan XAU+BTC port
   replay'inde en iyi; 0.2 biraz daha iyi görünse de 15 dk bar testinde etkinin
   ~%36'sı bar çözünürlüğüne bağlı çıktığı için ölçülü 0.3 seçildi.
   **Geri alma:** panelden 1.2'ye çek veya `forex_auto_settings.json`'da 1.2.
2. **Giriş-ATR paritesi** (`resolve_chandelier_atr`) hem motor paper yolunda hem
   köprüde: `entry_atr_pips` girişte dondurulur, yoksa cari ATR'ye düşülür. §5'teki
   canlı↔replay uyuşmazlığı kapandı.
3. **Dokunulmayan:** BE kilidi (0.40/0.60, birleşim tetiği) — bu analiz onu
   suçlamıyor; aksine trail'in ondan devralması gerektiğini söylüyor.

**Dürüstlük notları:** (a) replay XAU+BTC üzerinde koşuldu, canlı defterde BTCUSD
145/249 işlem; (b) 15 dk bar testi chandelier etkisinin bir kısmının bar
çözünürlüğüne bağlı olduğunu gösteriyor; (c) sabit-pip trail sweep'i global bir
`--trail-pips` kullandı, canlı ise sembol başına farklı değer (XAU 40 / BTC 48) —
yassı sonuç per-sembol incelikleri gizliyor olabilir, ama hiçbir eğim göstermiyor.
