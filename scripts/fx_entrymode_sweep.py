#!/usr/bin/env python3
"""FX giriş-modu süpürmesi — 2026-10-08 web-araştırması projesi.

`forex_replay_backtest.py`'yi bir konfigürasyon matrisi üzerinde paralel koşar ve
NEW varyantının (izole FX defteri) metriklerini tek bir liderlik tablosunda toplar.

Kullanım:
    python scripts/fx_entrymode_sweep.py --list
    python scripts/fx_entrymode_sweep.py --configs dp_t12,dp_t25 --workers 2
    python scripts/fx_entrymode_sweep.py --phase is --workers 10

Tek doğruluk kaynağı burasıdır: alt-agent'lar yalnız `--configs` seçip çalıştırır.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
REPLAY = os.path.join(ROOT, "scripts", "forex_replay_backtest.py")
CACHE60 = os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide.json")
CACHE15 = os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide_15m.json")
SPREAD = "outputs/fx_spread_p95.json"
SPREAD_2X = "outputs/fx_spread_p95_2x.json"   # 2× maliyet stress (Dalga-2 kill-gate)
OUTDIR = os.path.join(ROOT, "outputs", "fxsweep")

FX12 = "EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,NZDUSD,EURJPY,GBPJPY,EURCHF,GBPCHF,EURNZD,GBPNZD"
JPY2 = "GBPJPY,EURJPY"
EXCL = "XAUUSD,BTCUSD,US30,NAS100"

IS_START, IS_END = "2026-08-01", "2026-09-14"   # in-sample
OOS_START = "2026-09-14"                        # out-of-sample başlangıcı (bitiş = cache sonu)

# Kullanıcı talebi: "önce kısa, sonra 30 günlük". Ekran (kısa) penceresi ile doğrulama
# (30g) penceresi AYRIK tutulur (aynı veride seçip doğrulama = eğriye sığdırma).
SCREEN_START, SCREEN_END = "2026-08-10", "2026-08-31"   # kısa tarama (~3 hafta)
LONG_START, LONG_END = "2026-09-07", "2026-10-07"       # 30 günlük doğrulama (OOS)

# Ortak taban: izole FX defteri (XAU/BTC/endeks hariç), 99 slot, gerçek p95 spread
BASE = [
    "--cache", CACHE60, "--add-symbols", FX12, "--exclude-symbols", EXCL,
    "--max-open", "99", "--spread-profile", SPREAD,
]
IS_WIN = ["--start", IS_START, "--end", IS_END]


PX_WIN = ["--start", SCREEN_START, "--end", SCREEN_END]
LONG_WIN = ["--start", LONG_START, "--end", LONG_END]


def _cfg(name, entry_mode, extra, scope="fx12", window="is", desc="", symbols=""):
    return {"name": name, "entry_mode": entry_mode, "extra": extra,
            "scope": scope, "window": window, "desc": desc, "symbols": symbols}


# ---------------------------------------------------------------------------
# Konfigürasyon kaydı
# ---------------------------------------------------------------------------
CONFIGS = {
    # --- Referans: klasik skor motoru (izole FX) ---
    "classic_is": _cfg("classic_is", "classic", [], desc="klasik motor referansı (izole FX, IS)"),

    # --- donchian_pure: saf kanal kırılımı (kapanış > önceki N high) ---
    "dp_t12": _cfg("dp_t12", "donchian_pure", ["--chandelier", "1.2", "--mode-sl-atr", "2.0"],
                   desc="Donchian saf kırılım + chandelier 1.2 (motor varsayılanı)"),
    "dp_t25": _cfg("dp_t25", "donchian_pure", ["--chandelier", "2.5", "--mode-sl-atr", "2.0"],
                   desc="Donchian saf kırılım + chandelier 2.5 (literatür trend mesafesi)"),
    "dp_t30": _cfg("dp_t30", "donchian_pure", ["--chandelier", "3.0", "--mode-sl-atr", "2.0"],
                   desc="Donchian saf kırılım + chandelier 3.0"),
    "dp_t25_sl15": _cfg("dp_t25_sl15", "donchian_pure", ["--chandelier", "2.5", "--mode-sl-atr", "1.5"],
                        desc="Donchian saf + chand2.5 + SL1.5ATR"),
    "dp_t25_sl25": _cfg("dp_t25_sl25", "donchian_pure", ["--chandelier", "2.5", "--mode-sl-atr", "2.5"],
                        desc="Donchian saf + chand2.5 + SL2.5ATR"),
    "dp_tp2": _cfg("dp_tp2", "donchian_pure", ["--mode-tp-atr", "2.0", "--mode-sl-atr", "2.0"],
                   desc="Donchian saf + sabit TP 2R (trail yok)"),
    "dp_adx15_t25": _cfg("dp_adx15_t25", "donchian_pure", ["--chandelier", "2.5", "--da-adx-min", "15"],
                         desc="Donchian saf + ADX15 + chand2.5"),

    # --- nr7: Crabel dar-aralık kırılımı ---
    "nr7_t12": _cfg("nr7_t12", "nr7", ["--chandelier", "1.2", "--mode-sl-atr", "2.0"],
                    desc="NR7 + chandelier 1.2"),
    "nr7_t25": _cfg("nr7_t25", "nr7", ["--chandelier", "2.5", "--mode-sl-atr", "2.0"],
                    desc="NR7 + chandelier 2.5"),
    "nr7_tp2": _cfg("nr7_tp2", "nr7", ["--mode-tp-atr", "2.0"],
                    desc="NR7 + sabit TP 2R"),
    "nr7_adx25": _cfg("nr7_adx25", "nr7", ["--chandelier", "2.5", "--nr7-adx-min", "25"],
                      desc="NR7 + ADX25 + chand2.5"),
    "nr7_n4_t25": _cfg("nr7_n4_t25", "nr7", ["--chandelier", "2.5", "--nr7-n", "4"],
                       desc="NR4 (4-bar en dar) + chand2.5"),

    # --- squeeze: Bollinger sıkışma kırılımı ---
    "sq_t12": _cfg("sq_t12", "squeeze", ["--chandelier", "1.2", "--mode-sl-atr", "2.0"],
                   desc="BB squeeze + chandelier 1.2"),
    "sq_t25": _cfg("sq_t25", "squeeze", ["--chandelier", "2.5", "--mode-sl-atr", "2.0"],
                   desc="BB squeeze + chandelier 2.5"),
    "sq_tp2": _cfg("sq_tp2", "squeeze", ["--mode-tp-atr", "2.0"],
                   desc="BB squeeze + sabit TP 2R"),
    "sq_pct10_t25": _cfg("sq_pct10_t25", "squeeze", ["--chandelier", "2.5", "--squeeze-bb-pct", "10"],
                         desc="BB squeeze (pct10 daha sıkı) + chand2.5"),

    # --- orb_ny: London kutusu → NY overlap kırılımı ---
    "orb_tp15": _cfg("orb_tp15", "orb_ny", [], desc="ORB NY overlap (kutu 07-13) TP1.5R"),
    "orb_t12": _cfg("orb_t12", "orb_ny", ["--chandelier", "1.2", "--mode-tp-atr", "0"],
                    desc="ORB NY overlap + chandelier 1.2 (TP yok)"),
    "orb_w_tp15": _cfg("orb_w_tp15", "orb_ny", ["--orb-min-atr", "0.25", "--orb-max-atr", "1.5"],
                       desc="ORB + kutu/ATR genişlik filtresi [0.25,1.5] TP1.5R"),
    "orb_early": _cfg("orb_early", "orb_ny", ["--orb-box-start", "8", "--orb-box-end", "12",
                                              "--orb-entry-start", "12", "--orb-entry-end", "16"],
                      desc="ORB London kutusu 08-12 → tetik 12-16"),

    # --- london_breakout: Asya kutusu (mevcut mod) ---
    "lb_tp15": _cfg("lb_tp15", "london_breakout", [], desc="LB Asya kutusu TP1.5R (mevcut)"),
    "lb_t25": _cfg("lb_t25", "london_breakout", ["--chandelier", "2.5", "--lb-tp-r", "99"],
                   desc="LB + chand2.5 (TP pratikte kapalı)"),
    "lb_atr": _cfg("lb_atr", "london_breakout", ["--lb-min-box-atr", "0.25"],
                   desc="LB + kutu/ATR alt filtre 0.25"),

    # --- pullback: HTF trend + EMA21 geri çekilme (mevcut mod) ---
    "pb_tp2": _cfg("pb_tp2", "pullback", [], desc="Pullback TP2R (mevcut)"),
    "pb_t25": _cfg("pb_t25", "pullback", ["--chandelier", "2.5", "--pb-adx-min", "22"],
                   desc="Pullback + chand2.5 + ADX22"),

    # --- donchian_adx: mevcut kazanan (mid-cross) — trail varyantları ---
    "da_tp4": _cfg("da_tp4", "donchian_adx", [], desc="Donchian ADX mid-cross TP4×ATR (mevcut kazanan)"),
    "da_t25": _cfg("da_t25", "donchian_adx", ["--chandelier", "2.5", "--da-tp-atr", "0"],
                   desc="Donchian ADX mid-cross + chand2.5 (sabit TP yok)"),
    "da_adx15_t25": _cfg("da_adx15_t25", "donchian_adx", ["--chandelier", "2.5", "--da-adx-min", "15",
                                                          "--da-tp-atr", "0"],
                         desc="Donchian ADX mid-cross ADX15 + chand2.5"),
    "da_tp3": _cfg("da_tp3", "donchian_adx", ["--da-tp-atr", "3.0"],
                   desc="Donchian ADX mid-cross TP3×ATR"),
}

# JPY-only kapsam varyantları (araştırma: tek pozitif aile GBPJPY/EURJPY)
JPY_CONFIGS = {
    "jp_dp_t25": _cfg("jp_dp_t25", "donchian_pure", ["--chandelier", "2.5", "--mode-sl-atr", "2.0"],
                      scope="jpy2", desc="Donchian saf + chand2.5 (yalnız GBPJPY+EURJPY)"),
    "jp_nr7_t25": _cfg("jp_nr7_t25", "nr7", ["--chandelier", "2.5", "--mode-sl-atr", "2.0"],
                       scope="jpy2", desc="NR7 + chand2.5 (yalnız JPY)"),
    "jp_sq_t25": _cfg("jp_sq_t25", "squeeze", ["--chandelier", "2.5", "--mode-sl-atr", "2.0"],
                      scope="jpy2", desc="Squeeze + chand2.5 (yalnız JPY)"),
    "jp_da_t25": _cfg("jp_da_t25", "donchian_adx", ["--chandelier", "2.5", "--da-tp-atr", "0"],
                      scope="jpy2", desc="Donchian ADX + chand2.5 (yalnız JPY)"),
    "jp_da_tp4": _cfg("jp_da_tp4", "donchian_adx", [], scope="jpy2",
                      desc="Donchian ADX TP4×ATR (yalnız JPY — canlı kapsam)"),
    "jp_classic": _cfg("jp_classic", "classic", [], scope="jpy2",
                       desc="klasik motor (yalnız JPY — kapsam-dışı referans)"),

    # --- squeeze rafinasyonu (kısa taramanın tek pozitif ailesi) ---
    # Persentil: sıkışma ne kadar sıkı tanımlanırsa işlem azalır; TP/trail çıkış varyantları
    "sq_r2_t25": _cfg("sq_r2_t25", "squeeze", ["--chandelier", "2.5", "--squeeze-bb-pct", "30"],
                      desc="Squeeze pct30 (daha gevşek) + chand2.5"),
    "sq_r3_t25": _cfg("sq_r3_t25", "squeeze", ["--chandelier", "2.5", "--squeeze-bb-pct", "40"],
                      desc="Squeeze pct40 (gevşek) + chand2.5"),
    "sq_r3_tp2": _cfg("sq_r3_tp2", "squeeze", ["--squeeze-bb-pct", "40", "--mode-tp-atr", "2.0"],
                      desc="Squeeze pct40 + sabit TP2R"),
    "sq_tp3": _cfg("sq_tp3", "squeeze", ["--mode-tp-atr", "3.0"],
                   desc="Squeeze + sabit TP3R"),
    "sq_tp25_t15": _cfg("sq_tp25_t15", "squeeze", ["--mode-tp-atr", "2.5", "--mode-sl-atr", "1.5"],
                        desc="Squeeze TP2.5R + SL1.5ATR"),
    "sq_pct10_t12": _cfg("sq_pct10_t12", "squeeze", ["--chandelier", "1.2", "--squeeze-bb-pct", "10"],
                         desc="Squeeze pct10 + chand1.2 (motor varsayılanı)"),
    "sq_pct10_tp2": _cfg("sq_pct10_tp2", "squeeze", ["--squeeze-bb-pct", "10", "--mode-tp-atr", "2.0"],
                         desc="Squeeze pct10 + sabit TP2R"),
    "sq_pct10_t35": _cfg("sq_pct10_t35", "squeeze", ["--chandelier", "3.5", "--squeeze-bb-pct", "10"],
                         desc="Squeeze pct10 + chand3.5 (5m için geniş trail)"),
    "sq_bb14_t25": _cfg("sq_bb14_t25", "squeeze", ["--chandelier", "2.5", "--squeeze-bb-period", "14"],
                        desc="Squeeze BB14 (daha kısa) + chand2.5"),
    "sq_bb50_t25": _cfg("sq_bb50_t25", "squeeze", ["--chandelier", "2.5", "--squeeze-bb-period", "50"],
                        desc="Squeeze BB50 (daha uzun) + chand2.5"),
    "sq_adx20_t25": _cfg("sq_adx20_t25", "squeeze", ["--chandelier", "2.5", "--adx-min", "20"],
                         desc="Squeeze + ADX20 kapısı + chand2.5"),
    "sq_st_t25": _cfg("sq_st_t25", "squeeze", ["--chandelier", "2.5", "--st-filter"],
                      desc="Squeeze + SuperTrend teyit + chand2.5"),
    "jp_sq_pct10": _cfg("jp_sq_pct10", "squeeze", ["--chandelier", "2.5", "--squeeze-bb-pct", "10"],
                        scope="jpy2", desc="Squeeze pct10 + chand2.5 (yalnız JPY)"),
    "jp_sq_tp2": _cfg("jp_sq_tp2", "squeeze", ["--mode-tp-atr", "2.0"], scope="jpy2",
                      desc="Squeeze TP2R (yalnız JPY)"),
    # H1 EMA200 MTF kapısı + göreli-ATR bandı varyantları (2026-10-08 araştırma)
    "jp_da_h1": _cfg("jp_da_h1", "donchian_adx", ["--htf-ema200-gate"], scope="jpy2",
                     desc="Donchian ADX TP4 (JPY) + H1 EMA200 kapısı"),
    "jp_sq_h1": _cfg("jp_sq_h1", "squeeze", ["--chandelier", "2.5", "--htf-ema200-gate"], scope="jpy2",
                     desc="Squeeze (JPY) + H1 EMA200 kapısı"),
    "jp_da_relatr": _cfg("jp_da_relatr", "donchian_adx", ["--rel-atr-band"], scope="jpy2",
                         desc="Donchian ADX TP4 (JPY) + göreli-ATR bandı"),
    "jp_dp_h1": _cfg("jp_dp_h1", "donchian_pure", ["--chandelier", "2.5", "--htf-ema200-gate"],
                     scope="jpy2", desc="Donchian saf (JPY) + H1 EMA200 kapısı"),
    "sq_tp2_h1": _cfg("sq_tp2_h1", "squeeze", ["--mode-tp-atr", "2.0", "--htf-ema200-gate"],
                      desc="Squeeze TP2R (fx12) + H1 EMA200 kapısı"),
    "da_tp4_h1": _cfg("da_tp4_h1", "donchian_adx", ["--htf-ema200-gate"],
                      desc="Donchian ADX TP4 (fx12) + H1 EMA200 kapısı"),
    # H1 kapısı geniş FX evreninde + ek JPY adayları (çapraz pencere doğrulaması)
    "dp_h1": _cfg("dp_h1", "donchian_pure", ["--chandelier", "2.5", "--htf-ema200-gate"],
                  desc="Donchian saf + H1 EMA200 kapısı (tüm FX12)"),
    "dp_h1_t12": _cfg("dp_h1_t12", "donchian_pure", ["--chandelier", "1.2", "--htf-ema200-gate"],
                      desc="Donchian saf + chand1.2 + H1 EMA200 kapısı (tüm FX12)"),
    "nr7_h1": _cfg("nr7_h1", "nr7", ["--chandelier", "2.5", "--htf-ema200-gate"],
                   desc="NR7 + chand2.5 + H1 EMA200 kapısı (tüm FX12)"),
    "sq_tp2_h1_x": _cfg("sq_tp2_h1_x", "squeeze", ["--mode-tp-atr", "2.0", "--htf-ema200-gate"],
                        desc="Squeeze TP2R + H1 EMA200 (tüm FX12)"),
}

# ===========================================================================
# DALGA-2 adayları (2026-10-08 kodlamaya değer 6 aday) — her biri kendi scope'unda
# ===========================================================================
WAVE2 = {
    # C1 — EURUSD saat-günü sezonsallığı (yalnız EURUSD)
    "tod_base": _cfg("tod_base", "eurusd_tod", [], scope="one", symbols="EURUSD",
                     desc="EURUSD TOD: EUR saatleri short / USD saatleri long (base)"),
    "tod_wide": _cfg("tod_wide", "eurusd_tod", ["--tod-short-hours", "7-12", "--tod-long-hours", "12-17"],
                     scope="one", symbols="EURUSD", desc="EURUSD TOD geniş pencereler"),
    "tod_narrow": _cfg("tod_narrow", "eurusd_tod", ["--tod-short-hours", "8-11", "--tod-long-hours", "13-16"],
                       scope="one", symbols="EURUSD", desc="EURUSD TOD dar pencereler (çekirdek saatler)"),

    # C2 — filtreli seans-open ORB (EURUSD + GBPJPY, 15m kutu)
    "orb15_eur": _cfg("orb15_eur", "orb_filtered", [], scope="one", symbols="EURUSD",
                      desc="Filtreli ORB 15m kutu (EURUSD, London+NY)"),
    "orb15_gj": _cfg("orb15_gj", "orb_filtered", ["--orb15-min-adr", "80"], scope="one", symbols="GBPJPY",
                     desc="Filtreli ORB 15m kutu (GBPJPY, London+NY, ADR>=80)"),
    "orb15_gbp": _cfg("orb15_gbp", "orb_filtered", ["--orb15-min-adr", "45"], scope="one", symbols="GBPUSD",
                      desc="Filtreli ORB 15m kutu (GBPUSD, ADR>=45)"),
    "orb15_london": _cfg("orb15_london", "orb_filtered", ["--orb15-sessions", "7"],
                         scope="one", symbols="EURUSD", desc="Filtreli ORB yalnız London açılışı (EURUSD)"),
    "orb15_ny": _cfg("orb15_ny", "orb_filtered", ["--orb15-sessions", "13"],
                     scope="one", symbols="EURUSD", desc="Filtreli ORB yalnız NY açılışı (EURUSD)"),
    "orb15_band": _cfg("orb15_band", "orb_filtered", ["--orb15-or-adr-lo", "0.08", "--orb15-or-adr-hi", "0.18"],
                       scope="one", symbols="EURUSD", desc="Filtreli ORB sıkı OR/ADR bandı 0.08-0.18"),

    # C3 — 15m sıkışma-armed genişleme barı
    "sqx_eur": _cfg("sqx_eur", "squeeze_exp", [], scope="one", symbols="EURUSD",
                    desc="Sıkışma-armed genişleme (EURUSD)"),
    "sqx_gj": _cfg("sqx_gj", "squeeze_exp", [], scope="one", symbols="GBPJPY",
                   desc="Sıkışma-armed genişleme (GBPJPY)"),
    "sqx_pct10": _cfg("sqx_pct10", "squeeze_exp", ["--sqx-comp-pct", "10"], scope="one", symbols="EURUSD",
                      desc="Sıkışma pct10 (daha sıkı) EURUSD"),
    "sqx_nohtf": _cfg("sqx_nohtf", "squeeze_exp", ["--sqx-no-htf"], scope="one", symbols="EURUSD",
                      desc="Sıkışma-armed genişleme HTF yön filtresiz (EURUSD)"),

    # C4 — günlük reopen gap-fade
    "reopen_eur": _cfg("reopen_eur", "reopen_fade", [], scope="one", symbols="EURUSD",
                       desc="Günlük reopen gap-fade (EURUSD, min gap 1p)"),
    "reopen_eur_g2": _cfg("reopen_eur_g2", "reopen_fade", ["--reopen-min-gap", "2.0"], scope="one",
                          symbols="EURUSD", desc="Reopen gap-fade min gap 2p (EURUSD)"),
    "reopen_gbp": _cfg("reopen_gbp", "reopen_fade", [], scope="one", symbols="GBPUSD",
                       desc="Günlük reopen gap-fade (GBPUSD)"),
    "reopen_jpy": _cfg("reopen_jpy", "reopen_fade", [], scope="one", symbols="USDJPY",
                       desc="Günlük reopen gap-fade (USDJPY)"),

    # C5 — Tokyo fix tevriti
    "tfix_uj": _cfg("tfix_uj", "tokyo_fix", [], scope="one", symbols="USDJPY",
                    desc="Tokyo fix tevriti (USDJPY, 00:55 UTC ±5dk)"),
    "tfix_uj_gotobi": _cfg("tfix_uj_gotobi", "tokyo_fix", ["--tfix-gotobi-only"], scope="one",
                           symbols="USDJPY", desc="Tokyo fix yalnız gotobi/ay-sonu (USDJPY)"),
    "tfix_uj_w10": _cfg("tfix_uj_w10", "tokyo_fix", ["--tfix-window", "10"], scope="one", symbols="USDJPY",
                        desc="Tokyo fix penceresi ±10dk (USDJPY)"),

    # C6 — JPY krosları + Donchian ailesi + H1 EMA200 kapısı (önceki turdan)
    "jp_da_h1_v2": _cfg("jp_da_h1_v2", "donchian_adx", ["--htf-ema200-gate"], scope="jpy2",
                        desc="Donchian ADX + H1 EMA200 (JPY krosları)"),
    "jp_dp_h1_v2": _cfg("jp_dp_h1_v2", "donchian_pure", ["--chandelier", "2.5", "--htf-ema200-gate"],
                        scope="jpy2", desc="Donchian saf + chand2.5 + H1 EMA200 (JPY krosları)"),
}
CONFIGS.update(WAVE2)
CONFIGS.update(JPY_CONFIGS)

WAVE2_SET = list(WAVE2.keys())

PHASES = {
    "is": [n for n in CONFIGS if CONFIGS[n]["window"] == "is"],
    "all": list(CONFIGS.keys()),
    "wave2": WAVE2_SET,
    # Dalga-2 dalga-1 ile çakışmasın diye ayrı fazlar (paralel subagent iş bölümü)
    "w2_tod": ["tod_base", "tod_wide", "tod_narrow"],
    "w2_orb": ["orb15_eur", "orb15_gj", "orb15_gbp", "orb15_london", "orb15_ny", "orb15_band"],
    "w2_sqx": ["sqx_eur", "sqx_gj", "sqx_pct10", "sqx_nohtf"],
    "w2_reopen": ["reopen_eur", "reopen_eur_g2", "reopen_gbp", "reopen_jpy"],
    "w2_tfix": ["tfix_uj", "tfix_uj_gotobi", "tfix_uj_w10"],
    "w2_jpy": ["jp_da_h1_v2", "jp_dp_h1_v2"],
    "w2_best": ["tod_base", "orb15_eur", "orb15_gj", "sqx_eur", "sqx_gj",
                "reopen_eur", "tfix_uj", "jp_da_h1_v2", "jp_dp_h1_v2"],
}

# Kısa-tarama fazı: ayırt edici adaylar (hızlı eleme); sonra 30g doğrulama
SCREEN_SET = [
    "classic_is", "dp_t12", "dp_t25", "dp_t25_sl15", "dp_tp2", "dp_adx15_t25",
    "nr7_t12", "nr7_t25", "nr7_tp2", "nr7_n4_t25",
    "sq_t25", "sq_pct10_t25", "sq_tp2",
    "orb_tp15", "orb_w_tp15", "orb_early",
    "lb_tp15", "lb_t25", "pb_tp2", "pb_t25",
    "da_tp4", "da_t25", "da_adx15_t25", "da_tp3",
    "jp_dp_t25", "jp_nr7_t25", "jp_da_t25", "jp_da_tp4", "jp_classic",
]

# Squeeze rafinasyon seti (kısa taramanın tek pozitif ailesi derinleştirilir)
SQREF_SET = [
    "sq_t25", "sq_pct10_t25", "sq_tp2", "sq_pct10_t12", "sq_pct10_tp2", "sq_pct10_t35",
    "sq_r2_t25", "sq_r3_t25", "sq_r3_tp2", "sq_tp3", "sq_tp25_t15",
    "sq_bb14_t25", "sq_bb50_t25", "sq_adx20_t25", "sq_st_t25",
    "jp_sq_t25", "jp_sq_pct10", "jp_sq_tp2",
]

# 30 günlük OOS doğrulama seti (kısa taramada parlayan adaylar + referanslar)
LONG_SET = [
    "classic_is",
    "dp_t12", "dp_t25", "dp_tp2",
    "nr7_t12", "nr7_t25", "nr7_tp2",
    "sq_tp2", "sq_t25", "sq_pct10_t12", "sq_pct10_tp2", "sq_pct10_t25",
    "da_tp4", "da_t25",
    "lb_tp15", "pb_tp2", "orb_tp15",
    "jp_da_tp4", "jp_sq_t25", "jp_classic",
]


# 60 günlük tam pencere + H1 kapısı belirleyici set
FINAL_SET = [
    "jp_da_tp4", "jp_da_h1", "jp_da_relatr", "jp_sq_t25", "jp_sq_h1", "jp_sq_pct10", "jp_dp_h1",
    "da_tp4", "da_tp4_h1", "sq_tp2", "sq_tp2_h1", "lb_tp15", "jp_classic",
]


def long_window_args(cfg):
    """30 günlük doğrulama penceresi (cfg['window']'dan bağımsız)."""
    return ["--start", LONG_START, "--end", LONG_END]


def build_cmd(cfg, out_path, window_override=None, days_label=None, spread=None):
    sp = spread or SPREAD
    cmd = [PY, REPLAY, "--entry-mode", cfg["entry_mode"],
           "--tag", cfg["name"], "--out", out_path, "--skip-old"]
    if cfg["scope"] == "jpy2":
        # GBPJPY/EURJPY canlı allowed sette olduğundan --symbols ile doğrudan süzülür
        cmd += ["--cache", CACHE60, "--symbols", JPY2, "--max-open", "99",
                "--spread-profile", sp]
    elif cfg["scope"] == "one":
        # Tek sembol (Dalga-2 adayları kendi scope'unda): hedefi EKLE, diğer tüm FX'i DIŞLA.
        # --symbols kullanılamaz (canlı allowed ile KESİŞİR → boş kalır); ekle/dışla kullanılır.
        target = cfg.get("symbols", "EURUSD")
        others = [s for s in FX12.split(",") if s.strip() != target]
        cmd += ["--cache", CACHE60, "--add-symbols", target,
                "--exclude-symbols", EXCL + ("," + ",".join(others) if others else ""),
                "--max-open", "99", "--spread-profile", sp]
    else:
        cmd += list(BASE)
        if spread:
            # BASE zaten SPREAD taşıyor; override için sondaki değeri değiştir
            i = cmd.index("--spread-profile")
            cmd[i + 1] = sp
    if window_override:
        cmd += window_override
    elif cfg["window"] == "is":
        cmd += list(IS_WIN)
    cmd += list(cfg["extra"])
    return cmd


_MET_RE = re.compile(r"NEW\s+(\d+)\s+([\d.]+)%\s+([+-][\d.]+)")


def parse_metrics(out_path, log_text):
    """Replay JSON'undan NEW varyantının metriklerini çıkar."""
    if not os.path.exists(out_path):
        return {"error": "no_json"}
    try:
        with open(out_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return {"error": f"json:{e}"}
    v = d.get("variants", {}).get("NEW")
    if not v:
        return {"error": "no_new"}
    ps = v.get("per_symbol", {})
    jpy_net = sum(x["pnl"] for s, x in ps.items() if "JPY" in s)
    non_jpy = sum(x["pnl"] for s, x in ps.items() if "JPY" not in s)
    return {
        "trades": v.get("trades"), "wr": v.get("win_rate"),
        "net": v.get("net_pnl_usd"), "pf": v.get("profit_factor"),
        "dd": v.get("max_drawdown_usd"), "avg": v.get("avg_pnl_usd"),
        "jpy_net": round(jpy_net, 2), "nonjpy_net": round(non_jpy, 2),
        "exits": {k: v2.get("n") for k, v2 in (v.get("exit_reasons") or {}).items()},
        "per_symbol": {s: round(x["pnl"], 2) for s, x in sorted(ps.items(), key=lambda kv: -kv[1]["pnl"])},
        "config": (d.get("config") or "")[:180],
    }


def run_one(name, window_override=None, label=None, quiet=False, spread=None):
    cfg = CONFIGS[name]
    os.makedirs(OUTDIR, exist_ok=True)
    tag = label or name
    out_path = os.path.join(OUTDIR, f"{tag}.json")
    cmd = build_cmd(cfg, out_path, window_override, spread=spread)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = (proc.stdout or "") + (proc.stderr or "")
    m = parse_metrics(out_path, log)
    m["name"] = name
    m["elapsed_s"] = round(time.time() - t0, 1)
    m["desc"] = cfg["desc"]
    m["scope"] = cfg["scope"]
    m["log_tail"] = log[-600:] if m.get("error") else ""
    if not quiet:
        print(f"[{name}] net={m.get('net')} n={m.get('trades')} wr={m.get('wr')} "
              f"pf={m.get('pf')} dd={m.get('dd')} jpy={m.get('jpy_net')} ({m['elapsed_s']}s)"
              + (f" ERR={m['error']}" if m.get("error") else ""))
    return m


def print_leaderboard(results):
    ok = [r for r in results if "net" in r and r["net"] is not None]
    ok.sort(key=lambda r: -(r["net"] or 0))
    print("\n" + "=" * 118)
    print(f"{'KONFİG':18s} {'KAPSAM':6s} {'İŞLEM':>6s} {'WR%':>6s} {'NET$':>9s} {'PF':>6s} "
          f"{'DD$':>8s} {'JPY$':>8s} {'Diğer$':>9s}")
    print("-" * 118)
    for r in ok:
        print(f"{r['name']:18s} {r.get('scope','fx12'):6s} {r['trades']:>6} {r['wr']:>6.1f} "
              f"{r['net']:>+9.2f} {r['pf']:>6.2f} {r['dd']:>8.2f} "
              f"{r.get('jpy_net',0):>+8.2f} {r.get('nonjpy_net',0):>+9.2f}")
    errs = [r for r in results if r.get("error")]
    if errs:
        print("\nHATALI:")
        for r in errs:
            print(f"  {r['name']}: {r['error']} | {r.get('log_tail','')[-200:]}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="", help="Virgüllü konfig adları (boş = --phase)")
    ap.add_argument("--phase", default="", choices=["", "is", "all", "screen", "long", "sqref", "final",
                                                    "wave2", "w2_tod", "w2_orb", "w2_sqx", "w2_reopen",
                                                    "w2_tfix", "w2_jpy", "w2_best"])
    ap.add_argument("--window", default="", choices=["", "60g"], help="final fazı için: 60g = tüm cache (pencere yok)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--label-suffix", default="")
    ap.add_argument("--spread-2x", action="store_true", help="2× maliyet stress profili kullan (kill-gate)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for n, c in CONFIGS.items():
            print(f"  {n:18s} mode={c['entry_mode']:16s} scope={c['scope']:5s} win={c['window']:3s}  {c['desc']}")
        return

    if args.configs:
        names = [x.strip() for x in args.configs.split(",") if x.strip()]
    elif args.phase == "screen":
        names = SCREEN_SET
    elif args.phase == "sqref":
        names = SQREF_SET
    elif args.phase == "long":
        names = LONG_SET
    elif args.phase == "final":
        names = FINAL_SET
    elif args.phase:
        names = PHASES[args.phase]
    else:
        names = PHASES["is"]
    for n in names:
        if n not in CONFIGS:
            print(f"[HATA] bilinmeyen konfig: {n}")
            sys.exit(2)

    win = None
    if args.start or args.end:
        win = []
        if args.start:
            win += ["--start", args.start]
        if args.end:
            win += ["--end", args.end]
    elif args.phase == "screen":
        win = list(PX_WIN)
    elif args.phase == "long":
        win = list(LONG_WIN)
    # final: pencere verilmezse tam cache (60g) koşulur

    t0 = time.time()
    results = []
    sp = SPREAD_2X if getattr(args, "spread_2x", False) else None
    if args.workers <= 1:
        for n in names:
            results.append(run_one(n, win, label=(n + args.label_suffix) if args.label_suffix else None, spread=sp))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_one, n, win,
                              (n + args.label_suffix) if args.label_suffix else None, False, sp): n for n in names}
            for fut in concurrent.futures.as_completed(futs):
                results.append(fut.result())

    ok = print_leaderboard(results)
    summary = os.path.join(OUTDIR, f"_summary_{args.label_suffix or args.phase or 'sel'}.json")
    os.makedirs(OUTDIR, exist_ok=True)
    with open(summary, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nToplam {time.time()-t0:.0f}s | özet: {summary}")
    return ok


if __name__ == "__main__":
    main()
