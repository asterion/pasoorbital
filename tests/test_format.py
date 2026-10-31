from __future__ import annotations

import unittest

from desktop.pasoorbital_gui.format import fmt_dop, fmt_freq, short_address


class AddressFormatTests(unittest.TestCase):
    def test_short_address(self) -> None:
        self.assertEqual(
            short_address(
                "Santiago, Provincia de Santiago, Región Metropolitana de Santiago, "
                "8320000, Chile"
            ),
            "Santiago, Chile",
        )
        self.assertEqual(
            short_address("Plaza de Armas, Santiago, Chile"),
            "Plaza de Armas, Chile",
        )
        self.assertEqual(short_address("Madrid, Comunidad de Madrid, España"), "Madrid, España")
        self.assertEqual(short_address("Santiago"), "Santiago")
        self.assertEqual(short_address(""), "")

    def test_decimal_comma(self) -> None:
        self.assertEqual(fmt_freq(137_900_000), "137,900 MHz")
        self.assertEqual(fmt_freq(145_800_000), "145,800 MHz")
        self.assertEqual(fmt_dop(-1400), "−1,4 kHz")
        self.assertEqual(fmt_dop(0), "0,0 kHz")


if __name__ == "__main__":
    unittest.main()
