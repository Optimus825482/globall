"use client";
// ============================================================================
// AYARLAR — 2026-10-07: BİRLEŞTİRİLMİŞ TEK AYARLAR KONSOLU
//
// 1. Forex & Otonom Scalper ayarları (`/forex/ayarlar` ile birleştirildi)
// 2. Sistem Sağlığı sekmesi (sidebar'dan buraya sekme olarak taşındı)
// 3. TR Köprüsü ve spot parçaları tamamen kaldırıldı
// 4. Uygulama, LLM/Provider, Chat ve Profil yönetimi
// ============================================================================

import { useEffect, useState } from "react";
import { API_BASE, apiRequest, apiFetch } from "../lib/api";
import LlmManagement from "./LlmManagement";
import ChatSettingsPanel from "./ChatSettingsPanel";
import RequireAdmin from "../components/RequireAdmin";
import { useAuth } from "../lib/auth";
import { ProfileContent } from "../profile/page";
import SystemHealthTab from "./SystemHealthTab";
import AutoSettingsPanel, { type AutoSettings } from "../forex/components/AutoSettingsPanel";
import {
  getInAppNotificationSettings,
  saveInAppNotificationSettings,
  triggerTestInAppNotification,
  type InAppNotificationSettings,
} from "../lib/notificationSettings";

type SettingsTab = "forex" | "health" | "app" | "llm" | "chat" | "profile";

const VALID_TABS: SettingsTab[] = ["forex", "health", "app", "llm", "chat", "profile"];

interface CleanSlateResult {
  archived_count: number;
  reset_at: string;
  kept_paper_count?: number;
  note: string;
}

const noopClose = () => {};

export default function SettingsPage() {
  return <RequireAdmin><SettingsPageInner /></RequireAdmin>;
}

function SettingsPageInner() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("forex");
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

  // Forex Scalper Ayarları Durumu
  const [appliedForexSettings, setAppliedForexSettings] = useState<AutoSettings | null>(null);
  const [forexLoadError, setForexLoadError] = useState<string | null>(null);
  const [isResettingGuards, setIsResettingGuards] = useState(false);
  const [resetResult, setResetResult] = useState<CleanSlateResult | null>(null);
  const [resetError, setResetError] = useState<string | null>(null);

  // Push Testi Durumu
  const [testingPush, setTestingPush] = useState(false);
  const [pushTestResult, setPushTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  // Uygulama İçi Bildirim (Radar Modal) Ayarları
  const [inAppNotif, setInAppNotif] = useState<InAppNotificationSettings>(() =>
    getInAppNotificationSettings()
  );
  const [notifSavedToast, setNotifSavedToast] = useState(false);

  const updateInAppNotif = (partial: Partial<InAppNotificationSettings>) => {
    const next = { ...inAppNotif, ...partial };
    setInAppNotif(next);
    saveInAppNotificationSettings(next);
    setNotifSavedToast(true);
    setTimeout(() => setNotifSavedToast(false), 2000);
  };

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

  // LLM Config Yükleme
  useEffect(() => {
    apiRequest(`${API_BASE}/api/llm/config`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setLlm)
      .catch(() => setError("LLM yapılandırması alınamadı (HTTP hatası)"));
  }, []);

  // Forex Auto Settings Yükleme
  useEffect(() => {
    let cancelled = false;
    const fetchSettings = async () => {
      try {
        const res = await apiFetch("/api/forex/auto-paper/status");
        if (!cancelled && res?.settings) {
          const s = { ...res.settings };
          if (!s.allowed_symbols || s.allowed_symbols.length === 0) {
            s.allowed_symbols = [
              "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
              "USDCAD", "NZDUSD", "GBPJPY", "EURJPY", "BTCUSD",
              "NAS100", "US30", "XAUUSD"
            ];
          }
          setAppliedForexSettings(s);
        }
      } catch (err) {
        if (!cancelled) {
          console.error("Forex ayarları yüklenemedi:", err);
          setForexLoadError("Forex motor ayarları yüklenemedi — backend bağlantısını kontrol edin.");
        }
      }
    };
    fetchSettings();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCleanSlate = async () => {
    if (
      !confirm(
        "🧹 Temiz Sayfa: kesim öncesindeki TÜM kapalı işlemler arşive alınacak; EV kalkanı ve seri-SL sayaçları sıfırlanacak, rapor/KPI/CSV sıfırdan sayacak. Bakiyeye dokunulmaz. Devam edilsin mi?"
      )
    )
      return;
    setIsResettingGuards(true);
    setResetError(null);
    setResetResult(null);
    try {
      const res = await apiFetch("/api/forex/auto-paper/reset-symbol-guards", { method: "POST" });
      setResetResult({
        archived_count: Number(res?.archived_count ?? 0),
        reset_at: String(res?.reset_at ?? "-"),
        kept_paper_count: res?.kept_paper_count != null ? Number(res.kept_paper_count) : undefined,
        note: String(res?.note ?? ""),
      });
    } catch (err) {
      console.error("Temiz sayfa hatası:", err);
      setResetError(err instanceof Error ? err.message : "Temiz sayfa işlemi başarısız oldu.");
    } finally {
      setIsResettingGuards(false);
    }
  };

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
    setLlmForm(prev => ({ ...prev, api_key: "" }));
  };

  return (
    <div className="settings-page max-w-5xl mx-auto space-y-6">
      <header className="settings-header flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-bold tracking-tight">
            <span className="text-neon-green">AYARLAR</span>
          </h1>
          <p className="eyebrow mt-1">Forex parametreleri, sistem sağlığı, hesap ve altyapı yönetimi</p>
        </div>
      </header>

      {error && (
        <div className="card border-neon-red/40 bg-neon-red/5">
          <p className="font-mono text-sm text-neon-red">{error}</p>
        </div>
      )}

      <nav className="flex gap-2 border-b border-bunker-800 pb-2 overflow-x-auto scrollbar-none md:flex-wrap" aria-label="Ayar sekmeleri">
        {([
          ["forex", "Forex & Scalper", "⚡"],
          ["health", "Sistem Sağlığı", "🩺"],
          ["app", "Uygulama Ayarları", "⚙️"],
          ["profile", "Profil", "👤"],
          ["llm", "LLM / Provider", "🤖"],
          ["chat", "Chat Ayarları", "✦"],
        ] as const).map(([key, label, icon]) => (
          <button
            key={key}
            onClick={() => selectTab(key)}
            className={`shrink-0 px-3.5 py-2 rounded-xl border font-mono text-xs transition-all touch-target active:scale-95 whitespace-nowrap ${
              activeTab === key
                ? "border-cyan-400/60 bg-cyan-950/40 text-cyan-300 font-bold shadow-[0_0_8px_rgba(0,240,255,0.2)]"
                : "border-bunker-800 bg-bunker-900/80 text-bunker-muted hover:text-white"
            }`}
          >
            {icon} {label}
          </button>
        ))}
      </nav>

      <>
        {/* SEKME 1: FOREX & SCALPER AYARLARI */}
        <div className={`space-y-6 ${activeTab !== "forex" ? "hidden" : ""}`}>
          <div className="p-4 rounded-xl bg-gradient-to-r from-blue-950/40 via-bunker-900/90 to-cyan-950/30 border border-blue-500/40 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-xl shadow-[0_0_12px_rgba(59,130,246,0.3)]">
              ⚡
            </div>
            <div>
              <h2 className="text-sm font-bold text-white tracking-tight">Otonom Forex Scalper Motor Ayarları</h2>
              <p className="text-xs text-bunker-muted mt-0.5">
                Risk, kâr al / zarar durdur, dinamik lot ve sembol kalkanı parametreleri anında motora uygulanır.
              </p>
            </div>
          </div>

          {/* UYGULAMA İÇİ BİLDİRİM HIZLI KONTROLÜ */}
          <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-xs">
            <div className="flex items-center gap-2.5">
              <span className="text-lg">{inAppNotif.enabled ? "🔔" : "🔕"}</span>
              <div>
                <span className="font-bold text-white">Uygulama İçi Radar Bildirimleri: </span>
                <span className={inAppNotif.enabled ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                  {inAppNotif.enabled ? "AÇIK (Radar popupları aktif)" : "KAPALI (Popuplar susturuldu)"}
                </span>
                <span className="text-[11px] text-bunker-muted block mt-0.5">
                  {inAppNotif.soundEnabled ? "Ses: Açık" : "Ses: Kapalı"} · Otomatik Kapanma: {inAppNotif.autoCloseSec > 0 ? `${inAppNotif.autoCloseSec} sn` : "Manuel"}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => updateInAppNotif({ enabled: !inAppNotif.enabled })}
                className={`px-3.5 py-1.5 rounded-lg font-mono text-[11px] font-bold transition-all shadow-sm ${
                  inAppNotif.enabled
                    ? "bg-rose-950/60 border border-rose-500/40 text-rose-300 hover:bg-rose-900/60"
                    : "bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-900/60"
                }`}
              >
                {inAppNotif.enabled ? "🔕 Bildirimleri Kapat" : "🔔 Bildirimleri Aç"}
              </button>
              <button
                type="button"
                onClick={() => selectTab("app")}
                className="px-3 py-1.5 rounded-lg border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 font-mono text-[11px]"
              >
                ⚙️ Ses &amp; Süre
              </button>
            </div>
          </div>

          {forexLoadError && (
            <div className="p-3 rounded-xl bg-rose-500/20 border border-rose-500/40 text-rose-300 text-xs font-bold">
              {forexLoadError}
            </div>
          )}
          {!appliedForexSettings && !forexLoadError && (
            <div className="p-8 text-center text-bunker-muted text-xs animate-pulse rounded-2xl bg-bunker-900/70 border border-bunker-800 font-mono">
              Motor ayarları yükleniyor…
            </div>
          )}
          {appliedForexSettings && (
            <AutoSettingsPanel
              show={true}
              onClose={noopClose}
              appliedSettings={appliedForexSettings}
              onSaved={setAppliedForexSettings}
              accent="blue"
            />
          )}

          {/* TEMİZ SAYFA (reset-symbol-guards) */}
          <div className="p-5 rounded-2xl bg-bunker-900/80 border border-bunker-800 shadow-xl space-y-3 font-mono">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-base">🧹</span>
                  <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                    Temiz Sayfa (Sembol Kalkanlarını Sıfırla)
                  </h3>
                </div>
                <p className="text-[11px] text-bunker-muted mt-1.5 leading-relaxed">
                  Kesim öncesindeki tüm kapalı işlemler arşive alınır; EV kalkanı ve seri-SL sayaçları sıfırlanır,
                  rapor/KPI/CSV sıfırdan saymaya başlar. Bakiyeye dokunulmaz.
                </p>
              </div>
              <button
                type="button"
                onClick={handleCleanSlate}
                disabled={isResettingGuards}
                className="shrink-0 px-4 py-2 rounded-xl bg-bunker-950 border border-bunker-700 text-white hover:border-amber-400 transition-all text-xs font-bold flex items-center gap-1.5 disabled:opacity-50"
              >
                <span>{isResettingGuards ? "⏳ Temizleniyor…" : "🧹 Temiz Sayfa"}</span>
              </button>
            </div>

            {resetResult && (
              <div className="p-3 rounded-xl bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs space-y-1">
                <div className="font-bold">✓ Temiz sayfa tamamlandı — {resetResult.reset_at}</div>
                <div>
                  Arşive alınan işlem: <span className="font-bold">{resetResult.archived_count}</span>
                  {resetResult.kept_paper_count != null && (
                    <>
                      {" · "}Raporda kalan: <span className="font-bold">{resetResult.kept_paper_count}</span>
                    </>
                  )}
                </div>
                {resetResult.note && (
                  <div className="text-[11px] text-bunker-300 leading-relaxed">{resetResult.note}</div>
                )}
              </div>
            )}

            {resetError && (
              <div className="p-3 rounded-xl bg-rose-500/20 border border-rose-500/40 text-rose-300 text-xs font-bold">
                {resetError}
              </div>
            )}
          </div>
        </div>

        {/* SEKME 2: SİSTEM SAĞLIĞI */}
        <div className={`${activeTab !== "health" ? "hidden" : ""}`}>
          <SystemHealthTab />
        </div>

        {/* SEKME 3: PROFİL */}
        <div className={`${activeTab !== "profile" ? "hidden" : ""}`}>
          <ProfileContent />
        </div>

        {/* SEKME 4: CHAT AYARLARI */}
        <div className={`${activeTab !== "chat" ? "hidden" : ""}`}>
          <ChatSettingsPanel />
        </div>

        {/* SEKME 5: LLM / PROVIDER */}
        <div className={`space-y-4 ${activeTab !== "llm" ? "hidden" : ""}`}>
          <div className="card bg-bunker-950">
            <p className="eyebrow mb-3">LLM PROVIDER EKLE</p>
            <p className="text-xs text-bunker-muted mb-3">Yalnızca teknik yorum üretir; emir veya pozisyon kararı vermez.</p>
            <div className="grid md:grid-cols-2 gap-3">
              <input placeholder="Provider adı" value={llmForm.name} onChange={e => setLlmForm({...llmForm,name:e.target.value})} className="input" />
              <input placeholder="Base URL (https://.../v1)" value={llmForm.base_url} onChange={e => setLlmForm({...llmForm,base_url:e.target.value})} className="input" />
              <input type="password" placeholder="API key" value={llmForm.api_key} onChange={e => setLlmForm({...llmForm,api_key:e.target.value})} className="input" />
              <button onClick={saveLlmProvider} disabled={!llm.encryption_configured || !llmForm.name.trim() || !llmForm.base_url.trim() || !llmForm.api_key.trim()} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs disabled:opacity-40 disabled:cursor-not-allowed">
                PROVIDER KAYDET
              </button>
            </div>
            <p className={`text-xs mt-3 ${llm.encryption_configured ? "text-bunker-muted" : "text-yellow-300"}`}>
              Şifreleme anahtarı: {llm.encryption_configured ? "hazır" : "sunucuda LLM_ENCRYPTION_KEY eksik; Provider kaydı için backend ortamına eklenmeli"}
            </p>
          </div>

          <div className="card bg-bunker-950">
            <p className="eyebrow mb-3">MODEL / UZMANLIK</p>
            <div className="grid md:grid-cols-2 gap-3">
              <select value={llmForm.provider_id} onChange={e => setLlmForm({...llmForm,provider_id:e.target.value})} className="input">
                <option value="">Provider seç</option>
                {(llm.providers ?? []).map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <input placeholder="Model adı" value={llmForm.model} onChange={e => setLlmForm({...llmForm,model:e.target.value})} className="input" />
              <select value={llmForm.model_type} onChange={e => setLlmForm({...llmForm,model_type:e.target.value})} className="input">
                <option value="chat">Chat modeli</option>
                <option value="embedding">Embedding modeli</option>
              </select>
              {llmForm.model_type === "embedding" && (
                <input type="number" min="1" placeholder="Embedding dimension" value={llmForm.dimensions} onChange={e => setLlmForm({...llmForm,dimensions:e.target.value})} className="input" />
              )}
              <button onClick={() => llmRequest(`${API_BASE}/api/llm/models`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider_id:Number(llmForm.provider_id),name:llmForm.model,model_type:llmForm.model_type,dimensions:llmForm.dimensions ? Number(llmForm.dimensions) : undefined})}, "Model kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">
                MODEL EKLE
              </button>
              {llmForm.model_type === "embedding" && (
                <button onClick={async () => { const r=await apiRequest(`${API_BASE}/api/llm/embedding/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"embedding bağlantı testi"})}); const b=await r.json(); const m=b.status === "ok" ? `Embedding başarılı · ${b.dimensions} dimension` : (b.error || "Embedding testi başarısız"); setLlmMessage(m); window.alert(m); }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">
                  EMBEDDING TEST ET
                </button>
              )}
              <input placeholder="Uzmanlık adı" value={llmForm.skill} onChange={e => setLlmForm({...llmForm,skill:e.target.value})} className="input" />
              <textarea placeholder="Uzmanlık talimatları" value={llmForm.instructions} onChange={e => setLlmForm({...llmForm,instructions:e.target.value})} className="input min-h-24" />
              <button onClick={() => llmRequest(`${API_BASE}/api/llm/skills`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:llmForm.skill,instructions:llmForm.instructions})}, "Uzmanlık kaydedildi")} className="px-3 py-2 border border-sky-400/40 text-sky-300 rounded-lg font-mono text-xs">
                UZMANLIK EKLE
              </button>
            </div>
            {llmMessage && <p className="text-xs text-neon-green mt-3">{llmMessage}</p>}
          </div>

          <div className="card bg-bunker-950 flex flex-wrap gap-3">
            <select value={llm.active_model_id || ""} onChange={async e => { const id=Number(e.target.value); await llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:id})}, "LLM aktif edildi"); }} className="input">
              <option value="">Aktif model seç</option>
              {(llm.models ?? []).map((m:any)=><option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            <button onClick={() => llmRequest(`${API_BASE}/api/llm/active`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,model_id:llm.active_model_id})}, "LLM aktif edildi")} className="px-3 py-2 border border-neon-green/40 text-neon-green rounded-lg font-mono text-xs">
              LLM AKTİF
            </button>
            <button onClick={async () => { setLlmMessage("TEST EDİLİYOR..."); try { const r=await apiRequest(`${API_BASE}/api/llm/test`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})}); const body=await r.json(); const message=body.status === "ok" ? "Bağlantı başarılı" : (body.error || body.status || "Test başarısız"); setLlmMessage(message); window.alert(message); } catch { setLlmMessage("LLM test bağlantısı kurulamadı"); window.alert("LLM test bağlantısı kurulamadı"); } }} className="px-3 py-2 border border-yellow-400/40 text-yellow-300 rounded-lg font-mono text-xs">
              TEST ET
            </button>
          </div>

          <div className="card border-purple-400/30 bg-purple-400/5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <p className="eyebrow text-purple-300">MEVCUT KAYITLARI VECTORLEŞTİR</p>
              <p className="text-xs text-bunker-muted mt-2">Kapanmış işlemler ve sinyaller aktif embedding modeliyle pgvector memory tablosuna aktarılır.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={backfillEmbeddings} disabled={backfilling} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${backfillDone ? "border-neon-green/60 text-neon-green" : "border-purple-400/50 text-purple-300"}`}>
                {backfilling ? "KUYRUĞA ALINIYOR..." : backfillDone ? "✓ KUYRUĞA ALINDI" : "EMBEDDING BACKFILL BAŞLAT"}
              </button>
              <button onClick={repairHistoricalMemory} disabled={repairingMemory} className="shrink-0 px-4 py-2 rounded-lg border border-yellow-400/50 text-yellow-300 font-mono text-xs">
                {repairingMemory ? "ONARILIYOR..." : "TARİHSEL SNAPSHOT ONAR"}
              </button>
            </div>
          </div>

          <div className="card border-yellow-400/30 bg-yellow-400/5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <p className="eyebrow text-yellow-300">LLM PAPER İŞLEM YETKİSİ</p>
              <p className="text-xs text-bunker-muted mt-2">Açıkken LLM yalnızca sanal portföyde kontrollü LONG pozisyonu açabilir. Gerçek emir API&apos;si kullanılmaz.</p>
            </div>
            <div className="flex gap-2">
              <button onClick={async()=>{const enabled=!llm.paper_trade_enabled;await llmRequest(`${API_BASE}/api/llm/paper-trading`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled})},enabled?"Paper işlem yetkisi açıldı":"Paper işlem yetkisi kapatıldı");await reloadLlm()}} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${llm.paper_trade_enabled?"border-neon-green/60 text-neon-green":"border-bunker-700 text-bunker-muted"}`}>
                {llm.paper_trade_enabled?"AÇIK · KAPAT":"KAPALI · AÇ"}
              </button>
              <button disabled={!llm.paper_trade_enabled} onClick={async()=>{const enabled=!llm.auto_paper_enabled;await llmRequest(`${API_BASE}/api/llm/auto-paper-trading`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled})},enabled?"Kapanış sonrası otomatik yenileme açıldı":"Otomatik yenileme kapatıldı");await reloadLlm()}} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs ${llm.auto_paper_enabled?"border-yellow-300/60 text-yellow-300":"border-bunker-700 text-bunker-muted"}`}>
                {llm.auto_paper_enabled?"KAPANIŞ SONRASI · KAPAT":"KAPANIŞ SONRASI · AÇ"}
              </button>
            </div>
          </div>
          <LlmManagement llm={llm} reload={reloadLlm} />
        </div>

        {/* SEKME 6: UYGULAMA AYARLARI */}
        <div className={`space-y-4 ${activeTab !== "app" ? "hidden" : ""}`}>
          {/* UYGULAMA İÇİ BİLDİRİMLER (RADAR & SİNYAL POPUPLARI) */}
          <div className="card border-cyan-400/40 bg-cyan-950/20 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <p className="eyebrow text-cyan-300">UYGULAMA İÇİ BİLDİRİMLER</p>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      inAppNotif.enabled
                        ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                        : "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                    }`}
                  >
                    {inAppNotif.enabled ? "AÇIK" : "KAPALI"}
                  </span>
                </div>
                <h3 className="font-mono text-sm font-bold text-white mt-1">
                  Forex Radar Güçlü Sinyal Popupları
                </h3>
                <p className="text-xs text-bunker-muted mt-1 max-w-xl">
                  Forex radarı güçlü bir işlem fırsatı (BUY/SELL, Tier: STRONG veya Skor ≥ 75) yakaladığında ekranın ortasında açılan anlık bildirim penceresi.
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => triggerTestInAppNotification()}
                  disabled={!inAppNotif.enabled}
                  className="px-3 py-2 rounded-lg border border-cyan-500/40 text-cyan-300 font-mono text-xs hover:bg-cyan-500/10 disabled:opacity-40 transition-colors"
                >
                  🔔 Örnek Bildirimi Gör
                </button>
                <button
                  type="button"
                  onClick={() => updateInAppNotif({ enabled: !inAppNotif.enabled })}
                  className={`px-4 py-2 rounded-lg font-mono text-xs font-bold transition-all shadow-md ${
                    inAppNotif.enabled
                      ? "bg-rose-600 hover:bg-rose-500 text-white"
                      : "bg-emerald-600 hover:bg-emerald-500 text-white"
                  }`}
                >
                  {inAppNotif.enabled ? "BİLDİRİMLERİ KAPAT" : "BİLDİRİMLERİ AÇ"}
                </button>
              </div>
            </div>

            {/* Ek Detay Ayarları: Ses & Süre */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-3 border-t border-bunker-800 text-xs">
              {/* Ses Toggle */}
              <div className="p-3 rounded-xl bg-bunker-900/70 border border-bunker-800 flex items-center justify-between">
                <div>
                  <div className="font-bold text-white flex items-center gap-1.5">
                    <span>{inAppNotif.soundEnabled ? "🔊" : "🔇"}</span>
                    <span>Radar Uyarı Sesi</span>
                  </div>
                  <p className="text-[11px] text-bunker-muted mt-0.5">
                    Güçlü sinyal yakalandığında çift tonlu ses çal
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => updateInAppNotif({ soundEnabled: !inAppNotif.soundEnabled })}
                  disabled={!inAppNotif.enabled}
                  className={`px-3 py-1.5 rounded-lg border font-mono text-xs font-bold transition-colors disabled:opacity-40 ${
                    inAppNotif.soundEnabled
                      ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
                      : "border-bunker-700 bg-bunker-950 text-bunker-muted"
                  }`}
                >
                  {inAppNotif.soundEnabled ? "SES AÇIK" : "SESSİZ"}
                </button>
              </div>

              {/* Otomatik Kapanma Süresi */}
              <div className="p-3 rounded-xl bg-bunker-900/70 border border-bunker-800 flex items-center justify-between">
                <div>
                  <div className="font-bold text-white flex items-center gap-1.5">
                    <span>⏱️</span>
                    <span>Otomatik Kapanma Süresi</span>
                  </div>
                  <p className="text-[11px] text-bunker-muted mt-0.5">
                    Ekranda açık kalma süresi
                  </p>
                </div>
                <select
                  value={inAppNotif.autoCloseSec}
                  onChange={(e) => updateInAppNotif({ autoCloseSec: Number(e.target.value) })}
                  disabled={!inAppNotif.enabled}
                  className="bg-bunker-950 border border-bunker-700 text-white rounded-lg px-2.5 py-1 font-mono text-xs outline-none focus:border-cyan-400 disabled:opacity-40"
                >
                  <option value={10}>10 Saniye</option>
                  <option value={20}>20 Saniye (Önerilen)</option>
                  <option value={30}>30 Saniye</option>
                  <option value={0}>Manuel (Kapatana Kadar)</option>
                </select>
              </div>
            </div>

            {notifSavedToast && (
              <p className="text-xs font-bold text-emerald-400 animate-pulse">
                ✓ Uygulama içi bildirim ayarı anında uygulandı.
              </p>
            )}
          </div>

          <div className="card border-neon-green/30 bg-neon-green/5">
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

          <div className="card border-sky-400/30 bg-sky-400/5">
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
        </div>
      </>
    </div>
  );
}
