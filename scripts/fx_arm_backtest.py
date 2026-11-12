#!/usr/bin/env python3
"""KOL BACKTESTER — dosya tabanlı sinyal kollarını ölçer (2026-11-10)

NEDEN
-----
`app/arms/*` ile kollar **dosya** olarak tanımlandı (sözleşme: +1/−1/0, `0` kapatmaz, saf).
Motorun tamamını (çok kollu defter + kapılar) çalıştırmadan bir kolu hızlıca A/B etmek için
bu bağımsız koşucu var: sinyal serisi → işlem defteri → payoff/beklenti R.

KURALLAR (ölçüm dürüstlüğü)
---------------------------
1. **Look-ahead YOK:** sinyal bar `i`'de üretilirse giriş **bar i+1'in açılışından** yapılır.
2. **SL gerçekçi:** SL = `atr_mult × ATR(14)` (giriş anındaki ATR), yön tersi.
3. **Çıkış:** SL veya `hold_bars` sonunda kapanış (TP yok varsayılan; `--tp-r` ile eklenebilir).
4. **Maliyet:** sembol başına ölçülen spread (p50, tick) + komisyon (pip cinsine çevrilir),
   her tur için bir kez düşülür.
5. **Kontrol grubu:** sinyaller `--shift` bar kaydırılınca beklenti sıfıra çök meli —
   çökmüyorsa "etki" verinin genel eğilimidir, sinyalin değil.
6. Bar içi sıra **muhafazakâr**: SL önce (canlı replay ile aynı varsayım).

Kullanim:
    python scripts/fx_arm_backtest.py --arm tokyo_window --years 5 --tf 1h
    python scripts/fx_arm_backtest.py --arm tokyo_window --symbols GBPUSD --hold-bars 1 --json outputs/arm.json
"""
from __future__ import annotations

import argparse
import collections
import urllib.parse
import urllib.request
import datetime as dt
import json
import os
import statistics
import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: uygulama sembolü → broker sembolü (NAS100 terminalde USTEC)
BROKER_ALIAS = {"NAS100": "USTEC", "US100": "USTEC"}
sys.path.insert(0, os.path.join(ROOT, "backend"))

TFS = {"1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5,
       "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30, "1h": mt5.TIMEFRAME_H1,
       "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1}
# 2026-11-12: 1m/5m eklendi — `london_breakout` gibi seans kolları 5m'de tanımlı
# ve 15m'e çevirmek kuralı başka bir strateji yapar (kutu kırılımı incelir).


# --------------------------------------------------------------------------- saf çekirdek

def atr_series(bars: list[tuple], period: int = 14) -> list[float]:
    """Basit ATR (Wilder yumuşatma) — bar: (ts, o, h, l, c)."""
    out = [0.0] * len(bars)
    trs: list[float] = []
    for i, (_, _o, h, l, c) in enumerate(bars):
        prev_c = bars[i - 1][4] if i > 0 else c
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    if len(trs) < period:
        return out
    atr = statistics.mean(trs[:period])
    out[period - 1] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def build_trades(bars: list[tuple], signals: list[int], *, atr_mult: float = 1.5,
                 hold_bars: int = 1, tp_r: float = 0.0, cost_price: float = 0.0,
                 pip: float = 0.0, shift: int = 0, exit_on_opposite: bool = False) -> list[dict]:
    """Sinyal serisinden işlem defteri. Giriş = sinyal barından SONRAKİ barın açılışı.

    `atr_mult <= 0` → **SL YOK** (yalnız karşıt sinyal / zaman çıkışı; Donchian/EMA ailelerinin
    doğal çıkışı budur). `exit_on_opposite=True` → seride ters sinyal (−1) geldiğinde o barın
    kapanışından çık (sözleşmedeki "0 kapatmaz" kuralı korunur; yalnız −1 kapatır).
    """
    if len(bars) != len(signals):
        raise ValueError("bar/sinyal uzunluğu uyuşmuyor")
    if pip <= 0:
        raise ValueError("pip > 0 olmalı")
    atr = atr_series(bars)
    trades: list[dict] = []
    n = len(bars)
    for i in range(n):
        j = i - shift                     # kontrol grubu için kaydırma
        if j < 20:
            continue
        sig = int(signals[j])
        if sig not in (1, -1):
            continue
        entry_idx = i + 1
        if entry_idx >= n - 1:
            continue
        entry = bars[entry_idx][1]        # sonraki barın AÇILIŞI (look-ahead yok)
        a = atr[j]
        if a <= 0:
            continue
        use_sl = atr_mult > 0
        sl_dist = atr_mult * a if use_sl else 0.0
        sl = entry - sig * sl_dist if use_sl else 0.0
        tp = entry + sig * tp_r * sl_dist if (tp_r > 0 and use_sl) else None
        exit_idx = min(entry_idx + max(1, hold_bars), n - 1)
        exit_px, reason = bars[exit_idx][4], "TIME"
        for k in range(entry_idx, exit_idx + 1):
            hi, lo = bars[k][2], bars[k][3]
            if use_sl and ((lo <= sl) if sig == 1 else (hi >= sl)):
                exit_px, reason, exit_idx = sl, "SL", k     # muhafazakar: SL önce
                break
            if tp is not None and ((hi >= tp) if sig == 1 else (lo <= tp)):
                exit_px, reason, exit_idx = tp, "TP", k
                break
            # KARŞIT SİNYAL: sözleşmede −1 "ters yön adayı" demek; long-only kolda çıkıştır.
            if exit_on_opposite and k < n - 1:
                nxt = int(signals[min(k + 1, n - 1)])
                if nxt == -sig:
                    exit_px, reason, exit_idx = bars[k][4], "OPPOSITE", k
                    break
        gross = sig * (exit_px - entry)
        net = gross - cost_price
        risk = sl_dist
        trades.append({"entry_idx": entry_idx, "exit_idx": exit_idx, "dir": sig,
                       "gross_pips": gross / pip, "net_pips": net / pip,
                       "R": (net / risk) if use_sl and risk > 0 else float("nan"), "reason": reason})
    return trades


def build_trades_sequential(bars: list[tuple], signals: list[int], *, cost_price: float = 0.0,
                          pip: float = 0.0, shift: int = 0, atr_mult: float = 0.0) -> list[dict]:
    """TEK POZİSYON simülasyonu (Donchian/EMA gibi "karşıt sinyalde çık" aileleri).

    NEDEN: sinyal başına bağımsız işlem açan mod, sinyal-çıkışlı ailelerde her sinyali veri
    sonuna kadar taşır → **drift artefaktı** (2026-11-10'da ölçüldü: kontrol grubu bile t=18).
    Burada pozisyon durumu tutulur: sinyal gelince gir (sonraki bar açılışı), karşıt sinyalde
    çık (o barın kapanışı). `atr_mult > 0` ise SL de uygulanır.
    """
    if len(bars) != len(signals):
        raise ValueError("bar/sinyal uzunluğu uyuşmuyor")
    if pip <= 0:
        raise ValueError("pip > 0 olmalı")
    atr = atr_series(bars)
    n = len(bars)
    trades: list[dict] = []
    i = 1
    while i < n - 1:
        j = i - shift
        sig = int(signals[j]) if 0 <= j < n else 0
        if sig not in (1, -1):
            i += 1
            continue
        entry_idx = i + 1
        if entry_idx >= n:
            break
        entry = bars[entry_idx][1]
        use_sl = atr_mult > 0 and atr[j] > 0
        sl = entry - sig * atr_mult * atr[j] if use_sl else 0.0
        exit_idx, exit_px, reason = n - 1, bars[n - 1][4], "TIMEEOF"
        k = entry_idx
        while k < n:
            if use_sl and ((bars[k][3] <= sl) if sig == 1 else (bars[k][2] >= sl)):
                exit_idx, exit_px, reason = k, sl, "SL"
                break
            kj = k - shift
            nxt = int(signals[kj]) if 0 <= kj < n else 0
            if nxt == -sig:                     # karşıt sinyal → çıkış
                exit_idx, exit_px, reason = k, bars[k][4], "OPPOSITE"
                break
            k += 1
        trades.append({"entry_idx": entry_idx, "exit_idx": exit_idx, "dir": sig,
                       "gross_pips": sig * (exit_px - entry) / pip,
                       "net_pips": (sig * (exit_px - entry) - cost_price) / pip,
                       "R": (float("nan") if not use_sl else
                             (sig * (exit_px - entry) - cost_price) / (atr_mult * atr[j])),
                       "bars_held": exit_idx - entry_idx + 1, "reason": reason})
        i = exit_idx + 1                        # pozisyon kapandıktan sonra devam
    return trades


def summarize(trades: list[dict], years: float) -> dict:
    if not trades:
        return {"n": 0}
    rs = [t["R"] for t in trades if t["R"] == t["R"]]   # NaN'leri at (SL'siz kollar)
    wins = [t["R"] for t in trades if t["R"] > 0]
    losses = [t["R"] for t in trades if t["R"] <= 0]
    gw = sum(t["net_pips"] for t in trades if t["net_pips"] > 0)
    gl = -sum(t["net_pips"] for t in trades if t["net_pips"] <= 0) or 1e-9
    if not rs:                       # SL'siz kol: R tanımsız → pip bazlı özet
        pips = [t["net_pips"] for t in trades]
        m = statistics.mean(pips)
        sd = statistics.pstdev(pips) or 1e-9
        return {"n": len(trades), "isabet_pct": round(100.0 * sum(1 for v in pips if v > 0) / len(pips), 1),
                "ort_kazanan_R": None, "ort_kaybeden_R": None, "beklenti_R": None,
                "beklenti_pip": round(m, 3), "t": round(m / (sd / len(pips) ** 0.5), 2),
                "PF": round(sum(v for v in pips if v > 0) / (abs(sum(v for v in pips if v < 0)) or 1e-9), 3),
                "net_pip": round(sum(pips), 1), "islem_yil": round(len(trades) / years, 0) if years else None}
    m = statistics.mean(rs)
    sd = statistics.pstdev(rs) or 1e-9
    return {"n": len(trades), "isabet_pct": round(100.0 * len(wins) / len(trades), 1),
            "ort_kazanan_R": round(statistics.mean(wins), 3) if wins else 0.0,
            "ort_kaybeden_R": round(statistics.mean(losses), 3) if losses else 0.0,
            "beklenti_R": round(m, 4), "t": round(m / (sd / len(rs) ** 0.5), 2),
            "PF": round(gw / gl, 3), "net_pip": round(sum(t["net_pips"] for t in trades), 1),
            "islem_yil": round(len(trades) / years, 0) if years else None}


# --------------------------------------------------------------------------- veri + CLI

def load_bars(sym: str, years: float, tf: str) -> list[tuple]:
    broker = BROKER_ALIAS.get(str(sym).upper(), str(sym).upper())
    out: list[tuple] = []
    end = dt.datetime.now()
    days = int(years * 365.25)
    i = 0
    step = 7 if tf in ("1m", "5m") else (30 if tf in ("15m", "30m") else 180)
    while i < days:
        b_end = end - dt.timedelta(days=i)
        b_start = max(b_end - dt.timedelta(days=step), end - dt.timedelta(days=days))
        r = mt5.copy_rates_range(broker, TFS[tf], b_start, b_end)
        if r is not None and len(r):
            out.extend((int(x["time"]), float(x["open"]), float(x["high"]),
                        float(x["low"]), float(x["close"])) for x in r)
        i += step
    out.sort(key=lambda b: b[0])
    return out


def _yahoo_daily(sym: str, years: float) -> dict:
    """Yahoo günlük kapanışlar → {YYYY-MM-DD: close}. Ağ erişimi YOKSA boş sözlük."""
    try:
        u = (f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
             f"?range={int(years)}y&interval=1d")
        raw = urllib.request.urlopen(urllib.request.Request(
            u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
        r = json.loads(raw)["chart"]["result"][0]
        return {dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d"): float(c)
                for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c is not None}
    except Exception as exc:  # noqa: BLE001
        print(f"[UYARI] dış seri alınamadı {sym}: {type(exc).__name__} → kol sinyalsiz kalır")
        return {}


def _external_ctx(external: list[str], sym: str, years: float) -> dict:
    i = mt5.symbol_info(sym)
    off = int(round((int(i.time) - __import__("time").time()) / 3600.0)) if i and i.time else 2
    return {"external": {e: _yahoo_daily(e, years) for e in external}, "offset_h": off}


def cost_price(sym: str, days: int = 3) -> float:
    """Tur başına maliyet (fiyat cinsinden): spread p50 + komisyon 2 yön."""
    i = mt5.symbol_info(sym)
    if i is None:
        return 0.0
    end = dt.datetime.now()
    t = mt5.copy_ticks_range(sym, end - dt.timedelta(days=days), end, mt5.COPY_TICKS_ALL)
    sp = None
    if t is not None and len(t):
        vals = sorted(float(x["ask"]) - float(x["bid"]) for x in t if float(x["ask"]) > float(x["bid"]) > 0)
        if vals:
            sp = vals[len(vals) // 2]
    if sp is None:
        sp = float(i.spread) * float(i.point)
    tick_val, tick_size = float(i.trade_tick_value or 0), float(i.trade_tick_size or 0)
    pip = float(i.point) * (10.0 if i.digits in (3, 5) else 1.0)
    comm = (2.0 * 3.5 * (tick_size / tick_val) * pip) if (tick_val and tick_size and pip) else 0.0
    return sp + comm


def main() -> int:
    ap = argparse.ArgumentParser(description="Dosya tabanlı sinyal kolu backtester'ı")
    ap.add_argument("--arm", required=True, help="kol adı (app/arms içinde kayıtlı)")
    ap.add_argument("--symbols", default="", help="boş = kolun kendi symbols listesi")
    ap.add_argument("--years", type=float, default=5.0)
    ap.add_argument("--tf", default="", help="boş = kolun timeframe'i (1h/15m/1d…)")
    ap.add_argument("--atr-mult", type=float, default=1.5, help="SL = ATR × bu")
    ap.add_argument("--hold-bars", type=int, default=1, help="zaman çıkışı (bar)")
    ap.add_argument("--tp-r", type=float, default=0.0, help=">0 ise TP = bu R (yoksa yalnız SL/zaman)")
    ap.add_argument("--shift", type=int, default=0, help="kontrol: sinyali N bar kaydır")
    ap.add_argument("--exit-on-opposite", action="store_true",
                    help="ters sinyal (−1) geldiğinde çık (Donchian/EMA ailelerinin doğal çıkışı)")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2
    from app.arms.base import call_handler, get_arm, validate_signals
    arm = get_arm(args.arm)
    if arm is None:
        print(f"[HATA] kol bulunamadı: {args.arm} (kayıtlı: app/arms)")
        return 2
    tf = args.tf or arm.timeframe
    if tf not in TFS:
        print(f"[HATA] desteklenmeyen timeframe: {tf}")
        return 2
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or list(arm.symbols)
    print(f"KOL: {arm.name} | tf={tf} | {args.years} yıl | SL={args.atr_mult}×ATR | "
          f"tut={args.hold_bars} bar | TP={args.tp_r or 'yok'} | shift={args.shift}")
    print(f"KANIT NOTU: {arm.evidence[:140]}")

    print(f"\n{'sembol':<8}{'n':>6}{'isabet%':>8}{'kazR':>7}{'kayR':>7}{'beklentiR':>10}{'t':>7}"
          f"{'PF':>6}{'net_pip':>9}{'işlem/yıl':>10}")
    per_symbol: dict[str, dict] = {}
    all_trades: list[dict] = []
    for sym in syms:
        bars = load_bars(sym, args.years, tf)
        if len(bars) < 500:
            print(f"{sym:<8} veri yetersiz ({len(bars)})")
            continue
        # TUZAK (2026-11-12): uygulama adı ≠ terminal adı (NAS100→USTEC). `symbol_info`
        # uygulama adıyla None dönünce pip hesabı AttributeError ile TÜM koşuyu düşürüyordu.
        i = mt5.symbol_info(BROKER_ALIAS.get(str(sym).upper(), str(sym).upper())) or mt5.symbol_info(sym)
        if i is None:
            print(f"{sym:<8} terminalde yok — atlandı")
            continue
        pip = float(i.point) * (10.0 if i.digits in (3, 5) else 1.0)
        ctx = _external_ctx(arm.external_inputs, sym, args.years) if arm.external_inputs else None
        sig = call_handler(arm, bars, sym, ctx)
        errs = validate_signals(sig, len(bars), arm.name)
        if errs:
            print(f"{sym:<8} SÖZLEŞME İHLALİ: {errs[0]}")
            continue
        if args.exit_on_opposite:
            trades = build_trades_sequential(bars, sig, cost_price=cost_price(sym), pip=pip,
                                             shift=args.shift, atr_mult=args.atr_mult)
        else:
            trades = build_trades(bars, sig, atr_mult=args.atr_mult, hold_bars=args.hold_bars,
                                 tp_r=args.tp_r, cost_price=cost_price(sym), pip=pip, shift=args.shift)
        s = summarize(trades, args.years)
        per_symbol[sym] = s
        all_trades.extend(trades)
        if s.get("n"):
            _kr = s.get("ort_kazanan_R")
            _kay = s.get("ort_kaybeden_R")
            _bek = s.get("beklenti_R") if s.get("beklenti_R") is not None else s.get("beklenti_pip")
            print(f"{sym:<8}{s['n']:>6}{s['isabet_pct']:>8.1f}"
                  f"{(_kr if _kr is not None else float('nan')):>7.2f}"
                  f"{(_kay if _kay is not None else float('nan')):>7.2f}"
                  f"{(_bek if _bek is not None else float('nan')):>10.3f}{s['t']:>7.2f}"
                  f"{s['PF']:>6.2f}{s['net_pip']:>9.0f}{s['islem_yil']:>10.0f}")
    tot = summarize(all_trades, args.years)
    if tot.get("n") and tot.get("beklenti_R") is None:
        print("-" * 79)
        print(f"{'TOPLAM':<8}{tot['n']:>6}{tot['isabet_pct']:>8.1f}{'':>7}{'':>7}{tot['beklenti_pip']:>10.3f}"
              f"{tot['t']:>7.2f}{tot['PF']:>6.2f}{tot['net_pip']:>9.0f}{tot['islem_yil']:>10.0f}")
        print(f"\n  okay (SL'siz): beklenti {tot['beklenti_pip']:+.3f} pip/işlem · t={tot['t']} · "
              f"PF={tot['PF']} · işlem/yıl={tot['islem_yil']:.0f} · kontrol için --shift 5")
    elif tot.get("n"):
        print("-" * 79)
        print(f"{'TOPLAM':<8}{tot['n']:>6}{tot['isabet_pct']:>8.1f}{tot['ort_kazanan_R']:>7.2f}"
              f"{tot['ort_kaybeden_R']:>7.2f}{tot['beklenti_R']:>10.3f}{tot['t']:>7.2f}"
              f"{tot['PF']:>6.2f}{tot['net_pip']:>9.0f}{tot['islem_yil']:>10.0f}")
        print(f"\n  okay: beklenti {tot['beklenti_R']:+.3f}R · t={tot['t']} · PF={tot['PF']} · "
              f"işlem/yıl={tot['islem_yil']:.0f} · kontrol için --shift 5 ile tekrar koş "
              f"(beklenti sıfıra çökmeli)")
    if args.json:
        p = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"arm": arm.name, "tf": tf, "years": args.years, "atr_mult": args.atr_mult,
                       "hold_bars": args.hold_bars, "tp_r": args.tp_r, "shift": args.shift,
                       "per_symbol": per_symbol, "total": tot}, f, ensure_ascii=False, indent=2)
        print(f"JSON: {p}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
