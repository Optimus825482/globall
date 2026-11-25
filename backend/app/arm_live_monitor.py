"""CANLI KOL İZLEME ÇEKİRDEĞİ — ayar işledi mi + kâr ediyor mu (2026-11-12)

NEDEN
-----
2026-11-12'de iki canlı kolun sembol listesi ölçümle değiştirildi
(`lb_symbols`: USDCHF/USDJPY çıktı, AUDUSD/NAS100 girdi · `ema_adx_symbols`:
USDJPY/US30 girdi). Kod varsayılanı **kayıtlı ayar dosyasını EZMEZ** → panelden
girilmediyse eski liste yürürlükte kalır. Bu çekirdek iki soruyu yanıtlar:

  1. **Ayar işledi mi?** çıkarılan sembollerde yeni giriş var mı? (olmamalı)
  2. **Kâr ediyor mu?** kol×sembol n / isabet / net / PF; kill kriteri
     (n≥20 ve PF<1,0 → çıkar). Yetersiz örneklemde SAYI üretilmez.

Kim kullanır:
  * `scripts/arm_live_report.py` — elle/CLI rapor
  * `app/routines/db_routines.arm_live_monitor` — **3 günde bir otomatik** koşu,
    sonuç `routine_runs`'a yazılır (Raporlar > Rutinler) ve önemliyse push gider.

KAYNAK: `trades` (canlı kapanmış FX işlemleri, `strategy` kolonu) +
`decision_logs` (tarama/ret kayıtları — işlem olmasa da canlılık kanıtı).
Yerelde `trades` boştur → bu çekirdek **sunucuda** anlamlıdır.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from typing import Any, Dict, List, Optional

#: 2026-11-12 ölçümünde çıkarılan / eklenen semboller (ayar uygulandı mı kontrolü)
REMOVED: Dict[str, List[str]] = {"london_breakout": ["USDCHF", "USDJPY"], "ema_adx_pullback": []}
ADDED: Dict[str, List[str]] = {
    "london_breakout": ["AUDUSD", "NAS100"],
    "ema_adx_pullback": ["USDJPY", "US30"],
}
DEFAULT_STRATEGIES = ["london_breakout", "ema_adx_pullback"]
#: Kill kriteri: bu sayının altında PF'e karar verilmez.
MIN_N = 20


def db_url() -> str:
    u = (os.environ.get("DATABASE_URL") or "").strip()
    if u:
        return u
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        for line in open(os.path.join(root, "backend", ".env"), encoding="utf-8"):
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def pf_of(pnls: List[float]) -> Optional[float]:
    gw = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    if gl <= 0:
        return None if gw <= 0 else float("inf")
    return gw / gl


def _norm_strategy(raw: Any) -> str:
    s = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if "london" in s and "break" in s:
        return "london_breakout"
    if "ema" in s and "adx" in s:
        return "ema_adx_pullback"
    if "donchian" in s:
        return "donchian_adx"
    if "squeeze" in s or "keltner" in s:
        return "keltner_squeeze"
    if "kombo" in s:
        return "kombo_m5"
    if "firsat" in s or "fırsat" in s or s == "frs":
        return "firsat_taramasi"
    if "radar" in s or "m1_m5" in s:
        return "m1_m5_radar"
    return s or "unknown"


def _deal_ts(d: Dict[str, Any]) -> float:
    for k in ("close_time_ts", "time", "close_time", "closed_at_ts"):
        v = d.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
        if isinstance(v, str) and v.strip():
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return dt.datetime.strptime(v.strip()[:19], fmt).replace(tzinfo=dt.timezone.utc).timestamp()
                except ValueError:
                    continue
    return 0.0


def _deal_pnl(d: Dict[str, Any]) -> float:
    if d.get("pnl_usd") is not None:
        return float(d.get("pnl_usd") or 0.0)
    return float(d.get("profit") or 0.0) + float(d.get("commission") or 0.0) + float(d.get("swap") or 0.0)


def build_report(*, days: int = 14, since: str = "",
                 strategies: Optional[List[str]] = None,
                 url: Optional[str] = None,
                 mt5_deals: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Raporu kurar (DB `trades` + canlı MT5 `closed_deals`). Dönen sözlük JSON'a yazılabilir."""
    strat = list(strategies or DEFAULT_STRATEGIES)
    strat_set = {_norm_strategy(s) for s in strat}
    if since:
        since_ts = dt.datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
    else:
        since_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).timestamp()
    out: Dict[str, Any] = {
        "baslangic": dt.datetime.fromtimestamp(since_ts, dt.timezone.utc).isoformat(timespec="seconds"),
        "kaynak": "bos",
        "semboller": {}, "ayar_kontrolu": {}, "uyarilar": [], "karar_gereken": [],
    }

    rows: List[tuple] = []
    sources: List[str] = []

    # 1) Canlı MT5 kapanan işlemler (köprü senkronu üzerinden)
    mt5_count_by_pair: Dict[tuple, int] = {}
    if mt5_deals:
        mt5_added = 0
        for d in mt5_deals:
            if not isinstance(d, dict):
                continue
            ts = _deal_ts(d)
            if ts > 0 and ts < since_ts:
                continue
            st_norm = _norm_strategy(d.get("strategy") or d.get("strategy_label") or d.get("comment"))
            sym = str(d.get("symbol") or "").upper().split(".")[0]
            if not sym:
                continue
            pnl = _deal_pnl(d)
            # MT5 tarafında tüm aktif kollar (veya istenen stratejiler) izlenir
            if strategies is None or st_norm in strat_set:
                rows.append((st_norm, sym, pnl))
                mt5_added += 1
            mt5_count_by_pair[(st_norm, sym)] = mt5_count_by_pair.get((st_norm, sym), 0) + 1
        if mt5_added > 0:
            sources.append(f"mt5({mt5_added})")

    # 2) DB trades tablosu (varsa)
    dsn = url or db_url()
    db_conn = None
    if dsn:
        try:
            import psycopg
            db_conn = psycopg.connect(dsn)
        except Exception as exc:  # noqa: BLE001
            out["uyarilar"].append(f"DB bağlantısı kurulamadı: {type(exc).__name__}")
    elif not sources:
        out["uyarilar"].append("DATABASE_URL yok ve MT5 kapanan işlem bulunamadı")
        return out

    try:
        db_rows: List[tuple] = []
        if db_conn is not None:
            db_rows = db_conn.execute(
                "SELECT strategy, symbol, pnl FROM trades WHERE exit_time >= %s AND strategy = ANY(%s)",
                (since_ts, strat)).fetchall()
            if db_rows:
                sources.append(f"db({len(db_rows)})")
                for st, sym, pnl in db_rows:
                    rows.append((_norm_strategy(st), str(sym).upper(), float(pnl or 0.0)))

        out["kaynak"] = "+".join(sources) if sources else "bos"
        book_active = len(rows) > 0
        if not book_active:
            out["uyarilar"].append("bu aralıkta kapanmış işlem yok → ölçüm yapılamaz")

        agg: Dict[tuple, List[float]] = {}
        for st, sym, pnl in rows:
            agg.setdefault((str(st), str(sym).upper()), []).append(float(pnl or 0.0))
        for (st, sym), pnls in sorted(agg.items(), key=lambda kv: -sum(kv[1])):
            n = len(pnls)
            wins = sum(1 for p in pnls if p > 0)
            pf = pf_of(pnls)
            if n < MIN_N:
                verdict = f"YETERSIZ (n<{MIN_N})"
            elif pf is not None and pf < 1.0:
                verdict = "KAPAT (PF<1,0)"
            else:
                verdict = "DEVAM"
            out["semboller"][f"{st}:{sym}"] = {
                "n": n, "win_pct": round(100.0 * wins / n, 1), "net": round(sum(pnls), 2),
                "pf": (round(pf, 3) if pf not in (None, float("inf")) else pf),
                "verdict": verdict,
            }
            if verdict.startswith("KAPAT"):
                out["karar_gereken"].append(f"{st}:{sym} n={n} PF={pf:.2f} → çıkar")

        # Ayar uygulandı mı (DB + MT5 toplamı)
        for st in strat:
            st_norm = _norm_strategy(st)
            for sym in REMOVED.get(st, []):
                n_db = (db_conn.execute(
                    "SELECT count(*) FROM trades WHERE strategy=%s AND symbol=%s AND entry_time >= %s",
                    (st, sym, since_ts)).fetchone()[0] if db_conn is not None else 0)
                n = n_db + mt5_count_by_pair.get((st_norm, sym.upper()), 0)
                ok = (n == 0)
                if not book_active:
                    state = "OLCULEMEDI (defter bos)"
                elif ok:
                    state = "ayar isledi"
                else:
                    state = "AYAR ISLEMEMIS -> panelden guncelle"
                    out["karar_gereken"].append(f"{st}:{sym} çıkarılmıştı ama {n} yeni işlem var")
                out["ayar_kontrolu"][f"{st}:{sym}"] = {
                    "beklenen": "0 islem", "gercek": n, "state": state,
                    "ok": (ok if book_active else None)}
            for sym in ADDED.get(st, []):
                n_db = (db_conn.execute(
                    "SELECT count(*) FROM trades WHERE strategy=%s AND symbol=%s AND entry_time >= %s",
                    (st, sym, since_ts)).fetchone()[0] if db_conn is not None else 0)
                n = n_db + mt5_count_by_pair.get((st_norm, sym.upper()), 0)
                scan = (db_conn.execute(
                    "SELECT count(*) FROM decision_logs WHERE strategy ILIKE %s AND symbol=%s"
                    " AND timestamp >= %s", (f"%{st.split('_')[0]}%", sym, since_ts)).fetchone()[0]
                    if db_conn is not None else 0)
                out["ayar_kontrolu"][f"{st}:{sym}"] = {
                    "beklenen": ">0 (zamanla)", "islem": n, "tarama": scan}
    finally:
        if db_conn is not None:
            db_conn.close()
    return out


def push_message(report: Dict[str, Any]) -> Optional[str]:
    """Push metni — yalnız DİKKAT gerektiren bir şey varsa (yoksa None)."""
    acts = report.get("karar_gereken") or []
    if acts:
        return "Kol izleme: " + " · ".join(acts[:3])
    rows = [f"{k} n={v['n']} PF={v['pf']}"
            for k, v in list((report.get("semboller") or {}).items())[:3]]
    return ("Kol izleme haftalık özeti: " + " · ".join(rows)) if rows else None


def format_cli(report: Dict[str, Any]) -> List[str]:
    """CLI/panel çıktısı (satır listesi)."""
    lines = [f"=== KOL x SEMBOL (baslangic {report.get('baslangic')}) ===",
             f"{'kol':<20}{'sembol':<9}{'n':>4}{'isabet%':>9}{'net':>10}{'PF':>7}  karar"]
    for key, v in (report.get("semboller") or {}).items():
        st, sym = key.split(":", 1)
        pf = v.get("pf")
        lines.append(f"{st:<20}{sym:<9}{v['n']:>4}{v['win_pct']:>9.1f}{v['net']:>10.2f}"
                     f"{(f'{pf:.2f}' if isinstance(pf, float) else '—'):>7}  {v['verdict']}")
    lines.append("\n=== AYAR KONTROLÜ ===")
    for key, v in (report.get("ayar_kontrolu") or {}).items():
        st, sym = key.split(":", 1)
        if "state" in v:
            lines.append(f"  {st:<20}{sym:<9}Cikarildi -> yeni islem {v['gercek']}  [{v['state']}]")
        else:
            lines.append(f"  {st:<20}{sym:<9}Eklendi   -> islem {v['islem']} (tarama {v['tarama']})")
    for w in report.get("uyarilar") or []:
        lines.append(f"  ! {w}")
    if report.get("karar_gereken"):
        lines.append("\nKARAR GEREKEN: " + " | ".join(report["karar_gereken"]))
    return lines
