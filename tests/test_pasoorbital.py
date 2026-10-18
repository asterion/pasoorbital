"""Pruebas básicas de PasoOrbital (sin red).

Ejecutar con::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from pasoorbital import freqs, passes, tle

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  30777-3 0  9993"
ISS_L2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.50377579440000"

GOES_L1 = "1 51850U 22021A   26290.30589716  .00000098  00000+0  00000+0 0  9999"
GOES_L2 = "2 51850   0.0068  52.8892 0000201 214.3116  91.7680  1.00272447  7814"

ROOT = Path(__file__).resolve().parent.parent

T0 = 1704110400.0  # 2024-01-01T12:00:00Z
DAY = 86400.0


def iss_satrec() -> passes.Satrec:
    return tle.parse_tle(f"ISS (ZARYA)\n{ISS_L1}\n{ISS_L2}\n")[0]["satrec"]


class TestTle(unittest.TestCase):
    def test_parse_basic(self):
        items = tle.parse_tle(f"A\n{ISS_L1}\n{ISS_L2}\nB\n{ISS_L1}\n{ISS_L2}\n")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["norad"], 25544)
        self.assertEqual(items[0]["name"], "A")
        self.assertGreater(items[0]["period_min"], 80)
        self.assertLess(items[0]["period_min"], 110)
        self.assertAlmostEqual(items[0]["incl_deg"], 51.64, places=1)
        self.assertGreater(items[0]["epoch_ts"], 0)

    def test_parse_basura(self):
        self.assertEqual(tle.parse_tle("no hay tle aquí"), [])
        self.assertEqual(tle.parse_tle(""), [])

    def test_gso_period(self):
        item = tle.parse_tle(f"GOES 18\n{GOES_L1}\n{GOES_L2}\n")[0]
        self.assertGreater(item["period_min"], 1400)


class TestGeometry(unittest.TestCase):
    def test_gmst_j2000(self):
        # En J2000.0 el GMST vale 280.46061837°.
        self.assertAlmostEqual(math.degrees(passes.gmst_rad(2451545.0)), 280.46061837, places=4)

    def test_observer_validacion(self):
        with self.assertRaises(ValueError):
            passes.Observer(91.0, 0.0)
        with self.assertRaises(ValueError):
            passes.Observer(0.0, 181.0)
        obs = passes.Observer(40.4168, -3.7038, 650)
        self.assertAlmostEqual(float((obs.up**2).sum()), 1.0, places=12)

    def test_serie_vs_instante(self):
        sat = iss_satrec()
        obs = passes.Observer(40.4168, -3.7038, 650)
        ts = [T0 + 100.0, T0 + 3600.0, T0 + 7200.0]
        az, el, rng, rate = passes.look_series(sat, obs, ts)
        for i, t in enumerate(ts):
            single = passes.look_at(sat, obs, t)
            self.assertIsNotNone(single)
            self.assertAlmostEqual(float(az[i]), single[0], places=6)
            self.assertAlmostEqual(float(el[i]), single[1], places=6)
            self.assertAlmostEqual(float(rng[i]), single[2], places=6)
            self.assertAlmostEqual(float(rate[i]), single[3], places=6)

    def test_visibilidad_latitudes(self):
        sat = iss_satrec()
        self.assertTrue(passes.visible_possible(sat, 40.0))
        self.assertFalse(passes.visible_possible(sat, 89.0))
        goes = tle.parse_tle(f"GOES 18\n{GOES_L1}\n{GOES_L2}\n")[0]["satrec"]
        self.assertFalse(passes.visible_possible(goes, 89.0))


class TestPasses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sat = iss_satrec()
        cls.obs = passes.Observer(40.4168, -3.7038, 650)
        cls.min_el = 10.0
        cls.res = passes.find_passes(cls.sat, cls.obs, T0, T0 + DAY, cls.min_el, 10.0)

    def test_hay_pasos(self):
        self.assertGreaterEqual(len(self.res), 2)

    def test_orden_y_duracion(self):
        prev = -1.0
        for p in self.res:
            self.assertGreater(p["aos"], prev)
            self.assertLess(p["aos"], p["tca"])
            self.assertLess(p["tca"], p["los"])
            self.assertGreater(p["los"] - p["aos"], 30.0)
            prev = p["los"]

    def test_extremos(self):
        for p in self.res:
            aos = passes.look_at(self.sat, self.obs, p["aos"])
            los = passes.look_at(self.sat, self.obs, p["los"])
            self.assertAlmostEqual(aos[1], self.min_el, delta=0.02)
            self.assertAlmostEqual(los[1], self.min_el, delta=0.02)
            self.assertGreaterEqual(p["max_el"], self.min_el - 0.01)
            self.assertLessEqual(p["max_el"], 90.0)
            self.assertTrue(0.0 <= p["az_aos"] < 360.0)

    def test_tca_es_el_maximo(self):
        for p in self.res:
            for dt in (-30.0, 30.0):
                self.assertLessEqual(
                    passes.look_at(self.sat, self.obs, p["tca"] + dt)[1], p["max_el"] + 0.02
                )

    def test_doppler(self):
        for p in self.res:
            # Se acerca al principio (velocidad radial negativa) y se aleja al final.
            self.assertLess(p["rate_aos"], 0.0)
            self.assertGreater(p["rate_los"], 0.0)
            self.assertGreater(p["rate_max"], 1.0)

    def test_paso_en_curso(self):
        p = next(x for x in self.res if x["max_el"] > 25.0)
        mid = p["tca"] - 120.0
        res = passes.find_passes(self.sat, self.obs, mid, mid + 600.0, self.min_el, 5.0)
        self.assertTrue(res)
        self.assertEqual(res[0]["partial_start"], True)
        self.assertAlmostEqual(res[0]["aos"], mid, places=3)

    def test_geostacionario_sin_pasos(self):
        goes = tle.parse_tle(f"GOES 18\n{GOES_L1}\n{GOES_L2}\n")[0]["satrec"]
        self.assertEqual(passes.find_passes(goes, self.obs, T0, T0 + DAY, 5.0, 10.0), [])


class TestFrequencies(unittest.TestCase):
    def setUp(self):
        self.db = freqs.FrequencyDB(None)

    def test_iss(self):
        chans = self.db.lookup(25544, "ISS (ZARYA)")
        self.assertTrue(chans)
        self.assertEqual(chans[0]["freq_hz"], 145_800_000)

    def test_desconocido(self):
        self.assertEqual(self.db.lookup(999999), [])

    def test_regla_nombre(self):
        self.assertTrue(self.db.lookup(0, "ISS (ZARYA)"))
        self.assertEqual(self.db.lookup(0, "ISS (NAUKA)"), [])


@unittest.skipUnless((ROOT / "data" / "tle" / "stations.tle").exists(), "sin caché TLE local")
class TestCli(unittest.TestCase):
    def test_parser(self):
        from pasoorbital import cli

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(
                ["--lat", "40.4168", "--lon", "-3.7038", "--days", "0.3", "--min-el", "25", "--json"]
            )
        # main imprime JSON; basta con que no falle.
        self.assertEqual(code, 0)
        self.assertIn('"name"', buf.getvalue())


if __name__ == "__main__":
    unittest.main()
