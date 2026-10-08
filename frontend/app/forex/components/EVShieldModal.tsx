"use client";

// ============================================================================
// EV KALKANI YÖNETİM MODALI (EVShieldModal)
// Akut zarar veya düşük kazanma oranı nedeniyle otomatik dinlenmeye alınan
// sembolleri listeler; kullanıcının sembol bazında kalkanı o gün için iptal
// etmesine, 24 saat muafiyet vermesine veya sicilini sıfırlamasına olanak tanır.
// ============================================================================

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { apiFetch } from "../../lib/api";
import { useTheme } from "../../lib/theme";

export interface EVShieldSymbolItem {
  symbol: string;
  display: string;
  is_blocked: boolean;
  raw_blocked: boolean;
  is_overridden: boolean;
  override_until?: number | null;
  override_until_str?: string | null;
  override_remaining_sec?: number;
  n: number;
  wins: number;
  losses: number;
  win_rate: number;
  net_usd: number;
  reason: string;
  is_exempt_symbol?: boolean;
  is_allowed?: boolean;
}

export interface EVShieldStatusResponse {
  enabled: boolean;
  window_hours: number;
  risk_floor_usd: number;
  min_trades: number;
  max_win_rate: number;
  blocked_count: number;
  overridden_count: number;
  symbols: EVShieldSymbolItem[];
}

interface EVShieldModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUpdated?: () => void;
}

export default function EVShieldModal({ isOpen, onClose, onUpdated }: EVShieldModalProps) {
  const { isLight } = useTheme();
  const [loading, setLoading] = useState<boolean>(false);
  const [actionLoadingSymbol, setActionLoadingSymbol] = useState<string | null>(null);
  const [data, setData] = useState<EVShieldStatusResponse | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [filterTab, setFilterTab] = useState<"all" | "blocked" | "overridden">("all");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Durum verisini yükle
  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true);
      const res = (await apiFetch("/api/forex/ev-shield")) as EVShieldStatusResponse;
      if (res && Array.isArray(res.symbols)) {
        setData(res);
      }
    } catch (err: any) {
      console.error("EV Shield status error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchStatus();
      setFeedback(null);
      // Açıkken her 10 saniyede bir güncelle
      const timer = setInterval(() => {
        if (!document.hidden) fetchStatus();
      }, 10000);
      return () => clearInterval(timer);
    }
  }, [isOpen, fetchStatus]);

  // Eylem gerçekleştir (Muafiyet / Sıfırlama)
  const handleAction = async (symbol: string, action: "bypass_today" | "bypass_24h" | "restore" | "reset_history") => {
    try {
      setActionLoadingSymbol(symbol);
      setFeedback(null);

      const res = (await apiFetch("/api/forex/ev-shield/override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, action }),
      })) as { success: boolean; message: string };

      if (res && res.success) {
        setFeedback({
          type: "success",
          message: res.message || "İşlem başarıyla uygulandı.",
        });
        await fetchStatus();
        if (onUpdated) onUpdated();
      } else {
        setFeedback({
          type: "error",
          message: res?.message || "İşlem gerçekleştirilemedi.",
        });
      }
    } catch (err: any) {
      setFeedback({
        type: "error",
        message: err?.message || "Bağlantı hatası oluştu.",
      });
    } finally {
      setActionLoadingSymbol(null);
    }
  };

  // Tüm kalkanları sıfırla
  const handleResetAll = async () => {
    if (!window.confirm("Tüm sembollerin EV Kalkanı kayıtlarını ve muafiyetlerini sıfırlamak istediğinize emin misiniz?")) {
      return;
    }
    try {
      setLoading(true);
      setFeedback(null);
      const res = (await apiFetch("/api/forex/ev-shield/reset-all", {
        method: "POST",
      })) as { success: boolean; message: string };
      if (res && res.success) {
        setFeedback({
          type: "success",
          message: "Tüm sembollerin EV Kalkanı geçmişi sıfırlandı.",
        });
        await fetchStatus();
        if (onUpdated) onUpdated();
      }
    } catch (err: any) {
      setFeedback({
        type: "error",
        message: err?.message || "Sıfırlama sırasında hata oluştu.",
      });
    } finally {
      setLoading(false);
    }
  };

  // Filtrelenmiş sembol listesi
  const filteredSymbols = useMemo(() => {
    if (!data?.symbols) return [];
    let list = data.symbols;

    if (filterTab === "blocked") {
      list = list.filter((s) => s.is_blocked);
    } else if (filterTab === "overridden") {
      list = list.filter((s) => s.is_overridden);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.trim().toUpperCase();
      list = list.filter(
        (s) =>
          s.symbol.toUpperCase().includes(q) ||
          s.display.toUpperCase().includes(q) ||
          s.reason.toUpperCase().includes(q)
      );
    }

    return list;
  }, [data, filterTab, searchQuery]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-black/80 backdrop-blur-md animate-in fade-in duration-200"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl border shadow-2xl overflow-hidden transition-colors ${
          isLight
            ? "bg-white text-slate-900 border-slate-300 shadow-[0_20px_50px_rgba(0,0,0,0.15)]"
            : "bg-slate-950 text-slate-100 border-slate-800 shadow-[0_20px_60px_rgba(0,0,0,0.8)]"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Üst Başlık Barı */}
        <div
          className={`flex items-center justify-between px-5 py-4 border-b shrink-0 ${
            isLight ? "bg-slate-50 border-slate-200" : "bg-slate-900/90 border-slate-800"
          }`}
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-xl shadow-inner">
              🛡️
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className={`text-lg font-black tracking-tight ${isLight ? "text-slate-900" : "text-white"}`}>
                  Sembol EV Kalkanı & Muafiyet Listesi
                </h2>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                    data?.enabled
                      ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/40"
                      : "bg-rose-500/20 text-rose-600 dark:text-rose-400 border border-rose-500/40"
                  }`}
                >
                  {data?.enabled ? "Kalkan Devrede" : "Devre Dışı"}
                </span>
              </div>
              <p className={`text-xs mt-0.5 font-medium ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                Zarar üreten sembollerin otomatik dinlenmeye alınması ve kullanıcı muafiyet kontrolleri
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={fetchStatus}
              disabled={loading}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-colors flex items-center gap-1.5 ${
                isLight
                  ? "bg-slate-100 hover:bg-slate-200 text-slate-800 border-slate-300"
                  : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
              }`}
              title="Yenile"
            >
              <span className={loading ? "animate-spin" : ""}>🔄</span>
              <span>Yenile</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              className={`w-9 h-9 rounded-xl border flex items-center justify-center text-sm font-bold transition-all ${
                isLight
                  ? "bg-slate-100 hover:bg-slate-200 text-slate-700 hover:text-slate-900 border-slate-300"
                  : "bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white border-slate-700"
              }`}
              title="Kapat"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Özet Kartları & Parametreler */}
        <div
          className={`px-5 py-3.5 border-b shrink-0 grid grid-cols-2 sm:grid-cols-4 gap-2.5 sm:gap-3 ${
            isLight ? "bg-slate-100/70 border-slate-200" : "bg-slate-900/40 border-slate-800/80"
          }`}
        >
          {/* Dinlenmede (Bloke) */}
          <div
            className={`p-3 rounded-xl border transition-all ${
              (data?.blocked_count ?? 0) > 0
                ? isLight
                  ? "bg-rose-50 border-rose-300 ring-1 ring-rose-200"
                  : "bg-rose-950/30 border-rose-800/60 ring-1 ring-rose-700/40"
                : isLight
                ? "bg-white border-slate-200"
                : "bg-slate-900/60 border-slate-800"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className={`text-[11px] font-bold uppercase tracking-wider ${isLight ? "text-slate-700" : "text-slate-400"}`}>
                Dinlenmede (Bloke)
              </span>
              <span className="text-base">🛑</span>
            </div>
            <div className="flex items-baseline gap-2 mt-1">
              <span
                className={`text-2xl font-black ${
                  (data?.blocked_count ?? 0) > 0
                    ? isLight
                      ? "text-rose-600"
                      : "text-rose-400"
                    : isLight
                    ? "text-slate-800"
                    : "text-slate-200"
                }`}
              >
                {data?.blocked_count ?? 0}
              </span>
              <span className={`text-[11px] font-medium ${isLight ? "text-slate-600" : "text-slate-400"}`}>sembol</span>
            </div>
          </div>

          {/* Muaf Tutulanlar */}
          <div
            className={`p-3 rounded-xl border transition-all ${
              (data?.overridden_count ?? 0) > 0
                ? isLight
                  ? "bg-blue-50 border-blue-300"
                  : "bg-blue-950/30 border-blue-800/60"
                : isLight
                ? "bg-white border-slate-200"
                : "bg-slate-900/60 border-slate-800"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className={`text-[11px] font-bold uppercase tracking-wider ${isLight ? "text-slate-700" : "text-slate-400"}`}>
                Muaf Tutulanlar
              </span>
              <span className="text-base">⚡</span>
            </div>
            <div className="flex items-baseline gap-2 mt-1">
              <span
                className={`text-2xl font-black ${
                  (data?.overridden_count ?? 0) > 0
                    ? isLight
                      ? "text-blue-600"
                      : "text-blue-400"
                    : isLight
                    ? "text-slate-800"
                    : "text-slate-200"
                }`}
              >
                {data?.overridden_count ?? 0}
              </span>
              <span className={`text-[11px] font-medium ${isLight ? "text-slate-600" : "text-slate-400"}`}>sembol</span>
            </div>
          </div>

          {/* Aktif İzlenen Semboller */}
          <div
            className={`p-3 rounded-xl border ${
              isLight ? "bg-white border-slate-200" : "bg-slate-900/60 border-slate-800"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className={`text-[11px] font-bold uppercase tracking-wider ${isLight ? "text-slate-700" : "text-slate-400"}`}>
                Toplam Sembol
              </span>
              <span className="text-base">📈</span>
            </div>
            <div className="flex items-baseline gap-2 mt-1">
              <span className={`text-2xl font-black ${isLight ? "text-slate-900" : "text-white"}`}>
                {data?.symbols?.length ?? 0}
              </span>
              <span className={`text-[11px] font-medium ${isLight ? "text-slate-600" : "text-slate-400"}`}>sembol</span>
            </div>
          </div>

          {/* Kalkan Eşik Parametreleri */}
          <div
            className={`p-3 rounded-xl border ${
              isLight ? "bg-white border-slate-200 text-slate-800" : "bg-slate-900/60 border-slate-800 text-slate-200"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className={`text-[11px] font-bold uppercase tracking-wider ${isLight ? "text-slate-700" : "text-slate-400"}`}>
                Kural Kriteri
              </span>
              <span className="text-base">⚙️</span>
            </div>
            <div className="mt-1 space-y-0.5 text-[11px] font-semibold">
              <div className="flex justify-between">
                <span className={isLight ? "text-slate-600" : "text-slate-400"}>Pencere:</span>
                <span>{data?.window_hours ?? 24}s</span>
              </div>
              <div className="flex justify-between">
                <span className={isLight ? "text-slate-600" : "text-slate-400"}>Akut Eşik:</span>
                <span className="text-rose-500 font-bold">-${data?.risk_floor_usd?.toFixed(1) ?? "30.0"}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Geri Bildirim Bildirimi (Feedback toast) */}
        {feedback && (
          <div
            className={`px-5 py-2.5 text-xs font-bold flex items-center justify-between border-b ${
              feedback.type === "success"
                ? isLight
                  ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                  : "bg-emerald-950/60 text-emerald-300 border-emerald-800/80"
                : isLight
                ? "bg-rose-50 text-rose-800 border-rose-200"
                : "bg-rose-950/60 text-rose-300 border-rose-800/80"
            }`}
          >
            <div className="flex items-center gap-2">
              <span>{feedback.type === "success" ? "✅" : "⚠️"}</span>
              <span>{feedback.message}</span>
            </div>
            <button
              type="button"
              onClick={() => setFeedback(null)}
              className="hover:opacity-75 font-bold"
            >
              ✕
            </button>
          </div>
        )}

        {/* Filtre ve Arama Çubuğu */}
        <div
          className={`px-5 py-3 border-b flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 shrink-0 ${
            isLight ? "bg-slate-50/90 border-slate-200" : "bg-slate-900/30 border-slate-800"
          }`}
        >
          <div className="flex items-center gap-1.5 p-1 rounded-xl bg-slate-200/60 dark:bg-slate-900 border border-slate-300 dark:border-slate-800 shrink-0">
            <button
              type="button"
              onClick={() => setFilterTab("all")}
              className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                filterTab === "all"
                  ? isLight
                    ? "bg-white text-slate-900 shadow-sm"
                    : "bg-slate-800 text-white shadow-sm"
                  : isLight
                  ? "text-slate-700 hover:text-slate-900"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Tümü ({data?.symbols?.length ?? 0})
            </button>
            <button
              type="button"
              onClick={() => setFilterTab("blocked")}
              className={`px-3 py-1 rounded-lg text-xs font-bold transition-all flex items-center gap-1 ${
                filterTab === "blocked"
                  ? isLight
                    ? "bg-rose-600 text-white shadow-sm"
                    : "bg-rose-600 text-white shadow-sm"
                  : isLight
                  ? "text-rose-700 hover:text-rose-900"
                  : "text-rose-400 hover:text-rose-300"
              }`}
            >
              <span>🛑 Dinlenmede</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-black/20">
                {data?.blocked_count ?? 0}
              </span>
            </button>
            <button
              type="button"
              onClick={() => setFilterTab("overridden")}
              className={`px-3 py-1 rounded-lg text-xs font-bold transition-all flex items-center gap-1 ${
                filterTab === "overridden"
                  ? isLight
                    ? "bg-blue-600 text-white shadow-sm"
                    : "bg-blue-600 text-white shadow-sm"
                  : isLight
                  ? "text-blue-700 hover:text-blue-900"
                  : "text-blue-400 hover:text-blue-300"
              }`}
            >
              <span>⚡ Muaf</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-black/20">
                {data?.overridden_count ?? 0}
              </span>
            </button>
          </div>

          <div className="relative flex-1 sm:max-w-xs">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Sembol ara (örn: USD, JPY)..."
              className={`w-full px-3 py-1.5 pl-8 rounded-xl text-xs font-medium border transition-colors outline-none ${
                isLight
                  ? "bg-white text-slate-900 border-slate-300 focus:border-blue-500 placeholder:text-slate-400"
                  : "bg-slate-900 text-slate-100 border-slate-700 focus:border-blue-400 placeholder:text-slate-500"
              }`}
            />
            <span className="absolute left-2.5 top-2 text-xs text-slate-400">🔍</span>
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-2 text-xs text-slate-400 hover:text-slate-600"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Tablo / Kart Listesi */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-3">
          {filteredSymbols.length === 0 ? (
            <div
              className={`p-8 text-center rounded-2xl border ${
                isLight ? "bg-slate-50 border-slate-200 text-slate-600" : "bg-slate-900/30 border-slate-800 text-slate-400"
              }`}
            >
              <div className="text-3xl mb-2">🎉</div>
              <p className="text-sm font-bold">
                {filterTab === "blocked"
                  ? "Şu anda EV Kalkanı tarafından dinlenmeye alınan hiçbir sembol bulunmuyor!"
                  : "Filtre kriterinize uygun sembol bulunamadı."}
              </p>
              <p className="text-xs mt-1 text-slate-500">
                Tüm döviz çiftleri ve emtialar normal işlem koşullarına uygun çalışıyor.
              </p>
            </div>
          ) : (
            filteredSymbols.map((item) => {
              const isActionBusy = actionLoadingSymbol === item.symbol;
              const isPnlPositive = item.net_usd > 0;
              const isPnlNegative = item.net_usd < 0;

              return (
                <div
                  key={item.symbol}
                  className={`p-4 rounded-xl border transition-all ${
                    item.is_blocked
                      ? isLight
                        ? "bg-rose-50/70 border-rose-300 ring-1 ring-rose-200 shadow-sm"
                        : "bg-rose-950/20 border-rose-800/80 ring-1 ring-rose-900/40"
                      : item.is_overridden
                      ? isLight
                        ? "bg-blue-50/70 border-blue-300 shadow-sm"
                        : "bg-blue-950/20 border-blue-800/80"
                      : isLight
                      ? "bg-white border-slate-200 hover:border-slate-300 shadow-xs"
                      : "bg-slate-900/60 border-slate-800/80 hover:border-slate-700"
                  }`}
                >
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    {/* Sol Bilgiler: Sembol, Rozet, Açıklama */}
                    <div className="space-y-1.5 flex-1 min-w-0">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <span
                          className={`text-base font-black tracking-tight ${
                            isLight ? "text-slate-900" : "text-white"
                          }`}
                        >
                          {item.display}
                        </span>
                        <span className={`text-[11px] font-bold ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                          ({item.symbol})
                        </span>

                        {/* Durum Rozeti */}
                        {item.is_blocked ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-black uppercase bg-rose-500/20 text-rose-700 dark:text-rose-300 border border-rose-500/40 animate-pulse">
                            <span className="w-2 h-2 rounded-full bg-rose-500" />
                            🛑 DİNLENMEDE (BLOKE)
                          </span>
                        ) : item.is_overridden ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-black uppercase bg-blue-500/20 text-blue-700 dark:text-blue-300 border border-blue-500/40">
                            ⚡ BUGÜN MUAF (İZİNLİ)
                          </span>
                        ) : item.is_exempt_symbol ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase bg-amber-500/20 text-amber-700 dark:text-amber-300 border border-amber-500/40">
                            🌟 KALICI MUAF
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border border-emerald-500/40">
                            ✅ İŞLEME AÇIK
                          </span>
                        )}
                      </div>

                      {/* Açıklama & Neden */}
                      <p
                        className={`text-xs font-semibold leading-relaxed ${
                          item.is_blocked
                            ? isLight
                              ? "text-rose-800"
                              : "text-rose-300"
                            : item.is_overridden
                            ? isLight
                              ? "text-blue-800"
                              : "text-blue-300"
                            : isLight
                            ? "text-slate-600"
                            : "text-slate-400"
                        }`}
                      >
                        {item.reason}
                      </p>

                      {/* Muafiyet Süresi (varsa) */}
                      {item.is_overridden && item.override_until_str && (
                        <div className="flex items-center gap-2 text-[11px] font-bold text-blue-600 dark:text-blue-400">
                          <span>⏰ Muafiyet Bitişi: {item.override_until_str}</span>
                          {item.override_remaining_sec && (
                            <span>
                              (~{Math.ceil(item.override_remaining_sec / 3600)} saat kaldı)
                            </span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Orta Metrikler: İşlem sayısı, WR, Net PnL */}
                    <div
                      className={`grid grid-cols-3 gap-2 px-3 py-2 rounded-xl border shrink-0 text-center ${
                        isLight ? "bg-white/80 border-slate-200" : "bg-slate-950/60 border-slate-800"
                      }`}
                    >
                      <div className="min-w-[65px]">
                        <div className={`text-[10px] font-bold uppercase ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                          İşlem
                        </div>
                        <div className={`text-xs font-black mt-0.5 ${isLight ? "text-slate-900" : "text-white"}`}>
                          {item.n}
                        </div>
                        <div className="text-[10px] text-slate-500 font-medium">
                          {item.wins}K / {item.losses}Z
                        </div>
                      </div>

                      <div className="min-w-[65px]">
                        <div className={`text-[10px] font-bold uppercase ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                          Win Rate
                        </div>
                        <div
                          className={`text-xs font-black mt-0.5 ${
                            item.win_rate >= 50
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-rose-600 dark:text-rose-400"
                          }`}
                        >
                          %{item.win_rate.toFixed(0)}
                        </div>
                        <div className="text-[10px] text-slate-500 font-medium">Hedef: %35</div>
                      </div>

                      <div className="min-w-[75px]">
                        <div className={`text-[10px] font-bold uppercase ${isLight ? "text-slate-600" : "text-slate-400"}`}>
                          Net K/Z (24s)
                        </div>
                        <div
                          className={`text-xs font-black mt-0.5 ${
                            isPnlPositive
                              ? "text-emerald-600 dark:text-emerald-400"
                              : isPnlNegative
                              ? "text-rose-600 dark:text-rose-400 font-black"
                              : isLight
                              ? "text-slate-800"
                              : "text-slate-300"
                          }`}
                        >
                          ${item.net_usd > 0 ? `+${item.net_usd.toFixed(2)}` : item.net_usd.toFixed(2)}
                        </div>
                        <div className="text-[10px] text-slate-500 font-medium">USD</div>
                      </div>
                    </div>

                    {/* Sağ Aksiyon Butonları */}
                    <div className="flex items-center md:flex-col gap-1.5 shrink-0 justify-end">
                      {item.is_blocked ? (
                        <>
                          <button
                            type="button"
                            onClick={() => handleAction(item.symbol, "bypass_today")}
                            disabled={isActionBusy}
                            className={`w-full px-3 py-1.5 rounded-lg text-xs font-bold transition-all shadow-sm flex items-center justify-center gap-1.5 ${
                              isLight
                                ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                                : "bg-emerald-600 hover:bg-emerald-500 text-white"
                            }`}
                            title="Bugün gece yarısına (23:59 UTC+3) kadar bu sembolden kalkanı kaldır ve işleme izin ver"
                          >
                            <span>🛡️</span>
                            <span>Bugün İzin Ver</span>
                          </button>

                          <div className="flex items-center gap-1 w-full">
                            <button
                              type="button"
                              onClick={() => handleAction(item.symbol, "bypass_24h")}
                              disabled={isActionBusy}
                              className={`flex-1 px-2 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                                isLight
                                  ? "bg-slate-100 hover:bg-slate-200 text-slate-800 border-slate-300"
                                  : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
                              }`}
                              title="24 saat boyunca muaf tut"
                            >
                              24s Muaf
                            </button>
                            <button
                              type="button"
                              onClick={() => handleAction(item.symbol, "reset_history")}
                              disabled={isActionBusy}
                              className={`flex-1 px-2 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                                isLight
                                  ? "bg-slate-100 hover:bg-slate-200 text-slate-800 border-slate-300"
                                  : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
                              }`}
                              title="Sembolün geçmiş zarar sicilini sıfırla"
                            >
                              🔄 Sıfırla
                            </button>
                          </div>
                        </>
                      ) : item.is_overridden ? (
                        <>
                          <button
                            type="button"
                            onClick={() => handleAction(item.symbol, "restore")}
                            disabled={isActionBusy}
                            className={`w-full px-3 py-1.5 rounded-lg text-xs font-bold transition-all border flex items-center justify-center gap-1.5 ${
                              isLight
                                ? "bg-amber-100 hover:bg-amber-200 text-amber-900 border-amber-300"
                                : "bg-amber-950/60 hover:bg-amber-900/80 text-amber-300 border-amber-700"
                            }`}
                            title="Muafiyeti iptal et ve EV Kalkanını bu sembol için tekrar devreye al"
                          >
                            <span>🛡️</span>
                            <span>Kalkanı Devreye Al</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => handleAction(item.symbol, "reset_history")}
                            disabled={isActionBusy}
                            className={`w-full px-2 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                              isLight
                                ? "bg-slate-100 hover:bg-slate-200 text-slate-800 border-slate-300"
                                : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
                            }`}
                            title="Sembolün geçmiş zarar sicilini sıfırla"
                          >
                            🔄 Sicili Sıfırla
                          </button>
                        </>
                      ) : (
                        <div className="flex items-center gap-1 w-full">
                          <button
                            type="button"
                            onClick={() => handleAction(item.symbol, "bypass_today")}
                            disabled={isActionBusy}
                            className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                              isLight
                                ? "bg-slate-100 hover:bg-slate-200 text-slate-800 border-slate-300"
                                : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
                            }`}
                            title="Bugün kuraldan muaf tut"
                          >
                            ⚡ Muaf Tut
                          </button>
                          <button
                            type="button"
                            onClick={() => handleAction(item.symbol, "reset_history")}
                            disabled={isActionBusy}
                            className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                              isLight
                                ? "bg-slate-100 hover:bg-slate-200 text-slate-800 border-slate-300"
                                : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
                            }`}
                            title="Sembolün son 24s sicilini sıfırla"
                          >
                            🔄 Sıfırla
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Alt Bilgi & Global Eylemler Çubuğu */}
        <div
          className={`px-5 py-3 border-t flex flex-col sm:flex-row items-center justify-between gap-3 shrink-0 ${
            isLight ? "bg-slate-50 border-slate-200" : "bg-slate-900/90 border-slate-800"
          }`}
        >
          <div className="text-[11px] leading-tight font-medium max-w-xl text-slate-600 dark:text-slate-400">
            💡 <strong className={isLight ? "text-slate-800" : "text-slate-200"}>EV Kalkanı Mantığı:</strong> Bir sembol son 24 saatte arka arkaya veya akut kayıp (örn. 3x risk bütçesi) üretirse, sermayeyi korumak için geçici dinlenmeye alınır. <span className="underline font-bold">Bugün İzin Ver</span> derseniz, gün sonuna (23:59 UTC+3) kadar bu kural esnetilir ve sembole yeni scalper pozisyonları açılabilir.
          </div>

          <div className="flex items-center gap-2 shrink-0 w-full sm:w-auto justify-end">
            <button
              type="button"
              onClick={handleResetAll}
              disabled={loading}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold border transition-colors ${
                isLight
                  ? "bg-slate-100 hover:bg-rose-50 hover:text-rose-700 hover:border-rose-300 text-slate-700 border-slate-300"
                  : "bg-slate-800 hover:bg-rose-950/40 hover:text-rose-400 hover:border-rose-800 text-slate-300 border-slate-700"
              }`}
              title="Tüm sembollerin kalkan kayıtlarını ve muafiyetlerini temizler"
            >
              🔄 Tüm Kalkanları Sıfırla
            </button>
            <button
              type="button"
              onClick={onClose}
              className={`px-4 py-1.5 rounded-xl text-xs font-bold transition-colors ${
                isLight
                  ? "bg-slate-800 hover:bg-slate-900 text-white"
                  : "bg-slate-200 hover:bg-white text-slate-900"
              }`}
            >
              Kapat
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
