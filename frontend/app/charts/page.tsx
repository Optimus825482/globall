"use client";

// ─────────────────────────────────────────────────────────────────────────────
// BİRLEŞİK GRAFİK SAYFASI (2026-10-14, kullanıcı isteği)
//
// Eskiden İKİ ayrı grafik sayfası vardı:
//   • `/forex/charts`            → tekli, çok zengin sayfa (pozisyon çizgileri,
//                                  desen tarama, AI asistanı, indikatör kütüphanesi)
//   • `/forex/technical-charts`  → 4'lü MTF grid
// Kullanıcı bunların TEK sayfada birleşmesini istedi ve eski zengin sayfanın
// kaldırılmasını onayladı. Bu dosya o birleşik sayfadır; grid motoru
// `./MultiChartCard` (eski `technical-charts/MultiChartCard`'ın taşınmış hâli).
//
// Kullanıcının istediği yetenekler:
//   1. Sayfa ÜSTÜNDE grafik sayısı seçimi: 1 / 2 / 4.
//   2. TEK noktadan tüm grafiklere aynı sembolü yükle + her grafikte TEK TEK
//      sembol seç (kart başlığındaki sembol düğmesi).
//   3. Alt panelde varsayılan olarak standart MACD histogramı.
//   4. MA7 turuncu, MA20 mavi, MA99 mor (renkler SABİT, MA_COLORS).
//   5. Her grafiğin üst kısmında RSI-14 ve ADX-14 değerleri VARSAYILAN yazılı.
//   6. Her grafiğin üst kısmında KENDİ TF seçicisi.
//   7. Çok grafikte sıra numaraları 1'den başlar (ordinal).
//   8. TF etiketleri: 1m · 3m · 5m · 15m · 30m · H1 · H4 · D1 (3m eklendi).
//
// `?symbol=...` sorgu parametresi desteklenir (radar modalı, portföy ve profil
// sayfaları ile menü bu adrese bu parametreyle bağlanır).
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { API_BASE, apiRequest } from "../lib/api";
import type { MultiChartConfig, ChartIndicators } from "./MultiChartCard";
import { CHART_INTERVALS } from "./MultiChartCard";

// Lightweight Charts yalnızca tarayıcıda çalışır.
const MultiChartCard = dynamic(() => import("./MultiChartCard"), {
    ssr: false,
    loading: () => (
        <div className="h-full min-h-[300px] flex items-center justify-center bg-bunker-950 border border-bunker-800 rounded-xl">
            <div className="flex items-center gap-2 font-mono text-xs text-bunker-muted">
                <span className="w-2 h-2 rounded-full bg-neon-green animate-ping" />
                Grafik Tuvali Hazırlanıyor...
            </div>
        </div>
    ),
});

/** Grafik sayısı seçenekleri — kullanıcı isteğiyle yalnız 1 / 2 / 4. */
type ChartCount = 1 | 2 | 4;
const COUNT_OPTIONS: ChartCount[] = [1, 2, 4];

const DEFAULT_INDICATORS: ChartIndicators = {
    // Varsayılan AÇIK (kullanıcı isteği): MA7/MA20/MA99 + alt panelde MACD.
    ma7: true,
    ma20: true,
    ma99: true,
    ema9: false,
    ema21: false,
    ema50: false,
    ema200: false,
    bollinger: false,
    volume: false,
    vwap: false,
    obv: false,
    mfi: false,
    rsi: false,
    macd: true,
    stochastic: false,
    williamsR: false,
    cci: false,
    atr: false,
    supertrend: false,
};

/** Varsayılan MTF yerleşimi: 1m · 3m · 5m · 15m (tek sembol, artan ufuk). */
const DEFAULT_INTERVALS = ["1m", "3m", "5m", "15m"];
const DEFAULT_SYMBOL = "XAUUSD";

const makeSlots = (symbol: string, intervals: string[], indicators: ChartIndicators): MultiChartConfig[] =>
    [0, 1, 2, 3].map((i) => ({
        id: i + 1,
        symbol,
        interval: intervals[i] || "5m",
        indicators: { ...indicators },
    }));

const FALLBACK_SYMBOLS = [
    "EURUSD", "XAUUSD", "GBPUSD", "USDJPY", "BTCUSD", "NAS100", "US30",
    "GBPJPY", "EURJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "AUDCAD",
];

// Yerel kalıcılık anahtarları. ESKİ zengin sayfanın `scalper_chart_*`
// anahtarları KASITLI olarak kullanılmaz: o sayfa kaldırıldı, geriye kalan
// bayat kayıtları okumak sürpriz durum üretirdi.
const LS_COUNT   = "scalper_grid_count_v1";
const LS_SLOTS   = "scalper_grid_slots_v1";
const LS_SIDEBAR = "scalper_grid_sidebar_v1";
const LS_SYMBOL  = "scalper_grid_symbol_v1";
const LS_INTERVAL = "scalper_grid_interval_v1";

const isCount = (v: unknown): v is ChartCount =>
    v === 1 || v === 2 || v === 4;

export default function ChartsPage() {
    const pageRef = useRef<HTMLDivElement>(null);
    const searchParams = useSearchParams();

    const [count, setCount]         = useState<ChartCount>(4);
    const [slots, setSlots]         = useState<MultiChartConfig[]>(() =>
        makeSlots(DEFAULT_SYMBOL, DEFAULT_INTERVALS, DEFAULT_INDICATORS));
    const [maximizedId, setMaximizedId] = useState<number | null>(null);
    const [availableSymbols, setAvailableSymbols] = useState<string[]>(FALLBACK_SYMBOLS);
    const [globalSymbol, setGlobalSymbol]           = useState<string>(DEFAULT_SYMBOL);
    const [globalSymbolInput, setGlobalSymbolInput] = useState<string>(DEFAULT_SYMBOL);
    const [globalSearchOpen, setGlobalSearchOpen]   = useState(false);
    const [globalInterval, setGlobalInterval]       = useState<string>("5m");
    const [refreshKey, setRefreshKey]               = useState(0);
    const [globalIndOpen, setGlobalIndOpen]         = useState(false);
    const [sidebarHidden, setSidebarHidden]         = useState(false);
    const [isPageFullscreen, setIsPageFullscreen]   = useState(false);

    // ── Sidebar gizle/göster ─────────────────────────────────────────────────
    useEffect(() => {
        const sidebar = document.querySelector<HTMLElement>("[data-sidebar]");
        const topbar  = document.querySelector<HTMLElement>("[data-topbar]");
        if (sidebarHidden) {
            sidebar?.classList.add("!hidden");
            topbar?.classList.add("!hidden");
        } else {
            sidebar?.classList.remove("!hidden");
            topbar?.classList.remove("!hidden");
        }
        try { localStorage.setItem(LS_SIDEBAR, sidebarHidden ? "1" : "0"); } catch { }
        return () => {
            // Sayfadan çıkınca sidebar'ı geri aç — aksi halde diğer sayfalar
            // navigasyonsuz kalırdı.
            sidebar?.classList.remove("!hidden");
            topbar?.classList.remove("!hidden");
        };
    }, [sidebarHidden]);

    // ── Sayfa tam ekran ──────────────────────────────────────────────────────
    const togglePageFullscreen = useCallback(() => {
        if (!document.fullscreenElement) {
            pageRef.current?.requestFullscreen().catch(err => console.warn("Fullscreen hata:", err));
        } else {
            document.exitFullscreen();
        }
    }, []);

    useEffect(() => {
        const handler = () => setIsPageFullscreen(!!document.fullscreenElement);
        document.addEventListener("fullscreenchange", handler);
        return () => document.removeEventListener("fullscreenchange", handler);
    }, []);

    // ── Sembol evreni ────────────────────────────────────────────────────────
    // Üç kaynak birleşir: yerel yedek liste, forex motorunun sembolleri
    // (`/api/forex/symbols` — FOREX_SYMBOLS) ve borsa sembolleri.
    useEffect(() => {
        apiRequest(`${API_BASE}/api/forex/symbols`)
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                const list = (data?.symbols || [])
                    .map((s: any) => String(s?.symbol || "").toUpperCase())
                    .filter(Boolean);
                if (list.length) {
                    setAvailableSymbols((curr) => [...new Set([...curr, ...list])].sort((a, b) => a.localeCompare(b)));
                }
            })
            .catch(() => { });
        apiRequest(`${API_BASE}/api/market-symbols`)
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                const list = data?.symbols;
                if (Array.isArray(list) && list.length) {
                    setAvailableSymbols((curr) => [...new Set([...curr, ...list])].sort((a, b) => a.localeCompare(b)));
                }
            })
            .catch(() => { });
    }, []);

    // ── LocalStorage + `?symbol=` geri yükleme ───────────────────────────────
    useEffect(() => {
        try {
            const savedCount = Number(localStorage.getItem(LS_COUNT));
            if (isCount(savedCount)) setCount(savedCount);

            const savedSlots = localStorage.getItem(LS_SLOTS);
            if (savedSlots) {
                const parsed = JSON.parse(savedSlots);
                if (Array.isArray(parsed) && parsed.length === 4) {
                    // Kaldırılan/eski sürümden gelen eksik indikatör anahtarları
                    // varsayılanla tamamlanır (aksi halde `undefined` → kapalı).
                    const merged: MultiChartConfig[] = parsed.map((s: any, i: number) => ({
                        id: i + 1,
                        symbol: String(s?.symbol || DEFAULT_SYMBOL).toUpperCase(),
                        interval: String(s?.interval || DEFAULT_INTERVALS[i] || "5m"),
                        indicators: { ...DEFAULT_INDICATORS, ...(s?.indicators || {}) },
                    }));
                    setSlots(merged);
                    if (merged[0]?.symbol) {
                        setGlobalSymbol(merged[0].symbol);
                        setGlobalSymbolInput(merged[0].symbol);
                    }
                    if (merged[0]?.interval) setGlobalInterval(merged[0].interval);
                }
            }
            const savedSidebar = localStorage.getItem(LS_SIDEBAR);
            if (savedSidebar === "1") setSidebarHidden(true);
            const savedSym = localStorage.getItem(LS_SYMBOL);
            if (savedSym) { setGlobalSymbol(savedSym); setGlobalSymbolInput(savedSym); }
            const savedTf = localStorage.getItem(LS_INTERVAL);
            if (savedTf && CHART_INTERVALS.some(i => i.v === savedTf)) setGlobalInterval(savedTf);
        } catch { }

        // `?symbol=` — radar/portföy/profil bağlantılarının girdiği yol.
        // Sembolü TÜM grafiklere uygular; TF'ler MTF şablonu olarak dağıtılır ki
        // tek grafikte bile anlamlı bir ufukla açılsın.
        try {
            const querySymbol = searchParams.get("symbol");
            if (querySymbol) {
                const clean = querySymbol.trim().toUpperCase();
                setSlots((prev) => {
                    const next = prev.map((s, idx) => ({
                        ...s,
                        symbol: clean,
                        interval: DEFAULT_INTERVALS[idx] || s.interval,
                    }));
                    try { localStorage.setItem(LS_SLOTS, JSON.stringify(next)); } catch { }
                    return next;
                });
                setGlobalSymbol(clean);
                setGlobalSymbolInput(clean);
                setMaximizedId(null);
            }
        } catch { }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // ── Slot güncelle ────────────────────────────────────────────────────────
    const persistSlots = (next: MultiChartConfig[]) => {
        try { localStorage.setItem(LS_SLOTS, JSON.stringify(next)); } catch { }
    };

    const updateSlot = useCallback((id: number, updated: Partial<MultiChartConfig>) => {
        setSlots((prev) => {
            const next = prev.map((s) => (s.id === id ? { ...s, ...updated } : s));
            persistSlots(next);
            return next;
        });
    }, []);

    // ── Grafik sayısı ────────────────────────────────────────────────────────
    const changeCount = (n: ChartCount) => {
        setCount(n);
        setMaximizedId(null);
        try { localStorage.setItem(LS_COUNT, String(n)); } catch { }
    };

    // ── TEK noktadan sembol: tüm grafiklere yükle ────────────────────────────
    const applyGlobalSymbol = (raw: string) => {
        const clean = String(raw || "").trim().toUpperCase();
        if (!clean) return;
        setSlots((prev) => {
            const next = prev.map((s) => ({ ...s, symbol: clean }));
            persistSlots(next);
            return next;
        });
        setGlobalSymbol(clean);
        setGlobalSymbolInput(clean);
        setGlobalSearchOpen(false);
        try { localStorage.setItem(LS_SYMBOL, clean); } catch { }
    };

    // ── TEK noktadan TF: tüm grafiklere yükle ────────────────────────────────
    const applyGlobalInterval = (tf: string) => {
        setGlobalInterval(tf);
        setSlots((prev) => {
            const next = prev.map((s) => ({ ...s, interval: tf }));
            persistSlots(next);
            return next;
        });
        try { localStorage.setItem(LS_INTERVAL, tf); } catch { }
    };

    // ── MTF şablonu: 1m·3m·5m·15m ────────────────────────────────────────────
    const applyMtfTemplate = () => {
        const sym = globalSymbol || slots[0]?.symbol || DEFAULT_SYMBOL;
        setSlots((prev) => {
            const next = prev.map((s, idx) => ({
                ...s,
                symbol: sym,
                interval: DEFAULT_INTERVALS[idx] || s.interval,
                indicators: { ...s.indicators, macd: true },
            }));
            persistSlots(next);
            return next;
        });
        setCount(4);
        setMaximizedId(null);
        try { localStorage.setItem(LS_COUNT, "4"); } catch { }
    };

    // ── Tüm grafiklere indikatör aç/kapat ────────────────────────────────────
    const toggleGlobalIndicator = useCallback((key: keyof ChartIndicators) => {
        setSlots((prev) => {
            // Herhangi bir kartta açıksa hepsini kapat, yoksa hepsini aç.
            const anyActive = prev.some(s => s.indicators[key]);
            const next = prev.map(s => ({ ...s, indicators: { ...s.indicators, [key]: !anyActive } }));
            persistSlots(next);
            return next;
        });
    }, []);

    const setGlobalIndicators = useCallback((patch: Partial<ChartIndicators>) => {
        setSlots((prev) => {
            const next = prev.map(s => ({ ...s, indicators: { ...DEFAULT_INDICATORS, ...patch } }));
            persistSlots(next);
            return next;
        });
    }, []);

    /** Tüm indikatörleri KAPAT (preset'lerin aksine varsayılana dönmez —
     *  "Temizle" adı bunu vaat ediyor; eskiden MA7/MA20/MA99/MACD geri geliyordu). */
    const clearAllIndicators = useCallback(() => {
        setSlots((prev) => {
            const next = prev.map(s => ({
                ...s,
                indicators: Object.fromEntries(
                    Object.keys(s.indicators).map(k => [k, false])
                ) as unknown as ChartIndicators,
            }));
            persistSlots(next);
            return next;
        });
    }, []);

    const refreshAll = () => setRefreshKey((k) => k + 1);

    // Açılır menüler (sembol arama + indikatör paneli) dışarı tıklamayla ve Esc
    // ile kapanır. Bunlar olmadan menü yalnız kendi ✕ düğmesiyle kapanıyordu.
    const toolbarRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const onDown = (e: MouseEvent) => {
            if (!toolbarRef.current?.contains(e.target as Node)) {
                setGlobalSearchOpen(false);
                setGlobalIndOpen(false);
            }
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                setGlobalSearchOpen(false);
                setGlobalIndOpen(false);
            }
        };
        document.addEventListener("mousedown", onDown);
        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("mousedown", onDown);
            document.removeEventListener("keydown", onKey);
        };
    }, []);

    // ── Görünür slotlar / grid ───────────────────────────────────────────────
    const visibleSlots = useMemo(() => {
        if (maximizedId !== null) return slots.filter((s) => s.id === maximizedId);
        return slots.slice(0, count);
    }, [slots, count, maximizedId]);

    const gridLayoutClass = useMemo(() => {
        if (maximizedId !== null) return "grid-cols-1 grid-rows-1";
        if (count === 1) return "grid-cols-1 grid-rows-1";
        if (count === 2) return "grid-cols-1 md:grid-cols-2 grid-rows-1";
        return "grid-cols-1 md:grid-cols-2 grid-rows-2";
    }, [count, maximizedId]);

    const filteredSymbols = availableSymbols.filter(s =>
        s.toLowerCase().includes(globalSymbolInput.trim().toLowerCase()));

    const activeIndicatorCount = useMemo(() => {
        // Kartlarda en az bir kez açık olan indikatör sayısı (panel rozeti).
        const keys = new Set<keyof ChartIndicators>();
        slots.forEach(s => (Object.keys(s.indicators) as (keyof ChartIndicators)[])
            .forEach(k => { if (s.indicators[k]) keys.add(k); }));
        return keys.size;
    }, [slots]);

    return (
        <div
            ref={pageRef}
            className={`flex flex-col bg-bunker-950 ${
                isPageFullscreen
                    ? "fixed inset-0 z-[9998] overflow-hidden"
                    : "h-[calc(100vh-4rem)]"
            }`}
        >
            {/* ── Komut Çubuğu ────────────────────────────────────────────── */}
            <div
                ref={toolbarRef}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 bg-bunker-900 border-b border-bunker-800 shrink-0"
            >

                {/* Sol: sidebar + tam ekran + başlık */}
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={() => setSidebarHidden(v => !v)}
                        className={`p-1.5 rounded-lg border font-mono text-xs transition-colors ${
                            sidebarHidden
                                ? "bg-neon-green/15 border-neon-green/40 text-neon-green"
                                : "bg-bunker-800 border-bunker-700 text-bunker-muted hover:text-white"
                        }`}
                        title={sidebarHidden ? "Sidebar'ı Aç" : "Sidebar'ı Gizle (Daha Fazla Alan)"}
                    >
                        {sidebarHidden ? "◨" : "◧"}
                    </button>
                    <button
                        type="button"
                        onClick={togglePageFullscreen}
                        className={`p-1.5 rounded-lg border font-mono text-xs transition-colors ${
                            isPageFullscreen
                                ? "bg-neon-green/15 border-neon-green/40 text-neon-green font-bold"
                                : "bg-bunker-800 border-bunker-700 text-bunker-muted hover:text-white"
                        }`}
                        title={isPageFullscreen ? "Tam Ekrandan Çık (Esc)" : "Komple Sayfa Tam Ekran"}
                    >
                        {isPageFullscreen ? "⊠" : "⊞"}
                    </button>
                    <div className="hidden sm:block">
                        <h1 className="font-mono text-sm font-bold text-white flex items-center gap-2">
                            GRAFİK
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-neon-green/15 text-neon-green border border-neon-green/30">
                                {count === 1 ? "TEKLİ" : `${count}'LÜ`}
                            </span>
                        </h1>
                    </div>
                </div>

                {/* Orta: grafik sayısı + global sembol + global TF */}
                <div className="flex items-center gap-2 flex-wrap">
                    {/* 1 / 2 / 4 grafik */}
                    <div className="flex items-center bg-bunker-950 p-0.5 rounded-lg border border-bunker-700" title="Gösterilecek grafik sayısı">
                        {COUNT_OPTIONS.map((n) => (
                            <button
                                key={n}
                                type="button"
                                onClick={() => changeCount(n)}
                                className={`px-2.5 py-1 rounded font-mono text-xs font-bold transition-colors ${
                                    count === n ? "bg-neon-green text-bunker-950" : "text-bunker-muted hover:text-white"
                                }`}
                            >
                                {n}
                            </button>
                        ))}
                    </div>

                    {/* Global sembol → TÜM grafikler */}
                    <div className="relative flex items-center">
                        <div className="flex items-center bg-bunker-950 rounded-lg border border-bunker-700 overflow-hidden focus-within:border-neon-green/50">
                            <input
                                type="text"
                                value={globalSymbolInput}
                                onChange={(e) => { setGlobalSymbolInput(e.target.value.toUpperCase()); setGlobalSearchOpen(true); }}
                                onKeyDown={(e) => {
                                    if (e.key === "Enter") { e.preventDefault(); applyGlobalSymbol(globalSymbolInput); }
                                }}
                                onFocus={() => setGlobalSearchOpen(true)}
                                placeholder="Sembol (örn. XAUUSD)..."
                                className="w-28 md:w-36 px-2.5 py-1 font-mono text-xs text-white bg-transparent outline-none uppercase placeholder-bunker-600"
                            />
                            <button
                                type="button"
                                onClick={() => applyGlobalSymbol(globalSymbolInput)}
                                className="px-2.5 py-1 bg-neon-green/20 hover:bg-neon-green/30 text-neon-green border-l border-bunker-700 font-mono text-xs font-bold transition-colors"
                                title="Bu sembolü tüm grafiklere yükle (Enter)"
                            >
                                TÜMÜ
                            </button>
                        </div>

                        {globalSearchOpen && (
                            <div className="absolute left-0 top-full mt-1.5 z-50 w-64 bg-bunker-900 border border-bunker-700 rounded-xl shadow-2xl p-2 max-h-72 overflow-y-auto">
                                <div className="flex items-center justify-between pb-1 mb-1.5 border-b border-bunker-800">
                                    <span className="text-[10px] font-mono text-bunker-muted font-bold">
                                        Sembol Seç ({availableSymbols.length} adet)
                                    </span>
                                    <button type="button" onClick={() => setGlobalSearchOpen(false)} className="text-bunker-muted hover:text-white text-xs">✕</button>
                                </div>
                                {globalSymbolInput.trim() && (
                                    <button
                                        type="button"
                                        onClick={() => applyGlobalSymbol(globalSymbolInput)}
                                        className="w-full text-left px-2 py-1.5 mb-1.5 rounded text-xs font-mono bg-neon-green/15 text-neon-green hover:bg-neon-green/25 font-bold border border-neon-green/30 transition-colors"
                                    >
                                        ⚡ {globalSymbolInput.trim().toUpperCase()} Aç
                                    </button>
                                )}
                                {filteredSymbols.slice(0, 40).map((s) => (
                                    <button
                                        key={s}
                                        type="button"
                                        onClick={() => applyGlobalSymbol(s)}
                                        className="w-full text-left px-2 py-1 rounded text-xs font-mono text-bunker-muted hover:bg-bunker-800 hover:text-white transition-colors flex items-center justify-between"
                                    >
                                        <span>{s}</span>
                                        {globalSymbol === s && <span className="text-neon-green text-[10px]">Aktif</span>}
                                    </button>
                                ))}
                                {filteredSymbols.length === 0 && (
                                    <p className="text-center text-[11px] text-bunker-muted py-2 font-mono">Sembol listesinde bulunamadı</p>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Global TF → TÜM grafikler */}
                    <div className="flex items-center bg-bunker-950 rounded-lg border border-bunker-700 overflow-hidden" title="Tüm grafiklerin zaman dilimi">
                        <span className="px-2 py-1 font-mono text-[10px] text-bunker-muted border-r border-bunker-800">TF</span>
                        <select
                            value={globalInterval}
                            onChange={(e) => applyGlobalInterval(e.target.value)}
                            className="px-2 py-1 bg-transparent font-mono text-xs text-white outline-none cursor-pointer"
                        >
                            {CHART_INTERVALS.map((i) => (
                                <option key={i.v} value={i.v} className="bg-bunker-900">{i.l}</option>
                            ))}
                        </select>
                    </div>

                    {/* MTF şablonu */}
                    <button
                        type="button"
                        onClick={applyMtfTemplate}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-neon-yellow hover:text-white font-mono text-xs font-bold transition-colors"
                        title="Aynı sembolü 1m, 3m, 5m, 15m olarak 4 ekrana dağıtır"
                    >
                        <span>⏱</span>
                        <span className="hidden sm:inline">MTF 1·3·5·15</span>
                        <span className="sm:hidden">MTF</span>
                    </button>

                    {/* Tümüne indikatör */}
                    <div className="relative">
                        <button
                            type="button"
                            onClick={() => setGlobalIndOpen(v => !v)}
                            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border font-mono text-xs font-bold transition-colors ${
                                globalIndOpen
                                    ? "bg-neon-green/15 border-neon-green/40 text-neon-green"
                                    : "bg-bunker-800 border-bunker-700 text-bunker-muted hover:text-white"
                            }`}
                            title="Tüm grafiklere aynı indikatör setini uygula"
                        >
                            <span>fx</span>
                            <span className="hidden sm:inline">TÜMÜNE İNDİKATÖR</span>
                            <span className="bg-bunker-700 text-white font-bold rounded-full w-4 h-4 text-[9px] flex items-center justify-center">
                                {activeIndicatorCount}
                            </span>
                        </button>

                        {globalIndOpen && (
                            <div className="absolute left-0 top-full mt-1.5 z-50 w-80 bg-bunker-900 border border-bunker-700 rounded-xl shadow-2xl p-3">
                                <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-bunker-800">
                                    <span className="font-mono text-[11px] font-bold text-white">Tüm Grafiklere Uygula</span>
                                    <button type="button" onClick={() => setGlobalIndOpen(false)} className="text-bunker-muted hover:text-white text-xs">✕</button>
                                </div>
                                <div className="grid grid-cols-2 gap-1">
                                    {(Object.keys(DEFAULT_INDICATORS) as (keyof ChartIndicators)[]).map((key) => {
                                        const active = slots.some(s => s.indicators[key]);
                                        return (
                                            <button
                                                key={key}
                                                type="button"
                                                onClick={() => toggleGlobalIndicator(key)}
                                                className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg border font-mono text-[11px] transition-colors text-left ${
                                                    active
                                                        ? "bg-neon-green/15 border-neon-green/40 text-neon-green font-bold"
                                                        : "bg-bunker-800/60 border-bunker-700 text-bunker-muted hover:text-white hover:bg-bunker-800"
                                                }`}
                                            >
                                                <span>{key}</span>
                                                {active && <span className="ml-auto text-neon-green text-[9px]">✓</span>}
                                            </button>
                                        );
                                    })}
                                </div>
                                <div className="mt-2 pt-2 border-t border-bunker-800 flex flex-wrap gap-1.5">
                                    <span className="text-[10px] font-mono text-bunker-muted self-center">Preset:</span>
                                    <button
                                        type="button"
                                        onClick={() => setGlobalIndicators({ ma7: true, ma20: true, ma99: true, macd: true })}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors"
                                        title="MA7/MA20/MA99 + MACD (sayfa varsayılanı)"
                                    >Varsayılan</button>
                                    <button
                                        type="button"
                                        onClick={() => setGlobalIndicators({ ma7: true, ma20: true, ma99: true, macd: true, rsi: true, volume: true })}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors"
                                    >Orta</button>
                                    <button
                                        type="button"
                                        onClick={() => setGlobalIndicators({
                                            ma7: true, ma20: true, ma99: true, ema9: true, ema21: true, ema50: true,
                                            bollinger: true, vwap: true, volume: true, rsi: true, macd: true,
                                        })}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-bunker-muted hover:text-white transition-colors"
                                    >Pro</button>
                                    <button
                                        type="button"
                                        onClick={clearAllIndicators}
                                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-neon-red/10 hover:bg-neon-red/20 border border-neon-red/30 text-neon-red transition-colors"
                                    >Temizle</button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Sağ: yenile */}
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={refreshAll}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-bunker-800 hover:bg-bunker-700 border border-bunker-700 text-white font-mono text-xs transition-colors"
                        title="Tüm grafikleri yenile"
                    >
                        <span>↻</span>
                        <span className="hidden md:inline">YENİLE</span>
                    </button>
                </div>
            </div>

            {/* ── Grafik Gridi ─────────────────────────────────────────────── */}
            <div
                key={refreshKey}
                className={`grid gap-2 flex-1 min-h-0 w-full p-2 ${gridLayoutClass}`}
            >
                {visibleSlots.map((slot, idx) => (
                    <MultiChartCard
                        key={`${slot.id}_${slot.symbol}_${slot.interval}`}
                        config={slot}
                        availableSymbols={availableSymbols}
                        isMaximized={maximizedId === slot.id}
                        onToggleMaximize={() => setMaximizedId((curr) => (curr === slot.id ? null : slot.id))}
                        onUpdateConfig={(updated) => updateSlot(slot.id, updated)}
                        ordinal={idx + 1}
                    />
                ))}
            </div>
        </div>
    );
}
