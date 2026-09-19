"""Spatial topology, causal dependency and preservation checks (no source downloads)."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import Polygon, box, mapping

from src.features.features_espaciales_v2 import (
    ROOT, STATIC, CAUSAL, audit_geometry, build_spatial_features, causal_spatial_features,
    combine_features, feature_registry, metric_transformer, station_geometry_audit,
    validate_catalog, validate_neighbors,
)
from src.data.ecobici_v2 import sha256_file


def fixture():
    # A and B share an edge; B and C share only a vertex. D is isolated, E has no polygon.
    catalog = pd.DataFrame([{'zone_id': z, 'colonia': z, 'alcaldia': 'borough',
                            'aliases': json.dumps([z]), 'n_estaciones_catalogo_actual': i + 1}
                           for i, z in enumerate('ABCDE')])
    polygons = [box(0, 0, 100, 100), box(100, 0, 200, 100), box(200, 100, 300, 200), box(1000, 0, 1100, 100)]
    geo = {'type': 'FeatureCollection', 'crs': {'properties': {'name': 'EPSG:32614'}},
           'features': [{'properties': {'colonia': z, 'alcaldia': 'borough'}, 'geometry': mapping(g)}
                        for z, g in zip('ABCD', polygons)]}
    panel = pd.DataFrame([{'zone_id': z, 'periodo': str(p), 'viajes_total': float((i + 1) * (t + 1)),
                           'data_status': 'OBSERVED'}
                          for i, z in enumerate('ABCDE')
                          for t, p in enumerate(pd.period_range('2024-08', periods=5, freq='M'))])
    return catalog, geo, panel


class SpatialTests(unittest.TestCase):
    def setUp(self):
        self.catalog, self.geo, self.panel = fixture()
        self.audit, self.edges, self.overlaps, self.projected, self.info = audit_geometry(self.catalog, self.geo)

    def build(self, panel=None):
        return build_spatial_features(self.panel if panel is None else panel, self.catalog, self.audit, self.edges)

    def value(self, frame, zone='B', month='2024-12', col='neighbor_trips_lag1'):
        return frame.loc[frame.zone_id.eq(zone) & frame.periodo.eq(month), col].iloc[0]

    def test_catalog_ids_unique(self):
        with self.assertRaisesRegex(ValueError, 'unique'):
            validate_catalog(pd.concat([self.catalog, self.catalog.iloc[:1]]))

    def test_queen_edge_and_vertex_no_self_and_symmetric(self):
        pairs = set(zip(self.edges.zone_id, self.edges.neighbor_zone_id))
        self.assertEqual(pairs, {('A', 'B'), ('B', 'A'), ('B', 'C'), ('C', 'B')})
        validate_neighbors(self.edges, self.catalog.zone_id)
        self.assertFalse(self.edges.zone_id.eq(self.edges.neighbor_zone_id).any())

    def test_duplicate_neighbors_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            validate_neighbors(pd.concat([self.edges, self.edges.iloc[:1]]), self.catalog.zone_id)

    def test_self_neighbors_rejected(self):
        edges = self.edges.copy()
        edges.loc[0, 'neighbor_zone_id'] = edges.loc[0, 'zone_id']
        with self.assertRaisesRegex(ValueError, 'Self'):
            validate_neighbors(edges, self.catalog.zone_id)

    def test_normalized_weights_and_renormalization(self):
        np.testing.assert_allclose(self.edges.groupby('zone_id').weight_normalized.sum(), 1)
        panel = self.panel.copy()
        panel.loc[panel.zone_id.eq('C') & panel.periodo.eq('2024-11'), ['viajes_total', 'data_status']] = [np.nan, 'MISSING_DATA']
        result = self.build(panel)
        self.assertEqual(self.value(result), 4)  # A only, not 4 * 0.5
        self.assertEqual(self.value(result, col='neighbor_observation_coverage'), 0.5)
        self.assertEqual(self.value(result, col='neighbor_active_zones'), 1)

    def test_crs_and_projected_measurements(self):
        self.assertTrue(CRS(self.info['analysis_crs']).is_projected)
        self.assertAlmostEqual(self.audit.loc[self.audit.zone_id.eq('A'), 'area_m2'].iloc[0], 10000)
        self.assertAlmostEqual(self.edges.distance_centroid_m.iloc[0], 100)
        for crs in ['EPSG:4326', 'OGC:CRS84']:
            with self.assertRaisesRegex(ValueError, 'projected'):
                metric_transformer(crs, crs)

    def test_invalid_geometry_reported_not_repaired(self):
        self.geo['features'][0]['geometry'] = mapping(Polygon([(0, 0), (100, 100), (100, 0), (0, 100), (0, 0)]))
        audit, edges, _, _, _ = audit_geometry(self.catalog, self.geo)
        a = audit.set_index('zone_id').loc['A']
        self.assertFalse(a.geometry_valid)
        self.assertIn('Self-intersection', a.validity_error)
        self.assertFalse(a.geometry_repaired)
        self.assertNotIn('A', set(edges.zone_id))

    def test_null_geometry_reported(self):
        self.geo['features'][0]['geometry'] = None
        audit, _, _, _, info = audit_geometry(self.catalog, self.geo)
        self.assertEqual(info['n_null_geometries'], 1)
        self.assertFalse(audit.set_index('zone_id').loc['A'].geometry_available)

    def test_overlap_not_invented_as_queen(self):
        self.geo['features'][1]['geometry'] = mapping(box(50, 0, 150, 100))
        _, edges, overlaps, _, _ = audit_geometry(self.catalog, self.geo)
        self.assertFalse(((edges.zone_id == 'A') & (edges.neighbor_zone_id == 'B')).any())
        self.assertAlmostEqual(overlaps.overlap_area_m2.iloc[0], 5000)

    def test_same_target_and_neighbor_current_month_do_not_leak(self):
        before = self.build()
        for zone in ['B', 'A']:
            panel = self.panel.copy()
            panel.loc[panel.zone_id.eq(zone) & panel.periodo.eq('2024-12'), 'viajes_total'] = 99999
            self.assertEqual(self.value(before), self.value(self.build(panel)))
        panel = self.panel.copy()
        panel.loc[panel.zone_id.eq('A') & panel.periodo.eq('2024-11'), 'viajes_total'] = 104
        self.assertEqual(self.value(self.build(panel)) - self.value(before), 50)

    def test_future_truncation_invariance(self):
        extended = pd.concat([self.panel, pd.DataFrame([{'zone_id': z, 'periodo': '2025-01',
                                'viajes_total': 999999, 'data_status': 'OBSERVED'} for z in 'ABCDE'])])
        base, new = self.build(), self.build(extended)
        pd.testing.assert_frame_equal(base.reset_index(drop=True), new[new.periodo <= '2024-12'].reset_index(drop=True))

    def test_growth_same_as_phase2_and_full_window_mean(self):
        result = self.build()
        self.assertAlmostEqual(self.value(result, col='neighbor_growth_lag1'), 1 / 3)
        self.assertAlmostEqual(self.value(result, col='neighbor_trips_mean_lag3'), 6)

    def test_missing_unknown_and_zero_are_distinct(self):
        panel = self.panel.copy()
        mask = panel.zone_id.isin(['A', 'C']) & panel.periodo.eq('2024-11')
        panel.loc[mask, 'data_status'] = 'UNKNOWN_ACTIVITY_STATUS'
        # Even a misleading numeric value must be ignored under unknown status.
        result = self.build(panel)
        self.assertTrue(pd.isna(self.value(result)))
        self.assertEqual(self.value(result, col='neighbor_observation_coverage'), 0)
        panel.loc[mask, ['data_status', 'viajes_total']] = ['ZERO_DEMAND', 0.0]
        result = self.build(panel)
        self.assertEqual(self.value(result), 0)
        self.assertEqual(self.value(result, col='neighbor_observation_coverage'), 1)
        panel.loc[panel.zone_id.isin(['A', 'C']) & panel.periodo.eq('2024-10'), 'viajes_total'] = 0
        self.assertTrue(pd.isna(self.value(self.build(panel), col='neighbor_growth_lag1')))

    def test_calendar_gap_not_previous_row(self):
        panel = self.panel[~self.panel.periodo.eq('2024-11')]
        self.assertTrue(pd.isna(self.value(self.build(panel))))

    def test_late_availability_excluded(self):
        panel = self.panel.copy()
        panel['target_available_no_earlier_than'] = pd.NaT
        panel.loc[panel.zone_id.eq('A') & panel.periodo.eq('2024-11'), 'target_available_no_earlier_than'] = pd.Timestamp('2025-01-01')
        result = self.build(panel)
        self.assertEqual(self.value(result), 12)  # only C
        self.assertEqual(self.value(result, col='neighbor_observation_coverage'), 0.5)

    def test_coverage_bounds_and_preserve_missing_geometry(self):
        result = self.build()
        coverage = result.neighbor_observation_coverage.dropna()
        self.assertTrue(coverage.between(0, 1).all())
        self.assertEqual(len(result), len(self.panel))
        self.assertEqual(result.zone_id.nunique(), 5)
        self.assertTrue(result[result.zone_id.eq('E')].neighbor_trips_lag1.isna().all())
        self.assertFalse(result[result.zone_id.eq('E')].spatial_features_available.any())
        self.assertTrue(result[result.zone_id.eq('D')].n_neighbors_queen.eq(0).all())

    def test_merge_one_to_one_and_reject_universe_change(self):
        spatial = self.build()
        combined = combine_features(self.panel, spatial)
        self.assertEqual(len(combined), len(self.panel))
        self.assertFalse(combined.duplicated(['zone_id', 'periodo']).any())
        for left, right in [(pd.concat([self.panel, self.panel.iloc[:1]]), spatial),
                            (self.panel, pd.concat([spatial, spatial.iloc[:1]])),
                            (self.panel, spatial.iloc[1:])]:
            with self.assertRaises(ValueError):
                combine_features(left, right)

    def test_snapshots_blocked_by_default(self):
        result = self.build()
        self.assertTrue(set(STATIC) <= set(result))
        selected = causal_spatial_features(result)
        self.assertFalse(set(STATIC) & set(selected))
        self.assertTrue(set(CAUSAL) <= set(selected))
        self.assertTrue(all(not r['historical_safe'] for r in feature_registry() if r['name'] in STATIC))
        self.assertAlmostEqual(self.value(result, zone='A', col='estaciones_por_km2_catalogo'), 100)

    def test_station_conflict_not_reassigned(self):
        # Test in actual CDMX coordinates; outside catalog polygon, inside B.
        catalog, geo, _ = fixture()
        geo['crs']['properties']['name'] = 'OGC:CRS84'
        for i, f in enumerate(geo['features']):
            f['geometry'] = mapping(box(-99.2 + i * .01, 19.4, -99.19 + i * .01, 19.41))
        _, _, _, projected, _ = audit_geometry(catalog, geo)
        stations = pd.DataFrame([{'num_cicloe': '1', 'zone_id': 'A', 'longitud': -99.185, 'latitud': 19.405}])
        report = station_geometry_audit(stations, projected).iloc[0]
        self.assertFalse(report.inside_catalog_polygon)
        self.assertEqual(report.zone_id_catalog, 'A')
        self.assertEqual(report.zone_id_spatial, 'B')
        self.assertGreater(report.distance_to_catalog_polygon_m, 0)
        self.assertFalse(report.assignment_changed)


class SpatialArtifactsTests(unittest.TestCase):
    def test_generated_artifacts_and_protected_hashes(self):
        processed = ROOT / 'data/processed'
        meta_path = processed / 'features_espaciales_v2.metadata.json'
        if not meta_path.exists():
            self.skipTest('Run the spatial pipeline first')
        meta = json.loads(meta_path.read_text())
        for name, digest in meta['input_and_implementation_sha256'].items():
            self.assertEqual(sha256_file(ROOT / name), digest, name)
        for name, digest in meta['output_sha256'].items():
            self.assertEqual(sha256_file(processed / name), digest, name)
        for name, digest in meta['protected_previous_phase_sha256'].items():
            self.assertEqual(sha256_file(ROOT / name), digest, name)
        panel = pd.read_csv(processed / 'panel_demanda_v2.csv')
        spatial = pd.read_csv(processed / 'features_espaciales_v2.csv')
        combined = pd.read_csv(processed / 'features_temporal_spatial_v2.csv')
        self.assertEqual(len(combined), len(panel))
        self.assertEqual(spatial.zone_id.nunique(), 106)
        self.assertFalse(combined.duplicated(['zone_id', 'periodo']).any())
        self.assertTrue(spatial.loc[spatial.periodo.eq('2024-11'), 'neighbor_trips_lag1'].isna().all())
        legacy = json.loads((processed / 'panel_demanda_v2.metadata.json').read_text())
        for name, digest in legacy['legacy_sha256_unchanged'].items():
            self.assertEqual(sha256_file(Path(name)), digest)


if __name__ == '__main__':
    unittest.main()
