"""Contract, availability, comparability and reproducibility safeguards for Phase 4."""
import json
import unittest
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from src.data.ecobici_v2 import sha256_file
from src.features.features_temporales_v2 import build_temporal_features
from src.features.model_matrices_v2 import (
    TEMPORAL_CANDIDATES, SPATIAL_FEATURES, candidate_matrix, choose_temporal_features,
    feature_availability, model_matrices, origin_features, review_overlaps, select_X,
)
from src.models.lightgbm_compare_v2 import (
    ROOT, PARAMS, MODELS, SCOPES, eligible_masks, improvement_pct, training_rows,
    run_models, aggregate_metrics, metrics_for,
)


def fixture():
    periods = pd.period_range('2023-01', '2025-12', freq='M')
    panel = pd.DataFrame([{'zone_id': z, 'periodo': str(p), 'fecha': p.to_timestamp(),
                           'viajes_total': float((i + 1) * 100 + t * 7 + (t % 3) * 11),
                           'data_status': 'OBSERVED',
                           'target_available_no_earlier_than': (p + 1).to_timestamp().isoformat()}
                          for i, z in enumerate('ABC') for t, p in enumerate(periods)])
    neighbors = pd.DataFrame([{'zone_id': a, 'neighbor_zone_id': b, 'relation_type': 'queen',
                              'weight_raw': 1.0, 'weight_normalized': 1.0, 'distance_centroid_m': 200.0}
                             for a, b in [('A', 'B'), ('B', 'A')]])
    splits = pd.DataFrame([{'split_id': f'h{h}_2024-07', 'horizon': h, 'origin_period': '2024-07',
                           'target_period': str(pd.Period('2024-07') + h), 'status': 'USED'} for h in [1, 3]])
    return panel, neighbors, splits


class Phase4ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel, cls.neighbors, cls.splits = fixture()
        cls.candidates = candidate_matrix(cls.panel, cls.neighbors, horizons=(1, 3))
        cls.selected, cls.selection = choose_temporal_features(cls.candidates, cls.splits)
        cls.matrices, cls.sets = model_matrices(cls.candidates, cls.selected)
        cls.registry = feature_availability(cls.candidates.columns.tolist() + ['n_estaciones_colonia_catalogo', 'colonia', 'alcaldia'], cls.selected)

    def test_feature_sets_nested_and_same_targets(self):
        a, b = (self.matrices[m] for m in ['LGBM_TEMPORAL', 'LGBM_TEMPORAL_SPATIAL'])
        pd.testing.assert_frame_equal(a, b[a.columns])
        self.assertTrue(set(self.sets['LGBM_TEMPORAL']) < set(self.sets['LGBM_TEMPORAL_SPATIAL']))

    def test_identifiers_and_future_label_never_predictors(self):
        blocked = {'zone_id', 'colonia', 'alcaldia', 'horizon', 'target_viajes_total', 'target_period', 'label_available_no_earlier_than'}
        for model, features in self.sets.items():
            self.assertFalse(set(features) & blocked)
            X = select_X(self.matrices[model], features, self.registry)
            self.assertEqual(X.columns.tolist(), features)
        with self.assertRaises(ValueError):
            select_X(self.candidates, ['target_viajes_total'], self.registry)

    def test_unsafe_features_excluded(self):
        unsafe = self.registry[~self.registry.historical_safe].feature_name
        self.assertFalse(set(unsafe) & set(self.sets['LGBM_TEMPORAL_SPATIAL']))
        with self.assertRaises(ValueError):
            select_X(self.candidates.assign(n_estaciones_colonia_catalogo=10), ['n_estaciones_colonia_catalogo'], self.registry)

    def test_future_neighbor_targets_do_not_change_origin_features(self):
        before = origin_features(self.panel, self.neighbors, '2024-07')
        panel = self.panel.copy()
        panel.loc[panel.periodo > '2024-07', 'viajes_total'] = 1e10
        after = origin_features(panel, self.neighbors, '2024-07')
        pd.testing.assert_frame_equal(before, after)
        # Applies to h=12 just as to h=1: all features are frozen at this origin.
        panel.loc[panel.zone_id.eq('B') & panel.periodo.eq('2024-07'), 'viajes_total'] += 100
        modified = origin_features(panel, self.neighbors, '2024-07')
        self.assertEqual(modified.loc[0, 'neighbor_trips_lag1'] - before.loc[0, 'neighbor_trips_lag1'], 100)

    def test_formula_matches_phase2_without_late_observations(self):
        expected = build_temporal_features(self.panel).query("periodo == '2024-08'").set_index('zone_id')
        actual = origin_features(self.panel, self.neighbors, '2024-07').set_index('zone_id')
        cols = [c for c in TEMPORAL_CANDIDATES if c not in ['month', 'year', 'sin_month', 'cos_month']]
        np.testing.assert_allclose(expected[cols], actual[cols], atol=1e-10, equal_nan=True)

    def test_late_observations_masked_for_both_feature_groups(self):
        panel = self.panel.copy()
        panel.loc[panel.zone_id.eq('B') & panel.periodo.eq('2024-07'), 'target_available_no_earlier_than'] = '2024-09-01'
        result = origin_features(panel, self.neighbors, '2024-07').set_index('zone_id')
        self.assertTrue(pd.isna(result.loc['B', 'lag_1']))
        self.assertTrue(pd.isna(result.loc['A', 'neighbor_trips_lag1']))
        self.assertEqual(result.loc['A', 'neighbor_observation_coverage'], 0)

    def test_missing_and_october_not_imputed(self):
        panel = self.panel.copy()
        panel.loc[panel.periodo.eq('2024-10'), ['data_status', 'viajes_total']] = ['MISSING_DATA', np.nan]
        result = origin_features(panel, self.neighbors, '2024-11')
        self.assertTrue(result.rolling_mean_3.isna().all())
        self.assertTrue(result.neighbor_trips_mean_lag3.isna().all())
        X = select_X(self.candidates, self.sets['LGBM_TEMPORAL_SPATIAL'], self.registry)
        self.assertTrue(X.loc[self.candidates.zone_id.eq('C'), 'neighbor_trips_lag1'].isna().all())

    def test_training_availability_and_target_month_bound(self):
        train = training_rows(self.candidates, '2024-07', 3)
        self.assertTrue((train.target_period <= '2024-07').all())
        self.assertTrue((pd.to_datetime(train.label_available_no_earlier_than) <= pd.Timestamp('2024-08-01')).all())
        late = self.candidates.copy()
        index = train.index[0]
        late.loc[index, 'label_available_no_earlier_than'] = '2024-09-01'
        self.assertNotIn(index, training_rows(late, '2024-07', 3).index)

    def test_selection_cannot_see_future_coverage_or_targets(self):
        changed = self.candidates.copy()
        changed.loc[changed.target_period > self.selection['calibration_end'], TEMPORAL_CANDIDATES] = np.nan
        changed.loc[changed.target_period > self.selection['calibration_end'], 'target_viajes_total'] = 1e12
        selected, info = choose_temporal_features(changed, self.splits)
        self.assertEqual(selected, self.selected)
        self.assertEqual(info, self.selection)

    def test_comparable_mask_is_shared_and_strict(self):
        test = self.candidates.query("horizon == 1 and origin_period == '2024-07'")
        masks = eligible_masks(test, self.selected)
        self.assertEqual(int(masks[SCOPES[0]].sum()), 3)
        self.assertEqual(int(masks[SCOPES[1]].sum()), 2)
        self.assertTrue(test.loc[masks[SCOPES[1]], self.selected + SPATIAL_FEATURES].notna().all().all())

    def test_improvement_sign(self):
        self.assertEqual(improvement_pct(100, 80), 20)
        self.assertEqual(improvement_pct(100, 120), -20)
        self.assertEqual(improvement_pct(100, 100), 0)
        self.assertTrue(np.isnan(improvement_pct(0, 10)))

    def test_identical_hyperparameters_and_deterministic_fit(self):
        train = training_rows(self.candidates, '2024-07', 1)
        X = select_X(train, self.selected, self.registry)
        a, b = lgb.LGBMRegressor(**PARAMS), lgb.LGBMRegressor(**PARAMS)
        self.assertEqual(a.get_params(), b.get_params())
        a.fit(X, train.target_viajes_total)
        b.fit(X, train.target_viajes_total)
        np.testing.assert_array_equal(a.predict(X), b.predict(X))
        self.assertTrue(np.isfinite(a.predict(X)).all())
        self.assertEqual(PARAMS['subsample'], 1)
        self.assertFalse(PARAMS['zero_as_missing'])

    def test_pipeline_same_cut_rows_and_metric_universe(self):
        predictions, cuts, audit, _, _ = run_models(self.candidates, self.splits, self.sets, self.registry, verbose=False)
        self.assertEqual(set(predictions.split_id), set(self.splits.split_id))
        for _, g in audit.groupby(['evaluation_scope', 'split_id']):
            self.assertEqual(g.test_row_hash.nunique(), 1)
            self.assertEqual(g.train_row_hash.nunique(), 1)
            self.assertEqual(g.n_rows_usable.nunique(), 1)
            params = g.hyperparameters_json.dropna()
            self.assertEqual(params.nunique(), 1)
        for _, g in predictions.groupby(['evaluation_scope', 'split_id']):
            self.assertEqual(g.groupby('model').size().nunique(), 1)
            self.assertEqual(g.groupby('zone_id').actual.nunique().max(), 1)
        metrics = aggregate_metrics(predictions, cuts)
        self.assertEqual(metrics.groupby(['evaluation_scope', 'horizon']).n_observations.nunique().max(), 1)
        with self.assertRaises(ValueError):
            run_models(self.candidates, pd.concat([self.splits, self.splits.iloc[:1]]), self.sets, self.registry, verbose=False)

    def test_overlap_classification_and_no_graph_changes(self):
        audit = pd.DataFrame({'zone_id': ['a', 'b'], 'area_m2': [10000, 20000]})
        overlaps = pd.DataFrame({'zone_id': ['a'] * 4, 'other_zone_id': ['b'] * 4, 'overlap_area_m2': [0.01, 20, 200, np.nan]})
        result = review_overlaps(overlaps, audit)
        self.assertEqual(result.category.tolist(), ['LIKELY_BOUNDARY_ARTIFACT', 'SMALL_OVERLAP', 'MATERIAL_OVERLAP', 'REVIEW_REQUIRED'])
        self.assertAlmostEqual(result.loc[1, 'overlap_pct_zone_a'], 0.2)
        self.assertFalse(result.queen_changed.any())
        self.assertFalse(result.geometry_excluded.any())


class Phase4ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = ROOT / 'data/processed'
        meta = cls.p / 'lightgbm_compare_v2.metadata.json'
        if not meta.exists():
            raise unittest.SkipTest('Run Phase 4 pipeline to check outputs')
        cls.meta = json.loads(meta.read_text())

    def test_all_hashes_and_streamlit_unchanged(self):
        for name, digest in self.meta['output_sha256'].items():
            self.assertEqual(sha256_file(self.p / name), digest, name)
        for name, digest in self.meta['input_and_implementation_sha256'].items():
            self.assertEqual(sha256_file(ROOT / name), digest, name)
        protected = self.meta['protected_previous_phase_sha256']
        self.assertIn('src/app/app.py', protected)
        for name, digest in protected.items():
            self.assertEqual(sha256_file(ROOT / name), digest, name)
        legacy = json.loads((self.p / 'panel_demanda_v2.metadata.json').read_text())['legacy_sha256_unchanged']
        self.assertEqual(len(legacy), 17)
        for name, digest in legacy.items():
            self.assertEqual(sha256_file(Path(name)), digest, name)

    def test_saved_universes_and_metrics_identical_by_scope(self):
        predictions = pd.read_csv(self.p / 'lightgbm_compare_predictions_v2.csv')
        cuts = pd.read_csv(self.p / 'lightgbm_compare_cut_metrics_v2.csv')
        splits = pd.read_csv(self.p / 'rolling_splits_v2.csv')
        audit = pd.read_csv(self.p / 'lightgbm_compare_run_audit_v2.csv')
        self.assertEqual(set(audit.split_id), set(splits.loc[splits.status.eq('USED'), 'split_id']))
        self.assertEqual(set(predictions.model), set(MODELS))
        self.assertTrue(np.isfinite(predictions[['actual', 'predicted', 'origin_value']]).all().all())
        for _, g in audit.groupby(['evaluation_scope', 'split_id']):
            self.assertEqual(g.train_row_hash.nunique(), 1)
            self.assertEqual(g.test_row_hash.nunique(), 1)
        for _, g in predictions.groupby(['evaluation_scope', 'split_id', 'zone_id']):
            self.assertEqual(len(g), 3)
            self.assertEqual(g.actual.nunique(), 1)
        for r in cuts.itertuples():
            g = predictions[(predictions.evaluation_scope == r.evaluation_scope) & predictions.split_id.eq(r.split_id) & predictions.model.eq(r.model)]
            metrics = metrics_for(g)
            self.assertEqual(len(g), r.n_observations)
            if len(g): self.assertAlmostEqual(metrics['MAE'], r.MAE, places=7)

    def test_saved_model_columns_and_missing_preserved(self):
        a = pd.read_csv(self.p / 'model_matrix_temporal_v2.csv')
        b = pd.read_csv(self.p / 'model_matrix_temporal_spatial_v2.csv')
        pd.testing.assert_frame_equal(a, b[a.columns])
        self.assertFalse(a.duplicated(['zone_id', 'origin_period', 'horizon']).any())
        self.assertTrue(b.neighbor_trips_lag1.isna().any())
        for model, features in self.meta['feature_sets'].items():
            self.assertFalse({'zone_id', 'colonia', 'alcaldia', 'target_viajes_total'} & set(features))
        self.assertEqual(self.meta['hyperparameters_by_model']['LGBM_TEMPORAL'], self.meta['hyperparameters_by_model']['LGBM_TEMPORAL_SPATIAL'])


if __name__ == '__main__':
    unittest.main()
