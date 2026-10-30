"""Mum formasyonları, destek/direnç seviyeleri ve piyasa yapısı (saf fonksiyonlar)."""
from app import forex_patterns as fp


def bar(o, h, l, c, t=0):
    return {"time": t, "open": o, "high": h, "low": l, "close": c}


def flat(n=12, price=100.0):
    return [bar(price, price + 1, price - 1, price + (0.1 if i % 2 else -0.1), i) for i in range(n)]


def downtrend(n=12, start=120.0):
    out = []
    for i in range(n):
        o = start - i * 1.5
        out.append(bar(o, o + 0.6, o - 1.8, o - 1.4, i))
    return out


def uptrend(n=12, start=100.0):
    out = []
    for i in range(n):
        o = start + i * 1.5
        out.append(bar(o, o + 1.8, o - 0.6, o + 1.4, i))
    return out


def names(bars, **kw):
    return {(p["name"], p["bias"], p["bars_ago"]) for p in fp.detect_patterns(bars, **kw)}


def test_bullish_engulfing_after_downtrend():
    b = downtrend()
    last = b[-1]["close"]
    b.append(bar(last - 0.1, last + 4.5, last - 0.3, last + 4.2))          # önceki kırmızıyı yutan yeşil
    found = names(b)
    assert any(n.startswith("Yutan boğa") and bias == "BUY" and ago == 0 for n, bias, ago in found)


def test_bearish_engulfing_after_uptrend():
    b = uptrend()
    last = b[-1]["close"]
    b.append(bar(last + 0.1, last + 0.4, last - 4.0, last - 3.8))
    assert any(n.startswith("Yutan ayı") and bias == "SELL" for n, bias, _ in names(b))


def test_hammer_in_downtrend_and_shooting_star_in_uptrend():
    d = downtrend()
    last = d[-1]["close"]
    d.append(bar(last, last + 0.4, last - 3.0, last + 0.3))               # uzun alt fitil
    assert any(n.startswith("Çekiç") and bias == "BUY" for n, bias, _ in names(d))
    u = uptrend()
    last = u[-1]["close"]
    u.append(bar(last, last + 3.0, last - 0.1, last + 0.3))               # uzun üst fitil
    assert any(n.startswith("Kayan yıldız") and bias == "SELL" for n, bias, _ in names(u))


def test_doji_and_inside_bar():
    b = flat()
    b.append(bar(100.0, 101.0, 99.0, 100.05))
    found = {n for n, _b, _a in names(b)}
    assert any(n.startswith("Doji") for n in found)
    b2 = flat() + [bar(99.5, 101.5, 98.5, 100.2), bar(100.0, 101.0, 99.0, 100.3)]
    assert any(n.startswith("İç mum") for n, _b, _a in names(b2))


def test_morning_star_three_bar():
    b = downtrend()
    last = b[-1]["close"]
    b += [bar(last, last + 0.3, last - 4.0, last - 3.8),                   # büyük kırmızı
          bar(last - 4.2, last - 3.7, last - 4.6, last - 4.3),             # küçük gövde
          bar(last - 4.0, last + 0.6, last - 4.1, last + 0.2)]             # büyük yeşil, ilk mumun ortasının üstünde
    assert any(n.startswith("Sabah yıldızı") and bias == "BUY" for n, bias, _ in names(b))


def test_short_series_yields_nothing():
    assert fp.detect_patterns(flat(5)) == []


def test_market_structure_up_and_down():
    def zigzag(base_step):
        out, price = [], 100.0
        for i in range(60):
            leg = (i // 6) % 2
            price += (2.0 if leg == 0 else -1.0) * (1 if base_step > 0 else -1) * (1 if leg == 0 else 1)
            out.append(bar(price, price + 0.5, price - 0.5, price, i))
        return out
    up = fp.market_structure(zigzag(+1))
    assert "yapi" in up and up["kirilim"] in ("aralık içinde", "son 20 mumun yükseğini kırdı", "son 20 mumun düşüğünü kırdı")
    assert fp.market_structure(flat(10))["yapi"] == "yetersiz veri"


def _frames(price=77600.0, atr=500.0):
    def mk(n, step):
        out = []
        for i in range(n):
            c = price + (60 - i) * step * (1 if i % 7 else -1)
            out.append(bar(c, c + atr * 0.4, c - atr * 0.4, c + atr * 0.1 * (1 if i % 2 else -1), i * 3600))
        return out
    return {"1h": mk(120, 8.0), "4h": mk(120, 20.0), "1d": mk(30, 60.0)}


def test_key_levels_always_gives_both_sides_even_without_swings():
    # fiyat tarihsel düşükte: aşağıda swing yok; yine de pivot/yuvarlak/Fib seviyeleri alt tarafı doldurmalı
    price = 77000.0
    falling = [bar(price + (200 - i) * 30, price + (200 - i) * 30 + 40, price + (200 - i) * 30 - 40, price + (200 - i) * 30 - 20, i)
               for i in range(200)]
    frames = {"1h": falling, "4h": falling[::4] * 1, "1d": falling[::8]}
    lv = fp.key_levels(frames, price, 400.0)
    assert lv["supports"] and lv["resistances"]
    assert all(l["price"] < price for l in lv["supports"]) and all(l["price"] > price for l in lv["resistances"])
    assert any("yuvarlak seviye" in l["labels"] for l in lv["supports"] + lv["resistances"])


def test_key_levels_sorted_by_distance_and_clustered():
    price = 77600.0
    lv = fp.key_levels(_frames(price), price, 500.0, top=4)
    sup = [l["price"] for l in lv["supports"]]
    assert sup == sorted(sup, reverse=True) and len(sup) <= 4
    res = [l["price"] for l in lv["resistances"]]
    assert res == sorted(res)
    assert all(l["distance_atr"] is not None and l["strength"] > 0 for l in lv["supports"])


def test_compact_chart_and_ranges():
    f = _frames()
    assert len(fp.compact_chart(f["1h"], 24)) == 24 and len(fp.compact_chart(f["1h"], 24)[0]) == 4
    assert fp.compact_chart([], 5) == []
    r = fp.key_ranges(f)
    assert {"son_24s_yuksek", "son_24s_dusuk", "onceki_gun", "hafta_yuksek", "hafta_dusuk"} <= set(r)
