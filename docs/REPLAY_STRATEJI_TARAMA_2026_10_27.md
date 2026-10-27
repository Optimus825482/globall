# Mevcut Replay Motoru + Yeni Gösterge Kombinasyonları — Günlük 1000 → 1500 Hedefi (M3/M5/M15)

Tarih: 2026-10-27 · Motor: `scripts/forex_replay_backtest.py` (canlı scalper'ın replay'i; kapılar, BE/trailing/kısmi çıkış, risk bütçesi, lot tavanları DOKUNULMADI) · Değişen tek şey: giriş stratejisi
Veri: MT5 (mt5_bridge terminali) → `outputs/replay_cache_xaubtc_{m3,m5,m15}.json` (20 Haz – 27 Eki 2026)
Scriptler: `scripts/replay_strateji_gunluk.py` (strateji + günlük değerlendirme), `scripts/replay_strateji_tarama.py` (matris koşucu)
Sonuçlar: `outputs/replay_strateji/` (gun_*.json günlük, rep_*.json motor raporu, ozet_tur*.json özetler, log_*.txt)

## 1. Kısa sonuç

- **Sürtünmesiz replay'de hedef bulundu:** yalnız altın, risk %20, M5, üç stratejinin birleşimi (UT Bot ∪ Donchian+Vortex ∪ Vortex+ADX): 83 işlem gününün 33'ünde gün P&L ≥ +500 USD (1000 → 1500), 1 günde ≤ −700; ortalama gün +615 USD, PF 1.81, son 7 haftada 42 günün 18'i hedef.
- **Ama bu sonuç kayma stresine dayanmıyor:** bacak başına 2 pip (0.20 USD) aleyhe kayma eklenince aynı hücre PF 1.09, hedef 18/83, iflas 8 gün, ortalama +81; 5 pip kaymada PF 0.67 ve net −21.9k. M3 hücreleri 2 pip kaymada bile negatif.
- **BTCUSD her stratejide zarar** (tur 1'de 36 hücrenin tamamında BTC toplamı ≤ 0 veya küçük artı). Altın, motorun BE-kilidi mekaniğiyle çok sayıda küçük kârlı "BE" çıkışı üretiyor; bu mekanik kayma karşısında kırılgan.
- Dürüst karar: **hedef yalnızca motorun idealize fill modelinde tutuluyor; gerçekçi maliyetle tutmuyor.** Paper'a alınacaksa yalnız altın + M5 + combo3, ve önce canlı spread/kayma ölçümüyle doğrulanmalı.

## 2. Düzen

- Motor varsayılanları: min_score 75 (mod adayları 200 puanla geçer), ADX kalkanı 20, EV kalkanı açık, majör saat/ATR kapıları, BE "union" tetik, spread kategori: altın 2.5 pip (0.25 USD), kripto 12 pip; lot = risk bütçesi / (SL pip × pip değeri); BALANCE sabit 1000 (gün içi birikim yok → her gün 1000 tabanı). Altın seans filtresi kapalı (24 saat).
- Strateji: `--entry-mode` yolu monkeypatch ile bu dosyadaki fonksiyona bağlandı; klasik radar kolu kapalı. SL 1.5×ATR(14), TP 2R; BE/trailing motorun.
- Giriş sinyali kapanmış barda, fill o barın kapanışı + spread (motorun kuralı).
- 14 hafta: 21 Tem – 27 Eki (altın 83 işlem günü, BTC 99 gün); 7 hafta: 8 Eyl – 27 Eki.
- Günlük hedef: gün P&L ≥ +500; "iflas" gün P&L ≤ −700.

Stratejiler (hepsi TradingView formülleriyle, GOSTERGELER.HTML'den):

| Ad | Kural |
|---|---|
| hma_ao | HMA(21) eğimi + Awesome Osc sıfır kesişimi |
| vortex_adx | VI+ / VI− (14) kesişimi (motor ADX≥20 kapısı) |
| kama_cci | Kapanış KAMA(10,2,30)'ı keser + CCI(20) ±100 |
| stoch_kijun | Stoch(14,3,3) bölge kesişimi + fiyat Kijun(26) tarafı |
| tsi_ema50 | TSI(25,13) sinyal kesişimi (sıfırın ters tarafında) + EMA50 tarafı |
| fisher_st | Fisher(9) tetik kesişimi ±1.5 ötesi + Supertrend(10,3) yönü |
| cmo_bb | CMO(9) ±50 + Bollinger(20,2) bandına geri dönüş |
| wpr_ema_trend | %R(14) −80/−20 kesişimi + EMA21/EMA50 trend |
| psar_macd | PSAR(0.02,0.2) dönüşü + MACD hist işareti |
| donch_vortex | Donchian(20) kırılımı + VI+/VI− uyumu |
| ut_bot | UT Bot (ATR10 ×1) iz süren stop kesişimi |
| coral_trend | Coral Trend (T3, N=21, cd 0.4) renk dönüşü |
| combo3 | ut_bot ∪ donch_vortex ∪ vortex_adx (ilk ateşleyen yön) |
| combo3_onay | üçünden en az ikisi aynı yönde |

## 3. Tur 1 — 12 strateji × M3/M5/M15, sistem riski (altın %10, BTC %2), iki sembol

| Hücre | İşlem | WR | Net | PF | 14h hedef/gün | iflas | ort/gün | 7h hedef | Altın net | BTC net |
|---|---|---|---|---|---|---|---|---|---|---|
| ut_bot M3 | 4116 | 79 | 12866 | 1.28 | 16/99 | 1 | 130 | 9/50 | 15408 | −2541 |
| donch_vortex M3 | 3181 | 79 | 9391 | 1.24 | 15/99 | 0 | 95 | 6/50 | 10068 | −676 |
| ut_bot M5 | 2802 | 82 | 11104 | 1.46 | 7/99 | 0 | 112 | 2/50 | 12105 | −1001 |
| donch_vortex M5 | 1644 | 82 | 7393 | 1.46 | 6/99 | 0 | 75 | 3/50 | 8212 | −819 |
| vortex_adx M3 | 2328 | 80 | 6906 | 1.29 | 6/99 | 0 | 70 | 2/50 | 8455 | −1548 |
| vortex_adx M5 | 1543 | 84 | 7926 | 1.74 | 2/99 | 0 | 80 | 1/50 | 8148 | −222 |
| psar_macd M5 | 886 | 83 | 5375 | 1.81 | 3/99 | 0 | 54 | 2/50 | 5100 | +275 |
| M15 (12 hücre) | — | 82–95 | 182–4054 | — | 0 | 0 | 5–41 | 0 | — | — |

M15'te hiçbir hücre hedefe değmedi (işlem sayısı az). Tam tablo `outputs/replay_strateji/ozet_tur1.json`.

## 4. Tur 2 — risk artırımı ve birleşik stratejiler

Lot, BALANCE × risk% ile sabit; gün P&L riskle lineer ölçeklenir (risk %r ≈ %20 koşusu × r/20).

**Tur 2a/2b (iki sembol, altın %20 / BTC %10 ve altın %30 / BTC %15):** ut_bot M5 %30/15: 41/99 hedef, 5 iflas, ort +341; ut_bot M3 %30/15: 40/99 hedef ama 21 iflas. BTC yine negatif.

**Tur 2d (yalnız altın, risk %20):**

| Hücre | İşlem | WR | PF | Net | 14h hedef/gün | iflas | ort | medyan | 7h hedef | 7h iflas |
|---|---|---|---|---|---|---|---|---|---|---|
| combo3 M5 | 2742 | 89 | 1.81 | 51059 | 33/83 | 1 | 615 | 408 | 18/42 | 1 |
| combo3 M3 | 4718 | 85 | 1.42 | 60725 | 44/83 | 8 | 732 | — | 18/42 | 5 |
| ut_bot M5 | 1446 | 89 | 1.73 | 24731 | 22/82 | 0 | 302 | 191 | 14/41 | 0 |
| ut_bot M3 | 2327 | 85 | 1.44 | 31399 | 34/83 | 5 | 378 | — | 16/42 | 1 |
| donch_vortex M5 | 986 | 88 | 1.69 | 16409 | 18/78 | 2 | 210 | — | 9/39 | 1 |
| combo3_onay M5 | 212 | 89 | 1.71 | 3503 | 1/71 | 0 | 49 | — | 0/37 | 0 |

Risk ölçekleme (combo3 M5, yalnız altın): %10 → hedef 26/83, iflas 0; %20 → 33/83, 1; %30 → 45/83, 4; %40 → 49/83, 6; %50 → 52/83, 7.

combo3 M5 ayrıntı: en kötü gün −736, en iyi +4532; en uzun ardışık negatif 3 gün; her hafta pozitif (haftalık +747 … +8208); ilk 7 hafta ort +565/gün, son 7 hafta +664/gün; lot 0.09–0.82 (medyan 0.33); maks. düşüş 1301; çıkışlar: BE 2175 (+52981), SL 307 (−62756), TRAIL 249 (+56500), TP 11.

## 5. Tur 3 — kayma stresi (yalnız altın, risk %20, `--slip-pips` bacak başına)

| Hücre | Kayma | PF | Net | 14h hedef/gün | iflas | ort | 7h hedef |
|---|---|---|---|---|---|---|---|
| combo3 M5 | 0 | 1.81 | 51059 | 33/83 | 1 | 615 | 18/42 |
| combo3 M5 | 2 pip | 1.09 | 6694 | 18/83 | 8 | 81 | 10/42 |
| combo3 M5 | 5 pip | 0.67 | −21947 | 3/83 | 16 | −264 | 1/42 |
| ut_bot M5 | 0 | 1.73 | 24731 | 22/82 | 0 | 302 | 14/41 |
| ut_bot M5 | 2 pip | 1.11 | 4525 | 14/82 | 4 | 55 | 9/41 |
| ut_bot M5 | 5 pip | 0.60 | −15701 | 6/81 | 6 | −194 | 2/41 |
| combo3 M3 | 2 pip | 0.83 | −18537 | 9/84 | 17 | −221 | 1/42 |
| combo3 M3 | 5 pip | 0.40 | −42636 | 1/84 | 28 | −508 | 0/42 |

Okuma: kâr, işlem başına ortalama +18 USD (0.33 lot ≈ 5 pip) büyüklüğündeki BE-kilidi kazançlarından geliyor. 2 pip kayma (0.20 USD, bacak başına) bu kenarın yarısını, 5 pip tamamını yiyor. Canlıda ölçülen altın spread'i 1 pip (0.10 USD); motor zaten 2.5 pip spread kesiyor. Gerçek piyasa emri + stop fill kayması altında 1–3 pip olağan; haber saatlerinde daha fazla. M3 hücreleri gerçekçi değil; M5 sınırda.

## 6. Diğer sınırlar

- Bar kapanışında fill, BE/stop sıralaması bar OHLC ile (motor muhafazakâr sırada: SL önce, sonra BE; ama bar içi gerçek yol bilinmiyor).
- Marj: %20 risk, 0.33 lot altın ≈ 130k USD nominal; 1000 USD kasada ancak 1:500 kaldıraçla ve tek pozisyonla taşınır; motor sembol başına 3 piramit açabiliyor → marj yetmeyebilir. Bu replay'de marj kontrolü yok.
- Komisyon yok. Altın 24 saat işlem (seans filtresi kapalı); kapanışların %40'ı 00–07 UTC arasında (Asya seansı, düşük likidite).
- Strateji seçimi: 36 hücre → ilk 3 → birleşim; test (son 7 hafta) ayrı okundu ve tutarlı, ama tek rejim (altın güçlü trend dönemi).
- Hedef kriteri bileşik defter (altın + BTC) yerine yalnız altın defterinde tutuldu; BTC için hiçbir strateji hedefe yaklaşmadı.

## 7. Yapılacaklar (sonraki adım)

1. Canlı demo hesapta 1 hafta: combo3 M5 yalnız altın, risk %5 (hedefsiz), gerçek fill/kayma ölçümü (`fx_spread_collector.py` tarzı) — kayma 2 pip altındaysa risk kademeli artırılır.
2. Motorda marj kontrolü ve kayma modeli (stop fill'de kayma, limit yok) eklenmeden risk %20+ sonuçlarına güvenilmemeli.
3. BTCUSD bu motor+bu stratejilerle terk edilmeli; farklı bir model gerekir.
