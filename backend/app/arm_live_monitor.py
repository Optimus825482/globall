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


def build_report(*, days: int = 14, since: str = "",
                 strategies: Optional[List[str]] = None,
                 url: Optional[str] = None) -> Dict[str, Any]:
    """Raporu kurar. Dönen sözlük JSON'a yazılabilir (routine_runs sonucu)."""
    strat = list(strategies or DEFAULT_STRATEGIES)
    if since:
        since_ts = dt.datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
    else:
        since_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).timestamp()
    out: Dict[str, Any] = {
        "baslangic": dt.datetime.fromtimestamp(since_ts, dt.timezone.utc).isoformat(timespec="seconds"),
        "semboller": {}, "ayar_kontrolu": {}, "uyarilar": [], "karar_gereken": [],
    }
    dsn = url or db_url()
    if not dsn:
        out["uyarilar"].append("DATABASE_URL yok")
        return out
    import psycopg

    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT strategy, symbol, pnl FROM trades WHERE exit_time >= %s AND strategy = ANY(%s)",
            (since_ts, strat)).fetchall()
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

        # Ayar uygulandı mı
        for st in strat:
            for sym in REMOVED.get(st, []):
                n = conn.execute(
                    "SELECT count(*) FROM trades WHERE strategy=%s AND symbol=%s AND entry_time >= %s",
                    (st, sym, since_ts)).fetchone()[0]
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
                n = conn.execute(
                    "SELECT count(*) FROM trades WHERE strategy=%s AND symbol=%s AND entry_time >= %s",
                    (st, sym, since_ts)).fetchone()[0]
                scan = conn.execute(
                    "SELECT count(*) FROM decision_logs WHERE strategy ILIKE %s AND symbol=%s"
                    " AND timestamp >= %s", (f"%{st.split('_')[0]}%", sym, since_ts)).fetchone()[0]
                out["ayar_kontrolu"][f"{st}:{sym}"] = {
                    "beklenen": ">0 (zamanla)", "islem": n, "tarama": scan}
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
