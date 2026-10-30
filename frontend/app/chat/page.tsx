"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { streamChat } from "../lib/streamChat";
import MarkdownMessage from "../components/MarkdownMessage";
import { Button, Card } from "../components/ui";
import { useAuth } from "../lib/auth";
import AppLoader from "../components/AppLoader";

// Araştırma adımı: backend `step` olayı (teknik analiz, takvim, haber, dolar…).
type ResearchStep = { id: string; label: string; status: "running" | "done" | "error"; text?: string };

type Message = {
  role: "user" | "assistant";
  content: string;
  time?: string;
  steps?: ResearchStep[];
};

// Hazır sorular yalnız Altın, Bitcoin ve Forex içindir; her biri tek tıkla sorulur.
// `mode: "opportunity_scan"` yalnız bu düğmede gönderilir: backend Forex/Bitcoin/Altın'da yönlü fırsat arar ve
// kapıları geçenler için kayıtlı DEMO hesaba işlem açar (serbest metin asla işlem açmaz).
type QuickPrompt = { label: string; prompt: string; mode?: string };

const QUICK_PROMPTS: readonly QuickPrompt[] = [
  {
    label: "Fırsat taraması · demo işlem açar",
    mode: "opportunity_scan",
    prompt: "Fırsat taraması: Forex, Bitcoin, Altın ve endekslerde (Nasdaq, Dow) BUY veya SELL yönlü fırsat var mı? Varsa demo hesapta işlem aç.",
  },
  { label: "Altın şimdi nasıl?", prompt: "Altın (XAUUSD) şu an nasıl görünüyor? İşlem için uygun mu, beklemek mi mantıklı?" },
  { label: "Bitcoin ne yapıyor?", prompt: "Bitcoin şu an nasıl görünüyor? Kısa vadede yön ve dikkat edilecek nokta ne?" },
  { label: "Bugün hangi pariteler?", prompt: "Şu an en fırsatlı görünen Forex pariteleri hangileri? Neden?" },
  { label: "Yaklaşan haberler", prompt: "Önümüzdeki saatlerde işlemleri etkileyecek önemli ekonomik veriler var mı? Ne yapmalıyım?" },
  { label: "Son açıklanan veriler", prompt: "Az önce açıklanan ekonomik veriler neydi ve hangi pariteleri nasıl etkiledi?" },
  { label: "Dolar durumu", prompt: "Dolar şu an güçlü mü zayıf mı? Bu Altın ve EURUSD için ne anlama geliyor?" },
];

const starter: Message[] = [
  {
    role: "assistant",
    content: "Merhaba. Altın, Bitcoin ve Forex hakkında sorabilirsin: teknik görünüm, ekonomik takvim, haberler ve açıklanan verilerin etkisi. Her soruda güncel veriyi ve haberleri kendim araştırırım.",
    time: "Şimdi",
  },
];

// v2: eski kripto dönemi sohbet geçmişi yeni sayfada görünmesin.
const CHAT_STORAGE_KEY = "scalperagent:forexchat:v2";

const nowTime = () => new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });

/** Araştırma bulguları: her adım bittiği anda satır olarak düşer (araştırma sürerken görünür). */
function ResearchPanel({ steps, live }: { steps: ResearchStep[]; live: boolean }) {
  const visible = steps.filter((s) => s.id !== "answer");
  const done = visible.filter((s) => s.status !== "running").length;
  return (
    <details open={live} className="mb-3 rounded-lg border border-bunker-700/70 bg-black/20 text-xs">
      <summary className="cursor-pointer select-none px-3 py-2 font-mono font-bold text-cyan-300">
        {live ? `Araştırılıyor… ${done}/${visible.length}` : `Araştırma bulguları (${visible.length})`}
      </summary>
      <ul className="space-y-2 px-3 pb-3">
        {visible.map((s) => (
          <li key={s.id} className="leading-relaxed">
            <div className="flex items-center gap-2 font-semibold text-slate-200">
              {s.status === "running" && live ? (
                <span aria-hidden="true" className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-cyan-400/40 border-t-cyan-300" />
              ) : s.status === "error" ? (
                <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-amber-400" />
              ) : (
                <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-emerald-400" />
              )}
              <span>{s.label}</span>
              <span className="sr-only">{s.status === "running" && live ? "sürüyor" : s.status === "error" ? "tamamlanamadı" : "tamamlandı"}</span>
            </div>
            {s.text && <p className="mt-0.5 whitespace-pre-line pl-5 text-bunker-muted">{s.text}</p>}
          </li>
        ))}
      </ul>
    </details>
  );
}

function ChatPageInner() {
  const { username } = useAuth();
  const [messages, setMessages] = useState<Message[]>(starter);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hydrated, setHydrated] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [speakingIndex, setSpeakingIndex] = useState<number | null>(null);

  const endRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsUrlsRef = useRef<string[]>([]);
  const ttsSessionRef = useRef(0);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) || "null");
      if (Array.isArray(saved) && saved.length) {
        setMessages(saved.filter((m): m is Message => m?.role && typeof m.content === "string"));
      }
    } catch {
      /* yerel depolama isteğe bağlı */
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages.slice(-40)));
    } catch {
      /* yerel depolama isteğe bağlı */
    }
  }, [messages, hydrated]);

  useEffect(() => () => {
    ttsAudioRef.current?.pause();
    ttsUrlsRef.current.forEach(URL.revokeObjectURL);
    streamAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [messages, busy]);

  const stopSpeaking = () => {
    ttsSessionRef.current += 1;
    ttsAudioRef.current?.pause();
    ttsUrlsRef.current.forEach(URL.revokeObjectURL);
    ttsUrlsRef.current = [];
    setSpeakingIndex(null);
  };

  const speak = async (content: string, index: number) => {
    stopSpeaking();
    const session = ttsSessionRef.current;
    const clean = content.replace(/```[\s\S]*?```/g, " ").replace(/`([^`]*)`/g, "$1")
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[#>*_~|]/g, " ")
      .replace(/\p{Extended_Pictographic}/gu, " ").replace(/[.!?…]+/g, ",").replace(/\s+/g, " ").trim();
    const chunks = clean.match(/.{1,360}(?:\s|$)/g)?.map((part) => part.trim()).filter(Boolean) || [];
    if (!chunks.length) return;
    setSpeakingIndex(index);
    try {
      // Parçalar tembel istenir: yalnız çalan + bir sonraki (sunucu hız sınırı 3 patlama / 5 sn;
      // uzun yanıtta hepsini birden istemek 429 veriyordu).
      const fetchChunk = async (text: string) => {
        const response = await apiRequest(`${API_BASE}/api/tts/edge`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, rate: 0, pitch: 0 }),
        });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.detail || `Ses servisi HTTP ${response.status}`);
        }
        return URL.createObjectURL(await response.blob());
      };
      const requests: Promise<string>[] = [];
      const load = (i: number) => (requests[i] ??= fetchChunk(chunks[i]));
      const fail = (cause: unknown) => {
        if (session === ttsSessionRef.current) {
          stopSpeaking();
          setError(cause instanceof Error ? cause.message : "Sesli yanıt üretilemedi.");
        }
      };
      const play = async (i: number) => {
        if (session !== ttsSessionRef.current) return;
        const url = await load(i);
        if (i + 1 < chunks.length) load(i + 1).catch(() => undefined);
        ttsUrlsRef.current.push(url);
        if (session !== ttsSessionRef.current) { URL.revokeObjectURL(url); return; }
        const audio = new Audio(url);
        ttsAudioRef.current = audio;
        audio.onended = () => {
          URL.revokeObjectURL(url);
          if (session !== ttsSessionRef.current) return;
          if (i + 1 < chunks.length) play(i + 1).catch(fail); else setSpeakingIndex(null);
        };
        audio.onerror = () => {
          if (session === ttsSessionRef.current) { stopSpeaking(); setError("Ses oynatılamadı."); }
        };
        await audio.play();
      };
      await play(0);
    } catch (cause) {
      if (session === ttsSessionRef.current) {
        stopSpeaking();
        setError(cause instanceof Error ? cause.message : "Sesli yanıt üretilemedi.");
      }
    }
  };

  const handleCopy = async (content: string, index: number) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 1800);
    } catch {
      /* sessizce geç */
    }
  };

  const sendMessage = async (text: string, mode?: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    const time = nowTime();
    const next: Message[] = [...messages, { role: "user", content: trimmed, time }];
    setInput("");
    setBusy(true);
    setError("");
    setMessages([...next, { role: "assistant", content: "", time }]);
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      // Karşılama mesajı modele gönderilmez; son 8 mesaj yeterli bağlam.
      const history = next.filter((m) => m !== starter[0] && m.time !== "Şimdi").slice(-8)
        .map(({ role, content }) => ({ role, content }));
      await streamChat(
        `${API_BASE}/api/forex/chat`,
        history,
        (delta) =>
          setMessages((current) => [
            ...current.slice(0, -1),
            { ...current[current.length - 1], role: "assistant", content: (current[current.length - 1]?.content || "") + delta, time },
          ]),
        mode ? { mode } : {},
        {
          signal: controller.signal,
          onEvent: ({ event, data }) => {
            if (event !== "step") return;
            const d = data as { id?: unknown; label?: unknown; status?: unknown; text?: unknown };
            const step: ResearchStep = {
              id: String(d.id ?? ""),
              label: String(d.label ?? ""),
              status: d.status === "done" || d.status === "error" ? d.status : "running",
              text: typeof d.text === "string" ? d.text : undefined,
            };
            if (!step.id) return;
            setMessages((current) => {
              const last = current[current.length - 1];
              if (!last || last.role !== "assistant") return current;
              const steps = [...(last.steps ?? [])];
              const at = steps.findIndex((x) => x.id === step.id);
              if (at >= 0) steps[at] = step; else steps.push(step);
              return [...current.slice(0, -1), { ...last, steps }];
            });
          },
        },
      );
    } catch (e) {
      if (controller.signal.aborted) return;
      const message = e instanceof Error ? e.message : "Yanıt alınamadı, tekrar dene.";
      setError(message);
      setMessages([...next, { role: "assistant", content: message, time }]);
    } finally {
      if (streamAbortRef.current === controller) streamAbortRef.current = null;
      setBusy(false);
    }
  };

  const send = (event?: FormEvent) => {
    event?.preventDefault();
    void sendMessage(input);
  };

  const startNewChat = () => {
    streamAbortRef.current?.abort();
    stopSpeaking();
    setMessages(starter);
    setInput("");
    setError("");
  };

  const showWelcome = messages.length <= 1;

  return (
    <div className="chat-page">
      <div className="chat-layout" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
        <Card className="chat-conversation">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-3 mb-2 border-b border-bunker-800">
            <div>
              <h1 className="font-mono text-sm font-bold text-white tracking-wide">FOREX ASİSTANI</h1>
              <p className="text-[11px] text-bunker-muted">
                {username ? `${username} · ` : ""}Altın, Bitcoin ve Forex · demo hesap
              </p>
            </div>
            <Button variant="secondary" onClick={startNewChat} className="text-xs px-2.5 py-1.5 font-mono">
              Yeni sohbet
            </Button>
          </div>

          <ScheduledJobs />

          <div className="chat-messages flex-1 overflow-y-auto space-y-3 p-1">
            {messages.map((message, index) => {
              const isUser = message.role === "user";
              return (
                <div key={index} className={`chat-message group flex gap-2.5 ${isUser ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[92%] sm:max-w-[85%] flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                    {message.time && (
                      <span className="mb-1 px-1 text-[11px] font-mono text-bunker-muted">{message.time}</span>
                    )}
                    <div
                      className={`chat-bubble rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                        isUser
                          ? "bg-gradient-to-br from-cyan-950/40 to-bunker-900 border border-cyan-400/30 text-cyan-100 rounded-tr-sm"
                          : "bg-bunker-900/95 border border-bunker-700/70 text-slate-200 rounded-tl-sm"
                      }`}
                    >
                      {!isUser && message.steps && message.steps.length > 0 && (
                        <ResearchPanel steps={message.steps} live={busy && index === messages.length - 1} />
                      )}
                      <MarkdownMessage content={message.content} colorful={!isUser} />
                      {!isUser && message.content && index > 0 && (
                        <div className="flex items-center justify-end gap-1.5 mt-2.5 pt-2 border-t border-bunker-800/80 text-xs">
                          <button type="button" onClick={() => handleCopy(message.content, index)} className="chat-action-btn" title="Metni kopyala">
                            {copiedIndex === index ? "Kopyalandı" : "Kopyala"}
                          </button>
                          <button
                            type="button"
                            onClick={() => (speakingIndex === index ? stopSpeaking() : void speak(message.content, index))}
                            className="chat-action-btn"
                            title={speakingIndex === index ? "Seslendirmeyi durdur" : "Seslendir"}
                          >
                            {speakingIndex === index ? "Durdur" : "Dinle"}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}

            {busy && messages[messages.length - 1]?.content === "" && !(messages[messages.length - 1]?.steps?.length) && (
              <AppLoader variant="card" label="Araştırma başlıyor…" sublabel="Teknik analiz, ekonomik takvim ve haberler taranıyor" className="!p-5 !bg-bunker-900/80" />
            )}
            <div ref={endRef} />
          </div>

          <div className="pt-2">
            <div className="mb-2 flex gap-1.5 overflow-x-auto pb-1" aria-label="Hazır sorular">
              {QUICK_PROMPTS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => void sendMessage(item.prompt, item.mode)}
                  disabled={busy}
                  className={`shrink-0 min-h-9 px-3 py-1.5 rounded-full border text-xs transition-colors disabled:opacity-40 ${
                    item.mode
                      ? "bg-cyan-500/15 border-cyan-400/60 text-cyan-200 font-bold hover:bg-cyan-500/25"
                      : "bg-bunker-900/90 border-bunker-700/80 hover:border-cyan-400/60 hover:text-cyan-300 text-slate-200"
                  }`}
                  title={item.mode ? "Forex, Bitcoin, Altın ve endeksleri (Nasdaq, Dow) tarar; uygun fırsat varsa kayıtlı DEMO hesapta işlem açar" : undefined}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <form onSubmit={send}>
              <div className="flex items-end gap-2 p-2 bg-bunker-900/95 border border-bunker-700/80 rounded-xl focus-within:border-cyan-400/70 transition-colors">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={showWelcome ? "Örn. Altın için bugün ne düşünüyorsun?" : "Bir soru sor…"}
                  rows={1}
                  disabled={busy}
                  aria-label="Mesaj"
                  className="flex-1 bg-transparent border-0 text-white placeholder-bunker-muted resize-none text-sm py-2 px-1 max-h-36 min-h-[38px] leading-relaxed outline-none"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      if (!busy && input.trim()) void sendMessage(input);
                    }
                  }}
                />
                {busy ? (
                  <Button variant="danger" type="button" onClick={() => streamAbortRef.current?.abort()} className="text-xs px-3 py-2 shrink-0 font-mono font-bold">
                    Durdur
                  </Button>
                ) : (
                  <Button variant="primary" type="submit" disabled={!input.trim()} className="text-xs px-3.5 py-2 shrink-0 font-mono font-bold disabled:opacity-40">
                    Gönder
                  </Button>
                )}
              </div>
            </form>
            {error && <p role="alert" className="mt-2 text-xs text-neon-red font-mono bg-red-950/20 border border-red-500/30 p-2 rounded">{error}</p>}
            <p className="mt-1.5 px-1 text-[10px] text-bunker-muted">
              Yorumlar canlı fiyat verisi, ekonomik takvim ve haber başlıklarına dayanır; yatırım tavsiyesi değildir.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}

interface ScheduledJob {
  id: number;
  due_ts: number;
  due_label: string;
  kind: string;
  status: string;
  summary: string;
  result?: string | null;
  done_at?: number | null;
}

const JOB_STATUS_TR: Record<string, string> = {
  pending: "Bekliyor", done: "Tamamlandı", missed: "Kaçırıldı", failed: "Başarısız", cancelled: "İptal",
};

/** Sohbetten kurulan hatırlatıcı / zamanlı kapatma işleri: bekleyenler + son 12 saatte sonuçlananlar. */
function ScheduledJobs() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [dismissed, setDismissed] = useState<number[]>(() => {
    try {
      return JSON.parse(window.localStorage.getItem("dismissedJobs") || "[]") as number[];
    } catch {
      return [];
    }
  });

  const dismiss = (id: number) => {
    const next = [...dismissed, id].slice(-100);
    setDismissed(next);
    try {
      window.localStorage.setItem("dismissedJobs", JSON.stringify(next));
    } catch {
      /* depolama kapalı: yalnız bu oturumda gizlenir */
    }
  };

  const load = async () => {
    try {
      const r = await apiRequest(`${API_BASE}/api/scheduled`);
      if (!r.ok) return;
      const body = (await r.json()) as { jobs?: ScheduledJob[] };
      setJobs(body.jobs ?? []);
      setNow(Date.now() / 1000);
    } catch {
      /* ağ hatası: kart sessizce eski halini korur */
    }
  };

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 20000);
    return () => clearInterval(t);
  }, []);

  const cancel = async (id: number) => {
    await apiRequest(`${API_BASE}/api/scheduled/${id}/cancel`, { method: "POST" });
    void load();
  };

  // Bekleyenler hep görünür. Sonuçlananlar yalnız 10 dk görünür ve ✕ ile hemen kapatılabilir (kalıcı gizlenir).
  const recent = now - 10 * 60;
  const visible = jobs.filter(
    (j) => j.status === "pending" || ((j.done_at ?? 0) > recent && j.status !== "cancelled" && !dismissed.includes(j.id)),
  );
  if (visible.length === 0) return null;

  return (
    <div className="shrink-0 rounded-lg border border-bunker-700/80 bg-bunker-900/80 px-2.5 py-1.5" aria-label="Zamanlanmış işler">
      <ul className="max-h-[4.5rem] space-y-1 overflow-y-auto">
        {visible.map((j) => (
          <li key={j.id} className="flex items-center justify-between gap-2 text-[11px]">
            <div className="min-w-0 flex-1">
              <p className="truncate text-slate-200" title={`${j.summary}${j.result ? ` — ${j.result}` : ""}`}>
                <span aria-hidden="true">🕒 </span>
                <span className={j.status === "pending" ? "text-cyan-300" : j.status === "done" ? "text-emerald-300" : "text-amber-300"}>
                  {JOB_STATUS_TR[j.status] ?? j.status}
                </span>{" "}
                · {j.due_label} · {j.summary}
              </p>
              {j.result && <p className="truncate text-[10px] text-bunker-muted" title={j.result}>{j.result}</p>}
            </div>
            {j.status === "pending" ? (
              <button type="button" onClick={() => void cancel(j.id)} className="shrink-0 rounded-md border border-rose-400/40 px-2 py-0.5 text-[10px] text-rose-300 hover:bg-rose-500/10">
                İptal
              </button>
            ) : (
              <button type="button" onClick={() => dismiss(j.id)} aria-label="Kapat" title="Kapat" className="shrink-0 rounded-md border border-bunker-700 px-2 py-0.5 text-[10px] text-bunker-muted hover:text-white">
                ✕
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ChatPage() {
  return <ChatPageInner />;
}
