"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { streamChat } from "../lib/streamChat";
import MarkdownMessage from "../components/MarkdownMessage";
import { Button, Card } from "../components/ui";
import { useAuth } from "../lib/auth";
import AppLoader from "../components/AppLoader";

type Message = {
  role: "user" | "assistant";
  content: string;
  time?: string;
};

// Hazır sorular yalnız Altın, Bitcoin ve Forex içindir; her biri tek tıkla sorulur.
const QUICK_PROMPTS = [
  { label: "Altın şimdi nasıl?", prompt: "Altın (XAUUSD) şu an nasıl görünüyor? İşlem için uygun mu, beklemek mi mantıklı?" },
  { label: "Bitcoin ne yapıyor?", prompt: "Bitcoin şu an nasıl görünüyor? Kısa vadede yön ve dikkat edilecek nokta ne?" },
  { label: "Bugün hangi pariteler?", prompt: "Şu an en fırsatlı görünen Forex pariteleri hangileri? Neden?" },
  { label: "Yaklaşan haberler", prompt: "Önümüzdeki saatlerde işlemleri etkileyecek önemli ekonomik veriler var mı? Ne yapmalıyım?" },
  { label: "Son açıklanan veriler", prompt: "Az önce açıklanan ekonomik veriler neydi ve hangi pariteleri nasıl etkiledi?" },
  { label: "Dolar durumu", prompt: "Dolar şu an güçlü mü zayıf mı? Bu Altın ve EURUSD için ne anlama geliyor?" },
  { label: "Açık işlemlerim", prompt: "Açık pozisyonlarım nasıl gidiyor? Dikkat etmem gereken bir şey var mı?" },
] as const;

const starter: Message[] = [
  {
    role: "assistant",
    content: "Merhaba. Altın, Bitcoin ve Forex hakkında sorabilirsin: güncel görünüm, yaklaşan haberler, açıklanan verilerin etkisi veya açık işlemlerin.",
    time: "Şimdi",
  },
];

// v2: eski kripto dönemi sohbet geçmişi yeni sayfada görünmesin.
const CHAT_STORAGE_KEY = "scalperagent:forexchat:v2";

const nowTime = () => new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });

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
      const requests = chunks.map(async (text) => {
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
      });
      const play = async (i: number) => {
        if (session !== ttsSessionRef.current) return;
        const url = await requests[i];
        ttsUrlsRef.current.push(url);
        if (session !== ttsSessionRef.current) { URL.revokeObjectURL(url); return; }
        const audio = new Audio(url);
        ttsAudioRef.current = audio;
        audio.onended = () => {
          URL.revokeObjectURL(url);
          if (session !== ttsSessionRef.current) return;
          if (i + 1 < requests.length) void play(i + 1); else setSpeakingIndex(null);
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

  const sendMessage = async (text: string) => {
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
            { role: "assistant", content: (current[current.length - 1]?.content || "") + delta, time },
          ]),
        {},
        { signal: controller.signal },
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

            {busy && messages[messages.length - 1]?.content === "" && (
              <AppLoader variant="card" label="Piyasa verileri okunuyor…" sublabel="Radar, takvim ve açık işlemler kontrol ediliyor" className="!p-5 !bg-bunker-900/80" />
            )}
            <div ref={endRef} />
          </div>

          <div className="pt-2">
            <div className="mb-2 flex gap-1.5 overflow-x-auto pb-1" aria-label="Hazır sorular">
              {QUICK_PROMPTS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => void sendMessage(item.prompt)}
                  disabled={busy}
                  className="shrink-0 min-h-9 px-3 py-1.5 rounded-full bg-bunker-900/90 border border-bunker-700/80 hover:border-cyan-400/60 hover:text-cyan-300 text-slate-200 text-xs transition-colors disabled:opacity-40"
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
              Yorumlar mevcut radar, takvim ve hesap verisine dayanır; yatırım tavsiyesi değildir.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return <ChatPageInner />;
}
