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
import { canViewMacdMonitor } from "../lib/macdAccess";
import { ML_PROB_CLASS, ML_PROB_TITLE, formatMlProbability } from "../lib/mlProbability";
import { visibleGroups } from "../lib/menu";
import { useExchange } from "../lib/exchange";

const formatNotificationDate = (value: unknown) => {
    const numeric = Number(value);
    const date = Number.isFinite(numeric) ? new Date(toMs(numeric)) : new Date(String(value || ""));
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("tr-TR");
};

export default function Sidebar() {
    const pathname = usePathname();
    const { username, role, logout } = useAuth();
    const isAdmin = role === "admin";
    const canViewMacd = canViewMacdMonitor(role, username);
    const exchange = useExchange();
    // Menü borsaya göre değişir: `/binance-tr` private API'ye bağlıdır ve
    // Global örneğinde (api.binance.com) hiç çalışmaz.
    const isGlobal = exchange.exchange === "binance_global";
    const groups = visibleGroups({ isAdmin, canViewMacd, isGlobal });
    const [open, setOpen] = useState(false);
    // Grup açık/kapalı durumu. undefined = varsayılan (ana açık, diğerleri kapalı).
    const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
    const [busyLogout, setBusyLogout] = useState(false);
    const [installEvent, setInstallEvent] = useState<any>(null);
    const [installed, setInstalled] = useState(false);
    const [notifications, setNotifications] = useState<any[]>([]);
    const [unread, setUnread] = useState(0);
    const [notificationsOpen, setNotificationsOpen] = useState(false);
    const [health, setHealth] = useState<any>(null);
    const liveStatus = useLiveStatus();
    const onLiveMessage = useCallback((message: any) => {
        if (message.type !== "alert") return;
        const item = { ...(message.data || {}), id: message.data?.id || `${Date.now()}`, triggered_at: message.data?.triggered_at || Date.now() / 1000 };
        setNotifications((current) => [item, ...current.filter((entry) => entry.id !== item.id)].slice(0, 30));
        setUnread((count) => count + 1);
    }, []);
    useLiveMessages(onLiveMessage);
    useEffect(() => {
        if ("serviceWorker" in navigator) {
            if (process.env.NODE_ENV === "production") {
                // PUSH-RESILIENCE (2026-09-16): SW'ye VAPID public key'i SORGU ile
                // geçir. Service worker bundle'ı `process.env` göremez; abonelik
                // döndüğünde (`pushsubscriptionchange`) yeniden abone olmak için
                // anahtara ihtiyaç duyar. Anahtar, abonelik kadar uzun olmayan
                // base64url olduğundan sorgu parametresi güvenli.
                const vapid = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || "";
                navigator.serviceWorker.register(
                    `/sw.js?v=${process.env.NEXT_PUBLIC_BUILD_ID || "dev"}${vapid ? `&vapid=${encodeURIComponent(vapid)}` : ""}`,
                ).catch(() => undefined);
            }
            else navigator.serviceWorker.getRegistrations().then((registrations) => registrations.forEach((registration) => registration.unregister()));
        }
        const handler = (event: Event) => { event.preventDefault(); setInstallEvent(event); };
        window.addEventListener("beforeinstallprompt", handler);
        const installedHandler = () => setInstalled(true);
        window.addEventListener("appinstalled", installedHandler);
        return () => {
            window.removeEventListener("beforeinstallprompt", handler);
            window.removeEventListener("appinstalled", installedHandler);
        };
    }, []);
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
            .then((data) => setNotifications((data.events || []).slice(0, 30)))
            .catch(() => undefined);
        load();
    }, []);
    const loadHealth = useCallback(() => {
        apiFetch("/api/system/health").then(setHealth).catch(() => setHealth(null));
    }, []);
    useEffect(() => { loadHealth(); }, [loadHealth]);
    useVisibleInterval(loadHealth, 10_000);
    const isStandalone = typeof window !== "undefined" && (window.matchMedia?.("(display-mode: standalone)").matches || (window.navigator as any)?.standalone === true);
    const install = async () => {
        if (!installEvent) return;
        await installEvent.prompt();
        setInstallEvent(null);
    };

    return (
        <>
            <Button className="mobile-menu-button" onClick={() => setOpen(true)} aria-label="Menüyü aç">☰</Button>
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
                {/* Global Borsa Rozet Kartı: TR ile yan yana açıldığında anında ayırt edilir */}
                <div className="mt-3 rounded-lg border border-cyan-500/30 bg-gradient-to-r from-cyan-950/60 via-slate-900/60 to-blue-950/50 p-2.5 shadow-[0_4px_16px_rgba(0,0,0,0.3)]">
                    <div className="flex items-center justify-between font-mono">
                        <span className="flex items-center gap-1.5 text-xs font-bold text-cyan-300">
                            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_#00f0ff]" />
                            {exchange.loading ? "Borsa belirleniyor…" : exchange.label.toUpperCase()}
                        </span>
                        <span className="rounded bg-cyan-400/20 px-2.5 py-0.5 text-[11px] font-bold text-cyan-200 border border-cyan-400/40 shadow-[0_0_8px_rgba(0,240,255,0.2)]">
                            $
                        </span>
                    </div>
                    <div className="mt-1.5 flex items-center justify-between text-[10px] text-cyan-400/70 font-mono border-t border-cyan-500/20 pt-1.5">
                        <span>PİYASA: GLOBAL SPOT</span>
                        <span className="text-amber-400 font-bold">PAPER TRADING</span>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => { setNotificationsOpen(true); setUnread(0); }}
                    className="relative mt-3.5 flex w-full items-center justify-between rounded-lg border border-bunker-700 bg-bunker-950/70 px-3 py-2 text-left transition-colors hover:border-neon-green/50"
                    aria-label={`Bildirimleri aç${unread ? `, ${unread} yeni bildirim` : ""}`}
                >
                    <span className="flex items-center gap-2 font-mono text-xs text-white"><span className="text-lg">🔔</span> BİLDİRİMLER</span>
                    {unread > 0 && <span className="min-w-5 rounded-full bg-neon-red px-1.5 py-0.5 text-center font-mono text-[10px] font-bold text-white">{unread > 99 ? "99+" : unread}</span>}
                </button>
            </div>

            <nav className="flex-1 overflow-y-auto p-3 space-y-3" aria-label="Ana gezinme">
                {groups.map((group) => {
                    if (!group.items.length) return null;
                    // 2026-09-27: `ana` grubu DÜZ liste (grup başlığı yok —
                    // kullanıcı "gruplamayı kaldır" istedi). `diger` grubu
                    // açık/kapalı chevron'lu; varsayılan kapalı.
                    const isFlat = group.id === "ana";
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
                                // Terminal etiketi çalışan borsaya göre değişir:
                                // TR örneğinde "Binance TR", Global'da
                                // "Binance Global". Borsa henüz okunmadıysa
                                // jenerik "Binance" kalır — yanlış borsa adı
                                // göstermektense bunu söylemek yeğdir.
                                const label = m.exchangeLabel
                                    ? (exchange.loading ? m.label : exchange.label)
                                    : m.label;
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
            </nav>

            <div className="p-4 border-t border-bunker-800">
                {username && (
                    <div className="mb-3">
                        {/* 2026-09-27: Profil Ayarlar'a sekme taşındı (admin-only). */}
                        <Link href={isAdmin ? "/settings?tab=profile" : "/settings"} title={isAdmin ? "Ayarlar — Profil sekmesi" : "Ayarlar"} className="mb-1 flex items-center gap-1.5 rounded-lg border border-transparent px-1 py-1 font-mono text-[11px] text-bunker-muted transition-colors hover:border-bunker-700 hover:bg-bunker-800/60 hover:text-white">
                            <span className="w-1.5 h-1.5 rounded-full bg-neon-green" />
                            <span className="truncate">{username}</span>
                            <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] ${isAdmin ? "border border-neon-green/50 text-neon-green" : "border border-bunker-600 text-bunker-muted"}`}>{isAdmin ? "ADMIN" : "USER"}</span>
                            <span className="ml-auto text-[10px] opacity-60">⚙</span>
                        </Link>
                        <button
                            type="button"
                            onClick={async () => { setBusyLogout(true); try { await logout?.(); } finally { setBusyLogout(false); } }}
                            disabled={busyLogout}
                            className="flex w-full items-center justify-center gap-2 rounded-lg border border-bunker-700 bg-bunker-950/70 px-3 py-2 font-mono text-[11px] font-bold text-bunker-muted transition-colors hover:border-neon-red/60 hover:bg-neon-red/10 hover:text-neon-red disabled:opacity-50"
                            title="Oturumu kapat ve giriş ekranına dön"
                        >
                            {busyLogout ? "ÇIKILIYOR…" : "⏻ OTURUMU KAPAT"}
                        </button>
                    </div>
                )}
                <Button variant={installEvent ? "primary" : "secondary"} onClick={install} disabled={!installEvent} className="w-full mb-4">⬇ {installEvent ? "UYGULAMA OLARAK YÜKLE" : "YÜKLEME İÇİN TARAYICI MENÜSÜ"}</Button>
                {!installed && !installEvent && !isStandalone && (
                    <div className="mb-4 rounded-lg border border-bunker-700 bg-bunker-900/70 p-3">
                        <p className="font-mono text-xs font-bold text-white">📱 UYGULAMA OLARAK YÜKLE</p>
                        <p className="mt-1 text-[11px] leading-relaxed text-bunker-muted">
                            {/iPad|iPhone|iPod/.test(navigator.userAgent)
                                ? "Tarayıcıda Paylaş (⎋) → “Ana Ekrana Ekle” ile kurun."
                                : "Butonu kullanarak uygulamayı cihazınıza kurun."}
                        </p>
                    </div>
                )}
                <Link
                    href="/system-health"
                    onClick={() => setOpen(false)}
                    className={`group block rounded-lg border p-2.5 transition-all ${
                        pathname === "/system-health"
                            ? "border-neon-green/50 bg-neon-green/10"
                            : "border-bunker-800 bg-bunker-950/60 hover:border-bunker-700 hover:bg-bunker-900/80"
                    }`}
                    title="Detaylı sistem sağlığını görüntüle"
                >
                    <div className="flex items-center justify-between">
                        <p className="eyebrow group-hover:text-white transition-colors">SİSTEM SAĞLIĞI</p>
                        <span className="font-mono text-[10px] text-bunker-muted group-hover:text-neon-green transition-colors">Detay →</span>
                    </div>
                    <p className={`font-mono text-xs mt-1 flex items-center gap-1.5 ${health?.status === "ok" && liveStatus === "open" ? "text-neon-green" : "text-yellow-300"}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${health?.status === "ok" && liveStatus === "open" ? "bg-neon-green animate-pulse" : "bg-yellow-300"}`} />
                        {health ? `${String(health.status || "bilinmiyor").toUpperCase()} · WS ${liveStatus === "open" ? "BAĞLI" : "KAPALI"}` : "BAĞLANTI BEKLENİYOR"}
                    </p>
                    <p className="font-mono text-[10px] text-bunker-muted mt-0.5">Canlı servis & altyapı durumu</p>
                </Link>
                <p className="mt-2 font-mono text-[9px] text-bunker-muted/60" title="Build ID — eğer güncelleme sonrası bu değişmişse yeni sürüm yüklenmiştir">
                  ● v{typeof window !== "undefined" ? (document.documentElement.dataset.buildId || process.env.NEXT_PUBLIC_BUILD_ID || "dev") : (process.env.NEXT_PUBLIC_BUILD_ID || "dev")}
                </p>
            </div>
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

