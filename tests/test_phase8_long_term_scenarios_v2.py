"""Tests de Fase 8 para escenarios de largo plazo.

Ejecutar después de generar:
python -B -m src.models.long_term_scenarios_v2
"""

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.long_term_scenarios_v2 import (
    HORIZONS,
    MIN_GROWTH_POINTS,
    build_long_term_scenarios,
    compute_yoy_log_growth,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "processed" / "long_term_scenarios_v2.csv"


class Phase8LongTermScenarioTests(unittest.TestCase):

    def test_exact_12_month_growth_does_not_skip_calendar_gap(self):
        panel = pd.DataFrame(
            {
                "zone_id": ["z1", "z1", "z1"],
                "periodo": ["2024-01", "2024-12", "2025-01"],
                "viajes_total": [100.0, 999.0, 110.0],
            }
        )

        growth = compute_yoy_log_growth(panel)

        self.assertEqual(len(growth), 1)
        self.assertEqual(str(growth.iloc[0]["periodo"]), "2025-01")
        self.assertAlmostEqual(
            growth.iloc[0]["annual_growth_pct"],
            10.0,
            places=8,
        )

    def test_synthetic_scenarios_are_ordered_and_scenario_only(self):
        months = pd.period_range(
            "2023-01",
            "2026-08",
            freq="M",
        )

        rows = []

        for zone, base, annual_rate in [
            ("z1", 1000.0, 0.08),
            ("z2", 2000.0, -0.03),
        ]:
            for i, period in enumerate(months):
                value = base * (
                    (1 + annual_rate)
                    ** (i / 12)
                )

                rows.append(
                    {
                        "zone_id": zone,
                        "periodo": str(period),
                        "viajes_total": value,
                    }
                )

        panel = pd.DataFrame(rows)

        current = pd.DataFrame(
            {
                "zone_id": ["z1", "z2"],
                "colonia": ["Uno", "Dos"],
                "alcaldia": ["Cuauhtemoc", "Coyoacan"],
                "origin_period": ["2026-08", "2026-08"],
                "horizon_months": [12, 12],
                "target_period": ["2027-08", "2027-08"],
                "forecast_value": [1200.0, 1800.0],
            }
        )

        output, metadata = build_long_term_scenarios(
            panel,
            current,
            min_points=4,
        )

        self.assertEqual(
            set(output["horizon_months"]),
            set(HORIZONS),
        )

        self.assertTrue(
            output["validation_status"]
            .eq("SCENARIO_ONLY")
            .all()
        )

        self.assertFalse(
            output["is_validated_forecast"].any()
        )

        ready = output[
            output["scenario_status"].eq("READY")
        ]

        self.assertTrue(
            (
                ready["scenario_low"]
                <= ready["scenario_base"]
            ).all()
        )

        self.assertTrue(
            (
                ready["scenario_base"]
                <= ready["scenario_high"]
            ).all()
        )

        self.assertTrue(
            ready[
                [
                    "scenario_low",
                    "scenario_base",
                    "scenario_high",
                ]
            ]
            .ge(0)
            .all()
            .all()
        )

        self.assertTrue(
            metadata["not_a_forecast_interval"]
        )

        self.assertTrue(
            metadata["not_p10_p50_p90"]
        )

    def test_saved_artifact_contract_if_present(self):
        if not OUTPUT.exists():
            self.skipTest(
                "Genera long_term_scenarios_v2.csv antes de validar el artefacto"
            )

        frame = pd.read_csv(
            OUTPUT,
            dtype={"zone_id": str},
        )

        self.assertFalse(
            frame.duplicated(
                [
                    "zone_id",
                    "horizon_months",
                ]
            ).any()
        )

        self.assertEqual(
            set(frame["horizon_months"].unique()),
            set(HORIZONS),
        )

        self.assertTrue(
            frame["scenario_role"]
            .eq("SCENARIO_ONLY")
            .all()
        )

        self.assertTrue(
            frame["validation_status"]
            .eq("SCENARIO_ONLY")
            .all()
        )

        ready = frame[
            frame["scenario_status"].eq("READY")
        ]

        self.assertTrue(
            (
                ready["scenario_low"]
                <= ready["scenario_base"]
            ).all()
        )

        self.assertTrue(
            (
                ready["scenario_base"]
                <= ready["scenario_high"]
            ).all()
        )

        self.assertTrue(
            np.isfinite(
                ready[
                    [
                        "scenario_low",
                        "scenario_base",
                        "scenario_high",
                    ]
                ].to_numpy()
            ).all()
        )


if __name__ == "__main__":
    unittest.main()
