"""Phase 1 integrity tests; no training, network, or legacy writes."""
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.data.ecobici_v2 import (build_catalog, count_chunk, discover_months,
                               load_stations, stable_zone_id)
from src.features.panel_demanda_v2 import (ROOT, assemble_panel, attach_context,
                                         geometry_audit, monthly_calendar, validate_panel)


def catalog_fixture():
    return pd.DataFrame([{"zone_id": "z1", "colonia": "A", "alcaldia": "B",
                          "geometry_available": False}])


def counts_fixture(periods=("2023-01", "2023-03")):
    return pd.DataFrame([{"zone_id": "z1", "periodo": p, "event": event,
                          "count": 2, "source_period": p}
                         for p in periods for event in ["origen", "destino"]])


class DiscoveryTests(unittest.TestCase):
    def test_both_names_and_missing_calendar(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ["2023-01.csv", "2023_03.csv", "Caracteristicas_estaciones.csv"]:
                (root / name).touch()
            files = discover_months(root)
            self.assertEqual(list(files), ["2023-01", "2023-03"])
            cal = monthly_calendar(files)
            self.assertEqual(cal.archivo_disponible.tolist(), [True, False, True])

    def test_duplicate_month_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ["2023-01.csv", "2023_01.csv"]:
                (Path(folder) / name).touch()
            with self.assertRaises(ValueError):
                discover_months(Path(folder))

    def test_unrecognized_year_filename_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "2023.01.csv").touch()
            with self.assertRaises(ValueError):
                discover_months(Path(folder))


class EventTests(unittest.TestCase):
    def chunk(self, arrival_name="Fecha_Arribo"):
        return pd.DataFrame({"Ciclo_Estacion_Retiro": ["001", "unknown", "001"],
                             "Ciclo_EstacionArribo": ["001", "001", "001"],
                             "Fecha_Retiro": ["31/01/2023", "01/02/2023", "bad"],
                             arrival_name: ["01/02/2023"] * 3})

    def test_event_months_and_accounting(self):
        for name in ["Fecha Arribo", "Fecha_Arribo"]:
            counts, q = count_chunk(self.chunk(name), pd.Series({"001": "z1"}),
                                    "2023-02", "2023-01", "2023-02")
            self.assertEqual(q["cross_month_trips"], 1)
            self.assertEqual(q["invalid_dates"], 1)
            self.assertEqual(q["unmapped_origen"], 1)
            self.assertEqual(q["counted_destino"], 2)
            self.assertEqual(counts.loc[counts.event == "origen", "periodo"].tolist(), ["2023-01"])
            self.assertTrue((counts.source_period == "2023-02").all())

    def test_arrival_partition_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            count_chunk(self.chunk(), pd.Series({"001": "z1"}), "2023-03", "2023-01", "2023-03")

    def test_reversed_dates_excluded_and_reported(self):
        c = self.chunk().iloc[:1].copy()
        c["Fecha_Retiro"] = "02/02/2023"
        counts, q = count_chunk(c, pd.Series({"001": "z1"}), "2023-02", "2023-01", "2023-02")
        self.assertEqual(q["reversed_dates"], 1)
        self.assertEqual(counts["count"].sum(), 0)


class PanelTests(unittest.TestCase):
    def test_missing_is_not_zero_even_with_partial_observations(self):
        cal = monthly_calendar({"2023-01": Path("a"), "2023-03": Path("b")})
        panel = assemble_panel(catalog_fixture(), cal, counts_fixture(("2023-01", "2023-02", "2023-03")))
        middle = panel.iloc[1]
        self.assertEqual(middle.data_status, "MISSING_DATA")
        self.assertEqual(middle.observed_viajes_origen, 2)
        self.assertTrue(pd.isna(middle.target_demanda))
        validate_panel(panel)

    def test_zero_and_unknown_activation_are_distinct(self):
        files = {f"2023-{m:02}": Path("a") for m in range(1, 5)}
        panel = assemble_panel(catalog_fixture(), monthly_calendar(files), counts_fixture(("2023-02",)))
        self.assertEqual(panel.data_status.tolist(), ["UNKNOWN_ACTIVITY_STATUS", "OBSERVED", "ZERO_DEMAND", "ZERO_DEMAND"])
        self.assertTrue(pd.isna(panel.target_demanda.iloc[0]))
        self.assertEqual(panel.target_demanda.iloc[2], 0)

    def test_confirmed_activation_only(self):
        cal = monthly_calendar({"2023-01": Path("a"), "2023-02": Path("b")})
        panel = assemble_panel(catalog_fixture(), cal, counts_fixture(("2023-02",)), {"z1": "2023-02-01"})
        self.assertEqual(panel.data_status.iloc[0], "NOT_YET_ACTIVE")
        with self.assertRaises(ValueError):
            assemble_panel(catalog_fixture(), cal, counts_fixture(), {"z1": "2023-02-01"})

    def test_late_report_is_not_available_in_event_month(self):
        counts = counts_fixture(("2023-01",))
        counts["source_period"] = "2023-03"
        panel = assemble_panel(catalog_fixture(), monthly_calendar({"2023-01": Path("a")}), counts)
        self.assertEqual(panel.target_available_no_earlier_than.iloc[0], pd.Timestamp("2023-04-01"))
        self.assertFalse(panel.historical_availability_verified.any())

    def test_duplicate_key_and_order_are_rejected(self):
        panel = assemble_panel(catalog_fixture(), monthly_calendar({"2023-01": Path("a"), "2023-03": Path("b")}), counts_fixture())
        with self.assertRaises(ValueError):
            validate_panel(pd.concat([panel, panel]).reset_index(drop=True))
        with self.assertRaises(ValueError):
            validate_panel(panel.iloc[::-1].reset_index(drop=True))


class RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stations, cls.blank = load_stations(ROOT / "data/raw/ecobici/Caracteristicas_estaciones.csv")
        cls.crosswalk = pd.read_csv(ROOT / "data/processed/crosswalk_colonias.csv")
        cls.geo = json.loads((ROOT / "data/processed/zonas_geometria.geojson").read_text())
        cls.rules = json.loads((ROOT / "config/aliases_colonias_v2.json").read_text())["approved_aliases"]

    def test_alias_requires_evidence_and_keeps_station_identity(self):
        catalog, stations = build_catalog(self.stations, self.crosswalk, self.geo, self.rules)
        self.assertEqual(len(catalog), 106)
        self.assertEqual(len(stations), 677)
        self.assertEqual(self.blank, 312)
        d = catalog[catalog.colonia == "Del Valle Centro"].iloc[0]
        self.assertEqual(d.n_estaciones_catalogo_actual, 15)
        self.assertEqual(len(json.loads(d.aliases)), 2)
        self.assertEqual(catalog.geometry_available.sum(), 84)
        wrong = self.stations.copy()
        wrong.loc[wrong.num_cicloe == "343", "alcaldia"] = "Other"
        with self.assertRaises(ValueError):
            build_catalog(wrong, self.crosswalk, self.geo, self.rules)

    def test_no_automatic_alias_merge_and_stable_ids(self):
        catalog, _ = build_catalog(self.stations, self.crosswalk, self.geo, [])
        self.assertEqual(len(catalog), 107)
        shuffled, _ = build_catalog(self.stations.sample(frac=1, random_state=5), self.crosswalk, self.geo, [])
        self.assertEqual(set(catalog.zone_id), set(shuffled.zone_id))
        self.assertNotEqual(stable_zone_id("A", "Centro"), stable_zone_id("B", "Centro"))

    def test_snapshots_are_blocked_in_historical_forecast_columns(self):
        catalog, _ = build_catalog(self.stations, self.crosswalk, self.geo, self.rules)
        files = {"2023-01": Path("a"), "2026-08": Path("b")}
        counts = counts_fixture()
        counts["zone_id"] = catalog.zone_id.iloc[0]
        panel = assemble_panel(catalog, monthly_calendar(files), counts)
        enriched = attach_context(panel, catalog, ROOT / "data/processed")
        self.assertEqual(len(panel), len(enriched))
        for column in ["poblacion_colonia_2020", "km_ciclovia", "negocios_denue", "accidentes"]:
            self.assertTrue(enriched[column].isna().all(), column)
        self.assertTrue(enriched.loc[enriched.year == 2026, "accidentes_reportados_legacy"].isna().all())

    def test_geometry_topology(self):
        result = geometry_audit(self.geo)
        if not result["topology_verified"]:
            self.skipTest(result["reason"])
        self.assertEqual(result["valid_geometries"], 84)

    def test_generated_panel_integrity_and_legacy_hashes(self):
        path = ROOT / "data/processed/panel_demanda_v2.csv"
        if not path.exists():
            self.skipTest("Run generation first for integration verification")
        from src.data.ecobici_v2 import sha256_file
        panel = pd.read_csv(path, parse_dates=["fecha"])
        validate_panel(panel)
        self.assertEqual(len(panel), 106 * 44)
        self.assertEqual(panel.loc[panel.periodo == "2024-10", "data_status"].unique().tolist(), ["MISSING_DATA"])
        meta = json.loads(path.with_suffix(".metadata.json").read_text())
        for filename, expected in meta["legacy_sha256_unchanged"].items():
            self.assertEqual(sha256_file(Path(filename)), expected)
        for filename, expected in meta["output_sha256"].items():
            self.assertEqual(sha256_file(path.parent / filename), expected)


if __name__ == "__main__":
    unittest.main()
