# PAYOFF GEOMETRİSİ TEŞHİSİ — "kötü sembol" değil, kötü TP/SL oranı (2026-11-12)

## 1) Belirti
Kanonik defterde (düzeltilmiş maliyet + gerçek UTC) **7 sembol iki pencerede de negatif**:

| Sembol | IS net | OOS net |
|---|---|---|
| USDCHF | −16.719 $ | −16.824 $ |
| GBPUSD | −7.848 | −5.513 |
| AUDUSD | −5.452 | −6.980 |
| USDJPY | −2.368 | −4.936 |
| AUDCAD | −2.543 | −2.265 |
| EURJPY | −998 | −1.053 |
| GBPJPY | −938 | −954 |
| *(pozitif)* XAUUSD / US30 / NAS100 | +102.216 / +8.604 / +6.524 | +87.799 / +6.730 / +5.290 |

Hariç tutma A/B'si (7 sembol çıkarıldı, iki pencere): **PF 1,20→1,84 · net 80.153→153.310 $ · DD 11.635→6.159** — 2× maliyette de geçiyor (PF 1,70 / 1,68).

## 2) Neden "blokla" DEĞİL
1. `blocked_symbols` alanının kendi belgesi: **2026-11-10'da tam bu 5 parite (USDJPY/USDCHF/GBPUSD) bloklanıp GERİ ALINDI** — negatifliğin kaynağı pariteler değil, artık işlem açmayan iki kanaldı (`Scalper MT5`, `FVG`). Kanal çıkınca aynı pariteler nötr/pozitife dönmüştü.
2. Kullanıcı kuralı: *"Bloklamak mı çözüm? Bloklama yerine kârlı sinyal üretmeye yoğunlaş."*
3. Hariç tutma sonrası defter **XAU + US30 + NAS100**'e iner → tek varlığa aşırı yoğunlaşma.

## 3) Gerçek kök neden: payoff oranı
Sembol bazında ortalama kazanç / ortalama kayıp (IS, kanonik defter):

| Sembol | n | isabet % | ort kazanç | ort kayıp | **R oranı** | BE için gereken isabet |
|---|---|---|---|---|---|---|
| XAUUSD | 922 | 89,4 | 243,9 | 1.008,0 | 0,24 | %80 → **geçiyor** |
| US30 | 717 | 87,3 | 25,7 | 82,3 | 0,31 | %76 → geçiyor |
| NAS100 | 709 | 88,3 | 19,7 | 70,0 | 0,28 | %78 → geçiyor |
| GBPUSD | 405 | 61,0 | 236,4 | 419,2 | 0,56 | %64 → **kalıyor** |
| USDCHF | 341 | 60,1 | 242,7 | 488,8 | 0,50 | %67 → kalıyor |
| AUDUSD | 358 | 64,2 | 200,8 | 403,4 | 0,50 | %66 → kalıyor |
| USDJPY | 372 | 66,7 | 151,6 | 322,3 | 0,47 | %68 → kalıyor |
| AUDCAD | 607 | 58,5 | 8,7 | 22,3 | 0,39 | %72 → kalıyor |
| EURJPY | 789 | 65,3 | 9,2 | 20,9 | 0,44 | %69 → kalıyor |
| GBPJPY | 794 | 67,4 | 8,0 | 20,2 | 0,40 | %71 → kalıyor |
| BTCUSD | 922 | 78,7 | 52,5 | 196,0 | 0,27 | %79 → sınırda |

**Okuma:** Yenenler kaybedenlerin **yarısından az**. Kazanan semboller bunu %87-89 isabetle
kapatıyor; FX pariteleri %58-67 isabetle kapatamıyor. Yani sorun sembolün kendisi değil,
**TP/SL oranı** — ve bu, `--rr-floor` ile doğrudan ayarlanabilir bir parametre.

## 4) Sıradaki ölçüm (koşuluyor)
`--rr-floor` 1,5 (bugünkü) vs **2,5** vs **4,0**, tam evren, iki pencere. Beklenti: payoff
oranı yükselir, isabet düşer; net etki ölçülecek. Sonuç olumluysa **geometri** düzeltilir
(bloklama değil) ve `geometry_shadow` (SL %0,9 / hedef ATR×4) ile bağımsız teyit edilir.

## 5) Dosyalar
`outputs/ab_{cur,prior}_cap.json` (kanonik baseline) · `outputs/blk_*.json` (hariç tutma) ·
`outputs/rr{25,40}_*.json` (rr_floor A/B)


## 6) rr_floor A/B SONUCU → canlı ayara alındı (2,5)

| Pencere | rr 1,5 (PF / net / DD) | rr 2,5 (PF / net / DD) |
|---|---|---|
| cur | 1,20 / 80.153 $ / 11.635 $ | **1,26 / 92.947 $ / 12.099 $** |
| prior | 1,18 / 62.016 $ / 11.635 $ | **1,24 / 75.458 $ / 12.099 $** |
| cur @2× maliyet | 1,16 / 64.395 $ / 15.467 $ | **1,19 / 70.172 $ / 13.393 $** |
| prior @2× maliyet | 1,13 / 44.975 $ / 15.467 $ | **1,16 / 53.845 $ / 13.393 $** |

**rr 4,0 = rr 2,5** (spec TP tavanı bağlıyor) → 2,5 seçildi. Dört ölçümün dördünde de daha iyi;
2× maliyette DD de düşüyor (15.467 → 13.393).

**Uygulama:** `ForexAutoPaperSettings.atr_exit_rr_floor = 2.5` (panelden değiştirilebilir,
geri alma 1.5). Canlı ATR çıkış motoru ve 21-AI aynı ayardan okuyor.
