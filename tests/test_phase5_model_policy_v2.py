import hashlib
import inspect
import json
import re
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.models import forecast_policy_v2 as policy  # noqa: E402


class Phase5ModelPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy, cls.metadata = policy.build_policy()
        cls.forecast = policy.build_operational_forecast(cls.policy)
        cls.metadata = json.loads((ROOT / "data/processed/model_policy_v2.metadata.json").read_text())

    def test_policy_uses_existing_sources_only(self):
        self.assertTrue(all(path.exists() for path in policy.INPUTS.values()))
        self.assertEqual(set(self.metadata["source_sha256"]), {
            str(p.relative_to(ROOT)) for p in policy.INPUTS.values()
        })

    def test_module_does_not_fit_or_import_lightgbm(self):
        source = inspect.getsource(policy)
        self.assertIsNone(re.search(r"(?m)^(?:from|import)\s+lightgbm", source.lower()))
        self.assertNotIn(".fit(", source)

    def test_primary_is_allowed_and_policy_unique(self):
        self.assertEqual(list(self.policy.horizon_months), [1, 3, 6, 12])
        self.assertTrue(set(self.policy.primary_model).issubset(policy.CANDIDATES))
        self.assertEqual(self.policy.horizon_months.nunique(), 4)

    def test_spatial_never_primary(self):
        self.assertNotIn(policy.SPATIAL_MODEL, set(self.policy.primary_model))
        self.assertTrue((self.policy.spatial_role == "EXPLORATORY_ONLY").all())

    def test_long_horizons_are_scenarios_only(self):
        self.assertEqual(self.metadata["long_horizon_policy"]["36"], "SCENARIO_ONLY; excluded from operational CSV")
        self.assertEqual(self.metadata["long_horizon_policy"]["60"], "SCENARIO_ONLY; excluded from operational CSV")
        self.assertNotIn(36, set(self.forecast.horizon_months))
        self.assertNotIn(60, set(self.forecast.horizon_months))

    def test_policy_records_required_selection_fields(self):
        required = {"horizon_months", "primary_model", "secondary_model",
                    "MAE_primary", "RMSE_primary", "MAE_persistence",
                    "improvement_vs_persistence_pct", "cuts_won", "cuts_lost",
                    "n_cuts", "n_observations", "validation_status",
                    "selection_reason"}
        self.assertTrue(required.issubset(self.policy.columns))

    def test_primary_metrics_equal_persistence(self):
        self.assertTrue((self.policy.MAE_primary == self.policy.MAE_persistence).all())
        self.assertTrue((self.policy.improvement_vs_persistence_pct == 0).all())
        self.assertTrue((self.policy.primary_model == "PERSISTENCE").all())

    def test_validation_status_present_and_operational_role(self):
        self.assertTrue(self.policy.validation_status.notna().all())
        self.assertTrue(self.policy.forecast_role.eq("VALIDATED_FORECAST").all())
        self.assertTrue(set(self.policy.validation_status).issubset({
            "VALIDATED_SHORT_TERM", "VALIDATED_WITH_CAUTION", "SCENARIO_ONLY"
        }))

    def test_operational_output_schema_and_model_used(self):
        required = {"zone_id", "colonia", "origin_period", "horizon_months",
                    "target_period", "forecast_value", "reference_value",
                    "forecast_change_abs", "forecast_change_pct", "direction",
                    "model_used", "validation_status", "forecast_role",
                    "direction_threshold_version"}
        self.assertTrue(required.issubset(self.forecast.columns))
        self.assertTrue(self.forecast.model_used.eq("PERSISTENCE").all())
        self.assertTrue(self.forecast.validation_status.notna().all())

    def test_operational_forecasts_are_finite_and_have_correct_direction(self):
        self.assertTrue(self.forecast.forecast_value.map(pd.notna).all())
        self.assertTrue(self.forecast.reference_value.map(pd.notna).all())
        expected = self.forecast.forecast_value - self.forecast.reference_value
        self.assertTrue((expected == self.forecast.forecast_change_abs).all())
        self.assertTrue(set(self.forecast.direction).issubset({"UP", "DOWN", "NEUTRAL"}))

    def test_direction_threshold_version_is_explicit(self):
        self.assertTrue(self.forecast.direction_threshold_version.eq(policy.DIRECTION_THRESHOLD_VERSION).all())
        self.assertTrue(self.policy.direction_threshold_version.eq(policy.DIRECTION_THRESHOLD_VERSION).all())

    def test_target_unit_is_viajes_total_units(self):
        self.assertTrue(self.forecast.target_unit.eq("station_endpoints_per_calendar_month").all())
        self.assertNotIn("target_demanda", self.forecast.columns)
        self.assertNotIn("indice_demanda_compuesto", self.forecast.columns)

    def test_latest_audited_origin_per_zone_and_horizon(self):
        keys = self.forecast[["zone_id", "horizon_months"]]
        self.assertEqual(len(keys), len(keys.drop_duplicates()))
        self.assertTrue(set(self.forecast.horizon_months).issubset({1, 3, 6, 12}))

    def test_spatial_secondary_is_not_silently_operational(self):
        self.assertNotIn(policy.SPATIAL_MODEL, set(self.policy.secondary_model))

    def test_phase4_protected_hashes_intact(self):
        meta = json.loads((ROOT / "data/processed/lightgbm_compare_v2.metadata.json").read_text())
        for relative, expected in meta["protected_previous_phase_sha256"].items():
            path = ROOT / relative
            if path.exists():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(digest, expected, relative)

    def test_streamlit_files_are_not_modified(self):
        meta = json.loads((ROOT / "data/processed/lightgbm_compare_v2.metadata.json").read_text())
        for relative in ("src/app/app.py", "src/app/algoritmo_puntuacion.py"):
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                             meta["protected_previous_phase_sha256"][relative])


if __name__ == "__main__":
    unittest.main()
