"""Ortak test kurulumu.

`scripts/mt5_bridge.py` içe aktarılırken `MetaTrader5` paketi yoksa
`sys.exit(1)` çağırır; bu, pytest'in TÜM toplama aşamasını `SystemExit` ile
düşürüyordu (pytest yalnız Windows + MT5 terminali olan makinede çalışırdı).
Testler köprünün saf fonksiyonlarını sınar, gerçek MT5 bağlantısı gerekmez;
paket kurulu değilse boş bir yer tutucu modül yerleştirilir.
"""

import sys
from unittest.mock import MagicMock

try:  # pragma: no cover - ortama bağlı
    import MetaTrader5  # noqa: F401
except ImportError:
    sys.modules["MetaTrader5"] = MagicMock(name="MetaTrader5")
