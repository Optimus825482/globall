# CON DOR İNCELEMESİ — bu sisteme ne eklenir? (2026-11-10)

**Repo:** https://github.com/hummingbot/condor · **MIT** · ★257 · Python · son push **2026-11-06** (aktif)
**Kendi tanımı:** "An open source harness for creating and managing AI trading agents"
**Mimari (kaynaktan doğrulandı):** Telegram/web kontrol düzlemi → Hummingbot API.
`agents/<rol>/` (AGENT.md + controllers/ + loops/ + skills/) · `routines/` (one-shot/continuous analiz işleri) ·
`mcp_servers/` (tipli MCP araçları + `TOOL_STYLE.md`) · `condor/runtime/` (**danger.py** tehlike kapısı,
**code_guard.py**, confirmations.py) · `condor/backtesting.py` + `backtest_store.py` · `handlers/` (Telegram).

Bizim yığın farklı (MT5 köprüsü + FastAPI + Next.js + PostgreSQL, Python 3.12, numpy/sklearn).
Aşağıdakiler **taşınabilir fikirler**, kütüphane olarak import edilmez.

---

## P1 — Hemen alınmalı (ucuz, güvenlik/ölçüm değeri yüksek)

### 1) `danger.py` — araç çağrısı tehlike kapısı
**Ne yapıyor:** Yıkıcı araçları **İSİMDEN** sınıflandırır (`CREATE_EXECUTOR_TOOLS`, `LEVERAGE_TOOL`,
`DANGEROUS_TOOLS`), insan onayı bekleyen çağrıları işaretler, onay isteminde çağrıyı özetler. Dosya
**bilinçli olarak stdlib-only** — çünkü tehlike listesi/risk kapısı/onay özeti her yerden import ediyor;
runtime'a geri import kenarı büyümesin.
**Bizde eksik olan:** LLM sohbeti eylem tetikleyebiliyor (`/api/llm-chat` araçları, `scheduled_actions`,
pozisyon kapatma). Şu an **isimle sınıflandırma + onay kapısı yok**; `llm_tool_logs` sadece kayıt tutuyor.
**Uygulama:** `app/llm_danger.py` — stdlib-only, `{tool_name: {class: read|write|dangerous, requires_confirm: bool}}`,
tek çağrı noktası `llm_analysis.chat(tools=...)` + chat action handler. Onay akışı panelde (mevcut
`confirm` mekanizması yoksa tek adımlı "onay iste" + TTL).
**Kabul testi:** `execute_*`/`close_all` benzeri isim onay istemeden geçemez; bilinmeyen isim `write`
sınıfına düşer (fail-closed); stdlib-only olduğu bir kilit testiyle doğrulanır.

### 2) `AGENT.md` — ajan sözleşmesi (frontmatter + kapsam sınırı)
**Ne yapıyor:** Her uzman ajan bir Markdown sözleşmesiyle tanımlı: frontmatter'da
`name · description · tools · when_to_consult · server_required`, gövdede **"You handle" / "You do NOT handle"**
(→ yönlendirme kuralı) ve alan kuralları (örn. controller'da `signal` sözleşmesi).
**Bizde:** `llm_skills` + `.agents/skills/*` serbest metin; **ne zaman hangi uzmana gidileceği** ve
**neyi yapmadığı** yazılı değil.
**Uygulama:** `.agents/skills/*/SKILL.md` frontmatter'ına `when_to_consult` + `not_for` alanları; LLM
yönlendirici bunları okur (mevcut `llm_skills` tablosuna iki kolon). "21-AI konsensüsü sabit üretiyor"
kusurunun bir kısmı da bu: sınırsız uzman → aynı genel cevap.
**Kabul testi:** iki ajan aynı soruda farklı `not_for` sınırına düşüyor; yönlendirici doğru ajanı seçiyor.

### 3) `TOOL_STYLE.md` — araç tasarım sözleşmesi
**Kurallar (kaynaktan):** imza = şema; bir araç bir iş; her enum `Literal`; bilinen şekle asla
`dict[str, Any]` yok; opsiyonel `None` (backend varsayılanını imzada tekrarlama); **isim grep'lenebilir olmalı**
(`create_grid_executor` ✓ / `grid` ✗); tehlike **isimden** taşınır.
**Bizde:** `llm_second_eye`/araç tanımları ve planlanan MCP veri sunucuları için doğrudan geçerli.
**Kabul testi:** araç şemalarında `dict[str, Any]` sayısı 0; her yıkıcı aracın adı tehlike kapısında eşleşiyor.

---

## P2 — Stratejik değeri yüksek (orta maliyet)

### 4) Controller + loop sözleşmesi — "ajan kendi stratejisini yazar"
`agents/directional_trader/controllers/` = `bollinger_v1`, `macd_bb_v1`, `supertrend_v1`; `loops/ema_trend_loop`.
Sözleşme net: **`signal` kolonu `+1 / −1 / 0`**, ve **`0` "yeni sinyal yok" demektir, pozisyon KAPATMAZ**;
`update_processed_data` **vektörize** olmak zorunda (satır döngüsü yasak).
**Neden bizim için önemli:** Bugün kollar motorda gömülü; her yeni sinyal ailesi = motor değişikliği.
Böyle bir sözleşme, "parametre oynatma"dan "yeni aile ekleme"ye geçişi **hızlandırır** ve `signal=0` kuralı
pozisyon yönetimini stratejiden ayırır — bizim ölçtüğümüz "çıkış tarafı doymuş" bulgusuna uygun mimari.
**Uygulama:** `scripts/arms/<aile>.py` + `signal()` sözleşmesi; replay ve canlı aynı dosyayı yükler
(tek kaynak). Dry-run zorunlu (paper'da N gün).
**Kabul testi:** aynı kol dosyası replay'de ve canlıda aynı sinyalleri üretiyor; `signal=0` hiçbir pozisyonu kapatmıyor.

### 5) `routines/base.py` — rutin kayıt defteri (one-shot / continuous)
Rutinler sınıf tabanlı, keşif (discovery) ile bulunuyor; one-shot ve `CONTINUOUS=True` (kendi döngüsü) tipleri var;
`market_scanner`, `mean_reversion_scanner`, `price_monitor`, `logs_summary` gibi hazır örnekler.
**Bizde:** `scheduled_actions` yalnız `close_positions` + `reminder`. Bugün elle koştuğum **ölçüm probları**
(`fx_family_probe`, `fx_symbol_expectancy`, `fx_selectivity_probe`) rutin olamıyor.
**Uygulama:** `app/routines/` + `base.py` (isim, tip, aralık, çıktı şeması) ve mevcut scheduler'a kayıt;
gece 03:00'te "beklenti + MFE + seçicilik" raporu üretip panelde "Raporlar" altında göstermek.
**Kabul testi:** rutin elle tetiklenebilir + zamanlanabilir; çıktısı JSON şemasına uyar; hata rutini öldürmez.

---

## P3 — Sadece ileride (koşullu)

### 6) `code_guard.py` — ajan-kodu için kesilebilir deadline
Sandbox **değil**; `sys.monitoring` + audit hook ile **senkron kodu kesebilen** deadline koyuyor
(`BaseException` → `except Exception` yutamaz) ve politika listesi uyguluyor (kök dizin listeleme yok, `input()` yok…).
**Neden ileride:** Ajan-kodu çalıştırırsak zorunlu olur. Kendi kayıtlarındaki olay: bir snippet'in
`glob.glob("/**/x.py")` çağrısı ana thread'i saatlerce kilitleyip dashboard'ı dondurmuş (2026-10-07).
**Şimdi yapılacak:** ajan-kodu çalıştırma **yoksa** bir şey eklemeye gerek yok; ama #4'ü uygularsak bu şart.

### 7) `backtest_store` / `backtesting.py`
Ajan-stratejisi ↔ backtest bağı ve sonuç deposu. Bizim replay FX/MT5 için daha güçlü (tick, spread, SL-first,
payoff ölçümü). **Alınmaz**; yalnız "backtest sonucu = strateji kimliğine bağlı artefakt" fikri bizde zaten var.

---

## ALINMAYACAKLAR (bilinçli)
- Hummingbot API / Docker / Gateway / DEX-CLMM yığını — biz MT5 + FastAPI'deyiz, exchange adaptörleri gereksiz.
- Telegram-öncelikli kontrol düzlemi — bizde Next.js panel + VAPID push var.
- `pandas_ta` bağımlılığı (onların controller'ları pandas ister) — üretim imajımız numpy+sklearn, pandas yalnız araştırma.
- Per-seat LLM/ACP altyapısı — bizim `llm_analysis` çok-sağlayıcı yönlendirmesi yeterli.

---

## Önerilen sıra
1. **danger.py eşleniği** (P1, güvenlik) — en yüksek değer/maliyet oranı.
2. **Rutin kayıt defteri** (P2) — bugün elle yaptığımız ölçümleri otomatiğe bağlar; kanıt döngüsü kalıcılaşır.
3. **AGENT.md sözleşmesi + TOOL_STYLE** (P1) — LLM tarafının mevcut kusurlarına (sabit üretim, araç şeması) doğrudan dokunur.
4. **Controller/loop sözleşmesi** (P2) — en büyük stratejik kazanç ama en çok iş; #4 için `code_guard` şartı da gelir.
