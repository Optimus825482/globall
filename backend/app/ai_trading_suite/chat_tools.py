"""
LLM Chat Tools for Scalper Global Agent AI Trading Suite.
Provides callable tool interfaces for the chat model to query:
- 10-Model AI Trading Suite Full Evaluation
- Hedge Fund Investment Council (Soros, Simons, Dalio)
- TradingAgents & Freqtrade Risk Chief Veto
- Bull vs Bear Debate Protocol
- Riskfolio-Lib HRP Portfolio & CVaR Optimizer
- FreqAI Dissimilarity & Concept Drift Detector
- Liquidation Heatmap & Stop-Hunt Radar
- FinCon Episodic Negative Memory & Trap Shield
- VectorBT Pro Rapid Parameter Optimizer
"""
import time
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from app.ai_trading_suite import (
    AITradingSuiteOrchestrator,
    UnifiedEvaluationRequest,
    IndicatorEvaluation,
    MacroEvent,
    TradeContractProposal,
    RiskChiefVetoEngine,
    HedgeFundCouncil,
    AssetClass,
    TradeAction,
    evaluate_bull_bear_debate,
    evaluate_riskfolio_allocation,
    evaluate_freqai_drift,
    evaluate_liquidation_radar,
    evaluate_trap_shield,
    record_negative_episode,
    evaluate_vectorbt_optimal_params,
    evaluate_ofi_scalper,
    evaluate_stat_arb_pairs,
    evaluate_vwap_scalper,
    evaluate_ttm_squeeze,
    evaluate_avellaneda_stoikov,
    evaluate_ppo_adaptive_policy,
    evaluate_wyckoff_vsa,
    evaluate_momentum_rotation,
    evaluate_smart_rebalance,
    evaluate_infinity_grid,
    evaluate_obv_cmf_inflow,
    evaluate_volume_breakout,
)

orchestrator = AITradingSuiteOrchestrator()
council = HedgeFundCouncil()
risk_chief = RiskChiefVetoEngine()


LLM_AI_TRADING_SUITE_EVALUATE_TOOL = {
    "type": "function",
    "function": {
        "name": "run_ai_trading_suite_evaluation",
        "description": (
            "10 popüler açık kaynaklı AI ticaret mimarisini (OctoBot, FinRobot, Vibe-Trading, FinRL, "
            "AI-Trader, Hummingbot, NautilusTrader, Freqtrade, ai-hedge-fund, TradingAgents) "
            "verilen Spot (Binance) veya Forex/XAU (MT5) sembolü için tek seferde çalıştırır. "
            "Pydantic kontratı, Risk Chief vetosu, makro analizi, Soros/Simons konsey kararını ve "
            "gerçekçi simülasyonu döndürür. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Analiz edilecek sembol (ör. BTCUSDT, ETHUSDT, XAUUSD, EURUSD)"
                },
                "asset_type": {
                    "type": "string",
                    "enum": ["SPOT", "FOREX"],
                    "description": "Varlık sınıfı. Boş bırakılırsa sembolden otomatik algılanır."
                },
                "proposed_action": {
                    "type": "string",
                    "enum": ["BUY", "SELL", "WAIT"],
                    "description": "Değerlendirilecek olası işlem yönü (varsayılan: BUY)"
                }
            },
            "required": ["symbol"]
        }
    }
}

LLM_HEDGE_FUND_COUNCIL_TOOL = {
    "type": "function",
    "function": {
        "name": "get_hedge_fund_council_deliberation",
        "description": (
            "George Soros (Makro/Refleksivite), Jim Simons (Kantitatif z-score ve ortalamaya dönüş) "
            "ve Ray Dalio (Risk Paritesi/Sermaye Koruma) yatırım konseyinin sembol için oylama ve "
            "ortak kararını getirir. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "asset_type": {"type": "string", "enum": ["SPOT", "FOREX"]}
            },
            "required": ["symbol"]
        }
    }
}

LLM_RISK_CHIEF_VETO_TOOL = {
    "type": "function",
    "function": {
        "name": "check_risk_chief_veto",
        "description": (
            "TradingAgents ve Freqtrade Risk Masası kurallarını denetler: Günlük drawdown, "
            "haber saatleri (FOMC/NFP/CPI), spread genişliği ve R:R oranına göre proposed işleme "
            "onay veya VETO verir. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "asset_type": {"type": "string", "enum": ["SPOT", "FOREX"]},
                "action": {"type": "string", "enum": ["BUY", "SELL"]},
                "current_price": {"type": "number"},
                "stop_loss": {"type": "number"},
                "take_profit": {"type": "number"}
            },
            "required": ["symbol", "action"]
        }
    }
}

LLM_BULL_BEAR_DEBATE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_bull_bear_debate",
        "description": (
            "virattt/ai-hedge-fund ve TradingAgents protokolü: Boğa Araştırmacısı ile Ayı Sorgulayıcısı "
            "arasında çoklu-ajan çapraz sorgu münazarası yürütür. Arbitratör hakem kararını, zıt tezleri, "
            "net ikna puanını ve pozisyon iskonto katsayısını döner. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol (ör. BTCUSDT, GTRY)"},
                "price": {"type": "number", "description": "Mevcut fiyat (isteğe bağlı)"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_RISKFOLIO_ALLOCATION_TOOL = {
    "type": "function",
    "function": {
        "name": "get_riskfolio_allocation",
        "description": (
            "Riskfolio-Lib tabanlı Hierarchical Risk Parity (HRP) ve CVaR (Expected Shortfall %95) "
            "kuyruk riski portföy optimizasyonu. Verilen sembol listesi için ters varyanslı sermaye "
            "ağırlıklarını ve risk dağılımını hesaplar. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {"type": "string", "description": "Virgülle ayrılmış sembol listesi (ör. BTCTRY,ETHTRY,SOLTRY)"},
                "capital": {"type": "number", "description": "Toplam portföy sermayesi (TRY)"}
            },
            "required": ["symbols"]
        }
    }
}

LLM_FREQAI_DRIFT_TOOL = {
    "type": "function",
    "function": {
        "name": "get_freqai_drift",
        "description": (
            "FreqAI tabanlı Dissimilarity Index (DI) ve konsept kayması (concept drift) tespiti. "
            "Piyasa anomalisini ve model güvenilirlik sınırını Mahalanobis/Z-skor metrikleriyle denetler. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol (ör. BTCUSDT)"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_LIQUIDATION_RADAR_TOOL = {
    "type": "function",
    "function": {
        "name": "get_liquidation_radar",
        "description": (
            "Likidasyon Haritası ve Kurumsal Stop Avı Radarı (Open-Perp-Tracker). "
            "25x, 50x, 100x kaldıraçlı likidasyon yoğunlaşmalarını ve piyasa yapıcı mıknatıs hedeflerini modeller. Salt okunur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_FINCON_TRAP_SHIELD_TOOL = {
    "type": "function",
    "function": {
        "name": "get_fincon_trap_shield",
        "description": (
            "FinCon Episodik Negatif Hafıza ve Tuzak Kalkanı. Geçmişte stop-out veya boğa tuzağı (bull trap) "
            "yaratan formasyonlarla vektörel kosinüs benzerliği kurar ve benzer kayıp paternlerinde girişe koruyucu VETO verir."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "rsi": {"type": "number", "description": "RSI değeri"},
                "volume_ratio": {"type": "number", "description": "Hacim oranı"},
                "adx": {"type": "number", "description": "ADX trend gücü"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_VECTORBT_OPTIMAL_PARAMS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_vectorbt_optimal_params",
        "description": (
            "VectorBT Pro hızlı parametre simülasyonu ve optimizasyonu. Sembolün son barları üzerinde "
            "vektörize grid taraması yaparak en yüksek Sharpe ve kâr faktörüne sahip TP/SL ve RSI parametrelerini bulur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_OFI_SCALPER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_ofi_scalper",
        "description": (
            "Order Flow Imbalance (OFI) mikroyapı scalper analizi. Tahtanın ilk kademelerindeki alıcı/satıcı "
            "hacim dengesizliğini ölçerek 1m-3m mikro-scalp giriş ve çıkış hedefleri üretir."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_STAT_ARB_PAIRS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_stat_arb_pairs",
        "description": (
            "İstatistiki Arbitraj ve Eşbütünleşme (Cointegration) Pairs Scalper. İki korele parite arasındaki "
            "(ör. BTCTRY/ETHTRY, SOLTRY/AVAXTRY, XAUUSD/XAGUSD) spread Z-skorunu ve ortalamaya dönüş sinyalini hesaplar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "leg_a": {"type": "string", "description": "Birinci bacak sembolü (ör. BTCTRY)"},
                "leg_b": {"type": "string", "description": "İkinci bacak sembolü (ör. ETHTRY)"}
            },
            "required": ["leg_a", "leg_b"]
        }
    }
}

LLM_VWAP_SCALPER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_vwap_scalper",
        "description": (
            "Rolling VWAP ve +/- 1sigma, 2sigma, 3sigma standart sapma bantları scalpu. Fiyatın aşırı satım veya "
            "aşırı alım bantlarına çarpmasıyla merkeze dönüş (mean-reversion) işlemlerini modeller."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_TTM_SQUEEZE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_ttm_squeeze",
        "description": (
            "John Carter TTM Squeeze volatilite sıkışması ve patlama momentum dedektörü. Bollinger Bantlarının "
            "Keltner Kanalı içine girmesiyle oluşan enerji sıkışmasını ve yönlü patlamaları yakalar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_AVELLANEDA_STOIKOV_TOOL = {
    "type": "function",
    "function": {
        "name": "get_avellaneda_stoikov",
        "description": (
            "Avellaneda-Stoikov Pure Market Making (PMM) modeli. Envanter riskine göre düzeltilmiş rezervasyon fiyatı "
            "ve optimal çift taraflı (bid/ask) spread tekliflerini hesaplar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "mid_price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_PPO_POLICY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_ppo_policy",
        "description": (
            "PPO Reinforcement Learning uyarlamalı dinamik politika motoru. Mevcut rejim, volatilite, win-rate ve "
            "drawdown durumuna göre dinamik TP/SL ve sermaye çarpanı optimize eder."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "win_rate": {"type": "number", "description": "Son işlem kazanma oranı %"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_WYCKOFF_VSA_TOOL = {
    "type": "function",
    "function": {
        "name": "get_wyckoff_vsa",
        "description": (
            "Wyckoff Akümülasyonu ve Hacim Yayılım Analizi (VSA). Akıllı paranın (Smart Money) gizli mal toplama "
            "(Absorption), durdurucu hacim (Stopping Volume) ve silkeleme (Spring) formasyonlarını tespit eder."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol (ör. BTCTRY, SOLTRY)"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_MOMENTUM_ROTATION_TOOL = {
    "type": "function",
    "function": {
        "name": "get_momentum_rotation",
        "description": (
            "Çapraz-Kesit Momentum ve Lider Coin Rotasyon motoru. Binance Spot evrenini BTC'ye karşı Göreceli Güç (RS) "
            "ve Rate of Change (ROC) skoruna göre sıralayarak en güçlü lider coinleri seçer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {"type": "string", "description": "Virgülle ayrılmış taranacak semboller listesi"}
            },
            "required": []
        }
    }
}

LLM_SMART_REBALANCE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_smart_rebalance",
        "description": (
            "Akıllı Eşikli Portföy Dengeleme (Smart Rebalancing & Drift Bands). Spot varlıklarda tepede kâr realize edip "
            "dipteki varlıklara veya nakite aktarma kararı üretir."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "drift_tolerance": {"type": "number", "description": "Sapma toleransı yüzdesi (varsayılan: 5.0)"}
            },
            "required": []
        }
    }
}

LLM_INFINITY_GRID_TOOL = {
    "type": "function",
    "function": {
        "name": "get_infinity_grid",
        "description": (
            "Dinamik ATR Sonsuzluk Izgarası (Infinity Grid). Yatay ve dalgalı piyasada stop olmadan kademeli al-sat "
            "seviyeleri oluşturarak sürekli micro-kâr toplar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"},
                "capital": {"type": "number", "description": "Toplam ızgara sermayesi (TRY)"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_OBV_CMF_INFLOW_TOOL = {
    "type": "function",
    "function": {
        "name": "get_obv_cmf_inflow",
        "description": (
            "OBV ve Chaikin Money Flow (CMF) akıllı para akışı dedektörü. Fiyat henüz yükselmeden önceki "
            "kurumsal gizli spot toplama (Bullish Inflow Divergence) uyumsuzluğunu yakalar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

LLM_VOLUME_BREAKOUT_TOOL = {
    "type": "function",
    "function": {
        "name": "get_volume_breakout",
        "description": (
            "Ön-Patlama Hacim Anomalisi ve Konsolidasyon Kutusu Kırılım Radarı. Sıkışan fiyat kutusundan 3x hacim "
            "patlamasıyla çıkan spot kırılımları ilk mumda yakalar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Analiz edilecek sembol"},
                "price": {"type": "number", "description": "Mevcut fiyat"}
            },
            "required": ["symbol"]
        }
    }
}

AI_TRADING_SUITE_TOOLS = [
    LLM_AI_TRADING_SUITE_EVALUATE_TOOL,
    LLM_HEDGE_FUND_COUNCIL_TOOL,
    LLM_RISK_CHIEF_VETO_TOOL,
    LLM_BULL_BEAR_DEBATE_TOOL,
    LLM_RISKFOLIO_ALLOCATION_TOOL,
    LLM_FREQAI_DRIFT_TOOL,
    LLM_LIQUIDATION_RADAR_TOOL,
    LLM_FINCON_TRAP_SHIELD_TOOL,
    LLM_VECTORBT_OPTIMAL_PARAMS_TOOL,
    LLM_OFI_SCALPER_TOOL,
    LLM_STAT_ARB_PAIRS_TOOL,
    LLM_VWAP_SCALPER_TOOL,
    LLM_TTM_SQUEEZE_TOOL,
    LLM_AVELLANEDA_STOIKOV_TOOL,
    LLM_PPO_POLICY_TOOL,
    LLM_WYCKOFF_VSA_TOOL,
    LLM_MOMENTUM_ROTATION_TOOL,
    LLM_SMART_REBALANCE_TOOL,
    LLM_INFINITY_GRID_TOOL,
    LLM_OBV_CMF_INFLOW_TOOL,
    LLM_VOLUME_BREAKOUT_TOOL,
]


def _detect_asset_type(symbol: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.upper()
    sym = symbol.replace("_", "").upper()
    fx_symbols = {"XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD", "USTEC", "US30"}
    if sym in fx_symbols:
        return "FOREX"
    if any(sym.startswith(c) or sym.endswith(c) for c in ["EUR", "GBP", "JPY", "CHF"]) and not sym.endswith("TRY"):
        return "FOREX"
    return "SPOT"


def _real_inputs_from_analysis(a: dict) -> Optional[dict]:
    """`forex_research.analyze_symbol` çıktısını 21-AI motorunun girdilerine çevirir.

    NEDEN (2026-11-12): bu araç motora SABİT girdiler veriyordu — 4 gösterge hep
    +0.75/+0.70/+0.85/+0.60 (boğa), `rsi_value=56`, `price_change_pct=1.4`,
    `volume_ratio=1.9`, `quant_z_score=-0.2`, uydurma emir defteri ve
    `proposed_action` varsayılanı **BUY**. Sonuç: "21 AI Konsensüsü" her sembolde
    aynı sayıları (Qlib 65,7 · R:R 1,57 · Kelly 863,06) veriyordu; sembole
    bakmıyordu. Artık gerçek analizden türetiliyor; veri yoksa konsensüs ÜRETİLMEZ.
    """
    frames = (a or {}).get("frames") or {}
    f1 = frames.get("1h") or frames.get("4h")
    if not f1:
        return None
    price = float(a.get("price") or f1.get("price") or 0.0)
    atr = float(f1.get("atr") or 0.0) or max(price * 0.002, 1e-9)
    ind1 = ((a.get("indicators") or {}).get("1h")) or {}

    def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, v))

    inds: List[IndicatorEvaluation] = []
    st = (ind1.get("supertrend") or {}).get("yon")
    if st:
        inds.append(IndicatorEvaluation(indicator_name="Supertrend",
                                        signal=1.0 if st in ("yukari", "up") else -1.0, weight=1.2))
    sr = ind1.get("stoch_rsi") or {}
    if sr.get("k") is not None:
        # aşırı alım → aşağı baskı (-), aşırı satım → yukarı (+)
        inds.append(IndicatorEvaluation(indicator_name="StochRSI",
                                        signal=_clamp((50.0 - float(sr["k"])) / 50.0), weight=0.8))
    if ind1.get("cci20") is not None:
        inds.append(IndicatorEvaluation(indicator_name="CCI20",
                                        signal=_clamp(float(ind1["cci20"]) / 200.0), weight=0.7))
    if f1.get("bb_pos") is not None:
        inds.append(IndicatorEvaluation(indicator_name="Bollinger",
                                        signal=_clamp((0.5 - float(f1["bb_pos"])) * 2.0), weight=0.7))
    mh = f1.get("macd_hist")
    if mh is not None:
        inds.append(IndicatorEvaluation(indicator_name="MACD_hist",
                                        signal=1.0 if float(mh) > 0 else -1.0, weight=1.0))
    e20, e50 = f1.get("ema20"), f1.get("ema50")
    if e20 and e50:
        inds.append(IndicatorEvaluation(indicator_name="EMA20_50",
                                        signal=1.0 if float(e20) > float(e50) else -1.0, weight=1.1))

    # Fiyat değişimi: 1h mumlarından son 20 bar
    pct = 0.0
    candles = ((a.get("candles") or {}).get("1h")) or []
    try:
        if len(candles) >= 20 and float(candles[-20]["close"]) > 0:
            pct = (float(candles[-1]["close"]) / float(candles[-20]["close"]) - 1.0) * 100.0
    except Exception:  # noqa: BLE001
        pct = 0.0

    bias = str(a.get("bias") or "BEKLE").upper()
    return {
        "price": price,
        "atr": atr,
        "indicators": inds,
        "rsi_value": float(f1.get("rsi") or 50.0),
        "trend_slope": ((float(e20) - float(e50)) / float(e50)) if (e20 and e50) else 0.0,
        "quant_z_score": _clamp((price - float(e20)) / atr, -3.0, 3.0) if e20 else 0.0,
        "price_change_pct": round(pct, 3),
        # Hacim/sosyal veri FOREX'te yok: uydurmak yerine nötr + not.
        "volume_ratio": 1.0,
        "social_buzz": 0.5,
        "proposed_action": bias if bias in ("BUY", "SELL") else "WAIT",
        "notes": ["hacim oranı verisi yok (nötr 1,0)", "sosyal buzz verisi yok (nötr 0,5)"],
        "indicators_count": len(inds),
    }


async def execute_ai_trading_suite_evaluation(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "").replace("_", "").upper()
    if not raw_sym:
        return {"ok": False, "reason": "sembol verilmedi"}
    asset_type = _detect_asset_type(raw_sym, args.get("asset_type"))

    real = None
    if asset_type == "FOREX":
        try:
            from app import forex_research
            a = await forex_research.run_blocking(forex_research.analyze_symbol, raw_sym)
            if a and a.get("ok"):
                real = _real_inputs_from_analysis(a)
        except Exception:  # noqa: BLE001
            real = None
    if not real or not real.get("indicators"):
        # FAIL-CLOSED: sabit girdilerle "konsensüs" üretmek sahtekârlıktır.
        return {"ok": False,
                "reason": (f"{raw_sym} için gerçek gösterge verisi alınamadı — "
                           "21-AI konsensüsü ÜRETİLMEDİ (sabit girdiyle onay verilmez)")}

    macro_events: List[MacroEvent] = []
    try:
        from app.forex_news import get_economic_calendar
        events = await get_economic_calendar(limit=5)
        for ev in (events or []):
            macro_events.append(MacroEvent(
                event_name=ev.get("event") or "Economic Event",
                currency=ev.get("currency") or "USD",
                impact=ev.get("impact") or "MEDIUM",
                sentiment_score=0.0,
                minutes_until_event=ev.get("minutes_until")))
    except Exception:  # noqa: BLE001
        pass

    # OpenBB makro rejimi DXY günlük değişimine bakıyor; geçilmezse 0.0 kalıp
    # HER sembolde "NEUTRAL" üretiyordu (2026-11-12). Küresel nabızdan alınır.
    dxy_chg = 0.0
    try:
        from app import market_pulse
        _mp = market_pulse.summary() or {}
        _dxy = ((_mp.get("assets") or {}).get("dxy") or {})
        if _dxy.get("available") and _dxy.get("chg_pct") is not None:
            dxy_chg = float(_dxy["chg_pct"])
    except Exception:  # noqa: BLE001
        dxy_chg = 0.0

    req = UnifiedEvaluationRequest(
        symbol=raw_sym,
        asset_type=asset_type,
        dxy_change_pct=dxy_chg,
        current_price=float(real["price"]),
        atr=float(real["atr"]),
        indicators=real["indicators"],
        macro_events=macro_events,
        # L2 derinlik YOK: uydurma emir defteri göndermek yerine boş bırakılır.
        orderbook_bids=[],
        orderbook_asks=[],
        price_change_pct=float(real["price_change_pct"]),
        volume_ratio=float(real["volume_ratio"]),
        social_buzz=float(real["social_buzz"]),
        quant_z_score=float(real["quant_z_score"]),
        rsi_value=float(real["rsi_value"]),
        trend_slope=float(real["trend_slope"]),
        proposed_action=str(real["proposed_action"]),
        daily_drawdown_pct=float(args.get("daily_drawdown_pct") or 0.0),
        account_margin_used_pct=float(args.get("account_margin_used_pct") or 0.0),
        spread_pips_or_pct=float(args.get("spread") or 1.2),
    )

    resp = orchestrator.evaluate(req)
    data = asdict(resp)
    data["ok"] = True
    data["inputs_provenance"] = {
        "indicators": real["indicators_count"],
        "rsi": round(real["rsi_value"], 1),
        "proposed_action": real["proposed_action"],
        "notes": real["notes"],
    }
    return data


async def execute_hedge_fund_council(args: dict) -> dict:
    """Hedge Fund Konseyi — girdiler GERÇEK analizden (2026-11-12).

    Önceki hâli sabitti: macro_score=0.45, quant_z=-0.3, rsi=55, slope=0.01 →
    her sembolde aynı oylar (Soros NEUTRAL · Simons BULLISH · Dalio NEUTRAL).
    Veri yoksa konsey çağrılmaz (fail-closed).
    """
    raw_sym = str(args.get("symbol") or "").replace("_", "").upper()
    if not raw_sym:
        return {"ok": False, "reason": "sembol verilmedi"}
    asset_type = _detect_asset_type(raw_sym, args.get("asset_type"))

    real = None
    if asset_type == "FOREX":
        try:
            from app import forex_research
            a = await forex_research.run_blocking(forex_research.analyze_symbol, raw_sym)
            if a and a.get("ok"):
                real = _real_inputs_from_analysis(a)
                real["_score"] = float((a.get("score") or 0.0))
                # Oynaklık rejimi: GÜÇLÜ TREND ≠ PANİK. ADX trend gücüdür; rejim için
                # fiyat değişimi ve ATR/price kullanılır (ADX 47 olan sakin trend
                # "EXTREME" sayılıp Dalio'yu çekimser bırakıyordu).
                atr_pct = (float(real["atr"]) / float(real["price"]) * 100.0) if real["price"] else 0.0
                real["vol_regime"] = ("EXTREME"
                                      if abs(float(real["price_change_pct"])) > 5.0 or atr_pct > 1.5
                                      else "NORMAL")
        except Exception:  # noqa: BLE001
            real = None
    if not real or not real.get("indicators"):
        return {"ok": False,
                "reason": (f"{raw_sym} için gerçek veri alınamadı — konsey çağrılmadı "
                           "(sabit girdiyle oy üretilmez)")}

    res = council.deliberate(
        symbol=raw_sym,
        asset_type=asset_type,
        macro_score=max(-1.0, min(1.0, float(real["_score"]) / 6.0)),  # teknik skor -6..+6 → -1..+1
        quant_z_score=float(real["quant_z_score"]),
        volatility_regime=str(real.get("vol_regime") or "NORMAL"),
        rsi_value=float(real["rsi_value"]),
        trend_slope=float(real["trend_slope"]),
    )
    data = asdict(res)
    data["ok"] = True
    data["inputs_provenance"] = {"rsi": round(real["rsi_value"], 1),
                                 "quant_z": round(float(real["quant_z_score"]), 2),
                                 "macro_score": round(max(-1.0, min(1.0, real["_score"] / 6.0)), 2),
                                 "vol_regime": real.get("vol_regime")}
    return data


async def execute_risk_chief_veto(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    asset_type = _detect_asset_type(raw_sym, args.get("asset_type"))
    action_str = str(args.get("action") or "BUY").upper()
    action = TradeAction.BUY if action_str == "BUY" else TradeAction.SELL

    curr_p = float(args.get("current_price") or 68000.0)
    sl = float(args.get("stop_loss") or (curr_p * 0.985 if action == TradeAction.BUY else curr_p * 1.015))
    tp = float(args.get("take_profit") or (curr_p * 1.03 if action == TradeAction.BUY else curr_p * 0.97))

    risk_dist = max(0.0001, abs(curr_p - sl))
    reward_dist = max(0.0001, abs(tp - curr_p))
    rr = round(reward_dist / risk_dist, 2)

    proposal = TradeContractProposal(
        symbol=raw_sym,
        asset_class=AssetClass.SPOT if asset_type == "SPOT" else AssetClass.FOREX,
        action=action,
        confidence=0.85,
        current_price=curr_p,
        entry_target=curr_p,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=tp * 1.02 if action == TradeAction.BUY else tp * 0.98,
        risk_reward_ratio=rr,
        proposed_lot_or_qty=1.0,
        account_margin_used_pct=4.0,
        spread_pips_or_pct=0.0003 if asset_type == "SPOT" else 1.2,
        thesis_summary="Desk proposed trade setup via LLM chat review"
    )

    verdict = risk_chief.review_contract(proposal)
    data = verdict.model_dump()
    data["symbol"] = raw_sym
    data["asset_type"] = asset_type
    data["ok"] = True
    return data


async def execute_bull_bear_debate(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    if px <= 0:
        try:
            from app import analyzer
            c = analyzer.candles.get(raw_sym, [])
            if c:
                px = float(c[-1].get("close") or 100.0)
        except Exception:
            pass
    if px <= 0:
        px = 100.0
    res = evaluate_bull_bear_debate(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_riskfolio_allocation(args: dict) -> dict:
    syms_raw = str(args.get("symbols") or "BTCTRY,ETHTRY,SOLTRY")
    sym_list = [s.strip().upper() for s in syms_raw.split(",") if s.strip()]
    cap = float(args.get("capital") or 10000.0)
    res = evaluate_riskfolio_allocation(symbols=sym_list, total_capital=cap)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_freqai_drift(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    res = evaluate_freqai_drift(symbol=raw_sym)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_liquidation_radar(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    if px <= 0:
        try:
            from app import analyzer
            c = analyzer.candles.get(raw_sym, [])
            if c:
                px = float(c[-1].get("close") or 100.0)
        except Exception:
            pass
    if px <= 0:
        px = 100.0
    res = evaluate_liquidation_radar(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_fincon_trap_shield(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    rsi = float(args.get("rsi") or 50.0)
    vol = float(args.get("volume_ratio") or 1.0)
    adx = float(args.get("adx") or 20.0)
    res = evaluate_trap_shield(symbol=raw_sym, indicators={"rsi": rsi, "volume_ratio": vol, "adx": adx})
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_vectorbt_optimal_params(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    res = evaluate_vectorbt_optimal_params(symbol=raw_sym)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_ofi_scalper(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_ofi_scalper(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_stat_arb_pairs(args: dict) -> dict:
    leg_a = str(args.get("leg_a") or "BTCTRY").replace("_", "").upper()
    leg_b = str(args.get("leg_b") or "ETHTRY").replace("_", "").upper()
    pa = float(args.get("price_a") or 0.0)
    pb = float(args.get("price_b") or 0.0)
    res = evaluate_stat_arb_pairs(leg_a=leg_a, leg_b=leg_b, leg_a_price=pa, leg_b_price=pb)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_vwap_scalper(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_vwap_scalper(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_ttm_squeeze(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_ttm_squeeze(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_avellaneda_stoikov(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    mid_p = float(args.get("mid_price") or args.get("price") or 0.0)
    inv_q = float(args.get("inventory_qty") or 0.0)
    res = evaluate_avellaneda_stoikov(symbol=raw_sym, mid_price=mid_p, current_inventory_qty=inv_q)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_ppo_policy(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    wr = float(args.get("win_rate") or 62.0)
    dd = float(args.get("drawdown") or 0.5)
    atr = float(args.get("volatility_atr") or 1.4)
    res = evaluate_ppo_adaptive_policy(symbol=raw_sym, recent_win_rate_pct=wr, daily_drawdown_pct=dd, volatility_atr_pct=atr)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_wyckoff_vsa(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_wyckoff_vsa(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_momentum_rotation(args: dict) -> dict:
    syms_raw = str(args.get("symbols") or "")
    sym_list = [s.strip().upper() for s in syms_raw.split(",") if s.strip()] if syms_raw else None
    res = evaluate_momentum_rotation(universe_symbols=sym_list)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_smart_rebalance(args: dict) -> dict:
    tol = float(args.get("drift_tolerance") or 5.0)
    res = evaluate_smart_rebalance(drift_tolerance_pct=tol)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_infinity_grid(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    cap = float(args.get("capital") or 5000.0)
    res = evaluate_infinity_grid(symbol=raw_sym, price=px, total_capital_try=cap)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_obv_cmf_inflow(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_obv_cmf_inflow(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data


async def execute_volume_breakout(args: dict) -> dict:
    raw_sym = str(args.get("symbol") or "BTCUSDT").replace("_", "").upper()
    px = float(args.get("price") or 0.0)
    res = evaluate_volume_breakout(symbol=raw_sym, price=px)
    data = res.model_dump()
    data["ok"] = True
    return data
