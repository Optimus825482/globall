# Kombo XAU (M5) — Demo Kağıt Testi Kurulumu ve Ölçüm Protokolü

Tarih: 2026-10-28 · Kaynak kanıt: `docs/KOMBINASYON_TARAMASI_2026_10_28.md` (§5.2 kötümser BE dolumu, §6 holdout, §9 karar)
Kod: `backend/app/kombo_m5.py` (saf port), `backend/app/routers/forex.py` (canlı kol, sinyal günlüğü, `GET /api/forex/kombo/signals`), `backend/tests/test_kombo_m5.py` (parite), `backend/tests/test_kombo_live.py` (bağlantı)

## 1. Ne eklendi

- **Yeni giriş kolu `kombo_m5`** — plan v3 kombinasyon taramasında 5 ölçütü geçip temiz holdout'ta (zayıf/koşullu) tutunan üç XAUUSD m5 kombosu, her biri **kendi etiketiyle** ayrı ölçülür:

| Ad | Etiket | Tanım | SL / TP |
|---|---|---|---|
| kombo_1 | `KMB1` | `sonra(ut_bot → combo3, 12)` \| seans 00–07 UTC | 3.0×ATR / 3R |
| kombo_4 | `KMB4` | `or(hma_ao, tsi_ema50)` \| seans 13–20 UTC | 1.5×ATR / 2R |
| kombo_9 | `KMB9` | `sonra(btc_keltner_geri_htf → combo3, 3)` \| ATR14 yüzdeliği ≥ 50 | 2.0×ATR / 1R |

- **Sinyal paritesi kanıtı:** port, replay eklentisiyle (`scripts/strategies/kombo.py`) 25 284 XAUUSD M5 barında **birebir** aynı sinyali veriyor (kombo_1 1214, kombo_4 380, kombo_9 254 sinyal; 0 fark). Canlıya giden 600 barlık pencerede de son 3000 barın her birinde 0 fark (142 / 51 / 40 sinyal). 300 barlık pencerede kombo_9 EMA200 tohumu yüzünden 5 fark verdi; bu yüzden canlı kol **600 bar** okur (`_KOMBO_BAR_LIMIT`).
- **Kol-özel risk:** `kombo_risk_pct` (varsayılan **%2**, rapor §9) yalnız bu kolun işlemlerinde `risk_gold_pct`'yi ezer. Diğer kollar etkilenmez.
- **Etiket:** MT5 emir yorumu `KMB1|KMB4|KMB9 <skor>`; kapanan işlemler `KOMBO_M5` stratejisi olarak çözülür; kayma defteri (`GET /api/forex/slippage?tag=KMB1`) kombo başına süzülür.
- **Sinyal günlüğü:** her kombo sinyali, emre dönüşsün ya da dönmesin, bar başına bir kez `backend/data/kombo_signal_log.jsonl` dosyasına yazılır (`ad, tag, action, bar_time, close, sl_pips, tp_pips, atr, spread_pips, durum`). `durum`: `aday` (motora verildi) / `kota` (günlük kota). Motorun diğer kapıları (ADX, EV, spread, "zaten açık pozisyon") adayı düşürürse günlükte `aday` kalır ve kayma defterinde karşılığı olmaz → "sinyal / emir" oranı buradan okunur.
- **Endpoint:** `GET /api/forex/kombo/signals?ad=kombo_1&limit=500` → `{count, summary{ad: {tag, sinyal, emir, BUY, SELL, durum{}}}, records, tanimlar, risk_pct, enabled}`. `emir` = kayma defterinde aynı etiket + aynı sinyal barı olan kayıt sayısı.
- **Combo3 kolu varsayılan KAPALI** (`combo3_enabled=false`): kombo_1 ve kombo_9'un tetikleyicisi combo3 sinyali; iki kol aynı barda aynı XAUUSD pozisyon slotu için yarışmasın. Panelden tekrar açılabilir.
- SuperTrend yön filtresinden muaf (replay kanıtı filtre kapalıyken). BE/trailing motorun kendi mantığı (replay ile aynı).

Panel: "Otonom Ayarlar" → **🧪 Kombo XAU M5** sekmesi (aç/kapa, risk %, günlük kota, semboller; tanımlar salt-okunur). Radar sayfasında kol satırları (`KOMBO_M5`, kombo başına bir satır), rapor/işlemler sayfalarında `Kombo XAU (M5) KMB1/4/9` etiketi ve filtresi, portföy karar günlüğünde `Kombo XAU M5` filtresi.

## 2. İzolasyon sınırı (dürüst not)

Motorun **sembol başına tek pozisyon** kuralı değişmedi: XAUUSD'de aynı anda tek pozisyon olur. Aynı barda iki kombo ateşlerse ilk sıradaki emre dönüşür, diğeri günlükte `aday` kalır. Replay'deki "izole defter" (her kombo ayrı 1000 USD kasa) canlıda birebir yoktur; kombo bazında ölçüm **etiket + sinyal günlüğü** ile yapılır. Tam izolasyon isteniyorsa üç ayrı demo hesap gerekir.

## 3. Devreye alma

1. Sunucu: `git pull`, backend restart (forex.py + yeni modül), frontend build (radar, raporlar, işlemler, portföy, ayar paneli). Köprü PC'de değişiklik yok (combo3 kurulumundaki fill/spread yankısı yeterli).
2. Ayar gerekmez (varsayılan açık). Değiştirmek için panel sekmesi veya POST `/api/forex/auto-paper/settings`:

```json
{"kombo_enabled": true, "kombo_symbols": ["XAUUSD"], "kombo_risk_pct": 2.0, "kombo_max_per_day": 0, "combo3_enabled": false}
```

3. Doğrulama: radar sayfasında `KOMBO_M5 / XAUUSD` üç satır ("sinyal yok — …" normaldir); karar günlüğünde `🧪 [XAUUSD] Kombo …: kombo_x (KMBx) BUY adayı`; `GET /api/forex/kombo/signals` ilk sinyalden sonra dolmaya başlar; ilk emirden sonra `GET /api/forex/slippage?tag=KMBx`.
4. Sunucudaki `forex_auto_settings.json` eski `combo3_enabled: true` içeriyorsa combo3 açık kalır → panelden kapatın.

## 4. Ölçüm ve karar kuralı (rapor §9)

| Konu | Kural |
|---|---|
| Süre | En az 4 hafta **veya** kombo başına ≥ 40 kapanmış işlem (hangisi sonra gelirse) |
| Ölçülecekler | (a) BE/SL çıkışlarında hedef kilit fiyatı − gerçek dolum (pip); §5.2 ideal–kötümser aralığının neresinde. (b) Sinyal paritesi: `kombo_signal_log.jsonl` ile aynı günlerin replay koşumu (`scripts/replay_strateji_gunluk.py --strategy kombo_x --tf m5 --symbols XAUUSD --start … --end …`) bar bazında eşleşme. (c) Maliyet sonrası PF (kombo başına, `KMBx` kapanışları). |
| Geçme | Maliyet sonrası PF ≥ 1.3; medyan BE dolum kaybı kötümser senaryonun yarısından az; hiçbir komboda net < −%10 kasa |
| Durma | Herhangi bir komboda 20 işlem sonrası PF < 1.0 **veya** BE dolumları sistematik olarak kötümser tarafta → o kombo tanımlardan çıkarılır |
| Sonra | Geçen kombolar için risk kademeli %2 → %5; +500/gün hedefi bu sinyal setleriyle gerçekçi değil |

Kötümser BE dolum ölçüsü için replay tarafı: `python scripts/kombo_be_dolum_analizi.py dolum-hepsi` (bash / Git Bash; rapor §10).

## 5. Sınırlar

- Stop/TP fill kayması yalnız MT5 deal geçmişinden okunur (açılış kayması `slippage` defterinde); BE dolum farkı için OUT deal fiyatı ile `sl_price` karşılaştırılmalı — ileride otomatikleştirilecek.
- Hafta sonu altın kapalı; kol hafta sonu sessiz.
- `kombo_tanimlar` ayar dosyasından değiştirilebilir ama port yalnız `tek/or/sonra`, bileşenler `ut_bot, combo3, hma_ao, tsi_ema50, btc_keltner_geri_htf`, filtreler `seans_00_07/07_20/13_20, atr_yuksek/atr_dusuk` destekler; geçersiz tanımda kol o tur sessiz kalır ve uyarı loglar.
