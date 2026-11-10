"""LLM ARAÇ ÇAĞRISI TEHLİKE KAPISI (2026-11-10)

NEDEN
-----
LLM sohbeti araç çağırarak eylem tetikleyebiliyor (`_dispatch_tool`, `routers/llm_chat.py`).
Bugüne kadar tek koruma, bazı araçların içindeki dağınık `_require_admin_principal` kontrolleriydi;
**isimden tehlike sınıflandırması ve tek merkezî ret kapısı yoktu**. Model bir hata yaptığında
(yanlış araç seçimi, halüsinasyonla "live" bir aracı çağırma) hiçbir şey araya girmiyordu.

TASARIM — Condor `condor/runtime/danger.py` deseninden (MIT, hummingbot/condor) uyarlanmıştır:
  * Tehlike **İSİMDEN** taşınır (argüman okumadan). Böylece insan hiç görmeden sınıflanır.
  * **Bilinmeyen araç fail-closed**: WRITE sayılır ve onay ister (sessizce geçmez).
  * **DANGEROUS** araçlar LLM yolundan HİÇ çalışmaz — yalnız panelden manuel yapılır.
  * Dosya **stdlib-only**: her katman import edebilsin, döngüsel bağımlılık olmasın.

KATMANLAR
---------
READ       : yalnız okuma (`get_*`, `list_*`, `search_*`, `scan_*`, `validate_*`, `calculate_*`, ...)
WRITE      : sistem durumunu değiştirir ama PARA HAREKET ETTİRMEZ (paper emir, alarm, coin aktivasyonu)
DANGEROUS  : gerçek para / canlı işlem / canlı ayar — LLM yolu KAPALI, manuel onay şart
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

READ = "read"
WRITE = "write"
DANGEROUS = "dangerous"

#: Okuma araçlarının isim önekleri (sıra önemli değil; hepsi küçük harf).
READ_PREFIXES: tuple[str, ...] = (
    "get_", "list_", "search_", "scan_", "validate_", "calculate_", "detect_", "deep_",
    "query_", "read_only_", "check_", "show_", "fetch_", "describe_", "explain_",
)

#: Sistem durumunu değiştiren ama para hareket ettirmeyen araçlar (paper/alarm/ayar okuma-dışı).
WRITE_TOOLS: frozenset[str] = frozenset({
    # paper (sanal) emir yolu — gerçek borsa/MT5 emri DEĞİL
    "place_paper_order", "modify_paper_order", "cancel_paper_order", "open_llm_paper_trade",
    "close_llm_position", "update_llm_position_plan", "reconcile_portfolio",
    # alarm / uyarı
    "create_market_alert", "update_market_alert", "remove_market_alert",
    # evren (analiz sembolleri)
    "activate_coin", "deactivate_coin",
    # araştırma artefaktı / pahalı iş
    "save_research_pattern", "run_pattern_universe_research",
})

#: Gerçek para / canlı işlem / canlı ayar: LLM yolu KAPALI (yalnız panelden manuel).
#: Bugün LLM araç setinde canlı emir aracı YOK; bu liste ileride eklenirse kapı hazır olsun.
DANGEROUS_TOOLS: frozenset[str] = frozenset({
    "place_order", "place_live_order", "execute_order", "send_order",
    "close_position", "close_all_positions", "close_all_mt5_positions", "panic_close",
    "mt5_close", "force_close", "cancel_all_orders",
    "set_leverage", "set_account_position_mode_and_leverage",
    "update_auto_settings", "set_blocked_symbols", "enable_live_trading", "disable_kill_switch",
    "set_risk_limits", "withdraw", "transfer_funds",
})

#: DANGEROUS'a ek olarak isim parçası ile yakalanan kalıplar (ör. "live_order", "mt5_order").
DANGEROUS_TOKENS: tuple[str, ...] = ("live_order", "live_trade", "mt5_order", "real_order", "withdraw")

#: Argüman özetinde maskelenecek anahtar parçaları.
_SECRET_TOKENS: tuple[str, ...] = ("key", "token", "secret", "password", "passwd", "auth")


@dataclass(frozen=True)
class Verdict:
    """Bir araç çağrısının tehlike kararı (saf veri)."""
    tier: str
    requires_confirm: bool
    reason: str

    @property
    def blocked_in_llm(self) -> bool:
        return self.tier == DANGEROUS


def classify(tool_name: Any) -> Verdict:
    """Araç adından tehlike katmanı. Bilinmeyen ad → WRITE + onay (fail-closed)."""
    name = str(tool_name or "").strip()
    if not name:
        return Verdict(DANGEROUS, True, "araç adı boş — fail-closed")
    low = name.lower()
    if low in DANGEROUS_TOOLS or any(tok in low for tok in DANGEROUS_TOKENS):
        return Verdict(DANGEROUS, True, "gerçek para/canlı işlem: LLM yolu kapalı, manuel onay şart")
    if low in WRITE_TOOLS:
        return Verdict(WRITE, True, "sistem durumu değişir (para hareketi yok) — onay/denetim gerekir")
    if low.startswith(READ_PREFIXES):
        return Verdict(READ, False, "yalnız okuma")
    # Bilinmeyen önek ve listede yok → temkinli taraf
    return Verdict(WRITE, True, "sınıflandırılamadı — fail-closed (WRITE kabul edildi)")


def summarize(tool_name: Any, args: Optional[dict[str, Any]] = None) -> str:
    """Onay/denetim için kısa özet; gizli anahtarlar maskelenir."""
    name = str(tool_name or "?")
    if not isinstance(args, dict) or not args:
        return name
    parts: list[str] = []
    for k, v in list(args.items())[:6]:
        key = str(k)
        if any(tok in key.lower() for tok in _SECRET_TOKENS):
            parts.append(f"{key}=***")
            continue
        s = str(v)
        parts.append(f"{key}={s[:40]}{'…' if len(s) > 40 else ''}")
    return f"{name}(" + ", ".join(parts) + ")"


def gate(tool_name: Any) -> Optional[dict[str, Any]]:
    """LLM yolunda çalıştırılmaması gereken çağrı için RED yanıtı; geçerse None.

    Dönen sözlük modelin göreceği yanıttır (protokol uyumlu, `ok=False`).
    """
    v = classify(tool_name)
    if not v.blocked_in_llm:
        return None
    return {
        "ok": False,
        "error": "danger_blocked",
        "tool": str(tool_name or ""),
        "message": ("Bu işlem gerçek para/canlı işlem hattına dokunuyor; LLM tarafından "
                    "çalıştırılamaz. Panelden manuel onayla yapılmalı."),
        "reason": v.reason,
    }


def tiers(tool_names: Iterable[str]) -> dict[str, str]:
    """Araç listesi → {isim: katman} (panel/denetim görünümü)."""
    return {str(n): classify(n).tier for n in tool_names}
