"use client";

// ============================================================================
// ORTAK PARAMETRE PANELİ — Forex Çoklu Algoritma & 31 Sembol Yönetim Paneli
// ============================================================================

import React, { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";

export interface AutoSettings {
  enabled: boolean;
  llm_review_enabled?: boolean;
  llm_review_mode?: "veto" | "advisory";
  llm_review_fail_open?: boolean;
  llm_review_min_confidence?: number;
  llm_review_timeout_sec?: number;
  balance: number;
  risk_per_trade_pct: number;
  risk_gold_pct?: number;
  risk_crypto_index_pct?: number;
  loss_streak_limit?: number;
  loss_streak_cooldown_sec?: number;
  be_trigger_r_mult?: number;
  max_open_positions: number;
  max_positions_per_symbol?: number;
  min_score: number;
  tp_pips: number;
  sl_pips: number;
  breakeven_pips: number;
  trailing_stop_pips: number;
  session_filter: boolean;
  max_spread_pips: number;
  gold_cooldown_sec?: number;
  btc_min_score?: number;
  btc_cooldown_sec?: number;
  allowed_symbols: string[];
  mode_symbols?: string[];
  mode_exclusive?: string[];
  donchian_adx_min?: number;
  donchian_max_per_day?: number;
  ema_adx_enabled?: boolean;
  ema_adx_symbols?: string[];
  ema_adx_adx_min?: number;
  ema_adx_touch_atr?: number;
  ema_adx_sl_atr?: number;
  ema_adx_tp_atr?: number;
  ema_adx_max_per_day?: number;
  lb_enabled?: boolean;
  lb_symbols?: string[];
  lb_box_end_utc?: number;
  lb_entry_end_utc?: number;
  lb_sl_box_frac?: number;
  lb_tp_r?: number;
  lb_max_per_day?: number;
  s3_enabled?: boolean;
  s3_symbols_5m?: string[];
  s3_symbols_15m?: string[];
  s3_adx_min?: number;
  s3_rsi_lo?: number;
  s3_sl_atr?: number;
  s3_tp_atr_15m?: number;
  squeeze_kc_symbols?: string[];
  squeeze_kc_period?: number;
  squeeze_kc_bb_mult?: number;
  squeeze_kc_mult?: number;
  squeeze_kc_mom_min?: number;
  combo3_enabled?: boolean;
  combo3_symbols?: string[];
  combo3_risk_pct?: number;
  combo3_sl_atr?: number;
  combo3_tp_r?: number;
  combo3_max_per_day?: number;
  kombo_enabled?: boolean;
  kombo_symbols?: string[];
  kombo_risk_pct?: number;
  kombo_max_per_day?: number;
  kombo_tanimlar?: { ad: string; tag?: string; tanim?: Record<string, any> }[];
  fvg_pullback_enabled?: boolean;
  fvg_symbols?: string[];
  fvg_tp_r?: number;
  [key: string]: any;
}

export interface SymbolDef {
  sym: string;
  label: string;
  group: "Majörler" | "Emtia & Endeks" | "Kripto (7/24)" | "JPY Krosları" | "EUR Krosları" | "GBP Krosları" | "Diğer Kroslar";
}

export const ALL_31_SYMBOLS: SymbolDef[] = [
  // Majörler (7)
  { sym: "EURUSD", label: "EUR/USD", group: "Majörler" },
  { sym: "GBPUSD", label: "GBP/USD", group: "Majörler" },
  { sym: "USDJPY", label: "USD/JPY", group: "Majörler" },
  { sym: "USDCHF", label: "USD/CHF", group: "Majörler" },
  { sym: "AUDUSD", label: "AUD/USD", group: "Majörler" },
  { sym: "USDCAD", label: "USD/CAD", group: "Majörler" },
  { sym: "NZDUSD", label: "NZD/USD", group: "Majörler" },

  // Emtia, Kripto ve Endeksler (4)
  { sym: "XAUUSD", label: "Ons Altın (XAU)", group: "Emtia & Endeks" },
  { sym: "BTCUSD", label: "Bitcoin (BTC)", group: "Emtia & Endeks" },
  { sym: "NAS100", label: "Nasdaq 100 (USTEC)", group: "Emtia & Endeks" },
  { sym: "US30", label: "Dow Jones (US30)", group: "Emtia & Endeks" },

  // 7/24 Hafta Sonu Kriptoları (10)
  { sym: "ETHUSD", label: "Ethereum (ETH)", group: "Kripto (7/24)" },
  { sym: "SOLUSD", label: "Solana (SOL)", group: "Kripto (7/24)" },
  { sym: "BNBUSD", label: "Binance Coin (BNB)", group: "Kripto (7/24)" },
  { sym: "XRPUSD", label: "Ripple (XRP)", group: "Kripto (7/24)" },
  { sym: "LNKUSD", label: "Chainlink (LNK)", group: "Kripto (7/24)" },
  { sym: "UNIUSD", label: "Uniswap (UNI)", group: "Kripto (7/24)" },
  { sym: "AVXUSD", label: "Avalanche (AVAX)", group: "Kripto (7/24)" },
  { sym: "ADAUSD", label: "Cardano (ADA)", group: "Kripto (7/24)" },
  { sym: "XTZUSD", label: "Tezos (XTZ)", group: "Kripto (7/24)" },
  { sym: "DATAUSD", label: "Streamr (DATA)", group: "Kripto (7/24)" },

  // JPY Krosları (6)
  { sym: "GBPJPY", label: "GBP/JPY", group: "JPY Krosları" },
  { sym: "EURJPY", label: "EUR/JPY", group: "JPY Krosları" },
  { sym: "CHFJPY", label: "CHF/JPY", group: "JPY Krosları" },
  { sym: "CADJPY", label: "CAD/JPY", group: "JPY Krosları" },
  { sym: "AUDJPY", label: "AUD/JPY", group: "JPY Krosları" },
  { sym: "NZDJPY", label: "NZD/JPY", group: "JPY Krosları" },

  // EUR Krosları (5)
  { sym: "EURGBP", label: "EUR/GBP", group: "EUR Krosları" },
  { sym: "EURCHF", label: "EUR/CHF", group: "EUR Krosları" },
  { sym: "EURCAD", label: "EUR/CAD", group: "EUR Krosları" },
  { sym: "EURAUD", label: "EUR/AUD", group: "EUR Krosları" },
  { sym: "EURNZD", label: "EUR/NZD", group: "EUR Krosları" },

  // GBP Krosları (4)
  { sym: "GBPCHF", label: "GBP/CHF", group: "GBP Krosları" },
  { sym: "GBPAUD", label: "GBP/AUD", group: "GBP Krosları" },
  { sym: "GBPCAD", label: "GBP/CAD", group: "GBP Krosları" },
  { sym: "GBPNZD", label: "GBP/NZD", group: "GBP Krosları" },

  // Diğer Kroslar (5)
  { sym: "AUDCAD", label: "AUD/CAD", group: "Diğer Kroslar" },
  { sym: "AUDNZD", label: "AUD/NZD", group: "Diğer Kroslar" },
  { sym: "AUDCHF", label: "AUD/CHF", group: "Diğer Kroslar" },
  { sym: "NZDCHF", label: "NZD/CHF", group: "Diğer Kroslar" },
  { sym: "CADCHF", label: "CAD/CHF", group: "Diğer Kroslar" },
];

const GROUPS = ["Hepsi", "Majörler", "Emtia & Endeks", "Kripto (7/24)", "JPY Krosları", "EUR Krosları", "GBP Krosları", "Diğer Kroslar"] as const;

interface SymbolMultiSelectorProps {
  selected: string[];
  onChange: (next: string[]) => void;
  title: string;
  badgeLabel?: string;
  accentClass?: string;
  chipActiveClass?: string;
}

function SymbolMultiSelector({
  selected,
  onChange,
  title,
  badgeLabel,
  accentClass = "text-blue-400",
  chipActiveClass = "bg-blue-600/30 text-blue-300 border-blue-400/50",
}: SymbolMultiSelectorProps) {
  const [filterGroup, setFilterGroup] = useState<string>("Hepsi");

  const displayedSymbols = ALL_31_SYMBOLS.filter(
    (s) => filterGroup === "Hepsi" || s.group === filterGroup
  );

  const handleToggle = (sym: string) => {
    if (selected.includes(sym)) {
      onChange(selected.filter((s) => s !== sym));
    } else {
      onChange([...selected, sym]);
    }
  };

  const handleSelectGroup = (g: string) => {
    const groupSyms = ALL_31_SYMBOLS.filter((s) => g === "Hepsi" || s.group === g).map((s) => s.sym);
    const combined = Array.from(new Set([...selected, ...groupSyms]));
    onChange(combined);
  };

  const handleDeselectGroup = (g: string) => {
    const groupSyms = new Set(ALL_31_SYMBOLS.filter((s) => g === "Hepsi" || s.group === g).map((s) => s.sym));
    onChange(selected.filter((s) => !groupSyms.has(s)));
  };

  return (
    <div className="p-3 rounded-xl bg-bunker-950/80 border border-bunker-800 space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-bunker-800/80 pb-2">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-bold ${accentClass}`}>{title}</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-bunker-800 text-bunker-muted font-bold">
            {selected.length} / {ALL_31_SYMBOLS.length} Seçili
          </span>
          {badgeLabel && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
              {badgeLabel}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-[10px]">
          <button
            type="button"
            onClick={() => handleSelectGroup(filterGroup)}
            className="px-2 py-0.5 rounded bg-bunker-800 hover:bg-bunker-700 text-white font-medium transition-colors"
          >
            {filterGroup === "Hepsi" ? "Tümünü Seç" : `Gruptakileri Seç`}
          </button>
          <button
            type="button"
            onClick={() => handleDeselectGroup(filterGroup)}
            className="px-2 py-0.5 rounded bg-bunker-800 hover:bg-bunker-700 text-bunker-muted hover:text-white transition-colors"
          >
            {filterGroup === "Hepsi" ? "Temizle" : `Gruptakileri Kaldır`}
          </button>
        </div>
      </div>

      {/* Kategori Filtresi */}
      <div className="flex flex-wrap gap-1">
        {GROUPS.map((grp) => (
          <button
            key={grp}
            type="button"
            onClick={() => setFilterGroup(grp)}
            className={`px-2 py-0.5 rounded text-[10px] font-semibold transition-all ${
              filterGroup === grp
                ? "bg-bunker-800 text-white border border-bunker-600 shadow-sm"
                : "text-bunker-muted hover:text-bunker-300 bg-transparent"
            }`}
          >
            {grp}
          </button>
        ))}
      </div>

      {/* Sembol Çipleri */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-1.5 max-h-48 overflow-y-auto pr-1">
        {displayedSymbols.map((item) => {
          const active = selected.includes(item.sym);
          return (
            <button
              key={item.sym}
              type="button"
              onClick={() => handleToggle(item.sym)}
              className={`px-2 py-1.5 rounded-lg text-left text-[11px] font-bold border transition-all flex items-center justify-between ${
                active
                  ? chipActiveClass
                  : "bg-bunker-900/50 text-bunker-muted border-bunker-800/80 hover:border-bunker-700 hover:text-white"
              }`}
            >
              <span className="truncate">{item.label}</span>
              <span className="text-[10px] ml-1 opacity-80">{active ? "✓" : "+"}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface AutoSettingsPanelProps {
  show: boolean;
  onClose: () => void;
  appliedSettings: AutoSettings;
  onSaved: (settings: AutoSettings) => void;
  accent?: "amber" | "blue";
}

type TabKey = "risk" | "radar" | "fvg" | "donchian" | "ema_adx" | "london_box" | "s3" | "squeeze" | "combo3" | "kombo";

export default function AutoSettingsPanel({
  show,
  onClose,
  appliedSettings,
  onSaved,
  accent = "blue",
}: AutoSettingsPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("risk");
  const [form, setForm] = useState<AutoSettings>(() => ({
    ...appliedSettings,
    allowed_symbols: appliedSettings?.allowed_symbols?.length ? appliedSettings.allowed_symbols : ["XAUUSD", "BTCUSD", "US30", "NAS100", "AUDCAD"],
    fvg_pullback_enabled: appliedSettings?.fvg_pullback_enabled ?? true,
    fvg_symbols: appliedSettings?.fvg_symbols?.length ? appliedSettings.fvg_symbols : ["SOLUSD", "UNIUSD", "XTZUSD", "LNKUSD", "BTCUSD", "BNBUSD", "AVXUSD", "ETHUSD", "ADAUSD", "DATAUSD"],
    fvg_tp_r: appliedSettings?.fvg_tp_r ?? 1.8,
  }));
  const [isSaving, setIsSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    if (show) {
      setForm({
        ...appliedSettings,
        allowed_symbols: appliedSettings?.allowed_symbols?.length ? appliedSettings.allowed_symbols : ["XAUUSD", "BTCUSD", "US30", "NAS100", "AUDCAD"],
        fvg_pullback_enabled: appliedSettings?.fvg_pullback_enabled ?? true,
        fvg_symbols: appliedSettings?.fvg_symbols?.length ? appliedSettings.fvg_symbols : ["SOLUSD", "UNIUSD", "XTZUSD", "LNKUSD", "BTCUSD", "BNBUSD", "AVXUSD", "ETHUSD", "ADAUSD", "DATAUSD"],
        fvg_tp_r: appliedSettings?.fvg_tp_r ?? 1.8,
      });
      setSaveMsg(null);
    }
  }, [show, appliedSettings]);

  if (!show) return null;

  const acc =
    accent === "amber"
      ? {
          border: "border-amber-500/40",
          icon: "text-amber-400",
          focus: "focus:border-amber-400",
          saveBtn: "bg-amber-600 hover:bg-amber-500",
          tabActive: "bg-amber-500/20 text-amber-300 border-amber-500/50",
          check: "text-amber-500",
          activeChip: "bg-amber-600/30 text-amber-300 border-amber-400/50",
        }
      : {
          border: "border-blue-500/40",
          icon: "text-blue-400",
          focus: "focus:border-blue-400",
          saveBtn: "bg-blue-600 hover:bg-blue-500",
          tabActive: "bg-blue-500/20 text-blue-300 border-blue-500/50",
          check: "text-blue-500",
          activeChip: "bg-blue-600/30 text-blue-300 border-blue-400/50",
        };

  const setField = (key: keyof AutoSettings, val: any) =>
    setForm((prev) => ({ ...prev, [key]: val } as AutoSettings));
  const setNumField = (key: keyof AutoSettings, raw: string) =>
    setForm((prev) => ({ ...prev, [key]: raw === "" ? "" : parseFloat(raw) } as AutoSettings));
  const setIntField = (key: keyof AutoSettings, raw: string) =>
    setForm((prev) => ({ ...prev, [key]: raw === "" ? "" : parseInt(raw) } as AutoSettings));

  const num = (v: any, fallback: number) => {
    const p = parseFloat(v);
    return isNaN(p) ? fallback : p;
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveMsg(null);
    try {
      const payload: AutoSettings = {
        ...appliedSettings,
        ...form,
        risk_per_trade_pct: num(form.risk_per_trade_pct, appliedSettings.risk_per_trade_pct || 15.0),
        risk_gold_pct: num(form.risk_gold_pct, appliedSettings.risk_gold_pct || 7.0),
        risk_crypto_index_pct: num(form.risk_crypto_index_pct, appliedSettings.risk_crypto_index_pct || 2.0),
        loss_streak_limit: num(form.loss_streak_limit, appliedSettings.loss_streak_limit || 2),
        loss_streak_cooldown_sec: num(form.loss_streak_cooldown_sec, appliedSettings.loss_streak_cooldown_sec || 900.0),
        be_trigger_r_mult: num(form.be_trigger_r_mult, appliedSettings.be_trigger_r_mult ?? 0.40),
        tp_pips: num(form.tp_pips, appliedSettings.tp_pips || 20.0),
        sl_pips: num(form.sl_pips, appliedSettings.sl_pips || 8.0),
        breakeven_pips: num(form.breakeven_pips, appliedSettings.breakeven_pips ?? 14.0),
        trailing_stop_pips: num(form.trailing_stop_pips, appliedSettings.trailing_stop_pips || 35.0),
        min_score: num(form.min_score, appliedSettings.min_score || 75.0),
        btc_min_score: num(form.btc_min_score, appliedSettings.btc_min_score ?? 76.0),
        max_spread_pips: num(form.max_spread_pips, appliedSettings.max_spread_pips || 30.0),
        max_open_positions: Math.max(1, Math.min(99, Math.round(num(form.max_open_positions, 20)))),
        max_positions_per_symbol: Math.max(1, Math.min(5, Math.round(num(form.max_positions_per_symbol, 2)))),
        gold_cooldown_sec: Math.max(60, num(form.gold_cooldown_sec, 60.0)),
        session_filter: Boolean(form.session_filter),
        allowed_symbols: form.allowed_symbols && form.allowed_symbols.length > 0 ? form.allowed_symbols : ["XAUUSD", "BTCUSD", "US30", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "AUDNZD", "GBPJPY", "EURJPY", "NAS100", "USDCHF", "AUDCAD"],
        mode_symbols: form.mode_symbols || ["XAUUSD", "GBPJPY", "EURJPY", "NAS100"],
        mode_exclusive: form.mode_exclusive || ["GBPJPY", "EURJPY"],
        ema_adx_symbols: form.ema_adx_symbols || ["XAUUSD", "NAS100"],
        lb_symbols: form.lb_symbols || ["XAUUSD", "GBPUSD", "USDJPY", "BTCUSD", "USDCHF", "US30"],
        s3_symbols_5m: form.s3_symbols_5m || ["XAUUSD"],
        s3_symbols_15m: form.s3_symbols_15m || ["XAUUSD", "BTCUSD", "US30", "GBPUSD"],
        squeeze_kc_symbols: form.squeeze_kc_symbols || ["XAUUSD", "BTCUSD", "US30", "NAS100", "USDCHF"],
        fvg_pullback_enabled: Boolean(form.fvg_pullback_enabled),
        fvg_symbols: form.fvg_symbols || ["SOLUSD", "UNIUSD", "XTZUSD", "LNKUSD", "BTCUSD", "BNBUSD", "AVXUSD", "ETHUSD", "ADAUSD", "DATAUSD"],
        fvg_tp_r: num(form.fvg_tp_r, 1.8),
        // Combo3 (M5) paper-ölçüm kolu — 2026-10-28
        combo3_enabled: form.combo3_enabled ?? false,
        combo3_symbols: form.combo3_symbols || ["XAUUSD"],
        combo3_risk_pct: num(form.combo3_risk_pct, 1.0),
        combo3_sl_atr: num(form.combo3_sl_atr, 1.5),
        combo3_tp_r: num(form.combo3_tp_r, 2.0),
        combo3_max_per_day: Math.max(0, Math.round(num(form.combo3_max_per_day, 0))),
        // Kombo XAU (M5) demo ölçüm kolu — 2026-10-28 (tanımlar sunucu varsayılanı; UI'dan değiştirilmez)
        kombo_enabled: form.kombo_enabled ?? true,
        kombo_symbols: form.kombo_symbols || ["XAUUSD"],
        kombo_risk_pct: num(form.kombo_risk_pct, 2.0),
        kombo_max_per_day: Math.max(0, Math.round(num(form.kombo_max_per_day, 0))),
      };

      const res = await apiFetch("/api/forex/auto-paper/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res && res.status === "ok") {
        onSaved(res.settings);
        setSaveMsg("✓ Algoritma ve parite parametreleri kaydedildi!");
        setTimeout(() => {
          onClose();
          setSaveMsg(null);
        }, 1200);
      }
    } catch (err) {
      console.error("Ayarları kaydetme hatası:", err);
      alert("Parametre kaydedilirken bir hata oluştu.");
    } finally {
      setIsSaving(false);
    }
  };

  const inputCls = `w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none ${acc.focus}`;

  return (
    <form
      onSubmit={handleSave}
      className={`p-5 rounded-2xl bg-bunker-900/98 ${acc.border} border shadow-2xl space-y-4 animate-in fade-in slide-in-from-top-2 duration-200 max-w-4xl mx-auto`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
        <div className="flex items-center gap-2">
          <span className={`${acc.icon} font-bold text-base`}>⚙️</span>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Forex Çoklu Algoritma &amp; 31 Sembol Risk Yönetimi
            </h3>
            <span className="text-[10px] text-bunker-muted">
              IC Markets MT5 canlı veri hattı ve bağımsız kârlılık strateji motorları
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-bunker-muted hover:text-white px-2 py-1 rounded bg-bunker-800"
        >
          ✕ Kapat
        </button>
      </div>

      {saveMsg && (
        <div className="p-3 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-bold flex items-center gap-2 animate-pulse">
          <span>{saveMsg}</span>
        </div>
      )}

      {/* Algoritma Sekmeleri */}
      <div className="flex flex-wrap gap-1.5 border-b border-bunker-800 pb-2">
        {[
          { id: "risk", label: "🎯 Genel Risk & Çıkış" },
          { id: "radar", label: `📡 Klasik Radar (${form.allowed_symbols?.length || 0})` },
          { id: "fvg", label: `⚡ FVG Pullback (${form.fvg_symbols?.length || 0})` },
          { id: "donchian", label: `🌊 Donchian ADX (${form.mode_symbols?.length || 0})` },
          { id: "ema_adx", label: `📐 EMA+ADX (${form.ema_adx_symbols?.length || 0})` },
          { id: "london_box", label: `🇬🇧 London Breakout (${form.lb_symbols?.length || 0})` },
          { id: "s3", label: `🚀 SuperTrend RSI (${(form.s3_symbols_5m?.length || 0) + (form.s3_symbols_15m?.length || 0)})` },
          { id: "squeeze", label: `⚡ Keltner Squeeze (${form.squeeze_kc_symbols?.length || 0})` },
          { id: "combo3", label: `🧩 Combo3 M5 (${form.combo3_symbols?.length || 0})${form.combo3_enabled === false ? " · kapalı" : ""}` },
          { id: "kombo", label: `🧪 Kombo XAU M5 (${form.kombo_symbols?.length || 0})${form.kombo_enabled === false ? " · kapalı" : ""}` },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id as TabKey)}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all border ${
              activeTab === tab.id
                ? acc.tabActive
                : "bg-bunker-950/60 text-bunker-muted border-bunker-800 hover:text-white"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* TAB 1: GENEL RİSK & ÇIKIŞ MOTORU */}
      {activeTab === "risk" && (
        <div className="space-y-4 animate-in fade-in duration-150">
          {/* LLM TRADER İNCELEMESİ: işlem açılmadan önce ikinci görüş */}
          <div className="p-3 rounded-xl bg-bunker-950/80 border border-cyan-500/30 space-y-2.5">
            <div className="flex items-center justify-between border-b border-bunker-800/80 pb-2">
              <span className="text-xs font-bold text-cyan-300">LLM Trader İncelemesi (işlem açılmadan önce)</span>
              <span className={`text-[10px] px-2 py-0.5 rounded border font-bold ${form.llm_review_enabled !== false ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30" : "bg-bunker-800 text-bunker-muted border-bunker-700"}`}>
                {form.llm_review_enabled !== false ? "AÇIK" : "KAPALI"}
              </span>
            </div>
            <label className="inline-flex items-start gap-2 cursor-pointer text-xs">
              <input
                type="checkbox"
                checked={form.llm_review_enabled !== false}
                onChange={(e) => setField("llm_review_enabled", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4 mt-0.5`}
              />
              <span>
                <span className="text-white font-semibold block">Açılmadan önce LLM değerlendirsin</span>
                <span className="text-[10px] text-bunker-muted">
                  Motor bir işlemi açmadan önce deneyimli trader istemiyle LLM: çok zaman dilimli analiz, mum formasyonları, destek/direnç,
                  ekonomik takvim, haberler, dolar ve açık pozisyon yığılmasına bakıp ONAY/RED verir. Her karar kaydedilir; sonuçları
                  Raporlar &gt; LLM Kararları sekmesinde.
                </span>
              </span>
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs pt-1">
              <div>
                <label className="text-[11px] text-bunker-muted block mb-1">Çalışma modu:</label>
                <select
                  value={form.llm_review_mode ?? "veto"}
                  onChange={(e) => setField("llm_review_mode", e.target.value)}
                  className={`${inputCls}`}
                >
                  <option value="veto">Veto: LLM reddederse işlem açılmaz</option>
                  <option value="advisory">Danışman: yalnız kaydeder, engellemez (deneme)</option>
                </select>
              </div>
              <div>
                <label className="text-[11px] text-bunker-muted block mb-1">Onay için min. güven (0-100):</label>
                <input
                  type="number" min="0" max="100"
                  value={form.llm_review_min_confidence ?? 55}
                  onChange={(e) => setNumField("llm_review_min_confidence", e.target.value)}
                  className={`${inputCls} text-cyan-300`}
                />
              </div>
              <div>
                <label className="text-[11px] text-bunker-muted block mb-1">En fazla bekleme (sn, 3-90):</label>
                <input
                  type="number" min="3" max="90" step="1"
                  value={form.llm_review_timeout_sec ?? 25}
                  onChange={(e) => setNumField("llm_review_timeout_sec", e.target.value)}
                  className={`${inputCls} text-cyan-300`}
                />
              </div>
              <label className="inline-flex items-start gap-2 cursor-pointer self-end">
                <input
                  type="checkbox"
                  checked={form.llm_review_fail_open !== false}
                  onChange={(e) => setField("llm_review_fail_open", e.target.checked)}
                  className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4 mt-0.5`}
                />
                <span>
                  <span className="text-white font-semibold block">LLM yanıt vermezse işlem yine açılsın</span>
                  <span className="text-[10px] text-bunker-muted">Kapalıysa LLM yokken/yavaşken hiçbir işlem açılmaz.</span>
                </span>
              </label>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Forex Riski (% Bakiye):</label>
              <input
                type="number" step="0.5" min="0.1" max="30.0"
                value={form.risk_per_trade_pct ?? ""}
                onChange={(e) => setNumField("risk_per_trade_pct", e.target.value)}
                className={`${inputCls} text-blue-400 font-semibold`}
              />
              <span className="text-[10px] text-bunker-muted">Varsayılan: %15.0</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Altın (XAUUSD) Riski (%):</label>
              <input
                type="number" step="0.5" min="0.1" max="25.0"
                value={form.risk_gold_pct ?? ""}
                onChange={(e) => setNumField("risk_gold_pct", e.target.value)}
                className={`${inputCls} text-amber-400 font-semibold`}
              />
              <span className="text-[10px] text-bunker-muted">Varsayılan: %7.0</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">BTC / US30 / USTEC (%):</label>
              <input
                type="number" step="0.5" min="0.1" max="20.0"
                value={form.risk_crypto_index_pct ?? ""}
                onChange={(e) => setNumField("risk_crypto_index_pct", e.target.value)}
                className={`${inputCls} text-purple-400 font-semibold`}
              />
              <span className="text-[10px] text-bunker-muted">Varsayılan: %2.0</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Dinamik BE Kâr Kilidi (R):</label>
              <input
                type="number" step="0.05" min="0" max="2.0"
                value={form.be_trigger_r_mult ?? 0.40}
                onChange={(e) => setNumField("be_trigger_r_mult", e.target.value)}
                className={`${inputCls} text-cyan-400 font-semibold`}
              />
              <span className="text-[10px] text-bunker-muted">0 = Kapalı (Varsayılan: 0.40R)</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Kâr Al (TP Pips):</label>
              <input
                type="number" min="5" max="120"
                value={form.tp_pips ?? ""}
                onChange={(e) => setNumField("tp_pips", e.target.value)}
                className={`${inputCls} text-emerald-400`}
              />
              <span className="text-[10px] text-bunker-muted">Klasik hedef scalp kârı</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Zarar Durdur (SL Pips):</label>
              <input
                type="number" min="4" max="60"
                value={form.sl_pips ?? ""}
                onChange={(e) => setNumField("sl_pips", e.target.value)}
                className={`${inputCls} text-rose-400`}
              />
              <span className="text-[10px] text-bunker-muted">Sıkı Scalper SL</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Başabaş (BE Pips):</label>
              <input
                type="number" min="0" max="50"
                value={form.breakeven_pips ?? ""}
                onChange={(e) => setNumField("breakeven_pips", e.target.value)}
                className={`${inputCls} text-cyan-300`}
              />
              <span className="text-[10px] text-bunker-muted">0 = Kapalı (Stopu girişe çeker)</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">İz Süren Stop (Trail Pips):</label>
              <input
                type="number" min="4" max="60"
                value={form.trailing_stop_pips ?? ""}
                onChange={(e) => setNumField("trailing_stop_pips", e.target.value)}
                className={`${inputCls} text-yellow-300`}
              />
              <span className="text-[10px] text-bunker-muted">Adım adım takip</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Maksimum Spread (Pip):</label>
              <input
                type="number" step="0.5" min="0.5" max="50"
                value={form.max_spread_pips ?? ""}
                onChange={(e) => setNumField("max_spread_pips", e.target.value)}
                className={`${inputCls} text-white`}
              />
              <span className="text-[10px] text-bunker-muted">Spread filtresi</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Maksimum Açık İşlem:</label>
              <input
                type="number" min="1" max="99"
                value={form.max_open_positions ?? 20}
                onChange={(e) => setIntField("max_open_positions", e.target.value)}
                className={`${inputCls} text-white font-semibold`}
              />
              <span className="text-[10px] text-bunker-muted">Tüm semboller toplamı</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Sembol Başına İşlem (Piramit):</label>
              <input
                type="number" min="1" max="5"
                value={form.max_positions_per_symbol ?? 2}
                onChange={(e) => setIntField("max_positions_per_symbol", e.target.value)}
                className={`${inputCls} text-emerald-400 font-semibold`}
              />
              <span className="text-[10px] text-bunker-muted">Aynı sembolde max işlem (1: Tek, 2-5: Kârlı ekleme)</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Altın Soğuma (sn):</label>
              <input
                type="number" min="60" max="900" step="10"
                value={form.gold_cooldown_sec ?? 60}
                onChange={(e) => setNumField("gold_cooldown_sec", e.target.value)}
                className={`${inputCls} text-amber-300`}
              />
              <span className="text-[10px] text-bunker-muted">XAUUSD bekleme</span>
            </div>
          </div>

          {/* Koruma Kalkanları */}
          <div className="p-3 rounded-xl bg-bunker-950/70 border border-bunker-800 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <label className="inline-flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(form.dxy_filter_enabled)}
                onChange={(e) => setField("dxy_filter_enabled", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4 mt-0.5`}
              />
              <span>
                <span className="text-white font-semibold block">DXY Rejim Filtresi</span>
                <span className="text-[10px] text-bunker-muted">Dolar yönüyle çelişen girişleri engeller</span>
              </span>
            </label>
            <label className="inline-flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(form.correlation_guard)}
                onChange={(e) => setField("correlation_guard", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4 mt-0.5`}
              />
              <span>
                <span className="text-white font-semibold block">Korelasyon Kalkanı</span>
                <span className="text-[10px] text-bunker-muted">Yüksek korelasyonlu yığılmaları sınırlar</span>
              </span>
            </label>
            <label className="inline-flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(form.session_filter)}
                onChange={(e) => setField("session_filter", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4 mt-0.5`}
              />
              <span>
                <span className="text-white font-semibold block">Seans Filtresi</span>
                <span className="text-[10px] text-bunker-muted">Asya seansı chop saatlerinde kısıtlar</span>
              </span>
            </label>
          </div>
        </div>
      )}

      {/* TAB 2: KLASİK RADAR / MOMENTUM */}
      {activeTab === "radar" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Min. Radar Skoru (50-98):</label>
              <input
                type="number" min="50" max="98"
                value={form.min_score ?? 75}
                onChange={(e) => setNumField("min_score", e.target.value)}
                className={`${inputCls} text-amber-300`}
              />
              <span className="text-[10px] text-bunker-muted">Tüm pariteler için teyit eşiği (Varsayılan 75)</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">₿ BTC Min. Skor (0-98):</label>
              <input
                type="number" min="0" max="98"
                value={form.btc_min_score ?? 76}
                onChange={(e) => setNumField("btc_min_score", e.target.value)}
                className={`${inputCls} text-orange-400`}
              />
              <span className="text-[10px] text-bunker-muted">BTCUSD özel eşiği (Varsayılan 76)</span>
            </div>
          </div>

          {/* 30 Dk Ekonomik Takvim Yön Desteği & Haber Koruması */}
          <div className="p-3 rounded-xl bg-bunker-950/80 border border-bunker-800 space-y-2.5">
            <div className="flex items-center justify-between border-b border-bunker-800/80 pb-2">
              <span className="text-xs font-bold text-amber-400 flex items-center gap-1.5">
                <span>Ekonomik Takvim Yön Desteği (30 Dk Momentum & Kalkan)</span>
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 font-bold">
                Haber Besleyicisi
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs pt-1">
              <label className="inline-flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(form.news_bias_enabled)}
                  onChange={(e) => setField("news_bias_enabled", e.target.checked)}
                  className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4 mt-0.5`}
                />
                <span>
                  <span className="text-white font-semibold block">Haber Yönü Besleyicisi</span>
                  <span className="text-[10px] text-bunker-muted">
                    Açıklanan verileri 30 dk boyunca radar taramasına ve otonom girişe yön desteği olarak besler
                  </span>
                </span>
              </label>

              <label className="inline-flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(form.news_bias_block_opposing)}
                  onChange={(e) => setField("news_bias_block_opposing", e.target.checked)}
                  className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4 mt-0.5`}
                />
                <span>
                  <span className="text-white font-semibold block">Karşıt Yön Koruması</span>
                  <span className="text-[10px] text-bunker-muted">
                    Ekonomik verinin zıttı yöndeki sahte kırılımları ve ters sinyalleri 30 dk engeller
                  </span>
                </span>
              </label>
            </div>
          </div>

          <SymbolMultiSelector
            title="Klasik Radar Sinyali Üretilen Semboller (allowed_symbols)"
            badgeLabel="Momentum Scalper"
            selected={form.allowed_symbols || []}
            onChange={(syms) => setField("allowed_symbols", syms)}
            accentClass="text-blue-400"
            chipActiveClass={acc.activeChip}
          />
        </div>
      )}

      {/* TAB: FVG FAIR VALUE GAP PULLBACK (M5) */}
      {activeTab === "fvg" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="p-3 rounded-xl bg-bunker-950/70 border border-bunker-800 flex flex-wrap items-center justify-between gap-3 text-xs">
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(form.fvg_pullback_enabled)}
                onChange={(e) => setField("fvg_pullback_enabled", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4`}
              />
              <div>
                <span className="text-white font-semibold block">FVG Pullback Motorunu Etkinleştir</span>
                <span className="text-[10px] text-bunker-muted">
                  IC Markets 5M kurumsal likidite boşluklarında (Fair Value Gap) pullback ve retest yakalar (Hafta sonu 7/24 kripto destekli)
                </span>
              </div>
            </label>

            <div className="flex items-center gap-2">
              <label className="text-[11px] text-bunker-muted whitespace-nowrap">TP Çarpanı (R):</label>
              <input
                type="number"
                step="0.1"
                min="1.0"
                max="5.0"
                value={form.fvg_tp_r ?? 1.8}
                onChange={(e) => setNumField("fvg_tp_r", e.target.value)}
                className="w-20 bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1 text-emerald-400 font-bold outline-none text-xs"
              />
            </div>
          </div>

          <SymbolMultiSelector
            title="FVG Pullback Aktif Semboller (fvg_symbols)"
            badgeLabel="Kurumsal FVG & Kripto 7/24"
            selected={form.fvg_symbols || []}
            onChange={(syms) => setField("fvg_symbols", syms)}
            accentClass="text-emerald-400"
            chipActiveClass="bg-emerald-600/30 text-emerald-300 border-emerald-400/50"
          />
        </div>
      )}

      {/* TAB 3: DONCHIAN BREAKOUT + ADX (M5) */}
      {activeTab === "donchian" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Donchian ADX Eşiği:</label>
              <input
                type="number" min="0" max="60" step="1"
                value={form.donchian_adx_min ?? 18}
                onChange={(e) => setNumField("donchian_adx_min", e.target.value)}
                className={`${inputCls} text-cyan-300`}
              />
              <span className="text-[10px] text-bunker-muted">Trend gücü filtresi (Varsayılan: 18)</span>
            </div>
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Yön Başına Günde Maksimum Giriş:</label>
              <input
                type="number" min="0" max="20" step="1"
                value={form.donchian_max_per_day ?? 2}
                onChange={(e) => setIntField("donchian_max_per_day", e.target.value)}
                className={`${inputCls} text-white`}
              />
              <span className="text-[10px] text-bunker-muted">Aşırı işlem engeli (0 = sınırsız)</span>
            </div>
          </div>

          <SymbolMultiSelector
            title="Donchian+ADX Kırılım Modu Aktif Semboller (mode_symbols)"
            badgeLabel="Donchian Breakout"
            selected={form.mode_symbols || []}
            onChange={(syms) => setField("mode_symbols", syms)}
            accentClass="text-cyan-400"
            chipActiveClass="bg-cyan-600/30 text-cyan-300 border-cyan-400/50"
          />

          <SymbolMultiSelector
            title="YALNIZ Donchian Modu ile İşlem Yapılacak Semboller (mode_exclusive)"
            badgeLabel="Klasik Radar Devre Dışı"
            selected={form.mode_exclusive || []}
            onChange={(syms) => setField("mode_exclusive", syms)}
            accentClass="text-purple-400"
            chipActiveClass="bg-purple-600/30 text-purple-300 border-purple-400/50"
          />
        </div>
      )}

      {/* TAB 4: EMA + ADX PULLBACK (M5) */}
      {activeTab === "ema_adx" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="flex items-center justify-between p-2.5 rounded-xl bg-bunker-950 border border-bunker-800">
            <div>
              <span className="text-xs font-bold text-amber-300 block">EMA8/21/50 Dizilimi + EMA21 Geri Çekilme (M5)</span>
              <span className="text-[10px] text-bunker-muted">Trend yönünde EMA21 desteğine dokunuş ve onay barı</span>
            </div>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(form.ema_adx_enabled)}
                onChange={(e) => setField("ema_adx_enabled", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4`}
              />
              <span className="text-white text-xs font-bold">Strateji Aktif</span>
            </label>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">ADX Eşiği:</label>
              <input
                type="number" min="0" max="60"
                value={form.ema_adx_adx_min ?? 25}
                onChange={(e) => setNumField("ema_adx_adx_min", e.target.value)}
                className={`${inputCls} text-amber-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">SL (×ATR):</label>
              <input
                type="number" min="0.5" max="5" step="0.1"
                value={form.ema_adx_sl_atr ?? 1.5}
                onChange={(e) => setNumField("ema_adx_sl_atr", e.target.value)}
                className={`${inputCls} text-rose-400`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">TP (×ATR):</label>
              <input
                type="number" min="0" max="6" step="0.1"
                value={form.ema_adx_tp_atr ?? 2.0}
                onChange={(e) => setNumField("ema_adx_tp_atr", e.target.value)}
                className={`${inputCls} text-emerald-400`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">EMA21 Temas (×ATR):</label>
              <input
                type="number" min="0" max="2" step="0.05"
                value={form.ema_adx_touch_atr ?? 0.3}
                onChange={(e) => setNumField("ema_adx_touch_atr", e.target.value)}
                className={`${inputCls} text-cyan-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Günde Max Giriş:</label>
              <input
                type="number" min="0" max="20"
                value={form.ema_adx_max_per_day ?? 0}
                onChange={(e) => setIntField("ema_adx_max_per_day", e.target.value)}
                className={`${inputCls} text-white`}
              />
            </div>
          </div>

          <SymbolMultiSelector
            title="EMA+ADX Pullback Aktif Semboller (ema_adx_symbols)"
            badgeLabel="Pullback M5"
            selected={form.ema_adx_symbols || []}
            onChange={(syms) => setField("ema_adx_symbols", syms)}
            accentClass="text-amber-400"
            chipActiveClass="bg-amber-600/30 text-amber-300 border-amber-400/50"
          />
        </div>
      )}

      {/* TAB 5: LONDON BREAKOUT */}
      {activeTab === "london_box" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="flex items-center justify-between p-2.5 rounded-xl bg-bunker-950 border border-bunker-800">
            <div>
              <span className="text-xs font-bold text-indigo-300 block">Asya Kutusu (00:00 - 07:00 UTC) Kırılım Motoru</span>
              <span className="text-[10px] text-bunker-muted">Londra açılışında Asya kutusu high/low kırılımına yönlü tek giriş</span>
            </div>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(form.lb_enabled)}
                onChange={(e) => setField("lb_enabled", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4`}
              />
              <span className="text-white text-xs font-bold">Strateji Aktif</span>
            </label>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Kutu Bitiş Saati (UTC):</label>
              <input
                type="number" min="0" max="12"
                value={form.lb_box_end_utc ?? 7}
                onChange={(e) => setIntField("lb_box_end_utc", e.target.value)}
                className={`${inputCls} text-indigo-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Tetik Bitiş Saati (UTC):</label>
              <input
                type="number" min="1" max="18"
                value={form.lb_entry_end_utc ?? 11}
                onChange={(e) => setIntField("lb_entry_end_utc", e.target.value)}
                className={`${inputCls} text-indigo-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">SL = Kutu Boyu Oranı:</label>
              <input
                type="number" min="0.1" max="1.0" step="0.05"
                value={form.lb_sl_box_frac ?? 0.5}
                onChange={(e) => setNumField("lb_sl_box_frac", e.target.value)}
                className={`${inputCls} text-rose-400`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">TP = SL × R Katı:</label>
              <input
                type="number" min="0.5" max="5.0" step="0.1"
                value={form.lb_tp_r ?? 1.5}
                onChange={(e) => setNumField("lb_tp_r", e.target.value)}
                className={`${inputCls} text-emerald-400`}
              />
            </div>
          </div>

          <SymbolMultiSelector
            title="London Breakout Aktif Semboller (lb_symbols)"
            badgeLabel="Asian Box Breakout"
            selected={form.lb_symbols || []}
            onChange={(syms) => setField("lb_symbols", syms)}
            accentClass="text-indigo-400"
            chipActiveClass="bg-indigo-600/30 text-indigo-300 border-indigo-400/50"
          />
        </div>
      )}

      {/* TAB 6: SUPERTREND + RSI PULLBACK (S3) */}
      {activeTab === "s3" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="flex items-center justify-between p-2.5 rounded-xl bg-bunker-950 border border-bunker-800">
            <div>
              <span className="text-xs font-bold text-teal-300 block">SuperTrend + Wilder RSI Pullback (5M &amp; 15M)</span>
              <span className="text-[10px] text-bunker-muted">ST(10,3) + EMA200 yönünde RSI 40-50 / 50-60 geri çekilme kırılımı</span>
            </div>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(form.s3_enabled)}
                onChange={(e) => setField("s3_enabled", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} w-4 h-4`}
              />
              <span className="text-white text-xs font-bold">Strateji Aktif</span>
            </label>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">ADX Eşiği:</label>
              <input
                type="number" min="0" max="60"
                value={form.s3_adx_min ?? 25}
                onChange={(e) => setNumField("s3_adx_min", e.target.value)}
                className={`${inputCls} text-teal-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">RSI Alt Sınır (40-50):</label>
              <input
                type="number" min="30" max="50"
                value={form.s3_rsi_lo ?? 40}
                onChange={(e) => setNumField("s3_rsi_lo", e.target.value)}
                className={`${inputCls} text-teal-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">SL (×ATR):</label>
              <input
                type="number" min="0.5" max="5.0" step="0.1"
                value={form.s3_sl_atr ?? 1.5}
                onChange={(e) => setNumField("s3_sl_atr", e.target.value)}
                className={`${inputCls} text-rose-400`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">15M TP (×ATR):</label>
              <input
                type="number" min="0.5" max="6.0" step="0.1"
                value={form.s3_tp_atr_15m ?? 2.0}
                onChange={(e) => setNumField("s3_tp_atr_15m", e.target.value)}
                className={`${inputCls} text-emerald-400`}
              />
            </div>
          </div>

          <SymbolMultiSelector
            title="S3 5M Kolu Sembolleri (TP yok — ST Flip ile çıkış)"
            badgeLabel="5m ST Flip"
            selected={form.s3_symbols_5m || []}
            onChange={(syms) => setField("s3_symbols_5m", syms)}
            accentClass="text-teal-400"
            chipActiveClass="bg-teal-600/30 text-teal-300 border-teal-400/50"
          />

          <SymbolMultiSelector
            title="S3 15M Kolu Sembolleri (TP = 2.0×ATR)"
            badgeLabel="15m TP Hedefli"
            selected={form.s3_symbols_15m || []}
            onChange={(syms) => setField("s3_symbols_15m", syms)}
            accentClass="text-emerald-400"
            chipActiveClass="bg-emerald-600/30 text-emerald-300 border-emerald-400/50"
          />
        </div>
      )}

      {/* TAB 7: KELTNER SQUEEZE (M15) */}
      {activeTab === "squeeze" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="p-2.5 rounded-xl bg-bunker-950 border border-bunker-800">
            <span className="text-xs font-bold text-fuchsia-300 block">John Carter TTM Keltner Squeeze (M15)</span>
            <span className="text-[10px] text-bunker-muted">Bollinger bantlarının Keltner kanalı içine sıkışması ve yönlü patlama kırılımı</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Periyot:</label>
              <input
                type="number" min="5" max="100"
                value={form.squeeze_kc_period ?? 20}
                onChange={(e) => setIntField("squeeze_kc_period", e.target.value)}
                className={`${inputCls} text-fuchsia-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">BB Std-Dev Çarpanı:</label>
              <input
                type="number" min="0.5" max="4.0" step="0.1"
                value={form.squeeze_kc_bb_mult ?? 2.0}
                onChange={(e) => setNumField("squeeze_kc_bb_mult", e.target.value)}
                className={`${inputCls} text-fuchsia-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Keltner ATR Çarpanı:</label>
              <input
                type="number" min="0.5" max="4.0" step="0.1"
                value={form.squeeze_kc_mult ?? 1.5}
                onChange={(e) => setNumField("squeeze_kc_mult", e.target.value)}
                className={`${inputCls} text-fuchsia-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">TP = SL × R Katı:</label>
              <input
                type="number" min="0.0" max="6.0" step="0.1"
                value={form.squeeze_kc_tp_r ?? 2.0}
                onChange={(e) => setNumField("squeeze_kc_tp_r", e.target.value)}
                className={`${inputCls} text-emerald-400`}
              />
            </div>
          </div>

          <SymbolMultiSelector
            title="Keltner Squeeze M15 Aktif Semboller (squeeze_kc_symbols)"
            badgeLabel="TTM Squeeze M15"
            selected={form.squeeze_kc_symbols || []}
            onChange={(syms) => setField("squeeze_kc_symbols", syms)}
            accentClass="text-fuchsia-400"
            chipActiveClass="bg-fuchsia-600/30 text-fuchsia-300 border-fuchsia-400/50"
          />
        </div>
      )}

      {/* TAB 8: COMBO3 (M5) — UT Bot ∪ Donchian+Vortex ∪ Vortex, paper-ölçüm kolu (2026-10-28) */}
      {activeTab === "combo3" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="p-2.5 rounded-xl bg-bunker-950 border border-bunker-800">
            <span className="text-xs font-bold text-rose-300 block">Combo3 — UT Bot ∪ Donchian+Vortex ∪ Vortex Kesişimi (M5)</span>
            <span className="text-[10px] text-bunker-muted">
              Replay: yalnız XAUUSD, risk %20&apos;de 14 haftada 83 günün 33&apos;ü ≥ +%50; ancak 2 pip kaymada PF 1.81→1.09.
              Bu yüzden düşük riskle koşar ve gerçek kayma ölçülür (GET /api/forex/slippage?tag=CMB3).
            </span>
          </div>

          <label className="flex items-center gap-2 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={form.combo3_enabled ?? true}
              onChange={(e) => setField("combo3_enabled", e.target.checked)}
              className="accent-rose-500"
            />
            <span className="font-bold text-rose-300">Combo3 kolu aktif</span>
            <span className="text-[10px] text-bunker-muted">(kapatınca yalnız bu kol durur; kayma defteri diğer emirler için çalışmaya devam eder)</span>
          </label>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Risk (% bakiye, yalnız bu kol):</label>
              <input
                type="number" min="0.1" max="25" step="0.1"
                value={form.combo3_risk_pct ?? 1.0}
                onChange={(e) => setNumField("combo3_risk_pct", e.target.value)}
                className={`${inputCls} text-rose-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">SL = ATR(14) × :</label>
              <input
                type="number" min="0.5" max="5" step="0.1"
                value={form.combo3_sl_atr ?? 1.5}
                onChange={(e) => setNumField("combo3_sl_atr", e.target.value)}
                className={`${inputCls} text-rose-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">TP = SL × R Katı (0 = TP yok):</label>
              <input
                type="number" min="0" max="6" step="0.1"
                value={form.combo3_tp_r ?? 2.0}
                onChange={(e) => setNumField("combo3_tp_r", e.target.value)}
                className={`${inputCls} text-emerald-400`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Günlük azami giriş / yön (0 = sınırsız):</label>
              <input
                type="number" min="0" max="50"
                value={form.combo3_max_per_day ?? 0}
                onChange={(e) => setIntField("combo3_max_per_day", e.target.value)}
                className={`${inputCls} text-rose-300`}
              />
            </div>
          </div>

          <SymbolMultiSelector
            title="Combo3 M5 Aktif Semboller (combo3_symbols) — kanıt yalnız XAUUSD; BTCUSD replay'de her hücrede negatif"
            badgeLabel="Combo3 M5"
            selected={form.combo3_symbols || []}
            onChange={(syms) => setField("combo3_symbols", syms)}
            accentClass="text-rose-400"
            chipActiveClass="bg-rose-600/30 text-rose-300 border-rose-400/50"
          />
        </div>
      )}

      {/* TAB 9: KOMBO XAU (M5) — plan v3 kombinasyon taramasından üç kombo, demo ölçüm kolu (2026-10-28) */}
      {activeTab === "kombo" && (
        <div className="space-y-3 animate-in fade-in duration-150">
          <div className="p-2.5 rounded-xl bg-bunker-950 border border-bunker-800">
            <span className="text-xs font-bold text-fuchsia-300 block">Kombo XAU — kombo_1 / kombo_4 / kombo_9 (M5, yalnız XAUUSD)</span>
            <span className="text-[10px] text-bunker-muted">
              Kombinasyon taramasında 5 ölçütü geçip temiz holdout&apos;ta tutunan üç kombo. Amaç kazanç değil ölçüm:
              BE/SL dolum kalitesi (GET /api/forex/slippage?tag=KMB1|KMB4|KMB9) ve replay sinyal paritesi
              (GET /api/forex/kombo/signals). Geçme ölçütü: maliyet sonrası PF ≥ 1.3; durma: 20 işlem sonrası PF &lt; 1.0.
              Combo3 kolu bu kol açıkken kapalı tutulur (aynı barda aynı altın slotu için yarışmasın).
            </span>
          </div>

          <label className="flex items-center gap-2 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={form.kombo_enabled ?? true}
              onChange={(e) => setField("kombo_enabled", e.target.checked)}
              className="accent-fuchsia-500"
            />
            <span className="font-bold text-fuchsia-300">Kombo kolu aktif</span>
            <span className="text-[10px] text-bunker-muted">(üç kombo birlikte; her biri kendi KMBx etiketiyle ayrı ölçülür)</span>
          </label>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Risk (% bakiye, yalnız bu kol; rapor §9: %2):</label>
              <input
                type="number" min="0.1" max="25" step="0.1"
                value={form.kombo_risk_pct ?? 2.0}
                onChange={(e) => setNumField("kombo_risk_pct", e.target.value)}
                className={`${inputCls} text-fuchsia-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Günlük azami giriş / kombo+yön (0 = sınırsız):</label>
              <input
                type="number" min="0" max="50"
                value={form.kombo_max_per_day ?? 0}
                onChange={(e) => setIntField("kombo_max_per_day", e.target.value)}
                className={`${inputCls} text-fuchsia-300`}
              />
            </div>
          </div>

          <div className="p-2.5 rounded-xl bg-bunker-950 border border-bunker-800 text-[10px] text-bunker-muted space-y-1">
            <div className="text-xs font-bold text-fuchsia-300">Tanımlar (sunucu varsayılanı; SL/TP tanımdan, BE/trailing motorun)</div>
            {(form.kombo_tanimlar && form.kombo_tanimlar.length
              ? form.kombo_tanimlar
              : [
                  { ad: "kombo_1", tag: "KMB1", tanim: { tip: "sonra", a: "ut_bot", b: "combo3", n: 12, filtre: ["seans_00_07"], sl_atr: 3.0, tp_r: 3.0 } },
                  { ad: "kombo_4", tag: "KMB4", tanim: { tip: "or", a: "hma_ao", b: "tsi_ema50", filtre: ["seans_13_20"], sl_atr: 1.5, tp_r: 2.0 } },
                  { ad: "kombo_9", tag: "KMB9", tanim: { tip: "sonra", a: "btc_keltner_geri_htf", b: "combo3", n: 3, filtre: ["atr_yuksek"], sl_atr: 2.0, tp_r: 1.0 } },
                ]
            ).map((k) => (
              <div key={k.ad} className="font-mono">
                <span className="text-fuchsia-200">{k.ad}</span> ({k.tag}): {k.tanim?.tip}({k.tanim?.a},{k.tanim?.b}
                {k.tanim?.n ? `,${k.tanim.n}` : ""}) | {(k.tanim?.filtre || []).join(",") || "-"} | SL {k.tanim?.sl_atr}×ATR, TP {k.tanim?.tp_r}R
              </div>
            ))}
          </div>

          <SymbolMultiSelector
            title="Kombo Aktif Semboller (kombo_symbols) — kanıt yalnız XAUUSD m5"
            badgeLabel="Kombo XAU M5"
            selected={form.kombo_symbols || []}
            onChange={(syms) => setField("kombo_symbols", syms)}
            accentClass="text-fuchsia-400"
            chipActiveClass="bg-fuchsia-600/30 text-fuchsia-300 border-fuchsia-400/50"
          />
        </div>
      )}

      {/* Footer Actions */}
      <div className="flex items-center justify-between pt-3 border-t border-bunker-800">
        <div className="text-[11px] text-bunker-muted">
          Seçilen algoritmalar ve semboller anında kaydedilip canlı motora uygulanır.
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg bg-bunker-800 text-bunker-muted hover:text-white text-xs font-semibold"
          >
            Vazgeç
          </button>
          <button
            type="submit"
            disabled={isSaving}
            className={`px-4 py-1.5 rounded-lg ${acc.saveBtn} text-white font-bold text-xs shadow-md transition-all disabled:opacity-50`}
          >
            {isSaving ? "Kaydediliyor…" : "Kaydet ve Motora Uygula"}
          </button>
        </div>
      </div>
    </form>
  );
}
