"""Binance Global private (authenticated) REST adapter — AŞAMA 1: SALT OKUNUR.

Bu modül Aşama 1 gereği **emir göndermez**. `place_market_buy`,
`place_market_sell`, `place_oco_sell`, `place_stop_loss_sell`,
`place_limit_sell` ve `cancel_order` BİLEREK TANIMLANMAMIŞTIR. Çağıran taraf
bu adları import ederse `ImportError` alır — bu, "Global'da emir gönderiliyor"
izlenimi yaratmaktan iyidir; Aşama 2'ye kadar yanlışlıkla emir atılması
imkânsız olur.

Binance Global'ın imzalı API'si TR'den üç yerde ayrılır:

1. **Zarf yoktur.** TR `{"code":0,"data":...}` zarfını kullanır; Global doğrudan
   veri döner. Hata gövdesi ise `{"code":-2015,"msg":"Invalid API-key..."}`
   şeklindedir — `code` alanı olduğu için hata ayrımı korunur (bkz.
   `core.unwrap`).
2. **Liste dönen uçlar JSON DİZİSİ döner**, `{"list": [...]}` değil. Eski
   `rows.get("list", [])` deseni bu biçimde `[]` döndürür — hata fırlatmaz,
   log yazmaz; kullanıcı "açık emirim yok" görür, halbuki vardır. Burada
   `core.as_rows` kullanılır.
3. **Semboller bitişiktir** (`BTCUSDT`), alt çizgi yoktur.

İmza algoritması TR ile BİREBİR aynıdır (sorted query + HMAC-SHA256 +
`X-MBX-APIKEY`); bu yüzden `core.signed_request` doğrudan kullanılır.
"""

import json
import logging
import threading
import time
from urllib.request import Request, urlopen

from app.config import config
from app import binance_private_core as _core

logger = logging.getLogger(__name__)

REST_BASE = config.PRIVATE_REST_BASE

_GLOBAL_PROFILE = _core.PrivateExchangeProfile(
    key="binance_global",
    label="Binance Global",
    rest_base=REST_BASE,
    account="/account",
    open_orders="/openOrders",
    my_trades="/myTrades",
    exchange_info="/exchangeInfo",
    server_time="/time",
    path_prefix="/api/v3",
    wraps_in_envelope=False,
    list_key=None,          # gövde zaten JSON dizisi
    balance_key="balances",  # TR'de "accountAssets"
    notional_filter="MIN_NOTIONAL",  # TR'de "NOTIONAL"
    symbol_separator="",     # TR'de "_"
    open_orders_needs_symbol=False,  # sembolsüz tüm listeyi döner
)

BinanceGlobalApiError = _core.BinanceApiError

REST_TIMEOUT_SEC = _core.REST_TIMEOUT_SEC
RECV_WINDOW_MS = _core.RECV_WINDOW_MS
_SERVER_TIME_TTL_SEC = 60.0
_SYMBOLS_CACHE_TTL_SEC = 6 * 3600
_OPEN_ORDERS_CACHE_TTL_SEC = 30
_BALANCE_CACHE_TTL_SEC = 5.0

# Global'da `myTrades` "time between startTime and endTime can't be longer than
# 24 hours" diye reddeder. `main.py` gün başı–gün sonu arası TAM 1 gün
# hesapladığı için sınırda durur; birim hata yuvarlaması aşılırsa istek reddedilir
# ve `main.py` bunu `except → []` ile yutarak GÜNÜN TÜM İŞLEMLERİNİ sessizce
# boş döndürür (K/Z raporu yanlış çıkar). Bu yüzden pencere bilinçli olarak
# daraltılır ve aşarsa istek bölünür.
_TRADES_WINDOW_MAX_MS = int(23.5 * 3600 * 1000)

_symbols_cache: dict = {"symbols": [], "by_symbol": {}, "expires": 0.0, "filters": {}}
_symbols_lock = threading.Lock()
_symbols_load_lock = threading.Lock()
_open_orders_cache: dict = {"orders": [], "expires": 0.0, "partial": False}
_open_orders_lock = threading.Lock()
_balance_cache: dict[str, dict] = {}
_balance_lock = threading.Lock()
_server_time_cache: dict = {"at": 0.0, "offset": 0.0}
_server_time_lock = threading.Lock()


def _unwrap(payload) -> dict | list:
    """Global cevabı: zarf yok, hata gövdesi `code` alanıyla ayırt edilir."""
    return _core.unwrap(payload, _GLOBAL_PROFILE)


def _http_get_json(url: str, headers: dict | None = None) -> dict | list:
    req = Request(url, headers=headers or {}, method="GET")
    with urlopen(req, timeout=REST_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _server_time_offset_ms() -> float:
    return _core.server_time_offset_ms(
        _GLOBAL_PROFILE, _http_get_json, _server_time_cache, _server_time_lock,
        _SERVER_TIME_TTL_SEC,
    )


def _signed_request(method: str, path: str, params: dict | None,
                    api_key: str, api_secret: str,
                    idempotent: bool = True) -> dict | list:
    return _core.signed_request(
        method, path, params, api_key, api_secret, _GLOBAL_PROFILE,
        http_get=_http_get_json, http_post=_core.http_post_json,
        offset_ms_fn=_server_time_offset_ms,
        server_time_cache=_server_time_cache, server_time_lock=_server_time_lock,
        server_time_ttl=_SERVER_TIME_TTL_SEC,
        idempotent=idempotent,
    )


def to_api_symbol(symbol: str) -> str:
    """Sembolü Global biçimine çevirir — BİTİŞİK, alt çizgi YOK.

    `_to_underscore_symbol` (TR) bunun TERSİDİR ve burada kesinlikle
    çağrılmamalıdır: `BTC_USDT` Global'da `-1121 Invalid symbol` döner. Bu
    sessiz değil (görünür hata), ama filtre eşleşmelerini de bozar.
    """
    value = (symbol or "").upper().replace("_", "").strip()
    if not value:
        return value
    with _symbols_lock:
        return _symbols_cache["by_symbol"].get(value, value)


def _load_symbol_list(api_key: str, api_secret: str) -> None:
    """`GET /api/v3/exchangeInfo` — sembol listesi + filtreler (cache'li, tek uçuş)."""
    if time.monotonic() < _symbols_cache["expires"]:
        return
    with _symbols_load_lock:
        if time.monotonic() < _symbols_cache["expires"]:
            return
        _load_symbol_list_locked(api_key, api_secret)


def _load_symbol_list_locked(api_key: str, api_secret: str) -> None:
    now = time.monotonic()
    payload = _http_get_json(f"{REST_BASE}/api/v3/exchangeInfo")
    data = _unwrap(payload)
    rows = _core.as_rows(
        data.get("symbols") if isinstance(data, dict) else data,
        _GLOBAL_PROFILE, "Global sembol listesi"
    )
    symbols: list[str] = []
    by_symbol: dict[str, str] = {}
    filters_by_symbol: dict[str, dict] = {}
    for r in rows:
        sym = str(r.get("symbol") or "")
        if not sym:
            continue
        symbols.append(sym)
        by_symbol[sym.upper()] = sym
        entry = {
            "quote_asset": str(r.get("quoteAsset") or "").upper(),
            # Global exchangeInfo'de `ocoEnable` YOKTUR. `None` bırakılır ki
            # `filters.get("oco_enable") is False` kontrolü geçmesin; Aşama 2'de
            # OCO reddi borsadan 400 dönecektir.
            "order_types": r.get("orderTypes") or [],
        }
        for f in r.get("filters", []) or []:
            ft = f.get("filterType")
            if ft == "LOT_SIZE":
                entry["step_size"] = float(f.get("stepSize") or 0)
                entry["min_qty"] = float(f.get("minQty") or 0)
            elif ft == _GLOBAL_PROFILE.notional_filter:
                # Global'da filtre adı MIN_NOTIONAL; TR'deki "NOTIONAL" yazımı
                # burada TÜM sembollerde sessizce 0 döndürür ve minimum tutar
                # kontrolü ortadan kalkardı.
                entry["min_notional"] = float(f.get("minNotional") or f.get("notional") or 0)
            elif ft == "PRICE_FILTER":
                entry["tick_size"] = float(f.get("tickSize") or 0)
                entry["min_price"] = float(f.get("minPrice") or 0)
                entry["max_price"] = float(f.get("maxPrice") or 0)
        filters_by_symbol[sym] = entry
    with _symbols_lock:
        _symbols_cache.update({
            "symbols": symbols, "by_symbol": by_symbol,
            "filters": filters_by_symbol, "expires": now + _SYMBOLS_CACHE_TTL_SEC,
        })
    logger.info("Binance Global sembol listesi güncellendi: %d sembol", len(symbols))


def get_symbol_filters(api_key: str, api_secret: str, symbol: str) -> dict | None:
    """Sembol filtreleri (LOT_SIZE/MIN_NOTIONAL/PRICE_FILTER, quoteAsset).

    `symbol` BİTİŞİK olmalıdır (`BTCUSDT`); TR'deki `symbol_underscore`
    adı burada yanlış yönlendirirdi, bu yüzden parametre adı bilinçli olarak
    farklıdır.
    """
    _load_symbol_list(api_key, api_secret)
    target = (symbol or "").upper().replace("_", "")
    with _symbols_lock:
        return _symbols_cache["filters"].get(target)


def invalidate_account_balance_cache(api_key: str = "") -> None:
    with _balance_lock:
        if api_key:
            _balance_cache.pop(api_key[:16], None)
        else:
            _balance_cache.clear()


def get_account_balance(api_key: str, api_secret: str, force_refresh: bool = False) -> list[dict]:
    """`GET /api/v3/account` → `balances` [{asset, free, locked}].

    TR'de bu dizi `data["accountAssets"]" altındadır; Global'da `data["balances"]`.
    Yanlış anahtar okunursa bakiye SESSİZCE boş döner ve kullanıcı parasının
    kaybolduğunu sanar.
    """
    cache_key = (api_key or "")[:16]
    now = time.monotonic()
    if not force_refresh and cache_key:
        with _balance_lock:
            cached = _balance_cache.get(cache_key)
            if cached and now < cached["expires"]:
                return cached["data"]

    data = _signed_request("GET", _GLOBAL_PROFILE.account, None, api_key, api_secret)
    assets = data.get(_GLOBAL_PROFILE.balance_key, []) if isinstance(data, dict) else []
    if not isinstance(assets, list):
        logger.warning("Global bakiye alanı liste değil (%s) — boş dönüldü",
                       type(assets).__name__)
        assets = []
    result = [
        {"asset": a.get("asset", ""), "free": a.get("free", "0"), "locked": a.get("locked", "0")}
        for a in assets if isinstance(a, dict)
    ]
    if cache_key:
        with _balance_lock:
            _balance_cache[cache_key] = {"data": result, "expires": now + _BALANCE_CACHE_TTL_SEC}
    return result


def get_spot_account_raw(api_key: str, api_secret: str) -> dict:
    """`GET /api/v3/account` — TÜM ham veri.

    Global'da komisyon oranları gövdenin kökündedir:
    `makerCommission`, `takerCommission`, `commissionRates.{maker,taker}`.
    TR'de bunlar `fiatMakerCommission` alanlarındadır. Çağıran (LLM araçları)
    `accountAssets` okuyordu; Global'da `balances` okunmalıdır.
    """
    data = _signed_request("GET", _GLOBAL_PROFILE.account, None, api_key, api_secret)
    return data if isinstance(data, dict) else {}


def get_open_orders(api_key: str, api_secret: str, symbol: str = "",
                    candidate_symbols: list[str] | None = None) -> list[dict]:
    """`GET /api/v3/openOrders` — açık emirler.

    Global bu ucu **sembol vermeden** tüm açık emirleri döner; TR'deki ~155
    satırlık "akıllı tarama" (kilitli varlıklardan aday çift türetme) burada
    GEREKSİZDİR ve 20 sembollük sınır Global evreninde (~3000 sembol)
    yanlış bütünlük verirdi. `candidate_symbols` yalnız imza uyumu için kabul
    edilir ve yok sayılır.
    """
    if candidate_symbols:
        logger.debug("Global: candidate_symbols yok sayıldı (openOrders sembol gerektirmez)")
    now = time.monotonic()
    with _open_orders_lock:
        if not symbol and now < _open_orders_cache["expires"]:
            return _open_orders_cache["orders"]

    params: dict = {"limit": 100}
    if symbol:
        params["symbol"] = to_api_symbol(symbol)
    rows = _signed_request("GET", _GLOBAL_PROFILE.open_orders, params, api_key, api_secret)
    orders = [_core.normalize_order(o) for o in
              _core.as_rows(rows, _GLOBAL_PROFILE, "Global açık emir")]
    with _open_orders_lock:
        _open_orders_cache.update({"orders": orders, "partial": False,
                                   "expires": time.monotonic() + _OPEN_ORDERS_CACHE_TTL_SEC})
    return orders


def get_open_orders_partial(api_key: str, api_secret: str) -> bool:
    """Global'de her zaman `False`.

    TR'de tıklı tarama sınırına takılınca `True` dönüp "liste eksik olabilir"
    uyarısı verilir. Global'de sembolsüz tek istek tüm listeyi döndürür, bu
    yüzden parçalık liste diye bir durum oluşamaz.
    """
    return False


def get_trade_history(api_key: str, api_secret: str, symbol: str,
                      start_time: int | None = None, end_time: int | None = None,
                      limit: int = 100, offset: int = 0) -> list[dict]:
    """`GET /api/v3/myTrades` — geçmiş işlemler (salt okunur).

    İKİ ADET FARK vardır ve ikisi de sessiz bozulma üretir:

    1. **İşlem kimliği alanı.** TR'de `tradeId`, Global'da `id`. Yanlış alan
       okunursa tüm işlemler `id=0` olur ve FIFO maliyet hesabı sessizce
       sıfırlanır (tüm PnL "—" görünür).
    2. **24 saatlik pencere sınırı.** Aşılırsa istek reddedilir; `main.py`
       bunu `except → []` ile yutar ve gün defteri boş görünür. Pencere
       aşılıyorsa istek bölünür ve sonuçlar birleştirilir.

    `offset` (sayfalama) Global'da `fromId` ile İLERİ yönde çalışır; TR'deki
    `direct=prev` (geriye) semantiğinin TERSİDİR. Bu yüzden `offset>0`
    uygulanmaz ve uyarı basılır — yanlış yönde sayfalama, FIFO maliyeti
    ters kurardı.
    """
    if offset > 0:
        logger.warning(
            "Global get_trade_history: offset=%d desteklenmiyor (fromId ileri yönde "
            "çalışır, TR'deki direct=prev ile ters); en güncel %d işlem döndürülüyor",
            offset, min(max(1, limit), 1000),
        )
        offset = 0

    cap = min(max(1, limit), 1000)
    if not symbol:
        return []

    windows: list[tuple[int | None, int | None]] = [(start_time, end_time)]
    if start_time and end_time and (int(end_time) - int(start_time)) > _TRADES_WINDOW_MAX_MS:
        windows = []
        cursor = int(start_time)
        while cursor < int(end_time):
            chunk_end = min(cursor + _TRADES_WINDOW_MAX_MS, int(end_time))
            windows.append((cursor, chunk_end))
            cursor = chunk_end

    out: list[dict] = []
    for w_start, w_end in windows:
        params: dict = {"symbol": to_api_symbol(symbol), "limit": cap}
        if w_start:
            params["startTime"] = int(w_start)
        if w_end:
            params["endTime"] = int(w_end)
        rows = _signed_request("GET", _GLOBAL_PROFILE.my_trades, params,
                               api_key, api_secret)
        out.extend(_core.normalize_trade(t, "id")
                   for t in _core.as_rows(rows, _GLOBAL_PROFILE, "Global işlem geçmişi"))
    out.sort(key=lambda t: t.get("time") or 0, reverse=True)
    return out[:cap]


def get_common_symbols(api_key: str = "", api_secret: str = "") -> dict:
    """`GET /api/v3/exchangeInfo` — sembol listesi (public, imzasız)."""
    payload = _http_get_json(f"{REST_BASE}/api/v3/exchangeInfo")
    return _unwrap(payload) if isinstance(payload, dict) else payload
