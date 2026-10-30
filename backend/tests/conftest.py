"""Ortak test kurulumu.

`scripts/mt5_bridge.py` içe aktarılırken `MetaTrader5` paketi yoksa
`sys.exit(1)` çağırır; bu, pytest'in TÜM toplama aşamasını `SystemExit` ile
düşürüyordu (pytest yalnız Windows + MT5 terminali olan makinede çalışırdı).
Testler köprünün saf fonksiyonlarını sınar, gerçek MT5 bağlantısı gerekmez;
paket kurulu değilse boş bir yer tutucu modül yerleştirilir.
"""

import os
import sys
from unittest.mock import MagicMock

# Test izolasyonu: `forex.py` kalıcı ayarları (`/data/forex_auto_settings.json`; Windows'ta
# `D:\data\...`) İÇE AKTARMA anında yükler. Koddaki `PYTEST_CURRENT_TEST` koruması yalnız
# test ÇALIŞIRKEN ayarlı olduğundan, toplama sırasında devreye girmiyor ve geliştirme
# makinesindeki eski dosya testleri kirletiyordu (session_filter=True, btc_min_score=88).
# Modüller içe aktarılmadan ÖNCE kalıcılık kapatılır.
os.environ.setdefault("FOREX_SETTINGS_DISABLE_PERSIST", "1")

def _make_mt5_stub():
    """Gerçek MetaTrader5 sabitleriyle (tamsayı) yer tutucu modül.

    Düz `MagicMock` yetmiyor: köprü `pos.type == mt5.POSITION_TYPE_BUY` gibi
    karşılaştırmalar yapıyor; sabitler Mock nesnesi olunca her dal yanlış
    çalışıyor. Fonksiyonlar (`positions_get`, `order_send` …) testlerde zaten
    `mock.patch.object` ile yamalanır; tanımsız her özellik bir MagicMock döner.
    """
    import types

    mod = types.ModuleType("MetaTrader5")
    constants = {
        "POSITION_TYPE_BUY": 0, "POSITION_TYPE_SELL": 1,
        "ORDER_TYPE_BUY": 0, "ORDER_TYPE_SELL": 1,
        "TRADE_ACTION_DEAL": 1, "TRADE_ACTION_SLTP": 6,
        "TRADE_RETCODE_DONE": 10009,
        "ORDER_FILLING_FOK": 0, "ORDER_FILLING_IOC": 1, "ORDER_FILLING_RETURN": 2,
        "ORDER_TIME_GTC": 0,
        "DEAL_TYPE_BUY": 0, "DEAL_ENTRY_IN": 0, "DEAL_ENTRY_OUT": 1,
        "TIMEFRAME_M1": 1, "TIMEFRAME_M3": 3, "TIMEFRAME_M5": 5, "TIMEFRAME_M15": 15,
        "TIMEFRAME_M30": 30, "TIMEFRAME_H1": 16385, "TIMEFRAME_H4": 16388, "TIMEFRAME_D1": 16408,
    }
    for name, value in constants.items():
        setattr(mod, name, value)
    cache = {}

    # IC Markets'ın sembol tablosunu temsil eden küçük küme: 6 harfli pariteler ve
    # bilinen CFD/kripto adları VAR, `NAS100` gibi takma adlar YOK (broker `USTEC` kullanır).
    # `resolve_mt5_symbol` takma ad eşlemesini bu davranışa dayanarak sınanır.
    known = {"USTEC", "US30", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "XRPUSD", "SOLUSD",
             "BNBUSD", "ADAUSD", "LNKUSD", "UNIUSD", "AVXUSD", "XTZUSD", "DATAUSD"}

    def symbol_info(name):
        import re
        n = str(name)
        if n in known or re.fullmatch(r"[A-Z]{6}", n):
            return MagicMock(name=f"symbol_info.{n}", digits=5, volume_min=0.01)
        return None

    cache["symbol_info"] = symbol_info

    def __getattr__(name):  # PEP 562: tanımsız her özellik için kalıcı MagicMock
        if name.startswith("__"):
            raise AttributeError(name)
        return cache.setdefault(name, MagicMock(name=f"MetaTrader5.{name}"))

    mod.__getattr__ = __getattr__
    return mod


try:  # pragma: no cover - ortama bağlı
    import MetaTrader5  # noqa: F401
except ImportError:
    sys.modules["MetaTrader5"] = _make_mt5_stub()
