"""Fırsat taraması: kapılar, demo hesaba emir (MT5 komut kuyruğu), strateji etiketi ve düğme güvencesi."""
import asyncio
import json
import time

import pytest

from app import opportunity_trades as ot
from app.routers import forex as fx
from app.routers import forex_chat


def analysis(**kw):
    base = {
        "symbol": "XAUUSD", "ok": True, "bias": "BUY", "score": 3.4, "price": 4000.0, "price_source": "mt5_tick",
        "atr": 8.0, "frames": {"1h": {"atr": 4.0, "score": 3.0}, "1d": {"atr": 30.0, "score": 2.0}},
        "levels": {"resistances": [{"price": 4020.0}], "supports": [{"price": 3980.0}]}, "sources": {"1h": "mt5"},
    }
    base.update(kw)
    return base


SCAN = {"symbol": "XAUUSD", "direction": "BUY", "average": 0.6, "agreement": 1.0, "summary": "AL"}


def plan(a=None, scan=SCAN, cal=None):
    return ot.plan_trade(a or analysis(), scan, cal, pip_size=0.1)


# ----------------------------------------------------------------------------- kapılar

def test_all_gates_pass_builds_atr_based_plan():
    v = plan()
    assert v["ok"]
    p = v["plan"]
    assert p["direction"] == "BUY" and p["entry_price"] == 4000.0
    assert p["sl_pips"] == pytest.approx(60.0) and p["tp_pips"] == pytest.approx(90.0)     # 1.5×ATR(4)=6 → 60 pip; 1.5R
    assert p["atr_pips"] == pytest.approx(40.0) and "TradingView AL" in p["note"]


@pytest.mark.parametrize("mutate,expect", [
    (dict(bias="BEKLE"), "net yön yok"),
    (dict(score=1.0), "sinyal gücü"),
    (dict(price_source="yahoo"), "MT5"),
    (dict(ok=False), "analiz verisi"),
])
def test_analysis_gates_block(mutate, expect):
    v = plan(analysis(**mutate))
    assert not v["ok"] and expect in v["reason"]


def test_tradingview_disagreement_and_weak_agreement_block():
    assert "uyumsuz" in plan(scan={**SCAN, "direction": "SELL"})["reason"]
    assert "hemfikir" in plan(scan={**SCAN, "agreement": 0.5})["reason"]
    assert "hemfikir" in plan(scan={**SCAN, "average": 0.1})["reason"]
    assert not plan(scan=None)["ok"]


def test_imminent_high_impact_news_blocks_but_far_or_low_impact_does_not():
    assert "yüksek etkili veri" in plan(cal={"yaklasan_24_saat": [{"title": "NFP", "stars": 3, "dakika": 20}]})["reason"]
    assert plan(cal={"yaklasan_24_saat": [{"title": "NFP", "stars": 3, "dakika": 200}]})["ok"]
    assert plan(cal={"yaklasan_24_saat": [{"title": "X", "stars": 2, "dakika": 5}]})["ok"]


def test_opposing_level_nearly_on_top_still_blocks_sell_uses_supports():
    assert "dirence" in plan(analysis(levels={"resistances": [{"price": 4000.5}], "supports": []}))["reason"]
    a = analysis(bias="SELL", score=-3.4, levels={"resistances": [], "supports": [{"price": 3999.5}]})
    v = ot.plan_trade(a, {**SCAN, "direction": "SELL", "average": -0.6}, None, 0.1)
    assert not v["ok"] and "desteğe" in v["reason"]


def test_close_level_shrinks_lot_instead_of_blocking():
    v = plan(analysis(levels={"resistances": [{"price": 4003.0}], "supports": []}))        # stop 6, boşluk 3 → 3/4.8
    assert v["ok"] and v["plan"]["size_mult"] == pytest.approx(0.625) and "KÜÇÜLTÜLMÜŞ LOT" in v["plan"]["note"]
    assert plan()["plan"]["size_mult"] == 1.0                                               # uzak seviye: tam lot


def test_opposing_news_halves_lot_and_stacks_with_level_room():
    v = plan(cal=released({"XAUUSD": -1}))
    assert v["ok"] and v["plan"]["size_mult"] == 0.5 and "ABD CPI" in v["plan"]["note"]
    both = plan(analysis(levels={"resistances": [{"price": 4003.0}], "supports": []}), cal=released({"XAUUSD": -1}))
    assert both["plan"]["size_mult"] == pytest.approx(0.312, abs=0.001)
    floor = plan(analysis(levels={"resistances": [{"price": 4001.0}], "supports": []}), cal=released({"XAUUSD": -1}))
    assert floor["plan"]["size_mult"] == ot.MIN_SIZE_MULT


# ----------------------------------------------------------------------------- demo hesaba emir

@pytest.fixture
def mt5(monkeypatch):
    """Bağlı DEMO hesap + boş pozisyon listesi; komut kuyruğu ve yan etkiler izole."""
    state = {"connected": True, "auto_trade": True, "open_positions": [], "pending_commands": [],
             "account": {"server": "ICMarketsSC-Demo", "balance": 1000.0}}
    monkeypatch.setattr(fx, "_MT5_STATE", state)
    monkeypatch.setattr(fx, "_invalidate_status_cache", lambda: None)
    logs = []
    monkeypatch.setattr(fx, "_log_auto_decision", lambda *a, **k: logs.append((a, k)))
    monkeypatch.setattr(fx._AUTO_SETTINGS, "max_open_positions", 20, raising=False)
    state["logs"] = logs
    return state


def test_open_scan_position_queues_demo_order_with_strategy(mt5):
    res = fx.open_scan_position("XAUUSD", "BUY", 60.0, 90.0, 40.0, 3.4, "not")
    assert res["ok"] and res["lots"] >= 0.01
    cmd = mt5["pending_commands"][0]
    assert cmd["action"] == "OPEN_ORDER" and cmd["symbol"] == "XAUUSD" and cmd["direction"] == "BUY"
    assert cmd["strategy"] == "FIRSAT_TARAMASI" and cmd["strategy_label"].startswith("Fırsat") and cmd["comment"].startswith("FRS")
    assert cmd["sl_pips"] == 60.0 and cmd["tp_pips"] == 90.0 and cmd["entry_source"] == "firsat_taramasi"
    assert mt5["logs"] and mt5["logs"][0][0][0] == "ENTRY"


@pytest.mark.parametrize("mutate,expect", [
    (lambda s: s.update(connected=False), "bağlı değil"),
    (lambda s: s["account"].update(server="ICMarketsSC-Live"), "DEMO"),
    (lambda s: s["account"].update(server=""), "DEMO"),
    (lambda s: s.update(auto_trade=False), "otomatik işlem kapalı"),
    (lambda s: s["open_positions"].append({"symbol": "XAUUSD", "direction": "SELL"}), "zaten açık pozisyon"),
    (lambda s: s["account"].update(balance=0), "bakiye"),
])
def test_open_scan_position_refuses_unsafe_states(mt5, mutate, expect):
    mutate(mt5)
    res = fx.open_scan_position("XAUUSD", "BUY", 60.0, 90.0, 40.0, 3.4, "n")
    assert not res["ok"] and expect in res["reason"] and not mt5["pending_commands"]


def test_open_scan_position_respects_global_position_cap(mt5, monkeypatch):
    monkeypatch.setattr(fx._AUTO_SETTINGS, "max_open_positions", 1, raising=False)
    mt5["open_positions"].append({"symbol": "EURUSD", "direction": "BUY"})
    res = fx.open_scan_position("GBPUSD", "SELL", 20.0, 30.0, 14.0, 3.0, "n")
    assert not res["ok"] and "sınırı" in res["reason"]


def test_lot_is_capped_by_balance_and_category(mt5):
    mt5["account"]["balance"] = 1000.0
    res = fx.open_scan_position("EURUSD", "BUY", 10.0, 15.0, 7.0, 3.0, "n")    # dar stop → büyük ham lot
    assert res["ok"] and res["lots"] <= 0.25            # 1000$ hesapta FX tavanı (bakiyenin 0.00025'i)


def test_strategy_labels_and_deal_inference():
    assert fx.strategy_name_for("firsat_taramasi") == "FIRSAT_TARAMASI"
    assert fx.strategy_comment_tag("firsat_taramasi") == "FRS"
    assert fx.strategy_display_label("FIRSAT_TARAMASI").startswith("Fırsat Taraması")
    assert fx.strategy_display_label("FRS") == fx.FIRSAT_LABEL
    # köprüden dönen kapanış kaydı: yalnız yorum etiketi varsa da strateji çözülmeli
    assert fx.strategy_from_mt5_deal({"comment": "FRS 96"}) == "FIRSAT_TARAMASI"
    assert fx.strategy_from_mt5_deal({"strategy": "FIRSAT_TARAMASI"}) == "FIRSAT_TARAMASI"
    assert fx.strategy_from_mt5_deal({"comment": "RADAR 80"}) == "M1_M5_RADAR_SCALPER"     # mevcut etiketler bozulmadı


# ----------------------------------------------------------------------------- açma akışı

def _patch_open(monkeypatch, ok=True, reason="x"):
    calls = []

    def fake_open(sym, direction, sl, tp, atr, score, note, lots_mult=1.0):
        calls.append((sym, direction))
        return {"ok": True, "cmd_id": "CMD-1", "lots": 0.02, "risk_usd": 10.0} if ok else {"ok": False, "reason": reason}

    monkeypatch.setattr(fx, "open_scan_position", fake_open)
    monkeypatch.setattr(fx, "get_symbol_trading_specs", lambda sym, **k: {"pip_size": 0.1, "pip_val": 10.0})
    ot._last_open.clear()
    return calls


def test_open_from_scan_opens_qualified_and_reports_skips(monkeypatch):
    calls = _patch_open(monkeypatch)
    analyses = {"XAUUSD": analysis(), "BTCUSD": analysis(symbol="BTCUSD", bias="BEKLE")}
    scan = {"all": [SCAN, {"symbol": "BTCUSD", "direction": "SELL", "average": -0.5, "agreement": 1.0, "summary": "SAT"}]}
    res = asyncio.run(ot.open_from_scan(analyses, scan, None))
    assert calls == [("XAUUSD", "BUY")] and [o["symbol"] for o in res["opened"]] == ["XAUUSD"]
    assert res["skipped"][0]["symbol"] == "BTCUSD" and "net yön yok" in res["skipped"][0]["reason"]
    text = ot.describe_opening(res, {"XAUUSD": "Altın"})
    assert "Altın BUY: demo hesapta işlem açıldı" in text and "BTCUSD: açılmadı" in text


def test_cooldown_prevents_second_open_and_account_refusal_is_reported(monkeypatch):
    calls = _patch_open(monkeypatch)
    asyncio.run(ot.open_from_scan({"XAUUSD": analysis()}, {"all": [SCAN]}, None))
    again = asyncio.run(ot.open_from_scan({"XAUUSD": analysis()}, {"all": [SCAN]}, None))
    assert len(calls) == 1 and "soğuma" in again["skipped"][0]["reason"]
    calls2 = _patch_open(monkeypatch, ok=False, reason="bu sembolde zaten açık pozisyon var")
    res = asyncio.run(ot.open_from_scan({"XAUUSD": analysis()}, {"all": [SCAN]}, None))
    assert calls2 and not res["opened"] and "zaten açık" in res["skipped"][0]["reason"]
    assert "işlem açılmadı" in ot.describe_opening(res, {})


# ----------------------------------------------------------------------------- sohbet

def test_context_strips_hidden_analysis_and_includes_demo_result():
    findings = {"ta:XAUUSD": {"sembol": "XAUUSD", "yon": "BUY", "_analysis": {"candles": [1] * 1000}},
                "demo": {"acilan": [{"symbol": "XAUUSD"}], "acilmayan": []}}
    ctx = forex_chat.build_context(findings)
    assert "_analysis" not in json.dumps(ctx) and ctx["demo_islemler"]["acilan"][0]["symbol"] == "XAUUSD"


def test_chat_opens_orders_only_in_opportunity_mode(monkeypatch):
    """Serbest metin ('fırsat taraması yap, işlem aç') asla emir yazmaz; yalnız mode=opportunity_scan."""
    calls = []

    async def fake_open(analyses, scan, cal):
        calls.append(1)
        return {"opened": [], "skipped": []}

    monkeypatch.setattr(ot, "open_from_scan", fake_open)
    monkeypatch.setattr(forex_chat.forex_research, "scan_opportunities", lambda *a, **k: {"top": [SCAN], "all": [SCAN], "scanned": 1})

    async def fake_stream(*a, **k):
        yield {"event": "done", "data": {}}

    monkeypatch.setattr(forex_chat.llm_analysis, "stream_chat", fake_stream)
    monkeypatch.setattr(forex_chat, "plan_steps", lambda text, symbols=None: [])
    forex_chat.rate_limit.__globals__["_rate_limiters"].clear()

    async def drive(mode):
        body = {"messages": [{"role": "user", "content": "fırsat taraması yap, işlem aç"}]}
        if mode:
            body["mode"] = mode
        resp = await forex_chat.forex_chat(body, None)
        return [c async for c in resp.body_iterator]

    asyncio.run(drive(None))
    assert not calls                                   # metinle emir yazılmaz
    asyncio.run(drive("opportunity_scan"))
    assert calls == [1]                                # yalnız düğme modu açma adımını çalıştırır


# ----------------------------------------------------------------------------- haber SONUCU: destekler / bloklar

def released(yon, dakika=-20, stars=3, title="ABD CPI"):
    return {"aciklanan_son_6_saat": [{"title": title, "currency": "USD", "stars": stars, "dakika": dakika,
                                      "actual": "3.4%", "forecast": "3.0%", "sonuc": "Beklentiden yüksek", "yon": yon}]}


def test_released_data_supporting_direction_allows_and_relaxes_score():
    weak = analysis(score=2.1)                                # tek başına eşik (2.5) altı
    assert "sinyal gücü" in plan(weak)["reason"]
    v = plan(weak, cal=released({"XAUUSD": +1}))              # veri BUY'ı destekliyor → eşik 2.0
    assert v["ok"] and "haber DESTEKLİYOR" in v["plan"]["note"] and v["plan"]["news"]["verdict"] == "supports"


def test_old_or_unrelated_released_data_is_ignored():
    assert plan(cal=released({"XAUUSD": -1}, dakika=-300))["ok"]          # 3 saatten eski: etkisiz
    assert plan(cal=released({"EURUSD": -1}))["ok"]                       # başka sembole ait yön
    e = ot.news_effect(released({"XAUUSD": -1}, stars=2), "XAUUSD", "BUY")
    assert e["net"] == -1.0 and e["verdict"] == "opposes"                 # 2★ ağırlık 1 yeter
    assert ot.news_effect(None, "XAUUSD", "BUY")["verdict"] == "neutral"


def test_conflicting_events_net_out_and_sell_direction_flips_meaning():
    cal = {"aciklanan_son_6_saat": [
        {"title": "A", "stars": 2, "dakika": -10, "yon": {"XAUUSD": 1}},
        {"title": "B", "stars": 2, "dakika": -30, "yon": {"XAUUSD": -1}}]}
    assert ot.news_effect(cal, "XAUUSD", "BUY")["verdict"] == "neutral"
    assert ot.news_effect(released({"XAUUSD": -1}), "XAUUSD", "SELL")["verdict"] == "supports"     # SELL için -1 destek


def test_unreleased_imminent_event_still_blocks_even_with_supporting_result():
    cal = {**released({"XAUUSD": +1}), "yaklasan_24_saat": [{"title": "NFP", "stars": 3, "dakika": 10}]}
    assert "yüksek etkili veri" in plan(cal=cal)["reason"]               # henüz sonucu yok: bekle


def test_compact_calendar_adds_per_symbol_direction_from_outcome():
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(time.time() - 20 * 60, tz=timezone.utc).isoformat()
    items = [{"title": "CPI", "currency": "USD", "stars": 3, "date_iso": iso, "actual": "3.4%", "forecast": "3.0%",
              "outcome": {"side": "bullish", "label_tr": "Beklentiden yüksek"}, "affected_symbols": ["XAUUSD"]}]
    out = forex_chat.compact_calendar(items, time.time(), {"USD"}, ["XAUUSD", "EURUSD"])
    row = out["aciklanan_son_6_saat"][0]
    assert row["yon"]["XAUUSD"] == -1 and row["yon"]["EURUSD"] == -1        # USD güçlü: altın ve EURUSD aşağı
    plain = forex_chat.compact_calendar(items, time.time(), {"USD"})
    assert "yon" not in plain["aciklanan_son_6_saat"][0]


# ----------------------------------------------------------------------------- sürpriz z-skoru (2.6)

def test_news_effect_uses_z_to_drop_noise_and_weight_big_surprises():
    base = lambda z: {"aciklanan_son_6_saat": [{"title": "CPI", "stars": 2, "dakika": -10, "yon": {"XAUUSD": -1}, "z": z}]}   # noqa: E731
    assert ot.news_effect(base(0.3), "XAUUSD", "BUY")["verdict"] == "neutral"            # |z|<0.5: gürültü
    mid = ot.news_effect(base(1.0), "XAUUSD", "BUY")
    assert mid["net"] == -1.0 and mid["verdict"] == "opposes"
    big = ot.news_effect(base(3.0), "XAUUSD", "BUY")
    assert big["net"] == -2.0                                                              # z üst sınırı 2
    half = ot.news_effect(base(0.6), "XAUUSD", "BUY")
    assert half["net"] == pytest.approx(-0.6) and half["verdict"] == "neutral"             # küçük sürpriz: eşik altı


def test_attach_surprise_z_requires_history(monkeypatch):
    from app import database

    async def fake_sd(key, n=36):
        return (0.2, 12) if key.startswith("cpi") else (0.0, 3)

    monkeypatch.setattr(database, "get_surprise_sd", fake_sd)
    monkeypatch.setattr("app.forex_news.normalize_event_title", lambda t: str(t).lower())
    cal = {"aciklanan_son_6_saat": [
        {"title": "CPI", "actual": "3.4%", "forecast": "3.0%"},
        {"title": "Retail", "actual": "1.0%", "forecast": "0.5%"},
        {"title": "Konuşma", "actual": "—", "forecast": "—"}]}
    asyncio.run(forex_chat.attach_surprise_z(cal))
    rows = cal["aciklanan_son_6_saat"]
    assert rows[0]["z"] == pytest.approx(2.0) and rows[0]["z_n"] == 12
    assert "z" not in rows[1] and "z" not in rows[2]                                      # <8 örnek / sayısal değil


# ----------------------------------------------------------------------------- kısmi kapatmada etiket kaybı

def test_partial_close_comment_overwrite_restores_strategy_tag():
    fx._TICKET_TAGS.clear()
    fx.restore_position_tags([{"ticket": 7, "strategy_tag": "RADAR 96"}, {"ticket": 8, "strategy_tag": "FRS -4"}])
    out = fx.restore_position_tags([{"ticket": 7, "strategy_tag": "Scalper Partial"}, {"ticket": 9, "strategy_tag": "Scalper Partial"}])
    assert out[0]["strategy_tag"] == "RADAR 96"                       # ezilen etiket geri yazıldı
    assert out[1]["strategy_tag"] == "Scalper Partial"                # bilinmeyen: değişmez
    assert 8 not in fx._TICKET_TAGS                                   # kapanan pozisyon temizlenir
    assert fx.restore_position_tags(None) is None


# ----------------------------------------------------------------------------- sohbette açık emir komutu

@pytest.mark.parametrize("text,sym,expect", [
    ("btc sell açamıyormusun pozıyon", "BTCUSD", "SELL"),
    ("BTC sell aç", "BTCUSD", "SELL"),
    ("altında buy açar mısın", "XAUUSD", "BUY"),
    ("eurusd short ac", "EURUSD", "SELL"),
])
def test_parse_open_request_accepts_explicit_commands(text, sym, expect):
    assert ot.parse_open_request(text, [sym]) == {"symbol": sym, "direction": expect}


@pytest.mark.parametrize("text", [
    "neden btc sell açmıyor",                 # soru/olumsuz
    "btc sell açmak mantıklı mı",             # tavsiye sorusu
    "btc sell açma",                          # açma = yapma
    "23:50'de btc sell aç",                   # saat → zamanlanmış iş
    "btc aç",                                 # yön yok
    "btc buy sell aç",                        # çelişkili yön
])
def test_parse_open_request_rejects_questions_and_ambiguity(text):
    assert ot.parse_open_request(text, ["BTCUSD"]) is None
    assert ot.parse_open_request("btc eth sell aç", ["BTCUSD", "ETHUSD"]) is None      # tek sembol şart


def test_explicit_plan_uses_lower_score_and_skips_tradingview_gate():
    weak = analysis(score=-2.0, bias="SELL", levels={"resistances": [], "supports": []})
    assert not ot.plan_trade(weak, SCAN, None, 0.1)["ok"]                                   # normal kapı: 2.0 < 2.5
    v = ot.plan_trade(weak, None, None, 0.1, explicit=True)
    assert v["ok"] and v["plan"]["direction"] == "SELL" and "Kullanıcı komutuyla" in v["plan"]["note"]
    assert not ot.plan_trade(analysis(score=1.0, bias="SELL"), None, None, 0.1, explicit=True)["ok"]   # 1.0 < 1.5


def test_open_requested_blocks_opposite_direction_and_opens_matching(monkeypatch):
    seen = {}

    def fake_open(sym, direction, sl, tp, atr, score, note, lots_mult=1.0):
        seen.update(sym=sym, direction=direction)
        return {"ok": True, "lots": 0.01, "risk_usd": 2.0, "cmd_id": "CMD-9"}

    monkeypatch.setattr(fx, "open_scan_position", fake_open)
    monkeypatch.setattr(fx, "scan_lot_estimate", lambda *a: None)
    ot._last_open.clear()
    a = analysis(symbol="XAUUSD", score=-2.0, bias="SELL", levels={"resistances": [], "supports": []})
    wrong = asyncio.run(ot.open_requested(a, "BUY", None))
    assert not wrong["opened"] and "ters yönde" in wrong["skipped"][0]["reason"] and not seen
    ok = asyncio.run(ot.open_requested(a, "SELL", None))
    assert len(ok["opened"]) == 1 and seen == {"sym": "XAUUSD", "direction": "SELL"}


# ----------------------------------------------------------------------------- hafta sonu: yalnız kripto evreni

def utc(y, mo, d, h, mi=0):
    from datetime import datetime, timezone
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def test_weekend_window_boundaries():
    assert not ot.is_weekend(utc(2026, 10, 30, 21, 59))        # Cuma 21:59 UTC: piyasa açık
    assert ot.is_weekend(utc(2026, 10, 30, 22, 0))             # Cuma 22:00 UTC: kapandı
    assert ot.is_weekend(utc(2026, 10, 31, 12))                # Cumartesi
    assert ot.is_weekend(utc(2026, 11, 1, 21, 59))             # Pazar 21:59 UTC: hâlâ kapalı
    assert not ot.is_weekend(utc(2026, 11, 1, 22, 0))          # Pazar 22:00 UTC: açıldı
    assert not ot.is_weekend(utc(2026, 11, 2, 10))             # Pazartesi


def test_weekend_universe_is_crypto_only_and_deeper():
    wk, wd = utc(2026, 10, 31, 12), utc(2026, 11, 2, 10)
    assert ot.universe_now(wk) == ot.WEEKEND_UNIVERSE and all(s.endswith("USD") and not s.startswith(("EUR", "GBP", "XAU", "US")) for s in ot.WEEKEND_UNIVERSE)
    assert "BTCUSD" in ot.WEEKEND_UNIVERSE and "ETHUSD" in ot.WEEKEND_UNIVERSE
    assert ot.universe_now(wd) == ot.OPPORTUNITY_UNIVERSE and "XAUUSD" in ot.OPPORTUNITY_UNIVERSE
    assert ot.deep_top_now(wk) > ot.deep_top_now(wd)


def test_weekend_universe_is_researchable():
    from app import forex_research as fr
    for s in ot.WEEKEND_UNIVERSE:
        assert s in fr._TV and s in fr.YAHOO and s in fr.SYMBOL_NAME and fr._asset_class(s) == "crypto"
