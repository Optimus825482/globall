# GÖREV BRIEF'İ — "Trailing aktifken TP iptali"ni Binance TR (kripto) otonom işlemlerine uygula

> Bu metin başka bir proje (`scalperagent_v4` / Binance TR kripto uygulaması) oturumuna
> yapıştırılmak için yazıldı. İçeriği kendi başına yeterlidir; kaynak projeye erişim gerekmez.

## Nereden geliyor (kanıt)

`scalperagent_global` (forex/MT5) projesinde 2026-10-09'da çıkış mekanizmaları A/B test edildi
(izole defter, gerçek IC Markets spread, 4 bağımsız pencere). Bulgu:

**"Trailing devreye girince sabit TP emrini iptal et" (TP-cancel-on-trail) DÖRT pencerede de
net kazancı artırdı ve maxDD'yi düşürdü** → IS +$201 / OOS +$215 / OOS2 +$65 / F1 +$170.
ADX-rejimli dinamik trailing VE TP-ratchet pencereler arası **işaret değiştirdiği** için
reddedildi (tutarsız). Forex'te canlıya alındı (commit `1865667d`, varsayılan AÇIK,
`FOREX_TP_CANCEL_ON_TRAIL=false` ile geri alınır).

## ⚠️ BU PROJEDE ÖNCE BUNU OKU — çelişen kanıt var

Bu kripto projesinin otonom motoru `backend/app/routers/auto_paper.py` içinde bu mekanizma
**ZATEN BİR KEZ denendi ve BAŞARISIZ oldu**:
- **2026-09-18:** TP-cancel denendi → kârla kapanan işlem payı **%33'e düştü**, kâr **%93'e
  geriledi**, **%1.73 geri verildi**. Geri alındı.
- **2026-09-28:** yerine **TP-RATCHET** kondu (TP SİLİNMEZ; trailing TP'nin üstüne çıkınca TP
  yukarı kaydırılır). Kod yaklaşık `auto_paper.py:1101-1123`; kaynakta "TP ratchet" /
  "trailing TP'nin üstüne çıktı" ifadeleri geçer.

**Neden iki proje farklı sonuç veriyor olabilir:** forex'te kazanan işlem BE + kâr kilidi +
trailing üçlüsüyle korunuyordu; kripto o dönem çıkışı neredeyse tamamen trailing'e bırakıyordu.
Bağlamlar farklı. **SONUÇ: KÖR KOPYALAMA YOK — ÖNCE BU PROJEDE TEST ET.**

## Görev (kanıt-önce disiplini — `FX_KALIBRASYON_PLANI.md` ruhu)

1. **Anla:** `backend/app/routers/auto_paper.py` çıkış fonksiyonunu (TP-ratchet ~1101-1123,
   trailing/BE blokları, TP-primary dalı) ve `backend/app/config.py` ilgili ayarlarını oku:
   `AUTO_PAPER_TP_PRIMARY_ENABLED`, `AUTO_PAPER_BREAKEVEN_*`, `AUTO_PAPER_TRAILING_*`.
   Şu anki davranış: TP PRIMARY çıkış + trailing aktifken **ratchet**. 

2. **Ölç:** Bu projede kripto için replay/backtest harness'i var mı bul (yoksa en azından
   gerçek kapanmış işlem kaydından MFE/give-back ölç). Bir **A/B** kur:
   - A: mevcut (TP-ratchet) — referans
   - B: TP-cancel-on-trail (trailing aktifleşince TP silinir)
   Aynı girişler, izole defter, gerçek maliyet, **birden çok ayrık pencere**. Tek pencereye
   bakıp karar verme (forex'te tam bu hata ADX-trail'i yanlış kazandı gösterdi).

3. **Karar kuralı (sonuçtan ÖNCE yaz):**
   - B, en az **3 bağımsız pencerede** A'yı geçiyorsa VE işaret-tutarlıysa → uygula.
   - B pencereler arası işaret değiştiriyorsa VEYA give-back artıyorsa → **DOKUNMA**, ratchet
     kalsın; nedeni yorumda belgele (2026-09-18 başarısızlığının tekrarı olmasın).

4. **Uygula (yalnız 3. adım geçerse):** forex'teki deseni ayna:
   - `ForexAutoPaperSettings` muadili ayar modeline `tp_cancel_on_trail: bool` ekle — env-güdümlü
     varsayılan (bu projede muhafazakâr: `false` öner; en azından opt-in).
   - Çıkış döngüsünde trailing aktifleştiği anda `tp_price`'ı 0/None yap (TP-primary dalı bir daha
     ateşlemesin).
   - **KRİTİK İNCELİK:** TP bir kez iptal edilince, sonraki BE/trailing güncellemeleri TP'yi
     **geri diriltmemeli**. Forex'te bunu tek bir komut-üretici fonksiyondan geçirerek çözdük
     (`_build_modify_sltp_cmd`). Burada da TP yazımını tek yoldan geçir.
   - Ayarlar UI'ında toggle + `Ayarlar` payload'ında alan aç (forex'te olduğu gibi).

5. **Bildir:** Sonucu (A vs B, pencere tablosu) ve kararını yaz. Kazanmadıysa "eklenmedi, şu
   yüzden" demek de geçerli bir sonuçtur.

## Forex'teki referans implementasyon (bakılacak şekil)

- Ayar: `backend/app/routers/forex.py` → `ForexAutoPaperSettings.tp_cancel_on_trail`
  + modül düzeyi `FOREX_TP_CANCEL_ON_TRAIL_DEFAULT` (env).
- Çıkış döngüsü: trailing bloğundan sonra `if updated_trail and tp_cancel_on_trail and tp>0:
  pos["tp_price"]=0.0`.
- Köprü/emir: `_build_modify_sltp_cmd()` — iptal edilen TP'yi BE komutunun geri diriltmesini
  engeller. (Bu projede MT5 köprüsü yok; kripto tarafında TP emri mantığı farklı olabilir.)

## Notlar
- Forex kanıtı: `scalperagent_global/outputs/exit_sweep/FINDINGS.md` + `PREREG_V18_F1.md`
  (o repoda, `outputs/` gitignored).
- Bu projedeki mevcut ratchet kanıtı: `auto_paper.py:1101-1123` yorumları.
