"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "./ui";
import { apiFetch } from "../lib/api";
import { toMs } from "../lib/format";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import SymbolLink from "./SymbolLink";
import { useAuth } from "../lib/auth";
import { ML_PROB_CLASS, ML_PROB_TITLE, formatMlProbability } from "../lib/mlProbability";
import { visibleGroups } from "../lib/menu";

import { usePwa } from "../lib/pwa";

const formatNotificationDate = (value: unknown) => {
    const numeric = Number(value);
    const date = Number.isFinite(numeric) ? new Date(toMs(numeric)) : new Date(String(value || ""));
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("tr-TR");
};

export default function Sidebar() {
    const pathname = usePathname();
    const { username, role, logout } = useAuth();
    const { isInstallable, isInstalled, openInstallDialog } = usePwa();
    const isAdmin = role === "admin";
    const groups = visibleGroups({ isAdmin });
    const [open, setOpen] = useState(false);
    // Grup açık/kapalı durumu. undefined = varsayılan (ana açık, diğerleri kapalı).
    const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
    const [busyLogout, setBusyLogout] = useState(false);
    const [notifications, setNotifications] = useState<any[]>([]);
    const [unread, setUnread] = useState(0);
    const [notificationsOpen, setNotificationsOpen] = useState(false);
    const [health, setHealth] = useState<any>(null);
    const liveStatus = useLiveStatus();
    const onLiveMessage = useCallback((message: any) => {
        if (message.type !== "alert" && message.type !== "forex_alert") return;
        const sym = String(message.data?.symbol || "").toUpperCase();
        if (sym && !sym.includes("USD") && !sym.includes("EUR") && !sym.includes("XAU") && !sym.includes("GBP") && !sym.includes("JPY")) {
            return; // Kripto spot alarmlarını yut
        }
        const item = { ...(message.data || {}), id: message.data?.id || `${Date.now()}`, triggered_at: message.data?.triggered_at || Date.now() / 1000 };
        setNotifications((current) => [item, ...current.filter((entry) => entry.id !== item.id)].slice(0, 30));
        setUnread((count) => count + 1);
    }, []);
    useLiveMessages(onLiveMessage);
    useEffect(() => setOpen(false), [pathname]);
    useEffect(() => {
        if (!open) return;
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") setOpen(false);
        };
        const prevOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        window.addEventListener("keydown", handleKeyDown);
        return () => {
            document.body.style.overflow = prevOverflow;
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [open]);
    useEffect(() => {
        const handleOpen = () => setOpen(true);
        window.addEventListener("open-mobile-menu", handleOpen);
        return () => window.removeEventListener("open-mobile-menu", handleOpen);
    }, []);
    useEffect(() => {
        const load = () => apiFetch("/api/alerts")
            .then((data) => {
                const list = (data.events || []).filter((e: any) => {
                    const s = String(e.symbol || "").toUpperCase();
                    return !s || s.includes("USD") || s.includes("EUR") || s.includes("XAU") || s.includes("GBP") || s.includes("JPY");
                });
                setNotifications(list.slice(0, 30));
            })
            .catch(() => undefined);
        load();
    }, []);
    const loadHealth = useCallback(() => {
        apiFetch("/api/system/health").then(setHealth).catch(() => setHealth(null));
    }, []);
    useEffect(() => { loadHealth(); }, [loadHealth]);
    useVisibleInterval(loadHealth, 10_000);

    return (
        <>
            {open && <button className="mobile-menu-backdrop" onClick={() => setOpen(false)} aria-label="Menüyü kapat" />}
        <aside className={`app-sidebar w-64 max-w-[85vw] md:w-56 shrink-0 border-r border-bunker-800 bg-bunker-900/95 flex flex-col h-screen sticky top-0 ${open ? "is-open" : ""}`}>
            <div className="p-4 sm:p-5 border-b border-bunker-800">
                <div className="flex items-center justify-between">
                    <Link href="/" onClick={() => setOpen(false)} className="flex items-center gap-2.5">
                        <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/25 to-blue-600/30 border border-cyan-400/40 shadow-[0_0_12px_rgba(0,240,255,0.3)]">
                            <span className="text-base select-none">🌐</span>
                            <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_6px_#00f0ff]" />
                        </div>
                        <div className="flex flex-col">
                            <span className="font-mono text-sm font-bold tracking-tight text-white flex items-center gap-1">
                                SCALPER <span className="text-neon-green">GLOBAL</span>
                            </span>
                            <span className="font-mono text-[9px] font-bold text-cyan-400/80 tracking-widest uppercase">
                                $ TERMINAL
                            </span>
                        </div>
                    </Link>
                    <button
                        type="button"
                        onClick={() => setOpen(false)}
                        className="md:hidden flex items-center justify-center w-8 h-8 rounded-lg text-bunker-muted hover:text-white hover:bg-bunker-800 transition-colors"
                        aria-label="Menüyü kapat"
                    >
                        ✕
                    </button>
                </div>
                {/* PİYASA MODU SEÇİCİ (SPOT / FOREX) ve BTC BEAR REGIME ROZETİ
                    KALDIRILDI (2026-10-07): uygulama artık YALNIZCA Forex &
                    Emtia sunar; spot sayfalar silindiği için (a) piyasa-modu
                    anahtarı ve (b) yalnız spot sayfalardaki BTC rejim kalkanını
                    anlatan rozet yoktur. */}

                {/* Global Borsa / Forex Rozet Kartı — tek piyasa (Forex). */}
                <div className="mt-2.5 rounded-xl border p-2.5 shadow-sm transition-colors border-blue-300 dark:border-blue-500/40 bg-blue-50/80 dark:bg-gradient-to-r dark:from-blue-950/70 dark:via-slate-900/70 dark:to-indigo-950/60">
                    <div className="flex items-center justify-between font-mono">
                        <span className="flex items-center gap-1.5 text-xs font-black text-blue-900 dark:text-cyan-300">
                            <span className="w-2 h-2 rounded-full animate-pulse bg-blue-500 shadow-[0_0_8px_#38bdf8]" />
                            GLOBAL FOREX
                        </span>
                        <span className="rounded px-2 py-0.5 text-[10px] font-bold border bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-500/20 dark:text-blue-200 dark:border-blue-400/40">
                            FX
                        </span>
                    </div>
                    <div className="mt-1.5 flex items-center justify-between text-[10px] font-mono border-t border-blue-200 dark:border-bunker-700/60 pt-1.5">
                        <span className="text-blue-700 dark:text-blue-300/80 font-bold">
                            PARİTE &amp; EMTİA
                        </span>
                        <span className="text-emerald-700 dark:text-emerald-400 font-black">
                            DEMO / LIVE
                        </span>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => { setNotificationsOpen(true); setUnread(0); }}
                    className="relative mt-3.5 flex w-full items-center justify-between rounded-xl border border-slate-300 dark:border-bunker-700 bg-slate-50 dark:bg-bunker-950/70 px-3 py-2 text-left transition-colors hover:border-blue-400"
                    aria-label={`Bildirimleri aç${unread ? `, ${unread} yeni bildirim` : ""}`}
                >
                    <span className="flex items-center gap-2 font-mono text-xs font-bold text-slate-900 dark:text-white"><span className="text-lg">🔔</span> BİLDİRİMLER</span>
                    {unread > 0 && <span className="min-w-5 rounded-full bg-rose-600 px-1.5 py-0.5 text-center font-mono text-[10px] font-bold text-white">{unread > 99 ? "99+" : unread}</span>}
                </button>
            </div>

            <nav className="flex-1 overflow-y-auto p-3 space-y-3" aria-label="Ana gezinme">
                {groups.map((group) => {
                    if (!group.items.length) return null;
                    // 2026-09-27: `forex_ana` grubu DÜZ liste (grup başlığı yok
                    // — kullanıcı "gruplamayı kaldır" istedi). `diger` grubu
                    // açık/kapalı chevron'lu; varsayılan kapalı.
                    const isFlat = group.id === "forex_ana";
                    const open = openGroups[group.id] ?? isFlat;
                    return (
                        <div key={group.id} className="space-y-1">
                            {!isFlat && (
                                <button
                                    type="button"
                                    onClick={() => setOpenGroups((s) => ({ ...s, [group.id]: !open }))}
                                    className="flex w-full items-center gap-1.5 rounded-md px-3 py-1.5 text-left transition-colors hover:bg-bunker-800/50"
                                    aria-expanded={open}
                                >
                                    <span className={`text-[10px] text-bunker-muted transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
                                    <span className="font-mono text-[10px] font-bold tracking-[0.12em] text-bunker-muted">
                                        {group.label}
                                    </span>
                                    <span className="ml-auto font-mono text-[10px] text-bunker-muted/60">
                                        {group.items.length}
                                    </span>
                                </button>
                            )}
                            {(open || isFlat) && group.items.map((m) => {
                                const active = pathname === m.href
                                    || (m.alsoActive || []).includes(pathname);
                                const label = m.label;
                                return (
                                    <Link
                                        key={m.href}
                                        href={m.href}
                                        onClick={() => setOpen(false)}
                                        title={m.desc || label}
                                        className={`block px-3 py-2.5 rounded-lg border transition-colors touch-target ${active
                                            ? "bg-neon-green/10 border-neon-green/30"
                                            : "border-transparent hover:bg-bunker-800/60 hover:border-bunker-700"
                                            }`}
                                    >
                                        <span className="flex items-center gap-2.5">
                                            <span className="text-sm">{m.icon}</span>
                                            <span className={`font-mono text-sm ${active ? "text-neon-green font-bold" : "text-white"}`}>
                                                {label}
                                            </span>
                                        </span>
                                        {/* Açıklama yalnız geniş ekranda: 6 öğeli grupta
                                            her satıra iki satır harçlanıyordu. */}
                                        {m.desc && <span className="hidden lg:block text-[11px] text-bunker-muted mt-0.5 ml-7">{m.desc}</span>}
                                    </Link>
                                );
                            })}
                        </div>
                    );
                })}

                {/* Alt Bölüm: Artık ayrı/sticky değil, menü akışının içinde doğal olarak yer alır; ultra-kompakt & siber-estetik */}
                <div className="mt-auto pt-3 border-t border-bunker-800/80 space-y-2">
                    {username && (
                        <div className="flex items-center justify-between gap-1.5 p-2 rounded-xl bg-bunker-950/70 border border-cyan-500/20 hover:border-cyan-400/40 transition-all shadow-[0_2px_8px_rgba(0,0,0,0.3)]">
                            <Link
                                href={isAdmin ? "/settings?tab=profile" : "/settings"}
                                title={isAdmin ? "Ayarlar — Profil sekmesi" : "Ayarlar"}
                                className="flex items-center gap-2 min-w-0 flex-1 group"
                            >
                                <div className="relative w-6 h-6 rounded-lg bg-cyan-500/10 border border-cyan-400/30 flex items-center justify-center shrink-0">
                                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_#00f0ff]" />
                                </div>
                                <div className="flex flex-col min-w-0">
                                    <div className="flex items-center gap-1.5">
                                        <span className="font-mono text-xs font-bold text-white group-hover:text-cyan-300 transition-colors truncate">
                                            {username}
                                        </span>
                                        <span className={`text-[8px] font-mono px-1 py-0.2 rounded font-bold uppercase ${
                                            isAdmin
                                                ? "bg-cyan-400/15 text-cyan-300 border border-cyan-400/40"
                                                : "bg-bunker-800 text-bunker-muted border border-bunker-700"
                                        }`}>
                                            {isAdmin ? "ADMIN" : "USER"}
                                        </span>
                                    </div>
                                </div>
                            </Link>
                            <div className="flex items-center gap-1 shrink-0">
                                <Link
                                    href={isAdmin ? "/settings?tab=profile" : "/settings"}
                                    title="Ayarlar"
                                    className="p-1.5 rounded-lg text-bunker-muted hover:text-cyan-300 hover:bg-cyan-950/40 transition-colors"
                                >
                                    <span className="text-xs">⚙</span>
                                </Link>
                                <button
                                    type="button"
                                    onClick={async () => {
                                        setBusyLogout(true);
                                        try { await logout?.(); } finally { setBusyLogout(false); }
                                    }}
                                    disabled={busyLogout}
                                    title="Oturumu kapat ve giriş ekranına dön"
                                    className="p-1.5 rounded-lg text-bunker-muted hover:text-neon-red hover:bg-neon-red/10 transition-colors disabled:opacity-50"
                                >
                                    <span className="text-xs font-bold">{busyLogout ? "…" : "⏻"}</span>
                                </button>
                            </div>
                        </div>
                    )}

                    {isInstallable && !isInstalled && (
                        <button
                            type="button"
                            onClick={openInstallDialog}
                            className="w-full flex items-center justify-center gap-2 py-1.5 px-3 rounded-lg border border-cyan-400/40 bg-cyan-950/40 text-cyan-300 font-mono text-[10px] font-bold tracking-wide hover:bg-cyan-900/50 hover:border-cyan-400 transition-all shadow-[0_0_10px_rgba(0,240,255,0.15)] active:scale-95 touch-target"
                        >
                            <span>📲</span> UYGULAMAYI YÜKLE
                        </button>
                    )}

                    <Link
                        href="/settings?tab=health"
                        onClick={() => setOpen(false)}
                        className={`group flex items-center justify-between p-2 rounded-xl border transition-all ${
                            pathname === "/settings"
                                ? "border-cyan-400/60 bg-cyan-950/40 shadow-[0_0_12px_rgba(0,240,255,0.2)]"
                                : "border-bunker-800 bg-bunker-950/40 hover:border-cyan-500/30 hover:bg-bunker-900/60"
                        }`}
                        title="Ayarlar > Sistem Sağlığını görüntüle"
                    >
                        <div className="flex items-center gap-2 min-w-0">
                            <span className={`w-2 h-2 rounded-full shrink-0 ${
                                health?.status === "ok" && liveStatus === "open"
                                    ? "bg-cyan-400 animate-pulse shadow-[0_0_8px_#00f0ff]"
                                    : "bg-yellow-300"
                            }`} />
                            <div className="flex flex-col">
                                <span className="font-mono text-[10px] font-bold tracking-wider text-bunker-muted group-hover:text-white transition-colors">
                                    SİSTEM SAĞLIĞI
                                </span>
                                <span className="font-mono text-[9px] text-cyan-400/80">
                                    {health ? `${String(health.status || "bilinmiyor").toUpperCase()} · WS ${liveStatus === "open" ? "BAĞLI" : "KAPALI"}` : "BAĞLANTI BEKLENİYOR"}
                                </span>
                            </div>
                        </div>
                        <span className="font-mono text-[10px] text-bunker-muted group-hover:text-cyan-300 transition-colors ml-1">
                            →
                        </span>
                    </Link>

                    <div className="flex items-center justify-between px-1 text-[9px] font-mono text-bunker-muted/50">
                        <span className="flex items-center gap-1" title="Build ID">
                            <span className="w-1 h-1 rounded-full bg-cyan-400/50" />
                            v{typeof window !== "undefined" ? (document.documentElement.dataset.buildId || process.env.NEXT_PUBLIC_BUILD_ID || "dev") : (process.env.NEXT_PUBLIC_BUILD_ID || "dev")}
                        </span>
                        <span className="text-[8px] text-cyan-500/60 font-semibold tracking-wider">GLOBAL FOREX</span>
                    </div>
                </div>
            </nav>
        </aside>
        {notificationsOpen && <div className="fixed inset-0 z-[100] grid place-items-center bg-black/75 p-4" onClick={() => setNotificationsOpen(false)}>
            <section className="w-full max-w-xl max-h-[90vh] flex flex-col overflow-hidden rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="notifications-title">
                <div className="flex shrink-0 items-center justify-between border-b border-bunker-800 px-5 py-4">
                    <div><p className="eyebrow">CANLI MERKEZ</p><h2 id="notifications-title" className="font-mono text-lg font-bold text-white">Bildirimler</h2></div>
                    <button type="button" onClick={() => setNotificationsOpen(false)} className="text-bunker-muted hover:text-white" aria-label="Bildirimleri kapat">✕</button>
                </div>
                <div className="max-h-[75vh] overflow-y-auto p-4">
                    {notifications.length === 0 ? <p className="py-8 text-center font-mono text-sm text-bunker-muted">Henüz bildirim yok.</p> : <div className="space-y-2">{notifications.map((item, index) => <article key={item.id || index} className="rounded-lg border border-bunker-800 bg-bunker-900/70 p-3"><div className="flex items-start justify-between gap-3">{item.symbol ? <SymbolLink symbol={item.symbol} className="font-bold text-neon-green hover:text-white" /> : <span className="font-mono text-sm font-bold text-neon-green">SİSTEM</span>}<time className="font-mono text-[10px] text-bunker-muted">{formatNotificationDate(item.triggered_at)}</time></div><p className="mt-1 text-sm text-white">{item.message || item.reason || "Yeni alarm bildirimi"}</p>{item.ml_hit_probability != null && <span className={`mt-1 inline-block ${ML_PROB_CLASS}`} title={ML_PROB_TITLE}>ML {formatMlProbability(item.ml_hit_probability)}</span>}</article>)}</div>}
                </div>
            </section>
        </div>}
        </>
    );
}

