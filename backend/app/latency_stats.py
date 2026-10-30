"""İstek gecikmesi ölçümü (2026-10-30).

Uç nokta başına (yol şablonu) son N isteğin süresini bellekte tutar; ortalama,
p50/p95/p99, en yavaş ve hata sayısını üretir. Yavaş istekler (eşik üstü) ayrı
bir halka tamponunda tutulur. Amaç: Ayarlar → Sistem Sağlığı'ndan hangi
uç noktanın yavaş olduğunu görmek ve CSV olarak dışa aktarmak.

Bellek sınırlıdır: uç nokta başına 300 örnek, toplam en fazla 400 uç nokta,
100 yavaş istek. Veritabanına yazmaz, yeniden başlatınca sıfırlanır.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Tuple

SAMPLES_PER_ROUTE = 300
MAX_ROUTES = 400
SLOW_THRESHOLD_MS = 500.0
SLOW_LOG_SIZE = 100
# Ölçüm uç noktasının kendisi ve gürültülü olanlar istatistiği bozmasın.
IGNORED_PATHS = ("/api/system/latency",)
# Saldırgan kontrollü anahtar üretimini önler: yalnız standart yöntemler ve yalnız
# yönlendirmeyle eşleşen yol ŞABLONLARI ayrı satır olur; eşleşmeyenler (404 taraması,
# rastgele yol/yöntem) tek kovada toplanır, gerçek uç noktaların yerini dolduramaz.
STANDARD_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
UNMATCHED_BUCKET = "<eşleşmeyen>"

_lock = threading.Lock()
_started_at = time.time()
# anahtar: "GET /api/forex/radar" → (süre_ms, durum, zaman) örnekleri
_samples: Dict[str, Deque[Tuple[float, int, float]]] = {}
_totals: Dict[str, int] = {}
_slow: Deque[Dict[str, Any]] = deque(maxlen=SLOW_LOG_SIZE)


def record(method: str, path: str, duration_ms: float, status: int) -> None:
    if path in IGNORED_PATHS or method == "OPTIONS":
        return
    key = f"{method} {path}"
    now = time.time()
    with _lock:
        buf = _samples.get(key)
        if buf is None:
            if len(_samples) >= MAX_ROUTES:
                return
            buf = deque(maxlen=SAMPLES_PER_ROUTE)
            _samples[key] = buf
        buf.append((duration_ms, status, now))
        _totals[key] = _totals.get(key, 0) + 1
        if duration_ms >= SLOW_THRESHOLD_MS:
            _slow.append({"ts": now, "method": method, "path": path, "ms": round(duration_ms, 1), "status": status})


def _percentile(sorted_values: List[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def snapshot() -> Dict[str, Any]:
    with _lock:
        items = [(k, list(v), _totals.get(k, 0)) for k, v in _samples.items()]
        slow = list(_slow)
    rows: List[Dict[str, Any]] = []
    for key, samples, total in items:
        durations = sorted(s[0] for s in samples)
        method, _, path = key.partition(" ")
        errors = sum(1 for s in samples if s[1] >= 500)
        rows.append({
            "method": method,
            "path": path,
            "count": total,
            "window": len(samples),
            "avg_ms": round(sum(durations) / len(durations), 1),
            "p50_ms": round(_percentile(durations, 0.50), 1),
            "p95_ms": round(_percentile(durations, 0.95), 1),
            "p99_ms": round(_percentile(durations, 0.99), 1),
            "max_ms": round(durations[-1], 1),
            "last_ms": round(samples[-1][0], 1),
            "errors_5xx": errors,
            "last_at": samples[-1][2],
        })
    rows.sort(key=lambda r: r["p95_ms"], reverse=True)
    return {
        "generated_at": time.time(),
        "uptime_sec": round(time.time() - _started_at, 1),
        "slow_threshold_ms": SLOW_THRESHOLD_MS,
        "routes": rows,
        "slow_requests": sorted(slow, key=lambda s: s["ts"], reverse=True),
    }


def reset() -> None:
    with _lock:
        _samples.clear()
        _totals.clear()
        _slow.clear()


class LatencyMiddleware:
    """Saf ASGI ara katman: yanıtın tamamı gönderilene kadar geçen süreyi ölçer.

    `BaseHTTPMiddleware` kullanılmaz (her isteğe ek maliyet ve SSE akışını
    bozma riski). Yol şablonu yönlendirmeden sonra `scope["route"]`dan okunur;
    böylece `/api/auto-paper/trades/{trade_id}/close` tek satırda toplanır.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = int(message.get("status", 0))
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                route = scope.get("route")
                path = getattr(route, "path", None) or UNMATCHED_BUCKET
                method = str(scope.get("method", "GET")).upper()
                if method not in STANDARD_METHODS:
                    method = "OTHER"
                record(method, path, (time.perf_counter() - start) * 1000.0, status["code"])
            await send(message)

        await self.app(scope, receive, send_wrapper)
