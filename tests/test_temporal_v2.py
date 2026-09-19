import unittest

import numpy as np
import pandas as pd

from src.features.features_temporales_v2 import build_temporal_features
from src.validation.rolling_validation_v2 import (
    _theil_sen_predict,
    calculate_metrics,
    directional_accuracy,
    evaluate_rolling,
    smape,
)


def make_panel(periods, values_by_zone, statuses=None):
    rows = []
    statuses = statuses or {}
    for zone, values in values_by_zone.items():
        for period, value in zip(periods, values):
            status = statuses.get((zone, period), "OBSERVED" if value is not None else "MISSING_DATA")
            rows.append({
                "zone_id": zone, "colonia": zone, "alcaldia": "Test",
                "periodo": period, "fecha": pd.Period(period, freq="M").to_timestamp(),
                "data_status": status, "datos_disponibles": status == "OBSERVED",
                "archivo_disponible": status != "MISSING_DATA", "source_status": "AVAILABLE",
                "viajes_total": value, "target_demanda": value, "run_id": "test",
            })
    return pd.DataFrame(rows).sort_values(["zone_id", "fecha"]).reset_index(drop=True)


class TemporalFeaturesTests(unittest.TestCase):
    def test_calendar_lags_do_not_skip_missing_months(self):
        periods = ["2023-01", "2023-02", "2023-03", "2023-04"]
        panel = make_panel(periods, {"z": [10, 20, None, 40]})
        features = build_temporal_features(panel)
        april = features.loc[features.periodo.eq("2023-04")].iloc[0]
        self.assertTrue(pd.isna(april.lag_1))
        self.assertEqual(april.lag_3, 10)
        self.assertTrue(pd.isna(april.rolling_mean_3))
        self.assertTrue(pd.isna(april.growth_1))

    def test_current_target_cannot_change_same_row_features(self):
        periods = ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"]
        first = make_panel(periods, {"z": [10, 20, 30, 40, 50]})
        second = first.copy()
        second.loc[second.periodo.eq("2023-04"), "viajes_total"] = 999999
        second.loc[second.periodo.eq("2023-04"), "target_demanda"] = 999999
        left = build_temporal_features(first)
        right = build_temporal_features(second)
        feature_columns = ["lag_1", "rolling_mean_3", "growth_1", "trend_3"]
        pd.testing.assert_frame_equal(left.loc[left.periodo.eq("2023-04"), feature_columns].reset_index(drop=True),
                                      right.loc[right.periodo.eq("2023-04"), feature_columns].reset_index(drop=True))

    def test_zero_growth_denominator_is_missing(self):
        periods = ["2023-01", "2023-02", "2023-03", "2023-04"]
        features = build_temporal_features(make_panel(periods, {"z": [0, 5, 10, 20]}))
        self.assertTrue(pd.isna(features.loc[features.periodo.eq("2023-03"), "growth_1"].iloc[0]))
        self.assertAlmostEqual(features.loc[features.periodo.eq("2023-04"), "growth_1"].iloc[0], 1.0)

    def test_calendar_encoding_is_known_at_t(self):
        periods = ["2024-01", "2024-02", "2024-03"]
        features = build_temporal_features(make_panel(periods, {"z": [1, 2, 3]}))
        feb = features.loc[features.periodo.eq("2024-02")].iloc[0]
        self.assertEqual(feb.month, 2)
        self.assertEqual(feb.year, 2024)
        self.assertAlmostEqual(feb.sin_month, 0.5)
        self.assertAlmostEqual(feb.cos_month, np.sqrt(3) / 2)


class RollingValidationTests(unittest.TestCase):
    def test_metric_definitions(self):
        actual = np.array([1.0, 2.0, 3.0])
        predicted = np.array([1.0, 3.0, 2.0])
        origin = np.array([1.0, 1.0, 1.0])
        metrics = calculate_metrics(actual, predicted, origin)
        self.assertAlmostEqual(metrics["MAE"], 2 / 3)
        self.assertAlmostEqual(metrics["RMSE"], np.sqrt(2 / 3))
        self.assertAlmostEqual(metrics["sMAPE"], (0 + 2 / 5 + 2 / 5) / 3 * 100)
        self.assertAlmostEqual(metrics["directional_accuracy"], 1.0)
        self.assertAlmostEqual(smape([0, 0], [0, 0]), 0)
        self.assertAlmostEqual(directional_accuracy([1, 1], [1, 1], [1, 1]), 1)

    def test_theil_sen_linear_forecast(self):
        history = pd.period_range("2023-01", periods=3, freq="M")
        self.assertAlmostEqual(_theil_sen_predict(history, np.array([1, 3, 5]), history[-1] + 1), 7)

    def test_common_splits_exclude_missing_and_use_same_zones(self):
        periods = pd.period_range("2023-01", "2025-03", freq="M").astype(str).tolist()
        values = list(range(1, len(periods) + 1))
        features = build_temporal_features(make_panel(
            periods, {"a": values, "b": [v * 2 for v in values], "c": [v * 3 for v in values]}))
        splits, metrics, result = evaluate_rolling(features, horizons=(1,))
        used = splits[splits.status.eq("USED")]
        self.assertGreater(len(used), 0)
        self.assertEqual(set(used.n_zones), {3})
        self.assertEqual(set(metrics.model), {"persistence", "seasonal_naive", "theil_sen"})
        self.assertEqual(len(result["predictions"]), len(used) * 3)

    def test_missing_target_is_never_recast_as_zero(self):
        periods = ["2023-01", "2023-02", "2023-03", "2023-04"]
        panel = make_panel(periods, {"z": [10, None, 30, 40]})
        features = build_temporal_features(panel)
        self.assertTrue(pd.isna(features.loc[features.periodo.eq("2023-02"), "viajes_total"].iloc[0]))
        self.assertTrue(pd.isna(features.loc[features.periodo.eq("2023-03"), "lag_1"].iloc[0]))


if __name__ == "__main__":
    unittest.main()
