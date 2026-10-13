# Yeni Kârlı Strateji Araştırması — Top-5 Kısa Backtest + Replay (2026-10-13)

**İstek:** "Pariteler ve BTC ile ilgili kârlı işlem stratejileri araştır; en iyi gördüğün ilk 5'i
önce kısa backtest yap, olumlu olanları replay testi yap."

**Yöntem:** Repo'nun 3 dalga web-araştırması + tüm replay kanıtı tarandı (22+ araştırma kolu,
~150+ konfigürasyon). Aynı işi tekrarlamamak için **yalnız eleme listesinde OLMAYAN, ayakta kalan
tek aileye (trend/kırılım + seans-zamanı)** dayanan 5 aday seçildi. Kısa backtest = iki bağımsız
pencere; olumlu olanların derin replay'i = slipaj-şoku + 3. pencere + defter-katkısı.

Araç: `scripts/forex_replay_backtest.py` · Cache: `outputs/replay_cache_60d_fxwide.json`
(34 sembol, 5m, 2026-07-29→10-07) · Gerçek spread: `outputs/fx_spread_reality.json`.

---

## 0. Kanıt tabanı (neden bu 5 aday)

**Kesin eleme listesi (tekrar denenmedi):** mean-reversion/BB-fade (PF 0.21), stat-arb
(kointegrasyon p=0.17), ICT/order-block (5.242 işlem $10k→$571), ML (OOS IC +0.004, 0/42 DSR),
haber-drift, CVD (R²=0.031), DXY-lead, 5m squeeze (TTM PF 0.18), filtresiz ORB/Asya-fade (%49.4),
hafta-sonu gap (−$1.308/5y), **BTC HF scalping (0/90)**, **BTC momentum (12.288 kombinasyon,
blok-bootstrap p=0.17-0.27)**, kros genişletme (13/13).

**Ayakta kalan tek aile:** trend/kırılım + **seans-zamanı (time-of-day)**. Yeni kanıt:
- **London Sign** (NY-açılışı sign-momentum, Seeck 2026) — 2026-10-13'te canlıya alındı, XAU+US30.
- **BTC saat-08:00 UTC seans drifti** — 60g PF 1.57, t=+3.11, komşu saatler zarar.

**Denenmemiş boşluklar** (bu 5 aday buradan seçildi): Bollinger band-walk (rejim-kırılım, hiç
test edilmemiş), NR7/Crabel volatilite-kırılımı (kayıtlı mod, canlıda yok), Donchian+H1-EMA200
kapısı **güncel birleşim-BE düzeltmesiyle** yeniden, sign-momentum BTC'de (aile kanıtlı ama BTC'de
kapsam dışı bırakılmış), Supertrend+RSI US30 (kayıtlı mod, US30'da canlı değil).

---

## 1. Top-5 aday + kısa backtest (iki bağımsız pencere)

Pencereler: **W2 (IS) 2026-08-01→09-07** · **W1 (OOS) 2026-09-07→10-07**. (Bar: her iki pencerede
net>0 · işaret-tutarlı.)

| # | Aday | Kural | Kapsam | W2 (IS) | W1 (OOS) | Kısa-vade |
|---|---|---|---|---|---|---|
| A1 | **Bollinger band-walk** | üst/alt bantta ≥3 temas → bant-yürüyüşü devamı | XAUUSD | n10 +51.14 PF 6.22 | n3 +12.96 | ⚠ örneklem çok az |
| A2 | **NR7 (Crabel)** | son 7 barın en dar aralığının kırılımı | XAUUSD | **n93 +328.84** PF 4.07 WR 93.5 | **n80 +211.44** PF 3.14 WR 92.5 | ✅ güçlü |
| A3 | **Donchian+ADX+H1 EMA200** | Donchian kırılımı, ADX≥18, H1 EMA200 yön kapısı | GBPJPY,EURJPY | **n99 +46.38** PF 1.35 | **n85 +25.15** PF 1.21 | ✅ ölçülü |
| A4 | **London Sign** | sign-momentum (13:30→14:30 UTC) | BTCUSD | n28 −3.46 PF 0.89 | n30 +25.02 PF 2.05 | ❌ işaret dönüyor |
| A5 | **Supertrend+RSI** | ST yönü + RSI pullback bandı | US30 | n19 −25.68 PF 0.51 | n8 +10.78 PF 999 | ❌ işaret dönüyor |

**Kısa backtest sonucu:** A4 ve A5 işaret değiştirdiği için **elendi** (genellenmemiş katman).
A1 örneklem yetersiz. **A2 ve A3 replay'e kaldı.**

---

## 2. Derin replay (olumlu olanlar: A2, A3)

### A2 — NR7 / XAUUSD

| Test | n | WR% | net$ | PF | DD$ |
|---|---:|---:|---:|---:|---:|
| W2 (IS) | 93 | 93.5 | +328.84 | 4.07 | 42.9 |
| W1 (OOS) | 80 | 92.5 | +211.44 | 3.14 | 28.7 |
| W3 (15/07→15/08, 3. pencere) | 45 | 91.1 | +219.70 | 4.37 | 42.9 |
| W1 **slip 2p/bacak** | 80 | 91.2 | **+79.04** | 1.51 | 57.4 |
| W2 slip 2p/bacak | 93 | 92.5 | +257.94 | 3.02 | 53.2 |

Tek başına **üç pencerede de pozitif ve maliyet-şokuna dayanıklı** — yönetişim barının çoğunu geçer.

**Genelleşme (XAU+US30+NAS100, 08-01→10-07):** n282 +604.71 PF 2.19 → US30 +$64.43 (109 işlem),
NAS100 ~0 (hiç işlem). Yani edge metal/endekse taşınıyor.

**⚠ Kırılganlık — BE artefaktı testi:** BE kapatılınca NR7 çöküyor (WR %6.6 OOS / %10.6 IS,
DD $903–2502). Yani NR7'nin kârı büyük ölçüde **mevcut birleşim-BE yapısından** geliyor; çıplak
kırılım kenarı zayıf.

### A2 — KİLİT test: canlı deftere katkı (yönetişim barı #6)

NR7'yi XAU'da klasik motorun **yerine** koyduğumuzda (mode-symbols, 9 sembollük canlı defter):

| Defter | n | WR% | net$ | PF | DD$ |
|---|---:|---:|---:|---:|---:|
| **KLASİK** OOS | 7318 | 64.9 | **+1933.01** | 1.17 | 289.7 |
| **NR7@XAU** OOS | 5900 | 58.5 | **−177.11** | 0.98 | 406.0 |
| KLASİK IS | 6675 | 67.3 | +4000.21 | 1.36 | 165.4 |
| NR7@XAU IS | 5123 | 59.3 | +701.01 | 1.10 | 306.9 |

Klasik motor XAU'da zaten **+$2379 / 1846 işlem** (OOS) üretiyor; NR7 aynı sembolde **+$220 / 70
işlem**. NR7, klasik'in kârlı işlemlerinin **seyrek bir alt kümesidir** — kapsayıcı değil, yerini
alınca **defter netini −$2110 düşürüyor.**

**Verdict: A2 RED.** Tek başına güçlü ama **klasik XAU'ya göre baskın-değil (dominated)** ve
deftere ek katkı sağlamıyor. Yönetişim barı #6 başarısız.

### A3 — Donchian+ADX+H1 EMA200 / GBPJPY+EURJPY

| Test | n | WR% | net$ | PF | DD$ |
|---|---:|---:|---:|---:|---:|
| W2 (IS) | 99 | 58.6 | +46.38 | 1.35 | 55.9 |
| W1 (OOS) | 85 | 70.6 | +25.15 | 1.21 | 44.4 |
| W1 **slip 2p** | 81 | 69.1 | **−38.65** | 0.75 | 83.2 |
| W2 **slip 2p** | 90 | 53.3 | **−71.95** | 0.62 | 158.1 |

**Verdict: A3 RED.** Gerçek maliyet-şoku altında her iki pencere de negatife dönüyor (PF 0.62-0.75).
Bu, 2026-10-08'deki aynı bulgunun bağımsız teyidi (jp_dp_h1 pencere-bağımlı).

---

## 3. Nihai karar

| Aday | Kısa backtest | Derin replay | Karar | Neden |
|---|---|---|---|---|
| A1 Bollinger band-walk XAU | ⚠ düşük n | — | **RED** | n=3-10, istatistiksel anlamsız |
| A2 NR7 XAU | ✅ | ✅ tekil / ❌ defter | **RED** | Klasik XAU'ya baskın-değil; defteri −$2110 düşürüyor |
| A3 Donchian+H1 JPY | ✅ | ❌ maliyet | **RED** | slip 2p'de iki pencere de negatif |
| A4 London Sign BTC | ❌ işaret | — | **RED** | W2/W1 işaret dönüyor; önceki bulguyla tutarlı |
| A5 Supertrend+RSI US30 | ❌ işaret | — | **RED** | W2/W1 işaret dönüyor |

**Hiçbir yeni aday canlıya-alım barajını geçemedi.** Canlı politika değişmedi. Bu, projenin
tekrarlayan bulgusunun dördüncü bağımsız teyididir: **XAU/BTC/endeks dışındaki FX'te ve BTC'nin
kendisinde, maliyet-sonrası tutarlı yeni bir yön edge'i yok.** Mevcut klasik motor (XAU'da PF
1.65-1.83) ve London Sign (XAU+US30, seans-momentum) hâlâ en iyi iki dayanaktır.

## 4. Dürüst notlar / sınırlar

1. **Replay canlıya vekil değil** (bkz. `FX_BE_TETIK_BIRLESIM` §"Açık kalan"): MT5 tick
   gecikme/slipajı ve kısmi-TP + BE + chandelier etkileşimi modellenmiyor; replay iyimserdir.
2. **A2'nin gerçek sınavı (additive arm olarak) koşulamadı** — replay harness'ın `--mode-symbols`
   semantiği "yerine koy"dur, "yanına ekle" değil; `--combined` yalnız S3/LB/EAP/Donchian kollarını
   taşır. Ancak klasik XAU'nun +$2379'una karşı NR7'nin +$220'si ve 70≪1846 işlem, NR7'nin
   klasik'in alt kümesi olduğunu **güçlü biçimde** gösterir → ek katkı ~0.
3. **Örneklem:** A1 n=3-10, A4/A5 n=8-30 → bu adaylarda kısa pencere yalnız **eleme** içindi (onay
   için değil), eleme için yeterliydi.
4. **Kod maliyeti:** Bu turda giriş-modlarının **hepsi zaten** replay motorunda kayıtlıydı
   (`bb_bandwalk`, `nr7`, `donchian_adx`, `london_sign`, `supertrend_rsi`) — yeni kod yazılmadı.

## 5. Bir sonraki adım önerisi (kanıta dayalı)

Kalan tek gerçek boşluk: **non-FX enstrümanlarda (XAU/US30/NAS100) seans-açılışı kırılımı** —
London Sign bunun ilk kanıtlı örneği. Sıradaki mantıklı deney: **aynı sign-momentum iskeletini
farklı seans pencerelerinde** (Asya açılışı, 16:00 UTC fade) ve **XAGUSD/USTEC**'te test etmek;
ayrıca London Sign'ı US30 dışına (USTEC) genişletmenin defteri bozup bozmadığını ölçmek. Aile
kanıtlı, kapsam açık.

---

**Artefaktlar:** `outputs/t5_*.json` (tüm koşum çıktıları).
