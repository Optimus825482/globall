#!/usr/bin/env python3
"""GERÇEK SPREAD PROFİLİ — maliyet modeli denetimi (2026-11-12)

NEDEN
-----
`docs/FX_YENI_SINYAL_AILESI_TUR2_2026-11-10.md` §4'te yazılı açık:
"bizim p50 spread ölçümü roll/witching/tatil günlerinde YANLIŞ POZİTİF üretir
(gerçek spread 2-5×)". Replay ise maliyeti **tek sabit** `--slip-pips` ile alıyor.
İkisi de vekil; bu betik gerçek bid/ask tick'inden ölçer.

ÖLÇTÜĞÜ ŞEY (tanımlayıcı, kapı değil)
-------------------------------------
  * saat-of-day (0-23 UTC) ve haftanın günü kırılımında spread medyanı / p90'ı
  * gün içi tabana göre **rollover saati (21-22 UTC) katı** — "2-5×" iddiasının testi
  * dakika medyanlarının dağılımı → maliyet modeli p50 mi p90 mı kullanmalı
  * en pahalı 20 dakika (haber/roll/kapanış) — sabit slippage varsayımının nerede kırıldığı

Tuzaklar (kodda karşılanmış):
  * XAUUSD 90 günde ~60M tick → GÜN dilimleriyle çekilir, bellekte tutulmaz.
  * `pip_size` CANLIDAN okunur (`get_symbol_trading_specs`); elle 0.0001 yazmak
    XAU/endeks spread'ini 10× şişiriyordu (`fx_build_tick_cache.py` dersi).
  * MT5 tick derinliği ~120-180 gün (365 gün 0 döndü — ölçüldü); daha eskisi
    için `fx_dukascopy_import.py`.

Kullanim:
    python scripts/fx_spread_profile.py --symbols EURUSD,GBPUSD,USDJPY,XAUUSD --days 90
    python scripts/fx_spread_profile.py --symbols XAUUSD --days 30 --write-db
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[HATA] MetaTrader5 yok — Python 3.12'yi tam yolla cagirin.")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PIP_LIVE: dict[str, float] = {}


def pip_size_of(symbol: str) -> float:
    """Broker sembolü → CANLI pip_size (XAUUSD 0.1, US30/NAS100 1.0)."""
    if not PIP_LIVE:
        try:
            sys.path.insert(0, os.path.join(ROOT, "backend"))
            from app.routers import forex
            items = (list(forex.FOREX_SYMBOLS) if isinstance(forex.FOREX_SYMBOLS, dict)
                     else list(forex.FOREX_SYMBOLS))
            for item in items:
                sym = item.get("symbol") if isinstance(item, dict) else item
                try:
                    PIP_LIVE[sym] = float(forex.get_symbol_trading_specs(sym)["pip_size"])
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            print(f"[UYARI] canli pip tablosu okunamadi ({e})")
    if symbol in PIP_LIVE:
        return PIP_LIVE[symbol]
    # Evren listesinde olmayan semboller (ör. DE40) için CANLI çözücüyü doğrudan çağır:
    # jenerik `point` türetmesi endekslerde pip'i 0.01 yapıp spread'i 100× şişiriyordu.
    try:
        sys.path.insert(0, os.path.join(ROOT, "backend"))
        from app.routers import forex
        return float(forex.get_symbol_trading_specs(symbol)["pip_size"])
    except Exception:  # noqa: BLE001
        pass
    info = mt5.symbol_info(symbol)
    if info is not None and info.point:
        return info.point * (10 if info.digits in (3, 5) else 1)
    return 0.0001


def db_url() -> str:
    u = (os.environ.get("DATABASE_URL") or "").strip()
    if u:
        return u
    try:
        with open(os.path.join(ROOT, "backend", ".env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return ""


DDL = """
CREATE TABLE IF NOT EXISTS fx_spread_history (
  symbol TEXT NOT NULL, open_time BIGINT NOT NULL,
  spread_avg DOUBLE PRECISION NOT NULL, spread_p50 DOUBLE PRECISION NOT NULL,
  spread_p90 DOUBLE PRECISION NOT NULL, spread_max DOUBLE PRECISION NOT NULL,
  ticks INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'mt5_tick',
  fetched_at DOUBLE PRECISION NOT NULL, PRIMARY KEY (symbol, open_time)
)
"""


def q(vals: list[float], qq: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * qq))]


def server_offset_s() -> int:
    """MT5 sunucu saati ile gerçek UTC arasındaki fark (sn).

    TUZAK: `copy_ticks_range` zaman damgaları **broker saatinde** döner
    (ICMarkets UTC+2/+3). Düzeltilmezse saat profili 2-3 saat kayar ve
    "rollover 21-22 UTC" yanlış saate bakar — ölçüm sessizce yanlış olur.
    """
    now = int(time.time())
    best, gap_best = 0, 10 ** 9
    for probe in ("BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY"):
        ti = mt5.symbol_info_tick(probe)
        if ti is not None and ti.time:
            gap = abs(int(ti.time) - now)
            if gap < gap_best:
                gap_best, best = gap, int(ti.time) - now
    return int(round(best / 1800.0)) * 1800  # yarım saate yuvarla (DST geçişleri için)


ALIAS: dict[str, list[str]] = {}


def broker_name(symbol: str) -> str:
    """Uygulama adı (NAS100) → terminal adı (USTEC). Köprünün eşlemesi kullanılır."""
    if not ALIAS:
        try:
            sys.path.insert(0, os.path.join(ROOT, "scripts"))
            from mt5_bridge import SYMBOL_ALIAS_MAP  # type: ignore
            ALIAS.update(SYMBOL_ALIAS_MAP)
        except Exception:  # noqa: BLE001
            pass
    for cand in ALIAS.get(symbol, [symbol]):
        if mt5.symbol_info(cand) is not None:
            return cand
    return symbol


def profile_symbol(symbol: str, days: int, pip: float) -> tuple[dict, list[tuple]]:
    """Gün gün tick çeker; dakika bazında toplayıp saat/gün profiline indirger.

    Dönüş: (profil, dakika satırları) — DB yazımı çağırana ait.
    """
    off_ms = server_offset_s() * 1000
    bsym = broker_name(symbol)
    now = dt.datetime.now(dt.timezone.utc)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=days)

    by_hour: dict[int, list[float]] = {h: [] for h in range(24)}   # dakika medyanları
    by_wd: dict[int, list[float]] = {d: [] for d in range(7)}
    minute_rows: list[tuple] = []                                   # DB için
    expensive: list[tuple[float, int, str]] = []                     # (spread, ms, tür)
    all_min: list[float] = []
    total_ticks = 0
    empty_days: list[str] = []

    for d in range(days + 1):
        a = day0 + dt.timedelta(days=d)
        b = a + dt.timedelta(days=1)
        ticks = mt5.copy_ticks_range(bsym, a, b, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            empty_days.append(a.strftime("%Y-%m-%d"))
            continue
        total_ticks += len(ticks)
        buckets: dict[int, list[float]] = {}
        for t in ticks:
            bid, ask = float(t["bid"]), float(t["ask"])
            if bid <= 0 or ask <= 0 or ask < bid:
                continue  # köprü boşluğu / ters kotasyon
            # time_msc = epoch ms (tam çözünürlük); yoksa saniyeye düş.
            try:
                ms = int(t["time_msc"])
            except (KeyError, ValueError, IndexError):
                ms = int(t["time"]) * 1000
            ms -= off_ms  # sunucu saati → UTC
            m = (ms // 60_000) * 60_000
            buckets.setdefault(m, []).append((ask - bid) / pip)
        for m, sp in buckets.items():
            med = statistics.median(sp)
            p90 = q(sp, 0.9)
            ts = dt.datetime.fromtimestamp(m / 1000, dt.timezone.utc)
            by_hour[ts.hour].append(med)
            by_wd[ts.weekday()].append(med)
            all_min.append(med)
            minute_rows.append((symbol, m, sum(sp) / len(sp), med, p90, max(sp), len(sp)))
        # o günün en pahalı 5 dakikası (roll/haber/kapanış izi)
        for m, sp in sorted(buckets.items(), key=lambda kv: -q(kv[1], 0.9))[:5]:
            expensive.append((q(sp, 0.9), m, "gün-içi-en-pahalı"))

    if not all_min:
        return {"symbol": symbol, "hata": "tick yok", "empty_days": empty_days}, []

    base = statistics.median(all_min)
    roll = by_hour[21] + by_hour[22]
    roll_mult = (statistics.median(roll) / base) if roll and base > 0 else 0.0
    hours = {h: round(statistics.median(v), 3) if v else None for h, v in by_hour.items()}
    worst_hours = sorted(((v, h) for h, v in hours.items() if v), reverse=True)[:4]
    cheap_hours = sorted(((v, h) for h, v in hours.items() if v))[:4]

    return {
        "symbol": symbol,
        "pip_size": pip,
        "sunucu_ofset_saat": round(off_ms / 3_600_000.0, 2),
        "gun": days,
        "tick": total_ticks,
        "dakika": len(all_min),
        "bos_gun": empty_days,
        "taban_p50_pip": round(base, 3),
        "dakika_p50_dagilim": {
            "p50": round(q(all_min, 0.50), 3),
            "p90": round(q(all_min, 0.90), 3),
            "p99": round(q(all_min, 0.99), 3),
            "maks": round(max(all_min), 3),
        },
        "roll_21_22_utc": {"p50_pip": round(statistics.median(roll), 3) if roll else None,
                           "kat": round(roll_mult, 2)},
        "saat_profili_p50_pip": hours,
        "en_pahali_saatler": [{"utc": h, "p50_pip": v} for v, h in worst_hours],
        "en_ucuz_saatler": [{"utc": h, "p50_pip": v} for v, h in cheap_hours],
        "hafta_gunu_p50_pip": {["Pzt", "Sal", "Car", "Per", "Cum", "Cmt", "Paz"][d]:
                               (round(statistics.median(v), 3) if v else None)
                               for d, v in by_wd.items()},
        "en_pahali_dakikalar": [
            {"utc": dt.datetime.fromtimestamp(m / 1000, dt.timezone.utc)
             .strftime("%Y-%m-%d %H:%M"), "p90_pip": round(v, 3)}
            for v, m, _ in sorted(expensive, reverse=True)[:10]],
    }, minute_rows


def main() -> int:
    ap = argparse.ArgumentParser(description="MT5 tick → gerçek spread profili")
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY,XAUUSD")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "fx_spread_profile.json"))
    ap.add_argument("--write-db", action="store_true", help="dakika bazında fx_spread_history'ye yaz")
    ap.add_argument("--slippage-assumption", type=float, default=2.0,
                    help="replay'in kullandığı --slip-pips (varsayılan 2)")
    ap.add_argument("--emit-replay-profile", default="",
                    help="replay --spread-profile şemasında yaz: {symbols:{SYM:{avg_pips}}}")
    args = ap.parse_args()

    if not mt5.initialize():
        print(f"[HATA] MT5 initialize basarisiz: {mt5.last_error()}")
        return 2

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    conn = None
    if args.write_db:
        url = db_url()
        if not url:
            print("[HATA] DATABASE_URL yok")
            mt5.shutdown()
            return 2
        import psycopg
        conn = psycopg.connect(url)
        conn.execute(DDL)
        conn.commit()

    out = {"olcum_zamani": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "semboller": []}
    for sym in syms:
        if mt5.symbol_info(sym) is None and mt5.symbol_info(broker_name(sym)) is None:
            print(f"  {sym:<9} terminalde YOK — atlandı")
            continue
        mt5.symbol_select(broker_name(sym), True)
        pip = pip_size_of(sym)
        t0 = time.time()
        res, rows = profile_symbol(sym, args.days, pip)
        if conn is not None and rows:
            now_ts = time.time()
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO fx_spread_history (symbol, open_time, spread_avg, spread_p50, "
                    "spread_p90, spread_max, ticks, source, fetched_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,'mt5_tick',%s) "
                    "ON CONFLICT (symbol, open_time) DO UPDATE SET spread_avg=EXCLUDED.spread_avg, "
                    "spread_p50=EXCLUDED.spread_p50, spread_p90=EXCLUDED.spread_p90, "
                    "spread_max=EXCLUDED.spread_max, ticks=EXCLUDED.ticks, "
                    "source=EXCLUDED.source, fetched_at=EXCLUDED.fetched_at",
                    [r + (now_ts,) for r in rows])
            conn.commit()
        if "hata" in res:
            print(f"  {sym:<9} {res['hata']} (boş gün: {len(res['bos_gun'])})")
            continue
        out["semboller"].append(res)
        d = res["dakika_p50_dagilim"]
        print(f"  {sym:<9} {res['dakika']:>7} dakika · taban {res['taban_p50_pip']:.2f}p | "
              f"dakika p50 {d['p50']:.2f} p90 {d['p90']:.2f} p99 {d['p99']:.2f} | "
              f"roll {res['roll_21_22_utc']['kat']:.2f}× | "
              f"en pahalı saat {res['en_pahali_saatler'][0]['utc']:02d} UTC "
              f"({res['en_pahali_saatler'][0]['p50_pip']:.2f}p) | {time.time()-t0:.0f}s")

    # Maliyet modeli karşılaştırması: replay `--slip-pips` tek sayı kullanıyor.
    print(f"\nMALİYET MODELİ — replay varsayımı: {args.slippage_assumption:g} pip slippage")
    for r in out["semboller"]:
        d = r["dakika_p50_dagilim"]
        gercek_giris = d["p90"]  # giriş piyasa emri ≈ spread'in p90'ı
        fark = gercek_giris - args.slippage_assumption
        verdict = "VARSAYIM DÜŞÜK" if fark > 0.5 else ("FAZLA TEMKİNLİ" if fark < -0.5 else "TUTARLI")
        print(f"  {r['symbol']:<9} giriş maliyeti≈{gercek_giris:.2f}p (p90) vs varsayım "
              f"{args.slippage_assumption:g}p → {verdict} ({fark:+.2f}p/işlem) · "
              f"roll {r['roll_21_22_utc']['kat']:.1f}×")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Replay'in beklediği şema: {"symbols": {SYM: {"avg_pips": X}}}
    # avg_pips = SEANS TİPİK maliyet (dakika medyanlarının medyanı). Rollover saati
    # (22 UTC) ve gün-açılış dakikası HARİÇ: bunlar işlem başına değil SAAT başına
    # maliyet; işlem 22 UTC'de açılıyorsa ayrı ele alınmalı (saat profili JSON'da).
    if args.emit_replay_profile:
        prof = {"meta": {"kaynak": "mt5_tick", "gun": args.days,
                         "olcum": out["olcum_zamani"],
                         # Profil saatleri UTC'dir; replay bar damgası broker saatinde
                         # olduğu için bu kaydırma şart (yoksa rollover yanlış saate düşer).
                         "server_offset_hours": next(
                             (r["sunucu_ofset_saat"] for r in out["semboller"]
                              if r.get("sunucu_ofset_saat") is not None), 0),
                         "not": "avg_pips = dakika-medyanı p50, rollover/reopen hariç; "
                                "hour_pips = UTC saat → p50 pip (rollover dahil)"},
                "symbols": {}}
        for r in out["semboller"]:
            hours = {int(h): v for h, v in r["saat_profili_p50_pip"].items() if v}
            typical = sorted(hours.values())
            # rollover (22 UTC) ve en pahalı saat dışlanır
            drop = {22}
            if r["en_pahali_saatler"]:
                drop.add(int(r["en_pahali_saatler"][0]["utc"]))
            keep = [v for h, v in hours.items() if h not in drop] or typical
            prof["symbols"][r["symbol"]] = {
                "avg_pips": round(statistics.median(keep), 3),
                "p90_pips": r["dakika_p50_dagilim"]["p90"],
                "p99_pips": r["dakika_p50_dagilim"]["p99"],
                "roll_mult": r["roll_21_22_utc"]["kat"],
                "pip_size": r["pip_size"],
                "hour_pips": {str(h): v for h, v in sorted(hours.items())},
            }
        with open(args.emit_replay_profile, "w", encoding="utf-8") as f:
            json.dump(prof, f, ensure_ascii=False, indent=2)
        print(f"Replay profili: {args.emit_replay_profile} ({len(prof['symbols'])} sembol)")
    if conn is not None:
        conn.close()
    mt5.shutdown()
    print(f"\nYazıldı: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
