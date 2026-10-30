"use client";

import React, { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function cleanProviderMarkdown(value: string) {
  const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
  return lines
    .filter((line, index) => {
      const trimmed = line.trim();
      // Some providers emit decorative table separators as separate lines.
      // They are not valid GFM rows and prevent the parser from recognizing the table.
      if (!/^[|\s-]+$/.test(trimmed) || !trimmed.includes("|")) return true;
      const cells = trimmed.replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
      // Keep valid GFM separators such as | --- | --- |.
      if (cells.some(cell => /^:?-{3,}:?$/.test(cell))) return true;
      const previous = lines[index - 1]?.includes("|");
      const next = lines[index + 1]?.includes("|");
      return !(previous && next);
    })
    .join("\n")
    // ReDoS önlemi: Unicode property escape (\p{L}) yerine basit [a-zA-Z] kullan
    // (Türkçe karakterler için karakter sınıfı genişletildi)
    .replace(/([!?;:])(?=[a-zA-ZçğıöüşÇĞİÖÜŞ])/g, "$1 ")
    .replace(/\. (?=[a-zA-ZçğıöüşÇĞİÖÜŞ])/g, ". ");
}

// --- Renkli (yapılandırılmış) mod: Forex asistanı yanıtları ---------------------
const textOf = (node: React.ReactNode): string =>
  React.Children.toArray(node).map((c) => (typeof c === "string" || typeof c === "number" ? String(c) : React.isValidElement<{ children?: React.ReactNode }>(c) ? textOf(c.props.children) : "")).join("");

type Tone = "buy" | "sell" | "wait" | "info";
const toneOf = (text: string): Tone => {
  const t = text.toLocaleUpperCase("tr-TR");
  if (/(BUY|ALIŞ|YUKARI|YÜKSEL|GÜÇLÜ|BOĞA)/.test(t) && !/(SELL|SATIŞ|AŞAĞI|DÜŞ)/.test(t)) return "buy";
  if (/(SELL|SATIŞ|AŞAĞI|DÜŞ|ZAYIF|AYI)/.test(t) && !/(BUY|ALIŞ|YUKARI|YÜKSEL)/.test(t)) return "sell";
  if (/BEKLE|NÖTR|İZLE|BELİRSİZ|TEMKİN|YETERSİZ/.test(t)) return "wait";
  return "info";
};
const TONE_BOX: Record<Tone, string> = {
  buy: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
  sell: "border-rose-500/50 bg-rose-500/10 text-rose-300",
  wait: "border-amber-500/50 bg-amber-500/10 text-amber-300",
  info: "border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
};
const TONE_TEXT: Record<Tone, string> = {
  buy: "text-emerald-400", sell: "text-rose-400", wait: "text-amber-300", info: "text-cyan-300",
};
// Bölüm başlığına göre renk: Dikkat/Risk uyarı tonu, Neden bilgi tonu.
const sectionTone = (text: string): Tone => {
  const t = text.toLocaleLowerCase("tr-TR");
  if (/risk/.test(t)) return "sell";
  if (/dikkat|haber|uyarı/.test(t)) return "wait";
  if (/öneri|ne yap/.test(t)) return "buy";
  return "info";
};

function colorComponents() {
  return {
    h2: ({ children }: { children?: React.ReactNode }) => {
      const tone = toneOf(textOf(children));
      return <h2 className={`mb-2 rounded-lg border px-3 py-2 text-base font-bold leading-snug ${TONE_BOX[tone]}`}>{children}</h2>;
    },
    h3: ({ children }: { children?: React.ReactNode }) => {
      const tone = sectionTone(textOf(children));
      return <h3 className={`mt-3 mb-1 border-l-2 pl-2 text-xs font-bold uppercase tracking-wider ${TONE_TEXT[tone]} ${tone === "sell" ? "border-rose-500" : tone === "wait" ? "border-amber-400" : tone === "buy" ? "border-emerald-500" : "border-cyan-400"}`}>{children}</h3>;
    },
    strong: ({ children }: { children?: React.ReactNode }) => {
      const tone = toneOf(textOf(children));
      return <strong className={`font-bold ${tone === "info" ? "text-white" : TONE_TEXT[tone]}`}>{children}</strong>;
    },
    ul: ({ children }: { children?: React.ReactNode }) => <ul className="space-y-1.5 pl-1">{children}</ul>,
    li: ({ children }: { children?: React.ReactNode }) => (
      <li className="flex gap-2 leading-relaxed"><span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-400" /><span className="min-w-0">{children}</span></li>
    ),
    p: ({ children }: { children?: React.ReactNode }) => <p className="my-1.5 leading-relaxed">{children}</p>,
  };
}

function MarkdownMessage({ content, colorful = false }: { content: string; colorful?: boolean }) {
  return <div className="message-markdown">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h2: ({ children }) => <h2 className="pt-2 text-base font-bold text-white">{children}</h2>,
        h3: ({ children }) => <h3 className="pt-2 font-semibold text-neon-green">{children}</h3>,
        table: ({ children }) => <div className="message-table-wrap" role="region" aria-label="LLM tablosu" tabIndex={0}><table className="message-table">{children}</table></div>,
        th: ({ children }) => <th>{children}</th>,
        td: ({ children }) => <td>{children}</td>,
        code: ({ children }) => <code className="rounded bg-black/30 px-1 text-yellow-200">{children}</code>,
        // Renkli mod en sonda: yukarıdaki varsayılanların üzerine yazar.
        ...(colorful ? colorComponents() : {}),
      }}
    >{cleanProviderMarkdown(content)}</ReactMarkdown>
  </div>;
}

// Chat input changes re-render the parent; avoid reparsing every previous
// assistant message on each keystroke.
export default memo(MarkdownMessage);
