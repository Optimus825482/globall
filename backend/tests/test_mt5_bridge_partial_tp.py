"""Unit tests for Paket 3 in scripts/mt5_bridge.py:
- py_compile syntax check
- PARTIAL_TP_MAP dict structure & _ptp_already_done double-close guard
- Regime-adaptive trailing multiplier
- Close log transparency (reason)
"""

from pathlib import Path
import py_compile


REPO_ROOT = Path(__file__).resolve().parents[2]
MT5_BRIDGE_PATH = REPO_ROOT / "scripts" / "mt5_bridge.py"


def _is_partial_tp_done(partial_cfg) -> bool:
    return (isinstance(partial_cfg, dict) and bool(partial_cfg.get("done"))) or (partial_cfg is True)


def _can_run_block0_partial_tp(partial_cfg, partial_tp_enabled: bool = True) -> bool:
    return isinstance(partial_cfg, dict) and not partial_cfg.get("done") and bool(partial_tp_enabled)


def _compute_regime_trail_mult(pos_exits: dict | None) -> float:
    hurst_reg = str((pos_exits or {}).get("hurst_regime") or "UNKNOWN")
    hmm_reg = str((pos_exits or {}).get("hmm_regime") or "UNKNOWN")
    return 0.80 if (hurst_reg == "MEAN_REVERT" or hmm_reg == "LOW_VOL_RANGE") else 1.0


def test_mt5_bridge_py_compile():
    assert MT5_BRIDGE_PATH.exists(), f"Missing {MT5_BRIDGE_PATH}"
    compiled = py_compile.compile(str(MT5_BRIDGE_PATH), doraise=True)
    assert compiled is not None


def test_partial_tp_map_dict_structure_and_guard_in_source():
    src = MT5_BRIDGE_PATH.read_text(encoding="utf-8")
    assert 'PARTIAL_TP_MAP[ticket] = {"target_pips": round(1.5 * _sl0_ref, 1), "done": True}' in src
    assert "PARTIAL_TP_MAP[ticket] = True" not in src
    assert 'isinstance(partial_cfg, dict) and not partial_cfg.get("done")' in src
    assert "_ptp_already_done = (isinstance(partial_cfg, dict) and bool(partial_cfg.get(\"done\"))) or (partial_cfg is True)" in src
    assert "not _ptp_already_done" in src


def test_partial_tp_already_done_logic():
    # Not present -> neither block 0 runs nor is it marked done
    assert _is_partial_tp_done(None) is False
    assert _can_run_block0_partial_tp(None) is False

    # Open order dict with done=False -> block 0 can run, hybrid TP1 not yet done
    cfg_open = {"target_pips": 12.0, "done": False}
    assert _is_partial_tp_done(cfg_open) is False
    assert _can_run_block0_partial_tp(cfg_open, True) is True

    # Dict after Hybrid TP1 -> done=True, neither block 0 nor Hybrid TP1 double-closes
    cfg_done = {"target_pips": round(1.5 * 10.0, 1), "done": True}
    assert cfg_done == {"target_pips": 15.0, "done": True}
    assert _is_partial_tp_done(cfg_done) is True
    assert _can_run_block0_partial_tp(cfg_done, True) is False

    # Legacy bool True -> defensive check prevents AttributeError and prevents double-close
    assert _is_partial_tp_done(True) is True
    assert _can_run_block0_partial_tp(True, True) is False


def test_regime_adaptive_trailing_multiplier():
    src = MT5_BRIDGE_PATH.read_text(encoding="utf-8")
    assert '"hurst_regime": str(cmd.get("hurst_regime") or "UNKNOWN")' in src
    assert '"hmm_regime": str(cmd.get("hmm_regime") or "UNKNOWN")' in src
    assert "eff_chand_mult = chand_mult * _ratchet_mult * _vel_mult * _regime_trail_mult" in src

    assert _compute_regime_trail_mult(None) == 1.0
    assert _compute_regime_trail_mult({"hurst_regime": "TRENDING", "hmm_regime": "HIGH_VOL_TREND"}) == 1.0
    assert _compute_regime_trail_mult({"hurst_regime": "MEAN_REVERT", "hmm_regime": "UNKNOWN"}) == 0.80
    assert _compute_regime_trail_mult({"hurst_regime": "UNKNOWN", "hmm_regime": "LOW_VOL_RANGE"}) == 0.80
    assert _compute_regime_trail_mult({"hurst_regime": "MEAN_REVERT", "hmm_regime": "LOW_VOL_RANGE"}) == 0.80


def test_close_log_transparency_in_source():
    src = MT5_BRIDGE_PATH.read_text(encoding="utf-8")
    assert 'cmd.get("reason")' in src
    assert "_reason_suffix" in src
