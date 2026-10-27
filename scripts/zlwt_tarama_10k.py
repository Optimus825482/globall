#!/usr/bin/env python3
"""Ayni kural seti, 10.000 USD haftalik kasa (hedef 20.000). Risk yine %2.

Amac: 1000 USD kasada 0.01 lot tabani altinda 30m/1h stoplarini engelliyordu.
Tur 1 (96 config) ve tur 2 (18 config, genis stop) ayni kasayla tekrar kosulur.
Ciktilar: zlwt_tarama_10k.json, zlwt_tarama_tur2_10k.json
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xau_week_double_8w as wk  # noqa: E402
import zlwt_tarama_xau_btc as m  # noqa: E402

wk.START_CASH = 10_000.0
wk.TARGET = 20_000.0

which = sys.argv[1] if len(sys.argv) > 1 else "tur1"
if which == "tur1":
    m.OUT_NAME = "zlwt_tarama_10k.json"
else:
    m.STOP_ATR = 2.0
    m.RR_FIXED = 1.5
    m.RR_CAP = 3.0
    m.ENTRY_TFS = ("15m", "30m", "1h")
    m.RULES = ("ust1_zl_wt53", "ust1_zl_wt_geri", "ust12_wt_geri")
    m.OUT_NAME = "zlwt_tarama_tur2_10k.json"
m.main()
