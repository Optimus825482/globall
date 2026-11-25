"use client";

// ============================================================================
// BİRLEŞİK MARKET SENTIMENT KARTI
// Bileşik Endeks ve Perakende Konumlanma (Myfxbook) kartlarını tek kompakt
// kapsayıcıda sunar; varsayılan olarak "Bileşik Endeks" sekmesi açıktır ve
// daralt/genişlet anahtarıyla dikey kapladığı alan en aza indirilebilir.
// ============================================================================

import React, { useId, useState } from "react";
import { Card } from "./ui";
import SentimentGaugeCard from "./SentimentGaugeCard";
import RetailSentimentCard from "./RetailSentimentCard";

type SentimentTab = "composite" | "retail";

const TABS: ReadonlyArray<{ id: SentimentTab; label: string }> = [
  { id: "composite", label: "Bileşik Endeks" },
  { id: "retail", label: "Perakende (Myfxbook)" },
];

export default function UnifiedSentimentCard() {
  const [activeTab, setActiveTab] = useState<SentimentTab>("composite");
  const [expanded, setExpanded] = useState<boolean>(true);
  const baseId = useId();
  const panelId = `${baseId}-panel`;

  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") {
      return;
    }
    e.preventDefault();
    let nextIndex = index;
    if (e.key === "ArrowRight") nextIndex = (index + 1) % TABS.length;
    else if (e.key === "ArrowLeft") nextIndex = (index - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") nextIndex = 0;
    else if (e.key === "End") nextIndex = TABS.length - 1;

    const nextTab = TABS[nextIndex];
    setActiveTab(nextTab.id);
    if (!expanded) setExpanded(true);
    document.getElementById(`${baseId}-tab-${nextTab.id}`)?.focus();
  };

  return (
    <Card className="!p-0 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-bunker-800 px-4 py-2.5 sm:px-5">
        <div className="flex items-center gap-2 min-w-0">
          <p className="eyebrow">Market Sentiment</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div
            role="tablist"
            aria-label="Market sentiment görünümü"
            className="inline-flex items-center rounded-lg border border-bunker-800 bg-bunker-950/70 p-0.5"
          >
            {TABS.map((tab, index) => {
              const selected = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  id={`${baseId}-tab-${tab.id}`}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={panelId}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => {
                    setActiveTab(tab.id);
                    if (!expanded) setExpanded(true);
                  }}
                  onKeyDown={(e) => handleTabKeyDown(e, index)}
                  className={`px-2.5 py-1.5 min-h-9 sm:min-h-0 rounded-md font-mono text-2xs sm:text-xs font-bold transition-colors ${
                    selected
                      ? "bg-blue-500/20 text-cyan-300 border border-blue-400/50"
                      : "text-bunker-muted hover:text-white border border-transparent"
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={panelId}
            onClick={() => setExpanded((prev) => !prev)}
            className="px-2.5 py-1.5 min-h-9 sm:min-h-0 rounded-lg border border-bunker-700 bg-bunker-800/80 font-mono text-2xs font-semibold text-bunker-muted hover:text-white transition-colors"
          >
            {expanded ? "Daralt" : "Genişlet"}
          </button>
        </div>
      </div>

      {expanded && (
        <div
          id={panelId}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${activeTab}`}
        >
          {activeTab === "composite" ? (
            <SentimentGaugeCard embedded />
          ) : (
            <RetailSentimentCard embedded />
          )}
        </div>
      )}
    </Card>
  );
}
