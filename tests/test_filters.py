from __future__ import annotations

import unittest
from types import SimpleNamespace

from desktop.pasoorbital_gui.data import filter_passes


def make_item(
    name: str,
    freq_hz: int | None,
    groups: tuple[str, ...],
    max_el: float,
    aos: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        sat=SimpleNamespace(name=name, groups=groups),
        freq_hz=freq_hz,
        max_el=max_el,
        aos=aos,
    )


class FilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            make_item("ISS", 145_800_000, ("stations",), 30.0, 100.0),
            make_item("NOAA 19", 137_100_000, ("weather",), 20.0, 200.0),
            make_item("CUBESAT", None, ("cubesat",), 50.0, 300.0),
        ]

    def test_only_freq(self) -> None:
        up = filter_passes(self.items, only_freq=True)
        down = filter_passes(self.items, only_freq=False)
        self.assertEqual([item.sat.name for item in up], ["ISS", "NOAA 19"])
        self.assertEqual(len(down), 3)

    def test_groups(self) -> None:
        result = filter_passes(self.items, groups=("stations", "weather"))
        self.assertEqual([item.sat.name for item in result], ["ISS", "NOAA 19"])

    def test_min_el_and_days(self) -> None:
        result = filter_passes(self.items, min_el=25.0, limit=250.0)
        self.assertEqual([item.sat.name for item in result], ["ISS"])

    def test_query(self) -> None:
        result = filter_passes(self.items, query="noaa")
        self.assertEqual([item.sat.name for item in result], ["NOAA 19"])


if __name__ == "__main__":
    unittest.main()
