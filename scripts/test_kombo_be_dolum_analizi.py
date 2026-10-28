"""kombo_be_dolum_analizi: bosluk (kotumser dolum) aritmetigi.

  python -m unittest scripts.test_kombo_be_dolum_analizi
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kombo_be_dolum_analizi as bd  # noqa: E402


class BoslukFarkTest(unittest.TestCase):
    def test_buy_acilis_stopun_altinda(self):
        # XAU: pip 0.1, 0.30 lot, pip_val 1.0 -> 20 pip x 0.30 = -6 USD
        self.assertEqual(bd.bosluk_fark("BUY", 4000.0, 4002.0, 0.1, 0.30, 1.0), (-20.0, -6.0))

    def test_buy_acilis_stopun_ustunde_sifir(self):
        self.assertEqual(bd.bosluk_fark("BUY", 4002.5, 4002.0, 0.1, 0.30, 1.0), (0.0, 0.0))
        self.assertEqual(bd.bosluk_fark("BUY", 4002.0, 4002.0, 0.1, 0.30, 1.0), (0.0, 0.0))  # esit: bosluk yok

    def test_sell_acilis_stopun_ustunde(self):
        # EURJPY: pip 0.01, 0.50 lot, pip_val 6.5 -> 5 pip x 0.5 x 6.5 = -16.25 USD
        self.assertEqual(bd.bosluk_fark("SELL", 175.05, 175.00, 0.01, 0.50, 6.5), (-5.0, -16.25))

    def test_sell_acilis_stopun_altinda_sifir(self):
        self.assertEqual(bd.bosluk_fark("SELL", 174.95, 175.00, 0.01, 0.50, 6.5), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
