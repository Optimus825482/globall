"""Binance private (imzalı) ortak çekirdek — borsadan bağımsız.

Bu modül "nasıl imzalanır, nasıl beklenir, hata nasıl sınıflandırılır"
sorusunu yanıtlar; "hangi uç, hangi alan, hangi sembol biçimi" sorusunu
answerlamaz. O, adapter'ların (`binance_tr_private` / `binance_global_private`)
işidir.

TASARIM KURALI — neden bu modül `config` IMPORT ETMEZ:
Testler iki borsa modunda da çalışabilmeli. `config` import anında okunan
sabitler tutuyor (bkz. config.py:14-20 notu), yani çekirdek borsa kimliğini
`PrivateExchangeProfile` ile DIŞARIDAN alır. Böylece aynı çekirdek hem
`binance_tr` hem `binance_global` profiliyle, hatta testte sahte bir profille
bile kullanılabilir.

BİLEŞEN ENJEKSİYONU:
Ağ çağrıları ve diğer "yamalanabilir" yardımcılar (HTTP, imza, bekleme)
modül seviyesinde SABİT OLMAZ; `signed_request`'e parametre olarak geçer.
Böylece `binance_tr_private` kendi `_http_get_json` adını korur ve onu
patch'leyen mevcut testler çekirdeği de etkiler — yüzey değişmeden çekirdek
eklenebilir. Testler bu modülü doğrudan test etmez; çekirdek, TR adapter'ın
aynen taşınmış parçasıdır.
"""

import hashlib
import hmac
import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from email.message import Message
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# B-14 / #30 / #31 / #32 / #33 sayıları, TR örneğindeki denetim notlarına
# aittir; bu sabitler olduğu gibi korunur. Taşıma bir davranış değişikliği
# değildir.
RECV_WINDOW_MS = 10000
REST_TIMEOUT_SEC = 15
REST_MAX_ATTEMPTS = 4
REST_BACKOFF_BASE_SEC = 0.35
REST_BACKOFF_MAX_SEC = 4.0
REST_BAN_BACKOFF_BASE_SEC = 600.0
REST_BAN_BACKOFF_MAX_SEC = 3600.0
REST_RETRY_AFTER_MAX_SEC = 300.0
PRIVATE_MAX_CONCURRENCY = 4

_PRIVATE_SEMAPHORE = threading.Semaphore(PRIVATE_MAX_CONCURRENCY)


class BinanceApiError(RuntimeError):
    """Binance private API hata zarfı veya HTTP hatası.

    TR'de `BinanceTrApiError` adıyla anılır; isim taşınabilirlik için
    sadeleştirildi ve eski ad adapter'da alias olarak korunur.
    """
    def __init__(self, code: int | str, msg: str, http_code: int | None = None,
                 raw: dict | None = None, label: str = "Binance"):
        super().__init__(f"{label} API hatası {code}: {msg}")
        self.code = code
        self.msg = msg
        self.http_code = http_code
        self.raw = raw

    @property
    def is_transient(self) -> bool:
        """1008/-1008 (Server Busy / Request Throttled) ve benzeri geçici hatalar.

        Binance Global negatif kodlar kullanır (-1003 TOO_MANY_REQUESTS).
        TR'nin pozitif karşılıkları da listede tutulur — iki borsa aynı
        listeyi paylaşır, böylece davranış farkı ayrı kodla değil aynı
        kodla belgelenir.
        """
        c = str(self.code or "").strip()
        m = str(self.msg or "").lower()
        if c in ("1008", "-1008", "1002", "-1002", "1003", "-1003", "1007", "-1007", "1016", "-1016"):
            return True
        if "server busy" in m or "unknown error" in m or "too many requests" in m or "service unavailable" in m:
            return True
        return False


@dataclass(frozen=True)
class PrivateExchangeProfile:
    """Bir borsanın private API yüzeyi — imzadan bağımsız kısım."""
    key: str
    label: str
    rest_base: str
    # Uç yolları.
    account: str
    open_orders: str
    my_trades: str
    exchange_info: str
    server_time: str
    # `/open/v1/...` gibi önek `None` ise yol doğrudan kullanılır.
    path_prefix: str = ""
    # Zarf: TR `{"code":0,"data":...}` zarfını kullanır, Global zarfsızdır.
    wraps_in_envelope: bool = True
    # Zarfın içindeki liste anahtarı. Global'da gövde zaten JSON dizisidir.
    list_key: str | None = "list"
    # Bakiye dizisinin anahtarı.
    balance_key: str = "accountAssets"
    # Notional filtresinin adı: TR `NOTIONAL`, Global `MIN_NOTIONAL`.
    notional_filter: str = "NOTIONAL"
    # Private uçlarda sembol ayracı: TR `BTC_USDT`, Global `BTCUSDT`.
    symbol_separator: str = "_"
    # `/open/v1/orders` sembol vermeden tüm listeyi döner mi?
    open_orders_needs_symbol: bool = True
    # Bakiye gövdesinde hata ayırt etmek için aranan alanlar. Global'ın hata
    # gövdesi `{"code":-2015,"msg":...}` şeklindedir ve `data` içermez; zarf
    # sanılırsa bakiye sessizce `[]` olur.
    success_markers: tuple[str, ...] = field(default=())


def http_get_json(url: str, headers: dict | None = None) -> dict | list:
    req = Request(url, headers=headers or {}, method="GET")
    with urlopen(req, timeout=REST_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url: str, headers: dict | None = None) -> dict | list:
    """Boş gövdeli POST — tüm parametreler query string'te (doküman: kabul edilir)."""
    req = Request(url, headers=headers or {}, method="POST", data=b"")
    with urlopen(req, timeout=REST_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def unwrap(payload, profile: PrivateExchangeProfile) -> dict | list:
    """Cevabı açar: hata zarfı varsa fırlatır, veriye erişir.

    Global'da zarf YOKTUR. Bu yüzden profil `wraps_in_envelope=False`
    olduğunda yalnız hata tespiti yapılır: gövdede `code`/`msg` varsa ve
    `success_markers`'ın hiçbiri yoksa bu BİR HATA cevabıdır, aksi hâlde
    "başarılı ama boş" sanılır ve kullanıcı bakiyesini kaybetmiş görünür.
    """
    if not isinstance(payload, dict):
        return payload

    code = payload.get("code", payload.get("status"))
    if code not in (None, 0, "0"):
        msg = payload.get("msg") or payload.get("message") or "bilinmiyor"
        raise BinanceApiError(code=code, msg=msg, raw=payload, label=profile.label)

    if not profile.wraps_in_envelope:
        # Zarfsız borsa: yukarıdaki kontrol hata gövdesini zaten yakalar,
        # çünkü Global hatalar `code` alanı taşır. Yalnız `status` taşıyan
        # ve veri içeren payload'lar (bazı başarılı yanıtlar) geçmeli.
        return payload

    data = payload.get("data")
    return data if data is not None else payload


def as_rows(payload, profile: PrivateExchangeProfile, context: str) -> list[dict]:
    """Cevabı satır listesine çevirir — BEKLENMEYEN ŞEMAYI SESSİZCE YUTMAZ.

    Bu, taşımanın en tehlikeli sessiz bozulmasını kapatır: liste dönen uçlar
    iki farklı biçimde dönebilir (zarflı dict içinde `list`, ya da doğrudan
    JSON dizisi). Eski kod `rows.get("list", [])` + `isinstance` korumasıyla
    beklenmedik biçimde boş liste döndürüyordu — hata yok, log yok; kullanıcı
    "açık emirim yok" görür, halbuki vardır.

    Burada beklenmeyen biçim loglanır. Dönen değer yine `[]` olabilir ama
    artık GÖRÜLEBİLİR; sessiz bir portföy, gürültülü bir logdan iyidir.
    """
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        if profile.list_key:
            rows = payload.get(profile.list_key)
            if rows is None:
                # Zarf açılmamışsa bir kat daha dene.
                inner = payload.get("data")
                if isinstance(inner, dict):
                    rows = inner.get(profile.list_key)
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
            if rows is None:
                logger.warning("%s: liste alanı bulunamadı (%s) — boş dönüldü",
                               context, profile.list_key)
                return []
            logger.warning("%s: liste alanı liste değil (%s) — boş dönüldü",
                           context, type(rows).__name__)
            return []
        rows = payload.get("data")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    logger.warning("%s: beklenmeyen cevap biçimi (%s) — boş dönüldü",
                   context, type(payload).__name__)
    return []


def retry_delay(attempt: int, headers=None) -> float:
    """Üstel backoff + jitter + Retry-After (#31).

    #33: sunucunun Retry-After değeri kırpılmadan (yalnız 5 dk tavanına)
    kullanılır; aksi hâlde sunucu "dakikalarca bekle" dediğinde istek 0.35 sn
    sonra tekrar atılır.
    """
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after is not None:
        try:
            return min(REST_RETRY_AFTER_MAX_SEC, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    exponential = min(REST_BACKOFF_MAX_SEC, REST_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))
    return exponential + random.uniform(0.0, exponential * 0.25)


def ban_delay(attempt: int, headers=None) -> float:
    """418 / kalıcı IP ban geri çekilmesi — saniyeler değil, ONLARCA DAKİKA (#32).

    30/60/90 sn'lik lineer bir dizi 4 denemelik bir döngüde banı tırmandırmak
    demektir. Sunucunun ipucu varsa o esas alınır, yoksa en az 10 dakikadan
    başlayan üstel geri çekilme uygulanır.
    """
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after is not None:
        try:
            return min(REST_BAN_BACKOFF_MAX_SEC, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    return min(REST_BAN_BACKOFF_MAX_SEC, REST_BAN_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))


def _read_server_time_ms(profile: PrivateExchangeProfile, http_get) -> int:
    payload = http_get(f"{profile.rest_base}{profile.path_prefix}{profile.server_time}")
    data = unwrap(payload, profile)
    if isinstance(data, dict):
        return int(data.get("serverTime") or 0)
    return 0


def server_time_offset_ms(profile: PrivateExchangeProfile, http_get, cache: dict,
                          lock: threading.Lock, ttl_sec: float) -> float:
    """Sunucu saati ile yerel saat farkı (ms) — TTL'li önbellek (#35).

    #35'in asıl hatası: ölçüm BAŞARISIZ olduğunda ofset 0'a düşüyordu, yani
    sunucu saati ölçülemeyen bir anda 10 sn'yi aşan kayma TÜM
    bakiye/açık emir/emir akışını `-1021 Timestamp outside recvWindow` ile
    tek noktadan kırıyordu. Artık **son bilinen ofset korunur**.
    """
    now = time.time()
    with lock:
        cached = dict(cache)
    if cached.get("at") and now - float(cached["at"]) < ttl_sec:
        return float(cached.get("offset") or 0.0)
    measured: float | None = None
    try:
        server_ms = _read_server_time_ms(profile, http_get)
        if server_ms:
            measured = float(server_ms) - now * 1000
    except Exception as exc:
        logger.info("%s sunucu saati alınamadı (%s); son bilinen ofset korunuyor",
                    profile.label, exc)
    with lock:
        if measured is not None:
            cache.update({"at": now, "offset": measured})
        # Ölçüm yoksa önceki (at, offset) ÇİZİLMEDEN bırakılır; eski ofset
        # bir sonraki başarılı ölçüme kadar geçerli kalır.
        return float(cache.get("offset") or 0.0)


def signed_request(method: str, path: str, params: dict | None,
                   api_key: str, api_secret: str, profile: PrivateExchangeProfile,
                   http_get, http_post, offset_ms_fn, server_time_cache: dict,
                   server_time_lock: threading.Lock, server_time_ttl: float,
                   idempotent: bool = True) -> dict | list:
    """HMAC-SHA256 imzalı Binance isteği.

    Parametreler (recvWindow+timestamp+signature dahil) query string'te
    taşınır; POST için gövde boştur — dokümana göre toplam imza alanı
    "query string + body" olduğundan bu kombinasyon geçerlidir. Bu, TR ile
    Global arasında AYNI olan kısımdır; taşımada değişmemiştir.

    #30 — KRİTİK (idempotency): `idempotent=False` ile çağrılan POST'lar
    (emir gönderme) timeout / 5xx / bozuk JSON sonrası **YENİDEN
    GÖNDERİLMEZ**. Aksi hâlde ağ zaman aşımında borsa emri ALDIĞI HALDE
    cevap kaybolursa aynı emir ikinci kez atılır. Yeniden deneme yalnız
    418/429 için yapılır; 429'da borsa isteği ALMAMIŞTIR (ağırlık penceresi
    dolu), 429 dışı 5xx'te "emri aldım ama cevabım bozuk" durumu ayırt
    edilemez.
    """
    base_params = dict(params or {})
    base_params["recvWindow"] = RECV_WINDOW_MS
    offset_ms = offset_ms_fn()
    headers = {"X-MBX-APIKEY": api_key}
    last_error: Exception | None = None
    is_post = method.upper() == "POST"
    label = profile.label

    with _PRIVATE_SEMAPHORE:
        for attempt in range(1, REST_MAX_ATTEMPTS + 1):
            attempt_params = dict(base_params)
            attempt_params["timestamp"] = int(time.time() * 1000 + offset_ms)
            query = urlencode(sorted(attempt_params.items()))
            signature = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"),
                                 hashlib.sha256).hexdigest()
            url = f"{profile.rest_base}{profile.path_prefix}{path}?{query}&signature={signature}"
            try:
                payload = (http_post(url, headers) if is_post else http_get(url, headers))
                return unwrap(payload, profile)
            except BinanceApiError as exc:
                last_error = exc
                if exc.is_transient:
                    if not idempotent:
                        raise exc
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    delay = max(1.0, retry_delay(attempt))
                    logger.warning(
                        "%s geçici sunucu/yoğunluk yanıtı (kod %s, %s) | path=%s | %.2f sn beklenip yeniden denenecek (%d/%d)",
                        label, exc.code, exc.msg, path, delay, attempt, REST_MAX_ATTEMPTS
                    )
                    time.sleep(delay)
                    continue
                if str(exc.code) in ("1021", "-1021"):
                    # Timestamp outside recvWindow — saat ofsetini sıfırlayıp tazele
                    with server_time_lock:
                        server_time_cache["at"] = 0.0
                    offset_ms = offset_ms_fn()
                    if attempt < REST_MAX_ATTEMPTS:
                        time.sleep(0.5)
                        continue
                raise exc
            except HTTPError as exc:
                # Binance 4xx hataları JSON body'sinde {code, msg} taşır.
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                    parsed = json.loads(body)
                    api_code = parsed.get("code") or parsed.get("status") or exc.code
                    api_msg = parsed.get("msg") or parsed.get("message") or body[:200]
                    binance_err = BinanceApiError(api_code, api_msg, http_code=exc.code,
                                                  raw=parsed, label=label)
                    logger.error("%s HTTP %s | path=%s | code=%s msg=%s | params=%s",
                                 label, exc.code, path, api_code, api_msg, base_params)
                except Exception:
                    binance_err = BinanceApiError(exc.code, exc.reason, http_code=exc.code, label=label)
                    logger.error("%s HTTP %s | path=%s | reason=%s | params=%s",
                                 label, exc.code, path, exc.reason, base_params)
                last_error = binance_err
                if exc.code == 418:
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    time.sleep(ban_delay(attempt, exc.headers))
                    continue
                if exc.code == 429 or (500 <= exc.code < 600) or binance_err.is_transient:
                    if not idempotent and exc.code != 429 and not binance_err.is_transient:
                        raise binance_err
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    delay = (max(1.0, retry_delay(attempt, exc.headers))
                             if binance_err.is_transient else retry_delay(attempt, exc.headers))
                    logger.warning(
                        "%s HTTP %s geçici hata (kod %s) | %.2f sn sonra yeniden denenecek (%d/%d)",
                        label, exc.code, binance_err.code, delay, attempt, REST_MAX_ATTEMPTS
                    )
                    time.sleep(delay)
                    continue
                # 4xx hataları (400, 401, 403, vb.) — anlamlı hatayla raise
                raise binance_err
            except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                # #30: bu kolon "istek borsaya ULAŞTI mı?" sorusunun cevabı
                # OLMAYAN durumlardır. Okuma için yeniden denemek zararsızdır;
                # POST (emir) için ASLA — çağıranın durum sorgulaması gerekir.
                last_error = exc
                if not idempotent:
                    raise RuntimeError(
                        f"{label} {method.upper()} {path} cevap vermedi; emir gönderilmiş "
                        f"olabilir, TEKRAR GÖNDERİLMEDİ: {exc}"
                    ) from exc
                if attempt == REST_MAX_ATTEMPTS:
                    break
                time.sleep(retry_delay(attempt))
    raise RuntimeError(
        f"{label} imzalı istek {REST_MAX_ATTEMPTS} denemede başarısız: {last_error}"
    ) from last_error


def new_client_order_id(prefix: str = "sc") -> str:
    """Emirlere iliştirilecek benzersiz `clientOrderId` (#30 idempotency).

    Binance `clientOrderId` alanı en fazla 36 karakter kabul eder; UUID hex'i
    güvenle sığar. Anahtar BORSADA saklanır: ağ zaman aşımı sonrası aynı
    anahtarla yapılan ikinci gönderim "duplicate" olarak reddedilir. Bu, TR ve
    Global için birebir aynıdır (Global'da ayrıca karakter deseni
    `^[.A-Z:/a-z0-9_-]{1,36}$` ile sınırlıdır; üretilen değer uyumludur).
    """
    import uuid
    return f"{prefix}{uuid.uuid4().hex}"[:36]


def fmt_quantity(q: float, step_size: float | None = None) -> str:
    """Miktarı API'nin beklediği ondalık string'e çevir (bilimsel gösterim yok)."""
    import math
    if step_size and step_size > 0:
        q = math.floor(float(q) / float(step_size)) * float(step_size)
    return f"{q:.8f}".rstrip("0").rstrip(".")


def fmt_price(p: float, tick_size: float | None = None) -> str:
    """Fiyatı sembolün tick_size adımına göre yuvarlar ve string formatlar."""
    p_val = float(p)
    if tick_size and tick_size > 0:
        p_val = round(p_val / tick_size) * tick_size
        tick_str = f"{tick_size:.10f}".rstrip("0")
        decimals = len(tick_str.split(".")[1]) if "." in tick_str else 0
        return f"{p_val:.{decimals}f}"
    if p_val >= 1:
        return f"{p_val:.2f}"
    return f"{p_val:.6f}".rstrip("0").rstrip(".")


def normalize_trade(t: dict, id_field: str) -> dict:
    """İşlem satırını UI'nin beklediği alanlara indirger.

    `id_field` iki borsada FARKLIDIR ve bu, sessiz bir bozulmadır: TR'de
    `tradeId`, Global'da `id`. Yanlış alan okunursa tüm işlemler `id=0` olur
    ve FIFO maliyet hesabı sessizce sıfırlanır.
    """
    return {
        "id": int(t.get(id_field) or 0),
        "orderId": str(t.get("orderId") or ""),
        "symbol": t.get("symbol", "").replace("_", ""),
        "price": t.get("price", "0"),
        "qty": t.get("qty", "0"),
        "quoteQty": t.get("quoteQty", "0"),
        "commission": t.get("commission", "0"),
        "commissionAsset": t.get("commissionAsset", ""),
        "isBuyer": bool(t.get("isBuyer")),
        "isMaker": bool(t.get("isMaker")),
        "time": int(t.get("time") or 0),
    }


def normalize_order(o: dict) -> dict:
    """Açık emir satırını UI'nin beklediği alanlara indirger."""
    return {
        "orderId": int(o.get("orderId") or 0),
        "symbol": o.get("symbol", ""),
        "side": o.get("side", ""),
        "type": o.get("type", ""),
        "price": o.get("price", "0"),
        "stopPrice": o.get("stopPrice") or "0",
        "origQty": o.get("origQty", "0"),
        "executedQty": o.get("executedQty", "0"),
        "status": o.get("status", ""),
        # TR `createTime` öncelikli, Global `time` döner.
        "time": int(o.get("createTime") or o.get("time") or 0),
        "orderListId": int(o.get("orderListId") or -1),
        "clientOrderId": str(o.get("clientOrderId") or ""),
    }
