"""Tests del ajuste TomTom en escenarios ECOBICI de 36/60 meses."""

import unittest
import ast
import hashlib
import io
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.tomtom_v2 import (
    TRAFFIC_PASS_THROUGH,
    build_traffic_scenario_bundle,
    summarize_tomtom,
    traffic_activity_multiplier,
    load_tomtom_traffic_index,
    projected_congestion,
)
from src.models.long_term_scenarios_v2 import (
    build_long_term_scenarios,
)


def synthetic_tomtom():
    return pd.DataFrame(
        {
            "year": [2024, 2025],
            "congestion_level_pct": [79.5, 75.9],
            "yoy_change_pp": [np.nan, -3.6],
            "observation_type": [
                "annual_comparable",
                "annual_comparable",
            ],
            "is_derived": [True, False],
            "source_note": ["derived", "observed"],
            "source_url": ["x", "x"],
        }
    )


class TomTomTrafficScenarioTests(unittest.TestCase):

    def test_latest_signal_and_symmetric_stress(self):
        summary = summarize_tomtom(
            synthetic_tomtom()
        )

        self.assertEqual(
            summary.latest_year,
            2025,
        )

        self.assertAlmostEqual(
            summary.latest_congestion_pct,
            75.9,
        )

        self.assertAlmostEqual(
            summary.recent_change_pp,
            -3.6,
        )

        self.assertAlmostEqual(
            summary.stress_magnitude_pp_per_year,
            3.6,
        )

    def test_bundle_base_is_neutral_low_down_high_up(self):
        bundle = build_traffic_scenario_bundle(
            synthetic_tomtom(),
            years_after_anchor=4,
        )

        self.assertAlmostEqual(
            bundle["traffic_base_multiplier"],
            1.0,
        )

        self.assertLess(
            bundle["traffic_low_multiplier"],
            1.0,
        )

        self.assertGreater(
            bundle["traffic_high_multiplier"],
            1.0,
        )

        self.assertAlmostEqual(
            bundle[
                "traffic_low_target_congestion_pct"
            ],
            61.5,
            places=8,
        )

        self.assertAlmostEqual(
            bundle[
                "traffic_high_target_congestion_pct"
            ],
            90.3,
            places=8,
        )

    def test_multiplier_is_conservative_and_monotonic(self):
        low = traffic_activity_multiplier(
            75.9,
            61.5,
            pass_through=TRAFFIC_PASS_THROUGH,
        )

        base = traffic_activity_multiplier(
            75.9,
            75.9,
            pass_through=TRAFFIC_PASS_THROUGH,
        )

        high = traffic_activity_multiplier(
            75.9,
            90.3,
            pass_through=TRAFFIC_PASS_THROUGH,
        )

        self.assertLess(
            low,
            base,
        )

        self.assertAlmostEqual(
            base,
            1.0,
        )

        self.assertGreater(
            high,
            base,
        )

        # El pass-through deliberadamente pequeño evita que TomTom domine.
        self.assertLess(
            high,
            1.05,
        )

    def test_long_term_tomtom_changes_low_and_high_but_not_base(self):
        months = pd.period_range(
            "2023-01",
            "2026-08",
            freq="M",
        )

        panel_rows = []

        for zone, base_value, annual_rate in [
            ("z1", 1000.0, 0.08),
            ("z2", 2000.0, -0.03),
        ]:
            for i, period in enumerate(months):
                panel_rows.append(
                    {
                        "zone_id": zone,
                        "periodo": str(period),
                        "viajes_total": (
                            base_value
                            * (
                                (1 + annual_rate)
                                ** (i / 12)
                            )
                        ),
                    }
                )

        panel = pd.DataFrame(
            panel_rows
        )

        current = pd.DataFrame(
            {
                "zone_id": ["z1", "z2"],
                "colonia": ["Uno", "Dos"],
                "alcaldia": [
                    "Cuauhtemoc",
                    "Coyoacan",
                ],
                "origin_period": [
                    "2026-08",
                    "2026-08",
                ],
                "horizon_months": [12, 12],
                "target_period": [
                    "2027-08",
                    "2027-08",
                ],
                "forecast_value": [
                    1200.0,
                    1800.0,
                ],
            }
        )

        no_traffic, _ = (
            build_long_term_scenarios(
                panel,
                current,
                tomtom=None,
                min_points=4,
            )
        )

        with_traffic, metadata = (
            build_long_term_scenarios(
                panel,
                current,
                tomtom=synthetic_tomtom(),
                min_points=4,
            )
        )

        joined = no_traffic.merge(
            with_traffic,
            on=[
                "zone_id",
                "horizon_months",
            ],
            suffixes=(
                "_plain",
                "_traffic",
            ),
        )

        self.assertTrue(
            (
                joined[
                    "scenario_low_traffic"
                ]
                < joined[
                    "scenario_low_plain"
                ]
            ).all()
        )

        self.assertTrue(
            np.allclose(
                joined[
                    "scenario_base_traffic"
                ],
                joined[
                    "scenario_base_plain"
                ],
            )
        )

        self.assertTrue(
            (
                joined[
                    "scenario_high_traffic"
                ]
                > joined[
                    "scenario_high_plain"
                ]
            ).all()
        )

        self.assertTrue(
            metadata["tomtom_enabled"]
        )

        self.assertAlmostEqual(
            metadata[
                "tomtom_methodology"
            ][
                "pass_through"
            ],
            TRAFFIC_PASS_THROUGH,
        )

        self.assertTrue(
            with_traffic[
                "validation_status"
            ]
            .eq("SCENARIO_ONLY")
            .all()
        )


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/processed"
BASELINE = "f7c98b7"


class TomTomIntegrationGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = pd.read_csv(DATA / "panel_demanda_v2.csv")
        cls.current = pd.read_csv(DATA / "current_forecast_product_v2.csv")
        cls.tomtom = load_tomtom_traffic_index()
        cls.plain, _ = build_long_term_scenarios(cls.panel, cls.current)
        cls.traffic, _ = build_long_term_scenarios(cls.panel, cls.current, tomtom=cls.tomtom)

    def test_csv_source_and_derived_year(self):
        summary = summarize_tomtom(self.tomtom)
        self.assertEqual((summary.latest_year, summary.latest_congestion_pct, summary.recent_change_pp), (2025, 75.9, -3.6))
        previous = self.tomtom.set_index("year").loc[2024]
        self.assertTrue(previous.is_derived)
        self.assertAlmostEqual(previous.congestion_level_pct, 79.5)

    def test_invalid_source_rejected_without_silent_dropping(self):
        for column, value in [("congestion_level_pct", np.inf), ("congestion_level_pct", -1),
                              ("year", 2025.5), ("year", np.nan), ("yoy_change_pp", np.nan),
                              ("observation_type", "old_edition"), ("is_derived", "unknown"),
                              ("source_note", ""), ("yoy_change_pp", 3.6)]:
            changed = self.tomtom.copy().astype(object)
            changed.loc[1, column] = value
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                summarize_tomtom(changed)
        with self.assertRaises(ValueError):
            summarize_tomtom(pd.concat([self.tomtom, self.tomtom]))

    def test_projection_floor_and_nonfinite_inputs(self):
        self.assertEqual(projected_congestion(1, -3.6, 4), 0)
        self.assertGreater(projected_congestion(110, 3.6, 4), 100)
        for value in (np.nan, np.inf, -1):
            with self.assertRaises(ValueError):
                projected_congestion(75.9, -3.6, value)
            with self.assertRaises(ValueError):
                traffic_activity_multiplier(75.9, value)

    def test_pretraffic_values_and_growth_match_phase8(self):
        original = subprocess.check_output(["git", "show", f"{BASELINE}:data/processed/long_term_scenarios_v2.csv"], cwd=ROOT)
        previous = pd.read_csv(io.BytesIO(original))
        for name in ("low", "base", "high"):
            np.testing.assert_allclose(self.traffic[f"scenario_{name}_before_traffic"], previous[f"scenario_{name}"], equal_nan=True)
            np.testing.assert_allclose(self.plain[f"scenario_{name}"], previous[f"scenario_{name}"], equal_nan=True)
        old_code = ast.parse(subprocess.check_output(["git", "show", f"{BASELINE}:src/models/long_term_scenarios_v2.py"], cwd=ROOT, text=True))
        new_code = ast.parse((ROOT / "src/models/long_term_scenarios_v2.py").read_text())
        for name in ("compute_yoy_log_growth", "summarize_growth"):
            old = next(n for n in old_code.body if isinstance(n, ast.FunctionDef) and n.name == name)
            new = next(n for n in new_code.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(ast.dump(old), ast.dump(new))

    def test_citywide_multiplier_preserves_spatial_ranking(self):
        for _, rows in self.traffic.groupby("horizon_months"):
            for name in ("low", "base", "high"):
                self.assertEqual(rows[f"traffic_{name}_multiplier"].nunique(), 1)
                pd.testing.assert_series_equal(rows[f"scenario_{name}"].rank(), rows[f"scenario_{name}_before_traffic"].rank(), check_names=False)

    def test_missing_history_stays_missing_and_order_is_preserved(self):
        ready = self.traffic.scenario_status.eq("READY")
        columns = ["scenario_low", "scenario_base", "scenario_high"]
        self.assertTrue(self.traffic.loc[~ready, columns].isna().all().all())
        self.assertTrue(np.isfinite(self.traffic.loc[ready, columns]).all().all())
        self.assertTrue(self.traffic.loc[ready, columns].ge(0).all().all())
        self.assertTrue(self.traffic.loc[ready, "scenario_low"].le(self.traffic.loc[ready, "scenario_base"]).all())
        self.assertTrue(self.traffic.loc[ready, "scenario_base"].le(self.traffic.loc[ready, "scenario_high"]).all())
        self.assertTrue(self.traffic.scenario_role.eq("SCENARIO_ONLY").all())
        self.assertFalse(self.traffic.is_validated_forecast.any())

    def test_saved_output_is_reproducible_and_metadata_matches(self):
        saved = pd.read_csv(DATA / "long_term_scenarios_v2.csv")
        pd.testing.assert_frame_equal(saved, self.traffic, check_dtype=False)
        meta = json.loads((DATA / "long_term_scenarios_v2.metadata.json").read_text())
        for group in ("input_sha256", "implementation_sha256"):
            for relative, expected in meta[group].items():
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)
        self.assertEqual(hashlib.sha256((DATA / "long_term_scenarios_v2.csv").read_bytes()).hexdigest(), meta["output_sha256"])

    def test_short_forecast_legacy_and_existing_tests_unchanged(self):
        paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE, "data/processed", "tests", "src/app/app.py", "src/app/algoritmo_puntuacion.py", "src/models/current_forecast_v2.py", "src/app/product_contract_v2.py"], cwd=ROOT, text=True).splitlines()
        exceptions = {
            "data/processed/long_term_scenarios_v2.csv",
            "data/processed/long_term_scenarios_v2.metadata.json",
            "tests/test_ux_product_clarity_v2.py",
            "tests/test_tomtom_long_term_v2.py",
            "tests/test_phase7_app_contract_v2.py",
        }
        for path in paths:
            if path not in exceptions:
                expected = subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT)
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).digest(), hashlib.sha256(expected).digest(), path)

    def test_app_tomtom_only_long_term_and_all_selected_scenarios(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "src/app/app_v2.py")).run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any("¿Qué aporta el tráfico?" in s.value for s in app.subheader))
        app._page_hash = next(key for key, entry in app._registered_pages.items()
                              if entry["url_pathname"] == "futuro")
        app.run(timeout=30)
        for horizon in (36, 60):
            next(s for s in app.button_group if s.label == "Horizonte").set_value(horizon).run(timeout=30)
            for selected in ("Bajo", "Base", "Alto"):
                next(r for r in app.button_group if r.label == "¿Qué escenario quieres ver?").set_value(selected).run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.metric), 0)
                self.assertEqual(len(app.get("plotly_chart")), 1)
                self.assertFalse(any("TomTom" in s.value for s in app.info))


if __name__ == "__main__":
    unittest.main()
