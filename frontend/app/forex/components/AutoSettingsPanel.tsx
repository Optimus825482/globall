"use client";

// ============================================================================
// ORTAK PARAMETRE PANELİ — Forex'in TEK parametre formu.
// 2026-10-07: Panel /forex/btc-gold ve /forex/portfolio izleme sayfalarından
// sökülüp /forex/ayarlar sayfasına taşındı; sayfalar yalnızca izler,
// parametreler yalnız buradan düzenlenir (backend: /api/forex/auto-paper/
// settings, tek ayar nesnesi).
// ============================================================================

import React, { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";

export interface AutoSettings {
  enabled: boolean;
  balance: number;
  risk_per_trade_pct: number;
  max_open_positions: number;
  min_score: number;
  tp_pips: number;
  sl_pips: number;
  breakeven_pips: number;
  trailing_stop_pips: number;
  session_filter: boolean;
  max_spread_pips: number;
  gold_cooldown_sec?: number;
  btc_min_score?: number;
  allowed_symbols: string[];
  // Backend'in döndürdüğü diğer alanlar (crypto_sl_atr_mult, gold_be_lock_ratio,
  // ev_*, major_* vb.) kaydetme anında varsayılana sıfırlanmasın diye açık uçlu.
  [key: string]: any;
}

const ALL_SYMBOLS = [
  { sym: "EURUSD", label: "EUR/USD" },
  { sym: "GBPUSD", label: "GBP/USD" },
  { sym: "USDJPY", label: "USD/JPY" },
  { sym: "USDCHF", label: "USD/CHF" },
  { sym: "AUDUSD", label: "AUD/USD" },
  { sym: "USDCAD", label: "USD/CAD" },
  { sym: "NZDUSD", label: "NZD/USD" },
  // JPY kros pariteleri (donchian modu sembolleri — 2026-10-07 eklendi)
  { sym: "GBPJPY", label: "GBP/JPY" },
  { sym: "EURJPY", label: "EUR/JPY" },
  { sym: "BTCUSD", label: "Bitcoin (BTC)" },
  // ETH/USD ve WTI Oil 2026-10-07'de forex evreninden çıkarıldı (kullanıcı
  // kararı) — bu listeden kaldırıldılar ki tekrar açılamasınlar.
  { sym: "NAS100", label: "Nasdaq 100 (USTEC)" },
  { sym: "US30", label: "Dow Jones (US30)" },
  { sym: "XAUUSD", label: "Ons Altın (XAU)" },
];

const ALL_SYMBOL_KEYS = ALL_SYMBOLS.map((s) => s.sym);

const MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"];
// Odak seti: XAU + BTC + JPY krosları (donchian modu sembolleri).
const FOCUS_SYMBOLS = ["XAUUSD", "BTCUSD", "GBPJPY", "EURJPY"];

interface AutoSettingsPanelProps {
  show: boolean;
  onClose: () => void;
  appliedSettings: AutoSettings;
  onSaved: (settings: AutoSettings) => void;
  accent?: "amber" | "blue";
}

export default function AutoSettingsPanel({
  show,
  onClose,
  appliedSettings,
  onSaved,
  accent = "blue",
}: AutoSettingsPanelProps) {
  // Kapsam fallback'i ODAK setidir (XAU+BTC+JPY krosları). Tüm-enstrüman seçimini
  // varsayılan yapmak, 30g replay'de 28/28 negatif çıkan FX evrenini paneli açıp
  // kaydeden kullanıcıya sessizce açardı — bilinçli seçim olmalı, varsayılan değil.
  const resolveSymbols = (syms?: string[]) => {
    if (!syms || syms.length === 0) return FOCUS_SYMBOLS;
    return syms;
  };

  const [form, setForm] = useState<AutoSettings>(() => ({
    ...appliedSettings,
    allowed_symbols: resolveSymbols(appliedSettings?.allowed_symbols),
  }));
  const [isSaving, setIsSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  // Panel her açılışta backend'in en güncel ayarlarıyla tazelenir;
  // açıkken gelen yoklamalar kullanıcının yarım bıraktığı düzenlemeyi ezmesin.
  useEffect(() => {
    if (show) {
      setForm({
        ...appliedSettings,
        allowed_symbols: resolveSymbols(appliedSettings?.allowed_symbols),
      });
      setSaveMsg(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show]);

  if (!show) return null;

  const acc =
    accent === "amber"
      ? {
          border: "border-amber-500/40",
          icon: "text-amber-400",
          focus: "focus:border-amber-400",
          saveBtn: "bg-amber-600 hover:bg-amber-500",
          check: "text-amber-500",
          activeChip: "bg-amber-600/30 text-amber-300 border-amber-400/50",
        }
      : {
          border: "border-blue-500/40",
          icon: "text-blue-400",
          focus: "focus:border-blue-400",
          saveBtn: "bg-blue-600 hover:bg-blue-500",
          check: "text-blue-500",
          activeChip: "bg-blue-600/30 text-blue-300 border-blue-400/50",
        };

  const setField = (key: keyof AutoSettings, val: any) =>
    setForm((prev) => ({ ...prev, [key]: val } as AutoSettings));
  const setNumField = (key: keyof AutoSettings, raw: string) =>
    setForm((prev) => ({ ...prev, [key]: raw === "" ? "" : parseFloat(raw) } as AutoSettings));
  const setIntField = (key: keyof AutoSettings, raw: string) =>
    setForm((prev) => ({ ...prev, [key]: raw === "" ? "" : parseInt(raw) } as AutoSettings));

  const toggleSymbol = (sym: string) =>
    setForm((prev) => {
      const cur: string[] = prev.allowed_symbols || [];
      const next = cur.includes(sym) ? cur.filter((s) => s !== sym) : [...cur, sym];
      return { ...prev, allowed_symbols: next.length > 0 ? next : [sym] } as AutoSettings;
    });

  const num = (v: any, fb: number): number => {
    const n = typeof v === "string" ? parseFloat(v) : Number(v);
    return Number.isFinite(n) ? n : fb;
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveMsg(null);
    try {
      // appliedSettings önce yayılır: panelde görünmeyen motor alanları
      // (crypto_sl_atr_mult, gold_be_lock_ratio, ev_*, major_* vb.)
      // backend varsayılanlarına sıfırlanmasın.
      const payload: AutoSettings = {
        ...appliedSettings,
        ...form,
        risk_per_trade_pct: num(form.risk_per_trade_pct, appliedSettings.risk_per_trade_pct || 5.0),
        tp_pips: num(form.tp_pips, appliedSettings.tp_pips || 20.0),
        sl_pips: num(form.sl_pips, appliedSettings.sl_pips || 8.0),
        breakeven_pips: num(form.breakeven_pips, appliedSettings.breakeven_pips || 14.0),
        trailing_stop_pips: num(form.trailing_stop_pips, appliedSettings.trailing_stop_pips || 20.0),
        min_score: num(form.min_score, appliedSettings.min_score || 75.0),
        btc_min_score: num(
          form.btc_min_score,
          appliedSettings.btc_min_score ?? appliedSettings.min_score ?? 76.0
        ),
        max_spread_pips: num(form.max_spread_pips, appliedSettings.max_spread_pips || 10.0),
        max_open_positions: Math.max(
          1,
          Math.round(num(form.max_open_positions, appliedSettings.max_open_positions || 99))
        ),
        gold_cooldown_sec: Math.max(60, num(form.gold_cooldown_sec, appliedSettings.gold_cooldown_sec || 60.0)),
        session_filter: Boolean(form.session_filter),
        allowed_symbols:
          form.allowed_symbols && form.allowed_symbols.length > 0
            ? form.allowed_symbols
            : appliedSettings.allowed_symbols?.length
            ? appliedSettings.allowed_symbols
            : FOCUS_SYMBOLS,
      };

      const res = await apiFetch("/api/forex/auto-paper/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res && res.status === "ok") {
        onSaved(res.settings);
        setSaveMsg("✓ Parametreler kaydedildi — tüm izleme sayfalarında geçerli!");
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
      className={`p-5 rounded-2xl bg-bunker-900/95 ${acc.border} border shadow-2xl space-y-4 animate-in fade-in slide-in-from-top-2 duration-200`}
    >
      <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
        <div className="flex items-center gap-2">
          <span className={`${acc.icon} font-bold`}>⚙️</span>
          <h3 className="text-sm font-bold text-white uppercase tracking-wider">
            Otonom Scalping Risk &amp; Çıkış Parametreleri
          </h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-bunker-muted hover:text-white"
        >
          ✕ Kapat
        </button>
      </div>

      <div className="text-[10px] text-bunker-muted font-bold flex items-center gap-1.5">
        <span>🔗</span>
        <span>Tek kaynak: Bu panel Forex Ayarları sayfasından tüm motor ayarlarını düzenler; değişiklikler anında motora uygulanır.</span>
      </div>

      {saveMsg && (
        <div className="p-3 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-bold flex items-center gap-2 animate-pulse">
          <span>{saveMsg}</span>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">Pozisyon Hacmi Riski (% Bakiye):</label>
          <input
            type="number"
            step="0.1"
            min="0.1"
            max="20.0"
            value={form.risk_per_trade_pct ?? ""}
            onChange={(e) => setNumField("risk_per_trade_pct", e.target.value)}
            className={inputCls}
          />
          <span className="text-[10px] text-bunker-muted">Dinamik lot büyüklüğünü belirler</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">Kâr Al (TP Pips):</label>
          <input
            type="number"
            min="5"
            max="120"
            value={form.tp_pips ?? ""}
            onChange={(e) => setNumField("tp_pips", e.target.value)}
            className={`${inputCls} text-emerald-400`}
          />
          <span className="text-[10px] text-bunker-muted">Hedeflenen scalp kârı</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">Zarar Durdur (SL Pips):</label>
          <input
            type="number"
            min="4"
            max="60"
            value={form.sl_pips ?? ""}
            onChange={(e) => setNumField("sl_pips", e.target.value)}
            className={`${inputCls} text-rose-400`}
          />
          <span className="text-[10px] text-bunker-muted">Maksimum kayıp mesafesi</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">Başabaş Kilit (BE Pips):</label>
          <input
            type="number"
            min="2"
            max="50"
            value={form.breakeven_pips ?? ""}
            onChange={(e) => setNumField("breakeven_pips", e.target.value)}
            className={`${inputCls} text-cyan-300`}
          />
          <span className="text-[10px] text-bunker-muted">Hedef kâra ulaşınca stop girişe çekilir</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">İz Süren Stop (Trailing Pips):</label>
          <input
            type="number"
            min="4"
            max="60"
            value={form.trailing_stop_pips ?? ""}
            onChange={(e) => setNumField("trailing_stop_pips", e.target.value)}
            className={`${inputCls} text-yellow-300`}
          />
          <span className="text-[10px] text-bunker-muted">Trend uzarsa kârı adım adım korur</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">Min. Radar Skoru (50-98):</label>
          <input
            type="number"
            min="50"
            max="98"
            value={form.min_score ?? ""}
            onChange={(e) => setNumField("min_score", e.target.value)}
            className={`${inputCls} text-amber-300`}
          />
          <span className="text-[10px] text-bunker-muted">Genel teyit eşiği (XAUUSD dahil)</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">₿ BTC Min. Skor (0-98):</label>
          <input
            type="number"
            min="0"
            max="98"
            value={form.btc_min_score ?? ""}
            onChange={(e) => setNumField("btc_min_score", e.target.value)}
            className={`${inputCls} text-orange-400`}
          />
          <span className="text-[10px] text-bunker-muted">BTCUSD özel eşik (0 = genel eşiği kullan)</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">Max. Spread Limiti:</label>
          <input
            type="number"
            step="0.1"
            min="0.5"
            max="15.0"
            value={form.max_spread_pips ?? ""}
            onChange={(e) => setNumField("max_spread_pips", e.target.value)}
            className={inputCls}
          />
          <span className="text-[10px] text-bunker-muted">Spread yüksekse işlem açılmaz</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">Max. Açık Pozisyon (1-99):</label>
          <input
            type="number"
            min="1"
            max="99"
            value={form.max_open_positions ?? ""}
            onChange={(e) => setIntField("max_open_positions", e.target.value)}
            className={inputCls}
          />
          <span className="text-[10px] text-bunker-muted">Aynı anda en fazla işlem</span>
        </div>

        <div>
          <label className="text-[11px] text-bunker-muted block mb-1">🥇 Altın Soğuma Süresi (sn):</label>
          <input
            type="number"
            min="60"
            max="900"
            step="10"
            value={form.gold_cooldown_sec ?? 60}
            onChange={(e) => setNumField("gold_cooldown_sec", e.target.value)}
            className={`${inputCls} text-amber-300`}
          />
          <span className="text-[10px] text-bunker-muted">Kapanıştan sonra bekleme (min 60 sn)</span>
        </div>

        <div className="flex flex-col justify-center col-span-2">
          <label className="text-[11px] text-bunker-muted block mb-2">Hafta Sonu Kalkanı:</label>
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={Boolean(form.session_filter)}
              onChange={(e) => setField("session_filter", e.target.checked)}
              className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} focus:ring-0 w-4 h-4`}
            />
            <span className="text-white text-xs font-semibold">Sadece Piyasa Açıkken İşlem Yap</span>
          </label>
          <span className="text-[10px] text-emerald-400 mt-1 font-bold">
            ✓ Kapalıysa Asya (Tokyo &amp; Sydney) dahil tüm seanslarda işlem serbest
          </span>
        </div>

        {/* İZİN VERİLEN PARİTELER VE EMTİALAR */}
        <div className="col-span-2 md:col-span-4 pt-3 border-t border-bunker-800">
          <div className="flex items-center justify-between mb-2">
            <label className="text-[11px] text-bunker-muted font-bold">
              İşlem Yapılacak Pariteler ({form.allowed_symbols?.length || 0} Seçili):
            </label>
            <div className="flex gap-2 text-[10px]">
              <button
                type="button"
                onClick={() => setField("allowed_symbols", ALL_SYMBOL_KEYS)}
                className={`${acc.icon} hover:underline font-bold`}
              >
                Tümünü Seç ({ALL_SYMBOL_KEYS.length} Enstrüman)
              </button>
              <span className="text-bunker-700">|</span>
              <button
                type="button"
                onClick={() => setField("allowed_symbols", [...MAJORS, ...FOCUS_SYMBOLS])}
                className="text-bunker-muted hover:underline"
              >
                7 Majör + Odak (11)
              </button>
              <span className="text-bunker-700">|</span>
              <button
                type="button"
                onClick={() => setField("allowed_symbols", [...FOCUS_SYMBOLS])}
                className="text-amber-400 hover:underline"
              >
                Yalnız XAU+BTC+JPY Kros
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {ALL_SYMBOLS.map((item) => {
              const active = form.allowed_symbols?.includes(item.sym);
              return (
                <button
                  key={item.sym}
                  type="button"
                  onClick={() => toggleSymbol(item.sym)}
                  className={`px-2 py-1 rounded-md text-[11px] font-bold transition-all border ${
                    active
                      ? acc.activeChip
                      : "bg-bunker-950/70 text-bunker-muted border-bunker-800 hover:border-bunker-700 hover:text-white"
                  }`}
                >
                  {active ? "✓ " : "+ "}
                  {item.label}
                </button>
              );
            })}
          </div>
          <span className="text-[10px] text-bunker-muted block mt-2">
            Bu liste motor genelinde tektir — tüm forex izleme sayfaları aynı listeyi kullanır.
          </span>
        </div>

        {/* EMA+ADX GERİ-ÇEKİLME (M5) — 2026-10-08 canlıya alım */}
        <div className="col-span-2 md:col-span-4 pt-3 border-t border-bunker-800">
          <div className="flex items-center justify-between mb-2">
            <label className="text-[11px] text-amber-300 font-bold">
              📐 EMA+ADX Geri Çekilme (M5) — {form.ema_adx_symbols?.length || 0} Sembol:
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={Boolean(form.ema_adx_enabled)}
                onChange={(e) => setField("ema_adx_enabled", e.target.checked)}
                className={`rounded bg-bunker-950 border-bunker-700 ${acc.check} focus:ring-0 w-4 h-4`}
              />
              <span className="text-white text-[11px] font-semibold">Aktif</span>
            </label>
          </div>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {["XAUUSD", "BTCUSD"].map((sym) => {
              const list: string[] = form.ema_adx_symbols || [];
              const active = list.includes(sym);
              return (
                <button
                  key={sym}
                  type="button"
                  onClick={() => {
                    const next = active ? list.filter((s) => s !== sym) : [...list, sym];
                    setField("ema_adx_symbols", next);
                  }}
                  className={`px-2 py-1 rounded-md text-[11px] font-bold transition-all border ${
                    active
                      ? "bg-amber-600/30 text-amber-300 border-amber-400/50"
                      : "bg-bunker-950/70 text-bunker-muted border-bunker-800 hover:border-bunker-700 hover:text-white"
                  }`}
                >
                  {active ? "✓ " : "+ "}
                  {sym === "XAUUSD" ? "Ons Altın (XAU)" : "Bitcoin (BTC)"}
                </button>
              );
            })}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">ADX Eşiği:</label>
              <input
                type="number" min="0" max="60" step="1"
                value={form.ema_adx_adx_min ?? ""}
                onChange={(e) => setNumField("ema_adx_adx_min", e.target.value)}
                className={`${inputCls} text-amber-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">SL (×ATR):</label>
              <input
                type="number" min="0.5" max="5" step="0.1"
                value={form.ema_adx_sl_atr ?? ""}
                onChange={(e) => setNumField("ema_adx_sl_atr", e.target.value)}
                className={`${inputCls} text-rose-400`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">TP (×ATR):</label>
              <input
                type="number" min="0" max="6" step="0.1"
                value={form.ema_adx_tp_atr ?? ""}
                onChange={(e) => setNumField("ema_adx_tp_atr", e.target.value)}
                className={`${inputCls} text-emerald-400`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">EMA21 Temas (×ATR):</label>
              <input
                type="number" min="0" max="2" step="0.05"
                value={form.ema_adx_touch_atr ?? ""}
                onChange={(e) => setNumField("ema_adx_touch_atr", e.target.value)}
                className={`${inputCls} text-cyan-300`}
              />
            </div>
            <div>
              <label className="text-[10px] text-bunker-muted block mb-1">Günde Max Giriş:</label>
              <input
                type="number" min="0" max="20" step="1"
                value={form.ema_adx_max_per_day ?? ""}
                onChange={(e) => setIntField("ema_adx_max_per_day", e.target.value)}
                className={`${inputCls} text-white`}
              />
            </div>
          </div>
          <span className="text-[10px] text-bunker-muted block mt-2">
            Kural: EMA8/21/50 dizilimi + ADX eşiği + EMA21&apos;e geri çekilme + trend yönünde onay barı.
            Replay kanıtı (XAU 5m): 60g +$184.56, Temmuz 1-15 +$153.90. TP=0 → sabit TP yok (BE/trailing).
            Klasik radar ve donchian akışları bu sembollerde KORUNUR (üç akış birlikte).
          </span>
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-2 border-t border-bunker-800">
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 rounded-lg bg-bunker-800 text-bunker-muted hover:text-white text-xs"
        >
          Vazgeç
        </button>
        <button
          type="submit"
          disabled={isSaving}
          className={`px-4 py-1.5 rounded-lg ${acc.saveBtn} text-white font-bold text-xs shadow-md transition-all disabled:opacity-50`}
        >
          {isSaving ? "Kaydediliyor…" : "Kaydet ve Uygula"}
        </button>
      </div>
    </form>
  );
}
