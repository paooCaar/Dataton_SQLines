import hashlib
import subprocess
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.app.ux_signals_v2 import (
    classify_change, observed_trend, scenario_display, MAP_EXPLANATIONS,
    SCENARIO_EXPLANATIONS, LONG_MAP_EXPLANATIONS,
)

ROOT = Path(__file__).resolve().parents[1]


def history():
    return pd.DataFrame({"zone_id": ["z"] * 4,
        "periodo": ["2024-07", "2024-08", "2025-08", "2025-09"],
        "viajes_total": [99.0, 100.0, 110.0, 1e6], "data_status": ["OBSERVED"] * 4,
        "target_available_no_earlier_than": ["2024-08-01", "2024-09-01", "2025-09-01", "2025-10-01"]})


class UXSignalTests(unittest.TestCase):
    def trend(self, panel, origin="2025-08"):
        return observed_trend(panel, pd.DataFrame({"zone_id": ["z"], "origin_period": [origin]})).iloc[0]

    def test_no_future_activity_used(self):
        panel = history()
        expected = self.trend(panel)
        panel.loc[3, "viajes_total"] = -1e20
        pd.testing.assert_series_equal(self.trend(panel), expected)
        self.assertEqual(expected.trend_pct, 10)
        self.assertEqual(expected.trend_category, "Subiendo")

    def test_gap_not_replaced_by_previous_row(self):
        row = self.trend(history().drop(index=1))
        self.assertTrue(pd.isna(row.trend_pct))
        self.assertEqual(row.trend_category, "Sin dato")

    def test_missing_unknown_zero_denominator_and_late_publication(self):
        for column, value in [("viajes_total", np.nan), ("viajes_total", 0),
                              ("data_status", "UNKNOWN_ACTIVITY_STATUS"), ("data_status", "MISSING_DATA"),
                              ("target_available_no_earlier_than", "2025-10-01")]:
            panel = history()
            panel.loc[1, column] = value
            with self.subTest(column=column, value=value):
                row = self.trend(panel)
                self.assertTrue(pd.isna(row.trend_pct))
                self.assertEqual(row.trend_category, "Sin dato")

    def test_observed_zero_numerator_is_valid(self):
        panel = history()
        panel.loc[2, "viajes_total"] = 0
        panel.loc[2, "data_status"] = "ZERO_DEMAND"
        self.assertEqual(self.trend(panel).trend_pct, -100)

    def test_distinct_origins_stay_separate(self):
        result = observed_trend(history(), pd.DataFrame({"zone_id": ["z", "z"], "origin_period": ["2025-08", "2025-09"]}))
        self.assertEqual(result.iloc[0].trend_pct, 10)
        self.assertTrue(pd.isna(result.iloc[1].trend_pct))

    def test_threshold_includes_both_boundaries_in_stable(self):
        result = classify_change(pd.Series([-5.01, -5, 0, 5, 5.01, np.nan, np.inf]))
        self.assertEqual(result.tolist(), ["Bajando", "Estable", "Estable", "Estable", "Subiendo", "Sin dato", "Sin dato"])

    def test_scenario_change_direction_and_missing_without_mutation(self):
        frame = pd.DataFrame({"anchor_12m_value": [100, 100, 100, 100, 100, 0, np.nan],
            "scenario_low": [80, 95, 100, 105, 120, 100, 100], "traffic_low_adjustment_pct": [-1] * 7})
        original = frame.copy(deep=True)
        result = scenario_display(frame, "Bajo")
        np.testing.assert_allclose(result.scenario_change_pct[:5], [-20, -5, 0, 5, 20])
        self.assertEqual(result.scenario_direction.tolist(), ["DISMINUCIÓN", "ESTABLE", "ESTABLE", "ESTABLE", "AUMENTO", "Sin dato", "Sin dato"])
        self.assertTrue(result.scenario_change_pct.iloc[5:].isna().all())
        pd.testing.assert_frame_equal(frame, original)

    def test_models_artifacts_score_and_existing_tests_unchanged(self):
        baseline = "9899c41"
        paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", baseline,
            "data", "src/models", "src/data", "src/app/algoritmo_puntuacion.py", "src/app/app.py", "tests"], cwd=ROOT, text=True).splitlines()
        for path in paths:
            with self.subTest(path=path):
                expected = subprocess.check_output(["git", "show", f"{baseline}:{path}"], cwd=ROOT)
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).digest(), hashlib.sha256(expected).digest())


class UXNavigationTests(unittest.TestCase):
    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(ROOT / "src/app/app_v2.py")).run(timeout=30)

    def select(self, app, label):
        return next(widget for widget in app.selectbox if widget.label == label)

    def test_short_navigation_primary_technical_and_dynamic_explanations(self):
        app = self.app()
        for h in (1, 3, 6, 12):
            self.select(app, "Horizonte").set_value(h).run(timeout=30)
            for choice in ("Actividad prevista", "Incertidumbre", "Tendencia reciente"):
                self.select(app, "Vista principal del mapa").set_value(choice).run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(self.select(app, "Mostrar en mapa").value, choice)
                self.assertTrue(any(c.value == MAP_EXPLANATIONS[choice] for c in app.caption))
                self.assertFalse(any("¿Qué aporta el tráfico?" in s.value for s in app.subheader))
        for choice in ("Cambio esperado", "Dirección", "Opportunity Score"):
            self.select(app, "Mostrar en mapa").set_value(choice).run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertIsNone(self.select(app, "Vista principal del mapa").value)
            self.assertTrue(any(c.value == MAP_EXPLANATIONS[choice] for c in app.caption))
        self.select(app, "Vista principal del mapa").set_value("Actividad prevista").run(timeout=30)
        self.assertEqual(self.select(app, "Mostrar en mapa").value, "Actividad prevista")

    def test_long_navigation_four_maps_and_scenario_explanations(self):
        app = self.app()
        for h in (36, 60):
            self.select(app, "Horizonte").set_value(h).run(timeout=30)
            for name in ("Bajo", "Base", "Alto"):
                next(r for r in app.radio if r.label == "¿Qué escenario quieres ver?").set_value(name).run(timeout=30)
                self.assertTrue(any(s.value == SCENARIO_EXPLANATIONS[name] for s in app.info))
                for choice in LONG_MAP_EXPLANATIONS:
                    self.select(app, "Mostrar en mapa de escenarios").set_value(choice).run(timeout=30)
                    self.assertEqual(len(app.exception), 0)
                    self.assertEqual(len(app.metric), 0)
                    self.assertTrue(any("SCENARIO_ONLY" in s.value for s in app.subheader))
                    self.assertTrue(any("is_validated_forecast = False" in c.value for c in app.caption))

    def test_no_geometry_and_outside_coverage_in_both_products(self):
        app = self.app()
        catalog = pd.read_csv(ROOT / "data/processed/catalogo_zonas_v2.csv")
        zone = catalog[~catalog.geometry_available].zone_id.iloc[0]
        for h in (1, 36):
            self.select(app, "Horizonte").set_value(h).run(timeout=30)
            self.select(app, "Colonia").set_value(zone).run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Sin geometría" in s.value for s in app.info))
            self.select(app, "Alcaldía").set_value("Milpa Alta").run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("suficiente historia" in s.value for s in app.warning))
            self.assertEqual(len(app.metric), 0)
            self.select(app, "Alcaldía").set_value("Todas").run(timeout=30)

    def test_trend_hover_contains_observed_value_and_category(self):
        from src.app import app_v2
        inputs = app_v2.load_inputs()
        origins = inputs["current"][inputs["current"].horizon_months.eq(1)][["zone_id", "origin_period"]]
        frame = inputs["catalog"][["zone_id", "colonia", "alcaldia"]].merge(observed_trend(app_v2.load_observed_history(), origins), on="zone_id")
        ids = app_v2.geometry_zone_ids(inputs["geometry"])
        frame["map_status"] = frame.zone_id.map(lambda z: "Disponible" if z in ids else "Sin geometría")
        fig = app_v2.short_term_map(frame, inputs["geometry"], "Tendencia reciente")
        for trace in fig.data:
            self.assertIn("Cambio interanual", trace.hovertemplate)
            self.assertIn("Tendencia observada", trace.hovertemplate)
            self.assertIn("Alcaldía", trace.hovertemplate)


if __name__ == "__main__":
    unittest.main()
