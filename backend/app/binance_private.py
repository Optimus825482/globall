"""Borsaya göre private adapter seçicisi.

`config.EXCHANGE` hangi borsanın çalıştığını söyler; bu modül o borsanın
private adapter'ını seçer. `main.py` ve `routers/llm_chat.py` doğrudan
`binance_tr_private` import ETMEZ — buradan import eder, böylece çağrı
noktaları (30+ `asyncio.to_thread(...)` satırı) borsadan bağımsız kalır.

Neden `EXCHANGE` okunurken `binance_tr_private` hemen import edilmiyor:
Global modülü TR modülünden bağımsızdır ve ikisi birlikte yüklenebilir.
Seçim tek noktada, anlaşılır ve test edilebilir olsun diye burada yapılır.
"""

import importlib

from app.config import config

_ADAPTERS = {
    "binance_tr": "app.binance_tr_private",
    "binance_global": "app.binance_global_private",
}


def active_module():
    """Bu örneğin private adapter modülünü döndürür."""
    name = _ADAPTERS.get(config.EXCHANGE, _ADAPTERS["binance_tr"])
    return importlib.import_module(name)


def _reexport() -> dict:
    """Aktif adapter'ın okuma yüzeyini dışa aktarır.

    `import` satırı burada değil, `__getattr__` içinde yapılır: aksi hâlde bu
    modül import edilirken aktif olmayan borsanın adapter'ı da yüklenirdi.
    """
    mod = active_module()
    names = (
        "get_account_balance", "get_spot_account_raw",
        "get_open_orders", "get_open_orders_partial",
        "get_trade_history", "get_symbol_filters", "get_common_symbols",
    )
    for name in names:
        globals()[name] = getattr(mod, name)
    globals()["REST_BASE"] = getattr(mod, "REST_BASE", "")
    globals()["_MODULE"] = mod
    return globals()


def __getattr__(name: str):
    """PEP 562 geç erişim — modül yalnızca gerçekten bir ad okunduğunda seçilir."""
    if name in ("get_account_balance", "get_spot_account_raw", "get_open_orders",
                "get_open_orders_partial", "get_trade_history", "get_symbol_filters",
                "get_common_symbols", "REST_BASE"):
        _reexport()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(list(globals().keys()) + [
        "get_account_balance", "get_spot_account_raw", "get_open_orders",
        "get_open_orders_partial", "get_trade_history", "get_symbol_filters",
        "get_common_symbols", "REST_BASE",
    ]))
