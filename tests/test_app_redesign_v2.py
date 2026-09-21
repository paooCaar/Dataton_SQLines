"""La app pública debe seguir siendo simple sin cambiar sus fuentes de datos."""

import unittest
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
from streamlit.testing.v1 import AppTest

from src.app import app_v2
from src.app.product_contract_v2 import load_inputs


APP = Path(__file__).resolve().parents[1] / "src/app/app_v2.py"


def control(app, label):
    return next(widget for widget in app.button_group if widget.label == label)


def select(app, label):
    return next(widget for widget in app.selectbox if widget.label == label)


def future_page(app):
    # AppTest.switch_page no admite st.Page definido con una función.
    app._page_hash = next(
        key for key, entry in app._registered_pages.items()
        if entry["url_pathname"] == "futuro"
    )
    return app.run(timeout=30)


class PublicAppTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_file(str(APP)).run(timeout=30)
        self.assertFalse(app.exception)
        return app

    def test_exactly_two_pages_and_map_first(self):
        app = self.app()
        self.assertEqual(
            [entry["page_name"] for entry in app._registered_pages.values()],
            ["Panorama actual", "A futuro"],
        )
        self.assertEqual(len(app.get("plotly_chart")), 1)
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(len(app.dataframe), 0)
        self.assertFalse(app.button_group)
        self.assertEqual([widget.label for widget in app.selectbox], ["Alcaldía", "Colonia"])

        future_page(app)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("plotly_chart")), 1)
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(control(app, "Horizonte").value, 12)
        self.assertFalse(any(widget.label == "¿Qué escenario quieres ver?" for widget in app.button_group))

    def test_future_ranking_has_ten_ordered_zones_and_no_fake_probability(self):
        inputs = load_inputs()
        frame = app_v2.future_demand_frame(inputs, 12, "Base")
        ranked = app_v2.expansion_ranking(inputs["catalog"], frame.zone_id, 1)
        self.assertEqual(ranked.puesto.tolist(), list(range(1, 11)))
        self.assertTrue(ranked.opportunity_score.is_monotonic_decreasing)

        app = future_page(self.app())
        table = app.dataframe[0].value
        self.assertEqual(len(table), 10)
        self.assertEqual(table.columns.tolist(), ["#", "Colonia", "Alcaldía", "Potencial", "Nuevas estimadas"])
        self.assertEqual(table["#"].tolist(), list(range(1, 11)))
        self.assertTrue(table["Nuevas estimadas"].eq(0).all())
        self.assertTrue(any("no es una probabilidad real" in item.value for item in app.caption))
        self.assertFalse(any("Probabilidad" in column for column in table.columns))

        select(app, "Alcaldía").set_value("Benito Juarez").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(app.dataframe[0].value["Alcaldía"].eq("Benito Juárez").all())

        app = future_page(self.app())
        control(app, "Horizonte").set_value(36).run(timeout=30)
        result = app.dataframe[0].value
        values = result["Nuevas estimadas"].tolist()
        self.assertEqual(values, sorted(values, reverse=True))

    def test_current_map_uses_latest_observed_month_only(self):
        inputs = load_inputs()
        history = app_v2.load_observed_history()
        frame = app_v2.current_demand_frame(inputs, history)
        origin = inputs["metadata"]["common_origin_period"]
        expected = history[history.periodo.eq(origin)].set_index("zone_id").viajes_total
        pd.testing.assert_series_equal(
            frame.set_index("zone_id").map_value.sort_index(),
            expected.loc[frame.zone_id].sort_index().rename("map_value"),
            check_names=True,
        )
        self.assertTrue(frame.target_period.eq(origin).all())
        self.assertEqual(len(frame), len(inputs["geometry"]["features"]))

    def test_current_map_uses_colorblind_friendly_multihue_scale(self):
        self.assertEqual(app_v2.ACTIVITY_GRADIENT, list(px.colors.sequential.Viridis))
        self.assertNotEqual(app_v2.ACTIVITY_GRADIENT[0], app_v2.ACTIVITY_GRADIENT[-1])
        inputs = load_inputs()
        actual = app_v2.current_demand_frame(inputs, app_v2.load_observed_history())
        figure = app_v2.simple_demand_map(actual, inputs["geometry"], title="Actividad")
        colors = [color for _, color in figure.layout.coloraxis.colorscale]
        self.assertEqual(colors, app_v2.ACTIVITY_GRADIENT)

    def test_future_color_shows_change_on_one_fixed_high_contrast_scale(self):
        inputs = load_inputs()
        scenarios = app_v2.load_long_term_scenarios()
        median_changes = []
        for horizon in (12, 36, 60):
            frame = app_v2.future_demand_frame(inputs, horizon, "Base", scenarios)
            figure = app_v2.simple_demand_map(
                frame, inputs["geometry"], title="Cambio", future=True,
            )
            self.assertEqual(figure.layout.coloraxis.cmin, -35)
            self.assertEqual(figure.layout.coloraxis.cmax, 35)
            self.assertEqual(list(figure.layout.coloraxis.colorscale), app_v2.CHANGE_GRADIENT)
            expected = 100 * (frame.map_value / frame.reference_value - 1)
            actual = pd.Series(figure.data[0].z)
            self.assertAlmostEqual(actual.median(), expected.dropna().median(), places=5)
            median_changes.append(actual.median())
        self.assertNotEqual(median_changes[0], 0)
        self.assertNotEqual(median_changes[0], median_changes[1])
        self.assertLess(median_changes[2], median_changes[1])

    def test_current_map_has_real_station_points_with_toggle(self):
        stations = app_v2.load_current_station_points()
        activity = app_v2.load_station_activity()
        self.assertEqual(activity.periodo.unique().tolist(), ["2026-01"])
        self.assertEqual(len(activity), len(stations))
        self.assertEqual(activity.viajes_total.gt(0).sum(), 676)
        joined = app_v2.station_points_with_activity(stations, activity, "2026-08")
        self.assertEqual(len(joined), len(stations))
        self.assertEqual(joined.viajes_total.sum(), activity.viajes_total.sum())
        self.assertEqual(len(stations), 677)
        self.assertTrue(stations.num_cicloe.is_unique)
        self.assertTrue(stations.latitud.between(19, 20).all())
        self.assertTrue(stations.longitud.between(-100, -98).all())

        app = self.app()
        traces_with_stations = json.loads(app.get("plotly_chart")[0].proto.spec)["data"]
        self.assertEqual(sum(trace["type"] == "scattermap" for trace in traces_with_stations), 2)
        station_labels = next(trace["text"] for trace in traces_with_stations if trace.get("text"))
        self.assertTrue(any("Movimientos registrados en 2026-01" in label for label in station_labels))
        toggle = next(widget for widget in app.get("toggle") if widget.label == "Mostrar estaciones ECOBICI")
        toggle.set_value(False).run(timeout=30)
        self.assertFalse(app.exception)
        traces_without_stations = json.loads(app.get("plotly_chart")[0].proto.spec)["data"]
        self.assertEqual(sum(trace["type"] == "scattermap" for trace in traces_without_stations), 0)

    def test_rule_of_three_counts_only_additional_stations(self):
        actual = pd.Series([2, 2, 2, 2, 2])
        demand = pd.Series([100, 100, 100, 0, 100])
        future = pd.Series([151, 100, 75, 150, pd.NA])
        result = app_v2.estimate_additional_stations(actual, demand, future)
        self.assertEqual(result.iloc[:3].tolist(), [2, 0, 0])
        self.assertTrue(pd.isna(result.iloc[3]))
        self.assertTrue(pd.isna(result.iloc[4]))

        app = future_page(self.app())
        control(app, "Horizonte").set_value(36).run(timeout=30)
        base = app.dataframe[0].value["Nuevas estimadas"].tolist()
        control(app, "¿Qué escenario quieres ver?").set_value("Alto").run(timeout=30)
        high = app.dataframe[0].value["Nuevas estimadas"].tolist()
        self.assertFalse(app.exception)
        self.assertGreater(sum(high), sum(base))

    def test_future_map_uses_published_1_3_5_year_values(self):
        inputs = load_inputs()
        scenarios = app_v2.load_long_term_scenarios()
        for horizon in (12, 36, 60):
            for scenario in (("Base",) if horizon == 12 else ("Bajo", "Base", "Alto")):
                with self.subTest(horizon=horizon, scenario=scenario):
                    frame = app_v2.future_demand_frame(inputs, horizon, scenario, scenarios)
                    if horizon == 12:
                        trends, _ = app_v2.load_latest_annual_trend()
                        reference = inputs["current"][inputs["current"].horizon_months.eq(12)].set_index("zone_id").reference_value
                        source = (reference * (1 + trends.set_index("zone_id").growth_12)).rename("map_value")
                    else:
                        column = app_v2.SCENARIO_OPTIONS[scenario]["value"]
                        source = scenarios[scenarios.horizon_months.eq(horizon)].set_index("zone_id")[column]
                    pd.testing.assert_series_equal(frame.set_index("zone_id").map_value.sort_index(), source.loc[frame.zone_id].sort_index().rename("map_value"), check_names=True)

        one_year = app_v2.future_demand_frame(inputs, 12, "Base")
        self.assertGreater((one_year.map_value != one_year.reference_value).sum(), 0)

    def test_future_controls_show_only_1_3_5_years(self):
        app = future_page(self.app())
        for horizon in (12, 36, 60):
            control(app, "Horizonte").set_value(horizon).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("plotly_chart")), 1)
            self.assertEqual(len(app.metric), 0)
            if horizon == 12:
                self.assertFalse(any(widget.label == "¿Qué escenario quieres ver?" for widget in app.button_group))
            else:
                for scenario in ("Bajo", "Base", "Alto"):
                    control(app, "¿Qué escenario quieres ver?").set_value(scenario).run(timeout=30)
                    self.assertFalse(app.exception)
                    self.assertEqual(len(app.get("plotly_chart")), 1)

    def test_no_map_for_uncovered_municipality(self):
        app = self.app()
        select(app, "Alcaldía").set_value("Milpa Alta").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("plotly_chart")), 0)
        self.assertTrue(app.warning)

        future_page(app)
        self.assertFalse(app.exception)
        select(app, "Alcaldía").set_value("Milpa Alta").run(timeout=30)
        self.assertEqual(len(app.get("plotly_chart")), 0)
        self.assertTrue(app.warning)


if __name__ == "__main__":
    unittest.main()
