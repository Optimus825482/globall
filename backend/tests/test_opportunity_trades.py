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


def test_opposing_level_too_close_blocks_sell_uses_supports():
    assert "dirence" in plan(analysis(levels={"resistances": [{"price": 4003.0}], "supports": []}))["reason"]
    a = analysis(bias="SELL", score=-3.4, levels={"resistances": [], "supports": [{"price": 3997.0}]})
    v = ot.plan_trade(a, {**SCAN, "direction": "SELL", "average": -0.6}, None, 0.1)
    assert not v["ok"] and "desteğe" in v["reason"]


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

    def fake_open(sym, direction, sl, tp, atr, score, note):
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
