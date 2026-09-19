import hashlib
import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.app import product_contract_v2 as contract
from src.models import current_forecast_v2 as current


class Phase7AppContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = contract.load_inputs()
        cls.product = cls.inputs["current"]
        cls.panel = pd.read_csv(contract.DATA / "panel_demanda_v2.csv")

    def test_common_origin_and_complete_universe(self):
        self.assertEqual(self.product.origin_period.unique().tolist(), ["2026-08"])
        self.assertEqual(len(self.product), 424)
        for _, rows in self.product.groupby("horizon_months"):
            self.assertEqual(set(rows.zone_id), set(self.inputs["catalog"].zone_id))

    def test_regeneration_is_reproducible(self):
        rebuilt, meta = current.run(issued_at=self.inputs["metadata"]["issued_at"])
        pd.testing.assert_frame_equal(self.product, rebuilt, check_dtype=False)
        self.assertEqual(meta["common_origin_period"], "2026-08")

    def test_unknown_and_missing_never_become_zero(self):
        panel = self.panel.copy()
        last = panel.index[panel.periodo.eq("2026-08")][0]
        for status in ["MISSING_DATA", "UNKNOWN_ACTIVITY_STATUS"]:
            panel.loc[last, "data_status"] = status
            with self.assertRaises(ValueError):
                current.common_origin(panel, self.inputs["catalog"], "2026-09-19")
        panel.loc[last, "data_status"] = "OBSERVED"
        panel.loc[last, "viajes_total"] = np.nan
        with self.assertRaises(ValueError):
            current.common_origin(panel, self.inputs["catalog"], "2026-09-19")

    def test_future_availability_prevents_common_origin(self):
        panel = self.panel.copy()
        panel.loc[panel.periodo.eq("2026-08"), "target_available_no_earlier_than"] = "2026-10-01"
        with self.assertRaises(ValueError):
            current.common_origin(panel, self.inputs["catalog"], "2026-09-19")
        with self.assertRaises(ValueError):
            current.common_origin(self.panel, self.inputs["catalog"], "2026-08-31")

    def test_current_rejects_historical_and_mixed_origins(self):
        with self.assertRaises(ValueError):
            contract.validate_product(self.inputs["historical"], self.inputs["policy"], current=True)
        frame = self.product.copy()
        frame.loc[0, "origin_period"] = "2026-07"
        with self.assertRaises(ValueError):
            contract.validate_product(frame, self.inputs["policy"], current=True)
        with self.assertRaises(ValueError):
            contract.validate_product(self.product, self.inputs["policy"], current=False)

    def test_frozen_intervals_not_recalibrated(self):
        backtest = self.inputs["backtest"]
        for horizon, rows in self.product.groupby("horizon_months"):
            radius, origin, n = current.frozen_radius(backtest, horizon, "2026-08")
            np.testing.assert_allclose(rows.interval_upper_80, rows.forecast_value + radius)
            np.testing.assert_allclose(rows.interval_lower_80, np.maximum(0, rows.forecast_value - radius))
            self.assertTrue(rows.calibration_origin_period.eq(origin).all())
            self.assertTrue(rows.n_calibration_points.eq(n).all())
        changed = backtest.copy()
        changed["actual"] = 1e12
        self.assertEqual(current.frozen_radius(backtest, 1, "2026-08"), current.frozen_radius(changed, 1, "2026-08"))

    def test_invalid_interval_rejected_and_missing_interval_allowed(self):
        frame = self.product.copy()
        frame.loc[0, "interval_upper_80"] = -1
        with self.assertRaises(ValueError):
            contract.validate_product(frame, self.inputs["policy"], current=True)
        frame.loc[0, ["interval_lower_80", "interval_upper_80"]] = np.nan
        contract.validate_product(frame, self.inputs["policy"], current=True)

    def test_score_and_forecast_separate_and_legacy_formula_preserved(self):
        from src.app.algoritmo_puntuacion import calcular_scoring
        original = calcular_scoring(1, "general", "cualquiera", "medio")
        scores = contract.attach_scores(self.inputs["catalog"], original)
        frame = contract.zone_view(self.product, self.inputs["catalog"], self.inputs["geometry"], scores, 1)
        self.assertEqual(frame.opportunity_score.notna().sum(), 106)
        for row in frame.itertuples():
            expected = original[original.colonia.eq(row.score_source_colonia) & original.alcaldia.eq(row.alcaldia)].iloc[0].score
            self.assertEqual(row.opportunity_score, expected)
        altered = scores.copy()
        altered["opportunity_score"] = 1e10
        changed = contract.zone_view(self.product, self.inputs["catalog"], self.inputs["geometry"], altered, 1)
        np.testing.assert_array_equal(frame.forecast_value, changed.forecast_value)

    def test_no_geometry_still_queryable(self):
        scores = pd.DataFrame({"zone_id": self.inputs["catalog"].zone_id})
        frame = contract.zone_view(self.product, self.inputs["catalog"], self.inputs["geometry"], scores, 1)
        self.assertEqual(len(frame), 106)
        self.assertEqual(frame.map_status.ne("Disponible").sum(), 22)
        self.assertTrue(frame.loc[frame.map_status.ne("Disponible"), "forecast_value"].notna().all())

    def test_scenarios_never_numeric_or_validated(self):
        for h in [36, 60]:
            frame = self.product.copy()
            frame.loc[0, "horizon_months"] = h
            with self.assertRaises(ValueError):
                contract.validate_product(frame, self.inputs["policy"], current=True)
            self.assertTrue(contract.zone_view(self.product, self.inputs["catalog"], {}, pd.DataFrame(), h).empty)

    def test_correct_model_units_calendar_and_changes(self):
        self.assertTrue(self.product.model_used.eq("PERSISTENCE").all())
        self.assertTrue(self.product.target_unit.eq(contract.UNIT).all())
        self.assertTrue(self.product.direction.eq("NEUTRAL").all())
        self.assertEqual(set(self.product.target_period), {"2026-09", "2026-11", "2027-02", "2027-08"})
        changed = self.product.copy()
        changed.loc[0, "model_used"] = "LGBM_TEMPORAL"
        with self.assertRaises(ValueError):
            contract.validate_product(changed, self.inputs["policy"], current=True)

    def test_displayed_coverage_and_cut_counts_match_sources(self):
        table = self.inputs["validation"].set_index("horizon_months")
        for metric in self.inputs["coverage"].itertuples():
            self.assertEqual(table.loc[metric.horizon_months, "observed_coverage"], metric.observed_coverage)
            self.assertEqual(table.loc[metric.horizon_months, "interval_cuts"], metric.n_evaluable_origins)
        self.assertEqual(table.interval_cuts.tolist(), [15, 13, 10, 3])

    def test_unsafe_context_not_rendered_as_causal(self):
        row = self.product.iloc[0].copy()
        row["context_signal_1_feature"] = "population_snapshot"
        row["context_signal_1_value"] = 500
        row["context_signal_1"] = "La población causa crecimiento"
        self.assertEqual(contract.safe_context(row)[0], "Señal no disponible")
        self.assertNotIn("causa", " ".join(contract.safe_context(row)))
        self.assertEqual(contract.number(np.nan), "Sin dato")
        self.assertEqual(contract.number(np.inf), "Sin dato")

    def test_legacy_and_all_previous_artifacts_intact(self):
        # Frozen phase-6 tree, including the 17 legacy artifacts and both app files.
        paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "95ae85b", "data/processed", "src/app/app.py", "src/app/algoritmo_puntuacion.py"], cwd=ROOT, text=True).splitlines()
        self.assertGreater(len(paths), 64)
        for relative in paths:
            expected = subprocess.check_output(["git", "show", f"95ae85b:{relative}"], cwd=ROOT)
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).digest(), hashlib.sha256(expected).digest(), relative)

    def test_legacy_app_imports_and_v2_loads(self):
        legacy = importlib.import_module("src.app.app")
        app = importlib.import_module("src.app.app_v2")
        self.assertTrue(callable(legacy.main))
        self.assertTrue(callable(app.main))
        self.assertEqual(len(app.load_inputs()["current"]), 424)

    def test_metadata_input_and_output_hashes(self):
        meta = self.inputs["metadata"]
        for group in ["source_sha256", "implementation_sha256", "output_sha256"]:
            for path, digest in meta[group].items():
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)
        self.assertFalse(meta["current_coverage_validated"])

    def test_app_navigation_scenarios_and_no_geometry(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "src/app/app_v2.py")).run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        select = lambda label: next(widget for widget in app.selectbox if widget.label == label)
        no_geo = self.inputs["catalog"][~self.inputs["catalog"].geometry_available].zone_id.iloc[0]
        select("Colonia").set_value(no_geo).run()
        self.assertTrue(any("Sin geometría disponible" in x.value for x in app.info))
        for choice in ["Dirección", "Opportunity Score", "Cambio esperado"]:
            select("Mostrar en mapa").set_value(choice).run()
            self.assertEqual(len(app.exception), 0)
        for h in [3, 6, 12, 36, 60]:
            select("Horizonte").set_value(h).run()
            self.assertEqual(len(app.exception), 0)
            if h in [36, 60]:
                self.assertEqual(len(app.metric), 0)
                self.assertTrue(any("SCENARIO_ONLY" in x.value for x in app.subheader))
        select("Horizonte").set_value(1).run()
        app.radio[0].set_value("Validación histórica").run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("No es una emisión actual" in x.value for x in app.warning))

    def test_app_missing_current_does_not_substitute_backtest(self):
        from streamlit.testing.v1 import AppTest
        missing = dict(self.inputs, current=None)
        with patch("src.app.product_contract_v2.load_inputs", return_value=missing):
            app = AppTest.from_file(str(ROOT / "src/app/app_v2.py")).run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.metric), 0)
        self.assertTrue(any("Emisión actual no disponible" in x.value for x in app.warning))


if __name__ == "__main__":
    unittest.main()
