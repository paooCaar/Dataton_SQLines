"""Station activity uses dated endpoint events, not all-time totals."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data.station_activity_snapshot import build_station_activity


class StationActivitySnapshotTests(unittest.TestCase):
    def test_counts_only_valid_endpoints_in_latest_month(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pd.DataFrame({
                "num_cicloe": ["001", "002", "003"],
                "colonia": ["A", "A", "A"],
                "alcaldia": ["Cuauhtemoc"] * 3,
                "latitud": ["19.42"] * 3,
                "longitud": ["-99.15"] * 3,
            }).to_csv(root / "Caracteristicas_estaciones.csv", index=False)
            pd.DataFrame({
                "Ciclo_Estacion_Retiro": ["001", "001", "002", "001"],
                "Ciclo_EstacionArribo": ["002", "002", "001", "002"],
                "Fecha_Retiro": ["03/01/2026", "31/12/2025", "05/01/2026", "09/01/2026"],
                "Fecha_Arribo": ["03/01/2026", "01/01/2026", "04/01/2026", "09/01/2026"],
            }).to_csv(root / "2026-01.csv", index=False)

            result = build_station_activity(root).set_index("num_cicloe")
            self.assertEqual(result.periodo.unique().tolist(), ["2026-01"])
            self.assertEqual(result.loc["001", "viajes_origen"], 2)
            self.assertEqual(result.loc["001", "viajes_destino"], 0)
            self.assertEqual(result.loc["002", "viajes_destino"], 3)
            self.assertEqual(result.loc["003", "activity_status"], "NO_RECORD")


if __name__ == "__main__":
    unittest.main()
