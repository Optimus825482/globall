"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "./ui";
import { apiFetch } from "../lib/api";
import { useLiveStatus } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import { useAuth } from "../lib/auth";
import { visibleGroups } from "../lib/menu";
import NavIcon from "./NavIcon";

import { usePwa } from "../lib/pwa";

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
    const [health, setHealth] = useState<any>(null);
    const liveStatus = useLiveStatus();
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
                        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-400/30">
                            <NavIcon name="logo" className="w-5 h-5 text-cyan-300" />
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
            </div>

            <nav className="flex-1 overflow-y-auto p-3 space-y-4" aria-label="Ana gezinme">
                {groups.map((group) => {
                    if (!group.items.length) return null;
                    // 2026-10-30: gruplar (İZLE / İŞLEM / ANALİZ / SİSTEM) her zaman
                    // açık; başlık yalnız etiket. Açıklamalar ipucu (title) olarak kalır.
                    const isFlat = true;
                    const open = openGroups[group.id] ?? isFlat;
                    return (
                        <div key={group.id} className="space-y-1">
                            <p className="px-3 pt-1 font-mono text-[10px] font-bold tracking-[0.14em] text-bunker-muted/70">
                                {group.label}
                            </p>
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
                                        className={`block px-3 py-2 rounded-lg border transition-colors touch-target ${active
                                            ? "bg-neon-green/10 border-neon-green/30"
                                            : "border-transparent hover:bg-bunker-800/60 hover:border-bunker-700"
                                            }`}
                                    >
                                        <span className="flex items-center gap-2.5">
                                            <NavIcon name={m.icon} />
                                            <span className={`font-mono text-sm ${active ? "text-neon-green font-bold" : "text-white"}`}>
                                                {label}
                                            </span>
                                        </span>
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
                        
                    </div>
                </div>
            </nav>
        </aside>
        </>
    );
}

