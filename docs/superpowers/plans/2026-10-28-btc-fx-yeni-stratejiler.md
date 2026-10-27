# Plan: BTC ve FX için yeni strateji aileleri — eklenti mimarisi, geliştirme, test, doğrulama

Tarih: 2026-10-28 · Şube: main (depo konvansiyonu; kullanıcı kararı) · Yöntem: subagent-driven

## Spec (bağlayıcı)

**Amaç.** Mevcut replay motoru (`scripts/forex_replay_backtest.py`) üzerinde, yalnız giriş stratejisi değiştirilerek (`scripts/replay_strateji_gunluk.py` sarmalayıcısı), BTCUSD ve FX pariteleri için YENİ gösterge/kural aileleri geliştirip test etmek. Kullanıcının nihai hedefi günlük +%50 (1000 → 1500 USD); ölçülebilir başarı ölçütü ise aşağıdaki "robust kenar" tanımıdır — hedef güne ulaşan hücreler ayrıca raporlanır.

**Robust kenar (bir strateji × sembol × dilim hücresi "aday" sayılır):**
1. 14 hafta (21 Tem – 27 Eki 2026) PF ≥ 1.30 ve net > 0, ≥ 60 işlem.
2. İlk 7 hafta (21 Tem – 7 Eyl) VE son 7 hafta (8 Eyl – 27 Eki) ayrı ayrı net > 0.
3. Kayma stresinde (FX: `--slip-pips 1`; BTC: `--slip-pips 10`, 1 pip = 1 USD) PF ≥ 1.10.
4. Gün P&L ≤ −700 USD ("iflas") olan gün sayısı ≤ 2.

**Veri.** Önbellekler mevcut: `outputs/replay_cache_xaubtc_{m3,m5,m15}.json` (XAUUSD, BTCUSD), `outputs/replay_cache_fx21_{m1,m3,m5,m15,m30}.json` (21 parite). Postgres `historical_candles` 1m/3m (21 parite, kaynak `mt5_icmarkets_rates`). Gerçek spread profili `outputs/fx_spread_db_1m.json`. Yeni veri çekilmez.

**Koşum araçları.** `scripts/replay_strateji_tarama.py` (hücre matrisi; `--symbols` her sembol ayrı hücre; `--cache-pattern`; `--db`; `--extra=...`), sonuçlar `outputs/replay_strateji/gun_<tag>.json` ve `ozet_tur<tur>.json`. Sarmalayıcı `scripts/replay_strateji_gunluk.py`: `candidate()` motorun `_entry_mode_candidate`'ini değiştirir; `series_for(sym, strat, bars)` sembol başına bir kez gösterge serisi hesaplar; `side_for(strat, s, b, i)` kapanmış bar i için +1/−1/0 döner. Bar listesi `b` `ha_supertrend_mt5_7d.Bar` (t, open, high, low, close) nesneleridir. Çıkış: SL = sl_atr × ATR(14), TP = tp_r × SL; BE/trailing motorun.

**Global kısıtlar.**
- Look-ahead yok: `side_for` yalnız `i` ve öncesini okur; seri fonksiyonları ileri bakmaz.
- Yeni stratejiler `scripts/strategies/<aile>.py` eklenti dosyalarında yaşar (Task 1 arayüzü); `replay_strateji_gunluk.py` Task 1 dışında değiştirilmez; `forex_replay_backtest.py` değiştirilmez.
- Her strateji dosyası sentetik barlarla en az 1 look-ahead testi ve 1 sinyal testi içerir (`backend/tests/` değil; `scripts/strategies/test_<aile>.py`, `python -m unittest` ile koşar).
- Risk: sistem varsayılanı (FX %5, BTC %2); risk artırımı ancak Task 4'te, lineer ölçekleme ile raporlanır.
- FX stratejileri spread'e duyarlı tasarlanır: SL ≥ 8 × sembol spread'i (profil `outputs/fx_spread_db_1m.json`, yoksa 1.5 pip) değilse aday üretmez; M15/M30 dilimleri; seans filtresi (07–20 UTC) kullanılabilir.
- Her koşum `--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json` ile (FX) yapılır; BTC için spread profili gerekmez.
- Sonuçlar dürüst raporlanır: negatif sonuç da sonuçtur. Parametre taraması (grid) yasak; her strateji tek, önceden yazılmış parametre setiyle koşar (en fazla 2 varyant).
- Commit: her task kendi commit'ini yapar (main). Sonuç JSON dökümleri commit edilmez (depo kuralı).

## Task 1 — Strateji eklenti yükleyici (replay_strateji_gunluk.py)

Dosya: `scripts/replay_strateji_gunluk.py`. Eklenti dizini `scripts/strategies/` (yeni, `__init__.py` yok; dosyalar `importlib` ile yüklenir).

Eklenti arayüzü (her `scripts/strategies/*.py`, `test_*.py` hariç):
```python
STRATEGIES = {
    "ad": {
        "series": callable(bars_eng, closes) -> dict,   # sembol başına bir kez; dict'e "atr" EKLEMEK ZORUNLU DEĞİL (sarmalayıcı ekler)
        "side": callable(s, bars_eng, i) -> int,        # +1 BUY, -1 SELL, 0 yok; yalnız i ve öncesi
        "sl_atr": float, "tp_r": float,                 # varsayılan çıkış; CLI --sl-atr/--tp-r ezer
        "symbols": None | set[str],                     # None = her sembol; dolu = yalnız bu semboller (diğerleri için side çağrılmaz)
        "spread_min_mult": float | None,                # FX: SL ≥ bu × spread değilse aday yok (None = kontrol yok)
    },
}
```
Değişiklikler:
1. `load_plugins()` : `scripts/strategies/*.py` dosyalarını (`test_` ile başlayanlar hariç) yükler, `STRATEGIES` sözlüklerini `PLUGINS: dict` içine birleştirir; ad çakışmasında `SystemExit("eklenti ad cakismasi: ...")`.
2. `STRATEGIES` tuple'ı → yerleşik adlar + eklenti adları (argparse `choices` ve driver bunu okur).
3. `series_for`: strat eklentideyse `plug["series"](b, closes)` çağrılır ve `s["atr"] = wk.atr(b, 14)` eklenir (yoksa).
4. `side_for`: strat eklentideyse `plug["side"](s, b, i)`.
5. `candidate`: eklentinin `symbols` kümesi doluysa ve sym içinde değilse `None`; `sl_atr/tp_r` ACTIVE'den (CLI vermediyse eklenti varsayılanı: `main()` içinde `--sl-atr`/`--tp-r` argümanları `default=None`, None ise eklenti değeri, o da yoksa 1.5/2.0); `spread_min_mult` doluysa `sl_pips < mult × spread_pips` iken `None` — spread_pips `tech.get("spread_pips")` yoksa `_SPREAD_PROFILE` (sarmalayıcı başlangıçta `outputs/fx_spread_db_1m.json` varsa okur; `avg_pips`), o da yoksa 1.5.
6. Test: `scripts/strategies/test_loader.py` — geçici eklenti dosyası yazıp `load_plugins()` ile yüklendiğini, ad çakışmasında SystemExit, `symbols` filtresinin `candidate`'i None yaptığını, `spread_min_mult` kapısını doğrular. `python -m unittest scripts.strategies.test_loader` ile koşar (dizinde `__init__.py` olmadığı için `sys.path` ile `scripts/` eklenir; test dosyası bunu kendi yapar).
Tanım: mevcut 14 yerleşik strateji aynen çalışmaya devam eder (regresyon: `--strategy combo3 --tf m15 --symbols XAUUSD --start 2026-10-20 --end 2026-10-23` koşusu önceki `gun_hiz_test2.json` ile aynı işlem sayısını verir).

## Task 2 — BTC strateji ailesi (`scripts/strategies/btc_aile.py`)

Kapsam: BTCUSD, dilimler m5 ve m15 (`outputs/replay_cache_xaubtc_{tf}.json`), `symbols={"BTCUSD"}`.
En az 4 strateji, her biri farklı mantık, parametreler önceden sabit (grid yok):
1. `btc_seans_kirilim` — 13:30–14:30 UTC (ABD açılışı) aralığının high/low'u; 14:30–20:00 UTC arasında kapanış aralık dışına çıkınca yönünde giriş; günde yön başına 1; SL = aralık yüksekliğinin yarısı (ATR cinsinden `sl_atr` eşdeğeri: aralık/2 ÷ ATR, en az 1.0), TP 2R.
2. `btc_rsi2_bb_donus` — RSI(2) < 5 ve kapanış BB(20,2.5) alt bandının altında, EMA(200) üstünde → BUY (ters: RSI(2) > 95, üst bant üstünde, EMA200 altında → SELL); SL 3.0×ATR, TP 1.0R (ortalamaya dönüş).
3. `btc_donchian55_trend` — Donchian(55) kırılımı + EMA(200) tarafı + ADX(14) ≥ 25; SL 2.0×ATR, TP 0 (TP yok, motor trailing'i).
4. `btc_keltner_geri_htf` — EMA(200) tarafı, kapanış Keltner(20, 1.5×ATR10) orta bandına geri çekilip yönünde kapanış (önceki bar orta bandı aştı, bu bar yönünde kapandı), ayrıca son 3 barın en düşüğü/en yükseği üstünde/altında kapanış; SL 2.0×ATR, TP 2R.
5. (opsiyonel) `btc_nr7_kirilim` — NR7 barı sonrası kırılım + ADX ≥ 20; SL 1.5×ATR, TP 2R.
Her strateji için `scripts/strategies/test_btc_aile.py`: sentetik barlarla sinyal üretimi ve look-ahead testi (seri sonrasına bar eklenince önceki karar değişmez).
Koşum (implementer yapar): `python scripts/replay_strateji_tarama.py --tur btc1 --tfs m5,m15 --strategies <4-5 ad> --jobs 4 --symbols BTCUSD --cache-pattern "outputs/replay_cache_xaubtc_{tf}.json" "--extra=--all-symbols"` ve rapor dosyasına tablo (işlem, WR, PF, net, 14h hedef/iflas/ort, 7h) + yorum.

## Task 3 — FX spread-duyarlı strateji ailesi (`scripts/strategies/fx_aile.py`)

Kapsam: 8 parite EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF, GBPJPY, EURJPY, NZDUSD; dilimler m15 ve m30 (`outputs/replay_cache_fx21_{tf}.json`); `symbols` = bu 8; `spread_min_mult = 8.0`.
En az 4 strateji:
1. `fx_londra_aralik` — 07:00–08:00 UTC aralığı; 08:00–12:00 UTC kapanış aralık dışına çıkınca giriş; günde yön başına 1; aralık yüksekliği ≥ 0.8×ATR(14) şartı; SL = aralık/2 (ATR eşdeğeri, en az 1.0×ATR), TP 2R.
2. `fx_ema200_rsi_geri` — EMA(200) tarafı + ADX ≥ 20; RSI(14) 50 altına inip (BUY) 50 üstüne kapanışla dönerse, kapanış EMA(21) üstünde; SL 2.5×ATR, TP 1.5R; yalnız 07–20 UTC.
3. `fx_bb_donus_m30` — BB(20, 2.5) dışına kapanış + ADX(14) < 20 + sonraki bar bant içine kapanış → ters yön; SL 2.0×ATR, TP 1.0R; 07–20 UTC.
4. `fx_donchian_gunluk` — Donchian(20) kırılımı, kapanış günlük EMA(50) tarafında (M15/M30 barlarından `resample` ile günlük seri; yalnız kapanmış günler), ADX ≥ 25; SL 2.0×ATR, TP 0 (trailing).
Test dosyası `scripts/strategies/test_fx_aile.py` (sinyal + look-ahead + spread kapısı). Koşum: `--tur fx_yeni --tfs m15,m30 --strategies <adlar> --jobs 6 --symbols <8 parite> --cache-pattern "outputs/replay_cache_fx21_{tf}.json" "--extra=--all-symbols --spread-profile outputs/fx_spread_db_1m.json"`; rapor tablosu parite × strateji × dilim.

## Task 4 — Doğrulama ve rapor

Girdi: Task 2 ve 3 raporları (`outputs/replay_strateji/ozet_turbtc1.json`, `ozet_turfx_yeni.json`, `gun_*.json`).
1. Robust kenar ölçütlerini (Spec) her hücreye uygula; aday listesi çıkar (script: `scripts/strateji_dogrulama.py`, ozet json'ları okur, 7w/ilk-7w net'i `gun_*.json`'daki `daily`'den hesaplar, tablo basar, `outputs/replay_strateji/dogrulama.json` yazar).
2. Adaylar için kayma stresi koşumu (aynı driver, `--tur dogrulama_slip`, `--extra` ile `--slip-pips`), ölçüt 3.
3. Adaylar için risk ölçekleme tablosu (%2/5/10/20, gün P&L lineer; hedef gün ve iflas gün sayıları) — hedef (+500) kaç günde tutuluyor.
4. Rapor: `docs/BTC_FX_YENI_STRATEJILER_2026_10_28.md` — düzen, tüm hücre tablosu (kısa), aday tablosu, kayma, risk ölçekleme, dürüst karar; aday yoksa bunu açıkça yaz.
