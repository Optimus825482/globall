# Combo3 (M5, yalnız XAUUSD) — Canlı Demo Paper Kurulumu ve Kayma Ölçümü

Tarih: 2026-10-28 · Kaynak kanıt: `docs/REPLAY_STRATEJI_TARAMA_2026_10_27.md`
Kod: `backend/app/combo3_m5.py` (saf kural), `backend/app/routers/forex.py` (canlı kol + kayma defteri + `GET /api/forex/slippage`), `scripts/mt5_bridge.py` (fill/spread/gecikme yankısı), `scripts/combo3_slippage_report.py` (rapor), `backend/tests/test_combo3_m5.py`

## 1. Ne eklendi

- **Yeni giriş kolu `combo3_m5`**: UT Bot (ATR10×1) ∪ Donchian(20)+Vortex(14) ∪ Vortex(14) kesişimi, kapanmış M5 barları (köprü broker mumu; yoksa tik kovası), ilk ateşleyen yön. SL = `combo3_sl_atr` × ATR(14), TP = `combo3_tp_r` × SL. Diğer her şey (kapılar, EV, ADX kalkanı, BE/trailing, piramit, lot tavanı) mevcut motor.
- **Kol-özel risk**: `combo3_risk_pct` (varsayılan **%1**) yalnız bu kolun işlemlerinde `risk_gold_pct`'yi ezer (`effective_risk_pct`). Diğer kollar etkilenmez.
- **Etiket**: MT5 emir yorumu `CMB3 <skor>`; kapanan işlemler `COMBO3_M5` stratejisi olarak çözülür (panel/CSV).
- **Kayma defteri**: köprü her OPEN_ORDER sonucuna `fill_price` (MT5 `res.price`), `req_price` (gönderim anı tick), `spread_pips_exec`, `latency_ms`, `exec_ts` ekler ve motorun komutundaki `signal_price` (sinyal barı kapanışı), `signal_bar_time`, `spread_pips_signal`, `created_ts` alanlarını yankılar. Backend `_record_slippage` ile pip cinsinden hesaplar:
  - `exec_slip_pips` = fill − istek (broker icra kayması; pozitif = aleyhe)
  - `signal_slip_pips` = fill − sinyal barı kapanışı (karar → fill toplam maliyet)
  - `decision_to_fill_sec`, spread (sinyal / icra), gecikme
  Kayıtlar bellekte ve `backend/data/live_slippage_log.jsonl` dosyasında (yeniden başlatmada yüklenir). **Tüm kolların** emirleri kaydedilir; Combo3 `CMB3` etiketiyle süzülür.
- **Endpoint**: `GET /api/forex/slippage?tag=CMB3&limit=500` → `{count, summary{tag: {trades, exec_slip_pips{n,mean,median,p90,max}, signal_slip_pips, spread_pips_exec, latency_ms, decision_to_fill_sec}}, records}`.

Varsayılan **açık** (`combo3_enabled=true`, 2026-10-28 kullanıcı kararı); sunucudaki eski `forex_auto_settings.json` bu anahtarı içermediği için backend restart'ta varsayılan uygulanır. SuperTrend yön filtresinden muaf (replay kanıtı filtre kapalıyken alındı). Kayma defteri köprü güncellendiği anda tüm emirler için çalışır.

Panel: "Otonom Ayarlar" → **🧩 Combo3 M5** sekmesi (aç/kapa, risk %, SL×ATR, TP R, günlük kota, semboller). Radar sayfasında kol satırı (`COMBO3_M5`, 🧩 rozet), rapor/işlemler sayfalarında strateji etiketi ve filtresi (`Combo3 UTBot+Vortex (M5)`), portföy karar günlüğünde `Combo3 M5` filtresi eklendi.

## 2. Devreye alma (sunucu + köprü)

1. Sunucu: `git pull`, backend restart (forex.py değişti) ve frontend build (4 sayfa + ayar paneli değişti). Köprü PC: `scripts/mt5_bridge.py` güncel sürümle yeniden başlat (`run_mt5_bridge.bat`).
2. Ayar gerekmez (varsayılan açık). Değiştirmek için panel sekmesi veya POST `/api/forex/auto-paper/settings`:

```json
{"combo3_enabled": true, "combo3_symbols": ["XAUUSD"], "combo3_risk_pct": 1.0, "combo3_sl_atr": 1.5, "combo3_tp_r": 2.0, "combo3_max_per_day": 0}
```

3. Doğrulama: radar sayfasında `COMBO3_M5 / XAUUSD` satırı; karar günlüğünde `🧩 [XAUUSD] Combo3 ... adayı` ve ilk emirden sonra `📏 Kayma [XAUUSD] CMB3: icra X pip ...` satırı. `GET /api/forex/slippage?tag=CMB3` dolmaya başlamalı.
4. XAUUSD `allowed_symbols` içinde olmalı (zaten canlı listede). Motorun ADX kalkanı (ADX ≥ 20) ve EV kalkanı bu kol için de geçerli; replay'de de aynıydı.

Not: Diğer kollar (S3, EAP, Squeeze, Donchian…) XAUUSD'de açık kalır. Ölçüm `CMB3` etiketiyle izole edilir; strateji sonucunu izole görmek istiyorsanız XAUUSD'yi diğer kolların listelerinden geçici çıkarın (`s3_symbols_15m`, `ema_adx_symbols`; `squeeze_kc_symbols` ve `s3_symbols_5m` canlı sabittir, kodda).

## 3. Ölçüm ve karar kuralı

Rapor: `python scripts/combo3_slippage_report.py --api https://global.erkanerdem.online --tag CMB3` (veya `--file backend/data/live_slippage_log.jsonl`).

| Ölçüm | Eşik | Anlam |
|---|---|---|
| Örnek sayısı | ≥ 20 işlem | daha azıyla karar yok |
| İcra kayması medyan / p90 | ≤ 1 pip / ≤ 2 pip | replay 2 pip kaymada PF 1.81 → 1.09 |
| Spread (icra anı) medyan | ≤ 2 pip | replay 2.5 pip kesiyordu |
| Karar→fill | ≤ 10 sn | M5 kapanışı sonrası gecikme |

- p90 > 2 pip → strateji kenarını kaybeder; risk artırılmaz, kol kapatılır.
- Eşikler tutuyor **ve** 2 hafta `CMB3` kapanan işlemleri PF ≥ 1.3 → risk kademeli (%1 → %2 → %5), her kademede ölçüm tekrar.
- %20 (replay hücresi) için ayrıca marj kontrolü gerekir: 0.33 lot altın 1000 USD kasada ancak 1:500 ve tek pozisyonla; motor 3 piramide izin veriyor.

## 4. Sınırlar

- Kayma yalnız **açılış** emirlerinde ölçülür; stop/TP fill kayması MT5 deal geçmişinden ayrıca okunmalı (ileride: SL fiyatı vs OUT deal fiyatı).
- Sinyal fiyatı M5 bar kapanışı; motor döngüsü barı birkaç saniye gecikmeyle görür → `signal_slip_pips` gecikme + icra toplamıdır, `exec_slip_pips` saf broker kaymasıdır.
- Hafta sonu altın kapalı; `weekend_now` kol yalnız kripto sembollerinde çalışır (Combo3 listesinde kripto yok → hafta sonu sinyal yok).
