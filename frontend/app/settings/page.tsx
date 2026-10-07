"use client";
// ============================================================================
// AYARLAR — 2026-10-07: Global uygulaması YALNIZCA Forex & Emtia sunar.
//
// Spot piyasa yüzeyi (semboller / radar / bildirim kuralları / strateji
// parametreleri / otonom paper / MACD-Sıçrama ayarları) ve spot trading
// parametreleri bu sayfadan KALDIRILDI. Forex'in tek parametre ekranı
// `/forex/ayarlar` sayfasıdır.
//
// Burada kalanlar piyasa-bağımsız yüzeylerdir:
//   • Profil      → kullanıcı hesabı
//   • Uygulama    → altyapı eylemleri (DB yedeği, push testi)
//   • LLM/Provider→ chat motoru sağlayıcı-model-uzmanlık yönetimi
//   • Chat        → chat araç/yetki ve ses ayarları
// Spot konfigürasyon düzenleme (GET/PUT /api/config) de kaldırıldı: düzenlenecek
// spot parametresi kalmadığı için "KAYDET" düğmesi sessizce yanıltıcı olurdu.
// ============================================================================

import { useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import LlmManagement from "./LlmManagement";
import ChatSettingsPanel from "./ChatSettingsPanel";
import RequireAdmin from "../components/RequireAdmin";
import { useAuth } from "../lib/auth";
// 2026-09-27: Profil Ayarlar'a sekme taşındı. `ProfileContent` headless
// bileşendir (kendi page-shell'i yok) — settings kapsayıcısına girer.
import { ProfileContent } from "../profile/page";
// 2026-09-28: TR Köprüsü sekmesi. Global tarama artık v4 İÇİNDE yerel olarak
// çalışacak şekilde taşınıyor; köprü o iş bitene kadar canlı sinyal yoludur ve
// operatörün onu kapatabilmesi gerekir. Taşıma tamamlanınca bu sekme kaldırılır.
import BridgeSettingsPanel from "./BridgeSettingsPanel";

type SettingsTab = "app" | "llm" | "chat" | "bridge" | "profile";

const VALID_TABS: SettingsTab[] = ["app", "llm", "chat", "bridge", "profile"];

export default function SettingsPage() {
  return <RequireAdmin><SettingsPageInner /></RequireAdmin>;
}

function SettingsPageInner() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("app");
  const [error, setError] = useState<string | null>(null);
  const [backingUp, setBackingUp] = useState(false);
  const [backupDone, setBackupDone] = useState(false);
  const [llm, setLlm] = useState<any>({ providers: [], models: [], skills: [], active_model_id: null, encryption_configured: false });
  const [llmForm, setLlmForm] = useState({ name: "OpenAI Compatible", base_url: "", api_key: "", provider_id: "", model: "", model_type: "chat", dimensions: "", skill: "", instructions: "" });
  const [llmMessage, setLlmMessage] = useState<string | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillDone, setBackfillDone] = useState(false);
  const [repairingMemory, setRepairingMemory] = useState(false);
  const { role } = useAuth();
  const isAdmin = role === "admin";
  // TEST BİLDİRİMİ (2026-09-16): push zincirini tek tuşla sına. Bildirim
  // gelmediğinde NEREDE koptuğunu (VAPID yok / abone yok / teslim edilemedi)
  // backend `detail` alanında söyler.
  const [testingPush, setTestingPush] = useState(false);
  const [pushTestResult, setPushTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const tab = new URLSearchParams(window.location.search).get("tab") as SettingsTab | null;
    if (tab && VALID_TABS.includes(tab)) setActiveTab(tab);
  }, []);

  const selectTab = (key: SettingsTab) => {
    setActiveTab(key);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", key);
      window.history.replaceState({}, "", url.pathname + url.search);
    }
  };

  useEffect(() => {
    apiRequest(`${API_BASE}/api/llm/config`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setLlm)
      .catch(() => setError("LLM yapılandırması alınamadı (HTTP hatası)"));
  }, []);

  // TEST BİLDİRİMİ (2026-09-16): Ayarlar > Uygulama Ayarları'ndaki buton.
  // Backend'e "tüm aboneliklere test push'u gönder" der ve sonucu (veya zincirin
  // hangi katmanında koptuğunu) gösterir. Böylece kullanıcı push'un çalışıp
  // çalışmadığını gerçek bir bildirimle doğrular; "sessizce ölü" hâl kalmaz.
  const sendTestPush = async () => {
    setTestingPush(true);
    setPushTestResult(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/alerts/push-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Test bildirimi gönderilemedi (HTTP ${res.status})`);
      const sent = Number(data.sent ?? 0);
      const total = Number(data.total ?? 0);
      const dead = Number(data.dead ?? 0);
      setPushTestResult({
        ok: true,
        text: `✓ Gönderildi · ${sent}/${total} aboneye${dead > 0 ? ` · ${dead} ölü abonelik temizlendi` : ""}. `
          + "Bildirim gelmediyse işletim sistemi/tarayıcı bildirim izinlerini ve Rahatsız Etme modunu kontrol edin.",
      });
    } catch (err) {
      setPushTestResult({ ok: false, text: err instanceof Error ? err.message : "Test bildirimi gönderilemedi" });
    } finally {
      setTestingPush(false);
    }
  };

  const downloadBackup = async () => {
    setBackingUp(true);
    setError(null);
    setBackupDone(false);
    try {
      const res = await apiRequest(`${API_BASE}/api/postgres/backup`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Yedekleme başarısız (HTTP ${res.status})`);
      }
      const blob = await res.blob();
      const header = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
      const isPostgresCustomDump = Array.from(header).join(",") === "80,71,68,77,80";
      if (!isPostgresCustomDump) {
        throw new Error("Sunucunun ürettiği dosya geçerli PostgreSQL custom-format yedeği değil");
      }
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      const disposition = res.headers.get("content-disposition") || "";
      const serverFilename = disposition.match(/filename="?([^";]+)"?/i)?.[1];
      anchor.download = serverFilename || `scalperagent-postgres-${new Date().toISOString().replace(/[:.]/g, "-")}.dump`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setBackupDone(true);
      setTimeout(() => setBackupDone(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "PostgreSQL veritabanı yedeği alınamadı");
    } finally {
      setBackingUp(false);
    }
  };

  const backfillEmbeddings = async () => {
    if (!window.confirm("Mevcut işlem ve sinyal kayıtları embedding modeline gönderilecek. Kayıtlar silinmeyecek. Devam edilsin mi?")) return;
    setBackfilling(true); setLlmMessage(null);
    try {
      const response = await apiRequest(`${API_BASE}/api/memory/backfill`, { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Embedding backfill başlatılamadı");
      setBackfillDone(true);
      setLlmMessage(`${body.queued || 0} kayıt embedding kuyruğuna alındı.`);
      setTimeout(() => setBackfillDone(false), 3000);
    } catch (err) { setLlmMessage(err instanceof Error ? err.message : "Embedding backfill başarısız"); }
    finally { setBackfilling(false); }
  };

  const repairHistoricalMemory = async () => {
    if (!window.confirm("Eksik tarihsel likidite alanları tahmin edilmeden işaretlenecek ve ilgili embedding kayıtları yeniden üretilecek. Devam edilsin mi?")) return;
    setRepairingMemory(true); setLlmMessage(null);
    try {
      const response = await apiRequest(`${API_BASE}/api/memory/repair-historical`, { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Tarihsel memory onarımı başlatılamadı");
      setLlmMessage(`${body.queued || 0} tarihsel snapshot yeniden embedding kuyruğuna alındı.`);
    } catch (err) { setLlmMessage(err instanceof Error ? err.message : "Tarihsel memory onarımı başarısız"); }
    finally { setRepairingMemory(false); }
  };

  const reloadLlm = async () => setLlm(await (await apiRequest(`${API_BASE}/api/llm/config`, { cache: "no-store" })).json());
  const llmRequest = async (url: string, options: RequestInit, success: string) => {
    setLlmMessage(null);
    try {
      const response = await apiRequest(url, options);
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body.ok === false) throw new Error(body.detail || body.error || "İşlem başarısız");
      await reloadLlm();
      setLlmMessage(success);
      window.alert(`${success}.`);
    } catch (err) {
      setLlmMessage(err instanceof Error ? err.message : "LLM işlemi başarısız");
    }
  };

  const saveLlmProvider = async () => {
    // API key'i gönder; state'teki değer immutable güncellenir (React state'ini
    // doğrudan mutate etmek render'ı tetiklemez ve Strict Mode'da iz sürülemez).
    const apiKeyToSend = llmForm.api_key;
    await llmRequest(
      `${API_BASE}/api/llm/providers`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: llmForm.name.trim(),
          base_url: llmForm.base_url.trim(),
          api_key: apiKeyToSend,
        }),
      },
      "Provider kaydedildi",
    );
    // Başarısız olsa da key'i bellekte tutmamak için state'i sıfırla
    setLlmForm(prev => ({ ...prev, api_key: "" }));
  };

  return (
    <div className="settings-page max-w-5xl mx-auto space-y-6">
      <header className="settings-header flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-bold tracking-tight">
            <span className="text-neon-green">AYARLAR</span>
          </h1>
          <p className="eyebrow mt-1">Hesap, asistan ve altyapı ayarları</p>
        </div>
      </header>

      {error && (
        <div className="card border-neon-red/40 bg-neon-red/5">
          <p className="font-mono text-sm text-neon-red">{error}</p>
        </div>
      )}

      <nav className="flex gap-2 border-b border-bunker-800 pb-2 overflow-x-auto scrollbar-none md:flex-wrap" aria-label="Ayar sekmeleri">
        {([
          ["app", "Uygulama Ayarları", "⚙️"],
          ["profile", "Profil", "👤"],
          ["llm", "LLM / Provider", "🤖"],
          ["chat", "Chat Ayarları", "✦"],
          ["bridge", "TR Köprüsü", "🌉"],
        ] as const).map(([key, label, icon]) => (
          <button key={key} onClick={() => selectTab(key)} className={`shrink-0 px-3.5 py-2 rounded-xl border font-mono text-xs transition-all touch-target active:scale-95 whitespace-nowrap ${activeTab === key ? "border-cyan-400/60 bg-cyan-950/40 text-cyan-300 font-bold shadow-[0_0_8px_rgba(0,240,255,0.2)]" : "border-bunker-800 bg-bunker-900/80 text-bunker-muted hover:text-white"}`}>
            {icon} {label}
          </button>
        ))}
      </nav>

      <>
        {/* 2026-09-27: Profil sekmesi — headless ProfileContent gömülür. */}
        <div className={`${activeTab !== "profile" ? "hidden" : ""}`}>
          <ProfileContent />
        </div>

        <div className={`${activeTab !== "chat" ? "hidden" : ""}`}>
          <ChatSettingsPanel />
        </div>

        {/* 2026-09-28: TR Köprüsü sekmesi (Lead-Lag haberleşme ve canlı sinyal akışı) */}
        <div className={`${activeTab !== "bridge" ? "hidden" : ""}`}>
          <BridgeSettingsPanel />
        </div>

        <div className={`space-y-4 ${activeTab !== "llm" ? "hidden" : ""}`}>
          <div className="card bg-bunker-950"><p className="eyebrow mb-3">LLM PROVIDER EKLE</p><p className="text-xs text-bunker-muted mb-3">Yalnızca teknik yorum üretir; emir veya pozisyon kararı vermez.</p><div className="grid md:grid-cols-2 gap-3"><input placeholder="Provider adı" value={llmForm.name} onChange={e => setLlmForm({...llmForm,name:e.target.value})} className="input" /><input placeholder="Base URL (https://.../v1)" value={llmForm.base_url} onChange={e => setLlmForm({...llmForm,base_url:e.target.value})} className="input" /><input type="password" placeholder="API key" value={llmForm.api_key} onChange={e => setLlmForm({...llmForm,api_key:e.target.value})} className="input" /><button onClick={saveLlmProvider} disabled={!llm.encryption_configured || !llmForm.name.trim() || !llmForm.base_url.trim() || !llmForm.api_key.trim()} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs disabled:opacity-40 disabled:cursor-not-allowed">PROVIDER KAYDET</button></div><p className={`text-xs mt-3 ${llm.encryption_configured ? "text-bunker-muted" : "text-yellow-300"}`}>Şifreleme anahtarı: {llm.encryption_configured ? "hazır" : "sunucuda LLM_ENCRYPTION_KEY eksik; Provider kaydı için backend ortamına eklenmeli"}</p></div>
          <div className="card bg-bunker-950"><p className="eyebrow mb-3">MODEL / UZMANLIK</p><div className="grid md:grid-cols-2 gap-3"><select value={llmForm.provider_id} onChange={e => setLlmForm({...llmForm,provider_id:e.target.value})} className="input"><option value="">Provider seç</option>{(llm.providers ?? []).map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}</select><input placeholder="Model adı" value={llmForm.model} onChange={e => setLlmForm({...llmForm,model:e.target.value})} className="input" /><select value={llmForm.model_type} onChange={e => setLlmForm({...llmForm,model_type:e.target.value})} className="input"><option value="chat">Chat modeli</option><option value="embedding">Embedding modeli</option></select>{llmForm.model_type === "embedding" && <input type="number" min="1" placeholder="Embedding dimension" value={llmForm.dimensions} onChange={e => setLlmForm({...llmForm,dimensions:e.target.value})} className="input" />}<button onClick={() => llmRequest(`${API_BASE}/api/llm/models`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider_id:Number(llmForm.provider_id),name:llmForm.model,model_type:llmForm.model_type,dimensions:llmForm.dimensions ? Number(llmForm.dimensions) : undefined})}, "Model kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">MODEL EKLE</button>{llmForm.model_type === "embedding" && <button onClick={async () => { const r=await apiRequest(`${API_BASE}/api/llm/embedding/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"embedding bağlantı testi"})}); const b=await r.json(); const m=b.status === "ok" ? `Embedding başarılı · ${b.dimensions} dimension` : (b.error || "Embedding testi başarısız"); setLlmMessage(m); window.alert(m); }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">EMBEDDING TEST ET</button>}<input placeholder="Uzmanlık adı" value={llmForm.skill} onChange={e => setLlmForm({...llmForm,skill:e.target.value})} className="input" /><textarea placeholder="Uzmanlık talimatları" value={llmForm.instructions} onChange={e => setLlmForm({...llmForm,instructions:e.target.value})} className="input min-h-24" /><button onClick={() => llmRequest(`${API_BASE}/api/llm/skills`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:llmForm.skill,instructions:llmForm.instructions})}, "Uzmanlık kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">UZMANLIK EKLE</button></div>{llmMessage && <p className="text-xs text-neon-green mt-3">{llmMessage}</p>}</div>
          <div className="card bg-bunker-950 flex flex-wrap gap-3"><select value={llm.active_model_id || ""} onChange={async e => { const id=Number(e.target.value); await llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:id})}, "LLM aktif edildi"); }} className="input"><option value="">Aktif model seç</option>{(llm.models ?? []).map((m:any)=><option key={m.id} value={m.id}>{m.name}</option>)}</select><button onClick={() => llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:llm.active_model_id})}, "LLM aktif edildi")} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs">LLM AKTİF</button><button onClick={async () => { setLlmMessage("TEST EDİLİYOR..."); try { const r=await apiRequest(`${API_BASE}/api/llm/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})}); const body=await r.json(); const message=body.status === "ok" ? "Bağlantı başarılı" : (body.error || body.status || "Test başarısız"); setLlmMessage(message); window.alert(message); } catch { setLlmMessage("LLM test bağlantısı kurulamadı"); window.alert("LLM test bağlantısı kurulamadı"); } }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">TEST ET</button></div>
          <div className="card border-purple-400/30 bg-purple-400/5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"><div><p className="eyebrow text-purple-300">MEVCUT KAYITLARI VECTORLEŞTİR</p><p className="text-xs text-bunker-muted mt-2">Kapanmış işlemler ve sinyaller aktif embedding modeliyle pgvector memory tablosuna aktarılır.</p></div><div className="flex flex-wrap gap-2"><button onClick={backfillEmbeddings} disabled={backfilling} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${backfillDone ? "border-neon-green/60 text-neon-green" : "border-purple-400/50 text-purple-300"}`}>{backfilling ? "KUYRUĞA ALINIYOR..." : backfillDone ? "✓ KUYRUĞA ALINDI" : "EMBEDDING BACKFILL BAŞLAT"}</button><button onClick={repairHistoricalMemory} disabled={repairingMemory} className="shrink-0 px-4 py-2 rounded-lg border border-yellow-400/50 text-yellow-300 font-mono text-xs">{repairingMemory ? "ONARILIYOR..." : "TARİHSEL SNAPSHOT ONAR"}</button></div></div>
          <div className="card border-yellow-400/30 bg-yellow-400/5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"><div><p className="eyebrow text-yellow-300">LLM PAPER İŞLEM YETKİSİ</p><p className="text-xs text-bunker-muted mt-2">Açıkken LLM yalnızca sanal portföyde kontrollü LONG pozisyonu açabilir. Gerçek emir API&apos;si kullanılmaz.</p></div><div className="flex gap-2"><button onClick={async()=>{const enabled=!llm.paper_trade_enabled;await llmRequest(`${API_BASE}/api/llm/paper-trading`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled})},enabled?"Paper işlem yetkisi açıldı":"Paper işlem yetkisi kapatıldı");await reloadLlm()}} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${llm.paper_trade_enabled?"border-neon-green/60 text-neon-green":"border-bunker-700 text-bunker-muted"}`}>{llm.paper_trade_enabled?"AÇIK · KAPAT":"KAPALI · AÇ"}</button><button disabled={!llm.paper_trade_enabled} onClick={async()=>{const enabled=!llm.auto_paper_enabled;await llmRequest(`${API_BASE}/api/llm/auto-paper-trading`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled})},enabled?"Kapanış sonrası otomatik yenileme açıldı":"Otomatik yenileme kapatıldı");await reloadLlm()}} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${llm.auto_paper_enabled?"border-yellow-300/60 text-yellow-300":"border-bunker-700 text-bunker-muted"}`}>{llm.auto_paper_enabled?"KAPANIŞ SONRASI · KAPAT":"KAPANIŞ SONRASI · AÇ"}</button></div></div>
          <LlmManagement llm={llm} reload={reloadLlm} />
        </div>

        <div className={`card border-neon-green/30 bg-neon-green/5 ${activeTab !== "app" ? "hidden" : ""}`}>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <p className="eyebrow text-neon-green">VERİTABANI YEDEĞİ</p>
              <p className="font-mono text-sm text-white mt-2">Canlı veritabanının tutarlı kopyasını indir</p>
              <p className="text-xs text-bunker-muted mt-1">PostgreSQL custom-format .dump yedeği alınır. İşlemler, sinyaller ve açık pozisyonlar dahil edilir.</p>
            </div>
            <button onClick={downloadBackup} disabled={backingUp} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${backupDone ? "border-neon-green/60 bg-neon-green/20 text-neon-green" : "border-neon-green/50 bg-neon-green/10 text-neon-green hover:bg-neon-green/20"}`}>
              {backingUp ? "YEDEKLENİYOR..." : backupDone ? "✓ YEDEK İNDİRİLDİ" : "VERİTABANI YEDEĞİ AL"}
            </button>
          </div>
        </div>

        {/* TEST BİLDİRİMİ (2026-09-16): push zincirini UÇTAN UCA kanıtlar.
            Bildirim gelmiyorsa backend kopan katmanı `detail` alanında söyler
            (VAPID yok / kayıtlı abone yok / teslim edilemedi) — kullanıcı
            "push çalışmıyor" demek yerine NEDENİNİ görür. */}
        <div className={`card border-sky-400/30 bg-sky-400/5 ${activeTab !== "app" ? "hidden" : ""}`}>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <p className="eyebrow text-sky-300">BİLDİRİM TESTİ</p>
              <p className="text-xs text-bunker-muted mt-1">Tüm kayıtlı cihazlara bir test bildirimi gönderir. Ses, başlık ve tıklama davranışını doğrular. Bildirim gelmezse önce tarayıcı bildirim iznini ve Rahatsız Etme modunu kontrol edin.</p>
            </div>
            <button
              type="button"
              onClick={sendTestPush}
              disabled={testingPush || !isAdmin}
              className="shrink-0 px-4 py-2 rounded-lg border border-sky-400/50 text-sky-300 font-mono text-xs hover:bg-sky-400/10 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {testingPush ? "GÖNDERİLİYOR…" : "TEST BİLDİRİMİ GÖNDER"}
            </button>
          </div>
          {pushTestResult && (
            <p className={`mt-3 font-mono text-xs ${pushTestResult.ok ? "text-neon-green" : "text-neon-red"}`}>
              {pushTestResult.text}
            </p>
          )}
        </div>
      </>
    </div>
  );
}
