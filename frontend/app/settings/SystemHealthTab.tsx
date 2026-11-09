"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import ApiLatencyPanel from "./ApiLatencyPanel";

export default function SystemHealthTab() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const liveStatus = useLiveStatus();
  const load = useCallback(() => apiFetch("/api/system/health")
    .then((result) => { setData(result); setError(""); })
    .catch(() => setError("Sağlık verisi alınamadı")), []);

  useLiveMessages(useCallback((message: any) => {
    if (["reset", "trade_updated"].includes(message.type)) load();
  }, [load]));

  useEffect(() => {
    load();
  }, [load]);
  useVisibleInterval(load, 10_000);

  const healthy = data?.status === "ok" && liveStatus === "open";
  return <section aria-label="Sistem sağlığı" className="space-y-4">
    <div>
      <p className="eyebrow text-neon-green">SİSTEM SAĞLIĞI</p>
      <p className="mt-1 text-xs text-bunker-muted">Market data · WebSocket · veritabanı · LLM. 10 saniyede bir yenilenir.</p>
    </div>
    {error && <div className="card border-neon-red/40 bg-neon-red/5 text-neon-red">{error}</div>}
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {[["Backend", data?.status || "—"], ["Canlı kanal", liveStatus === "open" ? "bağlı" : liveStatus], ["Semboller", data?.market?.symbols], ["WS istemcileri", data?.websocket_clients]].map(([label, value]) => <div className="card" key={label}><p className="eyebrow">{label}</p><p className={`mt-2 font-mono text-2xl ${label === "Backend" || label === "Canlı kanal" ? healthy ? "text-neon-green" : "text-yellow-300" : "text-white"}`}>{value ?? "—"}</p></div>)}
    </div>
    <div className="grid gap-4 md:grid-cols-2">
      <div className="card"><p className="eyebrow">MARKET DATA</p><p className="mt-3 font-mono text-sm">Ticker: {data?.market?.tickers ?? "—"}</p><p className="mt-2 font-mono text-sm">Max ticker yaşı: {data?.market?.max_ticker_age_sec == null ? "—" : `${data.market.max_ticker_age_sec.toFixed(1)} sn`}</p><p className="mt-2 font-mono text-sm">Timeframe: {data?.market?.timeframes?.join(", ") || "—"}</p></div>
      <div className="card"><p className="eyebrow">ALTYAPI / RİSK</p><p className="mt-3 font-mono text-sm">DB: {data?.database?.status || "—"}</p><p className="mt-2 font-mono text-sm">Açık pozisyon: {data?.portfolio?.open_positions ?? "—"} / {data?.portfolio?.max_open_positions ?? "—"}</p><p className="mt-2 font-mono text-sm">LLM: {data?.llm?.active ? "aktif" : "pasif veya yapılandırılmamış"}</p></div>
    </div>
    {/* VERİ KAYNAKLARI (2026-11-09): takvim/COT kaynaklarının durumu GÖRÜNÜR
        olmalı. Kullanıcı "veri yok" gördüğünde nedenini panelde bulabilmeli;
        Investing 403 yiyorsa veya FMP anahtarı yoksa burada yazıyor. */}
    <div className="grid gap-4 md:grid-cols-2">
      <div className="card">
        <p className="eyebrow">EKONOMİK TAKVİM KAYNAĞI</p>
        {(() => {
          const src = data?.economic_calendar_source || {};
          const fmp = src.fmp || {};
          return (
            <>
              <p className="mt-3 font-mono text-sm">
                Investing.com:{" "}
                <span className={src.blocked ? "text-yellow-300" : "text-neon-green"}>
                  {src.blocked ? `dinleniyor (${Math.round((src.remaining_sec || 0) / 60)} dk)` : "açık"}
                </span>
                {src.reason ? <span className="text-bunker-muted"> · {src.reason}</span> : null}
              </p>
              {(() => {
                const ff = src.forexfactory_html || {};
                return (
                  <p className="mt-2 font-mono text-sm">
                    ForexFactory HTML (aynı gün değer):{" "}
                    <span className={ff.blocked ? "text-yellow-300" : "text-neon-green"}>
                      {ff.blocked ? `dinleniyor (${Math.round((ff.remaining_sec || 0) / 60)} dk)` : "erişilebilir"}
                    </span>
                    {ff.last_count ? <span className="text-bunker-muted"> · son tur {ff.last_count} olay</span> : null}
                    {ff.profile ? <span className="text-bunker-muted"> · parmak izi {ff.profile}</span> : null}
                  </p>
                );
              })()}
              <p className="mt-2 font-mono text-sm">
                FMP (aynı gün değer):{" "}
                <span className={fmp.configured ? "text-neon-green" : "text-yellow-300"}>
                  {fmp.configured ? "yapılandırıldı" : "anahtar yok"}
                </span>
                {fmp.configured && fmp.last_count != null ? (
                  <span className="text-bunker-muted"> · son tur {fmp.last_count} olay</span>
                ) : null}
              </p>
              {fmp.configured && fmp.last_error ? (
                <p className="mt-1 font-mono text-2xs text-neon-red">{String(fmp.last_error).slice(0, 120)}</p>
              ) : null}
              <p className="mt-2 text-2xs text-bunker-muted">
                TradingView her zaman açık ama açıklanan değerleri 1-2 gün gecikmeli verir; aynı gün değer
                için anahtarlı kaynak (FMP) gerekir.
              </p>
            </>
          );
        })()}
      </div>
      <div className="card">
        <p className="eyebrow">COT POZİSYONLANMA</p>
        {(() => {
          const cot = data?.cot || {};
          const n = Object.keys(cot.currencies || {}).length;
          return (
            <>
              <p className="mt-3 font-mono text-sm">
                Durum:{" "}
                <span className={cot.available ? "text-neon-green" : "text-yellow-300"}>
                  {cot.available ? `var · ${n} para birimi` : "artefakt yok"}
                </span>
              </p>
              <p className="mt-2 font-mono text-sm">
                Rapor: <span className="text-white">{cot.report_date || "—"}</span>
                {cot.age_days != null ? <span className="text-bunker-muted"> · {Number(cot.age_days).toFixed(1)} gün</span> : null}
                {cot.stale ? <span className="text-yellow-300"> · BAYAT</span> : null}
              </p>
              <p className="mt-2 text-2xs text-bunker-muted">
                Ayarlar → &quot;COT verisini indir&quot; düğmesiyle tazelenir; 9 günü geçerse sunucu kendi indirir.
                Artefakt yoksa LLM &quot;COT verisi yok&quot; der (uydurma yapılmaz).
              </p>
            </>
          );
        })()}
      </div>
    </div>
    <ApiLatencyPanel />
  </section>;
}
