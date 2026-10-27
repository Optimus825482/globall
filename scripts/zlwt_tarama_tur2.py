#!/usr/bin/env python3
"""Tur 2 (ilk tur sonucuna bakildiktan SONRA tanimlandi; secim yanliligi tasir).

Ilk turda en az zarar eden aile: ust dilim ZL yonu + WaveTrend bolge / geri
cekilme kesisimi. Ilk turda isabet ~%25 ve 2R hedef; stop 1.2 ATR dar.
Bu tur: stop 2.0 ATR, hedef 1.5R, dilim 15m/30m/1h, 3 kural, 2 cikis = 18 config.
Baska hicbir sey degismedi. Sonuc zlwt_tarama_tur2.json.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zlwt_tarama_xau_btc as m  # noqa: E402

m.STOP_ATR = 2.0
m.RR_FIXED = 1.5
m.RR_CAP = 3.0
m.ENTRY_TFS = ("15m", "30m", "1h")
m.RULES = ("ust1_zl_wt53", "ust1_zl_wt_geri", "ust12_wt_geri")
m.OUT_NAME = "zlwt_tarama_tur2.json"
m.main()
