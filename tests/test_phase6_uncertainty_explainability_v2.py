import hashlib
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.models import uncertainty_v2  # noqa: E402


class Phase6UncertaintyExplainabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.uncertainty, cls.metrics, cls.explanations, cls.product,
         cls.uncertainty_meta, cls.explanation_meta) = uncertainty_v2.run()
        cls.predictions = pd.read_csv(uncertainty_v2.INPUTS["predictions"])

    def test_calibration_uses_only_prior_origin_and_target(self):
        frame = pd.DataFrame([
            {"evaluation_scope": "EVALUATION_ALL", "model": "PERSISTENCE", "horizon": 1,
             "origin_period": "2025-01", "target_period": "2025-02", "actual": 12, "predicted": 10},
            {"evaluation_scope": "EVALUATION_ALL", "model": "PERSISTENCE", "horizon": 1,
             "origin_period": "2025-02", "target_period": "2025-03", "actual": 13, "predicted": 10},
            {"evaluation_scope": "EVALUATION_ALL", "model": "PERSISTENCE", "horizon": 1,
             "origin_period": "2024-12", "target_period": "2025-01", "actual": 11, "predicted": 10},
        ])
        frame["residual_available_at"] = ["2025-02-01", "2025-03-01", "2025-01-01"]
        residuals = uncertainty_v2._calibration_residuals(frame, 1, "2025-03")
        self.assertEqual(residuals.tolist(), [2.0, 1.0])

    def test_no_future_residual_leakage_in_source(self):
        prepared = uncertainty_v2.prepare_predictions(self.predictions,
            pd.read_csv(uncertainty_v2.INPUTS["panel"]), pd.read_csv(uncertainty_v2.INPUTS["splits"]))
        expected = uncertainty_v2._calibration_residuals(prepared, 1, "2026-01")
        later = prepared.residual_available_at.ge(pd.Timestamp("2026-01-01")) | prepared.residual_available_at.isna()
        changed = prepared.copy()
        changed.loc[later, "actual"] = 1e12
        np.testing.assert_array_equal(expected, uncertainty_v2._calibration_residuals(changed, 1, "2026-01"))
        # Past target with a later report is still unknown.
        changed.loc[~later, "residual_available_at"] = pd.Timestamp("2027-01-01")
        self.assertEqual(len(uncertainty_v2._calibration_residuals(changed, 1, "2026-01")), 0)

    def test_symmetric_interval_contains_forecast_and_is_nonnegative(self):
        lower, upper, n, clipped, status = uncertainty_v2._interval(100.0, np.array([-10, 0, 20] * 20, dtype=float))
        self.assertLessEqual(lower, 100.0)
        self.assertGreaterEqual(upper, 100.0)
        self.assertGreaterEqual(lower, 0.0)
        self.assertGreaterEqual(n, uncertainty_v2.MIN_CALIBRATION_POINTS)
        self.assertEqual(status, "CALIBRATED")

    def test_lower_clipping_is_recorded(self):
        lower, upper, _, clipped, status = uncertainty_v2._interval(5.0, np.array([-100] * 30, dtype=float))
        self.assertEqual(lower, 0.0)
        self.assertTrue(clipped)
        self.assertEqual(status, "CALIBRATED")

    def test_metrics_coverage_definition_and_target(self):
        self.assertTrue((self.metrics.target_coverage == 0.8).all())
        self.assertTrue(np.allclose(self.metrics.coverage_error,
                                    self.metrics.observed_coverage - self.metrics.target_coverage))
        self.assertTrue((self.metrics.n_predictions >= 0).all())
        audit = self.metrics.attrs["backtest"]
        for metric in self.metrics.itertuples():
            group = audit[audit.horizon_months.eq(metric.horizon_months)]
            valid = group.interval_lower_80.notna()
            good = group[valid]
            covered = (good.actual >= good.interval_lower_80) & (good.actual <= good.interval_upper_80)
            self.assertAlmostEqual(metric.observed_coverage, covered.mean())
            self.assertEqual(metric.n_calibration_failures, int((~valid).sum()))
            self.assertEqual(metric.n_predictions, len(good))

    def test_calibration_point_counts_are_persisted(self):
        self.assertTrue(self.uncertainty.n_calibration_points.notna().all())
        self.assertTrue((self.uncertainty.n_calibration_points >= 0).all())
        self.assertEqual(self.uncertainty_meta["min_calibration_points"], 30)
        prepared = uncertainty_v2.prepare_predictions(self.predictions,
            pd.read_csv(uncertainty_v2.INPUTS["panel"]), pd.read_csv(uncertainty_v2.INPUTS["splits"]))
        for r in self.uncertainty.groupby(["horizon_months", "origin_period"]).first().reset_index().itertuples():
            cutoff = pd.Timestamp(r.origin_period + "-01")
            count = ((prepared.horizon == r.horizon_months) &
                     (prepared.origin_period < r.origin_period) & (prepared.target_period < r.origin_period) &
                     (prepared.residual_available_at < cutoff)).sum()
            self.assertEqual(r.n_calibration_points, count)

    def test_insufficient_history_is_marked_without_interval(self):
        insufficient = self.uncertainty[self.uncertainty.uncertainty_status == "INSUFFICIENT_CALIBRATION_HISTORY"]
        self.assertGreater(len(insufficient), 0)
        self.assertTrue(insufficient.interval_lower_80.isna().all())
        self.assertTrue(insufficient.interval_upper_80.isna().all())

    def test_operational_intervals_are_nonnegative_and_contain_forecast_when_calibrated(self):
        calibrated = self.uncertainty[self.uncertainty.uncertainty_status == "CALIBRATED"]
        self.assertTrue((calibrated.interval_lower_80 >= 0).all())
        self.assertTrue((calibrated.interval_upper_80 >= calibrated.interval_lower_80).all())
        self.assertTrue((calibrated.interval_lower_80 <= calibrated.forecast_value).all())
        self.assertTrue((calibrated.interval_upper_80 >= calibrated.forecast_value).all())

    def test_primary_explanation_is_not_shap(self):
        self.assertTrue(self.explanations.forecast_model.eq("PERSISTENCE").all())
        self.assertTrue(self.explanations.forecast_explanation.str.contains("persistencia", case=False).all())
        self.assertNotIn("SHAP", " ".join(self.explanations.forecast_explanation.astype(str)))
        self.assertFalse(self.uncertainty_meta["shap_enabled"])

    def test_context_unsafe_snapshots_are_not_exported_as_signals(self):
        forbidden = {"n_estaciones_colonia_catalogo", "poblacion_colonia_2020",
                     "negocios_denue", "km_ciclovia", "station_density"}
        signal_names = set(self.explanations.context_signal_1) | set(self.explanations.context_signal_2) | set(self.explanations.context_signal_3)
        self.assertTrue(forbidden.isdisjoint(signal_names))
        self.assertFalse(self.uncertainty_meta["context_feature_rules"]["unsafe_snapshots_in_forecast"])

    def test_context_is_marked_descriptive(self):
        self.assertTrue(self.explanations.limitations.str.contains("contextuales|contexto", case=False, regex=True).all())
        self.assertTrue(self.explanations.explanation_version.eq("2.0-phase6-persistence-context").all())

    def test_product_has_unique_zone_horizon_and_required_fields(self):
        self.assertEqual(len(self.product), len(self.product[["zone_id", "horizon_months"]].drop_duplicates()))
        required = {"zone_id", "origin_period", "horizon_months", "target_period", "forecast_value",
                    "interval_lower_80", "interval_upper_80", "model_used", "forecast_explanation",
                    "context_signal_1", "context_signal_2", "context_signal_3", "uncertainty_status"}
        self.assertTrue(required.issubset(self.product.columns))

    def test_units_are_activity_endpoints(self):
        self.assertTrue(self.uncertainty.target_unit.eq("station_endpoints_per_calendar_month").all())
        self.assertNotIn("target_demanda", self.product.columns)
        self.assertNotIn("indice_demanda_compuesto", self.product.columns)

    def test_no_shap_model_is_created(self):
        self.assertFalse(self.uncertainty_meta["shap_enabled"])
        self.assertFalse(any("shap" in c.lower() for c in self.product.columns))

    def test_legacy_and_streamlit_hashes_intact(self):
        meta = json.loads((ROOT / "data/processed/lightgbm_compare_v2.metadata.json").read_text())
        for relative, expected in meta["protected_previous_phase_sha256"].items():
            path = ROOT / relative
            self.assertTrue(path.exists(), relative)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected, relative)

    def test_exact_conformal_order_statistic(self):
        lower, upper, _, _, _ = uncertainty_v2._interval(100., np.arange(1., 32.))
        # n=31, ceil(32*.8)=26; direct empirical 80% higher would be 25.
        self.assertEqual((lower, upper), (74., 126.))

    def test_missing_availability_fails_closed_and_nan_not_zero(self):
        frame = pd.DataFrame({"horizon": [1], "origin_period": ["2024-01"],
            "target_period": ["2024-02"], "model": ["PERSISTENCE"],
            "evaluation_scope": ["EVALUATION_ALL"], "actual": [0.], "predicted": [0.]})
        with self.assertRaises(ValueError):
            uncertainty_v2._calibration_residuals(frame, 1, "2025-01")
        frame["residual_available_at"] = pd.NaT
        self.assertEqual(len(uncertainty_v2._calibration_residuals(frame, 1, "2025-01")), 0)
        with self.assertRaises(ValueError):
            uncertainty_v2._interval(100., np.array([np.nan] * 30))

    def test_all_cold_start_metrics_work(self):
        audit = self.metrics.attrs["backtest"].iloc[:1].copy()
        audit["uncertainty_status"] = "INSUFFICIENT_CALIBRATION_HISTORY"
        audit[["interval_lower_80", "interval_upper_80", "covered"]] = np.nan
        m = uncertainty_v2.summarize_coverage(audit)
        self.assertTrue(m.observed_coverage.isna().all())
        self.assertTrue(m.n_predictions.eq(0).all())

    def test_context_matches_origin_frozen_matrix_and_ignores_unsafe_columns(self):
        matrix = pd.read_csv(uncertainty_v2.INPUTS["matrix"])
        operational = pd.read_csv(uncertainty_v2.INPUTS["operational"])
        lookup = matrix.set_index(["zone_id", "horizon", "origin_period"])
        for r in self.explanations.itertuples():
            for i in (1, 2, 3):
                name = getattr(r, f"context_signal_{i}_feature")
                if name != "NONE":
                    self.assertAlmostEqual(getattr(r, f"context_signal_{i}_value"),
                        lookup.loc[(r.zone_id, r.horizon_months, r.origin_period), name])
        matrix["target_viajes_total"] = 1e12
        matrix["station_density"] = 1e12
        result = uncertainty_v2.build_explanations(operational, self.uncertainty, matrix)
        pd.testing.assert_frame_equal(result, self.explanations)

    def test_product_rejects_duplicate_or_wrong_origin(self):
        bad = self.explanations.copy()
        bad.loc[0, "origin_period"] = "2099-01"
        with self.assertRaises(ValueError):
            uncertainty_v2.build_product(self.uncertainty, bad)
        with self.assertRaises(ValueError):
            uncertainty_v2.build_product(self.uncertainty, pd.concat([self.explanations, self.explanations.iloc[:1]]))
        self.assertTrue(self.product.target_unit.eq(uncertainty_v2.UNIT).all())
        self.assertTrue(self.product.artifact_role.eq("RETROSPECTIVE_REPLAY").all())

    def test_validation_coverage_is_known_at_origin(self):
        audit = self.metrics.attrs["backtest"]
        for r in self.uncertainty.itertuples():
            previous = audit[audit.horizon_months.eq(r.horizon_months) &
                (pd.to_datetime(audit.residual_available_at) < pd.Timestamp(r.origin_period + "-01")) &
                (audit.origin_period < r.origin_period)]
            self.assertEqual(r.n_validation_predictions, previous.covered.notna().sum())
            if previous.covered.notna().any():
                self.assertAlmostEqual(r.validation_coverage, previous.covered.mean())
            else:
                self.assertTrue(pd.isna(r.validation_coverage))

    def test_phase5_and_source_hashes_intact(self):
        for name in ["model_policy_v2.metadata.json", "lightgbm_compare_v2.metadata.json"]:
            metadata = json.loads((ROOT / "data/processed" / name).read_text())
            for path, digest in metadata.get("output_sha256", {}).items():
                p = ROOT / path if path.startswith("data/") else ROOT / "data/processed" / path
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
