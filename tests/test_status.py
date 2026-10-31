from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pasoorbital.satstatus import SatelliteStatus, StatusDB, label_for_code, parse_satcat

HEADER = (
    "OBJECT_NAME,OBJECT_ID,NORAD_CAT_ID,OBJECT_TYPE,OPS_STATUS_CODE,"
    "OWNER,LAUNCH_DATE,LAUNCH_SITE,DECAY_DATE\n"
)


class TestSatStatus(unittest.TestCase):
    def test_labels(self) -> None:
        self.assertEqual(label_for_code("+"), "Operativo")
        self.assertEqual(label_for_code("-"), "No operativo")
        self.assertEqual(label_for_code("P"), "Parcialmente operativo")
        self.assertIn("Desconocido", label_for_code("Z"))

    def test_parse(self) -> None:
        rows = [
            {
                "OBJECT_NAME": "ISS",
                "NORAD_CAT_ID": "25544",
                "OBJECT_TYPE": "PAY",
                "OPS_STATUS_CODE": "+",
                "DECAY_DATE": "",
            },
            {
                "OBJECT_NAME": "OLD",
                "NORAD_CAT_ID": "1",
                "OBJECT_TYPE": "R/B",
                "OPS_STATUS_CODE": "D",
                "DECAY_DATE": "1957-12-01",
            },
            {
                "OBJECT_NAME": "NO CODE",
                "NORAD_CAT_ID": "2",
                "OPS_STATUS_CODE": "",
            },
            {"OBJECT_NAME": "NO NORAD", "NORAD_CAT_ID": ""},
        ]
        statuses = parse_satcat(rows, fetched_at=1000.0)
        self.assertEqual(statuses[25544].short, "Operativo")
        self.assertEqual(statuses[25544].slug, "operational")
        self.assertEqual(statuses[1].short, "Decaído")
        self.assertEqual(statuses[1].slug, "decayed")
        self.assertEqual(statuses[2].code, "?")
        self.assertNotIn(0, statuses)
        self.assertIn("CelesTrak", statuses[25544].tooltip(now=1000.0))

    def test_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StatusDB(Path(tmp))
            db.csv_path.write_text(
                HEADER
                + "ISS,1998-067A,25544,PAY,+,CIS,1998-11-20,,,"
                + "\n",
                encoding="utf-8",
            )
            os.utime(db.csv_path, None)
            statuses = db.load()
            self.assertEqual(statuses[25544].label, "Operativo")

    def test_empty_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = StatusDB(Path(tmp))
            # Sin caché y sin red no debe lanzar; el test no fuerza descarga.
            self.assertIsInstance(db.csv_path, Path)
            self.assertFalse(db.csv_path.exists())
            self.assertIsInstance(SatelliteStatus(1, "+", "Operativo").tooltip(), str)


# La prueba de formato UTC se mantiene separada del estado SATCAT.
class TestFormatUtils(unittest.TestCase):
    def test_fmt_utc(self) -> None:
        from datetime import datetime, timezone
        from desktop.pasoorbital_gui.format import fmt_utc

        ts = datetime(2026, 10, 31, 12, 34, 56, tzinfo=timezone.utc).timestamp()
        self.assertEqual(fmt_utc(ts), "12:34:56")


if __name__ == "__main__":
    unittest.main()
