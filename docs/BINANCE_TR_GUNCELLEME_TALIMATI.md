# BINANCE TR UYGULAMASI İÇİN GÜNCELLEME VE ENTEGRASYON TALİMATI

**Tarih:** 2026-09-29  
**Hedef Repo:** Binance TR Scalper Agent  
**Kaynak Repo:** Scalper Agent Global (`d:\scalperagent_global`)  
**Amaç:** Global'de 105 gerçek işlem ve geriye dönük analizle kanıtlanmış kârlılık çıkış düzeltmelerini, kâr koruma bekleme süresini (Post-Win Cooldown), LLM İkinci Göz kapısını ve Raporlar karşılaştırma ekranını Binance TR sistemine birebir aktarmak.

---

## 1. YENİ OTURUMDA AJANA VERİLECEK TALİMAT (KOPYALA - YAPIŞTIR)

```markdown
Aşağıdaki güncellemeleri Binance TR uygulamamıza uygula:

1. AUTO PAPER ÇIKIŞ KÂRLILIK VE RATCHET DÜZELTMESİ (auto_paper.py):
   - Trailing stop devreye girdiğinde Take-Profit (TP) hedefinin silinmesini (take_profit = None) KALDIR.
   - TP silinmeyecek; trailing stop ile TP birlikte çalışacak. Fiyat TP'ye ulaşırsa işlem garanti kârla kapatılacak.
   - Trailing stop TP seviyesini aşarsa TP yukarı doğru ratchet edilecek (yükseltilecek).
   - _update_existing_trade fonksiyonunda trailing aktifken yeni gelen sinyallerin TP'yi yukarı güncellemesine izin verilecek.
   - try_open_from_notification içine fail-closed olarak block_reason ve master_surge_passed kontrolü eklenecek.

2. KÂR KORUMA (POST-WIN COOLDOWN) VE REOPEN ENGELİ (auto_paper.py & config.py):
   - AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE = false yap (koruma kapanışı sonrası hemen yeniden açma kapatıldı; aynı sembole tepeden tekrar girip kârı geri verme tuzağı elendi).
   - AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES = 15.0 ekle (kârlı kapanış veya TP/trailing/breakeven sonrası 15 dakika boyunca aynı sembole yeni pozisyon açılmasını engelle; -79.40 TRY kâr erimesi önlendi).
   - database.py içine get_last_auto_paper_winning_trade_time fonksiyonunu ekle ve try_open_from_notification içinde DB fallback'li post_win_cooldown kontrolü uygula.
   - reset_state() içine _post_win_cooldowns.clear() ekle.

3. LLM İKİNCİ GÖZ SİNYAL HAKEMLİK KAPISI (auto_paper.py):
   - try_open_from_notification içine LLM Sinyal Kapısı ekle:
     * Bildirimde llm_verdict in ("FAKE", "TUZAK") ve llm_confidence >= 50 ise işlemi ENGELLE (+22.59 TRY sahte kırılım zararı önlendi).
     * llm_verdict == "DEVAM" ancak llm_confidence < 60 ise (özellikle %50 varsayılan kararsız sinyaller) işlemi ENGELLE.
     * Bu kurallar settings'ten yönetilebilir olsun (llm_gate_enabled, llm_min_confidence).

4. PARAMETRE KALİBRASYONU (config.py):
   - AUTO_PAPER_BREAKEVEN_TRIGGER_PCT varsayılanı %2.5'ten %1.0'a çekilecek (erken zarar koruması).
   - AUTO_PAPER_TRAILING_GAP_PCT varsayılanı %1.0'dan %0.6'ya optimize edilecek (kâr koruma).

5. 4 ÖZEL LLM BECERİSİNİN (SKILLS) EKLENMESİ:
   - .agents/skills/ dizini altına şu 4 beceriyi ekle:
     * signal-arbiter-expert (CVD, emir defteri dengesizliği, boğa tuzağı dedektörü)
     * dynamic-exit-architect (ATR bazlı nefes alma payı, dinamik TP ve kâr takip)
     * market-regime-classifier (Trend vs Range vs Panik rejim teşhisi)
     * hard-guardrail-risk (Çelik risk sınırları, asla stopsuz kalmama kuralı)
   - app/llm_second_eye.py içindeki prompt ve bildirim yapısını bu 4 beceriye (regime, suggested_tp_pct, suggested_sl_pct) göre zenginleştir.

6. RAPORLAR SAYFASINA "KURAL VS LLM" PANELİ VE CSV AKTARIMI:
   - database.py içine get_llm_vs_rules_comparison fonksiyonunu ekle (Otonom işlemler ile LLM Second Eye kararlarını eşleştirip LLM_WIN, LLM_SAVED, LLM_LOSS analitiği üreten fonksiyon).
   - reports.py içine GET /api/reports/llm-vs-rules ve GET /api/reports/llm-vs-rules/csv uçlarını ekle.
   - frontend/app/reports/LlmVsRulesTab.tsx bileşenini oluştur (4 KPI kartı, filtre butonları, detaylı karşılaştırma tablosu ve tek tıkla Excel uyumlu CSV indirme butonu).
   - frontend/app/reports/page.tsx içindeki sekme çubuğunu yatay scrollbar çıkarmayan buton ızgarasına (grid-cols) dönüştür ve 🤖 Kural vs LLM sekmesini ekle.

7. DOĞRULAMA VE TESTLER:
   - pytest ile test_auto_paper, test_combined_radar, test_llm_second_eye ve test_llm_vs_rules_report testlerini çalıştır.
   - frontend tarafında npm run typecheck çalıştırarak 0 hata ile derlendiğini doğrula.
```

---

## 2. DEĞİŞEN DOSYALARIN LİSTESİ VE AYRINTILARI

### Backend Dosyaları:
1. `backend/app/routers/auto_paper.py`:
   - TP silme kodunun kaldırılması, TP ratchet eklenmesi.
   - Trailing aktifken yukarı yönlü TP güncellemelerine izin verilmesi.
   - `_close_trade` içinde `reopen_after_protect_close` şartına bağlama ve `_post_win_cooldowns` kaydı.
   - `try_open_from_notification` içinde `post_win_cooldown` ve `llm_fake_blocked` / `llm_low_confidence` kapıları.
   - `reset_state()` içinde `_post_win_cooldowns.clear()`.
   - `get_default_settings` ve `update_settings_endpoint` içinde yeni ayarlar.
2. `backend/app/config.py`:
   - `AUTO_PAPER_BREAKEVEN_TRIGGER_PCT = 1.0`
   - `AUTO_PAPER_TRAILING_GAP_PCT = 0.6`
   - `AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE = False`
   - `AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES = 15.0`
3. `backend/app/database.py`:
   - `get_last_auto_paper_winning_trade_time(symbol)` fonksiyonu.
   - `get_llm_vs_rules_comparison(day)` fonksiyonu.
4. `backend/app/llm_second_eye.py`:
   - Prompt'a 4 becerinin kurallarının eklenmesi.
   - `parse_verdict` içine `regime`, `suggested_tp_pct`, `suggested_sl_pct` eklenmesi.
   - `build_verdict_notification` içine zenginleştirilmiş bildirim formatı.
5. `backend/app/routers/reports.py`:
   - `/api/reports/llm-vs-rules` ve `/api/reports/llm-vs-rules/csv` endpoint'leri.

### Frontend Dosyaları:
1. `frontend/app/reports/LlmVsRulesTab.tsx`:
   - Karşılaştırmalı rapor bileşeni.
2. `frontend/app/reports/page.tsx`:
   - `LlmVsRulesTab` sekme entegrasyonu ve responsive grid buton bar tasarımı.

### Skill Dosyaları (`.agents/skills/`):
1. `signal-arbiter-expert/SKILL.md`
2. `dynamic-exit-architect/SKILL.md`
3. `market-regime-classifier/SKILL.md`
4. `hard-guardrail-risk/SKILL.md`
