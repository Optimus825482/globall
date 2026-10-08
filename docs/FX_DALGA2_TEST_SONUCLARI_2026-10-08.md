# FX Dalga-2 Adayları — Çoklu-Pencere Test Sonuçları ve Karar

**Tarih:** 2026-10-08
**Talimat:** "Kodlamaya değer 6 adaya sırayla başla; testleri yine maksimum sayıda subagent ile
multiparalel orkestrasyonla yap."
**Yöntem:** 6 aday replay motoruna giriş-modu olarak kodlandı → **11 paralel subagent** ile
5 ayrı pencere/koşul matrisi (kısa tarama Ağu-10/31, Ağustos tam, 30g OOS Eyl-7→Eki-7, 60g tam,
2× spread stress) koşuldu. Toplam **~40 konfig-koşusu.**

---

## 1. TL;DR — Karar

**Hiçbir aday plan §8 canlıya-alım barajını (≥2 ayrık pencerede pozitif + OOS>0 + 2× spread'te
pozitif + ≥100 işlem) tam geçemedi.** Ama **üç aday artık "ölü değil, izlemeye değer" bandında**:

| Aday | Pozitif pencere | Ortalama net | Karar |
|---|---|---|---|
| **jp_dp_h1_v2** (JPY Donchian+H1) | **4/5** | +$55…+$143 | **PAPER-İZLEME** (en güçlü) |
| **sqx_eur** (EURUSD sıkışma-genişleme) | **4/5** | +$2…+$9 | **PAPER-İZLEME** (küçük ama tutarlı) |
| **reopen_eur_g2** (EURUSD gap-fade, ≥2p) | **5/5** | +$0.3…+$2 | İZLE (örneklem çok küçük, n=4-7) |
| orb15_gbp (GBPUSD filtreli ORB) | 2/5 | −$53…+$41 | RED (pencereye bağımlı) |
| orb15_eur | 0/5 | hep negatif | **RED** |
| tod_base (EURUSD saat-günü) | 2/5 | −$12…+$7.5 | **RED** (lineer kanıta rağmen bu veride tutarsız) |
| tfix_uj_w10 | 2/3 | −$19…+$14 | RED (7 Eyl-Eki'de çöktü) |

---

## 2. Kodlanan Modlar (`scripts/forex_replay_backtest.py`, uncommitted)

| Mod | Kural | Exit |
|---|---|---|
| `eurusd_tod` | EURUSD: EUR saatleri (07-11 UTC) SHORT / USD saatleri (12-16) LONG, günde 1 | SL 1.5×ATR / TP 3×ATR |
| `orb_filtered` | London/NY açılış 15dk kutu; OR/ADR∈[0.05,0.25]; ADR≥25p; gövde-kapanış + 20-bar trend | SL=kutu, TP=1.5R, **time-exit 4h** |
| `squeeze_exp` | ATR% ve BBW alt %20 + genişleme barı (gövde üst/alt 1/3) + H1 trend yönü | SL 1.5×ATR / TP 3×ATR |
| `reopen_fade` | Broker günü ilk saat, ≥min-gap fade, spread-filtreli | SL=TP=1.2×ATR, **time-exit 1h** |
| `tokyo_fix` | USDJPY 00:55 UTC: fix öncesi short, sonrası long | SL 1×ATR / TP 1.5×ATR, **time-exit = pencere** |

**Kritik teknik düzeltmeler bu turda:**
- **Majör seans kapısı muafiyeti:** Dalga-2 modları kendi saat penceresini taşıdığından
  (Tokyo 00:55, reopen 00:00, TOD saat-blokları) majör 07-20 UTC kapısı onları buduyordu →
  `_mode_own_clock` muafiyeti eklendi (yoksa 3 mod 0 işlem veriyordu).
- **ORB eşik yeniden kalibrasyonu:** araştırmanın OR/ADR [0.25,0.60] bandı 24 saatlik ADR
  içindi; Yahoo 5m verisinde gün-içi ADR sıkışık (EURUSD OR/ADR med ~0.10) → eşik [0.05,0.25]'e
  çekildi; aksi halde ORB **0 işlem** üretiyordu.
- **Time-stop altyapısı:** `SimPos.time_stop_bars` + `manage_book` "TIME" çıkışı eklendi
  (araştırma: range-expansion'da sabit zaman-çıkışı trailing'den iyi).

---

## 3. Kanıt — 5 Pencere × Aday Matrisi

| CONFIG | Ağu10-31 | Ağustos | Eyl7-Eki7 (OOS) | 60g tam | 2× spread Sep | Pozitif |
|---|---:|---:|---:|---:|---:|---:|
| **jp_dp_h1_v2** | −31.2 (54) | **+54.0** (70) | **+142.7** (76) | **+54.9** (102) | **+102.6** (76) | **4/5** |
| jp_da_h1_v2 | −32.4 (58) | +54.4 (78) | +26.9 (85) | — | — | 2/3 |
| orb15_gbp | 0 (0) | −53.4 (77) | +40.9 (77) | −55.0 (80) | +36.4 (76) | 2/5 |
| orb15_eur | 0 (0) | −2.7 (102) | −32.5 (127) | −27.9 (150) | −39.6 (127) | 0/5 |
| **sqx_eur** | −3.7 (16) | **+2.5** (23) | **+6.2** (30) | **+9.3** (34) | **+5.8** (30) | **4/5** |
| **sqx_pct10** | −1.4 (11) | **+3.5** (16) | +1.6 (21) | +3.3 (22) | +1.3 (21) | **4/5** |
| tod_base | −0.5 (20) | −12.4 (28) | +7.5 (27) | −10.2 (40) | +7.1 (27) | 2/5 |
| reopen_eur | +1.3 (8) | +1.0 (12) | −1.3 (17) | +2.0 (18) | −1.6 (17) | 3/5 |
| **reopen_eur_g2** | +0.35 (4) | +1.3 (6) | +0.4 (5) | +2.0 (7) | +0.3 (5) | **5/5** |
| tfix_uj_w10 | +4.7 (20) | +14.0 (26) | −19.2 (25) | — | — | 2/3 |

**Referans (klasik motor):** `classic_is` her pencerede **−$1.600…−$4.635** (PF 0.64-0.72);
`jp_classic` (JPY krosları klasik) −$217…−$785. Yani **tüm adaylar klasikten 10-40× iyi**, ama
mutlak kâr barajı hâlâ sınırda.

**Kill-gate değerlendirmesi:**
- **jp_dp_h1_v2:** 4/5 pozitif, 2× spread'te pozitif kalıyor (+$103, PF 1.92 → kurşun geçirmez
  maliyet marjı), 60g'de n=102 (baraj sınırında). **Zayıf taraf:** 10-31 Ağu penceresinde −$31
  (tek negatif) ve DD 60g'de $110 (baraj $200 altı, geçer).
- **sqx_eur:** 4/5 pozitif, 2× spread'te korunuyor, ama işlem sayısı düşük (n=16-34) ve
  mutlak kâr küçük (+$2…+$9). Örneklem barajı (≥100) geçmiyor.
- **reopen_eur_g2:** 5/5 pozitif ama n=4-7 → **istatistiksel olarak anlamsız** (WFE hesabı yapılamaz).

---

## 4. Belirleyici Bulgular

1. **H1 EMA200 trend kapısı en güçlü ve en tutarlı iyileştirme** — `jp_dp_h1_v2` 4/5 pencerede
   pozitif, 2× spread'te bile PF 1.92. Araştırmanın "MTF kapısı DD/PF iyileştirir" öngörüsü
   burada en net doğrulandı. **Ama** 10-31 Ağu penceresinde negatif — yani pencere-bağımlılık
   tam ölmüş değil.
2. **Sıkışma-genişleme (squeeze_exp) EURUSD'de tutarlı küçük-pozitif** — JPY krosunda (sqx_gj)
   ise negatif (−$28). Sıkışma yön vermez ama EURUSD'de yön+trend kombinasyonu hafif edge veriyor.
3. **Filtreli ORB GBPUSD'de pencereye bağımlı** (+$41 / −$53 / −$55 / +$36) → araştırmanın
   "ORB coin-flip, filtreli versiyon sınırda" sonucuyla uyumlu. **RED.**
4. **EURUSD saat-günü sezonsallığı bu veride tutarsız** (−$12…+$7.5) — literatürün en güçlü
   kanıtı olmasına rağmen 5m replay'de net edge çıkmadı (muhtemelen 16.8 saatlik gün + spread
   filtresi literatürün 24-saat yapısını bozuyor). **RED.**
5. **Tokyo fix 7 Eyl-Eki'de çöktü** (−$19) — ay-sonu/gotobi bağımlı, örneklem 25 işlem. **RED.**
6. **2× spread stress:** tüm pozitif adaylar pozitif kaldı (maliyet marjı var), ama net kârlar
   küçük olduğundan marj yüzdesi dar.

---

## 5. Öneriler

**Kısa vade (canlı politika): DEĞİŞİKLİK YOK.** Mevcut 4'lü kapsam (XAU, BTC, GBPJPY, EURJPY)
+ JPY'de Donchian korunur. Yeni 5 mod canlı koda taşınmadı (barajı geçemediler).

**Orta vade — paper-izleme adayları (gerçek para yok):**
1. **jp_dp_h1_v2** — canlı gölge-defterde izle (motor zaten gölge tutuyor). 2-3 hafta daha
   veri birikince n>100 ve 5+ pencere netleşir; o zaman canlı MT5'e alma kararı.
2. **sqx_eur** — EURUSD'de tutarlı küçük-pozitif; yine paper-gözlem, örneklem büyüsün.

**Kesin RED (bu tur):** orb15_eur, tod_base, tfix_uj, orb15_gbp (pencere-bağımlı),
orb15_band, sqx_gj.

**Metodoloji kilidi:** Her FX adayı ≥5 pencere + ≥100 işlem + 2× spread + pozitif-pencere ≥4/5
barajını geçmeden "aday" sayılmasın. Bu turda sadece jp_dp_h1_v2 bu profile yaklaştı.

---

## 6. Artefaktlar

- Motor: `scripts/forex_replay_backtest.py` (5 yeni mod + time-stop + kapı muafiyetleri)
- Orkestratör: `scripts/fx_entrymode_sweep.py` (22 Dalga-2 config + `--spread-2x` stress)
- Sonuçlar: `outputs/fxsweep/*_{scr,aug,30,30s2x,60full,r30G}*.json` + `_consistency.py` tablosu
- 2× spread profili: `outputs/fx_spread_p95_2x.json`
